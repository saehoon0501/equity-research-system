"""Broker (Gate TradFi CFD) domain types and decision vocabulary.

Source of truth: ``.kiro/specs/broker-cfd-adapter/design.md`` "Data Models →
Domain Model (value objects — models.py)" and the core Service Interface.

Module name: this file is ``models.py`` (NOT ``types.py``). A module named
``types`` would shadow the Python stdlib ``types`` module: the MCP runtime
launches the server as ``python server.py`` with the broker dir on
``sys.path[0]``, so sibling production modules importing these domain types by
name would resolve a local ``types`` first and break stdlib ``enum`` (which
needs ``MappingProxyType`` from stdlib ``types``); with PYTHONSAFEPATH the local
file is instead unreachable (stdlib ``types`` wins). ``models`` collides with
nothing, so by-name sibling imports (``from models import OrderIntent``) work
under the production launch posture.

This is the bottom layer of the broker's layered ports-and-adapters stack
(`models → config → gate_client → {mappers, symbol_cache} → validation → paper →
core → server`). It defines pure value objects / enums only — no I/O, no
transport, no venue knowledge beyond field shapes.

P9 (one canonical vocabulary): the BUY/HOLD/TRIM/SELL decision vocabulary is the
shared ``Label`` enum from ``src.calibration.scorer``. It is IMPORTED and
re-exported here, never redefined. Every broker module that needs the decision
vocabulary imports ``Label`` from this module so there is a single import seam.

Repo-root bootstrap (pre-solved integration detail): the broker runs in its own
``uv`` venv that does NOT carry the repo root on ``sys.path``, so a bare
``from src.calibration.scorer import Label`` would fail at runtime. We insert the
repo root onto ``sys.path`` (if absent) before importing. ``src.calibration``
uses lazy imports, so this pulls no heavy dependencies (numpy etc.).

All venue numeric fields arrive from Gate as strings; the ``mappers`` layer
parses and validates them at the boundary (HG-23 is presence-only — P13; this
adapter validates its own types). These value objects therefore carry already
parsed Python scalars.
"""

from __future__ import annotations

import sys as _sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path as _Path
from typing import Any, Literal, Optional

# --- repo-root bootstrap so `src.calibration.scorer` resolves in the broker venv ---
# models.py lives at <repo>/src/mcp/broker/models.py:
#   parents[0] = .../src/mcp/broker
#   parents[1] = .../src/mcp
#   parents[2] = .../src
#   parents[3] = <repo root>   <-- what `from src.calibration...` needs on sys.path
_REPO_ROOT = _Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

# P9: import the canonical decision vocabulary; do NOT redefine BUY/HOLD/TRIM/SELL.
from src.calibration.scorer import Label  # noqa: E402  (after sys.path bootstrap)


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class Direction(str, Enum):
    """Caller-supplied trade direction (the reactive layer owns the side, §12.3)."""

    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(str, Enum):
    """Accepted order types. Only market and trigger are supported (Req 1.5)."""

    MARKET = "MARKET"
    TRIGGER = "TRIGGER"


class RejectionCode(str, Enum):
    """Enumerated rejection codes for the conservative reject-only chain.

    One code per design "Data Models → RejectionReason.code" set.
    """

    INACTIVE_ACCOUNT = "INACTIVE_ACCOUNT"
    UNKNOWN_SYMBOL = "UNKNOWN_SYMBOL"
    OUT_OF_CATEGORY = "OUT_OF_CATEGORY"
    UNTRADABLE = "UNTRADABLE"
    TRADE_MODE_BLOCKED = "TRADE_MODE_BLOCKED"
    BAD_ORDER_TYPE = "BAD_ORDER_TYPE"
    VOLUME_OUT_OF_BOUNDS = "VOLUME_OUT_OF_BOUNDS"
    MARKET_CLOSED = "MARKET_CLOSED"
    NO_POSITION = "NO_POSITION"
    LIVE_SEND_BLOCKED = "LIVE_SEND_BLOCKED"


