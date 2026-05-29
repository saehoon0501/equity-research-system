"""`integration_live` inner-ring tests for migration 048's append-only DB surface.

Shared file for tasks 3.2–3.4 (design.md "File Structure Plan"); this commit
adds ONLY task 3.2 — the `decision_process_trace` append-only guard. Tasks 3.3
(ledger migration-safety) and 3.4 (link/firewall/idempotency) land later in
this same file.

Task 3.2 (requirements 2.1, 2.2, 9.1; design "Testing Strategy → Integration"
append-only bullet + "Data Models → Physical (migration 048)" two guard
triggers): insert one `decision` row via direct SQL, then prove the migration's
guard rejects all three forbidden ops — DELETE, UPDATE (any column), and
TRUNCATE. The TRUNCATE case is the one the plain row-level UPDATE/DELETE guard
would miss: it is migration 048's separate `BEFORE TRUNCATE FOR EACH STATEMENT`
trigger (Physical DDL, design.md), so this test would FAIL if that statement-
level trigger were absent — even though UPDATE/DELETE still passed.

Reuses the task-1.3 harness (`tests/integration/conftest.py`): the `conn`
fixture (autocommit, `003→030→048` chain guaranteed-applied) and the
savepoint-based `expect_rejection` helper (asserts a guard `RAISE` / SQLSTATE
P0001 without poisoning the connection). Connection/chain logic is NOT
re-implemented here.

Non-destructive against the SHARED dev DB (per the repo convention in
`tests/integration/test_contamination_check.py`): a deterministic `uuid5`
trace_id + `ON CONFLICT (trace_id) DO NOTHING` make the seed idempotent across
re-runs (append-only, no teardown); the rejection probes are savepoint-wrapped
(the guard raises BEFORE any mutation and the savepoint rolls back regardless,
so nothing is ever actually deleted/updated/truncated). NEVER
`docker compose down` / wipe — the DB is shared across worktrees. Run:

    PYTHONPATH="$PWD" uv run --with pytest --with python-dotenv \
        --with "psycopg[binary]" --python 3.13 \
        pytest tests/integration/test_decision_trace_migration.py -m integration_live -q
"""

from __future__ import annotations

import uuid

import pytest
from psycopg.types.json import Jsonb

# Fixed namespace for deterministic, idempotent fixture ids (mirrors the uuid5
# convention in tests/integration/test_contamination_check.py and the smoke
# test). 0x4A8 == 1192 ~ "048", the owning migration.
_NS = uuid.UUID("00000000-0000-0000-0000-0000000004A8")
# Distinct seed strings from the smoke test so this suite owns its own row and
# does not couple to whether the smoke test ran first.
_TRACE_ID = str(uuid.uuid5(_NS, "task-3.2-append-only-decision"))
_RUN_ID = str(uuid.uuid5(_NS, "task-3.2-append-only-run"))


@pytest.mark.integration_live
def test_decision_trace_rejects_update_delete_and_truncate(conn, expect_rejection):
    """Migration 048's guard makes `decision_process_trace` append-only against
    all three forbidden ops: UPDATE (any column), DELETE, and TRUNCATE.

    Append-only proof for requirements 2.1 (persist append-only) and 2.2
    (reject modify/delete). TRUNCATE exercises 048's statement-level trigger
    specifically — the case the row-level UPDATE/DELETE guard would not cover.
    """
    # Seed a real decision row directly on the autocommit connection (NOT inside
    # expect_rejection) so the row-level BEFORE UPDATE/DELETE trigger has a row
    # to fire against. Deterministic uuid5 + ON CONFLICT DO NOTHING => idempotent
    # and non-destructive across re-runs (append-only, no teardown).
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
            (_TRACE_ID, _RUN_ID, Jsonb({"task": "3.2", "declined": False})),
        )

    # DELETE of the seeded row is rejected (row-level guard; WHERE must match the
    # seeded id so the FOR EACH ROW trigger actually fires).
    expect_rejection(
        conn,
        "DELETE FROM decision_process_trace WHERE trace_id = %s",
        (_TRACE_ID,),
    )

    # UPDATE of an arbitrary column is rejected (row-level guard; the trace is
    # strictly append-only — no window-close carve-out, unlike the ledger).
    expect_rejection(
        conn,
        "UPDATE decision_process_trace SET code_version = 'mutated' WHERE trace_id = %s",
        (_TRACE_ID,),
    )

    # TRUNCATE of the table is rejected (048's BEFORE TRUNCATE FOR EACH STATEMENT
    # trigger — fires regardless of matching rows; the case the row-level guard
    # alone would miss).
    expect_rejection(conn, "TRUNCATE decision_process_trace")

    # All three probes rolled back via savepoint; the session must still be
    # usable and the seeded row must still be present (nothing was mutated).
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM decision_process_trace WHERE trace_id = %s",
            (_TRACE_ID,),
        )
        assert cur.fetchone() is not None, "seeded trace row missing after probes"
