"""WS-7 (Phase 3) foundational extension: liquidity + correlation sizing dims.

Confirms the two new CalibratedWeights dimensions are (a) backward-compatible
no-ops at default 1.0, (b) apply as pre-cash haircuts when < 1.0, and (c)
recalibrate correctly — legacy 4-dim sample sets leave the new dims at 1.0.
"""

from __future__ import annotations

import math

import pytest

from src.sizing.composable import (
    CalibratedWeights,
    NotEnoughDataError,
    RECALIBRATION_MIN_N,
    composable_size,
    recalibrate_weights,
)


def _base(**kw):
    return composable_size(mode="B", conviction="HIGH", **kw)


def test_default_dims_are_noop():
    # No liquidity/correlation supplied => identical to a call without them.
    out = _base()
    assert out.multipliers["liquidity"] == 1.0
    assert out.multipliers["correlation"] == 1.0
    # net_multiplier unaffected by the 1.0^w no-op dims.
    ref = composable_size(mode="B", conviction="HIGH")
    assert out.net_multiplier == ref.net_multiplier


def test_liquidity_haircut_reduces_size():
    full = _base()
    haircut = _base(liquidity_multiplier=0.5)
    assert haircut.initial_pct < full.initial_pct
    assert haircut.max_pct < full.max_pct
    assert haircut.multipliers["liquidity"] == 0.5
    # With weight 1.0 the haircut is exactly the multiplier ratio.
    assert haircut.net_multiplier == pytest.approx(full.net_multiplier * 0.5)


def test_correlation_haircut_reduces_size():
    full = _base()
    haircut = _base(correlation_multiplier=0.6)
    assert haircut.initial_pct < full.initial_pct
    assert haircut.multipliers["correlation"] == 0.6
    assert haircut.net_multiplier == pytest.approx(full.net_multiplier * 0.6)


def test_both_haircuts_compose_multiplicatively():
    out = _base(liquidity_multiplier=0.5, correlation_multiplier=0.5)
    ref = _base()
    assert out.net_multiplier == pytest.approx(ref.net_multiplier * 0.25)


def test_weight_exponent_applies_to_new_dims():
    w = CalibratedWeights(liquidity=2.0)
    out = composable_size(mode="B", conviction="HIGH", liquidity_multiplier=0.5, weights=w)
    ref = composable_size(mode="B", conviction="HIGH")
    # liquidity contributes 0.5**2.0 = 0.25.
    assert out.net_multiplier == pytest.approx(ref.net_multiplier * 0.25)


def test_as_dict_has_six_dims():
    d = CalibratedWeights().as_dict()
    assert set(d) == {"conviction", "regime", "drawdown", "cash", "liquidity", "correlation"}


def test_payload_multipliers_include_new_dims():
    payload = _base(liquidity_multiplier=0.8, correlation_multiplier=0.9).to_payload()
    assert payload["multipliers"]["liquidity"] == 0.8
    assert payload["multipliers"]["correlation"] == 0.9
    assert payload["weights"]["liquidity"] == 1.0
    assert payload["weights"]["correlation"] == 1.0


def test_recalibrate_legacy_4dim_samples_leave_new_dims_at_one():
    # Legacy samples carry only the original 4 multipliers => new dims no-op.
    samples = []
    for i in range(max(RECALIBRATION_MIN_N, 50)):
        samples.append(
            {
                "conviction_mult": 1.0,
                "regime_mult": 1.0,
                "drawdown_mult": 0.5 if i % 2 else 1.0,
                "cash_mult": 1.0,
                "delta_vs_benchmark_90d": 0.02 * (i % 3 - 1),
            }
        )
    w = recalibrate_weights(samples)
    assert w.liquidity == 1.0
    assert w.correlation == 1.0


def test_recalibrate_with_new_dims_fits_them():
    # liquidity_mult correlates with alpha => non-1.0 fitted weight.
    samples = []
    for i in range(60):
        liq = 0.5 if i % 2 else 1.0
        # Make tighter liquidity (0.5) co-occur with worse alpha (the haircut
        # "did its job") so the OLS slope on log(liq) is positive/non-trivial.
        alpha = -0.05 if liq == 0.5 else 0.05
        samples.append(
            {
                "conviction_mult": 1.0,
                "regime_mult": 1.0,
                "drawdown_mult": 1.0,
                "cash_mult": 1.0,
                "liquidity_mult": liq,
                "correlation_mult": 1.0,
                "delta_vs_benchmark_90d": alpha,
            }
        )
    w = recalibrate_weights(samples)
    assert w.liquidity != 1.0  # fitted, not the default
    assert 0.0 <= w.liquidity <= 3.0  # clamped range
    assert w.correlation == 1.0  # constant column => no signal => 1.0 guard


def test_recalibrate_still_strict_on_missing_required_dim():
    samples = [
        {"conviction_mult": 1.0, "regime_mult": 1.0, "drawdown_mult": 1.0,
         "delta_vs_benchmark_90d": 0.01}  # missing cash_mult (required)
        for _ in range(60)
    ]
    with pytest.raises(ValueError):
        recalibrate_weights(samples)
