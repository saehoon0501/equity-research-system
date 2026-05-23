"""CTA-proximity composite bin classifier — pure compute layer.

Per the v0.1 plan, this module computes the flow_bin from price-only inputs
(no FRED, no options chain, no fundamentals — those land in v0.2 / v0.3).

Composite signal = ticker-level + market-level (SPY) CTA-proximity score
aggregated from three sub-signals per the Moskowitz-Ooi-Pedersen TSMOM
canon (JFE 2012) and the Antonacci dual-momentum framework:

  1. 12-month TSMOM sign (Antonacci canonical 12-0 lookback)
  2. Position relative to 50-day and 200-day moving averages (CTA-trigger proxy
     per kasmcapital + Goldman PB reverse-engineering convention)
  3. Donchian state — position within 55-day high / 20-day low band
     (Turtle-style breakout/breakdown indicator)

Architectural decoupling: pure compute on already-fetched price series.
Agent layer (.claude/agents/flow-overlay.md) handles MCP I/O.

Date helpers (first_trading_day_of_month, last_trading_day_of_prior_month)
are imported from src.p8_tactical_overlay.bin_classifier — single source of
truth; do not reimplement.

Open items for /review-me (placeholders below carry sensible v0.1 defaults):
- POSITIVE_BIN_THRESHOLD / NEGATIVE_BIN_THRESHOLD scoring cutoffs
- Sub-signal weighting (currently equal-weighted across the 6 components)
- Donchian band-fraction cutoffs (currently upper/lower quartile = breakout)
"""
from __future__ import annotations

from datetime import date
from typing import Optional

# Re-export date helpers from p8 — single source of truth.
# Use this module's public names so flow-overlay agent can import from one place
# without reaching into p8.
from src.p8_tactical_overlay.bin_classifier import (  # noqa: F401
    first_trading_day_of_month,
    last_trading_day_of_prior_month,
)

# Module-top constants
LOOKBACK_TRADING_DAYS = 252
MA_SHORT_WINDOW = 50
MA_LONG_WINDOW = 200
DONCHIAN_HIGH_WINDOW = 55
DONCHIAN_LOW_WINDOW = 20

# v0.1 placeholder thresholds — /review-me delivers final values + sub-signal weights.
# Range: composite_score is normalized to [-1.0, +1.0] (sum of votes / MAX_COMPOSITE_SCORE).
# Defaults err on the side of "neutral unless clearly directional" to avoid
# false-positive regime calls at launch.
#
# IMPORTANT: these are MODULE-LEVEL FALLBACKS for tests/standalone use only.
# The flow-overlay AGENT reads from `parameters_active` (flow.positive_bin_threshold /
# flow.negative_bin_threshold) per the PARAMETERS_USED ground-truth contract.
# A caller importing these constants directly will pin v0.1 placeholder values
# and miss any /review-me parameter update — DO NOT import from production code.
POSITIVE_BIN_THRESHOLD = 0.5  # default fallback; production reads parameters_active
NEGATIVE_BIN_THRESHOLD = -0.5  # default fallback; production reads parameters_active

# Donchian band-fraction cutoffs: where in the [low, high] range does price sit.
# Defaults: upper quartile = bullish breakout zone; lower quartile = bearish.
# Same parameters_active override contract as above.
DONCHIAN_BULLISH_FRACTION = 0.75  # default fallback; production reads parameters_active
DONCHIAN_BEARISH_FRACTION = 0.25  # default fallback; production reads parameters_active


def _vote_from_tsmom(price_series: list[float]) -> int:
    """Returns +1 if 12mo return > 0, -1 if < 0, 0 if exactly zero.

    Caller must ensure len(price_series) >= LOOKBACK_TRADING_DAYS.
    """
    ret = (price_series[-1] / price_series[-LOOKBACK_TRADING_DAYS]) - 1.0
    if ret > 0:
        return 1
    if ret < 0:
        return -1
    return 0


