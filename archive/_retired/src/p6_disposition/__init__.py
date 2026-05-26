"""p6_disposition — pure-derivation step between P5 and P7.

Per v3 spec Section 2.1 funnel composition: P6 derives the per-name
disposition (mode + horizon + per-horizon signal + suggested pacing) from
the P5 watchlist row + P4 PMSupervisor verdict + current portfolio state.

P6 is pure derivation — no LLM calls, no DB writes. Output feeds P7
(execution recommendation emitter) which then writes the operator-facing
``execution_recommendations`` row.

Reference:
  docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 2.1 (funnel composition; P6 disposition determination)
    Section 4.6 Q2 (multi-horizon disposition view; mode-anchored
                    primary horizon: B=Long / B'=Mid / C=Short)
"""

from __future__ import annotations

from src.p6_disposition.determiner import (
    DispositionDecision,
    DispositionInput,
    HORIZON_LONG,
    HORIZON_MID,
    HORIZON_SHORT,
    MODE_PRIMARY_HORIZON,
    determine_disposition,
)

__all__ = [
    "DispositionDecision",
    "DispositionInput",
    "HORIZON_LONG",
    "HORIZON_MID",
    "HORIZON_SHORT",
    "MODE_PRIMARY_HORIZON",
    "determine_disposition",
]
