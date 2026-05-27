"""Massive.com real-time stocks MCP server for the equity research system.

Per BUILD_LOG.md decision 6, this is a *tool* consumed by Claude Code — namely
the `/micro` day-trading helper — not an orchestrator. It exposes Massive's
real-time US-equities feed to the ≤1-day execution layer, deliberately distinct
from the slow-layer `market_data` server (daily OHLCV / news) that feeds
`/research-company`.

Two tools:

- ``stream_micro_aggregate(ticker, collect_seconds, channels)``: opens a
  SHORT-LIVED websocket per call, authenticates, subscribes to trades/quotes/
  per-second-aggregates, collects for ``collect_seconds`` (clamped 1..60),
  closes, and returns a single micro-aggregate snapshot (last/vwap/tick
  velocity/spread/hi-lo/volume). This is the "leverages real-time price via the
  Massive websocket" capability `/micro` was built around. MCP tools are
  request/response — they cannot stream — so the websocket is opened, drained
  for a bounded window, and closed within one call.
- ``get_intraday_bars(ticker, multiplier, timespan, lookback_minutes)``:
  REST aggregate bars. The websocket gives the *now*; the indicator suite in
  ``src/micro`` needs a *series*, and that comes from here.

Massive's wire protocol is Polygon-compatible (verified against
https://massive.com/docs/websocket/stocks/{trades,quotes,aggregates-per-second}):
status/auth/subscribe control frames and ``ev``-tagged data frames
(``T`` trade, ``Q`` quote, ``A`` per-second agg) arrive as JSON arrays. The REST
aggregates endpoint mirrors Polygon's ``/v2/aggs`` shape — hence the field
mapping below is intentionally the twin of ``market_data/polygon_provider.py``.

Configuration (``.env`` at repo root, loaded via python-dotenv):

    MASSIVE_API_KEY=...                       (required for live data)
    MASSIVE_WS_URL=wss://socket.massive.com   (default; wss://delayed.massive.com for the delayed feed)
    MASSIVE_REST_URL=https://api.massive.com  (default)

Tools degrade gracefully: a missing key, auth rejection, or a closed/illiquid
market return a structured payload with an explanatory ``status`` rather than
raising, so `/micro` can render a "no live signal" card instead of crashing.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from websockets import connect as ws_connect
from websockets.exceptions import ConnectionClosed, WebSocketException

# Walk: server.py -> massive/ -> mcp/ -> src/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")

_LOG = logging.getLogger(__name__)

_WS_URL = (os.environ.get("MASSIVE_WS_URL") or "wss://socket.massive.com").rstrip("/")
_REST_URL = (os.environ.get("MASSIVE_REST_URL") or "https://api.massive.com").rstrip("/")
_CLUSTER = "stocks"  # Massive stocks cluster path: <ws_url>/stocks
_REST_TIMEOUT_S = 15.0
_USER_AGENT = "equity-research-system/0.1 (massive-mcp)"

# Bounds for the per-call websocket window. Keep the agent un-blocked.
_MIN_WINDOW_S = 1
_MAX_WINDOW_S = 60
_AUTH_TIMEOUT_S = 8.0
_CONNECT_TIMEOUT_S = 8.0


def _api_key() -> str:
    return (os.environ.get("MASSIVE_API_KEY") or "").strip()


def _now_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _ms_to_iso(ms: Any) -> str | None:
    if not isinstance(ms, (int, float)):
        return None
    return (
        _dt.datetime.fromtimestamp(ms / 1000.0, tz=_dt.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


mcp = FastMCP("massive")


# --------------------------------------------------------------------------- #
# Tool 1 — websocket-per-call micro-aggregate (the real-time capability)
# --------------------------------------------------------------------------- #


def _accumulate(frame: dict[str, Any], acc: dict[str, Any]) -> None:
    """Fold one Massive data frame into the running accumulators."""
    ev = frame.get("ev")
    if ev == "T":  # trade
        price = frame.get("p")
        size = frame.get("s") or 0
        if isinstance(price, (int, float)):
            acc["trade_count"] += 1
            acc["last_trade_price"] = float(price)
            acc["last_trade_ts"] = frame.get("t")
            acc["volume"] += int(size or 0)
            acc["px_sz_sum"] += float(price) * float(size or 0)
            acc["sz_sum"] += float(size or 0)
            acc["high"] = price if acc["high"] is None else max(acc["high"], price)
            acc["low"] = price if acc["low"] is None else min(acc["low"], price)
    elif ev == "Q":  # quote
        bp, ap = frame.get("bp"), frame.get("ap")
        if isinstance(bp, (int, float)) and isinstance(ap, (int, float)):
            acc["quote_count"] += 1
            acc["last_bid"] = float(bp)
            acc["last_ask"] = float(ap)
            acc["last_bid_size"] = frame.get("bs")
            acc["last_ask_size"] = frame.get("as")
    elif ev == "A":  # per-second aggregate (fallback hi/lo/last when no raw trades)
        acc["agg_count"] += 1
        for k_src, k_dst in (("h", "agg_high"), ("l", "agg_low"), ("c", "agg_close")):
            v = frame.get(k_src)
            if isinstance(v, (int, float)):
                acc[k_dst] = float(v)


async def _collect_window(
    ticker: str, window_s: int, channels: list[str]
) -> dict[str, Any]:
    """Open ws, auth, subscribe, drain for window_s, close, summarize."""
    key = _api_key()
    if not key:
        return {
            "ticker": ticker,
            "status": "config_error",
            "message": (
                "MASSIVE_API_KEY not set. Register at massive.com and add it to "
                ".env. The /micro command will fall back to a bars-only signal."
            ),
            "as_of": _now_iso(),
        }

    sym = ticker.upper()
    sub_params = ",".join(f"{ch}.{sym}" for ch in channels)
    uri = f"{_WS_URL}/{_CLUSTER}"

    acc: dict[str, Any] = {
        "trade_count": 0,
        "quote_count": 0,
        "agg_count": 0,
        "volume": 0,
        "px_sz_sum": 0.0,
        "sz_sum": 0.0,
        "last_trade_price": None,
        "last_trade_ts": None,
        "high": None,
        "low": None,
        "last_bid": None,
        "last_ask": None,
        "last_bid_size": None,
        "last_ask_size": None,
        "agg_high": None,
        "agg_low": None,
        "agg_close": None,
    }

    try:
        async with ws_connect(
            uri, open_timeout=_CONNECT_TIMEOUT_S, max_size=2**22
        ) as ws:
            # --- auth phase ---
            await ws.send(json.dumps({"action": "auth", "params": key}))
            authed = await _await_auth(ws)
            if authed is not True:
                return {
                    "ticker": sym,
                    "status": "auth_failed",
                    "message": authed if isinstance(authed, str) else "auth rejected",
                    "ws_url": uri,
                    "as_of": _now_iso(),
                }

            # --- subscribe + drain phase ---
            await ws.send(json.dumps({"action": "subscribe", "params": sub_params}))
            loop = asyncio.get_event_loop()
            deadline = loop.time() + window_s
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                except ConnectionClosed:
                    break
                for frame in _as_frames(raw):
                    if frame.get("ev") == "status":
                        continue
                    _accumulate(frame, acc)
    except (OSError, WebSocketException) as exc:
        return {
            "ticker": sym,
            "status": "connection_error",
            "message": f"{type(exc).__name__}: {exc}",
            "ws_url": uri,
            "as_of": _now_iso(),
        }

    return _summarize(sym, window_s, channels, acc)


async def _await_auth(ws: Any) -> bool | str:
    """Read control frames until auth_success / auth_failed or timeout."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + _AUTH_TIMEOUT_S
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return "auth timeout (no auth_success within %.0fs)" % _AUTH_TIMEOUT_S
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            return "auth timeout"
        except ConnectionClosed as exc:
            return f"connection closed during auth: {exc}"
        for frame in _as_frames(raw):
            if frame.get("ev") != "status":
                continue
            status = (frame.get("status") or "").lower()
            if status == "auth_success":
                return True
            if status in ("auth_failed", "error", "max_connections"):
                return frame.get("message") or status
            # "connected" and other interim statuses: keep reading until auth resolves.


