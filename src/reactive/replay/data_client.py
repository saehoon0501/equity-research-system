"""Massive historical REST transport — Task 1.2 (transport layer only).

Source of truth: ``.kiro/specs/reactive-replay-harness/design.md`` — the
``data_client`` component block ("structured ``Result``/``Error`` (never raises),
rate-limit from response headers, ``apiKey`` auth from ``.env``"); the Technology
Stack "Data access" row ("new direct Massive REST client (``httpx``) … landed
FRED … ``gate_client.py`` transport pattern; ``adjusted=false``"); and the Allowed
Dependencies "External" row ("Massive TradFi-stocks REST APIv2/v3
(``MASSIVE_API_KEY``, ``MASSIVE_REST_URL`` from ``.env``); ``httpx``. Mirror
``src/mcp/broker/gate_client.py``'s structured-result / no-raise /
rate-limit-from-headers transport pattern (apiKey auth, not HMAC)."). Satisfies
the transport that Requirement 4 AC 4.1's point-in-time fetches ride on.

Scope (Task 1.2 only — the TRANSPORT): this module owns ONE thing — execute a
single Massive REST request and return the RAW parsed JSON in a structured
:class:`Result`, or a structured :class:`Error` on any failure (it NEVER raises).
The typed point-in-time fetch methods (``fetch_daily_bars`` / ``fetch_intraday`` /
``fetch_quotes`` / ``fetch_corporate_actions`` / ``fetch_rf_yield``) that satisfy
the ``types.DataPort`` protocol are Task 1.3 — this module does NOT implement them
and does NOT import ``types.py`` yet (dependency root stays clean).

Contract (mirrors ``gate_client.py`` but adapts auth + headers to Massive):

1. **apiKey auth, NOT HMAC.** Massive uses a simple ``apiKey`` query parameter
   (Polygon-compatible — see ``src/mcp/massive/server.py``), read FRESH per call
   from ``MASSIVE_API_KEY`` (operator key rotation needs no restart). There is no
   request signing — the Gate HMAC ``SIGN`` is deliberately NOT copied. The base
   URL is ``MASSIVE_REST_URL`` (default the Massive REST host), also read fresh.

2. **Return raw venue JSON only.** On a 2xx the parsed ``dict``/``list`` body is
   returned verbatim; the typed fetch methods (Task 1.3) parse at the domain
   boundary (P13 — validate types there, not here).

3. **Never raise.** Every failure class returns a STRUCTURED :class:`Error`:
   - missing ``MASSIVE_API_KEY`` / HTTP 401 / 403 -> ``error_class="auth"``; a
     missing-credential read transmits NOTHING.
   - HTTP 429 -> ``error_class="rate_limit"`` (a bounded back-off is performed via
     the injected ``sleep``, then the error is returned — no retry loop).
   - any other server-responded non-2xx (incl. 5xx) -> ``error_class="venue_error"``.
   - an httpx transport exception (connect/timeout — NO response) ->
     ``error_class="network"``.

4. **Rate limits parsed at RUNTIME from headers (Req 4-family / design).** Massive's
   exact per-tier limits are an unverified live-probe item and the endpoint shape
   is a moving product, so headers are parsed DEFENSIVELY: whatever rate-limit /
   ``Retry-After`` headers are present are captured; ``None`` when absent. The
   ``429 -> rate_limit`` classification does NOT depend on any specific header being
   present (Massive/Polygon often returns 429 with only a JSON body).

5. **Secrets never logged / never returned.** Massive's secret rides in the URL
   QUERY STRING (not, as for Gate, in an HMAC header) — so every structured
   ``Error`` message is built ONLY from ``type(exc).__name__`` and the venue body's
   safe ``error``/``message``/``status`` strings; the request URL/params (which
   carry ``apiKey``) are NEVER interpolated into an error.

6. **Injectable transport (testability seam, R9.2 inner-ring isolation).** Every
   request runs through an ``httpx.Client`` constructed with a caller-supplied
   ``transport=`` (tests pass an ``httpx.MockTransport``); production passes
   ``None`` and httpx uses a real transport. This layer executes a single request
   and returns.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Union

import httpx

# Default Massive REST host (Polygon-compatible). Matches src/mcp/massive/server.py.
_DEFAULT_REST_URL = "https://api.massive.com"

# Conservative per-request timeout (httpx default is none, unsafe here).
_REQUEST_TIMEOUT_S = 15.0

# Backoff bound on a 429 when the venue gives no usable reset hint. We back off at
# most once then surface a structured rate_limit error — never retry forever.
_DEFAULT_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 5.0

# Rate-limit / throttle response headers parsed DEFENSIVELY at runtime. Massive's
# exact tier limits are an unverified live-probe item and the shape is a moving
# product, so we capture whatever subset is present rather than assuming a fixed
# header family. Lower-cased; httpx.Headers lookups are case-insensitive anyway.
_RATE_LIMIT_HEADERS = (
    "retry-after",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
)


# --------------------------------------------------------------------------- #
# Structured results — never raise; always return one of these.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Result:
    """A successful transport call: the RAW parsed Massive JSON (``dict`` | ``list``).

    ``ok`` is always ``True``. ``data`` is returned verbatim (no domain mapping —
    the Task 1.3 fetch methods parse at the boundary). ``rate_limit`` carries any
    parsed rate-limit headers so a caller can pace itself.
    """

    data: Any
    status_code: int
    ok: bool = True
    rate_limit: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class Error:
    """A structured transport failure. ``ok`` is always ``False``; the call NEVER
    raised.

    ``error_class`` is one of:
      - ``"auth"``         — missing ``MASSIVE_API_KEY`` or HTTP 401/403.
      - ``"network"``      — an httpx transport exception (connect/timeout; no
        response was received).
      - ``"rate_limit"``   — HTTP 429; a bounded back-off was performed.
      - ``"venue_error"``  — any other server-responded non-2xx (including 5xx).

    ``error`` is a SECRET-FREE message: it is built only from the exception type
    name and the venue body's safe ``error``/``message``/``status`` strings — the
    request URL/params (which carry the ``apiKey``) are NEVER interpolated.
    """

    error_class: str
    error: str
    ok: bool = False
    status_code: Optional[int] = None
    rate_limit: Optional[dict[str, Any]] = None
    raw: Optional[Any] = None


# A request returns exactly one of these. Both carry ``ok`` so callers can branch
# without isinstance checks.
TransportOutcome = Union[Result, Error]


# --------------------------------------------------------------------------- #
# Credential / config resolution — FRESH per call (no restart on rotation).
# --------------------------------------------------------------------------- #


def _resolve_api_key() -> Optional[str]:
    """Read ``MASSIVE_API_KEY`` fresh per call; ``None``/empty -> missing."""
    key = (os.environ.get("MASSIVE_API_KEY") or "").strip()
    return key or None


def _resolve_base_url() -> str:
    """Read ``MASSIVE_REST_URL`` fresh per call; default the Massive REST host."""
    return (os.environ.get("MASSIVE_REST_URL") or _DEFAULT_REST_URL).rstrip("/")


# --------------------------------------------------------------------------- #
# Internal helpers.
# --------------------------------------------------------------------------- #


def _normalize_path(path: str) -> str:
    """Ensure the path has a leading slash (Massive paths are ``/v2/...``)."""
    return path if path.startswith("/") else "/" + path


def _parse_rate_limit(headers: httpx.Headers) -> Optional[dict[str, Any]]:
    """Discover rate-limit state at runtime from response headers, DEFENSIVELY.

    Returns whatever subset of the known throttle headers is present, or ``None``
    when none are. Never assumes a specific header exists (Massive's tier limits
    are an unverified, moving-product shape).
    """
    found = {h: headers.get(h) for h in _RATE_LIMIT_HEADERS if headers.get(h) is not None}
    return found or None


def _backoff_seconds(rate_limit: Optional[dict[str, Any]]) -> float:
    """Derive a bounded backoff delay from a ``Retry-After`` hint if present.

    Prefer the ``Retry-After`` header (seconds, bounded to ``_MAX_BACKOFF_S``);
    fall back to a small default. Only the *bound* is hardcoded — never the limit.
    """
    if rate_limit:
        retry_after = rate_limit.get("retry-after")
        if retry_after is not None:
            try:
                delta = float(retry_after)
            except (TypeError, ValueError):
                delta = _DEFAULT_BACKOFF_S
            if delta > 0:
                return min(delta, _MAX_BACKOFF_S)
    return _DEFAULT_BACKOFF_S


def _safe_venue_message(payload: Any) -> str:
    """Extract a SECRET-FREE venue error string from a parsed body.

    Massive error bodies carry ``error`` / ``message`` / ``status`` fields. Never
    includes the request URL, params, or any credential.
    """
    if isinstance(payload, dict):
        parts = [
            str(payload.get(k))
            for k in ("error", "message", "status")
            if payload.get(k)
        ]
        joined = " ".join(parts).strip()
        if joined:
            return joined
    return ""


# Sentinel for a body that failed to JSON-parse (distinct from a valid ``None``).
_PARSE_FAILED = object()


def _try_json(response: httpx.Response) -> Any:
    """Parse a response body as JSON, returning :data:`_PARSE_FAILED` on failure
    (never raises) so a malformed body becomes a structured error, not an
    exception."""
    try:
        return response.json()
    except Exception:
        return _PARSE_FAILED


# --------------------------------------------------------------------------- #
# The single public request entrypoint.
# --------------------------------------------------------------------------- #


def request(
    method: str,
    path: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    transport: Optional[httpx.BaseTransport] = None,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = _REQUEST_TIMEOUT_S,
) -> TransportOutcome:
    """Execute ONE Massive REST request and return the raw venue JSON.

    Parameters
    ----------
    method, path:
        HTTP method and the Massive ``/v2/...`` or ``/v3/...`` path.
    params:
        Optional query parameters. The ``apiKey`` is injected here automatically;
        callers pass only domain params (e.g. ``{"adjusted": "false"}``).
    transport:
        Injectable ``httpx.BaseTransport`` — tests pass an ``httpx.MockTransport``;
        production passes ``None`` (real transport). The R9.2 isolation seam.
    sleep:
        Injectable backoff callable (defaults to :func:`time.sleep`); invoked once
        on a 429 so tests/callers control pacing without really sleeping.
    timeout:
        Per-request timeout (seconds).

    Returns
    -------
    :class:`Result` on a 2xx (raw parsed JSON), else a structured :class:`Error`.
    NEVER raises.
    """
    # 1) Resolve the api key FRESH per call; missing -> structured auth error and
    #    NO transmit. The error names only the missing variable, never a value.
    api_key = _resolve_api_key()
    if api_key is None:
        return Error(
            error_class="auth",
            error="missing MASSIVE_API_KEY",
            status_code=None,
        )

    base_url = _resolve_base_url()
    full_path = _normalize_path(path)

    # apiKey rides the query string (Massive simple-auth, NOT an HMAC header).
    query: dict[str, Any] = dict(params or {})
    query["apiKey"] = api_key

    # 2) Execute via httpx against the injected transport; never raise.
    try:
        with httpx.Client(
            base_url=base_url, transport=transport, timeout=timeout
        ) as client:
            response = client.request(method.upper(), full_path, params=query)
    except httpx.TransportError as exc:
        # Unreachable / connection failure / timeout -> structured network error.
        # Only the exception TYPE NAME is surfaced — never str(exc), which is
        # free-form and could (unlike Gate, whose secret is in a header) embed the
        # request URL that carries the apiKey query param. Type name is secret-free.
        return Error(
            error_class="network",
            error=f"massive unreachable: {type(exc).__name__}",
            status_code=None,
        )
    except Exception as exc:  # defense-in-depth: never raise out of this layer.
        return Error(
            error_class="network",
            error=f"transport failure: {type(exc).__name__}",
            status_code=None,
        )

    rate_limit = _parse_rate_limit(response.headers)

    # 3) HTTP 429 -> back off once (injected sleep), then surface a structured
    #    rate-limit error. Classification does NOT depend on any header (Massive
    #    often returns a bare-body 429).
    if response.status_code == 429:
        sleep(_backoff_seconds(rate_limit))
        return Error(
            error_class="rate_limit",
            error=_safe_venue_message(_try_json(response)) or "rate limited (HTTP 429)",
            status_code=429,
            rate_limit=rate_limit,
        )

    # 4) HTTP 401 / 403 -> structured auth error (403 is Massive plan-tier denial).
    if response.status_code in (401, 403):
        return Error(
            error_class="auth",
            error=_safe_venue_message(_try_json(response))
            or f"authentication/authorization failed (HTTP {response.status_code})",
            status_code=response.status_code,
            rate_limit=rate_limit,
        )

    # 5) Any other server-responded non-2xx (including 5xx) -> venue error. The
    #    connection itself succeeded, so this is NOT a network error.
    if not (200 <= response.status_code < 300):
        return Error(
            error_class="venue_error",
            error=_safe_venue_message(_try_json(response))
            or f"venue error (HTTP {response.status_code})",
            status_code=response.status_code,
            rate_limit=rate_limit,
            raw=_try_json(response),
        )

    # 6) Success -> return RAW parsed JSON (no domain mapping at this layer).
    parsed = _try_json(response)
    if parsed is _PARSE_FAILED:
        return Error(
            error_class="venue_error",
            error="venue returned a non-JSON body",
            status_code=response.status_code,
            rate_limit=rate_limit,
        )
    return Result(
        data=parsed, status_code=response.status_code, rate_limit=rate_limit
    )


# --------------------------------------------------------------------------- #
# Thin GET convenience wrapper (Massive historical reads are all GETs).
# --------------------------------------------------------------------------- #


def get(
    path: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    transport: Optional[httpx.BaseTransport] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> TransportOutcome:
    """GET ``path`` with the ``apiKey`` injected. See :func:`request`."""
    return request("GET", path, params=params, transport=transport, sleep=sleep)


__all__ = [
    "request",
    "get",
    "Result",
    "Error",
    "TransportOutcome",
]
