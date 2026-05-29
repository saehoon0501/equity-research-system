"""Broker (Gate TradFi CFD) signed REST transport — Task 2.1.

Source of truth: ``.kiro/specs/broker-cfd-adapter/design.md`` — the ``gate_client``
Components row (Transport layer) + its "API Contract", the Architecture dependency
direction (``config → gate_client``), "Error Handling", "Technology Stack", and
"Security Considerations" (SIGN per request; secrets never logged/surfaced).

Layer position (``models → config → gate_client → …``): gate_client sits just
above ``config``. It owns ONE thing — execute a single signed APIv4 ``/tradfi``
request and return the RAW venue JSON — and NOTHING about domain semantics. The
decision→action mapping, polling, double-send guard, and typed readouts all live
in later layers (``mappers`` / ``core``). This module knows endpoints + transport,
never business rules.

Contract (Req 1.7, 9.1, 9.2, 9.5):

1. **SIGN per request.** Gate APIv4 HMAC-SHA512 over the canonical string
   ``"{METHOD}\n{path}\n{query_string}\n{hex_sha512(body)}\n{timestamp}"``. The
   signing function (:func:`sign`) is pure + unit-testable. Headers sent: ``KEY``,
   ``SIGN``, ``Timestamp`` (plus ``Content-Type`` for a JSON body).

2. **Return raw venue JSON only.** On a 2xx the parsed ``dict``/``list`` body is
   returned verbatim — venue numeric fields stay STRINGS; ``mappers`` parses at the
   domain boundary (P13 — this adapter validates its own types downstream, not
   here).

3. **Never raise.** Every failure class returns a STRUCTURED
   :class:`TransportError`:
   - missing credentials / auth failure (HTTP 401) -> ``error_class="auth"``
     (Req 9.1); a missing-credential read transmits NOTHING.
   - venue error (non-2xx other than 401/429) -> ``error_class="venue_error"``
     (Req 9.2).
   - unreachable / network failure -> ``error_class="network"`` (Req 9.2).
   - rate limited (HTTP 429) -> ``error_class="rate_limit"`` (Req 9.5).

4. **Rate limits (Req 9.5).** Parse the ``X-Gate-RateLimit-*`` response headers and
   discover the effective limit at RUNTIME (never hardcoded). On HTTP 429, BACK OFF
   (sleep) rather than retry immediately; the ``sleep`` callable is INJECTABLE
   (defaults to :func:`time.sleep`) so tests do not really sleep. The backoff delay
   is derived from the venue's ``X-Gate-RateLimit-Reset-Timestamp`` header when
   present (bounded), else a small default.

5. **Secrets never logged / never returned.** Only the missing-variable name(s)
   and venue ``label``/``message`` ever appear in a structured error — never the
   ``KEY``/``SECRET`` value or the computed ``SIGN``.

6. **Injectable transport (Req 1.7 testability seam).** Every request runs through
   an ``httpx.Client`` constructed with a caller-supplied ``transport=`` (the Task
   1.4 ``broker_gate_fakes.make_mock_transport(...)``); production passes ``None``
   and httpx uses a real transport. This layer executes a single request and
   returns — the submit→poll→reconcile loop is ``core`` (Task 4.3), NOT here.

Credentials are resolved FRESH per call via :func:`config.resolve_credentials`
(operator key-rotation needs no restart). ``config`` is the only intra-broker
import; ``models`` is not needed (this layer returns raw JSON, not domain types).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Union
from urllib.parse import urlencode

import httpx

# config is the layer directly below gate_client (dependency direction
# config -> gate_client). Imported by name; the broker dir is on sys.path when run
# under the broker venv / loaded by the importlib-by-path test harness.
import config as _config

# Gate APIv4 base URL (design "Allowed Dependencies" / API Contract).
_BASE_URL = "https://api.gateio.ws"
_API_V4_PREFIX = "/api/v4"

# Conservative network timeout (the daemon owns polling cadence; a single request
# must not hang the caller). httpx default is no timeout, which is unsafe here.
_REQUEST_TIMEOUT_S = 15.0

# Backoff bound on a 429 when the venue gives no usable reset hint. We never block
# the caller for long — the conservative posture is "surface a rate_limit error
# after a brief, bounded back-off", not "retry forever".
_DEFAULT_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 5.0

# Rate-limit response headers the venue returns (Req 9.5 — discovered at runtime).
_HDR_LIMIT = "X-Gate-RateLimit-Limit"
_HDR_REMAIN = "X-Gate-RateLimit-Requests-Remain"
_HDR_RESET = "X-Gate-RateLimit-Reset-Timestamp"


# --------------------------------------------------------------------------- #
# Structured results — never raise; always return one of these.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TransportResult:
    """A successful transport call: the RAW parsed venue JSON (``dict`` | ``list``).

    ``ok`` is always ``True``. ``data`` is returned verbatim — no domain mapping,
    no float coercion (venue numerics stay strings; ``mappers`` parses later).
    ``rate_limit`` carries any parsed ``X-Gate-RateLimit-*`` headers so a caller
    can pace itself (Req 9.5).
    """

    data: Any
    status_code: int
    ok: bool = True
    rate_limit: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class TransportError:
    """A structured transport failure. ``ok`` is always ``False``; the call NEVER
    raised (Req 9.1, 9.2, 9.5).

    ``error_class`` is one of:
      - ``"auth"``         — missing credentials or HTTP 401 (Req 9.1).
      - ``"network"``      — unreachable / connection failure (Req 9.2).
      - ``"rate_limit"``   — HTTP 429; backoff was performed (Req 9.5).
      - ``"venue_error"``  — any other non-2xx venue response (Req 9.2).

    ``error`` is a structured, SECRET-FREE message (Security Considerations): it
    never contains a credential value or the computed SIGN — only the missing
    variable name(s) and/or the venue's ``label``/``message``. ``rate_limit`` is
    populated for a 429 from the response headers (Req 9.5).
    """

    error_class: str
    error: str
    ok: bool = False
    status_code: Optional[int] = None
    rate_limit: Optional[dict[str, Any]] = None
    raw: Optional[Any] = None


# A request returns exactly one of these. Both carry ``ok`` so callers can branch
# without isinstance checks.
TransportOutcome = Union[TransportResult, TransportError]


# --------------------------------------------------------------------------- #
# SIGN — pure, unit-testable HMAC-SHA512 over the canonical APIv4 string.
# --------------------------------------------------------------------------- #


def sign(
    *,
    method: str,
    path: str,
    query_string: str,
    body: str,
    timestamp: str,
    secret: str,
) -> str:
    """Compute the Gate APIv4 ``SIGN`` for one request. PURE — no I/O, no globals.

    SIGN = HMAC-SHA512(secret, payload) where::

        payload = "{METHOD}\\n{path}\\n{query_string}\\n{hex_sha512(body)}\\n{timestamp}"

    ``path`` is the full request path (including the ``/api/v4`` prefix), ``query_string``
    is the URL-encoded query WITHOUT the leading ``?`` (empty string when none), and
    ``body`` is the exact request body text the wire will carry (empty string for a
    bodiless GET). Returns the lowercase hex digest (128 chars).

    The ``secret`` is consumed only to key the HMAC; it is never logged or returned
    by this function (Security Considerations).
    """
    body_hash = hashlib.sha512(body.encode("utf-8")).hexdigest()
    payload = f"{method.upper()}\n{path}\n{query_string}\n{body_hash}\n{timestamp}"
    return hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha512
    ).hexdigest()


# --------------------------------------------------------------------------- #
# Internal helpers.
# --------------------------------------------------------------------------- #


def _full_path(path: str) -> str:
    """Return the full request path including the ``/api/v4`` prefix.

    Accepts either a relative ``/tradfi/...`` path or an already-prefixed
    ``/api/v4/tradfi/...`` path; normalizes to the prefixed form used for signing
    and for the wire request.
    """
    if not path.startswith("/"):
        path = "/" + path
    if path.startswith(_API_V4_PREFIX):
        return path
    return _API_V4_PREFIX + path


def _encode_query(params: Optional[Mapping[str, Any]]) -> str:
    """URL-encode query params deterministically (sorted) into a signable string."""
    if not params:
        return ""
    # Sort for a stable, reproducible signing payload.
    items = sorted((str(k), str(v)) for k, v in params.items())
    return urlencode(items)


def _encode_body(body: Optional[Any]) -> str:
    """Serialize a JSON body to the exact text the wire will carry (or "" if none).

    Uses compact separators + sorted keys so the signed text matches the sent text
    deterministically.
    """
    if body is None:
        return ""
    import json

    return json.dumps(body, separators=(",", ":"), sort_keys=True)


def _parse_rate_limit(headers: httpx.Headers) -> Optional[dict[str, Any]]:
    """Discover the effective rate-limit state at runtime from the response headers
    (Req 9.5). Returns ``None`` when no rate-limit headers are present."""
    limit = headers.get(_HDR_LIMIT)
    remaining = headers.get(_HDR_REMAIN)
    reset = headers.get(_HDR_RESET)
    if limit is None and remaining is None and reset is None:
        return None
    return {"limit": limit, "remaining": remaining, "reset_timestamp": reset}


def _backoff_seconds(rate_limit: Optional[dict[str, Any]]) -> float:
    """Derive a bounded backoff delay from the venue's reset hint (Req 9.5).

    Prefer ``X-Gate-RateLimit-Reset-Timestamp`` (seconds-until-reset, bounded to
    ``_MAX_BACKOFF_S``); fall back to a small default. Never hardcodes the limit
    itself — only the *bound* on how long we are willing to pause.
    """
    if rate_limit:
        reset = rate_limit.get("reset_timestamp")
        if reset is not None:
            try:
                delta = float(reset) - time.time()
            except (TypeError, ValueError):
                delta = _DEFAULT_BACKOFF_S
            if delta > 0:
                return min(delta, _MAX_BACKOFF_S)
    return _DEFAULT_BACKOFF_S


def _safe_venue_message(payload: Any) -> str:
    """Extract a SECRET-FREE venue error string from a parsed body (``label`` /
    ``message``). Never includes request data, headers, or credentials."""
    if isinstance(payload, dict):
        label = payload.get("label") or ""
        message = payload.get("message") or ""
        joined = " ".join(p for p in (str(label), str(message)) if p).strip()
        if joined:
            return joined
    return ""


# --------------------------------------------------------------------------- #
# The single public request entrypoint.
# --------------------------------------------------------------------------- #


def request(
    method: str,
    path: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    body: Optional[Any] = None,
    transport: Optional[httpx.BaseTransport] = None,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = _REQUEST_TIMEOUT_S,
) -> TransportOutcome:
    """Execute ONE signed APIv4 ``/tradfi`` request and return raw venue JSON.

    Parameters
    ----------
    method, path:
        HTTP method and the ``/tradfi/...`` path (with or without the ``/api/v4``
        prefix).
    params:
        Optional query parameters (signed into the payload).
    body:
        Optional JSON-serializable request body (POST/PUT). Serialized compactly +
        deterministically so the signed text matches the wire text.
    transport:
        Injectable ``httpx.BaseTransport`` — tests pass the Task 1.4
        ``make_mock_transport(...)``; production passes ``None`` (real transport).
    sleep:
        Injectable backoff callable (defaults to :func:`time.sleep`); invoked on a
        429 so callers/tests control pacing.
    timeout:
        Per-request timeout (seconds).

    Returns
    -------
    :class:`TransportResult` on a 2xx (raw parsed JSON), else a structured
    :class:`TransportError`. NEVER raises (Req 9.1, 9.2, 9.5).
    """
    # 1) Resolve credentials FRESH per call; missing -> structured auth error,
    #    NO transmit (Req 9.1). The error names only the missing variable(s).
    creds = _config.resolve_credentials()
    if not creds.ok:
        return TransportError(
            error_class="auth",
            error=creds.error or "missing Gate credentials",
            status_code=None,
        )

    full_path = _full_path(path)
    query_string = _encode_query(params)
    body_text = _encode_body(body)
    timestamp = str(int(time.time()))

    # 2) SIGN per request (Security Considerations). The signature/secret are never
    #    logged or surfaced.
    signature = sign(
        method=method,
        path=full_path,
        query_string=query_string,
        body=body_text,
        timestamp=timestamp,
        secret=creds.api_secret or "",
    )

    headers = {
        "KEY": creds.api_key or "",
        "SIGN": signature,
        "Timestamp": timestamp,
        "Accept": "application/json",
    }
    if body_text:
        headers["Content-Type"] = "application/json"

    url = full_path + (("?" + query_string) if query_string else "")

    # 3) Execute via httpx against the injected transport; never raise (Req 9.2).
    try:
        with httpx.Client(
            base_url=_BASE_URL, transport=transport, timeout=timeout
        ) as client:
            response = client.request(
                method.upper(),
                url,
                headers=headers,
                content=body_text.encode("utf-8") if body_text else None,
            )
    except httpx.TransportError as exc:
        # Unreachable / connection failure -> structured network error (Req 9.2).
        # str(exc) is the httpx message only — no credentials are present in it.
        return TransportError(
            error_class="network",
            error=f"venue unreachable: {type(exc).__name__}: {exc}",
            status_code=None,
        )
    except Exception as exc:  # defense-in-depth: never raise out of this layer.
        return TransportError(
            error_class="network",
            error=f"transport failure: {type(exc).__name__}: {exc}",
            status_code=None,
        )

    rate_limit = _parse_rate_limit(response.headers)

    # 4) HTTP 429 -> back off (injected sleep) rather than retry immediately, then
    #    surface a structured, rate-limit-aware error (Req 9.5). The effective
    #    limit is discovered at runtime from the response headers.
    if response.status_code == 429:
        sleep(_backoff_seconds(rate_limit))
        return TransportError(
            error_class="rate_limit",
            error=_safe_venue_message(_try_json(response)) or "rate limited (HTTP 429)",
            status_code=429,
            rate_limit=rate_limit,
        )

    # 5) HTTP 401 -> structured auth error, no raise (Req 9.1).
    if response.status_code == 401:
        return TransportError(
            error_class="auth",
            error=_safe_venue_message(_try_json(response)) or "authentication failed (HTTP 401)",
            status_code=401,
            rate_limit=rate_limit,
        )

    # 6) Any other non-2xx -> structured venue error (Req 9.2).
    if not (200 <= response.status_code < 300):
        return TransportError(
            error_class="venue_error",
            error=_safe_venue_message(_try_json(response))
            or f"venue error (HTTP {response.status_code})",
            status_code=response.status_code,
            rate_limit=rate_limit,
            raw=_try_json(response),
        )

    # 7) Success -> return RAW parsed JSON (no domain mapping at this layer).
    parsed = _try_json(response)
    if parsed is _PARSE_FAILED:
        return TransportError(
            error_class="venue_error",
            error="venue returned a non-JSON body",
            status_code=response.status_code,
            rate_limit=rate_limit,
        )
    return TransportResult(
        data=parsed, status_code=response.status_code, rate_limit=rate_limit
    )


# Sentinel for a body that failed to JSON-parse (distinct from a valid ``None``).
_PARSE_FAILED = object()


def _try_json(response: httpx.Response) -> Any:
    """Parse a response body as JSON, returning :data:`_PARSE_FAILED` on failure
    (never raises). Used so a malformed body becomes a structured error, not an
    exception (Error Handling: boundary parsing)."""
    try:
        return response.json()
    except Exception:
        return _PARSE_FAILED


# --------------------------------------------------------------------------- #
# Thin method-convenience wrappers (optional; ``core`` may call ``request``
# directly). Each just forwards to :func:`request`.
# --------------------------------------------------------------------------- #


def get(
    path: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    transport: Optional[httpx.BaseTransport] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> TransportOutcome:
    """GET ``path`` (signed). See :func:`request`."""
    return request("GET", path, params=params, transport=transport, sleep=sleep)


def post(
    path: str,
    *,
    body: Optional[Any] = None,
    params: Optional[Mapping[str, Any]] = None,
    transport: Optional[httpx.BaseTransport] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> TransportOutcome:
    """POST ``path`` with a JSON ``body`` (signed). See :func:`request`."""
    return request(
        "POST", path, params=params, body=body, transport=transport, sleep=sleep
    )


__all__ = [
    "sign",
    "request",
    "get",
    "post",
    "TransportResult",
    "TransportError",
    "TransportOutcome",
]
