"""Calibration scorer — canonical home of the Layer-1 verdict primitives.

WS-4 replaces the placeholder ``src/eval/scorer.py``. The four public symbols
``Label``, ``ScoreInput``, ``Verdict``, ``score`` now live HERE; ``src/eval/scorer.py``
is a thin compatibility shim that re-exports them so its sole importer
(``tests/unit/eval/test_scorer.py``) stays green without edit.

Semantics preserved from the placeholder (signature + shape; the hit/miss table
is still the spec's parenthetical default pending an operator ``/review-me``):

    BUY  hit  iff excess_return > +margin
    HOLD hit  iff |excess_return| < margin
    TRIM hit  iff excess_return < +margin
    SELL hit  iff excess_return < -margin

This module is the verdict primitive consumed by the outer-ring eval loop; the
probabilistic calibration metrics (Brier/log-loss/reliability) live in
``src.calibration.metrics`` and operate on the snapshotted continuous_score, a
separate concern from the discrete label verdict here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Label(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    TRIM = "TRIM"
    SELL = "SELL"


class Verdict(str, Enum):
    HIT = "hit"
    MISS = "miss"


@dataclass(frozen=True)
class ScoreInput:
    label: Label
    excess_return_pct: float
    margin_pct: float


def _is_hit(inp: ScoreInput) -> bool:
    er = inp.excess_return_pct
    m = inp.margin_pct
    if inp.label is Label.BUY:
        return er > +m
    if inp.label is Label.HOLD:
        return abs(er) < m
    if inp.label is Label.TRIM:
        return er < +m
    if inp.label is Label.SELL:
        return er < -m
    raise ValueError(f"unknown label: {inp.label}")


def score(inp: ScoreInput) -> Verdict:
    """Map a (label, excess_return, margin) input to a hit/miss verdict."""
    return Verdict.HIT if _is_hit(inp) else Verdict.MISS


__all__ = ["Label", "Verdict", "ScoreInput", "score"]
