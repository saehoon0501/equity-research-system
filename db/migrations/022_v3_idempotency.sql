-- =============================================================================
-- Migration: 022_v3_idempotency
-- Purpose:   Add natural-key UNIQUE constraints to write paths that previously
--            relied on operator-discipline alone for idempotency. Closes the
--            duplicate-row class of bugs found by the v3 idempotency audit.
--
--            Tables touched:
--              - premortem            UNIQUE (ticker, premortem_date, trigger)
--              - materiality_events   UNIQUE (event_id_natural)  -- via composite
--                                     UNIQUE (ticker, event_date, event_type,
--                                             source_id, verbatim_quote)
--
--            DO NOT change column types or alter any of migrations 001-021's
--            spec-locked schema. This migration only ADDs constraints +
--            indexes.
--
-- Bug class: a function writes rows. If the operator (or a cron job) runs
-- it twice with identical inputs after a partial failure, the v0.1 INSERTs
-- WITHOUT ON CONFLICT would either:
--   (a) duplicate rows silently — corrupts downstream rollups (e.g., one
--       logical event counted twice in the daily-monitor materiality
--       histogram), OR
--   (b) raise a UniqueViolation that aborts the entire enclosing
--       transaction — surfaces as opaque "system_error" with no recovery
--       path for the operator.
--
-- Fix strategy:
--   1. Add a UNIQUE constraint at the natural-key tuple — DB-side defense.
--   2. Update the application-layer INSERT to use ON CONFLICT DO NOTHING
--      (first-call-wins semantics for event-log tables; first-call-wins
--      is correct because the second call for the same logical event is
--      either a retry of the first or a duplicate operator submission).
--
-- Rollout note:
--   These ALTER TABLE ADD CONSTRAINT statements WILL FAIL if the existing
--   rows in production already contain duplicates at the natural-key
--   tuple. Operator MUST run the verification queries below BEFORE
--   applying this migration; if duplicates exist, deduplicate manually
--   (preserve the lowest-created_at row; archive the rest to a quarantine
--   table for forensic review).
--
-- Reference:
--   Idempotency-audit findings: 6 production bugs class (parallel to the
--   3 HMAC-coercion + 3 transaction-boundary classes already shipped).
--
-- Dependencies:
--   - 009_v3_daily_monitor (materiality_events table)
--   - 012_v3_premortem    (premortem table)
--
-- How to apply:
--   # 1. PRE-CHECK (fail loudly if duplicates exist):
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -c "SELECT ticker, premortem_date, trigger, COUNT(*) \
--            FROM premortem GROUP BY 1,2,3 HAVING COUNT(*) > 1;"
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -c "SELECT ticker, event_date, event_type, source_id, \
--                   md5(verbatim_quote), COUNT(*) \
--            FROM materiality_events GROUP BY 1,2,3,4,5 HAVING COUNT(*) > 1;"
--   # 2. Apply migration:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/022_v3_idempotency.sql
--
-- Idempotency: safe to re-run (uses IF NOT EXISTS / DO $$ block guards).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- premortem: natural-key UNIQUE (ticker, premortem_date, trigger)
--
-- Operator submits a pre-mortem session via /premortem; double-click on a
-- flaky network or a cron-driven trigger could call record_premortem twice.
-- Migration 012 originally allowed multiple rows per (ticker, date, trigger)
-- under the rationale "revisions written as new rows" — but in practice
-- revisions append a NEW trigger (e.g., calendar_floor → mode_reclass);
-- a true revision-of-same-trigger is rare and operator-driven (handled by
-- /premortem with --replace flag in v0.5+).
--
-- For v0.1: lock the natural key. The application layer uses ON CONFLICT
-- DO NOTHING so duplicate submissions become silent no-ops.
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'premortem_natural_key_unique'
          AND conrelid = 'premortem'::regclass
    ) THEN
        ALTER TABLE premortem
            ADD CONSTRAINT premortem_natural_key_unique
            UNIQUE (ticker, premortem_date, trigger);
    END IF;
END $$;


-- -----------------------------------------------------------------------------
-- materiality_events: natural-key UNIQUE
--   (ticker, event_date, event_type, source_id, md5(verbatim_quote))
--
-- The verbatim_quote column carries the LLM-extracted quote that uniquely
-- identifies the event within the (ticker, date, type, source) tuple — two
-- M-2 fires for the same source_id at the same timestamp with DIFFERENT
-- verbatim quotes are legitimately distinct events; SAME quote on retry
-- is a duplicate.
--
-- We can't UNIQUE on raw TEXT (verbatim quotes can be > btree size limit)
-- so we use a UNIQUE INDEX on md5(verbatim_quote). MD5 is acceptable here
-- because we're only deduping retries of the SAME source quote — not
-- defending against adversarial collisions.
-- -----------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS materiality_events_natural_key_unique
    ON materiality_events
    (ticker, event_date, event_type, source_id, md5(verbatim_quote));


COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

-- VERIFY: premortem unique constraint exists.
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'premortem'::regclass
  AND conname = 'premortem_natural_key_unique';

-- VERIFY: materiality_events unique index exists.
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'materiality_events'
  AND indexname = 'materiality_events_natural_key_unique';

-- VERIFY: no duplicates currently in either table (should return 0 rows each).
SELECT 'premortem' AS table_name, COUNT(*) AS dupe_groups
FROM (
    SELECT ticker, premortem_date, trigger, COUNT(*) AS n
    FROM premortem
    GROUP BY 1, 2, 3
    HAVING COUNT(*) > 1
) p
UNION ALL
SELECT 'materiality_events' AS table_name, COUNT(*) AS dupe_groups
FROM (
    SELECT ticker, event_date, event_type, source_id, md5(verbatim_quote), COUNT(*) AS n
    FROM materiality_events
    GROUP BY 1, 2, 3, 4, 5
    HAVING COUNT(*) > 1
) m;
