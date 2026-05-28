"""Cross-asset market overlay for /micro: SPY-beta residual + intraday-momentum gate.

Single-ticker OHLCV misses two well-documented intraday signals:

  - **Beta-residual / relative strength** (Aït-Sahalia et al. 2023; standard
    practice): rolling 5-min realized beta of the name vs SPY; the residual
    return (stock − β · SPY) is the *idiosyncratic* move — by construction
    independent of the raw price-momentum component.

  - **Market intraday momentum** (Gao, Han, Li, Zhou, JFE 2018): the SPY
    first-half-hour return predicts the **last** half-hour. The published
    mechanism is r1 → r13 specifically — *not* an all-afternoon term. We
    therefore apply r1_SPY as a CONFIDENCE gate that ramps from 0 at ~14:30 ET
    to 1.0 by ~15:30 ET (not as an additive directional component, which would
    extrapolate the 30-min effect across hours).

5-min sampling for β follows Aït-Sahalia: 1-min has too much microstructure
noise for clean realized covariance. All series are filtered to a single ET
calendar day before computing — never beta across an overnight gap.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Sequence

from src.micro import sessions

# Gao et al.'s mechanism is the LAST half-hour. Confidence boost ramps in
# during the final hour of the regular session.
_GATE_START_ET_MIN = 14 * 60 + 30  # 14:30 ET — gate begins ramping
_GATE_FULL_ET_MIN = 15 * 60 + 30   # 15:30 ET — gate fully on
# Bounded confidence adjustment: ±20% of conviction at full ramp.
_MAX_CONVICTION_SCALE = 0.20


def _bars_in_latest_session(bars: Sequence[dict]) -> list[dict]:
    """Drop pre/after-hours and stitched earlier sessions; keep one regular day."""
    return sessions.filter_session(bars, "regular")


def _resample_5min_returns(bars: Sequence[dict]) -> list[float]:
    """5-min returns built by taking every 5th 1-min close (closes already
    reflect within-bar trades). Returns are simple percentage returns.
    """
    closes: list[float] = []
    for i, b in enumerate(bars):
        if i % 5 != 0:
            continue
        try:
            closes.append(float(b.get("close")))
        except (TypeError, ValueError):
            continue
    return [(closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes)) if closes[i - 1]]


def _windowed_return(bars: Sequence[dict], window_bars: int) -> float | None:
    """Return over the last `window_bars` 1-min bars (close-to-close)."""
    if len(bars) < window_bars + 1:
        return None
    try:
        start = float(bars[-window_bars - 1]["close"])
        end = float(bars[-1]["close"])
    except (TypeError, ValueError, KeyError):
        return None
    if not start:
        return None
    return (end - start) / start


def relative_strength(
    stock_bars: Sequence[dict],
    spy_bars: Sequence[dict],
    recent_window_minutes: int = 60,
) -> dict | None:
    """SPY-beta-residual relative-strength score in [-1, +1] (or None if
    insufficient overlapping latest-session data).

    Procedure:
      1. Filter both series to the latest regular session.
      2. β estimated on 5-min realized returns over the full intersected window
         (5-min sampling per Ait-Sahalia 2023 — 1-min has too much micro noise).
      3. Residual = (stock 1h return) − β · (SPY 1h return), both close-to-close
         over the last `recent_window_minutes` 1-min bars.
      4. Score = clamp(residual / 0.01, -1, +1) — a ±1% residual saturates.

    Returns {"score", "beta", "residual_pct", "stock_return_pct", "spy_return_pct"}.
    """
    s = _bars_in_latest_session(stock_bars)
    m = _bars_in_latest_session(spy_bars)
    if len(s) < 30 or len(m) < 30:
        return None

    # Build 5-min returns on the SHORTER overlap (truncate to common length).
    n = min(len(s), len(m))
    s_ret = _resample_5min_returns(s[-n:])
    m_ret = _resample_5min_returns(m[-n:])
    k = min(len(s_ret), len(m_ret))
    if k < 12:  # need >= 1h of 5-min returns
        return None
    s_ret = s_ret[-k:]
    m_ret = m_ret[-k:]

    # Fit β on the HISTORICAL window only — exclude the 5-min returns that
    # overlap the recent prediction window. If β saw the divergence we want
    # to detect, it would absorb it and residual would be ~0 by construction
    # (the OLS-residual-orthogonality trap the advisor flagged).
    recent_5m = max(1, recent_window_minutes // 5)
    hist_end = k - recent_5m
    if hist_end < 8:  # need a usable historical window
        # Not enough history to separate β from the recent window; fall back
        # to full-window β (degraded; residual will tend toward 0).
        s_hist, m_hist = s_ret, m_ret
    else:
        s_hist, m_hist = s_ret[:hist_end], m_ret[:hist_end]
    kh = len(s_hist)
    mean_m = sum(m_hist) / kh
    var_m = sum((r - mean_m) ** 2 for r in m_hist) / kh
    if var_m <= 0:
        return None
    mean_s = sum(s_hist) / kh
    cov = sum((s_hist[i] - mean_s) * (m_hist[i] - mean_m) for i in range(kh)) / kh
    beta = cov / var_m

    # Recent 1-min-window cumulative return for both — the "is the stock
    # outperforming the market right now" measurement that the score expresses.
    stock_ret = _windowed_return(s, recent_window_minutes)
    spy_ret = _windowed_return(m, recent_window_minutes)
    if stock_ret is None or spy_ret is None:
        return None
    residual = stock_ret - beta * spy_ret
    score = max(-1.0, min(1.0, residual / 0.01))  # saturate at ±1%
    return {
        "score": score,
        "beta": round(beta, 4),
        "residual_pct": round(residual * 100, 3),
        "stock_return_pct": round(stock_ret * 100, 3),
        "spy_return_pct": round(spy_ret * 100, 3),
    }


def spy_first30_return(spy_bars: Sequence[dict]) -> dict | None:
    """SPY's first-30-min return in the latest regular session, or None.

    r1 = (close at 10:00 ET − previous-day close) / previous-day close — matches
    the Gao et al. (JFE 2018) definition (previous-close → 10:00, not 09:30→10:00).
    """
    m = _bars_in_latest_session(spy_bars)
    if not m:
        return None
    # The 10:00 ET bar is the first one with ET minute >= 10:00 = 600.
    ten_am_bar = None
    for b in m:
        if sessions._et_minutes(b.get("ts")) is not None and sessions._et_minutes(b.get("ts")) >= 10 * 60:
            ten_am_bar = b
            break
    if ten_am_bar is None:
        return None
    try:
        ten_am_close = float(ten_am_bar["close"])
    except (TypeError, ValueError, KeyError):
        return None
    # Previous-day close: latest bar in spy_bars NOT in this session's date.
    latest_date = sessions._et_date(m[-1].get("ts"))
    prev_close = None
    for b in reversed(spy_bars):
        d = sessions._et_date(b.get("ts"))
        if d is None or d == latest_date:
            continue
        try:
            prev_close = float(b["close"])
            break
        except (TypeError, ValueError, KeyError):
            continue
    if prev_close is None or prev_close <= 0:
        return None
    r1 = (ten_am_close - prev_close) / prev_close
    return {"r1": round(r1, 6), "prev_close": prev_close, "ten_am_close": ten_am_close}


def late_session_gate(reference_ts: Any) -> float:
    """Linear ramp from 0 at 14:30 ET to 1.0 at 15:30 ET (then 1.0).

    Gates the SPY-r1 confidence modifier so the gate is *only* active in
    the last hour — faithful to Gao et al.'s last-30-min mechanism, not
    extrapolated across the full afternoon.
    """
    m = sessions._et_minutes(reference_ts)
    if m is None or m < _GATE_START_ET_MIN:
        return 0.0
    if m >= _GATE_FULL_ET_MIN:
        return 1.0
    return (m - _GATE_START_ET_MIN) / (_GATE_FULL_ET_MIN - _GATE_START_ET_MIN)


def conviction_scale_from_agreement(
    directional: float, r1_spy: float | None, gate: float
) -> float:
    """Multiplicative adjustment to `conviction` from market-momentum agreement.

    Returns a factor in [1 - MAX, 1 + MAX] (defaults to ±0.20). Agreement
    (same sign of directional and r1_spy) BOOSTS conviction; disagreement
    REDUCES it (raising the implicit HOLD floor). Scaled by `gate` so the
    effect is 0 before 14:30 ET.
    """
    if r1_spy is None or gate <= 0:
        return 1.0
    if abs(directional) < 1e-6 or abs(r1_spy) < 1e-9:
        return 1.0
    same_sign = (directional > 0) == (r1_spy > 0)
    delta = _MAX_CONVICTION_SCALE * gate * (1.0 if same_sign else -1.0)
    return 1.0 + delta
