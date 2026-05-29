"""`integration_live` inner-ring tests for migration 048's append-only DB surface.

Shared file for tasks 3.2–3.4 (design.md "File Structure Plan"); this commit
adds task 3.4 (decision→fill link, late-fill temporal firewall, and write-path
idempotency) on top of the already-landed tasks 3.2 (trace append-only guard)
and 3.3 (ledger migration-safety + guard extension).

Task 3.4 (requirements 1.4, 3.2, 5.1, 5.2, 6.1, 9.3; design "System Flows"
async decision→fill + "Late-fill attribution + temporal firewall", "Testing
Strategy → Integration" link/firewall/idempotency bullets): drives the REAL
Python write/read path (`write_decision_trace`/`write_fill_outcome` →
`query_trace`), not raw SQL. (1) Link: insert a decision then a linked fill
(`fill.parent_trace_id == decision.trace_id`; the fill carries the DECISION's
window per attribution), then a `(code_version, param_version,
walk_forward_window)` query returns BOTH, joinable by parent id. (2) Late-fill
firewall: a decision in window N + a linked fill whose `event_ts` lands in
window N+1 (but attributed to the decision's window) → an until-N-boundary read
EXCLUDES the late fill (predicate on `event_ts`) while the fill row still
carries the decision's window (§14.6 firewall: held out of in-sample fitting
yet attributed correctly). (3) Idempotency: a re-send of the same client-minted
trace_id through the writer is a no-op (`ON CONFLICT (trace_id) DO NOTHING` →
write count 1 then 0). Plus a lightweight build-order gate (R9.3): the
inner-ring suite files must exist before any outer-ring scoring is wired.

RED-first is N/A for 3.4: the writer + reader are already implemented (tasks
2.1/2.2), so the suite is green on the first run. The tests stay discriminating
nonetheless — the link test fails if the join/attribution is wrong, the
firewall test fails if the `until` predicate leaks the late fill, and the
idempotency test fails if `ON CONFLICT` is missing.

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
from pathlib import Path

import pytest
from psycopg.types.json import Jsonb

# Task 3.4 drives the REAL Python write/read path (not raw SQL), so it imports
# the leaf writers/reader + the schema row types. 3.2/3.3 above stay raw-SQL.
from src.reactive.telemetry.reader import query_trace
from src.reactive.telemetry.schema import (
    CorrelationKeys,
    DecisionTraceRow,
    FillOutcomeRow,
)
from src.reactive.telemetry.trace_writer import (
    write_decision_trace,
    write_fill_outcome,
)

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


# =============================================================================
# Task 3.4 — decision→fill link, late-fill temporal firewall, idempotency, and
# the inner-ring build-order gate (requirements 1.4, 3.2, 5.1, 5.2, 6.1, 9.3;
# design "System Flows" async decision→fill + "Late-fill attribution + temporal
# firewall", "Testing Strategy → Integration" link/firewall/idempotency bullets).
#
# Unlike 3.2/3.3 (raw SQL), these drive the REAL Python write/read path:
# write_decision_trace / write_fill_outcome → query_trace. All filter values are
# bound (the reader whitelists filter keys), and every row carries a complete
# CorrelationKeys, so a missing-key row would be rejected at the writer boundary.
#
# Non-destructive on the SHARED dev DB:
#   * Link + firewall rows use DETERMINISTIC uuid5 ids + the writer's
#     ON CONFLICT (trace_id) DO NOTHING — re-running is a clean no-op, and the
#     assertions are on the QUERY result (never the write count), so they stay
#     green whether the row was just inserted or already present from a prior
#     run. Each test also uses a test-unique code_version/param_version so the
#     (cv, pv, window) query is scoped to exactly its own rows on the shared DB.
#   * The idempotency test uses a per-RUN-UNIQUE uuid4 trace_id precisely
#     because it asserts the WRITE COUNT (1 then 0); a fixed uuid5 would return
#     0 on the second run and break the assertion. uuid4 rows persist harmlessly
#     (append-only, no teardown).
# No DELETE/TRUNCATE/wipe; the `expect_rejection` commit-on-success residual
# (tasks.md Implementation Notes) is irrelevant here — no destructive probes.
# =============================================================================

# --- Task 3.4 deterministic fixture ids (uuid5; own rows, distinct seeds) -----
# Link test: a decision + its linked fill share one (cv, pv, window) scope.
_LINK_DECISION_ID = str(uuid.uuid5(_NS, "task-3.4-link-decision"))
_LINK_FILL_ID = str(uuid.uuid5(_NS, "task-3.4-link-fill"))
_LINK_RUN_ID = str(uuid.uuid5(_NS, "task-3.4-link-run"))
_LINK_CODE_VERSION = "task-3.4-link-cv"
_LINK_PARAM_VERSION = "task-3.4-link-pv"
_LINK_WINDOW = "2026Q1"

# Firewall test: decision in window N (Jan), fill lands in window N+1 (Apr) but
# is ATTRIBUTED to the decision's window (2026Q1). Distinct cv/pv scope.
_FW_DECISION_ID = str(uuid.uuid5(_NS, "task-3.4-firewall-decision"))
_FW_FILL_ID = str(uuid.uuid5(_NS, "task-3.4-firewall-fill"))
_FW_RUN_ID = str(uuid.uuid5(_NS, "task-3.4-firewall-run"))
_FW_CODE_VERSION = "task-3.4-firewall-cv"
_FW_PARAM_VERSION = "task-3.4-firewall-pv"
_FW_WINDOW = "2026Q1"
# event_ts: decision in window N, fill in window N+1; explicit UTC ('Z') so the
# timestamptz comparison can't be shifted by the session's time zone.
_FW_DECISION_TS = "2026-01-15T12:00:00Z"  # window N (2026Q1)
_FW_FILL_TS = "2026-04-15T12:00:00Z"  # window N+1 (2026Q2) — the LATE fill
_FW_N_BOUNDARY = "2026-03-31T23:59:59Z"  # in-sample boundary at the end of N


@pytest.mark.integration_live
def test_decision_fill_link_query_returns_both_joinable(conn):
    """Decision→fill link through the real write/read path (R1.4, 3.2, 6.1).

    Insert a `decision` via `write_decision_trace`, then a linked `fill` via
    `write_fill_outcome` whose `parent_trace_id` is the decision's `trace_id`
    and whose `walk_forward_window` is the DECISION's window (attribution
    follows the decision, per design "System Flows"). A `query_trace` filtered
    by the shared `(code_version, param_version, walk_forward_window)` then
    returns BOTH rows, joinable by `fill.parent_trace_id == decision.trace_id`.

    Asserts the QUERY result, NEVER the writer's return count — deterministic
    uuid5 + ON CONFLICT means a re-run writes 0 rows but the rows are present,
    so the query assertion stays green across re-runs.
    """
    keys = CorrelationKeys(
        run_id=_LINK_RUN_ID,
        code_version=_LINK_CODE_VERSION,
        param_version=_LINK_PARAM_VERSION,
        walk_forward_window=_LINK_WINDOW,
    )
    decision = DecisionTraceRow(
        trace_id=_LINK_DECISION_ID,
        keys=keys,
        event_ts="2026-01-10T09:30:00Z",
        # plain dict — the writer json.dumps()es it; do NOT wrap in Jsonb.
        trace={"gate_link": "Survive", "probability": 0.61, "declined": False},
    )
    # Fill carries the DECISION's window (attribution follows the decision).
    fill = FillOutcomeRow(
        trace_id=_LINK_FILL_ID,
        parent_trace_id=_LINK_DECISION_ID,
        keys=keys,  # same (cv, pv, window) — window = the decision's
        event_ts="2026-01-10T09:31:00Z",
        trace={"expected_price": "100.00", "actual_fill_price": "100.05",
               "slippage": "0.05"},
    )

    # Live writes require a real conn (conn=None would be a dry-run / no write).
    # Idempotent across re-runs via ON CONFLICT; we do NOT assert the count.
    write_decision_trace([decision], conn=conn)
    write_fill_outcome([fill], conn=conn)

    # Read both back via a (cv, pv, window) query — scoped to this test's own
    # rows by the test-unique cv/pv, so exactly the decision + its fill match.
    rows = query_trace(
        {
            "code_version": _LINK_CODE_VERSION,
            "param_version": _LINK_PARAM_VERSION,
            "walk_forward_window": _LINK_WINDOW,
        },
        conn=conn,
    )
    assert len(rows) == 2, (
        f"(cv, pv, window) query should return the decision + its fill, got {len(rows)}"
    )

    by_kind = {r["kind"]: r for r in rows}
    assert set(by_kind) == {"decision", "fill"}, (
        f"query should return one decision + one fill, got kinds {sorted(by_kind)}"
    )
    decision_row = by_kind["decision"]
    fill_row = by_kind["fill"]

    # The join: the fill's parent_trace_id equals the decision's trace_id.
    # Both come from the DB as uuid.UUID (psycopg3 default loader), so this is
    # a UUID == UUID comparison; also coerce-check against the minted string id.
    assert fill_row["parent_trace_id"] == decision_row["trace_id"], (
        "fill.parent_trace_id must join to the decision's trace_id"
    )
    assert str(decision_row["trace_id"]) == _LINK_DECISION_ID
    assert str(fill_row["trace_id"]) == _LINK_FILL_ID
    assert str(fill_row["parent_trace_id"]) == _LINK_DECISION_ID
    # The fill carries the decision's window (attribution).
    assert fill_row["walk_forward_window"] == _LINK_WINDOW
    assert decision_row["walk_forward_window"] == _LINK_WINDOW


@pytest.mark.integration_live
def test_late_fill_firewall_excludes_fill_but_attributes_to_decision_window(conn):
    """Late-fill temporal firewall through the real write/read path (R5.1, 5.2,
    1.4; design "Late-fill attribution + temporal firewall", §14.6).

    A decision in walk-forward window N (Jan, 2026Q1) plus a linked fill whose
    `event_ts` lands in window N+1 (Apr, 2026Q2) BUT whose `walk_forward_window`
    is the DECISION's window (2026Q1 — attribution follows the decision). Then:

      * An until-N-boundary read (`until='2026-03-31T23:59:59Z'`) EXCLUDES the
        late fill — its `event_ts` (Apr 15) is past the boundary — while still
        INCLUDING the decision (Jan 15 ≤ boundary). This is the consumer-side
        firewall predicate on `event_ts` the reader PROVIDES but does not
        enforce (R5.2).
      * Separately, the fill ROW still carries `walk_forward_window == '2026Q1'`
        (the decision's window) — attribution is correct even though the fill
        is held out of in-sample fitting. This is exactly the §14.6 guarantee:
        a forward-window fill is firewalled out yet attributed to the decision.
    """
    keys = CorrelationKeys(
        run_id=_FW_RUN_ID,
        code_version=_FW_CODE_VERSION,
        param_version=_FW_PARAM_VERSION,
        walk_forward_window=_FW_WINDOW,  # decision's window = 2026Q1
    )
    decision = DecisionTraceRow(
        trace_id=_FW_DECISION_ID,
        keys=keys,
        event_ts=_FW_DECISION_TS,  # window N (Jan 15)
        trace={"gate_link": "Edge", "probability": 0.55, "declined": False},
    )
    # The LATE fill: its event_ts is in window N+1 (Apr 15), but it is
    # ATTRIBUTED to the decision's window (2026Q1) via keys.walk_forward_window.
    late_fill = FillOutcomeRow(
        trace_id=_FW_FILL_ID,
        parent_trace_id=_FW_DECISION_ID,
        keys=keys,  # walk_forward_window = 2026Q1 (the decision's), NOT 2026Q2
        event_ts=_FW_FILL_TS,  # window N+1 (Apr 15) — past the N boundary
        trace={"expected_price": "50.00", "actual_fill_price": "50.20",
               "slippage": "0.20"},
    )

    write_decision_trace([decision], conn=conn)
    write_fill_outcome([late_fill], conn=conn)

    # (1) Firewall read: until the N boundary. The predicate is event_ts ≤ until,
    # so the Apr-15 fill is held OUT while the Jan-15 decision is included.
    in_sample = query_trace(
        {
            "code_version": _FW_CODE_VERSION,
            "param_version": _FW_PARAM_VERSION,
            "until": _FW_N_BOUNDARY,
        },
        conn=conn,
    )
    in_sample_ids = {str(r["trace_id"]) for r in in_sample}
    assert _FW_DECISION_ID in in_sample_ids, (
        "the decision (event_ts in window N) must be inside the until-N read"
    )
    assert _FW_FILL_ID not in in_sample_ids, (
        "the late fill (event_ts in window N+1) must be EXCLUDED by the "
        "until-N-boundary predicate — the firewall leaked it"
    )
    in_sample_kinds = {r["kind"] for r in in_sample}
    assert "fill" not in in_sample_kinds, (
        "no fill row should survive the until-N firewall (the only fill is late)"
    )

    # (2) Attribution: the fill ROW itself still carries the DECISION's window
    # (2026Q1), even though its event_ts is in N+1. Pull it via a kind='fill'
    # query scoped to this test's cv/pv (no `until` bound this time).
    fills = query_trace(
        {
            "code_version": _FW_CODE_VERSION,
            "param_version": _FW_PARAM_VERSION,
            "kind": "fill",
        },
        conn=conn,
    )
    assert len(fills) == 1, (
        f"exactly the one late fill should match this test's cv/pv, got {len(fills)}"
    )
    fill_row = fills[0]
    assert str(fill_row["trace_id"]) == _FW_FILL_ID
    assert fill_row["walk_forward_window"] == _FW_WINDOW, (
        "the late fill must be ATTRIBUTED to the decision's window (2026Q1), "
        f"not the fill's landing window — got {fill_row['walk_forward_window']!r}"
    )
    assert str(fill_row["parent_trace_id"]) == _FW_DECISION_ID, (
        "the late fill must still join to its decision"
    )


@pytest.mark.integration_live
def test_writer_resend_same_trace_id_is_noop(conn):
    """Idempotency: a re-send of the SAME client-minted trace_id is a no-op
    (`ON CONFLICT (trace_id) DO NOTHING`; design trace_writer "Idempotency").

    Uses a per-RUN-UNIQUE uuid4 trace_id (NOT a fixed uuid5) BECAUSE this is the
    one 3.4 test that asserts the WRITER'S RETURN COUNT (the number of rows
    actually written): the first write returns len 1, an identical re-send
    returns len 0. A fixed uuid5 would already exist on a second run and the
    first write would return 0 — so the count assertion needs an id that is
    fresh every run. uuid4 rows persist harmlessly (append-only, no teardown).
    """
    unique_trace_id = str(uuid.uuid4())  # fresh every run — see docstring
    unique_run_id = str(uuid.uuid4())
    keys = CorrelationKeys(
        run_id=unique_run_id,
        code_version="task-3.4-idempotency-cv",
        param_version="task-3.4-idempotency-pv",
        walk_forward_window="2026Q1",
    )
    row = DecisionTraceRow(
        trace_id=unique_trace_id,
        keys=keys,
        event_ts="2026-02-01T10:00:00Z",
        trace={"gate_link": "Survive", "declined": True},
    )

    # First write actually inserts → exactly one row written.
    first = write_decision_trace([row], conn=conn)
    assert len(first) == 1, (
        f"first write of a fresh trace_id should write 1 row, got {len(first)}"
    )

    # Re-send the SAME row (same client-minted trace_id) → ON CONFLICT DO
    # NOTHING → zero rows written (idempotent no-op).
    second = write_decision_trace([row], conn=conn)
    assert len(second) == 0, (
        "re-sending the same client-minted trace_id must be a no-op "
        f"(ON CONFLICT DO NOTHING → 0 written), got {len(second)} — "
        "idempotency (ON CONFLICT) is missing or broken"
    )

    # The single row is present exactly once (read it back to confirm it stuck).
    rows = query_trace({"run_id": unique_run_id}, conn=conn)
    assert len(rows) == 1, (
        f"exactly one row should exist for the unique run_id, got {len(rows)}"
    )
    assert str(rows[0]["trace_id"]) == unique_trace_id


@pytest.mark.integration_live
def test_inner_ring_suites_exist_before_outer_ring_wiring():
    """Build-order gate (R9.3): the inner-ring suites must be in place before
    any version-attributed outer-ring (eval-loop) scoring is wired against the
    ledger (design "Testing Strategy → Build order").

    A lightweight guard: assert both inner-ring suite files exist — the
    pure-unit writer suite (3.1) and THIS integration_live suite (3.2–3.4). If
    a future change wires outer-ring scoring while deleting/relocating these,
    this test fails, surfacing the build-order violation (P14 / R9.3).
    """
    # parents[2] is the repo root (matches the conftest convention:
    # tests/integration/<file> → [0]=integration, [1]=tests, [2]=repo root).
    repo_root = Path(__file__).resolve().parents[2]
    unit_suite = repo_root / "tests" / "unit" / "reactive" / "telemetry" / "test_trace_writer.py"
    integration_suite = repo_root / "tests" / "integration" / "test_decision_trace_migration.py"

    assert unit_suite.exists(), (
        f"inner-ring pure-unit writer suite missing (R9.3 build-order gate): {unit_suite}"
    )
    assert integration_suite.exists(), (
        f"inner-ring integration_live suite missing (R9.3 build-order gate): {integration_suite}"
    )
