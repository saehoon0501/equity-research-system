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
MAX_COMPOSITE_SCORE_V01 = VOTES_PER_INSTRUMENT * 2  # ticker + SPY = 8

# v0.2 extension: gamma_regime contributes 1 additional ±1 vote when present.
# Composite max becomes 9 when gamma_regime is provided to classify_flow().
GAMMA_REGIME_VOTE_WEIGHT = 1
MAX_COMPOSITE_SCORE_V02 = MAX_COMPOSITE_SCORE_V01 + GAMMA_REGIME_VOTE_WEIGHT  # 9

# v0.3 extension: crowding_warning is ASYMMETRIC — contributes -1 to the
# composite when warning=True, 0 otherwise (NEVER +1). This preserves the
# ceiling (MAX = 9 = MAX_COMPOSITE_SCORE_V02); only the floor extends by 1
# downward. POSITIVE_BIN_THRESHOLD does NOT need recalibration as a result.
CROWDING_VOTE_NEGATIVE_ONLY = True
MAX_COMPOSITE_SCORE_V03 = MAX_COMPOSITE_SCORE_V02  # ceiling preserved by asymmetry

# Back-compat alias: v0.1 callers reading MAX_COMPOSITE_SCORE still get the
# v0.1 value (8). v0.2/v0.3 internal logic uses the version-specific constant per
# the gamma_regime / crowding_warning input presence.
MAX_COMPOSITE_SCORE = MAX_COMPOSITE_SCORE_V01


def _gamma_score(gamma_regime: dict | None) -> int:
    """Map v0.2 gamma_regime.bin to a ±1 vote contribution.

    Returns +1/0/-1/0 for positive/neutral/negative/anything-else.
    None gamma_regime returns 0 (v0.1 back-compat: tickers without options chain).
    """
    if gamma_regime is None:
        return 0
    bin_ = gamma_regime.get("bin")
    if bin_ == "positive":
        return 1
    if bin_ == "negative":
        return -1
    return 0  # neutral or any other value


def _crowding_score(crowding_warning: dict | None) -> int:
    """Map v0.3 crowding_warning to an asymmetric vote contribution.

    Returns -1 when warning=True, 0 otherwise (NEVER +1). Per the v0.3 plan:
    asymmetric signals contribute -N when fired, 0 otherwise.

    None crowding_warning returns 0 (back-compat: tickers without short-interest
    data, or v0.1/v0.2 callers that don't pass the kwarg).
    """
    if crowding_warning is None:
        return 0
    return -1 if crowding_warning.get("warning") is True else 0


def classify_flow(
    ticker_prices_adj_close: list[float],
    spy_prices_adj_close: list[float],
    gamma_regime: dict | None = None,
    crowding_warning: dict | None = None,
) -> dict:
    """CTA-proximity composite classification on already-fetched inputs.

    v0.2 extension: optional `gamma_regime` kwarg from
    `src.p9_flow_overlay.gex_aggregator.classify_gamma_regime()`. When
    provided, contributes one additional ±1 vote to the composite score
    (max_composite shifts from 8 to 9).

    v0.3 extension: optional `crowding_warning` kwarg from
    `src.p9_flow_overlay.crowding_classifier.classify_crowding()`. ASYMMETRIC:
    contributes -1 ONLY when warning=True; 0 otherwise (never +1). Ceiling
    of composite is preserved (still 9 when gamma_regime present); only the
    floor extends downward by 1.

    Back-compat: when both gamma_regime and crowding_warning are None,
    behavior is bit-identical to v0.1 (composite divisor = 8, components dict
    has only the 3 v0.1 keys, no v0.2/v0.3 keys present).

    Args:
        ticker_prices_adj_close: ordered list of ticker adjusted close
            (>= LOOKBACK_TRADING_DAYS). Index [-1] = most recent.
        spy_prices_adj_close: same shape for SPY (the market-level CTA proxy).
        gamma_regime: optional dict from gex_aggregator.classify_gamma_regime()
            with keys including 'bin' ∈ {positive, neutral, negative}.
        crowding_warning: optional dict from crowding_classifier.classify_crowding()
            with key 'warning' ∈ {True, False}.

    Returns:
        {
            'bin': 'positive' | 'neutral' | 'negative' | 'unavailable',
            'components': {
                'ticker_score': int (range [-4, +4]),
                'market_score': int (range [-4, +4]),
                'composite_score_normalized': float (range [-1.0, +1.0]),
                # v0.2 (only when gamma_regime is not None):
                'gamma_score': int (range [-1, +1]),
                'gamma_regime': dict (verbatim from input),
                # v0.3 (only when crowding_warning is not None):
                'crowding_score': int (range [-1, 0]),
                'crowding': dict (verbatim from input),
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

    # Determine composite denominator + assemble components dict.
    # - When both gamma_regime and crowding_warning are None: bit-identical v0.1
    #   (divisor=8, only the 3 v0.1 keys).
    # - When gamma_regime is provided (with/without crowding): divisor=9 (v0.2),
    #   ceiling preserved at +1; crowding adds asymmetric -1 only when warning=True.
    # - When crowding_warning is provided without gamma_regime: divisor stays at
    #   v0.1 (8); crowding asymmetric -1 contributes to numerator, ceiling unchanged.
    crowding_vote = _crowding_score(crowding_warning)

    if gamma_regime is not None:
        gamma_vote = _gamma_score(gamma_regime)
        numerator = ticker_score + market_score + gamma_vote + crowding_vote
        composite = numerator / MAX_COMPOSITE_SCORE_V02
        components = {
            "ticker_score": ticker_score,
            "market_score": market_score,
            "composite_score_normalized": composite,
            "gamma_score": gamma_vote,
            "gamma_regime": gamma_regime,
        }
    else:
        numerator = ticker_score + market_score + crowding_vote
        composite = numerator / MAX_COMPOSITE_SCORE_V01
        components = {
            "ticker_score": ticker_score,
            "market_score": market_score,
            "composite_score_normalized": composite,
        }

    if crowding_warning is not None:
        components["crowding_score"] = crowding_vote
        components["crowding"] = crowding_warning

    if composite >= POSITIVE_BIN_THRESHOLD:
        bin_ = "positive"
    elif composite <= NEGATIVE_BIN_THRESHOLD:
        bin_ = "negative"
    else:
        bin_ = "neutral"

    return {
        "bin": bin_,
        "components": components,
        "unavailable_reason": None,
    }
