"""Unit tests for decision routing, the pre-transmit snapshot, and live-send
gating (Task 4.2).

Covers the design "Operations layer -> core" component, the ORDER-ROUTING portion
(``submit_decision`` + the one pre-transmit snapshot + the 4-condition live-send
gate). The readout portion (4.1) lives in ``test_broker_core_readouts.py`` and is
NOT touched here; the async poll-loop + double-send guard hardening is 4.3.

Requirements:
    1.1  BUY -> open/increase in the requested direction.
    1.2  TRIM -> partial close by position_id.
    1.3  SELL -> full close by position_id.
    1.4  HOLD -> structured no-op, no transmit.
    1.8  TRIM/SELL with no matching position -> rejected, no position opened.
    1.9  Act only on the caller-supplied position_id (never self-select).
    1.10 Inactive account -> rejected (all order/close ops).
    7.1  Never autonomously increase the requested volume.
    7.3  No sizing/scoring/trigger decisions (volume/side surfaced verbatim).
    8.1  v0.1 paper-only: no live path transmits by default.
    8.3  Live only if paper off AND active AND clearance AND kill clear.
    8.4  Kill switch engaged -> refuse live.
    8.5  Any clearance absent -> refuse live (LIVE_SEND_BLOCKED, no POST).

Design: the "core (leaf functions)" Responsibilities & Constraints block (the
single pre-transmit snapshot whose ONE positions read feeds both the 1.8 check
and the 7.4 guard), the System Flows "Order submission" sequence + "Live-send
gating" state machine, and the Requirements Traceability rows above.

Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \\
        tests/unit/mcp/test_broker_core_orders.py -q

The broker runs in its own uv venv (carries ``mcp`` / ``httpx``); the repo root
is NOT on ``sys.path``. Broker modules are loaded by path (importlib-by-path under
unique aliases), loading ``models`` FIRST under its canonical alias so dependent
modules' ``from models import ...`` reuse the SAME class objects (enum / isinstance
identity holds) — mirrors ``test_broker_core_readouts.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Repo root: tests/unit/mcp/test_broker_core_orders.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"
# core + its deps do by-name sibling imports (`import config`, `import mappers`,
# `from models import ...`, `import gate_client`, etc.) — the production posture.
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

# LOAD-BEARING ordering: ``models`` FIRST under its canonical alias, then deps,
# then the unit-under-test. (Identity of Label / Direction / RejectionCode must be
# the SAME instances the production modules close over.)
broker_models = _load_by_path("models", _BROKER_DIR / "models.py")
broker_config = _load_by_path("config", _BROKER_DIR / "config.py")
broker_mappers = _load_by_path("mappers", _BROKER_DIR / "mappers.py")
gate_client = _load_by_path("gate_client", _BROKER_DIR / "gate_client.py")
symbol_cache = _load_by_path("symbol_cache", _BROKER_DIR / "symbol_cache.py")
validation = _load_by_path("validation", _BROKER_DIR / "validation.py")
paper = _load_by_path("paper", _BROKER_DIR / "paper.py")
core = _load_by_path("broker_core", _BROKER_DIR / "core.py")

Label = broker_models.Label
Direction = broker_models.Direction
OrderType = broker_models.OrderType
OrderResult = broker_models.OrderResult
RejectionCode = broker_models.RejectionCode
RejectionReason = broker_models.RejectionReason
RuntimeMode = broker_config.RuntimeMode

load_fixture = broker_gate_fakes.load_fixture
make_mock_transport = broker_gate_fakes.make_mock_transport


# --------------------------------------------------------------------------- #
# Helpers / fixtures.
# --------------------------------------------------------------------------- #


def _set_creds(monkeypatch, key: str = "k-test", secret: str = "s-test") -> None:
    """The /tradfi reads + any live POST are authenticated — creds resolved fresh."""
    monkeypatch.setenv("GATE_API_KEY", key)
    monkeypatch.setenv("GATE_API_SECRET", secret)


def _clients(transport):
    """Build the clients holder with the real gate_client + a mock-backed
    SymbolCache, both wired to an injected (mock) transport — reuses the 4.1
    ``ReadoutClients`` DI seam (no parallel holder per the task contract)."""
    cache = symbol_cache.SymbolCache(gate_client=gate_client, transport=transport)
    return core.ReadoutClients(
        gate_client=gate_client, symbol_cache=cache, transport=transport
    )


# An ACTIVE account by default for the order tests; the snapshot reads
# mt5-account status, but tests drive account_active through the runtime_mode the
# snapshot folds in (active path) unless a test overrides it.
def _paper_mode(active: bool = True) -> RuntimeMode:
    """Paper-default runtime mode (v0.1). ``account_active`` toggled for 1.10."""
    return RuntimeMode(paper_enabled=True, account_active=active)


def _live_cleared_mode() -> RuntimeMode:
    """A runtime mode where ALL FOUR live-send conditions hold — forces the live
    path (otherwise unreachable in v0.1 paper-default) so ``_submit_live`` runs."""
    return RuntimeMode(
        paper_enabled=False,
        account_active=True,
        survival_clearance=True,
        kill_switch_clear=True,
    )


# --------------------------------------------------------------------------- #
# 1.4 — HOLD is a structured no-op and transmits nothing.
# --------------------------------------------------------------------------- #


def test_hold_returns_noop_and_transmits_nothing(monkeypatch):
    """HOLD -> OrderResult(status='noop'); no validation snapshot fetch, no POST
    (Req 1.4)."""
    _set_creds(monkeypatch)

    posted: list[tuple] = []

    class _NoPostClient:
        """A client that records any POST so we can assert none happened."""

        def request(self, method, path, *, params=None, body=None, transport=None, **kw):
            if method.upper() == "POST":
                posted.append((method, path))
            return gate_client.TransportResult(data=[], status_code=200)

    clients = core.ReadoutClients(
        gate_client=_NoPostClient(),
        symbol_cache=symbol_cache.SymbolCache(
            gate_client=gate_client, transport=make_mock_transport()
        ),
        transport=None,
    )

    result = core.submit_decision(
        Label.HOLD,
        "AAPL",
        Direction.LONG,
        clients=clients,
        runtime_mode=_paper_mode(),
    )

    assert isinstance(result, OrderResult)
    assert result.status == "noop"
    assert posted == [], "HOLD must transmit nothing (Req 1.4)"


# --------------------------------------------------------------------------- #
# 1.1 / 8.1 / 8.2 — BUY in paper mode -> simulated, priced from bid/ask, NO POST.
# --------------------------------------------------------------------------- #


def test_buy_in_paper_mode_is_simulated_with_no_order_post(monkeypatch):
    """BUY (LONG) in paper mode -> OrderResult(status='simulated') priced from the
    venue ticker bid/ask, with NO order-create POST issued (Req 1.1, 8.1, 8.2)."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport())

    result = core.submit_decision(
        Label.BUY,
        "AAPL",
        Direction.LONG,
        volume=1.0,
        clients=clients,
        runtime_mode=_paper_mode(),
    )

    assert result.status == "simulated"
    # LONG entry = buy-to-open -> fills at the ASK (symbol_tickers fixture ask 212.41).
    assert result.fill_price == pytest.approx(212.41)
    # 7.1: the requested volume is surfaced verbatim — never upsized.
    assert result.fill_volume == pytest.approx(1.0)
    assert result.raw is not None and result.raw.get("simulated") is True


