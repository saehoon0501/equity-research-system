"""Forbes-Rigobon vol-conditional correlation correction.

Per v3 spec §4.1 method overlay #2: "MUST apply to dimension #6 to prevent
spurious correlation-regime triggers."

Forbes & Rigobon (2002) — "No contagion, only interdependence" — show that
naively comparing rolling correlations across periods of different volatility
*systematically* inflates the high-vol period's correlation. Their fix:

    rho_corrected = rho_observed * sqrt(
        (1 + delta_var) / (1 + delta_var * rho_observed^2)
    )

where `delta_var` is the proportional change in the conditioning variable's
variance between the high-vol regime and the low-vol baseline:

    delta_var = (var_high / var_low) - 1

If the high-vol-period variance is the same as the baseline, delta_var=0
and the correction is a no-op. The correction direction depends on which
side of the baseline the high-vol variance sits:

- var_high > var_low (delta_var > 0): observed rho was *biased down* during
  the high-vol period; correction *inflates* it back toward the true
  unconditional correlation. (This is the Forbes-Rigobon "no contagion,
  only interdependence" finding: spurious-decoupling claims in crisis
  periods often vanish under the correction.)
- var_high < var_low (delta_var < 0): observed rho was biased up; correction
  *shrinks* it toward zero.

Reference
---------
Forbes, K. and Rigobon, R. (2002). "No contagion, only interdependence:
Measuring stock market comovements." Journal of Finance 57, 2223-2261.
"""

from __future__ import annotations

import math


def vol_corrected_correlation(rho_observed: float, var_high: float, var_low: float) -> float:
    """Apply the Forbes-Rigobon vol-conditional correction.

    Args:
        rho_observed: observed (rolling-window) correlation in the high-vol
            period. Must lie in [-1, 1].
        var_high: variance of the conditioning variable in the high-vol
            period (e.g., S&P daily-return variance over the trailing
            window where we computed the rolling corr).
        var_low: variance of the conditioning variable in the low-vol
            baseline (e.g., long-run S&P daily-return variance — typically
            a 5y or full-history sample).

    Returns:
        Corrected correlation. Falls back to `rho_observed` if `var_low`
        is non-positive (cannot form `delta_var`).

    Edge cases:
        - var_low == 0 or NaN → returns rho_observed (degenerate baseline).
        - rho_observed magnitude > 1 → clipped to [-1, 1] before correcting.
        - corrected value is clipped to [-1, 1] (numerical bound).
    """
    if rho_observed is None or math.isnan(rho_observed):
        return float("nan")
    if var_low is None or var_low <= 0.0 or math.isnan(var_low):
        return rho_observed

    rho = max(-1.0, min(1.0, rho_observed))
    delta_var = (var_high / var_low) - 1.0

    denom = 1.0 + delta_var * (rho * rho)
    if denom <= 0.0:
        return rho

    factor = math.sqrt((1.0 + delta_var) / denom)
    corrected = rho * factor
    return max(-1.0, min(1.0, corrected))
