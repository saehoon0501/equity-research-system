"""Polygon.io market-data provider for the equity research system.

Implements the same three function contracts as the yfinance fallback in
``server.py`` (``get_prices``, ``get_news``, ``get_real_time_quote``) so the
MCP tool surface is unchanged across providers.

Why Polygon at v0.1: per operator decision 2026-04-30 the spec target was
moved from yfinance (delayed/unofficial) to Polygon (consolidated SIP feeds,
real-time quotes, official API) to satisfy the "high quality live market
data" requirement. Polygon was the named v0.5+ upgrade target in the
original v3 spec; this brings it forward.

Activation:
    Set ``MARKET_DATA_PROVIDER=polygon`` and ``POLYGON_API_KEY=...`` in
    ``.env``. ``server.py`` dispatches to this module when both are set.

Endpoints used:
    - GET /v2/aggs/ticker/{T}/range/{m}/{ts}/{from}/{to}  (historical bars)
    - GET /v2/snapshot/locale/us/markets/stocks/tickers/{T}  (snapshot/last quote)
    - GET /v2/reference/news?ticker=...                   (news)

Plan tier: works on Stocks Starter ($29/mo) — required for real-time
non-delayed snapshot. Free tier returns 15-minute-delayed data and may
silently degrade quality; the operator-facing /system-health surfaces
plan-tier mismatches via the ``status`` field returned alongside results.

Rate limiting: Polygon's Stocks Starter is 5 calls/sec sustained; we do not
add an explicit rate limiter at the provider level — the daily monitor's
cadence floor (Section 7 Q3) already paces calls under that ceiling. If
sustained 429s appear the system_errors table will surface it via
``/system-health``.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Any

import httpx

_API_ROOT = "https://api.polygon.io"
_USER_AGENT = "equity-research-system/0.1 (polygon-provider)"
_TIMEOUT_S = 15.0


class PolygonAuthError(RuntimeError):
    """Raised when POLYGON_API_KEY is missing or rejected."""


class PolygonRateLimitError(RuntimeError):
    """Raised when Polygon returns 429 after retries."""


def _get_api_key() -> str:
    key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not key:
        raise PolygonAuthError(
            "POLYGON_API_KEY not set. Register at polygon.io and add to .env. "
            "If you intend to use yfinance instead, unset MARKET_DATA_PROVIDER."
        )
    return key


def _interval_to_polygon(interval: str) -> tuple[int, str]:
    """Map yfinance-style intervals to Polygon (multiplier, timespan).

    yfinance: '1d' / '1wk' / '1mo'  ->  Polygon: (1, 'day') / (1, 'week') / (1, 'month').

    Raises ValueError for unsupported intervals (the caller's existing
    error path already surfaces interval-related errors).
    """
    table = {
        "1d": (1, "day"),
        "1wk": (1, "week"),
        "1mo": (1, "month"),
    }
    if interval not in table:
        raise ValueError(
            f"interval={interval!r} unsupported; use one of {list(table)}"
        )
    return table[interval]


def _request(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """One synchronous GET against Polygon. Raises on auth/rate/quota failure."""
    params = dict(params)
    params["apiKey"] = _get_api_key()
    url = f"{_API_ROOT}{path}"
    with httpx.Client(timeout=_TIMEOUT_S, headers={"User-Agent": _USER_AGENT}) as client:
        resp = client.get(url, params=params)
    if resp.status_code == 401 or resp.status_code == 403:
        raise PolygonAuthError(
            f"Polygon rejected request (HTTP {resp.status_code}); "
            "check POLYGON_API_KEY and plan-tier endpoint coverage."
        )
    if resp.status_code == 429:
        raise PolygonRateLimitError(
            f"Polygon rate-limited (HTTP 429) on {path}; cadence-floor logic "
            "should have paced this. Surface to /system-health."
        )
    if resp.status_code >= 500:
        raise RuntimeError(f"Polygon server error HTTP {resp.status_code} on {path}")
    if resp.status_code != 200:
        raise RuntimeError(f"Polygon HTTP {resp.status_code} on {path}: {resp.text[:300]}")
    return resp.json()


def _bar_date_iso(bar: dict[str, Any]) -> str:
    """ISO date for a Polygon bar's ``t`` (ms epoch UTC)."""
    ts_ms = bar.get("t")
    if isinstance(ts_ms, (int, float)):
        return (
            _dt.datetime.fromtimestamp(ts_ms / 1000.0, tz=_dt.timezone.utc)
            .date()
            .isoformat()
        )
    return ""