# Status / reason literals (narrative-only string unions; this layer carries the
# parsed value, the mappers / validation layers enforce membership).
OrderStatus = Literal["filled", "simulated", "unconfirmed", "noop", "rejected"]
CloseReason = Literal["normal", "forced_liquidation"]
HistoryKind = Literal["order", "position"]


# --------------------------------------------------------------------------- #
# Value objects
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RejectionReason:
    """A structured, conservative rejection (never a silent modify — Req 7.2).

    ``next_open_time`` is populated only for MARKET_CLOSED (Req 6.1).
    """

    code: RejectionCode
    message: str
    next_open_time: Optional[int] = None


@dataclass(frozen=True)
class OrderIntent:
    """A fully-specified, pre-transmit order intent.

    ``trigger_price`` is required when ``order_type`` is TRIGGER (Req 1.5);
    ``volume`` is required for BUY; ``position_id`` for TRIM/SELL (validated by
    the validation layer, not here). HOLD needs none of these (Req 1.4).
    """

    decision: Label
    symbol: str
    direction: Direction
    volume: Optional[float] = None
    position_id: Optional[str] = None
    order_type: OrderType = OrderType.MARKET
    trigger_price: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None


@dataclass(frozen=True)
class OrderResult:
    """The structured outcome of a submit_decision call (never raises — Req 9.2).

    ``status`` is one of filled | simulated | unconfirmed | noop | rejected.
    ``reason`` is populated on a rejected status; ``raw`` carries the venue
    payload for downstream slippage/telemetry consumers (Req 9.3, 9.4).
    """

    status: OrderStatus
    order_id: Optional[str] = None
    position_id: Optional[str] = None
    fill_price: Optional[float] = None
    fill_volume: Optional[float] = None
    reason: Optional[RejectionReason] = None
    raw: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class Position:
    """An open position with venue-authoritative valuations (Req 2.1, 2.2).

    ``unrealized_pnl`` is the venue-supplied figure; the adapter never substitutes
    a self-computed mark (Req 2.2).
    """

    position_id: str
    symbol: str
    direction: Direction
    volume: float
    avg_open_price: float
    used_margin: float
    unrealized_pnl: float


@dataclass(frozen=True)
class AccountAssets:
    """Account-level readout for downstream survival logic (Req 3.1, 3.2).

    Exposes ``stop_out_level`` so a downstream consumer can compute account-level
    liquidation distance. The adapter deliberately carries NO derived
    liquidation-distance field (Req 3.2 — that math belongs to survival-gate).
    """

    equity: float
    used_margin: float
    free_margin: float
    margin_level: float
    balance: float
    stop_out_level: float


@dataclass(frozen=True)
class SymbolInfo:
    """Per-symbol venue metadata, identified by US ticker only (Req 4.1).

    ``next_open_time`` is populated when ``status`` is closed (Req 6.1 input).
    """

    ticker: str
    category: str
    leverage: float
    trade_mode: str
    min_order_volume: float
    max_order_volume: float
    price_precision: int
    buy_swap_rate: float
    sell_swap_rate: float
    status: str
    next_open_time: Optional[int] = None


@dataclass(frozen=True)
class HistoryRecord:
    """A closed order or position with venue-supplied fill/carry data (Req 10.1).

    ``close_reason`` flags normal vs forced liquidation without interpretation
    (Req 10.2); all values are venue-supplied, never self-computed (Req 10.3).
    """

    kind: HistoryKind
    fill_price: float
    fill_volume: float
    realized_pnl: float
    realized_swap: float
    close_reason: CloseReason


__all__ = [
    "Label",  # re-exported P9 vocabulary — single import seam for broker modules
    "Direction",
    "OrderType",
    "RejectionCode",
    "RejectionReason",
    "OrderIntent",
    "OrderResult",
    "OrderStatus",
    "Position",
    "AccountAssets",
    "SymbolInfo",
    "HistoryRecord",
    "CloseReason",
    "HistoryKind",
]
