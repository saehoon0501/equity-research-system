-- =============================================================================
-- Migration: 014_v3_system_health
-- Purpose:   System-health observability — captures every MCP / data-pipe
--            failure, retry, and escalation; plus a stub view that will
--            compare system-vs-operator Brier scores once the prediction +
--            outcome + override tables land in later migrations.
--
--            Two artifacts:
--              - system_errors             (Section 8 Q6 — MCP failures,
--                                           retries, escalations)
--              - system_vs_operator_brier  (Phase 4 Q6 — STUB at v0.1; live
--                                           body lands once migrations
--                                           008 + 013 materialize the
--                                           dependent tables)
--
--            Per Section 7.5 / Section 8 Q6: never silent-fail; every MCP
--            failure logged here. The `/system-health` skill (Section 5.4
--            slash commands) reads this table for unified visibility.
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 3.2 (system_errors row);
--            Section 7.5 (cold-start + error handling);
--            Section 8 Q6 / Phase 4 Q6 (system-vs-operator Brier comparison).
--
-- Schema choice:
--   - error_id is UUID PK; timestamp_at defaults to NOW (insert-time).
--   - source is free-text (e.g., 'mcp__edgar__get_filings') so it can
--     accommodate any tool / subsystem identifier without a closed enum.
--   - blocked_decision is the operational pointer — what couldn't proceed
--     because of this failure (free-text, not FK; the failure may block
--     decisions across multiple subsystems).
--   - Append-mostly (NOT pure append-only): UPDATE allowed only on
--     resolution + resolved_at + retry_count + escalated_to_alert.
--     Block UPDATE on history rows (timestamp_at, source, error_type,
--     error_detail, blocked_decision). Block DELETE always.
--
-- system_vs_operator_brier (STUB):
--   The view body is intentionally a zero-row placeholder. When migrations
--   008 (execution_recommendations + recommendation_outcomes) and 013
--   (operator_overrides) land, this view should be REPLACED via
--   `CREATE OR REPLACE VIEW` in a follow-up migration with the real body
--   that joins those tables and computes per-cell Brier.
--
--   STUB CTE shape preserved so downstream consumers can develop against
--   the schema before the underlying tables exist:
--     mode | materiality | rec_type | system_brier | operator_brier | n
--
-- Dependencies:
--   - PostgreSQL 13+ (gen_random_uuid).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/014_v3_system_health.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: system_errors
-- Append-mostly log of every system / MCP / data-pipe failure.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS system_errors (
    error_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- e.g., 'mcp__edgar__get_filings', 'mcp__broker__get_positions',
    --       'regime_classifier_s0', 'p3_scorer_stage1b'
    source                TEXT NOT NULL,

    -- e.g., 'rate_limit', 'timeout', 'schema_mismatch', 'auth_failed',
    --       'data_stale', 'unexpected_null'
    error_type            TEXT NOT NULL,
    error_detail          TEXT NOT NULL,

    retry_count           INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    escalated_to_alert    BOOLEAN NOT NULL DEFAULT FALSE,

    -- What downstream decision was blocked because of this failure.
    -- e.g., 'P3_scoring_NVDA_2026-04-29', 'daily_refresh_full_watchlist'.
    blocked_decision      TEXT,

    -- Operator / auto-recovery resolution narrative.
    resolution            TEXT,
    resolved_at           TIMESTAMPTZ,

    CONSTRAINT system_errors_resolved_consistency
        CHECK (
            (resolved_at IS NULL AND resolution IS NULL)
            OR (resolved_at IS NOT NULL AND resolution IS NOT NULL)
        )
);

-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_system_errors_source_time
    ON system_errors(source, timestamp_at DESC);

CREATE INDEX IF NOT EXISTS idx_system_errors_unresolved
    ON system_errors(timestamp_at DESC)
    WHERE resolved_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_system_errors_escalated
    ON system_errors(escalated_to_alert, timestamp_at DESC)
    WHERE escalated_to_alert = TRUE;

