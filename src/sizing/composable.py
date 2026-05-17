"""Composable sizing formula — v0.5 upgrade path (v3 spec §4.6).

The formula:

    initial_pct = base_band_initial × ∏ (multiplier_i ^ weight_i)
    max_pct     = base_band_max × ∏ (multiplier_i ^ weight_i_for_max)

Dimensions:
    conviction — HIGH/MEDIUM/LOW or continuous score in [0, 1]
    regime     — BB-pseudo-BMA+ output (S7) or v0.1 mode-static fallback
    drawdown   — same as v0.1: ×0.5 if portfolio underperforming benchmark
                 by mode-specific threshold, else ×1.0
    cash       — initial_pct ≤ available_cash_pct (fence, not multiplier-only)

Calibration:
    At v0.5-entry, all weights = 1.0 (pure geometric product). After 3mo
    of data accrue, `recalibrate_weights` fits weights via OLS regression
    of T+90d alpha against per-dimension multipliers, so positive-alpha
    correlation lifts the corresponding weight above 1.0.

Why exponents not coefficients:
    The v0.1 formulation uses multiplicative overlays. Keeping the v0.5
    upgrade multiplicative preserves the property that any single overlay
    saying "tighten to zero" actually drives sizing to zero. With additive
    coefficients a single tighten can't override a positive sum from other
    dimensions — wrong semantics for risk overlays.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional


# Conviction tier → base multiplier. Pre-calibration default; v0.5+
# recalibrates these against alpha realizations.
_CONVICTION_PRIOR_MULTIPLIER: dict[str, float] = {
    "HIGH": 1.0,
    "MEDIUM": 0.7,
    "LOW": 0.4,
}

# Mode → (initial_band, max_band) per v3 spec §4.6 PB#2 v0.1.
_BAND_BY_MODE: dict[str, tuple[float, float]] = {
    "B": (0.03, 0.08),
    "B_prime": (0.02, 0.05),
    "C": (0.01, 0.03),
}

# Drawdown thresholds per mode (vs benchmark, in pp).
_DRAWDOWN_THRESHOLD_PP: dict[str, float] = {
    "B": 5.0,
    "B_prime": 7.0,
    "C": 10.0,
}

# Floor for any individual multiplier (avoids 0^0 = 1 surprises and keeps
# the geometric product well-defined when a tighten goes to 0).
_MULT_FLOOR = 1e-6

# Minimum sample-count to attempt recalibration. Below this we keep
# uncalibrated weights = 1.0.
RECALIBRATION_MIN_N = 50


class NotEnoughDataError(RuntimeError):
    """Raised by recalibrate_weights when fewer than RECALIBRATION_MIN_N
    resolved outcomes are available."""


@dataclass(frozen=True)
class CalibratedWeights:
    """Exponents per dimension. Loaded from `parameters` table at v0.5-active.

    Defaults are 1.0 — the pure geometric product. Empirical recalibration
    pushes weights >1.0 for dimensions that correlate positively with
    alpha and <1.0 for dimensions that correlate negatively (or noise).
    """

    conviction: float = 1.0
    regime: float = 1.0
    drawdown: float = 1.0
    cash: float = 1.0

    def as_dict(self) -> dict[str, float]:
        return {
            "conviction": self.conviction,
            "regime": self.regime,
            "drawdown": self.drawdown,
            "cash": self.cash,
        }


@dataclass(frozen=True)
class SizingResult:
    """Composable sizing output. Mirrors v0.1 SizingSuggestion's payload
    surface so callers can swap it in."""

    initial_pct: float
    max_pct: float
    base_band: dict[str, float]
    multipliers: dict[str, float]      # per-dimension raw multiplier
    weights: dict[str, float]          # per-dimension exponent
    net_multiplier: float
    funding_required: bool

    def to_payload(self) -> dict:
        return {
            "initial_pct": round(self.initial_pct, 4),
            "max_pct": round(self.max_pct, 4),
            "base_band": self.base_band,
            "multipliers": {k: round(v, 4) for k, v in self.multipliers.items()},
            "weights": {k: round(v, 4) for k, v in self.weights.items()},
            "net_multiplier": round(self.net_multiplier, 4),
            "funding_required": self.funding_required,
            "formula_version": "v0.5_composable",
        }


# --------------------------------------------------------------------------- #
# Multiplier helpers                                                          #
# --------------------------------------------------------------------------- #


def conviction_to_multiplier(conviction: str | float) -> float:
    """Map conviction (tier or continuous score in [0,1]) to multiplier.

    Tier mapping mirrors v0.1's implicit conviction tier semantics:
        HIGH=1.0 / MEDIUM=0.7 / LOW=0.4

    Continuous scores [0,1] linearly map: 0.0 → 0.4 (LOW floor),
    1.0 → 1.0 (HIGH ceiling). The endpoints match the discrete map so the
    transition between v0.5 discrete-band and v0.6+ continuous score is
    smooth.
    """
    if isinstance(conviction, str):
        m = _CONVICTION_PRIOR_MULTIPLIER.get(conviction)
        if m is None:
            raise ValueError(f"unknown conviction tier: {conviction!r}")
        return m
    if isinstance(conviction, (int, float)):
        x = max(0.0, min(1.0, float(conviction)))
        return 0.4 + 0.6 * x  # 0 → 0.4, 1 → 1.0
    raise TypeError(f"conviction must be str or float, got {type(conviction)}")


def drawdown_multiplier(
    mode: str, portfolio_underperformance_pp: Optional[float]
) -> float:
    """v0.1's drawdown overlay, retained for v0.5: ×0.5 above mode threshold."""
    if portfolio_underperformance_pp is None:
        return 1.0
    threshold = _DRAWDOWN_THRESHOLD_PP.get(mode)
    if threshold is None:
        raise ValueError(f"unknown mode: {mode!r}")
    if portfolio_underperformance_pp > threshold:
        return 0.5
    return 1.0


