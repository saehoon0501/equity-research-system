-- =============================================================================
-- Migration: 049_survival_gate_state_and_events
-- Purpose:   Persistence surface for the Survival Gate
--            (.kiro/specs/survival-gate). The pure decision core (src/survival/)
--            performs NO I/O; this migration lands the two caller-side tables
--            the core's emitted output is persisted into:
--
--            (1) `survival_gate_events` — an APPEND-ONLY anomaly/event log
--                (requirements.md 8.2: queue the triggering anomaly for the
--                after-market batch). Mirrors the mig-003/048 append-only-ledger
--                pattern: INSERT-only, with a self-contained guard function that
--                rejects UPDATE, DELETE, AND TRUNCATE (stricter, matching 048).
--                event_type is CHECK-constrained to the design.md "Data Models"
--                R7-reconciled 6-value vocabulary (see the event_type note below).
--
--            (2) `survival_gate_state` — the MONOTONIC single-current-row
--                operational-state store (requirements.md 8.1, 8.3, 9.1–9.3):
--                the current safe-mode grade + kill-switch flag. Transitions may
--                TIGHTEN (raise the safe-mode grade) or ENGAGE (kill-switch
--                FALSE→TRUE); LOOSENING (a less-safe grade) or DISENGAGING
--                (kill-switch TRUE→FALSE) is rejected by a monotonic guard UNLESS
--                an explicit operator/after-market path opens the bypass seam
--                (session GUC `survival.allow_loosen='on'`). This realizes R9.3
--                ("explicit operator action to re-enable") + R2.5 / R10.4
--                (tighten-only, no auto-loosen) at the DB level. The MECHANISM
--                (the guard + the seam) is in-boundary; the POLICY (who/when
--                decides to loosen — walkforward-tuning-loop / the after-market
--                path) is OUT of boundary and NOT built here.
--
-- Reference: .kiro/specs/survival-gate/design.md
--              "Data Models" (the two table definitions + the R7-reconciled
--              event_type vocabulary), "Architecture → Op-state freshness
--              guarantee", "Boundary Commitments".
--            .kiro/specs/survival-gate/requirements.md  Requirement 8, 9.
--            db/migrations/048_decision_trace_telemetry.sql — the append-only
--              guard pattern copied here (a self-contained function raising on
--              TG_OP, a row-level BEFORE UPDATE OR DELETE trigger + a statement-
--              level BEFORE TRUNCATE trigger).
--
-- THE MONOTONIC GUARD — RANK, NOT STRING (highest-blast-radius node, §11.5).
--   safe_mode_grade is compared by INTEGER RANK: NONE=0 < TIGHTEN=1 <
--   HALT_NEW=2 < FLATTEN=3 (severity order). A STRING comparison would be WRONG
--   and dangerous: lexically 'FLATTEN' < 'HALT_NEW' < 'NONE' < 'TIGHTEN', which
--   INVERTS the safety order and would silently permit loosens (e.g. FLATTEN→
--   NONE looks like an *increase* lexically). The guard maps both grades to
--   their rank and blocks when rank(NEW) < rank(OLD).
--
--   "Loosen" = ANY monitored dimension moving less-safe: rank(NEW) < rank(OLD)
--   OR kill_switch TRUE→FALSE. So a MIXED update (grade tightens but kill_switch
--   disengages, or vice-versa) is BLOCKED (the condition is an OR across both
--   dimensions). A NO-OP update (both monitored dimensions identical — strict
--   `<` on rank, no kill TRUE→FALSE) PASSES. `entered_at` /
--   `triggered_by_event_id` ride along freely (not monitored dimensions).
--
--   The BYPASS SEAM (minimal, in-boundary): an otherwise-blocked UPDATE-path
--   loosen is allowed ONLY when the session GUC `survival.allow_loosen` is 'on'
--   (`current_setting(..., true)` → missing_ok, so an unset GUC is NULL, not an
--   error). The operator/after-market path will `SET LOCAL
--   survival.allow_loosen='on'` before its UPDATE — that decision is OUT of
--   scope; this migration only builds the seam. No roles, no audit, no policy.
--
--   SCOPE (the guard is BEFORE UPDATE FOR EACH ROW only): the GUC is the only
--   escape hatch *for an UPDATE-path loosen*. A DELETE+reINSERT (or TRUNCATE)
--   reset of the singleton is OUTSIDE this guard's scope — deliberately: unlike
--   the append-only events log, `survival_gate_state` is MUTABLE current-state
--   (a decommissioned scope must remain deletable), and the daemon is the
--   single-threaded SOLE writer (the op-state-freshness assumption). Hard-
--   guarding DELETE/TRUNCATE here is therefore NOT done now; closing that path
--   under daemon concurrency is a named concurrency-revalidation trigger owned
--   by the `execution-daemon` spec (design.md "Revalidation Triggers").
--
-- event_type vocabulary — design.md is authoritative (R7-reconciled).
--   tasks.md says "halt"; design.md "Data Models" reconciles to 6 values:
--   margin_breach, forced_liquidation, safe_mode_entered, kill_switch_engaged,
--   flatten_directive, flat_verify_failed. There is NO real-time `halt` event
--   (R7: real-time per-instrument halt detection is OUT of boundary, operator
--   2026-05-29). `forced_liquidation` is the POST-HOC broker `get_history`
--   record (close_reason), NOT a live halt signal.
--
-- Dependencies:
--   - PostgreSQL 13+ (gen_random_uuid in core, used for survival_gate_events PK).
--   - No dependency on 003/030/048 tables; this is a self-contained new surface.
--     It does NOT touch (no CREATE OR REPLACE of) any existing 003/048 guard
--     function — its guard functions are uniquely named.
--
-- Apply (one-line psql, run from repo root):
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research -f db/migrations/049_survival_gate_state_and_events.sql
--
-- Idempotency: safe to re-run. Uses CREATE TABLE IF NOT EXISTS, CREATE INDEX
-- IF NOT EXISTS, CREATE OR REPLACE FUNCTION (its OWN functions only), and
-- DROP TRIGGER IF EXISTS + CREATE TRIGGER (Postgres has no CREATE TRIGGER
-- IF NOT EXISTS). event_type/safe_mode_grade are TEXT + CHECK (… IN (…)) — NOT
-- a native CREATE TYPE enum, which would need a DO-block guard to stay
-- idempotent on re-apply (matches 048's `kind` column convention). Forward-only:
-- no down-migration (repo convention, db/README.md).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- (1) Table: survival_gate_events — append-only anomaly/event log.
--
-- Created FIRST so survival_gate_state.triggered_by_event_id (FK) resolves.
-- event_id is DB-minted (gen_random_uuid default). event_type is CHECK-
-- constrained to the design's R7-reconciled 6 values. ticker is nullable
-- (account-level events — e.g. a kill_switch_engaged — name no instrument).
-- account_snapshot JSONB carries the AccountState at the event (shape enforced,
-- if ever needed, by a DB CHECK — design.md "Monitoring"; not enforced here).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS survival_gate_events (
    event_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id            UUID NOT NULL,
    ticker            TEXT NULL,                                       -- nullable: account-level events name no instrument
    event_type        TEXT NOT NULL CHECK (event_type IN (
                          'margin_breach',
                          'forced_liquidation',
                          'safe_mode_entered',
                          'kill_switch_engaged',
                          'flatten_directive',
                          'flat_verify_failed'
                      )),
    account_snapshot  JSONB NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Anomaly-queue scan indexes (after-market batch reads by run, by type, by time).
CREATE INDEX IF NOT EXISTS idx_survival_gate_events_run
    ON survival_gate_events (run_id);
CREATE INDEX IF NOT EXISTS idx_survival_gate_events_type
    ON survival_gate_events (event_type);
CREATE INDEX IF NOT EXISTS idx_survival_gate_events_created_at
    ON survival_gate_events (created_at);

-- -----------------------------------------------------------------------------
-- STRICT append-only guard for survival_gate_events.
--
-- Self-contained (uniquely named — does NOT CREATE OR REPLACE 003's
-- counterfactual_ledger_guard or 048's decision_process_trace_guard). Raises
-- UNCONDITIONALLY on TG_OP and touches no NEW/OLD, so ONE function serves both
-- the row-level BEFORE UPDATE OR DELETE trigger and the statement-level BEFORE
-- TRUNCATE trigger. Control never reaches the end (RAISE always fires), so no
-- RETURN is needed.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION survival_gate_events_no_modify() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'survival_gate_events is append-only — % not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

-- Row-level guard: reject UPDATE / DELETE on any row.
DROP TRIGGER IF EXISTS survival_gate_events_no_modify_trg ON survival_gate_events;
CREATE TRIGGER survival_gate_events_no_modify_trg
    BEFORE UPDATE OR DELETE ON survival_gate_events
    FOR EACH ROW EXECUTE FUNCTION survival_gate_events_no_modify();

-- Statement-level guard: reject TRUNCATE (fires no row-level triggers).
DROP TRIGGER IF EXISTS survival_gate_events_no_truncate_trg ON survival_gate_events;
CREATE TRIGGER survival_gate_events_no_truncate_trg
    BEFORE TRUNCATE ON survival_gate_events
    FOR EACH STATEMENT EXECUTE FUNCTION survival_gate_events_no_modify();

-- -----------------------------------------------------------------------------
-- (2) Table: survival_gate_state — monotonic single-current-row op-state.
--
-- SINGLETON design: `scope` is the PRIMARY KEY with DEFAULT 'default', so the
-- common case is a single current row keyed 'default'. The scope key leaves
-- room for a future multi-scope op-state (e.g. per-account) without a schema
-- change AND lets the inner-ring tests seed isolated per-test rows on the
-- SHARED dev DB (each test uses its own scope so a committed transition never
-- latches another test's row). One CURRENT row per scope (the store holds
-- current state, not history — the history lives append-only in
-- survival_gate_events).
--
-- safe_mode_grade is TEXT + CHECK (the SafeModeGrade vocabulary). kill_switch_
-- engaged is the emergency-halt flag (R9). triggered_by_event_id FKs the event
-- that drove the transition (nullable — the initial NONE/disengaged row has no
-- trigger). entered_at records when the current state was entered.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS survival_gate_state (
    scope                  TEXT PRIMARY KEY DEFAULT 'default',
    safe_mode_grade        TEXT NOT NULL DEFAULT 'NONE'
                               CHECK (safe_mode_grade IN ('NONE', 'TIGHTEN', 'HALT_NEW', 'FLATTEN')),
    kill_switch_engaged    BOOLEAN NOT NULL DEFAULT FALSE,
    entered_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    triggered_by_event_id  UUID NULL REFERENCES survival_gate_events(event_id)
);

-- -----------------------------------------------------------------------------
-- Monotonic guard for survival_gate_state (BEFORE UPDATE FOR EACH ROW).
--
-- RANK, NOT STRING (see header). A helper CASE maps each grade to its severity
-- rank (NONE=0 < TIGHTEN=1 < HALT_NEW=2 < FLATTEN=3). The guard:
--   1. Bypass seam FIRST: if `survival.allow_loosen` GUC is 'on', RETURN NEW
--      (the operator/after-market path opened the seam — policy is out of
--      boundary; this is the only escape hatch).
--   2. Otherwise block when EITHER monitored dimension loosens:
--        rank(NEW.safe_mode_grade) < rank(OLD.safe_mode_grade)   -- grade loosen
--        OR (OLD.kill_switch_engaged AND NOT NEW.kill_switch_engaged)  -- kill disengage
--      An OR (not AND): a mixed tighten+disengage is blocked. Strict `<` on
--      rank means a no-op (equal grade, unchanged kill) PASSES, and a pure
--      tighten/engage PASSES.
--
-- current_setting('survival.allow_loosen', true): the `true` is missing_ok, so
-- an UNSET GUC returns NULL (not an error) and the `= 'on'` is then NULL/false
-- → the seam is closed by default.
--
-- Uniquely named (no CREATE OR REPLACE of any pre-existing shared function).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION survival_gate_state_monotonic_guard() RETURNS TRIGGER AS $$
DECLARE
    old_rank INT;
    new_rank INT;
BEGIN
    -- Bypass seam (minimal, in-boundary): the operator/after-market path opens
    -- it with `SET LOCAL survival.allow_loosen='on'`. Policy is out of scope.
    IF current_setting('survival.allow_loosen', true) = 'on' THEN
        RETURN NEW;
    END IF;

    old_rank := CASE OLD.safe_mode_grade
                    WHEN 'NONE'     THEN 0
                    WHEN 'TIGHTEN'  THEN 1
                    WHEN 'HALT_NEW' THEN 2
                    WHEN 'FLATTEN'  THEN 3
                END;
    new_rank := CASE NEW.safe_mode_grade
                    WHEN 'NONE'     THEN 0
                    WHEN 'TIGHTEN'  THEN 1
                    WHEN 'HALT_NEW' THEN 2
                    WHEN 'FLATTEN'  THEN 3
                END;

    -- Loosen = ANY monitored dimension moving less-safe (OR, not AND).
    IF new_rank < old_rank
       OR (OLD.kill_switch_engaged AND NOT NEW.kill_switch_engaged)
    THEN
        RAISE EXCEPTION 'survival_gate_state is monotonic — loosen rejected (grade %->%, kill_switch %->%); set survival.allow_loosen=on for the operator path',
            OLD.safe_mode_grade, NEW.safe_mode_grade,
            OLD.kill_switch_engaged, NEW.kill_switch_engaged;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS survival_gate_state_monotonic_trg ON survival_gate_state;
CREATE TRIGGER survival_gate_state_monotonic_trg
    BEFORE UPDATE ON survival_gate_state
    FOR EACH ROW EXECUTE FUNCTION survival_gate_state_monotonic_guard();

-- -----------------------------------------------------------------------------
-- Table / column comments
-- -----------------------------------------------------------------------------
COMMENT ON TABLE survival_gate_events IS
  'Survival Gate (.kiro/specs/survival-gate) append-only anomaly/event log (requirements.md 8.2). Written caller-side (execution-daemon) from the pure core''s emitted SurvivalEvents. INSERT-only; UPDATE/DELETE/TRUNCATE rejected by survival_gate_events_no_modify(). event_type is the design.md "Data Models" R7-reconciled 6-value vocabulary.';

COMMENT ON COLUMN survival_gate_events.event_type IS
  'One of margin_breach / forced_liquidation / safe_mode_entered / kill_switch_engaged / flatten_directive / flat_verify_failed (design.md Data Models, R7-reconciled). NO real-time `halt` event (R7: real-time halt detection out of boundary). forced_liquidation is the POST-HOC broker get_history close_reason, not a live halt signal.';

COMMENT ON COLUMN survival_gate_events.ticker IS
  'Nullable: account-level events (e.g. kill_switch_engaged) name no instrument.';

COMMENT ON TABLE survival_gate_state IS
  'Survival Gate monotonic operational-state store (requirements.md 8.1, 9.1-9.3). One CURRENT row per `scope` (singleton; DEFAULT scope=''default''). Holds the current safe_mode_grade + kill_switch flag. Transitions may TIGHTEN/ENGAGE; LOOSEN/DISENGAGE is rejected by survival_gate_state_monotonic_guard() unless the operator/after-market path opens the bypass seam (SET LOCAL survival.allow_loosen=''on''). MECHANISM in-boundary; loosening POLICY (who/when) out of boundary.';

COMMENT ON COLUMN survival_gate_state.safe_mode_grade IS
  'SafeModeGrade: NONE < TIGHTEN < HALT_NEW < FLATTEN (severity order). The monotonic guard compares by INTEGER RANK (NONE=0..FLATTEN=3), NOT by string — a string compare inverts the safety order (lexically FLATTEN<HALT_NEW<NONE<TIGHTEN) and would silently permit loosens.';

COMMENT ON COLUMN survival_gate_state.kill_switch_engaged IS
  'Emergency-halt flag (R9). FALSE->TRUE (engage) is allowed; TRUE->FALSE (disengage) is rejected by the monotonic guard unless the operator bypass seam (survival.allow_loosen GUC) is set — R9.3 operator-only re-enable.';

COMMENT ON COLUMN survival_gate_state.triggered_by_event_id IS
  'FK to the survival_gate_events row that drove the current transition (nullable: the initial NONE/disengaged row has no trigger).';

COMMIT;

-- =============================================================================
-- VERIFY: read-only catalog checks. Run after applying to confirm the migration
-- took effect. (No guard-violation probe here — that would abort under
-- ON_ERROR_STOP=1 on the shared dev DB; rejection tests live in
-- tests/integration/test_survival_gate_migration.py.)
-- =============================================================================

-- VERIFY: both tables exist.
SELECT tablename
FROM pg_tables
WHERE tablename IN ('survival_gate_events', 'survival_gate_state')
ORDER BY tablename;

-- VERIFY: the three event-log guard / FK structures.
SELECT t.tgname AS trigger_name,
       CASE WHEN (t.tgtype & 1) = 1 THEN 'ROW' ELSE 'STATEMENT' END AS level
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname IN ('survival_gate_events', 'survival_gate_state')
  AND NOT t.tgisinternal
ORDER BY c.relname, t.tgname;

-- VERIFY: the event-log indexes exist.
SELECT indexname
FROM pg_indexes
WHERE tablename = 'survival_gate_events'
  AND indexname IN ('idx_survival_gate_events_run',
                    'idx_survival_gate_events_type',
                    'idx_survival_gate_events_created_at')
ORDER BY indexname;
