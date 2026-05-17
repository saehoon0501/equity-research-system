-- =============================================================================
-- Migration: 013_v3_calibration_capture
-- Purpose:   Calibration-capture tables — the audit-trail substrate that
--            lets v0.5+ rebuild the empirical foundation against actual
--            outcomes. Five artifacts, all tightly tied to Section 8 Q4
--            (calibration capture) and Phase 4 Q6 (operator-override
--            outcome tracking).
--
--            Tables:
--              - operator_overrides          (Section 8 Q4 / Phase 4 Q6;
--                                             append-only; every operator
--                                             deviation from a system rec)
--              - recommendation_outcomes     (Section 8 Q4; STATE; T+30/90/1y
--                                             returns vs benchmark)
--              - override_outcomes           (Phase 4 Q6; STATE; actual vs
--                                             counterfactual baseline)
--              - debate_consensus_history    (Section 8 Q4; append-only;
--                                             style-debate snapshots)
--              - fill_divergence             (Section 8 Q4; append-only;
--                                             suggested vs actual fill stats)
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 8 Q4 (calibration capture columns + tables);
--            Section 8 Phase 4 Q6 (operator override outcome tracking +
--            counterfactual baseline);
--            Section 8 Phase 4 #6 ((model_id, model_version) pair convention).
--
-- Schema notes:
--   - GENERATED ALWAYS columns where the value is a pure function of other
--     stored columns:
--       * recommendation_outcomes.delta_vs_benchmark_{30d,90d,1y}
--       * override_outcomes.operator_was_better
--       * fill_divergence.pct_divergence
--   - State tables update only T+N return columns (and last_updated_at);
--     all other columns are immutable post-insert; DELETE is blocked.
--   - Append-only tables block UPDATE and DELETE entirely.
--   - Forward-refs to execution_recommendations.recommendation_id and
--     position_history.event_id are captured as plain UUID without FK
--     constraint — those tables land in later migrations. The audit trail
--     remains intact via column naming + index discipline.
--
-- Dependencies:
--   - 004_v3_parameters (parameters_version FK convention).
--   - 009_v3_daily_monitor (operator_overrides may reference daily refresh
--     entries via recommendation_id, but no hard FK).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/013_v3_calibration_capture.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: operator_overrides
-- Section 8 Q4 / Phase 4 Q6 — append-only. Every time the operator
-- deviates from what the system recommended (sizing, routing, veto, mode,
-- recommendation, or exit timing), capture the deviation with rationale.
-- This is the input to Phase 4 Q6's counterfactual outcome tracking.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operator_overrides (
    override_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Forward-ref to execution_recommendations (created in a later migration).
    -- Nullable: not every override is tied to a specific recommendation
    -- (e.g., proactive sizing change on an existing position).
    recommendation_id       UUID,

    ticker                  TEXT NOT NULL,
    override_date           TIMESTAMPTZ NOT NULL,

    -- Closed set per Section 8 Q4 + Phase 4 Q6. Add types via migration,
    -- not via free-text smuggling.
    override_type           TEXT NOT NULL CHECK (override_type IN (
        'sizing',
        'routing',
        'veto',
        'mode',
        'recommendation',
        'exit_timing'
    )),

    -- prior_value = what the system recommended.
    -- new_value   = what the operator chose instead.
    -- JSONB so we can capture sizing %, mode strings, route choices, etc.
    prior_value             JSONB NOT NULL,
    new_value               JSONB NOT NULL,

    -- Rationale required — overrides without explanation defeat the audit.
    rationale               TEXT NOT NULL,
    -- Verbatim citation supporting the rationale (e.g., quoted filing
    -- text, news source). Optional: not all overrides cite external evidence.
    verbatim_citation       TEXT,

    operator                TEXT NOT NULL DEFAULT 'operator',
    parameters_version      UUID,                        -- FK to parameters.version_id

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Indexes — operator_overrides
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_operator_overrides_ticker_date
    ON operator_overrides(ticker, override_date DESC);

CREATE INDEX IF NOT EXISTS idx_operator_overrides_type
    ON operator_overrides(override_type, override_date DESC);

CREATE INDEX IF NOT EXISTS idx_operator_overrides_recommendation
    ON operator_overrides(recommendation_id)
    WHERE recommendation_id IS NOT NULL;

-- "Show all overrides under parameters_version X" — for cross-cohort drift.
CREATE INDEX IF NOT EXISTS idx_operator_overrides_params
    ON operator_overrides(parameters_version, override_date DESC);

