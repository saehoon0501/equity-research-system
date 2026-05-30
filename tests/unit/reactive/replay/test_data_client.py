"""Pure-unit transport tests for the Massive historical REST client (Task 1.2).

Non-behavioral infra: this exercises only the TRANSPORT layer of
``src.reactive.replay.data_client`` — the structured ``Result``/``Error``
return type, the ``apiKey``-query-param auth (NOT Gate's HMAC), the
runtime-parsed rate-limit headers, and the injectable-transport seam. The typed
``DataPort`` fetch methods (``fetch_daily_bars`` et al.) are Task 1.3 and are
NOT exercised here.

Source of truth (cited per the task):
  - requirements.md Requirement 4 AC 4.1 — point-in-time historical data access
    (the transport is the leaf that AC 4.1's fetches ride on).
  - design.md ``data_client`` component block ("structured ``Result``/``Error``
    (never raises), rate-limit from response headers, ``apiKey`` auth from
    ``.env``"); the Technology Stack "Data access" row ("new direct Massive REST
    client (``httpx``) … ``gate_client.py`` transport pattern"); and the Allowed
    Dependencies "External" row (``MASSIVE_API_KEY``, ``MASSIVE_REST_URL`` from
    ``.env``; ``httpx``; "apiKey auth, not HMAC").

Isolation (P14 inner-ring, R9.2): every request runs through an injected
``httpx.MockTransport`` — no network, no live DB, no MCP, no real key. The
``MASSIVE_API_KEY`` is set to a SENTINEL via ``monkeypatch`` so the fresh-per-call
credential read does not short-circuit to an auth-missing error before the mock
transport is reached; the same sentinel is asserted to appear as the ``apiKey``
query param and to be ABSENT from every structured ``Error`` message (secret-free).

Requirements: 4.1.
"""

from __future__ import annotations

import httpx
import pytest

from src.reactive.replay import data_client as dc

# A recognizable fake key: present in the outbound query param, never in errors.
_SENTINEL_KEY = "SENTINEL_MASSIVE_KEY_do_not_log_0xDEADBEEF"


