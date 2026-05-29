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

Scope of THIS file (Tasks 4.1 + 4.2)
------------------------------------
Task 4.1 (readouts): ``get_positions`` / ``get_account_assets`` /
``list_tradable_symbols`` / ``validate_symbol`` / ``get_history``. These are the
read-only leaf functions the execution-daemon imports in-process and that Task
5.1 wraps as MCP tools.

Task 4.2 (this addition — decision routing, the pre-transmit snapshot, live-send
gating): ``submit_decision`` plus the :class:`PreTransmitSnapshot` it gathers ONCE
(:func:`gather_snapshot`) and the live-send seam :func:`_submit_live` (a complete
BASIC transmit+confirm Task 4.3 hardens into an async poll-loop + double-send
guard). See the "Decision routing (Task 4.2)" block lower in this file.

Task 4.3 (still pending): async order lifecycle + double-send guard — it HARDENS
:func:`_submit_live` and REUSES the snapshot's single positions read (exposed on
:class:`PreTransmitSnapshot.open_positions`) rather than re-fetching.

The module is structured so each task ADDS to it without reworking the readouts:

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

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union

# Layers above ``core`` in the dependency direction. Imported BY NAME (production
# posture: broker dir on sys.path[0] when launched as `python server.py`).
import config as _config
import gate_client as _gate_client
import mappers as _mappers
import paper as _paper
import symbol_cache as _symbol_cache
import validation as _validation
from models import (
    AccountAssets,
    Direction,
    HistoryRecord,
    Label,
    OrderIntent,
    OrderResult,
    OrderType,
    Position,
    RejectionCode,
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
# Order/close + ticker paths the routing layer (Task 4.2) adds. The decision->action
# mapper (``mappers.map_decision_to_action``) is the single source of the exact
# endpoint a BUY/TRIM/SELL maps to; ``_ORDERS_PATH`` is named here only for the
# read-back confirmation (``GET /tradfi/orders``). ``_TICKER_PATH_FMT`` is the
# bid/ask read the snapshot gathers so paper prices from real venue quotes.
_ORDERS_PATH = "/tradfi/orders"
_TICKER_PATH_FMT = "/tradfi/symbols/{symbol}/tickers"

# Venue account ``status`` enum (gate-tradfi-api-reference "Critical enums":
# 1=not opened, 2=pending review, 3=active). Only status 3 is an ACTIVE account
# (Req 1.10); anything else is treated as not-active (conservative).
_ACCOUNT_STATUS_ACTIVE = 3

# Async submit->poll->reconcile bounds (Task 4.3). Order placement is ASYNCHRONOUS
# — the venue acknowledges with a queue-task-id, not a fill (Req 1.7) — so ``core``
# CONFIRMS by polling active orders/positions until the result is observed OR the
# attempt cap is hit, at which point the outcome is surfaced as ``unconfirmed``
# (never assumed filled — Req 9.2). Both the poll interval and the attempt cap are
# INJECTABLE through ``submit_decision`` (the ``poll_sleep`` callable + the
# ``poll_max_attempts`` int) so unit tests neither really sleep nor spin; these are
# the conservative production defaults only.
_DEFAULT_POLL_MAX_ATTEMPTS = 5
_DEFAULT_POLL_INTERVAL_S = 0.5


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


# --------------------------------------------------------------------------- #
# Decision routing (Task 4.2) — the one pre-transmit snapshot + live-send gating.
# --------------------------------------------------------------------------- #
#
# design "core (leaf functions)" Responsibilities & Constraints + System Flows
# ("Order submission" / "Live-send gating"). The flow is:
#
#   submit_decision -> build OrderIntent
#                   -> HOLD short-circuits to a structured no-op (1.4)
#                   -> gather ONE pre-transmit snapshot (gather_snapshot)
#                   -> validation.evaluate(intent, snapshot.context)  (rejections)
#                   -> route: paper.simulate  (paper default, v0.1 8.1)
#                         OR  _submit_live      (only when all four 8.3 clearances)
#
# The conservative posture (P7): every branch can reject/refuse/simulate but never
# upsizes (7.1/7.3) and never opens on a TRIM/SELL miss (1.8 via validation).


@dataclass(frozen=True)
class PreTransmitSnapshot:
    """The single consistent pre-transmit snapshot ``core`` gathers ONCE before any
    validation/transmit (design: "gathers a single consistent pre-transmit
    snapshot — account assets/status, open positions, and the target symbol's
    cached metadata + session status — into ``ValidationContext``").

    THE ONE-POSITIONS-READ SEAM (load-bearing for Task 4.3):
    ``open_positions`` is the result of the SINGLE ``GET /tradfi/positions`` read
    taken for this submit. The design requires that same read feed BOTH the Req 1.8
    position-exists check (inside ``validation`` via ``context.open_positions``) and
    the Req 7.4 double-send guard (Task 4.3). To make the reuse explicit and
    refetch-free, the list is held here AND threaded into ``context`` as the SAME
    object — ``context.open_positions is open_positions`` (asserted by test). Task
    4.3's double-send guard MUST read ``snapshot.open_positions`` rather than
    issuing a second positions fetch.

    ``symbol_info`` is the resolved tradable ``SymbolInfo`` (or ``None`` when the
    symbol is not in the validated set — drives the 4.3-chain UNKNOWN_SYMBOL gate).
    ``bid`` / ``ask`` are the target symbol's current quote (read once here so the
    paper simulator prices from a real venue quote without a second uninjected
    fetch); ``None`` when the symbol did not resolve (no quote needed — the chain
    rejects first). ``context`` is the fully-populated :class:`ValidationContext`
    the chain evaluates — built from this snapshot, never re-resolved mid-run (P2).
    """

    symbol_info: Optional[SymbolInfo]
    open_positions: list[Position]
    account_assets: Optional[AccountAssets]
    account_active: bool
    bid: Optional[float]
    ask: Optional[float]
    context: "_validation.ValidationContext"


def gather_snapshot(
    symbol: str,
    *,
    clients: Optional[ReadoutClients] = None,
    runtime_mode: Optional[_config.RuntimeMode] = None,
) -> PreTransmitSnapshot:
    """Gather the ONE pre-transmit snapshot for ``symbol`` (design "core"
    Responsibilities).

    Reads — ONCE each, all through the injected ``clients`` transport — the open
    positions (the single read the 1.8 check and the 7.4 guard share), the account
    assets, the account-active status (from mt5-account), the resolved target-symbol
    ``SymbolInfo``/session (via the symbol_cache), and the target symbol's bid/ask
    quote (so paper prices from a real venue quote). It then folds them into a
    :class:`validation.ValidationContext` (the same ``open_positions`` object) and
    returns both on the snapshot. No sizing/scoring (7.3); pure gather + assemble.

    ``runtime_mode`` defaults to a conservative paper-default ``RuntimeMode`` (paper
    on, all live clearances safe-default) so a snapshot is never accidentally
    live-capable.
    """
    c = _resolve(clients)
    rm = runtime_mode if runtime_mode is not None else _config.RuntimeMode()

    # ONE positions read — the read the 1.8 check and (Task 4.3) the 7.4 guard share.
    open_positions = get_positions(clients=c)

    # Account assets + active status. The account-active flag is sourced from the
    # live mt5-account read (its own field is the source of truth — see
    # ValidationContext docstring); we read assets here and derive active from the
    # mt5-account status, falling back to the runtime_mode flag when the venue read
    # does not expose an explicit status. Both reads are surfaced-on-failure
    # (BrokerReadoutError) by the readout layer, never masked.
    account_assets = get_account_assets(clients=c)
    account_active = _resolve_account_active(c, runtime_mode=rm)

    # Resolve the target symbol (or None -> the chain's UNKNOWN_SYMBOL gate fires).
    resolved = c.symbol_cache.resolve(symbol)
    symbol_info: Optional[SymbolInfo]
    if isinstance(resolved, SymbolInfo):
        symbol_info = resolved
    else:
        symbol_info = None

    # Bid/ask for the resolved symbol (paper prices from this; live confirms fills
    # via history). Only fetched when the symbol resolved — an unresolved symbol is
    # rejected by the chain before any pricing is needed.
    bid: Optional[float] = None
    ask: Optional[float] = None
    if symbol_info is not None:
        bid, ask = _fetch_quote(symbol, clients=c)

    context = _validation.ValidationContext(
        symbol_info=symbol_info,
        account_active=account_active,
        runtime_mode=rm,
        open_positions=open_positions,  # SAME object — the one-read reuse seam.
        account_assets=account_assets,
        us_stock_category_id=rm.us_stock_category_id,
    )

    return PreTransmitSnapshot(
        symbol_info=symbol_info,
        open_positions=open_positions,
        account_assets=account_assets,
        account_active=account_active,
        bid=bid,
        ask=ask,
        context=context,
    )


def _resolve_account_active(
    clients: ReadoutClients, *, runtime_mode: _config.RuntimeMode
) -> bool:
    """Derive the account-active flag for the snapshot (Req 1.10 input).

    The authoritative source is the live ``/tradfi/users/mt5-account`` ``status``
    read (venue enum: 1=not opened, 2=pending review, 3=active — only 3 is active).
    When the venue read fails or omits ``status`` we fall back to the caller's
    ``runtime_mode.account_active`` (the conservative default is inactive). Kept
    narrow so the source of truth — the live status — drives the 1.10 gate without
    the snapshot inventing one.
    """
    outcome = clients.gate_client.request(
        "GET", _MT5_ACCOUNT_PATH, transport=clients.transport
    )
    if getattr(outcome, "ok", False) is True and isinstance(outcome.data, dict):
        status = outcome.data.get("status")
        if status is not None:
            try:
                return int(status) == _ACCOUNT_STATUS_ACTIVE
            except (TypeError, ValueError):
                return False
    return runtime_mode.account_active


def _fetch_quote(
    symbol: str, *, clients: ReadoutClients
) -> tuple[Optional[float], Optional[float]]:
    """Read the target symbol's current bid/ask ONCE (``GET .../tickers``).

    Goes through the injected ``clients`` transport (so it is unit-testable and
    shares the snapshot's transport). Venue numerics arrive as strings; parse at
    this boundary (P13 — the adapter validates its own types). A failed/short quote
    returns ``(None, None)`` — the caller (paper) surfaces the gap rather than
    transmitting a guessed price.
    """
    outcome = clients.gate_client.request(
        "GET", _TICKER_PATH_FMT.format(symbol=symbol), transport=clients.transport
    )
    if getattr(outcome, "ok", False) is not True:
        return None, None
    data = outcome.data
    if not isinstance(data, dict):
        return None, None
    bid = data.get("bid_price")
    ask = data.get("ask_price")
    return (
        float(bid) if bid is not None else None,
        float(ask) if ask is not None else None,
    )


def _position_volume_for_close(
    intent: OrderIntent, snapshot: PreTransmitSnapshot
) -> Optional[float]:
    """For a full SELL (no request volume), the closed position's volume — surfaced
    verbatim by paper as ``fill_volume`` (never invented, Req 7.1).

    Looks the position up in the snapshot's SINGLE positions read (no refetch) by
    the caller-supplied ``position_id`` (Req 1.9). Returns ``None`` when not found
    or when the intent already carries a volume (TRIM/BUY).
    """
    if intent.volume is not None or intent.position_id is None:
        return None
    for p in snapshot.open_positions:
        if p.position_id == intent.position_id:
            return p.volume
    return None


def submit_decision(
    decision: Label,
    symbol: str,
    direction: Direction,
    volume: Optional[float] = None,
    position_id: Optional[str] = None,
    order_type: OrderType = OrderType.MARKET,
    trigger_price: Optional[float] = None,
    take_profit: Optional[float] = None,
    stop_loss: Optional[float] = None,
    *,
    clients: Optional[ReadoutClients] = None,
    runtime_mode: Optional[_config.RuntimeMode] = None,
    prior_queue_task_id: Optional[str] = None,
    poll_sleep: Callable[[float], None] = time.sleep,
    poll_max_attempts: int = _DEFAULT_POLL_MAX_ATTEMPTS,
    poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
) -> OrderResult:
    """Route a P9 ``Label`` + ``Direction`` to the right operation; never raises.

    The single validated path the daemon and ``server`` share (design "core"
    Service Interface). Steps:

    1. **HOLD -> structured no-op** (Req 1.4): return ``OrderResult(status="noop")``
       BEFORE any snapshot/transmit. HOLD carries no action (the mapper has none).
    2. Build the frozen :class:`OrderIntent` from the caller args verbatim — no
       sizing/scoring/trigger logic (Req 7.3); ``volume`` is surfaced as supplied
       (never upsized — Req 7.1).
    3. Gather the ONE pre-transmit snapshot (:func:`gather_snapshot`): one positions
       read (shared with the 4.3 guard), account assets/status, resolved symbol +
       session, bid/ask.
    4. Run the reject-only validation chain (``validation.evaluate``). A
       :class:`RejectionReason` -> ``OrderResult(status="rejected", reason=...)``
       (covers 1.8 TRIM/SELL-no-position, 1.10 inactive, 8.3/8.4/8.5
       LIVE_SEND_BLOCKED, etc.). The chain acts only on the caller-supplied
       ``position_id`` for TRIM/SELL (Req 1.9) and never upsizes (Req 7.1/7.2).
    5. **Route** (P9 via the mapper): BUY -> open; TRIM/SELL -> close by
       ``position_id``. In **paper** mode (the v0.1 default, Req 8.1) -> the paper
       simulator (Req 8.2: full validation already ran; price from bid/ask; NO
       order POST) -> ``OrderResult(status="simulated")``. **Live** transmit is
       permitted ONLY when ``runtime_mode.live_transmit_allowed()`` (all four Req
       8.3 conditions). The validation chain's ``_check_live_send`` already refuses
       a non-paper run missing a clearance with LIVE_SEND_BLOCKED (step 4), so by
       this point a non-paper run is fully cleared; route to :func:`_submit_live`.

    Live transmit (Task 4.3) is ASYNC: :func:`_submit_live` runs a double-send guard
    BEFORE any POST (Req 7.4 — correlate the retained ``prior_queue_task_id`` against
    active orders/positions, reusing ``snapshot.open_positions``) and, after the
    POST, confirms by POLLING orders/positions until observed or the attempt cap is
    hit (Req 1.7), surfacing ``unconfirmed`` rather than assuming a fill (Req 9.2).
    On a RE-SEND the caller passes ``prior_queue_task_id`` (the id retained on the
    prior unconfirmed result) so the guard can suppress a duplicate; a first send
    passes ``None`` and always transmits. The poll backoff (``poll_sleep`` +
    ``poll_interval_s``) and the attempt cap (``poll_max_attempts``) are injectable
    so tests neither sleep nor spin.

    No ``volume`` mutation, no second positions fetch, no telemetry (Req 9.4).
    """
    # 1) HOLD short-circuits to a structured no-op — no snapshot, no transmit (1.4).
    if decision is Label.HOLD:
        return OrderResult(
            status="noop",
            raw={"decision": Label.HOLD.value, "symbol": symbol, "noop": True},
        )

    # 2) Build the intent verbatim (no sizing/scoring — 7.3; volume as-supplied 7.1).
    intent = OrderIntent(
        decision=decision,
        symbol=symbol,
        direction=direction,
        volume=volume,
        position_id=position_id,
        order_type=order_type,
        trigger_price=trigger_price,
        take_profit=take_profit,
        stop_loss=stop_loss,
    )

    # 3) ONE pre-transmit snapshot (assets/status + positions + symbol/session + quote).
    snapshot = gather_snapshot(symbol, clients=clients, runtime_mode=runtime_mode)

    # 4) Reject-only validation chain. Any reason -> structured rejection (no transmit).
    reason = _validation.evaluate(intent, snapshot.context)
    if reason is not None:
        return OrderResult(status="rejected", reason=reason)

    # 5) Route. Paper (v0.1 default) simulates; live transmits only when fully cleared.
    rm = snapshot.context.runtime_mode
    if rm.paper_enabled:
        # Paper mode (8.1/8.2): full validation already ran; price from the snapshot
        # bid/ask; NO order POST. paper.simulate is a pure function given bid/ask.
        return _paper.simulate(
            intent,
            bid=snapshot.bid,
            ask=snapshot.ask,
            position_volume=_position_volume_for_close(intent, snapshot),
        )

    # Non-paper run: the chain's live-send gate (step 4) already refused any run
    # missing a clearance with LIVE_SEND_BLOCKED, so reaching here means all four
    # Req 8.3 conditions hold. Defense-in-depth: re-assert before transmitting.
    if not rm.live_transmit_allowed():  # pragma: no cover - chain refuses first
        return OrderResult(
            status="rejected",
            reason=RejectionReason(
                code=RejectionCode.LIVE_SEND_BLOCKED,
                message=(
                    "live transmit refused at the routing seam: not all four Req 8.3 "
                    "clearances hold (paper off AND active AND clearance AND kill clear)."
                ),
            ),
        )

    action = _mappers.map_decision_to_action(intent)
    return _submit_live(
        intent,
        snapshot,
        action,
        _resolve(clients),
        prior_queue_task_id=prior_queue_task_id,
        poll_sleep=poll_sleep,
        poll_max_attempts=poll_max_attempts,
        poll_interval_s=poll_interval_s,
    )


def _extract_queue_task_id(ack: Any) -> Optional[str]:
    """Pull the venue queue-task-id out of an order/close ack envelope (Req 1.7).

    Placement is ASYNCHRONOUS — the venue acks with a queue-task-id under
    ``data.id`` (reference gotcha #1), NOT a fill. The envelope is
    ``{"label","message","data":{"id":...}}``; prefer ``data.id``, falling back to a
    top-level ``id``. ``None`` when the ack carries neither (a degenerate ack the
    poll loop then treats as unconfirmable by id — it still correlates by
    symbol/side / position-id). The id is the correlation key the 7.4 double-send
    guard retains.
    """
    if not isinstance(ack, dict):
        return None
    data = ack.get("data")
    if isinstance(data, dict) and data.get("id") is not None:
        return str(data["id"])
    if ack.get("id") is not None:
        return str(ack["id"])
    return None


def _correlate_open_order(
    intent: OrderIntent, orders: Any, *, queue_task_id: Optional[str]
) -> Optional[dict[str, Any]]:
    """Find the order this BUY produced in an ``/tradfi/orders`` read-back.

    Correlation key, most-specific first: the retained ``queue_task_id`` (the venue
    echoes it as ``queue_task_id`` / ``task_id`` on the active order — Req 7.4), else
    the (symbol, side) the intent maps to. Returns the confirmation dict (``filled``
    when the venue marks the order ``finished``, else ``unconfirmed`` — never assume
    a fill, Req 9.2) or ``None`` when no correlating order is present yet (the poll
    loop retries; the guard reads "no prior order").
    """
    if not isinstance(orders, list):
        return None
    want_side = (
        _mappers.SIDE_BUY if intent.direction is Direction.LONG else _mappers.SIDE_SELL
    )
    for o in orders:
        if not isinstance(o, dict):
            continue
        task_match = queue_task_id is not None and (
            str(o.get("queue_task_id")) == queue_task_id
            or str(o.get("task_id")) == queue_task_id
        )
        attr_match = (
            str(o.get("symbol")) == intent.symbol and o.get("side") == want_side
        )
        if task_match or attr_match:
            price = o.get("price")
            vol = o.get("volume")
            return {
                "status": "filled" if o.get("finished") else "unconfirmed",
                "order_id": str(o.get("order_id")) if o.get("order_id") else None,
                "fill_price": float(price) if price is not None else None,
                "fill_volume": float(vol) if vol is not None else None,
                "raw": o,
            }
    return None


def _correlate_close_position(
    intent: OrderIntent, positions: Any
) -> Optional[dict[str, Any]]:
    """Confirm a TRIM/SELL close in a ``/tradfi/positions`` read-back, by the
    caller-supplied ``position_id`` (Req 1.9).

    A TRIM leaves the position present (smaller volume) -> ``filled`` with the
    remaining volume. A SELL fully closes -> the position is ABSENT -> ``filled``
    full close. Returns the confirmation dict, or ``None`` when the positions book
    could not be read as a list (the poll loop retries / surfaces ``unconfirmed``).
    """
    if not isinstance(positions, list):
        return None
    for p in positions:
        if isinstance(p, dict) and str(p.get("position_id")) == intent.position_id:
            # Position still open -> a partial (TRIM) close confirmed.
            vol = p.get("volume")
            return {
                "status": "filled",
                "position_id": intent.position_id,
                "fill_volume": float(vol) if vol is not None else None,
                "raw": p,
            }
    # Position absent from a successfully-read book -> a full close (SELL) confirmed.
    return {"status": "filled", "position_id": intent.position_id, "raw": None}


def _double_send_guard(
    intent: OrderIntent,
    snapshot: PreTransmitSnapshot,
    clients: ReadoutClients,
    *,
    prior_queue_task_id: Optional[str],
) -> Optional[dict[str, Any]]:
    """Correlate a PRIOR unconfirmed submission against the active book BEFORE any
    re-transmit, so a retry creates no duplicate (Req 7.4).

    The venue has no native idempotency key (requirements §7.4), so the adapter
    mitigates duplicate sends by retaining the prior submission's queue-task-id and
    correlating it against the active book before re-sending. The guard ONLY fires
    on a RE-SEND — i.e. when the caller passes the ``prior_queue_task_id`` returned
    on the prior (unconfirmed) :class:`OrderResult`. A FIRST send carries no prior
    id (``None``) and the guard returns ``None`` immediately, so a first send always
    transmits (it never false-positives off an unrelated pre-existing order).

    On a re-send:

    * **Opens (BUY):** read active orders ONCE keyed on the retained queue-task-id
      (the venue echoes it as ``queue_task_id`` / ``task_id`` on the resulting active
      order). A correlating order means the prior submit already landed -> return it
      (``filled``/``unconfirmed``) and do NOT POST a duplicate.
    * **Closes (TRIM/SELL):** REUSE ``snapshot.open_positions`` — the SINGLE
      pre-transmit positions read (the design's one-read seam, NOT a second fetch).
      If the caller-identified target position is already ABSENT, the prior close
      already landed -> surface that confirmation rather than re-issuing the close.

    Returns the already-existing confirmation dict when a prior submission is
    detected (caller skips the POST), else ``None`` (proceed to transmit).
    """
    # FIRST send (no retained id) -> nothing to correlate; always transmit.
    if prior_queue_task_id is None:
        return None

    if intent.decision is Label.BUY:
        # A fresh orders read keyed ONLY on the retained queue-task-id (not symbol/
        # side — that would false-positive off an unrelated pre-existing order).
        outcome = clients.gate_client.request(
            "GET", _ORDERS_PATH, transport=clients.transport
        )
        orders = _ok_or_raise(outcome, what="double-send guard (orders read)")
        return _correlate_open_order_by_task(orders, queue_task_id=prior_queue_task_id)

    # TRIM/SELL close: reuse the snapshot's SINGLE positions read (no second fetch).
    # If the caller-identified position is already absent, the prior close landed ->
    # surface the (full-close) confirmation rather than re-issuing the close.
    if intent.position_id is not None and not any(
        p.position_id == intent.position_id for p in snapshot.open_positions
    ):
        return {"status": "filled", "position_id": intent.position_id, "raw": None}
    return None


def _correlate_open_order_by_task(
    orders: Any, *, queue_task_id: str
) -> Optional[dict[str, Any]]:
    """Find an active order produced by ``queue_task_id`` (the 7.4 re-send key).

    The venue echoes the queue-task-id on the resulting active order as
    ``queue_task_id`` / ``task_id``. A match means the prior (unconfirmed) submit
    already produced an order -> return it (``filled`` when ``finished``, else
    ``unconfirmed`` — still no duplicate POST). ``None`` when no active order carries
    the id (the prior submit truly didn't land -> safe to (re)transmit).
    """
    if not isinstance(orders, list):
        return None
    for o in orders:
        if not isinstance(o, dict):
            continue
        if (
            str(o.get("queue_task_id")) == queue_task_id
            or str(o.get("task_id")) == queue_task_id
        ):
            price = o.get("price")
            vol = o.get("volume")
            return {
                "status": "filled" if o.get("finished") else "unconfirmed",
                "order_id": str(o.get("order_id")) if o.get("order_id") else None,
                "fill_price": float(price) if price is not None else None,
                "fill_volume": float(vol) if vol is not None else None,
                "raw": o,
            }
    return None


def _submit_live(
    intent: OrderIntent,
    snapshot: PreTransmitSnapshot,
    action: "_mappers.VenueAction",
    clients: ReadoutClients,
    *,
    prior_queue_task_id: Optional[str] = None,
    poll_sleep: Callable[[float], None] = time.sleep,
    poll_max_attempts: int = _DEFAULT_POLL_MAX_ATTEMPTS,
    poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
) -> OrderResult:
    """Transmit a fully-cleared live order through the async submit->poll->reconcile
    lifecycle, with a double-send guard (Task 4.3).

    UNREACHABLE in v0.1 (paper default, Req 8.1) — exercised only when a caller
    forces all four Req 8.3 clearances. The hardened lifecycle:

    1. **Double-send guard FIRST (Req 7.4).** Before any POST, correlate the
       retained ``prior_queue_task_id`` against the active book
       (:func:`_double_send_guard`): reuse ``snapshot.open_positions`` for a close
       and a fresh task-id-keyed orders read for an open. If the prior submission of
       this intent already produced an order/position, RETURN it — issue NO second
       POST (no duplicate position). A first send (``prior_queue_task_id`` is
       ``None``) correlates nothing -> proceed.
    2. **Transmit (Req 1.7).** POST the mapped action; the venue acks ASYNCHRONOUSLY
       with a queue-task-id under ``data.id`` (NOT a fill). The id is retained on
       ``result.raw["queue_task_id"]`` as the correlation key for any later resend.
    3. **Poll->reconcile (Req 1.7).** Poll the relevant book — orders for a BUY open,
       positions for a TRIM/SELL close — until the result is OBSERVED or the
       (injectable) attempt cap is reached, sleeping the (injectable) interval
       between attempts. A confirmed observation -> ``filled`` (+ fill data); the cap
       reached with no observation -> ``unconfirmed`` — NEVER assume a fill (Req 9.2).

    A transport failure on the POST surfaces as a structured BrokerReadoutError via
    :func:`_ok_or_raise` (the daemon/server boundary handles it).
    """
    # 1) DOUBLE-SEND GUARD (Req 7.4) — correlate BEFORE transmitting. A prior
    #    submission already landed -> return it, NO second POST (no duplicate).
    prior = _double_send_guard(
        intent, snapshot, clients, prior_queue_task_id=prior_queue_task_id
    )
    if prior is not None:
        return _result_from_confirmation(
            intent, prior, queue_task_id=prior_queue_task_id
        )

    # 2) Transmit the mapped action (async ack -> queue-task-id, not a fill).
    post_outcome = clients.gate_client.request(
        action.method, action.endpoint, body=action.body, transport=clients.transport
    )
    ack = _ok_or_raise(post_outcome, what="live order submit")
    queue_task_id = _extract_queue_task_id(ack)

    # 3) Poll->reconcile until observed or the attempt cap is hit (Req 1.7); an
    #    exhausted cap surfaces ``unconfirmed`` (never assume a fill — Req 9.2).
    confirmation = _poll_confirm(
        intent,
        clients,
        queue_task_id=queue_task_id,
        poll_sleep=poll_sleep,
        poll_max_attempts=poll_max_attempts,
        poll_interval_s=poll_interval_s,
    )
    return _result_from_confirmation(intent, confirmation, queue_task_id=queue_task_id)


def _result_from_confirmation(
    intent: OrderIntent,
    confirmation: dict[str, Any],
    *,
    queue_task_id: Optional[str],
) -> OrderResult:
    """Fold a confirmation dict into the typed :class:`OrderResult`.

    The retained ``queue_task_id`` rides on ``raw`` as the 7.4 correlation key for
    any later resend; ``confirmation`` is either a fresh poll result or a
    double-send-guard hit (both share the same shape).
    """
    raw: dict[str, Any] = {
        "queue_task_id": queue_task_id,
        "confirmation": confirmation.get("raw"),
    }
    return OrderResult(
        status=confirmation["status"],
        order_id=confirmation.get("order_id"),
        position_id=confirmation.get("position_id") or intent.position_id,
        fill_price=confirmation.get("fill_price"),
        fill_volume=confirmation.get("fill_volume"),
        raw=raw,
    )


def _poll_confirm(
    intent: OrderIntent,
    clients: ReadoutClients,
    *,
    queue_task_id: Optional[str],
    poll_sleep: Callable[[float], None],
    poll_max_attempts: int,
    poll_interval_s: float,
) -> dict[str, Any]:
    """Bounded submit->poll->reconcile confirmation loop (Req 1.7, 9.2).

    Polls the relevant book — ``/tradfi/orders`` for a BUY open, ``/tradfi/positions``
    for a TRIM/SELL close — up to ``poll_max_attempts`` times, correlating each
    read-back (by the retained ``queue_task_id`` then symbol/side for an open; by
    ``position_id`` for a close). The FIRST observed confirmation wins. Between
    attempts (only when another attempt will follow) it sleeps ``poll_interval_s``
    through the INJECTABLE ``poll_sleep`` so tests neither really sleep nor spin.

    If the cap is reached with no confirming observation, returns
    ``{"status": "unconfirmed"}`` — the async outcome is SURFACED as unconfirmed,
    never assumed filled (Req 9.2). A bounded loop (``max(1, cap)`` attempts) also
    guarantees the venue is polled at least once.
    """
    attempts = max(1, poll_max_attempts)
    for attempt in range(attempts):
        if intent.decision is Label.BUY:
            outcome = clients.gate_client.request(
                "GET", _ORDERS_PATH, transport=clients.transport
            )
            book = _ok_or_raise(outcome, what="live order confirm (orders read-back)")
            confirmation = _correlate_open_order(
                intent, book, queue_task_id=queue_task_id
            )
        else:
            outcome = clients.gate_client.request(
                "GET", _POSITIONS_PATH, transport=clients.transport
            )
            book = _ok_or_raise(
                outcome, what="live close confirm (positions read-back)"
            )
            confirmation = _correlate_close_position(intent, book)

        # A definitive ``filled`` observation ends the loop immediately. An order
        # correlated-but-not-yet-``finished`` (``unconfirmed``) keeps polling — the
        # fill may land on a later attempt — until the cap.
        if confirmation is not None and confirmation.get("status") == "filled":
            return confirmation

        # Sleep the injectable interval only when another attempt will follow.
        if attempt < attempts - 1:
            poll_sleep(poll_interval_s)

    # Cap exhausted with no confirming fill -> surface unconfirmed (Req 9.2).
    return {"status": "unconfirmed", "raw": None}


__all__ = [
    "BrokerReadoutError",
    "ReadoutClients",
    "default_clients",
    "get_positions",
    "get_account_assets",
    "list_tradable_symbols",
    "validate_symbol",
    "get_history",
    "PreTransmitSnapshot",
    "gather_snapshot",
    "submit_decision",
]
