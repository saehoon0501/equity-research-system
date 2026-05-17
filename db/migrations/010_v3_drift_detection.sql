-- =============================================================================
-- Migration: 010_v3_drift_detection
-- Purpose:   Drift-detection sidecar tables — three independent monitors that
--            continuously test whether the system's anchors and classifiers
--            are still calibrated to the world.
--
--            Three append-only tables:
--              - anchor_drift_checks            (Section 6 Q5 — 3 channels:
--                                                 pillar drift, outcome
--                                                 divergence, periodic re-read)
--              - materiality_classifier_drift   (Phase 4 Q8 — quarterly drift
--                                                 watch + rolling 30-event
--                                                 gold standard + confidence
--                                                 distribution monitoring)
--              - mode_vol_checks                (Phase 4 Q5 — semi-annual
--                                                 mode-implied-vol silent-
--                                                 failure detection)
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 3.2 (Postgres tables); Section 6 Q5 (3 anchor-drift
--            channels); Section 6.3 / Quality-Control table; Phase 4 Q5
--            (mode silent-failure detection); Phase 4 Q8 (materiality
--            classifier drift watch).
--
-- Channel discipline (Section 6 Q5): the three anchor-drift channels are
-- independent — channel_1 (LLM-diff of original-vs-current pillars),
-- channel_2 (outcome vs original projection), channel_3 (calendar-floor
-- periodic re-read). any_triggered = OR of the three; forced_review
-- captures the operator-acknowledgement workflow when any channel fires.
--
-- Dependencies:
--   - 004_v3_parameters (parameters_version FK)
--   - PostgreSQL 13+
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/010_v3_drift_detection.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: anchor_drift_checks
-- Per Section 6 Q5: three independent anchor-drift channels per name.
-- Each channel emits a structured payload + a `triggered` boolean; the
-- top-level any_triggered column is the OR. forced_review tracks the
-- operator-acknowledgement workflow when at least one channel fires.
--
-- One row per (ticker, check_date). Append-only.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS anchor_drift_checks (
    check_id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker                        TEXT NOT NULL,
    check_date                    DATE NOT NULL,

    -- Channel 1: LLM diff of original (HMAC-signed) thesis pillars vs current.
    --   { drift_score: numeric (0-1),
    --     pillars_softened: [...],
    --     pillars_rewritten: [...],
    --     diff_llm_model: text,
    --     triggered: bool   (true when drift_score > 0.25 per spec) }
    channel_1_pillar_drift        JSONB NOT NULL,

    -- Channel 2: outcome divergence vs original projection.
    --   { last_earnings: date,
    --     revenue_actual: numeric, revenue_projected: numeric,
    --     margin_actual:  numeric, margin_projected:  numeric,
    --     fcf_actual:     numeric, fcf_projected:     numeric,
    --     triggered: bool }
    channel_2_outcome_divergence  JSONB NOT NULL,

    -- Channel 3: calendar-floor periodic re-read.
    --   { last_reread: date,
    --     days_elapsed: int,
    --     cadence_threshold_days: int,
    --     triggered: bool   (days_elapsed >= cadence_threshold_days) }
    channel_3_periodic_reread     JSONB NOT NULL,

    -- Top-level OR — denormalized for fast "give me all triggered names" scan.
    any_triggered                 BOOLEAN NOT NULL,

    -- Forced-review workflow (nullable until a channel triggers):
    --   { type: 'pillar_drift'|'outcome_divergence'|'periodic_reread'|...,
    --     surfaced_to: 'operator',
    --     operator_acknowledged_at: timestamptz,
    --     operator_decision: 'reaffirm'|'revise_with_rationale'|'cut'|'pending' }
    forced_review                 JSONB,

    parameters_version            UUID,                   -- FK to parameters.version_id
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT anchor_drift_review_decision_valid
        CHECK (forced_review IS NULL
               OR (forced_review->>'operator_decision') IS NULL
               OR (forced_review->>'operator_decision') IN
                  ('reaffirm', 'revise_with_rationale', 'cut', 'pending')),

    CONSTRAINT anchor_drift_unique_per_day
        UNIQUE (ticker, check_date)
);

CREATE INDEX IF NOT EXISTS idx_anchor_drift_ticker_date
    ON anchor_drift_checks(ticker, check_date DESC);

CREATE INDEX IF NOT EXISTS idx_anchor_drift_triggered
    ON anchor_drift_checks(check_date DESC)
    WHERE any_triggered = true;

CREATE OR REPLACE FUNCTION anchor_drift_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'anchor_drift_checks is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS anchor_drift_no_modify ON anchor_drift_checks;
CREATE TRIGGER anchor_drift_no_modify
BEFORE UPDATE OR DELETE ON anchor_drift_checks
FOR EACH ROW EXECUTE FUNCTION anchor_drift_guard();


