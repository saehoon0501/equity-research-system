"""Inner-ring test for the §13 gate orchestration (task 4.1).

Boundary: orchestrator (Requirements 2, 5, 7, 10). Asserts the Observable from
tasks.md 4.1 + the design §13 System-Flows sequence (design.md:174-216) against
the **landed survival contract** — synthetic AccountState / OperationalState /
SurvivalParameters / ClockState fixtures + the **REAL pure** ``survival.admit``
and ``survival.assess`` (no DB, no MCP, no LLM — P14):

  * a **permitted + actionable** path runs ``assess`` → derive-permit →
    ``candidate`` → ``decide`` → ``order_builder`` → **BL-3 map** → build the
    ``OrderEvaluation`` → ``admit`` — *in that order*; ``admit`` (which consumes
    the built order) **never runs before** ``decide`` (Req 2.2/2.3);
  * a **kill-switch** ``OperationalState`` blocks an **open** (no decision
    requested, no order admitted — Req 2.1/7.1) but a **true exit** still reaches
    ``admit`` and short-circuits to ALLOW (fail-toward-flat — Req 7.2);
  * a ``REJECT`` carrying an ``advisory_max_volume`` triggers **exactly one**
    resize-rebuild-readmit (Req 3.5), and the resized volume **never upsizes**
    above the advisory (Req 2.4 / P7);
  * the ``binding_constraint`` on a reject is surfaced for the trace ``gate_link``
    (Req 2.3);
  * the daemon obtains every decision / verdict / sizing from the deps — it
    computes none of its own (Req 10.2/10.3).

The deps (``assemble`` / ``decide`` / ``build_order`` / broker readouts) are
**synthetic spies** recording call order; ``admit`` / ``assess`` are the **real**
``src.survival.gate`` functions. The BL-3 adaptation (daemon ``ProposedOrder`` →
survival ``ProposedOrder``: drop ``position_id``, ``direction`` enum→``.value``
str) is asserted at the seam.
"""

from __future__ import annotations

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
    ClockState,
    OperationalState,
    OrderEvaluation,
    Position as SurvivalPosition,
    ProposedOrder as SurvivalProposedOrder,
)

# Import the unit under test last (it does not exist yet — RED).
from src.reactive.daemon import orchestrator


# --------------------------------------------------------------------------- #
# Synthetic fixtures.                                                          #
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
        # The pinned survival namespace mapping (resolved to SurvivalParameters
        # at the admit seam, BL-3); kept as a dict here — the orchestrator passes
        # the resolved SurvivalParameters object below directly in tests.
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
    # A minimal FeatureSet stand-in: the orchestrator threads `features` into
    # `decide` opaquely (a spy here), so its internals are irrelevant.
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
    """A healthy, activated, well-capitalized account (so the survival walk only
    binds on op-state / size, not margin / activation)."""
    return AccountState(
        activated=True,
        equity=100_000.0,
        used_margin=1_000.0,
        free_margin=99_000.0,
        margin_level=10_000.0,  # far above any buffer
        balance=100_000.0,
        stop_out_level=SURVIVAL_DEFAULTS.stop_out_level_pct,
        positions=positions or [],
    )


def _clock() -> ClockState:
    return ClockState(session_open=True, seconds_to_next_closure=None)


def _op_state(
    *, kill_switch: bool = False, grade: str = "NONE"
) -> OperationalState:
    return OperationalState(
        kill_switch_engaged=kill_switch,
        safe_mode_grade=grade,  # type: ignore[arg-type]
        entered_at=None,
        triggered_by=None,
    )


def _survival_params(*, exclusion_enabled: bool = False):
    """SurvivalParameters with exclusion OFF (so the in-universe open is not
    rejected by the §12.6 screen — the screen wiring is a tracked follow-on; the
    test exercises the size / kill-switch constraints)."""
    import dataclasses

    return dataclasses.replace(
        SURVIVAL_DEFAULTS, exclusion_enabled=exclusion_enabled
    )


# --------------------------------------------------------------------------- #
# Recording spies for the injected deps (record call order).                  #
# --------------------------------------------------------------------------- #


