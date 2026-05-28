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
    # hold is derived as 1 - long - short, so the three sum to exactly 1.0.
    assert abs(sum(probs.values()) - 1.0) < 1e-9


def test_uptrend_plus_buy_prior_favors_long():
    # Clean monotonic uptrend + a slow-layer BUY tilt should make LONG primary.
    # NOTE: the slope is gentle by design — a steep ramp (e.g. +0.25/bar over
    # 60 bars = +14.7%) pushes the final close ~6%+ above session VWAP, which
    # is the stretched-fade zone the patched _vwap_score correctly flips to a
    # short-bias on (alignment 2026-05-27 MU replay). The "uptrend favors long"
    # invariant we want to assert is for moderate trending, not for parabolic
    # gappers; +0.05/bar = +3% total keeps the close ~1.5% above VWAP, well
    # inside the continuation regime.
    bars = [_bar(c=100.0 + i * 0.05, h=100.2 + i * 0.05, l=99.8 + i * 0.05)
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


def test_stretched_above_vwap_flips_to_fade():
    """Alignment lock-in (MU 2026-05-27): when price is >>0.5x ATR above VWAP,
    the vwap component must contribute a FADE (negative) signal, not pure
    continuation. The pre-alignment behavior gave vwap=+1.0 on a parabolic
    gap-up, which is what caused /micro to LONG-lean at the dead-cat-bounce
    short entry. The patched behavior flips sign past stretch threshold."""
    # 60 bars rising from $900 -> $960 with the last 5 bars spiking to $1000.
    # Session VWAP will be ~$935, last close $1000 => +7%, well past
    # stretch_full (5% with no atr; ~3.2% with atr=20 on $1000).
    bars = []
    for i in range(55):
        c = 900.0 + i * 0.5
        bars.append(_bar(c=c, h=c + 1.0, l=c - 1.0))
    for c in (970.0, 980.0, 990.0, 995.0, 1000.0):
        bars.append(_bar(c=c, h=c + 1.0, l=c - 1.0))
    out = compute_signal(bars, live=None, prior=None, daily_atr=20.0)
    vwap_score = out["indicators"]["component_scores"]["vwap"]
    assert vwap_score is not None and vwap_score < 0, (
        f"stretched-above-VWAP must signal FADE (negative vwap score); "
        f"got {vwap_score} (model would call parabolic gap-up as LONG-continuation)"
    )


def test_oversold_at_support_dampens_directional():
    """Alignment lock-in (MU 2026-05-27 exit case): when RSI<32 + %B<0.05
    (oversold-at-lower-band exhaustion), |directional| must shrink by ~half so
    HOLD probability rises. This is the model's 'cover the winning short'
    signal at gap-fill / strong support."""
    # 60 bars trending DOWN sharply then flattening at the lows — produces low
    # RSI and %B near/below the lower band.
    bars = []
    for i in range(40):
        c = 1000.0 - i * 4.0  # drop from 1000 to ~840
        bars.append(_bar(c=c, h=c + 1.5, l=c - 2.0, v=400000))
    for i in range(20):
        c = 840.0 - i * 0.5  # slow flush to ~830
        bars.append(_bar(c=c, h=c + 1.0, l=c - 1.5, v=600000))
    out = compute_signal(bars, live=None, prior=None)
    # The patched model must give HOLD when oversold + at lower band, because
    # the exhaustion dampener halves directional magnitude.
    assert out["primary"] == "HOLD", (
        f"oversold-at-lower-band must dampen toward HOLD; got primary={out['primary']} "
        f"(directional={out['directional_score']}, RSI={out['indicators']['rsi14']}, "
        f"%B={out['indicators']['bollinger_pct_b']})"
    )
    # Sanity: the model should still see DOWN bias (just less convicted)
    assert out["probabilities"]["short"] >= out["probabilities"]["long"], (
        f"oversold dampener must preserve direction sign; "
        f"got long={out['probabilities']['long']} short={out['probabilities']['short']}"
    )
