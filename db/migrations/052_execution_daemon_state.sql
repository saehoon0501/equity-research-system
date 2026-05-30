-- =============================================================================
-- Migration: 052_execution_daemon_state
-- Purpose:   The Execution Daemon's three remaining append-only state tables
--            (.kiro/specs/execution-daemon), co-located in ONE migration to keep
--            the daemon at 051/052 and avoid a 053+ renumber cascade (design.md
--            "Revalidation Triggers -> Migration coordination"):
--
--            (1) `execution_daemon_position_version` — INSERT-ONLY open/close +
--                version-pin record. The open/close pair reconstructs a
--                position's version-pinned lifetime; immutable after write
--                (requirements.md 8.2/8.3; design.md Data Models).
--
--            (2) `execution_daemon_command_intake` — the inbound command
--                transport. The out-of-process commander (monitor/operator)
--                INSERTs a gated command row; the daemon is the sole reader and
--                the sole applier, marking the SET-ONCE whitelist
--                `applied_at`/`status`/`reject_reason` (NULL->value once;
--                value->value rejected). The commander never sets applied_at;
--                the daemon never inserts (requirements.md 5.4, 9.2-9.3;
--                design.md Data Models + Write-authorization note).
--
--            (3) `execution_daemon_epoch` — the daemon-owned per-epoch param pin
--                (epoch_id IS the run_id carried on every trace + event). One row
--                per pinned-param epoch (daemon start + each hot-swap), closed via
--                the SET-ONCE whitelist `closed_at`/`status`. Deliberately NOT
--                `run_parameters_snapshot`, so the LLM /research-company run
--                lifecycle + the P6 orphan reconciler stay uncontaminated
--                (Issue 1 / option b; requirements.md 1.4, 4.2, 8.1).
--
--            Append-only guard pattern (per db/migrations/048 + 034): DELETE and
--            TRUNCATE rejected on all three; position_version rejects ALL UPDATE
--            (048 strict-block style); command_intake / epoch reject UPDATE
--            EXCEPT their SET-ONCE whitelist (NULL->value once, value->value
--            rejected — the daemon ADDS the `OLD.col IS NOT NULL` second-write
--            rejection on top of the immutability blacklist, research.md
--            Set-once SQL / G2 / CN-5).
--
-- Reference: .kiro/specs/execution-daemon/design.md
--              "Data Models" (all three tables), "Build Phasing", "Modified/New Files".
--            .kiro/specs/execution-daemon/requirements.md 4, 5, 8, 9.
--            db/migrations/048_decision_trace_telemetry.sql (strict-block + truncate guard).
--            db/migrations/034_run_parameters_snapshot.sql (mutable-whitelist pattern).
--
-- Dependencies:
--   - PostgreSQL 13+ (gen_random_uuid in core).
--   - Migration 051 (event_queue) applies first by number; no schema dependency.
--   - Survival-gate migrations 049/050 land first (numbering reservation only;
--     no schema dependency — these tables are daemon-owned). If survival
--     renumbers, the daemon migrations rev (research.md CN-5).
--
-- Apply (one-line psql, run from repo root):
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research -f db/migrations/052_execution_daemon_state.sql
--
-- Idempotency: safe to re-run. CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT
-- EXISTS, CREATE OR REPLACE FUNCTION, DROP TRIGGER IF EXISTS + CREATE TRIGGER.
-- Forward-only: no down-migration (repo convention, db/README.md).
-- =============================================================================

BEGIN;

