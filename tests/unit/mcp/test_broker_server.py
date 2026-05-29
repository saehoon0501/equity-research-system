"""Unit tests for the MCP server interface + registration (Task 5.1).

Covers the design "Simulation & Interface (summary) -> server" bullet, the
Components table ``server`` row, and the Error-Handling strategy that names the
``server`` as the never-raises seam: thin ``@mcp.tool()`` wrappers over ``core``
that coerce typed results to plain JSON-able ``dict`` and NEVER raise — wrapping
both a :class:`core.BrokerReadoutError` AND any unexpected exception into a
structured error ``dict`` (Req 9.2: ``error_class`` / ``message`` / ``status_code``,
secret-free).

Requirements: 9.2 (venue error / unreachable -> structured result, no raise;
the tool surface is the never-raises seam).

Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \\
        tests/unit/mcp/test_broker_server.py -q

The broker runs in its own uv venv (carries ``mcp`` / ``httpx``); the repo root
is NOT on ``sys.path``. This test loads the broker modules by path
(importlib-by-path under unique aliases), loading ``models`` FIRST under its
canonical alias so dependent modules' ``from models import ...`` reuse the SAME
class objects (enum / isinstance identity holds), mirroring
``test_broker_core_readouts.py``. ``server`` is loaded LAST (it imports ``core``
by name, which the earlier loads have already aliased into ``sys.modules``).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Repo root: tests/unit/mcp/test_broker_server.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"
# server + core + their deps do by-name sibling imports (`import config`,
# `import core`, `from models import ...`) — exactly the production posture
# (`python server.py` with the broker dir on sys.path[0]). The broker uv venv
# does NOT put the broker dir on sys.path, so seed it here.
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

# LOAD-BEARING ordering: load ``models`` FIRST under its CANONICAL alias so every
# dependent module's ``from models import ...`` reuses THIS instance (one canonical
# set of classes/enums -> isinstance/identity holds). Then config, mappers,
# gate_client, symbol_cache, paper, validation (deps of core), then core itself
# under its CANONICAL alias ``core`` (so server.py's ``import core`` resolves to
# THIS instance), then the unit-under-test ``server``.
broker_models = _load_by_path("models", _BROKER_DIR / "models.py")
broker_config = _load_by_path("config", _BROKER_DIR / "config.py")
broker_mappers = _load_by_path("mappers", _BROKER_DIR / "mappers.py")
gate_client = _load_by_path("gate_client", _BROKER_DIR / "gate_client.py")
symbol_cache = _load_by_path("symbol_cache", _BROKER_DIR / "symbol_cache.py")
paper = _load_by_path("paper", _BROKER_DIR / "paper.py")
validation = _load_by_path("validation", _BROKER_DIR / "validation.py")
core = _load_by_path("core", _BROKER_DIR / "core.py")
server = _load_by_path("broker_server", _BROKER_DIR / "server.py")

Position = broker_models.Position
AccountAssets = broker_models.AccountAssets
SymbolInfo = broker_models.SymbolInfo
HistoryRecord = broker_models.HistoryRecord
RejectionReason = broker_models.RejectionReason
RejectionCode = broker_models.RejectionCode
Direction = broker_models.Direction
Label = broker_models.Label

load_fixture = broker_gate_fakes.load_fixture
make_mock_transport = broker_gate_fakes.make_mock_transport


# The six core leaf functions the server wraps one-to-one.
_EXPECTED_TOOLS = {
    "submit_decision",
    "get_positions",
    "get_account_assets",
    "list_tradable_symbols",
    "validate_symbol",
    "get_history",
}


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _set_creds(monkeypatch, key: str = "k-test", secret: str = "s-test") -> None:
    """The /tradfi readouts are authenticated — gate_client resolves creds fresh."""
    monkeypatch.setenv("GATE_API_KEY", key)
    monkeypatch.setenv("GATE_API_SECRET", secret)


def _mock_clients(transport):
    """Build a real-core ReadoutClients holder wired to an injected mock transport
    (the DI seam) so the tools run end-to-end with NO live venue."""
    cache = symbol_cache.SymbolCache(gate_client=gate_client, transport=transport)
    return core.ReadoutClients(
        gate_client=gate_client, symbol_cache=cache, transport=transport
    )


def _install_default_clients(monkeypatch, transport) -> None:
    """Point ``core.default_clients`` (the production DI the tools call) at a
    mock-backed clients holder, so a tool invoked with NO explicit ``clients=``
    runs against the mock transport rather than a live venue."""
    holder = _mock_clients(transport)
    monkeypatch.setattr(core, "default_clients", lambda: holder)


def _tool_names() -> set[str]:
    """The set of tool names registered on the FastMCP instance, version-robust."""
    tm = server.mcp._tool_manager
    return {t.name for t in tm.list_tools()}


def _is_json_able(obj) -> bool:
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


def _assert_plain_dict(obj) -> dict:
    """A coerced tool result must be a plain JSON-able dict carrying no enum /
    dataclass instances (so an MCP client receives a wire-clean payload)."""
    assert isinstance(obj, dict), f"expected a dict, got {type(obj)}"
    assert _is_json_able(obj), f"result is not JSON-able: {obj!r}"
    return obj


# --------------------------------------------------------------------------- #
# (a) Registration: all six tools registered on the FastMCP instance.
# --------------------------------------------------------------------------- #


def test_mcp_instance_named_broker():
    """The server exposes a FastMCP instance named 'broker' (house pattern)."""
    assert hasattr(server, "mcp"), "FastMCP instance not exposed as `mcp`"
    assert server.mcp.name == "broker"


def test_all_six_tools_registered():
    """All six core leaf functions are registered as MCP tools (Task 5.1)."""
    assert _tool_names() == _EXPECTED_TOOLS, (
        f"registered tools {_tool_names()} != expected {_EXPECTED_TOOLS}"
    )


def test_tool_callables_exposed_at_module_scope():
    """Each @mcp.tool() callable remains accessible at module scope (house pattern,
    mirrors test_polygon.py)."""
    for name in _EXPECTED_TOOLS:
        assert callable(getattr(server, name)), f"missing endpoint {name}"


# --------------------------------------------------------------------------- #
# (b) Each tool returns a dict (or list of dicts) against the mock transport.
# --------------------------------------------------------------------------- #


def test_get_positions_tool_returns_dict_with_list_of_position_dicts(monkeypatch):
    """get_positions tool -> a dict envelope whose ``positions`` is a list of plain
    dicts (dataclasses coerced; enums -> plain strings)."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.get_positions()

    _assert_plain_dict(result)
    assert isinstance(result["positions"], list)
    assert result["positions"], "expected a non-empty positions list from fixtures"
    row = result["positions"][0]
    assert isinstance(row, dict)
    # Enum coerced to a PLAIN string (no Direction.* enum instance survives).
    assert row["direction"] in ("LONG", "SHORT")
    assert type(row["direction"]) is str


