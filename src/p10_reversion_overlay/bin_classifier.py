"""Mean-reversion bin classifier — pure compute layer (v0.4.0).

Per the plan at ~/.claude/plans/no-pm-supervisor-integration-yet-smooth-cascade.md,
this module computes a reversion_bin from price-only inputs.

Composite signal = 3-condition AND-gate per direction:

  MR_OVERSOLD when ALL of:
    - drawdown_from_252d_high_pct >= reversion.drawdown_252d_threshold_pct
    - rsi_14 <= reversion.rsi_14_oversold_threshold
    - bollinger_band_position <= reversion.bollinger_lower_band_pct

  MR_OVERBOUGHT when ALL of:
    - rsi_14 >= reversion.rsi_14_overbought_threshold
    - bollinger_band_position >= reversion.bollinger_upper_band_pct
    - ma_distance_200d_pct >= reversion.ma_distance_overbought_pct

  MR_NEUTRAL otherwise.
  MR_UNAVAILABLE on insufficient price history.

Frameworks invoked: DeBondt-Thaler 1985 (long-term reversal), Bollinger 1992
(bands), Wilder 1978 (RSI).

Architectural decoupling: pure compute on already-fetched price series.
Agent layer (.claude/agents/mean-reversion-overlay.md) handles MCP I/O.

Date helpers (first_trading_day_of_month, last_trading_day_of_prior_month)
are imported from src.p8_tactical_overlay.bin_classifier — single source of
truth; do not reimplement.
"""
from __future__ import annotations

# Re-export date helpers from p8 — single source of truth.
from src.p8_tactical_overlay.bin_classifier import (  # noqa: F401
    first_trading_day_of_month,
    last_trading_day_of_prior_month,
)

# Module-top constants — MODULE-LEVEL FALLBACKS for tests/standalone use only.
# The mean-reversion-overlay AGENT reads from `parameters_active` (reversion.*)
# per the PARAMETERS_USED ground-truth contract.
LOOKBACK_TRADING_DAYS = 252
MA_SHORT_WINDOW = 20  # for Bollinger MA centerline
MA_LONG_WINDOW = 200  # for ma-distance sub-signal
RSI_WINDOW = 14

# Threshold defaults — production code reads parameters_active
DRAWDOWN_252D_THRESHOLD_PCT = 40.0
RSI_14_OVERSOLD_THRESHOLD = 30.0
RSI_14_OVERBOUGHT_THRESHOLD = 70.0
BOLLINGER_LOWER_BAND_PCT = -2.0
BOLLINGER_UPPER_BAND_PCT = 2.0
MA_DISTANCE_OVERBOUGHT_PCT = 25.0


def _drawdown_from_high(price_series: list[float], lookback: int) -> tuple[float, float, int]:
    """Returns (drawdown_pct, high_value, high_index_in_lookback_window).

    Caller must ensure len(price_series) >= lookback.
    """
    window = price_series[-lookback:]
    high = max(window)
    high_index = window.index(high)
    spot = price_series[-1]
    dd_pct = (high - spot) / high * 100.0
    return dd_pct, high, high_index


