"""v0.5 composable sizing formula (v3 spec §4.6 line 620).

The v0.1 sizing path (`src/p7_recommendation_emitter/sizing.py`) is mode-
static + 3 hard overlays (cash / drawdown / vol). At v0.5-active this
module replaces it with a 4-dimensional composable formula:

    initial_pct = base_band × (conviction^w_c) × (regime^w_r)
                              × (drawdown^w_d) × (cash^w_x)

where the weights w_* are exponents calibrated empirically once ≥3 months
of v0.1 recommendation+fill+outcome data accrue. At v0.5-entry all weights
default to 1.0 (geometric product). Recalibration via OLS regression of
T+90d alpha against per-dimension multipliers.

Public surface:
    CalibratedWeights — weights container; loaded from `parameters` table
                        at v0.5-active.
    composable_size   — the formula.
    recalibrate_weights — fit weights from recommendation_outcomes (deferred
                        until 3mo of data; raises NotEnoughDataError otherwise).
"""

from src.sizing.composable import (
    CalibratedWeights,
    NotEnoughDataError,
    SizingResult,
    composable_size,
    conviction_to_multiplier,
    recalibrate_weights,
)

__all__ = [
    "CalibratedWeights",
    "NotEnoughDataError",
    "SizingResult",
    "composable_size",
    "conviction_to_multiplier",
    "recalibrate_weights",
]