-- =============================================================================
-- (1) execution_daemon_position_version — INSERT-ONLY version-pin record.
-- =============================================================================
CREATE TABLE IF NOT EXISTS execution_daemon_position_version (
    record_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id             UUID NOT NULL,
    venue_position_id  TEXT NOT NULL,
    code_version       TEXT NOT NULL,
    param_version      TEXT NOT NULL,
    event              TEXT NOT NULL CHECK (event IN ('opened', 'closed')),
    event_ts           TIMESTAMPTZ NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_edpv_run
    ON execution_daemon_position_version (run_id);
CREATE INDEX IF NOT EXISTS idx_edpv_position
    ON execution_daemon_position_version (venue_position_id);
CREATE INDEX IF NOT EXISTS idx_edpv_version
    ON execution_daemon_position_version (code_version, param_version);

-- STRICT append-only guard (048's decision_process_trace style): block UPDATE,
-- DELETE, AND TRUNCATE unconditionally. The open/close pair is immutable once
-- written. One raise-only function serves the row-level (UPDATE/DELETE) and
-- statement-level (TRUNCATE) triggers — it touches no NEW/OLD and always raises.
CREATE OR REPLACE FUNCTION execution_daemon_position_version_guard() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'execution_daemon_position_version is append-only — % not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS execution_daemon_position_version_no_modify ON execution_daemon_position_version;
CREATE TRIGGER execution_daemon_position_version_no_modify
    BEFORE UPDATE OR DELETE ON execution_daemon_position_version
    FOR EACH ROW EXECUTE FUNCTION execution_daemon_position_version_guard();

DROP TRIGGER IF EXISTS execution_daemon_position_version_no_truncate ON execution_daemon_position_version;
CREATE TRIGGER execution_daemon_position_version_no_truncate
    BEFORE TRUNCATE ON execution_daemon_position_version
    FOR EACH STATEMENT EXECUTE FUNCTION execution_daemon_position_version_guard();

-- =============================================================================
-- (2) execution_daemon_command_intake — inbound command transport.
--
-- Commander INSERTs (command_id is commander-minted, NO default). The daemon
-- polls un-applied rows, validates through the gated seams, and marks the
-- SET-ONCE whitelist applied_at/status/reject_reason. The commander never sets
-- applied_at; the daemon never inserts.
-- =============================================================================
CREATE TABLE IF NOT EXISTS execution_daemon_command_intake (
    command_id    UUID PRIMARY KEY,                                     -- commander-minted (no default)
    issued_by     TEXT NOT NULL CHECK (issued_by IN ('monitor', 'operator')),
    command_type  TEXT NOT NULL CHECK (command_type IN (
                      'engage_kill_switch', 'set_safe_mode_grade', 'select_validated_config')),
    target        JSONB NOT NULL,                                       -- e.g. {grade} or {version_id}
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at    TIMESTAMPTZ NULL,                                     -- set-once by the daemon
    status        TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'applied', 'rejected')),
    reject_reason TEXT NULL                                             -- set-once by the daemon on rejection
);

CREATE INDEX IF NOT EXISTS idx_edci_pending
    ON execution_daemon_command_intake (created_at)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_edci_command_type
    ON execution_daemon_command_intake (command_type);

-- Append-only + set-once guard: reject DELETE; reject UPDATE unless it ONLY
-- moves the whitelist (applied_at / status / reject_reason) forward set-once.
-- status moves pending -> {applied | rejected} once (a second status change
-- away from a terminal value is rejected); applied_at / reject_reason move
-- NULL -> value once.
CREATE OR REPLACE FUNCTION execution_daemon_command_intake_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'execution_daemon_command_intake is append-only — DELETE not permitted';
    END IF;

    -- TG_OP = 'UPDATE'. Immutable columns (everything outside the whitelist).
    IF NEW.command_id   IS DISTINCT FROM OLD.command_id
       OR NEW.issued_by    IS DISTINCT FROM OLD.issued_by
       OR NEW.command_type IS DISTINCT FROM OLD.command_type
       OR NEW.target       IS DISTINCT FROM OLD.target
       OR NEW.created_at   IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'execution_daemon_command_intake is append-only — only applied_at/status/reject_reason may change (set-once by the daemon)';
    END IF;

    -- Set-once on applied_at: NULL -> value once.
    IF OLD.applied_at IS NOT NULL AND NEW.applied_at IS DISTINCT FROM OLD.applied_at THEN
        RAISE EXCEPTION 'execution_daemon_command_intake.applied_at is set-once — NULL->value once (was %, attempted %)', OLD.applied_at, NEW.applied_at;
    END IF;

    -- Set-once on reject_reason: NULL -> value once.
    IF OLD.reject_reason IS NOT NULL AND NEW.reject_reason IS DISTINCT FROM OLD.reject_reason THEN
        RAISE EXCEPTION 'execution_daemon_command_intake.reject_reason is set-once — NULL->value once';
    END IF;

    -- Set-once on status: pending -> terminal once; a terminal status is frozen.
    IF OLD.status <> 'pending' AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'execution_daemon_command_intake.status is set-once — pending->applied|rejected once, then frozen (was %, attempted %)', OLD.status, NEW.status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS execution_daemon_command_intake_no_modify ON execution_daemon_command_intake;
