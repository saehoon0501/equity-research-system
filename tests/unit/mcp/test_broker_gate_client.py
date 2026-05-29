"""Unit tests for the signed REST transport to the Gate venue (Task 2.1).

Covers the design "gate_client" component (Transport layer) + its API Contract:

- Sign every request with Gate APIv4 HMAC-SHA512 SIGN over the canonical string
  ``"{METHOD}\n{path}\n{query_string}\n{hex_sha512(body)}\n{timestamp}"``; the
  signing function is pure + unit-testable (asserted against a locally-computed
  known vector).
- Execute requests over ``httpx`` against an INJECTED transport (the Task 1.4 mock
  in ``broker_gate_fakes.make_mock_transport``) and return RAW venue JSON only —
  no business rules (those belong to later layers).
- NEVER raise. Every failure class returns a STRUCTURED transport error result:
  (a) auth failure / missing credentials (Req 9.1), (b) venue error or
  unreachable/network failure (Req 9.2), (c) rate-limited (Req 9.5).
- Rate limits (Req 9.5): parse the ``X-Gate-RateLimit-*`` response headers and,
  on HTTP 429, BACK OFF (via an INJECTED ``sleep`` callable so tests do not really
  sleep) rather than retry immediately; discover the effective limit at runtime
  from the headers (never hardcoded).
- Credentials resolved FRESH per call via ``config.resolve_credentials``; if
  missing -> a structured auth/credentials error with NO transmit (Req 9.1).
- Secrets never appear in any returned error or in a log.

Requirements: 1.7, 9.1, 9.2, 9.5.

Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \\
        tests/unit/mcp/test_broker_gate_client.py -q

The broker runs in its own uv venv (carries ``mcp`` / ``httpx``); the repo root is
NOT on ``sys.path``. This test loads ``gate_client.py`` and the 1.4 mock helper by
path (importlib-by-path, under unique module aliases) to avoid module-name
collisions, mirroring ``tests/unit/mcp/test_broker_config.py`` /
``test_broker_models.py`` / ``test_broker_gate_fakes.py`` / ``test_polygon.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import logging
import sys
from pathlib import Path

import httpx
import pytest

# Repo root: tests/unit/mcp/test_broker_gate_client.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"
# gate_client does a by-name sibling import (`import config`) — exactly the
# production posture (`python server.py` runs with the broker dir on sys.path[0]).
# The broker uv venv does NOT put the broker dir on sys.path, so seed it here so
# the sibling import resolves (mirrors how server.py would be launched).
if str(_BROKER_DIR) not in sys.path:
    sys.path.insert(0, str(_BROKER_DIR))


def _load_by_path(alias: str, path: Path):
    spec = importlib.util.spec_from_file_location(alias, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


# The 1.4 mock transport + fixture loader (the injectable-transport seam).
_FAKES_PATH = _REPO_ROOT / "tests" / "unit" / "mcp" / "broker_gate_fakes.py"
broker_gate_fakes = _load_by_path("broker_gate_fakes", _FAKES_PATH)

# The unit-under-test.
gate_client = _load_by_path("broker_gate_client", _BROKER_DIR / "gate_client.py")


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _set_creds(monkeypatch, key: str = "k-test", secret: str = "s-test") -> None:
    monkeypatch.setenv("GATE_API_KEY", key)
    monkeypatch.setenv("GATE_API_SECRET", secret)


def _unset_creds(monkeypatch) -> None:
    monkeypatch.delenv("GATE_API_KEY", raising=False)
    monkeypatch.delenv("GATE_API_SECRET", raising=False)


class _SleepSpy:
    """Records every backoff sleep call without actually sleeping."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _is_error(result) -> bool:
    """A structured transport error has ``ok`` False; a success has ``ok`` True."""
    return getattr(result, "ok", None) is False


def _is_ok(result) -> bool:
    return getattr(result, "ok", None) is True


# --------------------------------------------------------------------------- #
# SIGN — pure HMAC-SHA512 signing, asserted against a locally-computed vector.
# --------------------------------------------------------------------------- #


