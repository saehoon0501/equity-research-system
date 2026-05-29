"""Shared `integration_live` harness for the Decision-Trace Telemetry suites.

First conftest in `tests/integration/`. It provides the three capabilities
the live-Postgres suites (task 1.3 here; tasks 3.2–3.4 in a separate file)
depend on, following the existing `integration_live` convention
(`tests/integration/test_contamination_check.py`):

  - `_dsn()` — a `python-dotenv`/`.env` psycopg connection string for the
    SHARED, already-running dev DB (container `equity-research-db`,
    127.0.0.1:5432). No fresh-schema, no `search_path` games, no migration
    runner (`db/README.md` — there isn't one).

  - `apply_migration_chain` (session-scoped) — idempotently applies the
    `003 → 030 → 048` chain. Every migration is `IF NOT EXISTS` /
    `CREATE OR REPLACE`, so re-running is a clean no-op and the suite is
    self-bootstrapping + robust to dev-DB migration drift. Each `.sql` file
    manages its own `BEGIN; … COMMIT;`, so we execute its full text with the
    connection in AUTOCOMMIT and let the file drive its own transaction.
    This leaves 048 permanently applied (which the execution-daemon needs).

  - `conn` (function-scoped, autocommit) — a fresh connection with the chain
    guaranteed-applied. Depends on `apply_migration_chain` explicitly
    (dependency, not autouse).

  - `expect_rejection` — a savepoint-based "expect-rejection" helper (first
    such pattern in the tree). It wraps a deliberately-failing op in a nested
    `with conn.transaction()` (a SAVEPOINT); the guard's `RAISE` (SQLSTATE
    P0001, `psycopg.errors.RaiseException`) is caught and the savepoint is
    rolled back, so the op can be asserted-rejected WITHOUT poisoning the
    connection for later assertions. If the op does NOT raise, the helper
    raises `AssertionError`.

Non-destructive: deterministic `uuid5` ids + `ON CONFLICT` in consumers,
savepoint-ROLLBACK for rejection probes, no teardown (append-only tables).
NEVER `docker compose down` / `TRUNCATE` / wipe — the DB is shared across
worktrees.

Tests built on this harness assert POST-MIGRATION INVARIANTS against the
migrated DB (column set present, new columns nullable, guard behavior), NOT a
live before/after column diff — a before/after goes vacuous once 048 is
permanently applied (and `IF NOT EXISTS` would hide the failure).
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

# tests/integration/conftest.py → parents[0]=integration, [1]=tests, [2]=repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS_DIR = _REPO_ROOT / "db" / "migrations"

# The chain, in apply order. Each manages its own BEGIN/COMMIT and ends with
# harmless read-only VERIFY SELECTs; all are idempotent (IF NOT EXISTS /
# CREATE OR REPLACE), so applying when already-applied is a clean no-op.
_MIGRATION_CHAIN = (
    "003_counterfactual_ledger.sql",
    "030_counterfactual_ledger_high4_redesign.sql",
    "048_decision_trace_telemetry.sql",
)


def _dsn() -> str:
    """Build the DB DSN from `.env` via python-dotenv.

    Mirrors `tests/integration/test_contamination_check.py::_dsn`. We use
    `load_dotenv` (NOT bash `set -a; . ./.env`) because `.env` has an unquoted
    `EDGAR_USER_AGENT` (an email) on line 6 that breaks shell sourcing.
    """
    load_dotenv(_REPO_ROOT / ".env")
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ["POSTGRES_DB"]
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@pytest.fixture(scope="session")
def apply_migration_chain() -> str:
    """Idempotently apply `003 → 030 → 048` to the shared dev DB.

    Executes each migration's FULL text in one `execute()` call with the
    connection in autocommit — the file's own `BEGIN; … COMMIT;` drives the
    transaction. We must NOT `;`-split the files: their plpgsql `$$ … $$`
    bodies and `COMMENT ON … '…; …'` strings contain semicolons.

    Returns the DSN so dependent fixtures can reuse it. No teardown — the
    tables are append-only and 048 is meant to stay applied.
    """
    dsn = _dsn()
    with psycopg.connect(dsn, autocommit=True) as conn:
        for fname in _MIGRATION_CHAIN:
            sql = (_MIGRATIONS_DIR / fname).read_text()
            conn.execute(sql)
    return dsn


@pytest.fixture
def conn(apply_migration_chain: str):
    """A fresh autocommit connection with the `003→030→048` chain applied.

    Function-scoped so each test gets a clean session; autocommit so the
    savepoint helper's nested `with conn.transaction()` is the only
    transaction boundary in play (a clean SAVEPOINT, not a nested BEGIN).
    """
    with psycopg.connect(apply_migration_chain, autocommit=True) as connection:
        yield connection


@pytest.fixture
def expect_rejection():
    """Return a callable asserting a SQL op is rejected by a guard trigger.

    Usage:
        expect_rejection(conn, "UPDATE … WHERE trace_id = %s", (some_id,))

    The op runs inside a nested `with conn.transaction()` (a SAVEPOINT). The
    guard's `RAISE EXCEPTION` surfaces as `psycopg.errors.RaiseException`
    (SQLSTATE P0001); we catch exactly that so a *malformed* probe (e.g. a
    typo'd column in a future 3.2–3.4 UPDATE → SQLSTATE 42703) surfaces as a
    real error instead of silently counting as a "rejection". Exiting the
    `with` block on exception rolls the SAVEPOINT back, so the connection
    stays usable for later assertions. If NO exception fires, the op was
    wrongly allowed → `AssertionError`.
    """

    def _expect_rejection(connection, sql: str, params=None):
        try:
            with connection.transaction():
                with connection.cursor() as cur:
                    cur.execute(sql, params)
        except psycopg.errors.RaiseException:
            # Expected: guard RAISE EXCEPTION (P0001). The savepoint is rolled
            # back on block exit; the connection remains usable.
            return
        raise AssertionError(
            f"expected guard rejection but the op was allowed: {sql!r}"
        )

    return _expect_rejection