def _as_frames(raw: Any) -> list[dict[str, Any]]:
    """Massive frames arrive as a JSON array (sometimes a bare object)."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(data, list):
        return [f for f in data if isinstance(f, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _summarize(
    sym: str, window_s: int, channels: list[str], acc: dict[str, Any]
) -> dict[str, Any]:
    trade_count = acc["trade_count"]
    vwap = (acc["px_sz_sum"] / acc["sz_sum"]) if acc["sz_sum"] > 0 else None
    last = acc["last_trade_price"]
    high = acc["high"] if acc["high"] is not None else acc["agg_high"]
    low = acc["low"] if acc["low"] is not None else acc["agg_low"]
    if last is None:
        last = acc["agg_close"]

    bid, ask = acc["last_bid"], acc["last_ask"]
    mid = (bid + ask) / 2.0 if bid is not None and ask is not None else None
    spread_bps = None
    if bid is not None and ask is not None and mid:
        spread_bps = round((ask - bid) / mid * 10_000, 2)

    # No data at all in the window: distinguish from a real (thin) read.
    if trade_count == 0 and acc["quote_count"] == 0 and acc["agg_count"] == 0:
        status = "no_ticks"
    else:
        status = "ok"

    return {
        "ticker": sym,
        "status": status,
        "window_seconds": window_s,
        "channels": channels,
        "last_trade_price": last,
        "vwap_window": round(vwap, 6) if vwap is not None else None,
        "trade_count": trade_count,
        "tick_velocity_per_s": round(trade_count / window_s, 3) if window_s else None,
        "window_volume": acc["volume"],
        "window_high": high,
        "window_low": low,
        "bid": bid,
        "ask": ask,
        "mid": round(mid, 6) if mid is not None else None,
        "spread_bps": spread_bps,
        "bid_size": acc["last_bid_size"],
        "ask_size": acc["last_ask_size"],
        "quote_count": acc["quote_count"],
        "agg_count": acc["agg_count"],
        "last_trade_at": _ms_to_iso(acc["last_trade_ts"]),
        "as_of": _now_iso(),
        "provider": "massive",
    }


@mcp.tool()
async def stream_micro_aggregate(
    ticker: str,
    collect_seconds: int = 10,
    channels: str = "T,Q,A",
) -> dict:
    """Open a short-lived Massive websocket, collect ticks, return a snapshot.

    Connects to ``<MASSIVE_WS_URL>/stocks``, authenticates with
    ``MASSIVE_API_KEY``, subscribes to ``channels`` for ``ticker``, drains for
    ``collect_seconds`` (clamped to 1..60), then closes the socket. Returns one
    micro-aggregate summarizing the window.

    Args:
        ticker: US-listed symbol, e.g. "SPY".
        collect_seconds: drain window length (1..60). Default 10.
        channels: comma-separated Massive channel prefixes. "T" trades,
            "Q" quotes, "A" per-second aggregates. Default "T,Q,A".

    Returns (status="ok"):
        {"ticker", "status", "last_trade_price", "vwap_window",
         "tick_velocity_per_s", "window_volume", "window_high", "window_low",
         "bid", "ask", "mid", "spread_bps", "trade_count", "quote_count",
         "as_of", "provider"}

    On degradation returns status in {"config_error", "auth_failed",
    "connection_error", "no_ticks"} with a "message" — never raises for
    operational failures, so /micro can render a graceful card.
    """
    window_s = max(_MIN_WINDOW_S, min(_MAX_WINDOW_S, int(collect_seconds)))
    chans = [c.strip().upper() for c in (channels or "T,Q,A").split(",") if c.strip()]
    chans = [c for c in chans if c in ("T", "Q", "A", "AM")] or ["T", "Q", "A"]
    return await _collect_window(ticker, window_s, chans)


# --------------------------------------------------------------------------- #
# Tool 2 — REST intraday bars (the series the indicators need)
# --------------------------------------------------------------------------- #


@mcp.tool()
def get_intraday_bars(
    ticker: str,
    multiplier: int = 1,
    timespan: str = "minute",
    lookback_minutes: int = 390,
) -> dict:
    """Intraday aggregate bars from Massive's REST ``/v2/aggs`` endpoint.

    The websocket tool gives the live tape; the technical-indicator suite in
    ``src/micro`` needs an ordered bar series, which this provides.

    Args:
        ticker: US-listed symbol.
        multiplier: bar size multiplier (e.g. 1, 5).
        timespan: "minute" | "hour" | "second". Default "minute".
        lookback_minutes: how far back from now to fetch. Default 390 (one
            regular US session).

    Returns:
        {"ticker", "multiplier", "timespan", "bars": [{"ts","open","high",
         "low","close","volume","vwap"}], "rowcount", "provider": "massive"}
        or {"status": "config_error" | "http_error", "message"} on failure.
    """
    key = _api_key()
    sym = ticker.upper()
    if not key:
        return {
            "ticker": sym,
            "status": "config_error",
            "message": "MASSIVE_API_KEY not set; cannot fetch intraday bars.",
            "as_of": _now_iso(),
        }

    now_ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
    from_ms = now_ms - int(lookback_minutes) * 60_000
    path = (
        f"/v2/aggs/ticker/{sym}/range/{int(multiplier)}/{timespan}/{from_ms}/{now_ms}"
    )
    url = f"{_REST_URL}{path}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50_000, "apiKey": key}

    try:
        with httpx.Client(
            timeout=_REST_TIMEOUT_S, headers={"User-Agent": _USER_AGENT}
        ) as client:
            resp = client.get(url, params=params)
    except httpx.HTTPError as exc:
        return {
            "ticker": sym,
            "status": "http_error",
            "message": f"{type(exc).__name__}: {exc}",
            "as_of": _now_iso(),
        }

    if resp.status_code in (401, 403):
        return {
            "ticker": sym,
            "status": "http_error",
            "message": f"Massive REST rejected request (HTTP {resp.status_code}); "
            "check MASSIVE_API_KEY and plan-tier coverage.",
            "as_of": _now_iso(),
        }
    if resp.status_code != 200:
        return {
            "ticker": sym,
            "status": "http_error",
            "message": f"Massive REST HTTP {resp.status_code}: {resp.text[:300]}",
            "as_of": _now_iso(),
        }

    data = resp.json()
    bars: list[dict[str, Any]] = []
    for bar in data.get("results") or []:
        bars.append(
            {
                "ts": _ms_to_iso(bar.get("t")),
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": bar.get("c"),
                "volume": bar.get("v"),
                "vwap": bar.get("vw"),
            }
        )
    return {
        "ticker": sym,
        "multiplier": int(multiplier),
        "timespan": timespan,
        "lookback_minutes": int(lookback_minutes),
        "bars": bars,
        "rowcount": len(bars),
        "status": "ok",
        "provider": "massive",
    }


if __name__ == "__main__":
    mcp.run()
