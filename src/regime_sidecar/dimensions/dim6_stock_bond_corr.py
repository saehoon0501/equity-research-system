"""Dimension 6 — Stock-bond rolling correlation, Forbes-Rigobon corrected.

Per v3 spec §3.3 row 6 + §4.1 (overlay #2: Forbes-Rigobon vol-conditional
correction MUST apply to dim 6 to prevent spurious correlation-regime
triggers).

Computation:
    r_spx_t = log(SP500_t / SP500_{t-1})
    r_bnd_t = -ΔY10Y_t                 # canonical bond-return proxy in
                                       # Forbes-Rigobon literature: negative
                                       # first-difference of the 10y yield
                                       # (a yield increase ≈ a price decrease
                                       # at 10y duration). Replace with log
                                       # change in 10y total-return index
                                       # when available (deferred to v0.5+).
    rho_60d_t = corr(r_spx[t-59..t], r_bnd[t-59..t])

Forbes-Rigobon correction
-------------------------
    var_high = var(r_spx[t-59..t])              # current 60d window variance
    var_low  = var(r_spx[full sample available])  # long-run baseline variance
    delta_var = var_high / var_low - 1
    rho_corrected = rho_60d * sqrt((1 + delta_var) / (1 + delta_var * rho_60d^2))

State classification on the *corrected* rho:

    negative  → rho_corrected < -0.2     # classic "diversifier" regime
    neutral   → -0.2 ≤ rho_corrected ≤ +0.2
    positive  → rho_corrected > +0.2     # 60/40 breakdown regime (e.g. 2022)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from src.regime_sidecar.bocpd import latest_signals
from src.regime_sidecar.forbes_rigobon import vol_corrected_correlation
from src.regime_sidecar.fred_client import get_series
from src.regime_sidecar.types import DimensionResult


SERIES_SPX = "SP500"
SERIES_DGS10 = "DGS10"

CORR_WINDOW_DAYS = 60

THRESHOLD_NEG_TO_NEUTRAL = -0.2
THRESHOLD_NEUTRAL_TO_POS = 0.2


def _classify(rho: float) -> str:
    if rho < THRESHOLD_NEG_TO_NEUTRAL:
        return "negative"
    if rho <= THRESHOLD_NEUTRAL_TO_POS:
        return "neutral"
    return "positive"


def _to_series(observations: list[dict[str, Any]]) -> pd.Series:
    df = pd.DataFrame(observations)
    if df.empty:
        return pd.Series(dtype=float)
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna().sort_values("date")
    return pd.Series(df["value"].to_numpy(), index=df["date"])


def compute(asof_date: date, history_days: int = 365 * 2) -> DimensionResult:
    """Compute Dim 6 (stock-bond correlation, FR-corrected) for `asof_date`.

    Note: 2-year default lookback so we have a long-run baseline variance
    for the Forbes-Rigobon correction.
    """
    start = asof_date - timedelta(days=history_days)

    spx = _to_series(get_series(SERIES_SPX, start=start, end=asof_date))
    dgs10 = _to_series(get_series(SERIES_DGS10, start=start, end=asof_date))

    warnings: list[str] = []
    if spx.empty or dgs10.empty:
        warnings.append("dim6_series_empty")
        return DimensionResult(
            dimension_id=6,
            dimension_name="stock_bond_corr",
            classification_date=asof_date,
            state_probabilities={"negative": 0.0, "neutral": 1.0, "positive": 0.0},
            headline_state="neutral",
            bocpd_change_probability=0.0,
            bocpd_short_run_mass=0.0,
            raw_inputs={"rho_observed": None, "rho_corrected": None},
            history_length_days=0,
            validation_depth="HIGH (Forbes-Rigobon 2002 correction applied)",
            warnings=warnings,
        )

    # Inner-join SPX and DGS10 on common dates, compute log returns.
    df = pd.concat({"spx": spx, "y10": dgs10}, axis=1).dropna()
    df["r_spx"] = np.log(df["spx"]).diff()
    # Bond return proxy: -ΔY (negative first-difference of 10y yield). This
    # is the canonical proxy in Forbes-Rigobon contagion literature: yield
    # up → bond price down at non-trivial duration. The previous form
    # `-Δlog(y10)` (negative log-change of yield level) was incorrect — it
    # measures proportional yield change, not approximate price change.
    # Total-return-index version is deferred to v0.5+.
    df["r_bnd"] = -df["y10"].diff()
    df = df.dropna()

    if len(df) < CORR_WINDOW_DAYS + 5:
        warnings.append("dim6_insufficient_history")
        return DimensionResult(
            dimension_id=6,
            dimension_name="stock_bond_corr",
            classification_date=asof_date,
            state_probabilities={"negative": 0.0, "neutral": 1.0, "positive": 0.0},
            headline_state="neutral",
            bocpd_change_probability=0.0,
            bocpd_short_run_mass=0.0,
            raw_inputs={"rho_observed": None, "rho_corrected": None},
            history_length_days=int(len(df)),
            validation_depth="HIGH (Forbes-Rigobon 2002 correction applied)",
            warnings=warnings,
        )

    # Rolling 60-day correlation for BOCPD (full series of corrected rhos).
    rolling_corr = df["r_spx"].rolling(CORR_WINDOW_DAYS).corr(df["r_bnd"])

    # Long-run baseline variance for FR correction.
    var_low = float(df["r_spx"].var(ddof=0))

    corrected_series = []
    for i in range(len(df)):
        if i < CORR_WINDOW_DAYS - 1:
            corrected_series.append(np.nan)
            continue
        window = df["r_spx"].iloc[i - CORR_WINDOW_DAYS + 1 : i + 1]
        var_high = float(window.var(ddof=0))
        rho_obs = rolling_corr.iloc[i]
        if pd.isna(rho_obs):
            corrected_series.append(np.nan)
            continue
        rho_corr = vol_corrected_correlation(float(rho_obs), var_high, var_low)
        corrected_series.append(rho_corr)

    df["rho_corrected"] = corrected_series

    latest_rho_obs = float(rolling_corr.iloc[-1]) if not pd.isna(rolling_corr.iloc[-1]) else float("nan")
    latest_rho_corr = float(df["rho_corrected"].iloc[-1]) if not pd.isna(df["rho_corrected"].iloc[-1]) else float("nan")
    latest_var_high = float(df["r_spx"].iloc[-CORR_WINDOW_DAYS:].var(ddof=0))

    headline = _classify(latest_rho_corr) if not np.isnan(latest_rho_corr) else "neutral"
    state_probs = {"negative": 0.0, "neutral": 0.0, "positive": 0.0}
    state_probs[headline] = 1.0

    # BOCPD on the corrected-rho series (drop NaNs from warm-up).
    rho_clean = df["rho_corrected"].dropna().to_numpy()
    if rho_clean.size:
        change_prob, short_run_mass = latest_signals(rho_clean)
    else:
        change_prob, short_run_mass = 0.0, 0.0

    return DimensionResult(
        dimension_id=6,
        dimension_name="stock_bond_corr",
        classification_date=asof_date,
        state_probabilities=state_probs,
        headline_state=headline,
        bocpd_change_probability=float(change_prob),
        bocpd_short_run_mass=float(short_run_mass),
        raw_inputs={
            "rho_observed_60d": None if np.isnan(latest_rho_obs) else latest_rho_obs,
            "rho_corrected_60d": None if np.isnan(latest_rho_corr) else latest_rho_corr,
            "var_high_60d_spx": latest_var_high,
            "var_low_baseline_spx": var_low,
            "thresholds": {
                "neg_to_neutral": THRESHOLD_NEG_TO_NEUTRAL,
                "neutral_to_pos": THRESHOLD_NEUTRAL_TO_POS,
            },
            "source": "FRED:SP500, FRED:DGS10 (10y yield → bond return proxy)",
        },
        history_length_days=int(len(df)),
        validation_depth="HIGH (Forbes-Rigobon 2002 correction applied)",
        warnings=warnings,
    )
