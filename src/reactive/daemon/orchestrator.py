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

from src.reactive.daemon.broker_seam import Direction, Position
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

__all__ = ["OrchestrationOutcome", "new_exposure_permitted", "orchestrate_tick"]


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
    """Run one §13 gate-orchestration walk and return its structured outcome.

    The deps are injected (the loop, task 4.4, wires the real
    ``candidate.assemble`` / ``signal_model.decide`` / ``order_builder.build_order``
    / ``broker.get_positions`` / ``gate.admit`` / ``gate.assess``) so this stays
    inner-ring-testable with synthetic state + the REAL pure ``admit`` / ``assess``
    (P14). ``assess`` is reached via the injected ``admit``'s sibling — but the
    standing-monitor is run here through the same gate module, so the loop passes
    ``gate.assess`` in as well; for the orchestrator's purposes the assess call is
    made through the injected ``_assess`` below.

    Args:
        symbol: the ticker under evaluation.
        epoch: the pinned-param epoch (P3 — supplies the reactive snapshot via
            ``epoch.pinned_params.reactive_snapshot`` for ``decide``).
        op_state: the **freshly-read** operational state (Req 5.2 — the loop reads
            it from ``survival_gate_state`` each tick; never a pinned copy).
        account: the broker-assembled survival ``AccountState`` (the loop builds it
            from ``broker.get_account_assets`` + ``get_positions`` and reads it
            fresh per tick) — fed to ``assess`` / ``admit``. Its ``.positions`` are
            **survival** ``Position``; the ``order_builder`` consumes the **broker**
            ``Position`` from ``get_positions`` (the two types share fields but are
            distinct — G4), so both seams are threaded rather than re-deriving one
            from the other.
        survival_params: the pinned ``SurvivalParameters`` (survival namespace).
        clock: the ``ClockState`` (closure-imminence + session — admit ignores it,
            assess uses it).
        feed: the fast-clock ``MarketFeed`` (threaded into ``assemble``).
        universe: the v0.1 S&P 500 ∩ Gate-441 allow-list (the OrderEvaluation
            universe leg).
        leverage: the broker-instrument leverage (the OrderEvaluation margin leg);
            ``None`` ⇒ margin unknown ⇒ the eval rejects ``margin_distance``.
        is_excluded: the §12.6 screen result (the OrderEvaluation exclusion leg);
            ``None`` ⇒ fail-safe excluded.
        stop_loss_atr_mult: the protective-stop multiplier threaded into
            ``build_order`` (Req 11.3).
        assemble / decide / build_order / get_positions / admit / assess: the
            injected deps (the loop wires the real ``gate.admit`` / ``gate.assess``;
            tests hand spies wrapping the real pure survival functions).

    Returns:
        An :class:`OrchestrationOutcome` (the assess directive + the op-state-derived
        permit + the admitted daemon order / admit verdict / declined flag /
        first-reject constraint).
    """
    # ----- Step 1: Survive standing-monitor (assess) — EVERY tick (Req 1.2). --
    # Runs first, even when the permit is later denied — the Survive gate's
    # standing monitor is never skipped (it emits the op-state transition the loop
    # persists before any act, persist-then-act Req 5.1).
    assess_directive = assess(account, op_state, survival_params, clock)

    # ----- Step 2: derive "new exposure permitted" from op-state (Req 2.1). ---
    permitted = new_exposure_permitted(op_state)

    # ----- Step 3: candidate → decide → order_builder → admit. ----------------
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
