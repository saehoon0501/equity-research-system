"""Antonacci dual-momentum bin classifier — pure compute layer.

Per Section 2 v3-final Plan B v6 spec. The agent (.claude/agents/tactical-overlay.md)
is responsible for fetching price + FRED data via MCPs; this module is pure compute
on already-fetched inputs.

Architectural decoupling rationale: pure compute is unit-testable without MCP mocks,
and the agent layer is the natural place for MCP I/O. Mirrors the pattern used by
src/sizing/ (compute) vs pm-supervisor.md (agent that fetches + passes to compute).

INV-B6: window_lookback_days == max_staleness + WEEKEND_HOLIDAY_BUFFER_DAYS (code-level).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

# Module-top constants (per v6 Q3 polish for grep-ability)
MAX_STALENESS_CALENDAR_DAYS_DEFAULT = 7
WEEKEND_HOLIDAY_BUFFER_DAYS = 7
LOOKBACK_TRADING_DAYS = 252
RF_DEGENERATE_THRESHOLD_PCT = 0.5


def resolve_rf_at(
    fred_window: list[tuple[date, Optional[float]]],
    target_date: date,
    max_staleness_calendar_days: int = MAX_STALENESS_CALENDAR_DAYS_DEFAULT,
) -> Optional[float]:
    """Walk a FRED DGS1 window backward to find last valid print at/before target_date.

    Thin adapter for Section 2 v3-final Plan B v6's (date, value) tuple-list
    shape; delegates the walker logic to
    ``src.regime_sidecar.fred_client.resolve_latest_value_in_window`` (single
    source of truth for "latest valid value at-or-before date with staleness
    guard"). Same utility powers regime_sidecar.latest_value.

    Args:
        fred_window: list of (date, value_or_None) from mcp__fred__get_series.
                     Window MUST span >= (max_staleness + WEEKEND_HOLIDAY_BUFFER_DAYS)
                     days before target_date per INV-B6.
        target_date: anchor date (typically window-start of the 12mo lookback).
        max_staleness_calendar_days: reject if resolved date > this many days stale.

    Returns:
        DGS1 yield percent (e.g., 4.61) if a valid value found within staleness;
        None if no valid value or only values beyond staleness.
    """
    from src.regime_sidecar.fred_client import resolve_latest_value_in_window

    assert max_staleness_calendar_days >= 1, "INV-B4 violation"
    observations = [
        {"date": d.isoformat(), "value": v}
        for d, v in sorted(fred_window, key=lambda x: x[0])
    ]
    _, value = resolve_latest_value_in_window(
        observations,
        target_date=target_date,
        max_staleness_calendar_days=max_staleness_calendar_days,
    )
    return value


def first_trading_day_of_month(year: int, month: int) -> date:
    """Returns first weekday of the month.

    NOTE: does not check NYSE holidays. Section 3 polish item if needed.
    For Section 2.1 lock, weekday-only suffices since prior_month_close
    derivation is what's anchored, and any holiday-vs-trading-day mismatch
    is at most 1-2 days, well within the 7-day staleness buffer.
    """
    d = date(year, month, 1)
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d += timedelta(days=1)
    return d


def last_trading_day_of_prior_month(anchor: date) -> date:
    """Returns last weekday before anchor's first-of-month."""
    d = date(anchor.year, anchor.month, 1) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def classify(
    ticker_prices_adj_close: list[float],
    spy_prices_adj_close: list[float],
    rf_yield_pct: Optional[float],
) -> dict:
    """Antonacci dual-momentum classification on already-fetched inputs.

    Args:
        ticker_prices_adj_close: ordered list of ticker adjusted close (>= LOOKBACK_TRADING_DAYS).
                                 Index [-1] = most recent; [-LOOKBACK_TRADING_DAYS] = 12mo prior.
        spy_prices_adj_close: same shape for SPY (the benchmark).
        rf_yield_pct: DGS1 yield (percent) at the 12mo-prior anchor date, or None if unavailable.

    Returns:
        {'bin': str, 'rf_degenerate': bool, 'unavailable_reason': str|None}

    Bin classification (Antonacci canonical at zero threshold):
    - rel = ticker_ret_12mo - spy_ret_12mo
    - abs = ticker_ret_12mo - rf_ret_12mo
    - rel >= 0 AND abs >= 0  → "positive"
    - rel <= 0 AND abs <= 0  → "negative"
    - mixed                  → "neutral"

    Failure modes:
    - Insufficient ticker or SPY history → "unavailable" / "insufficient_price_history"
    - rf_yield_pct is None                → "unavailable" / "rf_resolver_staleness"
    """
    if (len(ticker_prices_adj_close) < LOOKBACK_TRADING_DAYS
            or len(spy_prices_adj_close) < LOOKBACK_TRADING_DAYS):
        return {
            "bin": "unavailable",
            "rf_degenerate": False,
            "unavailable_reason": "insufficient_price_history",
        }

    if rf_yield_pct is None:
        return {
            "bin": "unavailable",
            "rf_degenerate": False,
            "unavailable_reason": "rf_resolver_staleness",
        }

    ticker_ret = (ticker_prices_adj_close[-1]
                  / ticker_prices_adj_close[-LOOKBACK_TRADING_DAYS]) - 1.0
    spy_ret = (spy_prices_adj_close[-1]
               / spy_prices_adj_close[-LOOKBACK_TRADING_DAYS]) - 1.0
    rf_ret = rf_yield_pct / 100.0
    rf_degenerate = rf_yield_pct < RF_DEGENERATE_THRESHOLD_PCT

    rel = ticker_ret - spy_ret
    abs_ = ticker_ret - rf_ret

    if rel >= 0.0 and abs_ >= 0.0:
        bin_ = "positive"
    elif rel <= 0.0 and abs_ <= 0.0:
        bin_ = "negative"
    else:
        bin_ = "neutral"

    return {"bin": bin_, "rf_degenerate": rf_degenerate, "unavailable_reason": None}
