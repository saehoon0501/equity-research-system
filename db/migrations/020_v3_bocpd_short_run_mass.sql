-- =============================================================================
-- Migration: 020_v3_bocpd_short_run_mass
-- Purpose:   Add `bocpd_short_run_mass` as a first-class dual signal alongside
--            the canonical Adams-MacKay marginal `bocpd_change_probability`.
--
--            Per operator-locked decision (BOCPD dual-signal architecture):
--              - `bocpd_change_probability` = canonical Adams-MacKay marginal
--                P(r_t = 0 | x_{1:t}). Retained for academic rigor + audit
--                traceability. Structurally pinned near hazard rate (~0.004)
--                in steady state — does NOT cross v3 §4.1 firing thresholds
--                in steady state.
--              - `bocpd_short_run_mass` = cumulative posterior
--                P(r_t < 10 | x_{1:t}). PRIMARY firing signal: drives M-2/M-3
--                materiality firing per v3 §4.1 thresholds (>0.7 sustained
--                2+d → M-2; >0.95 single-day → M-3 + alert).
--
--            Both signals are stored, both indexed, both auditable.
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            §4.1 (L1 / S0 — Regime sidecar; firing thresholds);
--            §3 Q3 (BOCPD method overlay lock — dual-signal architecture).
--
-- How to apply:
--   PGPASSWORD=... psql -h 127.0.0.1 -p 5432 -U equity_research_admin \
--                  -d equity_research -v ON_ERROR_STOP=1 \
--                  -f db/migrations/020_v3_bocpd_short_run_mass.sql
--
-- Idempotency: safe to re-run (uses ADD COLUMN IF NOT EXISTS / CREATE INDEX
-- IF NOT EXISTS / CREATE OR REPLACE VIEW).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Step 1 — Add bocpd_short_run_mass column with default 0 so existing rows
-- satisfy NOT NULL; drop default afterwards so future writes MUST explicitly
-- compute and provide both signals (per operator-locked dual-signal contract).
-- -----------------------------------------------------------------------------
ALTER TABLE regime_classification_history
    ADD COLUMN IF NOT EXISTS bocpd_short_run_mass NUMERIC NOT NULL DEFAULT 0
    CHECK (bocpd_short_run_mass BETWEEN 0 AND 1);

COMMENT ON COLUMN regime_classification_history.bocpd_short_run_mass IS
    'Cumulative posterior P(r_t < 10 | x_{1:t}). Drives M-2/M-3 firing per Section 4.1 thresholds (>0.7 sustained 2+d → M-2; >0.95 single-day → M-3). canonical Adams-MacKay marginal P(r_t=0) lives in bocpd_change_probability for audit traceability — that signal is structurally pinned near hazard rate.';

COMMENT ON COLUMN regime_classification_history.bocpd_change_probability IS
    'Canonical Adams-MacKay change-point marginal P(r_t = 0 | x_{1:t}). Retained for academic rigor + audit traceability per dual-signal architecture. Structurally pinned near hazard rate in steady state — does NOT systematically cross v3 §4.1 firing thresholds. Use bocpd_short_run_mass for firing decisions.';

-- Drop the DEFAULT now that the column is populated for existing rows.
-- Future INSERTs MUST explicitly supply bocpd_short_run_mass — this enforces
-- the dual-signal contract at the storage layer.
ALTER TABLE regime_classification_history
    ALTER COLUMN bocpd_short_run_mass DROP DEFAULT;

-- -----------------------------------------------------------------------------
-- Step 2 — Index for "short-run mass crossed firing threshold" queries.
-- Mirrors the existing idx_regime_history_bocpd_high pattern but keyed on
-- the firing-driver signal.
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_regime_history_short_run_high
    ON regime_classification_history(dimension_id, bocpd_short_run_mass DESC, classification_date)
    WHERE bocpd_short_run_mass >= 0.7;

-- -----------------------------------------------------------------------------
-- Step 3 — Refresh the regime_state view to include the new column. CREATE
-- OR REPLACE VIEW is permitted only when the column list at the front of the
-- SELECT does not change ORDER. We are *appending* bocpd_short_run_mass at
-- the end, so OR REPLACE works.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW regime_state AS
SELECT DISTINCT ON (dimension_id)
    classification_id,
    classification_date,
    dimension_id,
    dimension_name,
    state_probabilities,
    headline_state,
    bocpd_change_probability,
    raw_inputs,
    cold_start,
    history_length_days,
    rule_engine_version,
    parameters_version,
    bocpd_short_run_mass
FROM regime_classification_history
ORDER BY dimension_id, classification_date DESC;

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

-- Column added with the expected check constraint and NOT NULL.
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'regime_classification_history'
  AND column_name IN ('bocpd_change_probability', 'bocpd_short_run_mass')
ORDER BY column_name;

-- Index present.
SELECT indexname FROM pg_indexes
WHERE tablename = 'regime_classification_history'
  AND indexname = 'idx_regime_history_short_run_high';

-- View includes both signals.
SELECT column_name FROM information_schema.columns
WHERE table_name = 'regime_state'
  AND column_name IN ('bocpd_change_probability', 'bocpd_short_run_mass')
ORDER BY column_name;
