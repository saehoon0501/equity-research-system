"""`integration_live` inner-ring tests for migration 048's append-only DB surface.

Shared file for tasks 3.2–3.4 (design.md "File Structure Plan"); this commit
adds tasks 3.2 (trace append-only guard) and 3.3 (ledger migration-safety +
guard extension). Task 3.4 (link/firewall/idempotency) lands later in this
same file.

Task 3.2 (requirements 2.1, 2.2, 9.1; design "Testing Strategy → Integration"
append-only bullet + "Data Models → Physical (migration 048)" two guard
triggers): insert one `decision` row via direct SQL, then prove the migration's
guard rejects all three forbidden ops — DELETE, UPDATE (any column), and
TRUNCATE. The TRUNCATE case is the one the plain row-level UPDATE/DELETE guard
would miss: it is migration 048's separate `BEFORE TRUNCATE FOR EACH STATEMENT`
trigger (Physical DDL, design.md), so this test would FAIL if that statement-
level trigger were absent — even though UPDATE/DELETE still passed.

Task 3.3 (requirements 4.2, 4.4, 9.2; design "Testing Strategy → Integration"
ledger-invariants + guard-extension bullets): assert POST-MIGRATION INVARIANTS
on `counterfactual_ledger`. Every enumerated pre-048 column (003 + 030) is
present with its unchanged `data_type` (the enumerated list IS the "before", so
a dropped/retyped column fails the assertion — R4.2); the three new version
columns exist and are nullable; the version+window index exists. A legacy-style
row (the three NEW version columns NULL) inserts, and a stratified read by
`summary_code`/`window`/`gics_sector` still returns it. The 048 guard extension
freezes a new version column (UPDATE rejected via the savepoint helper) while a
window-close completion field (`measurement_date`) still updates — that success
probe is wrapped in its OWN rolled-back savepoint so the shared ledger row is
never mutated (R4.4). No destructive ledger op (DELETE/TRUNCATE) is probed, so
the `expect_rejection` commit-on-success residual (tasks.md Implementation
Notes) is moot here.

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

# --- Task 3.3 fixture ids (own row; distinct seed strings from 3.2) -----------
_LEDGER_ENTRY_ID = str(uuid.uuid5(_NS, "task-3.3-ledger-migration-safety-entry"))
_LEDGER_AGENT_RUN_ID = str(uuid.uuid5(_NS, "task-3.3-ledger-migration-safety-run"))
# gics_sector has NO CHECK constraint, so we plant a test-unique marker there to
# make the stratified postmortem read return EXACTLY this seeded row on the
# SHARED dev DB (summary_code='BUY' / window='1y' alone could match other rows).
_LEDGER_SECTOR_MARKER = "task-3.3-Information-Technology"

# The full enumerated pre-048 ledger column set — the "before" for the R4.2
# preservation assertion. A dropped or retyped column fails the assertion.
# Each entry: (column_name, information_schema.data_type). Values verified
# against the live migrated DB. 003's TIMESTAMP (no tz) reports as
# 'timestamp without time zone'; UUID -> 'uuid'; DATE -> 'date'; TEXT -> 'text';
# NUMERIC -> 'numeric' (including the GENERATED delta_vs_baseline).
_PRE_048_LEDGER_COLUMNS = {
    # migration 003 (15 columns)
    "ledger_entry_id": "uuid",
    "agent_id": "text",
    "agent_run_id": "uuid",
    "ticker": "text",
    "decision_made": "text",
    "decision_date": "date",
    "baseline": "text",
    "evaluation_window_start": "date",
    "evaluation_window_end": "date",
    "system_return": "numeric",
    "baseline_return": "numeric",
    "delta_vs_baseline": "numeric",
    "related_position_id": "uuid",
    "notes": "text",
    "created_at": "timestamp without time zone",
    # migration 030 (14 columns)
    "research_date": "date",
    "run_id": "uuid",
    "summary_code": "text",
    "conviction": "text",
    "gics_sector": "text",
    "benchmark_etf": "text",
    "window": "text",
    "measurement_date": "date",
    "ticker_return_pct": "numeric",
    "benchmark_return_pct": "numeric",
    "vs_sector_etf_return_pct": "numeric",
    "spy_return_pct": "numeric",
    "vs_spy_return_pct": "numeric",
    "envelope_id": "uuid",
}

# The three additive model-version columns migration 048 adds (nullable).
_NEW_VERSION_COLUMNS = ("code_version", "param_version", "walk_forward_window")


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


# =============================================================================
# Task 3.3 — Ledger migration-safety + guard-extension (requirements 4.2, 4.4,
# 9.2; design "Testing Strategy → Integration" ledger-invariants + guard-
# extension bullets, "Data Models → Physical (migration 048)" ledger ALTER +
# guard).
#
# These assert POST-MIGRATION INVARIANTS against the already-migrated DB, NOT a
# live before/after column diff (which goes vacuous once 048 is permanently
# applied; conftest docstring). The enumerated pre-048 column list above IS the
# "before": a dropped/retyped column fails the column-set assertion (R4.2), and
# the guard sub-assertions fail if 048 regressed the guard (a new version column
# mutable, or a window-close completion column wrongly frozen).
# =============================================================================


@pytest.mark.integration_live
def test_ledger_pre_048_columns_preserved_and_version_columns_added(conn):
    """Post-048 ledger invariants (R4.2 preservation): every enumerated pre-048
    column (003 + 030) is still present with its unchanged `data_type`, the
    three new version columns exist and are nullable, and the version+window
    index exists.

    Read-only. Catches a 048 regression that dropped or retyped any pre-048
    ledger column (the additive migration must preserve all existing columns
    and behavior — requirements 4.2).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'counterfactual_ledger'
            """
        )
        cols = {name: (data_type, is_nullable) for name, data_type, is_nullable in cur.fetchall()}

    # Every enumerated pre-048 column is present with its expected data_type.
    # The enumerated list IS the "before"; a dropped column => KeyError-style
    # assertion miss, a retyped column => data_type mismatch (R4.2).
    for col, expected_type in _PRE_048_LEDGER_COLUMNS.items():
        assert col in cols, f"pre-048 ledger column dropped by migration 048: {col!r}"
        actual_type, _ = cols[col]
        assert actual_type == expected_type, (
            f"pre-048 ledger column {col!r} retyped by migration 048: "
            f"expected data_type {expected_type!r}, got {actual_type!r}"
        )

    # The three new model-version columns exist and are nullable (additive,
    # back-compatible: legacy rows keep them NULL — requirements 4.1).
    for col in _NEW_VERSION_COLUMNS:
        assert col in cols, f"migration 048 did not add version column {col!r}"
        actual_type, is_nullable = cols[col]
        assert actual_type == "text", (
            f"new version column {col!r} should be text, got {actual_type!r}"
        )
        assert is_nullable == "YES", (
            f"new version column {col!r} must be nullable (additive), got "
            f"is_nullable={is_nullable!r}"
        )

    # The version+window index exists (version-attributed forward-P&L scan;
    # requirements 4.3, 5.1).
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM pg_indexes
            WHERE tablename = 'counterfactual_ledger'
              AND indexname = 'idx_counterfactual_version_window'
            """
        )
        assert cur.fetchone() is not None, (
            "migration 048 did not create idx_counterfactual_version_window"
        )


