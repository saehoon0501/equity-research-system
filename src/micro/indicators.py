"""Pure technical-indicator math for the /micro intraday signal.

Every function is a deterministic transform of a price/bar series — no I/O, no
network, no global state — so the inner-ring unit tests (CLAUDE.md P14) can
verify them in <1s. Insufficient-data cases return ``None`` rather than raising;
callers treat ``None`` as "indicator unavailable, abstain".

A "bar" is a dict with float-ish ``open/high/low/close/volume`` and optional
``vwap`` (see ``src/mcp/massive/server.py:get_intraday_bars`` output shape).
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence


def _norm_cdf(x: float) -> float:
    """Standard-normal CDF via erf (no scipy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _floats(values: Iterable) -> list[float]:
    out: list[float] = []
    for v in values:
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def closes(bars: Sequence[dict]) -> list[float]:
    return _floats(b.get("close") for b in bars)


def sma(values: Sequence[float], window: int) -> float | None:
    vals = _floats(values)
    if window <= 0 or len(vals) < window:
        return None
    return sum(vals[-window:]) / window


def ema(values: Sequence[float], window: int) -> float | None:
    vals = _floats(values)
    if window <= 0 or len(vals) < window:
        return None
    k = 2.0 / (window + 1)
    # Seed with the SMA of the first `window` points, then walk forward.
    e = sum(vals[:window]) / window
    for v in vals[window:]:
        e = v * k + e * (1 - k)
    return e


def rsi(values: Sequence[float], window: int = 14) -> float | None:
    """Wilder's RSI in [0, 100]. Needs at least window+1 closes."""
    vals = _floats(values)
    if len(vals) < window + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, window + 1):
        delta = vals[i] - vals[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / window
    avg_loss = losses / window
    # Wilder smoothing over the remainder.
    for i in range(window + 1, len(vals)):
        delta = vals[i] - vals[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (window - 1) + gain) / window
        avg_loss = (avg_loss * (window - 1) + loss) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float, float, float] | None:
    """Return (macd_line, signal_line, histogram) or None.

    Builds the MACD line as a series so the signal EMA has something to chew on.
    """
    vals = _floats(values)
    if len(vals) < slow + signal:
        return None

    def ema_series(series: list[float], window: int) -> list[float]:
        k = 2.0 / (window + 1)
        out = [sum(series[:window]) / window]
        for v in series[window:]:
            out.append(v * k + out[-1] * (1 - k))
        return out

    fast_e = ema_series(vals, fast)
    slow_e = ema_series(vals, slow)
    # Align tails (fast EMA series is longer than slow's).
    n = min(len(fast_e), len(slow_e))
    macd_line = [fast_e[-n:][i] - slow_e[-n:][i] for i in range(n)]
    if len(macd_line) < signal:
        return None
    signal_e = ema_series(macd_line, signal)
    macd_v = macd_line[-1]
    signal_v = signal_e[-1]
    return (macd_v, signal_v, macd_v - signal_v)


def atr(bars: Sequence[dict], window: int = 14) -> float | None:
    """Wilder's Average True Range. Needs at least window+1 bars."""
    rows = [b for b in bars if b.get("high") is not None and b.get("low") is not None]
    if len(rows) < window + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(rows)):
        high = float(rows[i]["high"])
        low = float(rows[i]["low"])
        prev_close = float(rows[i - 1]["close"])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if len(trs) < window:
        return None
    a = sum(trs[:window]) / window
    for tr in trs[window:]:
        a = (a * (window - 1) + tr) / window
    return a


def bollinger_pct_b(
    values: Sequence[float], window: int = 20, k: float = 2.0
) -> float | None:
    """%B = (price - lower) / (upper - lower). ~0 at lower band, ~1 at upper."""
    vals = _floats(values)
    if len(vals) < window:
        return None
    window_vals = vals[-window:]
    mean = sum(window_vals) / window
    var = sum((v - mean) ** 2 for v in window_vals) / window
    std = var ** 0.5
    if std == 0:
        return 0.5
    upper = mean + k * std
    lower = mean - k * std
    return (vals[-1] - lower) / (upper - lower)


