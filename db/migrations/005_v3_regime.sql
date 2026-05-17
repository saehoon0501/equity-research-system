-- =============================================================================
-- Migration: 005_v3_regime
-- Purpose:   S0 regime sidecar tables — daily classification of the 6 Tier-1
--            regime dimensions (per Section 3 Q1 lock) with BOCPD change-point
--            probabilities (per Section 3 Q3 lock).
--
--            Two artifacts:
--              - regime_classification_history (append-only event log;
--                one row per (date, dimension) tuple per day)
--              - regime_state (view exposing latest classification per
--                dimension; resolves Phase 2 Finding #16)
--
--            S0 outputs probability distributions per dimension (NOT point
--            classifications) at daily cadence. Cold-start window: first 90
--            trading days post-launch carry `cold_start: true` flag (per
--            Section 7.5 / Section 8 Q6).
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 4.1 (L1 / S0 — Regime sidecar); Section 3.2 (Postgres
--            tables); Section 8 Phase 4 — clarifies regime_state is a view.
--
-- Dimensions captured (per Section 3 Q1):
--   1 = Excess Bond Premium (EBP) — Gilchrist-Zakrajšek 2012
--   2 = Near-Term Forward Spread (NTFS) — Engstrom-Sharpe 2018
--   3 = Variance Risk Premium (VRP) — Bollerslev-Tauchen-Zhou 2009
--   4 = Monetary-policy / liquidity composite
--   5 = Trade-Weighted Broad Dollar (DTWEXBGS)
--   6 = Stock-bond correlation (Forbes-Rigobon corrected)
--
-- Dependencies:
--   - 004_v3_parameters (for parameters_version FK references at v0.5+;
--     not strictly required at v0.1 but applied first as a convention).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/005_v3_regime.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: regime_classification_history
-- Append-only daily classification log per dimension. One row per
-- (classification_date, dimension_id) tuple.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regime_classification_history (
    classification_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    classification_date        DATE NOT NULL,
    dimension_id               SMALLINT NOT NULL CHECK (dimension_id BETWEEN 1 AND 6),
    dimension_name             TEXT NOT NULL CHECK (dimension_name IN
                                  ('credit_ebp', 'cycle_2y3m_slope', 'vol_vrp',
                                   'mp_liquidity', 'dollar_dtwexbgs', 'stock_bond_corr')),
    -- NB: dim 2 was named 'cycle_ntfs' in v0.1 spec but the implementation
    -- uses the (DGS2 - DGS3MO) CMT slope, not the Engstrom-Sharpe NTFS. The
    -- canonical name reflects the actual computation; full GSW zero-coupon
    -- NTFS is deferred to v0.5+ (FRED THREEFY1/THREEFY2 wiring or
    -- neartermforwardspread.com CSV).

    -- Probability distribution per state. JSONB keyed by state name.
    -- E.g., for credit_ebp: {"benign": 0.65, "stressed": 0.30, "crisis": 0.05}
    state_probabilities        JSONB NOT NULL,

    -- Headline state = argmax of state_probabilities (denormalized for query speed).
    headline_state             TEXT NOT NULL,

    -- BOCPD change-point probability for this dimension at this date.
    -- 0.0 = no change-point; 1.0 = certain change-point.
    -- Per Section 3 Q3: > 0.7 sustained 2+ days = M-2; > 0.95 single-day = M-3.
    bocpd_change_probability   NUMERIC NOT NULL CHECK (bocpd_change_probability BETWEEN 0 AND 1),

    -- Raw inputs the classification was computed from (for replay / audit).
    -- E.g., for vol_vrp: {"vix_squared": 0.026, "realized_variance": 0.012, "vrp": 0.014}
    raw_inputs                 JSONB NOT NULL,

    -- Cold-start flag — true for first 90 trading days post-launch.
    -- See Section 7.5: regime overlays apply with cold_start_caveat annotation.
    cold_start                 BOOLEAN NOT NULL DEFAULT false,

    -- History length (days) used for the BOCPD computation. Useful for
    -- diagnosing cold-start quality issues (T-12mo seed at v0.1 launch).
    history_length_days        INTEGER NOT NULL,

    -- Versioning per Section 5 Q1 audit-trail lock + Phase 4 cleanup
    -- (uses (model_id, model_version) pair convention).
    rule_engine_version        TEXT NOT NULL,
    parameters_version         UUID,                  -- FK to parameters.version_id

    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Each (date, dimension_id) tuple should have exactly one row.
    CONSTRAINT regime_classification_unique
        UNIQUE (classification_date, dimension_id)
);

-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------

-- Time-series scans for BOCPD escalation detection per Section 3 Q3 firing rules.
CREATE INDEX IF NOT EXISTS idx_regime_history_date_dim
    ON regime_classification_history(classification_date DESC, dimension_id);

-- "Find all dates where BOCPD > 0.7 on a given dimension" — drives M-2/M-3 fire.
CREATE INDEX IF NOT EXISTS idx_regime_history_bocpd_high
    ON regime_classification_history(dimension_id, bocpd_change_probability DESC, classification_date)
    WHERE bocpd_change_probability >= 0.7;

-- Cold-start diagnostic queries.
CREATE INDEX IF NOT EXISTS idx_regime_history_cold_start
    ON regime_classification_history(cold_start, classification_date)
    WHERE cold_start = true;

-- -----------------------------------------------------------------------------
-- View: regime_state
-- Latest classification per dimension. Read this for "current regime."
-- (Resolves Phase 2 Finding #16: regime_state is a view, not a separate table.)
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
    parameters_version
FROM regime_classification_history
ORDER BY dimension_id, classification_date DESC;

-- -----------------------------------------------------------------------------
-- Append-only trigger
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION regime_classification_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'regime_classification_history is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS regime_classification_no_modify ON regime_classification_history;
CREATE TRIGGER regime_classification_no_modify
BEFORE UPDATE OR DELETE ON regime_classification_history
FOR EACH ROW EXECUTE FUNCTION regime_classification_guard();

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

SELECT schemaname, tablename FROM pg_tables WHERE tablename = 'regime_classification_history';
SELECT schemaname, viewname FROM pg_views WHERE viewname = 'regime_state';
SELECT indexname, tablename FROM pg_indexes
WHERE tablename = 'regime_classification_history'
  AND indexname LIKE 'idx_regime%'
ORDER BY indexname;
SELECT t.tgname, c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'regime_classification_history' AND NOT t.tgisinternal;
