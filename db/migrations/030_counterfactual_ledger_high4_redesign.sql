-- =============================================================================
-- Migration: 030_counterfactual_ledger_high4_redesign
-- Purpose:   Implement the HIGH-4 consensus redesign of the counterfactual_ledger
--            per docs/high-4-enum-drift-consensus.md (2026-05-16), Consensus Items
--            #4 + #5. The prior schema (migration 003) assumed a 5-bin decision
--            enum {BUY, SELL, PASS, WATCH, TRIM, HOLD} and a 4-baseline
--            counterfactual {SPY, equal_weight_watchlist, sector_matched, 60_40}.
--            The HIGH-4 consensus dissolves both:
--              - Canonical decision enum collapses to 4-bin {BUY, HOLD, TRIM, SELL}
--                (Consensus Item #1; pm-supervisor.md §8 line 417).
--              - Benchmark is sector-conditional (SPDR sector ETF via GICS
--                mapping) per Brinson-Fachler convention (Consensus Item #5;
--                research-grounded — see consensus doc §9 sources [⁷]).
--              - Trigger generalizes to universal: every /research-company run
--                writes 4 rows (one per window: 90d / 1y / 3y / 5y) per
--                Consensus Item #4 (was: only PASS/REJECT bins triggered).
--              - Row-level formula is uniform raw active return; bin info
--                preserved as the summary_code column for stratified postmortem
--                queries (Consensus Item #5; CFA convention — sources [¹][⁵]).
--
-- Migration strategy: ADDITIVE (expand-then-contract pattern).
--   This migration ONLY adds new columns + indexes + check constraints. It
--   does NOT drop the legacy columns from migration 003 (decision_made,
--   baseline, system_return, baseline_return, delta_vs_baseline, etc.) so
--   that any in-flight code still writing to the old schema continues to
--   function during the rollout.
--
--   A subsequent contract migration (e.g., 03x_counterfactual_ledger_drop_legacy)
--   should be applied after all writers have migrated to the new columns
--   and any historical rows have been backfilled or archived.
--
-- Dependencies:
--   - Migration 003 (counterfactual_ledger base table) must be applied first.
--   - PostgreSQL 12+ for CHECK constraints with ALTER TABLE ADD CONSTRAINT.
--
-- Apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research -f db/migrations/030_counterfactual_ledger_high4_redesign.sql
--
-- Idempotency: safe to re-run. Uses ADD COLUMN IF NOT EXISTS, CREATE INDEX
-- IF NOT EXISTS, DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT, and CREATE OR
-- REPLACE FUNCTION for the trigger guard update.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- HIGH-4 schema columns (Consensus Item #5)
-- -----------------------------------------------------------------------------

ALTER TABLE counterfactual_ledger
    ADD COLUMN IF NOT EXISTS research_date              DATE,
    ADD COLUMN IF NOT EXISTS run_id                     UUID,
    ADD COLUMN IF NOT EXISTS summary_code               TEXT,
    ADD COLUMN IF NOT EXISTS conviction                 TEXT,
    ADD COLUMN IF NOT EXISTS gics_sector                TEXT,
    ADD COLUMN IF NOT EXISTS benchmark_etf              TEXT,
    ADD COLUMN IF NOT EXISTS "window"                   TEXT,
    ADD COLUMN IF NOT EXISTS measurement_date           DATE,
    ADD COLUMN IF NOT EXISTS ticker_return_pct          NUMERIC,
    ADD COLUMN IF NOT EXISTS benchmark_return_pct       NUMERIC,
    ADD COLUMN IF NOT EXISTS vs_sector_etf_return_pct   NUMERIC,
    ADD COLUMN IF NOT EXISTS spy_return_pct             NUMERIC,
    ADD COLUMN IF NOT EXISTS vs_spy_return_pct          NUMERIC,
    ADD COLUMN IF NOT EXISTS envelope_id                UUID;

-- -----------------------------------------------------------------------------
-- CHECK constraints aligned with HIGH-4 canonical enums
-- -----------------------------------------------------------------------------

-- Consensus Item #1: summary_code is the canonical 4-bin enum.
-- We add this as a constraint on the new column only; the legacy
-- decision_made constraint (allowing 5-bin) is preserved on legacy rows.
ALTER TABLE counterfactual_ledger
    DROP CONSTRAINT IF EXISTS counterfactual_ledger_summary_code_canonical;
ALTER TABLE counterfactual_ledger
    ADD CONSTRAINT counterfactual_ledger_summary_code_canonical
    CHECK (summary_code IS NULL
           OR summary_code IN ('BUY', 'HOLD', 'TRIM', 'SELL'));

-- Consensus Item #5: window is one of the 4 canonical measurement horizons.
ALTER TABLE counterfactual_ledger
    DROP CONSTRAINT IF EXISTS counterfactual_ledger_window_canonical;
ALTER TABLE counterfactual_ledger
    ADD CONSTRAINT counterfactual_ledger_window_canonical
    CHECK ("window" IS NULL
           OR "window" IN ('90d', '1y', '3y', '5y'));

-- Conviction enum mirrors the conviction_rollup module.
ALTER TABLE counterfactual_ledger
    DROP CONSTRAINT IF EXISTS counterfactual_ledger_conviction_canonical;
ALTER TABLE counterfactual_ledger
    ADD CONSTRAINT counterfactual_ledger_conviction_canonical
    CHECK (conviction IS NULL
           OR conviction IN ('HIGH', 'MEDIUM', 'LOW'));

-- HIGH-4 row uniqueness: one row per (ticker, run_id, window) triple. We
-- enforce this only when the new columns are populated; legacy rows from
-- migration 003 have all three NULL and are not affected.
DROP INDEX IF EXISTS idx_counterfactual_ledger_high4_unique;
CREATE UNIQUE INDEX idx_counterfactual_ledger_high4_unique
    ON counterfactual_ledger(ticker, run_id, "window")
    WHERE ticker IS NOT NULL
      AND run_id IS NOT NULL
      AND "window" IS NOT NULL;

-- -----------------------------------------------------------------------------
-- Indexes for postmortem query patterns
-- -----------------------------------------------------------------------------

-- Per-bin stratified queries: "all BUY rows where vs_sector_etf_return_pct > N"
CREATE INDEX IF NOT EXISTS idx_counterfactual_summary_code_window
    ON counterfactual_ledger(summary_code, "window")
    WHERE summary_code IS NOT NULL;

-- Aggregate calibration scan: every closed row per window.
CREATE INDEX IF NOT EXISTS idx_counterfactual_window_measurement
    ON counterfactual_ledger("window", measurement_date)
    WHERE measurement_date IS NOT NULL;

-- Per-sector postmortem: "all rows in Information Technology with 1y window"
CREATE INDEX IF NOT EXISTS idx_counterfactual_sector_window
    ON counterfactual_ledger(gics_sector, "window")
    WHERE gics_sector IS NOT NULL;

-- Envelope back-reference: trace a ledger row to the pm-supervisor envelope
-- that produced it (audit trail).
CREATE INDEX IF NOT EXISTS idx_counterfactual_envelope_id
    ON counterfactual_ledger(envelope_id)
    WHERE envelope_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- Append-only-with-completion trigger update
--
-- The HIGH-4 redesign keeps the append-only invariant but extends the
-- allowed UPDATE columns to include the new measurement fields. The
-- pattern is the same as migration 003: identity + decision metadata is
-- immutable; only the measurement fields populated when the window closes
-- may change after insert.
--
-- Allowed-to-change-after-insert (window-close completion fields):
--   - LEGACY (migration 003): evaluation_window_end, system_return, baseline_return
--   - HIGH-4 NEW: measurement_date, ticker_return_pct, benchmark_return_pct,
--                 vs_sector_etf_return_pct, spy_return_pct, vs_spy_return_pct
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION counterfactual_ledger_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'counterfactual_ledger is append-only — DELETE not permitted';
    END IF;

    -- TG_OP = 'UPDATE'. Allow only the completion fields to change.
    -- Identity / decision-metadata columns are immutable.
    IF NEW.ledger_entry_id          IS DISTINCT FROM OLD.ledger_entry_id
       OR NEW.agent_id              IS DISTINCT FROM OLD.agent_id
       OR NEW.agent_run_id          IS DISTINCT FROM OLD.agent_run_id
       OR NEW.ticker                IS DISTINCT FROM OLD.ticker
       OR NEW.decision_made         IS DISTINCT FROM OLD.decision_made
       OR NEW.decision_date         IS DISTINCT FROM OLD.decision_date
       OR NEW.baseline              IS DISTINCT FROM OLD.baseline
       OR NEW.evaluation_window_start IS DISTINCT FROM OLD.evaluation_window_start
       OR NEW.related_position_id   IS DISTINCT FROM OLD.related_position_id
       OR NEW.notes                 IS DISTINCT FROM OLD.notes
       OR NEW.created_at            IS DISTINCT FROM OLD.created_at
       -- HIGH-4 identity columns: immutable after insert.
       OR NEW.research_date         IS DISTINCT FROM OLD.research_date
       OR NEW.run_id                IS DISTINCT FROM OLD.run_id
       OR NEW.summary_code          IS DISTINCT FROM OLD.summary_code
       OR NEW.conviction            IS DISTINCT FROM OLD.conviction
       OR NEW.gics_sector           IS DISTINCT FROM OLD.gics_sector
       OR NEW.benchmark_etf         IS DISTINCT FROM OLD.benchmark_etf
       OR NEW."window"              IS DISTINCT FROM OLD."window"
       OR NEW.envelope_id           IS DISTINCT FROM OLD.envelope_id
    THEN
        RAISE EXCEPTION 'counterfactual_ledger UPDATE rejected: only window-close completion fields may change after insert (legacy: evaluation_window_end, system_return, baseline_return; HIGH-4: measurement_date, ticker_return_pct, benchmark_return_pct, vs_sector_etf_return_pct, spy_return_pct, vs_spy_return_pct)';
    END IF;
    -- Note: delta_vs_baseline (legacy) is GENERATED ALWAYS AS STORED and is
    -- intentionally excluded from the comparison — it auto-derives from
    -- system_return and baseline_return.

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger DDL is unchanged from migration 003 — the function-replace above
-- updates the body in place. Re-declaring the trigger here is defensive
-- (in case migration 003 has been partially rolled back).
DROP TRIGGER IF EXISTS counterfactual_ledger_no_modify ON counterfactual_ledger;
CREATE TRIGGER counterfactual_ledger_no_modify
BEFORE UPDATE OR DELETE ON counterfactual_ledger
FOR EACH ROW EXECUTE FUNCTION counterfactual_ledger_guard();

-- -----------------------------------------------------------------------------
-- Column comments — document deprecation of legacy columns
-- -----------------------------------------------------------------------------

COMMENT ON COLUMN counterfactual_ledger.decision_made IS
  'LEGACY (migration 003 5-bin enum). DEPRECATED per HIGH-4 consensus 2026-05-16. New rows should populate summary_code instead. CHECK constraint allows {BUY, SELL, PASS, WATCH, TRIM, HOLD} for back-compat with legacy rows; new code must NOT emit PASS or WATCH (per Consensus Item #1).';

COMMENT ON COLUMN counterfactual_ledger.baseline IS
  'LEGACY (migration 003 4-baseline enum {SPY, equal_weight_watchlist, sector_matched, 60_40}). DEPRECATED per HIGH-4 consensus 2026-05-16 — new rows use benchmark_etf (sector-ETF mapped from gics_sector).';

COMMENT ON COLUMN counterfactual_ledger.summary_code IS
  'HIGH-4 canonical decision (Consensus Item #1). One of {BUY, HOLD, TRIM, SELL}. The 5-bin operator vocabulary (ADD/WATCH/PASS/REJECT) is dissolved.';

COMMENT ON COLUMN counterfactual_ledger."window" IS
  'HIGH-4 measurement horizon (Consensus Item #5). One of {90d, 1y, 3y, 5y}. Each /research-company run produces 4 rows (one per window). 90d = catalyst tracking; 1y/3y/5y = industry-canonical postmortem trio.';

COMMENT ON COLUMN counterfactual_ledger.benchmark_etf IS
  'SPDR sector ETF mapped from gics_sector per Brinson-Fachler convention (Consensus Item #5). Isolates stock-picking from sector-allocation skill.';

COMMENT ON COLUMN counterfactual_ledger.vs_sector_etf_return_pct IS
  'Primary calibration signal: ticker_return_pct - benchmark_return_pct over the row''s window. Uniform raw active return per CFA single-name attribution convention. Risk-adjustment (Information Ratio) is computed at the /parameters-review aggregation layer across rows, not per-row.';

COMMIT;

-- =============================================================================
-- VERIFY: run these after applying to confirm the migration took effect.
-- =============================================================================

-- VERIFY: new HIGH-4 columns exist.
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'counterfactual_ledger'
  AND column_name IN ('summary_code', 'window', 'gics_sector', 'benchmark_etf',
                      'vs_sector_etf_return_pct', 'envelope_id')
ORDER BY column_name;

-- VERIFY: summary_code CHECK constraint enforces the canonical 4-bin enum.
-- This should error: INSERT ... summary_code = 'WATCH' violates the constraint.
-- Uncomment to test (will leave a dangling failed insert otherwise):
-- INSERT INTO counterfactual_ledger (
--     agent_id, agent_run_id, decision_made, decision_date, baseline,
--     evaluation_window_start, summary_code
-- ) VALUES (
--     'test', gen_random_uuid(), 'BUY', CURRENT_DATE, 'SPY',
--     CURRENT_DATE, 'WATCH'
-- );  -- Expected: ERROR — violates counterfactual_ledger_summary_code_canonical

-- VERIFY: new indexes exist.
SELECT indexname
FROM pg_indexes
WHERE tablename = 'counterfactual_ledger'
  AND indexname LIKE 'idx_counterfactual_%'
ORDER BY indexname;
