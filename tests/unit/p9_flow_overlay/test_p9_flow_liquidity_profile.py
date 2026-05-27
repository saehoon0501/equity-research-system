"""Tests for WS-7.1 liquidity-profile + sizing-haircut module.

Pure / offline: every input is a fixture; no network, no live ADV fetch.
"""
from __future__ import annotations

import math

import pytest

from src.p9_flow_overlay.liquidity_profile import (
    LiquidityInputs,
    LiquidityProfile,
    compute_notional_adv_30d,
    liquidity_profile,
    liquidity_haircut_multiplier,
    _dtl_multiplier,
    _market_cap_multiplier,
    _spread_multiplier,
)
from src.sizing.composable import composable_size


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


def _liquid_large_cap() -> LiquidityInputs:
    """A $1M position in a mega-cap: ADV $5B, tight spread, $2T cap.
    DTL = 1e6 / (5e9 × 0.2) = 0.001 days → no haircut on any dimension."""
    return LiquidityInputs(
        position_notional=1_000_000.0,
        notional_adv_30d=5_000_000_000.0,
        bid_ask_spread_bps=2.0,
        market_cap=2_000_000_000_000.0,
    )


def _illiquid_thin() -> LiquidityInputs:
    """A $5M position in a micro-cap: ADV $1M, wide spread, $150M cap.
    DTL = 5e6 / (1e6 × 0.2) = 25 days → heavy haircut."""
    return LiquidityInputs(
        position_notional=5_000_000.0,
        notional_adv_30d=1_000_000.0,
        bid_ask_spread_bps=150.0,
        market_cap=150_000_000.0,
    )


# --------------------------------------------------------------------------- #
# compute_notional_adv_30d (reused gex_aggregator ADV definition)             #
# --------------------------------------------------------------------------- #


def test_compute_notional_adv_avg_shares_times_avg_close():
    # avg shares = 100, avg close = 10 → notional ADV = 1000.
    adv = compute_notional_adv_30d([90, 100, 110], [9.0, 10.0, 11.0])
    assert adv == pytest.approx(100.0 * 10.0)


def test_compute_notional_adv_empty_series_returns_none():
    assert compute_notional_adv_30d([], [10.0]) is None
    assert compute_notional_adv_30d([100], []) is None


def test_compute_notional_adv_nonpositive_returns_none():
    assert compute_notional_adv_30d([0, 0], [0.0, 0.0]) is None


def test_profile_derives_adv_from_raw_series_when_not_supplied():
    inp = LiquidityInputs(
        position_notional=1_000.0,
        shares_volume_30d=[100, 100],
        adj_close_30d=[10.0, 10.0],
    )
    prof = liquidity_profile(inp)
    assert prof.notional_adv_30d == pytest.approx(1_000.0)


# --------------------------------------------------------------------------- #
# liquidity_profile                                                           #
# --------------------------------------------------------------------------- #


def test_profile_days_to_liquidate_math():
    prof = liquidity_profile(_illiquid_thin())
    # 5e6 / (1e6 × 0.2) = 25
    assert prof.days_to_liquidate == pytest.approx(25.0)


def test_profile_options_leg_uses_contract_multiplier():
    # 10 contracts × 100 (CONTRACT_MULTIPLIER) × $50 = $50,000 added notional.
    inp = LiquidityInputs(
        position_notional=0.0,
        notional_adv_30d=1_000_000_000.0,
        option_contracts=10,
        option_underlying_price=50.0,
    )
    prof = liquidity_profile(inp)
    assert prof.effective_notional == pytest.approx(50_000.0)


def test_profile_requires_inputs_or_fetcher():
    with pytest.raises(ValueError):
        liquidity_profile()


def test_profile_fetcher_seam_is_injectable_and_offline():
    captured = {}

    def fake_fetcher(ticker: str) -> LiquidityInputs:
        captured["ticker"] = ticker
        return _liquid_large_cap()

    prof = liquidity_profile(ticker="AAPL", fetcher=fake_fetcher)
    assert captured["ticker"] == "AAPL"
    assert isinstance(prof, LiquidityProfile)


# --------------------------------------------------------------------------- #
# liquidity_haircut_multiplier — acceptance                                   #
# --------------------------------------------------------------------------- #


