-- =============================================================================
-- Migration: 034_run_parameters_snapshot
-- Purpose:   Per-run parameter snapshot table. Each /research-company run
--            captures the resolved parameter values (post-§1.5 single-txn
--            REPEATABLE READ read of parameters_active) as one row here.
--            Downstream tables (recommendation_outcomes, override_outcomes,
--            debate_consensus_history, calibration_test_results, and the
--            other 8 tables carrying parameters_version columns per Phase 0
--            audit) reference this row via run_parameters_snapshot_id
--            instead of pinning a single parameters.version_id — because a
--            single run consumes N parameters across namespaces and the
--            single-UUID model can't represent the snapshot.
--
-- Reference: /review-me v7-final convergence 2026-05-18.
--            Audit checklist: docs/superpowers/audits/2026-05-18-parameter-externalization-phase3-audit-checklist.md
--
-- Schema choice:
--   - One row per /research-company run.
--   - `parameters_version_max` is the largest version_id seen in the
--     snapshot rowset — convenience pointer for ad-hoc audits, but the
--     authoritative content is `effective_parameters_jsonb`.
--   - `effective_parameters_jsonb` is the resolved key→value map after the
--     snapshot SELECT; this is what every subagent's PARAMETERS_USED header
--     was composed from.
--   - `effective_parameters_hash` is sha256 of the canonical JSON
--     serialization of effective_parameters_jsonb — used for fast equality
--     comparisons (sweep deduplication, audit replay verification).
--   - `tag` records the tag value used (NULL for production runs, sweep_uuid
--     for sweep test runs). Audit-clarity: post-hoc readers can distinguish
--     production vs sweep at a glance.
--   - `tag_signature` records the HMAC sig over (tag, tag_issued_at_unix);
--     present only when tag is non-NULL. Validated by the PreToolUse hook
--     at scripts/research_company_as_of_tag_gate.sh before the run starts.
--   - `tag_issued_at_unix` is the operator-supplied issuance timestamp; the
--     PreToolUse hook enforces a 600-second validity window vs hook fire time.
--
-- Dependencies:
--   - 004_v3_parameters (parameters table that snapshot reads from).
--   - 033_parameters_seed_research_company (tag column + filtered view).
--
-- Idempotency: safe to re-run. CREATE TABLE IF NOT EXISTS, CREATE INDEX
--   IF NOT EXISTS, CREATE OR REPLACE FUNCTION, DROP TRIGGER IF EXISTS.
--
-- Append-only: state-table guard rejects DELETE; UPDATE permitted only on
-- a narrow whitelist (run_ended_at, run_status) since the snapshot itself
-- is immutable.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS run_parameters_snapshot (
    run_id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    ticker                       TEXT NOT NULL,
    run_started_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_ended_at                 TIMESTAMPTZ,                  -- mutable; set at run end

    -- Largest parameters.version_id present in the snapshot rowset.
    -- Convenience pointer; authoritative content is effective_parameters_jsonb.
    parameters_version_max       UUID NOT NULL,

    -- Full resolved snapshot (key→value object).
    effective_parameters_jsonb   JSONB NOT NULL,

    -- sha256 of canonical-JSON-serialized effective_parameters_jsonb.
    effective_parameters_hash    TEXT NOT NULL,

    -- Tag this run used. NULL = production. Non-NULL = sweep test row set.
    tag                          TEXT,

    -- HMAC sig and issuance timestamp for tagged runs (NULL when tag IS NULL).
    -- Validated by PreToolUse hook before run dispatch.
    tag_signature                TEXT,
    tag_issued_at_unix           BIGINT,

    -- Final disposition of the run. Set at termination.
    -- Canonical run_status values (source of truth for the symmetric terminal
    -- UPDATEs across /research-company orchestrator paths — per /review-me
    -- post-apply iteration 3 defect #5):
    --   in-flight (transient — NULL until run terminates):
    --     NULL                            — orchestrator §1.5 INSERT default
    --   terminal (set by orchestrator at end-of-run):
    --     'completed'                     — happy path, §6.5
    --     'rejected'                      — evaluator HG fail OR contamination
    --                                        check fail, §4.5
    --     'failed_INV-1'                  — §1.5 invariant validator failure
    --     'failed_INV-3'                  — §1.5 invariant validator failure
    --     'failed_evaluator_dispatch'     — §4.5 dispatch infra failure
    -- TEXT (not enum) so future status values can land via skill-markdown
    -- edits alone without a column-type migration. If the list grows beyond
    -- ~10 values, consider promoting to a CHECK constraint to prevent typos.
    run_status                   TEXT,                         -- mutable; see canonical list above

    created_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- If a tag is present, both signature and issued_at must be present.
    CONSTRAINT run_parameters_snapshot_tag_attestation
        CHECK ((tag IS NULL AND tag_signature IS NULL AND tag_issued_at_unix IS NULL)
            OR (tag IS NOT NULL AND tag_signature IS NOT NULL AND tag_issued_at_unix IS NOT NULL))
);

-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_run_parameters_snapshot_ticker_started
    ON run_parameters_snapshot(ticker, run_started_at DESC);

CREATE INDEX IF NOT EXISTS idx_run_parameters_snapshot_hash
    ON run_parameters_snapshot(effective_parameters_hash);

-- "Show all sweep runs under a given tag."
CREATE INDEX IF NOT EXISTS idx_run_parameters_snapshot_tag
    ON run_parameters_snapshot(tag, run_started_at DESC)
    WHERE tag IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_run_parameters_snapshot_parameters_version_max
    ON run_parameters_snapshot(parameters_version_max);

-- -----------------------------------------------------------------------------
-- State-table guard.
-- All columns immutable after insert EXCEPT run_ended_at and run_status (the
-- two columns set at run termination).
-- DELETE blocked entirely.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION run_parameters_snapshot_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'run_parameters_snapshot: DELETE not permitted';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF NEW.run_id                       IS DISTINCT FROM OLD.run_id
           OR NEW.ticker                    IS DISTINCT FROM OLD.ticker
           OR NEW.run_started_at            IS DISTINCT FROM OLD.run_started_at
           OR NEW.parameters_version_max    IS DISTINCT FROM OLD.parameters_version_max
           OR NEW.effective_parameters_jsonb IS DISTINCT FROM OLD.effective_parameters_jsonb
           OR NEW.effective_parameters_hash IS DISTINCT FROM OLD.effective_parameters_hash
           OR NEW.tag                       IS DISTINCT FROM OLD.tag
           OR NEW.tag_signature             IS DISTINCT FROM OLD.tag_signature
           OR NEW.tag_issued_at_unix        IS DISTINCT FROM OLD.tag_issued_at_unix
           OR NEW.created_at                IS DISTINCT FROM OLD.created_at
        THEN
            RAISE EXCEPTION 'run_parameters_snapshot: only run_ended_at and run_status are mutable post-insert';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS run_parameters_snapshot_state_guard ON run_parameters_snapshot;
CREATE TRIGGER run_parameters_snapshot_state_guard
BEFORE UPDATE OR DELETE ON run_parameters_snapshot
FOR EACH ROW EXECUTE FUNCTION run_parameters_snapshot_guard();

COMMIT;

-- =============================================================================
-- VERIFY: run these after applying.
-- =============================================================================

SELECT schemaname, tablename FROM pg_tables WHERE tablename = 'run_parameters_snapshot';

SELECT indexname, tablename FROM pg_indexes
WHERE tablename = 'run_parameters_snapshot' ORDER BY indexname;

SELECT t.tgname AS trigger_name, c.relname AS table_name
FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'run_parameters_snapshot' AND NOT t.tgisinternal
ORDER BY t.tgname;

SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'run_parameters_snapshot'::regclass
ORDER BY conname;
