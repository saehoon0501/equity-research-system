"""Probabilistic LONG/SHORT/HOLD model for the /micro intraday helper.

Fuses the technical-indicator panel (``indicators.py``) computed over an
intraday bar series with an optional slow-layer *prior* (the latest
/research-company ``summary_code`` for the ticker) and a live websocket
micro-aggregate (for confidence/confirmation), then emits:

  - probabilities over {long, short, hold} (softmax; sum to 1),
  - a primary direction and a confidence score,
  - ATR-anchored price ranges (entry zone / target / stop) per actionable
    direction.

Design stance (documented so it isn't "tuned away" later):
  * Intraday technicals DOMINATE. The /research-company prior is a *bias* term,
    not a veto — a day-trader can fade a multi-month BUY intraday. The prior
    nudges; it does not decide.
  * The slow layer is long-only (BUY/HOLD/TRIM/SELL). We map that onto a small
    directional tilt: BUY -> mild long tilt, SELL/TRIM -> mild short/avoid-long
    tilt, HOLD/none -> neutral. This is the P9 lane boundary in code: we read
    the 4-bin prior but emit only LONG/SHORT/HOLD, never the reverse.
  * Conflict and thin liquidity push probability toward HOLD, not toward a
    coin-flip between LONG and SHORT.

No I/O — pure function of its inputs, unit-tested in tests/unit/micro.
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Sequence

from src.micro import indicators as ind
from src.micro import sessions

# Slow-layer 4-bin prior -> intraday directional tilt in [-1, +1].
_PRIOR_TILT = {
    "BUY": 0.30,
    "HOLD": 0.0,
    "TRIM": -0.15,
    "SELL": -0.30,
}

# Relative weights of each component in the directional score. Kept close to
# equal-weight on purpose: optimized signal weights overfit and fail OOS
# (DeMiguel-Garlappi-Uppal 2009; data-snooping critique Sullivan-Timmermann-White
# 1999). `flow` is the synthesized Flow-Pressure indicator (BVC signed volume +
# CMF) — the volume-bearing, OHLCV-native order-flow proxy, independent of the
# price-only trend/momentum terms.
_W_TREND = 0.25
_W_MOMENTUM = 0.20
_W_VWAP = 0.15
_W_MEANREV = 0.10
_W_FLOW = 0.20
_W_PRIOR = 0.10

# Softmax temperature: higher => probabilities closer to uniform (less decisive).
_TEMP = 0.45

# Trade-horizon bounds. Price ranges scale to a holding horizon so targets are
# executable. Microstructure research (2026-05-27) is decisive that minute-scale
# intraday targets are eaten by spread + impact + noise (round trip must clear
# ~2x effective spread; sub-minute moves ARE the bid-ask bounce a taker pays,
# not earns — Bessembinder-Venkataraman 2009, Kyle-Obizhaeva 2018) and that
# minute-scale backtested edges are the max-overfitting regime (López de Prado
# 2014). So the floor is HOURS, not minutes; the cap is one trading day.
#   floor   = 60 min  (1 hour — "no min but hours at least")
#   session = 390 min (one regular US session = the "1 day" cap)
# Volatility is anchored on DAILY ATR scaled by sqrt(horizon/session): the
# sqrt-of-time rule breaks under jumps/serial-correlation and a 1-min ATR is
# inflated by microstructure noise (Danielsson-Zigrand), so daily ATR is the
# robust unit. Falls back to intraday-ATR sqrt-time only when daily ATR is absent.
_MIN_HORIZON_MINUTES = 60.0
_SESSION_MINUTES = 390.0
_DEFAULT_HORIZON_MINUTES = 120.0


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _trend_score(cl: list[float]) -> float | None:
    """EMA stack (9>20>50 => up). Returns tilt in [-1, 1]."""
    e9, e20, e50 = ind.ema(cl, 9), ind.ema(cl, 20), ind.ema(cl, 50)
    if e9 is None or e20 is None:
        return None
    score = 0.0
    score += 0.5 if e9 > e20 else -0.5
    if e50 is not None:
        score += 0.25 if e20 > e50 else -0.25
        score += 0.25 if cl[-1] > e50 else -0.25
    else:
        score += 0.5 if cl[-1] > e20 else -0.5
    return _clamp(score)


def _momentum_score(cl: list[float]) -> float | None:
    """RSI distance from 50 + MACD histogram sign. Tilt in [-1, 1]."""
    r = ind.rsi(cl, 14)
    parts: list[float] = []
    if r is not None:
        parts.append(_clamp((r - 50.0) / 30.0))  # 80->+1, 20->-1
    m = ind.macd(cl)
    if m is not None:
        _, _, hist = m
        parts.append(_clamp(hist * 5.0))  # sign-dominant, saturates quickly
    if not parts:
        return None
    return _clamp(sum(parts) / len(parts))


def _vwap_score(
    bars: Sequence[dict],
    cl: list[float],
    daily_atr: float | None = None,
) -> float | None:
    """Price-vs-VWAP score with stretched-fade reversal.

    Normal zone (price within ~0.5x daily-ATR % of VWAP): pure continuation —
    above VWAP is bullish, below is bearish.

    Stretched zone (beyond ~1.5x daily-ATR %): the sign FLIPS to a fade signal.
    Across [stretch_start, stretch_full] the score smoothly transitions from
    continuation to fade. Pure continuation reads a parabolic gap-up as a
    strong-long when it's actually exhaustion — the MU 2026-05-27 replay
    found the model gave vwap=+1.0 at $935 (5.2% above session VWAP) when the
    setup was a textbook gap-fade short. This piecewise function corrects that
    blind spot without making the call deterministic — past stretch, the
    signal just flips, the magnitude is still bounded.

    Without daily_atr, falls back to fixed % thresholds (2.5%/7.5%) — wider
    than the ATR-anchored version on quiet names but safe.
    """
    vwap = ind.session_vwap(bars)
    if vwap is None or vwap == 0 or not cl:
        return None
    raw_pct = (cl[-1] - vwap) / vwap
    cont = _clamp(raw_pct / 0.005)  # normal continuation regime

    if daily_atr and daily_atr > 0 and cl[-1] > 0:
        atr_pct = daily_atr / cl[-1]
        stretch_start = 0.5 * atr_pct
        stretch_full = 1.5 * atr_pct
    else:
        stretch_start = 0.025
        stretch_full = 0.075

    abs_pct = abs(raw_pct)
    if abs_pct <= stretch_start:
        return cont
    span = max(1e-9, stretch_full - stretch_start)
    fade_fraction = _clamp((abs_pct - stretch_start) / span, 0.0, 1.0)
    return _clamp((1.0 - fade_fraction) * cont + fade_fraction * (-cont))


def _meanrev_score(cl: list[float]) -> float | None:
    """Bollinger %B as a *fade* signal: near upper band => short tilt."""
    pb = ind.bollinger_pct_b(cl, 20, 2.0)
    if pb is None:
        return None
    # %B 1.0 (upper) -> -1 (fade/short); 0.0 (lower) -> +1 (fade/long).
    return _clamp((0.5 - pb) * 2.0)


def _softmax3(long_l: float, short_l: float, hold_l: float) -> dict[str, float]:
    logits = {"long": long_l, "short": short_l, "hold": hold_l}
    m = max(logits.values())
    exps = {k: math.exp((v - m) / _TEMP) for k, v in logits.items()}
    z = sum(exps.values())
    # Round long/short, then set hold = 1 - long - short so the three always sum
    # to exactly 1.0 (independent rounding would leave 0.9999 / 1.0001).
    p_long = round(exps["long"] / z, 4)
    p_short = round(exps["short"] / z, 4)
    p_hold = round(1.0 - p_long - p_short, 4)
    return {"long": p_long, "short": p_short, "hold": p_hold}


def _price_ranges(
    ref: float, band: float, direction: str, vwap: float | None
) -> dict[str, Any]:
    """Entry/target/stop anchored on a horizon-scaled volatility ``band``.

    ``band`` is the expected price move over the trade horizon (per-bar ATR
    scaled by sqrt(horizon/bar) — see ``compute_signal``), NOT a single 1-minute
    ATR. That keeps the levels executable: a 1-min ATR (~$0.7 on a $900 name)
    produces tick-width targets nobody can trade; a 30-min band is ~$3-4.
    """
    if direction == "long":
        entry = (round(ref - 0.25 * band, 4), round(ref + 0.10 * band, 4))
        target = (round(ref + 1.0 * band, 4), round(ref + 1.8 * band, 4))
        stop = round(ref - 1.0 * band, 4)
    elif direction == "short":
        entry = (round(ref - 0.10 * band, 4), round(ref + 0.25 * band, 4))
        target = (round(ref - 1.8 * band, 4), round(ref - 1.0 * band, 4))
        stop = round(ref + 1.0 * band, 4)
    else:
        return {"note": "no actionable range for HOLD"}
    return {
        "entry_zone": entry,
        "target_zone": target,
        "stop": stop,
        "band_used": round(band, 4),
        "vwap_anchor": round(vwap, 4) if vwap is not None else None,
    }


def _infer_bar_minutes(bars: Sequence[dict]) -> float:
    """Median minutes between consecutive bar timestamps (default 1.0)."""
    ts = [b.get("ts") for b in bars if b.get("ts")]
    deltas: list[float] = []
    for a, b in zip(ts, ts[1:]):
        try:
            ta = _dt.datetime.fromisoformat(str(a).replace("Z", "+00:00"))
            tb = _dt.datetime.fromisoformat(str(b).replace("Z", "+00:00"))
            d = (tb - ta).total_seconds() / 60.0
            if d > 0:
                deltas.append(d)
        except (ValueError, TypeError):
            continue
    if not deltas:
        return 1.0
    deltas.sort()
    return deltas[len(deltas) // 2] or 1.0


def compute_signal(
    bars: Sequence[dict],
    live: dict | None = None,
    prior: dict | None = None,
    horizon_minutes: float = _DEFAULT_HORIZON_MINUTES,
    daily_atr: float | None = None,
    session: str = "regular",
) -> dict[str, Any]:
    """Produce the probabilistic intraday signal payload.

    Args:
        bars: ordered intraday OHLCV bars (oldest -> newest), as emitted by the
            massive ``get_intraday_bars`` tool. Pass the FULL day's series
            (incl. pre/after) so the after-hours move can be annotated.
        live: optional micro-aggregate from ``stream_micro_aggregate`` (used for
            the reference price and a confidence/liquidity modifier).
        prior: optional {"summary_code": "BUY"|"HOLD"|"TRIM"|"SELL", ...} from
            the latest /research-company run for this ticker.
        horizon_minutes: intended holding horizon for the price ranges, clamped
            to [60 min, 390 min] (1 hour floor → 1 trading day cap). Entry/
            target/stop scale to the expected move over this window.
        daily_atr: optional daily ATR (robust volatility unit). When given, the
            band = daily_atr * sqrt(horizon/session); else falls back to
            intraday ATR * sqrt(horizon/bar_minutes).
        session: bar scope for the indicators — "regular" (default; 09:30–16:00
            ET), "extended" (pre+regular+after), or "all". After-hours is thin
            and reverts, so it's excluded by default and surfaced as an
            annotation. Bars without timestamps are not filtered.

    Returns a JSON-serializable dict (see /micro command for the rendered card).
    """
    # Annotate the after-hours move from the FULL series, then scope the bars
    # the indicators see to `session` (default regular-only).
    after_hours = sessions.after_hours_annotation(bars)
    full_bar_count = len(bars)
    bars = sessions.filter_session(bars, session)

    cl = ind.closes(bars)
    live = live or {}
    prior = prior or {}
    prior_code = (prior.get("summary_code") or "").upper().strip() or None

    # Reference price: prefer the live tape, else last bar close.
    ref = None
    for cand in (live.get("last_trade_price"), live.get("mid")):
        if isinstance(cand, (int, float)):
            ref = float(cand)
            break
    if ref is None and cl:
        ref = cl[-1]

    if not cl or ref is None or len(cl) < 5:
        return {
            "status": "insufficient_data",
            "message": f"need >=5 {session} bars, got {len(cl)}",
            "primary": "HOLD",
            "probabilities": {"long": 0.0, "short": 0.0, "hold": 1.0},
            "reference_price": ref,
            "prior_used": {"summary_code": prior_code},
            "session": {
                "scope": session,
                "bars_used": len(cl),
                "bars_available": full_bar_count,
                "after_hours": after_hours,
            },
        }

    trend = _trend_score(cl)
    meanrev = _meanrev_score(cl)
    # Regime gate: mean-reversion (Bollinger fade) makes most sense in a
    # range-bound tape. In a strong trend, price riding the upper/lower band is
    # mostly *continuation*, not a reversal signal — so we damp the fade by
    # trend strength. BUT keeping a 30% floor preserves fade contribution at
    # the exact gap-fade moments where the playbook needs it: parabolic gappers
    # have strong-trend EMAs by construction, and the prior zero-floor zeroed
    # out the fade exactly when it should fire (MU 2026-05-27 replay finding).
    if trend is not None and meanrev is not None:
        meanrev = meanrev * max(0.30, 1.0 - abs(trend))

    components: dict[str, float | None] = {
        "trend": trend,
        "momentum": _momentum_score(cl),
        "vwap": _vwap_score(bars, cl, daily_atr),
        "meanrev": meanrev,
        "flow": ind.flow_pressure(bars, 20),  # synthesized Flow-Pressure indicator
    }
    prior_tilt = _PRIOR_TILT.get(prior_code, 0.0) if prior_code else 0.0

    weights = {
        "trend": _W_TREND,
        "momentum": _W_MOMENTUM,
        "vwap": _W_VWAP,
        "meanrev": _W_MEANREV,
        "flow": _W_FLOW,
    }
    used_w = 0.0
    raw = 0.0
    for name, val in components.items():
        if val is not None:
            raw += weights[name] * val
            used_w += weights[name]
    # Renormalize by the weight actually available, then fold in the prior tilt.
    ta_score = (raw / used_w) if used_w > 0 else 0.0
    directional = _clamp((1 - _W_PRIOR) * ta_score + _W_PRIOR * prior_tilt)

    # Exhaustion-at-extreme dampener: oversold-at-lower-band or overbought-at-
    # upper-band tape is structurally a "wait for reversal / cover a winning
    # trade" zone, not "press the move further". Shrink |directional| toward
    # HOLD without flipping sign — preserves direction read but lowers
    # conviction so HOLD probability rises. MU 2026-05-27 replay: at the $895
    # gap-fill print, RSI 30.5 + %B -0.008 + price at prior-close magnet — model
    # had no signal for "we're at support, stop pressing the short". This
    # corrects it. Soft-prob (not hard answer) per goal.
    rsi_now = ind.rsi(cl, 14)
    pb_now = ind.bollinger_pct_b(cl, 20, 2.0)
    if rsi_now is not None and pb_now is not None:
        oversold_at_support = rsi_now < 32.0 and pb_now < 0.05
        overbought_at_resist = rsi_now > 68.0 and pb_now > 0.95
        if oversold_at_support or overbought_at_resist:
            directional = directional * 0.50

    # Confidence: agreement among available components + liquidity from live tape.
    available = [v for v in components.values() if v is not None]
    if available:
        signs = [1 if v > 0.05 else (-1 if v < -0.05 else 0) for v in available]
        nonzero = [s for s in signs if s != 0]
        agreement = abs(sum(nonzero)) / len(nonzero) if nonzero else 0.0
    else:
        agreement = 0.0
    liquidity_ok = True
    spread_bps = live.get("spread_bps")
    if isinstance(spread_bps, (int, float)) and spread_bps > 25:
        liquidity_ok = False  # wide spread => push toward HOLD
    confidence = round(agreement * (1.0 if liquidity_ok else 0.6), 3)

    # Logits: directional magnitude splits long/short; a HOLD floor rises as
    # conviction (|directional| * agreement) falls and when liquidity is poor.
    conviction = abs(directional) * (0.5 + 0.5 * agreement)
    long_l = max(0.0, directional)
    short_l = max(0.0, -directional)
    hold_l = (1.0 - conviction) * (1.0 if liquidity_ok else 1.4)
    probs = _softmax3(long_l, short_l, hold_l)

    # Highest-probability bucket; break exact ties toward HOLD (the conservative
    # call) rather than letting dict insertion order silently pick LONG.
    primary = max(probs, key=lambda k: (probs[k], k == "hold")).upper()

    atr_v = ind.atr(bars, 14)
    vwap = ind.session_vwap(bars)
    o_range = ind.opening_range(bars, 30)

    # Expected-move band for the trade horizon, clamped to [1h, 1 trading day].
    # Prefer the DAILY ATR as the volatility unit (robust); scale by
    # sqrt(horizon/session). Fall back to intraday ATR * sqrt(horizon/bar) only
    # when daily ATR is unavailable. (Rationale + research in the constants block.)
    horizon = min(_SESSION_MINUTES, max(_MIN_HORIZON_MINUTES, float(horizon_minutes)))
    bar_minutes = _infer_bar_minutes(bars)
    if daily_atr and daily_atr > 0:
        band = daily_atr * math.sqrt(horizon / _SESSION_MINUTES)
        band_source = "daily_atr"
    else:
        per_bar = atr_v if (atr_v and atr_v > 0) else ref * 0.004
        band = per_bar * math.sqrt(horizon / bar_minutes)
        band_source = "intraday_atr_sqrt_time"

    directions = {
        "LONG": _price_ranges(ref, band, "long", vwap),
        "SHORT": _price_ranges(ref, band, "short", vwap),
        "HOLD": {"note": "stand aside; re-check on the next /micro pull"},
    }

    return {
        "status": "ok",
        "reference_price": round(ref, 4),
        "primary": primary,
        "probabilities": probs,
        "confidence": confidence,
        "directional_score": round(directional, 4),
        "session": {
            "scope": session,
            "bars_used": len(bars),
            "bars_available": full_bar_count,
            "after_hours": after_hours,
        },
        "indicators": {
            "rsi14": _round(ind.rsi(cl, 14)),
            "macd_hist": _round(ind.macd(cl)[2]) if ind.macd(cl) else None,
            "ema9": _round(ind.ema(cl, 9)),
            "ema20": _round(ind.ema(cl, 20)),
            "ema50": _round(ind.ema(cl, 50)),
            "session_vwap": _round(vwap),
            "atr14": _round(atr_v),
            "bollinger_pct_b": _round(ind.bollinger_pct_b(cl, 20, 2.0)),
            "flow_pressure": _round(ind.flow_pressure(bars, 20)),
            "bvc_imbalance": _round(ind.bvc_imbalance(bars, 20)),
            "chaikin_money_flow": _round(ind.chaikin_money_flow(bars, 21)),
            "opening_range": o_range,
            "component_scores": {k: _round(v) for k, v in components.items()},
        },
        "prior_used": {
            "summary_code": prior_code,
            "tilt_applied": prior_tilt,
            "note": "slow-layer /research-company bias; intraday TA dominates",
        },
        "live_tape": {
            "status": live.get("status"),
            "tick_velocity_per_s": live.get("tick_velocity_per_s"),
            "spread_bps": spread_bps,
            "liquidity_ok": liquidity_ok,
        },
        "horizon": {
            "minutes": round(horizon, 1),
            "label": _horizon_label(horizon),
            "bar_minutes": round(bar_minutes, 2),
            "expected_move_band": round(band, 4),
            "band_source": band_source,
            "daily_atr": _round(daily_atr),
            "bounds": {"floor_min": _MIN_HORIZON_MINUTES, "cap_min": _SESSION_MINUTES},
            "note": "floor 1h, cap 1 trading day; band scaled to holding horizon",
        },
        "directions": directions,
        "vocabulary_note": (
            "LONG/SHORT/HOLD is the intraday day-trading lane (CLAUDE.md P9 "
            "carveout) — NOT the slow-layer BUY/HOLD/TRIM/SELL portfolio decision."
        ),
    }


def _round(v: Any, n: int = 4) -> Any:
    if isinstance(v, (int, float)):
        return round(v, n)
    return v


def _horizon_label(minutes: float) -> str:
    if minutes >= _SESSION_MINUTES:
        return "1 trading day"
    hours = minutes / 60.0
    if abs(hours - round(hours)) < 1e-6:  # whole hours, robust to float dust
        return f"{round(hours)}h"
    return f"{int(round(minutes))}m"
