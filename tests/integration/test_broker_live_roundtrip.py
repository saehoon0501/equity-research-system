"""Task 6.4 — opt-in authenticated live round-trip (P12 / P14 build-time validation).

This is the ONE authenticated round-trip the spec calls the "build-time validation
(P12/P14)" vehicle: before the adapter is trusted, read ``symbols/detail`` for a
known US ticker, read ``users/assets`` + ``users/mt5-account``, and (in PAPER mode)
exercise the order -> poll -> close lifecycle against a LIVE Gate account, asserting
the venue FIELD NAMES + types match what the adapter expects and surfacing the actual
fill data. Source of truth:

  * ``.kiro/specs/broker-cfd-adapter/tasks.md`` task 6.4 (Boundary: tests integration;
    _Requirements: 1.7, 9.3_).
  * ``.kiro/specs/broker-cfd-adapter/gate-api-gaps.md`` "Build-time validation
    (P12/P14)" — names the authenticated symbols/detail + assets + mt5-account read
    plus the paper order->poll->close cycle as the field-name + async/position-id
    lifecycle ground-truth, and ``gate/gate-local-mcp`` (read-only) as the manual
    corroboration vehicle (documented below; we cannot run that npm tool here).
  * ``.kiro/specs/broker-cfd-adapter/gate-tradfi-api-reference.md`` — the operator-
    supplied venue field schema this test asserts the live responses against.

DOUBLE-GUARDED (the whole point of an opt-in live test):

  1. ``@pytest.mark.integration_live`` — deselected by default. The repo-root
     ``tests/conftest.py`` auto-skips ``integration_live`` unless ``-m
     integration_live`` is explicitly passed (so a bare ``pytest`` never reaches the
     venue), and the marker is registered there too.
  2. ``@pytest.mark.skipif(GATE_* unset)`` — even when ``-m integration_live`` IS
     selected, the test SKIPS CLEANLY unless BOTH ``GATE_API_KEY`` and
     ``GATE_API_SECRET`` are present in the environment. The credential probe is a
     pure ``os.environ`` read at COLLECTION time: NO client is constructed and NO HTTP
     is attempted before the skip. In this credential-less environment the test always
     skips (no error, no live call), and collection still succeeds.

Why broker modules are imported INSIDE the test body (not at module top): the
importlib-by-path load of ``core`` (and its dependency chain) is deferred behind the
skipif so that in the credential-less / deselected case, collection only needs stdlib
+ the ``sys.path`` bootstrap. The live readouts + the paper submit all run through the
production ``core`` leaf functions (``default_clients`` real-transport constructor),
so this exercises the REAL signing / transport / mapping path against the live venue —
the P12/P14 round-trip — not a mock.

Run environment: the broker MCP runs in its own ``uv`` venv, but ``tests/integration/``
carries a committed shared ``conftest.py`` (the decision-trace-telemetry
``integration_live`` harness) that imports ``psycopg`` at module top, and the broker
venv deliberately does not carry ``psycopg``. So this live integration test collects
+ skips under the REPO/system Python (where ``psycopg`` / ``dotenv`` / ``httpx`` /
``mcp`` are all present — the same env the rest of ``tests/integration/`` runs in),
selected via::

    pytest tests/integration/test_broker_live_roundtrip.py -m integration_live

with ``GATE_API_KEY`` / ``GATE_API_SECRET`` exported. Without the creds it skips
cleanly; without ``-m integration_live`` it is deselected by the repo-root conftest.

Manual corroboration (``gate/gate-local-mcp`` read-only cross-check)
-------------------------------------------------------------------
The operator decision (gate-api-gaps.md "Vehicle") is to cross-check these live field
names + the async order->poll->close lifecycle against ``gate/gate-local-mcp`` (npm
``gate-mcp`` >=0.19.0) run READ-ONLY (``GATE_READONLY=true --modules=tradfi``). That is
a TypeScript stdio MCP we cannot launch from this Python test harness, so the
cross-check is a MANUAL step: run the local MCP read-only against the same account and
confirm its ``symbols/detail`` / ``users/assets`` / ``users/mt5-account`` /
``orders`` / ``positions`` field names match the assertions below. This test is the
automated half; the gate-local-mcp read is the manual half.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# tests/integration/test_broker_live_roundtrip.py -> parents[2] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"

# The double-guard credential probe — a PURE os.environ read evaluated at collection
# time. Both keys must be present and non-blank; a half-set pair is treated as unset
# (it would fail credential resolution anyway). No client, no network here.
_GATE_KEY = (os.environ.get("GATE_API_KEY") or "").strip()
_GATE_SECRET = (os.environ.get("GATE_API_SECRET") or "").strip()
_HAS_GATE_CREDS = bool(_GATE_KEY and _GATE_SECRET)
_NO_CREDS_REASON = (
    "opt-in live round-trip: GATE_API_KEY/GATE_API_SECRET unset (no live venue call)"
)

# A known US-stock CFD ticker present in the Gate TradFi US-stock category (id 2).
# Used for the symbols/detail read and the paper order->poll->close cycle.
_KNOWN_TICKER = os.environ.get("GATE_LIVE_TEST_TICKER", "AAPL").strip() or "AAPL"


def _load_by_path(alias: str, path: Path):
    """importlib-by-path loader (mirrors the broker unit tests' helper)."""
    spec = importlib.util.spec_from_file_location(alias, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def _load_broker_modules():
    """Load the broker production modules canonical-alias-first.

    LOAD-BEARING ordering (tasks.md Implementation Notes): load ``models`` FIRST under
    its CANONICAL alias ``models`` so every dependent module's ``from models import
    ...`` reuses the SAME class objects (enum / isinstance identity holds), then the
    dependency chain, then ``core``. Called INSIDE the test (post-skip) so collection
    in the credential-less / deselected case needs no broker import.

    Returns a small namespace object exposing the symbols the test uses.
    """
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    # core + deps do by-name sibling imports (`import config`, `from models import …`)
    # — the production launch posture (broker dir on sys.path[0]).
    if str(_BROKER_DIR) not in sys.path:
        sys.path.insert(0, str(_BROKER_DIR))

    models = _load_by_path("models", _BROKER_DIR / "models.py")
    config = _load_by_path("config", _BROKER_DIR / "config.py")
    _load_by_path("mappers", _BROKER_DIR / "mappers.py")
    gate_client = _load_by_path("gate_client", _BROKER_DIR / "gate_client.py")
    _load_by_path("symbol_cache", _BROKER_DIR / "symbol_cache.py")
    _load_by_path("validation", _BROKER_DIR / "validation.py")
    _load_by_path("paper", _BROKER_DIR / "paper.py")
    core = _load_by_path("broker_core", _BROKER_DIR / "core.py")

    class _Ns:
        pass

    ns = _Ns()
    ns.models = models
    ns.config = config
    ns.gate_client = gate_client
    ns.core = core
    return ns


def _assert_isinstance(value, types, field: str) -> None:
    """Assert a parsed domain field has an expected Python type (P13 — HG-23 is
    presence-only, so this test validates the TYPES itself), with a field-named msg."""
    assert isinstance(value, types), (
        f"venue field {field!r} did not parse to {types!r}: got "
        f"{type(value).__name__} = {value!r}"
    )


@pytest.mark.integration_live
@pytest.mark.skipif(not _HAS_GATE_CREDS, reason=_NO_CREDS_REASON)
def test_live_roundtrip_fields_and_paper_lifecycle(monkeypatch):
    """P12/P14 authenticated round-trip against a LIVE Gate TradFi account.

    Reached ONLY when ``-m integration_live`` is selected AND both GATE_* creds are
    present. It performs, all through the production ``core`` leaf functions (real
    signing / transport / mapping — not a mock):

    1. **symbols/detail** for ``_KNOWN_TICKER`` via ``core.validate_symbol`` ->
       ``SymbolInfo``: assert the venue field NAMES + types the adapter expects
       (ticker / leverage / min+max_order_volume / price_precision / swap rates /
       trade_mode / status) all parsed (gate-tradfi-api-reference symbols/detail row).
    2. **users/assets + users/mt5-account** via ``core.get_account_assets`` ->
       ``AccountAssets``: assert equity / used+free margin / margin_level / balance
       (assets) and ``stop_out_level`` (mt5-account) parsed to floats — and that the
       account is the ACTIVE one (mt5-account ``status`` == 3) so the paper cycle runs
       against a real, funded account's data (Req 9.3 surfaces real account data).
    3. **PAPER order -> poll -> close** lifecycle (Req 1.7) with paper mode ON (NO
       real-money order): a BUY ``submit_decision`` returns ``status="simulated"``
       priced from the live bid/ask (no POST), then — if a real position exists — a
       SELL close by ``position_id`` is simulated. This confirms the async /
       position-id lifecycle WIRING end-to-end against the live account's data and
       surfaces the actual fill data (Req 9.3). Paper stays ON throughout: the
       assertions REQUIRE ``status == "simulated"`` (never ``filled``), which is the
       structural proof that no live-money order was transmitted.
    """
    b = _load_broker_modules()
    core = b.core
    config = b.config
    models = b.models
    Label = models.Label
    Direction = models.Direction
    SymbolInfo = models.SymbolInfo
    AccountAssets = models.AccountAssets
    Position = models.Position

    # Production clients (real httpx transport, real SymbolCache). The credentials are
    # resolved FRESH per call from the environment we just guarded on.
    clients = core.default_clients()

    # --- (1) symbols/detail field-name + type ground-truth (P12/P14) ----------- #
    resolved = core.validate_symbol(_KNOWN_TICKER, clients=clients)
    assert isinstance(resolved, SymbolInfo), (
        f"known US ticker {_KNOWN_TICKER!r} did not resolve to a SymbolInfo against "
        f"the live venue (got {resolved!r}) — symbols/detail field names may have "
        "drifted from gate-tradfi-api-reference, or the ticker is out of category 2"
    )
    assert resolved.ticker == _KNOWN_TICKER
    # Identity is the US ticker only (Req 4.1) — never the free-text description.
    _assert_isinstance(resolved.leverage, float, "symbols/detail.leverage")
    assert resolved.leverage > 0, "leverage must be a positive per-symbol value"
    _assert_isinstance(
        resolved.min_order_volume, float, "symbols/detail.min_order_volume"
    )
    _assert_isinstance(
        resolved.max_order_volume, float, "symbols/detail.max_order_volume"
    )
    assert resolved.max_order_volume >= resolved.min_order_volume
    _assert_isinstance(resolved.price_precision, int, "symbols/detail.price_precision")
    _assert_isinstance(resolved.buy_swap_rate, float, "symbols/detail.buy_swap_cost_rate")
    _assert_isinstance(
        resolved.sell_swap_rate, float, "symbols/detail.sell_swap_cost_rate"
    )
    # trade_mode + status are venue-supplied strings the validation layer interprets.
    _assert_isinstance(resolved.trade_mode, str, "symbols(detail/universe).trade_mode")
    _assert_isinstance(resolved.status, str, "symbols.status")

    # --- (2) users/assets + users/mt5-account field-name + type ground-truth ---- #
    assets = core.get_account_assets(clients=clients)
    assert isinstance(assets, AccountAssets)
    _assert_isinstance(assets.equity, float, "users/assets.equity")
    _assert_isinstance(assets.used_margin, float, "users/assets.margin")
    _assert_isinstance(assets.free_margin, float, "users/assets.margin_free")
    _assert_isinstance(assets.margin_level, float, "users/assets.margin_level")
    _assert_isinstance(assets.balance, float, "users/assets.balance")
    # Req 3.2: stop_out_level is surfaced verbatim from mt5-account (the adapter
    # computes NO liquidation distance). Field-name ground-truth for the survival input.
    _assert_isinstance(assets.stop_out_level, float, "users/mt5-account.stop_out_level")

    # The mt5-account read must report an ACTIVE account (status == 3) for the paper
    # cycle to be a meaningful round-trip against a real account's data. We assert the
    # raw field name + enum the adapter keys account-active off of.
    mt5_outcome = core._gate_client.request(
        "GET", core._MT5_ACCOUNT_PATH, transport=clients.transport
    )
    assert getattr(mt5_outcome, "ok", False) is True, (
        "users/mt5-account read failed against the live venue: "
        f"{getattr(mt5_outcome, 'error', mt5_outcome)!r}"
    )
    assert isinstance(mt5_outcome.data, dict)
    assert "status" in mt5_outcome.data, (
        "users/mt5-account response missing the 'status' field the adapter keys "
        "account-active off of (gate-tradfi-api-reference: 1=not opened, 2=pending, "
        "3=active)"
    )
    assert int(mt5_outcome.data["status"]) == core._ACCOUNT_STATUS_ACTIVE, (
        "TradFi account is not ACTIVE (status != 3); activate the account before "
        "running the live round-trip (gate-tradfi-api-reference: account status enum)"
    )

    # --- (3) PAPER order -> poll -> close lifecycle (Req 1.7, 9.3) ------------- #
    # Paper mode ON + active account: the BUY runs the FULL validate-then-simulate
    # path (snapshot + chain + mapping) and prices from the LIVE bid/ask with NO order
    # POST. The 'simulated' status is the structural guarantee no real-money order
    # transmits. min_order_volume keeps the simulated intent venue-valid.
    paper_mode = config.RuntimeMode(paper_enabled=True, account_active=True)
    buy_result = core.submit_decision(
        Label.BUY,
        _KNOWN_TICKER,
        Direction.LONG,
        volume=resolved.min_order_volume,
        clients=clients,
        runtime_mode=paper_mode,
    )
    assert buy_result.status == "simulated", (
        "paper BUY must simulate (NO live order) — got "
        f"status={buy_result.status!r}, reason={buy_result.reason!r}. A non-simulated "
        "status here would mean either the chain rejected (field/session drift) or, "
        "worse, a live POST was attempted with paper mode ON."
    )
    # Req 9.3: the actual fill data is surfaced — priced from the live venue bid/ask.
    assert buy_result.fill_price is not None and buy_result.fill_price > 0, (
        "paper BUY did not surface a fill_price priced from the live bid/ask "
        f"(got {buy_result.fill_price!r}); symbols/{_KNOWN_TICKER}/tickers field names "
        "(bid_price/ask_price) may have drifted"
    )
    assert buy_result.fill_volume == resolved.min_order_volume, (
        "paper BUY fill_volume must equal the REQUESTED volume verbatim (Req 7.1 — "
        f"never upsized); got {buy_result.fill_volume!r}"
    )

    # Poll the live positions book (the async/position-id lifecycle read the live close
    # would correlate against) and, if a real position exists for the ticker, exercise
    # the SELL close-by-position-id leg — still in PAPER (simulated), confirming the
    # position-id wiring end-to-end without transmitting a real close.
    positions = core.get_positions(clients=clients)
    assert isinstance(positions, list)
    target = next(
        (p for p in positions if isinstance(p, Position) and p.symbol == _KNOWN_TICKER),
        None,
    )
    if target is not None:
        # Field-name ground-truth on the live position object (Req 1.9 position_id +
        # Req 2.2 venue unrealized_pnl verbatim).
        _assert_isinstance(target.position_id, str, "positions.position_id")
        _assert_isinstance(target.volume, float, "positions.volume")
        _assert_isinstance(target.avg_open_price, float, "positions.price_open")
        _assert_isinstance(target.used_margin, float, "positions.margin")
        _assert_isinstance(target.unrealized_pnl, float, "positions.unrealized_pnl")

        close_result = core.submit_decision(
            Label.SELL,
            _KNOWN_TICKER,
            target.direction,
            position_id=target.position_id,
            clients=clients,
            runtime_mode=paper_mode,
        )
        assert close_result.status == "simulated", (
            "paper SELL close must simulate (NO live close) — got "
            f"status={close_result.status!r}, reason={close_result.reason!r}"
        )
        # The close echoes the caller-supplied position_id (Req 1.9 — acts only on it).
        assert close_result.position_id == target.position_id
    else:
        # No open position for the ticker: a naked SELL with no position MUST be
        # rejected (Req 1.8) — assert that conservative leg so the position-id close
        # path is still exercised against the live (empty) book.
        naked_sell = core.submit_decision(
            Label.SELL,
            _KNOWN_TICKER,
            Direction.LONG,
            position_id="POS-DOES-NOT-EXIST",
            clients=clients,
            runtime_mode=paper_mode,
        )
        assert naked_sell.status == "rejected", (
            "a SELL close against a non-existent position_id must be rejected "
            f"(Req 1.8); got status={naked_sell.status!r}"
        )
        assert naked_sell.reason is not None
        assert naked_sell.reason.code == models.RejectionCode.NO_POSITION
