"""Operations layer — importable leaf functions (the daemon interface).

Source of truth: ``.kiro/specs/broker-cfd-adapter/design.md`` — the "Operations
layer -> core (leaf functions — the daemon interface)" block (Service Interface,
Responsibilities & Constraints), the Architecture map (``core -> {validation,
paper, symbol_cache, mappers, gate_client, config}``), the System Flows, the
"Error Handling" strategy, and the Requirements Traceability rows. Requirements:
``.kiro/specs/broker-cfd-adapter/requirements.md`` Req 2.1, 2.3, 3.1, 3.2, 3.3,
9.3, 9.4, 10.1, 10.4 (this file — the READOUT portion of 4.1).

Layer position (``models -> config -> gate_client -> {mappers, symbol_cache} ->
validation -> paper -> core -> server``): ``core`` is the Operations layer just
below ``server`` (the MCP wrapper). It may import any layer above it; nothing
imports ``core`` except ``server`` and the external execution-daemon.

Scope of THIS file (Task 4.1 — readouts ONLY)
---------------------------------------------
Implemented here: ``get_positions`` / ``get_account_assets`` /
``list_tradable_symbols`` / ``validate_symbol`` / ``get_history``. These are the
read-only leaf functions the execution-daemon imports in-process and that Task
5.1 wraps as MCP tools.

This module is ALSO extended by Task 4.2 (decision routing, the pre-transmit
snapshot, live-send gating — ``submit_decision``) and Task 4.3 (async order
lifecycle + double-send guard). It is structured so those tasks ADD to it without
reworking the readouts:

* the injected-dependency holder :class:`ReadoutClients` is the seam every
  leaf function takes — 4.2/4.3 reuse the same holder (it already carries the
  ``gate_client``, ``SymbolCache`` and ``transport`` ``submit_decision`` needs);
* :func:`default_clients` is the single production constructor (config/env →
  clients) the daemon and ``server`` call once; and
* the venue ``/tradfi`` path constants live in one block so the order/close paths
  4.2/4.3 add sit alongside the readout paths.

Dependency injection (Req testability; mirrors how ``SymbolCache`` took an
injected ``gate_client`` — tasks.md)
-----------------------------------------------------------------------------
Every readout takes a ``clients: ReadoutClients`` holding the ``gate_client``
transport module, a built ``SymbolCache``, and an optional ``httpx`` transport
forwarded on every venue call. Tests inject the Task 1.4
``make_mock_transport(...)`` (no live venue); production builds the holder from
config/env via :func:`default_clients` (real transport). The default is built
lazily and memoized so a bare ``core.get_positions()`` works in production.

Error contract — "no data" vs a TRANSPORT/venue FAILURE (design "Error Handling")
---------------------------------------------------------------------------------
* **Empty-but-successful** is an empty list. An empty venue position set (Req 2.3)
  or an empty history window (Req 10.4) is a SUCCESS that returns ``[]`` — never
  an error. ``validate_symbol`` returns a structured ``RejectionReason`` for an
  unknown / out-of-category ticker (a business outcome, not a transport failure).
* **Transport / venue failure is SURFACED, never masked.** On a structured
  ``gate_client`` error (auth / network / rate_limit / venue_error) a readout
  RAISES :class:`BrokerReadoutError` carrying the failure class — it does NOT
  silently return ``[]`` as if the book/window were empty (that would hide a
  failure as flat data). Raising (rather than returning a structured error) keeps
  the readout return types clean for the in-process daemon caller; **Task 5.1's
  ``server`` is the never-raises seam** — its thin ``@mcp.tool()`` wrappers catch
  :class:`BrokerReadoutError` and coerce it to a structured error ``dict`` so the
  MCP tool never raises (Req 9.2). This split is intentional and documented for
  5.1 to wrap (see CONCERNS in the task status report).

Req 9.4 (no telemetry): this layer emits NO decision-trace / telemetry. It only
returns fill / swap / rate data in its typed results so ``decision-trace-
telemetry`` can record slippage downstream — surfacing is the boundary of the
adapter's responsibility, emission is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union

import httpx

# Layers above ``core`` in the dependency direction. Imported BY NAME (production
# posture: broker dir on sys.path[0] when launched as `python server.py`).
import config as _config
import gate_client as _gate_client
import mappers as _mappers
import symbol_cache as _symbol_cache
from models import (
    AccountAssets,
    HistoryRecord,
    Position,
    RejectionReason,
    SymbolInfo,
)

# Venue ``/tradfi`` paths (the signed-transport layer prefixes /api/v4 + adds
# auth; ``core`` names only the /tradfi paths). The order/close paths Task 4.2/4.3
# add belong in this same block.
_POSITIONS_PATH = "/tradfi/positions"
_ASSETS_PATH = "/tradfi/users/assets"
_MT5_ACCOUNT_PATH = "/tradfi/users/mt5-account"
_ORDERS_HISTORY_PATH = "/tradfi/orders/history"
_POSITIONS_HISTORY_PATH = "/tradfi/positions/history"


# --------------------------------------------------------------------------- #
# Error contract — a SURFACED transport/venue failure (vs empty-but-successful).
# --------------------------------------------------------------------------- #


class BrokerReadoutError(RuntimeError):
    """A SURFACED transport / venue failure from a readout (design "Error
    Handling").

    Raised when a ``gate_client`` call returns a structured ``TransportError`` —
    so a real failure is never masked as an empty success (an empty book/window is
    ``[]``; a failure is this). Carries the ``error_class`` (auth | network |
    rate_limit | venue_error) and the secret-free message + status so Task 5.1's
    ``server`` can coerce it to a structured error ``dict`` without re-deriving the
    class. The in-process daemon caller may catch it directly.
    """

    def __init__(
        self,
        *,
        error_class: str,
        message: str,
        status_code: Optional[int] = None,
        rate_limit: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(f"[{error_class}] {message}")
        self.error_class = error_class
        self.message = message
        self.status_code = status_code
        self.rate_limit = rate_limit


# --------------------------------------------------------------------------- #
# Injected-dependency holder — the DI seam every leaf function takes.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReadoutClients:
    """The injected dependencies the leaf functions operate against.

    * ``gate_client`` — the signed-transport module (Task 2.1). Exposes
      ``request(method, path, *, params=, transport=, ...)`` returning a structured
      ``TransportResult`` / ``TransportError``.
    * ``symbol_cache`` — a built :class:`symbol_cache.SymbolCache` (Task 3.1) for
      ``list_tradable_symbols`` / ``validate_symbol``.
    * ``transport`` — an optional ``httpx`` transport forwarded on every venue
      call (tests pass the Task 1.4 ``make_mock_transport(...)``; production passes
      ``None`` → real transport).

    Task 4.2/4.3 reuse this SAME holder for ``submit_decision`` (it already carries
    the transport + cache + client they need); they do not introduce a parallel
    holder.
    """

    gate_client: Any
    symbol_cache: Any
    transport: Any = None


# Production clients are built lazily once and memoized so a bare
# ``core.get_positions()`` (no explicit ``clients=``) works for the daemon /
# server. Tests always pass an explicit ``clients=`` and never touch this.
_DEFAULT_CLIENTS: Optional[ReadoutClients] = None


def default_clients() -> ReadoutClients:
    """Construct (once, memoized) the production clients holder from config/env.

    Wires the real ``gate_client`` module, a fresh ``SymbolCache`` (US-stock
    category from ``config``), and a ``None`` transport (real httpx). This is the
    single production constructor the daemon / ``server`` call; Task 4.2/4.3 reuse
    it unchanged.
    """
    global _DEFAULT_CLIENTS
    if _DEFAULT_CLIENTS is None:
        cache = _symbol_cache.SymbolCache(
            gate_client=_gate_client,
            transport=None,
            us_stock_category_id=_config.US_STOCK_CATEGORY_ID,
        )
        _DEFAULT_CLIENTS = ReadoutClients(
            gate_client=_gate_client, symbol_cache=cache, transport=None
        )
    return _DEFAULT_CLIENTS


def _resolve(clients: Optional[ReadoutClients]) -> ReadoutClients:
    """Return the caller-supplied clients holder, else the memoized production one."""
    return clients if clients is not None else default_clients()


def _ok_or_raise(outcome: Any, *, what: str) -> Any:
    """Unwrap a structured ``gate_client`` outcome to its raw venue payload, or
    SURFACE a structured failure as :class:`BrokerReadoutError`.

    A successful ``TransportResult`` (``ok`` True) yields ``.data`` verbatim — an
    empty list is a legitimate success (Req 2.3 / 10.4), passed through untouched.
    A structured ``TransportError`` (``ok`` False) is raised, NOT swallowed: a
    failure must never look like a flat book / empty window (design "Error
    Handling"). ``what`` names the read for the message only (no secrets).
    """
    if getattr(outcome, "ok", False) is True:
        return outcome.data
    raise BrokerReadoutError(
        error_class=getattr(outcome, "error_class", "venue_error"),
        message=f"{what}: {getattr(outcome, 'error', '') or 'transport failure'}",
        status_code=getattr(outcome, "status_code", None),
        rate_limit=getattr(outcome, "rate_limit", None),
    )


# --------------------------------------------------------------------------- #
# Readout leaf functions (Task 4.1).
# --------------------------------------------------------------------------- #


def get_positions(*, clients: Optional[ReadoutClients] = None) -> list[Position]:
    """Open positions readout (Req 2.1, 2.2, 2.3).

    GET ``/tradfi/positions`` via ``gate_client`` → ``mappers.parse_positions`` →
    ``[Position]``. The venue ``unrealized_pnl`` is reported VERBATIM (Req 2.2 — no
    self-computed mark; the mapper preserves the value). An empty book is a SUCCESS
    that returns ``[]`` (Req 2.3), not an error. A transport/venue failure is
    SURFACED as :class:`BrokerReadoutError` (not masked as a flat book).
    """
    c = _resolve(clients)
    outcome = c.gate_client.request("GET", _POSITIONS_PATH, transport=c.transport)
    raw = _ok_or_raise(outcome, what="positions readout")
    return _mappers.parse_positions(raw)


def get_account_assets(
    *, clients: Optional[ReadoutClients] = None
) -> AccountAssets:
    """Account-assets readout (Req 3.1, 3.2).

    GET ``/tradfi/users/assets`` + ``/tradfi/users/mt5-account`` via ``gate_client``
    → ``mappers.parse_account_assets`` → :class:`AccountAssets`. Exposes
    equity / used / free margin / margin_level / balance (Req 3.1) plus the venue
    ``stop_out_level`` (Req 3.2); the adapter computes / asserts NO liquidation
    distance (Req 3.2 — that math is survival-gate's). Either read failing is
    SURFACED as :class:`BrokerReadoutError`.
    """
    c = _resolve(clients)
    assets_outcome = c.gate_client.request("GET", _ASSETS_PATH, transport=c.transport)
    assets_raw = _ok_or_raise(assets_outcome, what="account assets readout")
    mt5_outcome = c.gate_client.request(
        "GET", _MT5_ACCOUNT_PATH, transport=c.transport
    )
    mt5_raw = _ok_or_raise(mt5_outcome, what="mt5-account readout")
    return _mappers.parse_account_assets(assets_raw, mt5_raw)


def list_tradable_symbols(
    *, clients: Optional[ReadoutClients] = None
) -> list[SymbolInfo]:
    """Tradable-symbol readout (Req 3.3, 4.1, 4.2 via the cache).

    Delegates to ``SymbolCache.tradable_symbols()`` — the in-category (US-stock
    CFD) validated set, identified by US ticker only (Req 4.1). Each
    :class:`SymbolInfo` surfaces per-symbol swap rates (Req 3.3) and leverage /
    trade_mode for downstream validation. The cache's conservative posture (an
    unbuildable set → ``[]``) is preserved.
    """
    c = _resolve(clients)
    return c.symbol_cache.tradable_symbols()


def validate_symbol(
    ticker: str, *, clients: Optional[ReadoutClients] = None
) -> Union[SymbolInfo, RejectionReason]:
    """Validate a single US ticker (Req 4.1, 4.2 via the cache).

    Delegates to ``SymbolCache.resolve(ticker)``: a known in-category ticker
    resolves to its :class:`SymbolInfo`; an unknown ticker → ``UNKNOWN_SYMBOL``
    and an out-of-category ticker → ``OUT_OF_CATEGORY`` (both structured
    :class:`RejectionReason`, not exceptions). Identity is the US ticker only — the
    venue free-text description never resolves (Req 4.1).
    """
    c = _resolve(clients)
    return c.symbol_cache.resolve(ticker)


def get_history(
    since: Optional[int] = None,
    until: Optional[int] = None,
    *,
    clients: Optional[ReadoutClients] = None,
) -> list[HistoryRecord]:
    """Order- and position-history readout (Req 9.3, 10.1, 10.2, 10.3, 10.4, 3.3).

    GET ``/tradfi/orders/history`` + ``/tradfi/positions/history`` via
    ``gate_client`` → ``mappers.parse_orders_history`` / ``parse_positions_history``
    → ``[HistoryRecord]``. Surfaces venue-supplied fill price / volume (Req 9.3),
    realized swap (Req 3.3), realized PnL, and the forced-liquidation flag (Req
    10.1 / 10.2 — flagged from ``order_opt_type`` 5|6 / ``position_status`` 2,
    without interpretation). All values are venue-supplied, never self-computed
    (Req 10.3). An empty window is a SUCCESS that returns ``[]`` (Req 10.4); a
    transport/venue failure is SURFACED as :class:`BrokerReadoutError`.

    ``since`` / ``until`` are forwarded as the venue ``from`` / ``to`` window query
    params when supplied (omitted params → the venue's default window).
    """
    c = _resolve(clients)
    params = _window_params(since, until)

    orders_outcome = c.gate_client.request(
        "GET", _ORDERS_HISTORY_PATH, params=params, transport=c.transport
    )
    orders_raw = _ok_or_raise(orders_outcome, what="orders history readout")

    positions_outcome = c.gate_client.request(
        "GET", _POSITIONS_HISTORY_PATH, params=params, transport=c.transport
    )
    positions_raw = _ok_or_raise(positions_outcome, what="positions history readout")

    records: list[HistoryRecord] = []
    records.extend(_mappers.parse_orders_history(orders_raw))
    records.extend(_mappers.parse_positions_history(positions_raw))
    return records


def _window_params(
    since: Optional[int], until: Optional[int]
) -> Optional[dict[str, int]]:
    """Build the venue history-window query params from ``since`` / ``until``.

    Maps to the venue ``from`` / ``to`` epoch-second window. Returns ``None`` when
    neither bound is supplied so the request carries no window (the venue's default
    window applies) rather than empty params.
    """
    params: dict[str, int] = {}
    if since is not None:
        params["from"] = since
    if until is not None:
        params["to"] = until
    return params or None


__all__ = [
    "BrokerReadoutError",
    "ReadoutClients",
    "default_clients",
    "get_positions",
    "get_account_assets",
    "list_tradable_symbols",
    "validate_symbol",
    "get_history",
]
