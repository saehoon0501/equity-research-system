-- =============================================================================
-- Migration: 002_predictions.sql
-- Purpose:   Create the Predictions DB table — the canonical store for every
--            falsifiable, dated prediction emitted by any agent (CompanyDeepDive
--            reviewable_predictions, BearCase predictions, MacroCycle regime
--            calls, PMSupervisor portfolio claims, DailyMonitor materiality
--            predictions). Resolution job (per .claude/references/prediction-
--            resolution.md) writes back into the resolution-fields columns when
--            the resolution_date hits.
--
-- Dependencies:
--   - Postgres 16
--   - pgcrypto extension (for gen_random_uuid()) — assumed installed in
--     migration 001 (extensions). If not, this migration enables it
--     idempotently below.
--   - TimescaleDB extension is NOT required for this table (Predictions is a
--     row store, not a hypertable — predictions are sparse and queried by
--     resolution_date / agent_run_id, not by continuous time series).
--
-- How to apply:
--     docker exec -i equity-research-db \
--         psql -U postgres -d equity_research \
--         < db/migrations/002_predictions.sql
--
-- Schema choice:
--   NOTE: docs/v2-final-spec.md does NOT contain a fully-specified Predictions
--   DB CREATE TABLE statement. §3.2 ("Outcome Rubrics") and §4.4 ("Resolves
--   predictions due today") reference the table conceptually, and
--   .claude/references/prediction-resolution.md gives a worked example with
--   fields {prediction_id, agent_run_id, ticker, claim, direction,
--   target_value, resolution_date, confidence}. That example is illustrative,
--   not a normative schema. THIS MIGRATION USES THE MINIMAL VIABLE SCHEMA
--   defined in the build-task spec, which is a strict superset of the example
--   (it generalizes `claim` -> `prediction_text`, `direction/target_value` ->
--   the typed (p10/p50/p90) + (predicted_outcome) split, and adds explicit
--   resolution-job write-back columns). When the v2 spec is updated with a
--   normative schema, a follow-up migration may add columns; this one will
--   not be breaking.
--
-- Append-only contract:
--   Per .claude/references/prediction-resolution.md ("predictions are append-
--   only") and v2-final §4.2.5 ("Append-only — no deletions or updates")
--   applied analogously here, this table:
--     - REJECTS all DELETEs.
--     - ALLOWS UPDATEs only on the resolution-fields tuple
--       (resolution_date, resolved_value, resolved_outcome, resolved_correct,
--       brier_component) — and only when the prior value of each touched
--       field was NULL is implicit by the resolution job's idempotency
--       discipline; this trigger does not enforce that, it only enforces the
--       column boundary. Updates that change any other column are rejected.
--   Enforced via the prediction_no_mutation trigger below.
-- =============================================================================

-- 0. Extensions ---------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Table --------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS predictions (
    prediction_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id             TEXT        NOT NULL,
    agent_run_id         UUID        NOT NULL,
    prediction_text      TEXT        NOT NULL,
    prediction_type      TEXT        NOT NULL,
    target_metric        TEXT,
    target_date          DATE        NOT NULL,
    p10                  NUMERIC,
    p50                  NUMERIC,
    p90                  NUMERIC,
    predicted_outcome    TEXT,
    resolution_date      DATE,
    resolved_value       NUMERIC,
    resolved_outcome     TEXT,
    resolved_correct     BOOLEAN,
    brier_component      NUMERIC,
    related_position_id  UUID,
    created_at           TIMESTAMP   NOT NULL DEFAULT NOW(),

    -- prediction_type vocabulary
    CONSTRAINT predictions_type_check
        CHECK (prediction_type IN ('point_estimate','range','binary','categorical')),

    -- p10 <= p50 <= p90 when all three are present (range predictions)
    CONSTRAINT predictions_quantile_order_check
        CHECK (
            p10 IS NULL OR p50 IS NULL OR p90 IS NULL
            OR (p10 <= p50 AND p50 <= p90)
        ),

    -- numerical predictions populate the quantile columns; categorical/binary
    -- populate predicted_outcome. Enforce loose alignment.
    CONSTRAINT predictions_shape_by_type_check
        CHECK (
            (prediction_type IN ('point_estimate','range')
                AND (p10 IS NOT NULL OR p50 IS NOT NULL OR p90 IS NOT NULL))
            OR (prediction_type IN ('binary','categorical')
                AND predicted_outcome IS NOT NULL)
        ),

    -- target_date sanity: cannot be before created_at
    CONSTRAINT predictions_target_after_created_check
        CHECK (target_date >= created_at::date),

    -- Brier component, when populated, is in [0, 1]
    CONSTRAINT predictions_brier_range_check
        CHECK (brier_component IS NULL OR (brier_component >= 0 AND brier_component <= 1)),

    -- Resolution coherence: if resolution_date is set, at least one of
    -- (resolved_value, resolved_outcome, resolved_correct) must be set.
    CONSTRAINT predictions_resolution_coherence_check
        CHECK (
            resolution_date IS NULL
            OR (resolved_value IS NOT NULL
                OR resolved_outcome IS NOT NULL
                OR resolved_correct IS NOT NULL)
        )
);

-- 2. Indexes ------------------------------------------------------------------

-- Lookup all predictions emitted by a single agent run (memo, daily-monitor
-- batch, etc.).
CREATE INDEX IF NOT EXISTS idx_predictions_agent_run_id
    ON predictions (agent_run_id);

-- "Predictions due today" — the resolution job's hot path.
CREATE INDEX IF NOT EXISTS idx_predictions_target_date
    ON predictions (target_date);

-- Resolved-set queries (calibration views over resolved_at proxy).
CREATE INDEX IF NOT EXISTS idx_predictions_resolution_date
    ON predictions (resolution_date)
    WHERE resolution_date IS NOT NULL;

-- Per-agent calibration view scans.
CREATE INDEX IF NOT EXISTS idx_predictions_agent_id
    ON predictions (agent_id);

-- 3. Append-only / conditional-update trigger ---------------------------------
--
-- Contract:
--   - DELETE: always rejected.
--   - INSERT: always allowed (PK + CHECK constraints handle validity).
--   - UPDATE: allowed iff every non-resolution column is unchanged
--     (compared with IS DISTINCT FROM, which treats NULL safely). The
--     resolution-fields columns may be freely written by the resolution job.
--
-- The set of mutable columns is:
--     resolution_date, resolved_value, resolved_outcome, resolved_correct,
--     brier_component
-- All other columns must satisfy NEW.col IS NOT DISTINCT FROM OLD.col.

CREATE OR REPLACE FUNCTION predictions_enforce_append_only()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'predictions table is append-only: DELETE rejected (prediction_id=%)',
            OLD.prediction_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        -- Identity / immutable metadata columns must not change.
        IF NEW.prediction_id      IS DISTINCT FROM OLD.prediction_id      THEN
            RAISE EXCEPTION 'predictions: prediction_id is immutable';
        END IF;
        IF NEW.agent_id           IS DISTINCT FROM OLD.agent_id           THEN
            RAISE EXCEPTION 'predictions: agent_id is immutable (prediction_id=%)',
                OLD.prediction_id;
        END IF;
        IF NEW.agent_run_id       IS DISTINCT FROM OLD.agent_run_id       THEN
            RAISE EXCEPTION 'predictions: agent_run_id is immutable (prediction_id=%)',
                OLD.prediction_id;
        END IF;
        IF NEW.prediction_text    IS DISTINCT FROM OLD.prediction_text    THEN
            RAISE EXCEPTION 'predictions: prediction_text is immutable (prediction_id=%)',
                OLD.prediction_id;
        END IF;
        IF NEW.prediction_type    IS DISTINCT FROM OLD.prediction_type    THEN
            RAISE EXCEPTION 'predictions: prediction_type is immutable (prediction_id=%)',
                OLD.prediction_id;
        END IF;
        IF NEW.target_metric      IS DISTINCT FROM OLD.target_metric      THEN
            RAISE EXCEPTION 'predictions: target_metric is immutable (prediction_id=%)',
                OLD.prediction_id;
        END IF;
        IF NEW.target_date        IS DISTINCT FROM OLD.target_date        THEN
            RAISE EXCEPTION 'predictions: target_date is immutable (prediction_id=%)',
                OLD.prediction_id;
        END IF;
        IF NEW.p10                IS DISTINCT FROM OLD.p10                THEN
            RAISE EXCEPTION 'predictions: p10 is immutable (prediction_id=%)',
                OLD.prediction_id;
        END IF;
        IF NEW.p50                IS DISTINCT FROM OLD.p50                THEN
            RAISE EXCEPTION 'predictions: p50 is immutable (prediction_id=%)',
                OLD.prediction_id;
        END IF;
        IF NEW.p90                IS DISTINCT FROM OLD.p90                THEN
            RAISE EXCEPTION 'predictions: p90 is immutable (prediction_id=%)',
                OLD.prediction_id;
        END IF;
        IF NEW.predicted_outcome  IS DISTINCT FROM OLD.predicted_outcome  THEN
            RAISE EXCEPTION 'predictions: predicted_outcome is immutable (prediction_id=%)',
                OLD.prediction_id;
        END IF;
        IF NEW.related_position_id IS DISTINCT FROM OLD.related_position_id THEN
            RAISE EXCEPTION 'predictions: related_position_id is immutable (prediction_id=%)',
                OLD.prediction_id;
        END IF;
        IF NEW.created_at         IS DISTINCT FROM OLD.created_at         THEN
            RAISE EXCEPTION 'predictions: created_at is immutable (prediction_id=%)',
                OLD.prediction_id;
        END IF;

        -- All checked columns are unchanged. The remaining columns
        -- (resolution_date, resolved_value, resolved_outcome,
        --  resolved_correct, brier_component) are the resolution-fields
        -- tuple and are writable by the resolution job.
        RETURN NEW;
    END IF;

    -- INSERT path: nothing to check beyond CHECK constraints.
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS predictions_no_mutation ON predictions;

CREATE TRIGGER predictions_no_mutation
    BEFORE UPDATE OR DELETE ON predictions
    FOR EACH ROW
    EXECUTE FUNCTION predictions_enforce_append_only();

-- =============================================================================
-- VERIFY: copy/paste these into psql after applying the migration.
-- =============================================================================

-- VERIFY: table exists with expected columns
-- SELECT column_name, data_type, is_nullable
--   FROM information_schema.columns
--  WHERE table_schema = 'public'
--    AND table_name = 'predictions'
--  ORDER BY ordinal_position;

-- VERIFY: indexes exist
-- SELECT indexname, indexdef
--   FROM pg_indexes
--  WHERE schemaname = 'public'
--    AND tablename = 'predictions'
--  ORDER BY indexname;

-- VERIFY: append-only trigger is attached
-- SELECT tgname, tgtype, tgenabled, pg_get_triggerdef(oid) AS definition
--   FROM pg_trigger
--  WHERE tgrelid = 'public.predictions'::regclass
--    AND NOT tgisinternal;

-- VERIFY: trigger function is installed
-- SELECT proname, prolang::regtype, pg_get_functiondef(oid) IS NOT NULL AS has_body
--   FROM pg_proc
--  WHERE proname = 'predictions_enforce_append_only';

-- VERIFY: CHECK constraints in place
-- SELECT conname, pg_get_constraintdef(oid)
--   FROM pg_constraint
--  WHERE conrelid = 'public.predictions'::regclass
--    AND contype = 'c'
--  ORDER BY conname;

-- VERIFY (smoke test, run in a ROLLBACK'd txn):
--   BEGIN;
--   INSERT INTO predictions (agent_id, agent_run_id, prediction_text,
--                            prediction_type, target_date, p50)
--     VALUES ('company-deep-dive', gen_random_uuid(),
--             'Revenue exceeds $X by FY26 Q4', 'point_estimate',
--             CURRENT_DATE + INTERVAL '60 days', 1234.5);
--   -- Expect: success.
--   UPDATE predictions SET resolved_value = 1300, resolution_date = CURRENT_DATE
--     WHERE prediction_text = 'Revenue exceeds $X by FY26 Q4';
--   -- Expect: success (resolution-fields update).
--   UPDATE predictions SET prediction_text = 'changed'
--     WHERE prediction_text = 'Revenue exceeds $X by FY26 Q4';
--   -- Expect: ERROR -- prediction_text is immutable.
--   DELETE FROM predictions
--    WHERE prediction_text = 'Revenue exceeds $X by FY26 Q4';
--   -- Expect: ERROR -- DELETE rejected.
--   ROLLBACK;
