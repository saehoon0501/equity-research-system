"""Inner-ring test for the evaluation loop (task 4.4).

Boundary: loop (Requirements 1, 5, 7, 9). Asserts the Observable from tasks.md
4.4 + the design §13 System-Flows "intake polled first / persist-then-act /
fail-toward-minimum-exposure" against the **landed survival contract** —
synthetic AccountState / OperationalState / SurvivalParameters / ClockState
fixtures + the **REAL pure** ``survival.admit`` / ``survival.assess`` (no DB, no
MCP, no LLM — P14):

  * **single-eval-at-a-time (Req 1.1):** one ``run_cycle`` completes its
    read-modify-write of op-state before the next begins; the loop never
    overlaps two evaluations (the call log is strictly serialized — every
    cycle's intake-poll/op-state-read/assess block is contiguous).
  * **intake polled FIRST each cycle (design §System-Flows / Req 5.2/7.3):** the
    command intake is polled + applied **before** ``assess`` so a just-issued
    kill-switch is observed on this same tick's admit (op-state read fresh
    *after* the intake apply).
  * **assess within cadence + on a margin-material event (Req 1.2/1.3):** the
    standing monitor runs at least once per cycle; a margin-material event
    triggers an out-of-cadence cycle (no wait for the next interval).
  * **fail-toward-minimum-exposure on a dependency error (Req 1.5):** when an
    evaluation cannot complete (a dep raises), the loop **rejects any opening
    order** but **never blocks a true exit / reduce / flatten directive** — the
    de-risk directives from ``assess`` still flow, and the failure is recorded.

The deps are **synthetic spies** recording call order; ``admit`` / ``assess``
are the **real** ``src.survival.gate`` functions (P14 — exercise the real
fail-toward-flat short-circuit, not a re-implementation).
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from src.reactive.daemon.broker_seam import Direction, Label, Position
from src.reactive.daemon.candidate import NonDirectionalReason
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
)

# Import the unit under test last (it does not exist yet — RED).
from src.reactive.daemon import loop as loop_mod


# --------------------------------------------------------------------------- #
# Synthetic fixtures (mirror test_orchestrator's style).                       #
# --------------------------------------------------------------------------- #

_SYMBOL = "AAPL"
_REFERENCE = 100.0
_ATR = 3.0
_ATR_MULT = 2.0
_LEVERAGE = 5.0
_UNIVERSE = frozenset({_SYMBOL})


def _epoch() -> EpochContext:
    pinned = PinnedParams(
        reactive_snapshot=REACTIVE_DEFAULTS,
        survival_snapshot={},
    )
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


def _decision(
    decision: str, *, sizing_hint: Optional[float], atr: Optional[float] = _ATR
) -> ReactiveDecision:
    return ReactiveDecision(
        decision=decision,  # type: ignore[arg-type]
        direction_in=decision if decision != "HOLD" else "LONG",  # type: ignore[arg-type]
        probability=0.72,
        sizing_hint=sizing_hint,
        non_final=True,
        reason=None if decision != "HOLD" else "invalid_direction",
        substrate=_substrate(atr),
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
    stop = _REFERENCE - _ATR * _ATR_MULT
    return ProposedOrder(
        symbol=_SYMBOL,
        intent=intent,
        direction=direction,
        volume=volume,
        stop_loss=stop,
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
# The synthetic loop dependency seam — records a single global call log.        #
# --------------------------------------------------------------------------- #


class _LoopDeps:
    """The injected loop dependencies — spies recording a single ordered call
    log across the whole cycle, so the test can assert intake-before-assess and
    single-eval serialization. ``admit`` / ``assess`` are the REAL survival
    functions.

    The op-state is a small mutable holder the synthetic intake apply mutates
    (a just-applied kill-switch is then read fresh by the cycle), so the test can
    prove the cycle reads op-state *after* the intake apply (Req 5.2).
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
        kill_switch_command: bool = False,
        decide_raises: bool = False,
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
        self._kill_switch_command = kill_switch_command
        self._decide_raises = decide_raises
        self.submitted: list[ProposedOrder] = []
        self.de_risk_submitted: list[tuple[str, str]] = []
        self.recorded_failures: list[str] = []
        # The persist-then-act seam: records each persisted op-state transition in
        # the single ordered call log so the test can assert the persist write
        # happens BEFORE admit (Req 5.1). ``persist_raises`` makes the durable
        # persist fail (the persist-then-act hard gate).
        self.persisted: list[AssessDirective] = []
        self._persist_raises = persist_raises

    # -- the fresh op-state read (Req 5.2) -----------------------------------
    def read_op_state(self) -> OperationalState:
        self.calls.append("read_op_state")
        return self._op_state_holder["op_state"]

    # -- command intake poll + apply (FIRST each cycle) ----------------------
    def poll_commands(self, op_state_holder: dict) -> None:
        self.calls.append("poll_commands")
        if self._kill_switch_command:
            # A just-issued kill-switch op-state write — the cycle must read this
            # fresh AFTER this apply (op-state freshness, Req 5.2/7.3).
            op_state_holder["op_state"] = _op_state(kill_switch=True)

    # -- candidate --
    def assemble(self, symbol, feed, params, on_non_directional=None):
        self.calls.append("assemble")
        return self._candidate

    # -- signal model --
    def decide(self, features, direction, snapshot, runtime_threshold=None):
        self.calls.append("decide")
        if self._decide_raises:
            raise RuntimeError("synthetic signal-model failure")
        return self._decision

    # -- order builder --
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

    # -- broker readouts --
    def get_positions(self):
        self.calls.append("get_positions")
        return self._account.positions

    # -- survival (REAL) --
    def admit(self, order, state, op_state, params, clock, evaluation):
        self.calls.append("admit")
        return survival_gate.admit(order, state, op_state, params, clock, evaluation)

    def assess(self, state, op_state, params, clock):
        self.calls.append("assess")
        if self._assess_directive is not None:
            return self._assess_directive
        return survival_gate.assess(state, op_state, params, clock)

    # -- persist-then-act (Req 5.1): durably persist the op-state transition --
    # BEFORE the edge path admit/submit. Records the call in the single ordered
    # call log so the test can assert persist precedes admit.
    def persist_op_state(self, directive: AssessDirective):
        self.calls.append("persist_op_state")
        if self._persist_raises:
            raise RuntimeError("synthetic op-state persist failure")
        self.persisted.append(directive)

    # -- paper submit (the lifecycle driver wires this) ----------------------
    def submit_order(self, order: ProposedOrder):
        self.calls.append("submit_order")
        self.submitted.append(order)

    # -- de-risk action (flatten/reduce directives) -------------------------
    def execute_de_risk(self, directives, account):
        self.calls.append("execute_de_risk")
        for d in directives:
            if d.kind in ("FLATTEN", "REDUCE"):
                self.de_risk_submitted.append((d.kind, d.symbol or "*"))

    # -- failure recorder (Req 1.5) -----------------------------------------
    def record_failure(self, reason: str):
        self.calls.append("record_failure")
        self.recorded_failures.append(reason)


