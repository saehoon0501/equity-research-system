"""Layer 1 — pure-function scorer for the outer-ring Eval loop.

Maps (label, excess_return, margin) -> hit / miss. No I/O, no clock, no DB.

WARNING: PLACEHOLDER RULE TABLE — DO NOT USE FOR PRODUCTION CALIBRATION.

The hit/miss semantics in `_placeholder_hit` are reasonable defaults
per the spec's parenthetical guesses (sec 5.2) but are NOT operator-approved.
The real rule table comes from a `/review-me` resolution. Until that lands,
this module produces verdicts only well enough to satisfy signature tests.

Per docs/superpowers/specs/2026-05-23-ring-architecture-and-layer1-scaffold-design.md sec 5.
"""

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


def _placeholder_hit(inp: ScoreInput) -> bool:
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
    return Verdict.HIT if _placeholder_hit(inp) else Verdict.MISS