def _rsi_wilder(price_series: list[float], window: int) -> float:
    """Wilder-smoothed RSI over `window` periods on `price_series`.

    Standard formula:
      Initial avg gain/loss = simple mean over first `window` deltas.
      Subsequent avg = (prev_avg * (window-1) + current) / window.
      RS = avg_gain / avg_loss; RSI = 100 - (100 / (1 + RS)).

    Caller must ensure len(price_series) >= window + 1.
    """
    if len(price_series) < window + 1:
        raise ValueError(f"need >= {window+1} prices for RSI({window}), got {len(price_series)}")

    deltas = [price_series[i] - price_series[i - 1] for i in range(1, len(price_series))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [-min(d, 0.0) for d in deltas]

    # Initial average over first `window` deltas
    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window

    # Wilder smoothing over the remaining deltas
    for i in range(window, len(deltas)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _bollinger_band_position(price_series: list[float], window: int) -> tuple[float, float, float]:
    """Returns (position_in_sigma, ma, stdev).

    position_in_sigma = (close - MA) / stdev. Standard 2σ bands → +/- 2.0.
    Caller must ensure len(price_series) >= window.
    """
    win = price_series[-window:]
    ma = sum(win) / window
    variance = sum((x - ma) ** 2 for x in win) / window
    stdev = variance ** 0.5
    if stdev == 0:
        return 0.0, ma, 0.0
    return (price_series[-1] - ma) / stdev, ma, stdev


def _ma_distance_pct(price_series: list[float], window: int) -> tuple[float, float]:
    """Returns (distance_pct, ma). distance_pct = (close - MA) / MA * 100.

    Caller must ensure len(price_series) >= window.
    """
    win = price_series[-window:]
    ma = sum(win) / window
    if ma == 0:
        return 0.0, 0.0
    return (price_series[-1] - ma) / ma * 100.0, ma


def classify_reversion(
    ticker_prices_adj_close: list[float],
    *,
    drawdown_252d_threshold_pct: float = DRAWDOWN_252D_THRESHOLD_PCT,
    rsi_14_oversold_threshold: float = RSI_14_OVERSOLD_THRESHOLD,
    rsi_14_overbought_threshold: float = RSI_14_OVERBOUGHT_THRESHOLD,
    bollinger_lower_band_pct: float = BOLLINGER_LOWER_BAND_PCT,
    bollinger_upper_band_pct: float = BOLLINGER_UPPER_BAND_PCT,
    ma_distance_overbought_pct: float = MA_DISTANCE_OVERBOUGHT_PCT,
    ma_short_window: int = MA_SHORT_WINDOW,
    ma_long_window: int = MA_LONG_WINDOW,
    rsi_window: int = RSI_WINDOW,
    lookback_trading_days: int = LOOKBACK_TRADING_DAYS,
) -> dict:
    """Mean-reversion classification on already-fetched price inputs.

    Args:
        ticker_prices_adj_close: ordered list of ticker adjusted close
            (>= lookback_trading_days). Index [-1] = most recent.
        ... parameter overrides (defaults match module constants; production
            agent passes values from `parameters_active`).

    Returns:
        {
            'bin': 'MR_OVERSOLD' | 'MR_NEUTRAL' | 'MR_OVERBOUGHT' | 'MR_UNAVAILABLE',
            'components': {
                'drawdown_from_252d_high_pct': float,
                'rsi_14': float,
                'bollinger_band_position': float,
                'ma_distance_200d_pct': float,
                '252d_high': float,
                'prior_close': float,
            } | None,
            'sub_signal_fires': {
                'drawdown_threshold': bool,
                'rsi_oversold': bool,
                'rsi_overbought': bool,
                'bollinger_lower_extreme': bool,
                'bollinger_upper_extreme': bool,
            } | None,
            'unavailable_reason': str | None,
        }

    Bin classification:
    - All-3 oversold conditions fire → 'MR_OVERSOLD'
    - All-3 overbought conditions fire → 'MR_OVERBOUGHT'
    - Otherwise → 'MR_NEUTRAL'
    - Insufficient history → 'MR_UNAVAILABLE'

    INV-3.6-A (HG-36): unavailable_reason != None IFF bin == 'MR_UNAVAILABLE'.
    INV-3.6-B (HG-36): bin == 'MR_OVERSOLD' requires all 3 oversold sub_signal_fires True.
                       bin == 'MR_OVERBOUGHT' requires all 3 overbought sub_signal_fires True.
    """
    if len(ticker_prices_adj_close) < lookback_trading_days:
        return {
            "bin": "MR_UNAVAILABLE",
            "components": None,
            "sub_signal_fires": None,
            "unavailable_reason": "insufficient_price_history",
        }

    # Compute components
    dd_pct, high_value, _ = _drawdown_from_high(ticker_prices_adj_close, lookback_trading_days)
    rsi = _rsi_wilder(ticker_prices_adj_close, rsi_window)
    bb_pos, _, _ = _bollinger_band_position(ticker_prices_adj_close, ma_short_window)
    ma_dist_pct, _ = _ma_distance_pct(ticker_prices_adj_close, ma_long_window)
    spot = ticker_prices_adj_close[-1]

    # Sub-signal fires
    drawdown_threshold = dd_pct >= drawdown_252d_threshold_pct
    rsi_oversold = rsi <= rsi_14_oversold_threshold
    rsi_overbought = rsi >= rsi_14_overbought_threshold
    bollinger_lower_extreme = bb_pos <= bollinger_lower_band_pct
    bollinger_upper_extreme = bb_pos >= bollinger_upper_band_pct
    ma_distance_overbought = ma_dist_pct >= ma_distance_overbought_pct

    # Bin classification — AND-gates per direction
    if drawdown_threshold and rsi_oversold and bollinger_lower_extreme:
        bin_ = "MR_OVERSOLD"
    elif rsi_overbought and bollinger_upper_extreme and ma_distance_overbought:
        bin_ = "MR_OVERBOUGHT"
    else:
        bin_ = "MR_NEUTRAL"

    return {
        "bin": bin_,
        "components": {
            "drawdown_from_252d_high_pct": dd_pct,
            "rsi_14": rsi,
            "bollinger_band_position": bb_pos,
            "ma_distance_200d_pct": ma_dist_pct,
            "252d_high": high_value,
            "prior_close": spot,
        },
        "sub_signal_fires": {
            "drawdown_threshold": drawdown_threshold,
            "rsi_oversold": rsi_oversold,
            "rsi_overbought": rsi_overbought,
            "bollinger_lower_extreme": bollinger_lower_extreme,
            "bollinger_upper_extreme": bollinger_upper_extreme,
        },
        "unavailable_reason": None,
    }
