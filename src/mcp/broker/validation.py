"""Pre-transmit validation chain — the broker's Policy layer (Task 3.2).

Source of truth: ``.kiro/specs/broker-cfd-adapter/design.md`` — the "Policy layer
-> validation (ordered reject-only chain)" block (Responsibilities & Constraints,
the ``evaluate(intent, ctx)`` Service Interface, and the locked predicate order)
plus the Requirements Traceability rows for 1.5, 1.6, 1.8, 1.10, 1.11, 4.2, 4.3,
5.1, 6.1, 7.1, 7.2. Requirements: ``.kiro/specs/broker-cfd-adapter/requirements.md``
Req 1.5, 1.6, 1.8, 1.10, 1.11, 4.2, 4.3, 5.1, 6.1, 7.1, 7.2. Venue semantics:
``.kiro/specs/broker-cfd-adapter/gate-tradfi-api-reference.md`` ("Critical enums" —
``trade_mode`` 0..4; ``side`` 1=SELL/2=BUY) and ``gate-api-gaps.md`` ("Already
verified": 441 US-stock CFDs, 65@5x / 370@4x = product floor / 6@3.33x sub-floor).

Layer position (``models -> config -> gate_client -> {mappers, symbol_cache} ->
validation -> paper -> core -> server``): validation sits in the Policy layer,
ABOVE the transport/domain layers. It is a PURE, ordered predicate chain that runs
before any transmit and can ONLY reject.

Purity contract (design "validation" Invariants):
    - NO I/O. This module imports ONLY ``models`` + ``config``. It does NOT import
      ``gate_client`` / ``symbol_cache`` / ``httpx`` — the caller (``core``, Task
      4.2) resolves the SymbolInfo, account snapshot, open positions, and runtime
      mode and hands them in via a populated :class:`ValidationContext`. Validation
      never fetches.
    - NEVER mutates the request (Req 7.1, 7.2): the only outcomes are pass-through
      (``None``) or a structured :class:`models.RejectionReason`. It never
      increases / clamps / modifies ``volume`` or any other field. The input
      ``OrderIntent`` is a frozen dataclass and is returned untouched.

Locked chain order (first failure short-circuits — design "validation"
Responsibilities; a unit test asserts the ordering):

    1. account active (Req 1.10) ............ INACTIVE_ACCOUNT
    2. symbol in the validated set (Req 4.3)  UNKNOWN_SYMBOL
    3. category is US-stock (Req 4.2) ....... OUT_OF_CATEGORY
    4. tradable: not disabled AND not a sub-floor-leverage name (Req 5.1) UNTRADABLE
    5. trade_mode allows the action (Req 1.11) TRADE_MODE_BLOCKED
    6. order type market/trigger; trigger_price present when TRIGGER (Req 1.5) BAD_ORDER_TYPE
    7. volume within [min, max] (Req 1.6) ... VOLUME_OUT_OF_BOUNDS
    8. session open (Req 6.1) ............... MARKET_CLOSED (+ next_open_time)
    9. live-send clearances when live (Req 8.3) LIVE_SEND_BLOCKED

    For TRIM/SELL: the target position must exist in the snapshot (Req 1.8) NO_POSITION.
    The 1.8 position-exists check is folded into step 5's action context (a close on
    a missing position can never be a legal action) and runs as part of that step's
    decision — see ``_check_trade_mode_and_position``.

Why this exact order: the chain widens from cheapest, most-global gates (account,
identity) to symbol-specific gates (category, tradability, mode) to request-shaped
gates (order type, volume) to environment gates (session, live-send). Each later
predicate may legitimately ASSUME the earlier ones held (e.g. step 3 dereferences
the SymbolInfo, which step 2 proved present). Reordering would let a predicate read
an unvalidated field, so the order is load-bearing and locked by test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

# Validation imports ONLY the domain types + config — never transport / cache /
# httpx (purity contract above). ``config`` is needed for the US-stock category id
# default; ``models`` for the value objects + rejection vocabulary.
import config as _config
from models import (
    AccountAssets,
    Direction,
    Label,
    OrderIntent,
    OrderType,
    Position,
    RejectionCode,
    RejectionReason,
    SymbolInfo,
)

# --------------------------------------------------------------------------- #
# Product leverage floor (Req 5.1).
# --------------------------------------------------------------------------- #
# The US-stock CFD universe (category 2, 441 names) has THREE fixed per-instrument
# leverage tiers (gate-api-gaps.md "Already verified": 65 @ 5x, 370 @ 4x, 6 @
# 3.33x). The PRODUCT MIN-ORDER-LEVERAGE FLOOR is 4x; the 6 names at 3.33x sit
# BELOW that floor and are untradeable ("sub-floor names" — Req 5.1, design row
# 5.1, tasks.md 3.2). This is an explicit, spec-sourced constant, never a magic
# literal: a name whose per-symbol leverage is strictly below the floor is rejected
# UNTRADABLE regardless of trade_mode. (A tiny epsilon guards float dust so 3.33x
# is unambiguously sub-floor and 4.0x is unambiguously at-floor.)
PRODUCT_LEVERAGE_FLOOR: float = 4.0
_LEVERAGE_EPSILON: float = 1e-9

# Venue ``trade_mode`` enum (reference "Critical enums"): the per-symbol metadata
# carries this as a string of the venue int. Naming the modes here keeps the
# allowance logic readable and the magic ints out of the predicate body.
_TRADE_MODE_DISABLED = "0"  # no trading at all
_TRADE_MODE_LONG_ONLY = "1"  # only long entries (and closes)
_TRADE_MODE_SHORT_ONLY = "2"  # only short entries (and closes)
_TRADE_MODE_CLOSE_ONLY = "3"  # only position closes (no new opens)
_TRADE_MODE_FULL = "4"  # full trading

# Venue symbol session ``status`` (reference "Critical enums": open | closed).
_STATUS_OPEN = "open"


# --------------------------------------------------------------------------- #
# Validation context — populated by the caller (core, Task 4.2); validation reads.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ValidationContext:
    """The fully-resolved snapshot the chain evaluates against (design "validation"
    Invariants: "``core`` populates ``ctx`` with the single pre-transmit snapshot;
    ``validation`` never fetches").

    Every field is RESOLVED BY THE CALLER before ``evaluate`` is called — validation
    performs no I/O and dereferences only what is handed in:

    - ``symbol_info``: the resolved :class:`models.SymbolInfo` for the intent's
      symbol, or ``None`` if the symbol is not in the validated tradable set
      (the symbol_cache returned a rejection). ``None`` -> step 2 rejects.
    - ``account_active``: whether the TradFi account is in the active state
      (Req 1.10). This is the account-activation flag the snapshot carries
      (mirrors ``RuntimeMode.account_active`` but kept distinct so the source of
      truth — the live ``mt5-account.status`` read — drives it).
    - ``account_assets``: the account-assets snapshot (carried for completeness /
      future margin-aware predicates; validation does NOT gate on margin per Req
      1.6 — volume bounds are enforced regardless of margin). May be ``None`` when
      not yet read; the chain does not dereference it.
    - ``open_positions``: the open positions list from the single pre-transmit
      positions read (the SAME read the 7.4 double-send guard reuses). Drives the
      1.8 TRIM/SELL position-exists check.
    - ``runtime_mode``: the :class:`config.RuntimeMode` carrying paper flag +
      the four live-send clearances (Req 8.3 via ``live_transmit_allowed()``).
    - ``us_stock_category_id``: the in-scope category id (defaults to the venue
      constant); ``SymbolInfo.category`` is the venue's ``category_id`` as a string
      (see ``mappers.parse_symbols_detail``), so the comparison is string-vs-string.
    """

    symbol_info: Optional[SymbolInfo]
    account_active: bool
    runtime_mode: _config.RuntimeMode
    open_positions: list[Position] = field(default_factory=list)
    account_assets: Optional[AccountAssets] = None
    us_stock_category_id: int = _config.US_STOCK_CATEGORY_ID


# --------------------------------------------------------------------------- #
# Predicate helpers (each returns a RejectionReason | None; pure, no mutation).
# --------------------------------------------------------------------------- #


def _check_account_active(intent: OrderIntent, ctx: ValidationContext) -> Optional[RejectionReason]:
    """1. Account active (Req 1.10) — inactive account rejects ALL order/close ops."""
    if not ctx.account_active:
        return RejectionReason(
            code=RejectionCode.INACTIVE_ACCOUNT,
            message=(
                "TradFi account is not active; activate the account before any "
                "order or close operation (Req 1.10)."
            ),
        )
    return None


def _check_symbol_present(intent: OrderIntent, ctx: ValidationContext) -> Optional[RejectionReason]:
    """2. Symbol present in the validated set (Req 4.3) — unknown symbol rejects.

    ``symbol_info is None`` means the symbol_cache did not resolve the ticker to a
    tradable, in-category symbol. Every later predicate dereferences
    ``ctx.symbol_info``, so this gate must precede them.
    """
    if ctx.symbol_info is None:
        return RejectionReason(
            code=RejectionCode.UNKNOWN_SYMBOL,
            message=(
                f"symbol {intent.symbol!r} is not in the validated tradable set "
                "(Req 4.3)."
            ),
        )
    return None


def _check_category(intent: OrderIntent, ctx: ValidationContext) -> Optional[RejectionReason]:
    """3. Category is US-stock (Req 4.2) — out-of-category rejects.

    ``SymbolInfo.category`` is the venue ``category_id`` AS A STRING (mappers
    stringify it); compare against the in-scope category id as a string.
    """
    info = ctx.symbol_info
    assert info is not None  # step 2 proved presence
    if info.category != str(ctx.us_stock_category_id):
        return RejectionReason(
            code=RejectionCode.OUT_OF_CATEGORY,
            message=(
                f"symbol {intent.symbol!r} category {info.category!r} is outside the "
                f"in-scope US-stock CFD category {ctx.us_stock_category_id} (Req 4.2)."
            ),
        )
    return None


def _check_tradable(intent: OrderIntent, ctx: ValidationContext) -> Optional[RejectionReason]:
    """4. Tradable: not disabled AND not a sub-floor-leverage name (Req 5.1).

    Rejects (a) ``trade_mode == 0`` (disabled) and (b) any name whose per-symbol
    leverage is strictly BELOW ``PRODUCT_LEVERAGE_FLOOR`` (the 6 @ 3.33x sub-floor
    names). Both are structurally untradeable irrespective of the requested action,
    so this gate precedes the action-specific trade_mode gate (step 5).
    """
    info = ctx.symbol_info
    assert info is not None  # step 2 proved presence

    if info.trade_mode == _TRADE_MODE_DISABLED:
        return RejectionReason(
            code=RejectionCode.UNTRADABLE,
            message=(
                f"symbol {intent.symbol!r} is disabled (trade_mode=0); untradeable "
                "(Req 5.1)."
            ),
        )

    if info.leverage < PRODUCT_LEVERAGE_FLOOR - _LEVERAGE_EPSILON:
        return RejectionReason(
            code=RejectionCode.UNTRADABLE,
            message=(
                f"symbol {intent.symbol!r} leverage {info.leverage}x is below the "
                f"product floor {PRODUCT_LEVERAGE_FLOOR}x (sub-floor name; "
                "untradeable per Req 5.1)."
            ),
        )
    return None


def _check_trade_mode_and_position(
    intent: OrderIntent, ctx: ValidationContext
) -> Optional[RejectionReason]:
    """5. trade_mode allows the requested action (Req 1.11) + TRIM/SELL position
    exists (Req 1.8).

    Decision -> action semantics (reference P9 table + "Critical enums"):
        - BUY  = an OPEN (long entry = buy-to-open side 2; short entry =
                 sell-to-open side 1). An open is allowed only under FULL (4),
                 LONG_ONLY (1) for a LONG entry, or SHORT_ONLY (2) for a SHORT
                 entry. CLOSE_ONLY (3) rejects any open.
        - TRIM / SELL = a CLOSE (partial / full). A close is allowed under FULL,
                 LONG_ONLY, SHORT_ONLY, AND CLOSE_ONLY (closing is never blocked by
                 a directional / close-only mode; only DISABLED blocks it, handled
                 in step 4). For a close, the target position must EXIST (Req 1.8) —
                 a TRIM/SELL with no matching open position rejects NO_POSITION and
                 NEVER opens a new position.

    HOLD never reaches here: ``core`` short-circuits HOLD to a no-op upstream (Req
    1.4); if a HOLD intent were passed it carries no action and is left to pass
    through (the order-type / volume gates also have nothing to reject for it).
    """
    info = ctx.symbol_info
    assert info is not None  # step 2 proved presence
    mode = info.trade_mode

    if intent.decision is Label.BUY:
        # An OPEN. Disallowed under close-only; under long/short-only only the
        # matching direction may open.
        if mode == _TRADE_MODE_CLOSE_ONLY:
            return RejectionReason(
                code=RejectionCode.TRADE_MODE_BLOCKED,
                message=(
                    f"symbol {intent.symbol!r} is close-only (trade_mode=3); a BUY "
                    "(open) is not allowed (Req 1.11)."
                ),
            )
        if mode == _TRADE_MODE_LONG_ONLY and intent.direction is Direction.SHORT:
            return RejectionReason(
                code=RejectionCode.TRADE_MODE_BLOCKED,
                message=(
                    f"symbol {intent.symbol!r} is long-only (trade_mode=1); a SHORT "
                    "entry (sell-to-open) is not allowed (Req 1.11)."
                ),
            )
        if mode == _TRADE_MODE_SHORT_ONLY and intent.direction is Direction.LONG:
            return RejectionReason(
                code=RejectionCode.TRADE_MODE_BLOCKED,
                message=(
                    f"symbol {intent.symbol!r} is short-only (trade_mode=2); a LONG "
                    "entry (buy-to-open) is not allowed (Req 1.11)."
                ),
            )
        return None

    if intent.decision in (Label.TRIM, Label.SELL):
        # A CLOSE. Permitted under every non-disabled mode (disabled rejected in
        # step 4). Req 1.8: the target position must exist; never open on a miss.
        if not _position_exists(intent, ctx):
            return RejectionReason(
                code=RejectionCode.NO_POSITION,
                message=(
                    f"{intent.decision.value} references no open position for symbol "
                    f"{intent.symbol!r} (position_id={intent.position_id!r}); rejected "
                    "without opening a new position (Req 1.8)."
                ),
            )
        return None

    # HOLD (or any non-action decision): no trade-mode / position constraint applies.
    return None


def _position_exists(intent: OrderIntent, ctx: ValidationContext) -> bool:
    """Req 1.8 / 1.9 — does the caller-identified open position exist in the snapshot?

    When the caller supplied a ``position_id`` (Req 1.9 — the caller owns selection
    among same-symbol multiples), the match is by id. When no ``position_id`` is
    supplied, fall back to a symbol match so a TRIM/SELL with no position of that
    symbol still rejects. Either way: NO matching open position -> close is illegal.
    """
    if intent.position_id is not None:
        return any(p.position_id == intent.position_id for p in ctx.open_positions)
    return any(p.symbol == intent.symbol for p in ctx.open_positions)


def _check_order_type(intent: OrderIntent, ctx: ValidationContext) -> Optional[RejectionReason]:
    """6. Order type is MARKET or TRIGGER, with a ``trigger_price`` PRESENT when
    TRIGGER (Req 1.5) — else reject.

    ``OrderType`` is a closed enum (MARKET | TRIGGER), so the type is structurally
    constrained; the live gate here is the TRIGGER -> trigger_price requirement. (A
    TRIGGER without an activation price is an incomplete request, not a silent
    fill-at-market — reject, never substitute.)
    """
    if intent.order_type is OrderType.TRIGGER and intent.trigger_price is None:
        return RejectionReason(
            code=RejectionCode.BAD_ORDER_TYPE,
            message=(
                "TRIGGER order requires a trigger_price; none supplied (Req 1.5)."
            ),
        )
    return None


def _check_volume(intent: OrderIntent, ctx: ValidationContext) -> Optional[RejectionReason]:
    """7. Volume within [min_order_volume, max_order_volume] (Req 1.6).

    Below min or above max (the venue max IS the observed ~100-lot cap — read live
    from ``SymbolInfo.max_order_volume``, never hardcoded) rejects REGARDLESS of
    available margin. This gate applies to actions that carry a volume:

        - BUY: ``volume`` is the open size — required and bounds-checked.
        - TRIM: ``volume`` is the partial close size — bounds-checked when present.
        - SELL: a full close carries ``volume=None`` (venue null = full) — nothing
          to bounds-check, so a None volume on a close passes this gate.

    A missing volume where one is REQUIRED (BUY) is out of bounds (cannot be within
    [min, max]); reject rather than transmit a sizeless open.
    """
    info = ctx.symbol_info
    assert info is not None  # step 2 proved presence

    if intent.decision is Label.SELL and intent.volume is None:
        # Full close: no volume to bound (venue treats null close_volume as full).
        return None

    if intent.volume is None:
        # BUY/TRIM with no volume cannot satisfy [min, max] — reject, never default.
        return RejectionReason(
            code=RejectionCode.VOLUME_OUT_OF_BOUNDS,
            message=(
                f"{intent.decision.value} requires a volume within "
                f"[{info.min_order_volume}, {info.max_order_volume}]; none supplied "
                "(Req 1.6)."
            ),
        )

    if intent.volume < info.min_order_volume or intent.volume > info.max_order_volume:
        return RejectionReason(
            code=RejectionCode.VOLUME_OUT_OF_BOUNDS,
            message=(
                f"volume {intent.volume} is outside the venue bounds "
                f"[{info.min_order_volume}, {info.max_order_volume}] for "
                f"{intent.symbol!r} (Req 1.6; checked regardless of margin)."
            ),
        )
    return None


def _check_session_open(intent: OrderIntent, ctx: ValidationContext) -> Optional[RejectionReason]:
    """8. Session open (Req 6.1) — a closed session rejects and reports next_open_time.

    v0.1 holds no order-queuing state, so a closed session is ALWAYS a rejection
    (design Req 6.1). The ``next_open_time`` is carried onto the RejectionReason so
    the caller can surface "when does it reopen" (it is the only code that populates
    that field — see ``models.RejectionReason``).
    """
    info = ctx.symbol_info
    assert info is not None  # step 2 proved presence
    if info.status != _STATUS_OPEN:
        return RejectionReason(
            code=RejectionCode.MARKET_CLOSED,
            message=(
                f"symbol {intent.symbol!r} session is {info.status!r} (not open); "
                "rejected without transmitting (Req 6.1; v0.1 queues nothing)."
            ),
            next_open_time=info.next_open_time,
        )
    return None


def _check_live_send(intent: OrderIntent, ctx: ValidationContext) -> Optional[RejectionReason]:
    """9. Live-send clearances when live (Req 8.3) — else reject LIVE_SEND_BLOCKED.

    When paper/dry-run is ON (the v0.1 default) this gate PASSES: paper never
    transmits live, so the live clearances are not required (the paper simulator
    runs the identical validation + mapping path). When paper is explicitly
    disabled, ALL FOUR Req 8.3 conditions must hold simultaneously
    (``RuntimeMode.live_transmit_allowed()``): paper off AND account active AND
    survival clearance present AND kill switch clear. Any one absent -> refuse.

    Note: ``live_transmit_allowed()`` already includes the account-active condition;
    step 1 (1.10) is the earlier, independent account gate and the two agree.
    """
    rm = ctx.runtime_mode
    if rm.paper_enabled:
        # Paper mode: no live transmit happens, so live clearances are not required.
        return None
    if not rm.live_transmit_allowed():
        return RejectionReason(
            code=RejectionCode.LIVE_SEND_BLOCKED,
            message=(
                "live transmit refused: requires paper disabled AND account active "
                "AND survival-gate clearance present AND kill switch clear; one or "
                "more clearances absent (Req 8.3/8.4/8.5)."
            ),
        )
    return None


# --------------------------------------------------------------------------- #
# The locked predicate chain (order is load-bearing — asserted by test).
# --------------------------------------------------------------------------- #

# Each entry is (predicate). The list ORDER IS the chain order: ``evaluate`` runs
# them top-to-bottom and short-circuits on the first non-None reason. Reordering
# this tuple changes the contract — a test asserts it.
_CHAIN: tuple[Callable[[OrderIntent, ValidationContext], Optional[RejectionReason]], ...] = (
    _check_account_active,          # 1  Req 1.10  INACTIVE_ACCOUNT
    _check_symbol_present,          # 2  Req 4.3   UNKNOWN_SYMBOL
    _check_category,                # 3  Req 4.2   OUT_OF_CATEGORY
    _check_tradable,                # 4  Req 5.1   UNTRADABLE
    _check_trade_mode_and_position, # 5  Req 1.11 + 1.8  TRADE_MODE_BLOCKED / NO_POSITION
    _check_order_type,              # 6  Req 1.5   BAD_ORDER_TYPE
    _check_volume,                  # 7  Req 1.6   VOLUME_OUT_OF_BOUNDS
    _check_session_open,            # 8  Req 6.1   MARKET_CLOSED (+ next_open_time)
    _check_live_send,               # 9  Req 8.3   LIVE_SEND_BLOCKED
)


def evaluate(intent: OrderIntent, ctx: ValidationContext) -> Optional[RejectionReason]:
    """Run the ordered, reject-only validation chain (design "validation" Service
    Interface).

    Returns ``None`` when every predicate passes (the request may transmit /
    simulate). Otherwise returns the FIRST failing :class:`models.RejectionReason`
    (short-circuit — later predicates are not evaluated). Pure + deterministic:
    no I/O, and the input ``intent`` is NEVER mutated (Req 7.1, 7.2) — the only
    outcomes are pass-through (``None``) or a structured rejection.
    """
    for predicate in _CHAIN:
        reason = predicate(intent, ctx)
        if reason is not None:
            return reason
    return None


__all__ = [
    "ValidationContext",
    "evaluate",
    "PRODUCT_LEVERAGE_FLOOR",
]
