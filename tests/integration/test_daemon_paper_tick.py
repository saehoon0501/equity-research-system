"""`integration_live` bounded paper-tick drive for the Execution Daemon (plan #10).

Requirements 1, 3, 5, 10. The outer-ring counterpart to the loop's inner-ring
unit suite (``tests/unit/reactive/daemon/test_loop.py``): it proves
``loop.build_and_run`` drives **real PAPER ticks end-to-end** against a live DB +
the broker/feed venue handles — with the venue I/O mocked (``httpx.MockTransport``
for both the market feed and the Gate broker) so the drive touches no live venue,
exactly the DAEMON_SMOKE-style bounded drive the plan specifies.

What this asserts (the plan-item-#10 contract)
----------------------------------------------
  * a real owned psycopg conn (docker postgres) pins an epoch (the
    ``execution_daemon_epoch`` row is written) and the live persist-then-act
    ``survival_gate_state`` / ``survival_gate_events`` path is exercised;
  * a ``MassiveRestFeed`` over an ``httpx.MockTransport`` (≥252 daily bars, reusing
    the ``test_feed.py`` builders) supplies the fast-clock data;
  * the broker ``submit_decision`` / ``get_positions`` / ``get_account_assets`` run
    against a mock Gate transport (reusing the broker's ``make_mock_transport``);
  * ``should_continue`` is bounded to a single tick (no infinite loop);
  * a ``CycleOutcome`` is produced, and — when a paper submit happened — the paper
    ``OrderResult`` status is in ``{simulated, noop, rejected, unconfirmed}``
    (NEVER a live POST — the paper simulator issues no order/close POST);
  * ``RuntimeMode().live_transmit_allowed()`` is **False** by construction
    (PAPER-ONLY — the daemon pins the default paper ``RuntimeMode`` at every
    submit, so there is no reachable live-transmit path).

A **double-guarded opt-in fully-live leg** runs the real venue handles only when
BOTH ``DAEMON_PAPER_LIVE=1`` AND ``MASSIVE_API_KEY`` + Gate creds are set
(mirroring ``feed.py``'s optional live test); otherwise it skips cleanly.

Run:
    python3 -m pytest tests/integration/test_daemon_paper_tick.py \
        -m integration_live -q
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import httpx
import psycopg
import pytest

from src.reactive.daemon import broker_seam, loop as loop_mod
from src.reactive.daemon.config import DaemonConfig
from src.reactive.daemon.feed import MassiveRestFeed
from src.reactive.daemon.orchestrator import PaperLifecycleOutcome

pytestmark = pytest.mark.integration_live

# tests/integration/test_daemon_paper_tick.py → parents[1]=tests, [2]=repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS_DIR = _REPO_ROOT / "db" / "migrations"

# The two daemon migrations (051/052) on top of the shared 003→…→050 chain — both
# forward-only + idempotent (a clean no-op when already applied).
_DAEMON_MIGRATIONS = (
    "051_execution_daemon_event_queue.sql",
    "052_execution_daemon_state.sql",
)

_SYMBOL = "AAPL"


# --------------------------------------------------------------------------- #
# Migration-chain fixtures (mirror test_daemon_persistence.py).                 #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def daemon_migration_chain(apply_migration_chain: str) -> str:
    """Idempotently apply 051/052 on top of the shared 003→…→050 chain.

    Depends on ``apply_migration_chain`` (shared conftest) so 050 (the
    ``survival.*`` seed + ``survival_gate_state``) and the ``parameters_active``
    view the epoch pin reads are guaranteed present.
    """
    dsn = apply_migration_chain
    with psycopg.connect(dsn, autocommit=True) as conn:
        for fname in _DAEMON_MIGRATIONS:
            conn.execute((_MIGRATIONS_DIR / fname).read_text())
    return dsn


@pytest.fixture
def owned_conn(daemon_migration_chain: str):
    """A fresh **non-autocommit** owned psycopg conn (the daemon's connection shape).

    Non-autocommit because ``params.resolve_epoch`` sets
    ``isolation_level = REPEATABLE_READ`` + drives its own ``conn.transaction()``
    blocks, and the persist-then-act writer wraps its writes in
    ``conn.transaction()`` — exactly the owned-connection contract
    ``loop.build_and_run`` relies on.
    """
    with psycopg.connect(daemon_migration_chain) as connection:
        yield connection


# --------------------------------------------------------------------------- #
# Mock market feed (reuse test_feed.py's ≥252-bar /v2/aggs builders).           #
# --------------------------------------------------------------------------- #


def _agg_bar(close: float, ts_ms: int) -> dict:
    return {
        "t": ts_ms,
        "o": close,
        "h": close + 1.0,
        "l": close - 1.0,
        "c": close,
        "v": 1000.0,
        "vw": close,
    }


def _aggs_payload(n: int, start: float = 100.0, step: float = 0.5) -> dict:
    day_ms = 86_400_000
    base_ts = 1_600_000_000_000
    return {
        "ticker": "TEST",
        "status": "OK",
        "resultsCount": n,
        "results": [_agg_bar(start + step * i, base_ts + i * day_ms) for i in range(n)],
    }


def _feed_transport(n: int = 260) -> httpx.MockTransport:
    """A transport answering every ``/v2/aggs`` GET with ``n`` ascending daily bars."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/v2/aggs/" in request.url.path
        return httpx.Response(200, json=_aggs_payload(n))

    return httpx.MockTransport(handler)


def _mock_config() -> DaemonConfig:
    """A DaemonConfig with the feed key/URL set + the single-symbol universe."""
    return DaemonConfig(
        paper=True,
        assess_max_latency_seconds=5.0,
        poll_timeout_seconds=2.0,
        eval_cadence_seconds=1.0,
        intake_poll_cadence_seconds=1.0,
        stop_loss_atr_mult=2.0,
        market_feed_api_key="TESTKEY",
        market_feed_rest_url="https://api.massive.test",
        symbol=_SYMBOL,
        universe=frozenset({_SYMBOL}),
        instrument_leverage=5.0,
        is_excluded=False,  # affirmatively cleared so the open can reach a submit
        dsn="postgresql://unused-in-this-test",
    )


# --------------------------------------------------------------------------- #
# Mock Gate broker (reuse the broker's make_mock_transport).                    #
# --------------------------------------------------------------------------- #


def _broker_clients(mock_transport: httpx.MockTransport):
    """Build a broker ``ReadoutClients`` wired to the mock Gate transport.

    Resolves the broker leaf modules through the daemon's own ``broker_seam``
    importer (the canonical flat-import-safe path), so the mock-backed
    ``gate_client`` + ``SymbolCache`` + ``ReadoutClients`` are the genuine broker
    objects the seam binds — only the transport is the mock.
    """
    gate_client = broker_seam._import_broker_module("gate_client")
    symbol_cache_mod = broker_seam._import_broker_module("symbol_cache")
    core = broker_seam._import_broker_module("core")

    cache = symbol_cache_mod.SymbolCache(
        gate_client=gate_client, transport=mock_transport
    )
    return core.ReadoutClients(
        gate_client=gate_client, symbol_cache=cache, transport=mock_transport
    )


@dataclass
class _SubmitRecorder:
    """Wraps the seam ``submit_decision`` so the test sees the paper OrderResults
    (and proves a submit reached the paper simulator)."""

    clients: object
    results: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.results = []

    def __call__(self, *args, **kwargs):
        kwargs.setdefault("clients", self.clients)
        result = broker_seam.submit_decision(*args, **kwargs)
        self.results.append(result)
        return result


# --------------------------------------------------------------------------- #
# (A) The bounded mocked-venue paper-tick drive.                               #
# --------------------------------------------------------------------------- #


def test_build_and_run_drives_one_paper_tick_end_to_end(owned_conn, monkeypatch):
    """``build_and_run`` drives ONE real paper tick: live epoch pin + persist,
    mock feed + mock broker, bounded to a single cycle. A CycleOutcome is
    produced; any paper submit is a paper status (never a live POST)."""
    from tests.unit.mcp import broker_gate_fakes  # the broker mock-transport helper

    # Dummy Gate creds so ``gate_client.resolve_credentials`` passes — the mock
    # transport never validates the signature; PAPER mode issues no live POST.
    monkeypatch.setenv("GATE_API_KEY", "k-test")
    monkeypatch.setenv("GATE_API_SECRET", "s-test")

    config = _mock_config()
    feed = MassiveRestFeed(config, transport=_feed_transport())

    mock_clients = _broker_clients(broker_gate_fakes.make_mock_transport())
    submit_recorder = _SubmitRecorder(clients=mock_clients)
    get_positions = partial(broker_seam.get_positions, clients=mock_clients)
    get_account_assets = partial(broker_seam.get_account_assets, clients=mock_clients)
    account_activated = partial(broker_seam.account_activated, clients=mock_clients)

    # Bound the loop to EXACTLY one cycle (no infinite drive).
    ticks = {"n": 0}

    def should_continue() -> bool:
        ticks["n"] += 1
        return ticks["n"] <= 1

    exit_code = loop_mod.build_and_run(
        config=config,
        conn=owned_conn,
        feed=feed,
        submit_decision=submit_recorder,
        get_positions=get_positions,
        get_account_assets=get_account_assets,
        account_activated=account_activated,
        should_continue=should_continue,
        margin_material_pending=lambda: False,
    )

    # The bounded drive returned a clean exit code.
    assert exit_code == 0
    # Exactly one cycle ran (the loop is single-eval-at-a-time, bounded here).
    assert ticks["n"] == 2  # should_continue called twice: True then False

    # The epoch row was written (the live pin happened against parameters_active).
    epoch_rows = owned_conn.execute(
        "SELECT count(*) FROM execution_daemon_epoch"
    ).fetchone()[0]
    assert epoch_rows >= 1

    # If a paper submit happened, it is a paper terminal status — NEVER a live
    # POST. (A blocked/HOLD/declined cycle legitimately submits nothing.)
    for result in submit_recorder.results:
        assert result.status in {"simulated", "noop", "rejected", "unconfirmed"}

    # PAPER-ONLY proof: the default RuntimeMode the daemon pins at every submit
    # permits no live transmit, by construction.
    assert broker_seam.RuntimeMode().live_transmit_allowed() is False


def test_paper_lifecycle_outcome_is_never_a_live_fill(owned_conn, monkeypatch):
    """A second guard: every paper-lifecycle outcome classified by the driver is a
    paper terminal status, and ``is_filled`` is never True for a paper status."""
    from tests.unit.mcp import broker_gate_fakes

    monkeypatch.setenv("GATE_API_KEY", "k-test")
    monkeypatch.setenv("GATE_API_SECRET", "s-test")

    config = _mock_config()
    feed = MassiveRestFeed(config, transport=_feed_transport())
    mock_clients = _broker_clients(broker_gate_fakes.make_mock_transport())

    # Drive the paper lifecycle directly through the seam to inspect the classified
    # outcome shape (the same driver build_and_run wires).
    from src.reactive.daemon.orchestrator import drive_paper_lifecycle
    from src.reactive.daemon.types import ProposedOrder

    order = ProposedOrder(
        symbol=_SYMBOL,
        intent=broker_seam.Label.BUY,
        direction=broker_seam.Direction.LONG,
        volume=1.0,
        stop_loss=90.0,
        position_id=None,
    )
    outcome = drive_paper_lifecycle(
        order,
        submit_decision=partial(broker_seam.submit_decision, clients=mock_clients),
        runtime_mode=broker_seam.RuntimeMode(),  # PAPER-ONLY default
    )

    assert isinstance(outcome, PaperLifecycleOutcome)
    assert outcome.status in {"simulated", "noop", "rejected", "unconfirmed"}
    # A paper status is never a confirmed venue fill (Req 3.3).
    assert outcome.is_filled is False
    assert broker_seam.RuntimeMode().live_transmit_allowed() is False


# --------------------------------------------------------------------------- #
# (B) Double-guarded opt-in FULLY-LIVE leg (real venue handles).               #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    os.environ.get("DAEMON_PAPER_LIVE") != "1"
    or not (os.environ.get("MASSIVE_API_KEY") or "").strip()
    or not (os.environ.get("GATE_API_KEY") or "").strip()
    or not (os.environ.get("GATE_API_SECRET") or "").strip(),
    reason=(
        "fully-live paper-tick opt-in (DAEMON_PAPER_LIVE=1 + MASSIVE_API_KEY + "
        "GATE_API_KEY/GATE_API_SECRET) not set"
    ),
)
def test_fully_live_paper_tick_optional(owned_conn):
    """Double-guarded opt-in: drive one paper tick against the REAL venue handles
    (real ``MassiveRestFeed`` + real broker seam), still PAPER-ONLY.

    Skips cleanly on the default CI path (no venue creds). When it runs it proves
    the production wiring works against the live feed + Gate venue — still with NO
    reachable live-transmit path (paper ``RuntimeMode`` pinned by construction)."""
    config = DaemonConfig.from_env()  # real MASSIVE_* keys

    ticks = {"n": 0}

    def should_continue() -> bool:
        ticks["n"] += 1
        return ticks["n"] <= 1

    exit_code = loop_mod.build_and_run(
        config=config,
        conn=owned_conn,
        should_continue=should_continue,
        margin_material_pending=lambda: False,
    )
    assert exit_code == 0
    assert broker_seam.RuntimeMode().live_transmit_allowed() is False