class _Deps:
    """The injected, order-recording dependency seam. ``assemble`` / ``decide`` /
    ``build_order`` are spies; ``admit`` / ``assess`` are the REAL survival funcs.
    """

    def __init__(
        self,
        *,
        candidate: Optional[Candidate],
        decision: ReactiveDecision,
        orders: list[Optional[ProposedOrder]],
        account: AccountState,
        op_state: OperationalState,
        params,
        clock: ClockState,
    ):
        self.calls: list[str] = []
        self._candidate = candidate
        self._decision = decision
        # `orders` is the queue of order_builder return values (initial build,
        # then the resize re-build) — pop in call order.
        self._orders = list(orders)
        self._account = account
        self._op_state = op_state
        self._params = params
        self._clock = clock
        # Capture what reached `admit` (BL-3-mapped survival ProposedOrders).
        self.admitted_orders: list[SurvivalProposedOrder] = []
        self.build_volumes: list[Optional[float]] = []

    # -- candidate --
    def assemble(self, symbol, feed, params, on_non_directional=None):
        self.calls.append("assemble")
        return self._candidate

    # -- signal model --
    def decide(self, features, direction, snapshot, runtime_threshold=None):
        self.calls.append("decide")
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
        self.build_volumes.append(advisory_max_volume)
        return self._orders.pop(0)

    # -- broker readouts --
    def get_positions(self):
        self.calls.append("get_positions")
        return self._account.positions

    def get_account_assets(self):
        self.calls.append("get_account_assets")
        return self._account

    # -- survival (REAL) --
    def admit(self, order, state, op_state, params, clock, evaluation):
        self.calls.append("admit")
        self.admitted_orders.append(order)
        return survival_gate.admit(
            order, state, op_state, params, clock, evaluation
        )

    def assess(self, state, op_state, params, clock):
        self.calls.append("assess")
        return survival_gate.assess(state, op_state, params, clock)


def _run(deps: _Deps, *, advisory_cap_on_reject: bool = True):
    """Drive one orchestration tick with the injected deps."""
    return orchestrator.orchestrate_tick(
        symbol=_SYMBOL,
        epoch=_epoch(),
        op_state=deps._op_state,
        account=deps._account,
        survival_params=deps._params,
        clock=deps._clock,
        feed=object(),  # opaque; assemble is a spy
        universe=_UNIVERSE,
        leverage=_LEVERAGE,
        is_excluded=False,
        stop_loss_atr_mult=_ATR_MULT,
        assemble=deps.assemble,
        decide=deps.decide,
        build_order=deps.build_order,
        get_positions=deps.get_positions,
        admit=deps.admit,
        assess=deps.assess,
    )


# --------------------------------------------------------------------------- #
# 1. Permitted + actionable → build → map → admit, in §13 order.              #
# --------------------------------------------------------------------------- #


def test_permitted_actionable_walks_assess_candidate_decide_build_admit_in_order():
    deps = _Deps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        orders=[_daemon_order(volume=0.5)],
        account=_account_state(),
        op_state=_op_state(),  # permits new exposure
        params=_survival_params(),
        clock=_clock(),
    )

    outcome = _run(deps)

    # §13 ordering: assess gates Survive first; admit consumes the BUILT order so
    # it can never precede decide/build (Req 2.2/2.3).
    assert deps.calls.index("assess") < deps.calls.index("decide")
    assert deps.calls.index("decide") < deps.calls.index("build_order")
    assert deps.calls.index("build_order") < deps.calls.index("admit")
    # admit NEVER before decide — the headline ordering invariant.
    assert deps.calls.index("admit") > deps.calls.index("decide")

    # The order reached admit ALLOW (well-capitalized, in-universe, not excluded).
    assert outcome.admit_decision is not None
    assert outcome.admit_decision.decision == "ALLOW"
    assert outcome.admitted_order is not None


