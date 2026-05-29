"""Unit tests for the broker domain types (Task 1.2).

Covers the value objects / enums declared in the design "Data Models" section and
the architectural P9 contract that the canonical BUY/HOLD/TRIM/SELL ``Label`` is
IMPORTED from ``src.calibration.scorer`` and re-exported by the broker ``models``
module (never redefined locally).

Remediation note (Task 1.2, reject -> fix): the module under test was renamed
``types.py`` -> ``models.py``. A module named ``types`` shadows the Python stdlib
``types`` module under the production launch posture (``python server.py`` with
the broker dir on ``sys.path[0]``), so sibling production modules could not import
the domain types BY NAME. ``test_production_launch_by_name_import_works`` below
locks that fix by reproducing the real launch posture in a subprocess.

Test-run mechanism (canonical broker pytest command — see task report):
    uv run --directory src/mcp/broker python -m pytest \
        tests/unit/mcp/test_broker_models.py -q

The broker runs in its own uv venv that does NOT have the repo root on
``sys.path``; the module-under-test bootstraps the repo root itself so the bare
``from src.calibration.scorer import Label`` resolves at runtime. This test
loads ``models.py`` by path (importlib-by-path avoids any module-name collisions,
mirroring ``tests/unit/mcp/test_polygon.py``) and also seeds ``sys.path`` with
the repo root for belt-and-suspenders.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from enum import Enum
from pathlib import Path

import pytest

# Repo root: tests/unit/mcp/test_broker_models.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Load the broker models module by path under a unique module name (loading by
# path keeps the test independent of how the broker dir sits on sys.path).
_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"
_MODELS_PATH = _BROKER_DIR / "models.py"
_spec = importlib.util.spec_from_file_location("broker_models", _MODELS_PATH)
assert _spec is not None and _spec.loader is not None
broker_models = importlib.util.module_from_spec(_spec)
sys.modules["broker_models"] = broker_models
_spec.loader.exec_module(broker_models)

Direction = broker_models.Direction
OrderType = broker_models.OrderType
RejectionCode = broker_models.RejectionCode
RejectionReason = broker_models.RejectionReason
OrderIntent = broker_models.OrderIntent
OrderResult = broker_models.OrderResult
Position = broker_models.Position
AccountAssets = broker_models.AccountAssets
SymbolInfo = broker_models.SymbolInfo
HistoryRecord = broker_models.HistoryRecord
Label = broker_models.Label


# --------------------------------------------------------------------------- #
# Production-launch regression — locks the types.py -> models.py rename fix.
#
# The MCP runtime launches the broker as `python server.py` with the broker dir
# on sys.path[0] and WITHOUT PYTHONSAFEPATH. Under that posture a sibling module
# named `types.py` shadowed the stdlib `types` module, so production siblings
# could not import the domain types BY NAME (stdlib `enum` then failed to import
# `MappingProxyType`). This test reproduces the exact launch posture in a
# subprocess and asserts a clean by-name import — the precise thing `types.py`
# could not do, and the regression a future rename-back would re-introduce.
# --------------------------------------------------------------------------- #


def test_production_launch_by_name_import_works():
    """Simulate `python server.py` (broker dir on sys.path[0], no PYTHONSAFEPATH)
    and assert a by-name `from models import ...` resolves cleanly."""
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(_BROKER_DIR)!r}); "
        "from models import OrderIntent, OrderResult, Label; "
        "print('ok')"
    )
    # Strip PYTHONSAFEPATH from the child env so we exercise the real production
    # posture (sys.path[0] = broker dir, local module wins for bare imports).
    import os

    env = {k: v for k, v in os.environ.items() if k != "PYTHONSAFEPATH"}

    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, (
        "by-name production-posture import of broker `models` failed "
        f"(returncode={proc.returncode}); stderr:\n{proc.stderr}"
    )
    assert "ok" in proc.stdout


# --------------------------------------------------------------------------- #
# P9 — Label is imported from the shared scorer module, not redefined locally.
# --------------------------------------------------------------------------- #


def test_label_reexported_is_the_shared_scorer_label():
    """The broker `models.Label` must be the SAME object as scorer.Label (P9)."""
    from src.calibration.scorer import Label as ScorerLabel

    assert Label is ScorerLabel


def test_label_has_exactly_four_members():
    members = {m.name for m in Label}
    assert members == {"BUY", "HOLD", "TRIM", "SELL"}
    assert [m.value for m in Label] == ["BUY", "HOLD", "TRIM", "SELL"]


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


def test_direction_enum_members():
    assert {m.name for m in Direction} == {"LONG", "SHORT"}
    assert issubclass(Direction, Enum)


def test_order_type_enum_members():
    assert {m.name for m in OrderType} == {"MARKET", "TRIGGER"}
    assert issubclass(OrderType, Enum)


def test_rejection_code_covers_all_design_codes():
    expected = {
        "INACTIVE_ACCOUNT",
        "UNKNOWN_SYMBOL",
        "OUT_OF_CATEGORY",
        "UNTRADABLE",
        "TRADE_MODE_BLOCKED",
        "BAD_ORDER_TYPE",
        "VOLUME_OUT_OF_BOUNDS",
        "MARKET_CLOSED",
        "NO_POSITION",
        "LIVE_SEND_BLOCKED",
    }
    assert {m.name for m in RejectionCode} == expected


# --------------------------------------------------------------------------- #
# Value objects — each instantiates with the design "Data Models" fields.
# --------------------------------------------------------------------------- #


def test_rejection_reason_instantiates_with_optional_next_open_time():
    r = RejectionReason(code=RejectionCode.MARKET_CLOSED, message="closed")
    assert r.code is RejectionCode.MARKET_CLOSED
    assert r.message == "closed"
    assert r.next_open_time is None

    r2 = RejectionReason(
        code=RejectionCode.MARKET_CLOSED, message="closed", next_open_time=1700000000
    )
    assert r2.next_open_time == 1700000000


def test_order_intent_instantiates_with_trigger_price_field():
    intent = OrderIntent(
        decision=Label.BUY,
        symbol="AAPL",
        direction=Direction.LONG,
        volume=1.0,
        position_id=None,
        order_type=OrderType.TRIGGER,
        trigger_price=190.0,
        take_profit=210.0,
        stop_loss=180.0,
    )
    assert intent.decision is Label.BUY
    assert intent.symbol == "AAPL"
    assert intent.direction is Direction.LONG
    assert intent.volume == 1.0
    assert intent.order_type is OrderType.TRIGGER
    # Req 1.5 / design: trigger_price is a field on the intent.
    assert intent.trigger_price == 190.0
    assert intent.take_profit == 210.0
    assert intent.stop_loss == 180.0


def test_order_intent_hold_noop_minimal_shape():
    # Req 1.4 — a HOLD intent needs no volume / position / trigger.
    intent = OrderIntent(
        decision=Label.HOLD,
        symbol="MSFT",
        direction=Direction.LONG,
    )
    assert intent.decision is Label.HOLD
    assert intent.volume is None
    assert intent.position_id is None
    assert intent.trigger_price is None
    assert intent.order_type is OrderType.MARKET  # sensible default


def test_order_result_status_covers_all_design_states():
    for status in ("filled", "simulated", "unconfirmed", "noop", "rejected"):
        res = OrderResult(status=status)
        assert res.status == status

    full = OrderResult(
        status="filled",
        order_id="o-1",
        position_id="p-1",
        fill_price=190.5,
        fill_volume=1.0,
        reason=None,
        raw={"venue": "payload"},
    )
    assert full.order_id == "o-1"
    assert full.position_id == "p-1"
    assert full.fill_price == 190.5
    assert full.fill_volume == 1.0
    assert full.raw == {"venue": "payload"}


def test_order_result_noop_status_for_hold():
    # Req 1.4 — HOLD yields a structured no-op result.
    res = OrderResult(status="noop")
    assert res.status == "noop"


def test_order_result_rejected_carries_reason():
    reason = RejectionReason(code=RejectionCode.NO_POSITION, message="no position")
    res = OrderResult(status="rejected", reason=reason)
    assert res.status == "rejected"
    assert res.reason is reason


def test_position_instantiates_with_venue_supplied_fields():
    pos = Position(
        position_id="p-1",
        symbol="AAPL",
        direction=Direction.LONG,
        volume=2.0,
        avg_open_price=185.0,
        used_margin=74.0,
        unrealized_pnl=11.0,
    )
    assert pos.position_id == "p-1"
    assert pos.direction is Direction.LONG
    assert pos.unrealized_pnl == 11.0


def test_account_assets_exposes_stop_out_level_and_no_liquidation_distance():
    aa = AccountAssets(
        equity=1000.0,
        used_margin=200.0,
        free_margin=800.0,
        margin_level=5.0,
        balance=990.0,
        stop_out_level=0.5,
    )
    assert aa.equity == 1000.0
    assert aa.stop_out_level == 0.5
    # Req 3.2 — the adapter exposes stop-out but NEVER a derived liquidation distance.
    field_names = set(getattr(AccountAssets, "__dataclass_fields__", {}).keys())
    assert "stop_out_level" in field_names
    forbidden = {
        "liquidation_distance",
        "liq_distance",
        "distance_to_liquidation",
        "distance_to_stop_out",
    }
    assert forbidden.isdisjoint(field_names)


def test_symbol_info_instantiates_with_all_metadata_fields():
    si = SymbolInfo(
        ticker="AAPL",
        category="us-stock-cfd",
        leverage=5.0,
        trade_mode="full",
        min_order_volume=0.01,
        max_order_volume=100.0,
        price_precision=2,
        buy_swap_rate=-0.5,
        sell_swap_rate=-0.3,
        status="open",
        next_open_time=None,
    )
    assert si.ticker == "AAPL"
    assert si.leverage == 5.0
    assert si.min_order_volume == 0.01
    assert si.max_order_volume == 100.0
    assert si.buy_swap_rate == -0.5
    assert si.sell_swap_rate == -0.3
    assert si.status == "open"


def test_history_record_close_reason_covers_normal_and_forced_liquidation():
    normal = HistoryRecord(
        kind="position",
        fill_price=190.0,
        fill_volume=1.0,
        realized_pnl=5.0,
        realized_swap=-0.2,
        close_reason="normal",
    )
    assert normal.close_reason == "normal"

    forced = HistoryRecord(
        kind="position",
        fill_price=150.0,
        fill_volume=1.0,
        realized_pnl=-40.0,
        realized_swap=-0.2,
        close_reason="forced_liquidation",
    )
    assert forced.close_reason == "forced_liquidation"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
