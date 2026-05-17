-- =============================================================================
-- Migration: 007_v3_watchlist_positions
-- Purpose:   Three tables that bridge research artifact to real-money state:
--              - watchlist        (P5 research-approved names; research artifact)
--              - positions        (current portfolio state; broker-MCP synced)
--              - position_history (append-only event log of fills / corp actions)
--
--            Per Section 2.1, watchlist != portfolio. Watchlist is a research
--            artifact (curated approved-to-buy names with conviction + size
--            bands + kill criteria); positions is the real-money state synced
--            from broker MCP (Section 7 Q5). position_history is the append-
--            only ledger of every fill / dividend / split / transfer.
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 2.1 (funnel composition; watchlist vs portfolio);
--            Section 2.2 (mode + company-quality flag);
--            Section 3.2 (Postgres tables);
--            Section 6.2 (HMAC-signed thesis pillars / scenario A baselines);
--            Section 7 Q5 (broker MCP position state source).
--
-- Schema choice:
--   - watchlist PK is ticker (TEXT) — single-mode-per-name model per
--     Section 2.2. Reclassification = UPDATE in place + Section 6 Q4
--     pre-mortem (enforced by application layer, not schema).
--   - thesis_pillars_original + scenario_A_base_projections are JSONB +
--     accompanying *_hmac TEXT fields. Per Section 6 Q5 / 6.2, these are
--     HMAC-signed at write time so anchor-drift detection (3-channel) can
--     verify the original is untampered. The HMAC is computed over the
--     canonical-JSON serialization of the JSONB; verification lives in the
--     drift-checking application code.
--   - positions has UNIQUE(ticker, broker, account_id_hash) so the same
--     ticker held in two accounts (e.g., taxable + IRA) gets two rows.
--   - position_history.recommendation_ref is nullable because divergence
--     events (operator override, manual fill) may have no system rec to
--     reference; divergence_from_recommendation captures the diff.
--
-- Append policy:
--   - watchlist:         UPDATE allowed (state table; conviction / mode /
--                        kill criteria revised over name's life). DELETE
--                        blocked (history matters; rejected names are
--                        marked, not deleted).
--   - positions:         UPDATE allowed (broker MCP overwrites snapshot
--                        each poll). DELETE blocked.
--   - position_history:  full append-only (UPDATE + DELETE blocked).
--
-- Dependencies:
--   - 004_v3_parameters (parameters_version FK target on watchlist).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/007_v3_watchlist_positions.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: watchlist
-- P5 research-approved names. One row per ticker (single-mode-per-name model
-- per Section 2.2).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS watchlist (
    ticker                          TEXT PRIMARY KEY,

    -- Mode bin per Section 2.2 Stage 1 market-structural classifier.
    mode                            TEXT NOT NULL
                                      CHECK (mode IN ('B', 'B_prime', 'C')),

    -- Quality flag per Section 2.2 Stage 2 (conviction multiplier input).
    company_quality_flag            TEXT NOT NULL
                                      CHECK (company_quality_flag IN ('HIGH', 'STANDARD')),

    -- Conviction threshold for trade-eligibility. Mode-default: B≥0.7, B'≥0.6,
    -- C≥0.5 per Section 2.2 mode-specific discipline; per-name override allowed.
    conviction_threshold            NUMERIC NOT NULL
                                      CHECK (conviction_threshold BETWEEN 0 AND 1),

    -- Original thesis pillars at P5 lock — IMMUTABLE in spirit, HMAC-signed
    -- so 3-channel anchor-drift detection (Section 6.2) can verify tamper-
    -- evidence. Application layer must NOT mutate this column post-lock; the
    -- HMAC validation in `/anchor-drift` will refuse any post-lock change.
    thesis_pillars_original         JSONB NOT NULL,
    thesis_pillars_original_hmac    TEXT NOT NULL,

    -- Scenario A (base) projections at P5 lock — same HMAC discipline.
    scenario_A_base_projections     JSONB NOT NULL,
    scenario_A_base_projections_hmac TEXT NOT NULL,

    -- Regime sensitivity per Section 4.7 / 4.8 — drives auto-re-underwrite
    -- on S0 regime shift (HIGH = auto; MEDIUM = quarterly; LOW = ignore).
    regime_sensitivity              TEXT NOT NULL
                                      CHECK (regime_sensitivity IN ('HIGH', 'MEDIUM', 'LOW')),

    added_at                        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_reunderwritten_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Pin to parameters config used at P5 lock.
    parameters_version              UUID REFERENCES parameters(version_id)
);

-- Indexes for watchlist
CREATE INDEX IF NOT EXISTS idx_watchlist_mode
    ON watchlist(mode);

CREATE INDEX IF NOT EXISTS idx_watchlist_regime_sensitivity
    ON watchlist(regime_sensitivity)
    WHERE regime_sensitivity = 'HIGH';

CREATE INDEX IF NOT EXISTS idx_watchlist_quality
    ON watchlist(mode, company_quality_flag);

-- -----------------------------------------------------------------------------
-- Table: positions
-- Real-money portfolio state. Broker-MCP-synced (Section 7 Q5).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS positions (
    position_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker                      TEXT NOT NULL,
    shares_held                 NUMERIC NOT NULL,
    cost_basis                  NUMERIC NOT NULL,
    cost_basis_method           TEXT NOT NULL DEFAULT 'FIFO'
                                  CHECK (cost_basis_method IN ('FIFO', 'LIFO', 'SPECIFIC_LOT', 'AVERAGE')),
    first_acquired              DATE NOT NULL,
    last_updated                TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Provenance metadata per Section 7 Q5.
    source                      TEXT NOT NULL,        -- e.g., 'mcp__broker__get_positions'
    broker                      TEXT NOT NULL,        -- e.g., 'fidelity', 'schwab'
    account_id_hash             TEXT NOT NULL,        -- hashed account ID (PII protection)

    -- Same ticker held across two accounts (taxable + IRA) = two rows.
    CONSTRAINT positions_unique_per_account
        UNIQUE (ticker, broker, account_id_hash)
);

-- Indexes for positions
CREATE INDEX IF NOT EXISTS idx_positions_ticker
    ON positions(ticker);

CREATE INDEX IF NOT EXISTS idx_positions_broker
    ON positions(broker, account_id_hash);

-- -----------------------------------------------------------------------------
-- Table: position_history
-- Append-only event log of every position-state change.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS position_history (
    event_id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker                            TEXT NOT NULL,
    event_type                        TEXT NOT NULL
                                        CHECK (event_type IN
                                          ('BUY', 'SELL', 'DIVIDEND', 'SPLIT',
                                           'TRANSFER_IN', 'TRANSFER_OUT')),
    event_date                        DATE NOT NULL,
    shares_delta                      NUMERIC NOT NULL,
    price                             NUMERIC,
    detection_method                  TEXT NOT NULL,    -- 'broker_diff' / 'manual' / 'corp_action_feed'

    -- Reference to the system recommendation that should have produced this
    -- event (nullable — manual fills / corp actions / overrides have no rec).
    recommendation_ref                UUID,

    -- Captures gap between what system recommended and what actually filled
    -- (timing, sizing %, slippage). Schema (per Section 4.6 fill_divergence):
    --   {timing_lag_days: int, sizing_pct_diff: numeric, slippage_bps: numeric,
    --    override_rationale: text|null}
    divergence_from_recommendation    JSONB,

    created_at                        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for position_history
CREATE INDEX IF NOT EXISTS idx_position_history_ticker_date
    ON position_history(ticker, event_date DESC);

CREATE INDEX IF NOT EXISTS idx_position_history_event_type
    ON position_history(event_type, event_date DESC);

CREATE INDEX IF NOT EXISTS idx_position_history_rec_ref
    ON position_history(recommendation_ref)
    WHERE recommendation_ref IS NOT NULL;

-- -----------------------------------------------------------------------------
-- Triggers
--
-- watchlist:        UPDATE allowed; DELETE blocked.
-- positions:        UPDATE allowed; DELETE blocked.
-- position_history: full append-only.
-- -----------------------------------------------------------------------------

-- watchlist guard
CREATE OR REPLACE FUNCTION watchlist_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'watchlist is delete-protected — DELETE not permitted (rejected names should be marked, not deleted)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS watchlist_no_delete ON watchlist;
CREATE TRIGGER watchlist_no_delete
BEFORE DELETE ON watchlist
FOR EACH ROW EXECUTE FUNCTION watchlist_guard();

-- positions guard
CREATE OR REPLACE FUNCTION positions_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'positions is delete-protected — DELETE not permitted (closed positions kept for tax-lot history)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS positions_no_delete ON positions;
CREATE TRIGGER positions_no_delete
BEFORE DELETE ON positions
FOR EACH ROW EXECUTE FUNCTION positions_guard();

-- position_history guard (full append-only)
CREATE OR REPLACE FUNCTION position_history_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        RAISE EXCEPTION 'position_history is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS position_history_no_modify ON position_history;
CREATE TRIGGER position_history_no_modify
BEFORE UPDATE OR DELETE ON position_history
FOR EACH ROW EXECUTE FUNCTION position_history_guard();

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

-- VERIFY: all 3 tables exist.
SELECT schemaname, tablename FROM pg_tables
WHERE tablename IN ('watchlist', 'positions', 'position_history')
ORDER BY tablename;

-- VERIFY: indexes present.
SELECT indexname, tablename FROM pg_indexes
WHERE tablename IN ('watchlist', 'positions', 'position_history')
  AND indexname LIKE 'idx_%'
ORDER BY tablename, indexname;

-- VERIFY: UNIQUE constraint on positions.
SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
WHERE conrelid = 'positions'::regclass AND contype = 'u'
ORDER BY conname;

-- VERIFY: triggers wired.
SELECT t.tgname, c.relname FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname IN ('watchlist', 'positions', 'position_history')
  AND NOT t.tgisinternal
ORDER BY c.relname, t.tgname;

-- VERIFY: CHECK constraints on watchlist (mode / quality / sensitivity).
SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
WHERE conrelid = 'watchlist'::regclass AND contype = 'c'
ORDER BY conname;