CREATE TRIGGER execution_daemon_command_intake_no_modify
    BEFORE UPDATE OR DELETE ON execution_daemon_command_intake
    FOR EACH ROW EXECUTE FUNCTION execution_daemon_command_intake_guard();

CREATE OR REPLACE FUNCTION execution_daemon_command_intake_no_truncate_guard() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'execution_daemon_command_intake is append-only — TRUNCATE not permitted';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS execution_daemon_command_intake_no_truncate ON execution_daemon_command_intake;
CREATE TRIGGER execution_daemon_command_intake_no_truncate
    BEFORE TRUNCATE ON execution_daemon_command_intake
    FOR EACH STATEMENT EXECUTE FUNCTION execution_daemon_command_intake_no_truncate_guard();

-- =============================================================================
-- (3) execution_daemon_epoch — daemon-owned per-epoch param pin.
--
-- epoch_id IS the run_id carried on every trace + event in the epoch. The daemon
-- INSERTs one row per pinned-param epoch (start + each hot-swap) and closes it
-- via the SET-ONCE whitelist closed_at/status.
-- =============================================================================
CREATE TABLE IF NOT EXISTS execution_daemon_epoch (
    epoch_id            UUID PRIMARY KEY,                               -- IS the run_id (daemon-minted, no default)
    pinned_param_hash   TEXT NOT NULL,
    code_version        TEXT NOT NULL,
    param_version       TEXT NOT NULL,
    walk_forward_window TEXT NULL,                                      -- bootstrap label until the tuner publishes
    opened_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at           TIMESTAMPTZ NULL,                              -- set-once by the daemon
    status              TEXT NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open', 'closed'))
);

CREATE INDEX IF NOT EXISTS idx_ede_open
    ON execution_daemon_epoch (opened_at)
    WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_ede_version
    ON execution_daemon_epoch (code_version, param_version);

-- Append-only + set-once guard: reject DELETE; reject UPDATE unless it ONLY
-- moves the whitelist (closed_at / status) forward set-once. status moves
-- open -> closed once; closed_at moves NULL -> value once.
CREATE OR REPLACE FUNCTION execution_daemon_epoch_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'execution_daemon_epoch is append-only — DELETE not permitted';
    END IF;

    -- TG_OP = 'UPDATE'. Immutable columns (everything outside the whitelist).
    IF NEW.epoch_id            IS DISTINCT FROM OLD.epoch_id
       OR NEW.pinned_param_hash   IS DISTINCT FROM OLD.pinned_param_hash
       OR NEW.code_version        IS DISTINCT FROM OLD.code_version
       OR NEW.param_version       IS DISTINCT FROM OLD.param_version
       OR NEW.walk_forward_window IS DISTINCT FROM OLD.walk_forward_window
       OR NEW.opened_at           IS DISTINCT FROM OLD.opened_at
    THEN
        RAISE EXCEPTION 'execution_daemon_epoch is append-only — only closed_at/status may change (set-once by the daemon)';
    END IF;

    -- Set-once on closed_at: NULL -> value once.
    IF OLD.closed_at IS NOT NULL AND NEW.closed_at IS DISTINCT FROM OLD.closed_at THEN
        RAISE EXCEPTION 'execution_daemon_epoch.closed_at is set-once — NULL->value once (was %, attempted %)', OLD.closed_at, NEW.closed_at;
    END IF;

    -- Set-once on status: open -> closed once; a closed epoch is frozen.
    IF OLD.status <> 'open' AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'execution_daemon_epoch.status is set-once — open->closed once, then frozen (was %, attempted %)', OLD.status, NEW.status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS execution_daemon_epoch_no_modify ON execution_daemon_epoch;
CREATE TRIGGER execution_daemon_epoch_no_modify
    BEFORE UPDATE OR DELETE ON execution_daemon_epoch
    FOR EACH ROW EXECUTE FUNCTION execution_daemon_epoch_guard();