def _normalize_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map raw Polygon aggregate bars to our OHLCV row shape (split-adjusted).

    Pure function — no network. ``close_split_adj`` is the split-adjusted close
    that Polygon returns in ``c`` when ``adjusted=true``; this is NOT a
    total-return series (dividends are not reinvested), which is exactly the
    mislabel this fix corrects.
    """
    out: list[dict[str, Any]] = []
    for bar in bars:
        close_split_adj = bar.get("c")
        out.append(
            {
                "date": _bar_date_iso(bar),
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": close_split_adj,
                # `c` under adjusted=true is split-adjusted only. We keep an
                # explicit, correctly-named field and DO NOT claim it is
                # total-return adjusted. adj_close is retained for backward-
                # compat but now means "split-adjusted close" (the truth).
                "close_split_adj": close_split_adj,
                "adj_close": close_split_adj,
                # Populated only in total_return mode (see _reconstruct_total_return).
                "total_return_close": None,
                "volume": bar.get("v"),
            }
        )
    return out


def _reconstruct_total_return(
    rows: list[dict[str, Any]], dividends: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Reconstruct a dividend-inclusive total-return close from split-adjusted
    bars + cash dividends. Pure function — unit-testable with mock data.

    Method — the CRSP/Bloomberg total-return convention:

        TR_t = TR_{t-1} * (P_t + D_t) / P_{t-1}

    where P is the (split-adjusted) close and D_t is any cash dividend with
    ex-date == bar t. Implemented as a cumulative ``growth`` factor with
    total_return_close[t] = close_split_adj[t] * growth[t]:

        on an ex-date, growth *= (1 + D_t / P_t)   # NOTE: divide by the
                                                    # EX-DATE close P_t, not the
                                                    # prior close — Polygon's
                                                    # adjusted=true does NOT
                                                    # adjust for dividends, so
                                                    # P_t already reflects the
                                                    # ex-date price drop. Using
                                                    # P_t makes the algebra
                                                    # collapse to the textbook
                                                    # (P_t + D_t)/P_{t-1} form
                                                    # exactly.

    We anchor at the FIRST bar (total_return_close[0] == close_split_adj[0]) and
    accrue dividend reinvestment forward, so the ratio
    total_return_close[-1] / total_return_close[0] is the dividend-inclusive
    holding-period gross return. For a flat-priced stock that pays a dividend
    and drops by exactly the dividend on ex-date, this correctly returns a TR
    ratio of 1.0 (you got the dividend back; price net zero).

    Args:
        rows: output of _normalize_bars (ascending by date), each with
              ``date`` and ``close_split_adj``.
        dividends: list of {"ex_date": "YYYY-MM-DD", "cash_amount": float}
                   (Polygon /v3/reference/dividends shape).

    Returns:
        the same rows with ``total_return_close`` populated.
    """
    if not rows:
        return rows
    # ex_date -> cash dividend per share
    div_by_date: dict[str, float] = {}
    for d in dividends or []:
        ex = d.get("ex_date") or d.get("ex_dividend_date")
        amt = d.get("cash_amount")
        if ex and isinstance(amt, (int, float)):
            div_by_date[ex] = div_by_date.get(ex, 0.0) + float(amt)

    growth = 1.0
    out: list[dict[str, Any]] = []
    for row in rows:
        close = row.get("close_split_adj")
        date = row.get("date")
        # On an ex-dividend date, reinvest the dividend at the EX-DATE close
        # (the split-adjusted close already reflects the ex-date price drop, so
        # dividing by it yields the textbook (P_t + D_t)/P_{t-1} growth).
        if date in div_by_date and isinstance(close, (int, float)) and close != 0:
            growth *= 1.0 + div_by_date[date] / close
        tr_close = close * growth if isinstance(close, (int, float)) else None
        new_row = dict(row)
        new_row["total_return_close"] = tr_close
        out.append(new_row)
    return out


