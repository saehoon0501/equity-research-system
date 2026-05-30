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
