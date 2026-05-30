"""Concrete 3-leg fast-clock market feed — the daemon's one impure edge (task 3.6).

Boundary: feed (Requirements 12, 1; design §"one impure edge" / §14.10, gap G1).

``candidate.assemble`` (task 3.1) shipped against a **mocked** ``MarketFeed``
Protocol. This module un-mocks it: ``MassiveRestFeed`` is the concrete
``MarketFeed`` the daemon runs against live data, built as the **three legs**
``compute_features`` needs (Req 12.1) — *not* the MCP wrappers (G1):

  (a) **ticker daily bars** — a thin standalone ``httpx`` REST client to the
      Massive ``/v2/aggs`` aggregates endpoint with a ``day`` timespan, and a
      ``dict`` → daily ``Bar`` adapter. Massive defaults to *intraday-minute*
      bars (``src/mcp/massive/server.py::get_intraday_bars`` uses
      ``timespan="minute"``), so this leg explicitly requests **daily** bars over
      a window long enough to clear ``compute_features``'s 252d longest reused
      window, and **strips** the wire-only ``t`` (ts) / ``vw`` (vwap) fields the
      OHLCV ``Bar`` does not carry.
  (b) **SPY daily adj-close** — the *same* Massive/Polygon ``/v2/aggs`` REST
      shape, reusing the **provider body** of
      ``src/mcp/market_data/polygon_provider.py`` (its ``adjusted=true`` daily
      aggregate read + ``c`` = split-adjusted close), **NOT** its ``@mcp.tool``.
      Rather than scoped-importing the flat ``market_data`` MCP package (a second
      MCP-package import landmine — no ``__init__``, drags the FastMCP server),
      the ~one-helper REST body is **vendored** here (the two legs share the
      identical aggregate wire shape, so a single internal ``_fetch_daily_aggs``
      serves both — ticker bars and the SPY close series).
  (c) **risk-free DGS1** — ``src.shared.regime_sidecar.fred_client.latest_value``
      (the clean, importable leg — httpx + dotenv only, no MCP), wrapped in a
      **per-epoch/day TTL cache** so the persistent loop does **not** issue a
      fresh FRED GET on every fast-clock tick. DGS1 moves daily at most; a
      day-bucketed cache hits the network once per UTC day.

The §14.10 boundary is load-bearing: **no ``mcp.server.fastmcp`` / no
``websockets`` import** is pulled into the daemon interpreter by this module. It
imports ``httpx`` + the clean ``fred_client`` leaf + the daemon-owned
``config``/``candidate`` shapes only — never ``src/mcp/massive/server.py`` (which
instantiates ``FastMCP`` at import and pulls ``websockets``) nor the flat
``market_data`` server. The REST bodies are vendored, exactly the design's
"accessed via its client **directly, not through the MCP wrapper**".

Errors are **surfaced, not swallowed** (fail-loud at the impure edge): a
401/403/429/non-200 on a bars leg raises ``MarketFeedError`` — never a silent
empty series that would mis-read as ``insufficient_history`` downstream. A FRED
miss (value ``None``) is the one *non-error* absence: it surfaces as ``None`` so
the tactical core abstains (→ ``unavailable`` bin), which is no-edge, not a fault.

Dependency direction: ``config, types, candidate (MarketFeed) → feed``. Inner-ring
testable with ``httpx.MockTransport`` (no live network); a double-guarded opt-in
live leg exists for an explicit smoke (skips cleanly with no keys).
"""

from __future__ import annotations

import datetime as _dt
from typing import Callable, Optional, Sequence

import httpx

from src.reactive.daemon.config import DaemonConfig
from src.reactive.types import Bar
from src.shared.regime_sidecar import fred_client

__all__ = [
    "MarketFeedError",
    "MassiveRestFeed",
]

# The risk-free series the tactical absolute-momentum gate reads (1-year CMT).
_DGS1_SERIES_ID = "DGS1"

# Daily-bars lookback: enough calendar days to clear the 252-*trading*-day
# longest reused window (``features.LONGEST_WINDOW``) with weekend/holiday
# headroom. 252 trading days ≈ 366 calendar days; 600 calendar days is a
# comfortable margin so a missed session never drops us under 252 daily bars.
_DAILY_LOOKBACK_CALENDAR_DAYS = 600

