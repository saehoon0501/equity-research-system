-- =============================================================================
-- Migration: 045_calibration_resolver
-- Purpose:   Phase-0 (P0-2) calibration substrate for the insight-quality
--            enhancement. Extends the calibration-capture layer from
--            013_v3_calibration_capture so the WS-4 resolver can compute
--            reproducible Brier / log-loss labels against actual outcomes.
--
--            Three additive changes (all backward-compatible — no existing
--            column is dropped, renamed, or made non-nullable):
--
--              1. recommendation_outcomes gains:
--                   - label_binary         (BOOLEAN)  resolved beat/no-beat label
--                   - excess_return        (NUMERIC)  rec return minus benchmark
--                                                     over primary_horizon window
--                   - label_method_version (TEXT)     versions the labeling rule
--                                                     so a later rule change is
--                                                     auditable + re-derivable
--                   - primary_horizon      (TEXT)     which T+N window the label
--                                                     was computed over; CHECK-
--                                                     constrained to {30d,90d,1y}
--                                                     mapping 1:1 to the EXISTING
--                                                     t_plus_{30d,90d,1y}_return
--                                                     columns (NO t_plus_365).
--
--              2. recommendation_outcomes STATE-guard is widened to ALSO permit
--                 UPDATE of the four new resolver-written columns (alongside the
--                 existing t_plus_* / last_updated_at mutability) — every other
--                 column stays immutable, DELETE stays blocked.
--
--              3. New WRITE-ONCE table calibration_emission_snapshot — captures
--                 the model's emission-time state {rec_id, as_of_ts,
--                 continuous_score, p_beat_benchmark, model_version} so the Brier
--                 label is reproducible against the exact score that was emitted.
--                 Write-once = a second INSERT for the same rec_id is rejected
--                 (PK collision) and UPDATE/DELETE are blocked by a guard trigger.
--
-- primary_horizon → column mapping (1:1, enforced by application/resolver, the
-- DB just constrains the domain to the three legal values):
--      '30d' -> t_plus_30d_return  / benchmark_return_30d  / delta_vs_benchmark_30d
--      '90d' -> t_plus_90d_return  / benchmark_return_90d  / delta_vs_benchmark_90d
--      '1y'  -> t_plus_1y_return   / benchmark_return_1y   / delta_vs_benchmark_1y
--   '1y' is the 365-calendar-day window already used by mig-013's resolver
--   query. There is intentionally NO t_plus_365 column anywhere.
--
-- Reference: docs/superpowers/plans/2026-05-27-insight-quality-enhancement-parallel-plan.md
--            Phase 0, deliverable P0-2.
--
-- Dependencies:
--   - 013_v3_calibration_capture (recommendation_outcomes + its STATE guard).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/045_calibration_resolver.sql
--
-- Idempotency: safe to re-run. ADD COLUMN IF NOT EXISTS, CREATE TABLE IF NOT
-- EXISTS, CREATE OR REPLACE FUNCTION, DROP TRIGGER IF EXISTS + CREATE TRIGGER.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Extend recommendation_outcomes with resolver-written label columns.
--    All nullable (populated only once the resolver closes a window).
-- -----------------------------------------------------------------------------
ALTER TABLE recommendation_outcomes
    ADD COLUMN IF NOT EXISTS label_binary         BOOLEAN;

ALTER TABLE recommendation_outcomes
    ADD COLUMN IF NOT EXISTS excess_return        NUMERIC;

ALTER TABLE recommendation_outcomes
    ADD COLUMN IF NOT EXISTS label_method_version TEXT;

ALTER TABLE recommendation_outcomes
    ADD COLUMN IF NOT EXISTS primary_horizon      TEXT;

-- Domain constraint on primary_horizon: exactly the three windows that map
-- 1:1 to the existing t_plus_*_return columns. Added separately + guarded so a
-- re-run does not error on an already-present constraint.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'recommendation_outcomes_primary_horizon_chk'
    ) THEN
        ALTER TABLE recommendation_outcomes
            ADD CONSTRAINT recommendation_outcomes_primary_horizon_chk
            CHECK (primary_horizon IS NULL
                   OR primary_horizon IN ('30d', '90d', '1y'));
    END IF;
END$$;

-- Resolver work-queue: "which closed-window rows still need a label computed?"
CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_label_pending
    ON recommendation_outcomes(recommendation_date)
    WHERE label_binary IS NULL;

-- -----------------------------------------------------------------------------
-- 2. Widen the recommendation_outcomes STATE-guard.
--
--    The mig-013 guard rejected UPDATE of anything except t_plus_* / close_date
--    / last_updated_at. The resolver now also writes label_binary,
--    excess_return, label_method_version, primary_horizon. We must permit those
--    four to mutate while keeping every identity/benchmark/created_at column
--    immutable and DELETE blocked.
--
--    Implemented as a deny-list on the immutable columns (mirrors mig-013's own
--    style) so the four new columns are mutable by omission.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION recommendation_outcomes_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'recommendation_outcomes: DELETE not permitted';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF NEW.outcome_id            IS DISTINCT FROM OLD.outcome_id
           OR NEW.recommendation_id  IS DISTINCT FROM OLD.recommendation_id
           OR NEW.ticker             IS DISTINCT FROM OLD.ticker
           OR NEW.recommendation_date IS DISTINCT FROM OLD.recommendation_date
           OR NEW.benchmark          IS DISTINCT FROM OLD.benchmark
           OR NEW.benchmark_return_30d IS DISTINCT FROM OLD.benchmark_return_30d
           OR NEW.benchmark_return_90d IS DISTINCT FROM OLD.benchmark_return_90d
           OR NEW.benchmark_return_1y  IS DISTINCT FROM OLD.benchmark_return_1y
           OR NEW.created_at         IS DISTINCT FROM OLD.created_at
        THEN
            RAISE EXCEPTION 'recommendation_outcomes: only T+N return / close_date, label_* (label_binary, excess_return, label_method_version, primary_horizon) and last_updated_at columns are mutable';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS recommendation_outcomes_state_guard ON recommendation_outcomes;