CREATE INDEX IF NOT EXISTS idx_system_errors_type
    ON system_errors(error_type, timestamp_at DESC);

-- -----------------------------------------------------------------------------
-- Append-mostly trigger
--
-- Allowed UPDATEs (operational mutations during error lifecycle):
--   resolution, resolved_at, retry_count, escalated_to_alert
-- Blocked UPDATEs (history columns):
--   error_id, timestamp_at, source, error_type, error_detail, blocked_decision
-- DELETE: blocked unconditionally.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION system_errors_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'system_errors is delete-protected — DELETE not permitted (audit trail)';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.error_id IS DISTINCT FROM NEW.error_id THEN
            RAISE EXCEPTION 'system_errors.error_id is immutable';
        END IF;
        IF OLD.timestamp_at IS DISTINCT FROM NEW.timestamp_at THEN
            RAISE EXCEPTION 'system_errors.timestamp_at is immutable';
        END IF;
        IF OLD.source IS DISTINCT FROM NEW.source THEN
            RAISE EXCEPTION 'system_errors.source is immutable';
        END IF;
        IF OLD.error_type IS DISTINCT FROM NEW.error_type THEN
            RAISE EXCEPTION 'system_errors.error_type is immutable';
        END IF;
        IF OLD.error_detail IS DISTINCT FROM NEW.error_detail THEN
            RAISE EXCEPTION 'system_errors.error_detail is immutable';
        END IF;
        IF OLD.blocked_decision IS DISTINCT FROM NEW.blocked_decision THEN
            RAISE EXCEPTION 'system_errors.blocked_decision is immutable (record a new error if scope changes)';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS system_errors_guard_trg ON system_errors;
CREATE TRIGGER system_errors_guard_trg
BEFORE UPDATE OR DELETE ON system_errors
FOR EACH ROW EXECUTE FUNCTION system_errors_guard();

-- -----------------------------------------------------------------------------
-- View: system_vs_operator_brier (STUB — Phase 4 Q6)
--
-- Real body computes per-cell Brier comparison from:
--   execution_recommendations  (migration 008, not yet applied)
--   recommendation_outcomes    (migration 008, not yet applied)
--   operator_overrides         (migration 013, not yet applied)
--
-- Cell key: (mode, materiality, recommendation_type)
-- Output:  mode | materiality | rec_type | system_brier | operator_brier | n
--
-- This stub returns zero rows so consumers can develop against the schema
-- shape before the dependent tables exist. REPLACE this view body in a
-- follow-up migration once 008 + 013 land.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW system_vs_operator_brier AS
WITH placeholder AS (
    SELECT
        NULL::TEXT     AS mode,
        NULL::INTEGER  AS materiality,
        NULL::TEXT     AS rec_type,
        NULL::NUMERIC  AS system_brier,
        NULL::NUMERIC  AS operator_brier,
        NULL::INTEGER  AS n
    WHERE FALSE
)
SELECT * FROM placeholder;

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

-- VERIFY: system_errors table exists.
SELECT schemaname, tablename FROM pg_tables WHERE tablename = 'system_errors';

-- VERIFY: stub view exists.
SELECT schemaname, viewname FROM pg_views WHERE viewname = 'system_vs_operator_brier';

-- VERIFY: stub view returns zero rows (and has the expected columns).
SELECT * FROM system_vs_operator_brier;

-- VERIFY: indexes present.
SELECT indexname, tablename FROM pg_indexes
WHERE tablename = 'system_errors'
  AND indexname LIKE 'idx_system_errors%'
ORDER BY indexname;

-- VERIFY: guard trigger wired.
SELECT t.tgname, c.relname FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'system_errors'
  AND t.tgname = 'system_errors_guard_trg'
  AND NOT t.tgisinternal;

-- VERIFY: CHECK constraints.
SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
WHERE conrelid = 'system_errors'::regclass AND contype = 'c'
ORDER BY conname;