@pytest.mark.integration_live
def test_ledger_legacy_row_inserts_and_stratified_read_returns_it(conn):
    """A representative legacy-style row (the three NEW version columns NULL but
    the 030 columns populated) inserts, and a stratified postmortem read by
    `summary_code` / `window` / `gics_sector` still returns it (R4.2: the
    additive migration keeps stratified reads working).

    Deterministic `uuid5` `ledger_entry_id` + `ON CONFLICT (ledger_entry_id)
    DO NOTHING` makes the seed idempotent and non-destructive across re-runs
    (append-only ledger, no teardown). The row satisfies 003's NOT NULL + CHECK
    constraints (`decision_made`/`baseline`) and 030's CHECK constraints
    (`summary_code`/`window`/`conviction`). `delta_vs_baseline` is omitted (it
    is GENERATED ALWAYS). `"window"` is quoted (reserved keyword).
    """
    # Seed on the autocommit connection (idempotent). The three new version
    # columns are intentionally left NULL (legacy-style row); the 030 columns
    # are populated so the stratified read finds it.
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO counterfactual_ledger (
                ledger_entry_id, agent_id, agent_run_id, ticker,
                decision_made, decision_date, baseline, evaluation_window_start,
                run_id, summary_code, conviction, gics_sector, "window"
            )
            VALUES (
                %s, 'task-3.3-agent', %s, 'TSTT',
                'BUY', '2026-01-01', 'SPY', '2026-01-01',
                %s, 'BUY', 'HIGH', %s, '1y'
            )
            ON CONFLICT (ledger_entry_id) DO NOTHING
            """,
            (
                _LEDGER_ENTRY_ID,
                _LEDGER_AGENT_RUN_ID,
                _LEDGER_AGENT_RUN_ID,
                _LEDGER_SECTOR_MARKER,
            ),
        )

    # Stratified postmortem read by summary_code / window / gics_sector. The
    # test-unique gics_sector marker pins the result to exactly the seeded row
    # on the SHARED dev DB. Assert the three NEW version columns are NULL on it.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ledger_entry_id, code_version, param_version, walk_forward_window
            FROM counterfactual_ledger
            WHERE summary_code = 'BUY'
              AND "window" = '1y'
              AND gics_sector = %s
            """,
            (_LEDGER_SECTOR_MARKER,),
        )
        rows = cur.fetchall()

    assert len(rows) == 1, (
        f"stratified read should return exactly the seeded legacy row, got {len(rows)}"
    )
    entry_id, code_version, param_version, walk_forward_window = rows[0]
    assert str(entry_id) == _LEDGER_ENTRY_ID, "stratified read returned the wrong row"
    assert code_version is None, "legacy row code_version should be NULL"
    assert param_version is None, "legacy row param_version should be NULL"
    assert walk_forward_window is None, "legacy row walk_forward_window should be NULL"


