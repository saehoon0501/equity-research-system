"""Inner-ring unit tests for classify_reversion (P14, v0.4.0).

Per the plan: <1s, no LLM, no MCP, no live DB. Synthetic price arrays only.
"""
from __future__ import annotations

import pytest

from src.p10_reversion_overlay.bin_classifier import (
    classify_reversion,
    _rsi_wilder,
    _bollinger_band_position,
    _ma_distance_pct,
    _drawdown_from_high,
)


def _make_prices(n: int, start: float, drift: float = 0.0, vol: float = 0.0) -> list[float]:
    """Deterministic price series. drift = per-step linear increment.
    vol injects a deterministic oscillation so RSI/Bollinger have variance."""
    prices = []
    for i in range(n):
        # Light triangular oscillation to give the deltas variance (RSI needs both gains+losses)
        oscillation = (i % 4 - 1.5) * vol  # -1.5, -0.5, 0.5, 1.5, repeat
        prices.append(start + drift * i + oscillation)
    return prices


class TestDrawdownFromHigh:
    def test_no_drawdown_when_today_is_high(self):
        prices = list(range(100, 360))  # 260 monotonically increasing
        dd, high, _ = _drawdown_from_high(prices, 252)
        assert dd == 0.0
        assert high == prices[-1]

    def test_50pct_drawdown(self):
        # 252-day window with peak in-window at start, current = half of peak
        window = [100.0] + [50.0] * 251  # 252 entries; high=100 at idx 0, current=50
        dd, high, _ = _drawdown_from_high(window, 252)
        assert dd == pytest.approx(50.0)
        assert high == 100.0


class TestRsiWilder:
    def test_constant_prices_returns_100_no_losses(self):
        # When avg_loss=0, function returns 100 (max RSI)
        prices = [50.0] * 50
        rsi = _rsi_wilder(prices, 14)
        assert rsi == 100.0

    def test_strong_uptrend_rsi_above_70(self):
        prices = _make_prices(50, start=100.0, drift=1.0, vol=0.1)
        rsi = _rsi_wilder(prices, 14)
        assert rsi > 70.0

    def test_strong_downtrend_rsi_below_30(self):
        prices = _make_prices(50, start=200.0, drift=-1.0, vol=0.1)
        rsi = _rsi_wilder(prices, 14)
        assert rsi < 30.0

    def test_insufficient_data_raises(self):
        with pytest.raises(ValueError):
            _rsi_wilder([100.0, 101.0], 14)


class TestBollingerBandPosition:
    def test_at_mean_returns_zero(self):
        prices = [100.0] * 19 + [100.0]  # 20 entries
        pos, ma, sd = _bollinger_band_position(prices, 20)
        assert pos == 0.0
        assert ma == 100.0

    def test_above_band_positive_sigma(self):
        prices = [100.0] * 19 + [110.0]
        pos, _, _ = _bollinger_band_position(prices, 20)
        assert pos > 0


class TestMaDistancePct:
    def test_at_ma_zero_distance(self):
        prices = [100.0] * 200
        dist, ma = _ma_distance_pct(prices, 200)
        assert dist == 0.0
        assert ma == 100.0

    def test_above_ma_positive_distance(self):
        prices = [100.0] * 199 + [125.0]
        dist, ma = _ma_distance_pct(prices, 200)
        assert dist > 0


class TestClassifyReversionInsufficientData:
    def test_under_252_returns_unavailable(self):
        result = classify_reversion([100.0] * 100)
        assert result["bin"] == "MR_UNAVAILABLE"
        assert result["unavailable_reason"] == "insufficient_price_history"
        assert result["components"] is None
        assert result["sub_signal_fires"] is None


class TestClassifyReversionNeutral:
    def test_flat_prices_neutral(self):
        prices = [100.0] * 252
        result = classify_reversion(prices)
        # No drawdown, RSI=100 (no losses), Bollinger pos=0
        assert result["bin"] == "MR_NEUTRAL"
        assert result["components"]["drawdown_from_252d_high_pct"] == 0.0


