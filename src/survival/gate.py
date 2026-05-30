"""Survival Gate decision core (pure, deterministic, inner-ring).

This is the ``gate`` module of the ``survival`` package (dependency direction
``types → params → gate``): it imports only from :mod:`src.survival.types` and
:mod:`src.survival.params` and the standard library. Nothing is imported
upward. Pure: **no I/O**, no DB / MCP / LLM imports; identical inputs produce an
identical result (R11.1 / R11.2, P14).

Design source: ``.kiro/specs/survival-gate/design.md`` §"Decision core — `gate`",
§"Architecture → Fail direction" + "Op-state freshness", and the Requirements
Traceability row 1.

Scope (task 3.1)
----------------
This task creates the module and the **one** shared account-level margin-distance
helper, :func:`check_margin_distance`. The two public entry points ``admit`` /
``assess`` and the capitalization precondition ``check_capitalization`` are
*later* tasks (3.2 / 4.1 / 4.2) that ADD to this same file — they are
deliberately **not** stubbed here (no placeholder functions, no TODOs); the
module is a clean skeleton carrying exactly this helper.

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
from src.survival.types import AccountState


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


__all__ = [
    "MarginDistanceResult",
    "check_margin_distance",
]