CREATE OR REPLACE FUNCTION execution_daemon_epoch_no_truncate_guard() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'execution_daemon_epoch is append-only — TRUNCATE not permitted';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS execution_daemon_epoch_no_truncate ON execution_daemon_epoch;
CREATE TRIGGER execution_daemon_epoch_no_truncate
    BEFORE TRUNCATE ON execution_daemon_epoch
    FOR EACH STATEMENT EXECUTE FUNCTION execution_daemon_epoch_no_truncate_guard();

-- -----------------------------------------------------------------------------
-- Table / column comments
-- -----------------------------------------------------------------------------
COMMENT ON TABLE execution_daemon_position_version IS
  'Execution Daemon (.kiro/specs/execution-daemon): INSERT-only version-pin record. The opened/closed pair reconstructs a position version-pinned lifetime; immutable after write (requirements.md 8.2/8.3).';

COMMENT ON TABLE execution_daemon_command_intake IS
  'Execution Daemon (.kiro/specs/execution-daemon): inbound command transport. The out-of-process commander INSERTs a gated command row (command_id commander-minted); the daemon is the sole applier, marking the set-once whitelist applied_at/status/reject_reason. Write-authorization: v0.1 (paper) permissive default; a dedicated DB role/grant + issued_by allowlist mandated before live cutover (design.md Write-authorization note). requirements.md 5.4, 9.2-9.3.';

COMMENT ON COLUMN execution_daemon_command_intake.applied_at IS
  'SET-ONCE by the daemon: NULL->value once. The commander never sets it; the guard rejects any second write.';

COMMENT ON COLUMN execution_daemon_command_intake.status IS
  'pending -> applied|rejected once, then frozen. The daemon is the sole mutator; the guard rejects any change away from a terminal status.';

COMMENT ON TABLE execution_daemon_epoch IS
  'Execution Daemon (.kiro/specs/execution-daemon): daemon-owned per-epoch param pin. epoch_id IS the run_id on every trace + event in the epoch. One row per pinned-param epoch (start + each hot-swap), closed via the set-once whitelist closed_at/status. Deliberately NOT run_parameters_snapshot, keeping the /research-company run lifecycle + the P6 orphan reconciler uncontaminated (Issue 1/option b). requirements.md 1.4, 4.2, 8.1.';

COMMENT ON COLUMN execution_daemon_epoch.epoch_id IS
  'IS the run_id carried on every decision trace + event in this epoch (daemon-minted, no default).';

COMMENT ON COLUMN execution_daemon_epoch.closed_at IS
  'SET-ONCE by the daemon: NULL->value once, on hot-swap/shutdown. The guard rejects any second write.';

COMMIT;

-- =============================================================================
-- VERIFY: read-only catalog checks. Run after applying to confirm the migration
-- took effect. (No guard-violation probe here — that would abort under
-- ON_ERROR_STOP=1 on a shared dev DB; rejection tests belong to task 5.1.)
-- =============================================================================

-- VERIFY: all three daemon-state tables exist.
SELECT tablename
FROM pg_tables
WHERE tablename IN ('execution_daemon_position_version',
                    'execution_daemon_command_intake',
                    'execution_daemon_epoch')
ORDER BY tablename;

-- VERIFY: indexes are present.
SELECT indexname
FROM pg_indexes
WHERE indexname IN ('idx_edpv_run', 'idx_edpv_position', 'idx_edpv_version',
                    'idx_edci_pending', 'idx_edci_command_type',
                    'idx_ede_open', 'idx_ede_version')
ORDER BY indexname;

-- VERIFY: each table carries BOTH a row-level (UPDATE/DELETE) and a
-- statement-level (TRUNCATE) guard trigger.
SELECT c.relname AS table_name,
       t.tgname  AS trigger_name,
       CASE WHEN (t.tgtype & 1) = 1 THEN 'ROW' ELSE 'STATEMENT' END AS level
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname IN ('execution_daemon_position_version',
                    'execution_daemon_command_intake',
                    'execution_daemon_epoch')
  AND NOT t.tgisinternal
ORDER BY c.relname, t.tgname;
