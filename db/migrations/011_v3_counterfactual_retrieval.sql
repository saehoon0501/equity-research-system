-- =============================================================================
-- Migration: 011_v3_counterfactual_retrieval
-- Purpose:   Three-table cluster for the peak-pain archetype catalog and its
--            retrieval-time / veto-lifecycle event logs:
--              - peak_pain_archetypes      (the catalog itself)
--              - counterfactual_retrievals (event log per retrieval trigger)
--              - veto_lifecycle            (Section 6 Q6 PB#5 veto state machine)
--
--            Catalog is ~160 cases across 15 sectors + 4 pre-2008 expansion
--            eras (Section 4.4). Two-layer schema (universal core / sector
--            extensions) per Section 6 Q6 PB#1. 3-LLM iterative-consensus
--            validation per Phase 4 Q4 with feature-typed agreement rule.
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 4.4 (peak-pain catalog two-layer schema, retrieval scoring,
--            catalog hygiene PB#6, validation PB#7);
--            Section 6 Q6 (PB#5 veto lifecycle states; Phase 4 Q4
--            feature-typed consensus rule).
--
-- Schema choice:
--   - case_id is TEXT (e.g., 'NVDA-2008'), not UUID — human-readable case
--     identifiers are core to operator-facing catalog audit; UUIDs would be
--     hostile to manual review.
--   - universal_core_features + sector_extensions are JSONB so the catalog
--     can evolve schema (add new sector-specific fields) without ALTER TABLE.
--   - universal_core_consensus tracks per-feature HIGH/LOW confidence per
--     Phase 4 Q4 (feature-typed-v0.1).
--   - top_3_case_ids is TEXT[] (not JSONB) since it's always a fixed-arity
--     list of catalog case IDs and we want btree-indexable membership tests
--     at v0.5+.
--   - archetype_distribution is JSONB keyed by outcome
--     ({"SURVIVOR": 2, "NON-SURVIVOR": 1, ...}).
--   - veto_lifecycle.m3_refreshes is JSONB array of refresh events captured
--     each time a follow-up M-3 fires while a veto is active.
--
-- Append policy:
--   - peak_pain_archetypes:    UPDATE allowed (catalog hygiene per PB#6 —
--                              audits, last_touched_in_retrieval timestamps,
--                              consensus_method evolution). DELETE blocked
--                              (case removal = mark validation_status='disputed',
--                              not delete).
--   - counterfactual_retrievals: full append-only (event log).
--   - veto_lifecycle:           full append-only (state-machine event log;
--                              status transitions captured as new rows
--                              joined to the same retrieval_id at v0.5+
--                              if needed; at v0.1 one row per veto, status
--                              field is the terminal state).
--
--   NOTE: The task spec calls veto_lifecycle "append-only on event log"
--   while also describing a state field that transitions over a veto's life.
--   Resolution: at v0.1 we implement strict append-only (DELETE + UPDATE
--   blocked); operationally, status mutations during a veto's life are
--   captured by appending to m3_refreshes JSONB and rewriting the row
--   in-place is forbidden. State transitions (active → released-by-recovery
--   etc.) at terminal-resolve time will be handled by inserting a follow-up
--   row in v0.5+ if needed; at v0.1 the field captures terminal status.
--
-- Dependencies:
--   - 004_v3_parameters (parameters_version FK target).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/011_v3_counterfactual_retrieval.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: peak_pain_archetypes
-- The catalog. ~160 cases at launch.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS peak_pain_archetypes (
    case_id                       TEXT PRIMARY KEY,        -- e.g., 'NVDA-2008'
    ticker                        TEXT NOT NULL,
    peak_date                     DATE NOT NULL,
    trough_date                   DATE NOT NULL,
    peak_dd_pct                   NUMERIC NOT NULL CHECK (peak_dd_pct < 0),

    -- Outcome bucket per Section 4.4 catalog status.
    outcome                       TEXT NOT NULL
                                    CHECK (outcome IN
                                      ('SURVIVOR', 'DILUTED-SURVIVOR',
                                       'NON-SURVIVOR', 'TBD')),

    sector                        TEXT NOT NULL,
    era_category                  TEXT NOT NULL,           -- e.g., 'GFC', 'dot-com', 'covid', 'stagflation_1973_82'

    -- Layer 1 universal core (6 features; Section 4.4):
    -- {founder_insider_stake_direction, cash_runway, founder_in_place,
    --  margin_trajectory, revenue_trajectory, industry_tailwind}
    universal_core_features       JSONB NOT NULL,

    -- Layer 2 sector-specific extensions (variable per sector).
    sector_extensions             JSONB NOT NULL,

    -- Per-feature consensus output: {feature_name: 'HIGH'|'LOW', ...}
    -- Per Phase 4 Q4 feature-typed-v0.1 rule.
    universal_core_consensus      JSONB NOT NULL,

    -- 3-LLM iterative-consensus validation status per PB#7.
    validation_status             TEXT NOT NULL
                                    CHECK (validation_status IN
                                      ('validated', 'pending', 'disputed')),

    -- Method tag — bumped when consensus rule changes (e.g., to feature-typed-v0.2).
    consensus_method              TEXT NOT NULL DEFAULT 'feature-typed-v0.1',

    -- Catalog hygiene (PB#6): mark when case is retrieved as a top-3 match.
    last_touched_in_retrieval     TIMESTAMPTZ,
    last_audit_date               DATE,
    audit_priority                TEXT NOT NULL DEFAULT 'low'
                                    CHECK (audit_priority IN ('low', 'medium', 'high')),

    notes                         TEXT,
    source_urls                   JSONB NOT NULL DEFAULT '[]'::jsonb,

    created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Sanity: trough must follow peak.
    CONSTRAINT peak_pain_dates_ordered CHECK (trough_date >= peak_date)
);

-- Indexes for peak_pain_archetypes
CREATE INDEX IF NOT EXISTS idx_archetype_sector_outcome
    ON peak_pain_archetypes(sector, outcome);

CREATE INDEX IF NOT EXISTS idx_archetype_outcome
    ON peak_pain_archetypes(outcome)
    WHERE outcome != 'TBD';   -- active retrieval pool excludes TBD

CREATE INDEX IF NOT EXISTS idx_archetype_validation
    ON peak_pain_archetypes(validation_status);

CREATE INDEX IF NOT EXISTS idx_archetype_audit_priority
    ON peak_pain_archetypes(audit_priority, last_audit_date NULLS FIRST)
    WHERE audit_priority IN ('medium', 'high');

CREATE INDEX IF NOT EXISTS idx_archetype_universal_core_gin
    ON peak_pain_archetypes USING GIN (universal_core_features);

-- -----------------------------------------------------------------------------
-- Table: counterfactual_retrievals
-- Event log: one row per retrieval trigger (peak-pain candidate scan).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS counterfactual_retrievals (
    retrieval_id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_ticker                TEXT NOT NULL,
    retrieval_date                  DATE NOT NULL,

    -- Drawdown vs benchmark in percentage points (the trigger threshold).
    drawdown_vs_benchmark_pp        NUMERIC NOT NULL,

    -- Top-3 retrieval results (parallel arrays — same length, same order).
    top_3_case_ids                  TEXT[] NOT NULL,
    top_3_similarities              NUMERIC[] NOT NULL,

    -- Distribution of outcomes across top-3 (denormalized for /audit-trail UX).
    -- E.g., {"SURVIVOR": 2, "NON-SURVIVOR": 1}
    archetype_distribution          JSONB NOT NULL,

    -- Veto fired? Status (per Section 6 Q6 PB#5).
    veto_invoked                    BOOLEAN NOT NULL DEFAULT FALSE,
    veto_status                     TEXT NOT NULL
                                      CHECK (veto_status IN
                                        ('not_triggered', 'blocked', 'operator_override',
                                         'released-by-recovery', 'released-by-feature-shift')),

    -- Versioning per Section 5 Q1 audit trail.
    parameters_version              UUID REFERENCES parameters(version_id),
    catalog_version_hash            TEXT NOT NULL,    -- hash of peak_pain_archetypes snapshot at retrieval

    -- Reference to the recommendation event that triggered this retrieval (nullable).
    recommendation_ref              UUID,

    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Sanity: top_3 arrays must be aligned in length.
    CONSTRAINT retrieval_top3_aligned
        CHECK (array_length(top_3_case_ids, 1) = array_length(top_3_similarities, 1))
);

-- Indexes for counterfactual_retrievals
CREATE INDEX IF NOT EXISTS idx_retrievals_ticker_date
    ON counterfactual_retrievals(candidate_ticker, retrieval_date DESC);

CREATE INDEX IF NOT EXISTS idx_retrievals_veto_invoked
    ON counterfactual_retrievals(veto_invoked, retrieval_date DESC)
    WHERE veto_invoked = TRUE;

CREATE INDEX IF NOT EXISTS idx_retrievals_recommendation_ref
    ON counterfactual_retrievals(recommendation_ref)
    WHERE recommendation_ref IS NOT NULL;

-- -----------------------------------------------------------------------------
-- Table: veto_lifecycle
-- State-machine event log per veto fire (Section 6 Q6 PB#5).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS veto_lifecycle (
    veto_id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retrieval_id                    UUID NOT NULL REFERENCES counterfactual_retrievals(retrieval_id),
    ticker                          TEXT NOT NULL,
    initial_fire_date               DATE NOT NULL,

    -- Terminal status field (PB#5).
    status                          TEXT NOT NULL
                                      CHECK (status IN
                                        ('active', 'released-by-recovery',
                                         'released-by-feature-shift',
                                         'overridden-by-operator')),

    -- M-3 follow-up refresh events captured during veto life.
    -- Schema: [{refresh_date, drawdown_vs_benchmark_pp, top_3_case_ids,
    --          archetype_distribution, action_taken}]
    m3_refreshes                    JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Operator override audit (PB#5).
    operator_override_occurred      BOOLEAN NOT NULL DEFAULT FALSE,
    operator_override_rationale     TEXT,

    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for veto_lifecycle
CREATE INDEX IF NOT EXISTS idx_veto_lifecycle_ticker
    ON veto_lifecycle(ticker, initial_fire_date DESC);

CREATE INDEX IF NOT EXISTS idx_veto_lifecycle_status
    ON veto_lifecycle(status, initial_fire_date DESC);

CREATE INDEX IF NOT EXISTS idx_veto_lifecycle_retrieval
    ON veto_lifecycle(retrieval_id);

-- -----------------------------------------------------------------------------
-- Triggers
--
-- peak_pain_archetypes:        UPDATE allowed (catalog hygiene); DELETE blocked.
-- counterfactual_retrievals:   full append-only.
-- veto_lifecycle:              full append-only.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION peak_pain_archetypes_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'peak_pain_archetypes is delete-protected — mark validation_status=disputed instead of deleting';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS peak_pain_archetypes_no_delete ON peak_pain_archetypes;
CREATE TRIGGER peak_pain_archetypes_no_delete
BEFORE DELETE ON peak_pain_archetypes
FOR EACH ROW EXECUTE FUNCTION peak_pain_archetypes_guard();

CREATE OR REPLACE FUNCTION counterfactual_retrievals_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'counterfactual_retrievals is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS counterfactual_retrievals_no_modify ON counterfactual_retrievals;
CREATE TRIGGER counterfactual_retrievals_no_modify
BEFORE UPDATE OR DELETE ON counterfactual_retrievals
FOR EACH ROW EXECUTE FUNCTION counterfactual_retrievals_guard();

CREATE OR REPLACE FUNCTION veto_lifecycle_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'veto_lifecycle is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS veto_lifecycle_no_modify ON veto_lifecycle;
CREATE TRIGGER veto_lifecycle_no_modify
BEFORE UPDATE OR DELETE ON veto_lifecycle
FOR EACH ROW EXECUTE FUNCTION veto_lifecycle_guard();

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

-- VERIFY: all 3 tables exist.
SELECT schemaname, tablename FROM pg_tables
WHERE tablename IN ('peak_pain_archetypes', 'counterfactual_retrievals', 'veto_lifecycle')
ORDER BY tablename;

-- VERIFY: indexes present.
SELECT indexname, tablename FROM pg_indexes
WHERE tablename IN ('peak_pain_archetypes', 'counterfactual_retrievals', 'veto_lifecycle')
  AND indexname LIKE 'idx_%'
ORDER BY tablename, indexname;

-- VERIFY: triggers wired.
SELECT t.tgname, c.relname FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname IN ('peak_pain_archetypes', 'counterfactual_retrievals', 'veto_lifecycle')
  AND NOT t.tgisinternal
ORDER BY c.relname, t.tgname;

-- VERIFY: CHECK constraints.
SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
WHERE conrelid IN (
    'peak_pain_archetypes'::regclass,
    'counterfactual_retrievals'::regclass,
    'veto_lifecycle'::regclass)
  AND contype = 'c'
ORDER BY conrelid::regclass::text, conname;

-- VERIFY: FK (veto_lifecycle.retrieval_id → counterfactual_retrievals).
SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
WHERE conrelid = 'veto_lifecycle'::regclass AND contype = 'f';