def test_bl3_map_drops_position_id_and_lowercases_direction_to_value_str():
    """The BL-3 adaptation: the survival ProposedOrder reaching admit carries the
    direction `.value` str and NO position_id field (survival's ProposedOrder has
    no position_id)."""
    deps = _Deps(
        candidate=_candidate("SHORT"),
        decision=_decision("SHORT", sizing_hint=0.5),
        orders=[_daemon_order(direction=Direction.SHORT, volume=0.5)],
        account=_account_state(),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
    )

    _run(deps)

    assert len(deps.admitted_orders) == 1
    survival_order = deps.admitted_orders[0]
    assert isinstance(survival_order, SurvivalProposedOrder)
    # direction is the broker enum `.value` str (not the enum object).
    assert survival_order.direction == Direction.SHORT.value == "SHORT"
    assert isinstance(survival_order.direction, str)
    # survival's ProposedOrder has no position_id field at all.
    assert not hasattr(survival_order, "position_id")
    assert survival_order.symbol == _SYMBOL
    assert survival_order.intent == "BUY"
    assert survival_order.stop_loss is not None


# --------------------------------------------------------------------------- #
# 2. Op-state derives the permit: kill-switch blocks an OPEN; a true EXIT      #
#    still reaches admit and ALLOWs (fail-toward-flat).                        #
# --------------------------------------------------------------------------- #


def test_kill_switch_blocks_open_no_decision_requested():
    """Under an engaged kill switch the daemon must NOT request a directional
    decision and must NOT admit an open (Req 2.1 / 7.1)."""
    deps = _Deps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        orders=[_daemon_order(volume=0.5)],
        account=_account_state(),  # flat book → an open, not an exit
        op_state=_op_state(kill_switch=True),
        params=_survival_params(),
        clock=_clock(),
    )

    outcome = _run(deps)

    # Permit derived from op-state: kill-switch off is required. No decision /
    # build / admit for an open.
    assert "decide" not in deps.calls
    assert "build_order" not in deps.calls
    assert "admit" not in deps.calls
    assert outcome.new_exposure_permitted is False
    assert outcome.admitted_order is None


def test_safe_mode_halt_new_blocks_open():
    """safe_mode_grade HALT_NEW (rank >= HALT_NEW) blocks new exposure (Req 2.1)."""
    deps = _Deps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        orders=[_daemon_order(volume=0.5)],
        account=_account_state(),
        op_state=_op_state(grade="HALT_NEW"),
        params=_survival_params(),
        clock=_clock(),
    )

    outcome = _run(deps)

    assert outcome.new_exposure_permitted is False
    assert "decide" not in deps.calls


def test_true_exit_reaches_admit_and_allows_under_kill_switch():
    """A true exit (opposite-side to a single held position, volume <= held) must
    STILL reach admit even under an engaged kill switch — survival short-circuits
    it to ALLOW (fail-toward-flat, Req 7.2)."""
    # Held LONG position; a SHORT decision opposes it → a reduce/close (exit).
    held = SurvivalPosition(
        position_id="P1",
        symbol=_SYMBOL,
        direction="LONG",
        volume=0.5,
        avg_open_price=_REFERENCE,
        used_margin=10.0,
        unrealized_pnl=0.0,
    )
    account = _account_state(positions=[held])
    # order_builder produces a reduce: SELL/TRIM targeting the held position, the
    # HELD side (LONG), volume <= held.
    reduce_order = _daemon_order(
        intent=Label.SELL,
        direction=Direction.LONG,  # closing the held LONG (survival classifies by effect)
        volume=0.5,
        position_id="P1",
    )
    deps = _Deps(
        candidate=_candidate("SHORT"),
        decision=_decision("SHORT", sizing_hint=0.5),
        orders=[reduce_order],
        account=account,
        op_state=_op_state(kill_switch=True),
        params=_survival_params(),
        clock=_clock(),
    )

    outcome = _run(deps)

    # The exit path runs even under kill-switch: it reaches admit and ALLOWs.
    assert "admit" in deps.calls
    assert outcome.admit_decision is not None
    assert outcome.admit_decision.decision == "ALLOW"
    # The survival order at the admit seam is OPPOSITE-side to the held LONG (the
    # BL-3 reduce flip: a SELL closing a held LONG nets on the SHORT side) with
    # volume <= held — so gate._is_true_exit short-circuits it to ALLOW.
    survival_order = deps.admitted_orders[0]
    assert survival_order.direction == "SHORT"
    assert survival_order.volume == 0.5