def test_paper_buy_issues_no_post_asserted_against_spy(monkeypatch):
    """Stronger 8.1/8.2 assertion: NO POST reaches the venue in paper mode."""
    _set_creds(monkeypatch)
    base = make_mock_transport()
    posted: list[tuple] = []

    class _SpyClient:
        def request(self, method, path, *, params=None, body=None, transport=None, **kw):
            if method.upper() == "POST":
                posted.append((method, path))
            return gate_client.request(
                method, path, params=params, body=body, transport=base
            )

        def get(self, path, *, params=None, transport=None, **kw):
            return self.request("GET", path, params=params, transport=base)

    clients = core.ReadoutClients(
        gate_client=_SpyClient(),
        symbol_cache=symbol_cache.SymbolCache(gate_client=gate_client, transport=base),
        transport=None,
    )

    result = core.submit_decision(
        Label.BUY,
        "AAPL",
        Direction.LONG,
        volume=2.0,
        clients=clients,
        runtime_mode=_paper_mode(),
    )

    assert result.status == "simulated"
    assert posted == [], "paper mode must issue no order/close POST (Req 8.1/8.2)"


# --------------------------------------------------------------------------- #
# 1.2 / 1.3 — TRIM / SELL with an existing position -> simulated close, no POST.
# --------------------------------------------------------------------------- #


