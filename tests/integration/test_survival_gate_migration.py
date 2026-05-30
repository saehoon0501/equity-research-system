"""`integration_live` inner-ring tests for migration 049's survival-gate DB surface.

Task 2.1 (requirements 8, 9; design.md "Data Models" — the
`survival_gate_state` + `survival_gate_events` definitions + the R7-reconciled
event_type vocabulary; "Architecture → Op-state freshness guarantee";
"Boundary Commitments"). Proves the migration's TWO observable invariants
against the SHARED, already-migrated dev DB:

  (1) `survival_gate_events` is append-only — an UPDATE, a DELETE, and a
      TRUNCATE are each rejected by the migration's self-contained guard
      (a row-level BEFORE UPDATE OR DELETE trigger + a statement-level BEFORE
      TRUNCATE trigger, mirroring 048). Follows the decision-trace precedent
      exactly: a deterministic `uuid5` seed + `ON CONFLICT DO NOTHING` insert
      (INSERT is unguarded) then `expect_rejection` on each forbidden op.

  (2) `survival_gate_state` is monotonic — a tighten/engage UPDATE succeeds
      and round-trips; an un-gated loosen (grade less-safe OR kill_switch
      TRUE→FALSE) is BLOCKED; a mixed update (grade tightens but kill_switch
      disengages) is BLOCKED; a no-op update (all monitored dimensions
      identical) PASSES; and the GUC bypass seam (`SET LOCAL
      survival.allow_loosen='on'`) lets an otherwise-blocked loosen through.

THE RANK-COMPARISON FOOTGUN (highest-blast-radius node). `safe_mode_grade` must
be compared by INTEGER RANK (NONE=0 < TIGHTEN=1 < HALT_NEW=2 < FLATTEN=3), not
by string. Lexically `FLATTEN < HALT_NEW < NONE < TIGHTEN`, which INVERTS the
safety order — a string-comparison bug would silently permit loosens. The
`FLATTEN→NONE` loosen test below is a deliberate lexical-opposite-to-rank case:
`'NONE' > 'FLATTEN'` lexically (looks like a tighten), so a label-comparison
guard would WRONGLY ALLOW it and this test would FAIL. That is the footgun-kill.

SHARED-DB DISCIPLINE. The event log is append-only, so its seed + savepoint-
wrapped rejection probes leave nothing mutated (re-run = no-op). The state store
is MUTABLE + MONOTONIC: a committed tighten would latch the singleton and make
the next run order-dependent. So each state-store test (a) uses its OWN `scope`
key (INSERT is unguarded → each test seeds its own row at whatever start grade
it needs, including FLATTEN) and (b) wraps ALL its mutations in an explicit
`with conn.transaction():` that it rolls back — mirroring the allowed-UPDATE
success-probe precedent in `test_decision_trace_migration.py` (~line 406). The
round-trip read-back happens in-transaction (before rollback), which still
proves the UPDATE persisted + the guard allowed it. `SET LOCAL` only binds
inside a transaction, so the gated-loosen test MUST be in an explicit
transaction anyway (it would silently no-op in bare autocommit, then the loosen
would block and the "succeeds" assertion would fail with a misleading error).

Reuses the task-1.3 harness (`tests/integration/conftest.py`): the `conn`
fixture (autocommit, chain guaranteed-applied — now `003→030→048→049`) and the
savepoint-based `expect_rejection` helper (asserts a guard `RAISE` / SQLSTATE
P0001 without poisoning the connection). Connection/chain logic is NOT
re-implemented here.

Non-destructive against the SHARED dev DB. NEVER `docker compose down` / wipe —
the DB is shared across worktrees. Run:

    PYTHONPATH="$PWD" uv run --with pytest --with python-dotenv \
        --with "psycopg[binary]" --python 3.13 \
        pytest tests/integration/test_survival_gate_migration.py -m integration_live -q
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.integration_live

# Fixed namespace for deterministic, idempotent fixture ids (mirrors the uuid5
# convention in test_decision_trace_migration.py / test_contamination_check.py).
_NS = uuid.uuid5(uuid.NAMESPACE_URL, "survival-gate/migration-049")

# --- Event-log append-only seed (task 2.1, append-only path) ------------------
_EVENT_ID = str(uuid.uuid5(_NS, "task-2.1-append-only-event"))
_EVENT_RUN_ID = str(uuid.uuid5(_NS, "task-2.1-append-only-run"))


def test_survival_gate_events_rejects_update_delete_and_truncate(
    conn, expect_rejection
):
    """`survival_gate_events` is append-only: UPDATE, DELETE, TRUNCATE rejected.

    Seed one row (idempotent: deterministic uuid5 + ON CONFLICT DO NOTHING; the
    INSERT is unguarded — the guard is BEFORE UPDATE/DELETE/TRUNCATE only) so
    the row-level trigger has a row to fire against, then prove all three
    forbidden ops raise. The TRUNCATE case is the one a plain row-level
    UPDATE/DELETE guard would MISS — it exercises the separate statement-level
    BEFORE TRUNCATE trigger, so this would FAIL if that trigger were absent even
    though UPDATE/DELETE still passed (matches 048's stricter guard).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO survival_gate_events
                (event_id, run_id, ticker, event_type, account_snapshot)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                _EVENT_ID,
                _EVENT_RUN_ID,
                "AAPL",
                "margin_breach",
                Jsonb({"margin_level": 0.42, "probe": "task-2.1"}),
            ),
        )

    # UPDATE rejected (any column).
    expect_rejection(
        conn,
        "UPDATE survival_gate_events SET ticker = %s WHERE event_id = %s",
        ("MSFT", _EVENT_ID),
    )
    # DELETE rejected.
    expect_rejection(
        conn,
        "DELETE FROM survival_gate_events WHERE event_id = %s",
        (_EVENT_ID,),
    )
    # The BARE TRUNCATE is independently blocked by the FK reference from
    # survival_gate_state (a separate, defense-in-depth shadow: 0A000
    # FeatureNotSupported, fired BEFORE the statement-level trigger). It can
    # never truncate anything, so this is fully non-destructive — and it
    # documents why the guard probe below must use CASCADE to reach the trigger.
    with conn.cursor() as cur:
        with pytest.raises(psycopg.errors.FeatureNotSupported):
            cur.execute("TRUNCATE survival_gate_events")

    # TRUNCATE … CASCADE satisfies the FK check and reaches the statement-level
    # BEFORE TRUNCATE guard → P0001 RaiseException, caught by expect_rejection.
    # This is the case a plain row-level UPDATE/DELETE guard would MISS — it
    # would FAIL if that statement-level trigger were absent.
    expect_rejection(conn, "TRUNCATE survival_gate_events CASCADE")

    # The row survives all three rejected probes (savepoints rolled back).
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_type FROM survival_gate_events WHERE event_id = %s",
            (_EVENT_ID,),
        )
        row = cur.fetchone()
        assert row is not None, "seeded event row missing after rejection probes"
        assert row[0] == "margin_breach"


