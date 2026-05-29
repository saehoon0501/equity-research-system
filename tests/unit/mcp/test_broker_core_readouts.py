"""Unit tests for the readout leaf functions (Task 4.1).

Covers the design "Operations layer -> core" component, READOUT portion only
(``get_positions`` / ``get_account_assets`` / ``list_tradable_symbols`` /
``validate_symbol`` / ``get_history``). The order-routing (4.2) and async
lifecycle (4.3) portions of ``core`` are out of scope here — this file exercises
only the read-only leaf functions and the structured "no data vs transport
failure" contract those functions establish for the MCP wrapper (Task 5.1).

Requirements: 2.1 (positions fields), 2.3 (empty positions -> [] not error),
3.1 (assets fields), 3.2 (stop-out exposed, NO derived liquidation distance),
3.3 (per-symbol swap rates + realized swap), 9.3 (surface fill price/volume via
history), 9.4 (emit no telemetry), 10.1 (history fills/PnL/swap/close-reason),
10.4 (empty window -> [] not error). Plus the design Error-Handling contract:
a transport/venue failure is SURFACED, never masked as an empty success.

Dependency-injection seam (mirrors how ``SymbolCache`` took an injected
``gate_client`` — tasks.md): the readouts accept injected dependencies (a
``gate_client`` module + a ``SymbolCache``) via a small clients holder, so tests
inject the Task 1.4 ``make_mock_transport(...)`` and a mock-backed cache with NO
live venue.

Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \\
        tests/unit/mcp/test_broker_core_readouts.py -q

The broker runs in its own uv venv (carries ``mcp`` / ``httpx``); the repo root
is NOT on ``sys.path``. This test loads the broker modules by path
(importlib-by-path under unique aliases), loading ``models`` FIRST under its
canonical alias so dependent modules' ``from models import ...`` reuse the SAME
class objects (enum / isinstance identity holds), mirroring
``test_broker_symbol_cache.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Repo root: tests/unit/mcp/test_broker_core_readouts.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"
# core + its deps do by-name sibling imports (`import config`, `import mappers`,
# `from models import ...`, `import gate_client`, `import symbol_cache`) — exactly
# the production posture (`python server.py` with the broker dir on sys.path[0]).
# The broker uv venv does NOT put the broker dir on sys.path, so seed it here.
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
# gate_client, symbol_cache (deps of core), then the unit-under-test.
broker_models = _load_by_path("models", _BROKER_DIR / "models.py")
broker_config = _load_by_path("config", _BROKER_DIR / "config.py")
broker_mappers = _load_by_path("mappers", _BROKER_DIR / "mappers.py")
gate_client = _load_by_path("gate_client", _BROKER_DIR / "gate_client.py")
symbol_cache = _load_by_path("symbol_cache", _BROKER_DIR / "symbol_cache.py")
core = _load_by_path("broker_core", _BROKER_DIR / "core.py")

Position = broker_models.Position
AccountAssets = broker_models.AccountAssets
SymbolInfo = broker_models.SymbolInfo
HistoryRecord = broker_models.HistoryRecord
RejectionReason = broker_models.RejectionReason
RejectionCode = broker_models.RejectionCode
Direction = broker_models.Direction

load_fixture = broker_gate_fakes.load_fixture
make_mock_transport = broker_gate_fakes.make_mock_transport


# --------------------------------------------------------------------------- #
# Helpers / fixtures.
# --------------------------------------------------------------------------- #


def _set_creds(monkeypatch, key: str = "k-test", secret: str = "s-test") -> None:
    """The /tradfi readouts are authenticated — gate_client resolves creds fresh."""
    monkeypatch.setenv("GATE_API_KEY", key)
    monkeypatch.setenv("GATE_API_SECRET", secret)


def _clients(transport):
    """Build the readout clients holder with the real gate_client + a mock-backed
    SymbolCache, both wired to an injected (mock) transport — the DI seam under
    test. Production constructs this from config/env via ``core.default_clients()``.
    """
    cache = symbol_cache.SymbolCache(gate_client=gate_client, transport=transport)
    return core.ReadoutClients(
        gate_client=gate_client, symbol_cache=cache, transport=transport
    )


# --------------------------------------------------------------------------- #
# get_positions (Req 2.1, 2.2 surfaced, 2.3).
# --------------------------------------------------------------------------- #


def test_get_positions_returns_typed_list_with_venue_upnl_verbatim(monkeypatch):
    """positions readout -> [Position] with the VENUE unrealized_pnl reported
    verbatim (Req 2.1, 2.2) — no self-computed mark."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport())

    positions = core.get_positions(clients=clients)

    assert isinstance(positions, list)
    assert all(isinstance(p, Position) for p in positions)
    by_id = {p.position_id: p for p in positions}
    # Venue fixture: AAPL long uPnL 37.20, MSFT short uPnL -12.50 — reported
    # verbatim (Req 2.2). The float is the parsed venue string, value preserved.
    assert by_id["POS-500001"].unrealized_pnl == pytest.approx(37.20)
    assert by_id["POS-500001"].direction is Direction.LONG
    assert by_id["POS-500002"].unrealized_pnl == pytest.approx(-12.50)
    assert by_id["POS-500002"].direction is Direction.SHORT


