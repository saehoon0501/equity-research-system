"""Massive historical REST client — Tasks 1.2 (transport) + 1.3 (fetch methods).

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

Scope, Task 1.2 — the TRANSPORT (lower half): execute a single Massive REST
request and return the RAW parsed JSON in a structured :class:`Result`, or a
structured :class:`Error` on any failure (it NEVER raises).

Scope, Task 1.3 — the typed point-in-time fetch methods (upper-of-lower half):
:class:`MassiveDataClient` implements the ``types.DataPort`` protocol on top of
the 1.2 transport — ``fetch_daily_bars`` / ``fetch_intraday`` / ``fetch_quotes`` /
``fetch_corporate_actions`` / ``fetch_rf_yield`` plus the extra fetches the task
names that the protocol does not pin (``fetch_trades`` / ``fetch_grouped_daily`` /
``fetch_delisted_tickers``). Per design §"data_client (Massive historical REST)":
all aggregate reads send ``adjusted=false`` (R4.2 — the as-of split *adjustment*
itself is task 2.1 / features_adapter, design §"Core algorithms #4"); every fetch
is point-in-time bounded so no row timestamped after the requested instant feeds a
decision (R4.1); the per-request row cap is paginated past via the ``next_url``
cursor (R4.4); a delisted/IPO name's traded sub-window is returned as-is (R4.4 —
NOT a depth failure). **Fail explicitly (R4.3): the DataPort methods return bare
``list``/``dict``/``float`` (no ``Result|Error`` union), so a window that predates
available depth — surfaced by the venue's EXPLICIT 403 ``NOT_AUTHORIZED`` (or any
transport ``Error`` at any page, incl. mid-pagination) — RAISES a typed
:class:`DataFetchError`, discarding everything accumulated; it never returns a
silently-truncated/partial window.** 4.3 and 4.4 are one invariant: complete iff
every page succeeded and ``next_url`` terminated naturally.

FRED rf-yield (R-feature input) rides its OWN injectable transport seam (its own
``api_key`` param / ``FRED_API_KEY`` / ``api.stlouisfed.org``), NOT the Massive
``request()`` — a small dedicated helper here per the task boundary ("if FRED
needs a tiny helper keep it in data_client"). Series ``DGS1`` matches the landed
reactive consumer (``src/reactive/features.py`` rf_yield_pct, ``src/overlays/
tactical/bin_classifier.py``); the helper walks back over FRED's ``"."`` missing
prints to the last good value at-or-before the requested day (weekend/holiday).

This module imports ``types`` ONLY structurally (``MassiveDataClient`` satisfies
the ``runtime_checkable`` ``DataPort`` by shape, not inheritance) — the dependency
direction (``types -> data_client``) holds; nothing imports upward.

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
from datetime import date, datetime, timezone
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


# =========================================================================== #
# Task 1.3 — the typed point-in-time DataPort fetch methods.
#
# These ride the transport above but parse + bound + paginate at the domain
# boundary. ``MassiveDataClient`` satisfies the ``types.DataPort`` runtime_checkable
# Protocol structurally (R9.2 injection seam) and adds the extra fetches the task
# names (trades, grouped-daily, delisted tickers) that the protocol does not pin.
# =========================================================================== #


# FRED rf-yield series: DGS1 (1Y CMT) — matches the landed reactive consumer
# (src/reactive/features.py rf_yield_pct; src/overlays/tactical/bin_classifier.py).
_FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
_RF_SERIES_ID = "DGS1"

# Polygon/Massive aggregate ``t`` is epoch MILLIseconds; trade/quote SIP/participant
# timestamps are epoch NANOseconds. Point-in-time bounding is unit-aware.
_MS_PER_S = 1_000
_NS_PER_S = 1_000_000_000

# A hard cap on cursor follows: defense-in-depth so a malformed/looping ``next_url``
# can never spin forever. Real windows page a handful of times.
_MAX_PAGES = 10_000


class DataFetchError(Exception):
    """A point-in-time fetch FAILED EXPLICITLY (R4.3) — never a partial window.

    Raised when any page of a fetch returns a transport :class:`Error` (the
    venue's explicit beyond-tier-depth 403 ``NOT_AUTHORIZED``, a 5xx, a 429, an
    auth failure, or a network error — at any page, including mid-pagination).
    The ``DataPort`` methods return bare ``list``/``dict``/``float`` (no
    ``Result|Error`` union), so failing explicitly here means RAISING: anything
    accumulated so far is discarded rather than returned as a silently-truncated
    window. 4.3 (fail-on-exceeds-depth) and 4.4 (paginate-to-completion) are one
    invariant — a result is complete iff every page succeeded and the ``next_url``
    cursor terminated naturally.
    """

    def __init__(self, message: str, *, error_class: Optional[str] = None) -> None:
        super().__init__(message)
        self.error_class = error_class


# --------------------------------------------------------------------------- #
# Point-in-time bounding helpers (unit-aware; inclusive of the boundary).
# --------------------------------------------------------------------------- #


def _day_end_epoch(day: str, *, unit: int) -> int:
    """The inclusive upper bound for ``day`` (ISO date) in the given epoch ``unit``.

    The boundary date is INCLUSIVE (R4.1 lets the as-of instant's own rows in), so
    the cutoff is the END of ``day`` (23:59:59.999... UTC) expressed in ``unit``
    (``_MS_PER_S`` for aggregate ``t``, ``_NS_PER_S`` for SIP/participant ts).
    """
    d = date.fromisoformat(day[:10])
    # Start of the NEXT day, minus one tick — i.e. anything strictly before
    # midnight of day+1 is "<= day". We compare with ``<`` against that boundary.
    next_midnight = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    start_epoch_s = int(next_midnight.timestamp()) + 86_400  # +1 calendar day
    return start_epoch_s * unit


def _bound_rows_by_ts(
    rows: list[dict], *, until_day: str, ts_field: str, unit: int
) -> list[dict]:
    """Drop rows whose ``ts_field`` is strictly after the end of ``until_day`` (R4.1).

    Rows missing the timestamp field are kept (cannot prove they are future); the
    domain parser downstream validates shape (P13 — types are not our concern here).
    """
    cutoff = _day_end_epoch(until_day, unit=unit)
    kept: list[dict] = []
    for r in rows:
        ts = r.get(ts_field)
        if ts is None or ts < cutoff:
            kept.append(r)
    return kept


def _bound_by_date(
    rows: list[dict], *, until_day: str, date_field: str
) -> list[dict]:
    """Drop rows whose ISO ``date_field`` is strictly after ``until_day`` (R4.1).

    For reference endpoints (splits/dividends) whose point-in-time field is an ISO
    date string (e.g. ``ex_dividend_date``), not an epoch timestamp.
    """
    cutoff = until_day[:10]
    kept: list[dict] = []
    for r in rows:
        d = r.get(date_field)
        if d is None or str(d)[:10] <= cutoff:
            kept.append(r)
    return kept


class MassiveDataClient:
    """Point-in-time Massive historical REST client implementing ``types.DataPort``.

    Injectable transports (R9.2 isolation): ``transport`` rides the Massive
    :func:`request`; ``fred_transport`` rides the dedicated FRED helper. Tests pass
    ``httpx.MockTransport``; production passes ``None`` (real transports).
    """

    def __init__(
        self,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        fred_transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = _REQUEST_TIMEOUT_S,
    ) -> None:
        self._transport = transport
        self._fred_transport = fred_transport
        self._sleep = sleep
        self._timeout = timeout

    # -- internal: one GET via the 1.2 transport; raise on any Error -------- #

    def _get_or_raise(
        self, path: str, *, params: Optional[Mapping[str, Any]] = None
    ) -> Any:
        """GET ``path`` and return the raw JSON, or RAISE :class:`DataFetchError`.

        The transport never raises (returns a structured :class:`Error`); the
        DataPort contract is bare data, so we translate any transport ``Error``
        into an explicit raise here (R4.3 — never a partial/truncated result).
        """
        out = request(
            "GET", path, params=params, transport=self._transport, sleep=self._sleep,
            timeout=self._timeout,
        )
        if not out.ok:
            raise DataFetchError(
                f"massive fetch failed ({out.error_class}): {out.error}",
                error_class=out.error_class,
            )
        return out.data

    # -- internal: follow a paginated endpoint to completion (R4.4) --------- #

    def _get_paginated(
        self, path: str, *, params: Optional[Mapping[str, Any]] = None
    ) -> list[dict]:
        """Accumulate every ``results`` row across the ``next_url`` cursor (R4.4).

        Follows ``next_url`` until it is absent (natural termination). ANY page
        returning a transport ``Error`` RAISES (R4.3 — the partial accumulation is
        discarded, never returned). The cursor URL already carries its query state;
        we re-append only the ``apiKey`` (it is stripped from Polygon ``next_url``).
        """
        rows: list[dict] = []
        # First page rides the supplied path + params.
        data = self._get_or_raise(path, params=params)
        rows.extend(self._results(data))
        next_url = self._next_url(data)

        pages = 1
        while next_url:
            if pages >= _MAX_PAGES:
                raise DataFetchError(
                    f"pagination exceeded {_MAX_PAGES} pages — aborting",
                    error_class="pagination",
                )
            # ``next_url`` is an absolute Massive URL carrying the cursor; strip the
            # host so it rides the same base_url/apiKey injection as page 1. The
            # cursor's query is passed as ``params`` (NOT baked into the path —
            # httpx drops a path query string when ``params`` is also supplied), and
            # the transport re-appends apiKey (R4.4 — cursor pages stay authenticated).
            cursor_path, cursor_params = self._split_url(next_url)
            data = self._get_or_raise(cursor_path, params=cursor_params)
            rows.extend(self._results(data))
            next_url = self._next_url(data)
            pages += 1
        return rows

    @staticmethod
    def _results(data: Any) -> list[dict]:
        """The ``results`` array from a Massive body, or ``[]`` (never raise here)."""
        if isinstance(data, dict):
            res = data.get("results")
            if isinstance(res, list):
                return res
        return []

    @staticmethod
    def _next_url(data: Any) -> Optional[str]:
        """The ``next_url`` cursor if present and non-empty, else ``None``."""
        if isinstance(data, dict):
            nxt = data.get("next_url")
            if isinstance(nxt, str) and nxt:
                return nxt
        return None

    @staticmethod
    def _split_url(url: str) -> tuple[str, dict[str, str]]:
        """Reduce an absolute Massive ``next_url`` to ``(path, query_params)``.

        The query is returned as a dict (NOT baked into the path) because httpx
        discards a path's own query string when ``params`` is also supplied — so
        the cursor must travel via ``params`` for the transport's apiKey injection
        to merge with it rather than clobber it.
        """
        parsed = httpx.URL(url)
        # httpx.QueryParams -> a plain dict; the apiKey (if any leaked into the
        # cursor) is overwritten fresh by the transport, never trusted from here.
        params = {k: v for k, v in parsed.params.items() if k != "apiKey"}
        return parsed.path, params

    # -- DataPort: aggregate bars (adjusted=false, R4.2) -------------------- #

    def fetch_daily_bars(self, symbol: str, start: str, end: str) -> list[dict]:
        """As-of daily OHLCV bars (``adjusted=false``) over [start, end] (R4.1/4.2/4.4).

        Paginates to completion; bounds out any bar timestamped after ``end``.
        Raises :class:`DataFetchError` if any page fails (R4.3). A delisted/IPO
        name's traded sub-window is returned as-is (R4.4 — not a depth failure).
        """
        path = f"/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}"
        rows = self._get_paginated(path, params={"adjusted": "false", "sort": "asc"})
        return _bound_rows_by_ts(rows, until_day=end, ts_field="t", unit=_MS_PER_S)

    def fetch_intraday(
        self, symbol: str, day: str, *, multiplier: int = 1, timespan: str = "minute"
    ) -> list[dict]:
        """The intraday aggregate path for ``day`` (``adjusted=false``) (R6.2/4.2).

        Default 1-minute bars over the single ``day``; paginated + bounded to the
        end of ``day`` (R4.1). Drives fill + stop-hit determination downstream.
        """
        path = f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{day}/{day}"
        rows = self._get_paginated(path, params={"adjusted": "false", "sort": "asc"})
        return _bound_rows_by_ts(rows, until_day=day, ts_field="t", unit=_MS_PER_S)

    # -- DataPort: NBBO quotes (bid/ask, R6.1) ------------------------------ #

    def fetch_quotes(self, symbol: str, ts: str) -> dict:
        """NBBO quotes as-of ``ts`` for counterparty-price fills (R6.1/4.1).

        Returns ``{"results": [...]}`` (each row carries ``bp``/``ap`` bid/ask);
        bounded to the end of the ``ts`` day. ``sip_timestamp`` is NANOseconds.
        """
        path = f"/v3/quotes/{symbol}"
        rows = self._get_paginated(path, params={"timestamp.lte": ts[:10], "order": "asc"})
        rows = _bound_rows_by_ts(rows, until_day=ts, ts_field="sip_timestamp", unit=_NS_PER_S)
        return {"results": rows}

    # -- trades (tick) ------------------------------------------------------ #

    def fetch_trades(self, symbol: str, ts: str) -> dict:
        """Tick trades as-of ``ts`` (R4.1). ``participant_timestamp`` is NANOseconds."""
        path = f"/v3/trades/{symbol}"
        rows = self._get_paginated(path, params={"timestamp.lte": ts[:10], "order": "asc"})
        rows = _bound_rows_by_ts(
            rows, until_day=ts, ts_field="participant_timestamp", unit=_NS_PER_S
        )
        return {"results": rows}

    # -- grouped daily (universe) ------------------------------------------- #

    def fetch_grouped_daily(self, day: str) -> list[dict]:
        """Whole-market grouped daily bars for ``day`` (``adjusted=false``) — the
        universe snapshot (R4.2). Single-day endpoint; no cross-day bounding needed."""
        path = f"/v2/aggs/grouped/locale/us/market/stocks/{day}"
        return self._get_paginated(path, params={"adjusted": "false"})

    # -- DataPort: corporate actions (splits + dividends, R5.1) ------------- #

    def fetch_corporate_actions(self, symbol: str, start: str, end: str) -> dict:
        """Splits + cash dividends over [start, end] for total-return P&L (R5.1/4.1).

        Returns ``{"splits": [...], "dividends": [...]}`` (split *adjustment* is
        task 2.1 / features_adapter — we only FETCH the reference). Both legs are
        point-in-time bounded by ``end`` so no action after the instant leaks in.
        """
        splits = self._get_paginated(
            "/v3/reference/splits",
            params={"ticker": symbol, "execution_date.gte": start,
                    "execution_date.lte": end, "order": "asc"},
        )
        splits = _bound_by_date(splits, until_day=end, date_field="execution_date")
        dividends = self._get_paginated(
            "/v3/reference/dividends",
            params={"ticker": symbol, "ex_dividend_date.gte": start,
                    "ex_dividend_date.lte": end, "order": "asc"},
        )
        dividends = _bound_by_date(dividends, until_day=end, date_field="ex_dividend_date")
        return {"splits": splits, "dividends": dividends}

    # -- delisted-name discovery (active=false, R4.4) ----------------------- #

    def fetch_delisted_tickers(self) -> list[dict]:
        """Delisted names via the Tickers reference with ``active=false`` (R4.4).

        Names the trading universe over a window including names that have since
        delisted; their per-name bars (their traded sub-window) come from
        :meth:`fetch_daily_bars`.
        """
        return self._get_paginated(
            "/v3/reference/tickers",
            params={"market": "stocks", "active": "false", "order": "asc"},
        )

    # -- DataPort: FRED risk-free yield (own transport seam) ---------------- #

    def fetch_rf_yield(self, day: str) -> float:
        """The risk-free DGS1 yield as-of ``day`` (FRED) — a feature input (R4.1).

        Rides the dedicated FRED helper (its own ``api_key`` / ``FRED_API_KEY`` /
        ``api.stlouisfed.org``), NOT the Massive ``request()``. Point-in-time
        bounded via ``observation_end=day``; walks back over FRED's ``"."`` missing
        prints (weekend/holiday) to the last good value at-or-before ``day``.
        Raises :class:`DataFetchError` if FRED fails or no value is available.
        """
        return _fetch_fred_rf_yield(
            day, transport=self._fred_transport, sleep=self._sleep, timeout=self._timeout
        )


# --------------------------------------------------------------------------- #
# FRED rf-yield — tiny dedicated helper (own auth/seam; kept here per the task).
# --------------------------------------------------------------------------- #


def _resolve_fred_api_key() -> Optional[str]:
    """Read ``FRED_API_KEY`` fresh per call; ``None``/empty -> missing."""
    key = (os.environ.get("FRED_API_KEY") or "").strip()
    return key or None


def _parse_fred_value(raw: Any) -> Optional[float]:
    """FRED ships missing observations as the literal ``"."`` — map to ``None``,
    else ``float`` (mirrors ``src/mcp/fred/server.py::_parse_value``)."""
    if raw is None or raw == "" or raw == ".":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _fetch_fred_rf_yield(
    day: str,
    *,
    transport: Optional[httpx.BaseTransport] = None,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = _REQUEST_TIMEOUT_S,
) -> float:
    """Fetch DGS1 as-of ``day``, walking back to the last good value (R4.1).

    A direct, secret-free FRED observations read on its OWN injectable transport
    (R9.2). ``observation_end=day`` bounds it point-in-time; the last non-``"."``
    print at-or-before ``day`` is returned. Raises :class:`DataFetchError` on a
    missing key, a non-2xx, a transport failure, or when no value is available
    (explicit failure — never a silent default).
    """
    api_key = _resolve_fred_api_key()
    if api_key is None:
        raise DataFetchError("missing FRED_API_KEY", error_class="auth")

    params = {
        "series_id": _RF_SERIES_ID,
        "api_key": api_key,
        "file_type": "json",
        "observation_end": day[:10],
        "sort_order": "asc",
    }
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.get(_FRED_OBSERVATIONS_URL, params=params)
    except Exception as exc:  # never leak the URL (carries api_key) — type name only.
        raise DataFetchError(
            f"FRED unreachable: {type(exc).__name__}", error_class="network"
        ) from None

    if not (200 <= response.status_code < 300):
        raise DataFetchError(
            f"FRED error (HTTP {response.status_code})", error_class="venue_error"
        )
    try:
        body = response.json()
    except Exception:
        raise DataFetchError("FRED returned a non-JSON body", error_class="venue_error") from None

    observations = body.get("observations") if isinstance(body, dict) else None
    if not isinstance(observations, list):
        observations = []

    cutoff = day[:10]
    # Walk back: the last good (non-".") value with date <= day. observation_end
    # already bounds the right edge; we still guard the cutoff defensively.
    last_good: Optional[float] = None
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        d = str(obs.get("date", ""))[:10]
        if d and d <= cutoff:
            val = _parse_fred_value(obs.get("value"))
            if val is not None:
                last_good = val
    if last_good is None:
        raise DataFetchError(
            f"no DGS1 risk-free yield available at-or-before {cutoff}",
            error_class="no_data",
        )
    return last_good


__all__ = [
    "request",
    "get",
    "Result",
    "Error",
    "TransportOutcome",
    "MassiveDataClient",
    "DataFetchError",
]