def vol_regime_multiplier(s0_vol_z: Optional[float]) -> float:
    """v0.1's vol overlay, used as the default `regime` dimension when BB
    weights aren't available yet (S7 deferred until N≥30)."""
    if s0_vol_z is None or s0_vol_z <= 1.0:
        return 1.0
    return 0.7


# --------------------------------------------------------------------------- #
# Main entrypoint                                                             #
# --------------------------------------------------------------------------- #


def composable_size(
    *,
    mode: str,
    conviction: str | float,
    regime_multiplier: float = 1.0,
    portfolio_underperformance_pp: Optional[float] = None,
    s0_vol_z: Optional[float] = None,
    available_cash_pct: Optional[float] = None,
    weights: Optional[CalibratedWeights] = None,
) -> SizingResult:
    """Compute v0.5 composable sizing.

    Args:
        mode: 'B' / 'B_prime' / 'C'.
        conviction: 'HIGH'/'MEDIUM'/'LOW' or continuous in [0,1].
        regime_multiplier: BB-pseudo-BMA+ scalar in (0,1]. If unset (1.0),
            falls back to v0.1 vol-regime multiplier from `s0_vol_z`.
        portfolio_underperformance_pp: drawdown vs benchmark.
        s0_vol_z: only used if regime_multiplier == 1.0 (S7 not active yet).
        available_cash_pct: cap on initial_pct.
        weights: empirical exponents; default = 1.0 across the board.

    Returns:
        SizingResult.
    """
    if mode not in _BAND_BY_MODE:
        raise ValueError(f"unknown mode: {mode!r}")
    weights = weights or CalibratedWeights()

    initial_band, max_band = _BAND_BY_MODE[mode]

    conv_mult = conviction_to_multiplier(conviction)
    dd_mult = drawdown_multiplier(mode, portfolio_underperformance_pp)
    if regime_multiplier == 1.0 and s0_vol_z is not None:
        regime_mult = vol_regime_multiplier(s0_vol_z)
    else:
        regime_mult = regime_multiplier

    # Floor each multiplier so that a^w doesn't blow up.
    conv_mult = max(conv_mult, _MULT_FLOOR)
    regime_mult = max(regime_mult, _MULT_FLOOR)
    dd_mult = max(dd_mult, _MULT_FLOOR)

    # Cash applies as a fence on initial_pct; we represent it as a multiplier
    # that scales [0, 1] so it composes cleanly into net_multiplier.
    # If available_cash < target, cash_mult = available / target; else 1.0.
    pre_cash_initial = (
        initial_band
        * (conv_mult ** weights.conviction)
        * (regime_mult ** weights.regime)
        * (dd_mult ** weights.drawdown)
    )
    if available_cash_pct is None or available_cash_pct >= pre_cash_initial:
        cash_mult = 1.0
        funding_required = False
    elif pre_cash_initial > 0:
        cash_mult = available_cash_pct / pre_cash_initial
        funding_required = True
    else:
        cash_mult = 0.0
        funding_required = True
    cash_mult = max(cash_mult, _MULT_FLOOR)

    initial_pct = pre_cash_initial * (cash_mult ** weights.cash)

    # max_pct does NOT include cash overlay (max is the post-funding ceiling).
    max_pct = (
        max_band
        * (conv_mult ** weights.conviction)
        * (regime_mult ** weights.regime)
        * (dd_mult ** weights.drawdown)
    )

    net_multiplier = (
        (conv_mult ** weights.conviction)
        * (regime_mult ** weights.regime)
        * (dd_mult ** weights.drawdown)
        * (cash_mult ** weights.cash)
    )

    return SizingResult(
        initial_pct=initial_pct,
        max_pct=max_pct,
        base_band={"initial": initial_band, "max": max_band},
        multipliers={
            "conviction": conv_mult,
            "regime": regime_mult,
            "drawdown": dd_mult,
            "cash": cash_mult,
        },
        weights=weights.as_dict(),
        net_multiplier=net_multiplier,
        funding_required=funding_required,
    )


