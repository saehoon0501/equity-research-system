"""Calibration package — Brier scoring + believability tracking + haircut.

Per v3 spec §6.4 + §8.1, v0.5-active applies:
    * Brier-haircut on conviction
    * Believability-weighted Issue Log

Both consume `recommendation_outcomes` joined to source artifacts:
    Brier-haircut       → execution_recommendations.conviction
    Believability       → debate_consensus_history.per_style_outputs

At v0.1 the calculations run in shadow mode (recorded, no behavior change);
phase_detector flips them to live at v0.5-active.

Public surface:
    score_brier(conn, *, scope, as_of) → list[BrierCell]
    apply_haircut(conviction, brier) → adjusted_conviction
"""

from src.calibration.brier import (
    BrierCell,
    BrierScope,
    apply_haircut,
    score_brier,
)

__all__ = [
    "BrierCell",
    "BrierScope",
    "apply_haircut",
    "score_brier",
]
