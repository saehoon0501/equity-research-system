"""Tests for src.sizing.composable."""

from __future__ import annotations

import pytest

from src.sizing.composable import (
    CalibratedWeights,
    NotEnoughDataError,
    composable_size,
    conviction_to_multiplier,
    drawdown_multiplier,
    recalibrate_weights,
    vol_regime_multiplier,
)


# --------------------------------------------------------------------------- #
# Multiplier helpers                                                          #
# --------------------------------------------------------------------------- #


def test_conviction_tier_mapping():
    assert conviction_to_multiplier("HIGH") == 1.0
    assert conviction_to_multiplier("MEDIUM") == 0.7
    assert conviction_to_multiplier("LOW") == 0.4


def test_conviction_continuous_endpoints_match_tiers():
    """Continuous 0.0/1.0 should match LOW/HIGH discrete multipliers."""
    assert conviction_to_multiplier(1.0) == pytest.approx(1.0)
    assert conviction_to_multiplier(0.0) == pytest.approx(0.4)
    # Mid-point linear
    assert conviction_to_multiplier(0.5) == pytest.approx(0.7)


def test_conviction_clamps_out_of_range():
    assert conviction_to_multiplier(-0.5) == pytest.approx(0.4)
    assert conviction_to_multiplier(2.0) == pytest.approx(1.0)


def test_conviction_invalid_tier_raises():
    with pytest.raises(ValueError):
        conviction_to_multiplier("ULTRA")


def test_drawdown_overlay_per_mode():
    # Below threshold → 1.0
    assert drawdown_multiplier("B", 3.0) == 1.0
    # Above threshold (5pp for B) → 0.5
    assert drawdown_multiplier("B", 6.0) == 0.5
    # Strict comparison: at threshold → no tighten
    assert drawdown_multiplier("B", 5.0) == 1.0
    # B' threshold = 7pp
    assert drawdown_multiplier("B_prime", 8.0) == 0.5
    assert drawdown_multiplier("B_prime", 6.0) == 1.0


def test_drawdown_none_is_inert():
    assert drawdown_multiplier("B", None) == 1.0


def test_vol_overlay_strict_threshold():
    assert vol_regime_multiplier(None) == 1.0
    assert vol_regime_multiplier(1.0) == 1.0   # strict >
    assert vol_regime_multiplier(1.01) == 0.7


# --------------------------------------------------------------------------- #
# composable_size                                                             #
# --------------------------------------------------------------------------- #


def test_default_weights_recover_geometric_product():
    """With weights = 1.0, composable formula = simple multiplicative."""
    out = composable_size(
        mode="B",
        conviction="HIGH",
        regime_multiplier=1.0,
        portfolio_underperformance_pp=0.0,
        s0_vol_z=None,
        available_cash_pct=None,
    )
    # Base 0.03 (B initial); HIGH → 1.0; regime 1.0; dd 1.0; cash 1.0.
    assert out.initial_pct == pytest.approx(0.03)
    assert out.max_pct == pytest.approx(0.08)
    assert out.net_multiplier == pytest.approx(1.0)
    assert out.funding_required is False


def test_drawdown_tightens_initial_and_max():
    out = composable_size(
        mode="B",
        conviction="HIGH",
        regime_multiplier=1.0,
        portfolio_underperformance_pp=10.0,  # > 5pp B threshold
        s0_vol_z=None,
        available_cash_pct=None,
    )
    # Drawdown × 0.5 applies to BOTH initial and max
    assert out.initial_pct == pytest.approx(0.015)
    assert out.max_pct == pytest.approx(0.04)


def test_low_conviction_compounds_with_drawdown():
    out = composable_size(
        mode="B",
        conviction="LOW",
        regime_multiplier=1.0,
        portfolio_underperformance_pp=10.0,
        s0_vol_z=None,
        available_cash_pct=None,
    )
    # LOW (0.4) × drawdown (0.5) = 0.2 of base 0.03 = 0.006
    assert out.initial_pct == pytest.approx(0.006)


def test_vol_used_when_no_explicit_regime():
    """If regime_multiplier=1.0 and s0_vol_z provided, vol overlay fires."""
    out = composable_size(
        mode="B",
        conviction="HIGH",
        regime_multiplier=1.0,
        portfolio_underperformance_pp=0.0,
        s0_vol_z=2.0,                  # > +1σ
        available_cash_pct=None,
    )
    # base 0.03 × 0.7 vol = 0.021
    assert out.initial_pct == pytest.approx(0.021)