def _run_cycle(deps: _LoopDeps):
    """Drive one loop cycle with the injected deps."""
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
# 1. Intake polled FIRST each cycle (before assess) — op-state read fresh.      #
# --------------------------------------------------------------------------- #


def test_intake_polled_before_assess_each_cycle():
    deps = _LoopDeps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        order=_daemon_order(volume=0.5),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(),
    )

    _run_cycle(deps)

    # The command intake is polled FIRST, before the op-state read and assess.
    assert deps.calls.index("poll_commands") < deps.calls.index("read_op_state")
    assert deps.calls.index("read_op_state") < deps.calls.index("assess")
    assert deps.calls.index("poll_commands") < deps.calls.index("assess")


def test_just_applied_kill_switch_is_seen_this_same_tick():
    """A kill-switch issued via intake (applied at poll) is read fresh by the
    cycle and blocks the open on this same tick (Req 5.2/5.3/7.3)."""
    deps = _LoopDeps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        order=_daemon_order(volume=0.5),
        op_state=_op_state(),  # starts permissive
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(),
        kill_switch_command=True,  # intake applies a kill-switch
    )

    outcome = _run_cycle(deps)

    # The open is blocked — no order submitted (the just-applied kill-switch is
    # read fresh after the intake poll, Req 5.2).
    assert deps.submitted == []
    assert outcome.admitted_order is None