# --------------------------------------------------------------------------- #
# Recalibration (deferred until 3mo of data — N≥50)                           #
# --------------------------------------------------------------------------- #


def recalibrate_weights(samples: Iterable[dict]) -> CalibratedWeights:
    """Fit per-dimension exponents via log-linear OLS on T+90d alpha.

    Each sample dict must carry:
        conviction_mult / regime_mult / drawdown_mult / cash_mult
        delta_vs_benchmark_90d  (the realized T+90d alpha)

    The model:
        log(1 + alpha) = β0 + Σ w_i × log(multiplier_i)

    Multipliers in (0,1] map to log values in (-∞, 0]; positive correlation
    of a tighter multiplier with worse alpha → positive weight (the
    multiplier "did its job"). Weights below 0 are clamped to 0 since the
    composable formula cannot represent inverse-multiplication semantics.

    Args:
        samples: iterable of resolved-outcome rows.

    Returns:
        CalibratedWeights with empirically-fit exponents.

    Raises:
        NotEnoughDataError when fewer than RECALIBRATION_MIN_N samples.
    """
    sample_list = [s for s in samples]
    n = len(sample_list)
    if n < RECALIBRATION_MIN_N:
        raise NotEnoughDataError(
            f"{n} samples; recalibration needs ≥{RECALIBRATION_MIN_N}"
        )

    # Build matrices.
    # X is N×4 (one column per dimension; intercept handled separately).
    # y is the realized log-return.
    dims = ("conviction", "regime", "drawdown", "cash")
    X: list[list[float]] = []
    y: list[float] = []
    for s in sample_list:
        try:
            row = [math.log(max(s[f"{d}_mult"], _MULT_FLOOR)) for d in dims]
            alpha = s["delta_vs_benchmark_90d"]
        except KeyError as e:
            raise ValueError(f"sample missing key: {e}") from e
        if alpha is None:
            continue
        X.append(row)
        # log(1 + alpha) — guards against alpha <= -1 which is total wipeout
        y.append(math.log(max(1.0 + float(alpha), _MULT_FLOOR)))

    n = len(X)
    if n < RECALIBRATION_MIN_N:
        raise NotEnoughDataError(
            f"{n} usable samples; recalibration needs ≥{RECALIBRATION_MIN_N}"
        )

    # Demean for an intercept-free fit on column slopes.
    mean_X = [sum(col) / n for col in zip(*X)]
    mean_y = sum(y) / n
    Xc = [[x - m for x, m in zip(row, mean_X)] for row in X]
    yc = [yi - mean_y for yi in y]

    # Closed-form per-dim slope (univariate-OLS approximation; cheaper than
    # full multi-variate matrix inversion and adequate at the v0.5 sample-
    # size regime where the dimensions are largely independent.)
    weights = []
    for j in range(len(dims)):
        num = sum(Xc[i][j] * yc[i] for i in range(n))
        den = sum(Xc[i][j] ** 2 for i in range(n))
        slope = num / den if den > 1e-12 else 1.0
        # Clamp to [0, 3] — negative weights are nonsensical (would invert
        # the multiplier semantics); a single dimension shouldn't dominate
        # at >3× weight either.
        weights.append(max(0.0, min(3.0, slope)))

    return CalibratedWeights(
        conviction=weights[0],
        regime=weights[1],
        drawdown=weights[2],
        cash=weights[3],
    )
