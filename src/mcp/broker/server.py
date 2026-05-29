"""Broker (Gate TradFi CFD) MCP server — the thin tool surface over ``core``.

Source of truth: ``.kiro/specs/broker-cfd-adapter/design.md`` — "Simulation &
Interface (summary) -> server" bullet, the Components table ``server`` row
("Thin MCP tool wrappers; never raise"), the File Structure Plan (``server.py``
+ the modified ``.mcp.json``), and the Error-Handling strategy (``server`` is the
never-raises seam). Requirements: ``.kiro/specs/broker-cfd-adapter/requirements.md``
Req 9.2 (venue error / unreachable -> structured result, no raise).

Layer position (``models -> config -> gate_client -> {mappers, symbol_cache} ->
validation -> paper -> core -> server``): ``server`` is the TOP layer — the
Claude->tool seam. It imports ``core`` (the daemon-callable leaf functions) and
nothing imports it. The execution-daemon bypasses this layer entirely and imports
``core`` in-process; this module exists only for the MCP transport.

House MCP pattern (mirrors ``src/mcp/massive/server.py`` /
``src/mcp/polygon/server.py``): ``mcp = FastMCP("broker")``; one ``@mcp.tool()``
per ``core`` leaf function; every tool returns a plain JSON-able ``dict`` and
NEVER raises; ``if __name__ == "__main__": mcp.run()``. The deliberate deviation
this server family carries (design "Existing Architecture Analysis") is the
``core.py`` / ``server.py`` split — the daemon needs in-process leaf functions,
not an MCP round-trip — so the leaf logic lives in ``core`` and this file is a
thin coercion+never-raise shell only.

The never-raises seam (design "Error Handling"; Req 9.2)
--------------------------------------------------------
``core``'s readouts RAISE :class:`core.BrokerReadoutError` on a surfaced
transport/venue failure (so the in-process daemon caller gets a clean return
type), and ``submit_decision`` returns a structured ``OrderResult`` without
raising. This module is where that split is reconciled for the MCP client: EVERY
tool wraps its ``core`` call in a guard that catches BOTH
:class:`core.BrokerReadoutError` AND any unexpected ``Exception``, coercing each
into a structured error ``dict`` (``error_class`` / ``message`` /
``status_code`` — Req 9.2). The tool therefore never raises — the MCP client
always receives a dict.

Coercion (typed result -> plain JSON-able dict)
-----------------------------------------------
``core`` returns frozen dataclasses (``Position`` / ``AccountAssets`` /
``SymbolInfo`` / ``HistoryRecord`` / ``OrderResult``) or a
``RejectionReason``. :func:`_to_jsonable` walks those into plain dicts/lists and
normalizes every enum (``Direction`` / ``OrderType`` / ``RejectionCode`` / the
P9 ``Label``) to its plain string value, so the wire payload carries no enum or
dataclass instances. List readouts are wrapped in a small named envelope
(``{"positions": [...]}`` etc.) so the tool return type is always a ``dict``
(the house convention; MCP tools return ``dict``).

Secrets (Security Considerations): error dicts are secret-free. ``core`` /
``gate_client`` never put the API key/secret into ``BrokerReadoutError`` or an
exception message, and this module surfaces only ``error_class`` / ``message`` /
``status_code`` — never the raw exception's environment.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

# ``core`` is imported BY NAME (production posture: broker dir on sys.path[0]
# when launched as ``python server.py``; the unit test aliases ``core`` into
# sys.modules before loading this file so the same instance is reused).
import core as _core
from models import Direction, Label, OrderType  # noqa: F401  (re-resolve for coercion args)

mcp = FastMCP("broker")


# --------------------------------------------------------------------------- #
# Coercion — typed core result -> plain JSON-able dict (no enum/dataclass leak).
# --------------------------------------------------------------------------- #


def _to_jsonable(value: Any) -> Any:
    """Recursively coerce a ``core`` result into a plain JSON-able structure.

    * a frozen dataclass (``Position`` / ``OrderResult`` / ``RejectionReason`` /
      ...) -> a ``dict`` of its fields, each coerced;
    * an ``Enum`` (``Direction`` / ``OrderType`` / ``RejectionCode`` / the P9
      ``Label``) -> its ``.value`` (a plain string — these enums are ``str, Enum``
      so the value is already a string);
    * a list / tuple -> a list of coerced items;
    * a dict -> a dict of coerced values (``raw`` venue payloads ride through
      unchanged once their leaves are JSON-able);
    * a plain scalar (str / int / float / bool / None) -> itself.

    Normalizing enums to ``.value`` (rather than relying on the ``str, Enum``
    subclass) guarantees the wire payload carries plain ``str`` instances, not
    enum objects — a clean MCP-client contract.
    """
    # Enums FIRST: ``Direction`` / ``RejectionCode`` / ``Label`` are ``str, Enum``
    # subclasses, so an ``isinstance(value, str)`` test would short-circuit and
    # leak the enum instance through. Normalize to ``.value`` (a plain ``str``).
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    # Anything else (shouldn't occur for core's typed results) -> string form, so
    # the tool still returns a JSON-able dict rather than raising on json encode.
    return str(value)


def _error_dict(
    *,
    error_class: str,
    message: str,
    status_code: Optional[int] = None,
) -> dict[str, Any]:
    """Build the structured error dict shape (Req 9.2): ``error_class`` /
    ``message`` / ``status_code``, plus an ``error`` flag the MCP client can
    branch on. Secret-free by construction (callers pass only the failure class /
    a secret-free message / the venue status code)."""
    return {
        "error": True,
        "error_class": error_class,
        "message": message,
        "status_code": status_code,
    }


def _guard(call, *args, **kwargs) -> Any:
    """Run a ``core`` call and NEVER raise (design: ``server`` is the never-raises
    seam; Req 9.2).

    Catches BOTH a surfaced :class:`core.BrokerReadoutError` (a transport/venue
    failure ``core`` raises so its in-process return types stay clean) AND any
    unexpected ``Exception``, coercing each into a structured error dict. On
    success returns the raw (un-coerced) ``core`` result — the caller coerces it
    into the tool's envelope shape.
    """
    try:
        return call(*args, **kwargs)
    except _core.BrokerReadoutError as exc:
        return _error_dict(
            error_class=exc.error_class,
            message=exc.message,
            status_code=exc.status_code,
        )
    except Exception as exc:  # noqa: BLE001 — the never-raises seam (9.2).
        # Surface only the class + a secret-free string; do NOT echo args/env.
        return _error_dict(error_class="unexpected", message=str(exc))


def _is_error(result: Any) -> bool:
    """True when ``_guard`` already produced a structured error dict (so the tool
    returns it verbatim rather than re-wrapping it as a success envelope)."""
    return isinstance(result, dict) and result.get("error") is True


# --------------------------------------------------------------------------- #
# MCP tools — one per core leaf function. Each returns a dict; none raise (9.2).
# --------------------------------------------------------------------------- #


@mcp.tool()
def submit_decision(
    decision: str,
    symbol: str,
    direction: str,
    volume: Optional[float] = None,
    position_id: Optional[str] = None,
    order_type: str = "MARKET",
    trigger_price: Optional[float] = None,
    take_profit: Optional[float] = None,
    stop_loss: Optional[float] = None,
) -> dict:
    """Route a BUY/HOLD/TRIM/SELL decision + direction to the venue (paper-only v0.1).

    Wraps ``core.submit_decision`` (the single validated path the daemon shares).
    ``decision`` is the P9 vocabulary (BUY | HOLD | TRIM | SELL); ``direction`` is
    LONG | SHORT; ``order_type`` is MARKET | TRIGGER. Strings are coerced to the
    domain enums here (an unknown value surfaces as a structured error dict, never
    a raise).

    Returns a plain dict — the coerced ``OrderResult`` (``status`` one of
    ``simulated`` | ``noop`` | ``rejected`` | ``filled`` | ``unconfirmed``, with a
    nested ``reason`` dict on a rejection). On any failure returns a structured
    error dict (Req 9.2); never raises.
    """
    # Coerce the string inputs to the domain enums; an invalid value -> error dict.
    try:
        decision_enum = Label(decision)
        direction_enum = Direction(direction)
        order_type_enum = OrderType(order_type)
    except (ValueError, KeyError) as exc:
        return _error_dict(error_class="bad_input", message=str(exc))

    result = _guard(
        _core.submit_decision,
        decision_enum,
        symbol,
        direction_enum,
        volume=volume,
        position_id=position_id,
        order_type=order_type_enum,
        trigger_price=trigger_price,
        take_profit=take_profit,
        stop_loss=stop_loss,
    )
    if _is_error(result):
        return result
    return _to_jsonable(result)


@mcp.tool()
def get_positions() -> dict:
    """Read all open positions (Req 2.1–2.3).

    Wraps ``core.get_positions``. Returns ``{"positions": [<position dict>, ...]}``
    — an empty book is ``{"positions": []}`` (Req 2.3), never an error. Each
    position dict carries the venue-supplied ``unrealized_pnl`` verbatim (Req 2.2;
    ``direction`` is a plain string). On a transport/venue failure returns a
    structured error dict (Req 9.2); never raises.
    """
    result = _guard(_core.get_positions)
    if _is_error(result):
        return result
    return {"positions": _to_jsonable(result)}


@mcp.tool()
def get_account_assets() -> dict:
    """Read account assets incl. the stop-out level (Req 3.1, 3.2).

    Wraps ``core.get_account_assets``. Returns the coerced ``AccountAssets`` dict
    (equity / used_margin / free_margin / margin_level / balance / stop_out_level)
    — NO derived liquidation distance (Req 3.2). On failure returns a structured
    error dict (Req 9.2); never raises.
    """
    result = _guard(_core.get_account_assets)
    if _is_error(result):
        return result
    return _to_jsonable(result)


@mcp.tool()
def list_tradable_symbols() -> dict:
    """List the in-category (US-stock CFD) tradable symbol set (Req 3.3, 4.1, 4.2).

    Wraps ``core.list_tradable_symbols``. Returns ``{"symbols": [<symbol dict>, ...]}``
    — each dict surfaces per-symbol swap rates / leverage / trade_mode / volume
    bounds, identified by US ticker only (Req 4.1). On failure returns a structured
    error dict (Req 9.2); never raises.
    """
    result = _guard(_core.list_tradable_symbols)
    if _is_error(result):
        return result
    return {"symbols": _to_jsonable(result)}


@mcp.tool()
def validate_symbol(symbol: str) -> dict:
    """Validate a single US ticker (Req 4.1, 4.2).

    Wraps ``core.validate_symbol``. A known in-category ticker -> the coerced
    ``SymbolInfo`` dict; an unknown / out-of-category ticker -> the coerced
    ``RejectionReason`` dict (``code`` one of ``UNKNOWN_SYMBOL`` / ``OUT_OF_CATEGORY``,
    a plain string). On a transport/venue failure returns a structured error dict
    (Req 9.2); never raises.
    """
    result = _guard(_core.validate_symbol, symbol)
    if _is_error(result):
        return result
    return _to_jsonable(result)


@mcp.tool()
def get_history(since: Optional[int] = None, until: Optional[int] = None) -> dict:
    """Read closed order/position history (Req 9.3, 10.1–10.4).

    Wraps ``core.get_history``. Returns ``{"history": [<history record dict>, ...]}``
    surfacing venue-supplied fills (Req 9.3), realized swap (Req 3.3), realized
    PnL, and the ``close_reason`` (``normal`` | ``forced_liquidation`` — Req 10.2).
    An empty window is ``{"history": []}`` (Req 10.4), never an error. ``since`` /
    ``until`` are the venue window bounds (epoch seconds). On failure returns a
    structured error dict (Req 9.2); never raises.
    """
    result = _guard(_core.get_history, since, until)
    if _is_error(result):
        return result
    return {"history": _to_jsonable(result)}


if __name__ == "__main__":
    mcp.run()
