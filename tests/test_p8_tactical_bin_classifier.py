"""Tests for Antonacci dual-momentum bin classifier (pure compute)."""

from datetime import date, timedelta

from src.p8_tactical_overlay.bin_classifier import (
    LOOKBACK_TRADING_DAYS,
    MAX_STALENESS_CALENDAR_DAYS_DEFAULT,
    RF_DEGENERATE_THRESHOLD_PCT,
    WEEKEND_HOLIDAY_BUFFER_DAYS,
    classify,
    first_trading_day_of_month,
    last_trading_day_of_prior_month,
    resolve_rf_at,
)


def test_inv_b6_module_constants():
    """INV-B6 grep-ability: module-top constants."""
    assert WEEKEND_HOLIDAY_BUFFER_DAYS == 7
    assert MAX_STALENESS_CALENDAR_DAYS_DEFAULT == 7
    assert LOOKBACK_TRADING_DAYS == 252
    assert RF_DEGENERATE_THRESHOLD_PCT == 0.5


def test_resolve_rf_at_returns_most_recent_valid_print():
    target = date(2026, 5, 20)
    window = [
        (date(2026, 5, 18), 4.61),
        (date(2026, 5, 19), 4.62),
        (date(2026, 5, 20), None),  # ND day
    ]
    assert resolve_rf_at(window, target, max_staleness_calendar_days=7) == 4.62


def test_resolve_rf_at_rejects_stale_beyond_max():
    target = date(2026, 5, 20)
    window = [(date(2026, 5, 5), 4.50)]  # 15 days stale > 7d gate
    assert resolve_rf_at(window, target, max_staleness_calendar_days=7) is None


def test_resolve_rf_at_returns_none_on_empty_window():
    assert resolve_rf_at([], date(2026, 5, 20)) is None


def test_resolve_rf_at_walks_backward_through_nd_days():
    """Holiday-cluster scenario: target date has no DGS1; walk back to find valid."""
    target = date(2026, 12, 26)  # Christmas weekend; Treasury closed
    window = [
        (date(2026, 12, 22), 4.50),
        (date(2026, 12, 23), 4.51),
        (date(2026, 12, 24), None),  # Christmas Eve early close
        (date(2026, 12, 25), None),  # Christmas
        (date(2026, 12, 26), None),  # Day after
    ]
    assert resolve_rf_at(window, target, max_staleness_calendar_days=7) == 4.51


def test_first_trading_day_of_month_skips_weekend():
    # July 2026: July 1 is Wednesday
    assert first_trading_day_of_month(2026, 7) == date(2026, 7, 1)
    # August 2026: August 1 is Saturday → expect Monday Aug 3
    assert first_trading_day_of_month(2026, 8) == date(2026, 8, 3)


def test_last_trading_day_of_prior_month():
    # anchor = 2026-08-03 (first Mon of Aug); prior month last trading = 2026-07-31 (Fri)
    assert last_trading_day_of_prior_month(date(2026, 8, 3)) == date(2026, 7, 31)
    # anchor = 2026-09-01 (Tue); prior month last trading = 2026-08-31 (Mon)
    assert last_trading_day_of_prior_month(date(2026, 9, 1)) == date(2026, 8, 31)


def _flat_then_rally(start_val: float, end_val: float, n: int = LOOKBACK_TRADING_DAYS) -> list[float]:
    """Helper: list of n adj_close values where first n-1 are start_val, last is end_val."""
    return [start_val] * (n - 1) + [end_val]


def test_classify_positive_both_legs():
    """ticker +30% vs SPY +5% vs rf 4% → both rel and abs positive → positive."""
    ticker = _flat_then_rally(100.0, 130.0)  # +30%
    spy = _flat_then_rally(400.0, 420.0)  # +5%
    result = classify(ticker, spy, rf_yield_pct=4.0)
    assert result["bin"] == "positive"
    assert result["rf_degenerate"] is False
    assert result["unavailable_reason"] is None


def test_classify_negative_both_legs():
    """ticker -30% vs SPY -5% vs rf 4% → both rel and abs negative → negative."""
    ticker = _flat_then_rally(100.0, 70.0)  # -30%
    spy = _flat_then_rally(400.0, 380.0)  # -5%
    result = classify(ticker, spy, rf_yield_pct=4.0)
    assert result["bin"] == "negative"


def test_classify_mixed_returns_neutral():
    """ticker +2% beats SPY -1% (rel positive) but below rf 5% (abs negative) → neutral."""
    ticker = _flat_then_rally(100.0, 102.0)  # +2%
    spy = _flat_then_rally(400.0, 396.0)  # -1%
    result = classify(ticker, spy, rf_yield_pct=5.0)
    assert result["bin"] == "neutral"


def test_classify_rf_degenerate_flag_fires():
    """ZIRP regime: rf 0.04% < threshold 0.5 → rf_degenerate=true."""
    ticker = _flat_then_rally(100.0, 110.0)
    spy = _flat_then_rally(400.0, 405.0)
    result = classify(ticker, spy, rf_yield_pct=0.04)
    assert result["rf_degenerate"] is True


def test_classify_rf_degenerate_flag_off_above_threshold():
    ticker = _flat_then_rally(100.0, 110.0)
    spy = _flat_then_rally(400.0, 405.0)
    result = classify(ticker, spy, rf_yield_pct=0.5)
    assert result["rf_degenerate"] is False  # boundary: not strictly < 0.5


def test_classify_insufficient_history_returns_unavailable():
    short = [100.0] * 100  # < 252
    spy = _flat_then_rally(400.0, 405.0)
    result = classify(short, spy, rf_yield_pct=4.0)
    assert result["bin"] == "unavailable"
    assert result["unavailable_reason"] == "insufficient_price_history"


def test_classify_rf_none_returns_unavailable():
    ticker = _flat_then_rally(100.0, 110.0)
    spy = _flat_then_rally(400.0, 405.0)
    result = classify(ticker, spy, rf_yield_pct=None)
    assert result["bin"] == "unavailable"
    assert result["unavailable_reason"] == "rf_resolver_staleness"


def test_classify_zero_thresholds_canonical():
    """Antonacci canonical: rel=0 AND abs=0 → positive (>=0 inclusive)."""
    # ticker and SPY identical → rel = 0
    # ticker_ret = rf_ret → abs = 0
    # 0 / 100 = 0%, then last value 104 / 100 = 4% → ticker_ret 4%
    ticker = _flat_then_rally(100.0, 104.0)
    spy = _flat_then_rally(400.0, 416.0)  # +4%
    result = classify(ticker, spy, rf_yield_pct=4.0)  # rf = 4%
    assert result["bin"] == "positive"  # >=0 inclusive on both legs