# --------------------------------------------------------------------------- #
# 3. REJECT + advisory_max_volume → exactly ONE resize-rebuild-readmit.        #
# --------------------------------------------------------------------------- #


def test_size_breach_resize_rebuild_readmit_exactly_once():
    """An over-cap open is REJECTed `size_limit` + an advisory max; the daemon
    resizes to <= advisory, RE-BUILDS, and RE-ADMITS exactly once (Req 3.5)."""
    cap = _survival_params().per_order_size_max  # DEFAULTS per_order_size_max = 1.0
    over = cap + 5.0  # strictly above the cap → size_limit reject + advisory=cap

    # First build is over-cap; the resize re-build returns an at-advisory order.
    first = _daemon_order(volume=over)
    resized = _daemon_order(volume=cap)
    deps = _Deps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=over),
        orders=[first, resized],
        account=_account_state(),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
    )

    outcome = _run(deps)

    # Exactly two builds (initial + one resize) and two admits (one re-admit).
    assert deps.calls.count("build_order") == 2
    assert deps.calls.count("admit") == 2
    # The second build was threaded the advisory cap (the gate's advisory max).
    assert deps.build_volumes[1] == cap
    # The re-admit ALLOWs the resized (at-cap) order.
    assert outcome.admit_decision.decision == "ALLOW"
    assert outcome.admitted_order is not None
    assert outcome.admitted_order.volume == cap
    # The binding_constraint of the FIRST reject is surfaced (gate_link).
    assert outcome.first_reject_constraint == "size_limit"


def test_resize_never_upsizes_above_advisory():
    """The resize re-build is threaded the advisory as a CAP (never-upsize, P7):
    the re-built volume must not exceed the advisory max."""
    cap = _survival_params().per_order_size_max
    over = cap + 5.0
    first = _daemon_order(volume=over)
    # Build the resized order honoring the cap (the real order_builder would clamp
    # via _capped_volume); the orchestrator must pass the cap so it can.
    resized = _daemon_order(volume=cap)
    deps = _Deps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=over),
        orders=[first, resized],
        account=_account_state(),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
    )

    outcome = _run(deps)

    assert outcome.admitted_order.volume <= cap


def test_persistent_reject_after_single_resize_is_not_admitted():
    """If the single resize still REJECTs, the order is not admitted (no second
    resize loop — exactly one resize pass, Req 3.5)."""
    cap = _survival_params().per_order_size_max
    over = cap + 5.0
    # Both builds return over-cap orders (a misbehaving builder) → both reject;
    # the orchestrator stops after one resize, leaving the order un-admitted.
    first = _daemon_order(volume=over)
    still_over = _daemon_order(volume=over)
    deps = _Deps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=over),
        orders=[first, still_over],
        account=_account_state(),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
    )

    outcome = _run(deps)

    assert deps.calls.count("build_order") == 2  # initial + one resize only
    assert deps.calls.count("admit") == 2
    assert outcome.admitted_order is None
    assert outcome.admit_decision.decision == "REJECT"


# --------------------------------------------------------------------------- #
# 4. HOLD / non-directional → declined, no order, no admit.                    #
# --------------------------------------------------------------------------- #


def test_hold_decision_is_declined_no_order_no_admit():
    deps = _Deps(
        candidate=_candidate("LONG"),
        decision=_decision("HOLD", sizing_hint=None),
        orders=[None],  # build_order returns None on HOLD
        account=_account_state(),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
    )

    outcome = _run(deps)

    # decide ran (permitted), but no order was built/admitted.
    assert "decide" in deps.calls
    assert "admit" not in deps.calls
    assert outcome.declined is True
    assert outcome.admitted_order is None


def test_no_candidate_skips_decide_and_declines():
    """A non-directional / insufficient-data evaluation (candidate is None) →
    no decision, no order, declined (Req 12.4/12.5)."""
    deps = _Deps(
        candidate=None,
        decision=_decision("LONG", sizing_hint=0.5),
        orders=[_daemon_order()],
        account=_account_state(),
        op_state=_op_state(),
        params=_survival_params(),
        clock=_clock(),
    )

    outcome = _run(deps)

    assert "decide" not in deps.calls
    assert "admit" not in deps.calls
    assert outcome.declined is True
    assert outcome.admitted_order is None


