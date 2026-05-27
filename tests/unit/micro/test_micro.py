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


def test_wide_spread_pushes_toward_hold():
    bars = [_bar(c=100.0 + i * 0.25) for i in range(60)]
    tight = compute_signal(bars, live={"status": "ok", "spread_bps": 2}, prior=None)
    wide = compute_signal(bars, live={"status": "ok", "spread_bps": 80}, prior=None)
    assert wide["probabilities"]["hold"] >= tight["probabilities"]["hold"]
