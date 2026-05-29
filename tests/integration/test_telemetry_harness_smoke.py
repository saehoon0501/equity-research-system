"""Smoke test proving the shared `integration_live` telemetry harness.

This file is the ONLY way to verify `tests/integration/conftest.py` (task 1.3)
in isolation. It exercises the three harness capabilities the consuming
suites (tasks 3.2–3.4, a *different* file) depend on:

  1. The `003 → 030 → 048` chain is guaranteed-applied — `decision_process_trace`
     (created by 048) AND the additive `counterfactual_ledger.code_version`
     column (added by 048's ALTER on the pre-existing ledger) both exist.
  2. The savepoint-based `expect_rejection` helper asserts a deliberate guard
     `RAISE` without poisoning the connection for later assertions.
  3. The connection is still usable after a rejection (the savepoint rolled
     back, not the whole session) — `SELECT 1` succeeds afterward.

Non-destructive against the SHARED dev DB: deterministic `uuid5` ids +
`ON CONFLICT (trace_id) DO NOTHING`, savepoint-ROLLBACK for the rejection
probe, no teardown (append-only). Run from repo root:

    PYTHONPATH="$PWD" uv run --with pytest --with python-dotenv \
        --with "psycopg[binary]" --python 3.13 \
        pytest tests/integration/test_telemetry_harness_smoke.py -m integration_live -q
"""

from __future__ import annotations

import uuid

import pytest
from psycopg.types.json import Jsonb

# Fixed namespace for deterministic, idempotent fixture ids (mirrors
# tests/integration/test_contamination_check.py's uuid5 convention).
_NS = uuid.UUID("00000000-0000-0000-0000-0000000004A8")  # 0x4A8 == 1192 ~ "048"
_SMOKE_TRACE_ID = str(uuid.uuid5(_NS, "harness-smoke-decision-row"))
_SMOKE_RUN_ID = str(uuid.uuid5(_NS, "harness-smoke-run"))


@pytest.mark.integration_live
def test_chain_applied_trace_table_and_ledger_column(conn):
    """The `003→030→048` chain is applied: 048's new table AND its additive
    ledger column both exist (proves CREATE TABLE *and* the ALTER ran)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_tables WHERE tablename = 'decision_process_trace'"
        )
        assert cur.fetchone() is not None, "048 CREATE TABLE did not apply"

        cur.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = 'counterfactual_ledger'
              AND column_name = 'code_version'
            """
        )
        row = cur.fetchone()
        assert row is not None, "048 ALTER on counterfactual_ledger did not apply"
        assert row[0] == "YES", "code_version must be nullable (additive)"


@pytest.mark.integration_live
def test_expect_rejection_helper_and_connection_survives(conn, expect_rejection):
    """A deliberate guard RAISE is asserted via the savepoint helper without
    poisoning the connection — `SELECT 1` still works afterward."""
    # Seed a real row so the BEFORE UPDATE/DELETE FOR EACH ROW trigger fires
    # (it is a no-op against zero matching rows). Idempotent + non-destructive.
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO decision_process_trace (
                trace_id, kind, parent_trace_id, event_ts,
                run_id, code_version, param_version, walk_forward_window, trace
            )
            VALUES (%s, 'decision', NULL, now(), %s, 'v0', 'p0', 'wf-0', %s)
            ON CONFLICT (trace_id) DO NOTHING
            """,
            (_SMOKE_TRACE_ID, _SMOKE_RUN_ID, Jsonb({"smoke": True, "declined": False})),
        )

    # The append-only guard must reject an UPDATE of the seeded row. The helper
    # wraps it in a SAVEPOINT and rolls that back on the expected RAISE.
    expect_rejection(
        conn,
        "UPDATE decision_process_trace SET code_version = 'mutated' WHERE trace_id = %s",
        (_SMOKE_TRACE_ID,),
    )

    # A SECOND, sequential rejection probe on the same connection must also
    # work — proving probes don't accumulate poison (this is the actual reuse
    # pattern in tasks 3.2–3.4, which probe DELETE/UPDATE/TRUNCATE in sequence).
    expect_rejection(
        conn,
        "DELETE FROM decision_process_trace WHERE trace_id = %s",
        (_SMOKE_TRACE_ID,),
    )

    # Both savepoints rolled back; the SESSION must still be usable.
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1, "connection poisoned after rejection probe"


@pytest.mark.integration_live
def test_expect_rejection_raises_when_op_unexpectedly_succeeds(conn, expect_rejection):
    """The helper must fail the test (AssertionError) when the op does NOT
    raise — otherwise it would silently pass a broken guard."""
    with pytest.raises(AssertionError):
        # A plain SELECT never raises, so the helper must flag the missing
        # rejection rather than swallow it.
        expect_rejection(conn, "SELECT 1")
