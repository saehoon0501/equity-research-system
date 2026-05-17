-- =============================================================================
-- Migration: 004_v3_parameters
-- Purpose:   Versioned parameters table — central config store for all
--            tunable thresholds, prompts, weights, and policies in the v3
--            architecture. Every parameter change is captured as a new row
--            (append-only); the `effective_at` column determines which row
--            is active for any point-in-time query.
--
--            This is the foundation for `/parameters-review` (Section 1
--            Item 5) and for cross-cohort drift detection (Section 3 Q2;
--            Section 5 Q1; Section 6 catalog hygiene). Every audit-trail
--            row in subsequent tables references a `parameters_version`
--            so that recommendations can be reconstructed against the
--            exact config that produced them.
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 3.2 (Postgres tables); Section 6.3 (parameter governance);
--            Section 1 Item 5 (`/parameters-review` skill).
--
-- Schema choice:
--   - One row per (parameter_key, effective_at) tuple. Active value at
--     time T = the row with the latest effective_at <= T.
--   - `value` is JSONB so we can store scalars, arrays, full prompt text,
--     weight matrices, etc. uniformly.
--   - `description` and `change_rationale` are required so future-self can
--     reconstruct WHY a parameter changed when reviewing the history.
--   - `approved_by` captures `/parameters-review` operator-approval audit.
--   - `version_id` is a monotonically-increasing UUID-based version that
--     downstream tables reference to pin the exact config they used.
--
-- Dependencies:
--   - PostgreSQL 13+ for gen_random_uuid().
--   - JSONB column type (Postgres 9.4+; satisfied by pg16 in dev container).
--   - This migration is independent of 001-003; can apply in any order
--     after init.
--
-- How to apply (one-line psql, run from repo root):
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/004_v3_parameters.sql
--
-- Idempotency: safe to re-run. CREATE TABLE IF NOT EXISTS, CREATE INDEX
-- IF NOT EXISTS, CREATE OR REPLACE FUNCTION, DROP TRIGGER IF EXISTS.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: parameters
-- Append-only history of every parameter setting. Active value at time T
-- = the row matching parameter_key with the largest effective_at <= T.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parameters (
    version_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parameter_key       TEXT NOT NULL,            -- e.g., 'mode_classifier.market_cap_threshold_B'
    parameter_namespace TEXT NOT NULL,            -- e.g., 'mode_classifier', 'sizing', 'regime', 'materiality'
    value               JSONB NOT NULL,           -- scalar / object / array / prompt-text
    description         TEXT NOT NULL,            -- what does this parameter control?
    change_rationale    TEXT NOT NULL,            -- why is this value being set / changed?
    effective_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_by         TEXT NOT NULL,            -- 'operator' / 'launch_default' / 'parameters_review_2026Q4'
    supersedes_version  UUID REFERENCES parameters(version_id),  -- nullable; points to prior active row
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Sanity: namespace must be the prefix of parameter_key (helps query routing).
    CONSTRAINT parameters_namespace_prefix
        CHECK (parameter_key LIKE parameter_namespace || '.%')
);

-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------

-- Lookup current value of a parameter (latest effective_at per key).
CREATE INDEX IF NOT EXISTS idx_parameters_key_effective
    ON parameters(parameter_key, effective_at DESC);

-- Namespace-scoped scans (e.g., "show me all sizing parameters").
CREATE INDEX IF NOT EXISTS idx_parameters_namespace
    ON parameters(parameter_namespace, effective_at DESC);

-- Audit query — what parameters changed during a /parameters-review session?
CREATE INDEX IF NOT EXISTS idx_parameters_approved_by
    ON parameters(approved_by, created_at);

-- -----------------------------------------------------------------------------
-- View: parameters_active
-- Convenience view exposing the currently-active value per parameter.
-- Read this via mcp__postgres for "what's the current threshold?" queries.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW parameters_active AS
SELECT DISTINCT ON (parameter_key)
    version_id,
    parameter_key,
    parameter_namespace,
    value,
    description,
    effective_at,
    approved_by
FROM parameters
WHERE effective_at <= NOW()
ORDER BY parameter_key, effective_at DESC;

-- -----------------------------------------------------------------------------
-- Append-only trigger
--
-- Parameters table is append-only. To "change" a parameter, INSERT a new row
-- with a later effective_at; the parameters_active view will surface it as
-- the active value. UPDATE and DELETE are rejected.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION parameters_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'parameters is append-only — DELETE not permitted (insert a new row with later effective_at to override)';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'parameters is append-only — UPDATE not permitted (insert a new row with later effective_at to override)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS parameters_no_modify ON parameters;
CREATE TRIGGER parameters_no_modify
BEFORE UPDATE OR DELETE ON parameters
FOR EACH ROW EXECUTE FUNCTION parameters_guard();

COMMIT;

-- =============================================================================
-- VERIFY: run these after applying.
-- =============================================================================

-- VERIFY: parameters table exists.
SELECT schemaname, tablename
FROM pg_tables
WHERE tablename = 'parameters';

-- VERIFY: parameters_active view exists.
SELECT schemaname, viewname
FROM pg_views
WHERE viewname = 'parameters_active';

-- VERIFY: all 3 expected indexes are present.
SELECT indexname, tablename
FROM pg_indexes
WHERE tablename = 'parameters'
  AND indexname IN (
      'idx_parameters_key_effective',
      'idx_parameters_namespace',
      'idx_parameters_approved_by'
  )
ORDER BY indexname;

-- VERIFY: append-only trigger is wired.
SELECT t.tgname AS trigger_name, c.relname AS table_name, p.proname AS function_name
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_proc  p ON p.oid = t.tgfoid
WHERE c.relname = 'parameters'
  AND t.tgname  = 'parameters_no_modify'
  AND NOT t.tgisinternal;

-- VERIFY: namespace-prefix CHECK constraint is present.
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'parameters'::regclass
  AND contype = 'c'
ORDER BY conname;