def test_trim_existing_position_simulated_close_no_post(monkeypatch):
    """TRIM with an existing AAPL long position (POS-500001) in paper mode ->
    simulated partial close, no POST (Req 1.2, 1.9, 8.2)."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport())

    result = core.submit_decision(
        Label.TRIM,
        "AAPL",
        Direction.LONG,
        volume=0.5,
        position_id="POS-500001",
        clients=clients,
        runtime_mode=_paper_mode(),
    )

    assert result.status == "simulated"
    assert result.position_id == "POS-500001"
    # Closing a LONG sells -> fills at the BID (212.34); volume surfaced verbatim.
    assert result.fill_price == pytest.approx(212.34)
    assert result.fill_volume == pytest.approx(0.5)


def test_sell_existing_position_simulated_full_close(monkeypatch):
    """SELL with an existing position -> simulated FULL close (no request volume);
    no POST (Req 1.3)."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport())

    result = core.submit_decision(
        Label.SELL,
        "AAPL",
        Direction.LONG,
        position_id="POS-500001",
        clients=clients,
        runtime_mode=_paper_mode(),
    )

    assert result.status == "simulated"
    assert result.position_id == "POS-500001"
    assert result.fill_price == pytest.approx(212.34)  # close a long -> BID


# --------------------------------------------------------------------------- #
# 1.8 — TRIM/SELL with NO matching position -> rejected, no position opened.
# --------------------------------------------------------------------------- #


def test_trim_with_no_position_is_rejected_no_open(monkeypatch):
    """A TRIM whose position_id matches no open position -> rejected NO_POSITION,
    and NO new position is opened (Req 1.8)."""
    _set_creds(monkeypatch)
    base = make_mock_transport()
    posted: list[tuple] = []

    class _SpyClient:
        def request(self, method, path, *, params=None, body=None, transport=None, **kw):
            if method.upper() == "POST":
                posted.append((method, path))
            return gate_client.request(
                method, path, params=params, body=body, transport=base
            )

        def get(self, path, *, params=None, transport=None, **kw):
            return self.request("GET", path, params=params, transport=base)

    clients = core.ReadoutClients(
        gate_client=_SpyClient(),
        symbol_cache=symbol_cache.SymbolCache(gate_client=gate_client, transport=base),
        transport=None,
    )

    result = core.submit_decision(
        Label.SELL,
        "AAPL",
        Direction.LONG,
        position_id="POS-DOES-NOT-EXIST",
        clients=clients,
        runtime_mode=_paper_mode(),
    )

    assert result.status == "rejected"
    assert result.reason is not None
    assert result.reason.code is RejectionCode.NO_POSITION
    assert posted == [], "a TRIM/SELL miss must open NO position (Req 1.8)"


# --------------------------------------------------------------------------- #
# 1.10 — inactive account -> rejected.
# --------------------------------------------------------------------------- #


def test_inactive_account_rejects(monkeypatch):
    """An inactive account rejects all order/close ops (Req 1.10).

    The authoritative active flag is the live ``mt5-account.status`` read (venue
    enum: 3=active). Override it to 2 (pending review) so the snapshot resolves the
    account as NOT active and the chain rejects with INACTIVE_ACCOUNT.
    """
    _set_creds(monkeypatch)
    transport = make_mock_transport(
        overrides={
            ("GET", "/tradfi/users/mt5-account"): {
                "leverage": "5",
                "stop_out_level": "50",
                "status": 2,  # pending review -> NOT active (only 3 is active).
                "settlement_currency": "USD",
            }
        }
    )
    clients = _clients(transport)

    result = core.submit_decision(
        Label.BUY,
        "AAPL",
        Direction.LONG,
        volume=1.0,
        clients=clients,
        runtime_mode=_paper_mode(active=False),
    )

    assert result.status == "rejected"
    assert result.reason is not None
    assert result.reason.code is RejectionCode.INACTIVE_ACCOUNT


# --------------------------------------------------------------------------- #
# 8.1 — v0.1 paper-default never transmits live.
# --------------------------------------------------------------------------- #


def test_v01_paper_default_never_transmits_live(monkeypatch):
    """With the DEFAULT runtime mode (paper on, all clearances safe-default), a BUY
    is simulated and NO live POST occurs (Req 8.1)."""
    _set_creds(monkeypatch)
    base = make_mock_transport()
    posted: list[tuple] = []

    class _SpyClient:
        def request(self, method, path, *, params=None, body=None, transport=None, **kw):
            if method.upper() == "POST":
                posted.append((method, path))
            return gate_client.request(
                method, path, params=params, body=body, transport=base
            )

        def get(self, path, *, params=None, transport=None, **kw):
            return self.request("GET", path, params=params, transport=base)

    clients = core.ReadoutClients(
        gate_client=_SpyClient(),
        symbol_cache=symbol_cache.SymbolCache(gate_client=gate_client, transport=base),
        transport=None,
    )

    # Default RuntimeMode() == v0.1 posture, BUT account must be active to pass the
    # 1.10 gate; default account_active=False would reject earlier. Use an active
    # paper mode so we reach the (paper) simulate branch and prove no live POST.
    result = core.submit_decision(
        Label.BUY,
        "AAPL",
        Direction.LONG,
        volume=1.0,
        clients=clients,
        runtime_mode=_paper_mode(active=True),
    )

    assert result.status == "simulated"
    assert posted == [], "v0.1 paper-default must transmit no live order (Req 8.1)"


