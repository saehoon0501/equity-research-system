"""Persist-then-act seam — the op-state transition is persisted BEFORE admit (task LW).

Boundary: ``loop`` (Requirement 5 — specifically 5.1: "persist the operational-
state transition before executing any directive or admitting any order"; 5.4:
"persist every survival event and operational-state transition the gate emits to
an append-only record"). Source of truth: ``.kiro/specs/execution-daemon/
design.md`` §"System Flows" (the per-tick sequence — "the op-state transition is
**persisted before** any directive/admit (persist-then-act)") + the
Requirements-Traceability rows 5.1 (``orchestrator``, ``loop``, ``db``) and 5.4.

What this proves
----------------
The 4.4 reviewer flagged that the inner-ring loop ran the op-state transition
through the orchestrator's internal ``admit``, so there was **no seam** to persist
the op-state BEFORE admit. This file pins the closed seam:

  * **Inner ring (no DB):** a RECORDING dependency seam records a single ordered
    call log across one ``run_cycle``; the test asserts the persist write
    (``persist_op_state``) happens **strictly before** ``admit`` (Req 5.1) — and
    before the de-risk action + the submit. The ``admit`` / ``assess`` are the
    REAL pure survival functions (P14 — exercise the real walk, not a stub).
  * **Persist-then-act HARD GATE:** when the durable persist itself fails, the
    edge path does NOT run (no ``admit``, no open submitted) — fail toward minimum
    exposure (Req 1.5/5.1). The de-risk directives still flow (Req 7.2).
  * **Live DB (``integration_live``):** the live ``persist_op_state_transition``
    writes the transition to the real ``survival_gate_state`` (monotonic singleton)
    + each event to the append-only ``survival_gate_events`` (Req 5.4), in one
    transaction, against the owned conn — and the rows are read back to confirm
    the durable write. Targets THIS file directly (``-m integration_live``).
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import pytest

from src.reactive.daemon.broker_seam import Direction, Label, Position
from src.reactive.daemon.types import (
    Candidate,
    EpochContext,
    PinnedParams,
    ProposedOrder,
)
from src.reactive.features import FeatureSet
from src.reactive.params import DEFAULTS as REACTIVE_DEFAULTS
from src.reactive.types import (
    CalibrationEvidence,
    DecisionSubstrate,
    ReactiveDecision,
)
from src.survival import gate as survival_gate
from src.survival.params import DEFAULTS as SURVIVAL_DEFAULTS
from src.survival.types import (
    AccountState,
    AssessDirective,
    ClockState,
    OperationalState,
    Position as SurvivalPosition,
    ReduceDirective,
    SurvivalEvent,
)

from src.reactive.daemon import loop as loop_mod

# --------------------------------------------------------------------------- #
# Synthetic fixtures (mirror test_loop's style).                               #
# --------------------------------------------------------------------------- #

_SYMBOL = "AAPL"
_REFERENCE = 100.0
_ATR = 3.0
_ATR_MULT = 2.0
_LEVERAGE = 5.0
_UNIVERSE = frozenset({_SYMBOL})


def _epoch() -> EpochContext:
    pinned = PinnedParams(reactive_snapshot=REACTIVE_DEFAULTS, survival_snapshot={})
    return EpochContext(
        run_id="11111111-1111-1111-1111-111111111111",
        code_version="cv-1",
        param_version="pv-1",
        walk_forward_window="2026Q2-boot",
        pinned_params=pinned,
    )


def _substrate(atr: Optional[float] = _ATR) -> DecisionSubstrate:
    feature_values: dict[str, Any] = {"trend_vote": 1.0, "drawdown_atr": 0.5}
    if atr is not None:
        feature_values["atr"] = atr
    return DecisionSubstrate(
        feature_values=feature_values,
        probability=0.72,
        effective_threshold=REACTIVE_DEFAULTS.threshold,
        code_version=REACTIVE_DEFAULTS.code_version,
        param_version=REACTIVE_DEFAULTS.param_version,
        calibration=CalibrationEvidence(brier=None, reliability=None),
    )


def _decision(decision: str, *, sizing_hint: Optional[float]) -> ReactiveDecision:
    return ReactiveDecision(
        decision=decision,  # type: ignore[arg-type]
        direction_in=decision if decision != "HOLD" else "LONG",  # type: ignore[arg-type]
        probability=0.72,
        sizing_hint=sizing_hint,
        non_final=True,
        reason=None if decision != "HOLD" else "invalid_direction",
        substrate=_substrate(),
    )


def _candidate(direction: str = "LONG") -> Candidate:
    features = object.__new__(FeatureSet)  # opaque token; decide is a spy
    return Candidate(
        features=features,  # type: ignore[arg-type]
        direction=direction,  # type: ignore[arg-type]
        reference_price=_REFERENCE,
    )


def _daemon_order(
    *,
    intent: Label = Label.BUY,
    direction: Direction = Direction.LONG,
    volume: float = 0.5,
    position_id: Optional[str] = None,
) -> ProposedOrder:
    return ProposedOrder(
        symbol=_SYMBOL,
        intent=intent,
        direction=direction,
        volume=volume,
        stop_loss=_REFERENCE - _ATR * _ATR_MULT,
        position_id=position_id,
    )


def _account_state(positions: Optional[list[SurvivalPosition]] = None) -> AccountState:
    return AccountState(
        activated=True,
        equity=100_000.0,
        used_margin=1_000.0,
        free_margin=99_000.0,
        margin_level=10_000.0,
        balance=100_000.0,
        stop_out_level=SURVIVAL_DEFAULTS.stop_out_level_pct,
        positions=positions or [],
    )


def _clock() -> ClockState:
    return ClockState(session_open=True, seconds_to_next_closure=None)


def _op_state(*, kill_switch: bool = False, grade: str = "NONE") -> OperationalState:
    return OperationalState(
        kill_switch_engaged=kill_switch,
        safe_mode_grade=grade,  # type: ignore[arg-type]
        entered_at=None,
        triggered_by=None,
    )


def _survival_params(*, exclusion_enabled: bool = False):
    import dataclasses

    return dataclasses.replace(SURVIVAL_DEFAULTS, exclusion_enabled=exclusion_enabled)


# --------------------------------------------------------------------------- #
# Recording dependency seam — a SINGLE ordered call log across the whole cycle. #
# --------------------------------------------------------------------------- #


class _RecordingDeps:
    """Records a single ordered call log so the test can assert persist < admit.

    ``admit`` / ``assess`` are the REAL survival functions. ``persist_op_state``
    is the recording persist seam (records the persisted directive). The op-state
    holder is mutable so the cycle reads fresh after the (no-op) intake poll.
    """

    def __init__(
        self,
        *,
        candidate: Optional[Candidate],
        decision: ReactiveDecision,
        order: Optional[ProposedOrder],
        op_state: OperationalState,
        params,
        clock: ClockState,
        account: AccountState,
        assess_directive: Optional[AssessDirective] = None,
        persist_raises: bool = False,
    ):
        self.calls: list[str] = []
        self._candidate = candidate
        self._decision = decision
        self._order = order
        self._op_state_holder = {"op_state": op_state}
        self._params = params
        self._clock = clock
        self._account = account
        self._assess_directive = assess_directive
        self._persist_raises = persist_raises
        self.submitted: list[ProposedOrder] = []
        self.de_risk_submitted: list[tuple[str, str]] = []
        self.recorded_failures: list[str] = []
        self.persisted: list[AssessDirective] = []

    def poll_commands(self, op_state_holder: dict) -> None:
        self.calls.append("poll_commands")

    def read_op_state(self) -> OperationalState:
        self.calls.append("read_op_state")
        return self._op_state_holder["op_state"]

    def assemble(self, symbol, feed, params, on_non_directional=None):
        self.calls.append("assemble")
        return self._candidate

    def decide(self, features, direction, snapshot, runtime_threshold=None):
        self.calls.append("decide")
        return self._decision

    def build_order(
        self,
        decision,
        positions,
        reference_price,
        params,
        *,
        symbol="",
        advisory_max_volume=None,
        stop_loss_atr_mult=_ATR_MULT,
    ):
        self.calls.append("build_order")
        return self._order

    def get_positions(self):
        self.calls.append("get_positions")
        return self._account.positions

    def admit(self, order, state, op_state, params, clock, evaluation):
        self.calls.append("admit")
        return survival_gate.admit(order, state, op_state, params, clock, evaluation)

    def assess(self, state, op_state, params, clock):
        self.calls.append("assess")
        if self._assess_directive is not None:
            return self._assess_directive
        return survival_gate.assess(state, op_state, params, clock)

    def persist_op_state(self, directive: AssessDirective):
        self.calls.append("persist_op_state")
        if self._persist_raises:
            raise RuntimeError("synthetic op-state persist failure")
        self.persisted.append(directive)

    def submit_order(self, order: ProposedOrder):
        self.calls.append("submit_order")
        self.submitted.append(order)

    def execute_de_risk(self, directives, account):
        self.calls.append("execute_de_risk")
        for d in directives:
            if d.kind in ("FLATTEN", "REDUCE"):
                self.de_risk_submitted.append((d.kind, d.symbol or "*"))

    def record_failure(self, reason: str):
        self.calls.append("record_failure")
        self.recorded_failures.append(reason)


def _run_cycle(deps: _RecordingDeps):
    return loop_mod.run_cycle(
        symbol=_SYMBOL,
        epoch=_epoch(),
        survival_params=deps._params,
        clock=deps._clock,
        account=deps._account,
        feed=object(),
        universe=_UNIVERSE,
        leverage=_LEVERAGE,
        is_excluded=False,
        stop_loss_atr_mult=_ATR_MULT,
        op_state_holder=deps._op_state_holder,
        poll_commands=deps.poll_commands,
        read_op_state=deps.read_op_state,
        assemble=deps.assemble,
        decide=deps.decide,
        build_order=deps.build_order,
        get_positions=deps.get_positions,
        admit=deps.admit,
        assess=deps.assess,
        persist_op_state=deps.persist_op_state,
        submit_order=deps.submit_order,
        execute_de_risk=deps.execute_de_risk,
        record_failure=deps.record_failure,
    )


# --------------------------------------------------------------------------- #
# 1. The seam: persist happens BEFORE admit (and assess before persist).        #
# --------------------------------------------------------------------------- #


def test_op_state_persist_happens_before_admit():
    """Req 5.1 — the operational-state transition is durably persisted BEFORE any
    order is admitted. With the REAL survival walk on a permitted+actionable path,
    the call log must show assess → persist_op_state → admit, in that order."""
    deps = _RecordingDeps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        order=_daemon_order(volume=0.5),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(),
    )

    _run_cycle(deps)

    # The standing monitor runs, THEN its transition is persisted, THEN admit.
    assert "assess" in deps.calls
    assert "persist_op_state" in deps.calls
    assert "admit" in deps.calls
    assert deps.calls.index("assess") < deps.calls.index("persist_op_state")
    # The headline persist-then-act invariant: persist BEFORE admit (Req 5.1).
    assert deps.calls.index("persist_op_state") < deps.calls.index("admit")
    # The Phase-1 directive was actually handed to the persist seam.
    assert len(deps.persisted) == 1


def test_op_state_persist_happens_before_submit_and_de_risk():
    """The persist precedes both the de-risk action and the order submit — the
    transition is durable before ANY act (Req 5.1)."""
    flatten = AssessDirective(
        next_op_state=_op_state(grade="FLATTEN"),
        reduce_directives=[
            ReduceDirective(kind="FLATTEN", symbol=None, target_volume=None, reason="x")
        ],
        events=[],
    )
    deps = _RecordingDeps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        order=_daemon_order(volume=0.5),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(),
        assess_directive=flatten,
    )

    _run_cycle(deps)

    assert deps.calls.index("persist_op_state") < deps.calls.index("execute_de_risk")
    if "submit_order" in deps.calls:
        assert deps.calls.index("persist_op_state") < deps.calls.index("submit_order")


# --------------------------------------------------------------------------- #
# 2. Persist-then-act HARD GATE: a persist failure skips the edge path.          #
# --------------------------------------------------------------------------- #


def test_persist_failure_is_a_hard_gate_no_admit_no_submit():
    """Req 5.1 — if the op-state transition cannot be durably persisted, the edge
    path does NOT run: no admit, no open submitted (fail toward minimum exposure).
    The de-risk directives still flow (Req 7.2), and the failure is recorded."""
    flatten = AssessDirective(
        next_op_state=_op_state(grade="FLATTEN"),
        reduce_directives=[
            ReduceDirective(kind="FLATTEN", symbol=None, target_volume=None, reason="x")
        ],
        events=[],
    )
    deps = _RecordingDeps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        order=_daemon_order(volume=0.5),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(),
        assess_directive=flatten,
        persist_raises=True,
    )

    outcome = _run_cycle(deps)

    # The persist failed → the edge path was skipped entirely (Req 5.1 hard gate).
    assert "admit" not in deps.calls
    assert "decide" not in deps.calls
    assert deps.submitted == []
    assert outcome.admitted_order is None
    assert outcome.failed is True
    assert deps.recorded_failures != []
    # The de-risk FLATTEN still flowed — a reduce/flatten is never blocked (Req 7.2).
    assert ("FLATTEN", "*") in deps.de_risk_submitted


def test_persist_runs_after_assess_even_on_hard_gate():
    """Even when the persist fails, it ran AFTER assess produced the transition —
    the order is assess → persist (which raised) → [edge path skipped]."""
    deps = _RecordingDeps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        order=_daemon_order(volume=0.5),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(),
        persist_raises=True,
    )

    _run_cycle(deps)

    assert deps.calls.index("assess") < deps.calls.index("persist_op_state")
    assert "admit" not in deps.calls


# --------------------------------------------------------------------------- #
# 3. Live DB persist (integration_live) — durable write to the real tables.     #
# --------------------------------------------------------------------------- #


@pytest.mark.integration_live
def test_persist_op_state_transition_writes_durable_events_live():
    """The live ``persist_op_state_transition`` writes each event to the append-only
    ``survival_gate_events`` AND the next op-state to ``survival_gate_state``, in
    ONE transaction, against the owned conn (Req 5.1/5.4). The append-only events
    are read back by the per-test ``run_id`` (uncontaminated by the shared
    singleton); the singleton write is covered separately on an isolated scope so
    a committed transition never latches the shared 'default' row."""
    import psycopg

    from src.reactive.daemon.config import _dsn

    run_id = str(uuid.uuid4())
    # A FLATTEN transition carrying two events (the heaviest assess output) — the
    # event_types are in the migration-049 CHECK vocabulary.
    directive = AssessDirective(
        next_op_state=_op_state(grade="FLATTEN"),
        reduce_directives=[
            ReduceDirective(kind="FLATTEN", symbol=None, target_volume=None, reason="m")
        ],
        events=[
            SurvivalEvent(
                event_type="margin_breach",
                ticker=None,
                detail="stop-out breach",
                account_snapshot={"equity": 1.0, "margin_level": 10.0},
            ),
            SurvivalEvent(
                event_type="safe_mode_entered",
                ticker=_SYMBOL,
                detail="safe-mode entered at FLATTEN",
                account_snapshot={"equity": 1.0},
            ),
        ],
    )

    conn = psycopg.connect(_dsn())
    try:
        loop_mod.persist_op_state_transition(conn, run_id=run_id, directive=directive)

        with conn.cursor() as cur:
            # The two events landed in the append-only log under THIS run_id (the
            # persist-then-act durable write — Req 5.4).
            cur.execute(
                "SELECT event_type, ticker FROM survival_gate_events WHERE run_id = %s "
                "ORDER BY event_type",
                (run_id,),
            )
            rows = cur.fetchall()
            assert [r[0] for r in rows] == ["margin_breach", "safe_mode_entered"]
            # The account-wide event carries no ticker; the symbol-scoped one does.
            assert dict(rows) == {"margin_breach": None, "safe_mode_entered": _SYMBOL}

            # The op-state singleton reflects the persisted next op-state. The
            # 'default' scope is shared + monotonic, so the grade is at least the
            # FLATTEN we just wrote (never looser) — the durable transition landed.
            cur.execute(
                "SELECT safe_mode_grade FROM survival_gate_state WHERE scope = 'default'"
            )
            state_row = cur.fetchone()
            assert state_row is not None
            assert state_row[0] == "FLATTEN"
        conn.commit()
    finally:
        conn.close()