def test_liquid_large_cap_multiplier_is_exactly_one():
    prof = liquidity_profile(_liquid_large_cap())
    assert liquidity_haircut_multiplier(prof) == 1.0


def test_illiquid_thin_multiplier_below_one():
    prof = liquidity_profile(_illiquid_thin())
    assert liquidity_haircut_multiplier(prof) < 1.0


def test_multiplier_always_in_open_zero_one_interval():
    for inp in (_liquid_large_cap(), _illiquid_thin()):
        m = liquidity_haircut_multiplier(liquidity_profile(inp))
        assert 0.0 < m <= 1.0


def test_multiplier_monotone_thinner_means_smaller():
    """Holding everything else fixed, larger position (thinner relative
    liquidity / larger DTL) => strictly smaller multiplier."""
    base = dict(
        notional_adv_30d=10_000_000.0,
        bid_ask_spread_bps=2.0,
        market_cap=2_000_000_000_000.0,
    )
    sizes = [1_000_000.0, 5_000_000.0, 20_000_000.0, 60_000_000.0]
    mults = [
        liquidity_haircut_multiplier(
            liquidity_profile(LiquidityInputs(position_notional=s, **base))
        )
        for s in sizes
    ]
    # Non-increasing, and strictly decreasing across the haircut range.
    for a, b in zip(mults, mults[1:]):
        assert b <= a
    assert mults[-1] < mults[0]


def test_multiplier_never_exceeds_one_even_with_no_data():
    # No ADV, no spread, no cap → all dimensions no-op → exactly 1.0, not >1.
    inp = LiquidityInputs(position_notional=1_000_000.0)
    m = liquidity_haircut_multiplier(liquidity_profile(inp))
    assert m == 1.0


def test_wide_spread_alone_haircuts():
    inp = LiquidityInputs(
        position_notional=1_000.0,
        notional_adv_30d=1_000_000_000.0,  # DTL ~0
        bid_ask_spread_bps=200.0,          # very wide
        market_cap=2_000_000_000_000.0,    # mega
    )
    m = liquidity_haircut_multiplier(liquidity_profile(inp))
    assert m < 1.0


def test_micro_cap_alone_haircuts():
    inp = LiquidityInputs(
        position_notional=1_000.0,
        notional_adv_30d=1_000_000_000.0,
        bid_ask_spread_bps=2.0,
        market_cap=150_000_000.0,          # micro/nano
    )
    m = liquidity_haircut_multiplier(liquidity_profile(inp))
    assert m < 1.0


# --------------------------------------------------------------------------- #
# Integration with composable_size                                            #
# --------------------------------------------------------------------------- #


def test_haircut_reduces_composable_sizing():
    """Feeding the illiquid multiplier into composable_size reduces
    initial_pct / net_multiplier vs the no-haircut (1.0) baseline."""
    m = liquidity_haircut_multiplier(liquidity_profile(_illiquid_thin()))
    assert m < 1.0

    baseline = composable_size(
        mode="B", conviction="HIGH", liquidity_multiplier=1.0
    )
    haircut = composable_size(
        mode="B", conviction="HIGH", liquidity_multiplier=m
    )

    assert haircut.initial_pct < baseline.initial_pct
    assert haircut.max_pct < baseline.max_pct
    assert haircut.net_multiplier < baseline.net_multiplier
    # The liquidity multiplier surfaced in the per-dimension map equals m.
    assert haircut.multipliers["liquidity"] == pytest.approx(m)


def test_liquid_haircut_is_noop_in_composable_sizing():
    m = liquidity_haircut_multiplier(liquidity_profile(_liquid_large_cap()))
    assert m == 1.0
    baseline = composable_size(mode="B", conviction="HIGH")
    with_liq = composable_size(
        mode="B", conviction="HIGH", liquidity_multiplier=m
    )
    assert with_liq.initial_pct == pytest.approx(baseline.initial_pct)
    assert with_liq.net_multiplier == pytest.approx(baseline.net_multiplier)


# --------------------------------------------------------------------------- #
# WS-7.1 NaN regression: no fail-open, consistent NaN handling                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_dtl_multiplier_non_finite_does_not_fail_open(bad):
    """Bug 1: a non-finite DTL must NOT hit the liquid band's clean 1.0 by way
    of `max(0.0, NaN) == 0.0`. It degrades to the documented unavailable-skip
    (the benign 1.0), and the result is finite in (0, 1.0] either way."""
    m = _dtl_multiplier(bad)
    assert math.isfinite(m)
    assert 0.0 < m <= 1.0
    # Consistent with the None/skip path.
    assert m == _dtl_multiplier(None)


