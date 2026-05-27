"""Inner-ring sanity tests for the /micro intraday signal helper.

Scope (CLAUDE.md P14, "build inner before outer"): a handful of off-by-one /
weighting checks on the deterministic cores — RSI window, ATR seed, VWAP
dollar-weighting — plus the LONG/SHORT/HOLD model's contract (probabilities
sum to 1; trend + prior agree => LONG; insufficient data => HOLD). Not a
coverage suite; there is no outer-ring scoring wired against this module yet.
"""

from __future__ import annotations

from src.micro import indicators as ind
from src.micro.signal_model import compute_signal


def _bar(c, h=None, l=None, v=1000, vw=None):
    h = c if h is None else h
    l = c if l is None else l
    return {"open": c, "high": h, "low": l, "close": c, "volume": v, "vwap": vw}


def test_rsi_all_gains_is_100():
    closes = list(range(1, 30))  # strictly increasing -> avg_loss 0 -> RSI 100
    assert ind.rsi(closes, 14) == 100.0


def test_rsi_needs_window_plus_one():
    assert ind.rsi([1, 2, 3], 14) is None


def test_atr_constant_true_range():
    # Each bar: high-low = 2, no gaps -> TR = 2 every bar -> ATR = 2.
    bars = [_bar(c=10.0, h=11.0, l=9.0) for _ in range(20)]
    a = ind.atr(bars, 14)
    assert a is not None
    assert abs(a - 2.0) < 1e-9


def test_session_vwap_dollar_weighted():
    # Two bars: 10@100sh and 20@300sh -> (10*100 + 20*300)/(400) = 17.5
    bars = [_bar(c=10.0, v=100, vw=10.0), _bar(c=20.0, v=300, vw=20.0)]
    assert abs(ind.session_vwap(bars) - 17.5) < 1e-9


def test_probabilities_sum_to_one():
    bars = [_bar(c=100.0 + i * 0.1) for i in range(60)]
    out = compute_signal(bars, live=None, prior={"summary_code": "BUY"})
    probs = out["probabilities"]
    # Probabilities are rounded to 4 dp for display, so the sum is 1 within
    # rounding (3 values * 5e-5 max drift).
    assert abs(sum(probs.values()) - 1.0) < 1e-3


def test_uptrend_plus_buy_prior_favors_long():
    # Clean monotonic uptrend + a slow-layer BUY tilt should make LONG primary.
    bars = [_bar(c=100.0 + i * 0.25, h=100.2 + i * 0.25, l=99.8 + i * 0.25)
            for i in range(60)]
    out = compute_signal(bars, live=None, prior={"summary_code": "BUY"})
    assert out["primary"] == "LONG"
    assert out["probabilities"]["long"] >= out["probabilities"]["short"]


def test_insufficient_bars_is_hold():
    out = compute_signal([_bar(c=100.0), _bar(c=101.0)], live=None, prior=None)
    assert out["status"] == "insufficient_data"
    assert out["primary"] == "HOLD"
    assert out["probabilities"]["hold"] == 1.0


def test_price_ranges_scale_with_horizon_hours_to_day():
    # Horizon is bounded to [60min, 390min] = [1h, 1 trading day]. A 4h horizon
    # must give wider (executable) targets than 1h; sub-hour clamps to the 1h
    # floor; over-a-day clamps to the 1-day cap.
    bars = [_bar(c=100.0 + i * 0.25, h=100.4 + i * 0.25, l=99.6 + i * 0.25)
            for i in range(60)]
    h1 = compute_signal(bars, horizon_minutes=60)
    h4 = compute_signal(bars, horizon_minutes=240)
    floored = compute_signal(bars, horizon_minutes=15)    # below 60 -> 60
    capped = compute_signal(bars, horizon_minutes=2000)   # above 390 -> 390
    def width(out):
        return out["directions"]["LONG"]["target_zone"][1] - out["reference_price"]
    assert width(h4) > width(h1) > 0
    assert floored["horizon"]["minutes"] == 60.0
    assert floored["horizon"]["label"] == "1h"
    assert capped["horizon"]["minutes"] == 390.0
    assert capped["horizon"]["label"] == "1 trading day"


def test_daily_atr_anchors_the_band():
    # With a daily ATR supplied, the 1-day band equals daily ATR; shorter
    # horizons scale by sqrt(horizon/session); source is tagged daily_atr.
    bars = [_bar(c=100.0 + i * 0.1) for i in range(60)]
    day = compute_signal(bars, horizon_minutes=390, daily_atr=20.0)
    hour = compute_signal(bars, horizon_minutes=60, daily_atr=20.0)
    assert day["horizon"]["band_source"] == "daily_atr"
    assert abs(day["horizon"]["expected_move_band"] - 20.0) < 1e-6
    assert abs(hour["horizon"]["expected_move_band"] - 20.0 * (60 / 390) ** 0.5) < 1e-3


def test_wide_spread_pushes_toward_hold():
    bars = [_bar(c=100.0 + i * 0.25) for i in range(60)]
    tight = compute_signal(bars, live={"status": "ok", "spread_bps": 2}, prior=None)
    wide = compute_signal(bars, live={"status": "ok", "spread_bps": 80}, prior=None)
    assert wide["probabilities"]["hold"] >= tight["probabilities"]["hold"]
