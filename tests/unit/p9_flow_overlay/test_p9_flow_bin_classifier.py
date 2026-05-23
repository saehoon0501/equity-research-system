"""Tests for CTA-proximity composite bin classifier (pure compute)."""

from src.p9_flow_overlay.bin_classifier import (
    LOOKBACK_TRADING_DAYS,
    MAX_COMPOSITE_SCORE,
    NEGATIVE_BIN_THRESHOLD,
    POSITIVE_BIN_THRESHOLD,
    VOTES_PER_INSTRUMENT,
    classify_flow,
)


def test_module_constants_match_plan():
    assert LOOKBACK_TRADING_DAYS == 252
    assert VOTES_PER_INSTRUMENT == 4
    assert MAX_COMPOSITE_SCORE == 8
    assert POSITIVE_BIN_THRESHOLD == 0.5
    assert NEGATIVE_BIN_THRESHOLD == -0.5


def _series_with_trend(start: float, end: float, n: int = LOOKBACK_TRADING_DAYS + 10) -> list[float]:
    """Linearly-interpolated price series from start to end across n sessions."""
    step = (end - start) / (n - 1)
    return [start + step * i for i in range(n)]


def _series_flat_at(base: float, n: int = LOOKBACK_TRADING_DAYS + 10) -> list[float]:
    """Flat series at `base` — no trend, no MA distance, degenerate Donchian.
    All four sub-signals vote 0 → composite 0 → neutral bin.
    """
    return [base] * n


def test_classify_positive_when_both_ticker_and_market_uptrending():
    """Strong uptrend on both ticker + SPY should produce positive bin."""
    ticker = _series_with_trend(100.0, 150.0)
    spy = _series_with_trend(400.0, 500.0)
    result = classify_flow(ticker, spy)
    assert result["bin"] == "positive"
    assert result["components"]["ticker_score"] > 0
    assert result["components"]["market_score"] > 0
    assert result["components"]["composite_score_normalized"] >= POSITIVE_BIN_THRESHOLD


def test_classify_negative_when_both_ticker_and_market_downtrending():
    """Strong downtrend on both ticker + SPY should produce negative bin."""
    ticker = _series_with_trend(150.0, 100.0)
    spy = _series_with_trend(500.0, 400.0)
    result = classify_flow(ticker, spy)
    assert result["bin"] == "negative"
    assert result["components"]["ticker_score"] < 0
    assert result["components"]["market_score"] < 0
    assert result["components"]["composite_score_normalized"] <= NEGATIVE_BIN_THRESHOLD


def test_classify_neutral_when_flat():
    """Flat (no-trend) markets should produce neutral bin (all sub-signals = 0)."""
    ticker = _series_flat_at(100.0)
    spy = _series_flat_at(400.0)
    result = classify_flow(ticker, spy)
    assert result["bin"] == "neutral"
    assert result["components"]["ticker_score"] == 0
    assert result["components"]["market_score"] == 0
    assert result["components"]["composite_score_normalized"] == 0.0


def test_classify_unavailable_insufficient_ticker_history():
    """Ticker series shorter than lookback → unavailable / insufficient_price_history."""
    ticker = _series_with_trend(100.0, 130.0, n=100)  # too short
    spy = _series_with_trend(400.0, 500.0)
    result = classify_flow(ticker, spy)
    assert result["bin"] == "unavailable"
    assert result["unavailable_reason"] == "insufficient_price_history"
    assert result["components"] is None


def test_classify_unavailable_spy_history_missing():
    """SPY series shorter than lookback → unavailable / spy_price_history_unavailable."""
    ticker = _series_with_trend(100.0, 130.0)
    spy = _series_with_trend(400.0, 500.0, n=50)  # too short
    result = classify_flow(ticker, spy)
    assert result["bin"] == "unavailable"
    assert result["unavailable_reason"] == "spy_price_history_unavailable"


def test_classify_handles_exactly_lookback_length():
    """Boundary: exactly LOOKBACK_TRADING_DAYS samples should NOT trigger unavailable."""
    ticker = _series_with_trend(100.0, 130.0, n=LOOKBACK_TRADING_DAYS)
    spy = _series_with_trend(400.0, 420.0, n=LOOKBACK_TRADING_DAYS)
    result = classify_flow(ticker, spy)
    assert result["bin"] != "unavailable"


def test_classify_composite_score_in_normalized_range():
    """composite_score_normalized must lie in [-1.0, +1.0]."""
    ticker = _series_with_trend(100.0, 200.0)
    spy = _series_with_trend(400.0, 800.0)
    result = classify_flow(ticker, spy)
    assert -1.0 <= result["components"]["composite_score_normalized"] <= 1.0


def test_ticker_score_bounded_by_votes_per_instrument():
    """ticker_score must be in [-4, +4] (4 votes, each ±1)."""
    ticker = _series_with_trend(100.0, 1000.0)
    spy = _series_with_trend(400.0, 4000.0)
    result = classify_flow(ticker, spy)
    assert -VOTES_PER_INSTRUMENT <= result["components"]["ticker_score"] <= VOTES_PER_INSTRUMENT
    assert -VOTES_PER_INSTRUMENT <= result["components"]["market_score"] <= VOTES_PER_INSTRUMENT
