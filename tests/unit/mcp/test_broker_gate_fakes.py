"""Smoke test for the broker Gate test fixtures + mock venue transport (Task 1.4).

This is the P14 *inner-ring* infrastructure: it makes the broker's leaf functions
unit-testable with NO live venue. Tasks 2.x / 3.x / 4.x / 6.x consume the fixtures
under ``tests/fixtures/gate/`` and the mock transport in
``tests/unit/mcp/broker_gate_fakes.py``.

What this smoke test PROVES (Task 1.4 observable + validation):

1. Every fixture file under ``tests/fixtures/gate/`` is valid JSON and loads.
2. Field names / enum encodings in the fixtures match the operator-supplied
   ``gate-tradfi-api-reference.md`` (numeric/price/volume fields are STRINGS;
   ``side`` 1=SELL/2=BUY; ``trade_mode`` 0-4; ``position_status`` 2=forced
   liquidation; ``order_opt_type`` 5/6=force close; create returns ``data.id``
   queue-task-id, NOT an order/position id).
3. The mock transport returns the canned ``positions`` and ``users/assets``
   payloads for their endpoints (success path).
4. The three failure injections are producible: an auth failure (401), a
   rate-limit (429 carrying ``X-Gate-RateLimit-Requests-Remain`` / ``-Limit`` /
   ``-Reset-Timestamp`` headers), and an unreachable/network error.
5. At least one forced-liquidation history record is present.

Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \\
        tests/unit/mcp/test_broker_gate_fakes.py -q

The broker runs in its own uv venv (carries ``mcp`` / ``httpx``); the repo root is
NOT on ``sys.path``. This test loads the helper by path (importlib-by-path, under a
unique module alias) to avoid module-name collisions, mirroring
``tests/unit/mcp/test_broker_config.py`` / ``test_broker_models.py`` / ``test_polygon.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

# Repo root: tests/unit/mcp/test_broker_gate_fakes.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_FAKES_PATH = _REPO_ROOT / "tests" / "unit" / "mcp" / "broker_gate_fakes.py"
_spec = importlib.util.spec_from_file_location("broker_gate_fakes", _FAKES_PATH)
assert _spec is not None and _spec.loader is not None
broker_gate_fakes = importlib.util.module_from_spec(_spec)
sys.modules["broker_gate_fakes"] = broker_gate_fakes
_spec.loader.exec_module(broker_gate_fakes)

FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures" / "gate"

# Endpoints the adapter reads/writes; each must have a fixture (Task 1.4 list).
EXPECTED_FIXTURE_FILES = {
    "symbols.json",
    "symbols_categories.json",
    "symbols_detail.json",
    "symbol_tickers.json",
    "users_assets.json",
    "users_mt5_account.json",
    "orders.json",
    "orders_create.json",
    "positions.json",
    "position_close.json",
    "orders_history.json",
    "positions_history.json",
}


# --------------------------------------------------------------------------- #
# 1. Every fixture file is valid JSON and loads.
# --------------------------------------------------------------------------- #


def test_fixtures_directory_exists():
    assert FIXTURES_DIR.is_dir(), f"missing fixtures dir: {FIXTURES_DIR}"


def test_all_expected_fixture_files_present():
    present = {p.name for p in FIXTURES_DIR.glob("*.json")}
    missing = EXPECTED_FIXTURE_FILES - present
    assert not missing, f"missing fixture files: {sorted(missing)}"


@pytest.mark.parametrize("name", sorted(EXPECTED_FIXTURE_FILES))
def test_each_fixture_is_valid_json(name):
    path = FIXTURES_DIR / name
    data = json.loads(path.read_text())
    assert data is not None


# --------------------------------------------------------------------------- #
# 2. Field names / enum encodings match the reference doc.
# --------------------------------------------------------------------------- #


def _load(name: str):
    return json.loads((FIXTURES_DIR / name).read_text())


def test_numeric_fields_are_strings():
    """Reference: all numeric monetary/price/volume fields are STRINGS."""
    assets = _load("users_assets.json")
    for key in ("equity", "margin_level", "balance", "margin", "margin_free"):
        assert isinstance(assets[key], str), f"assets.{key} must be a string"

    pos = _load("positions.json")[0]
    for key in ("margin", "unrealized_pnl", "volume", "price_open"):
        assert isinstance(pos[key], str), f"positions[0].{key} must be a string"

    ticker = _load("symbol_tickers.json")
    for key in ("bid_price", "ask_price", "last_price"):
        assert isinstance(ticker[key], str), f"ticker.{key} must be a string"

    detail = _load("symbols_detail.json")[0]
    for key in ("max_order_volume", "min_order_volume", "leverage"):
        assert isinstance(detail[key], str), f"detail[0].{key} must be a string"


def test_side_enum_encoding_present():
    """side: 1 = SELL, 2 = BUY (counterintuitive)."""
    orders = _load("orders.json")
    sides = {o["side"] for o in orders}
    assert sides <= {1, 2}, f"order.side must be 1 (SELL) or 2 (BUY), got {sides}"


def test_trade_mode_in_valid_range():
    """trade_mode: 0=disabled,1=long only,2=short only,3=close only,4=full."""
    for detail in _load("symbols_detail.json"):
        assert detail["trade_mode"] in {0, 1, 2, 3, 4}


def test_account_status_active():
    """account status: 1=not opened, 2=pending review, 3=active."""
    acct = _load("users_mt5_account.json")
    assert acct["status"] in {1, 2, 3}
    assert "stop_out_level" in acct
    assert "leverage" in acct


def test_categories_include_stocks_category_2():
    cats = _load("symbols_categories.json")
    ids = {c["category_id"] for c in cats}
    assert 2 in ids, "stocks must be category 2 per reference §11.3"


def test_create_order_returns_queue_task_id_not_order_id():
    """POST /tradfi/orders returns data.id = Queue Task ID (NOT order/position id)."""
    resp = _load("orders_create.json")
    assert "data" in resp, "create response must wrap the queue-task-id in data"
    assert "id" in resp["data"], "create response data must carry the queue-task-id"
    # The async create response must NOT pretend to be an order/position id.
    assert "order_id" not in resp["data"]
    assert "position_id" not in resp["data"]


def test_position_close_returns_queue_task_id():
    resp = _load("position_close.json")
    assert "data" in resp and "id" in resp["data"]


def test_position_close_request_semantics_documented_in_fixture():
    """close_type (1/2) + close_volume (null=full SELL, partial=TRIM)."""
    resp = _load("position_close.json")
    # The fixture documents the request shape it answers to so 2.2 / 4.x can key on it.
    req = resp.get("request", {})
    assert req.get("close_type") in {1, 2}
    assert "close_volume" in req  # may be null (full close) per reference


def test_positions_history_has_forced_liquidation_record():
    """position_status: 1=fully closed, 2=forced liquidation. >=1 forced record."""
    hist = _load("positions_history.json")
    forced = [r for r in hist if r.get("position_status") == 2]
    assert forced, "need >=1 forced-liquidation (position_status=2) record"
    rec = forced[0]
    for key in ("realized_pnl", "swap", "close_price", "stop_out_level"):
        assert key in rec, f"forced record missing {key}"


def test_orders_history_force_close_opt_types_present():
    """order_opt_type: 5=force close long, 6=force close short (liquidation)."""
    hist = _load("orders_history.json")
    opt_types = {r["order_opt_type"] for r in hist}
    assert opt_types & {5, 6}, "need a force-close (5/6) order-history record"


def test_symbols_detail_is_multi_symbol_batch():
    detail = _load("symbols_detail.json")
    assert isinstance(detail, list) and len(detail) >= 2, "need a multi-symbol batch"


# --------------------------------------------------------------------------- #
# 3. Mock transport returns the canned success payloads for their endpoints.
# --------------------------------------------------------------------------- #


def test_mock_returns_canned_positions_payload():
    transport = broker_gate_fakes.make_mock_transport()
    client = httpx.Client(transport=transport, base_url="https://api.gateio.ws")
    resp = client.get("/api/v4/tradfi/positions")
    assert resp.status_code == 200
    body = resp.json()
    assert body == _load("positions.json")
    assert body[0]["position_id"] == _load("positions.json")[0]["position_id"]


def test_mock_returns_canned_assets_payload():
    transport = broker_gate_fakes.make_mock_transport()
    client = httpx.Client(transport=transport, base_url="https://api.gateio.ws")
    resp = client.get("/api/v4/tradfi/users/assets")
    assert resp.status_code == 200
    assert resp.json() == _load("users_assets.json")


def test_mock_create_order_returns_queue_task_id():
    transport = broker_gate_fakes.make_mock_transport()
    client = httpx.Client(transport=transport, base_url="https://api.gateio.ws")
    resp = client.post(
        "/api/v4/tradfi/orders",
        json={"symbol": "AAPL", "side": 2, "volume": "1", "price_type": "market"},
    )
    assert resp.status_code == 200
    assert "id" in resp.json()["data"]


# --------------------------------------------------------------------------- #
# 4. The three failure injections are producible.
# --------------------------------------------------------------------------- #


def test_inject_auth_failure_401():
    transport = broker_gate_fakes.make_mock_transport(fail="auth")
    client = httpx.Client(transport=transport, base_url="https://api.gateio.ws")
    resp = client.get("/api/v4/tradfi/users/assets")
    assert resp.status_code == 401


def test_inject_rate_limit_429_carries_headers():
    transport = broker_gate_fakes.make_mock_transport(fail="rate_limit")
    client = httpx.Client(transport=transport, base_url="https://api.gateio.ws")
    resp = client.get("/api/v4/tradfi/positions")
    assert resp.status_code == 429
    assert "X-Gate-RateLimit-Requests-Remain" in resp.headers
    assert "X-Gate-RateLimit-Limit" in resp.headers
    assert "X-Gate-RateLimit-Reset-Timestamp" in resp.headers


def test_inject_network_error_raises_transport_error():
    transport = broker_gate_fakes.make_mock_transport(fail="network")
    client = httpx.Client(transport=transport, base_url="https://api.gateio.ws")
    with pytest.raises(httpx.TransportError):
        client.get("/api/v4/tradfi/positions")


def test_mock_unknown_path_returns_404():
    """A path with no fixture is a 404 — keeps the mock honest about coverage."""
    transport = broker_gate_fakes.make_mock_transport()
    client = httpx.Client(transport=transport, base_url="https://api.gateio.ws")
    resp = client.get("/api/v4/tradfi/does-not-exist")
    assert resp.status_code == 404