-- -----------------------------------------------------------------------------
-- Append-only trigger — operator_overrides
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION operator_overrides_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'operator_overrides is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS operator_overrides_no_modify ON operator_overrides;
CREATE TRIGGER operator_overrides_no_modify
BEFORE UPDATE OR DELETE ON operator_overrides
FOR EACH ROW EXECUTE FUNCTION operator_overrides_guard();


-- -----------------------------------------------------------------------------
-- Table: recommendation_outcomes
-- Section 8 Q4 — STATE table. One row per recommendation. T+30 / T+90 / T+1y
-- return + benchmark + delta-vs-benchmark (GENERATED). Updates as time
-- passes and outcome windows close; never deleted.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recommendation_outcomes (
    outcome_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Forward-ref to execution_recommendations (FK enforced in later migration).
    recommendation_id       UUID NOT NULL,

    ticker                  TEXT NOT NULL,
    recommendation_date     DATE NOT NULL,

    -- T+N return windows. Nullable until the window closes.
    t_plus_30d_return       NUMERIC,
    t_plus_30d_close_date   DATE,
    t_plus_90d_return       NUMERIC,
    t_plus_90d_close_date   DATE,
    t_plus_1y_return        NUMERIC,
    t_plus_1y_close_date    DATE,

    -- Benchmark return over each window. Default benchmark for v0.1 is SPY
    -- per Section 8 Q4 — but stored as text so the benchmark can vary by
    -- mode (e.g., sector ETF for Mode-C names).
    benchmark_return_30d    NUMERIC,
    benchmark_return_90d    NUMERIC,
    benchmark_return_1y     NUMERIC,
    benchmark               TEXT NOT NULL DEFAULT 'SPY',

    -- Pure functions of stored columns; recompute automatically.
    delta_vs_benchmark_30d  NUMERIC GENERATED ALWAYS AS
        (t_plus_30d_return - benchmark_return_30d) STORED,
    delta_vs_benchmark_90d  NUMERIC GENERATED ALWAYS AS
        (t_plus_90d_return - benchmark_return_90d) STORED,
    delta_vs_benchmark_1y   NUMERIC GENERATED ALWAYS AS
        (t_plus_1y_return  - benchmark_return_1y)  STORED,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One outcome row per recommendation.
    CONSTRAINT recommendation_outcomes_recommendation_unique
        UNIQUE (recommendation_id)
);

-- -----------------------------------------------------------------------------
-- Indexes — recommendation_outcomes
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_ticker_date
    ON recommendation_outcomes(ticker, recommendation_date DESC);

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_recommendation
    ON recommendation_outcomes(recommendation_id);

-- "Which recommendations still need their T+1y window closed?"
CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_pending_1y
    ON recommendation_outcomes(recommendation_date)
    WHERE t_plus_1y_return IS NULL;

CREATE INDEX IF NOT EXISTS idx_recommendation_outcomes_delta_1y
    ON recommendation_outcomes(delta_vs_benchmark_1y DESC NULLS LAST);

-- -----------------------------------------------------------------------------
-- State-table guard — recommendation_outcomes
--
-- UPDATE allowed only on T+N return + close_date columns and last_updated_at.
-- All other columns immutable post-insert. DELETE blocked.
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
            RAISE EXCEPTION 'recommendation_outcomes: only T+N return / close_date columns and last_updated_at are mutable';
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
-- Table: override_outcomes
-- Phase 4 Q6 — STATE table. Every operator override gets T+N actual outcome
-- AND a counterfactual baseline ("what the system's recommendation would
-- have produced"). The GENERATED column operator_was_better collapses the
-- T+1y comparison into a boolean for fast rollups.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS override_outcomes (
    override_outcome_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    override_id                 UUID NOT NULL REFERENCES operator_overrides(override_id),

    ticker                      TEXT NOT NULL,
    override_date               DATE NOT NULL,

    -- Actual outcome under the OPERATOR'S choice.
    actual_outcome_t30d         NUMERIC,
    actual_outcome_t90d         NUMERIC,
    actual_outcome_t1y          NUMERIC,

    -- Counterfactual outcome under the SYSTEM'S recommendation (i.e., what
    -- would have happened if the operator had not overridden). Computed
    -- via shadow-portfolio replay during the calibration job.
    counterfactual_outcome_t30d NUMERIC,
    counterfactual_outcome_t90d NUMERIC,
    counterfactual_outcome_t1y  NUMERIC,

    -- Boolean rollup at the T+1y horizon. NULL until both the actual and
    -- counterfactual T+1y values are populated.
    operator_was_better         BOOLEAN GENERATED ALWAYS AS (
        CASE
            WHEN actual_outcome_t1y IS NULL OR counterfactual_outcome_t1y IS NULL THEN NULL
            ELSE actual_outcome_t1y > counterfactual_outcome_t1y
        END
    ) STORED,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One outcome row per override.
    CONSTRAINT override_outcomes_override_unique
        UNIQUE (override_id)
);

