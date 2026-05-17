-- =============================================================================
-- Migration: 003_counterfactual_ledger
-- Purpose:   Create the Counterfactual Ledger table — a v2-final first-class
--            object that records every agent decision alongside what would
--            have happened under simple baselines (SPY, equal-weight watchlist,
--            sector-matched basket, 60/40). This is "the system's escape from
--            self-deception" (v2-final §3.3): excellent process scores plus
--            poor counterfactual performance = sophisticated theater.
--
--            Each row pairs a decision moment (agent + ticker + decision_date)
--            with one baseline and one evaluation window. Multiple baselines
--            for the same decision = multiple rows (one per baseline).
--
-- Reference: docs/v2-final-spec.md §3.3 ("Counterfactual Ledger") and §2.7
--            (counterfactual baselines list, line 495).
--
-- Schema choice: MINIMAL VIABLE schema.
--   v2-final-spec.md §3.3 specifies the *behavior* of the ledger (which
--   agent actions trigger entries, and which counterfactual is computed
--   for each), but does NOT enumerate column-level fields. The rubric
--   reference (.claude/references/process-rubric.md) does not extend
--   that specification. We therefore implement the minimal schema
--   defined in the migration brief, which captures: who decided what,
--   when, against which baseline, over what window, and the realized
--   delta. Additional columns (e.g., risk-adjusted return, drawdown,
--   after-tax delta for ExitSignal cases) can be added in a later
--   migration once the LearningLoop's actual query patterns are known.
--
-- Dependencies:
--   - PostgreSQL 13+ for gen_random_uuid() in core.
--   - PostgreSQL 12+ for GENERATED ALWAYS AS ... STORED columns
--     (delta_vs_baseline). Postgres 16 in the dev container satisfies this.
--   - Migration 001 (evidence_index) is logically related but not a hard
--     dependency. related_position_id is intentionally a bare UUID, not
--     a FK — positions live in a separate table that arrives in a later
--     migration, and we want the ledger to be writable before that table
--     exists.
--
-- How to apply (one-line psql, run from repo root):
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research -f db/migrations/003_counterfactual_ledger.sql
--
-- Idempotency: safe to re-run. Uses CREATE TABLE IF NOT EXISTS, CREATE INDEX
-- IF NOT EXISTS, CREATE OR REPLACE FUNCTION, and DROP TRIGGER IF EXISTS +
-- CREATE TRIGGER (Postgres has no CREATE TRIGGER IF NOT EXISTS).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: counterfactual_ledger
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS counterfactual_ledger (
    ledger_entry_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id                  TEXT NOT NULL,        -- 'entry-timing', 'exit-check', 'pm-supervisor', etc.
    agent_run_id              UUID NOT NULL,        -- groups all ledger entries from one agent invocation
    ticker                    TEXT,                 -- null when decision is portfolio-level (e.g., 60/40 sleeve)
    decision_made             TEXT NOT NULL CHECK (decision_made IN
                                  ('BUY', 'SELL', 'PASS', 'WATCH', 'TRIM', 'HOLD')),
    decision_date             DATE NOT NULL,
    baseline                  TEXT NOT NULL CHECK (baseline IN
                                  ('SPY', 'equal_weight_watchlist', 'sector_matched', '60_40')),
    evaluation_window_start   DATE NOT NULL,
    evaluation_window_end     DATE,                 -- null while window is open
    system_return             NUMERIC,              -- null until window closes; realized return of the system's decision
    baseline_return           NUMERIC,              -- null until window closes; realized return of the chosen baseline
    delta_vs_baseline         NUMERIC GENERATED ALWAYS AS (system_return - baseline_return) STORED,
    related_position_id       UUID,                 -- optional; null for Pass / Watch decisions that never opened a position
    notes                     TEXT,
    created_at                TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Sanity: window must not run backwards when it is closed.
    CONSTRAINT counterfactual_ledger_window_order
        CHECK (evaluation_window_end IS NULL
               OR evaluation_window_end >= evaluation_window_start)
);

-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------

-- Lookup all ledger entries from a single agent run (debugging, audit).
CREATE INDEX IF NOT EXISTS idx_counterfactual_agent_run
    ON counterfactual_ledger(agent_run_id);

-- Per-ticker time-series queries (e.g., "all decisions on AAPL").
CREATE INDEX IF NOT EXISTS idx_counterfactual_ticker_date
    ON counterfactual_ledger(ticker, decision_date);