def test_get_account_assets_tool_returns_plain_dict(monkeypatch):
    """get_account_assets tool -> a plain dict with the venue-supplied fields."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.get_account_assets()

    _assert_plain_dict(result)
    assert result["stop_out_level"] == pytest.approx(50.0)
    # Req 3.2 surfaced unchanged: no derived liquidation distance field appears.
    assert not any("liquidation" in k or "distance" in k for k in result)


def test_list_tradable_symbols_tool_returns_list_of_symbol_dicts(monkeypatch):
    """list_tradable_symbols tool -> a dict envelope whose ``symbols`` is a list of
    plain dicts."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.list_tradable_symbols()

    _assert_plain_dict(result)
    assert isinstance(result["symbols"], list)
    assert all(isinstance(s, dict) for s in result["symbols"])
    by_ticker = {s["ticker"]: s for s in result["symbols"]}
    assert "AAPL" in by_ticker


def test_validate_symbol_tool_known_ticker_returns_dict(monkeypatch):
    """validate_symbol tool (known ticker) -> a plain SymbolInfo dict."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.validate_symbol("AAPL")

    _assert_plain_dict(result)
    assert result.get("ticker") == "AAPL"


def test_validate_symbol_tool_unknown_ticker_returns_rejection_dict(monkeypatch):
    """validate_symbol tool (unknown ticker) -> a structured rejection dict (the
    RejectionReason coerced; ``code`` is a plain string, not an enum)."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.validate_symbol("NOPE")

    _assert_plain_dict(result)
    assert result.get("code") == "UNKNOWN_SYMBOL"
    assert type(result["code"]) is str