# --------------------------------------------------------------------------- #
# 2. Single-eval-at-a-time — op-state read-modify-write contiguous per cycle.   #
# --------------------------------------------------------------------------- #


def test_single_eval_read_modify_write_completes_before_next_begins():
    """The loop runs at most one evaluation at a time: each cycle's
    intake-poll → op-state-read → assess block completes before the next cycle's
    intake poll (no interleaving) — Req 1.1."""
    deps = _LoopDeps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        order=_daemon_order(volume=0.5),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(),
    )

    # Two sequential cycles through the same deps (the persistent loop calls
    # run_cycle one at a time).
    _run_cycle(deps)
    first_assess = deps.calls.index("assess")
    deps.calls.clear()
    _run_cycle(deps)

    # The second cycle is a fresh contiguous block: poll → read → assess, in
    # order, with no leftover from the first (cleared) — single-eval serialization.
    assert deps.calls.index("poll_commands") < deps.calls.index("read_op_state")
    assert deps.calls.index("read_op_state") < deps.calls.index("assess")


def test_assess_runs_every_cycle_even_when_blocked():
    """The Survive standing monitor (assess) runs at least once per cycle even
    when no order is contemplated (Req 1.2 cadence)."""
    deps = _LoopDeps(
        candidate=None,  # no candidate — nothing to open
        decision=_decision("HOLD", sizing_hint=None),
        order=None,
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(),
    )

    _run_cycle(deps)

    assert "assess" in deps.calls


# --------------------------------------------------------------------------- #
# 3. Fail-toward-minimum-exposure on a dependency error (Req 1.5).              #
# --------------------------------------------------------------------------- #


def test_dependency_error_rejects_open_but_still_flows_de_risk():
    """When a dependency raises mid-evaluation, the loop rejects any opening
    order (no submit) but STILL executes the assess de-risk directives — a true
    exit / reduce / flatten is never blocked by the failure (Req 1.5)."""
    # assess emits an account-wide FLATTEN directive (a de-risk action that must
    # ALWAYS flow, even on a dep error).
    flatten_directive = AssessDirective(
        next_op_state=_op_state(grade="FLATTEN"),
        reduce_directives=[
            ReduceDirective(
                kind="FLATTEN", symbol=None, target_volume=None, reason="margin"
            )
        ],
        events=[],
    )
    deps = _LoopDeps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        order=_daemon_order(volume=0.5),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(
            positions=[
                SurvivalPosition(
                    position_id="p1",
                    symbol=_SYMBOL,
                    direction="LONG",
                    volume=1.0,
                    avg_open_price=95.0,
                    used_margin=500.0,
                    unrealized_pnl=-10.0,
                )
            ]
        ),
        assess_directive=flatten_directive,
        decide_raises=True,  # the Edge dep blows up mid-eval
    )

    outcome = _run_cycle(deps)

    # The opening order is rejected — nothing was submitted as an open.
    assert deps.submitted == []
    assert outcome.admitted_order is None
    # The de-risk FLATTEN directive STILL flowed (a true exit is never blocked).
    assert ("FLATTEN", "*") in deps.de_risk_submitted
    # The failure was recorded (Req 1.5).
    assert deps.recorded_failures != []
    assert outcome.failed is True


def test_dependency_error_de_risk_runs_before_or_independent_of_the_failure():
    """On a dep error the de-risk path is not gated by the failure — the flatten
    submit happens regardless (Req 1.5 — never block a reduce/flatten)."""
    flatten_directive = AssessDirective(
        next_op_state=_op_state(grade="FLATTEN"),
        reduce_directives=[
            ReduceDirective(
                kind="REDUCE", symbol=_SYMBOL, target_volume=0.5, reason="margin"
            )
        ],
        events=[],
    )
    deps = _LoopDeps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        order=_daemon_order(volume=0.5),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(),
        assess_directive=flatten_directive,
        decide_raises=True,
    )

    _run_cycle(deps)

    assert "execute_de_risk" in deps.calls
    assert ("REDUCE", _SYMBOL) in deps.de_risk_submitted


# --------------------------------------------------------------------------- #
# 4. Healthy path: admitted open submits; de-risk directives execute.           #
# --------------------------------------------------------------------------- #