-- Per-baseline aggregation (e.g., "system delta vs SPY across all decisions").
CREATE INDEX IF NOT EXISTS idx_counterfactual_baseline_date
    ON counterfactual_ledger(baseline, decision_date);

-- Closed-window scans for outcome reporting. Partial index keeps it small,
-- since rows live with NULL evaluation_window_end for most of their lifetime.
CREATE INDEX IF NOT EXISTS idx_counterfactual_closed_windows
    ON counterfactual_ledger(evaluation_window_end)
    WHERE evaluation_window_end IS NOT NULL;

-- -----------------------------------------------------------------------------
-- Append-only-with-completion trigger
--
-- The Counterfactual Ledger is append-only with one explicit exception:
-- when an evaluation window closes, a resolution job populates three fields
-- and three fields only:
--     evaluation_window_end, system_return, baseline_return
-- Any other column change is rejected. DELETE is always rejected.
--
-- delta_vs_baseline is a STORED GENERATED column derived from system_return
-- and baseline_return; it changes automatically when those change, so we
-- explicitly skip it in the OLD/NEW comparison (touching it in NEW would
-- itself error out at the column level).
--
-- IS DISTINCT FROM is used for NULL-safe equality so that NULL → value is
-- detected as a change (NULL = NULL evaluates to NULL, which would make a
-- naive equality test miss the transition we are specifically allowing).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION counterfactual_ledger_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'counterfactual_ledger is append-only — DELETE not permitted';
    END IF;

    -- TG_OP = 'UPDATE'. Allow only the three completion fields to change.
    IF NEW.ledger_entry_id         IS DISTINCT FROM OLD.ledger_entry_id
       OR NEW.agent_id             IS DISTINCT FROM OLD.agent_id
       OR NEW.agent_run_id         IS DISTINCT FROM OLD.agent_run_id
       OR NEW.ticker               IS DISTINCT FROM OLD.ticker
       OR NEW.decision_made        IS DISTINCT FROM OLD.decision_made
       OR NEW.decision_date        IS DISTINCT FROM OLD.decision_date
       OR NEW.baseline             IS DISTINCT FROM OLD.baseline
       OR NEW.evaluation_window_start IS DISTINCT FROM OLD.evaluation_window_start
       OR NEW.related_position_id  IS DISTINCT FROM OLD.related_position_id
       OR NEW.notes                IS DISTINCT FROM OLD.notes
       OR NEW.created_at           IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'counterfactual_ledger UPDATE rejected: only evaluation_window_end, system_return, and baseline_return may change after insert';
    END IF;
    -- Note: delta_vs_baseline is GENERATED ALWAYS AS STORED and is intentionally
    -- excluded from the comparison above — it auto-derives from system_return
    -- and baseline_return.

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS counterfactual_ledger_no_modify ON counterfactual_ledger;
CREATE TRIGGER counterfactual_ledger_no_modify
BEFORE UPDATE OR DELETE ON counterfactual_ledger
FOR EACH ROW EXECUTE FUNCTION counterfactual_ledger_guard();

COMMIT;

-- =============================================================================
-- VERIFY: run these after applying to confirm the migration took effect.
-- Each query should return the expected row(s); zero rows = migration failed.
-- =============================================================================

-- VERIFY: counterfactual_ledger table exists in the public schema.
SELECT schemaname, tablename
FROM pg_tables
WHERE tablename = 'counterfactual_ledger';

-- VERIFY: delta_vs_baseline is a STORED GENERATED column.
SELECT column_name, is_generated, generation_expression
FROM information_schema.columns
WHERE table_name = 'counterfactual_ledger'
  AND column_name = 'delta_vs_baseline';

-- VERIFY: all four expected indexes are present.
SELECT indexname, tablename
FROM pg_indexes
WHERE tablename = 'counterfactual_ledger'
  AND indexname IN (
      'idx_counterfactual_agent_run',
      'idx_counterfactual_ticker_date',
      'idx_counterfactual_baseline_date',
      'idx_counterfactual_closed_windows'
  )
ORDER BY indexname;

-- VERIFY: append-only-with-completion trigger is wired to counterfactual_ledger.
SELECT t.tgname AS trigger_name,
       c.relname AS table_name,
       p.proname AS function_name
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_proc  p ON p.oid = t.tgfoid
WHERE c.relname = 'counterfactual_ledger'
  AND t.tgname  = 'counterfactual_ledger_no_modify'
  AND NOT t.tgisinternal;

-- VERIFY: CHECK constraints for decision_made and baseline are present.
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'counterfactual_ledger'::regclass
  AND contype = 'c'
ORDER BY conname;