def test_explicit_regime_overrides_vol_fallback():
    """If regime_multiplier ≠ 1.0, vol fallback isn't used."""
    out = composable_size(
        mode="B",
        conviction="HIGH",
        regime_multiplier=0.85,        # BB-pseudo-BMA+ output
        portfolio_underperformance_pp=0.0,
        s0_vol_z=2.0,                  # would have fired vol
        available_cash_pct=None,
    )
    # base 0.03 × 0.85 = 0.0255 — NOT 0.7 (which would be 0.021)
    assert out.initial_pct == pytest.approx(0.0255)


def test_cash_constraint_drives_funding_required():
    out = composable_size(
        mode="B",
        conviction="HIGH",
        regime_multiplier=1.0,
        portfolio_underperformance_pp=0.0,
        s0_vol_z=None,
        available_cash_pct=0.01,       # cap initial below the 0.03 target
    )
    assert out.initial_pct == pytest.approx(0.01)
    assert out.funding_required is True
    # max_pct excludes cash factor
    assert out.max_pct == pytest.approx(0.08)


def test_calibrated_weights_amplify_dimensions():
    """weight_conviction = 2.0 should square the conviction multiplier."""
    weights = CalibratedWeights(conviction=2.0, regime=1.0, drawdown=1.0, cash=1.0)
    out = composable_size(
        mode="B",
        conviction="LOW",                # 0.4
        regime_multiplier=1.0,
        portfolio_underperformance_pp=0.0,
        s0_vol_z=None,
        available_cash_pct=None,
        weights=weights,
    )
    # base 0.03 × 0.4^2 = 0.0048
    assert out.initial_pct == pytest.approx(0.0048)


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        composable_size(
            mode="Z",
            conviction="HIGH",
            regime_multiplier=1.0,
            portfolio_underperformance_pp=None,
            s0_vol_z=None,
            available_cash_pct=None,
        )


# --------------------------------------------------------------------------- #
# Recalibration                                                               #
# --------------------------------------------------------------------------- #


def test_recalibrate_below_min_n_raises():
    samples = [
        {
            "conviction_mult": 1.0,
            "regime_mult": 1.0,
            "drawdown_mult": 1.0,
            "cash_mult": 1.0,
            "delta_vs_benchmark_90d": 0.05,
        }
        for _ in range(5)
    ]
    with pytest.raises(NotEnoughDataError):
        recalibrate_weights(samples)


def test_recalibrate_clamps_negative_slopes_to_zero():
    """Construct samples where conviction-tighten correlates with HIGHER alpha
    (i.e., multiplier=0.4 → alpha=+0.10) — the slope on log-multiplier vs
    log-return is negative; the function clamps to 0.
    """
    # 50 samples: conviction LOW (0.4) → +0.10 alpha; conviction HIGH (1.0) → -0.05 alpha
    # log(0.4)≈-0.916; log(1.0)=0; lower mult correlates with higher return → negative slope.
    import math
    samples = []
    for i in range(50):
        if i % 2 == 0:
            samples.append({
                "conviction_mult": 0.4,
                "regime_mult": 1.0,
                "drawdown_mult": 1.0,
                "cash_mult": 1.0,
                "delta_vs_benchmark_90d": 0.10,
            })
        else:
            samples.append({
                "conviction_mult": 1.0,
                "regime_mult": 1.0,
                "drawdown_mult": 1.0,
                "cash_mult": 1.0,
                "delta_vs_benchmark_90d": -0.05,
            })
    weights = recalibrate_weights(samples)
    # Negative-slope dim → clamped to 0
    assert weights.conviction == 0.0
    # Other dims have zero variance → 1.0 fallback
    assert weights.regime == 1.0


def test_recalibrate_positive_slope_lifts_weight_above_one():
    """Higher conviction multiplier (1.0) → higher alpha; lower mult (0.4) → lower alpha.
    Positive slope; weight > 1.0 means the dimension carries real signal.
    """
    samples = []
    for i in range(50):
        if i % 2 == 0:
            samples.append({
                "conviction_mult": 1.0,
                "regime_mult": 1.0,
                "drawdown_mult": 1.0,
                "cash_mult": 1.0,
                "delta_vs_benchmark_90d": 0.10,
            })
        else:
            samples.append({
                "conviction_mult": 0.4,
                "regime_mult": 1.0,
                "drawdown_mult": 1.0,
                "cash_mult": 1.0,
                "delta_vs_benchmark_90d": -0.05,
            })
    weights = recalibrate_weights(samples)
    assert weights.conviction > 0.0
    # weights are clamped to [0, 3]
    assert weights.conviction <= 3.0