def test_healthy_permitted_open_is_submitted():
    deps = _LoopDeps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        order=_daemon_order(volume=0.5),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(),
    )

    outcome = _run_cycle(deps)

    assert outcome.admitted_order is not None
    assert deps.submitted != []
    assert outcome.failed is False


def test_assess_de_risk_directives_execute_on_a_healthy_cycle():
    """A flatten directive from assess is executed in the normal (non-error)
    flow too — the de-risk action is part of every cycle (Req 6.1 action seam)."""
    flatten_directive = AssessDirective(
        next_op_state=_op_state(grade="FLATTEN"),
        reduce_directives=[
            ReduceDirective(
                kind="FLATTEN", symbol=None, target_volume=None, reason="closure"
            )
        ],
        events=[],
    )
    deps = _LoopDeps(
        candidate=None,
        decision=_decision("HOLD", sizing_hint=None),
        order=None,
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(),
        assess_directive=flatten_directive,
    )

    _run_cycle(deps)

    assert ("FLATTEN", "*") in deps.de_risk_submitted


# --------------------------------------------------------------------------- #
# 4b. Persist-then-act (Req 5.1): the durable op-state transition is committed   #
#     BEFORE any admit/submit, and a persist FAILURE is a hard gate that skips   #
#     the edge path without blocking a true exit (fail toward minimum exposure). #
# --------------------------------------------------------------------------- #


def test_persist_op_state_precedes_admit_and_submit_on_a_healthy_open():
    """On a healthy permitted-open cycle the durable op-state transition is
    persisted BEFORE the per-order admit and the open submit (persist-then-act,
    Req 5.1) — a just-engaged kill switch / safe-mode escalation can never be
    bypassed by an in-flight admit because the transition is committed first.

    The single ordered call log proves the seam: ``persist_op_state`` is recorded
    strictly before ``admit`` and before ``submit_order``.
    """
    deps = _LoopDeps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        order=_daemon_order(volume=0.5),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(),
    )

    outcome = _run_cycle(deps)

    # The open really cleared (so admit + submit are present in the call log) —
    # the ordering assertion would be vacuous on a blocked/HOLD cycle.
    assert outcome.admitted_order is not None
    assert deps.submitted != []
    assert "admit" in deps.calls
    assert "submit_order" in deps.calls
    # The durable persist write happens BEFORE the edge path's admit AND before
    # the open submit (persist-then-act, Req 5.1).
    assert deps.calls.index("persist_op_state") < deps.calls.index("admit")
    assert deps.calls.index("persist_op_state") < deps.calls.index("submit_order")
    # And the directive was actually handed to the persist seam (the recorded
    # transition is the Phase-1 assess directive, not an empty write).
    assert deps.persisted != []


def test_persist_failure_is_a_hard_gate_but_a_true_exit_still_flows():
    """A persist-then-act FAILURE is a hard gate (Req 5.1): on a would-be open the
    edge path is skipped entirely — nothing is admitted or submitted — yet a
    de-risk FLATTEN/REDUCE directive from assess STILL flows (Req 1.5/7.2). This
    is fail-toward-minimum-exposure: a transition that could not be durably
    recorded must not be bypassed by an in-flight open, but a true exit is never
    blocked by the failure.
    """
    # assess emits an account-wide FLATTEN directive (a de-risk action that must
    # ALWAYS flow, even when the persist of the transition itself failed).
    flatten_directive = AssessDirective(
        next_op_state=_op_state(grade="FLATTEN"),
        reduce_directives=[
            ReduceDirective(
                kind="FLATTEN", symbol=None, target_volume=None, reason="margin"
            )
        ],
        events=[],
    )
    deps = _LoopDeps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        order=_daemon_order(volume=0.5),  # a would-be open
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
        account=_account_state(),
        assess_directive=flatten_directive,
        persist_raises=True,  # the durable op-state persist fails (hard gate)
    )

    outcome = _run_cycle(deps)

    # Hard gate: the edge path is skipped — nothing admitted, nothing submitted,
    # and admit was never even reached (the persist failure short-circuits before
    # any per-order admit).
    assert deps.submitted == []
    assert outcome.admitted_order is None
    assert "admit" not in deps.calls
    # The failure is recorded (Req 1.5 — the fail-toward-minimum-exposure path).
    assert outcome.failed is True
    assert deps.recorded_failures != []
    # Yet the de-risk FLATTEN directive STILL flows — a true exit is never blocked
    # by the persist failure (Req 1.5/7.2 — fail toward minimum exposure).
    assert "execute_de_risk" in deps.calls
    assert ("FLATTEN", "*") in deps.de_risk_submitted