@pytest.mark.integration_live
def test_ledger_guard_freezes_version_column_but_allows_window_close(
    conn, expect_rejection
):
    """The 048 guard extension (22-column immutable set): an UPDATE of a NEW
    version column post-insert is REJECTED, while a window-close completion
    field (`measurement_date`) still UPDATES (requirements 4.4 — the additive
    migration preserves the ledger's append-only integrity AND keeps the
    window-close carve-out working).

    Depends on the legacy row seeded by the stratified-read test; re-seeds
    idempotently here so the test is order-independent. The shared dev ledger
    holds real data, so the window-close UPDATE (which MUST succeed) is wrapped
    in our own savepoint and rolled back — the seeded row is never mutated.
    """
    # Idempotent re-seed so this test does not depend on test ordering. Same
    # deterministic id + ON CONFLICT DO NOTHING (no-op if already present).
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO counterfactual_ledger (
                ledger_entry_id, agent_id, agent_run_id, ticker,
                decision_made, decision_date, baseline, evaluation_window_start,
                run_id, summary_code, conviction, gics_sector, "window"
            )
            VALUES (
                %s, 'task-3.3-agent', %s, 'TSTT',
                'BUY', '2026-01-01', 'SPY', '2026-01-01',
                %s, 'BUY', 'HIGH', %s, '1y'
            )
            ON CONFLICT (ledger_entry_id) DO NOTHING
            """,
            (
                _LEDGER_ENTRY_ID,
                _LEDGER_AGENT_RUN_ID,
                _LEDGER_AGENT_RUN_ID,
                _LEDGER_SECTOR_MARKER,
            ),
        )

    # (1) UPDATE of a NEW version column is rejected by the extended guard.
    # The seed leaves code_version NULL, so we SET a NON-NULL value: NULL -> 'x'
    # IS DISTINCT (the guard's OR-chain fires). A SET ... = NULL would NOT be
    # distinct and would wrongly pass the guard. The savepoint helper rolls the
    # rejected probe back, leaving the connection usable.
    expect_rejection(
        conn,
        "UPDATE counterfactual_ledger SET code_version = 'x' WHERE ledger_entry_id = %s",
        (_LEDGER_ENTRY_ID,),
    )

    # (2) UPDATE of a window-close completion field (measurement_date) is
    # ALLOWED. We must NOT use expect_rejection here (it expects a raise).
    # Instead: own savepoint, run the UPDATE, capture rowcount, then raise a
    # sentinel to ROLL THE SAVEPOINT BACK so the SHARED seeded row is not
    # mutated. Assert rowcount AFTER the block so the assertion is not entangled
    # with the rollback exception.
    class _Rollback(Exception):
        """Sentinel to roll back the success-probe savepoint without leaking."""

    update_rowcount = None
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE counterfactual_ledger SET measurement_date = '2026-01-01' "
                    "WHERE ledger_entry_id = %s",
                    (_LEDGER_ENTRY_ID,),
                )
                update_rowcount = cur.rowcount
            raise _Rollback
    except _Rollback:
        pass

    assert update_rowcount == 1, (
        "window-close completion field (measurement_date) UPDATE should succeed "
        f"(rowcount 1), got rowcount={update_rowcount!r} — the 048 guard wrongly "
        "froze a window-close column"
    )

    # The success-probe savepoint was rolled back: measurement_date is still
    # NULL on the seeded row (nothing mutated on the shared DB).
    with conn.cursor() as cur:
        cur.execute(
            "SELECT measurement_date, code_version FROM counterfactual_ledger "
            "WHERE ledger_entry_id = %s",
            (_LEDGER_ENTRY_ID,),
        )
        row = cur.fetchone()
    assert row is not None, "seeded ledger row missing after guard probes"
    assert row[0] is None, "measurement_date probe should have been rolled back (still NULL)"
    assert row[1] is None, "code_version rejection probe must not have mutated the row"
