"""Golden / contract tests for the broker MCP tool OUTPUT SHAPES (Task 6.3).

These tests PIN the wire contract every broker MCP tool emits, so downstream
consumers (``execution-daemon`` / ``decision-trace-telemetry``) can rely on a
stable, JSON-serializable ``dict`` shape with an EXACT documented key set and
value types. Where the Task-5.1 ``test_broker_server.py`` proves the never-raises
seam and spot-checks a few keys, THIS suite is the golden lock: it asserts the
FULL key set per tool, the value TYPES (P13 — HG-23 is presence-only; this layer
validates its own types), that NO enum / dataclass instance leaks (every output is
``json.dumps``-able), and that the structured error dict shape is secret-free. If a
tool's envelope key is renamed or an enum leaks, a test here MUST fail.

Source of truth: ``.kiro/specs/broker-cfd-adapter/design.md`` "Simulation &
Interface (summary) -> server" + the ``server`` Components row; ``server.py`` (the
``@mcp.tool()`` wrappers and their named-list envelopes
``{"positions":[...]}`` / ``{"symbols":[...]}`` / ``{"history":[...]}``);
``models.py`` (the dataclass field sets the coercion walks). Requirements: 9.2
(venue error / unreachable -> structured result, no raise; the tool surface is the
wire contract).

Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \\
        tests/contract/test_broker_contracts.py -q

The broker runs in its own uv venv (carries ``mcp`` / ``httpx``); the repo root is
NOT on ``sys.path``. This test loads the broker modules by path (importlib-by-path
under unique aliases), loading ``models`` FIRST under its CANONICAL alias so
dependent modules' ``from models import ...`` reuse the SAME class objects (enum /
isinstance identity holds — the LOAD-BEARING ordering from tasks.md Implementation
Notes), mirroring ``tests/unit/mcp/test_broker_server.py``. ``core`` is loaded
under its canonical alias so ``server.py``'s ``import core`` resolves to THIS
instance; the tools are then driven against the Task-1.4 mock by monkeypatching
``core.default_clients`` to a mock-transport-backed clients holder.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Repo root: tests/contract/test_broker_contracts.py -> parents[2] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"
# server + core + their deps do by-name sibling imports (`import config`,
# `import core`, `from models import ...`) — the production posture (`python
# server.py` with the broker dir on sys.path[0]). The broker uv venv does NOT put
# the broker dir on sys.path, so seed it here.
if str(_BROKER_DIR) not in sys.path:
    sys.path.insert(0, str(_BROKER_DIR))


def _load_by_path(alias: str, path: Path):
    spec = importlib.util.spec_from_file_location(alias, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


# The 1.4 mock transport + fixture loader (the injectable-transport seam).
_FAKES_PATH = _REPO_ROOT / "tests" / "unit" / "mcp" / "broker_gate_fakes.py"
broker_gate_fakes = _load_by_path("broker_gate_fakes", _FAKES_PATH)

# LOAD-BEARING ordering (tasks.md Implementation Notes): load ``models`` FIRST under
# its CANONICAL alias so every dependent module's ``from models import ...`` reuses
# THIS instance (one canonical set of classes/enums -> isinstance/identity holds).
# Then the deps of ``core`` in dependency order, ``core`` under its CANONICAL alias
# (so ``server``'s ``import core`` resolves to THIS instance), then ``server``.
broker_models = _load_by_path("models", _BROKER_DIR / "models.py")
broker_config = _load_by_path("config", _BROKER_DIR / "config.py")
broker_mappers = _load_by_path("mappers", _BROKER_DIR / "mappers.py")
gate_client = _load_by_path("gate_client", _BROKER_DIR / "gate_client.py")
symbol_cache = _load_by_path("symbol_cache", _BROKER_DIR / "symbol_cache.py")
paper = _load_by_path("paper", _BROKER_DIR / "paper.py")
validation = _load_by_path("validation", _BROKER_DIR / "validation.py")
core = _load_by_path("core", _BROKER_DIR / "core.py")
server = _load_by_path("broker_server", _BROKER_DIR / "server.py")

make_mock_transport = broker_gate_fakes.make_mock_transport


# --------------------------------------------------------------------------- #
# The GOLDEN key sets — the exact documented top-level dict keys each row emits.
# These are the wire contract; a rename in server.py / models.py breaks a test.
# --------------------------------------------------------------------------- #

# get_positions row (coerced ``Position``) — design "Data Models -> Position".
_POSITION_KEYS = {
    "position_id",
    "symbol",
    "direction",
    "volume",
    "avg_open_price",
    "used_margin",
    "unrealized_pnl",
}

# get_account_assets (coerced ``AccountAssets``) — design "Data Models ->
# AccountAssets"; NO derived liquidation-distance key (Req 3.2).
_ACCOUNT_ASSETS_KEYS = {
    "equity",
    "used_margin",
    "free_margin",
    "margin_level",
    "balance",
    "stop_out_level",
}

# list_tradable_symbols / validate_symbol(known) row (coerced ``SymbolInfo``) —
# design "Data Models -> SymbolInfo".
_SYMBOL_INFO_KEYS = {
    "ticker",
    "category",
    "leverage",
    "trade_mode",
    "min_order_volume",
    "max_order_volume",
    "price_precision",
    "buy_swap_rate",
    "sell_swap_rate",
    "status",
    "next_open_time",
}

# get_history row (coerced ``HistoryRecord``) — design "Data Models ->
# HistoryRecord".
_HISTORY_KEYS = {
    "kind",
    "fill_price",
    "fill_volume",
    "realized_pnl",
    "realized_swap",
    "close_reason",
}

# submit_decision (coerced ``OrderResult``) — design "Data Models -> OrderResult".
_ORDER_RESULT_KEYS = {
    "status",
    "order_id",
    "position_id",
    "fill_price",
    "fill_volume",
    "reason",
    "raw",
}

# validate_symbol(unknown) row (coerced ``RejectionReason``) — design "Data Models
# -> RejectionReason".
_REJECTION_KEYS = {"code", "message", "next_open_time"}

# Structured error dict (Req 9.2) — server ``_error_dict``.
_ERROR_KEYS = {"error", "error_class", "message", "status_code"}


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _set_creds(monkeypatch, key: str = "k-test", secret: str = "s-test") -> None:
    """The /tradfi readouts are authenticated — gate_client resolves creds fresh."""
    monkeypatch.setenv("GATE_API_KEY", key)
    monkeypatch.setenv("GATE_API_SECRET", secret)


def _mock_clients(transport):
    """A real-core ReadoutClients holder wired to the injected mock transport (the
    DI seam) so the tools run end-to-end with NO live venue."""
    cache = symbol_cache.SymbolCache(gate_client=gate_client, transport=transport)
    return core.ReadoutClients(
        gate_client=gate_client, symbol_cache=cache, transport=transport
    )


def _install_default_clients(monkeypatch, transport) -> None:
    """Point ``core.default_clients`` (the production DI the tools call when no
    explicit ``clients=`` is passed) at a mock-backed holder, so a tool runs against
    the mock transport rather than a live venue."""
    holder = _mock_clients(transport)
    monkeypatch.setattr(core, "default_clients", lambda: holder)


def _assert_json_serializable(obj):
    """The CORE golden guarantee (Req 9.2 / wire contract): every tool output must
    ``json.dumps`` cleanly — i.e. carry NO enum / dataclass / other non-JSON
    instance. Returns the re-loaded value so callers can re-assert on plain types."""
    try:
        blob = json.dumps(obj)
    except (TypeError, ValueError) as exc:  # pragma: no cover - asserted as failure
        pytest.fail(f"tool output is not JSON-serializable ({exc}): {obj!r}")
    return json.loads(blob)


def _assert_keys(d: dict, expected: set, *, where: str) -> None:
    """Pin the EXACT documented key set (golden): a renamed / dropped / added
    top-level key fails. ``set ==`` (not superset) so an envelope rename is caught."""
    assert isinstance(d, dict), f"{where}: expected a dict, got {type(d)}"
    assert set(d.keys()) == expected, (
        f"{where}: key set drift — got {sorted(d.keys())}, expected {sorted(expected)}"
    )


def _assert_no_enum_or_dataclass(obj) -> None:
    """Recursively assert no Enum instance and no dataclass INSTANCE survives the
    coercion (the wire must carry plain str / number / bool / None / dict / list)."""
    import dataclasses
    from enum import Enum

    assert not isinstance(obj, Enum), f"enum leaked to the wire: {obj!r}"
    assert not (
        dataclasses.is_dataclass(obj) and not isinstance(obj, type)
    ), f"dataclass instance leaked to the wire: {obj!r}"
    if isinstance(obj, dict):
        for v in obj.values():
            _assert_no_enum_or_dataclass(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _assert_no_enum_or_dataclass(v)


# --------------------------------------------------------------------------- #
# get_positions — {"positions": [ <Position dict>, ... ]} (Req 2.1–2.3).
# --------------------------------------------------------------------------- #


def test_get_positions_contract(monkeypatch):
    """GOLDEN: get_positions -> ``{"positions": [...]}`` with each row carrying the
    EXACT ``Position`` key set; ``direction`` a plain string; numerics numbers; the
    whole payload json-serializable; no enum/dataclass leaks."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.get_positions()

    # Envelope: exactly {"positions": [...]} (the named-list wrapper).
    _assert_keys(result, {"positions"}, where="get_positions envelope")
    reloaded = _assert_json_serializable(result)
    _assert_no_enum_or_dataclass(result)

    rows = reloaded["positions"]
    assert isinstance(rows, list) and rows, "expected non-empty positions from fixtures"
    for row in rows:
        _assert_keys(row, _POSITION_KEYS, where="position row")
        # direction serialized as a plain string (no Direction enum instance).
        assert type(row["direction"]) is str
        assert row["direction"] in ("LONG", "SHORT")
        # numerics are numbers, not venue strings.
        for num_key in ("volume", "avg_open_price", "used_margin", "unrealized_pnl"):
            assert isinstance(row[num_key], (int, float)), (
                f"position.{num_key} must be a number, got {type(row[num_key])}"
            )
        assert type(row["position_id"]) is str
        assert type(row["symbol"]) is str