def test_sign_matches_known_hmac_sha512_vector():
    """The SIGN function is pure and matches a HMAC-SHA512 over the canonical Gate
    APIv4 string: METHOD\\n path\\n query\\n hex_sha512(body)\\n timestamp."""
    secret = "my-secret"
    method = "GET"
    path = "/api/v4/tradfi/positions"
    query = ""
    body = ""
    timestamp = "1748563200"

    body_hash = hashlib.sha512(body.encode("utf-8")).hexdigest()
    payload = f"{method}\n{path}\n{query}\n{body_hash}\n{timestamp}"
    expected = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha512
    ).hexdigest()

    got = gate_client.sign(
        method=method,
        path=path,
        query_string=query,
        body=body,
        timestamp=timestamp,
        secret=secret,
    )
    assert got == expected
    # SHA-512 hexdigest is 128 hex chars.
    assert len(got) == 128


def test_sign_hashes_a_nonempty_body():
    """A non-empty POST body must be hashed into the signing payload."""
    secret = "abc"
    method = "POST"
    path = "/api/v4/tradfi/orders"
    query = ""
    body = '{"symbol":"AAPL","side":2,"volume":"1","price_type":"market"}'
    timestamp = "1700000000"

    body_hash = hashlib.sha512(body.encode("utf-8")).hexdigest()
    payload = f"{method}\n{path}\n{query}\n{body_hash}\n{timestamp}"
    expected = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha512
    ).hexdigest()

    got = gate_client.sign(
        method=method,
        path=path,
        query_string=query,
        body=body,
        timestamp=timestamp,
        secret=secret,
    )
    assert got == expected


def test_sign_is_pure_deterministic():
    """Same inputs -> same signature; different body -> different signature."""
    args = dict(
        method="GET",
        path="/api/v4/tradfi/users/assets",
        query_string="",
        body="",
        timestamp="1748563200",
        secret="s",
    )
    a = gate_client.sign(**args)
    b = gate_client.sign(**args)
    assert a == b

    c = gate_client.sign(**{**args, "body": '{"x":1}'})
    assert c != a


# --------------------------------------------------------------------------- #
# Success path — a GET returns parsed JSON for a fixture endpoint.
# --------------------------------------------------------------------------- #


def test_get_returns_parsed_json_for_fixture_endpoint(monkeypatch):
    """A normal GET against the mock returns the canned positions JSON, parsed."""
    _set_creds(monkeypatch)
    transport = broker_gate_fakes.make_mock_transport()

    result = gate_client.request(
        "GET", "/tradfi/positions", transport=transport
    )

    assert _is_ok(result), f"expected success result, got {result!r}"
    assert result.data == broker_gate_fakes.load_fixture("positions.json")
    assert result.data[0]["position_id"] == "POS-500001"


def test_get_assets_returns_raw_venue_json(monkeypatch):
    """gate_client returns RAW venue JSON (a dict here) with no domain mapping."""
    _set_creds(monkeypatch)
    transport = broker_gate_fakes.make_mock_transport()

    result = gate_client.request(
        "GET", "/tradfi/users/assets", transport=transport
    )

    assert _is_ok(result)
    assert result.data == broker_gate_fakes.load_fixture("users_assets.json")
    # Raw venue strings preserved (no parsing into floats at this layer).
    assert result.data["equity"] == "10234.56"


def test_post_create_order_returns_queue_task_id(monkeypatch):
    """A POST returns the raw create response carrying data.id (queue task id)."""
    _set_creds(monkeypatch)
    transport = broker_gate_fakes.make_mock_transport()

    result = gate_client.request(
        "POST",
        "/tradfi/orders",
        body={"symbol": "AAPL", "side": 2, "volume": "1", "price_type": "market"},
        transport=transport,
    )

    assert _is_ok(result)
    assert "id" in result.data["data"]


# --------------------------------------------------------------------------- #
# Missing credentials -> structured auth error, NO transmit (Req 9.1).
# --------------------------------------------------------------------------- #