CREATE TRIGGER recommendation_outcomes_state_guard
BEFORE UPDATE OR DELETE ON recommendation_outcomes
FOR EACH ROW EXECUTE FUNCTION recommendation_outcomes_guard();

-- -----------------------------------------------------------------------------
-- 3. calibration_emission_snapshot — write-once emission-time capture.
--
--    One row per recommendation, written at emission time. Holds the exact
--    continuous_score / p_beat_benchmark / model_version that produced the
--    recommendation, so the resolver's Brier/log-loss labels are reproducible
--    against the score as emitted (NOT a later re-scored value).
--
--    Write-once enforcement:
--      - rec_id is the PRIMARY KEY → a second INSERT for the same rec_id raises
--        a duplicate-key error.
--      - the guard trigger rejects ALL UPDATE and DELETE.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calibration_emission_snapshot (
    -- The recommendation this snapshot is for. PK ⇒ exactly one snapshot/rec.
    -- Forward-ref to execution_recommendations (FK enforced in a later
    -- migration, mirroring mig-013's forward-ref discipline).
    rec_id              UUID PRIMARY KEY,

    -- Emission timestamp — the moment the score below was produced/emitted.
    as_of_ts            TIMESTAMPTZ NOT NULL,

    -- The continuous conviction score [0,1] emitted by
    -- continuous_conviction.py at as_of_ts.
    continuous_score    NUMERIC NOT NULL
                            CHECK (continuous_score BETWEEN 0 AND 1),

    -- The model's emitted probability that the rec beats its benchmark over the
    -- primary horizon — the value Brier/log-loss is scored against.
    p_beat_benchmark    NUMERIC NOT NULL
                            CHECK (p_beat_benchmark BETWEEN 0 AND 1),

    -- Resolved (not alias) model id pinned at emission, per the (model_id,
    -- model_version) convention from mig-013's debate_consensus_history.
    model_version       TEXT NOT NULL,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- "Snapshots in emission-time order" — drives backfilled-history calibration.
CREATE INDEX IF NOT EXISTS idx_calibration_emission_snapshot_as_of
    ON calibration_emission_snapshot(as_of_ts);

CREATE INDEX IF NOT EXISTS idx_calibration_emission_snapshot_model
    ON calibration_emission_snapshot(model_version, as_of_ts);

-- -----------------------------------------------------------------------------
-- Write-once guard — calibration_emission_snapshot.
-- Blocks UPDATE and DELETE entirely; the PK blocks duplicate INSERT.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION calibration_emission_snapshot_guard() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'calibration_emission_snapshot is write-once — % not permitted (one snapshot per rec_id, set at emission time)', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS calibration_emission_snapshot_write_once
    ON calibration_emission_snapshot;
CREATE TRIGGER calibration_emission_snapshot_write_once
BEFORE UPDATE OR DELETE ON calibration_emission_snapshot
FOR EACH ROW EXECUTE FUNCTION calibration_emission_snapshot_guard();

COMMIT;

-- =============================================================================
-- VERIFY: run these after applying.
-- =============================================================================

-- VERIFY: the four new columns exist on recommendation_outcomes.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'recommendation_outcomes'
  AND column_name IN ('label_binary', 'excess_return',
                      'label_method_version', 'primary_horizon')
ORDER BY column_name;

-- VERIFY: primary_horizon CHECK constraint is present + correct domain.
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conname = 'recommendation_outcomes_primary_horizon_chk';

-- VERIFY: primary_horizon maps 1:1 to existing columns — no t_plus_365 anywhere.
--   This SELECT joins each legal horizon value to its matching column via a
--   CASE; it must resolve for every row without referencing t_plus_365.
SELECT outcome_id,
       primary_horizon,
       CASE primary_horizon
           WHEN '30d' THEN t_plus_30d_return
           WHEN '90d' THEN t_plus_90d_return
           WHEN '1y'  THEN t_plus_1y_return
       END AS resolved_horizon_return
FROM recommendation_outcomes
WHERE primary_horizon IS NOT NULL
LIMIT 5;

-- VERIFY: calibration_emission_snapshot exists with the write-once trigger.
SELECT t.tgname AS trigger_name, c.relname AS table_name, p.proname AS function_name
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_proc  p ON p.oid = t.tgfoid
WHERE c.relname = 'calibration_emission_snapshot'
  AND NOT t.tgisinternal
ORDER BY t.tgname;

-- VERIFY (manual / requires live DB): write-once is enforced.
--   1) INSERT a snapshot for some rec_id            -> OK
--   2) INSERT a SECOND snapshot for the same rec_id -> ERROR (duplicate key)
--   3) UPDATE that snapshot                         -> ERROR (write-once guard)
--   4) DELETE that snapshot                         -> ERROR (write-once guard)

-- VERIFY (manual / requires live DB): recommendation_outcomes STATE-guard.
--   - UPDATE label_binary / excess_return / label_method_version /
--     primary_horizon / t_plus_*_return / last_updated_at -> OK
--   - UPDATE ticker / recommendation_id / benchmark / created_at -> ERROR
--   - DELETE any row -> ERROR
