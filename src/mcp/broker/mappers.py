"""Pure venue<->domain mappers + decision->action mapping (Task 2.2).

Domain layer of the broker's layered ports-and-adapters stack
(`models -> config -> gate_client -> {mappers, symbol_cache} -> validation ->
paper -> core -> server`). This module imports ONLY ``models`` (the layers above
it): it is pure — no I/O, no ``httpx``, no transport construction (design: "the
``validation`` / ``paper`` / ``mappers`` layers must stay free of
transport-construction side effects").

Two responsibility groups (design "symbol_cache & mappers (summary)" + the P9
vocabulary->endpoint table in ``gate-tradfi-api-reference.md``):

1. **Decision -> venue action.** ``map_decision_to_action(intent)`` turns a P9
   ``Label`` + ``Direction`` into the venue request to issue. The venue ``side``
   enum is COUNTERINTUITIVE — ``1 = SELL``, ``2 = BUY`` — so a buy-to-open (LONG
   entry) is ``side`` 2 and a sell-to-open (SHORT entry) is ``side`` 1
   (reference "Critical enums"). TRIM is a PARTIAL position-close; SELL is a FULL
   position-close (``close_volume`` null). Both close on the CALLER-supplied
   ``position_id`` (Req 1.9) — this layer never selects among same-symbol
   positions. The order request carries NO per-order leverage parameter (Req 5.2
   / reference gotcha #2): exposure is controlled via ``volume`` only.

2. **Raw venue JSON -> typed readouts.** All venue numeric/price/volume fields
   arrive as STRINGS (reference header); these parsers coerce them to typed
   Python scalars at the boundary (HG-23 is presence-only — P13; the adapter
   validates its own types). Venue-authoritative values — ``unrealized_pnl``
   (Req 2.2), ``stop_out_level`` (Req 3.2), and history ``realized_pnl`` /
   ``swap`` (Req 10.3) — are reported VERBATIM; the adapter never substitutes a
   self-computed mark, liquidation distance, or carry. ``close_reason`` flags
   normal vs forced liquidation from ``position_status`` = 2 (positions history)
   or ``order_opt_type`` 5|6 (orders history) WITHOUT interpretation (Req 10.2).

The used-margin helper (Req 5.3) implements the venue cross-margin model:
``used_margin = notional / leverage`` where ``notional = volume x contract_volume
x price`` (``contract_volume`` is the per-symbol contract size — reference gotcha
#4). It is exposed for the validation layer; this adapter never sizes or upsizes
(Req 7.1/7.3) — the value is for a reject decision only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Domain types — imported BY NAME (production posture: broker dir on sys.path[0]).
# This is the only dependency of the mappers layer (pure domain).
from models import (
    AccountAssets,
    CloseReason,
    Direction,
    HistoryRecord,
    Label,
    OrderIntent,
    OrderType,
    Position,
    SymbolInfo,
)

# --------------------------------------------------------------------------- #
# Venue enum constants (reference "Critical enums"). Named so the side-enum
# guard is explicit at every use site — the 1=SELL/2=BUY inversion is the single
# most error-prone field in the venue contract.
# --------------------------------------------------------------------------- #

SIDE_SELL = 1  # ⚠ venue: 1 = SELL
SIDE_BUY = 2  # ⚠ venue: 2 = BUY

# orders/history order_opt_type force-close codes (reference: 5=force close long,
# 6=force close short) -> liquidation events.
_FORCED_OPT_TYPES = frozenset({5, 6})
# positions/history position_status (reference: 1=fully closed, 2=forced liquidation).
_POSITION_STATUS_FORCED = 2


# --------------------------------------------------------------------------- #
# Decision -> venue action.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class VenueAction:
    """The venue request a decision maps to (Req 1.1-1.3, 1.9, 5.2).

    ``endpoint`` / ``method`` name the Gate `/tradfi` route; ``body`` is the
    request payload (the signed-transport layer adds auth / SIGN, never this
    layer). ``body`` NEVER contains a ``leverage`` key (Req 5.2).
    """

    endpoint: str
    method: str
    body: dict[str, Any] = field(default_factory=dict)


def _price_type(order_type: OrderType) -> str:
    """Venue ``price_type`` for an order (reference: market | trigger)."""
    return "trigger" if order_type is OrderType.TRIGGER else "market"


def _open_order_action(intent: OrderIntent) -> VenueAction:
    """BUY decision -> open/increase a position via POST /tradfi/orders.

    LONG entry  = buy-to-open  -> side 2 (SIDE_BUY).
    SHORT entry = sell-to-open -> side 1 (SIDE_SELL).
    (reference P9 table + "Critical enums": side 1=SELL/2=BUY — guard the inversion.)
    """
    # Side-enum guard: derive purely from the caller-supplied direction so the
    # 1=SELL/2=BUY inversion lives in exactly one place.
    side = SIDE_BUY if intent.direction is Direction.LONG else SIDE_SELL

    body: dict[str, Any] = {
        "symbol": intent.symbol,
        "side": side,
        "volume": intent.volume,
        "price_type": _price_type(intent.order_type),
    }
    # Trigger orders carry the activation price in the request `price` field;
    # a market order has no resting price (reference: no limit book).
    if intent.order_type is OrderType.TRIGGER:
        body["price"] = intent.trigger_price
    # Optional TP/SL are separate venue fields (reference gotcha) — pass through
    # only when supplied; never synthesized here.
    if intent.take_profit is not None:
        body["price_tp"] = intent.take_profit
    if intent.stop_loss is not None:
        body["price_sl"] = intent.stop_loss

    # Req 5.2: the venue order request carries NO leverage parameter. (Asserted
    # by construction — we never add a 'leverage' key on any path.)
    return VenueAction(endpoint="/tradfi/orders", method="POST", body=body)


def _close_action(intent: OrderIntent, *, full: bool) -> VenueAction:
    """TRIM/SELL decision -> close-by-position-id via POST .../positions/{id}/close.

    TRIM (``full=False``) sends a partial ``close_volume`` = caller volume.
    SELL (``full=True``) sends ``close_volume`` = None (venue: null = full close).
    The position id is the CALLER-supplied one, verbatim (Req 1.9) — this layer
    never selects among same-symbol positions.
    """
    position_id = intent.position_id
    body: dict[str, Any] = {
        # close_type 1/2 semantics are TBD per the reference (confirm on first
        # authenticated close); default to 1 — the venue accepts it and v0.1 is
        # paper-only so no live close is transmitted.
        "close_type": 1,
        "close_volume": None if full else intent.volume,
    }
    return VenueAction(
        endpoint=f"/tradfi/positions/{position_id}/close",
        method="POST",
        body=body,
    )


def map_decision_to_action(intent: OrderIntent) -> VenueAction:
    """Map a P9 ``Label`` + ``Direction`` to the venue order action (Req 1.1-1.3, 1.9).

    HOLD has no venue action (reference P9 table: "no call") — ``core`` short-
    circuits HOLD to a no-op before reaching the mapper, so it is a programming
    error to ask the mapper to build a venue action for HOLD.

    The order request carries NO per-order leverage parameter (Req 5.2). TRIM/SELL
    act on ``intent.position_id`` exactly as supplied (Req 1.9).
    """
    if intent.decision is Label.BUY:
        return _open_order_action(intent)
    if intent.decision is Label.TRIM:
        return _close_action(intent, full=False)
    if intent.decision is Label.SELL:
        return _close_action(intent, full=True)
    # HOLD (or any non-actionable label) has no venue action.
    raise ValueError(
        f"{intent.decision} has no venue order action; HOLD is a no-op handled by core"
    )


# --------------------------------------------------------------------------- #
# Margin / exposure (Req 5.3).
# --------------------------------------------------------------------------- #


def compute_used_margin(
    *,
    volume: float,
    contract_volume: float,
    price: float,
    leverage: float,
) -> float:
    """Used-margin / exposure = notional / leverage (Req 5.3).

    ``notional = volume x contract_volume x price`` (``contract_volume`` is the
    per-symbol contract size — reference gotcha #4). The result is the
    cross-margin requirement for the order, used by the validation layer for a
    REJECT decision only — this adapter never sizes or upsizes (Req 7.1/7.3).

    Pure function. Raises ``ValueError`` on a non-positive leverage (a degenerate
    venue/cache value) rather than returning ``inf`` / dividing by zero.
    """
    if leverage <= 0:
        raise ValueError(f"leverage must be positive, got {leverage!r}")
    notional = volume * contract_volume * price
    return notional / leverage


# --------------------------------------------------------------------------- #
# Raw JSON -> typed readouts. All venue numerics arrive as strings.
# --------------------------------------------------------------------------- #


def _f(value: Any) -> float:
    """Parse a venue string numeric to ``float`` (boundary coercion)."""
    return float(value)


def _i(value: Any) -> int:
    """Parse a venue string numeric to ``int`` (e.g. price_precision)."""
    # Venue precision arrives as a string like "2"; tolerate an int too.
    return int(value)


def _direction_from_position_dir(position_dir: str) -> Direction:
    """Map the venue ``position_dir`` (``Long`` | ``Short``) to ``Direction``."""
    return Direction.LONG if str(position_dir).lower() == "long" else Direction.SHORT


def parse_positions(raw: Any) -> list[Position]:
    """Raw ``/tradfi/positions`` JSON -> ``[Position]`` (Req 2.1, 2.2).

    The venue ``unrealized_pnl`` is reported VERBATIM (parsed string->float, value
    preserved) — the adapter never substitutes a self-computed mid/mark (Req 2.2).
    An empty venue set yields ``[]`` (Req 2.3 surfaced at the readout layer).
    """
    return [
        Position(
            position_id=str(p["position_id"]),
            symbol=str(p["symbol"]),
            direction=_direction_from_position_dir(p["position_dir"]),
            volume=_f(p["volume"]),
            avg_open_price=_f(p["price_open"]),
            used_margin=_f(p["margin"]),
            # Req 2.2: venue figure, verbatim. No self-computed mark.
            unrealized_pnl=_f(p["unrealized_pnl"]),
        )
        for p in raw
    ]


def parse_account_assets(assets_raw: Any, mt5_raw: Any) -> AccountAssets:
    """Raw ``/tradfi/users/assets`` + ``/tradfi/users/mt5-account`` -> ``AccountAssets``.

    Exposes ``stop_out_level`` (from mt5-account) so a downstream consumer can
    compute account-level liquidation distance; the adapter itself carries NO
    derived liquidation-distance field and asserts none (Req 3.2 — that math is
    survival-gate's). Venue-supplied equity/margin/balance are parsed string->float.
    """
    return AccountAssets(
        equity=_f(assets_raw["equity"]),
        used_margin=_f(assets_raw["margin"]),
        free_margin=_f(assets_raw["margin_free"]),
        margin_level=_f(assets_raw["margin_level"]),
        balance=_f(assets_raw["balance"]),
        # Req 3.2: stop-out level exposed verbatim; NO liquidation-distance math.
        stop_out_level=_f(mt5_raw["stop_out_level"]),
    )


def parse_symbols_detail(raw: Any) -> list[SymbolInfo]:
    """Raw ``/tradfi/symbols/detail`` JSON -> ``[SymbolInfo]`` (Req 4.* inputs, 5.*).

    Identity is the US ticker (``symbol``); ``symbol_desc`` is NEVER used for
    identity (Req 4.1 — enforced in symbol_cache; this parser simply does not read
    it). ``trade_mode`` and ``category`` are reported as the venue's own values
    (verbatim) so the validation layer interprets them, not this layer. Numeric
    fields are parsed string->typed; ``price_precision`` is an int.
    """
    return [
        SymbolInfo(
            ticker=str(s["symbol"]),
            category=str(s["category_id"]),
            leverage=_f(s["leverage"]),
            trade_mode=str(s["trade_mode"]),
            min_order_volume=_f(s["min_order_volume"]),
            max_order_volume=_f(s["max_order_volume"]),
            price_precision=_i(s["price_precision"]),
            buy_swap_rate=_f(s["buy_swap_cost_rate"]),
            sell_swap_rate=_f(s["sell_swap_cost_rate"]),
            # detail rows do not carry an open/closed status field; the symbols
            # universe (/tradfi/symbols) carries session status + next_open_time.
            # symbol_cache merges them — here detail rows default to "unknown".
            status=str(s.get("status", "unknown")),
            next_open_time=_optional_int(s.get("next_open_time")),
        )
        for s in raw
    ]


def _optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    return int(value)


def _close_reason_from_opt_type(order_opt_type: Any) -> CloseReason:
    """orders/history ``order_opt_type`` -> close reason (Req 10.2).

    5 = force close long, 6 = force close short -> forced_liquidation; everything
    else is a normal open/close. No interpretation beyond the venue's own flag.
    """
    return (
        "forced_liquidation" if int(order_opt_type) in _FORCED_OPT_TYPES else "normal"
    )


def _close_reason_from_position_status(position_status: Any) -> CloseReason:
    """positions/history ``position_status`` -> close reason (Req 10.2).

    2 = forced liquidation; 1 = normal full close. Venue flag, no interpretation.
    """
    return (
        "forced_liquidation"
        if int(position_status) == _POSITION_STATUS_FORCED
        else "normal"
    )


def parse_orders_history(raw: Any) -> list[HistoryRecord]:
    """Raw ``/tradfi/orders/history`` JSON -> ``[HistoryRecord]`` (kind=order).

    Venue values reported VERBATIM (Req 10.3): ``price`` (avg fill), ``fill_volume``,
    ``close_pnl`` are parsed string->float, never recomputed. ``close_reason`` is
    flagged from ``order_opt_type`` (Req 10.2). Orders history carries no per-order
    swap field; realized swap is a positions-history figure (reported there).
    Empty window -> ``[]`` (Req 10.4 surfaced at the readout layer).
    """
    return [
        HistoryRecord(
            kind="order",
            fill_price=_f(r["price"]),
            fill_volume=_f(r["fill_volume"]),
            realized_pnl=_f(r["close_pnl"]),
            # orders/history has no swap field; realized swap lives on positions/
            # history. Report 0.0 carry on an order record rather than inventing one.
            realized_swap=0.0,
            close_reason=_close_reason_from_opt_type(r["order_opt_type"]),
        )
        for r in raw
    ]


def parse_positions_history(raw: Any) -> list[HistoryRecord]:
    """Raw ``/tradfi/positions/history`` JSON -> ``[HistoryRecord]`` (kind=position).

    Venue values reported VERBATIM (Req 10.3): ``realized_pnl``, ``swap``,
    ``close_price`` are parsed string->float, never recomputed. ``close_reason`` is
    flagged from ``position_status`` 2 (Req 10.2). Empty window -> ``[]`` (Req 10.4).
    """
    return [
        HistoryRecord(
            kind="position",
            fill_price=_f(r["close_price"]),
            # positions/history reports the closed volume implicitly via pnl; the
            # venue close record carries no separate fill_volume — surface 0.0 so
            # the typed field is populated without a self-computed substitution.
            fill_volume=_f(r["close_volume"]) if "close_volume" in r else 0.0,
            realized_pnl=_f(r["realized_pnl"]),
            # Req 10.3: venue swap verbatim (a financing/carry figure, not derived).
            realized_swap=_f(r["swap"]),
            close_reason=_close_reason_from_position_status(r["position_status"]),
        )
        for r in raw
    ]


__all__ = [
    "VenueAction",
    "SIDE_BUY",
    "SIDE_SELL",
    "map_decision_to_action",
    "compute_used_margin",
    "parse_positions",
    "parse_account_assets",
    "parse_symbols_detail",
    "parse_orders_history",
    "parse_positions_history",
]