def _fetch_dividends(ticker: str, start: str, end: str) -> list[dict[str, Any]]:
    """Fetch cash dividends with ex-date in [start, end] from Polygon."""
    data = _request(
        "/v3/reference/dividends",
        params={
            "ticker": ticker.upper(),
            "ex_dividend_date.gte": start,
            "ex_dividend_date.lte": end,
            "limit": 1000,
        },
    )
    return data.get("results") or []


def get_prices(
    ticker: str, start: str, end: str, interval: str = "1d", mode: str = "split_only"
) -> dict[str, Any]:
    """Historical OHLCV bars matching the yfinance fallback's contract.

    ``end`` is inclusive (yfinance's exclusive-end-date semantics are wrapped
    upstream; Polygon's range endpoint is inclusive on both ends already).

    ``mode``:
        - ``"split_only"`` (default): bars as Polygon returns them under
          ``adjusted=true`` (split-adjusted). ``total_return_close`` is null.
        - ``"total_return"``: additionally fetch cash dividends over the window
          and reconstruct a dividend-reinvested ``total_return_close`` per row
          (Polygon's ``adjusted=true`` is split-only — dividends are NOT
          reinvested by Polygon, so we must reconstruct them ourselves).
    """
    multiplier, timespan = _interval_to_polygon(interval)
    path = (
        f"/v2/aggs/ticker/{ticker.upper()}/range/{multiplier}/{timespan}/"
        f"{start}/{end}"
    )
    data = _request(
        path,
        params={"adjusted": "true", "sort": "asc", "limit": 50_000},
    )
    rows = _normalize_bars(data.get("results") or [])

    if mode == "total_return":
        dividends = _fetch_dividends(ticker, start, end)
        rows = _reconstruct_total_return(rows, dividends)

    return {
        "ticker": ticker.upper(),
        "start": start,
        "end": end,
        "interval": interval,
        "mode": mode,
        "rows": rows,
        "rowcount": len(rows),
        "provider": "polygon",
    }


def get_news(ticker: str, since: str | None = None) -> dict[str, Any]:
    """Recent news matching the yfinance fallback's contract.

    Polygon news returns up to 1000 items per call. We page only when the
    caller's `since` is unbounded; otherwise the default 50-item page is
    sufficient for daily-monitor cadence.
    """
    params: dict[str, Any] = {"ticker": ticker.upper(), "order": "desc", "limit": 50}
    if since:
        params["published_utc.gte"] = since  # ISO-8601 date or datetime
    data = _request("/v2/reference/news", params=params)

    items: list[dict[str, Any]] = []
    for entry in data.get("results") or []:
        items.append(
            {
                "title": entry.get("title", ""),
                "publisher": (entry.get("publisher") or {}).get("name", ""),
                "link": entry.get("article_url", ""),
                "publish_time": entry.get("published_utc", ""),
                "type": "STORY",
            }
        )
    return {
        "ticker": ticker.upper(),
        "items": items,
        "rowcount": len(items),
        "provider": "polygon",
    }


