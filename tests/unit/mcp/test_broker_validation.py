"""Unit tests for the pre-transmit validation chain (Task 3.2).

Covers the design "Policy layer -> validation (ordered reject-only chain)"
component. Requirements: 1.5, 1.6, 1.8, 1.10, 1.11, 4.2, 4.3, 5.1, 6.1, 7.1, 7.2.

What ``validation`` owns (per design "validation" Responsibilities & Constraints +
the locked predicate order):

    1. account active (Req 1.10) ............ INACTIVE_ACCOUNT
    2. symbol in the validated set (Req 4.3)  UNKNOWN_SYMBOL
    3. category is US-stock (Req 4.2) ....... OUT_OF_CATEGORY
    4. tradable: not disabled / not sub-floor leverage (Req 5.1) UNTRADABLE
    5. trade_mode allows the action (Req 1.11) + TRIM/SELL position exists (Req 1.8)
       TRADE_MODE_BLOCKED / NO_POSITION
    6. order type market/trigger; trigger_price present when TRIGGER (Req 1.5) BAD_ORDER_TYPE
    7. volume within [min, max] incl. the venue cap (Req 1.6) VOLUME_OUT_OF_BOUNDS
    8. session open (Req 6.1) ............... MARKET_CLOSED (+ next_open_time)
    9. live-send clearances when live (Req 8.3) LIVE_SEND_BLOCKED

The chain is PURE (no I/O; the caller populates ``ValidationContext``) and
REJECT-ONLY: the only outcomes are pass-through (``None``) or a structured
``RejectionReason`` — it NEVER mutates / clamps / increases the request (Req
7.1, 7.2).

Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \\
        tests/unit/mcp/test_broker_validation.py -q

The broker runs in its own uv venv (carries ``mcp`` / ``httpx``); the repo root is
NOT on ``sys.path``. This test loads the broker modules by path (importlib-by-path
under unique aliases), loading ``models`` FIRST under its canonical alias so the
dependent modules' ``from models import ...`` reuse the SAME class objects (enum /
isinstance identity holds), mirroring ``test_broker_mappers.py`` /
``test_broker_symbol_cache.py``. This validation test is PURE — it needs no mock
transport and no fixtures (it constructs ``SymbolInfo`` / ``Position`` directly).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

import pytest

# Repo root: tests/unit/mcp/test_broker_validation.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"
# validation does by-name sibling imports (`import config`, `from models import
# ...`) — exactly the production posture (`python server.py` with the broker dir on
# sys.path[0]). The broker uv venv does NOT put the broker dir on sys.path, so seed
# it here so the sibling imports resolve (mirrors how server.py would be launched).
if str(_BROKER_DIR) not in sys.path:
    sys.path.insert(0, str(_BROKER_DIR))


def _load_by_path(alias: str, path: Path):
    spec = importlib.util.spec_from_file_location(alias, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


# LOAD-BEARING ordering (tasks.md Implementation Notes / Task 2.2 note): load
# ``models`` FIRST under its CANONICAL alias so every dependent module's
# ``from models import ...`` reuses THIS instance (one canonical set of
# classes/enums -> isinstance/identity holds). Then config, then the unit-under-test.
broker_models = _load_by_path("models", _BROKER_DIR / "models.py")
broker_config = _load_by_path("config", _BROKER_DIR / "config.py")
validation = _load_by_path("broker_validation", _BROKER_DIR / "validation.py")

Label = broker_models.Label
Direction = broker_models.Direction
OrderType = broker_models.OrderType
OrderIntent = broker_models.OrderIntent
RejectionCode = broker_models.RejectionCode
RejectionReason = broker_models.RejectionReason
SymbolInfo = broker_models.SymbolInfo
Position = broker_models.Position
AccountAssets = broker_models.AccountAssets
RuntimeMode = broker_config.RuntimeMode
US_STOCK_CATEGORY_ID = broker_config.US_STOCK_CATEGORY_ID

ValidationContext = validation.ValidationContext
evaluate = validation.evaluate
PRODUCT_LEVERAGE_FLOOR = validation.PRODUCT_LEVERAGE_FLOOR


# --------------------------------------------------------------------------- #
# Builders — a "clean pass" baseline; each test perturbs ONE thing so a removed
# predicate would let that perturbation slip through (meaningful tests).
# --------------------------------------------------------------------------- #


def _symbol(
    *,
    ticker: str = "AAPL",
    category: str | None = None,
    leverage: float = 5.0,
    trade_mode: str = "4",          # 4 = full trading
    min_order_volume: float = 1.0,
    max_order_volume: float = 100.0,  # the observed ~100-lot venue cap (Req 1.6)
    status: str = "open",
    next_open_time: int | None = None,
) -> "SymbolInfo":
    return SymbolInfo(
        ticker=ticker,
        category=str(US_STOCK_CATEGORY_ID) if category is None else category,
        leverage=leverage,
        trade_mode=trade_mode,
        min_order_volume=min_order_volume,
        max_order_volume=max_order_volume,
        price_precision=2,
        buy_swap_rate=0.0,
        sell_swap_rate=0.0,
        status=status,
        next_open_time=next_open_time,
    )


def _position(*, position_id: str = "pos-1", symbol: str = "AAPL", direction=None) -> "Position":
    return Position(
        position_id=position_id,
        symbol=symbol,
        direction=direction or Direction.LONG,
        volume=10.0,
        avg_open_price=100.0,
        used_margin=200.0,
        unrealized_pnl=0.0,
    )


# Sentinel distinguishing "not provided" (use a default symbol) from an explicit
# ``symbol_info=None`` (the unknown-symbol case the test must be able to express).
_UNSET = object()


def _ctx(
    *,
    symbol_info=_UNSET,
    account_active: bool = True,
    runtime_mode=None,
    open_positions=None,
) -> "ValidationContext":
    return ValidationContext(
        symbol_info=_symbol() if symbol_info is _UNSET else symbol_info,
        account_active=account_active,
        runtime_mode=runtime_mode if runtime_mode is not None else RuntimeMode(),  # paper-on default
        open_positions=[] if open_positions is None else open_positions,
    )


def _buy_intent(*, direction=None, volume: float | None = 10.0, **kw) -> "OrderIntent":
    return OrderIntent(
        decision=Label.BUY,
        symbol="AAPL",
        direction=direction or Direction.LONG,
        volume=volume,
        **kw,
    )


def _trim_intent(*, position_id: str | None = "pos-1", volume: float | None = 5.0) -> "OrderIntent":
    return OrderIntent(
        decision=Label.TRIM,
        symbol="AAPL",
        direction=Direction.LONG,
        volume=volume,
        position_id=position_id,
    )


def _sell_intent(*, position_id: str | None = "pos-1") -> "OrderIntent":
    return OrderIntent(
        decision=Label.SELL,
        symbol="AAPL",
        direction=Direction.LONG,
        volume=None,  # full close = null volume
        position_id=position_id,
    )


# --------------------------------------------------------------------------- #
# Clean pass.
# --------------------------------------------------------------------------- #


def test_clean_buy_passes_returns_none():
    """A fully-valid BUY on an active account, in-category, tradable, full-trading,
    market order, in-bounds volume, open session, paper mode -> None (pass)."""
    assert evaluate(_buy_intent(), _ctx()) is None


def test_clean_trigger_with_price_passes():
    intent = _buy_intent(order_type=OrderType.TRIGGER, trigger_price=123.45)
    assert evaluate(intent, _ctx()) is None


def test_clean_trim_with_existing_position_passes():
    ctx = _ctx(open_positions=[_position(position_id="pos-1")])
    assert evaluate(_trim_intent(position_id="pos-1"), ctx) is None


def test_clean_sell_with_existing_position_passes():
    ctx = _ctx(open_positions=[_position(position_id="pos-1")])
    assert evaluate(_sell_intent(position_id="pos-1"), ctx) is None


# --------------------------------------------------------------------------- #
# 1. account active (Req 1.10).
# --------------------------------------------------------------------------- #


def test_inactive_account_rejects_buy():
    reason = evaluate(_buy_intent(), _ctx(account_active=False))
    assert reason is not None
    assert reason.code is RejectionCode.INACTIVE_ACCOUNT


def test_inactive_account_rejects_close_too():
    """Inactive account rejects ALL order/close ops (Req 1.10), TRIM included."""
    ctx = _ctx(account_active=False, open_positions=[_position()])
    reason = evaluate(_trim_intent(), ctx)
    assert reason is not None and reason.code is RejectionCode.INACTIVE_ACCOUNT


# --------------------------------------------------------------------------- #
# 2. symbol present (Req 4.3).
# --------------------------------------------------------------------------- #


def test_unknown_symbol_rejects():
    reason = evaluate(_buy_intent(), _ctx(symbol_info=None))
    assert reason is not None and reason.code is RejectionCode.UNKNOWN_SYMBOL


# --------------------------------------------------------------------------- #
# 3. category (Req 4.2).
# --------------------------------------------------------------------------- #


def test_out_of_category_rejects():
    # category "9" is not the US-stock category (str(2)).
    reason = evaluate(_buy_intent(), _ctx(symbol_info=_symbol(category="9")))
    assert reason is not None and reason.code is RejectionCode.OUT_OF_CATEGORY


# --------------------------------------------------------------------------- #
# 4. tradable: disabled / sub-floor leverage (Req 5.1).
# --------------------------------------------------------------------------- #


def test_disabled_trade_mode_rejects_untradable():
    reason = evaluate(_buy_intent(), _ctx(symbol_info=_symbol(trade_mode="0")))
    assert reason is not None and reason.code is RejectionCode.UNTRADABLE


def test_sub_floor_leverage_rejects_untradable():
    # 3.33x sits below the 4x product floor -> sub-floor name (Req 5.1).
    reason = evaluate(_buy_intent(), _ctx(symbol_info=_symbol(leverage=3.33)))
    assert reason is not None and reason.code is RejectionCode.UNTRADABLE


def test_at_floor_leverage_is_tradable():
    # Exactly at the 4x floor is tradable (boundary — not sub-floor).
    assert evaluate(_buy_intent(), _ctx(symbol_info=_symbol(leverage=4.0))) is None


def test_product_leverage_floor_constant_is_four():
    # The floor is an EXPLICIT spec-sourced constant (gate-api-gaps.md: 4x product
    # min-order-leverage floor; 6 names @ 3.33x are sub-floor), not a magic literal.
    assert PRODUCT_LEVERAGE_FLOOR == 4.0


# --------------------------------------------------------------------------- #
# 5. trade_mode allows the action (Req 1.11) for EACH mode.
# --------------------------------------------------------------------------- #


def test_long_only_rejects_short_entry():
    # trade_mode 1 = long only; a BUY-SHORT (sell-to-open) is disallowed.
    intent = _buy_intent(direction=Direction.SHORT)
    reason = evaluate(intent, _ctx(symbol_info=_symbol(trade_mode="1")))
    assert reason is not None and reason.code is RejectionCode.TRADE_MODE_BLOCKED


def test_long_only_allows_long_entry():
    intent = _buy_intent(direction=Direction.LONG)
    assert evaluate(intent, _ctx(symbol_info=_symbol(trade_mode="1"))) is None


def test_short_only_rejects_long_entry():
    intent = _buy_intent(direction=Direction.LONG)
    reason = evaluate(intent, _ctx(symbol_info=_symbol(trade_mode="2")))
    assert reason is not None and reason.code is RejectionCode.TRADE_MODE_BLOCKED


def test_short_only_allows_short_entry():
    intent = _buy_intent(direction=Direction.SHORT)
    assert evaluate(intent, _ctx(symbol_info=_symbol(trade_mode="2"))) is None


def test_close_only_rejects_buy_open():
    # trade_mode 3 = close only; a BUY (open) is disallowed.
    reason = evaluate(_buy_intent(), _ctx(symbol_info=_symbol(trade_mode="3")))
    assert reason is not None and reason.code is RejectionCode.TRADE_MODE_BLOCKED


def test_close_only_allows_trim():
    # TRIM (a close) is allowed under close-only.
    ctx = _ctx(symbol_info=_symbol(trade_mode="3"), open_positions=[_position()])
    assert evaluate(_trim_intent(), ctx) is None


def test_close_only_allows_sell():
    # SELL (a full close) is allowed under close-only.
    ctx = _ctx(symbol_info=_symbol(trade_mode="3"), open_positions=[_position()])
    assert evaluate(_sell_intent(), ctx) is None


# --------------------------------------------------------------------------- #
# 1.8 — TRIM/SELL with no position rejects, never opens a new position.
# --------------------------------------------------------------------------- #


def test_trim_with_no_position_rejects_no_position():
    # No open positions in the snapshot -> NO_POSITION (Req 1.8).
    reason = evaluate(_trim_intent(position_id="pos-1"), _ctx(open_positions=[]))
    assert reason is not None and reason.code is RejectionCode.NO_POSITION


def test_sell_with_no_position_rejects_no_position():
    reason = evaluate(_sell_intent(position_id="pos-1"), _ctx(open_positions=[]))
    assert reason is not None and reason.code is RejectionCode.NO_POSITION


def test_trim_with_wrong_position_id_rejects():
    # The caller-supplied id (Req 1.9) does not match any open position.
    ctx = _ctx(open_positions=[_position(position_id="pos-OTHER")])
    reason = evaluate(_trim_intent(position_id="pos-1"), ctx)
    assert reason is not None and reason.code is RejectionCode.NO_POSITION


# --------------------------------------------------------------------------- #
# 6. order type (Req 1.5).
# --------------------------------------------------------------------------- #


def test_trigger_without_trigger_price_rejects():
    intent = _buy_intent(order_type=OrderType.TRIGGER, trigger_price=None)
    reason = evaluate(intent, _ctx())
    assert reason is not None and reason.code is RejectionCode.BAD_ORDER_TYPE


# --------------------------------------------------------------------------- #
# 7. volume bounds incl. the venue cap (Req 1.6) — regardless of margin.
# --------------------------------------------------------------------------- #


def test_volume_below_min_rejects():
    intent = _buy_intent(volume=0.5)  # below min_order_volume 1.0
    reason = evaluate(intent, _ctx())
    assert reason is not None and reason.code is RejectionCode.VOLUME_OUT_OF_BOUNDS


def test_volume_above_max_rejects():
    intent = _buy_intent(volume=150.0)  # above max_order_volume 100.0
    reason = evaluate(intent, _ctx())
    assert reason is not None and reason.code is RejectionCode.VOLUME_OUT_OF_BOUNDS


def test_volume_above_venue_cap_rejects():
    # The ~100-lot venue cap is read live from max_order_volume; just above it
    # rejects even though margin is never considered (Req 1.6).
    intent = _buy_intent(volume=100.0001)
    reason = evaluate(intent, _ctx(symbol_info=_symbol(max_order_volume=100.0)))
    assert reason is not None and reason.code is RejectionCode.VOLUME_OUT_OF_BOUNDS


def test_buy_with_missing_volume_rejects_out_of_bounds():
    # A sizeless BUY cannot satisfy [min, max]; reject, never default a size.
    reason = evaluate(_buy_intent(volume=None), _ctx())
    assert reason is not None and reason.code is RejectionCode.VOLUME_OUT_OF_BOUNDS


# --------------------------------------------------------------------------- #
# 8. session open (Req 6.1) — populate next_open_time on the rejection.
# --------------------------------------------------------------------------- #


def test_closed_session_rejects_with_next_open_time():
    info = _symbol(status="closed", next_open_time=1_700_000_000)
    reason = evaluate(_buy_intent(), _ctx(symbol_info=info))
    assert reason is not None
    assert reason.code is RejectionCode.MARKET_CLOSED
    assert reason.next_open_time == 1_700_000_000


# --------------------------------------------------------------------------- #
# 9. live-send clearances when live (Req 8.3).
# --------------------------------------------------------------------------- #


def test_live_without_clearance_rejects_live_send_blocked():
    # Paper explicitly disabled but the other clearances absent -> refuse.
    rm = RuntimeMode(
        paper_enabled=False,
        account_active=True,
        survival_clearance=False,   # missing
        kill_switch_clear=False,    # missing
    )
    reason = evaluate(_buy_intent(), _ctx(runtime_mode=rm))
    assert reason is not None and reason.code is RejectionCode.LIVE_SEND_BLOCKED


def test_live_with_all_clearances_passes():
    # All four Req 8.3 conditions hold -> the live gate passes (the rest is clean).
    rm = RuntimeMode(
        paper_enabled=False,
        account_active=True,
        survival_clearance=True,
        kill_switch_clear=True,
    )
    assert evaluate(_buy_intent(), _ctx(runtime_mode=rm)) is None


def test_paper_mode_does_not_require_live_clearances():
    # Default paper mode: the live gate passes without any clearance present.
    rm = RuntimeMode(paper_enabled=True)
    assert evaluate(_buy_intent(), _ctx(runtime_mode=rm)) is None


# --------------------------------------------------------------------------- #
# Ordering / short-circuit on first failure (the chain order is load-bearing).
# --------------------------------------------------------------------------- #


def test_first_failure_short_circuits_account_before_symbol():
    # Both account-inactive (step 1) AND unknown-symbol (step 2) hold; the FIRST
    # failure (account) must win — proves step 1 precedes step 2.
    ctx = _ctx(account_active=False, symbol_info=None)
    reason = evaluate(_buy_intent(), ctx)
    assert reason is not None and reason.code is RejectionCode.INACTIVE_ACCOUNT


def test_symbol_failure_precedes_category():
    # Unknown symbol (step 2) wins over a would-be category failure (step 3) —
    # symbol_info None can't even reach the category dereference.
    reason = evaluate(_buy_intent(), _ctx(symbol_info=None))
    assert reason is not None and reason.code is RejectionCode.UNKNOWN_SYMBOL


def test_category_failure_precedes_tradable():
    # Out-of-category (step 3) AND disabled trade_mode (step 4) both hold; category
    # must win -> step 3 precedes step 4.
    info = _symbol(category="9", trade_mode="0")
    reason = evaluate(_buy_intent(), _ctx(symbol_info=info))
    assert reason is not None and reason.code is RejectionCode.OUT_OF_CATEGORY


def test_tradable_failure_precedes_trade_mode():
    # Sub-floor leverage (step 4) AND close-only mode that would block a BUY (step
    # 5) both hold; UNTRADABLE must win -> step 4 precedes step 5.
    info = _symbol(leverage=3.33, trade_mode="3")
    reason = evaluate(_buy_intent(), _ctx(symbol_info=info))
    assert reason is not None and reason.code is RejectionCode.UNTRADABLE


def test_trade_mode_failure_precedes_order_type():
    # close-only blocks the BUY (step 5) AND a TRIGGER w/o price would fail (step 6);
    # TRADE_MODE_BLOCKED must win -> step 5 precedes step 6.
    intent = _buy_intent(order_type=OrderType.TRIGGER, trigger_price=None)
    reason = evaluate(intent, _ctx(symbol_info=_symbol(trade_mode="3")))
    assert reason is not None and reason.code is RejectionCode.TRADE_MODE_BLOCKED


def test_order_type_failure_precedes_volume():
    # TRIGGER w/o price (step 6) AND out-of-bounds volume (step 7) both hold;
    # BAD_ORDER_TYPE must win -> step 6 precedes step 7.
    intent = _buy_intent(order_type=OrderType.TRIGGER, trigger_price=None, volume=9999.0)
    reason = evaluate(intent, _ctx())
    assert reason is not None and reason.code is RejectionCode.BAD_ORDER_TYPE


def test_volume_failure_precedes_session():
    # Out-of-bounds volume (step 7) AND closed session (step 8) both hold;
    # VOLUME_OUT_OF_BOUNDS must win -> step 7 precedes step 8.
    info = _symbol(status="closed", next_open_time=42)
    intent = _buy_intent(volume=9999.0)
    reason = evaluate(intent, _ctx(symbol_info=info))
    assert reason is not None and reason.code is RejectionCode.VOLUME_OUT_OF_BOUNDS


def test_session_failure_precedes_live_send():
    # Closed session (step 8) AND a live-send that would fail (step 9) both hold;
    # MARKET_CLOSED must win -> step 8 precedes step 9.
    info = _symbol(status="closed", next_open_time=42)
    rm = RuntimeMode(paper_enabled=False, account_active=True)  # would fail live gate
    reason = evaluate(_buy_intent(), _ctx(symbol_info=info, runtime_mode=rm))
    assert reason is not None and reason.code is RejectionCode.MARKET_CLOSED


# --------------------------------------------------------------------------- #
# Never-mutate invariant (Req 7.1, 7.2) — the input intent is unchanged.
# --------------------------------------------------------------------------- #


def test_evaluate_never_mutates_input_intent_on_pass():
    intent = _buy_intent(volume=10.0)
    before = dataclasses.asdict(intent)
    evaluate(intent, _ctx())
    assert dataclasses.asdict(intent) == before


def test_evaluate_never_mutates_input_intent_on_reject():
    # Even an out-of-bounds volume is NOT clamped/modified (Req 7.2) — rejected as-is.
    intent = _buy_intent(volume=9999.0)
    before = dataclasses.asdict(intent)
    reason = evaluate(intent, _ctx())
    assert reason is not None and reason.code is RejectionCode.VOLUME_OUT_OF_BOUNDS
    after = dataclasses.asdict(intent)
    assert after == before
    assert after["volume"] == 9999.0  # explicitly: never reduced to a venue cap


def test_evaluate_returns_rejection_reason_type():
    reason = evaluate(_buy_intent(), _ctx(account_active=False))
    assert isinstance(reason, RejectionReason)


def test_validation_is_pure_no_transport_imports():
    """Lock the design Invariant (Policy layer): validation is PURE — it imports
    only ``models`` + ``config`` (+ stdlib) and NEVER httpx / gate_client /
    symbol_cache. The caller (core) populates ``ValidationContext``; validation
    performs no I/O and does not fetch. A future edit adding a transport/cache
    import must turn this test RED.
    """
    import ast

    source_path = (
        Path(__file__).resolve().parents[3] / "src/mcp/broker/validation.py"
    )
    tree = ast.parse(source_path.read_text())
    imported_top_level: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_top_level.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_top_level.add(node.module.split(".")[0])

    forbidden = {"httpx", "gate_client", "symbol_cache", "requests", "urllib"}
    leaked = imported_top_level & forbidden
    assert not leaked, f"validation must stay pure (no transport/cache); found: {leaked}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
