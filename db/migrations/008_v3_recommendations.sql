-- =============================================================================
-- Migration: 008_v3_recommendations
-- Purpose:   Recommendation emission, mode classification, and audit-provenance
--            tables — the operator-facing output layer of the v3 architecture.
--
--            Three append-only tables:
--              - execution_recommendations  (Section 4.6 Q1 schema +
--                                             Phase 4 Q2 conviction rollup)
--              - mode_classifications       (Section 7 PB#3 + Phase 4 Q1
--                                             layered classifier outputs)
--              - audit_provenance           (Section 7 Q4 layered drill-down,
--                                             HMAC-chained tamper evidence)
--
--            Append-only by default; revisions are written as new rows that
--            reference the prior row (e.g., prior_recommendation_date,
--            prior_classification_id, parent_audit_id). For v0.1 simplicity
--            we only allow narrow column UPDATEs on execution_recommendations
--            (the conviction-pending state machine: pending_transition,
--            pending_target, flip_count_30d, frozen_pending_review). All other
--            UPDATEs and all DELETEs are blocked. mode_classifications and
--            audit_provenance are fully append-only.
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 3.2 (Postgres tables); Section 4.6 (recommendation
--            output schema); Section 5.2 (audit-mode UX, layered drill-down);
--            Section 7 PB#3 / PB#4 / PB#5 / Q1-Q4; Phase 4 Q1 (mode classifier
--            layered architecture); Phase 4 Q2 (conviction rollup revision).
--
-- Audit signing: each row in execution_recommendations carries an
-- audit_signature (HMAC of the row payload computed at write time). The
-- signing function is implemented as an external service hook; this migration
-- enforces NOT NULL on the column and provides a stub trigger that errors if
-- the signature is missing. The application layer must compute and supply
-- audit_signature in the INSERT payload. Same applies to audit_provenance
-- (hmac_signature) for the chained audit log.
--
-- Dependencies:
--   - 004_v3_parameters (parameters_version FK)
--   - PostgreSQL 13+ (gen_random_uuid)
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/008_v3_recommendations.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: execution_recommendations
-- Per Section 4.6 Q1: clean operator-facing recommendation envelope. Emitted
-- by P5/P9 (Section 3.2). One row per (ticker, date, recommendation-event);
-- revisions written as new rows linked via trigger_metadata.prior_*.
--
-- Conviction rollup (Phase 4 Q2): conviction is the rollup of debate consensus
-- + kills + counterfactual + mode certainty + drift channels. The per-channel
-- breakdown is stored in conviction_breakdown JSONB.
--
-- Pending-transition state machine (Phase 4 Q2):
--   conviction_pending_transition flips to true when a tier change is queued
--   but not yet committed (e.g., awaiting confirmation event); _target holds
--   the proposed next tier; _flip_count_30d tracks oscillation; _frozen_*
--   freezes conviction at the prior tier pending operator review.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS execution_recommendations (
    recommendation_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity
    ticker                         TEXT NOT NULL,
    date                           DATE NOT NULL,

    -- Decision envelope (Section 4.6 Q1)
    recommendation                 TEXT NOT NULL
                                       CHECK (recommendation IN ('BUY', 'HOLD', 'TRIM', 'SELL')),
    conviction                     TEXT NOT NULL
                                       CHECK (conviction IN ('HIGH', 'MEDIUM', 'LOW')),

    -- Conviction breakdown rollup (Phase 4 Q2):
    --   { debate_consensus: <text>,
    --     kills_fired:      <int>,
    --     counterfactual_top_3: [...],
    --     mode_certainty:   'rule_clean' | 'llm_tiebreaker',
    --     drift_channels:   '<n> of 3 triggered' }
    conviction_breakdown           JSONB NOT NULL,

    -- Conviction-pending state machine (Phase 4 Q2 oscillation guard).
    -- These columns are the ONLY ones permitted to UPDATE post-insert
    -- (see append-only trigger below).
    conviction_pending_transition  BOOLEAN NOT NULL DEFAULT false,
    conviction_pending_target      TEXT
                                       CHECK (conviction_pending_target IS NULL
                                              OR conviction_pending_target IN ('HIGH', 'MEDIUM', 'LOW')),
    conviction_changed_from_prior  BOOLEAN NOT NULL DEFAULT false,
    conviction_flip_count_30d      INTEGER NOT NULL DEFAULT 0,
    conviction_frozen_pending_review BOOLEAN NOT NULL DEFAULT false,

    -- Mode + quality (Phase 4 Q1; Section 7 PB#3)
    mode                           TEXT NOT NULL
                                       CHECK (mode IN ('B', 'B_prime', 'C')),
    company_quality_flag           TEXT NOT NULL
                                       CHECK (company_quality_flag IN ('HIGH', 'STANDARD')),
    mode_certainty                 TEXT NOT NULL
                                       CHECK (mode_certainty IN ('rule_clean', 'llm_tiebreaker')),

    -- Sizing suggestion envelope (Section 4.6 Q1):
    --   { initial_pct, max_pct, base_band, applied_overlays:[...],
    --     net_multiplier, funding_required }
    sizing_suggestion              JSONB NOT NULL,

    -- Execution context envelope (Section 4.6 Q1):
    --   { current_price, fair_value_estimate, near_term_catalysts:[...],
    --     suggested_pacing, technical_signals:[...], risk_flags:[...] }
    execution_context              JSONB NOT NULL,

    -- Trigger metadata (Section 7 Q3 trigger logic):
    --   { triggered_by, cadence_floor_due_at, materiality_event_ref,
    --     prior_recommendation_date, prior_recommendation, changed_from_prior }
    trigger_metadata               JSONB NOT NULL,

    -- Audit availability flag (Section 5.2 audit-mode UX)
    audit_available                BOOLEAN NOT NULL DEFAULT true,

    -- Versioning quintet (Section 5 Q1 audit-trail lock; Phase 4 cleanup
    -- standardizes on (model_id, model_version) pair).
    rule_engine_version            TEXT NOT NULL,
    debate_prompt_version          TEXT NOT NULL,
    model_id                       TEXT NOT NULL,
    model_version                  TEXT NOT NULL,
    parameters_version             UUID,             -- FK to parameters.version_id

    -- HMAC of canonical row payload, computed and supplied by application
    -- at INSERT time. Trigger enforces non-empty.
    audit_signature                TEXT NOT NULL,

    created_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes — driven by daily-monitor / dashboard queries.
CREATE INDEX IF NOT EXISTS idx_exec_recs_ticker_date
    ON execution_recommendations(ticker, date DESC);

CREATE INDEX IF NOT EXISTS idx_exec_recs_recommendation
    ON execution_recommendations(recommendation, date DESC);

CREATE INDEX IF NOT EXISTS idx_exec_recs_conviction
    ON execution_recommendations(conviction, date DESC);

CREATE INDEX IF NOT EXISTS idx_exec_recs_mode
    ON execution_recommendations(mode, date DESC);

CREATE INDEX IF NOT EXISTS idx_exec_recs_pending_review
    ON execution_recommendations(conviction_frozen_pending_review)
    WHERE conviction_frozen_pending_review = true;

-- -----------------------------------------------------------------------------
-- Append-only trigger for execution_recommendations
--
-- Permits UPDATE only on the conviction-pending state-machine columns:
--   conviction_pending_transition, conviction_pending_target,
--   conviction_flip_count_30d, conviction_frozen_pending_review.
-- All other column UPDATEs and any DELETE are rejected. Revisions to the
-- recommendation itself must be written as new rows referencing
-- trigger_metadata.prior_recommendation_date.
--
-- Also enforces audit_signature non-empty at INSERT.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION exec_recs_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.audit_signature IS NULL OR length(trim(NEW.audit_signature)) = 0 THEN
            RAISE EXCEPTION 'execution_recommendations.audit_signature must be a non-empty HMAC supplied by the application layer';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'execution_recommendations is append-only — DELETE not permitted';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        -- Allow narrow updates to the conviction-pending state-machine columns only.
        IF NEW.recommendation_id          IS DISTINCT FROM OLD.recommendation_id
           OR NEW.ticker                  IS DISTINCT FROM OLD.ticker
           OR NEW.date                    IS DISTINCT FROM OLD.date
           OR NEW.recommendation          IS DISTINCT FROM OLD.recommendation
           OR NEW.conviction              IS DISTINCT FROM OLD.conviction
           OR NEW.conviction_breakdown    IS DISTINCT FROM OLD.conviction_breakdown
           OR NEW.conviction_changed_from_prior IS DISTINCT FROM OLD.conviction_changed_from_prior
           OR NEW.mode                    IS DISTINCT FROM OLD.mode
           OR NEW.company_quality_flag    IS DISTINCT FROM OLD.company_quality_flag
           OR NEW.mode_certainty          IS DISTINCT FROM OLD.mode_certainty
           OR NEW.sizing_suggestion       IS DISTINCT FROM OLD.sizing_suggestion
           OR NEW.execution_context       IS DISTINCT FROM OLD.execution_context
           OR NEW.trigger_metadata        IS DISTINCT FROM OLD.trigger_metadata
           OR NEW.audit_available         IS DISTINCT FROM OLD.audit_available
           OR NEW.rule_engine_version     IS DISTINCT FROM OLD.rule_engine_version
           OR NEW.debate_prompt_version   IS DISTINCT FROM OLD.debate_prompt_version
           OR NEW.model_id                IS DISTINCT FROM OLD.model_id
           OR NEW.model_version           IS DISTINCT FROM OLD.model_version
           OR NEW.parameters_version      IS DISTINCT FROM OLD.parameters_version
           OR NEW.audit_signature         IS DISTINCT FROM OLD.audit_signature
           OR NEW.created_at              IS DISTINCT FROM OLD.created_at
        THEN
            RAISE EXCEPTION 'execution_recommendations is append-only — only conviction-pending state-machine columns may be updated (conviction_pending_transition, conviction_pending_target, conviction_flip_count_30d, conviction_frozen_pending_review). To revise a recommendation, INSERT a new row referencing prior_recommendation_date in trigger_metadata.';
        END IF;
        RETURN NEW;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS exec_recs_no_modify ON execution_recommendations;
CREATE TRIGGER exec_recs_no_modify
BEFORE INSERT OR UPDATE OR DELETE ON execution_recommendations
FOR EACH ROW EXECUTE FUNCTION exec_recs_guard();


-- -----------------------------------------------------------------------------
-- Table: mode_classifications
-- Per Section 7 PB#3 + Phase 4 Q1 layered architecture:
--   Stage 1 — mechanical rule classifier (B / B_prime / C)
--   Stage 2 — company-quality refinement (HIGH / STANDARD flag within bin)
--   Stage 3 — overlap detection + LLM tie-breaker (only when rules disagree)
--
-- Append-only. Reclassifications written as new rows linked via
-- prior_classification_id. recheck_status carries the workflow state when
-- quarterly re-classification (Phase 4 Q5) flags a mismatch.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mode_classifications (
    classification_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker                      TEXT NOT NULL,

    final_mode                  TEXT NOT NULL
                                    CHECK (final_mode IN ('B', 'B_prime', 'C')),
    company_quality_flag        TEXT NOT NULL
                                    CHECK (company_quality_flag IN ('HIGH', 'STANDARD')),
    classification_method       TEXT NOT NULL
                                    CHECK (classification_method IN ('rule', 'llm_tiebreaker')),

    -- Rule-stage outcomes:
    --   { B_match: bool, B_prime_match: bool, C_match: bool, overlap_detected: bool }
    rule_outcomes               JSONB NOT NULL,

    -- LLM tie-breaker payload (nullable; populated only when method='llm_tiebreaker'):
    --   { model, prompt_version, rating, confidence, rationale,
    --     evidence_quotes:[...], self_consistency:{...} }
    llm_tiebreaker              JSONB,

    -- Quarterly re-check workflow state (Phase 4 Q5).
    recheck_status              TEXT NOT NULL DEFAULT 'confirmed'
                                    CHECK (recheck_status IN
                                        ('confirmed', 'pending_review', 'reclassification_proposed')),
    prior_classification_id     UUID REFERENCES mode_classifications(classification_id),

    parameters_version          UUID,                  -- FK to parameters.version_id
    classified_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Tie-breaker payload required iff method = 'llm_tiebreaker'.
    CONSTRAINT mode_class_tiebreaker_payload
        CHECK ((classification_method = 'llm_tiebreaker' AND llm_tiebreaker IS NOT NULL)
               OR (classification_method = 'rule' AND llm_tiebreaker IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_mode_class_ticker_classified
    ON mode_classifications(ticker, classified_at DESC);

CREATE INDEX IF NOT EXISTS idx_mode_class_final_mode
    ON mode_classifications(final_mode, classified_at DESC);

CREATE INDEX IF NOT EXISTS idx_mode_class_recheck_pending
    ON mode_classifications(recheck_status, classified_at)
    WHERE recheck_status IN ('pending_review', 'reclassification_proposed');

CREATE OR REPLACE FUNCTION mode_classifications_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'mode_classifications is append-only — % not permitted (insert a new row referencing prior_classification_id to reclassify)', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS mode_classifications_no_modify ON mode_classifications;
CREATE TRIGGER mode_classifications_no_modify
BEFORE UPDATE OR DELETE ON mode_classifications
FOR EACH ROW EXECUTE FUNCTION mode_classifications_guard();


-- -----------------------------------------------------------------------------
-- Table: audit_provenance
-- Per Section 5.2 / Section 7 Q4 layered drill-down. Each recommendation
-- carries multiple stage-keyed audit rows (mechanical rule, debate, kill
-- criteria, counterfactual, materiality). hmac_signature on each row plus
-- parent_audit_id forms a tamper-evident chain.
--
-- Append-only.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_provenance (
    audit_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recommendation_id     UUID NOT NULL REFERENCES execution_recommendations(recommendation_id),

    stage                 TEXT NOT NULL
                              CHECK (stage IN
                                  ('stage_1_mechanical',
                                   'stage_2_debate',
                                   'stage_3_kill_criteria',
                                   'stage_4_counterfactual',
                                   'materiality')),

    -- Verbatim quotes, agent outputs, retrieval results, kill-criteria
    -- evaluation chain. JSONB so we can store arbitrarily-shaped per-stage
    -- payloads without DDL churn.
    drill_payload         JSONB NOT NULL,

    hmac_signature        TEXT NOT NULL,
    parent_audit_id       UUID REFERENCES audit_provenance(audit_id),

    -- Versioning bundle:
    --   { rule_engine_version, debate_prompt_version, model_id,
    --     model_version, parameters_version }
    versions              JSONB NOT NULL,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_prov_recommendation
    ON audit_provenance(recommendation_id, created_at);

CREATE INDEX IF NOT EXISTS idx_audit_prov_stage
    ON audit_provenance(stage, created_at);

CREATE INDEX IF NOT EXISTS idx_audit_prov_parent
    ON audit_provenance(parent_audit_id)
    WHERE parent_audit_id IS NOT NULL;

CREATE OR REPLACE FUNCTION audit_provenance_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.hmac_signature IS NULL OR length(trim(NEW.hmac_signature)) = 0 THEN
            RAISE EXCEPTION 'audit_provenance.hmac_signature must be a non-empty HMAC supplied by the application layer';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'audit_provenance is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_provenance_no_modify ON audit_provenance;
CREATE TRIGGER audit_provenance_no_modify
BEFORE INSERT OR UPDATE OR DELETE ON audit_provenance
FOR EACH ROW EXECUTE FUNCTION audit_provenance_guard();


COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

-- Tables exist.
SELECT schemaname, tablename FROM pg_tables
WHERE tablename IN ('execution_recommendations', 'mode_classifications', 'audit_provenance')
ORDER BY tablename;

-- Indexes present.
SELECT indexname, tablename FROM pg_indexes
WHERE tablename IN ('execution_recommendations', 'mode_classifications', 'audit_provenance')
ORDER BY tablename, indexname;

-- Triggers wired.
SELECT t.tgname, c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname IN ('execution_recommendations', 'mode_classifications', 'audit_provenance')
  AND NOT t.tgisinternal
ORDER BY c.relname, t.tgname;

-- Constraints visible.
SELECT conname, conrelid::regclass AS table_name, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid::regclass::text IN ('execution_recommendations', 'mode_classifications', 'audit_provenance')
  AND contype = 'c'
ORDER BY conrelid::regclass::text, conname;