def test_get_positions_empty_book_returns_empty_list_not_error(monkeypatch):
    """An empty venue position set is SUCCESS -> [] (Req 2.3), never an error."""
    _set_creds(monkeypatch)
    transport = make_mock_transport(overrides={("GET", "/tradfi/positions"): []})
    clients = _clients(transport)

    positions = core.get_positions(clients=clients)

    assert positions == []


def test_get_positions_transport_failure_is_surfaced_not_masked(monkeypatch):
    """A transport/venue FAILURE must be SURFACED (Error Handling), not masked as
    an empty success that looks like a flat book."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport(fail="auth"))

    with pytest.raises(core.BrokerReadoutError) as excinfo:
        core.get_positions(clients=clients)
    # The surfaced error names the failure class so Task 5.1 can structure it.
    assert excinfo.value.error_class == "auth"


# --------------------------------------------------------------------------- #
# get_account_assets (Req 3.1, 3.2).
# --------------------------------------------------------------------------- #


def test_get_account_assets_exposes_stop_out_and_no_liquidation_distance(monkeypatch):
    """assets readout -> AccountAssets with equity/margin fields + stop_out_level
    (Req 3.1, 3.2) and NO derived liquidation-distance field (Req 3.2 — that math
    belongs to survival-gate)."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport())

    assets = core.get_account_assets(clients=clients)

    assert isinstance(assets, AccountAssets)
    # Req 3.1 fields, parsed verbatim from the venue fixtures.
    assert assets.equity == pytest.approx(10234.56)
    assert assets.used_margin == pytest.approx(1215.00)
    assert assets.free_margin == pytest.approx(9019.56)
    assert assets.margin_level == pytest.approx(842.10)
    assert assets.balance == pytest.approx(10180.00)
    # Req 3.2: stop-out level exposed (from mt5-account), verbatim.
    assert assets.stop_out_level == pytest.approx(50.0)
    # Req 3.2: the adapter must NOT compute/assert a liquidation distance — no such
    # field exists on the readout.
    field_names = {f for f in vars(assets)}
    assert not any(
        "liquidation" in n or "liq_distance" in n or "distance" in n
        for n in field_names
    ), f"AccountAssets must carry no derived liquidation distance; got {field_names}"


def test_get_account_assets_transport_failure_is_surfaced(monkeypatch):
    """An assets transport failure is surfaced, never silently empty."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport(fail="network"))

    with pytest.raises(core.BrokerReadoutError) as excinfo:
        core.get_account_assets(clients=clients)
    assert excinfo.value.error_class == "network"


# --------------------------------------------------------------------------- #
# list_tradable_symbols / validate_symbol (Req 3.3, 4.1, 4.2).
# --------------------------------------------------------------------------- #


def test_list_tradable_symbols_returns_symbolinfos_with_swap_rates(monkeypatch):
    """tradable symbols -> [SymbolInfo] surfacing per-symbol swap rates (Req 3.3)."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport())

    symbols = core.list_tradable_symbols(clients=clients)

    assert isinstance(symbols, list)
    assert symbols, "expected the in-category tradable set to be non-empty"
    assert all(isinstance(s, SymbolInfo) for s in symbols)
    by_ticker = {s.ticker: s for s in symbols}
    # Req 3.3: per-symbol swap rates surfaced (AAPL buy/sell swap from fixtures).
    assert by_ticker["AAPL"].buy_swap_rate == pytest.approx(-0.0021)
    assert by_ticker["AAPL"].sell_swap_rate == pytest.approx(-0.0008)


def test_validate_symbol_known_ticker_returns_symbolinfo(monkeypatch):
    """A known in-category ticker resolves to a SymbolInfo (via SymbolCache)."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport())

    info = core.validate_symbol("AAPL", clients=clients)

    assert isinstance(info, SymbolInfo)
    assert info.ticker == "AAPL"


def test_validate_symbol_unknown_ticker_returns_rejection(monkeypatch):
    """An unknown ticker -> structured RejectionReason (not a SymbolInfo, not an
    exception)."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport())

    result = core.validate_symbol("NOPE", clients=clients)

    assert isinstance(result, RejectionReason)
    assert result.code is RejectionCode.UNKNOWN_SYMBOL


