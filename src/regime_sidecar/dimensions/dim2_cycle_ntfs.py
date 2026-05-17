"""Dimension 2 — Cycle slope (DGS2 − DGS3MO).

Per v3 spec §3.3 row 2 + §4.1. The published edge form is the
Engstrom-Sharpe (2018) Near-Term Forward Spread (NTFS), which dominates
the 10y-3mo slope in recession-nowcast tests. NTFS is defined as

    NTFS = (6-quarter-ahead implied 3-month rate) − (current 3-month spot)

…and requires zero-coupon Treasury yields (Gürkaynak-Sack-Wright series
THREEFY1, THREEFY2, …) or the neartermforwardspread.com CSV.

v0.1 implementation
-------------------
Ships the CMT slope (DGS2 − DGS3MO) and is named `cycle_2y3m_slope` so we
do NOT claim Engstrom-Sharpe edge. The GSW NTFS wiring is deferred to
v0.5+ (see BUILD_LOG / spec section 4.1 dim #2 for the deferral note).

State classification (v3 §4.1) on the 2y-3mo slope:
    expansion   → slope > 0.5
    late_cycle  → -0.5 < slope ≤ 0.5
    recession   → slope ≤ -0.5

Cutoffs are tunable via `parameters` (key: `regime.dim2_cycle_2y3m_slope.thresholds`).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from src.regime_sidecar.bocpd import latest_signals
from src.regime_sidecar.fred_client import get_series
from src.regime_sidecar.types import DimensionResult


# FRED CMT series.
SERIES_DGS2 = "DGS2"        # 2-year constant-maturity Treasury yield.
SERIES_DGS3MO = "DGS3MO"    # 3-month constant-maturity Treasury yield.

THRESHOLD_RECESSION_TO_LATE = -0.5
THRESHOLD_LATE_TO_EXPANSION = 0.5


def _classify(ntfs: float) -> str:
    if ntfs <= THRESHOLD_RECESSION_TO_LATE:
        return "recession"
    if ntfs <= THRESHOLD_LATE_TO_EXPANSION:
        return "late_cycle"
    return "expansion"


def _to_df(observations: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(observations)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def compute(asof_date: date, history_days: int = 365) -> DimensionResult:
    """Compute Dim 2 (DGS2-DGS3MO cycle slope) for `asof_date`.

    Returns a `DimensionResult` with:
      - dimension_name = "cycle_2y3m_slope" (NOT "cycle_ntfs"; we do not
        claim Engstrom-Sharpe edge under a CMT proxy).
      - raw_inputs.surprise_overlay_status = "deferred_to_v0.5" (per v3
        §4.1 method overlay #3).
      - raw_inputs.engstrom_sharpe_ntfs_status = "deferred_to_v0.5" (GSW
        THREEFY1/THREEFY2 wiring or neartermforwardspread.com CSV).
    """
    start = asof_date - timedelta(days=history_days)

    df_2y = _to_df(get_series(SERIES_DGS2, start=start, end=asof_date))
    df_3m = _to_df(get_series(SERIES_DGS3MO, start=start, end=asof_date))

    warnings: list[str] = []
    if df_2y.empty or df_3m.empty:
        warnings.append("cycle_slope_series_empty")
        return DimensionResult(
            dimension_id=2,
            dimension_name="cycle_2y3m_slope",
            classification_date=asof_date,
            state_probabilities={"expansion": 0.0, "late_cycle": 1.0, "recession": 0.0},
            headline_state="late_cycle",
            bocpd_change_probability=0.0,
            bocpd_short_run_mass=0.0,
            raw_inputs={
                "dgs2": None,
                "dgs3mo": None,
                "slope_2y3m_pct": None,
                "engstrom_sharpe_ntfs_status": "deferred_to_v0.5",
                "surprise_overlay_status": "deferred_to_v0.5",
            },
            history_length_days=0,
            validation_depth="MEDIUM (2y-3mo CMT slope; Engstrom-Sharpe NTFS deferred)",
            warnings=warnings,
        )

    merged = pd.merge(
        df_2y[["date", "value"]].rename(columns={"value": "dgs2"}),
        df_3m[["date", "value"]].rename(columns={"value": "dgs3mo"}),
        on="date",
        how="inner",
    ).dropna()
    merged["slope"] = merged["dgs2"] - merged["dgs3mo"]

    if merged.empty:
        warnings.append("cycle_slope_inner_join_empty")
        latest_slope = float("nan")
        change_prob = 0.0
        short_run_mass = 0.0
        history_len = 0
    else:
        latest_slope = float(merged["slope"].iloc[-1])
        history_len = int(len(merged))
        change_prob, short_run_mass = latest_signals(merged["slope"].to_numpy())

    headline = _classify(latest_slope) if not np.isnan(latest_slope) else "late_cycle"
    state_probs = {"expansion": 0.0, "late_cycle": 0.0, "recession": 0.0}
    state_probs[headline] = 1.0

    return DimensionResult(
        dimension_id=2,
        dimension_name="cycle_2y3m_slope",
        classification_date=asof_date,
        state_probabilities=state_probs,
        headline_state=headline,
        bocpd_change_probability=float(change_prob),
        bocpd_short_run_mass=float(short_run_mass),
        raw_inputs={
            "dgs2_pct": None if merged.empty else float(merged["dgs2"].iloc[-1]),
            "dgs3mo_pct": None if merged.empty else float(merged["dgs3mo"].iloc[-1]),
            "slope_2y3m_pct": None if np.isnan(latest_slope) else latest_slope,
            "thresholds": {
                "recession_to_late": THRESHOLD_RECESSION_TO_LATE,
                "late_to_expansion": THRESHOLD_LATE_TO_EXPANSION,
            },
            "source": "FRED:DGS2 − FRED:DGS3MO (2y-3mo CMT slope)",
            # Deferred per v3 §4.1: full Engstrom-Sharpe NTFS (GSW
            # zero-coupon-derived 6q-ahead 3mo forward) is the higher-edge
            # form. Wiring the GSW series is a v0.5+ task.
            "engstrom_sharpe_ntfs_status": "deferred_to_v0.5",
            # Deferred per v3 §4.1 method overlay #3: surprises (actual −
            # consensus) for cycle-related macro releases (e.g., NFP, CPI)
            # are not yet wired into this dimension.
            "surprise_overlay_status": "deferred_to_v0.5",
        },
        history_length_days=history_len,
        validation_depth="MEDIUM (2y-3mo CMT slope; Engstrom-Sharpe NTFS deferred)",
        warnings=warnings,
    )