# --------------------------------------------------------------------------- #
# 5. Margin-material event triggers an out-of-cadence cycle (Req 1.3).          #
# --------------------------------------------------------------------------- #


def test_margin_material_event_triggers_an_immediate_cycle():
    """A margin-material event flag makes the scheduler run a cycle without
    waiting for the next cadence interval (Req 1.3)."""
    # The scheduler decision is pure: should_run_now(elapsed, cadence,
    # margin_material) is True when the cadence has elapsed OR a margin-material
    # event is pending.
    assert loop_mod.should_run_now(
        elapsed_seconds=0.1, cadence_seconds=5.0, margin_material_event=True
    )
    # Without a margin-material event, an un-elapsed cadence does NOT run.
    assert not loop_mod.should_run_now(
        elapsed_seconds=0.1, cadence_seconds=5.0, margin_material_event=False
    )
    # An elapsed cadence runs regardless.
    assert loop_mod.should_run_now(
        elapsed_seconds=6.0, cadence_seconds=5.0, margin_material_event=False
    )


# --------------------------------------------------------------------------- #
# 6. The persistent loop driver — single-eval serialization + cadence.         #
# --------------------------------------------------------------------------- #


def test_run_drives_cycles_one_at_a_time_until_should_continue_is_false():
    """The persistent loop runs run_one_cycle serially (one at a time, Req 1.1),
    bounded by should_continue, with an injected fake clock + no real sleep."""
    cycles: list[int] = []
    # A monotonic clock that advances 10s each read so the cadence always elapses
    # → the scheduler runs the next cycle every iteration (never sleeps).
    clock = {"t": 0.0}

    def monotonic() -> float:
        clock["t"] += 10.0
        return clock["t"]

    def run_one_cycle():
        cycles.append(len(cycles))
        return None

    # Continue for exactly 3 cycles, then stop (a bounded run — no infinite loop).
    state = {"n": 0}

    def should_continue() -> bool:
        state["n"] += 1
        return state["n"] <= 3

    slept: list[float] = []

    loop_mod.run(
        run_one_cycle=run_one_cycle,
        cadence_seconds=5.0,
        margin_material_pending=lambda: False,
        should_continue=should_continue,
        sleep=lambda s: slept.append(s),
        monotonic=monotonic,
    )

    # Exactly the bounded number of cycles ran, one at a time (serialized).
    assert cycles == [0, 1, 2]


def test_run_runs_immediately_on_a_margin_material_event_without_waiting():
    """A margin-material event makes the loop run a cycle immediately rather than
    sleeping out the cadence (Req 1.3)."""
    cycles: list[int] = []
    # The clock never advances past the cadence — only the margin-material event
    # can trigger a run.
    ticks = iter([0.0, 0.0, 0.1, 0.1, 0.2, 0.2])

    def monotonic() -> float:
        try:
            return next(ticks)
        except StopIteration:
            return 0.3

    def run_one_cycle():
        cycles.append(len(cycles))

    state = {"n": 0}

    def should_continue() -> bool:
        state["n"] += 1
        return state["n"] <= 2

    # margin-material pending for the second iteration → an out-of-cadence cycle.
    pending = iter([True])

    def margin_material_pending() -> bool:
        try:
            return next(pending)
        except StopIteration:
            return False

    slept: list[float] = []

    loop_mod.run(
        run_one_cycle=run_one_cycle,
        cadence_seconds=5.0,
        margin_material_pending=margin_material_pending,
        should_continue=should_continue,
        sleep=lambda s: slept.append(s),
        monotonic=monotonic,
    )

    # The first cycle runs immediately (first=True); the second runs out-of-cadence
    # because a margin-material event was pending (not because the cadence elapsed).
    assert cycles == [0, 1]
