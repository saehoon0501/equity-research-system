-- =============================================================================
-- Migration: 015_v3_calibration_test_results
-- Purpose:   Calibration-test ledger — stores results from periodic test
--            runs against canonical gold-standard sets (canonical-survivor /
--            canonical-non-survivor archetypes; pain-date retrieval
--            agreement; archetype-coverage agreement within ±1).
--
--            One append-only table:
--              - calibration_test_results
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 3.2 (Postgres tables); Section 6 (Quality-Control table
--            — calibration cadence); Section 7 v0.1 launch gates (canonical
--            archetype walkthroughs).
--
-- Schema notes:
--   - per_case_results carries the per-ticker test outcomes:
--       array of {
--         ticker: text,
--         peak_pain_date: date,
--         expected_archetype_distribution: { archetype: weight, ... },
--         retrieved_archetype_distribution: { archetype: weight, ... },
--         agreement_within_pm1: bool,    -- ±1 archetype tolerance
--         pass: bool
--       }
--   - archetype_coverage_agreement_pct = % of cases where
--     agreement_within_pm1 = true.
--   - canonical_survivor_correctness_pct / canonical_non_survivor_correctness_pct
--     break down pass-rate by canonical group.
--   - catalog_version_hash pins the archetype catalog snapshot used for the
--     test (so historical test runs can be replayed against the exact catalog
--     version under which they were executed).
--
-- Append-only — every test run is its own row.
--
-- Dependencies:
--   - 004_v3_parameters (parameters_version FK)
--   - PostgreSQL 13+
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/015_v3_calibration_test_results.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: calibration_test_results
-- One row per (test_run_date, test_set_name) tuple.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calibration_test_results (
    test_id                                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    test_run_date                              DATE NOT NULL,
    test_set_name                              TEXT NOT NULL,

    -- Per-case outcomes (see header for schema).
    per_case_results                           JSONB NOT NULL,

    -- Aggregate agreement: % of cases retrieving the expected archetype
    -- distribution within ±1 archetype tolerance.
    archetype_coverage_agreement_pct           NUMERIC NOT NULL
        CHECK (archetype_coverage_agreement_pct BETWEEN 0 AND 100),

    -- Canonical group correctness breakdown (Section 7 launch gate).
    canonical_survivor_correctness_pct         NUMERIC NOT NULL
        CHECK (canonical_survivor_correctness_pct BETWEEN 0 AND 100),
    canonical_non_survivor_correctness_pct     NUMERIC NOT NULL
        CHECK (canonical_non_survivor_correctness_pct BETWEEN 0 AND 100),

    -- Pin the catalog snapshot under which this test was executed.
    catalog_version_hash                       TEXT NOT NULL,

    parameters_version                         UUID,        -- FK to parameters.version_id
    created_at                                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT calibration_test_unique
        UNIQUE (test_run_date, test_set_name, catalog_version_hash)
);

-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_calib_test_run_date
    ON calibration_test_results(test_run_date DESC);

CREATE INDEX IF NOT EXISTS idx_calib_test_set_name
    ON calibration_test_results(test_set_name, test_run_date DESC);

CREATE INDEX IF NOT EXISTS idx_calib_test_catalog_version
    ON calibration_test_results(catalog_version_hash);

-- -----------------------------------------------------------------------------
-- Append-only trigger
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION calibration_test_results_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'calibration_test_results is append-only — % not permitted (insert a new row to record a fresh test run)', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS calibration_test_results_no_modify ON calibration_test_results;
CREATE TRIGGER calibration_test_results_no_modify
BEFORE UPDATE OR DELETE ON calibration_test_results
FOR EACH ROW EXECUTE FUNCTION calibration_test_results_guard();

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

SELECT schemaname, tablename FROM pg_tables WHERE tablename = 'calibration_test_results';

SELECT indexname, tablename FROM pg_indexes
WHERE tablename = 'calibration_test_results'
ORDER BY indexname;

SELECT t.tgname, c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'calibration_test_results' AND NOT t.tgisinternal;

SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'calibration_test_results'::regclass
  AND contype IN ('c', 'u')
ORDER BY conname;