-- -----------------------------------------------------------------------------
-- Indexes — override_outcomes
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_override_outcomes_ticker_date
    ON override_outcomes(ticker, override_date DESC);

CREATE INDEX IF NOT EXISTS idx_override_outcomes_override
    ON override_outcomes(override_id);

-- Rollup: "what % of overrides outperformed the system at T+1y?"
CREATE INDEX IF NOT EXISTS idx_override_outcomes_was_better
    ON override_outcomes(operator_was_better, override_date DESC)
    WHERE operator_was_better IS NOT NULL;

-- "Which overrides still need their T+1y outcome populated?"
CREATE INDEX IF NOT EXISTS idx_override_outcomes_pending_1y
    ON override_outcomes(override_date)
    WHERE actual_outcome_t1y IS NULL OR counterfactual_outcome_t1y IS NULL;

-- -----------------------------------------------------------------------------
-- State-table guard — override_outcomes
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION override_outcomes_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'override_outcomes: DELETE not permitted';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF NEW.override_outcome_id IS DISTINCT FROM OLD.override_outcome_id
           OR NEW.override_id      IS DISTINCT FROM OLD.override_id
           OR NEW.ticker           IS DISTINCT FROM OLD.ticker
           OR NEW.override_date    IS DISTINCT FROM OLD.override_date
           OR NEW.created_at       IS DISTINCT FROM OLD.created_at
        THEN
            RAISE EXCEPTION 'override_outcomes: only actual_/counterfactual_ outcome columns and last_updated_at are mutable';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS override_outcomes_state_guard ON override_outcomes;
CREATE TRIGGER override_outcomes_state_guard
BEFORE UPDATE OR DELETE ON override_outcomes
FOR EACH ROW EXECUTE FUNCTION override_outcomes_guard();