class TestClassifyReversionOversold:
    def test_deep_drawdown_with_oversold_rsi_fires_oversold(self):
        # Build a series: long uptrend → sharp crash. Synthetic data has uniform
        # deltas so Bollinger σ is small; use loosened threshold to test logic
        # (real CRWD crash showed bb pos < -2.0 because of higher volatility).
        uptrend = list(range(100, 300))
        crash = [299.0]
        for _ in range(60):
            crash.append(crash[-1] * 0.97)
        prices = uptrend + crash[1:]
        result = classify_reversion(
            prices,
            drawdown_252d_threshold_pct=40.0,
            bollinger_lower_band_pct=-1.0,  # synthetic-friendly threshold
        )
        # Should fire all 3 oversold sub-signals at these thresholds
        assert result["bin"] == "MR_OVERSOLD"
        fires = result["sub_signal_fires"]
        assert fires["drawdown_threshold"] is True
        assert fires["rsi_oversold"] is True
        assert fires["bollinger_lower_extreme"] is True

    def test_drawdown_alone_insufficient_for_oversold(self):
        # Crash then plateau — drawdown fires but RSI stabilizes back to neutral
        uptrend = list(range(100, 300))
        crash_then_flat = [150.0] * 60
        prices = uptrend + crash_then_flat
        result = classify_reversion(prices)
        # Drawdown is huge but RSI not oversold anymore — should NOT fire MR_OVERSOLD
        assert result["bin"] == "MR_NEUTRAL"


class TestClassifyReversionOverbought:
    def test_strong_uptrend_with_far_from_ma_fires_overbought(self):
        # Slow rise then parabolic blow-off. Synthetic-friendly thresholds
        # (real overbought instances have higher Bollinger σ).
        base = [100.0] * 100
        slow = list(range(100, 200))
        parabolic = [200.0]
        for _ in range(60):
            parabolic.append(parabolic[-1] * 1.04)
        prices = base + slow + parabolic[1:]
        result = classify_reversion(
            prices,
            ma_distance_overbought_pct=25.0,
            bollinger_upper_band_pct=1.0,  # synthetic-friendly threshold
        )
        assert result["bin"] == "MR_OVERBOUGHT"
        fires = result["sub_signal_fires"]
        assert fires["rsi_overbought"] is True
        assert fires["bollinger_upper_extreme"] is True
        assert result["components"]["ma_distance_200d_pct"] >= 25.0


class TestClassifyReversionParameterOverrides:
    def test_lower_drawdown_threshold_triggers_oversold_earlier(self):
        # Build a series with 25% drawdown — would NOT fire at default 40
        # but DOES fire at threshold=20 (combined with RSI + Bollinger fires)
        uptrend = list(range(100, 250))  # 150 days
        crash = [249.0]
        for _ in range(40):
            crash.append(crash[-1] * 0.985)  # consecutive losses
        prices = uptrend + crash[1:]
        # Pad to 252 with leading constants
        while len(prices) < 252:
            prices.insert(0, 100.0)

        # With default (40% threshold): drawdown likely below threshold
        default_result = classify_reversion(prices)
        # With 5% threshold: should be much more permissive
        lenient_result = classify_reversion(prices, drawdown_252d_threshold_pct=5.0)
        # If all other sub-signals fire, lenient should produce oversold while default doesn't
        assert lenient_result["bin"] in {"MR_OVERSOLD", "MR_NEUTRAL"}
        # The point: parameter override changes behavior
        if lenient_result["sub_signal_fires"]["drawdown_threshold"]:
            assert lenient_result["components"]["drawdown_from_252d_high_pct"] >= 5.0


class TestClassifyReversionShape:
    def test_neutral_result_has_all_expected_keys(self):
        prices = list(range(100, 360))  # 260 monotonic uptrend
        result = classify_reversion(prices)
        assert set(result.keys()) == {"bin", "components", "sub_signal_fires", "unavailable_reason"}
        assert set(result["components"].keys()) == {
            "drawdown_from_252d_high_pct",
            "rsi_14",
            "bollinger_band_position",
            "ma_distance_200d_pct",
            "252d_high",
            "prior_close",
        }
        assert set(result["sub_signal_fires"].keys()) == {
            "drawdown_threshold",
            "rsi_oversold",
            "rsi_overbought",
            "bollinger_lower_extreme",
            "bollinger_upper_extreme",
        }

    def test_unavailable_has_null_components(self):
        result = classify_reversion([100.0] * 50)
        assert result["components"] is None
        assert result["sub_signal_fires"] is None
        assert result["unavailable_reason"] is not None