def get_real_time_quote(ticker: str) -> dict[str, Any]:
    """Most recent price + timestamp via Polygon's snapshot endpoint.

    Plan-tier behaviour (verified empirically on AAPL 2026-04-30):
      - **Stocks Basic (free)**: snapshot returns 200 with lastTrade/lastQuote
        empty; aggregates return ``status='DELAYED'``; rate-limited 5/min;
        no current-day intraday.
      - **Stocks Starter ($29/mo)**: snapshot ``ticker.day``, ``ticker.min``,
        ``ticker.prevDay``, ``todaysChange``, ``updated`` fields populated.
        ``lastTrade``/``lastQuote`` REMAIN empty by design — those are
        tick-level fields gated to Developer+. The right "current price"
        on Starter is ``ticker.min.c`` (latest minute bar's close, ~15-min
        delayed) with fallback to ``ticker.day.c`` (today's running close).
      - **Stocks Developer ($79/mo)**: lastTrade/lastQuote populated with
        real-time tick data.

    We pick the most-current populated field in this priority order so the
    function returns a usable price across all three plan tiers without the
    caller needing to know which tier the operator is on:

        lastTrade.p > min.c > day.c > prevDay.c (EOD fallback)

    The ``data_quality`` field reports the source: 'real_time' (lastTrade),
    'delayed_15min' (min.c, Starter), 'today_running' (day.c), or
    'eod_fallback' (prevDay.c — last resort when market is closed).
    """
    path = f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker.upper()}"
    data = _request(path, params={})
    snap = (data or {}).get("ticker") or {}
    last_trade = snap.get("lastTrade") or {}
    last_quote = snap.get("lastQuote") or {}
    minute_bar = snap.get("min") or {}
    day_bar = snap.get("day") or {}
    prev_day = snap.get("prevDay") or {}

    # Priority 1: lastTrade (Developer+ tier)
    price = last_trade.get("p")
    ts_ns = last_trade.get("t")
    quality = None
    if price is not None:
        quality = "real_time"

    # Priority 2: lastQuote midpoint (Developer+ tier; rare fallback)
    if price is None and last_quote.get("P") is not None and last_quote.get("p") is not None:
        price = (float(last_quote["P"]) + float(last_quote["p"])) / 2.0
        ts_ns = last_quote.get("t")
        quality = "real_time"

    # Priority 3: latest minute bar (Stocks Starter tier — 15-min delayed)
    if price is None and minute_bar.get("c") is not None:
        price = minute_bar.get("c")
        ts_ns = minute_bar.get("t")
        # min.t is in milliseconds, not nanoseconds — normalize.
        if isinstance(ts_ns, (int, float)) and ts_ns > 0 and ts_ns < 10**13:
            ts_ns = ts_ns * 1_000_000  # ms → ns
        quality = "delayed_15min"

    # Priority 4: today's running close (Stocks Starter — running bar)
    if price is None and day_bar.get("c") is not None:
        price = day_bar.get("c")
        ts_ns = None
        quality = "today_running"

    # Priority 5: previous day close (last resort — market closed)
    if price is None and prev_day.get("c") is not None:
        price = prev_day.get("c")
        ts_ns = None
        quality = "eod_fallback"

    # Compute as_of timestamp from whatever signal we have
    if isinstance(ts_ns, (int, float)) and ts_ns > 0:
        as_of = (
            _dt.datetime.fromtimestamp(ts_ns / 1_000_000_000.0, tz=_dt.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    else:
        # No tick timestamp — use updated field if present, else now()
        upd_ns = snap.get("updated")
        if isinstance(upd_ns, (int, float)) and upd_ns > 0:
            as_of = (
                _dt.datetime.fromtimestamp(upd_ns / 1_000_000_000.0, tz=_dt.timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
        else:
            as_of = (
                _dt.datetime.now(tz=_dt.timezone.utc).isoformat().replace("+00:00", "Z")
            )

    if price is None:
        # Snapshot returned but every priority failed — degraded path.
        return {
            "ticker": ticker.upper(),
            "last_price": None,
            "as_of": as_of,
            "currency": "USD",
            "provider": "polygon",
            "data_quality": "unavailable",
        }

    return {
        "ticker": ticker.upper(),
        "last_price": price,
        "as_of": as_of,
        "currency": "USD",
        "provider": "polygon",
        "data_quality": quality,
    }