def session_vwap(bars: Sequence[dict]) -> float | None:
    """Dollar-volume-weighted average price across the bar series.

    Uses each bar's own ``vwap`` weighted by volume when present, else the
    bar's typical price (H+L+C)/3. Returns None if there is no volume.
    """
    num = 0.0
    den = 0.0
    for b in bars:
        vol = b.get("volume")
        if vol is None:
            continue
        try:
            vol = float(vol)
        except (TypeError, ValueError):
            continue
        if vol <= 0:
            continue
        if b.get("vwap") is not None:
            px = float(b["vwap"])
        elif all(b.get(k) is not None for k in ("high", "low", "close")):
            px = (float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0
        else:
            continue
        num += px * vol
        den += vol
    if den == 0:
        return None
    return num / den


def _money_flow_multiplier(bar: dict) -> float | None:
    """Close Location Value: ((C-L)-(H-C))/(H-L), in [-1, +1]. None if H==L."""
    try:
        h, low, c = float(bar["high"]), float(bar["low"]), float(bar["close"])
    except (KeyError, TypeError, ValueError):
        return None
    rng = h - low
    if rng <= 0:
        return 0.0  # no intrabar range -> neutral
    return ((c - low) - (h - c)) / rng


def chaikin_money_flow(bars: Sequence[dict], window: int = 21) -> float | None:
    """CMF = sum(MFM*Vol) / sum(Vol) over `window` bars, in [-1, +1].

    Buying pressure (>0) when closes print in the upper part of bar ranges on
    volume; selling pressure (<0) in the lower part. Standard money-flow
    indicator (StockCharts ChartSchool).
    """
    rows = bars[-window:]
    num = 0.0
    den = 0.0
    for b in rows:
        mfm = _money_flow_multiplier(b)
        vol = b.get("volume")
        if mfm is None or vol is None:
            continue
        try:
            vol = float(vol)
        except (TypeError, ValueError):
            continue
        if vol <= 0:
            continue
        num += mfm * vol
        den += vol
    if den == 0:
        return None
    return num / den


def bvc_imbalance(bars: Sequence[dict], window: int = 20) -> float | None:
    """Bulk Volume Classification signed-volume imbalance over `window`, in [-1,1].

    Per Easley, Lopez de Prado & O'Hara (Flow Toxicity / VPIN), each bar's volume
    is split into buy/sell *fractions* by the standard-normal CDF of the bar's
    standardized close-to-close return:
        buy_fraction = Phi( dP / sigma_dP ),   signed = volume * (2*buy_fraction - 1)
    Returns sum(signed) / sum(volume) in [-1, +1]. Needs only OHLCV bars (no L2).
    A bar-native order-flow proxy appropriate to the intraday-to-daily horizon
    (true OFI lives at a seconds horizon and needs full book depth).
    """
    rows = bars[-(window + 1):]
    # Build (close, volume) pairs in lockstep, dropping bars without a numeric
    # close. Keeping close and its own volume together is essential: filtering
    # closes and volumes into separate lists would misalign delta[i] with
    # volume[i] on any data gap (a None close), corrupting the imbalance.
    pairs: list[tuple[float, float]] = []
    for b in rows:
        try:
            c = float(b.get("close"))
        except (TypeError, ValueError):
            continue
        try:
            v = float(b.get("volume"))
        except (TypeError, ValueError):
            v = 0.0
        pairs.append((c, v))
    if len(pairs) < 3:
        return None
    closes = [p[0] for p in pairs]
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    n = len(deltas)
    mean_d = sum(deltas) / n
    var = sum((d - mean_d) ** 2 for d in deltas) / n
    sigma = var ** 0.5
    # When every move is identical (sigma == 0) the normal CDF can't standardize;
    # fall back to sign-based classification (all-up -> buy, all-down -> sell).
    use_sign = sigma <= 0
    signed = 0.0
    total = 0.0
    # deltas[i] is the move INTO bar pairs[i+1]; weight it by that bar's volume.
    for i, d in enumerate(deltas):
        vol = pairs[i + 1][1]
        if vol <= 0:
            continue
        if use_sign:
            buy_frac = 1.0 if d > 0 else (0.0 if d < 0 else 0.5)
        else:
            buy_frac = _norm_cdf(d / sigma)
        signed += vol * (2.0 * buy_frac - 1.0)
        total += vol
    if total == 0:
        return None
    return signed / total


def flow_pressure(bars: Sequence[dict], window: int = 20) -> float | None:
    """Synthesized FLOW PRESSURE indicator: equal blend of BVC signed-volume
    imbalance and Chaikin Money Flow, in [-1, +1].

    Combines two OHLCV-native, horizon-appropriate buying/selling-pressure
    measures that both add the VOLUME dimension price-only momentum lacks.
    Equal-weighted by design (DeMiguel 2009 / data-snooping critique: optimized
    signal weights overfit and fail out of sample). Returns None only if BOTH
    components are unavailable; uses whichever is present otherwise.
    """
    bvc = bvc_imbalance(bars, window)
    cmf = chaikin_money_flow(bars, window)
    parts = [x for x in (bvc, cmf) if x is not None]
    if not parts:
        return None
    val = sum(parts) / len(parts)
    return max(-1.0, min(1.0, val))


def opening_range(bars: Sequence[dict], minutes: int = 30) -> tuple[float, float] | None:
    """High/low of the first `minutes` 1-minute bars (opening-range breakout)."""
    rows = [b for b in bars if b.get("high") is not None and b.get("low") is not None]
    if not rows:
        return None
    span = rows[: max(1, minutes)]
    hi = max(float(b["high"]) for b in span)
    lo = min(float(b["low"]) for b in span)
    return (hi, lo)
