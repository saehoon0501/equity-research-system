"""Unit tests for the pure venue<->domain mappers (Task 2.2).

Covers the design "mappers" component (Domain layer) — pure functions only, no
I/O, no transport. Requirements: 1.1, 1.2, 1.3, 1.9, 2.2, 3.2, 5.2, 5.3, 10.2,
10.3.

What the mappers own (per design "symbol_cache & mappers (summary)" + the P9
vocabulary->endpoint table in ``gate-tradfi-api-reference.md``):

- Decision (``Label``) + ``Direction`` -> the venue order ACTION:
  * BUY + LONG  -> buy-to-open,  ``side`` = 2
  * BUY + SHORT -> sell-to-open, ``side`` = 1   (side enum 1=SELL/2=BUY ⚠ guard)
  * TRIM        -> position-close with a PARTIAL ``close_volume``
  * SELL        -> position-close FULL (``close_volume`` null)
  The order-request builder carries NO per-order leverage parameter (Req 5.2).
  TRIM/SELL act on the CALLER-supplied ``position_id`` (Req 1.9) — the mapper
  never selects among same-symbol positions.

- Used-margin / exposure (Req 5.3): notional / per-symbol leverage, where
  notional = volume x contract_volume (contract size) x price.

- Raw venue JSON (STRING numerics) -> typed readouts:
  * ``positions`` -> ``Position`` (venue ``unrealized_pnl`` reported VERBATIM —
    never a self-computed mark, Req 2.2).
  * ``users/assets`` + ``mt5-account`` -> ``AccountAssets`` exposing
    ``stop_out_level`` and NO derived liquidation distance (Req 3.2).
  * ``symbols/detail`` -> ``SymbolInfo``.
  * ``orders/history`` + ``positions/history`` -> ``HistoryRecord`` with
    ``close_reason`` flagging normal vs forced liquidation from
    ``position_status`` = 2 / ``order_opt_type`` 5|6 (Req 10.2), reporting venue
    values verbatim with no substitution (Req 10.3).

Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \\
        tests/unit/mcp/test_broker_mappers.py -q

The broker runs in its own uv venv (carries ``mcp`` / ``httpx``); the repo root is
NOT on ``sys.path``. This test loads ``mappers.py`` and the 1.4 mock/fixture helper
by path (importlib-by-path, under unique module aliases) to avoid module-name
collisions, mirroring ``test_broker_gate_client.py`` / ``test_broker_models.py``.
Inputs are driven from the Task 1.4 recorded fixtures (``tests/fixtures/gate/``).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Repo root: tests/unit/mcp/test_broker_mappers.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"
# mappers does a by-name sibling import (`from models import ...`) — exactly the
# production posture (`python server.py` runs with the broker dir on sys.path[0]).
# The broker uv venv does NOT put the broker dir on sys.path, so seed it here so
# the sibling import resolves (mirrors how server.py would be launched).
if str(_BROKER_DIR) not in sys.path:
    sys.path.insert(0, str(_BROKER_DIR))


def _load_by_path(alias: str, path: Path):
    spec = importlib.util.spec_from_file_location(alias, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


# The 1.4 mock transport + fixture loader (we use only its fixture loader here).
_FAKES_PATH = _REPO_ROOT / "tests" / "unit" / "mcp" / "broker_gate_fakes.py"
broker_gate_fakes = _load_by_path("broker_gate_fakes", _FAKES_PATH)

# Load the domain types FIRST, under the canonical name ``models`` — the same name
# the production ``mappers`` module imports them by (``from models import ...``).
# Loading under this exact alias means the mapper's ``import models`` resolves to
# THIS module instance (it is already in ``sys.modules``), so the enum / dataclass
# objects the mapper builds with are IDENTICAL to the ones the test asserts against
# (one canonical set, exactly as under the real ``python server.py`` launch). If
# we loaded models under a different alias, identity comparisons (``is Direction``,
# ``isinstance(..., Position)``) would spuriously fail across two class objects.
broker_models = _load_by_path("models", _BROKER_DIR / "models.py")

# The unit-under-test (its ``from models import ...`` now reuses the instance above).
mappers = _load_by_path("broker_mappers", _BROKER_DIR / "mappers.py")

Direction = broker_models.Direction
OrderType = broker_models.OrderType
Label = broker_models.Label
Position = broker_models.Position
AccountAssets = broker_models.AccountAssets
SymbolInfo = broker_models.SymbolInfo
HistoryRecord = broker_models.HistoryRecord
OrderIntent = broker_models.OrderIntent

load_fixture = broker_gate_fakes.load_fixture


# --------------------------------------------------------------------------- #
# Purity guard — the mappers layer does no I/O / no transport construction.
# --------------------------------------------------------------------------- #


def test_mappers_module_imports_no_transport():
    """mappers is a pure domain layer (depends only on models) — it must not pull
    httpx / the gate_client transport into its namespace (design: 'validation /
    paper / mappers must stay free of transport-construction side effects')."""
    assert not hasattr(mappers, "httpx"), "mappers must not import httpx"
    assert not hasattr(mappers, "gate_client"), "mappers must not import gate_client"


# --------------------------------------------------------------------------- #
# Decision + direction -> venue order action (Req 1.1, side enum guard).
# --------------------------------------------------------------------------- #


def test_buy_long_maps_to_buy_to_open_side_2():
    intent = OrderIntent(
        decision=Label.BUY, symbol="AAPL", direction=Direction.LONG, volume=1.0
    )
    action = mappers.map_decision_to_action(intent)
    assert action.endpoint == "/tradfi/orders"
    assert action.method == "POST"
    # ⚠ side enum 1=SELL / 2=BUY: long entry = buy-to-open = side 2.
    assert action.body["side"] == 2
    assert action.body["symbol"] == "AAPL"
    assert action.body["volume"] == 1.0


def test_buy_short_maps_to_sell_to_open_side_1():
    intent = OrderIntent(
        decision=Label.BUY, symbol="MSFT", direction=Direction.SHORT, volume=0.5
    )
    action = mappers.map_decision_to_action(intent)
    assert action.endpoint == "/tradfi/orders"
    assert action.method == "POST"
    # ⚠ side enum 1=SELL / 2=BUY: short entry = sell-to-open = side 1.
    assert action.body["side"] == 1
    assert action.body["volume"] == 0.5


def test_trim_maps_to_partial_position_close_by_position_id():
    intent = OrderIntent(
        decision=Label.TRIM,
        symbol="AAPL",
        direction=Direction.LONG,
        volume=0.25,
        position_id="POS-500001",
    )
    action = mappers.map_decision_to_action(intent)
    # close-by-position-id endpoint, caller-supplied id verbatim (Req 1.9).
    assert action.endpoint == "/tradfi/positions/POS-500001/close"
    assert action.method == "POST"
    # TRIM = PARTIAL close: close_volume is the caller volume, not null.
    assert action.body["close_volume"] == 0.25
    assert action.body["close_volume"] is not None


def test_sell_maps_to_full_position_close_close_volume_null():
    intent = OrderIntent(
        decision=Label.SELL,
        symbol="AAPL",
        direction=Direction.LONG,
        position_id="POS-500001",
    )
    action = mappers.map_decision_to_action(intent)
    assert action.endpoint == "/tradfi/positions/POS-500001/close"
    assert action.method == "POST"
    # SELL = FULL close: close_volume null/None signals full per the venue.
    assert action.body["close_volume"] is None


def test_trim_sell_use_caller_supplied_position_id_verbatim():
    """Req 1.9: the mapper acts ONLY on the caller-supplied position_id and never
    selects among same-symbol positions."""
    for pid in ("POS-500001", "POS-500002"):
        intent = OrderIntent(
            decision=Label.SELL,
            symbol="AAPL",
            direction=Direction.LONG,
            position_id=pid,
        )
        action = mappers.map_decision_to_action(intent)
        assert pid in action.endpoint


def test_order_request_carries_no_per_order_leverage(
):
    """Req 5.2: the venue order request has NO leverage parameter — exposure is
    controlled via volume only. The builder must not emit 'leverage' on any path."""
    for direction in (Direction.LONG, Direction.SHORT):
        intent = OrderIntent(
            decision=Label.BUY, symbol="AAPL", direction=direction, volume=1.0
        )
        action = mappers.map_decision_to_action(intent)
        assert "leverage" not in action.body


def test_buy_market_vs_trigger_price_type_and_trigger_price():
    market = OrderIntent(
        decision=Label.BUY, symbol="AAPL", direction=Direction.LONG, volume=1.0,
        order_type=OrderType.MARKET,
    )
    trigger = OrderIntent(
        decision=Label.BUY, symbol="AAPL", direction=Direction.LONG, volume=1.0,
        order_type=OrderType.TRIGGER, trigger_price=205.5,
    )
    m = mappers.map_decision_to_action(market)
    t = mappers.map_decision_to_action(trigger)
    assert m.body["price_type"] == "market"
    assert t.body["price_type"] == "trigger"
    # trigger price carried into the request price field for a trigger order.
    assert t.body.get("price") == 205.5
    # still no leverage on either path.
    assert "leverage" not in m.body and "leverage" not in t.body


# --------------------------------------------------------------------------- #
# Used-margin / exposure = notional / leverage (Req 5.3).
# --------------------------------------------------------------------------- #


def test_used_margin_is_notional_over_leverage_known_vector():
    # notional = volume * contract_volume * price; used_margin = notional / lev.
    # 2.0 contracts * 1 contract size * 200.0 price / 5x leverage = 80.0.
    used = mappers.compute_used_margin(
        volume=2.0, contract_volume=1.0, price=200.0, leverage=5.0
    )
    assert used == pytest.approx(80.0)


def test_used_margin_scales_with_contract_size():
    # contract_volume (contract size) participates in the notional.
    used = mappers.compute_used_margin(
        volume=1.0, contract_volume=10.0, price=50.0, leverage=5.0
    )
    # notional = 1 * 10 * 50 = 500; / 5 = 100.
    assert used == pytest.approx(100.0)


def test_used_margin_rejects_nonpositive_leverage():
    with pytest.raises(ValueError):
        mappers.compute_used_margin(
            volume=1.0, contract_volume=1.0, price=100.0, leverage=0.0
        )


# --------------------------------------------------------------------------- #
# Raw JSON -> Position (venue uPnL verbatim, Req 2.2; string -> typed).
# --------------------------------------------------------------------------- #


def test_parse_position_parses_strings_and_reports_venue_upnl_verbatim():
    raw = load_fixture("positions.json")
    positions = mappers.parse_positions(raw)
    assert len(positions) == 2
    aapl = positions[0]
    assert isinstance(aapl, Position)
    assert aapl.position_id == "POS-500001"
    assert aapl.symbol == "AAPL"
    assert aapl.direction == Direction.LONG
    # string numerics parsed to typed floats.
    assert aapl.volume == pytest.approx(1.0)
    assert isinstance(aapl.volume, float)
    assert aapl.avg_open_price == pytest.approx(210.36)
    assert aapl.used_margin == pytest.approx(424.80)
    # Req 2.2: venue unrealized_pnl reported VERBATIM (value preserved, no mark).
    assert aapl.unrealized_pnl == pytest.approx(37.20)


def test_parse_position_short_direction_and_negative_upnl_preserved():
    raw = load_fixture("positions.json")
    positions = mappers.parse_positions(raw)
    msft = positions[1]
    assert msft.direction == Direction.SHORT
    # negative venue uPnL preserved verbatim (no self-computed substitution).
    assert msft.unrealized_pnl == pytest.approx(-12.50)


def test_parse_positions_empty_returns_empty_list():
    assert mappers.parse_positions([]) == []


# --------------------------------------------------------------------------- #
# Raw JSON -> AccountAssets: stop_out_level present, NO liq distance (Req 3.2).
# --------------------------------------------------------------------------- #


def test_parse_account_assets_exposes_stop_out_no_liq_distance():
    assets_raw = load_fixture("users_assets.json")
    mt5_raw = load_fixture("users_mt5_account.json")
    assets = mappers.parse_account_assets(assets_raw, mt5_raw)
    assert isinstance(assets, AccountAssets)
    assert assets.equity == pytest.approx(10234.56)
    assert assets.used_margin == pytest.approx(1215.00)
    assert assets.free_margin == pytest.approx(9019.56)
    assert assets.margin_level == pytest.approx(842.10)
    assert assets.balance == pytest.approx(10180.00)
    # Req 3.2: stop_out_level exposed (from mt5-account); NO derived liq distance.
    assert assets.stop_out_level == pytest.approx(50.0)
    # The dataclass carries no liquidation-distance field (3.2 — that math is
    # survival-gate's, not the adapter's).
    field_names = set(AccountAssets.__dataclass_fields__)
    assert not any("liquidation" in f or "liq_distance" in f for f in field_names)


# --------------------------------------------------------------------------- #
# Raw JSON -> SymbolInfo (Req 4.* inputs; string -> typed fields).
# --------------------------------------------------------------------------- #


def test_parse_symbol_info_parses_detail_fields():
    detail = load_fixture("symbols_detail.json")
    infos = mappers.parse_symbols_detail(detail)
    by_ticker = {s.ticker: s for s in infos}
    aapl = by_ticker["AAPL"]
    assert isinstance(aapl, SymbolInfo)
    assert aapl.ticker == "AAPL"
    assert aapl.leverage == pytest.approx(5.0)
    assert aapl.min_order_volume == pytest.approx(0.01)
    assert aapl.max_order_volume == pytest.approx(100.0)
    assert aapl.price_precision == 2
    assert isinstance(aapl.price_precision, int)
    assert aapl.buy_swap_rate == pytest.approx(-0.0021)
    assert aapl.sell_swap_rate == pytest.approx(-0.0008)
    # trade_mode reported verbatim (the venue's encoding); 4 = full trading.
    assert aapl.trade_mode == "4"
    # category from category_id (stocks = 2).
    assert aapl.category == "2"


def test_parse_symbol_info_close_only_mode_preserved():
    detail = load_fixture("symbols_detail.json")
    infos = mappers.parse_symbols_detail(detail)
    tsla = {s.ticker: s for s in infos}["TSLA"]
    # TSLA fixture is trade_mode 3 (close-only), leverage 3x — preserved verbatim.
    assert tsla.trade_mode == "3"
    assert tsla.leverage == pytest.approx(3.0)


# --------------------------------------------------------------------------- #
# Raw JSON -> HistoryRecord (close_reason flag; venue values verbatim, Req 10.*).
# --------------------------------------------------------------------------- #


def test_parse_orders_history_forced_liquidation_flag_from_opt_type():
    raw = load_fixture("orders_history.json")
    records = mappers.parse_orders_history(raw)
    assert len(records) == 4
    # opt_type 2 (buy) / 3 (close long) -> normal.
    assert records[0].close_reason == "normal"
    assert records[1].close_reason == "normal"
    # opt_type 5 (force close long) -> forced_liquidation (Req 10.2).
    assert records[2].close_reason == "forced_liquidation"
    # opt_type 6 (force close short) -> forced_liquidation (Req 10.2).
    assert records[3].close_reason == "forced_liquidation"
    # venue values verbatim (Req 10.3): fill price / volume / realized pnl preserved.
    assert records[2].fill_price == pytest.approx(168.42)
    assert records[2].fill_volume == pytest.approx(2.0)
    assert records[2].realized_pnl == pytest.approx(-310.18)
    assert records[2].kind == "order"


def test_parse_positions_history_forced_liquidation_from_position_status():
    raw = load_fixture("positions_history.json")
    records = mappers.parse_positions_history(raw)
    assert len(records) == 2
    # position_status 1 -> normal close.
    assert records[0].close_reason == "normal"
    assert records[0].realized_pnl == pytest.approx(44.40)
    assert records[0].realized_swap == pytest.approx(-1.26)
    # position_status 2 -> forced liquidation (Req 10.2).
    assert records[1].close_reason == "forced_liquidation"
    # venue values verbatim (Req 10.3) — swap and pnl preserved, not recomputed.
    assert records[1].realized_pnl == pytest.approx(-310.18)
    assert records[1].realized_swap == pytest.approx(-4.80)
    assert records[1].kind == "position"


def test_parse_history_empty_returns_empty_list():
    assert mappers.parse_orders_history([]) == []
    assert mappers.parse_positions_history([]) == []