# --------------------------------------------------------------------------- #
# get_account_assets — flat AccountAssets dict, NO liquidation distance (Req 3.2).
# --------------------------------------------------------------------------- #


def test_get_account_assets_contract(monkeypatch):
    """GOLDEN: get_account_assets -> the EXACT ``AccountAssets`` key set (equity /
    used_margin / free_margin / margin_level / balance / stop_out_level), every
    value a number, and NO derived liquidation-distance key (Req 3.2)."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.get_account_assets()

    _assert_keys(result, _ACCOUNT_ASSETS_KEYS, where="account_assets")
    reloaded = _assert_json_serializable(result)
    _assert_no_enum_or_dataclass(result)

    for k in _ACCOUNT_ASSETS_KEYS:
        assert isinstance(reloaded[k], (int, float)), (
            f"account_assets.{k} must be a number, got {type(reloaded[k])}"
        )
    # Req 3.2: the adapter surfaces stop_out_level but NEVER a derived
    # liquidation-distance field — assert no such key sneaks in.
    assert not any(
        "liquidation" in k or "distance" in k for k in result
    ), "a derived liquidation-distance key leaked (Req 3.2 violation)"


# --------------------------------------------------------------------------- #
# list_tradable_symbols — {"symbols": [ <SymbolInfo dict>, ... ]} (Req 3.3/4.1/4.2).
# --------------------------------------------------------------------------- #


def test_list_tradable_symbols_contract(monkeypatch):
    """GOLDEN: list_tradable_symbols -> ``{"symbols": [...]}`` with each row carrying
    the EXACT ``SymbolInfo`` key set (ticker / category / leverage / trade_mode /
    min+max_order_volume / price_precision / swap rates / status / next_open_time);
    json-serializable; no enum/dataclass leaks."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.list_tradable_symbols()

    _assert_keys(result, {"symbols"}, where="list_tradable_symbols envelope")
    reloaded = _assert_json_serializable(result)
    _assert_no_enum_or_dataclass(result)

    rows = reloaded["symbols"]
    assert isinstance(rows, list) and rows, "expected non-empty symbols from fixtures"
    for row in rows:
        _assert_keys(row, _SYMBOL_INFO_KEYS, where="symbol row")
        assert type(row["ticker"]) is str
        assert type(row["trade_mode"]) is str
        assert type(row["status"]) is str
        for num_key in (
            "leverage",
            "min_order_volume",
            "max_order_volume",
            "buy_swap_rate",
            "sell_swap_rate",
        ):
            assert isinstance(row[num_key], (int, float)), (
                f"symbol.{num_key} must be a number, got {type(row[num_key])}"
            )
        assert isinstance(row["price_precision"], int)
        # next_open_time is int | None (populated only when closed — Req 6.1 input).
        assert row["next_open_time"] is None or isinstance(row["next_open_time"], int)


