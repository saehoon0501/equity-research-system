"""Unit tests for the async order lifecycle + double-send guard (Task 4.3).

Hardens the live submit path (``_submit_live`` / the confirm helpers) that Task
4.2 left as a basic single read-back. Covers the design "Operations layer -> core"
async submit->poll->reconcile lifecycle and the 7.4 double-send guard:

Requirements:
    1.7  Async — placement returns a queue-task-id (not a fill); confirm the
         resulting order/position by POLLING active orders/positions, never assume
         a synchronous fill.
    7.4  Double-send guard — before re-submitting an order whose prior submission
         is unconfirmed, correlate the retained queue-task-id against active
         orders/positions; do NOT transmit a duplicate if the prior submission
         already produced an order/position.
    9.2  An unconfirmed async outcome is surfaced as ``unconfirmed`` (never assumed
         filled).

Design: System Flows "Order submission (async submit -> poll -> reconcile, with
double-send guard)" sequence; the "core (leaf functions)" Responsibilities (owns
the async submit->poll->reconcile loop + double-send guard; reuses the snapshot's
single positions read; surfaces ``unconfirmed``); Error Handling "Async
uncertainty".

Scope guard: the 4.1 readouts (``test_broker_core_readouts.py``) and the 4.2
routing/gating/snapshot tests (``test_broker_core_orders.py``) are NOT touched by
this file — they remain the contract for those behaviors; this file ONLY exercises
the 4.3 hardening of the live lifecycle.

Test-run mechanism (canonical broker pytest command):
    PYTHONSAFEPATH=1 uv run --directory src/mcp/broker python -m pytest \\
        tests/unit/mcp/test_broker_core_lifecycle.py -q

The broker runs in its own uv venv (carries ``mcp`` / ``httpx``); the repo root is
NOT on ``sys.path``. Broker modules are loaded by path (importlib-by-path under
unique aliases), loading ``models`` FIRST under its canonical alias so dependent
modules' ``from models import ...`` reuse the SAME class objects (enum / isinstance
identity holds) — mirrors ``test_broker_core_orders.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Repo root: tests/unit/mcp/test_broker_core_lifecycle.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BROKER_DIR = _REPO_ROOT / "src" / "mcp" / "broker"
# core + its deps do by-name sibling imports (production posture).
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

# LOAD-BEARING ordering: ``models`` FIRST under its canonical alias, then deps, then
# the unit-under-test (Label / Direction / RejectionCode identity must match the
# instances the production modules close over).
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
RuntimeMode = broker_config.RuntimeMode

load_fixture = broker_gate_fakes.load_fixture
make_mock_transport = broker_gate_fakes.make_mock_transport

# The queue-task-id the orders_create fixture acks with (the 7.4 correlation key).
_QTASK_ID = "QTASK-7f3a91c4-2026-05-29"


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _set_creds(monkeypatch, key: str = "k-test", secret: str = "s-test") -> None:
    """The /tradfi reads + any live POST are authenticated — creds resolved fresh."""
    monkeypatch.setenv("GATE_API_KEY", key)
    monkeypatch.setenv("GATE_API_SECRET", secret)


def _live_cleared_mode() -> RuntimeMode:
    """A runtime mode where ALL FOUR live-send conditions hold — forces the live
    path (otherwise unreachable in v0.1 paper-default) so ``_submit_live`` runs."""
    return RuntimeMode(
        paper_enabled=False,
        account_active=True,
        survival_clearance=True,
        kill_switch_clear=True,
    )


class _ScriptedClient:
    """A gate_client stand-in that scripts per-route responses so a test can model
    the venue's async behavior (an order/position that APPEARS only after N polls).

    It records every call (method, path, body) for assertions (POST counting, poll
    counting) and delegates to the real ``gate_client.request`` against a baseline
    mock transport for routes a test does not script (mt5-account/assets/symbols/
    tickers used by the snapshot). Scripted routes are functions ``() -> data`` (the
    raw venue JSON) invoked per call so a test can return different payloads across
    successive polls.
    """

    def __init__(self, base_transport, *, scripts=None):
        self._base = base_transport
        self._scripts = scripts or {}
        self.calls: list[tuple[str, str]] = []
        self.posts: list[tuple[str, str]] = []
        self.get_counts: dict[str, int] = {}

    def request(self, method, path, *, params=None, body=None, transport=None, **kw):
        method = method.upper()
        self.calls.append((method, path))
        if method == "POST":
            self.posts.append((method, path))
        if method == "GET":
            self.get_counts[path] = self.get_counts.get(path, 0) + 1
        script = self._scripts.get((method, path))
        if script is not None:
            data = script()
            return gate_client.TransportResult(data=data, status_code=200)
        return gate_client.request(
            method, path, params=params, body=body, transport=self._base
        )

    def get(self, path, *, params=None, transport=None, **kw):
        return self.request("GET", path, params=params, transport=self._base)


def _clients(client) -> "core.ReadoutClients":
    """Build the ReadoutClients holder around a scripted/spy client. The SymbolCache
    uses the real gate_client + a baseline mock transport (the snapshot's symbol /
    ticker / assets reads need real fixtures); the order-path GETs/POSTs route
    through the scripted client."""
    base = make_mock_transport()
    cache = symbol_cache.SymbolCache(gate_client=gate_client, transport=base)
    return core.ReadoutClients(gate_client=client, symbol_cache=cache, transport=None)


# --------------------------------------------------------------------------- #
# (a) Async confirm: submit -> queue-task-id, position APPEARS on a later poll ->
#     filled with fill data; the injected sleep shows polling/backoff happened.
# --------------------------------------------------------------------------- #


def test_async_buy_confirmed_when_order_appears_on_later_poll(monkeypatch):
    """A live BUY: the POST acks with a queue-task-id; the resulting order is NOT
    visible on the first poll but APPEARS (finished) on a later poll -> the result
    is ``filled`` with the venue fill, and the injected sleep proves the loop
    polled/backed off across attempts (Req 1.7)."""
    _set_creds(monkeypatch)
    base = make_mock_transport()

    # The order is invisible for the first two polls, then appears finished (filled)
    # on the third — carrying the queue-task-id the POST acked with.
    poll_state = {"n": 0}
    filled_order = {
        "order_id": "ORD-NEW-1",
        "symbol": "AAPL",
        "side": broker_mappers.SIDE_BUY,
        "queue_task_id": _QTASK_ID,
        "finished": True,
        "volume": "1.00",
        "price": "212.55",
    }

    def _orders_script():
        poll_state["n"] += 1
        # Empty for polls 1-2, the filled order on poll 3+.
        return [] if poll_state["n"] < 3 else [filled_order]

    client = _ScriptedClient(base, scripts={("GET", "/tradfi/orders"): _orders_script})
    clients = _clients(client)

    sleeps: list[float] = []

    result = core.submit_decision(
        Label.BUY,
        "AAPL",
        Direction.LONG,
        volume=1.0,
        clients=clients,
        runtime_mode=_live_cleared_mode(),
        poll_sleep=lambda s: sleeps.append(s),
        poll_max_attempts=5,
        poll_interval_s=0.25,
    )

    # Exactly one create POST, then the order confirmed via polling.
    assert client.posts == [("POST", "/tradfi/orders")]
    assert result.status == "filled"
    assert result.order_id == "ORD-NEW-1"
    assert result.fill_price == pytest.approx(212.55)
    assert result.fill_volume == pytest.approx(1.0)
    # The queue-task-id is retained on the result (the 7.4 correlation key).
    assert result.raw is not None and result.raw.get("queue_task_id") == _QTASK_ID
    # Polling happened across attempts: the order appeared on poll 3, so the loop
    # slept (the injected backoff) between the earlier empty polls.
    assert client.get_counts.get("/tradfi/orders", 0) >= 3
    assert sleeps, "expected the injected poll backoff to fire while polling"
    assert all(s == pytest.approx(0.25) for s in sleeps)


# --------------------------------------------------------------------------- #
# (b) Unconfirmed: the order/position NEVER appears within the cap ->
#     status="unconfirmed" (not filled), bounded attempts.
# --------------------------------------------------------------------------- #


def test_async_buy_unconfirmed_when_never_appears_within_cap(monkeypatch):
    """A live BUY whose resulting order NEVER appears within the attempt cap ->
    ``unconfirmed`` (NEVER ``filled``), and the loop is BOUNDED to exactly
    ``poll_max_attempts`` order reads (Req 1.7/9.2)."""
    _set_creds(monkeypatch)
    base = make_mock_transport()

    # The orders book never shows the new order (always empty).
    client = _ScriptedClient(
        base, scripts={("GET", "/tradfi/orders"): lambda: []}
    )
    clients = _clients(client)

    sleeps: list[float] = []
    cap = 4

    result = core.submit_decision(
        Label.BUY,
        "AAPL",
        Direction.LONG,
        volume=1.0,
        clients=clients,
        runtime_mode=_live_cleared_mode(),
        poll_sleep=lambda s: sleeps.append(s),
        poll_max_attempts=cap,
        poll_interval_s=0.1,
    )

    # One POST, then the bounded poll loop exhausts -> unconfirmed (NOT filled).
    assert client.posts == [("POST", "/tradfi/orders")]
    assert result.status == "unconfirmed"
    assert result.status != "filled", "an unconfirmed outcome must NEVER assume a fill"
    assert result.fill_price is None and result.fill_volume is None
    # BOUNDED: exactly `cap` order read-backs, and `cap - 1` inter-attempt sleeps.
    assert client.get_counts.get("/tradfi/orders", 0) == cap
    assert len(sleeps) == cap - 1
    # The queue-task-id is still retained for a later 7.4-guarded resend.
    assert result.raw is not None and result.raw.get("queue_task_id") == _QTASK_ID


# --------------------------------------------------------------------------- #
# (c) Double-send guard: after an unconfirmed submit, a re-send with the SAME
#     intent + retained queue-task-id correlates the prior order and issues NO
#     second POST (no duplicate).
# --------------------------------------------------------------------------- #


def test_double_send_guard_no_second_post_when_prior_order_exists(monkeypatch):
    """First BUY -> unconfirmed (order not yet visible). The prior submission then
    DID land (an active order now carries the retained queue-task-id). A re-send of
    the SAME intent, passing the retained ``prior_queue_task_id``, correlates that
    order and issues NO second create POST — exactly ONE create POST across both
    calls (Req 7.4)."""
    _set_creds(monkeypatch)
    base = make_mock_transport()

    # The order is invisible during the first call's polling, then becomes visible
    # (carrying the queue-task-id) before the second call's guard runs.
    landed = {"visible": False}
    prior_order = {
        "order_id": "ORD-LANDED-1",
        "symbol": "AAPL",
        "side": broker_mappers.SIDE_BUY,
        "queue_task_id": _QTASK_ID,
        "finished": False,  # still working, but it EXISTS -> no duplicate
        "volume": "1.00",
        "price": "212.40",
    }

    def _orders_script():
        return [prior_order] if landed["visible"] else []

    client = _ScriptedClient(base, scripts={("GET", "/tradfi/orders"): _orders_script})
    clients = _clients(client)

    # ---- First send: order never appears within the cap -> unconfirmed. ----
    first = core.submit_decision(
        Label.BUY,
        "AAPL",
        Direction.LONG,
        volume=1.0,
        clients=clients,
        runtime_mode=_live_cleared_mode(),
        poll_sleep=lambda s: None,
        poll_max_attempts=3,
        poll_interval_s=0.0,
    )
    assert first.status == "unconfirmed"
    retained = first.raw["queue_task_id"]
    assert retained == _QTASK_ID
    assert client.posts == [("POST", "/tradfi/orders")], "first send posts once"

    # The prior submission actually landed (the venue eventually queued the order).
    landed["visible"] = True

    # ---- Re-send the SAME intent WITH the retained queue-task-id. ----
    second = core.submit_decision(
        Label.BUY,
        "AAPL",
        Direction.LONG,
        volume=1.0,
        clients=clients,
        runtime_mode=_live_cleared_mode(),
        prior_queue_task_id=retained,
        poll_sleep=lambda s: None,
        poll_max_attempts=3,
        poll_interval_s=0.0,
    )

    # The guard correlated the prior order -> returns it; NO second create POST.
    assert second.status in ("filled", "unconfirmed")
    assert second.order_id == "ORD-LANDED-1"
    # LOAD-BEARING: exactly ONE create POST across BOTH calls (no duplicate).
    create_posts = [p for p in client.posts if p == ("POST", "/tradfi/orders")]
    assert len(create_posts) == 1, (
        f"a 7.4-guarded resend must issue NO duplicate create POST; got {client.posts!r}"
    )


def test_double_send_guard_does_not_block_a_first_send(monkeypatch):
    """A FIRST send (no retained queue-task-id) correlates nothing and ALWAYS
    transmits — the guard must not false-positive off an unrelated pre-existing
    same-direction order in the book (Req 7.4 fires only on a re-send)."""
    _set_creds(monkeypatch)
    base = make_mock_transport()

    # The default orders.json fixture ALREADY contains an AAPL side-2 (BUY) order;
    # a first send (prior_queue_task_id=None) must still POST despite it.
    client = _ScriptedClient(base)  # no script -> real orders.json fixture
    clients = _clients(client)

    result = core.submit_decision(
        Label.BUY,
        "AAPL",
        Direction.LONG,
        volume=1.0,
        clients=clients,
        runtime_mode=_live_cleared_mode(),
        poll_sleep=lambda s: None,
        poll_max_attempts=2,
        poll_interval_s=0.0,
    )

    assert client.posts == [("POST", "/tradfi/orders")], (
        "a first send must transmit even when an unrelated same-side order exists"
    )
    assert result.status in ("filled", "unconfirmed")


# --------------------------------------------------------------------------- #
# Close-side double-send guard: a SELL re-send whose prior close already removed
# the position issues no duplicate close (reuses the snapshot's positions read).
# --------------------------------------------------------------------------- #


def test_async_close_confirmed_when_position_absent(monkeypatch):
    """A live SELL on an existing position: the POST acks with a queue-task-id; the
    position is GONE on the read-back -> confirmed full close (``filled``), via a
    bounded poll (Req 1.7)."""
    _set_creds(monkeypatch)
    base = make_mock_transport()

    # The position is PRESENT for the pre-transmit snapshot read (so validation's
    # 1.8 position-exists check passes), then ABSENT once the close POST has been
    # issued (the confirm poll sees the full close).
    client_ref: dict = {}

    def _positions_script():
        full = load_fixture("positions.json")
        closed = any(p.endswith("/close") for (_, p) in client_ref["c"].posts)
        if not closed:
            return full
        return [p for p in full if p["position_id"] != "POS-500001"]

    client = _ScriptedClient(
        base, scripts={("GET", "/tradfi/positions"): _positions_script}
    )
    client_ref["c"] = client
    clients = _clients(client)

    result = core.submit_decision(
        Label.SELL,
        "AAPL",
        Direction.LONG,
        position_id="POS-500001",
        clients=clients,
        runtime_mode=_live_cleared_mode(),
        poll_sleep=lambda s: None,
        poll_max_attempts=3,
        poll_interval_s=0.0,
    )

    assert any(m == "POST" and p.endswith("/close") for (m, p) in client.posts)
    assert result.status == "filled"
    assert result.position_id == "POS-500001"
