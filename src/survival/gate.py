"""Survival Gate decision core (pure, deterministic, inner-ring).

This is the ``gate`` module of the ``survival`` package (dependency direction
``types → params → gate``): it imports only from :mod:`src.survival.types` and
:mod:`src.survival.params` and the standard library. Nothing is imported
upward. Pure: **no I/O**, no DB / MCP / LLM imports; identical inputs produce an
identical result (R11.1 / R11.2, P14).

Design source: ``.kiro/specs/survival-gate/design.md`` §"Decision core — `gate`",
§"Architecture → Fail direction" + "Op-state freshness", and the Requirements
Traceability row 1.

Scope (tasks 3.1 + 3.2 + 4.1)
-----------------------------
Task 3.1 created the module and the shared account-level margin-distance helper,
:func:`check_margin_distance`. Task 3.2 ADDED the first public entry point,
:func:`admit` (the per-order veto), and its private exit-vs-open classifier.
Task 4.1 ADDS the second public entry point, :func:`assess` (the no-order
standing monitor). The capitalization precondition ``check_capitalization`` (task
4.2) is a *later* task that ADDS to this same file — it is deliberately **not**
stubbed here (no placeholder functions, no TODOs).

The ``assess`` standing monitor (task 4.1)
------------------------------------------
:func:`assess` evaluates account state with **no proposed order** — the daemon
calls it every tick whether or not an order exists (design §"System Flows →
`assess`"). It returns an :class:`AssessDirective` carrying the next operational
state, the de-risk directives, and the after-market events.

The design flowchart reads as a cascade, but ``assess`` is implemented as an
**accumulate-then-rank-max** evaluator (per the operator's safe-interpretation
note, P6/P7): every condition is evaluated and its directives + events are
*accumulated*, then the next grade is the **rank-max** over the input grade and
every condition grade. This deliberately overrides the flowchart's branch
structure so an engaged kill switch can never short-circuit and **mask** a
co-occurring margin breach (the catastrophe to avoid is letting one protective
condition hide another — fail-toward-more-protection).

Conditions (each evaluated; none masks another):

  1. **kill switch** (``op_state.kill_switch_engaged``): emit a ``FREEZE_ENTRIES``
     directive. ``assess`` does NOT engage/disengage the kill switch
     (operator-only, R9.3) — ``kill_switch_engaged`` is carried through unchanged.
  2. **margin path (R1.5 / R8):** reuse :func:`check_margin_distance` with
     ``additional_used_margin=0.0`` (no order → no delta). The band→grade mapping
     reuses the helper's breach booleans (no re-derived thresholds):
       * ``breaches_stop_out`` (level ≤ stop-out, the liquidation line) → FLATTEN
         grade + FLATTEN directive + ``margin_breach`` / ``safe_mode_entered``
         events.
       * ``breaches_safe_mode_buffer and not breaches_stop_out`` (the danger band
         strictly above stop-out) → HALT_NEW grade + REDUCE directive + the same
         two events.
     The lighter TIGHTEN band is **not** entered by the pure-margin path: with
     only the two pinned thresholds (``stop_out_level_pct`` /
     ``safe_mode_buffer_pct``) there is no third margin line to key a TIGHTEN
     sub-band off, and inventing one would violate "no thresholds not in params"
     (R10.3). TIGHTEN is reserved for other / Phase-2 anomaly inputs.
     A degraded ``AccountState`` (e.g. ``NaN`` equity) fails toward breach for
     free — :func:`check_margin_distance` already coerces ``NaN`` → ``0.0`` level
     → stop-out breach → FLATTEN (so there is no parallel degraded-state detector
     here; the fail-toward-protection direction is inherited).
  3. **closure path (R6):** if ``clock.seconds_to_next_closure`` is within
     ``params.flatten_lead_seconds`` AND there is open levered exposure
     (positions held), emit a FLATTEN directive per held position, then
     **re-check the flat post-condition** (R6.2 — verify actually flat, do not
     trust that a flatten was issued). Within a single ``assess`` call the
     ``state`` is fixed, so the re-check against the same ``state`` is not-flat
     **whenever there were positions to flatten** — i.e. emitting flatten
     directives and escalating to FLATTEN grade + a ``flat_verify_failed`` event
     **co-occur** (there is no within-call grace period: a stateless function
     cannot grant one — ``op_state`` carries no "flatten-requested" flag). R6.3's
     "until flat" is realized **across ticks** by the daemon: the next tick sees a
     now-flat state → the closure path does not fire → the latched grade stays.
     The re-check is a structurally separate :func:`_is_flat` call (not an inlined
     ``True``), proven by the already-flat closure case (no directives, no
     escalation, no event).

There is **no halt branch** (R7): ``assess`` has no ``trading_status`` / halt
parameter and emits no halt-triggered freeze / flatten / alert under any input.
An intraday halt is invisible to ``assess`` except via its account-level margin
consequence (margin moving against the book), which routes through the margin /
safe-mode path above. There is no ``FLATTEN_AT_REOPEN`` directive kind in the
type at all.

The grade is **monotonic-tighten + latched** (R8.3, design line 202):
``next_op_state.safe_mode_grade`` rank is **≥** the input grade rank — it never
decreases. It is computed as the rank-max of the input grade and every triggered
condition grade, via the centralized :func:`grade_rank` (compared by integer
rank, never by string string-comparison). Latching falls out: a clean call
computes ``max(input, NONE) == input``, so a tripped grade survives a later clean
tick (loosening is the operator / after-market path, out of boundary —
R10.4 / §14.4).

``assess`` is deterministic in all inputs (R11.1): it reads only its arguments
(closure-imminence comes from ``clock``, never ``datetime.now()``) and builds the
emitted ``entered_at`` / ``account_snapshot`` from inputs only — it never stamps
a wall-clock time (the daemon stamps the real persist time). It carries the
input ``op_state.entered_at`` / ``triggered_by`` through unchanged so two
identical calls compare equal.

The ``admit`` lexicographic walk + exit classification
------------------------------------------------------
:func:`admit` evaluates a proposed order through the design's fixed
lexicographic order (§"System Flows → `admit`"), stopping at and reporting the
**first** binding constraint via ``AdmitDecision.binding_constraint``:

    kill_switch → safe_mode → not_activated → universe → entry_exclusion →
    margin_distance → size_limit → missing_sl

There is **no halt step** (R7, real-time halt detection out of boundary) and
``funding_cap`` is **never** emitted here — the §16 funding cap is a
*capitalization-time* precondition (task 4.2 ``check_capitalization``), not part
of this per-order walk (design §"System Flows", R3.2 reconciliation).

**Exit-vs-open is classified by EFFECT on the held position, not by the
disposition label** (P7 — the upstream ``intent`` BUY/TRIM/SELL is audit/trace
only and must NOT be trusted for this decision). A proposed order short-circuits
to ALLOW (fail-toward-flat) *iff* it is a **true exit** — opposite-side to a
single held position in the same symbol, with volume ≤ that position's held
volume (strictly net-reducing, no side flip). The exit short-circuit runs
**before every walk step**, so getting flat is always possible: a true exit is
allowed even under an engaged kill switch, under safe-mode HALT_NEW/FLATTEN, and
with ``stop_loss=None``. Everything else — no held position, a same-side add, or
an opposite-side order whose volume *exceeds* the held position (flatten-then-
flip = net-new exposure) — is an **open/add** and takes the full walk. On **any**
classification ambiguity (an unrecognized ``direction`` value, a garbage held
direction, or *multiple* held positions in the same symbol) the classifier
**fails toward open** — the catastrophe to avoid is misclassifying an open as an
exit and slipping new exposure past the kill switch (design §"Fail direction =
minimum exposure"). The classifier keeps netting deliberately light: it never
builds a multi-position netting engine, it only refuses to short-circuit an
ambiguous case.

The three daemon-derived inputs — :class:`OrderEvaluation`
----------------------------------------------------------
``admit`` needs an order's projected margin delta, its universe membership, and
its exclusion flag, none of which the pure core can derive (they need broker /
instrument / screen knowledge = Phase-2, out of boundary). They are threaded in
via one explicit frozen context, :class:`~src.survival.types.OrderEvaluation`,
which the ``execution-daemon`` populates (a cross-spec, revalidation-adjacent
seam). Its **reject-leaning defaults** make the safe value the rejecting one for
opens (fail-toward-not-adding): an absent margin delta (``None``) rejects
``margin_distance`` (never silently coerced to ``0.0``); unknown universe rejects
``universe``; unknown exclusion, *when exclusion is enabled*, rejects
``entry_exclusion``. A missing screen can therefore never read as "in-universe,
not-excluded, zero-margin."

Op-state is read fresh (R9 freshness)
-------------------------------------
``op_state`` is an argument read on every call — never folded into the pinned
parameter snapshot — so a just-engaged kill switch / escalated safe-mode is
observed by every subsequent ``admit`` (the freshness guarantee, design
§Architecture). The kill-switch-freshness unit test toggles ``op_state`` between
otherwise-identical calls and asserts the result flips.

Margin-level convention (R1.1)
------------------------------
**margin level (%) = equity / aggregate_used_margin × 100** — cross-margin,
account-level (R1.1). A **higher** percentage is **safer** (more liquidation
distance). Because the venue stop-out and the safe-mode buffer are both
margin-level percentages, a **breach is margin level ≤ threshold** (at-or-below,
not strictly below): a lower level is the dangerous direction.

The current level is **computed** here (per R1.1) — the venue-supplied
``state.margin_level`` is **not** trusted; the computed value is **authoritative**
("keep it simple", task 3.1). We deliberately do **not** mix in the venue field:
an asymmetric ``min(computed, venue)`` on the current level only would break the
"``projected_level`` ≤ ``current_level``" invariant the breach booleans rely on
(a venue value below the computed current, with no add, would pull
``current_level`` below ``projected_level`` and the projected-keyed booleans
would fail-open in the ``assess`` no-add path — the dangerous direction). The
design's "tighter of the two" note concerns ``stop_out_level`` vs the pinned
parameter, **not** ``margin_level`` vs the computed level, so no venue-min is
required here. Both current and projected are computed solely from ``equity`` and
the supplied margin deltas, on the same basis — preserving projected-is-worst-case.

The projection input (scope boundary)
--------------------------------------
Deriving an order's margin requirement from its ``volume`` needs
leverage / price / contract-size — **broker/instrument knowledge = Phase-2, out
of this boundary**. So this pure check takes the projected margin delta as an
**explicit input** (``additional_used_margin``, default ``0.0`` for the
no-order ``assess`` case). Synthetic inner-ring tests supply it directly. This
helper does **not** compute margin-from-volume (that is Phase-2 wiring).

The breach booleans key off the **projected** (worst-case) level
----------------------------------------------------------------
Adding to the denominator only ever lowers the ratio, so ``projected_level`` ≤
``current_level`` always. Keying ``breaches_stop_out`` / ``breaches_safe_mode_buffer``
off the **projected** level therefore (a) covers an already-breaching current
level, and (b) catches a proposed add that pushes a currently-safe account into
breach — exactly what the ``admit`` consumer (task 3.2) needs. With the default
``additional_used_margin == 0.0`` (the ``assess`` no-order case, task 4.1)
projected == current, so the booleans reflect the current level there.

Funding balance as the hard loss bound (R1.4)
---------------------------------------------
Per R1.4 the account-level *hard loss bound* is the funded ``balance`` (the §16
funding cap), **not** any per-position stop-loss distance: with no
negative-balance protection, the most the account can lose is what was funded.
This helper reasons about *liquidation distance* (margin level vs the venue
stop-out + safe-mode buffer); the funding-cap enforcement itself is task 4.2
(``check_capitalization``). The bound is honored conceptually here — the
margin-distance question is "how close is the account to the venue liquidation
line", never "how far is price from a stop".

Edge cases (fail toward a safe assessment)
------------------------------------------
- ``aggregate_used_margin == 0`` (no open positions / no leverage): the margin
  level is undefined / infinite → represented as ``math.inf`` and therefore
  **not breaching** (``inf <= threshold`` is ``False``); there is no liquidation
  risk with zero leverage and no divide-by-zero. The same applies to the
  projected denominator.
- Negative / zero equity (a blown account, no NBP) falls out naturally as a
  breach: a non-positive numerator over a positive denominator yields a level
  ≤ 0 ≤ threshold. It is **not** special-cased.
- A **non-finite computed level** (e.g. a ``NaN`` ``equity`` field on a degraded
  ``AccountState``) would make ``NaN <= threshold`` evaluate ``False`` →
  fail-*open*, the wrong direction for this node. So a ``NaN`` level is coerced
  toward **breach** (treated as ``0.0``, the most-dangerous level); a genuine
  ``inf`` (zero-leverage, below) is preserved as not-breaching. (Validating the
  ``AccountState`` shape is the Phase-2 adapter's job; this is a defensive
  fail-toward-breach so a degraded field cannot read as "all clear" here.)
- This helper never raises on a plausible (even odd) market input — a degraded
  state degrades toward "breach", never toward "all clear".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.survival.params import SurvivalParameters
from src.survival.types import (
    AccountState,
    AdmitDecision,
    AssessDirective,
    ClockState,
    HALT_NEW_RANK,
    OperationalState,
    OrderEvaluation,
    ProposedOrder,
    ReduceDirective,
    SafeModeGrade,
    SurvivalEvent,
    grade_rank,
)


@dataclass(frozen=True)
class MarginDistanceResult:
    """The account-level margin-distance assessment (internal intermediate).

    Consumed by ``admit`` (task 3.2) and ``assess`` (task 4.1). Not one of the
    design's enumerated input/output *contracts* (those live in ``types``); it is
    a lean, frozen, internal result of the shared margin-distance check.

    Fields (margin levels are percentages; higher = safer):

      * ``current_level`` — the computed current account margin level (R1.1;
        equity / used_margin × 100, authoritative — the venue ``margin_level``
        is not mixed in). ``math.inf`` when there is no used margin.
      * ``projected_level`` — the margin level after the proposed add
        (``equity / (used_margin + additional_used_margin) × 100``). Equals
        ``current_level`` when ``additional_used_margin == 0``. ``math.inf`` when
        the projected denominator is zero.
      * ``breaches_stop_out`` — ``projected_level <= stop_out_level_pct`` (R1.2
        liquidation line).
      * ``breaches_safe_mode_buffer`` — ``projected_level <= safe_mode_buffer_pct``
        (R1.3 buffer strictly above stop-out). A stop-out breach implies a buffer
        breach (the buffer is the higher threshold).
    """

    current_level: float
    projected_level: float
    breaches_stop_out: bool
    breaches_safe_mode_buffer: bool


def _margin_level(equity: float, used_margin: float) -> float:
    """Margin level (%) = equity / used_margin × 100 (R1.1).

    Returns ``math.inf`` when ``used_margin`` is zero (no leverage → no
    liquidation risk) so the downstream ``<= threshold`` comparison is naturally
    ``False`` with no special-casing. A non-positive ``used_margin`` is also
    treated as "no liquidation distance to measure" → ``inf`` (a negative
    aggregate used margin is not a plausible venue state; failing toward
    not-breaching here is safe because zero/sub-zero leverage carries no
    liquidation risk — the dangerous direction is a *small positive* denominator
    against a *small* numerator, which this formula reflects directly).

    A ``NaN`` result (e.g. a ``NaN`` ``equity`` on a degraded state) is coerced
    to ``0.0`` — the most-dangerous level — so a degraded field fails toward
    **breach**, never toward "all clear" (R1 fail-direction). A genuine ``inf``
    is preserved (zero-leverage = not breaching).
    """
    if used_margin <= 0.0:
        return math.inf
    level = equity / used_margin * 100.0
    if math.isnan(level):
        return 0.0
    return level


def check_margin_distance(
    state: AccountState,
    params: SurvivalParameters,
    additional_used_margin: float = 0.0,
) -> MarginDistanceResult:
    """Account-level margin-distance check (pure; R1.1–R1.3, R11.1).

    Computes the **current** margin level (R1.1: ``equity / used_margin × 100``;
    higher = safer) and the **projected** level after a proposed add
    (``equity / (used_margin + additional_used_margin) × 100``), then compares the
    projected (worst-case) level against the venue stop-out (R1.2) and the
    safe-mode buffer (R1.3). A breach is margin level **≤** the threshold.

    ``additional_used_margin`` is the **explicit** projected margin delta of a
    proposed add (default ``0.0`` for the no-order ``assess`` case). Deriving it
    from order volume needs broker/instrument knowledge and is **out of this
    boundary** (Phase-2) — this helper does not compute margin-from-volume.

    The current level is computed (not trusted from ``state.margin_level``); the
    computed value is authoritative ("keep it simple", task 3.1). Both current
    and projected are computed on the same basis (``equity`` + the supplied
    margin deltas), preserving ``projected_level`` ≤ ``current_level`` so the
    projected-keyed breach booleans cover the current level too.

    Pure and deterministic: reads only its arguments, performs no I/O, and never
    raises on a plausible market input (a degraded state degrades toward
    "breach"). ``used_margin == 0`` → ``math.inf`` level → not breaching (no
    divide-by-zero).
    """
    equity = state.equity

    # Current level: computed per R1.1, authoritative (the venue ``margin_level``
    # is not mixed in — an asymmetric current-only venue-min would break the
    # projected ≤ current invariant the breach booleans rely on, fail-open in the
    # no-add ``assess`` path).
    current_level = _margin_level(equity, state.used_margin)

    # Projected level: computed on the SAME basis + the supplied margin deltas
    # (the venue reports no projected level). Adding to the denominator only
    # lowers the ratio, so projected_level <= current_level always.
    projected_level = _margin_level(equity, state.used_margin + additional_used_margin)

    breaches_stop_out = projected_level <= params.stop_out_level_pct
    breaches_safe_mode_buffer = projected_level <= params.safe_mode_buffer_pct

    return MarginDistanceResult(
        current_level=current_level,
        projected_level=projected_level,
        breaches_stop_out=breaches_stop_out,
        breaches_safe_mode_buffer=breaches_safe_mode_buffer,
    )


# --------------------------------------------------------------------------- #
# admit — the per-order veto (task 3.2).                                       #
# --------------------------------------------------------------------------- #

# The two recognized market sides (the broker ``Direction`` enum, mirrored on
# ``Position.direction`` / ``ProposedOrder.direction``). Any other value is
# unrecognized and fails toward OPEN in the exit classifier (never short-circuits
# as an exit). ``intent`` (BUY/TRIM/SELL) is deliberately NOT consulted here —
# classification is by effect on the held position, not the disposition label
# (P7).
_RECOGNIZED_DIRECTIONS = frozenset({"LONG", "SHORT"})


def _is_true_exit(order: ProposedOrder, state: AccountState) -> bool:
    """Classify the order as a **true exit** (net-reducing, no side flip) — the
    only case that short-circuits ``admit`` to ALLOW (fail-toward-flat).

    A true exit is, *strictly*: opposite-side to a **single** held position in the
    **same symbol**, with ``order.volume <= position.volume`` (≤ is inclusive — a
    full flatten is an exit). Classification is by **effect on the held position,
    not the disposition label** (P7 — ``intent`` is ignored).

    **Fails toward OPEN on every ambiguity** (the catastrophe to avoid is
    misclassifying an open as an exit and slipping new exposure past the kill
    switch): an unrecognized ``order.direction`` value; no held position in the
    symbol; *multiple* held positions in the symbol (ambiguous netting — we never
    build a netting engine, we only refuse to short-circuit); a held position
    whose own ``direction`` is unrecognized; a same-side order (an add); or an
    opposite-side order whose volume *exceeds* the held position
    (flatten-then-flip = net-new exposure). Each of those returns ``False`` →
    the order takes the full walk.
    """
    if order.direction not in _RECOGNIZED_DIRECTIONS:
        return False  # unrecognized order side → fail toward open

    same_symbol = [p for p in state.positions if p.symbol == order.symbol]
    if len(same_symbol) != 1:
        # No held position (0) or multiple held positions (>1, ambiguous
        # netting) → fail toward open. We deliberately do not net a multi-leg
        # book here.
        return False

    held = same_symbol[0]
    if held.direction not in _RECOGNIZED_DIRECTIONS:
        return False  # garbage held side → fail toward open
    if held.direction == order.direction:
        return False  # same-side add increases exposure → open
    # Opposite side: a true exit iff it does not exceed the held volume (no flip).
    return order.volume <= held.volume


def _reject(
    binding_constraint: str,
    reason: str,
    advisory_max_volume: float | None = None,
) -> AdmitDecision:
    """A REJECT decision naming the first binding constraint (audit, R2/R11.3).

    ``advisory_max_volume`` is a non-binding suggestion supplied only on a size
    breach — the gate **never** returns a mutated/resized order (R2.3); the
    daemon resizes + re-submits.
    """
    return AdmitDecision(
        decision="REJECT",
        binding_constraint=binding_constraint,
        advisory_max_volume=advisory_max_volume,
        reason=reason,
    )


_ALLOW = AdmitDecision(
    decision="ALLOW",
    binding_constraint=None,
    advisory_max_volume=None,
    reason=None,
)


def admit(
    order: ProposedOrder,
    state: AccountState,
    op_state: OperationalState,
    params: SurvivalParameters,
    clock: ClockState,
    evaluation: OrderEvaluation,
) -> AdmitDecision:
    """The per-order veto: evaluate a proposed order through the fixed
    lexicographic walk and return ALLOW or REJECT(+binding constraint) (R2, R4,
    R5, R9, R11).

    A **true exit** (opposite-side to a single held position, volume ≤ held —
    net-reducing, no side flip) short-circuits to ALLOW *before every walk step*
    (fail-toward-flat: getting flat must always be possible, even under an
    engaged kill switch / safe-mode and with no stop-loss). Classification is by
    **effect on the held position, not the upstream disposition label** (P7); see
    :func:`_is_true_exit` (fails toward open on any ambiguity).

    For an **open/add** the walk runs in this fixed order, stopping at and
    reporting the first binding constraint:

      1. kill switch engaged                  → REJECT ``kill_switch`` (R9.1)
      2. safe-mode halts new entries          → REJECT ``safe_mode`` (R8/R1.5)
         (rank ≥ HALT_NEW — i.e. HALT_NEW or FLATTEN; TIGHTEN does not block)
      3. account not activated                → REJECT ``not_activated``
      4. symbol off-universe                  → REJECT ``universe`` (R5.1)
      5. exclusion enabled and flagged        → REJECT ``entry_exclusion`` (R5.2)
      6. projected margin breaches the buffer → REJECT ``margin_distance`` (R1)
      7. volume > per-order size cap          → REJECT ``size_limit`` +
                                                 ``advisory_max_volume`` (R4.1, R2.3)
      8. stop-loss missing                    → REJECT ``missing_sl`` (R4.2/R4.3)
      9. else                                 → ALLOW

    There is **no halt step** (R7) and ``funding_cap`` is never emitted here (it
    is task 4.2's capitalization-time precondition, not per-order — R3.2
    reconciliation). The three daemon-derived inputs arrive via ``evaluation``
    (:class:`OrderEvaluation`) with **reject-leaning defaults** so a missing
    screen fails toward not-adding.

    ``op_state`` is read fresh on every call (R9 freshness — never pinned).
    ``clock`` is part of the contract but unused by the admit walk (closure
    handling is ``assess``'s responsibility, R6). Pure / deterministic (R11.1):
    identical ``(order, state, op_state, params, clock, evaluation)`` →
    identical :class:`AdmitDecision`; reads only its arguments, performs no I/O,
    and never mutates ``order``.
    """
    # ----- Exit short-circuit (fail-toward-flat) — BEFORE every walk step. ---- #
    # A true exit always ALLOWs: it reduces exposure, so the kill switch /
    # safe-mode (which freeze NEW exposure) must never block it, and the
    # missing-SL check must not run ahead of it. ``intent`` is ignored — only the
    # effect on the held position decides (P7).
    if _is_true_exit(order, state):
        return _ALLOW

    # ----- The open/add lexicographic walk (first binding constraint wins). --- #
    # 1. Kill switch (R9.1) — the emergency halt; first because it is absolute.
    if op_state.kill_switch_engaged:
        return _reject("kill_switch", "kill switch engaged — all new routing halted")

    # 2. Safe-mode halts new entries (R8 / R1.5). Compared by integer RANK from
    #    the single ordering source (types._GRADE_RANK, shared with mig 049 and
    #    task 4.1), NOT by string. Rank ≥ HALT_NEW (HALT_NEW or FLATTEN) blocks an
    #    open; TIGHTEN (the lighter response) lets opens proceed.
    if grade_rank(op_state.safe_mode_grade) >= HALT_NEW_RANK:
        return _reject(
            "safe_mode",
            f"safe-mode grade {op_state.safe_mode_grade!r} halts new entries",
        )

    # 3. Account activation.
    if not state.activated:
        return _reject("not_activated", "account is not activated")

    # 4. Universe restriction (R5.1) — S&P 500 ∩ Gate-441. Unknown → off-universe
    #    by the reject-leaning OrderEvaluation default.
    if not evaluation.in_universe:
        return _reject("universe", "symbol outside the S&P 500 ∩ Gate-441 universe")

    # 5. Ex-ante exclusion (R5.2/R5.4) — only when enabled. Unknown is_excluded →
    #    flagged by the reject-leaning default (rejects only because enabled).
    if params.exclusion_enabled and evaluation.is_excluded:
        return _reject("entry_exclusion", "symbol flagged by the ex-ante exclusion screen")

    # 6. Projected margin distance (R1). An absent margin delta (None sentinel)
    #    means margin CANNOT be assessed → reject (never coerced to 0.0, which
    #    would make projected == current and fail open). Key the breach off the
    #    safe-mode BUFFER (the stricter early-warning line per design node M), not
    #    the stop-out line — an add must not drop the account below the buffer.
    if evaluation.additional_used_margin is None:
        return _reject(
            "margin_distance",
            "projected margin cannot be assessed (no margin delta supplied)",
        )
    margin = check_margin_distance(state, params, evaluation.additional_used_margin)
    if margin.breaches_safe_mode_buffer:
        return _reject(
            "margin_distance",
            "projected margin level at or below the safe-mode buffer",
        )

    # 7. Per-order size limit (R4.1). Breach is STRICTLY above the cap; on breach,
    #    REJECT + an ADVISORY max (the cap) — never a resized order (R2.3).
    if order.volume > params.per_order_size_max:
        return _reject(
            "size_limit",
            "order volume exceeds the per-order size limit",
            advisory_max_volume=params.per_order_size_max,
        )

    # 8. Mandatory protective stop-loss (R4.2/R4.3). Runs only on the open path
    #    (a true exit already short-circuited above).
    if order.stop_loss is None:
        return _reject("missing_sl", "open order carries no protective stop-loss")

    # 9. All survival constraints cleared.
    return _ALLOW


# --------------------------------------------------------------------------- #
# assess — the no-order standing monitor (task 4.1).                           #
# --------------------------------------------------------------------------- #

def _is_flat(state: AccountState) -> bool:
    """The flat post-condition (R6.2): the account is flat iff it holds no open
    positions. A structurally separate check — the closure path re-checks this
    against the (fixed) ``state`` rather than trusting that a flatten directive
    was issued.
    """
    return len(state.positions) == 0


def _json_safe(value: float) -> float | None:
    """Coerce a non-finite float (``NaN`` / ``inf`` — possible on a degraded
    ``AccountState``) to ``None``.

    Two reasons (both load-bearing for the degraded path the spec names by name):
      * **Determinism (R11.1):** ``NaN != NaN``, so embedding a raw ``NaN`` in the
        snapshot would make ``assess(...) == assess(...)`` False for a degraded
        state — breaking "deterministic in **all** inputs". Mapping every
        non-finite value to the single ``None`` sentinel restores equality.
      * **JSONB persistence:** ``float('nan')`` / ``inf`` are not valid JSON, so a
        raw non-finite snapshot field could fail when the daemon persists the
        event. ``None`` is JSON-safe.
    A finite value is returned unchanged.
    """
    return value if math.isfinite(value) else None


def _account_snapshot(state: AccountState) -> dict:
    """A deterministic, inputs-only, JSON-safe snapshot for a
    :class:`SurvivalEvent`.

    Built solely from ``state`` fields (no ``datetime.now()``, no object ids) so
    two identical ``assess`` calls emit equal snapshots (R11.1). Numeric fields
    pass through :func:`_json_safe` so a degraded ``NaN`` / ``inf`` (the spec's
    named degraded case) becomes ``None`` — keeping the snapshot both
    equality-stable (NaN != NaN would otherwise break determinism) and
    JSONB-persistable. Position count is captured rather than the full mutable
    position objects (the event log only needs the account-level picture; the
    daemon persists it as JSONB).
    """
    return {
        "equity": _json_safe(state.equity),
        "used_margin": _json_safe(state.used_margin),
        "free_margin": _json_safe(state.free_margin),
        "margin_level": _json_safe(state.margin_level),
        "balance": _json_safe(state.balance),
        "stop_out_level": _json_safe(state.stop_out_level),
        "activated": state.activated,
        "open_position_count": len(state.positions),
    }


def _max_grade(*grades: str) -> SafeModeGrade:
    """The monotonic rank-max of ``grades`` (R8.3 monotonic-tighten + latch).

    Returns the grade *string* whose :func:`grade_rank` is highest — comparison
    is by integer rank from the single ordering source (``types._GRADE_RANK``),
    never by string. Keeping the winning string avoids needing a rank→string
    inverse map. With ``_max_grade(input_grade)`` on a clean tick the input grade
    is returned unchanged, so a tripped grade is **latched** across calls.
    """
    return max(grades, key=grade_rank)  # type: ignore[return-value]


def assess(
    state: AccountState,
    op_state: OperationalState,
    params: SurvivalParameters,
    clock: ClockState,
) -> AssessDirective:
    """The no-order standing monitor: evaluate account state with **no proposed
    order** and emit the next operational state, de-risk directives, and
    after-market events (R1.5, R6, R7, R8, R11).

    **Accumulate, then rank-max — never cascade-mask** (P6/P7): every condition is
    evaluated and its directives + events are accumulated; the next grade is the
    rank-max over the input grade and every triggered condition grade. An engaged
    kill switch therefore cannot short-circuit and hide a co-occurring margin
    breach (fail-toward-more-protection).

    Conditions (each evaluated independently):

      1. **kill switch** (``op_state.kill_switch_engaged``) → ``FREEZE_ENTRIES``
         directive; ``kill_switch_engaged`` carried through unchanged (assess never
         engages/disengages — operator-only, R9.3).
      2. **margin (R1.5/R8)** — reuse :func:`check_margin_distance`
         (``additional_used_margin=0.0``): stop-out breach → FLATTEN grade +
         FLATTEN directive; buffer-only breach → HALT_NEW grade + REDUCE directive;
         both emit ``margin_breach`` + ``safe_mode_entered``. A degraded state
         (``NaN`` equity) fails toward breach via the helper (no parallel detector).
      3. **closure (R6)** — closure within ``params.flatten_lead_seconds`` with
         open exposure → a FLATTEN directive per held position, then re-check
         :func:`_is_flat`; while not flat (positions remain in this fixed state) →
         escalate to FLATTEN grade + a ``flat_verify_failed`` event. (R6.3's "until
         flat" is realized across ticks by the daemon.)

    There is **no halt branch** (R7): no halt input, no halt-triggered directive.
    An intraday halt surfaces only via its margin consequence → the margin path.

    The grade is monotonic-tighten + **latched** (R8.3): ``next_op_state``'s grade
    rank is ≥ the input grade's; a clean tick keeps the input grade. Deterministic
    in all inputs (R11.1): reads only its arguments, never the wall clock; carries
    the input ``entered_at`` / ``triggered_by`` through (no ``now()`` re-stamp).
    """
    reduce_directives: list[ReduceDirective] = []
    events: list[SurvivalEvent] = []
    # Condition grades accumulate; the input grade seeds the rank-max so a
    # previously-tripped grade is latched (never auto-loosens).
    condition_grades: list[str] = [op_state.safe_mode_grade]

    # --- Condition 1: kill switch (freeze new entries; carried through). ----- #
    # assess never engages/disengages the kill switch (operator-only, R9.3); it
    # only surfaces the freeze directive. This does NOT short-circuit — the
    # margin and closure conditions below are still evaluated (no masking).
    if op_state.kill_switch_engaged:
        reduce_directives.append(
            ReduceDirective(
                kind="FREEZE_ENTRIES",
                symbol=None,
                target_volume=None,
                reason="kill switch engaged — new entries frozen",
            )
        )

    # --- Condition 2: margin path (R1.5 / R8). ------------------------------- #
    # No proposed order → additional_used_margin = 0.0 (projected == current).
    # The breach booleans key off the same helper used by admit; a degraded
    # state (NaN equity) is already coerced to a stop-out breach inside the
    # helper (fail toward FLATTEN, never "all clear").
    margin = check_margin_distance(state, params, additional_used_margin=0.0)
    if margin.breaches_stop_out:
        # At/below the liquidation line → the heaviest response.
        condition_grades.append("FLATTEN")
        reduce_directives.append(
            ReduceDirective(
                kind="FLATTEN",
                symbol=None,
                target_volume=None,
                reason="margin level at or below the stop-out liquidation line",
            )
        )
        events.append(
            SurvivalEvent(
                event_type="margin_breach",
                ticker=None,
                detail="margin level at or below the stop-out line (FLATTEN band)",
                account_snapshot=_account_snapshot(state),
            )
        )
        events.append(
            SurvivalEvent(
                event_type="safe_mode_entered",
                ticker=None,
                detail="safe-mode entered at FLATTEN (stop-out breach)",
                account_snapshot=_account_snapshot(state),
            )
        )
    elif margin.breaches_safe_mode_buffer:
        # In the danger band (stop-out < level <= buffer) → halt new + reduce.
        condition_grades.append("HALT_NEW")
        reduce_directives.append(
            ReduceDirective(
                kind="REDUCE",
                symbol=None,
                target_volume=None,
                reason="margin level at or below the safe-mode buffer (danger band)",
            )
        )
        events.append(
            SurvivalEvent(
                event_type="margin_breach",
                ticker=None,
                detail="margin level at or below the safe-mode buffer (HALT_NEW band)",
                account_snapshot=_account_snapshot(state),
            )
        )
        events.append(
            SurvivalEvent(
                event_type="safe_mode_entered",
                ticker=None,
                detail="safe-mode entered at HALT_NEW (safe-mode buffer breach)",
                account_snapshot=_account_snapshot(state),
            )
        )

    # --- Condition 3: flat-before-closure (R6). ------------------------------ #
    # Fire only when a closure is within the flatten-lead window AND levered
    # exposure is open. Emit a FLATTEN per held position, then RE-CHECK the flat
    # post-condition (R6.2 — never trust that a flatten was issued). Because the
    # state is fixed within this call, the re-check is not-flat whenever there
    # were positions to flatten → escalate to FLATTEN + a flat_verify_failed
    # event (R6.3). The daemon realizes "until flat" across ticks: a later tick
    # over a now-flat state will not re-enter this path.
    s2c = clock.seconds_to_next_closure
    closure_imminent = s2c is not None and s2c <= params.flatten_lead_seconds
    if closure_imminent and not _is_flat(state):
        for pos in state.positions:
            reduce_directives.append(
                ReduceDirective(
                    kind="FLATTEN",
                    symbol=pos.symbol,
                    target_volume=0.0,
                    reason="flat-before-closure: closure within the flatten-lead window",
                )
            )
        # Re-check the post-condition against the (fixed) state. Within this call
        # positions still remain, so verify fails → escalate + record the event.
        if not _is_flat(state):
            condition_grades.append("FLATTEN")
            events.append(
                SurvivalEvent(
                    event_type="flat_verify_failed",
                    ticker=None,
                    detail=(
                        "flat post-condition not satisfied as closure approaches — "
                        "levered exposure still open; escalating to FLATTEN"
                    ),
                    account_snapshot=_account_snapshot(state),
                )
            )

    # --- Monotonic rank-max grade (latched; never auto-loosens). ------------- #
    next_grade = _max_grade(*condition_grades)

    next_op_state = OperationalState(
        # Kill switch is operator-only (R9.3) — carry the input through unchanged.
        kill_switch_engaged=op_state.kill_switch_engaged,
        safe_mode_grade=next_grade,
        # No wall-clock stamp (R11.1): carry the input identity fields through so
        # identical inputs yield an identical directive. The daemon stamps the
        # real persist time.
        entered_at=op_state.entered_at,
        triggered_by=op_state.triggered_by,
    )

    return AssessDirective(
        next_op_state=next_op_state,
        reduce_directives=reduce_directives,
        events=events,
    )


__all__ = [
    "MarginDistanceResult",
    "check_margin_distance",
    "admit",
    "assess",
]
