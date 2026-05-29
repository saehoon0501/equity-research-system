"""Mock Gate `/tradfi` venue transport + fixture loader for the broker adapter.

Task 1.4 test infrastructure (P14 inner ring). This module is REUSED by tasks
2.x / 3.x / 4.x / 6.x to unit-test the broker's leaf functions with NO live venue.

What this provides
------------------
* ``load_fixture(name)`` / ``FIXTURES`` — deterministic access to the recorded Gate
  JSON payloads under ``tests/fixtures/gate/``.
* ``make_mock_transport(...)`` — an ``httpx.MockTransport`` that serves canned
  responses keyed by ``(method, path)`` from the fixtures, and can inject the
  three failure conditions later tests need: auth failure (401), rate-limit (429
  with ``X-Gate-RateLimit-*`` headers), and an unreachable/network error.

------------------------------------------------------------------------------
SEAM FOR TASK 2.1 (gate_client) — READ THIS BEFORE IMPLEMENTING THE TRANSPORT.
------------------------------------------------------------------------------
The real ``gate_client`` (task 2.1) will issue signed APIv4 requests over
``httpx``. To make it unit-testable against this mock WITHOUT a live venue,
``gate_client`` MUST expose an **injectable transport seam**: the ``httpx.Client``
(or ``AsyncClient``) it uses internally must be constructable with a caller-supplied
``transport=`` argument (an ``httpx.BaseTransport`` / ``httpx.MockTransport``).

Recommended shape for 2.1::

    def _client(*, transport: httpx.BaseTransport | None = None) -> httpx.Client:
        return httpx.Client(
            base_url="https://api.gateio.ws",
            transport=transport,          # tests pass make_mock_transport(...)
            timeout=...,
        )

Then 2.1's unit tests do::

    from tests.unit.mcp import broker_gate_fakes  # (importlib-by-path in practice)
    transport = broker_gate_fakes.make_mock_transport()
    result = gate_client.get_positions(transport=transport)   # or via a client factory

Constraints this mock assumes about 2.1's requests:
* base_url ``https://api.gateio.ws``; paths are prefixed ``/api/v4/tradfi/...``
  (the mock matches on the path SUFFIX after ``/api/v4``, so either a full or a
  relative path works).
* The create-order (``POST /tradfi/orders``) and close (``POST
  /tradfi/positions/{id}/close``) responses return a Queue Task ID under
  ``data.id`` — NOT an order/position id (reference gotcha #1). 2.1 must treat
  placement as async and poll; this mock returns the queue-task-id fixture.

This module deliberately does NOT import any broker production module, so it can
be created before ``gate_client`` exists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Literal

import httpx

# tests/unit/mcp/broker_gate_fakes.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures" / "gate"

FailMode = Literal["auth", "rate_limit", "network"]

# Rate-limit headers the venue returns on a 429 (reference: X-Gate-RateLimit-*).
# 2.1 discovers the effective limit at runtime from these (Req 9.5).
RATE_LIMIT_HEADERS: dict[str, str] = {
    "X-Gate-RateLimit-Requests-Remain": "0",
    "X-Gate-RateLimit-Limit": "300",
    "X-Gate-RateLimit-Reset-Timestamp": "1748563260",
}


def load_fixture(name: str) -> Any:
    """Load and parse a Gate fixture by file name (e.g. ``"positions.json"``)."""
    path = FIXTURES_DIR / name
    return json.loads(path.read_text())


# Endpoint path-suffix (after /api/v4) -> fixture file, for the readable GETs and
# the async-create / close POSTs. ``{...}`` segments match a single path segment.
# Order matters only for the regex-y dynamic paths, which we handle explicitly.
_GET_ROUTES: dict[str, str] = {
    "/tradfi/users/mt5-account": "users_mt5_account.json",
    "/tradfi/users/assets": "users_assets.json",
    "/tradfi/symbols/categories": "symbols_categories.json",
    "/tradfi/symbols/detail": "symbols_detail.json",
    "/tradfi/symbols": "symbols.json",
    "/tradfi/orders/history": "orders_history.json",
    "/tradfi/orders": "orders.json",
    "/tradfi/positions/history": "positions_history.json",
    "/tradfi/positions": "positions.json",
}

# Dynamic GET: /tradfi/symbols/{symbol}/tickers -> tickers fixture.
_TICKERS_RE = re.compile(r"/tradfi/symbols/[^/]+/tickers$")
# Dynamic POST: /tradfi/positions/{position_id}/close -> close queue-task-id.
_CLOSE_RE = re.compile(r"/tradfi/positions/[^/]+/close$")


def _normalize_path(url: httpx.URL) -> str:
    """Return the path suffix after an optional ``/api/v4`` prefix, no query."""
    path = url.path
    if path.startswith("/api/v4"):
        path = path[len("/api/v4"):]
    return path


def _json_response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def make_mock_transport(
    fail: FailMode | None = None,
    *,
    overrides: dict[tuple[str, str], Any] | None = None,
) -> httpx.MockTransport:
    """Build an ``httpx.MockTransport`` serving canned Gate fixtures.

    Parameters
    ----------
    fail:
        Inject a failure for ALL requests:
        * ``"auth"``    -> HTTP 401 (authentication failure, Req 9.1).
        * ``"rate_limit"`` -> HTTP 429 with ``X-Gate-RateLimit-*`` headers (Req 9.5).
        * ``"network"`` -> raises ``httpx.ConnectError`` (unreachable, Req 9.2).
        ``None`` (default) serves the success fixtures.
    overrides:
        Optional ``{(METHOD, path_suffix): payload}`` map to override or add a
        canned response for a specific route (later tasks can stub edge cases,
        e.g. an empty positions/history set, without new fixture files).

    The returned transport is consumable directly by ``httpx.Client(transport=...)``
    and by task 2.1's injectable-transport seam (see module docstring).
    """
    overrides = overrides or {}

    def handler(request: httpx.Request) -> httpx.Response:
        if fail == "network":
            raise httpx.ConnectError("mock venue unreachable", request=request)
        if fail == "auth":
            return _json_response(
                {"label": "AUTHENTICATION_FAILED", "message": "invalid key"},
                status=401,
            )
        if fail == "rate_limit":
            resp = _json_response(
                {"label": "TOO_MANY_REQUESTS", "message": "rate limited"},
                status=429,
            )
            resp.headers.update(RATE_LIMIT_HEADERS)
            return resp

        method = request.method.upper()
        path = _normalize_path(request.url)

        # Explicit per-test overrides win.
        if (method, path) in overrides:
            return _json_response(overrides[(method, path)])

        if method == "GET":
            if _TICKERS_RE.search(path):
                return _json_response(load_fixture("symbol_tickers.json"))
            route = _GET_ROUTES.get(path)
            if route is not None:
                return _json_response(load_fixture(route))

        if method == "POST":
            if _CLOSE_RE.search(path):
                return _json_response(load_fixture("position_close.json"))
            if path == "/tradfi/orders":
                return _json_response(load_fixture("orders_create.json"))

        # No fixture for this route -> 404 keeps the mock honest about coverage.
        return _json_response(
            {"label": "NOT_FOUND", "message": f"no fixture for {method} {path}"},
            status=404,
        )

    return httpx.MockTransport(handler)


def make_request_handler(
    fail: FailMode | None = None,
    *,
    overrides: dict[tuple[str, str], Any] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """Return the bare request->response handler (for callers that build their
    own ``httpx.MockTransport`` or want to compose handlers)."""
    transport = make_mock_transport(fail, overrides=overrides)
    return transport.handler  # type: ignore[attr-defined]
