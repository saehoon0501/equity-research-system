-- =============================================================================
-- Migration: 006_v3_scenarios
-- Purpose:   P2 probabilistic-scenario branches per trend theme. Each scenario
--            row captures a discrete future-path narrative with a calibrated
--            probability, hybrid pre-mortem kill criteria (narrative + structured
--            conditions), value drivers, regime fit, and key dates to watch.
--
--            Per Section 4.2 Q2, 2-4 scenarios per theme; sibling probabilities
--            sum to 1.0. Per Q5, revision cadence is hybrid daily kill-checks
--            (deterministic, no LLM) + event-driven full re-write (LLM
--            regenerates only on regime-shift / kill-fire / operator
--            invocation). Per Q6, probabilities are hybrid-schema bounded to
--            [0.05, 0.95] with 0.05 step quantization (post-write linter
--            checks sum-to-1 + round-number / arithmetic-series detection).
--
--            Sum-to-1.0 across siblings is a WRITE-TIME check (P2 emitter +
--            post-write linter), NOT a per-row CHECK constraint, because the
--            constraint is across-rows-with-same-theme_id and Postgres CHECKs
--            are per-row. Enforcement lives in the P2 writer + a verification
--            view at v0.5+.
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 3.2 (scenarios row); Section 4.2 (P2 scenario writing,
--            Q1 schema, Q2 sibling count, Q3 kill criteria, Q5 revision
--            cadence, Q6 probability granularity).
--
-- Schema choice:
--   - scenario_id is a UUID PK (server-generated). theme_id is a UUID that
--     conceptually references a P1 trend theme; no FK at v0.1 because the
--     trend_themes table doesn't exist yet (P1 capture is operator-narrative
--     for v0.1; theme_id is a stable handle so children can be grouped).
--   - probability is NUMERIC (NOT DOUBLE PRECISION) so the 0.05-step
--     quantization check is exact. The step check is `(probability * 20)::INT
--     = (probability * 20)` — multiplying by 20 makes 0.05-step values
--     exact integers.
--   - kill_criteria_structured is JSONB so per-criterion records (criterion_id,
--     type=hard|soft, template_id, variable, comparator, threshold, deadline,
--     description, precedent_episodes, degradation_status) can be queried
--     via JSONB path operators + indexed GIN for kill-firing scans.
--   - parameters_version pins the prompt/model/weight config used to generate
--     the scenario, per Section 5 Q1 audit-trail lock.
--
-- Append-only policy (DEPARTURE from 004/005 pattern):
--   Per Section 4.2 Q5, scenarios are revisable via event-driven full re-write.
--   Allow UPDATE on (probability, kill_criteria_structured, last_updated_at).
--   Block UPDATE on (theme_id, scenario_id, name). Block DELETE always
--   (revision history matters; superseded scenarios stay queryable).
--
-- Dependencies:
--   - 004_v3_parameters (parameters_version FK target).
--   - PostgreSQL 13+ (gen_random_uuid, JSONB).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/006_v3_scenarios.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: scenarios
-- One row per scenario branch. Multiple rows per theme_id (2-4 per Q2 lock).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Conceptual ref to P1 trend theme. No FK at v0.1 (P1 themes table not
    -- yet materialized; theme_id stays a stable handle for sibling grouping).
    theme_id                    UUID NOT NULL,

    -- Human-readable scenario label, e.g., "AI capex normalizes 2027".
    name                        TEXT NOT NULL,

    -- Horizon — per Section 4.2 spec, scenarios written at 3y / 5y / 10y.
    horizon_years               SMALLINT NOT NULL CHECK (horizon_years IN (3, 5, 10)),

    -- Probability — bounded [0.05, 0.95], quantized to 0.05 step (Q6 lock).
    -- Sum-to-1 across siblings (same theme_id + horizon_years) enforced by
    -- write-time linter (NOT by CHECK; cross-row constraints aren't per-row).
    probability                 NUMERIC NOT NULL
                                  CHECK (probability >= 0.05 AND probability <= 0.95)
                                  CHECK ((probability * 20)::INTEGER = (probability * 20)),

    -- Narrative description of the scenario path.
    description                 TEXT NOT NULL,

    -- Hybrid kill criteria — narrative pre-mortem prose.
    kill_criteria_narrative     TEXT NOT NULL,

    -- Hybrid kill criteria — structured array of per-criterion records.
    -- Schema (per Section 4.2 Q3 lock):
    --   [{criterion_id: uuid, type: 'hard'|'soft', template_id: uuid|null,
    --     variable: text, comparator: text, threshold: numeric, deadline: date|null,
    --     description: text, precedent_episodes: [text],
    --     degradation_status: 'durable'|'recalibrate'|'discredit_post_2020'|'new_post_2020'}]
    kill_criteria_structured    JSONB NOT NULL,

    -- Value drivers — JSONB array of per-driver records (driver_name,
    -- direction, magnitude_estimate, confidence).
    value_drivers               JSONB NOT NULL,

    -- Regime fit — JSONB keyed by S0 dimension (credit_ebp, cycle_2y3m_slope, etc.)
    -- with state-conditional weights. Section 4.1 / 4.2 Q7 contract.
    regime_fit                  JSONB NOT NULL,

    -- Key dates to watch — JSONB array [{date, event, importance}].
    key_dates_to_watch          JSONB NOT NULL,

    -- Versioning per Section 5 Q1 audit-trail lock.
    parameters_version          UUID REFERENCES parameters(version_id),
    prompt_version              TEXT NOT NULL,
    model_id                    TEXT NOT NULL,
    model_version               TEXT NOT NULL,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------

-- Sibling lookups: "fetch all scenarios for theme T".
CREATE INDEX IF NOT EXISTS idx_scenarios_theme
    ON scenarios(theme_id);

-- Probability-ordered sibling fetch: "what's the dominant scenario for theme T?"
CREATE INDEX IF NOT EXISTS idx_scenarios_theme_prob
    ON scenarios(theme_id, probability DESC);

-- GIN on kill_criteria_structured — supports JSONB containment queries
-- ("find scenarios with any 'hard' criterion on variable=fed_funds_rate").
CREATE INDEX IF NOT EXISTS idx_scenarios_kill_structured_gin
    ON scenarios USING GIN (kill_criteria_structured);

-- -----------------------------------------------------------------------------
-- Append-mostly trigger (revisable per Q5; keys + name immutable)
--
-- Allowed UPDATEs: probability, kill_criteria_structured, last_updated_at,
--                  value_drivers, regime_fit, key_dates_to_watch, description,
--                  kill_criteria_narrative, parameters_version, prompt_version,
--                  model_id, model_version.
-- Blocked UPDATEs: theme_id, scenario_id, name, created_at, horizon_years.
-- DELETE: blocked unconditionally.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION scenarios_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'scenarios is delete-protected — DELETE not permitted (revision history matters)';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.scenario_id IS DISTINCT FROM NEW.scenario_id THEN
            RAISE EXCEPTION 'scenarios.scenario_id is immutable';
        END IF;
        IF OLD.theme_id IS DISTINCT FROM NEW.theme_id THEN
            RAISE EXCEPTION 'scenarios.theme_id is immutable (move requires new row)';
        END IF;
        IF OLD.name IS DISTINCT FROM NEW.name THEN
            RAISE EXCEPTION 'scenarios.name is immutable (rename requires new row)';
        END IF;
        IF OLD.created_at IS DISTINCT FROM NEW.created_at THEN
            RAISE EXCEPTION 'scenarios.created_at is immutable';
        END IF;
        IF OLD.horizon_years IS DISTINCT FROM NEW.horizon_years THEN
            RAISE EXCEPTION 'scenarios.horizon_years is immutable (re-write at new horizon = new row)';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS scenarios_guard_trg ON scenarios;
CREATE TRIGGER scenarios_guard_trg
BEFORE UPDATE OR DELETE ON scenarios
FOR EACH ROW EXECUTE FUNCTION scenarios_guard();

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

-- VERIFY: scenarios table exists.
SELECT schemaname, tablename FROM pg_tables WHERE tablename = 'scenarios';

-- VERIFY: all 3 expected indexes are present.
SELECT indexname, tablename FROM pg_indexes
WHERE tablename = 'scenarios'
  AND indexname IN (
      'idx_scenarios_theme',
      'idx_scenarios_theme_prob',
      'idx_scenarios_kill_structured_gin'
  )
ORDER BY indexname;

-- VERIFY: guard trigger is wired.
SELECT t.tgname, c.relname FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'scenarios'
  AND t.tgname = 'scenarios_guard_trg'
  AND NOT t.tgisinternal;

-- VERIFY: CHECK constraints (probability bounds + 0.05-step + horizon).
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'scenarios'::regclass AND contype = 'c'
ORDER BY conname;