@pytest.fixture(autouse=True)
def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a sentinel ``MASSIVE_API_KEY`` so the per-call credential read passes
    and the injected transport (not an auth short-circuit) is exercised."""
    monkeypatch.setenv("MASSIVE_API_KEY", _SENTINEL_KEY)


def _transport(handler) -> httpx.MockTransport:  # noqa: ANN001
    return httpx.MockTransport(handler)


# --- 200 -> structured Result(ok=True, data=...) -------------------------


def test_200_returns_structured_result_with_parsed_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"c": 1.0}], "status": "OK"})

    out = dc.request("GET", "/v2/aggs/ticker/SPY/range/1/day/X/Y",
                     params={"adjusted": "false"}, transport=_transport(handler))

    assert out.ok is True
    assert isinstance(out, dc.Result)
    assert out.data == {"results": [{"c": 1.0}], "status": "OK"}
    assert out.status_code == 200


# --- apiKey is sent as a query param, never in an Error -------------------


def test_apikey_is_sent_as_query_param() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["apiKey"] = request.url.params.get("apiKey", "")
        return httpx.Response(200, json={"status": "OK"})

    out = dc.request("GET", "/v2/aggs/ticker/SPY/range/1/day/X/Y",
                     transport=_transport(handler))

    assert out.ok is True
    # apiKey rides the query string (Massive simple-auth), NOT an HMAC header.
    assert seen["apiKey"] == _SENTINEL_KEY


def test_apikey_never_appears_in_an_error_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Venue error whose body is safe; the URL it echoes carries the key.
        return httpx.Response(
            400, json={"status": "ERROR", "error": "bad range"}
        )

    out = dc.request("GET", "/v2/aggs/ticker/SPY/range/1/day/X/Y",
                     transport=_transport(handler))

    assert out.ok is False
    # The sentinel key must not leak through the error string or its repr —
    # the query string (where apiKey lives) must never be interpolated.
    assert _SENTINEL_KEY not in out.error
    assert _SENTINEL_KEY not in repr(out)


# --- 429 -> structured Error(error_class="rate_limit"), no raise ----------


def test_429_returns_rate_limit_error_without_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # 429 with ONLY a JSON body (no provider-specific rate-limit headers) —
        # the rate_limit classification must not depend on a particular header.
        return httpx.Response(429, json={"status": "ERROR", "error": "too many"})

    sleeps: list[float] = []
    out = dc.request("GET", "/v2/aggs/ticker/SPY/range/1/day/X/Y",
                     transport=_transport(handler), sleep=sleeps.append)

    assert out.ok is False
    assert isinstance(out, dc.Error)
    assert out.error_class == "rate_limit"
    assert out.status_code == 429
    # Single request: backs off at most once, then returns — no retry loop.
    assert len(sleeps) <= 1


def test_429_rate_limit_headers_parsed_when_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "2"},
            json={"status": "ERROR"},
        )

    out = dc.request("GET", "/v2/aggs/ticker/SPY/range/1/day/X/Y",
                     transport=_transport(handler), sleep=lambda _s: None)

    assert out.error_class == "rate_limit"
    # Whatever rate-limit hint is present is surfaced (runtime-parsed, not hardcoded).
    assert out.rate_limit is not None


# --- 5xx -> structured Error (server responded => venue_error) ------------


def test_5xx_returns_venue_error_without_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"status": "ERROR", "error": "down"})

    out = dc.request("GET", "/v2/aggs/ticker/SPY/range/1/day/X/Y",
                     transport=_transport(handler))

    assert out.ok is False
    assert isinstance(out, dc.Error)
    # A server-responded 5xx is a venue error (gate_client taxonomy); the
    # connection itself succeeded, so it is NOT a network error.
    assert out.error_class == "venue_error"
    assert out.status_code == 503


# --- transport exception (no response) -> network -------------------------


def test_transport_exception_returns_network_error_without_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # The exception message embeds the sentinel key to prove the network
        # error string (built from the exception TYPE NAME only, never str(exc))
        # cannot leak it — the riskiest path, since the key rides the URL.
        raise httpx.ConnectError(f"connection refused to host?apiKey={_SENTINEL_KEY}")

    out = dc.request("GET", "/v2/aggs/ticker/SPY/range/1/day/X/Y",
                     transport=_transport(handler))

    assert out.ok is False
    assert isinstance(out, dc.Error)
    assert out.error_class == "network"
    # Secret-free on the network path too (not just venue_error).
    assert _SENTINEL_KEY not in out.error
    assert _SENTINEL_KEY not in repr(out)


# --- 401 -> structured auth error -----------------------------------------


def test_401_returns_auth_error_without_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status": "ERROR", "error": "bad key"})

    out = dc.request("GET", "/v2/aggs/ticker/SPY/range/1/day/X/Y",
                     transport=_transport(handler))

    assert out.ok is False
    assert out.error_class == "auth"
    assert out.status_code == 401


# --- missing MASSIVE_API_KEY -> auth error, no transmit -------------------


def test_missing_api_key_returns_auth_error_and_does_not_transmit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    transmitted = {"hit": False}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        transmitted["hit"] = True
        return httpx.Response(200, json={})

    out = dc.request("GET", "/v2/aggs/ticker/SPY/range/1/day/X/Y",
                     transport=_transport(handler))

    assert out.ok is False
    assert out.error_class == "auth"
    # A missing-credential read transmits NOTHING (mirror gate_client).
    assert transmitted["hit"] is False


# =========================================================================== #
# Task 1.3 — the typed point-in-time DataPort fetch methods.
#
# These ride the Task 1.2 transport (above) but parse + bound + paginate at the
# domain boundary. They satisfy the ``types.DataPort`` Protocol structurally and
# add the extra fetches the task names (trades, grouped-daily, tickers).
#
# Source of truth (cited per the task):
#   - requirements.md R4 AC 4.1 (no rows after the instant for decision inputs),
#     AC 4.2 (``adjusted=false`` on aggregates), AC 4.3 (fail explicitly — RAISE,
#     do not return a partial/truncated window — when a window predates available
#     depth), AC 4.4 (paginate past the per-request row cap via ``next_url``;
#     retrieve delisted names over their trading window via Tickers active=false).
#   - requirements.md R5 AC 5.1 (cash dividends are fetchable for total-return
#     P&L — the harness credits them separately from price).
#   - requirements.md R6 AC 6.1 (NBBO quotes carry bid/ask for counterparty fills).
#   - design.md §"data_client (Massive historical REST)" (the 5 pinned fetch
#     methods, all point-in-time bounded; pagination; fail-on-exceeds-depth;
#     delisted) and §"Core algorithms #4 (as-of split rule)" (the WHY for
#     ``adjusted=false`` raw + a splits reference — the split *adjustment* itself
#     is task 2.1 / features_adapter, NOT fetched-here logic).
#
# Per the advisor checkpoint: 4.3 and 4.4 are the SAME invariant — any transport
# ``Error`` mid-fetch (incl. a 403 NOT_AUTHORIZED beyond plan-tier depth, incl.
# mid-pagination) RAISES a typed error and discards everything accumulated; a
# natural ``next_url`` termination returns the complete window. A delisted/IPO
# name whose earliest bar is legitimately after ``start`` is the CORRECT 4.4
# result, not a 4.3 failure — depth-vs-existence is the venue's explicit signal,
# never a row-shape heuristic.
#
# Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 6.1.
# =========================================================================== #


def _client(handler) -> "dc.MassiveDataClient":  # noqa: ANN001
    """A MassiveDataClient whose Massive transport is the injected MockTransport
    (R9.2 isolation — no network)."""
    return dc.MassiveDataClient(transport=_transport(handler), sleep=lambda _s: None)


# --- structural: the class satisfies the DataPort Protocol ----------------


def test_client_satisfies_dataport_protocol() -> None:
    from src.reactive.replay import types as t

    client = dc.MassiveDataClient(transport=_transport(lambda r: httpx.Response(200, json={})))
    # runtime_checkable Protocol — structural conformance (R9.2 injection seam).
    assert isinstance(client, t.DataPort)


# --- 4.2: aggregates always send adjusted=false ---------------------------


def test_fetch_daily_bars_sends_adjusted_false() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["adjusted"] = request.url.params.get("adjusted", "<absent>")
        seen["path"] = request.url.path
        return httpx.Response(200, json={"results": [], "status": "OK"})

    _client(handler).fetch_daily_bars("AAPL", "2024-01-02", "2024-01-31")

    # AC 4.2 — split-unadjusted price data so post-instant splits cannot
    # retroactively alter prices. Never adjusted=true.
    assert seen["adjusted"] == "false"
    assert "/v2/aggs/ticker/AAPL/range/1/day/2024-01-02/2024-01-31" in seen["path"]


def test_fetch_intraday_sends_adjusted_false() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["adjusted"] = request.url.params.get("adjusted", "<absent>")
        return httpx.Response(200, json={"results": [], "status": "OK"})

    _client(handler).fetch_intraday("AAPL", "2024-01-02")

    assert seen["adjusted"] == "false"


# --- 4.1: never return rows timestamped after the requested instant --------


def test_fetch_daily_bars_drops_rows_after_until() -> None:
    # Bars (Polygon/Massive ``t`` is epoch MILLIseconds). End is 2024-01-03.
    ms = lambda s: int(  # noqa: E731
        __import__("datetime").datetime.fromisoformat(s)
        .replace(tzinfo=__import__("datetime").timezone.utc)
        .timestamp() * 1000
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "OK", "results": [
            {"t": ms("2024-01-02"), "c": 10.0},
            {"t": ms("2024-01-03"), "c": 11.0},
            {"t": ms("2024-01-04"), "c": 12.0},   # AFTER end -> must be dropped
        ]})

    bars = _client(handler).fetch_daily_bars("AAPL", "2024-01-02", "2024-01-03")

    # AC 4.1 — no data timestamped after the requested instant feeds a decision.
    ts = [b["t"] for b in bars]
    assert ms("2024-01-04") not in ts
    assert ms("2024-01-03") in ts          # the boundary day is INCLUSIVE
    assert ms("2024-01-02") in ts


# --- 4.4: paginate to completion via next_url -----------------------------


def test_fetch_daily_bars_paginates_to_completion() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "cursor" not in request.url.params:
            # Page 1: a partial page + a next_url cursor (per-request cap reached).
            return httpx.Response(200, json={
                "status": "OK",
                "results": [{"t": 1, "c": 1.0}, {"t": 2, "c": 2.0}],
                "next_url": "https://api.massive.com/v2/aggs/ticker/AAPL/"
                            "range/1/day/2000/2099?cursor=PAGE2",
            })
        # Page 2: the tail, no further next_url -> natural termination.
        return httpx.Response(200, json={
            "status": "OK",
            "results": [{"t": 3, "c": 3.0}],
        })

    bars = _client(handler).fetch_daily_bars("AAPL", "2000-01-01", "2099-12-31")

    # AC 4.4 — the cursor is followed until exhausted; all rows accumulated.
    assert len(calls) == 2
    assert [b["t"] for b in bars] == [1, 2, 3]
    # The cursor page must still carry the apiKey (re-appended by the client).
    assert "apiKey=" in calls[1]


# --- 4.3: a window beyond available depth FAILS explicitly (no partial) ----


def test_fetch_daily_bars_raises_on_depth_denial_not_partial() -> None:
    # The venue's EXPLICIT beyond-tier-depth signal is a 403 NOT_AUTHORIZED
    # (the transport classifies it as an Error). The fetch method must RAISE a
    # typed error, NOT return a truncated/partial window.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"status": "NOT_AUTHORIZED",
                                         "error": "history beyond your plan"})

    with pytest.raises(dc.DataFetchError):
        _client(handler).fetch_daily_bars("AAPL", "1990-01-01", "1990-12-31")


def test_fetch_daily_bars_raises_on_mid_pagination_error_discarding_partial() -> None:
    # 4.3 == 4.4 (one invariant): an error on page 2 (after a good page 1) must
    # NOT return page 1 as a silently-truncated window — it must RAISE.
    def handler(request: httpx.Request) -> httpx.Response:
        if "cursor" not in request.url.params:
            return httpx.Response(200, json={
                "status": "OK",
                "results": [{"t": 1, "c": 1.0}],
                "next_url": "https://api.massive.com/v2/aggs/ticker/AAPL/"
                            "range/1/day/2000/2099?cursor=PAGE2",
            })
        return httpx.Response(503, json={"status": "ERROR", "error": "down"})

    with pytest.raises(dc.DataFetchError):
        _client(handler).fetch_daily_bars("AAPL", "2000-01-01", "2099-12-31")


# --- 4.4: a delisted name returns its (sub-window) trading bars ------------


def test_fetch_daily_bars_delisted_name_returns_trading_window() -> None:
    # A delisted name legitimately trades only part of the requested window; its
    # earliest/last bar being inside [start, end] is the CORRECT 4.4 result, NOT
    # a 4.3 depth failure. The venue 200s with just the traded sub-window.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "OK", "results": [
            {"t": 1_577_923_200_000, "c": 5.0},   # 2020-01-02
            {"t": 1_578_009_600_000, "c": 4.0},   # 2020-01-03 (then delisted)
        ]})

    bars = _client(handler).fetch_daily_bars("DEAD", "2019-01-01", "2021-12-31")

    assert len(bars) == 2          # the traded sub-window, no spurious raise
    assert [b["c"] for b in bars] == [5.0, 4.0]


def test_fetch_corporate_actions_requests_tickers_active_false_for_delisted() -> None:
    # 4.4 — delisted names are retrievable; the Tickers reference uses
    # active=false. fetch_delisted_tickers names the trading universe over a window.
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["active"] = request.url.params.get("active", "<absent>")
        return httpx.Response(200, json={"status": "OK", "results": [
            {"ticker": "DEAD", "active": False, "delisted_utc": "2020-06-01"},
        ]})

    rows = _client(handler).fetch_delisted_tickers()

    assert "/v3/reference/tickers" in seen["path"]
    assert seen["active"] == "false"
    assert rows[0]["ticker"] == "DEAD"


# --- 6.1: quotes return bid/ask (NBBO) ------------------------------------


def test_fetch_quotes_returns_bid_and_ask() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/v3/quotes/AAPL" in request.url.path
        return httpx.Response(200, json={"status": "OK", "results": [
            # ``sip_timestamp`` is NANOseconds; bid=``bp``, ask=``ap`` (Polygon shape).
            {"sip_timestamp": 1_577_923_200_000_000_000, "bp": 99.98, "ap": 100.02},
        ]})

    quotes = _client(handler).fetch_quotes("AAPL", "2020-01-02")

    # AC 6.1 — counterparty fills price against bid/ask, never mid.
    assert quotes["results"][0]["bp"] == 99.98
    assert quotes["results"][0]["ap"] == 100.02


# --- 5.1: cash dividends are fetchable -------------------------------------


def test_fetch_corporate_actions_returns_dividends() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/v3/reference/dividends" in path:
            return httpx.Response(200, json={"status": "OK", "results": [
                {"ex_dividend_date": "2024-02-09", "cash_amount": 0.24},
            ]})
        # splits leg of the same corporate-actions fetch
        return httpx.Response(200, json={"status": "OK", "results": [
            {"execution_date": "2024-06-10", "split_from": 1, "split_to": 4},
        ]})

    actions = _client(handler).fetch_corporate_actions("AAPL", "2024-01-01", "2024-12-31")

    # AC 5.1 — cash dividends fetchable so total-return P&L credits them
    # separately (the price bars are never dividend-adjusted, R5.2).
    divs = actions["dividends"]
    assert divs[0]["cash_amount"] == 0.24
    assert actions["splits"][0]["split_to"] == 4


# --- 4.1: corporate actions are point-in-time bounded by `end` -------------


def test_fetch_corporate_actions_drops_dividends_after_end() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/v3/reference/dividends" in request.url.path:
            return httpx.Response(200, json={"status": "OK", "results": [
                {"ex_dividend_date": "2024-02-09", "cash_amount": 0.24},
                {"ex_dividend_date": "2025-02-09", "cash_amount": 0.26},  # after end
            ]})
        return httpx.Response(200, json={"status": "OK", "results": []})

    actions = _client(handler).fetch_corporate_actions("AAPL", "2024-01-01", "2024-12-31")

    ex_dates = [d["ex_dividend_date"] for d in actions["dividends"]]
    assert "2024-02-09" in ex_dates
    assert "2025-02-09" not in ex_dates     # AC 4.1 — nothing after the instant


# --- grouped-daily (universe) ---------------------------------------------


def test_fetch_grouped_daily_returns_universe_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/v2/aggs/grouped/locale/us/market/stocks/2024-01-02" in request.url.path
        assert request.url.params.get("adjusted") == "false"
        return httpx.Response(200, json={"status": "OK", "results": [
            {"T": "AAPL", "c": 100.0}, {"T": "MSFT", "c": 200.0},
        ]})

    rows = _client(handler).fetch_grouped_daily("2024-01-02")

    assert {r["T"] for r in rows} == {"AAPL", "MSFT"}


# --- trades ---------------------------------------------------------------


def test_fetch_trades_returns_rows_bounded_by_until() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/v3/trades/AAPL" in request.url.path
        return httpx.Response(200, json={"status": "OK", "results": [
            {"participant_timestamp": 1_577_923_200_000_000_000, "price": 100.0},
        ]})

    out = _client(handler).fetch_trades("AAPL", "2020-01-02")

    assert out["results"][0]["price"] == 100.0


# --- 4.3: a fetch with no rf yield available raises, not a silent default ---


def test_fetch_rf_yield_walks_back_to_last_good_value() -> None:
    # FRED rides its OWN transport seam (api_key / FRED_API_KEY / stlouisfed),
    # NOT the Massive request(). Missing prints arrive as "." -> the helper walks
    # back to the last good value at-or-before the requested day (weekend/holiday).
    def fred_handler(request: httpx.Request) -> httpx.Response:
        assert "stlouisfed.org" in request.url.host
        assert request.url.params.get("observation_end") == "2024-01-15"
        return httpx.Response(200, json={"observations": [
            {"date": "2024-01-11", "value": "4.50"},
            {"date": "2024-01-12", "value": "4.55"},
            {"date": "2024-01-13", "value": "."},   # Saturday — missing
            {"date": "2024-01-14", "value": "."},   # Sunday — missing
            {"date": "2024-01-15", "value": "."},   # MLK holiday — missing
        ]})

    client = dc.MassiveDataClient(
        transport=_transport(lambda r: httpx.Response(200, json={})),
        fred_transport=_transport(fred_handler),
    )
    rf = client.fetch_rf_yield("2024-01-15")

    # Last good print at/before the day is Friday 2024-01-12 = 4.55.
    assert rf == 4.55