# --------------------------------------------------------------------------- #
# 8.3 / 8.4 / 8.5 — paper disabled but a clearance missing / kill engaged ->
# LIVE_SEND_BLOCKED refusal, NO POST.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "mode",
    [
        # paper off, account active, clearance present, but kill switch NOT clear (8.4).
        RuntimeMode(
            paper_enabled=False,
            account_active=True,
            survival_clearance=True,
            kill_switch_clear=False,
        ),
        # paper off, account active, kill clear, but survival clearance MISSING (8.5).
        RuntimeMode(
            paper_enabled=False,
            account_active=True,
            survival_clearance=False,
            kill_switch_clear=True,
        ),
    ],
)
def test_live_send_blocked_when_clearance_missing_or_kill_engaged(monkeypatch, mode):
    """Paper disabled but at least one of the four live conditions absent ->
    LIVE_SEND_BLOCKED, no transmit (Req 8.3/8.4/8.5)."""
    _set_creds(monkeypatch)
    base = make_mock_transport()
    posted: list[tuple] = []

    class _SpyClient:
        def request(self, method, path, *, params=None, body=None, transport=None, **kw):
            if method.upper() == "POST":
                posted.append((method, path))
            return gate_client.request(
                method, path, params=params, body=body, transport=base
            )

        def get(self, path, *, params=None, transport=None, **kw):
            return self.request("GET", path, params=params, transport=base)

    clients = core.ReadoutClients(
        gate_client=_SpyClient(),
        symbol_cache=symbol_cache.SymbolCache(gate_client=gate_client, transport=base),
        transport=None,
    )

    result = core.submit_decision(
        Label.BUY,
        "AAPL",
        Direction.LONG,
        volume=1.0,
        clients=clients,
        runtime_mode=mode,
    )

    assert result.status == "rejected"
    assert result.reason is not None
    assert result.reason.code is RejectionCode.LIVE_SEND_BLOCKED
    assert posted == [], "a refused live send must transmit nothing (Req 8.5)"


# --------------------------------------------------------------------------- #
# 7.1 / 7.3 — never upsize the requested volume.
# --------------------------------------------------------------------------- #


def test_volume_never_upsized(monkeypatch):
    """The simulated fill volume equals the REQUESTED volume exactly — never
    increased or rounded up (Req 7.1, 7.3)."""
    _set_creds(monkeypatch)
    clients = _clients(make_mock_transport())

    requested = 3.0
    result = core.submit_decision(
        Label.BUY,
        "AAPL",
        Direction.LONG,
        volume=requested,
        clients=clients,
        runtime_mode=_paper_mode(),
    )

    assert result.status == "simulated"
    assert result.fill_volume == pytest.approx(requested)
    assert result.fill_volume <= requested, "adapter must never upsize (Req 7.1)"


# --------------------------------------------------------------------------- #
# Snapshot: ONE positions read, gathered once and exposed for the 4.3 reuse seam.
# --------------------------------------------------------------------------- #


def test_one_pre_transmit_snapshot_positions_read_once_and_exposed(monkeypatch):
    """The pre-transmit snapshot reads ``/tradfi/positions`` EXACTLY ONCE, and that
    single positions read is exposed on the snapshot for the 4.3 double-send guard
    to reuse (design: one read feeds both 1.8 and 7.4)."""
    _set_creds(monkeypatch)
    base = make_mock_transport()
    positions_reads: list[str] = []

    class _CountingClient:
        def request(self, method, path, *, params=None, body=None, transport=None, **kw):
            if method.upper() == "GET" and path == "/tradfi/positions":
                positions_reads.append(path)
            return gate_client.request(
                method, path, params=params, body=body, transport=base
            )

        def get(self, path, *, params=None, transport=None, **kw):
            return self.request("GET", path, params=params, transport=base)

    clients = core.ReadoutClients(
        gate_client=_CountingClient(),
        symbol_cache=symbol_cache.SymbolCache(gate_client=gate_client, transport=base),
        transport=None,
    )

    snapshot = core.gather_snapshot(
        "AAPL", clients=clients, runtime_mode=_paper_mode()
    )

    # ONE positions read for the whole snapshot (Req 7.4 / design "one read").
    assert positions_reads == ["/tradfi/positions"], (
        f"expected exactly one positions read; got {positions_reads!r}"
    )
    # The positions read is EXPOSED on the snapshot so 4.3 reuses it (no refetch).
    assert hasattr(snapshot, "open_positions")
    assert any(p.position_id == "POS-500001" for p in snapshot.open_positions)
    # And the snapshot carries the ValidationContext core hands to validation.
    assert isinstance(snapshot.context, validation.ValidationContext)
    assert snapshot.context.open_positions is snapshot.open_positions