# --------------------------------------------------------------------------- #
# validate_symbol — SymbolInfo dict (known) OR RejectionReason dict (unknown).
# --------------------------------------------------------------------------- #


def test_validate_symbol_known_contract(monkeypatch):
    """GOLDEN: validate_symbol(known) -> a coerced ``SymbolInfo`` dict with the EXACT
    key set; json-serializable; the ticker echoed."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.validate_symbol("AAPL")

    _assert_keys(result, _SYMBOL_INFO_KEYS, where="validate_symbol(known)")
    _assert_json_serializable(result)
    _assert_no_enum_or_dataclass(result)
    assert result["ticker"] == "AAPL"


def test_validate_symbol_unknown_contract(monkeypatch):
    """GOLDEN: validate_symbol(unknown) -> a coerced ``RejectionReason`` dict with
    the EXACT key set; ``code`` a plain string (no RejectionCode enum leak);
    json-serializable. This is a BUSINESS outcome, NOT the 9.2 error dict — so it
    carries no ``error`` flag and is distinguishable from a transport failure."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.validate_symbol("NOPE")

    _assert_keys(result, _REJECTION_KEYS, where="validate_symbol(unknown)")
    _assert_json_serializable(result)
    _assert_no_enum_or_dataclass(result)
    assert type(result["code"]) is str
    assert result["code"] == "UNKNOWN_SYMBOL"
    assert type(result["message"]) is str
    # A rejection is NOT the structured error dict — keep them distinguishable.
    assert "error" not in result


