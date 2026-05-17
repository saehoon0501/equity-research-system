-- =============================================================================
-- Migration: 012_v3_premortem
-- Purpose:   Pre-mortem ledger — captures the operator's structured "imagine
--            this position fails: why?" exercise on a mode-tuned cadence,
--            plus event-triggered occurrences.
--
--            One append-only table:
--              - premortem  (mode-tuned cadence + event triggers; LLM-assisted
--                            but operator-led contestable judgment per spec
--                            requirement that Opus is used for high-stakes
--                            contestable judgment)
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 3.2 (Postgres tables); Section 5 / `/premortem <ticker>`;
--            Section 6 (Quality-Control table — pre-mortem cadence floor);
--            Phase 4 (Opus required for high-stakes contestable judgment;
--            kill-criteria coverage).
--
-- Trigger taxonomy:
--   - calendar_floor          — mode-tuned cadence floor reached
--   - thesis_confirmation     — major thesis-confirming event (forces a
--                                fresh failure-imagination pass)
--   - consecutive_m2          — consecutive M-2 materiality events
--   - auto_tighten            — auto-tighten policy fired
--   - mode_reclass            — mode reclassification proposed/confirmed
--
-- Append-only. Each pre-mortem session is its own row; revisions written as
-- new rows (no updates).
--
-- Dependencies:
--   - 004_v3_parameters (parameters_version FK)
--   - PostgreSQL 13+
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/012_v3_premortem.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: premortem
-- One row per pre-mortem session for a ticker.
--
-- operator_imagined_failure_modes:
--   array of {
--     mode: text,                     -- e.g., 'demand_reversal'
--     probability_estimate: numeric,
--     kill_criterion_added: bool,
--     kill_criterion_id: uuid,        -- FK to kill_criteria when added
--     rationale_for_skip: text        -- when not added as a kill criterion
--   }
--
-- thesis_pillars_revisited:
--   array of {
--     pillar: text,
--     still_holds: bool,
--     confidence_delta: numeric,
--     verbatim_evidence: text
--   }
--
-- llm_assist_metadata:
--   {
--     model: text,                  -- spec requires Opus for contestable judgment
--     role: text,                   -- 'devil's_advocate' | 'kill_criteria_proposer' | ...
--     operator_accepted_count: int,
--     operator_rejected_count: int
--   }
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS premortem (
    premortem_id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker                           TEXT NOT NULL,
    premortem_date                   DATE NOT NULL,

    trigger                          TEXT NOT NULL
                                         CHECK (trigger IN
                                             ('calendar_floor',
                                              'thesis_confirmation',
                                              'consecutive_m2',
                                              'auto_tighten',
                                              'mode_reclass')),

    days_since_last_premortem        INTEGER,
    mode                             TEXT
                                         CHECK (mode IS NULL OR mode IN ('B', 'B_prime', 'C')),

    operator_imagined_failure_modes  JSONB NOT NULL,
    thesis_pillars_revisited         JSONB NOT NULL,

    -- Aggregate score capturing the net pillar strength after the session.
    net_thesis_strength              NUMERIC,

    -- LLM-assist metadata (Phase 4: Opus required for high-stakes contestable
    -- judgment). The application is responsible for ensuring model='opus-*'
    -- when this row reflects a high-stakes session.
    llm_assist_metadata              JSONB NOT NULL,

    parameters_version               UUID,                  -- FK to parameters.version_id
    created_at                       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_premortem_ticker_date
    ON premortem(ticker, premortem_date DESC);

CREATE INDEX IF NOT EXISTS idx_premortem_trigger
    ON premortem(trigger, premortem_date DESC);

-- "When was the last pre-mortem for this ticker?" — drives cadence-floor
-- detection on the next /daily-monitor sweep.
CREATE INDEX IF NOT EXISTS idx_premortem_latest_per_ticker
    ON premortem(ticker, created_at DESC);

-- -----------------------------------------------------------------------------
-- Append-only trigger
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION premortem_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'premortem is append-only — % not permitted (insert a new row to record a fresh session)', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS premortem_no_modify ON premortem;
CREATE TRIGGER premortem_no_modify
BEFORE UPDATE OR DELETE ON premortem
FOR EACH ROW EXECUTE FUNCTION premortem_guard();

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

SELECT schemaname, tablename FROM pg_tables WHERE tablename = 'premortem';

SELECT indexname, tablename FROM pg_indexes
WHERE tablename = 'premortem'
ORDER BY indexname;

SELECT t.tgname, c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'premortem' AND NOT t.tgisinternal;

SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'premortem'::regclass AND contype = 'c'
ORDER BY conname;