def test_profile_nan_notional_adv_flags_unavailable_not_clean_one():
    """Bug 2: an explicit NaN ADV with a real position must NOT silently yield
    the no-haircut 1.0 indistinguishable from a liquid large-cap. The combined
    multiplier stays finite in (0, 1.0], and the profile flags the data gap."""
    inp = LiquidityInputs(
        position_notional=5_000_000.0,
        notional_adv_30d=float("nan"),
        bid_ask_spread_bps=2.0,
        market_cap=2_000_000_000_000.0,
    )
    prof = liquidity_profile(inp)
    assert prof.liquidity_data_unavailable is True
    assert prof.days_to_liquidate is None  # NaN ADV → DTL not computed
    m = liquidity_haircut_multiplier(prof)
    assert math.isfinite(m)
    assert 0.0 < m <= 1.0
    # Surfaced in the audit payload so a monitor can see the gap.
    assert prof.to_payload()["liquidity_data_unavailable"] is True


def test_profile_nan_derived_adv_from_raw_series_flags_unavailable():
    """A NaN in the raw volume/close series derives a non-finite notional →
    treated as unavailable, flagged, never a silent clean 1.0."""
    inp = LiquidityInputs(
        position_notional=5_000_000.0,
        shares_volume_30d=[100.0, float("nan")],
        adj_close_30d=[10.0, 10.0],
    )
    prof = liquidity_profile(inp)
    assert prof.notional_adv_30d is None
    assert prof.liquidity_data_unavailable is True
    m = liquidity_haircut_multiplier(prof)
    assert math.isfinite(m)
    assert 0.0 < m <= 1.0


def test_market_cap_multiplier_nan_is_consistent_with_other_dims():
    """Bug 3: _market_cap_multiplier(NaN) must NOT be the lone dimension that
    haircuts garbage to the 0.60 NANO tier. It degrades to the same
    unavailable-skip (1.0) as the DTL/spread dims."""
    assert _market_cap_multiplier(float("nan")) == 1.0
    assert _spread_multiplier(float("nan")) == 1.0
    assert _dtl_multiplier(float("nan")) == 1.0
    # All three NaN paths agree with their respective None/skip path.
    assert _market_cap_multiplier(float("nan")) == _market_cap_multiplier(None)
    assert _spread_multiplier(float("nan")) == _spread_multiplier(None)
    assert _dtl_multiplier(float("nan")) == _dtl_multiplier(None)


def test_profile_nan_market_cap_flags_and_no_lone_haircut():
    """A provided NaN market-cap is a data gap: flagged, multiplier 1.0 for that
    dim (consistent), and the combined result stays finite in (0, 1.0]."""
    inp = LiquidityInputs(
        position_notional=1_000.0,
        notional_adv_30d=1_000_000_000.0,
        bid_ask_spread_bps=2.0,
        market_cap=float("nan"),
    )
    prof = liquidity_profile(inp)
    assert prof.liquidity_data_unavailable is True
    assert prof.market_cap_multiplier == 1.0
    m = liquidity_haircut_multiplier(prof)
    assert math.isfinite(m)
    assert 0.0 < m <= 1.0


def test_liquid_large_cap_not_flagged_unavailable():
    """A genuinely liquid large-cap still returns exactly 1.0 AND is NOT flagged
    — the flag distinguishes garbage-1.0 from legitimately-liquid-1.0."""
    prof = liquidity_profile(_liquid_large_cap())
    assert prof.liquidity_data_unavailable is False
    assert liquidity_haircut_multiplier(prof) == 1.0


def test_missing_none_inputs_not_flagged_unavailable():
    """Cleanly-missing (None) inputs keep the documented 1.0-skip and are NOT
    flagged — only non-finite garbage raises the data-gap flag."""
    inp = LiquidityInputs(position_notional=1_000_000.0)
    prof = liquidity_profile(inp)
    assert prof.liquidity_data_unavailable is False
    assert liquidity_haircut_multiplier(prof) == 1.0