def test_validate_symbol_out_of_category_contract(monkeypatch):
    """GOLDEN: validate_symbol(out-of-category, e.g. a Forex ticker) -> a
    ``RejectionReason`` dict with ``code`` == OUT_OF_CATEGORY (a plain string)."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    # EURUSD is category_id 1 (Forex) in the fixtures — out of the US-stock set.
    result = server.validate_symbol("EURUSD")

    _assert_keys(result, _REJECTION_KEYS, where="validate_symbol(out-of-category)")
    _assert_json_serializable(result)
    _assert_no_enum_or_dataclass(result)
    assert type(result["code"]) is str
    assert result["code"] == "OUT_OF_CATEGORY"


# --------------------------------------------------------------------------- #
# get_history — {"history": [ <HistoryRecord dict>, ... ]} (Req 9.3, 10.1–10.4).
# --------------------------------------------------------------------------- #


def test_get_history_contract(monkeypatch):
    """GOLDEN: get_history -> ``{"history": [...]}`` with each row carrying the EXACT
    ``HistoryRecord`` key set; ``close_reason`` a plain string in
    {normal, forced_liquidation}; numerics numbers; json-serializable; no
    enum/dataclass leaks. The forced-liquidation flag must survive as a string."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.get_history()

    _assert_keys(result, {"history"}, where="get_history envelope")
    reloaded = _assert_json_serializable(result)
    _assert_no_enum_or_dataclass(result)

    rows = reloaded["history"]
    assert isinstance(rows, list) and rows, "expected non-empty history from fixtures"
    for row in rows:
        _assert_keys(row, _HISTORY_KEYS, where="history row")
        assert type(row["kind"]) is str
        assert type(row["close_reason"]) is str
        assert row["close_reason"] in ("normal", "forced_liquidation")
        for num_key in ("fill_price", "fill_volume", "realized_pnl", "realized_swap"):
            assert isinstance(row[num_key], (int, float)), (
                f"history.{num_key} must be a number, got {type(row[num_key])}"
            )
    # The forced-liquidation flag must surface (fixtures carry a forced close).
    assert any(r["close_reason"] == "forced_liquidation" for r in rows), (
        "forced_liquidation close_reason did not survive the wire contract (Req 10.2)"
    )


# --------------------------------------------------------------------------- #
# submit_decision — OrderResult dict; ``status`` a plain string.
# --------------------------------------------------------------------------- #


def test_submit_decision_paper_simulated_contract(monkeypatch):
    """GOLDEN: submit_decision(paper BUY) -> a coerced ``OrderResult`` dict with the
    EXACT key set; ``status`` a plain string == 'simulated' (paper-default v0.1,
    8.1/8.2); json-serializable; no enum/dataclass leaks."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.submit_decision(
        decision="BUY", symbol="AAPL", direction="LONG", volume=1.0
    )

    _assert_keys(result, _ORDER_RESULT_KEYS, where="submit_decision(paper BUY)")
    _assert_json_serializable(result)
    _assert_no_enum_or_dataclass(result)
    assert type(result["status"]) is str
    assert result["status"] == "simulated"
    # On a non-rejected result ``reason`` is null (the rejection slot is unused).
    assert result["reason"] is None


def test_submit_decision_hold_noop_contract(monkeypatch):
    """GOLDEN: submit_decision(HOLD) -> a coerced ``OrderResult`` no-op dict with the
    EXACT key set; ``status`` == 'noop' (Req 1.4); json-serializable."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.submit_decision(decision="HOLD", symbol="AAPL", direction="LONG")

    _assert_keys(result, _ORDER_RESULT_KEYS, where="submit_decision(HOLD)")
    _assert_json_serializable(result)
    _assert_no_enum_or_dataclass(result)
    assert type(result["status"]) is str
    assert result["status"] == "noop"