_USER_AGENT = "equity-research-system/0.1 (daemon-feed)"
_HTTP_TIMEOUT_S = 15.0

# The benchmark series the relative-strength legs compare against (Req 12.1).
_SPY_SYMBOL = "SPY"

# A FRED-fetch callable: (series_id, asof) -> (resolved_date_str, value | None).
# ``fred_client.latest_value`` is the production binding; injectable for tests.
DGS1Fetcher = Callable[..., "tuple[str, Optional[float]]"]


class MarketFeedError(RuntimeError):
    """A fast-clock feed fetch failed loud (auth / rate-limit / non-200).

    Surfaced (not swallowed) so a fetch failure never degrades into a silent
    empty series that the feature compute would mis-read as
    ``insufficient_history`` — the daemon's fail-toward-no-new-exposure path
    (Req 1.5 / 12.4) keys off a real ``None`` candidate, not a fabricated one.
    """


class MassiveRestFeed:
    """The concrete 3-leg ``MarketFeed`` (Massive daily bars + SPY + FRED DGS1).

    Satisfies the ``candidate.MarketFeed`` Protocol structurally (the consumer
    owns that interface; this is the live implementation behind it). Constructed
    once per daemon process from the ``DaemonConfig`` provider keys; the
    single-threaded loop calls its three accessors each evaluation.

    Args:
        config: the daemon config carrying ``market_feed_api_key`` /
            ``market_feed_rest_url`` (§14.10 — the same provider keys
            ``src/mcp/massive`` uses, accessed directly here).
        transport: an optional ``httpx`` transport — injected as an
            ``httpx.MockTransport`` by the inner-ring tests so no live network is
            touched; ``None`` (the default) uses the real network transport.
        dgs1_fetcher: the FRED ``latest_value`` callable for the rf leg;
            defaults to ``fred_client.latest_value``. Injectable so the TTL-cache
            behavior is asserted without a live FRED GET.
        ttl_clock: a callable returning the current UTC ``datetime`` — the TTL
            cache buckets by UTC day; injectable for deterministic tests.
    """

    def __init__(
        self,
        config: DaemonConfig,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        dgs1_fetcher: Optional[DGS1Fetcher] = None,
        ttl_clock: Optional[Callable[[], _dt.datetime]] = None,
    ) -> None:
        self._config = config
        self._rest_url = (config.market_feed_rest_url or "").rstrip("/")
        self._api_key = config.market_feed_api_key
        self._transport = transport
        self._dgs1_fetcher: DGS1Fetcher = dgs1_fetcher or fred_client.latest_value
        self._ttl_clock = ttl_clock or _utcnow

        # Per-epoch/day rf TTL cache: (utc_day_bucket, value). A second tick in
        # the same UTC day returns the cached value with NO new GET.
        self._rf_cache: Optional[tuple[str, Optional[float]]] = None

    # --- Leg (a): ticker daily bars ---------------------------------------

    def ticker_bars(self, symbol: str) -> Sequence[Bar]:
        """Fetch ≥252 chronological daily OHLCV ``Bar``s for ``symbol`` (Req 12.1).

        Massive ``/v2/aggs`` with a ``day`` timespan; the raw ``dict`` results are
        adapted to the daily ``Bar`` shape (``ts``/``vwap`` stripped, OHLCV
        coerced to float). Index ``[-1]`` is the most recent bar.
        """
        rows = self._fetch_daily_aggs(symbol)
        return [_to_bar(r) for r in rows]

    # --- Leg (b): SPY daily adj-close -------------------------------------

    def spy_close(self) -> Sequence[float]:
        """Fetch the SPY benchmark daily adjusted-close series (≥252; Req 12.1).

        The same ``/v2/aggs`` ``adjusted=true`` daily read the polygon-provider
        body uses (``c`` = split-adjusted close); only the close column is
        surfaced (the relative-strength legs compare close-to-close). Index
        ``[-1]`` is the most recent close.
        """
        rows = self._fetch_daily_aggs(_SPY_SYMBOL)
        return [float(r["c"]) for r in rows]

    # --- Leg (c): risk-free DGS1 (TTL-cached) ------------------------------

    def rf_yield_pct(self) -> Optional[float]:
        """Return the latest DGS1 risk-free yield (percent), TTL-cached per UTC day.

        The persistent loop must not issue a fresh FRED GET each fast-clock tick
        (DGS1 updates daily at most), so the value is bucketed by UTC day: the
        first call in a day fetches via ``fred_client.latest_value``; subsequent
        calls in the same day return the cached value with no network hit.

        A FRED miss (value ``None``) is **not** a feed error — it surfaces as
        ``None`` so the tactical core abstains (→ ``unavailable`` bin), the
        no-edge path (Req 12.5), not a fault.
        """
        day_bucket = self._ttl_clock().date().isoformat()
        cached = self._rf_cache
        if cached is not None and cached[0] == day_bucket:
            return cached[1]

        # Cache miss / stale day → one fetch, then cache for the rest of the day.
        _resolved_date, value = self._dgs1_fetcher(_DGS1_SERIES_ID)
        self._rf_cache = (day_bucket, value)
        return value

    # --- Shared REST body (vendored polygon-provider aggregate shape) ------

    def _fetch_daily_aggs(self, symbol: str) -> list[dict]:
        """One synchronous GET of Massive/Polygon ``/v2/aggs`` *daily* bars.

        The vendored provider body (the ~one helper shared by the ticker and SPY
        legs): ``/v2/aggs/ticker/{T}/range/1/day/{from}/{to}`` with
        ``adjusted=true``, ascending. Raises ``MarketFeedError`` on a missing key
        or any non-200 (fail-loud); returns the raw ``results`` list otherwise.
        """
        if not (self._api_key or "").strip():
            raise MarketFeedError(
                "market-feed API key not set; cannot fetch daily aggregates "
                "(set MASSIVE_API_KEY / DaemonConfig.market_feed_api_key)."
            )

        now = _utcnow().date()
        start = (now - _dt.timedelta(days=_DAILY_LOOKBACK_CALENDAR_DAYS)).isoformat()
        end = now.isoformat()
        sym = symbol.upper()
        path = f"/v2/aggs/ticker/{sym}/range/1/day/{start}/{end}"
        url = f"{self._rest_url}{path}"
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50_000,
            "apiKey": self._api_key,
        }

        with httpx.Client(
            timeout=_HTTP_TIMEOUT_S,
            headers={"User-Agent": _USER_AGENT},
            transport=self._transport,
        ) as client:
            resp = client.get(url, params=params)

        if resp.status_code in (401, 403):
            raise MarketFeedError(
                f"market feed rejected request (HTTP {resp.status_code}) for "
                f"{sym}; check the API key and plan-tier coverage."
            )
        if resp.status_code == 429:
            raise MarketFeedError(
                f"market feed rate-limited (HTTP 429) for {sym}; the loop "
                "cadence floor should pace this."
            )
        if resp.status_code != 200:
            raise MarketFeedError(
                f"market feed HTTP {resp.status_code} for {sym}: "
                f"{resp.text[:300]}"
            )

        data = resp.json()
        return data.get("results") or []


# --- Pure adapters (no I/O) -----------------------------------------------


def _to_bar(row: dict) -> Bar:
    """Adapt a raw Massive/Polygon ``/v2/aggs`` result dict to the daily ``Bar``.

    Strips the wire-only ``t`` (timestamp) and ``vw`` (vwap) the OHLCV ``Bar``
    does not carry; coerces OHLCV to float so the indicator cores
    (``indicators.atr`` / ``.closes``) get clean numerics.
    """
    return {
        "open": float(row["o"]),
        "high": float(row["h"]),
        "low": float(row["l"]),
        "close": float(row["c"]),
        "volume": float(row["v"]),
    }


def _utcnow() -> _dt.datetime:
    """Current UTC datetime (the TTL cache buckets by its UTC date)."""
    return _dt.datetime.now(tz=_dt.timezone.utc)
