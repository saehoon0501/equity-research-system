-- =============================================================================
-- Migration: 051_execution_daemon_event_queue
-- Purpose:   Inner-ring storage surface for the Execution Daemon's after-market
--            event queue (.kiro/specs/execution-daemon). ONE NEW append-only,
--            emit-only event store `execution_daemon_event_queue` — the daemon's
--            single emit-side hand-off to its one external drainer
--            (`walkforward-tuning-loop`, the sole `drained_at` setter).
--
--            The daemon INSERTs decision / fill / lifecycle / command /
--            safe_mode / kill_switch events (event_queue.py, EMIT ONLY). It
--            NEVER drains: `drained_at` is the ONLY mutable column, and it is
--            set EXCLUSIVELY by the external drainer (design.md Data Models;
--            requirements.md 9.1).
--
--            Append-only guard (per db/migrations/048 + 034): UPDATE, DELETE,
--            and TRUNCATE are rejected, EXCEPT a SET-ONCE whitelist allowing
--            `drained_at` to move NULL -> value ONCE (value -> value rejected).
--            048's `decision_process_trace_guard` blocks ALL modification and
--            034's `run_parameters_snapshot_guard` is a column-IMMUTABILITY
--            blacklist — neither is a NULL->value-once guard, so this guard ADDS
--            the `OLD.drained_at IS NOT NULL` second-write rejection on top of
--            the immutability blacklist (research.md Set-once SQL / G2 / CN-5).
--
-- Reference: .kiro/specs/execution-daemon/design.md
--              "Data Models -> execution_daemon_event_queue (mig 051)",
--              "Boundary Commitments -> after-market event queue".
--            .kiro/specs/execution-daemon/requirements.md 9.1.
--            db/migrations/048_decision_trace_telemetry.sql (guard pattern).
--            db/migrations/034_run_parameters_snapshot.sql (mutable-whitelist pattern).
--
-- Dependencies:
--   - PostgreSQL 13+ (gen_random_uuid in core).
--   - Survival-gate migrations 049/050 land first (numbering reservation;
--     no schema dependency — this table is daemon-owned and standalone). If
--     survival renumbers, the daemon migrations rev (research.md CN-5).
--
-- Apply (one-line psql, run from repo root):
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research -f db/migrations/051_execution_daemon_event_queue.sql
--
-- Idempotency: safe to re-run. Uses CREATE TABLE IF NOT EXISTS, CREATE INDEX
-- IF NOT EXISTS, CREATE OR REPLACE FUNCTION, and DROP TRIGGER IF EXISTS +
-- CREATE TRIGGER (Postgres has no CREATE TRIGGER IF NOT EXISTS). Forward-only:
-- no down-migration (repo convention, db/README.md).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: execution_daemon_event_queue — append-only, emit-only event log.
--
-- event_id is server-minted (gen_random_uuid). `event_type` is the discriminated
-- kind. `payload` is JSONB so new per-event fields never force a schema migration.
-- `drained_at` is the SOLE mutable column, set NULL -> value ONCE by the single
-- external drainer (`walkforward-tuning-loop`); the daemon never writes it.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS execution_daemon_event_queue (
    event_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID NOT NULL,                                          -- the epoch_id carried on the emitting tick
    event_type  TEXT NOT NULL CHECK (event_type IN (
                    'decision', 'fill', 'lifecycle',
                    'command', 'safe_mode', 'kill_switch')),
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    drained_at  TIMESTAMPTZ NULL                                        -- set-once NULL->value by the external drainer ONLY
);

-- Drain-scan + correlation indexes.
CREATE INDEX IF NOT EXISTS idx_edeq_run
    ON execution_daemon_event_queue (run_id);
CREATE INDEX IF NOT EXISTS idx_edeq_undrained
    ON execution_daemon_event_queue (created_at)
    WHERE drained_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_edeq_event_type
    ON execution_daemon_event_queue (event_type);

