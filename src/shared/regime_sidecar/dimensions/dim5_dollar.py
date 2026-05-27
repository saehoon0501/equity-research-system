"""Dimension 5 — Trade-Weighted Broad Dollar.

Per v3 spec §3.3 row 5 + §4.1. Source: FRED `DTWEXBGS` (Nominal Broad
U.S. Dollar Index, daily). Returns the level + 60-trading-day trend
(percent-change over 60 trading days) and a tri-state classification:

    strong   → 60d % change > +2%
    neutral  → -2% ≤ 60d % change ≤ +2%
    weak     → 60d % change < -2%

Cutoffs are tunable via `parameters` (key: `regime.dim5_dollar.thresholds`).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from src.shared.regime_sidecar.bocpd import latest_signals
from src.shared.regime_sidecar.fred_client import get_series
from src.shared.regime_sidecar.types import DimensionResult


SERIES_DTWEXBGS = "DTWEXBGS"
TREND_WINDOW_DAYS = 60

THRESHOLD_WEAK_TO_NEUTRAL = -0.02
THRESHOLD_NEUTRAL_TO_STRONG = 0.02


def _classify(trend_pct: float) -> str:
    if trend_pct < THRESHOLD_WEAK_TO_NEUTRAL:
        return "weak"
    if trend_pct <= THRESHOLD_NEUTRAL_TO_STRONG:
        return "neutral"
    return "strong"


def _to_df(observations: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(observations)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)


def compute(asof_date: date, history_days: int = 365) -> DimensionResult:
    """Compute Dim 5 (Trade-Weighted Broad Dollar) for `asof_date`."""
    start = asof_date - timedelta(days=history_days)
    df = _to_df(get_series(SERIES_DTWEXBGS, start=start, end=asof_date))

    warnings: list[str] = []
    if df.empty:
        warnings.append("dtwexbgs_empty")
        return DimensionResult(
            dimension_id=5,
            dimension_name="dollar_dtwexbgs",
            classification_date=asof_date,
            state_probabilities={"strong": 0.0, "neutral": 1.0, "weak": 0.0},
            headline_state="neutral",
            bocpd_change_probability=0.0,
            bocpd_short_run_mass=0.0,
            raw_inputs={"level": None, "trend_60d_pct": None},
            history_length_days=0,
            validation_depth="HIGH (FRED canonical broad dollar index)",
            warnings=warnings,
        )

    level = float(df["value"].iloc[-1])
    if len(df) > TREND_WINDOW_DAYS:
        prior = float(df["value"].iloc[-1 - TREND_WINDOW_DAYS])
        trend_pct = (level / prior) - 1.0 if prior > 0 else 0.0
    else:
        prior = float(df["value"].iloc[0])
        trend_pct = (level / prior) - 1.0 if prior > 0 else 0.0
        warnings.append("trend_window_truncated")

    history_len = int(len(df))
    change_prob, short_run_mass = latest_signals(df["value"].to_numpy())

    headline = _classify(trend_pct)
    state_probs = {"strong": 0.0, "neutral": 0.0, "weak": 0.0}
    state_probs[headline] = 1.0

    return DimensionResult(
        dimension_id=5,
        dimension_name="dollar_dtwexbgs",
        classification_date=asof_date,
        state_probabilities=state_probs,
        headline_state=headline,
        bocpd_change_probability=float(change_prob),
        bocpd_short_run_mass=float(short_run_mass),
        raw_inputs={
            "level": level,
            "level_60d_ago": prior,
            "trend_60d_pct": trend_pct,
            "thresholds": {
                "weak_to_neutral": THRESHOLD_WEAK_TO_NEUTRAL,
                "neutral_to_strong": THRESHOLD_NEUTRAL_TO_STRONG,
            },
            "source": "FRED:DTWEXBGS",
        },
        history_length_days=history_len,
        validation_depth="HIGH (FRED canonical broad dollar index)",
        warnings=warnings,
    )