def _vote_from_ma_distance(price_series: list[float], window: int) -> int:
    """Returns +1 if price > MA, -1 if < MA, 0 if exactly equal.

    Caller must ensure len(price_series) >= window.
    """
    ma = sum(price_series[-window:]) / window
    spot = price_series[-1]
    if spot > ma:
        return 1
    if spot < ma:
        return -1
    return 0


def _vote_from_donchian(price_series: list[float]) -> int:
    """Returns +1 if price in upper quartile of (low20, high55), -1 if lower, else 0.

    Caller must ensure len(price_series) >= DONCHIAN_HIGH_WINDOW.
    """
    high = max(price_series[-DONCHIAN_HIGH_WINDOW:])
    low = min(price_series[-DONCHIAN_LOW_WINDOW:])
    spot = price_series[-1]
    if high == low:
        # Degenerate range (extremely rare; gives no signal)
        return 0
    fraction = (spot - low) / (high - low)
    if fraction >= DONCHIAN_BULLISH_FRACTION:
        return 1
    if fraction <= DONCHIAN_BEARISH_FRACTION:
        return -1
    return 0


# 4 votes per instrument (TSMOM + MA50 + MA200 + Donchian); ticker + SPY → max 8.
VOTES_PER_INSTRUMENT = 4
MAX_COMPOSITE_SCORE = VOTES_PER_INSTRUMENT * 2


def classify_flow(
    ticker_prices_adj_close: list[float],
    spy_prices_adj_close: list[float],
) -> dict:
    """CTA-proximity composite classification on already-fetched inputs.

    Args:
        ticker_prices_adj_close: ordered list of ticker adjusted close
            (>= LOOKBACK_TRADING_DAYS). Index [-1] = most recent.
        spy_prices_adj_close: same shape for SPY (the market-level CTA proxy).

    Returns:
        {
            'bin': 'positive' | 'neutral' | 'negative' | 'unavailable',
            'components': {
                'ticker_score': int (range [-4, +4]),
                'market_score': int (range [-4, +4]),
                'composite_score_normalized': float (range [-1.0, +1.0]),
            },
            'unavailable_reason': str | None,
        }

    Bin classification:
    - composite_score_normalized >= POSITIVE_BIN_THRESHOLD → 'positive'
    - composite_score_normalized <= NEGATIVE_BIN_THRESHOLD → 'negative'
    - otherwise → 'neutral'

    Failure modes:
    - Insufficient ticker history → 'unavailable' / 'insufficient_price_history'
    - Insufficient SPY history    → 'unavailable' / 'spy_price_history_unavailable'
    """
    if len(ticker_prices_adj_close) < LOOKBACK_TRADING_DAYS:
        return {
            "bin": "unavailable",
            "components": None,
            "unavailable_reason": "insufficient_price_history",
        }

    if len(spy_prices_adj_close) < LOOKBACK_TRADING_DAYS:
        return {
            "bin": "unavailable",
            "components": None,
            "unavailable_reason": "spy_price_history_unavailable",
        }

    ticker_score = (
        _vote_from_tsmom(ticker_prices_adj_close)
        + _vote_from_ma_distance(ticker_prices_adj_close, MA_SHORT_WINDOW)
        + _vote_from_ma_distance(ticker_prices_adj_close, MA_LONG_WINDOW)
        + _vote_from_donchian(ticker_prices_adj_close)
    )
    market_score = (
        _vote_from_tsmom(spy_prices_adj_close)
        + _vote_from_ma_distance(spy_prices_adj_close, MA_SHORT_WINDOW)
        + _vote_from_ma_distance(spy_prices_adj_close, MA_LONG_WINDOW)
        + _vote_from_donchian(spy_prices_adj_close)
    )

    composite = (ticker_score + market_score) / MAX_COMPOSITE_SCORE

    if composite >= POSITIVE_BIN_THRESHOLD:
        bin_ = "positive"
    elif composite <= NEGATIVE_BIN_THRESHOLD:
        bin_ = "negative"
    else:
        bin_ = "neutral"

    return {
        "bin": bin_,
        "components": {
            "ticker_score": ticker_score,
            "market_score": market_score,
            "composite_score_normalized": composite,
        },
        "unavailable_reason": None,
    }