def test_survival_gate_events_event_type_check_constraint(conn):
    """The CHECK constraint admits the 6 R7-reconciled values, rejects others.

    design.md "Data Models" is authoritative (tasks.md says "halt"; there is no
    real-time `halt` event — R7). The 6 values: margin_breach, forced_liquidation,
    safe_mode_entered, kill_switch_engaged, flatten_directive, flat_verify_failed.
    An off-vocabulary value (e.g. tasks.md's bare 'halt') must be rejected by the
    CHECK — surfacing as a CheckViolation, distinct from a guard RaiseException.
    """
    allowed = (
        "margin_breach",
        "forced_liquidation",
        "safe_mode_entered",
        "kill_switch_engaged",
        "flatten_directive",
        "flat_verify_failed",
    )
    # All 6 allowed values insert (each in a rolled-back transaction so the
    # shared table is not grown by this probe). psycopg.Rollback is swallowed
    # by `with conn.transaction()` (rolls back, exits cleanly).
    for et in allowed:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO survival_gate_events
                        (event_id, run_id, ticker, event_type, account_snapshot)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        str(uuid.uuid4()),
                        _EVENT_RUN_ID,
                        None,
                        et,
                        Jsonb({"probe": "check-constraint", "event_type": et}),
                    ),
                )
            raise psycopg.Rollback()

    # An off-vocabulary value (tasks.md's bare 'halt') is rejected by the CHECK.
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO survival_gate_events
                    (event_id, run_id, event_type, account_snapshot)
                VALUES (%s, %s, %s, %s)
                """,
                (str(uuid.uuid4()), _EVENT_RUN_ID, "halt", Jsonb({})),
            )


def _seed_state(cur, scope: str, grade: str, kill: bool) -> None:
    """INSERT a fresh state row for `scope` (unguarded; per-test isolation)."""
    cur.execute(
        """
        INSERT INTO survival_gate_state
            (scope, safe_mode_grade, kill_switch_engaged)
        VALUES (%s, %s, %s)
        ON CONFLICT (scope) DO UPDATE
            SET safe_mode_grade = EXCLUDED.safe_mode_grade,
                kill_switch_engaged = EXCLUDED.kill_switch_engaged
        """,
        (scope, grade, kill),
    )


def test_state_tighten_transition_roundtrips(conn):
    """A tighten (NONE→TIGHTEN) and an engage (kill_switch FALSE→TRUE) succeed.

    Read the row back IN-TRANSACTION to confirm persistence (round-trip), then
    roll back so the shared singleton is untouched and the test is re-runnable.
    """
    scope = "test-2.1-tighten-roundtrip"
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                _seed_state(cur, scope, "NONE", False)

                # Tighten the grade NONE→TIGHTEN.
                cur.execute(
                    "UPDATE survival_gate_state SET safe_mode_grade = %s "
                    "WHERE scope = %s",
                    ("TIGHTEN", scope),
                )
                # Engage the kill switch FALSE→TRUE (a tighten on the other dim).
                cur.execute(
                    "UPDATE survival_gate_state SET kill_switch_engaged = TRUE "
                    "WHERE scope = %s",
                    (scope,),
                )
                # Round-trip read-back (in-transaction, before rollback).
                cur.execute(
                    "SELECT safe_mode_grade, kill_switch_engaged "
                    "FROM survival_gate_state WHERE scope = %s",
                    (scope,),
                )
                row = cur.fetchone()
                assert row == ("TIGHTEN", True), (
                    f"tighten did not persist: {row!r}"
                )
            raise psycopg.Rollback()
    except psycopg.Rollback:
        pass


def test_state_noop_update_passes(conn):
    """A no-op update (all monitored dimensions identical) is allowed."""
    scope = "test-2.1-noop"
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                _seed_state(cur, scope, "HALT_NEW", True)
                # Rewrite to the SAME grade + kill: strict `<` rank check + no
                # kill TRUE→FALSE => passes.
                cur.execute(
                    "UPDATE survival_gate_state "
                    "SET safe_mode_grade = %s, kill_switch_engaged = %s, "
                    "    entered_at = now() "
                    "WHERE scope = %s",
                    ("HALT_NEW", True, scope),
                )
                cur.execute(
                    "SELECT safe_mode_grade FROM survival_gate_state "
                    "WHERE scope = %s",
                    (scope,),
                )
                assert cur.fetchone()[0] == "HALT_NEW"
            raise psycopg.Rollback()
    except psycopg.Rollback:
        pass


def test_state_ungated_grade_loosen_blocked_lexical_opposite(conn, expect_rejection):
    """An un-gated grade loosen FLATTEN→NONE is blocked (RANK, not string).

    THE FOOTGUN-KILL. `'NONE' > 'FLATTEN'` lexically — a string comparison would
    read this as a TIGHTEN and WRONGLY ALLOW it. Only an integer-rank comparison
    (FLATTEN=3 → NONE=0 is a loosen) blocks it. A label-comparison guard would
    FAIL this test. The probe is savepoint-wrapped (expect_rejection) inside an
    outer transaction that seeds at FLATTEN and rolls everything back.
    """
    scope = "test-2.1-flatten-to-none"
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                _seed_state(cur, scope, "FLATTEN", False)
            # The un-gated loosen must be rejected by the monotonic guard.
            expect_rejection(
                conn,
                "UPDATE survival_gate_state SET safe_mode_grade = %s "
                "WHERE scope = %s",
                ("NONE", scope),
            )
            raise psycopg.Rollback()
    except psycopg.Rollback:
        pass


def test_state_ungated_killswitch_disengage_blocked(conn, expect_rejection):
    """An un-gated kill_switch TRUE→FALSE is blocked (R9.3 operator-only)."""
    scope = "test-2.1-kill-disengage"
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                _seed_state(cur, scope, "TIGHTEN", True)
            expect_rejection(
                conn,
                "UPDATE survival_gate_state SET kill_switch_engaged = FALSE "
                "WHERE scope = %s",
                (scope,),
            )
            raise psycopg.Rollback()
    except psycopg.Rollback:
        pass


def test_state_mixed_update_blocked(conn, expect_rejection):
    """A mixed update (grade tightens but kill_switch disengages) is BLOCKED.

    Proves the loosen condition is an OR across both dimensions, not an AND: a
    less-safe move on EITHER monitored dimension blocks the whole update.
    Start TIGHTEN+kill_engaged; attempt grade→HALT_NEW (tighten) WITH
    kill→FALSE (loosen) in one statement → blocked.
    """
    scope = "test-2.1-mixed"
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                _seed_state(cur, scope, "TIGHTEN", True)
            expect_rejection(
                conn,
                "UPDATE survival_gate_state "
                "SET safe_mode_grade = %s, kill_switch_engaged = FALSE "
                "WHERE scope = %s",
                ("HALT_NEW", scope),
            )
            raise psycopg.Rollback()
    except psycopg.Rollback:
        pass


def test_state_gated_loosen_passes(conn):
    """A GATED loosen succeeds — `SET LOCAL survival.allow_loosen='on'` seam.

    Proves (a) the bypass seam works, and (b) the earlier blocks are the
    monotonic guard, not some unrelated error (the SAME FLATTEN→NONE loosen that
    was rejected un-gated now passes once the GUC is set). `SET LOCAL` binds only
    within a transaction — which is why this whole test is in an explicit
    transaction (and conveniently the rollback also keeps the shared row clean).
    """
    scope = "test-2.1-gated-loosen"
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                _seed_state(cur, scope, "FLATTEN", True)
                # Open the bypass seam for THIS transaction only.
                cur.execute("SET LOCAL survival.allow_loosen = 'on'")
                # The same loosen that was blocked un-gated now passes: grade
                # FLATTEN→NONE AND kill TRUE→FALSE in one statement.
                cur.execute(
                    "UPDATE survival_gate_state "
                    "SET safe_mode_grade = %s, kill_switch_engaged = FALSE "
                    "WHERE scope = %s",
                    ("NONE", scope),
                )
                cur.execute(
                    "SELECT safe_mode_grade, kill_switch_engaged "
                    "FROM survival_gate_state WHERE scope = %s",
                    (scope,),
                )
                row = cur.fetchone()
                assert row == ("NONE", False), (
                    f"gated loosen did not persist: {row!r}"
                )
            raise psycopg.Rollback()
    except psycopg.Rollback:
        pass