# --------------------------------------------------------------------------- #
# 5. assess always runs (Survive gate every tick), op-state is read, and the   #
#    daemon obtains verdicts from deps (no self-computed survival values).      #
# --------------------------------------------------------------------------- #


def test_assess_runs_every_tick_even_when_blocked():
    """assess (the Survive standing-monitor) runs first every tick, even when the
    permit is denied (Req 1.2 cadence honored by the orchestrator entry)."""
    deps = _Deps(
        candidate=_candidate("LONG"),
        decision=_decision("LONG", sizing_hint=0.5),
        orders=[_daemon_order()],
        account=_account_state(),
        op_state=_op_state(kill_switch=True),
        params=_survival_params(),
        clock=_clock(),
    )

    outcome = _run(deps)

    assert deps.calls[0] == "assess"
    assert outcome.assess_directive is not None


# --------------------------------------------------------------------------- #
# 6. BL-3 seam pinned against the REAL order_builder output (P12 spirit).      #
# --------------------------------------------------------------------------- #


def test_bl3_map_against_real_order_builder_open_and_reduce():
    """The BL-3 ``_to_survival_order`` map must hold against the **real**
    ``order_builder.build_order`` output, not just synthetic orders — pinning the
    cross-spec seam (open keeps the side; a reduce flips to the netting side so
    ``gate._is_true_exit`` classifies it as an exit)."""
    from src.reactive.daemon.order_builder import build_order
    from src.reactive.daemon.orchestrator import _to_survival_order

    pinned = PinnedParams(
        reactive_snapshot=REACTIVE_DEFAULTS, survival_snapshot={}
    )

    # --- Open: a LONG decision on a flat book → BUY+LONG → survival "LONG". ---
    open_order = build_order(
        _decision("LONG", sizing_hint=0.5),
        [],
        _REFERENCE,
        pinned,
        symbol=_SYMBOL,
        stop_loss_atr_mult=_ATR_MULT,
    )
    assert open_order is not None
    s_open = _to_survival_order(open_order)
    assert s_open.intent == "BUY"
    assert s_open.direction == "LONG"
    assert not hasattr(s_open, "position_id")

    # --- Reduce: a SHORT decision against a held LONG → SELL/TRIM on the held
    #     LONG side → survival flips to "SHORT" (the netting side → a true exit). -
    held = Position(
        position_id="POS-1",
        symbol=_SYMBOL,
        direction=Direction.LONG,
        volume=0.5,
        avg_open_price=_REFERENCE,
        used_margin=10.0,
        unrealized_pnl=0.0,
    )
    reduce_order = build_order(
        _decision("SHORT", sizing_hint=0.5),
        [held],
        _REFERENCE,
        pinned,
        symbol=_SYMBOL,
        stop_loss_atr_mult=_ATR_MULT,
    )
    assert reduce_order is not None
    assert reduce_order.position_id == "POS-1"  # targets the held position
    s_reduce = _to_survival_order(reduce_order)
    assert s_reduce.intent in ("SELL", "TRIM")
    # The daemon order carries the HELD side (LONG); survival sees the OPPOSITE.
    assert reduce_order.direction is Direction.LONG
    assert s_reduce.direction == "SHORT"

    # And the flipped survival order is classified as a TRUE EXIT by the gate
    # (opposite-side to the single held LONG, volume <= held) → ALLOW even under
    # an engaged kill switch.
    account = _account_state(
        positions=[
            SurvivalPosition(
                position_id="POS-1",
                symbol=_SYMBOL,
                direction="LONG",
                volume=0.5,
                avg_open_price=_REFERENCE,
                used_margin=10.0,
                unrealized_pnl=0.0,
            )
        ]
    )
    decision = survival_gate.admit(
        s_reduce,
        account,
        _op_state(kill_switch=True),
        _survival_params(),
        _clock(),
        OrderEvaluation(),  # bare reject-leaning eval — a true exit ignores it
    )
    assert decision.decision == "ALLOW"