-- -----------------------------------------------------------------------------
-- Table: debate_consensus_history
-- Section 8 Q4 — append-only. One row per debate (i.e., per recommendation
-- that went through the multi-style debate pipeline). Captures per-style
-- outputs, Phase-C trigger + judge confidence, and Phase-D synthesis.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS debate_consensus_history (
    debate_id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Forward-ref to execution_recommendations.
    recommendation_id           UUID NOT NULL,

    ticker                      TEXT NOT NULL,
    debate_date                 DATE NOT NULL,

    -- Per-style outputs. Schema:
    --   {
    --     value:           {verdict, claims, non_negotiables, weight},
    --     growth:          {...},
    --     quality:         {...},
    --     macro_regime:    {...},
    --     quant_technical: {...}
    --   }
    -- verdict ∈ {ADD, WATCH, PASS} (matches src/p4_debate ALL_VERDICTS).
    per_style_outputs           JSONB NOT NULL,

    -- Phase-C is the dissent-resolution phase per Section 8 Q4. Triggered
    -- when style verdicts diverge enough that the judge needs to re-read
    -- claims and either resolve or escalate to operator.
    phase_c_triggered           BOOLEAN NOT NULL DEFAULT false,
    phase_c_judge_confidence    NUMERIC CHECK (phase_c_judge_confidence IS NULL
                                               OR phase_c_judge_confidence BETWEEN 0 AND 1),

    -- Phase-D synthesis. Schema:
    --   {
    --     final_decision: 'ADD' | 'WATCH' | 'PASS',
    --     dissent_trace: [...],
    --     override_reasoning: '...',
    --     non_negotiables_not_addressed: [...]
    --   }
    phase_d_synthesis           JSONB NOT NULL,

    -- Per Phase 4 #6: (model_id, model_version) pair convention.
    debate_prompt_version       TEXT NOT NULL,
    model_id                    TEXT NOT NULL,
    model_version               TEXT NOT NULL,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Indexes — debate_consensus_history
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_debate_consensus_ticker_date
    ON debate_consensus_history(ticker, debate_date DESC);

CREATE INDEX IF NOT EXISTS idx_debate_consensus_recommendation
    ON debate_consensus_history(recommendation_id);

-- "Which recommendations triggered phase-C?" — drives dissent-rate audits.
CREATE INDEX IF NOT EXISTS idx_debate_consensus_phase_c
    ON debate_consensus_history(phase_c_triggered, debate_date DESC)
    WHERE phase_c_triggered = true;

CREATE INDEX IF NOT EXISTS idx_debate_consensus_prompt_version
    ON debate_consensus_history(debate_prompt_version, debate_date DESC);

-- -----------------------------------------------------------------------------
-- Append-only trigger — debate_consensus_history
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION debate_consensus_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'debate_consensus_history is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS debate_consensus_no_modify ON debate_consensus_history;
CREATE TRIGGER debate_consensus_no_modify
BEFORE UPDATE OR DELETE ON debate_consensus_history
FOR EACH ROW EXECUTE FUNCTION debate_consensus_guard();


-- -----------------------------------------------------------------------------
-- Table: fill_divergence
-- Section 8 Q4 — append-only normalized table that joins to position_history
-- (forward-ref). One row per fill event where the actual fill differed from
-- the system's suggested initial sizing. pct_divergence is GENERATED.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fill_divergence (
    divergence_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Forward-ref to position_history.event_id.
    event_id                UUID NOT NULL,

    -- Forward-ref to execution_recommendations. Nullable for discretionary
    -- fills not tied to a system recommendation.
    recommendation_id       UUID,

    suggested_initial_pct   NUMERIC NOT NULL,
    actual_initial_pct      NUMERIC NOT NULL,

    -- Pure function: signed divergence (actual - suggested) in pct points.
    pct_divergence          NUMERIC GENERATED ALWAYS AS
        (actual_initial_pct - suggested_initial_pct) STORED,

    -- Calendar days between recommendation issuance and actual fill.
    timing_lag_days         INTEGER NOT NULL,

    -- Slippage in $/share or bps depending on convention; signed.
    price_slippage          NUMERIC NOT NULL,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Indexes — fill_divergence
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_fill_divergence_event
    ON fill_divergence(event_id);

CREATE INDEX IF NOT EXISTS idx_fill_divergence_recommendation
    ON fill_divergence(recommendation_id)
    WHERE recommendation_id IS NOT NULL;

-- "Show fills with the largest sizing divergence" — drives execution-quality
-- audits.
CREATE INDEX IF NOT EXISTS idx_fill_divergence_pct
    ON fill_divergence(pct_divergence DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_fill_divergence_timing_lag
    ON fill_divergence(timing_lag_days DESC, created_at DESC);

-- -----------------------------------------------------------------------------
-- Append-only trigger — fill_divergence
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fill_divergence_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'fill_divergence is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS fill_divergence_no_modify ON fill_divergence;
CREATE TRIGGER fill_divergence_no_modify
BEFORE UPDATE OR DELETE ON fill_divergence
FOR EACH ROW EXECUTE FUNCTION fill_divergence_guard();

COMMIT;

-- =============================================================================
-- VERIFY: run these after applying.
-- =============================================================================

-- VERIFY: all 5 tables exist.
SELECT schemaname, tablename
FROM pg_tables
WHERE tablename IN (
    'operator_overrides',
    'recommendation_outcomes',
    'override_outcomes',
    'debate_consensus_history',
    'fill_divergence'
)
ORDER BY tablename;

-- VERIFY: all expected indexes are present.
SELECT indexname, tablename
FROM pg_indexes
WHERE tablename IN (
    'operator_overrides',
    'recommendation_outcomes',
    'override_outcomes',
    'debate_consensus_history',
    'fill_divergence'
)
  AND indexname LIKE 'idx_%'
ORDER BY tablename, indexname;

-- VERIFY: append-only / state-guard triggers wired on every table.
SELECT t.tgname AS trigger_name, c.relname AS table_name, p.proname AS function_name
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_proc  p ON p.oid = t.tgfoid
WHERE c.relname IN (
    'operator_overrides',
    'recommendation_outcomes',
    'override_outcomes',
    'debate_consensus_history',
    'fill_divergence'
)
  AND NOT t.tgisinternal
ORDER BY c.relname, t.tgname;

-- VERIFY: GENERATED ALWAYS columns on the four computed columns.
SELECT table_name, column_name, is_generated, generation_expression
FROM information_schema.columns
WHERE (table_name = 'recommendation_outcomes' AND column_name LIKE 'delta_vs_benchmark_%')
   OR (table_name = 'override_outcomes'       AND column_name = 'operator_was_better')
   OR (table_name = 'fill_divergence'         AND column_name = 'pct_divergence')
ORDER BY table_name, column_name;

-- VERIFY: CHECK constraints on override_type + phase_c_judge_confidence.
SELECT conrelid::regclass AS table_name, conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid IN (
        'operator_overrides'::regclass,
        'debate_consensus_history'::regclass
    )
  AND contype = 'c'
ORDER BY conrelid::regclass::text, conname;

-- VERIFY: FK from override_outcomes.override_id → operator_overrides.override_id.
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'override_outcomes'::regclass
  AND contype = 'f'
ORDER BY conname;
