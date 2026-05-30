"""OrderEvaluation projection — the survival ``admit`` seam (task 4.5).

Boundary: evaluation (Requirements 2, 10). Source of truth:
``.kiro/specs/execution-daemon/tasks.md`` task 4.5 / test 5.11 + the
``src/survival/types.py:OrderEvaluation`` docstring ("a cross-spec contract the
``execution-daemon`` must populate", reject-leaning by default).

What this module is
-------------------
A **pure projection** turning the three daemon-derived inputs the survival pure
core *cannot* itself derive into the single frozen ``survival.types.OrderEvaluation``
that ``gate.admit`` consumes. ``admit``'s lexicographic walk (``gate.py:497``)
reads exactly three fields off this object:

  * ``additional_used_margin`` — the order's projected margin delta, fed to
    ``check_margin_distance``;
  * ``in_universe`` — symbol ∈ S&P 500 ∩ Gate-441;
  * ``is_excluded`` — flagged by the consumed ex-ante (§12.6) catalyst/quality
    screen.

Deriving these needs broker / instrument / screen knowledge that is **out of the
survival spec's boundary** — so the survival pure walk takes the *results* in,
and the daemon owns producing them (Req 10.2/10.3 — the daemon consumes the
survival verdict, it never recomputes the survival walk; the projection is the
daemon's own input assembly, not a survival re-implementation).

Reject-leaning by construction (fail-toward-not-adding for opens)
-----------------------------------------------------------------
Every leg fails toward the value that **rejects** an open, so a missing /
unpopulated input can never read as "in-universe, not-excluded, zero-margin"
(the dangerous fail-open direction). The survival contract's bare
``OrderEvaluation()`` already rejects every open; this projection never produces
anything looser:

  * **margin (a).** ``additional_used_margin = volume × reference_price ×
    leverage`` — the projected margin delta. ``None`` (the unknown sentinel)
    whenever ``reference_price`` or ``leverage`` is genuinely unknown, or the
    product is non-finite — **never ``0.0``** (which would make
    ``projected == current`` and a margin-unknown order fail open; ``admit``
    rejects ``margin_distance`` on the ``None`` sentinel, ``gate.py:586``).
  * **universe (b).** ``in_universe = symbol ∈ universe`` — a v0.1 config
    allow-list (S&P 500 ∩ Gate-441). An empty / absent list → off-universe →
    reject ``universe``.
  * **exclusion (c).** ``is_excluded`` = the slow-layer §12.6 catalyst/quality
    screen result. v0.1 **fail-safe default**: an unknown screen result
    (``is_excluded`` omitted / ``None``) → ``True`` (excluded → reject
    ``entry_exclusion`` when exclusion is enabled). The live §12.6 screen wiring
    is a tracked follow-on; until then an order is admitted past this leg only
    when the daemon affirmatively passes ``is_excluded=False``.

v0.1 leverage / universe are **config-supplied** (broker instrument leverage; a
config allow-list) — threaded in by the orchestrator (task 4.1), not fetched
here, so this stays a pure, inner-ring-testable leaf.

Pure leaf (P1): stdlib + the single ``OrderEvaluation`` type import from
``src.survival.types`` (the type this populates) — no ``gate`` / ``params``
logic, no numpy, no MCP, no DB. Deterministic and isolatable (P14).
"""

from __future__ import annotations

import math
from typing import AbstractSet, Optional

# Import ONLY the type this projection populates — never gate/params logic
# (Req 10.2: the daemon consumes the survival verdict, it does not recompute the
# survival walk). The projection is the daemon's own input assembly.
from src.survival.types import OrderEvaluation


def _projected_margin_delta(
    *,
    volume: float,
    reference_price: Optional[float],
    leverage: Optional[float],
) -> Optional[float]:
    """The order's projected margin delta = ``volume × reference_price ×
    leverage`` (leg a), or ``None`` when it is genuinely unknown.

    Returns the ``None`` **unknown sentinel** (never ``0.0``) whenever a factor
    is missing or the product is non-finite / negative — so a margin that cannot
    be assessed makes ``admit`` reject ``margin_distance`` rather than fail open
    (``gate.py:586``: ``None`` rejects; ``0.0`` would make ``projected ==
    current``). A real open has a strictly-positive notional, so a finite
    positive product is the only value that flows through to the gate.
    """
    if reference_price is None or leverage is None:
        return None
    delta = volume * reference_price * leverage
    if not math.isfinite(delta) or delta <= 0.0:
        # A non-finite (NaN/inf) or non-positive product is not a usable margin
        # delta — fail toward unknown so the gate cannot read it as zero-margin.
        return None
    return delta


def build_order_evaluation(
    *,
    symbol: str,
    volume: float,
    reference_price: Optional[float],
    leverage: Optional[float],
    universe: AbstractSet[str],
    is_excluded: Optional[bool] = None,
) -> OrderEvaluation:
    """Project the three daemon-derived inputs into a ``survival.OrderEvaluation``.

    Pure + deterministic (P14): no I/O, reads only its arguments, and produces a
    reject-leaning ``OrderEvaluation`` so a missing / unknown input can never
    fail open (Req 2 / Req 10).

    Args:
        symbol: the order's symbol — checked for universe membership (leg b).
        volume: the order's volume — a factor of the projected margin delta.
        reference_price: the current reference price (the candidate's last close)
            — a factor of the margin delta; ``None`` ⇒ margin unknown ⇒ reject.
        leverage: the broker-instrument leverage (a v0.1 config value) — a factor
            of the margin delta; ``None`` ⇒ margin unknown ⇒ reject.
        universe: the v0.1 config allow-list (S&P 500 ∩ Gate-441). Membership
            sets ``in_universe``; a symbol outside it → reject ``universe``.
        is_excluded: the slow-layer §12.6 catalyst/quality screen result. ``True``
            = flagged (reject ``entry_exclusion``); ``False`` = affirmatively
            cleared; ``None`` (unknown / screen not yet wired) ⇒ **fail-safe
            excluded** (``True``) per the v0.1 default.

    Returns:
        A frozen ``OrderEvaluation`` with the three legs populated reject-leaning.
    """
    additional_used_margin = _projected_margin_delta(
        volume=volume,
        reference_price=reference_price,
        leverage=leverage,
    )

    in_universe = symbol in universe

    # Fail-safe: an unknown screen result (None) is treated as EXCLUDED — the
    # v0.1 default (unknown → excluded → reject) until the live §12.6 screen wiring
    # lands. Only an affirmative ``is_excluded=False`` clears this leg.
    excluded = True if is_excluded is None else is_excluded

    return OrderEvaluation(
        additional_used_margin=additional_used_margin,
        in_universe=in_universe,
        is_excluded=excluded,
    )


__all__ = ["build_order_evaluation"]
