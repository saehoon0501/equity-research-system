-- =============================================================================
-- Migration: 048_decision_trace_telemetry
-- Purpose:   Inner-ring storage surface for Decision-Trace Telemetry
--            (.kiro/specs/decision-trace-telemetry). Two artifacts land in ONE
--            migration so the trace and the version dimension arrive atomically:
--
--            (1) A NEW append-only, single-table, kind-discriminated event store
--                `decision_process_trace` — a durable, replayable per-decision
--                MODEL trace written directly by the execution-daemon (§14.10).
--                Each row carries the four typed correlation keys (run_id,
--                code_version, param_version, walk_forward_window) + a JSONB
--                `trace` payload so new per-decision signal fields never force a
--                schema migration (requirements.md 8.2). A `fill` row links to
--                its `decision` row via `parent_trace_id` (async decision→fill,
--                resolved as a SEPARATE linked row, never an in-place update —
--                design.md "System Flows", R1.4 ↔ R2). trace_id is CLIENT-minted
--                (no DEFAULT) so it doubles as the ON CONFLICT idempotency key.
--                Append-only is STRICTER than the ledger: UPDATE, DELETE, AND
--                TRUNCATE are all rejected (requirements.md 2.1, 2.2).
--
--            (2) An ADDITIVE extension of the existing `counterfactual_ledger`
--                with three nullable model-version columns (code_version,
--                param_version, walk_forward_window) + a version+window index,
--                so forward P&L attributes per-(code version, param version)-per-
--                walk-forward-window without disturbing the existing 4-bin
--                sector-ETF-excess scoring (requirements.md 4.1–4.4). The ledger's
--                append-only guard is CREATE OR REPLACE'd to add the three new
--                columns to its immutable (insert-set-only) set; all of migration
--                030's immutable columns are reproduced verbatim and the window-
--                close completion fields stay mutable (requirements.md 4.4, 5.1).
--
-- Reference: .kiro/specs/decision-trace-telemetry/design.md
--              "Data Models → Physical (migration 048)", "Migration Strategy".
--            .kiro/specs/decision-trace-telemetry/requirements.md
--              2.1, 2.2, 4.1, 4.2, 4.3, 4.4, 5.1, 7.4, 8.1.
--
-- Dependencies:
--   - Migration 003 (counterfactual_ledger base table + guard) applied first.
--   - Migration 030 (HIGH-4 redesign: 19-column immutable guard + new columns)
--     applied first. The guard CREATE OR REPLACE below starts from 030's CURRENT
--     body (its full 19-column immutable blacklist), NOT 003's older 11-column
--     body — CREATE OR REPLACE swaps the WHOLE body, so a fresh 3-column-only
--     guard would silently regress immutability of summary_code/gics_sector/etc.
--   - PostgreSQL 13+ (gen_random_uuid in core; not used for trace_id — it is
--     client-minted — but referenced by the ledger's own DEFAULT from 003).
--
-- Apply (one-line psql, run from repo root):
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research -f db/migrations/048_decision_trace_telemetry.sql
--
-- Idempotency: safe to re-run. Uses CREATE TABLE IF NOT EXISTS, CREATE INDEX
-- IF NOT EXISTS, ADD COLUMN IF NOT EXISTS, CREATE OR REPLACE FUNCTION, and
-- DROP TRIGGER IF EXISTS + CREATE TRIGGER (Postgres has no CREATE TRIGGER
-- IF NOT EXISTS). Forward-only: no down-migration (repo convention, db/README.md;
-- expand-then-contract per design.md "Migration Strategy").
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- (1) Table: decision_process_trace — append-only, single-table, kind-discriminated
--
-- trace_id is CLIENT-minted (NO DEFAULT): the caller supplies the UUID, which
-- (a) lets a 'fill' row reference its 'decision' row before the DB assigns
-- anything, and (b) doubles as the ON CONFLICT idempotency key in the writer
-- (addresses the broker G10 double-send residual — design.md trace_writer).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS decision_process_trace (
    trace_id            UUID PRIMARY KEY,                                       -- CLIENT-minted (no default)
    kind                TEXT NOT NULL CHECK (kind IN ('decision', 'fill')),
    parent_trace_id     UUID NULL REFERENCES decision_process_trace(trace_id),  -- set on 'fill' = the decision's trace_id
    event_ts            TIMESTAMPTZ NOT NULL,                                   -- time of THIS event (decision time, or fill-landing time for kind=fill)
    run_id              UUID NOT NULL,
    code_version        TEXT NOT NULL,
    param_version       TEXT NOT NULL,
    walk_forward_window TEXT NULL,
    trace               JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Correlation-key + replay indexes (design.md "Physical (migration 048)").
CREATE INDEX IF NOT EXISTS idx_dpt_run
    ON decision_process_trace (run_id);
CREATE INDEX IF NOT EXISTS idx_dpt_version_window
    ON decision_process_trace (code_version, param_version, walk_forward_window);
CREATE INDEX IF NOT EXISTS idx_dpt_event_ts
    ON decision_process_trace (event_ts);
CREATE INDEX IF NOT EXISTS idx_dpt_parent
    ON decision_process_trace (parent_trace_id);

-- -----------------------------------------------------------------------------
-- STRICT append-only guard for decision_process_trace.
--
-- Stricter than the ledger: block UPDATE, DELETE, AND TRUNCATE. (The ledger
-- allows window-close completion UPDATEs and leaves TRUNCATE uncovered; that
-- ledger carve-out is inherited unchanged and is out of THIS table's boundary.)
--
-- The guard raises UNCONDITIONALLY on TG_OP and touches no NEW/OLD, so ONE
-- function serves both triggers: the row-level BEFORE UPDATE OR DELETE trigger
-- and the statement-level BEFORE TRUNCATE trigger. Control never reaches the
-- end of the function (RAISE always fires), so no RETURN is needed.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION decision_process_trace_guard() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'decision_process_trace is append-only — % not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

-- Row-level guard: reject UPDATE / DELETE on any row.
DROP TRIGGER IF EXISTS decision_process_trace_no_modify ON decision_process_trace;
CREATE TRIGGER decision_process_trace_no_modify
    BEFORE UPDATE OR DELETE ON decision_process_trace
    FOR EACH ROW EXECUTE FUNCTION decision_process_trace_guard();

-- Statement-level guard: reject TRUNCATE (TRUNCATE fires no row-level triggers,
-- so it needs its own BEFORE TRUNCATE FOR EACH STATEMENT trigger).
DROP TRIGGER IF EXISTS decision_process_trace_no_truncate ON decision_process_trace;
CREATE TRIGGER decision_process_trace_no_truncate
    BEFORE TRUNCATE ON decision_process_trace
    FOR EACH STATEMENT EXECUTE FUNCTION decision_process_trace_guard();

-- -----------------------------------------------------------------------------
-- (2) counterfactual_ledger: additive model-version dimension.
--
-- Three nullable columns (back-compatible: legacy rows keep NULL version cols)
-- + a version+window index. Preserves all existing columns, scoring, and
-- behavior (requirements.md 4.1, 4.2). ADD COLUMN runs before the guard
-- CREATE OR REPLACE so the new columns exist when the guard references them
-- (cosmetic — PL/pgSQL is late-bound — but matches the design sketch).
-- -----------------------------------------------------------------------------
ALTER TABLE counterfactual_ledger
    ADD COLUMN IF NOT EXISTS code_version        TEXT,
    ADD COLUMN IF NOT EXISTS param_version       TEXT,
    ADD COLUMN IF NOT EXISTS walk_forward_window TEXT;

-- Version-attributed forward-P&L scan: "all rows for (code_version,
-- param_version, walk_forward_window)" (requirements.md 4.3, 5.1).
CREATE INDEX IF NOT EXISTS idx_counterfactual_version_window
    ON counterfactual_ledger (code_version, param_version, walk_forward_window);

-- -----------------------------------------------------------------------------
-- counterfactual_ledger_guard(): CREATE OR REPLACE extending migration 030's
-- CURRENT immutable blacklist.
--
-- CREATE OR REPLACE swaps the WHOLE body, so this reproduces migration 030's
-- full 19-column immutable set VERBATIM and ADDS the three new model-version
-- columns (code_version, param_version, walk_forward_window) with NULL-safe
-- IS DISTINCT FROM checks — making them insert-set-only (immutable after
-- insert), 22 immutable columns total.
--
-- The window-close completion fields stay MUTABLE (intentionally absent from
-- the OR-chain): legacy evaluation_window_end / system_return / baseline_return
-- + HIGH-4 measurement_date / ticker_return_pct / benchmark_return_pct /
-- vs_sector_etf_return_pct / spy_return_pct / vs_spy_return_pct. delta_vs_baseline
-- (legacy) is GENERATED ALWAYS AS STORED and is intentionally excluded — it
-- auto-derives from system_return + baseline_return (touching it in NEW would
-- itself error at the column level). This preserves the ledger's existing
-- append-only integrity (requirements.md 4.4).
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
       -- Decision-Trace Telemetry model-version columns (migration 048):
       -- insert-set-only, immutable after insert.
       OR NEW.code_version          IS DISTINCT FROM OLD.code_version
       OR NEW.param_version         IS DISTINCT FROM OLD.param_version
       OR NEW.walk_forward_window   IS DISTINCT FROM OLD.walk_forward_window
    THEN
        RAISE EXCEPTION 'counterfactual_ledger UPDATE rejected: only window-close completion fields may change after insert (legacy: evaluation_window_end, system_return, baseline_return; HIGH-4: measurement_date, ticker_return_pct, benchmark_return_pct, vs_sector_etf_return_pct, spy_return_pct, vs_spy_return_pct)';
    END IF;
    -- Note: delta_vs_baseline (legacy) is GENERATED ALWAYS AS STORED and is
    -- intentionally excluded from the comparison — it auto-derives from
    -- system_return and baseline_return.

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger DDL is unchanged from migration 003/030 — the function-replace above
-- updates the body in place. Re-declaring the trigger is defensive (in case an
-- earlier migration has been partially rolled back).
DROP TRIGGER IF EXISTS counterfactual_ledger_no_modify ON counterfactual_ledger;
CREATE TRIGGER counterfactual_ledger_no_modify
BEFORE UPDATE OR DELETE ON counterfactual_ledger
FOR EACH ROW EXECUTE FUNCTION counterfactual_ledger_guard();

-- -----------------------------------------------------------------------------
-- Column comments
-- -----------------------------------------------------------------------------
COMMENT ON TABLE decision_process_trace IS
  'Decision-Trace Telemetry (.kiro/specs/decision-trace-telemetry): append-only, single-table, kind-discriminated per-decision MODEL trace. Written directly by the execution-daemon (§14.10). MODEL trace only — the LLM-action/reasoning audit is owned per-spec by walkforward-tuning-loop + in-session-monitor (P11) and joins here via the correlation keys.';

COMMENT ON COLUMN decision_process_trace.trace_id IS
  'CLIENT-minted UUID (no default). Caller supplies it so a fill row can reference its decision row and so the writer''s ON CONFLICT (trace_id) DO NOTHING is an idempotency key.';

COMMENT ON COLUMN decision_process_trace.kind IS
  'decision | fill. A fill row resolves a prior decision row (async order, §11.4) and links via parent_trace_id — never an in-place update of the decision row (append-only; R1.4 ↔ R2).';

COMMENT ON COLUMN decision_process_trace.event_ts IS
  'Time of THIS event: decision time for kind=decision; fill-landing time for kind=fill (may be a LATER walk_forward_window than the decision). Pinned, not wall-clock at write. The consumer-enforced temporal firewall is a predicate on event_ts <= in-sample boundary (R5).';

COMMENT ON COLUMN decision_process_trace.walk_forward_window IS
  'Attribution follows the DECISION: a fill row carries the decision''s window even if its event_ts lands in a later window (late-fill firewall, §14.6 / R5).';

COMMENT ON COLUMN counterfactual_ledger.code_version IS
  'Decision-Trace Telemetry model-version dimension (migration 048; requirements.md 4.1). Nullable, additive — legacy rows keep NULL. Insert-set-only (immutable after insert) per the guard. Lets forward P&L attribute per code version per walk-forward window without disturbing the 4-bin sector-ETF-excess scoring.';

COMMENT ON COLUMN counterfactual_ledger.param_version IS
  'Decision-Trace Telemetry model-version dimension (migration 048; requirements.md 4.1). Nullable, additive. Insert-set-only (immutable after insert) per the guard.';

COMMENT ON COLUMN counterfactual_ledger.walk_forward_window IS
  'Decision-Trace Telemetry model-version dimension (migration 048; requirements.md 4.1, 5.1). Nullable, additive. Insert-set-only (immutable after insert) per the guard. Distinct from the legacy/HIGH-4 measurement "window" (90d/1y/3y/5y) — this is the walk-forward training/forward window for version attribution.';

COMMIT;

-- =============================================================================
-- VERIFY: read-only catalog checks. Run after applying to confirm the migration
-- took effect. (No guard-violation probe here — that would abort under
-- ON_ERROR_STOP=1 on the shared dev DB; rejection tests belong to task 3.x.)
-- =============================================================================

-- VERIFY: decision_process_trace table exists.
SELECT schemaname, tablename
FROM pg_tables
WHERE tablename = 'decision_process_trace';

-- VERIFY: all four decision_process_trace indexes are present.
SELECT indexname
FROM pg_indexes
WHERE tablename = 'decision_process_trace'
  AND indexname IN ('idx_dpt_run', 'idx_dpt_version_window',
                    'idx_dpt_event_ts', 'idx_dpt_parent')
ORDER BY indexname;

-- VERIFY: BOTH guard triggers on decision_process_trace — the row-level
-- UPDATE/DELETE trigger AND the statement-level TRUNCATE trigger.
SELECT t.tgname AS trigger_name,
       CASE WHEN (t.tgtype & 1) = 1 THEN 'ROW' ELSE 'STATEMENT' END AS level
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'decision_process_trace'
  AND NOT t.tgisinternal
ORDER BY t.tgname;

-- VERIFY: the three new counterfactual_ledger version columns exist and are nullable.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'counterfactual_ledger'
  AND column_name IN ('code_version', 'param_version', 'walk_forward_window')
ORDER BY column_name;

-- VERIFY: the version+window index exists on counterfactual_ledger.
SELECT indexname
FROM pg_indexes
WHERE tablename = 'counterfactual_ledger'
  AND indexname = 'idx_counterfactual_version_window';

-- VERIFY: the replaced counterfactual_ledger_guard() contains the 22-column
-- immutable blacklist (030's 19 + the 3 new version columns). Inspect with:
--   \sf counterfactual_ledger_guard
