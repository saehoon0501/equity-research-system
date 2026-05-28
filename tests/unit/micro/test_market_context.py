"""Tests for the SPY market-overlay context (relative-strength + last-hour gate).

Grounded in Tier-1 work surfaced in the /research report: Aït-Sahalia et al.
(robust intraday beta, 5-min sampling) and Gao-Han-Li-Zhou JFE 2018 (SPY first-
30min predicts last-30min). The advisor specifically asked for an orthogonality
test between `relative_strength` and the raw `trend` component — that's
`test_relative_strength_diverges_from_raw_trend` below.
"""

from __future__ import annotations

from src.micro import market_context as mc
from src.micro.signal_model import compute_signal


def _ts(minute_of_day_utc: int) -> str:
    h, m = divmod(minute_of_day_utc, 60)
    return f"2026-05-27T{h:02d}:{m:02d}:00Z"


def _bar(ts, c, v=1000):
    return {"ts": ts, "open": c, "high": c + 0.1, "low": c - 0.1, "close": c, "volume": v}


def _session_bars(prices: list[float]) -> list[dict]:
    """Build a regular-session series (13:30->19:59 UTC = 09:30->15:59 ET)."""
    return [_bar(_ts(13 * 60 + 30 + i), prices[i]) for i in range(len(prices))]


def test_late_session_gate_ramps_only_in_final_hour():
    # 14:30 ET = 18:30 UTC -> 0; 15:30 ET = 19:30 UTC -> 1.0; midpoint -> 0.5
    assert mc.late_session_gate(_ts(13 * 60 + 30)) == 0.0       # 09:30 ET
    assert mc.late_session_gate(_ts(18 * 60 + 30)) == 0.0       # 14:30 ET (gate just starts)
    assert mc.late_session_gate(_ts(19 * 60)) == 0.5            # 15:00 ET (mid-ramp)
    assert mc.late_session_gate(_ts(19 * 60 + 30)) == 1.0       # 15:30 ET (full)
    assert mc.late_session_gate(_ts(19 * 60 + 59)) == 1.0       # 15:59 ET


def test_conviction_scale_only_in_late_session_and_signed_by_agreement():
    # Outside the gate (gate=0) -> no scaling, regardless of agreement.
    assert mc.conviction_scale_from_agreement(0.5, 0.01, gate=0.0) == 1.0
    # Same-sign agreement at full gate -> boost.
    assert mc.conviction_scale_from_agreement(0.5, 0.01, gate=1.0) > 1.0
    # Disagreement at full gate -> penalty (< 1).
    assert mc.conviction_scale_from_agreement(0.5, -0.01, gate=1.0) < 1.0
    # No spy_r1 -> identity.
    assert mc.conviction_scale_from_agreement(0.5, None, gate=1.0) == 1.0


def _two_regime(late_pct: tuple[float, float], n_early: int = 80, n_late: int = 30):
    """Stock + SPY share a deterministic-noisy early window (β fits ~1 there),
    then diverge by `late_pct = (stock_total, spy_total)` over `n_late` bars.

    A smooth/constant early ramp would give zero return-variance and β would
    be undefined; the seeded-shared-noise gives β estimation something to fit.
    """
    import random
    random.seed(42)
    s_closes = [100.0]
    m_closes = [400.0]
    for _ in range(n_early):
        r = random.gauss(0.0001, 0.002)  # shared 1-min return: ~bps mean, σ 20bps
        s_closes.append(s_closes[-1] * (1 + r))
        m_closes.append(m_closes[-1] * (1 + r))
    s_step = late_pct[0] / n_late
    m_step = late_pct[1] / n_late
    for _ in range(n_late):
        s_closes.append(s_closes[-1] * (1 + s_step))
        m_closes.append(m_closes[-1] * (1 + m_step))
    return _session_bars(s_closes), _session_bars(m_closes)


def test_relative_strength_diverges_from_raw_trend():
    # Two-regime: 80 bars where stock and SPY move together (β fits ~1),
    # then 30 bars where the STOCK LAGS the market move. Both raw trends are
    # still positive at the session level, but the *idiosyncratic* recent move
    # is NEGATIVE — this is the orthogonality the advisor specifically asked for.
    stock, spy = _two_regime(late_pct=(0.0, 0.01))
    rs = mc.relative_strength(stock, spy, recent_window_minutes=30)
    assert rs is not None
    # Stock recent return ≈ 0, SPY recent ≈ +1% -> residual negative.
    assert rs["spy_return_pct"] > 0
    assert rs["residual_pct"] < 0
    assert rs["score"] < 0


def test_relative_strength_positive_when_stock_outperforms():
    # Mirror: stock and SPY move together early; stock SURGES in the recent
    # window beyond what β predicts -> RS positive.
    stock, spy = _two_regime(late_pct=(0.015, 0.005))
    rs = mc.relative_strength(stock, spy, recent_window_minutes=30)
    assert rs is not None and rs["score"] > 0


def test_compute_signal_runs_without_spy_bars_unchanged():
    # spy_bars=None: market_context block reports null payloads, no crash.
    bars = _session_bars([100.0 + i * 0.05 for i in range(60)])
    out = compute_signal(bars, prior=None, daily_atr=5.0)
    assert out["market_context"]["relative_strength"] is None
    assert out["market_context"]["spy_first30"] is None
    # conviction scale defaults to 1.0 when no spy_r1.
    assert out["market_context"]["conviction_scale"] == 1.0


def test_compute_signal_with_spy_overlay_adds_rs_component():
    # Two-regime: stock surges in the recent window vs SPY -> RS component > 0.
    bars, spy = _two_regime(late_pct=(0.015, 0.005))
    out = compute_signal(bars, prior=None, daily_atr=5.0, spy_bars=spy)
    cs = out["indicators"]["component_scores"]
    assert cs.get("relative_strength") is not None
    assert cs["relative_strength"] > 0
    assert out["market_context"]["relative_strength"] is not None
    assert out["market_context"]["conviction_scale"] >= 0