def test_validate_symbol_out_of_category_returns_rejection(monkeypatch):
    """An out-of-category ticker (EURUSD = category 1) -> OUT_OF_CATEGORY
    rejection (Req 4.2)."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport())

    result = core.validate_symbol("EURUSD", clients=clients)

    assert isinstance(result, RejectionReason)
    assert result.code is RejectionCode.OUT_OF_CATEGORY


# --------------------------------------------------------------------------- #
# get_history (Req 9.3, 10.1, 10.2 surfaced, 10.4).
# --------------------------------------------------------------------------- #


def test_get_history_returns_fills_swap_and_forced_liquidation_flag(monkeypatch):
    """history readout -> [HistoryRecord] surfacing fills (Req 9.3), realized swap
    (Req 3.3), and the forced-liquidation flag (Req 10.1/10.2)."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport())

    history = core.get_history(clients=clients)

    assert isinstance(history, list)
    assert all(isinstance(h, HistoryRecord) for h in history)

    # Req 9.3: an order fill surfaces fill price + volume (AAPL open ORD-090001).
    order_records = [h for h in history if h.kind == "order"]
    assert order_records, "expected order-history records"
    assert any(
        r.fill_price == pytest.approx(210.36) and r.fill_volume == pytest.approx(1.00)
        for r in order_records
    )

    # Req 3.3 / 10.1: realized swap surfaced on a closed position (POS-490001 swap
    # -1.26 from positions/history).
    position_records = [h for h in history if h.kind == "position"]
    assert position_records, "expected position-history records"
    assert any(r.realized_swap == pytest.approx(-1.26) for r in position_records)

    # Req 10.1/10.2: a forced-liquidation event is flagged (TSLA POS-490002
    # position_status 2; ORD-090003 order_opt_type 5).
    assert any(
        h.close_reason == "forced_liquidation" for h in history
    ), "expected at least one forced_liquidation close_reason"
    # And a normal close stays "normal" (no over-flagging).
    assert any(h.close_reason == "normal" for h in history)


def test_get_history_empty_window_returns_empty_list_not_error(monkeypatch):
    """An empty history window is SUCCESS -> [] (Req 10.4), never an error."""
    _set_creds(monkeypatch)
    transport = make_mock_transport(
        overrides={
            ("GET", "/tradfi/orders/history"): [],
            ("GET", "/tradfi/positions/history"): [],
        }
    )
    clients = _clients(transport)

    history = core.get_history(clients=clients)

    assert history == []


def test_get_history_passes_window_params_to_venue(monkeypatch):
    """since/until are forwarded as venue query params (window readout)."""
    _set_creds(monkeypatch)
    captured: list[dict] = []

    class _SpyClient:
        def request(self, method, path, *, params=None, transport=None, **kw):
            captured.append({"method": method, "path": path, "params": params})
            # Return a structured success with an empty list so the readout is [].
            return gate_client.TransportResult(data=[], status_code=200)

        def get(self, path, *, params=None, transport=None, **kw):
            return self.request("GET", path, params=params, transport=transport)

    clients = core.ReadoutClients(
        gate_client=_SpyClient(),
        symbol_cache=symbol_cache.SymbolCache(
            gate_client=gate_client, transport=make_mock_transport()
        ),
        transport=None,
    )

    core.get_history(since=1748470000, until=1748500000, clients=clients)

    history_calls = [c for c in captured if "history" in c["path"]]
    assert history_calls, "expected the history endpoints to be queried"
    for c in history_calls:
        assert c["params"] is not None
        assert c["params"].get("from") == 1748470000
        assert c["params"].get("to") == 1748500000


def test_get_history_transport_failure_is_surfaced(monkeypatch):
    """A history transport failure is surfaced, never silently empty."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport(fail="rate_limit"))

    with pytest.raises(core.BrokerReadoutError) as excinfo:
        core.get_history(clients=clients)
    assert excinfo.value.error_class == "rate_limit"


# --------------------------------------------------------------------------- #
# No telemetry (Req 9.4).
# --------------------------------------------------------------------------- #


def test_core_emits_no_telemetry_or_decision_trace():
    """Req 9.4: the readout layer emits NO telemetry / decision-trace.

    The invariant is structural — no telemetry/decision-trace module is IMPORTED
    and no emission hook is CALLED. (Narrative docstring/comment prose may mention
    ``decision-trace-telemetry`` to EXPLAIN the boundary — the adapter surfaces
    fill/rate data so that downstream consumer can record slippage; that is the
    no-telemetry invariant being described, not an emission.) We therefore assert
    on import statements and call sites, not on raw prose.
    """
    import ast

    src = (_BROKER_DIR / "core.py").read_text()
    tree = ast.parse(src)

    forbidden_module_substrings = ("decision_trace", "telemetry")
    forbidden_call_names = {"emit_trace", "log_decision", "emit_telemetry"}

    for node in ast.walk(tree):
        # No telemetry/decision-trace MODULE imported.
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not any(
                    s in alias.name.lower() for s in forbidden_module_substrings
                ), f"core.py must import no telemetry module; got import {alias.name!r}"
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").lower()
            assert not any(
                s in mod for s in forbidden_module_substrings
            ), f"core.py must import no telemetry module; got from {node.module!r}"
        # No telemetry-emit CALL.
        if isinstance(node, ast.Call):
            fn = node.func
            name = (
                fn.attr if isinstance(fn, ast.Attribute)
                else fn.id if isinstance(fn, ast.Name)
                else ""
            )
            assert name not in forbidden_call_names, (
                f"core.py readout must emit no telemetry (Req 9.4); "
                f"offending call: {name!r}"
            )