-- -----------------------------------------------------------------------------
-- Append-only + set-once guard for execution_daemon_event_queue.
--
-- Stricter than the ledger, mirrored on 048's strict block but with one carve-out:
--   * DELETE  -> always rejected.
--   * TRUNCATE -> always rejected (its own statement-level trigger below).
--   * UPDATE  -> rejected UNLESS it ONLY moves `drained_at` from NULL to a value.
--               Every other column is immutable (IS DISTINCT FROM blacklist),
--               and `drained_at` itself is SET-ONCE: a second write
--               (OLD.drained_at IS NOT NULL) is rejected, so it can never be
--               cleared back to NULL or overwritten to a different timestamp.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION execution_daemon_event_queue_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'execution_daemon_event_queue is append-only — DELETE not permitted';
    END IF;

    -- TG_OP = 'UPDATE'. Only `drained_at` may change, and only NULL -> value once.
    IF NEW.event_id   IS DISTINCT FROM OLD.event_id
       OR NEW.run_id     IS DISTINCT FROM OLD.run_id
       OR NEW.event_type IS DISTINCT FROM OLD.event_type
       OR NEW.payload    IS DISTINCT FROM OLD.payload
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'execution_daemon_event_queue is append-only — only drained_at may change (set-once NULL->value by the external drainer)';
    END IF;

    -- Set-once on drained_at: NULL -> value succeeds; a second write is rejected.
    IF OLD.drained_at IS NOT NULL AND NEW.drained_at IS DISTINCT FROM OLD.drained_at THEN
        RAISE EXCEPTION 'execution_daemon_event_queue.drained_at is set-once — it may move NULL->value once and cannot be re-written (was %, attempted %)', OLD.drained_at, NEW.drained_at;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Row-level guard: reject DELETE and non-whitelisted UPDATE.
DROP TRIGGER IF EXISTS execution_daemon_event_queue_no_modify ON execution_daemon_event_queue;
CREATE TRIGGER execution_daemon_event_queue_no_modify
    BEFORE UPDATE OR DELETE ON execution_daemon_event_queue
    FOR EACH ROW EXECUTE FUNCTION execution_daemon_event_queue_guard();

-- Statement-level guard: reject TRUNCATE (fires no row-level trigger, so it
-- needs its own BEFORE TRUNCATE FOR EACH STATEMENT trigger). Reuses the same
-- function — TG_OP = 'TRUNCATE' falls through neither branch above, so use a
-- dedicated raise-only function to keep the truncate path unconditional.
CREATE OR REPLACE FUNCTION execution_daemon_event_queue_no_truncate_guard() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'execution_daemon_event_queue is append-only — TRUNCATE not permitted';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS execution_daemon_event_queue_no_truncate ON execution_daemon_event_queue;
CREATE TRIGGER execution_daemon_event_queue_no_truncate
    BEFORE TRUNCATE ON execution_daemon_event_queue
    FOR EACH STATEMENT EXECUTE FUNCTION execution_daemon_event_queue_no_truncate_guard();

-- -----------------------------------------------------------------------------
-- Column comments
-- -----------------------------------------------------------------------------
COMMENT ON TABLE execution_daemon_event_queue IS
  'Execution Daemon (.kiro/specs/execution-daemon): append-only, emit-only after-market event queue. The daemon INSERTs decision/fill/lifecycle/command/safe_mode/kill_switch events and NEVER drains; drained_at is set-once (NULL->value) EXCLUSIVELY by the single external drainer (walkforward-tuning-loop). requirements.md 9.1.';

COMMENT ON COLUMN execution_daemon_event_queue.run_id IS
  'The epoch_id (execution_daemon_epoch.epoch_id) in effect on the emitting tick — the same run_id carried on the decision trace.';

COMMENT ON COLUMN execution_daemon_event_queue.drained_at IS
  'SET-ONCE: the ONLY mutable column. Moves NULL->value exactly once, set EXCLUSIVELY by the external drainer (walkforward-tuning-loop). The daemon never writes it; the guard rejects any second write (value->value) and any other column change.';

COMMIT;

-- =============================================================================
-- VERIFY: read-only catalog checks. Run after applying to confirm the migration
-- took effect. (No guard-violation probe here — that would abort under
-- ON_ERROR_STOP=1 on a shared dev DB; rejection tests belong to task 5.1.)
-- =============================================================================

-- VERIFY: execution_daemon_event_queue table exists.
SELECT schemaname, tablename
FROM pg_tables
WHERE tablename = 'execution_daemon_event_queue';

-- VERIFY: all three indexes are present.
SELECT indexname
FROM pg_indexes
WHERE tablename = 'execution_daemon_event_queue'
  AND indexname IN ('idx_edeq_run', 'idx_edeq_undrained', 'idx_edeq_event_type')
ORDER BY indexname;

-- VERIFY: BOTH guard triggers — the row-level UPDATE/DELETE trigger AND the
-- statement-level TRUNCATE trigger.
SELECT t.tgname AS trigger_name,
       CASE WHEN (t.tgtype & 1) = 1 THEN 'ROW' ELSE 'STATEMENT' END AS level
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'execution_daemon_event_queue'
  AND NOT t.tgisinternal
ORDER BY t.tgname;
