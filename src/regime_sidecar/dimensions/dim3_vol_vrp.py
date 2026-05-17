"""Dimension 3 — Variance Risk Premium (VRP).

Per v3 spec §3.3 row 3 + §4.1 (Bollerslev-Tauchen-Zhou 2009: VRP forecasts
returns 1-3 months out; "VIX² − realized variance").

Implementation:

    VRP_t = (VIX_t / 100) ** 2  −  RV_t

where RV_t is the trailing 22-day annualized realized variance of S&P 500
log returns:

    RV_t = 252 * (1/22) * Σ_{i=t-21..t} r_i²

Both are unitless variance. Convention scales: VIX is published as percent
points of annualized vol → divide by 100 then square to get annualized
variance. Realized variance is computed on daily returns then annualized
by 252.

State classification (v3 §4.1):
    benign    → VRP ≤ 0          (RV exceeds implied — fearful but realized
                                  is the actual; positive risk to upside)
    normal    → 0 < VRP < 0.01
    elevated  → 0.01 ≤ VRP < 0.03
    crisis    → VRP ≥ 0.03

Sources:
    VIX  → FRED 'VIXCLS'
    SPY  → FRED 'SP500' (S&P 500 close)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from src.regime_sidecar.bocpd import latest_signals
from src.regime_sidecar.fred_client import get_series
from src.regime_sidecar.types import DimensionResult


SERIES_VIX = "VIXCLS"
SERIES_SPX = "SP500"

REALIZED_WINDOW_DAYS = 22
TRADING_DAYS_YEAR = 252

THRESHOLD_NEG_TO_NORMAL = 0.0
THRESHOLD_NORMAL_TO_ELEVATED = 0.01
THRESHOLD_ELEVATED_TO_CRISIS = 0.03


def _classify(vrp: float) -> str:
    if vrp <= THRESHOLD_NEG_TO_NORMAL:
        return "benign"
    if vrp < THRESHOLD_NORMAL_TO_ELEVATED:
        return "normal"
    if vrp < THRESHOLD_ELEVATED_TO_CRISIS:
        return "elevated"
    return "crisis"


def _to_df(observations: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(observations)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def compute(asof_date: date, history_days: int = 365) -> DimensionResult:
    """Compute Dim 3 (Variance Risk Premium) for `asof_date`."""
    start = asof_date - timedelta(days=history_days)

    df_vix = _to_df(get_series(SERIES_VIX, start=start, end=asof_date))
    df_spx = _to_df(get_series(SERIES_SPX, start=start, end=asof_date))

    warnings: list[str] = []
    if df_vix.empty or df_spx.empty:
        warnings.append("vrp_series_empty")
        return DimensionResult(
            dimension_id=3,
            dimension_name="vol_vrp",
            classification_date=asof_date,
            state_probabilities={
                "benign": 0.0,
                "normal": 1.0,
                "elevated": 0.0,
                "crisis": 0.0,
            },
            headline_state="normal",
            bocpd_change_probability=0.0,
            bocpd_short_run_mass=0.0,
            raw_inputs={"vix": None, "rv": None, "vrp": None},
            history_length_days=0,
            validation_depth="HIGH (Bollerslev-Tauchen-Zhou 2009)",
            warnings=warnings,
        )

    # Realized variance = annualized rolling variance of daily log returns.
    spx = df_spx.dropna(subset=["value"]).copy()
    spx["logret"] = np.log(spx["value"]).diff()
    spx["rv_22d"] = (
        spx["logret"].pow(2).rolling(REALIZED_WINDOW_DAYS).sum() * (TRADING_DAYS_YEAR / REALIZED_WINDOW_DAYS)
    )

    # VIX → annualized variance.
    vix = df_vix.dropna(subset=["value"]).copy()
    vix["vix_var"] = (vix["value"] / 100.0) ** 2

    merged = pd.merge(
        spx[["date", "rv_22d"]],
        vix[["date", "vix_var", "value"]].rename(columns={"value": "vix"}),
        on="date",
        how="inner",
    ).dropna(subset=["rv_22d", "vix_var"])

    merged["vrp"] = merged["vix_var"] - merged["rv_22d"]

    if merged.empty:
        warnings.append("vrp_merge_empty")
        latest_vrp = float("nan")
        latest_vix = None
        latest_rv = None
        change_prob = 0.0
        short_run_mass = 0.0
        history_len = 0
    else:
        latest_vrp = float(merged["vrp"].iloc[-1])
        latest_vix = float(merged["vix"].iloc[-1])
        latest_rv = float(merged["rv_22d"].iloc[-1])
        history_len = int(len(merged))
        change_prob, short_run_mass = latest_signals(merged["vrp"].to_numpy())

    headline = _classify(latest_vrp) if not np.isnan(latest_vrp) else "normal"
    state_probs = {"benign": 0.0, "normal": 0.0, "elevated": 0.0, "crisis": 0.0}
    state_probs[headline] = 1.0

    return DimensionResult(
        dimension_id=3,
        dimension_name="vol_vrp",
        classification_date=asof_date,
        state_probabilities=state_probs,
        headline_state=headline,
        bocpd_change_probability=float(change_prob),
        bocpd_short_run_mass=float(short_run_mass),
        raw_inputs={
            "vix": latest_vix,
            "vix_squared": (latest_vix / 100.0) ** 2 if latest_vix is not None else None,
            "realized_variance_22d_annualized": latest_rv,
            "vrp": None if np.isnan(latest_vrp) else latest_vrp,
            "thresholds": {
                "neg_to_normal": THRESHOLD_NEG_TO_NORMAL,
                "normal_to_elevated": THRESHOLD_NORMAL_TO_ELEVATED,
                "elevated_to_crisis": THRESHOLD_ELEVATED_TO_CRISIS,
            },
            "source": "FRED:VIXCLS, FRED:SP500",
        },
        history_length_days=history_len,
        validation_depth="HIGH (Bollerslev-Tauchen-Zhou 2009)",
        warnings=warnings,
    )
