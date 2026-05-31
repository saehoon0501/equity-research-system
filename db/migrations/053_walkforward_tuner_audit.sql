-- =============================================================================
-- Migration: 053_walkforward_tuner_audit
-- Purpose:   Inner-ring storage surface for the Walk-Forward Tuning Loop's
--            tuner-action audit (.kiro/specs/walkforward-tuning-loop).
--
--            A NEW append-only, single-table audit store
--            `walkforward_tuner_audit` — one row per tuning cycle (promote OR
--            decline; requirements.md 8.1). Each row records WHY the loop
--            promoted (or declined to promote) a candidate: the derived gate
--            metrics (P15 — derived, not asserted) and the FALSIFIABLE promotion
--            hypothesis with observable falsifiers (requirements.md 8.2). Each
--            row carries the four typed correlation keys (run_id, code_version,
--            param_version, walk_forward_window) so it joins to the model trace
--            (`decision_process_trace`, mig 048) and the outcome ledger
--            (`counterfactual_ledger`, mig 003/030) — requirements.md 8.3.
--
--            This audit surface is OWNED by walkforward-tuning-loop and is
--            SEPARATE from the decision-trace telemetry, which owns the model
--            trace only (requirements.md 8.4, P11 — each agent owns its own
--            audit surface + HG validator).
--
--            Append-only is STRICT (like `decision_process_trace`, mig 048):
--            the table has NO mutable column (design.md "Data Models →
--            Integrity": "all columns immutable after insert (no mutable
--            column)"), so UPDATE, DELETE, AND TRUNCATE are all rejected. This
--            is stricter than `counterfactual_ledger`'s append-only-with-
--            completion guard (003/030), which carves out window-close fields.
--
--            audit_id is CLIENT-minted (no DEFAULT), mirroring mig 048's
--            trace_id: the writer (task 3.2 `audit.py`) supplies the UUID so its
--            `ON CONFLICT (audit_id) DO NOTHING` doubles as an idempotency key
--            for crash/resume on the hours-long batch (requirements.md 9.1).
--
-- Reference: .kiro/specs/walkforward-tuning-loop/design.md
--              "Data Models → Physical — walkforward_tuner_audit (migration 053)",
--              "Integrity".
--            .kiro/specs/walkforward-tuning-loop/requirements.md
--              8.1, 8.2, 8.3, 8.4.
--            Pattern: mig 003 (counterfactual_ledger guard) + mig 048
--              (decision_process_trace STRICT guard — the closest precedent:
--              UPDATE/DELETE/TRUNCATE all rejected, one shared RAISE function).
--
-- Dependencies:
--   - PostgreSQL 13+ (gen_random_uuid in core; NOT used here — audit_id is
--     client-minted — but the dev container is Postgres 16).
--   - No hard FK dependency: the four correlation keys are bare typed columns
--     (matching mig 048's typing) so the audit row is writable independent of
--     whether the joined trace/ledger rows exist yet. Joinability is by value,
--     not by FK (the trace and ledger are owned by other specs, P11).
--
-- Apply (one-line psql, run from repo root):
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research -f db/migrations/053_walkforward_tuner_audit.sql
--
-- Idempotency: safe to re-run. Uses CREATE TABLE IF NOT EXISTS, CREATE INDEX
-- IF NOT EXISTS, CREATE OR REPLACE FUNCTION, and DROP TRIGGER IF EXISTS +
-- CREATE TRIGGER (Postgres has no CREATE TRIGGER IF NOT EXISTS). Forward-only:
-- no down-migration (repo convention, db/README.md).
--
-- Migration number 053 is free (049–052 + 054 taken; 053 unclaimed —
-- design.md / tasks.md note, verified in db/migrations/).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: walkforward_tuner_audit — append-only, one row per cycle.
--
-- audit_id is CLIENT-minted (NO DEFAULT): the writer supplies the UUID so its
-- ON CONFLICT (audit_id) DO NOTHING is an idempotency key on crash/resume
-- (requirements.md 9.1), mirroring decision_process_trace.trace_id (mig 048).
--
-- The four correlation keys are typed to MATCH mig 048's decision_process_trace
-- exactly (run_id UUID, code_version/param_version TEXT, walk_forward_window
-- TEXT NULL) so the value-join across the two surfaces does not break on a
-- type mismatch (requirements.md 8.3). walk_forward_window is NULL until
-- promoted (design.md Data Models: "the IS-boundary label advanced (null
-- until promoted)").
--
-- promoted / track / gate_metrics / hypothesis are NOT NULL: EVERY cycle row
-- (promote AND decline) carries the verdict, the track, the derived gate
-- metrics, and the falsifiable hypothesis (requirements.md 8.1, 8.2).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS walkforward_tuner_audit (
    audit_id            UUID PRIMARY KEY,                                  -- CLIENT-minted (no default)
    run_id              UUID NOT NULL,                                     -- correlation key
    code_version        TEXT NOT NULL,                                     -- correlation key
    param_version       TEXT NOT NULL,                                     -- the candidate's version
    walk_forward_window TEXT NULL,                                         -- IS-boundary label advanced (null until promoted)
    promoted            BOOLEAN NOT NULL,                                  -- verdict
    track               TEXT NOT NULL CHECK (track IN ('param', 'code', 'both')),
    gate_metrics        JSONB NOT NULL,                                    -- dsr, psr, min_trl_met, pbo, effective_n, lexicographic_ok (derived, P15)
    hypothesis          JSONB NOT NULL,                                    -- falsifiable statement + observable falsifiers (P15)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- Correlation-key indexes (design.md observable: "the 4 correlation keys are
-- present for joinability"). Mirrors mig 048's decision_process_trace indexes
-- so the value-join across the two surfaces is index-supported.
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_wfta_run
    ON walkforward_tuner_audit (run_id);
CREATE INDEX IF NOT EXISTS idx_wfta_version_window
    ON walkforward_tuner_audit (code_version, param_version, walk_forward_window);

-- -----------------------------------------------------------------------------
-- STRICT append-only guard for walkforward_tuner_audit.
--
-- The table has NO mutable column (design.md "Integrity": "all columns
-- immutable after insert"), so the guard is STRICT — like mig 048's
-- decision_process_trace and UNLIKE mig 003's counterfactual_ledger (which
-- carves out window-close completion fields). It rejects UPDATE, DELETE, AND
-- TRUNCATE.
--
-- The guard raises UNCONDITIONALLY on TG_OP and touches no NEW/OLD, so ONE
-- function serves both triggers: the row-level BEFORE UPDATE OR DELETE trigger
-- and the statement-level BEFORE TRUNCATE trigger. Control never reaches the
-- end of the function (RAISE always fires), so no RETURN is needed.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION walkforward_tuner_audit_guard() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'walkforward_tuner_audit is append-only — % not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

-- Row-level guard: reject UPDATE / DELETE on any row.
DROP TRIGGER IF EXISTS walkforward_tuner_audit_no_modify ON walkforward_tuner_audit;
CREATE TRIGGER walkforward_tuner_audit_no_modify
    BEFORE UPDATE OR DELETE ON walkforward_tuner_audit
    FOR EACH ROW EXECUTE FUNCTION walkforward_tuner_audit_guard();

-- Statement-level guard: reject TRUNCATE (TRUNCATE fires no row-level triggers,
-- so it needs its own BEFORE TRUNCATE FOR EACH STATEMENT trigger).
DROP TRIGGER IF EXISTS walkforward_tuner_audit_no_truncate ON walkforward_tuner_audit;
CREATE TRIGGER walkforward_tuner_audit_no_truncate
    BEFORE TRUNCATE ON walkforward_tuner_audit
    FOR EACH STATEMENT EXECUTE FUNCTION walkforward_tuner_audit_guard();

-- -----------------------------------------------------------------------------
-- Column comments
-- -----------------------------------------------------------------------------
COMMENT ON TABLE walkforward_tuner_audit IS
  'Walk-Forward Tuning Loop tuner-action audit (.kiro/specs/walkforward-tuning-loop): append-only (STRICT — no mutable column; UPDATE/DELETE/TRUNCATE rejected), one row per cycle (promote OR decline, R8.1). Records the derived gate metrics (P15) + the falsifiable promotion hypothesis (R8.2). Owned by this loop, separate from the decision-trace telemetry which owns the model trace only (R8.4, P11). Joins to decision_process_trace (mig 048) + counterfactual_ledger (mig 003/030) by the four correlation keys (R8.3).';

COMMENT ON COLUMN walkforward_tuner_audit.audit_id IS
  'CLIENT-minted UUID (no default). The writer (task 3.2 audit.py) supplies it so its ON CONFLICT (audit_id) DO NOTHING is an idempotency key on crash/resume of the hours-long batch (R9.1). Mirrors decision_process_trace.trace_id (mig 048).';

COMMENT ON COLUMN walkforward_tuner_audit.walk_forward_window IS
  'The advanced IS-boundary label (the walk-forward window correlation key). NULL until promoted — a decline cycle advances no boundary (design.md Data Models). Typed TEXT NULL to match decision_process_trace.walk_forward_window (mig 048) for the value-join (R8.3).';

COMMENT ON COLUMN walkforward_tuner_audit.gate_metrics IS
  'JSONB: dsr, psr, min_trl_met, pbo, effective_n, lexicographic_ok — DERIVED gate metrics (P15: derived, not asserted probabilities; R8.2). NOT NULL: present on both promote and decline.';

COMMENT ON COLUMN walkforward_tuner_audit.hypothesis IS
  'JSONB: the FALSIFIABLE promotion-rationale statement + observable falsifiers (P15; R8.2). NOT NULL: present on both promote and decline. Validated by the HG validator (task 3.3) before release.';

COMMIT;

-- =============================================================================
-- VERIFY: read-only catalog checks. Run after applying to confirm the migration
-- took effect. (No guard-violation probe here — that would abort under
-- ON_ERROR_STOP=1 on the shared dev DB; rejection tests belong to task 4.3,
-- integration_live — mirrors mig 048's VERIFY-block convention.)
-- =============================================================================

-- VERIFY: walkforward_tuner_audit table exists.
SELECT schemaname, tablename
FROM pg_tables
WHERE tablename = 'walkforward_tuner_audit';

-- VERIFY: all 10 columns present with the expected types / nullability.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'walkforward_tuner_audit'
ORDER BY ordinal_position;

-- VERIFY: both correlation-key indexes are present.
SELECT indexname
FROM pg_indexes
WHERE tablename = 'walkforward_tuner_audit'
  AND indexname IN ('idx_wfta_run', 'idx_wfta_version_window')
ORDER BY indexname;

-- VERIFY: BOTH guard triggers — the row-level UPDATE/DELETE trigger AND the
-- statement-level TRUNCATE trigger — are wired to walkforward_tuner_audit.
SELECT t.tgname AS trigger_name,
       CASE WHEN (t.tgtype & 1) = 1 THEN 'ROW' ELSE 'STATEMENT' END AS level
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'walkforward_tuner_audit'
  AND NOT t.tgisinternal
ORDER BY t.tgname;

-- VERIFY: the track CHECK constraint is present.
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'walkforward_tuner_audit'::regclass
  AND contype = 'c'
ORDER BY conname;