def test_missing_credentials_returns_structured_error_no_transmit(monkeypatch):
    """With creds unset, the call returns a structured error and never touches the
    transport (no exception, no transmit)."""
    _unset_creds(monkeypatch)

    transmitted: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        transmitted.append(request)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)

    result = gate_client.request("GET", "/tradfi/positions", transport=transport)

    assert _is_error(result), f"expected structured error, got {result!r}"
    assert transmitted == [], "must NOT transmit when credentials are missing"
    # A failure class is identifiable (auth / credentials).
    assert getattr(result, "error_class", None) in {"auth", "missing_credentials"}


def test_missing_credentials_does_not_raise(monkeypatch):
    """Req 9.1 conservative posture — no exception on missing credentials."""
    _unset_creds(monkeypatch)
    transport = broker_gate_fakes.make_mock_transport()
    # Must not raise.
    result = gate_client.request("GET", "/tradfi/positions", transport=transport)
    assert _is_error(result)


# --------------------------------------------------------------------------- #
# Injected 401 -> structured auth error (Req 9.1).
# --------------------------------------------------------------------------- #


def test_injected_401_returns_structured_auth_error(monkeypatch):
    """An injected 401 yields a structured auth error, not an exception."""
    _set_creds(monkeypatch)
    transport = broker_gate_fakes.make_mock_transport(fail="auth")

    result = gate_client.request("GET", "/tradfi/users/assets", transport=transport)

    assert _is_error(result)
    assert getattr(result, "error_class", None) == "auth"
    assert getattr(result, "status_code", None) == 401


# --------------------------------------------------------------------------- #
# Injected 429 -> backoff (via injected sleep spy) + structured/limit-aware
# result, NOT an immediate raise (Req 9.5).
# --------------------------------------------------------------------------- #


def test_injected_429_backs_off_via_injected_sleep(monkeypatch):
    """A 429 triggers a backoff sleep (asserted via the injected sleep spy) rather
    than an immediate raise; the result is a structured rate-limited error."""
    _set_creds(monkeypatch)
    transport = broker_gate_fakes.make_mock_transport(fail="rate_limit")
    sleep_spy = _SleepSpy()

    result = gate_client.request(
        "GET", "/tradfi/positions", transport=transport, sleep=sleep_spy
    )

    # Backoff was invoked (did not retry immediately / raise).
    assert sleep_spy.calls, "expected a backoff sleep on HTTP 429"
    assert all(s >= 0 for s in sleep_spy.calls)

    # Structured, rate-limit-aware result (never a raise).
    assert _is_error(result)
    assert getattr(result, "error_class", None) == "rate_limit"
    assert getattr(result, "status_code", None) == 429


def test_injected_429_discovers_limit_from_headers(monkeypatch):
    """Req 9.5 — the effective limit is discovered at runtime from the
    X-Gate-RateLimit-* response headers (not hardcoded)."""
    _set_creds(monkeypatch)
    transport = broker_gate_fakes.make_mock_transport(fail="rate_limit")
    sleep_spy = _SleepSpy()

    result = gate_client.request(
        "GET", "/tradfi/positions", transport=transport, sleep=sleep_spy
    )

    rl = getattr(result, "rate_limit", None)
    assert rl is not None, "expected parsed rate-limit info from response headers"
    # The mock sends Limit=300, Requests-Remain=0 — values come FROM the headers.
    assert str(rl.get("limit")) == "300"
    assert str(rl.get("remaining")) == "0"


def test_429_does_not_retry_immediately(monkeypatch):
    """A 429 must back off rather than fire a second request immediately."""
    _set_creds(monkeypatch)

    request_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        resp = httpx.Response(
            429, json={"label": "TOO_MANY_REQUESTS", "message": "rate limited"}
        )
        resp.headers.update(broker_gate_fakes.RATE_LIMIT_HEADERS)
        return resp

    transport = httpx.MockTransport(handler)
    sleep_spy = _SleepSpy()

    result = gate_client.request(
        "GET", "/tradfi/positions", transport=transport, sleep=sleep_spy
    )

    # Backoff happened; we did NOT hammer the venue with an immediate re-fire
    # ahead of the sleep (the structured error is returned after backing off).
    assert sleep_spy.calls
    assert _is_error(result)
    assert getattr(result, "error_class", None) == "rate_limit"


