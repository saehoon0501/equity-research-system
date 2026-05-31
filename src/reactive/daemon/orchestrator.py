"""§13 gate orchestration — the Survive ⊳ Preserve ⊳ Edge ⊳ Return walk (task 4.1).

Boundary: orchestrator (Requirements 2, 5, 7, 10). Source of truth:
``.kiro/specs/execution-daemon/design.md`` §"System Flows" (the per-tick sequence,
lines 174-216) + §"Control — ``orchestrator``" + the Requirements-Traceability
rows 2.x / 5.1 / 7.1 / 10.x.

What this module is
-------------------
The §13 walk against the **landed survival contract** (``src/survival/gate.py``).
On each evaluation it runs, *in this fixed order*:

  1. ``assess`` (the Survive standing-monitor) — every tick, even when blocked
     (Req 1.2 cadence is honored at this entry; the loop, task 4.4, drives the
     cadence). Returns the next op-state + de-risk directives + events.
  2. **Derive "new exposure permitted"** from the freshly-read ``OperationalState``
     — ``kill_switch`` off **and** ``safe_mode_grade`` rank below ``HALT_NEW``
     (i.e. not ``HALT_NEW`` / ``FLATTEN``). ``assess`` returns directives + an
     op-state, *not* a permit flag, so the daemon derives the branch from op-state
     (design §System-Flows "Key decisions"; Req 2.1 / 7.1).
  3. ``candidate.assemble`` → ``decide`` → ``order_builder`` → per-order ``admit``.

The walk proceeds to ``candidate``/``decide``/``order_builder`` when new exposure
is permitted **or** when a held position could be reduced/closed on this tick (the
true-exit path must always be able to get flat — Req 7.2). The **per-order
``admit`` is the enforcer**: under an engaged kill-switch it *rejects* a new open
but *short-circuits a true exit to ALLOW* (fail-toward-flat — ``gate._is_true_exit``).
So the orchestrator never itself decides "this exit may pass the kill switch"; it
constructs the order and lets ``admit`` classify it (Req 10.2/10.3 — verdicts come
from the dep, never self-computed).

The BL-3 adaptation (the Phase-2 cross-spec seam)
-------------------------------------------------
``order_builder`` returns the **daemon-owned** ``types.ProposedOrder`` (with a
``position_id`` + the broker ``Direction`` **enum**). ``survival.admit`` consumes
the **survival** ``ProposedOrder`` (``symbol``, ``intent``, ``direction:str``,
``volume``, ``stop_loss`` — **no** ``position_id``). At the admit seam the daemon
maps daemon→survival: **drops ``position_id``** (kept on the daemon order for the
broker submit, task 4.2) and projects ``direction`` enum→``.value`` str. The
other ``admit`` args are assembled here: the ``AccountState`` (broker
readouts), the fresh ``OperationalState`` (read by the loop from
``survival_gate_state``), the pinned ``SurvivalParameters`` (the survival
namespace), the ``ClockState``, and the ``OrderEvaluation`` projection (built via
``evaluation.build_order_evaluation``, task 4.5).

Resize-on-advisory (Req 3.5) — exactly one pass
-----------------------------------------------
On a ``REJECT`` carrying an ``advisory_max_volume`` (a ``size_limit`` breach), the
daemon resizes to ≤ the advisory by threading the advisory cap into a **re-build**
of ``order_builder`` (never mutating the gate's order — the gate returns an
advisory, not a resized order, ``gate._reject``), then **re-admits once**. The ATR
stop-loss is volume-independent, so the re-build reaches a fixpoint in one pass
(design §System-Flows). A persistent reject after the single resize leaves the
order **un-admitted** (never-upsize, P7 — the daemon never loops to force a fit).

Leaf-executor boundary (Req 10): this module **orchestrates and never recomputes**
a dependency value. It obtains the directional decision (``decide``), the survival
verdicts (``admit`` / ``assess``), the sizing (``order_builder`` ≤ advisory), and
the position state (``get_positions``) exclusively from their owning deps. It
imports the survival types + the daemon ``evaluation`` projection; the survival
*logic* is injected as ``admit`` (the loop wires the real ``gate.admit``), so this
stays inner-ring-testable with synthetic state + the REAL pure ``admit`` (P14).

Pure of I/O at this seam: the broker submit + the trace persist are the
**paper-lifecycle driver** (task 4.2) and the loop (task 4.4) — this module
returns a structured :class:`OrchestrationOutcome` the lifecycle driver acts on
(persist-then-act: the op-state transition from ``assess`` is surfaced for the
loop to persist *before* any submit). No MCP, no LLM (P1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet, Any, Callable, Optional, Sequence

from src.reactive.daemon.broker_seam import (
    Direction,
    OrderResult,
    Position,
    RuntimeMode,
)
from src.reactive.daemon.evaluation import build_order_evaluation
from src.reactive.daemon.types import (
    Candidate,
    EpochContext,
    ProposedOrder,
)
from src.reactive.daemon.candidate import MarketFeed, NonDirectionalReason
from src.reactive.types import ReactiveDecision
from src.survival.params import SurvivalParameters
from src.survival.types import (
    AccountState,
    AdmitDecision,
    AssessDirective,
    ClockState,
    OperationalState,
    OrderEvaluation,
    ProposedOrder as SurvivalProposedOrder,
)
from src.survival.types import HALT_NEW_RANK, grade_rank

__all__ = [
    "OrchestrationOutcome",
    "new_exposure_permitted",
    "run_assess",
    "run_edge_path",
    "orchestrate_tick",
    "PaperLifecycleOutcome",
    "PaperSendGuard",
    "drive_paper_lifecycle",
]


# --------------------------------------------------------------------------- #
# The structured tick outcome (the lifecycle driver / loop act on this).      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OrchestrationOutcome:
    """The result of one §13 walk — what the paper-lifecycle driver (task 4.2) and
    the loop (task 4.4) act on.

    ``assess_directive`` carries the Survive standing-monitor result (the op-state
    transition the loop persists **before** any act — persist-then-act, Req 5.1,
    plus the de-risk directives + events). ``new_exposure_permitted`` is the
    op-state-derived branch (Req 2.1). ``admitted_order`` is the **daemon-owned**
    ``ProposedOrder`` (with ``position_id`` retained for the broker submit) that
    cleared ``admit`` — ``None`` when nothing was admitted (blocked open / HOLD /
    no candidate / persistent reject). ``admit_decision`` is the gate's verdict on
    the order that reached ``admit`` (``None`` when no order was constructed).
    ``declined`` is True on a HOLD / sub-threshold / no-candidate evaluation (the
    declined-trace path, Req 2.5). ``first_reject_constraint`` surfaces the binding
    constraint of the first reject for the trace ``gate_link`` (Req 2.3).
    ``non_directional_reason`` attributes a no-candidate skip to 12.5 vs 12.4.
    """

    assess_directive: AssessDirective
    new_exposure_permitted: bool
    admitted_order: Optional[ProposedOrder]
    admit_decision: Optional[AdmitDecision]
    declined: bool
    first_reject_constraint: Optional[str]
    non_directional_reason: Optional[NonDirectionalReason]


# --------------------------------------------------------------------------- #
# Permit derivation (op-state, never an assess return; Req 2.1 / 7.1).        #
# --------------------------------------------------------------------------- #


def new_exposure_permitted(op_state: OperationalState) -> bool:
    """Derive "Survive permits new exposure" from the freshly-read op-state.

    New exposure is permitted iff the **kill switch is off** AND the
    ``safe_mode_grade`` rank is **below** ``HALT_NEW`` (i.e. ``NONE`` or
    ``TIGHTEN`` — not ``HALT_NEW`` / ``FLATTEN``). Read off the same single
    ordering source (``survival.types.grade_rank`` / ``HALT_NEW_RANK``) the gate's
    ``admit`` halt-new test uses, so the daemon's pre-filter cannot drift from the
    gate's own block (Req 2.1 / 7.1). This is a **derivation, not a recomputation**
    — the gate remains the enforcer; the daemon only avoids requesting a decision
    it could never open on.
    """
    if op_state.kill_switch_engaged:
        return False
    return grade_rank(op_state.safe_mode_grade) < HALT_NEW_RANK


def _direction_str(direction: Any) -> str:
    """The broker ``Direction`` as a plain ``.value`` str (BL-3 projection)."""
    value = getattr(direction, "value", direction)
    return str(value)


# The intents that REDUCE/close a held position (vs BUY, which opens/adds). On a
# reduce the daemon order's ``direction`` is the HELD side (the venue convention —
# a SELL on the position's side closes it); survival classifies an exit by the
# *netting* side, so the survival-facing direction is the OPPOSITE (BL-3 flip).
_REDUCE_INTENTS = frozenset({"TRIM", "SELL"})

# The opposite-side map (the netting side of a reduce).
_OPPOSITE_DIRECTION: dict[str, str] = {"LONG": "SHORT", "SHORT": "LONG"}


def _to_survival_order(order: ProposedOrder) -> SurvivalProposedOrder:
    """BL-3: map the daemon ``ProposedOrder`` → survival's ``ProposedOrder``.

    Two field adaptations the cross-spec seam requires:

      * **Drop ``position_id``** — survival's order has none (it classifies
        exit/open by *effect on the held position*, not a target id, P7). The
        daemon keeps ``position_id`` on its own order for the broker submit
        (task 4.2).
      * **Project + (on a reduce) flip the direction.** The broker ``Direction``
        enum → its ``.value`` str (survival's ``direction`` is a plain ``str``).
        For an **open/add** (``intent=BUY``) that exposure side is the survival
        side directly. For a **reduce/close** (``intent ∈ {TRIM, SELL}``) the
        daemon order's direction is the HELD position's side (the venue closes a
        long via a sell on the long), but survival's ``_is_true_exit`` recognizes
        an exit only when ``order.direction`` is **opposite** to the held side —
        so the survival-facing direction is the OPPOSITE (the netting side). This
        flip is what lets a true exit short-circuit ``admit`` to ALLOW
        (fail-toward-flat, Req 7.2). ``intent`` (the P9 ``Label``) is carried
        verbatim — survival ignores it for classification (P7) but pins it
        ``Literal``-typed.

    The flip is part of the venue↔survival contract, not a recomputation of a
    survival value (Req 10.2) — survival still independently classifies + vetoes.
    """
    direction = _direction_str(order.direction)
    intent = _intent_str(order.intent)
    if intent in _REDUCE_INTENTS:
        # A reduce/close: the netting (survival-facing) side is the opposite of
        # the held side the daemon order carries. An unrecognized direction is
        # left as-is → survival fails it toward OPEN (never a false exit).
        direction = _OPPOSITE_DIRECTION.get(direction, direction)
    return SurvivalProposedOrder(
        symbol=order.symbol,
        intent=intent,  # type: ignore[arg-type]
        direction=direction,
        volume=order.volume,
        stop_loss=order.stop_loss,
    )


def _intent_str(intent: Any) -> str:
    """The P9 ``Label`` intent as a plain ``.value`` str (survival ``intent`` is a
    ``Literal[str]``). ``Label`` is a str-Enum, so ``.value`` is BUY/TRIM/SELL."""
    return str(getattr(intent, "value", intent))


def _opposing_held_exists(
    direction: str, positions: Sequence[Position], symbol: str
) -> bool:
    """Whether a same-symbol held position OPPOSES the candidate direction — i.e.
    a decision on ``direction`` would *reduce/close* it (a potential true exit),
    not open fresh exposure.

    Used **only** to decide whether to proceed to build+admit when new exposure is
    *not* permitted: a reduce/exit must always be buildable so it can reach
    ``admit`` and get the fail-toward-flat short-circuit (Req 7.2). The gate's
    ``_is_true_exit`` is the authoritative exit classifier — this is the daemon's
    coarse "is there anything to exit here" pre-filter, deliberately conservative
    (it only proceeds when a clearly-opposing held position exists).
    """
    target = _DIRECTION_FOR_DECISION.get(direction)
    if target is None:
        return False
    for pos in positions:
        if pos.symbol == symbol and pos.direction is not target:
            # An opposing same-symbol position → the decided side reduces it.
            return True
    return False


# The reactive decided side ↔ broker Direction enum (mirrors order_builder's map).
_DIRECTION_FOR_DECISION: dict[str, Direction] = {
    "LONG": Direction.LONG,
    "SHORT": Direction.SHORT,
}


def run_assess(
    *,
    op_state: OperationalState,
    account: AccountState,
    survival_params: SurvivalParameters,
    clock: ClockState,
    assess: Callable[
        [AccountState, OperationalState, SurvivalParameters, ClockState],
        AssessDirective,
    ],
) -> AssessDirective:
    """Phase 1 of the §13 walk — the Survive standing-monitor (Req 1.2/5.1).

    Runs ``assess`` and returns the directive **without acting on it**. This is
    the **persist-then-act seam** (Req 5.1): the loop (task 4.4) calls this first,
    **durably persists** the resulting ``next_op_state`` transition + the events
    (to ``survival_gate_state`` / ``survival_gate_events`` via the owned conn,
    inside a transaction) **before** :func:`run_edge_path` runs the per-order
    admit/submit path. Splitting the §13 walk here means the op-state transition
    is committed to durable storage before any directive is executed or any order
    is admitted — a just-engaged kill switch / safe-mode escalation can never be
    bypassed by an in-flight admit (Req 5.1). ``assess`` is pure (no I/O); it only
    *emits* the transition + events for the daemon to persist.
    """
    return assess(account, op_state, survival_params, clock)


def run_edge_path(
    *,
    symbol: str,
    epoch: EpochContext,
    op_state: OperationalState,
    account: AccountState,
    survival_params: SurvivalParameters,
    clock: ClockState,
    feed: MarketFeed,
    universe: AbstractSet[str],
    leverage: Optional[float],
    is_excluded: Optional[bool],
    stop_loss_atr_mult: float,
    assess_directive: AssessDirective,
    assemble: Callable[..., Optional[Candidate]],
    decide: Callable[..., ReactiveDecision],
    build_order: Callable[..., Optional[ProposedOrder]],
    get_positions: Callable[[], Sequence[Position]],
    admit: Callable[
        [
            SurvivalProposedOrder,
            AccountState,
            OperationalState,
            SurvivalParameters,
            ClockState,
            OrderEvaluation,
        ],
        AdmitDecision,
    ],
) -> OrchestrationOutcome:
    """Phase 2 of the §13 walk — candidate → decide → order_builder → admit.

    Runs the **edge path** on top of the **already-persisted** ``assess_directive``
    (Phase 1, :func:`run_assess`): derive the op-state permit, assemble the
    candidate, request the decision, build the order, and run the per-order admit
    (with the single resize-on-advisory pass). This is the part that **acts** —
    it constructs the order ``admit`` vetoes (and the loop submits). It runs
    **only after** the loop has durably persisted the Phase-1 op-state transition
    (persist-then-act, Req 5.1), so a just-persisted kill-switch op-state is the
    one this path's permit + admit observe.

    The ``assess_directive`` is threaded in (rather than re-run) so the standing
    monitor is evaluated exactly once per tick and its transition is the one that
    was persisted before this path acts. Otherwise behaviorally identical to the
    Phase-3 portion of the legacy combined walk.

    Args:
        symbol: the ticker under evaluation.
        epoch: the pinned-param epoch (P3 — supplies the reactive snapshot via
            ``epoch.pinned_params.reactive_snapshot`` for ``decide``).
        op_state: the **freshly-read** operational state (Req 5.2). When the loop
            wires this it is the op-state read *after* the Phase-1 persist, so the
            admit sees the just-persisted transition.
        account: the broker-assembled survival ``AccountState`` fed to ``admit``.
        survival_params: the pinned ``SurvivalParameters`` (survival namespace).
        clock: the ``ClockState``.
        feed: the fast-clock ``MarketFeed`` (threaded into ``assemble``).
        universe / leverage / is_excluded: the ``OrderEvaluation`` legs.
        stop_loss_atr_mult: the protective-stop multiplier (Req 11.3).
        assess_directive: the Phase-1 directive (already persisted by the loop) —
            surfaced verbatim on the outcome so the same transition flows downstream.
        assemble / decide / build_order / get_positions / admit: the injected deps.

    Returns:
        An :class:`OrchestrationOutcome` (the threaded assess directive + the
        op-state-derived permit + the admitted daemon order / admit verdict /
        declined flag / first-reject constraint).
    """
    # ----- derive "new exposure permitted" from op-state (Req 2.1). ----------
    permitted = new_exposure_permitted(op_state)

    # ----- candidate → decide → order_builder → admit. -----------------------
    # When new exposure is NOT permitted we still proceed *iff* a candidate could
    # reduce/close a held position (the true-exit path must reach admit, Req 7.2).
    # A blocked open with nothing to exit short-circuits here (no decision
    # requested — Req 2.1).
    positions = list(get_positions())

    captured_reason: dict[str, Optional[NonDirectionalReason]] = {"reason": None}

    def _record_non_directional(reason: NonDirectionalReason) -> None:
        captured_reason["reason"] = reason

    candidate = assemble(
        symbol, feed, epoch.pinned_params, _record_non_directional
    )

    if candidate is None:
        # No directional edge (12.5) or insufficient data (12.4) → declined,
        # no decision/order/admit.
        return OrchestrationOutcome(
            assess_directive=assess_directive,
            new_exposure_permitted=permitted,
            admitted_order=None,
            admit_decision=None,
            declined=True,
            first_reject_constraint=None,
            non_directional_reason=captured_reason["reason"],
        )

    # If blocked AND the candidate would only OPEN fresh exposure (no opposing
    # held position to reduce), do not request a decision (Req 2.1 / 7.1).
    if not permitted and not _opposing_held_exists(
        candidate.direction, positions, symbol
    ):
        return OrchestrationOutcome(
            assess_directive=assess_directive,
            new_exposure_permitted=permitted,
            admitted_order=None,
            admit_decision=None,
            declined=True,
            first_reject_constraint=None,
            non_directional_reason=captured_reason["reason"],
        )

    # ----- decide (Edge) — fed the pinned reactive snapshot (BL-2). -----------
    decision = decide(
        candidate.features,
        candidate.direction,
        epoch.pinned_params.reactive_snapshot,
    )

    # ----- order_builder — only on an actionable decision (HOLD → declined). --
    order = build_order(
        decision,
        positions,
        candidate.reference_price,
        epoch.pinned_params,
        symbol=symbol,
        advisory_max_volume=None,  # initial build: no survival cap known yet
        stop_loss_atr_mult=stop_loss_atr_mult,
    )

    if order is None:
        # HOLD / sub-threshold / a reactive-contract violation → declined trace
        # (Req 2.5); no admit.
        return OrchestrationOutcome(
            assess_directive=assess_directive,
            new_exposure_permitted=permitted,
            admitted_order=None,
            admit_decision=None,
            declined=True,
            first_reject_constraint=None,
            non_directional_reason=captured_reason["reason"],
        )

    # ----- per-order admit (the veto) — admit runs on the BUILT order. --------
    admit_decision, first_reject, final_order = _admit_with_single_resize(
        order=order,
        account=account,
        op_state=op_state,
        survival_params=survival_params,
        clock=clock,
        universe=universe,
        leverage=leverage,
        is_excluded=is_excluded,
        decision=decision,
        positions=positions,
        reference_price=candidate.reference_price,
        epoch=epoch,
        symbol=symbol,
        stop_loss_atr_mult=stop_loss_atr_mult,
        build_order=build_order,
        admit=admit,
    )

    # The admitted daemon order (with its position_id retained for the broker
    # submit, task 4.2) is the order that cleared the FINAL admit — the resized
    # one if a resize happened. None when nothing was admitted.
    admitted = final_order if admit_decision.decision == "ALLOW" else None

    return OrchestrationOutcome(
        assess_directive=assess_directive,
        new_exposure_permitted=permitted,
        admitted_order=admitted,
        admit_decision=admit_decision,
        declined=False,
        first_reject_constraint=first_reject,
        non_directional_reason=captured_reason["reason"],
    )


def orchestrate_tick(
    *,
    symbol: str,
    epoch: EpochContext,
    op_state: OperationalState,
    account: AccountState,
    survival_params: SurvivalParameters,
    clock: ClockState,
    feed: MarketFeed,
    universe: AbstractSet[str],
    leverage: Optional[float],
    is_excluded: Optional[bool],
    stop_loss_atr_mult: float,
    assemble: Callable[..., Optional[Candidate]],
    decide: Callable[..., ReactiveDecision],
    build_order: Callable[..., Optional[ProposedOrder]],
    get_positions: Callable[[], Sequence[Position]],
    admit: Callable[
        [
            SurvivalProposedOrder,
            AccountState,
            OperationalState,
            SurvivalParameters,
            ClockState,
            OrderEvaluation,
        ],
        AdmitDecision,
    ],
    assess: Callable[
        [AccountState, OperationalState, SurvivalParameters, ClockState],
        AssessDirective,
    ],
) -> OrchestrationOutcome:
    """Run one §13 gate-orchestration walk (assess then edge path) and return its
    structured outcome.

    This is the **combined** walk — :func:`run_assess` (Phase 1) immediately
    followed by :func:`run_edge_path` (Phase 2), with **no persist seam between
    them**. It is the inner-ring-testable surface (the orchestrator unit test
    drives it directly with synthetic state + the REAL pure ``admit`` / ``assess``,
    P14) and the shape a caller uses when it does **not** own the durable
    persist-then-act seam (e.g. a dry-run harness).

    The **loop** (task 4.4) does **not** call this combined form on its live path —
    it calls :func:`run_assess`, **durably persists** the resulting op-state
    transition + events (Req 5.1), then calls :func:`run_edge_path`, so the
    op-state transition is committed before any directive/admit acts. The two
    forms are behaviorally identical when no kill-switch is engaged mid-tick;
    the split exists purely to give the loop a seam to persist *between* the
    standing monitor and the act (persist-then-act).

    The deps are injected (the loop wires the real ``candidate.assemble`` /
    ``signal_model.decide`` / ``order_builder.build_order`` / ``broker.get_positions``
    / ``gate.admit`` / ``gate.assess``).

    Args:
        symbol: the ticker under evaluation.
        epoch: the pinned-param epoch (P3 — supplies the reactive snapshot).
        op_state: the **freshly-read** operational state (Req 5.2).
        account: the broker-assembled survival ``AccountState`` fed to
            ``assess`` / ``admit``. Its ``.positions`` are **survival**
            ``Position``; the ``order_builder`` consumes the **broker**
            ``Position`` from ``get_positions`` (the two types share fields but are
            distinct — G4), so both seams are threaded.
        survival_params: the pinned ``SurvivalParameters`` (survival namespace).
        clock: the ``ClockState``.
        feed: the fast-clock ``MarketFeed`` (threaded into ``assemble``).
        universe / leverage / is_excluded: the ``OrderEvaluation`` legs.
        stop_loss_atr_mult: the protective-stop multiplier (Req 11.3).
        assemble / decide / build_order / get_positions / admit / assess: the
            injected deps.

    Returns:
        An :class:`OrchestrationOutcome`.
    """
    # ----- Step 1 (Phase 1): Survive standing-monitor (assess) — Req 1.2. ----
    assess_directive = run_assess(
        op_state=op_state,
        account=account,
        survival_params=survival_params,
        clock=clock,
        assess=assess,
    )

    # ----- Step 2 + 3 (Phase 2): permit → candidate → decide → build → admit. -
    # No persist seam here — the combined form acts immediately. The LOOP inserts
    # the durable persist of `assess_directive.next_op_state` between these phases
    # (persist-then-act, Req 5.1).
    return run_edge_path(
        symbol=symbol,
        epoch=epoch,
        op_state=op_state,
        account=account,
        survival_params=survival_params,
        clock=clock,
        feed=feed,
        universe=universe,
        leverage=leverage,
        is_excluded=is_excluded,
        stop_loss_atr_mult=stop_loss_atr_mult,
        assess_directive=assess_directive,
        assemble=assemble,
        decide=decide,
        build_order=build_order,
        get_positions=get_positions,
        admit=admit,
    )


def _admit_with_single_resize(
    *,
    order: ProposedOrder,
    account: AccountState,
    op_state: OperationalState,
    survival_params: SurvivalParameters,
    clock: ClockState,
    universe: AbstractSet[str],
    leverage: Optional[float],
    is_excluded: Optional[bool],
    decision: ReactiveDecision,
    positions: Sequence[Position],
    reference_price: float,
    epoch: EpochContext,
    symbol: str,
    stop_loss_atr_mult: float,
    build_order: Callable[..., Optional[ProposedOrder]],
    admit: Callable[..., AdmitDecision],
) -> tuple[AdmitDecision, Optional[str], ProposedOrder]:
    """Admit the order; on a size-breach REJECT+advisory, resize+rebuild+readmit
    EXACTLY ONCE (Req 3.5), never upsizing above the advisory (P7).

    Returns ``(final AdmitDecision, first-reject binding constraint, final order)``:
    the ``binding_constraint`` is that of the **first** reject (the trace
    ``gate_link``, Req 2.3, even after a resize re-admit), and ``final order`` is
    the daemon ``ProposedOrder`` that reached the final ``admit`` — the **resized**
    one if a resize happened, else the original — so the caller surfaces the
    actually-admitted order (with its ``position_id`` retained for the submit).
    """
    survival_order = _to_survival_order(order)
    evaluation = build_order_evaluation(
        symbol=order.symbol,
        volume=order.volume,
        reference_price=reference_price,
        leverage=leverage,
        universe=universe,
        is_excluded=is_excluded,
    )
    first = admit(
        survival_order, account, op_state, survival_params, clock, evaluation
    )
    if first.decision == "ALLOW":
        return first, None, order

    first_reject_constraint = first.binding_constraint

    # Resize-on-advisory: ONLY when the gate supplies an advisory_max_volume (a
    # size breach). Any other reject (kill_switch / universe / margin / missing_sl)
    # is terminal — the daemon never loops to force a fit (P7 / never-upsize).
    if first.advisory_max_volume is None:
        return first, first_reject_constraint, order

    # Re-build with the advisory cap threaded in (order_builder clamps ≤ advisory
    # — never-upsize). The daemon NEVER mutates the gate's order; it rebuilds.
    resized = build_order(
        decision,
        positions,
        reference_price,
        epoch.pinned_params,
        symbol=symbol,
        advisory_max_volume=first.advisory_max_volume,
        stop_loss_atr_mult=stop_loss_atr_mult,
    )
    if resized is None:
        # The re-build declined (degenerate) → the original reject stands; no
        # admitted order.
        return first, first_reject_constraint, order

    resized_survival = _to_survival_order(resized)
    resized_eval = build_order_evaluation(
        symbol=resized.symbol,
        volume=resized.volume,
        reference_price=reference_price,
        leverage=leverage,
        universe=universe,
        is_excluded=is_excluded,
    )
    second = admit(
        resized_survival,
        account,
        op_state,
        survival_params,
        clock,
        resized_eval,
    )
    # Exactly one resize pass — the second verdict is final whether ALLOW or
    # REJECT (no further resize loop).
    return second, first_reject_constraint, resized


# --------------------------------------------------------------------------- #
# Paper-mode order lifecycle driver (task 4.2 — Requirement 3).               #
# --------------------------------------------------------------------------- #
#
# Once an order clears ``admit`` (ALLOW), the daemon drives it through the
# broker's **paper-mode** submit→poll→reconcile lifecycle. This seam is
# deliberately small and pure-of-its-own-logic (Req 10): it obtains the venue
# action from ``broker.submit_decision`` and never simulates a fill itself.
#
# Four contracts (Req 3):
#
#   * **Paper-only (3.1).** The driver pins a paper ``RuntimeMode``
#     (``paper_enabled=True``) onto every ``submit_decision`` call, so the broker
#     can *never* route to its live-transmit path (``live_transmit_allowed()`` is
#     False whenever paper is on, by construction — broker ``config.RuntimeMode``).
#     There is no live branch in this module; v0.1 has no reachable live path.
#   * **submit→poll→reconcile to a terminal outcome (3.2).** ``submit_decision``
#     in paper mode returns a structured ``OrderResult`` synchronously
#     (``simulated`` / ``rejected`` / ``noop``); the driver classifies it to a
#     terminal lifecycle outcome. The poll is bounded (a slow venue surfaces
#     ``unconfirmed`` rather than stalling the single-threaded loop, Req 3.2/3.3)
#     — in paper the result is immediate, but the bounded shape is kept so the
#     same driver tolerates an ``unconfirmed`` without looping forever.
#   * **Unconfirmed surfaced, never filled (3.3).** An ``unconfirmed`` result is
#     reported AS unconfirmed; ``is_filled`` is True *only* for ``filled``.
#   * **Double-send guard (3.4).** While a submitted order's confirmation is
#     pending (an ``unconfirmed`` outcome), a re-drive for the **same order
#     intent** does NOT issue a duplicate submission — the daemon-owned
#     ``PaperSendGuard`` suppresses it (the broker's own 7.4 guard is on the
#     *live* path, unreachable in paper, so the daemon owns the paper-mode guard).
#
# This driver returns a structured :class:`PaperLifecycleOutcome` the loop
# (task 4.4) and the trace assembler (task 3.3) act on — it does not itself
# persist a trace or emit an event (those are the loop's seams; persist-then-act).


# Terminal lifecycle statuses (the broker ``OrderStatus`` union, all terminal in
# paper mode). ``filled`` is the only *confirmed fill* (Req 3.3); ``simulated`` is
# the paper confirm. ``unconfirmed`` is the only status that keeps an intent
# PENDING for the double-send guard (Req 3.4) — every other status
# (``filled`` / ``simulated`` / ``rejected`` / ``noop``) is a confirmed terminal
# that clears the pending mark.
_FILLED_STATUS = "filled"
_PENDING_STATUS = "unconfirmed"


@dataclass(frozen=True)
class PaperLifecycleOutcome:
    """The structured result of one paper-mode order lifecycle (task 4.2).

    ``status`` is the broker ``OrderStatus`` the lifecycle reached
    (``filled`` | ``simulated`` | ``rejected`` | ``noop`` | ``unconfirmed``).
    ``terminal`` is True once the poll/reconcile reached a terminal state (always
    True here — paper returns synchronously and an unconfirmed is itself the
    bounded-poll terminal). ``is_filled`` is True **only** on a ``filled`` status
    (an ``unconfirmed`` is never a fill — Req 3.3). ``result`` is the broker
    ``OrderResult`` surfaced verbatim for the trace/fill consumer (the fill price
    / volume / venue ids / reason live there). ``submitted`` is False when the
    double-send guard suppressed the submission (a re-drive while pending —
    Req 3.4); the surfaced ``result`` is then the prior pending outcome.
    """

    status: str
    terminal: bool
    is_filled: bool
    result: OrderResult
    submitted: bool = True


def _intent_fingerprint(order: ProposedOrder) -> tuple[str, str, str, Optional[str]]:
    """The double-send identity of an order intent (Req 3.4).

    Two submissions are "the same order intent" iff they target the same
    (``symbol``, ``intent``, ``direction``, ``position_id``). An open carries
    ``position_id=None``; a reduce/close carries the targeted id — so a reduce of
    one position never collides with an open or with a different position's
    reduce. The guard keys pending state on this tuple.
    """
    return (
        order.symbol,
        _intent_str(order.intent),
        _direction_str(order.direction),
        order.position_id,
    )


class PaperSendGuard:
    """The daemon-owned double-send guard for the paper lifecycle (Req 3.4).

    The broker's own duplicate-suppression (``core._double_send_guard``) lives on
    the *live* transmit path, which is unreachable in paper mode (Req 3.1), so the
    daemon owns the paper-mode guard. It records the **pending** (unconfirmed)
    submissions by intent fingerprint; while an intent is pending, a re-drive for
    the same intent is suppressed (no duplicate ``submit_decision``). A confirmed
    terminal outcome (``filled`` / ``simulated`` / ``rejected`` / ``noop``) clears
    the pending mark, so a genuinely-new later intent for the same target submits.

    Single-threaded by construction (the loop serializes evaluations, Req 1.1), so
    no lock is needed — a plain dict keyed on the intent fingerprint.
    """

    def __init__(self) -> None:
        # fingerprint -> the prior pending PaperLifecycleOutcome (surfaced verbatim
        # to a suppressed re-drive so the caller still sees the unconfirmed state).
        self._pending: dict[
            tuple[str, str, str, Optional[str]], PaperLifecycleOutcome
        ] = {}

    def pending_outcome(
        self, order: ProposedOrder
    ) -> Optional[PaperLifecycleOutcome]:
        """The prior pending outcome for this intent, or ``None`` if not pending."""
        return self._pending.get(_intent_fingerprint(order))

    def mark_pending(
        self, order: ProposedOrder, outcome: PaperLifecycleOutcome
    ) -> None:
        """Record an unconfirmed submission as pending (suppresses a re-send)."""
        self._pending[_intent_fingerprint(order)] = outcome

    def clear(self, order: ProposedOrder) -> None:
        """Clear a pending mark once the intent reaches a confirmed terminal."""
        self._pending.pop(_intent_fingerprint(order), None)


def drive_paper_lifecycle(
    order: ProposedOrder,
    *,
    submit_decision: Callable[..., OrderResult],
    guard: Optional[PaperSendGuard] = None,
    runtime_mode: Optional[RuntimeMode] = None,
    prior_queue_task_id: Optional[str] = None,
) -> PaperLifecycleOutcome:
    """Drive an admitted daemon ``ProposedOrder`` through the paper-mode
    submit→poll→reconcile lifecycle (task 4.2, Requirement 3).

    Maps the daemon-owned ``ProposedOrder`` (with its ``position_id`` retained for
    the submit, BL-3) to the broker ``submit_decision`` args, pins a **paper**
    ``RuntimeMode`` so no live path is reachable (Req 3.1), and classifies the
    structured ``OrderResult`` to a terminal :class:`PaperLifecycleOutcome`.

    The double-send guard (Req 3.4): if a ``guard`` is supplied and this exact
    order intent is already pending (a prior ``unconfirmed``), the driver does NOT
    re-submit — it returns the prior pending outcome with ``submitted=False``. A
    fresh submission that comes back ``unconfirmed`` is recorded as pending; a
    confirmed terminal (``filled`` / ``simulated`` / ``rejected`` / ``noop``)
    clears the pending mark (Req 3.3 surfaces ``unconfirmed``, never a fill).

    Args:
        order: the **admitted** daemon ``ProposedOrder`` (post-``admit`` ALLOW).
        submit_decision: the broker leaf ``broker.core.submit_decision`` (injected
            so this is inner-ring-testable with a synthetic broker stub — the loop,
            task 4.4, wires the real one through the broker seam).
        guard: the daemon-owned double-send guard (Req 3.4). When ``None`` the
            guard is skipped (a single isolated submit — e.g. the inner-ring poll
            tests); the loop owns one guard across ticks.
        runtime_mode: an explicit paper ``RuntimeMode``; when ``None`` the driver
            constructs the safe default (``paper_enabled=True`` ⇒ no live path).
        prior_queue_task_id: retained from a prior unconfirmed result; threaded to
            the broker so its own (live-path) guard can correlate on a re-send. In
            paper mode this is moot (no live POST), but it is carried for parity.

    Returns:
        A :class:`PaperLifecycleOutcome` (terminal status + is_filled + the raw
        ``OrderResult``); ``submitted=False`` when the guard suppressed the send.
    """
    # ----- double-send guard (Req 3.4): suppress a re-drive while pending. ----
    if guard is not None:
        pending = guard.pending_outcome(order)
        if pending is not None:
            # A prior submission for this exact intent is still pending — do NOT
            # issue a duplicate. Surface the prior pending (unconfirmed) outcome,
            # flagged not-submitted.
            return PaperLifecycleOutcome(
                status=pending.status,
                terminal=pending.terminal,
                is_filled=pending.is_filled,
                result=pending.result,
                submitted=False,
            )

    # ----- paper-only routing (Req 3.1): pin paper; no live path reachable. ---
    # A default ``RuntimeMode`` is already paper-on + all live clearances safe-off,
    # so ``live_transmit_allowed()`` is False by construction. We pin it explicitly
    # so the broker can never route to ``_submit_live`` regardless of env.
    rm = runtime_mode if runtime_mode is not None else RuntimeMode()
    # Defense-in-depth (P6): force paper on even if a non-paper RuntimeMode was
    # passed — v0.1 has no reachable live path through this driver.
    if not rm.paper_enabled:
        rm = RuntimeMode(paper_enabled=True)

    # ----- submit (at most once per pending intent) → poll/reconcile. ---------
    # Map the daemon ProposedOrder → broker submit args: ``intent`` is the P9
    # ``Label`` (BUY/TRIM/SELL) ``submit_decision`` routes on; ``direction`` the
    # broker ``Direction`` enum; ``volume`` / ``stop_loss`` verbatim; the
    # ``position_id`` retained on the daemon order (BL-3) targets a reduce/close.
    result = submit_decision(
        order.intent,
        order.symbol,
        order.direction,
        volume=order.volume,
        position_id=order.position_id,
        stop_loss=order.stop_loss,
        runtime_mode=rm,
        prior_queue_task_id=prior_queue_task_id,
    )

    outcome = _classify_paper_result(result)

    # ----- reconcile the guard (Req 3.4): pending iff unconfirmed. ------------
    if guard is not None:
        if outcome.status == _PENDING_STATUS:
            guard.mark_pending(order, outcome)
        else:
            # A confirmed terminal clears any prior pending mark for this intent.
            guard.clear(order)

    return outcome


def _classify_paper_result(result: OrderResult) -> PaperLifecycleOutcome:
    """Classify a broker ``OrderResult`` to a terminal :class:`PaperLifecycleOutcome`.

    Every paper-mode ``OrderResult`` is terminal (the broker returns synchronously
    in paper; an ``unconfirmed`` is itself the bounded-poll terminal — Req 3.2).
    ``is_filled`` is True **only** for ``filled`` — an ``unconfirmed`` is never a
    fill (Req 3.3), nor is a ``simulated`` paper confirm a venue fill.
    """
    status = result.status
    return PaperLifecycleOutcome(
        status=status,
        terminal=True,
        is_filled=status == _FILLED_STATUS,
        result=result,
        submitted=True,
    )