-- -----------------------------------------------------------------------------
-- Table: materiality_classifier_drift
-- Per Phase 4 Q8: quarterly drift watch on the materiality classifier.
-- N >= 30 sample size requirement; rolling 30-event gold standard re-rated
-- each quarter; confidence distribution (P50/P90) shifts > 0.1 flag drift.
--
-- One row per (period). Append-only.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS materiality_classifier_drift (
    drift_check_id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- e.g., '2026-Q4'
    period                               TEXT NOT NULL,

    -- Phase 4 Q8 hard floor: N >= 30.
    sample_size                          INTEGER NOT NULL CHECK (sample_size >= 30),

    -- Rolling 30-event gold standard for the period — array of event_ids.
    rolling_gold_standard_event_ids      JSONB NOT NULL,

    -- Cohen's kappa (or similar agreement metric) vs gold standard.
    kappa                                NUMERIC NOT NULL,
    confidence_p50                       NUMERIC NOT NULL,
    confidence_p90                       NUMERIC NOT NULL,

    -- Delta vs prior quarter:
    --   { kappa_delta, p50_delta, p90_delta, gold_event_overlap_pct }
    delta_from_prior_quarter             JSONB,

    -- Flags surfaced for operator review (e.g., p50/p90 shifts > 0.1).
    flags                                JSONB,

    parameters_version                   UUID,
    created_at                           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT materiality_drift_period_unique
        UNIQUE (period)
);

CREATE INDEX IF NOT EXISTS idx_materiality_drift_period
    ON materiality_classifier_drift(period DESC);

CREATE INDEX IF NOT EXISTS idx_materiality_drift_created
    ON materiality_classifier_drift(created_at DESC);

CREATE OR REPLACE FUNCTION materiality_drift_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'materiality_classifier_drift is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS materiality_drift_no_modify ON materiality_classifier_drift;
CREATE TRIGGER materiality_drift_no_modify
BEFORE UPDATE OR DELETE ON materiality_classifier_drift
FOR EACH ROW EXECUTE FUNCTION materiality_drift_guard();


-- -----------------------------------------------------------------------------
-- Table: mode_vol_checks
-- Per Phase 4 Q5: semi-annual mode-implied-volatility check. Each mode
-- (B, B_prime, C) has an expected realized-vol band; consecutive violations
-- flag silent classifier failure (the company is no longer behaving like
-- the mode it was filed under).
--
-- One row per (ticker, check_date). Append-only.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mode_vol_checks (
    check_id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker                      TEXT NOT NULL,
    check_date                  DATE NOT NULL,

    mode                        TEXT NOT NULL CHECK (mode IN ('B', 'B_prime', 'C')),
    realized_vol_252d           NUMERIC NOT NULL,
    mode_band_low               NUMERIC NOT NULL,
    mode_band_high              NUMERIC NOT NULL,

    within_band                 BOOLEAN NOT NULL,
    consecutive_outside_count   INTEGER NOT NULL DEFAULT 0,
    flagged                     BOOLEAN NOT NULL DEFAULT false,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT mode_vol_band_ordering CHECK (mode_band_low <= mode_band_high),
    CONSTRAINT mode_vol_unique_per_day UNIQUE (ticker, check_date)
);

CREATE INDEX IF NOT EXISTS idx_mode_vol_ticker_date
    ON mode_vol_checks(ticker, check_date DESC);

CREATE INDEX IF NOT EXISTS idx_mode_vol_flagged
    ON mode_vol_checks(check_date DESC)
    WHERE flagged = true;

CREATE OR REPLACE FUNCTION mode_vol_checks_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'mode_vol_checks is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS mode_vol_checks_no_modify ON mode_vol_checks;
CREATE TRIGGER mode_vol_checks_no_modify
BEFORE UPDATE OR DELETE ON mode_vol_checks
FOR EACH ROW EXECUTE FUNCTION mode_vol_checks_guard();


COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

SELECT schemaname, tablename FROM pg_tables
WHERE tablename IN ('anchor_drift_checks', 'materiality_classifier_drift', 'mode_vol_checks')
ORDER BY tablename;

SELECT indexname, tablename FROM pg_indexes
WHERE tablename IN ('anchor_drift_checks', 'materiality_classifier_drift', 'mode_vol_checks')
ORDER BY tablename, indexname;

SELECT t.tgname, c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname IN ('anchor_drift_checks', 'materiality_classifier_drift', 'mode_vol_checks')
  AND NOT t.tgisinternal
ORDER BY c.relname, t.tgname;

SELECT conname, conrelid::regclass AS table_name, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid::regclass::text IN ('anchor_drift_checks', 'materiality_classifier_drift', 'mode_vol_checks')
  AND contype IN ('c', 'u')
ORDER BY conrelid::regclass::text, conname;