def test_submit_decision_rejected_contract(monkeypatch):
    """GOLDEN: submit_decision rejection -> an ``OrderResult`` dict whose ``status``
    == 'rejected' and whose nested ``reason`` is a coerced ``RejectionReason`` dict
    (its ``code`` a plain string, NOT a RejectionCode enum). A SELL with no matching
    position (Req 1.8) drives a NO_POSITION rejection."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    # SELL with a position_id absent from the fixture book -> NO_POSITION rejection.
    result = server.submit_decision(
        decision="SELL",
        symbol="AAPL",
        direction="LONG",
        position_id="POS-DOES-NOT-EXIST",
    )

    _assert_keys(result, _ORDER_RESULT_KEYS, where="submit_decision(rejected)")
    _assert_json_serializable(result)
    _assert_no_enum_or_dataclass(result)
    assert result["status"] == "rejected"
    reason = result["reason"]
    assert isinstance(reason, dict), "rejection ``reason`` must be a nested dict"
    _assert_keys(reason, _REJECTION_KEYS, where="rejected.reason")
    # ``code`` is a plain string (no enum instance leaked through the nesting).
    assert type(reason["code"]) is str
    assert reason["code"] == "NO_POSITION"


# --------------------------------------------------------------------------- #
# Error path — structured {error, error_class, message, status_code} dict (Req 9.2),
# secret-free; NOT an enum/dataclass; json-serializable.
# --------------------------------------------------------------------------- #


def test_error_dict_contract(monkeypatch):
    """GOLDEN: a transport/venue failure surfaces as the EXACT structured error dict
    key set (Req 9.2): ``error`` flag / ``error_class`` / ``message`` /
    ``status_code``. ``error`` is True, ``error_class`` a plain string, the venue
    status code surfaced; json-serializable; no enum/dataclass leaks."""
    _set_creds(monkeypatch)
    # The mock 'auth' failure -> core.get_positions raises BrokerReadoutError ->
    # the tool coerces it to the structured error dict (never raises).
    _install_default_clients(monkeypatch, make_mock_transport(fail="auth"))

    result = server.get_positions()  # must NOT raise

    _assert_keys(result, _ERROR_KEYS, where="error dict")
    _assert_json_serializable(result)
    _assert_no_enum_or_dataclass(result)
    assert result["error"] is True
    assert type(result["error_class"]) is str
    assert result["error_class"] == "auth"
    assert type(result["message"]) is str
    assert result["status_code"] == 401


def test_error_dict_is_secret_free(monkeypatch):
    """GOLDEN (Security): the structured error dict must NOT echo the API key/secret
    even when a failure occurs with creds set — no secret leakage on the wire."""
    secret_key = "SUPER-SECRET-KEY-abc123"
    secret_val = "SUPER-SECRET-VAL-xyz789"
    _set_creds(monkeypatch, key=secret_key, secret=secret_val)
    _install_default_clients(monkeypatch, make_mock_transport(fail="auth"))

    result = server.get_positions()

    blob = json.dumps(_assert_json_serializable(result))
    assert secret_key not in blob, "API key leaked into the error dict"
    assert secret_val not in blob, "API secret leaked into the error dict"


# --------------------------------------------------------------------------- #
# Cross-tool invariant — EVERY tool output json-serializable (the core guarantee).
# --------------------------------------------------------------------------- #


def test_every_tool_output_is_json_serializable(monkeypatch):
    """GOLDEN cross-tool invariant: every one of the six tools returns a
    ``json.dumps``-able dict carrying NO enum / dataclass instance — the single
    contract downstream consumers depend on. Drives each tool once against the mock
    and asserts serializability + no-leak in one sweep."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    outputs = {
        "get_positions": server.get_positions(),
        "get_account_assets": server.get_account_assets(),
        "list_tradable_symbols": server.list_tradable_symbols(),
        "validate_symbol_known": server.validate_symbol("AAPL"),
        "validate_symbol_unknown": server.validate_symbol("NOPE"),
        "get_history": server.get_history(),
        "submit_decision_paper": server.submit_decision(
            decision="BUY", symbol="AAPL", direction="LONG", volume=1.0
        ),
        "submit_decision_hold": server.submit_decision(
            decision="HOLD", symbol="AAPL", direction="LONG"
        ),
    }
    for name, out in outputs.items():
        assert isinstance(out, dict), f"{name}: tool output must be a dict"
        _assert_json_serializable(out)
        _assert_no_enum_or_dataclass(out)
