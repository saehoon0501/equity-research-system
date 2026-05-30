"""Inner-ring test for the concrete 3-leg market feed (task 3.6).

Boundary: feed (Requirements 12, 1). Un-mocks task 3.1's live fetch: builds the
daemon's concrete ``MarketFeed`` (design's "one impure edge", §14.10) as THREE
legs and asserts the tasks.md 3.6 Observable, with the **httpx transport mocked**
(``httpx.MockTransport``) so the inner ring touches no live network:

  * the ticker leg returns **≥252 daily ``Bar``s** (Massive ``/v2/aggs`` with a
    ``day`` timespan, ``dict``→daily ``Bar`` adapter — ``ts``/``vwap`` stripped);
  * the SPY leg returns **≥252 daily adj-closes** (same REST shape, reusing the
    polygon-provider body, NOT its ``@mcp.tool``);
  * the DGS1 (rf) leg is a **per-epoch/day TTL cache that hits the network once**
    — a second ``rf_yield_pct()`` in the same TTL window does NO new GET;
  * a 401 / 403 / non-200 on the bars legs is **surfaced** (raises), never
    silently returned as an empty series;
  * **no FastMCP / websocket import** is pulled into the daemon interpreter by
    importing/using the feed (the §14.10 boundary);
  * ``candidate.assemble`` over the real feed (mocked transport) produces a
    ``Candidate`` end-to-end (≥252 bars satisfy ``compute_features``);
  * a **double-guarded opt-in live leg** skips cleanly when no feed keys are set.

No LLM, no MCP, no live DB, no ``src.survival`` (P14).
"""

from __future__ import annotations

import os
import sys

import httpx
import pytest

from src.reactive.daemon.config import DaemonConfig
from src.reactive.daemon.types import Candidate


# --- Synthetic Massive /v2/aggs response builders --------------------------


def _agg_bar(close: float, ts_ms: int) -> dict:
    """One raw Massive/Polygon ``/v2/aggs`` result bar (the wire shape)."""
    return {
        "t": ts_ms,
        "o": close,
        "h": close + 1.0,
        "l": close - 1.0,
        "c": close,
        "v": 1000.0,
        "vw": close,  # vwap — the adapter MUST strip this
    }


def _aggs_payload(n: int, start: float = 100.0, step: float = 0.5) -> dict:
    """A Massive ``/v2/aggs`` JSON body with ``n`` ascending daily bars."""
    day_ms = 86_400_000
    base_ts = 1_600_000_000_000
    return {
        "ticker": "TEST",
        "status": "OK",
        "resultsCount": n,
        "results": [
            _agg_bar(start + step * i, base_ts + i * day_ms) for i in range(n)
        ],
    }


# A history comfortably past the 252d longest reused window.
_N = 260


def _ok_transport(n: int = _N) -> httpx.MockTransport:
    """A transport that answers every ``/v2/aggs`` GET with ``n`` daily bars."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/v2/aggs/" in request.url.path
        return httpx.Response(200, json=_aggs_payload(n))

    return httpx.MockTransport(handler)


def _status_transport(status_code: int) -> httpx.MockTransport:
    """A transport that answers every GET with a non-200 status."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "nope"})

    return httpx.MockTransport(handler)


def _config(**overrides) -> DaemonConfig:
    """A DaemonConfig with a market-feed key + URL set (so the live legs run)."""
    base = dict(
        paper=True,
        assess_max_latency_seconds=5.0,
        poll_timeout_seconds=2.0,
        eval_cadence_seconds=1.0,
        intake_poll_cadence_seconds=1.0,
        stop_loss_atr_mult=2.0,
        market_feed_api_key="TESTKEY",
        market_feed_rest_url="https://api.massive.test",
        dsn="postgresql://u:p@127.0.0.1:5432/db",
    )
    base.update(overrides)
    return DaemonConfig(**base)


# --- Import-time boundary: no FastMCP / websocket pulled in ----------------


def test_importing_feed_pulls_no_fastmcp_or_websocket():
    """Importing the feed module must not drag FastMCP / websockets into the
    daemon interpreter (§14.10 — the daemon is not an MCP client)."""
    # Import inside the test so the assertion reflects this module's effect.
    import src.reactive.daemon.feed  # noqa: F401

    assert "mcp.server.fastmcp" not in sys.modules
    assert "websockets" not in sys.modules
    # The flat massive/market_data MCP server modules must not be imported either.
    assert "server" not in sys.modules or not hasattr(
        sys.modules.get("server"), "stream_micro_aggregate"
    )


# --- Leg (a): ticker daily bars -------------------------------------------


def test_ticker_bars_returns_at_least_252_daily_bars():
    """The ticker leg requests daily aggregates and adapts them to ≥252 daily
    ``Bar``s with the OHLCV keys ``compute_features`` consumes."""
    from src.reactive.daemon.feed import MassiveRestFeed

    feed = MassiveRestFeed(_config(), transport=_ok_transport())
    bars = feed.ticker_bars("AAPL")

    assert len(bars) >= 252
    last = bars[-1]
    # Each adapted bar is the daily OHLCV Bar shape — no ts / vwap leakage.
    assert set(last.keys()) == {"open", "high", "low", "close", "volume"}
    assert "ts" not in last
    assert "vwap" not in last
    # Chronological: index [-1] is the most recent (highest close on the ramp).
    assert bars[-1]["close"] > bars[0]["close"]


