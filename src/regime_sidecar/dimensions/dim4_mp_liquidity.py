"""Dimension 4 — Monetary-policy / liquidity composite.

Per v3 spec §3.3 row 4 + §4.1. Composite of:

    WALCL       — Fed total assets (Fed balance sheet size)
    RESBALNS    — Reserve balances at Federal Reserve Banks
    RRPONTSYD   — Overnight Reverse Repo (drains liquidity)
    M2SL        — M2 monetary aggregate
    + Cboe Fed-Funds futures expected path (deferred to v0.5+; "actual −
      consensus" surprises overlay #3)

At v0.1, we compute a YoY% change z-score composite from the four FRED
series and classify:

    easy     → composite z-score > +0.5
    neutral  → -0.5 ≤ z-score ≤ +0.5
    tight    → composite z-score < -0.5

Composite = mean of:
    +1 × YoY% WALCL
    +1 × YoY% RESBALNS
    -1 × YoY% RRPONTSYD   (reverse-repo drains; sign-inverted)
    +1 × YoY% M2SL

…each individually z-scored over a 5-year rolling baseline. RRP is
sign-inverted because higher RRP means *less* liquidity in the system.

FF-futures-based surprise is a v0.5+ overlay; not computed here.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from src.regime_sidecar.bocpd import latest_signals
from src.regime_sidecar.fred_client import get_series
from src.regime_sidecar.types import DimensionResult


SERIES_WALCL = "WALCL"        # weekly
SERIES_RESBALNS = "RESBALNS"  # weekly
SERIES_RRPONTSYD = "RRPONTSYD"  # daily
SERIES_M2SL = "M2SL"          # monthly

# Series weights in composite (RRP is sign-flipped: higher RRP = less liquidity).
COMPOSITE_WEIGHTS: dict[str, float] = {
    "WALCL": 1.0,
    "RESBALNS": 1.0,
    "RRPONTSYD": -1.0,
    "M2SL": 1.0,
}

THRESHOLD_TIGHT_TO_NEUTRAL = -0.5
THRESHOLD_NEUTRAL_TO_EASY = 0.5

# 5-year baseline window for the rolling z-score.
ZSCORE_WINDOW_DAYS = 5 * 365


def _classify(z: float) -> str:
    if z < THRESHOLD_TIGHT_TO_NEUTRAL:
        return "tight"
    if z <= THRESHOLD_NEUTRAL_TO_EASY:
        return "neutral"
    return "easy"


def _to_series(observations: list[dict[str, Any]]) -> pd.Series:
    df = pd.DataFrame(observations)
    if df.empty:
        return pd.Series(dtype=float)
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna().sort_values("date")
    return pd.Series(df["value"].to_numpy(), index=df["date"])


def _yoy_pct_zscore(s: pd.Series) -> pd.Series:
    """YoY% change per observation, then rolling z-score over `ZSCORE_WINDOW_DAYS`.

    YoY: value_t / value_{t - ~365d} − 1, computed via reindex-and-shift over
    calendar days then resampled back to the original sample dates.
    """
    if s.empty:
        return s

    # Reindex to daily frequency for YoY shift.
    daily_idx = pd.date_range(start=s.index.min(), end=s.index.max(), freq="D")
    daily = s.reindex(daily_idx).ffill()
    yoy = daily / daily.shift(365) - 1.0

    # Rolling z-score on the daily-aligned YoY series.
    roll = yoy.rolling(ZSCORE_WINDOW_DAYS, min_periods=180)
    z = (yoy - roll.mean()) / roll.std(ddof=0)

    # Restrict back to the sample dates of the original series.
    return z.reindex(s.index).dropna()


def compute(asof_date: date, history_days: int = 365 * 6) -> DimensionResult:
    """Compute Dim 4 (MP/liquidity composite) for `asof_date`.

    Note: 6-year default lookback so the 5-year z-score window has data.
    """
    start = asof_date - timedelta(days=history_days)

    z_components: dict[str, pd.Series] = {}
    raw_components: dict[str, float | None] = {}
    warnings: list[str] = []

    for series_id, weight in COMPOSITE_WEIGHTS.items():
        obs = get_series(series_id, start=start, end=asof_date)
        s = _to_series(obs)
        if s.empty:
            warnings.append(f"{series_id}_empty")
            raw_components[series_id] = None
            continue
        raw_components[series_id] = float(s.iloc[-1])
        z = _yoy_pct_zscore(s)
        if z.empty:
            warnings.append(f"{series_id}_z_empty")
            continue
        z_components[series_id] = weight * z

    if not z_components:
        return DimensionResult(
            dimension_id=4,
            dimension_name="mp_liquidity",
            classification_date=asof_date,
            state_probabilities={"tight": 0.0, "neutral": 1.0, "easy": 0.0},
            headline_state="neutral",
            bocpd_change_probability=0.0,
            bocpd_short_run_mass=0.0,
            raw_inputs={"components": raw_components},
            history_length_days=0,
            validation_depth="MEDIUM (composite; FF-futures surprise deferred to v0.5+)",
            warnings=warnings,
        )

    # Align components on a common date index then mean.
    df_z = pd.concat(z_components, axis=1)
    composite = df_z.mean(axis=1, skipna=True).dropna()

    if composite.empty:
        latest_comp = float("nan")
        change_prob = 0.0
        short_run_mass = 0.0
        history_len = 0
        warnings.append("composite_empty")
    else:
        latest_comp = float(composite.iloc[-1])
        history_len = int(len(composite))
        change_prob, short_run_mass = latest_signals(composite.to_numpy())

    headline = _classify(latest_comp) if not np.isnan(latest_comp) else "neutral"
    state_probs = {"tight": 0.0, "neutral": 0.0, "easy": 0.0}
    state_probs[headline] = 1.0

    return DimensionResult(
        dimension_id=4,
        dimension_name="mp_liquidity",
        classification_date=asof_date,
        state_probabilities=state_probs,
        headline_state=headline,
        bocpd_change_probability=float(change_prob),
        bocpd_short_run_mass=float(short_run_mass),
        raw_inputs={
            "composite_z": None if np.isnan(latest_comp) else latest_comp,
            "components": raw_components,
            "weights": COMPOSITE_WEIGHTS,
            "thresholds": {
                "tight_to_neutral": THRESHOLD_TIGHT_TO_NEUTRAL,
                "neutral_to_easy": THRESHOLD_NEUTRAL_TO_EASY,
            },
            # Per v3 §4.1 method overlay #3: Cboe FF-futures surprise
            # (actual − expected ahead of FOMC) and FOMC-press-release tonal
            # surprise. Both deferred to v0.5+ — they require either Cboe
            # data subscription (FF futures) or NLP-on-press-release infra.
            "ff_futures_surprise_overlay": "deferred_to_v0.5",
            "surprise_overlay_status": "deferred_to_v0.5",
            "source": "FRED:WALCL, RESBALNS, RRPONTSYD, M2SL",
        },
        history_length_days=history_len,
        validation_depth="MEDIUM (composite; FF-futures surprise deferred to v0.5+)",
        warnings=warnings,
    )