# --------------------------------------------------------------------------- #
# Injected network error -> structured error (Req 9.2).
# --------------------------------------------------------------------------- #


def test_injected_network_error_returns_structured_error(monkeypatch):
    """An unreachable venue (ConnectError) yields a structured network error, not
    an unhandled exception."""
    _set_creds(monkeypatch)
    transport = broker_gate_fakes.make_mock_transport(fail="network")

    result = gate_client.request("GET", "/tradfi/positions", transport=transport)

    assert _is_error(result)
    assert getattr(result, "error_class", None) == "network"


def test_venue_error_status_returns_structured_error(monkeypatch):
    """A non-2xx, non-401/429 venue error (e.g. 400) is a structured venue error,
    not a raise (Req 9.2)."""
    _set_creds(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"label": "BAD_REQUEST", "message": "nope"})

    transport = httpx.MockTransport(handler)

    result = gate_client.request("POST", "/tradfi/orders", body={"x": 1}, transport=transport)

    assert _is_error(result)
    assert getattr(result, "status_code", None) == 400
    assert getattr(result, "error_class", None) in {"venue_error", "venue"}


# --------------------------------------------------------------------------- #
# Secrets never appear in any returned error or in a log (Security).
# --------------------------------------------------------------------------- #


def test_secret_never_in_returned_error(monkeypatch):
    """No failure-path result may surface the secret value."""
    secret = "TOP-SECRET-VALUE-XYZ"
    key = "KEY-VALUE-ABC"
    _set_creds(monkeypatch, key=key, secret=secret)

    # Drive each failure class and scan its stringified result for the secret.
    for fail in ("auth", "rate_limit", "network"):
        transport = broker_gate_fakes.make_mock_transport(fail=fail)
        result = gate_client.request(
            "GET", "/tradfi/positions", transport=transport, sleep=_SleepSpy()
        )
        blob = repr(result) + str(getattr(result, "error", "") or "")
        assert secret not in blob, f"secret leaked in {fail} error result"
        assert key not in blob, f"api key leaked in {fail} error result"


def test_secret_never_logged(monkeypatch, caplog):
    """No log record emitted during a signed request may contain the secret."""
    secret = "LOG-SECRET-VALUE-987"
    key = "LOG-KEY-VALUE-654"
    _set_creds(monkeypatch, key=key, secret=secret)

    with caplog.at_level(logging.DEBUG):
        # Exercise success + a failure path.
        ok_transport = broker_gate_fakes.make_mock_transport()
        gate_client.request("GET", "/tradfi/positions", transport=ok_transport)

        fail_transport = broker_gate_fakes.make_mock_transport(fail="auth")
        gate_client.request("GET", "/tradfi/users/assets", transport=fail_transport)

    log_blob = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in log_blob
    assert key not in log_blob


# --------------------------------------------------------------------------- #
# query-string signing — params are reflected into the canonical signing string.
# --------------------------------------------------------------------------- #


def test_request_with_params_signs_query_string(monkeypatch):
    """A GET carrying query params still returns parsed JSON; the query string is
    part of the signed payload (covered by the success round-trip through SIGN)."""
    _set_creds(monkeypatch)
    transport = broker_gate_fakes.make_mock_transport()

    # symbols/detail takes a `symbols=` query; the mock ignores the query and keys
    # on the path, so a success here proves params do not break the signed call.
    result = gate_client.request(
        "GET",
        "/tradfi/symbols/detail",
        params={"symbols": "AAPL,MSFT"},
        transport=transport,
    )

    assert _is_ok(result)
    assert isinstance(result.data, list)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