def test_ticker_bars_strips_ts_and_vwap_and_coerces_floats():
    """``ts`` and ``vwap`` are stripped; OHLCV values are floats."""
    from src.reactive.daemon.feed import MassiveRestFeed

    feed = MassiveRestFeed(_config(), transport=_ok_transport())
    bar = feed.ticker_bars("AAPL")[-1]

    for key in ("open", "high", "low", "close", "volume"):
        assert isinstance(bar[key], float)


# --- Leg (b): SPY daily adj-close -----------------------------------------


def test_spy_close_returns_at_least_252_daily_adj_closes():
    """The SPY leg returns the benchmark daily adj-close series (≥252), the same
    REST shape as the ticker leg (polygon-provider body, not its MCP tool)."""
    from src.reactive.daemon.feed import MassiveRestFeed

    feed = MassiveRestFeed(_config(), transport=_ok_transport())
    spy = feed.spy_close()

    assert len(spy) >= 252
    assert all(isinstance(c, float) for c in spy)
    # Ascending ramp → last > first.
    assert spy[-1] > spy[0]


# --- Leg (c): rf DGS1 TTL cache -------------------------------------------


def test_rf_yield_dgs1_caches_and_hits_network_once_per_ttl():
    """The DGS1 leg caches per epoch/day: the first call fetches, a second call
    within the TTL window returns the cached value with NO new GET."""
    from src.reactive.daemon.feed import MassiveRestFeed

    calls: list[str] = []

    def _fake_latest_value(series_id, asof=None):
        calls.append(series_id)
        return ("2026-05-29", 5.0)

    feed = MassiveRestFeed(
        _config(), transport=_ok_transport(), dgs1_fetcher=_fake_latest_value
    )

    first = feed.rf_yield_pct()
    second = feed.rf_yield_pct()

    assert first == 5.0
    assert second == 5.0
    # Hit the underlying FRED fetch exactly once across the two ticks (no
    # per-tick GET) — the cache served the second call.
    assert calls == ["DGS1"]


def test_rf_yield_dgs1_none_when_unresolved():
    """A FRED miss (value None) surfaces as ``None`` — the tactical core then
    abstains (→ ``unavailable`` bin), which is NOT a feed failure."""
    from src.reactive.daemon.feed import MassiveRestFeed

    def _miss(series_id, asof=None):
        return ("", None)

    feed = MassiveRestFeed(
        _config(), transport=_ok_transport(), dgs1_fetcher=_miss
    )
    assert feed.rf_yield_pct() is None


# --- Error surfacing (401 / 403 / non-200) --------------------------------


@pytest.mark.parametrize("status_code", [401, 403, 429, 500])
def test_non_200_on_ticker_bars_is_surfaced(status_code):
    """A 401/403/429/non-200 on the bars endpoint is surfaced (raises), never a
    silent empty series — fail-loud at the impure edge."""
    from src.reactive.daemon.feed import MassiveRestFeed, MarketFeedError

    feed = MassiveRestFeed(_config(), transport=_status_transport(status_code))
    with pytest.raises(MarketFeedError):
        feed.ticker_bars("AAPL")


@pytest.mark.parametrize("status_code", [401, 403, 500])
def test_non_200_on_spy_close_is_surfaced(status_code):
    """Same fail-loud contract on the SPY leg."""
    from src.reactive.daemon.feed import MassiveRestFeed, MarketFeedError

    feed = MassiveRestFeed(_config(), transport=_status_transport(status_code))
    with pytest.raises(MarketFeedError):
        feed.spy_close()


# --- The feed satisfies the MarketFeed Protocol candidate consumes ---------


def test_feed_is_a_marketfeed_and_drives_candidate_end_to_end():
    """``candidate.assemble`` over the real feed (mocked transport) produces a
    ``Candidate`` — the ≥252 daily bars satisfy ``compute_features`` and the
    rf leg resolves a directional tactical bin."""
    from src.reactive.daemon import candidate as candidate_mod
    from src.reactive.daemon.candidate import MarketFeed, assemble
    from src.reactive.daemon.feed import MassiveRestFeed
    from src.reactive.params import DEFAULTS
    from src.reactive.daemon.types import PinnedParams

    feed = MassiveRestFeed(
        _config(),
        transport=_ok_transport(),
        dgs1_fetcher=lambda series_id, asof=None: ("2026-05-29", 1.0),
    )
    # Structural Protocol conformance (the consumer-owned interface).
    assert isinstance(feed, MarketFeed)

    cand = assemble(
        "AAPL", feed, PinnedParams(reactive_snapshot=DEFAULTS, survival_snapshot={})
    )
    # An ascending ramp that outperforms a flat SPY with a low rf → LONG.
    assert isinstance(cand, Candidate)
    assert cand.direction in ("LONG", "SHORT")
    assert cand.reference_price == feed.ticker_bars("AAPL")[-1]["close"]


# --- Double-guarded opt-in live leg ---------------------------------------


@pytest.mark.skipif(
    os.environ.get("DAEMON_FEED_LIVE") != "1"
    or not (os.environ.get("MASSIVE_API_KEY") or "").strip(),
    reason="live feed opt-in (DAEMON_FEED_LIVE=1 + MASSIVE_API_KEY) not set",
)
def test_live_round_trip_optional():
    """Double-guarded opt-in live round trip: only runs when BOTH the
    ``DAEMON_FEED_LIVE=1`` opt-in flag AND a real ``MASSIVE_API_KEY`` are set;
    otherwise it skips cleanly with no keys (the default CI path)."""
    from src.reactive.daemon.feed import MassiveRestFeed

    feed = MassiveRestFeed(DaemonConfig.from_env())
    bars = feed.ticker_bars("AAPL")
    assert len(bars) >= 252
    assert feed.spy_close()