# --------------------------------------------------------------------------- #
# Live path seam (4.3 will harden) — with all four clearances FORCED on,
# ``_submit_live`` issues a POST and returns a confirmed result (basic path).
# --------------------------------------------------------------------------- #


def test_live_send_when_cleared_posts_and_confirms(monkeypatch):
    """With paper disabled and all four live conditions satisfied, ``_submit_live``
    transmits via gate_client (a POST) and confirms by reading back orders/positions
    — returning a non-simulated, non-rejected OrderResult. (Unreachable in v0.1
    paper-default; forced here to exercise the seam 4.3 hardens.)"""
    _set_creds(monkeypatch)
    base = make_mock_transport()
    posted: list[tuple] = []

    class _SpyClient:
        def request(self, method, path, *, params=None, body=None, transport=None, **kw):
            if method.upper() == "POST":
                posted.append((method, path))
            return gate_client.request(
                method, path, params=params, body=body, transport=base
            )

        def get(self, path, *, params=None, transport=None, **kw):
            return self.request("GET", path, params=params, transport=base)

    clients = core.ReadoutClients(
        gate_client=_SpyClient(),
        symbol_cache=symbol_cache.SymbolCache(gate_client=gate_client, transport=base),
        transport=None,
    )

    result = core.submit_decision(
        Label.BUY,
        "AAPL",
        Direction.LONG,
        volume=1.0,
        clients=clients,
        runtime_mode=_live_cleared_mode(),
    )

    # A real (basic) transmit happened: an order-create POST was issued.
    assert any(p == ("POST", "/tradfi/orders") for p in posted), (
        f"expected a live order-create POST; got {posted!r}"
    )
    # Not simulated, not rejected — the live path returned a structured outcome.
    assert result.status in ("filled", "unconfirmed")
    # The venue queue-task-id is retained on the result for the 4.3 guard to
    # correlate before any resend.
    assert result.raw is not None
    assert result.raw.get("queue_task_id") == "QTASK-7f3a91c4-2026-05-29"


def test_live_send_close_posts_to_close_endpoint(monkeypatch):
    """A live SELL on an existing position closes via the position-close POST
    (basic path) — confirming the close route, not the open route."""
    _set_creds(monkeypatch)
    base = make_mock_transport()
    posted: list[tuple] = []

    class _SpyClient:
        def request(self, method, path, *, params=None, body=None, transport=None, **kw):
            if method.upper() == "POST":
                posted.append((method, path))
            return gate_client.request(
                method, path, params=params, body=body, transport=base
            )

        def get(self, path, *, params=None, transport=None, **kw):
            return self.request("GET", path, params=params, transport=base)

    clients = core.ReadoutClients(
        gate_client=_SpyClient(),
        symbol_cache=symbol_cache.SymbolCache(gate_client=gate_client, transport=base),
        transport=None,
    )

    result = core.submit_decision(
        Label.SELL,
        "AAPL",
        Direction.LONG,
        position_id="POS-500001",
        clients=clients,
        runtime_mode=_live_cleared_mode(),
    )

    assert any(
        m == "POST" and p.endswith("/close") for (m, p) in posted
    ), f"expected a position-close POST; got {posted!r}"
    assert result.status in ("filled", "unconfirmed")


# --------------------------------------------------------------------------- #
# No unused-import regression: core.py must not carry the dead 4.1 ``import httpx``.
# --------------------------------------------------------------------------- #


def test_core_does_not_import_httpx_directly():
    """4.1 left an unused ``import httpx`` in core.py; 4.2 removes it (core does its
    transport via gate_client / paper, never httpx directly)."""
    import ast

    src = (_BROKER_DIR / "core.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "httpx", "core.py must not import httpx directly"
        if isinstance(node, ast.ImportFrom):
            assert node.module != "httpx", "core.py must not import from httpx"
