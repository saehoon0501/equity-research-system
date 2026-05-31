"""`integration_live` persistence tests for the Execution Daemon (task 5.1).

Requirements 4, 5, 8, 9. Source of truth:
``.kiro/specs/execution-daemon/{requirements.md, design.md}`` §"Testing Strategy
→ Integration Tests (``integration_live``, real Postgres —
``tests/integration/test_daemon_persistence.py``)" + the migration-051/052 Data
Models. The outer-ring counterpart to the daemon's inner-ring unit suite
(``tests/unit/reactive/daemon/``): this proves the daemon's persist seams behave
against the **live** DB the migrations already landed on.

What this asserts (the task-5.1 contract)
------------------------------------------
(1) **Append-only guards** reject a direct UPDATE and a DELETE on each of the
    four ``execution_daemon_*`` tables, EXCEPT the migration set-once whitelists:
      * ``event_queue.drained_at``      — NULL→value once, value→value rejected
      * ``command_intake.applied_at / status / reject_reason`` — set-once
      * ``epoch.closed_at / status``    — set-once
      * ``position_version``            — fully immutable after write (no
                                          whitelist; ALL UPDATE/DELETE rejected)
(2) **event_queue emit round-trip** — ``event_queue.emit_event`` INSERTs one row
    with a real ``conn``; a SELECT reads it back; ``drained_at`` is NULL (the
    daemon never drains — single-drainer invariant).
(3) **decision trace + linked fill round-trip** — ``trace_assembler`` →
    ``trace_writer.write_decision_trace`` / ``write_fill_outcome`` with the real
    ``conn``; the fill links to its parent; a re-send is an ON CONFLICT no-op
    (idempotency, Req 4.5).
(4) **command_intake insert + mark-applied round-trip** — a commander-INSERTed
    pending row is polled, marked ``applied`` via the set-once whitelist, and
    reads back terminal.

SHARED-DB DISCIPLINE (load-bearing — another agent may be writing concurrently).
These tables are append-only and SHARED across worktrees. So this suite:
  * uses a **unique** ``run_id`` / ``trace_id`` / ``command_id`` per test (fresh
    ``uuid4`` — NOT a deterministic seed — so concurrent runs never collide and a
    re-run never trips a stale row), and
  * NEVER ``TRUNCATE`` / wipes; rejection probes are savepoint-wrapped via the
    shared ``expect_rejection`` helper (rolls the SAVEPOINT back, leaving nothing
    mutated and the connection usable).
The set-once *success* probes (drained_at NULL→value, intake mark-applied, epoch
close) write a row this test owns by its unique id, so they are self-contained
and order-independent even committed.

Harness. Reuses ``tests/integration/conftest.py``'s ``expect_rejection`` (the
savepoint-based guard-rejection assertion). The shared ``conn`` fixture applies
the chain only through 050, so this module adds a ``daemon_conn`` fixture that
ALSO applies 051/052 idempotently (``CREATE … IF NOT EXISTS`` / ``CREATE OR
REPLACE`` — a clean no-op when already-applied) and depends on
``apply_migration_chain`` so 048 (the ``decision_process_trace`` FK target the
fill round-trip needs) is guaranteed present.

Run:
    python3 -m pytest tests/integration/test_daemon_persistence.py \
        -m integration_live -q
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

from src.reactive.daemon.event_queue import emit_event
from src.reactive.daemon.trace_assembler import (
    assemble_decision_trace,
    assemble_fill_outcome,
)
from src.reactive.daemon.types import EpochContext, PinnedParams
from src.reactive.telemetry.trace_writer import (
    write_decision_trace,
    write_fill_outcome,
)
from src.reactive.types import (
    CalibrationEvidence,
    DecisionSubstrate,
    ReactiveDecision,
)

pytestmark = pytest.mark.integration_live

# tests/integration/test_daemon_persistence.py → parents[1]=tests, [2]=repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS_DIR = _REPO_ROOT / "db" / "migrations"

# The two daemon migrations (051/052), applied AFTER the shared chain's 048/049/
# 050. Both are forward-only + idempotent (IF NOT EXISTS / CREATE OR REPLACE /
# DROP TRIGGER IF EXISTS + CREATE TRIGGER), so re-applying is a clean no-op.
_DAEMON_MIGRATIONS = (
    "051_execution_daemon_event_queue.sql",
    "052_execution_daemon_state.sql",
)


@pytest.fixture(scope="session")
def daemon_migration_chain(apply_migration_chain: str) -> str:
    """Idempotently apply 051/052 on top of the shared 003→…→050 chain.

    Depends on ``apply_migration_chain`` (shared conftest) so 048 — the
    ``decision_process_trace`` table the fill round-trip FK-references — is
    guaranteed applied first. Returns the DSN for the function-scoped conn.
    Executes each file's FULL text in autocommit so the file's own ``BEGIN; …
    COMMIT;`` drives its transaction (never ``;``-split — the plpgsql ``$$ … $$``
    bodies and ``COMMENT ON … '…; …'`` strings contain semicolons).
    """
    dsn = apply_migration_chain
    with psycopg.connect(dsn, autocommit=True) as conn:
        for fname in _DAEMON_MIGRATIONS:
            conn.execute((_MIGRATIONS_DIR / fname).read_text())
    return dsn


@pytest.fixture
def daemon_conn(daemon_migration_chain: str):
    """A fresh autocommit connection with 051/052 guaranteed-applied.

    Function-scoped + autocommit so the shared ``expect_rejection`` helper's
    nested ``with conn.transaction()`` is the only transaction boundary (a clean
    SAVEPOINT). Mirrors the shared ``conn`` fixture but on the daemon chain.
    """
    with psycopg.connect(daemon_migration_chain, autocommit=True) as connection:
        yield connection


def _now_iso() -> str:
    """A timezone-aware ISO-8601 timestamp (the writer casts ``::timestamptz``)."""
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# (1) Append-only guards — reject UPDATE/DELETE except the set-once whitelists. #
# --------------------------------------------------------------------------- #


def test_event_queue_rejects_nonwhitelisted_update_and_delete(
    daemon_conn, expect_rejection
):
    """``execution_daemon_event_queue``: only ``drained_at`` may change.

    Seed one row (INSERT is unguarded), then prove (a) a DELETE is rejected,
    (b) an UPDATE of a non-whitelisted column (``payload``) is rejected, and
    (c) the set-once ``drained_at`` moves NULL→value ONCE but a SECOND write
    (value→value) is rejected.
    """
    run_id = str(uuid.uuid4())
    row = daemon_conn.execute(
        """
        INSERT INTO execution_daemon_event_queue (run_id, event_type, payload)
        VALUES (%s, 'decision', '{"k": 1}'::jsonb)
        RETURNING event_id
        """,
        (run_id,),
    ).fetchone()
    event_id = row[0]

    # DELETE rejected.
    expect_rejection(
        daemon_conn,
        "DELETE FROM execution_daemon_event_queue WHERE event_id = %s",
        (event_id,),
    )
    # Non-whitelisted column UPDATE rejected (payload is immutable).
    expect_rejection(
        daemon_conn,
        "UPDATE execution_daemon_event_queue SET payload = '{\"k\": 2}'::jsonb "
        "WHERE event_id = %s",
        (event_id,),
    )

    # Set-once drained_at: NULL→value succeeds ONCE (the external-drainer move).
    drained_first = _now_iso()
    daemon_conn.execute(
        "UPDATE execution_daemon_event_queue SET drained_at = %s::timestamptz "
        "WHERE event_id = %s",
        (drained_first, event_id),
    )
    back = daemon_conn.execute(
        "SELECT drained_at FROM execution_daemon_event_queue WHERE event_id = %s",
        (event_id,),
    ).fetchone()
    assert back[0] is not None, "drained_at NULL→value once should have persisted"

    # A SECOND drained_at write (value→value) is rejected (set-once).
    expect_rejection(
        daemon_conn,
        "UPDATE execution_daemon_event_queue SET drained_at = %s::timestamptz "
        "WHERE event_id = %s",
        (_now_iso(), event_id),
    )


def test_position_version_rejects_all_update_and_delete(
    daemon_conn, expect_rejection
):
    """``execution_daemon_position_version`` is fully immutable after write.

    No whitelist — the open/close pair is frozen (Req 8.2/8.3). Both an UPDATE
    (of any column) and a DELETE are rejected.
    """
    run_id = str(uuid.uuid4())
    pos_id = f"pos-{uuid.uuid4()}"
    row = daemon_conn.execute(
        """
        INSERT INTO execution_daemon_position_version (
            run_id, venue_position_id, code_version, param_version,
            event, event_ts
        ) VALUES (%s, %s, 'code-v1', 'param-v1', 'opened', now())
        RETURNING record_id
        """,
        (run_id, pos_id),
    ).fetchone()
    record_id = row[0]

    expect_rejection(
        daemon_conn,
        "UPDATE execution_daemon_position_version SET event = 'closed' "
        "WHERE record_id = %s",
        (record_id,),
    )
    expect_rejection(
        daemon_conn,
        "DELETE FROM execution_daemon_position_version WHERE record_id = %s",
        (record_id,),
    )


def test_command_intake_rejects_nonwhitelisted_update_and_delete(
    daemon_conn, expect_rejection
):
    """``execution_daemon_command_intake``: only applied_at/status/reject_reason.

    DELETE rejected; an UPDATE of a non-whitelisted column (``target``)
    rejected; the set-once whitelist moves pending→applied ONCE (success), and
    a SECOND status change away from the terminal value is rejected (frozen).
    """
    command_id = str(uuid.uuid4())
    daemon_conn.execute(
        """
        INSERT INTO execution_daemon_command_intake (
            command_id, issued_by, command_type, target
        ) VALUES (%s, 'operator', 'engage_kill_switch', '{}'::jsonb)
        """,
        (command_id,),
    )

    expect_rejection(
        daemon_conn,
        "DELETE FROM execution_daemon_command_intake WHERE command_id = %s",
        (command_id,),
    )
    # target is immutable (outside the whitelist).
    expect_rejection(
        daemon_conn,
        "UPDATE execution_daemon_command_intake SET target = '{\"x\": 1}'::jsonb "
        "WHERE command_id = %s",
        (command_id,),
    )

    # Set-once whitelist: pending→applied + applied_at NULL→value succeeds ONCE.
    daemon_conn.execute(
        """
        UPDATE execution_daemon_command_intake
        SET status = 'applied', applied_at = now()
        WHERE command_id = %s
        """,
        (command_id,),
    )
    back = daemon_conn.execute(
        "SELECT status, applied_at FROM execution_daemon_command_intake "
        "WHERE command_id = %s",
        (command_id,),
    ).fetchone()
    assert back[0] == "applied" and back[1] is not None

    # A second status change away from the terminal value is rejected (frozen).
    expect_rejection(
        daemon_conn,
        "UPDATE execution_daemon_command_intake SET status = 'rejected' "
        "WHERE command_id = %s",
        (command_id,),
    )


def test_epoch_rejects_nonwhitelisted_update_and_delete(
    daemon_conn, expect_rejection
):
    """``execution_daemon_epoch``: only closed_at/status may change.

    DELETE rejected; an UPDATE of a non-whitelisted column
    (``pinned_param_hash``) rejected; the set-once whitelist moves open→closed
    ONCE (success), and a SECOND status change is rejected (frozen).
    """
    epoch_id = str(uuid.uuid4())
    daemon_conn.execute(
        """
        INSERT INTO execution_daemon_epoch (
            epoch_id, pinned_param_hash, code_version, param_version,
            walk_forward_window
        ) VALUES (%s, 'hash-abc', 'code-v1', 'param-v1', 'bootstrap')
        """,
        (epoch_id,),
    )

    expect_rejection(
        daemon_conn,
        "DELETE FROM execution_daemon_epoch WHERE epoch_id = %s",
        (epoch_id,),
    )
    # pinned_param_hash is immutable (outside the whitelist).
    expect_rejection(
        daemon_conn,
        "UPDATE execution_daemon_epoch SET pinned_param_hash = 'hash-xyz' "
        "WHERE epoch_id = %s",
        (epoch_id,),
    )

    # Set-once whitelist: open→closed + closed_at NULL→value succeeds ONCE.
    daemon_conn.execute(
        """
        UPDATE execution_daemon_epoch
        SET status = 'closed', closed_at = now()
        WHERE epoch_id = %s
        """,
        (epoch_id,),
    )
    back = daemon_conn.execute(
        "SELECT status, closed_at FROM execution_daemon_epoch WHERE epoch_id = %s",
        (epoch_id,),
    ).fetchone()
    assert back[0] == "closed" and back[1] is not None

    # A second status change away from the terminal value is rejected (frozen).
    expect_rejection(
        daemon_conn,
        "UPDATE execution_daemon_epoch SET status = 'open' WHERE epoch_id = %s",
        (epoch_id,),
    )


# --------------------------------------------------------------------------- #
# (2) event_queue emit round-trip — emit_event(conn) INSERTs; SELECT reads back. #
# --------------------------------------------------------------------------- #


def test_event_queue_emit_round_trip(daemon_conn):
    """``event_queue.emit_event`` with a real conn INSERTs one undrained row.

    The emit-side contract (Req 9.1): one append-only row, ``drained_at`` left
    NULL (the daemon never drains — single-drainer invariant). Read it back to
    prove the live INSERT landed with the emitted ``event_type`` / ``payload``.
    """
    run_id = str(uuid.uuid4())
    payload = {"decision": "LONG", "symbol": "TESTSYM", "probability": 0.61}

    shaped = emit_event(
        run_id=run_id,
        event_type="decision",
        payload=payload,
        conn=daemon_conn,
    )
    assert shaped == [
        {"run_id": run_id, "event_type": "decision", "payload": payload}
    ]

    rows = daemon_conn.execute(
        """
        SELECT event_type, payload, drained_at
        FROM execution_daemon_event_queue
        WHERE run_id = %s
        """,
        (run_id,),
    ).fetchall()
    assert len(rows) == 1, "emit_event should INSERT exactly one row"
    event_type, db_payload, drained_at = rows[0]
    assert event_type == "decision"
    assert db_payload == payload
    assert drained_at is None, "the daemon never drains — drained_at stays NULL"


# --------------------------------------------------------------------------- #
# (3) decision trace + linked fill round-trip via trace_assembler → writer.     #
# --------------------------------------------------------------------------- #


def _make_epoch(run_id: str) -> EpochContext:
    """A minimal pinned epoch carrying the four correlation keys.

    ``pinned_params`` is required by the dataclass but unused by the assembler's
    trace path; a bare ``PinnedParams`` (reactive snapshot None) suffices for the
    persistence round-trip (the writer reads only ``keys`` + ``trace``).
    """
    return EpochContext(
        run_id=run_id,
        code_version="code-v1",
        param_version="param-v1",
        walk_forward_window="wfw-2026Q2",
        pinned_params=PinnedParams(reactive_snapshot=None, survival_snapshot={}),
    )


def _make_decision(direction: str = "LONG") -> ReactiveDecision:
    """A synthetic actionable ``ReactiveDecision`` with a reconstructable substrate."""
    substrate = DecisionSubstrate(
        feature_values={"atr": 1.5, "trend_vote": 1.0},
        probability=0.62,
        effective_threshold=0.55,
        code_version="code-v1",
        param_version="param-v1",
        calibration=CalibrationEvidence(brier=None, reliability=None),
    )
    return ReactiveDecision(
        decision=direction,
        direction_in=direction,
        probability=0.62,
        sizing_hint=0.8,
        non_final=True,
        reason=None,
        substrate=substrate,
    )


def test_decision_and_linked_fill_round_trip_with_idempotency(daemon_conn):
    """A decision trace + its linked fill round-trip via the real ``conn``.

    Asserts: (a) the assembled decision row writes once and reads back from
    ``decision_process_trace``; (b) the linked fill row references the decision's
    ``trace_id`` via ``parent_trace_id`` (FK-resolvable — the write would roll
    back otherwise); (c) a re-send of BOTH rows is an ON CONFLICT no-op (Req 4.5
    idempotency — the writer returns ``[]`` and no duplicate row appears).
    """
    run_id = str(uuid.uuid4())
    epoch = _make_epoch(run_id)
    symbol = f"SYM{uuid.uuid4().hex[:8].upper()}"
    decision_ts = _now_iso()

    decision_row = assemble_decision_trace(
        epoch=epoch,
        decision=_make_decision("LONG"),
        symbol=symbol,
        event_ts=decision_ts,
        binding_constraint="margin_distance",
        liq_proximity=0.2,
        stop_out=False,
    )
    written = write_decision_trace([decision_row], conn=daemon_conn)
    assert len(written) == 1, "the decision row should INSERT once"

    # Read the decision back by its client-minted trace_id.
    drow = daemon_conn.execute(
        """
        SELECT kind, run_id, code_version, param_version, walk_forward_window
        FROM decision_process_trace WHERE trace_id = %s
        """,
        (decision_row.trace_id,),
    ).fetchone()
    assert drow is not None, "the decision row should be readable post-write"
    assert drow[0] == "decision"
    assert str(drow[1]) == run_id
    assert drow[2] == "code-v1"
    assert drow[3] == "param-v1"
    assert drow[4] == "wfw-2026Q2"

    # The linked fill references the decision's trace_id (FK-resolvable).
    fill_ts = _now_iso()
    fill_row = assemble_fill_outcome(
        epoch=epoch,
        parent_trace_id=decision_row.trace_id,
        event_ts=fill_ts,
        fill={"actual_fill_price": 101.2, "fill_volume": 0.8, "slippage": 0.05},
    )
    fwritten = write_fill_outcome([fill_row], conn=daemon_conn)
    assert len(fwritten) == 1, "the linked fill row should INSERT once"

    frow = daemon_conn.execute(
        """
        SELECT kind, parent_trace_id, walk_forward_window
        FROM decision_process_trace WHERE trace_id = %s
        """,
        (fill_row.trace_id,),
    ).fetchone()
    assert frow is not None
    assert frow[0] == "fill"
    assert str(frow[1]) == decision_row.trace_id, "fill links to its parent decision"
    # Attribution follows the decision: the fill carries the DECISION's window.
    assert frow[2] == "wfw-2026Q2"

    # Idempotency (Req 4.5): re-sending BOTH rows is an ON CONFLICT no-op.
    assert write_decision_trace([decision_row], conn=daemon_conn) == []
    assert write_fill_outcome([fill_row], conn=daemon_conn) == []

    # And no duplicate landed: exactly one decision + one fill for this trace pair.
    counts = daemon_conn.execute(
        "SELECT count(*) FROM decision_process_trace WHERE trace_id IN (%s, %s)",
        (decision_row.trace_id, fill_row.trace_id),
    ).fetchone()
    assert counts[0] == 2, "exactly the decision + fill rows, no duplicates"


# --------------------------------------------------------------------------- #
# (4) command_intake insert + mark-applied round-trip (commander INSERT →       #
#     daemon polls pending → marks applied via the set-once whitelist).         #
# --------------------------------------------------------------------------- #


def test_command_intake_insert_and_mark_applied_round_trip(daemon_conn):
    """A commander-INSERTed pending row is polled, then marked ``applied`` once.

    Mirrors the daemon's intake-transport contract (the commander INSERTs a
    gated row; the daemon is the sole applier, marking the set-once whitelist):
    INSERT a ``pending`` row, SELECT it as un-applied, then mark it ``applied``
    via ``applied_at``/``status``, and read back the terminal state.
    """
    command_id = str(uuid.uuid4())
    daemon_conn.execute(
        """
        INSERT INTO execution_daemon_command_intake (
            command_id, issued_by, command_type, target
        ) VALUES (%s, 'monitor', 'set_safe_mode_grade', %s::jsonb)
        """,
        (command_id, '{"grade": "TIGHTEN"}'),
    )

    # The daemon polls un-applied (pending) rows — this row is visible.
    pending = daemon_conn.execute(
        """
        SELECT command_id, command_type, target, status
        FROM execution_daemon_command_intake
        WHERE command_id = %s AND status = 'pending'
        """,
        (command_id,),
    ).fetchone()
    assert pending is not None, "the pending intake row should be poll-visible"
    assert pending[1] == "set_safe_mode_grade"
    assert pending[2] == {"grade": "TIGHTEN"}
    assert pending[3] == "pending"

    # The daemon marks it applied (set-once whitelist: status + applied_at).
    daemon_conn.execute(
        """
        UPDATE execution_daemon_command_intake
        SET status = 'applied', applied_at = now()
        WHERE command_id = %s
        """,
        (command_id,),
    )
    back = daemon_conn.execute(
        """
        SELECT status, applied_at, reject_reason
        FROM execution_daemon_command_intake WHERE command_id = %s
        """,
        (command_id,),
    ).fetchone()
    assert back[0] == "applied"
    assert back[1] is not None, "applied_at should be stamped on apply"
    assert back[2] is None, "an applied (non-rejected) row carries no reject_reason"
