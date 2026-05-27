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

import math
from typing import Any, Sequence

from src.micro import indicators as ind

# Slow-layer 4-bin prior -> intraday directional tilt in [-1, +1].
_PRIOR_TILT = {
    "BUY": 0.30,
    "HOLD": 0.0,
    "TRIM": -0.15,
    "SELL": -0.30,
}

# Relative weights of each TA component in the directional score.
_W_TREND = 0.30
_W_MOMENTUM = 0.25
_W_VWAP = 0.20
_W_MEANREV = 0.15
_W_PRIOR = 0.10

# Softmax temperature: higher => probabilities closer to uniform (less decisive).
_TEMP = 0.45


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


def _vwap_score(bars: Sequence[dict], cl: list[float]) -> float | None:
    """Price above session VWAP => long tilt. Normalized by ~0.5%."""
    vwap = ind.session_vwap(bars)
    if vwap is None or vwap == 0 or not cl:
        return None
    return _clamp((cl[-1] - vwap) / vwap / 0.005)


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
    return {k: round(v / z, 4) for k, v in exps.items()}


def _price_ranges(
    ref: float, atr_v: float | None, direction: str, vwap: float | None
) -> dict[str, Any]:
    """ATR-anchored entry/target/stop. Falls back to % bands if ATR is None."""
    band = atr_v if atr_v and atr_v > 0 else ref * 0.004  # ~0.4% fallback
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
        "atr_used": round(band, 4),
        "vwap_anchor": round(vwap, 4) if vwap is not None else None,
    }


def compute_signal(
    bars: Sequence[dict],
    live: dict | None = None,
    prior: dict | None = None,
) -> dict[str, Any]:
    """Produce the probabilistic intraday signal payload.

    Args:
        bars: ordered intraday OHLCV bars (oldest -> newest), as emitted by the
            massive ``get_intraday_bars`` tool.
        live: optional micro-aggregate from ``stream_micro_aggregate`` (used for
            the reference price and a confidence/liquidity modifier).
        prior: optional {"summary_code": "BUY"|"HOLD"|"TRIM"|"SELL", ...} from
            the latest /research-company run for this ticker.

    Returns a JSON-serializable dict (see /micro command for the rendered card).
    """
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
            "message": f"need >=5 intraday bars, got {len(cl)}",
            "primary": "HOLD",
            "probabilities": {"long": 0.0, "short": 0.0, "hold": 1.0},
            "reference_price": ref,
            "prior_used": {"summary_code": prior_code},
        }

    trend = _trend_score(cl)
    meanrev = _meanrev_score(cl)
    # Regime gate: mean-reversion (Bollinger fade) only makes sense in a
    # range-bound tape. In a strong trend, price riding the upper/lower band is
    # *continuation*, not a reversal signal — so we damp the fade in proportion
    # to trend strength. At |trend|=1 the fade is fully suppressed; at trend~0
    # (chop) it carries full weight.
    if trend is not None and meanrev is not None:
        meanrev = meanrev * (1.0 - abs(trend))

    components: dict[str, float | None] = {
        "trend": trend,
        "momentum": _momentum_score(cl),
        "vwap": _vwap_score(bars, cl),
        "meanrev": meanrev,
    }
    prior_tilt = _PRIOR_TILT.get(prior_code, 0.0) if prior_code else 0.0

    weights = {
        "trend": _W_TREND,
        "momentum": _W_MOMENTUM,
        "vwap": _W_VWAP,
        "meanrev": _W_MEANREV,
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

    primary = max(probs, key=probs.get).upper()

    atr_v = ind.atr(bars, 14)
    vwap = ind.session_vwap(bars)
    o_range = ind.opening_range(bars, 30)

    directions = {
        "LONG": _price_ranges(ref, atr_v, "long", vwap),
        "SHORT": _price_ranges(ref, atr_v, "short", vwap),
        "HOLD": {"note": "stand aside; re-check on the next /micro pull"},
    }

    return {
        "status": "ok",
        "reference_price": round(ref, 4),
        "primary": primary,
        "probabilities": probs,
        "confidence": confidence,
        "directional_score": round(directional, 4),
        "indicators": {
            "rsi14": _round(ind.rsi(cl, 14)),
            "macd_hist": _round(ind.macd(cl)[2]) if ind.macd(cl) else None,
            "ema9": _round(ind.ema(cl, 9)),
            "ema20": _round(ind.ema(cl, 20)),
            "ema50": _round(ind.ema(cl, 50)),
            "session_vwap": _round(vwap),
            "atr14": _round(atr_v),
            "bollinger_pct_b": _round(ind.bollinger_pct_b(cl, 20, 2.0)),
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