def test_get_history_tool_returns_list_of_history_dicts(monkeypatch):
    """get_history tool -> a dict envelope whose ``history`` is a list of plain
    dicts surfacing fills / swap / close_reason."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.get_history()

    _assert_plain_dict(result)
    assert isinstance(result["history"], list)
    assert all(isinstance(h, dict) for h in result["history"])
    assert any(h.get("close_reason") == "forced_liquidation" for h in result["history"])


def test_submit_decision_tool_paper_simulated_returns_dict(monkeypatch):
    """submit_decision tool (paper default) -> a plain dict; a BUY in paper mode is
    simulated (status='simulated'), no enum instances leak."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.submit_decision(
        decision="BUY", symbol="AAPL", direction="LONG", volume=1.0
    )

    _assert_plain_dict(result)
    # Paper-default v0.1: a validated BUY simulates (8.1/8.2). status is a plain str.
    assert result["status"] == "simulated"


def test_submit_decision_tool_hold_noop_returns_dict(monkeypatch):
    """submit_decision tool with HOLD -> a structured no-op dict (Req 1.4)."""
    _set_creds(monkeypatch)
    _install_default_clients(monkeypatch, make_mock_transport())

    result = server.submit_decision(
        decision="HOLD", symbol="AAPL", direction="LONG"
    )

    _assert_plain_dict(result)
    assert result["status"] == "noop"


# --------------------------------------------------------------------------- #
# (c) Never-raises seam (Req 9.2): BrokerReadoutError AND a forced unexpected
#     exception each yield a structured error dict, NOT a raise.
# --------------------------------------------------------------------------- #


def test_readout_tool_wraps_broker_readout_error_into_structured_dict(monkeypatch):
    """A transport/venue failure surfaces from core as BrokerReadoutError; the tool
    must NOT raise — it coerces to a structured error dict (Req 9.2) carrying the
    failure class / message / status_code."""
    _set_creds(monkeypatch)
    # The mock 'auth' failure -> core.get_positions raises BrokerReadoutError.
    _install_default_clients(monkeypatch, make_mock_transport(fail="auth"))

    result = server.get_positions()  # must NOT raise

    _assert_plain_dict(result)
    assert result.get("error_class") == "auth"
    assert "message" in result
    # The 401 status code is surfaced for the consumer (Req 9.2 shape).
    assert result.get("status_code") == 401


def test_submit_decision_tool_wraps_unexpected_exception_into_structured_dict(
    monkeypatch,
):
    """ANY unexpected exception (not just BrokerReadoutError) must be caught and
    coerced to a structured error dict — the tool is the never-raises seam (9.2)."""
    _set_creds(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("unexpected core explosion")

    monkeypatch.setattr(core, "submit_decision", _boom)

    result = server.submit_decision(
        decision="BUY", symbol="AAPL", direction="LONG", volume=1.0
    )  # must NOT raise

    _assert_plain_dict(result)
    assert "error_class" in result
    assert "message" in result


def test_error_dict_carries_no_secrets(monkeypatch):
    """The structured error dict must be secret-free (Security: secrets never in
    results). The error message must not echo the API key/secret even if a failure
    occurs while creds are set."""
    secret_key = "SUPER-SECRET-KEY-abc123"
    secret_val = "SUPER-SECRET-VAL-xyz789"
    _set_creds(monkeypatch, key=secret_key, secret=secret_val)
    _install_default_clients(monkeypatch, make_mock_transport(fail="auth"))

    result = server.get_positions()

    _assert_plain_dict(result)
    blob = json.dumps(result)
    assert secret_key not in blob
    assert secret_val not in blob


# --------------------------------------------------------------------------- #
# (d) .mcp.json parses + carries a `broker` entry with the exact uv-run shape.
# --------------------------------------------------------------------------- #


def test_mcp_json_has_broker_entry_with_house_uv_run_shape():
    """.mcp.json parses as valid JSON and the new `broker` entry follows the EXACT
    house uv-run shape (a surgical add alongside the existing servers)."""
    mcp_json_path = _REPO_ROOT / ".mcp.json"
    data = json.loads(mcp_json_path.read_text())  # asserts valid JSON

    servers = data["mcpServers"]
    assert "broker" in servers, "broker entry missing from .mcp.json"
    entry = servers["broker"]
    assert entry == {
        "command": "uv",
        "args": ["run", "--directory", "src/mcp/broker", "python", "server.py"],
        "cwd": ".",
    }
    # Surgical add: the pre-existing servers must remain registered.
    for pre_existing in (
        "postgres",
        "edgar",
        "market_data",
        "fundamentals",
        "fred",
        "yfinance",
        "polygon",
        "macro_stack",
        "massive",
        "contamination_check",
    ):
        assert pre_existing in servers, f"surgical add dropped {pre_existing!r}"
