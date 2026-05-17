-- =============================================================================
-- Migration: 018_v3_forced_review_blocked_pending
-- Purpose:   Spec Section 4.5 Q5 line 536 mandates "No-op default BLOCKED" —
--            forced_review->>'operator_decision' must be a TERMINAL value
--            (reaffirm / revise_with_rationale / cut). Migration 010's CHECK
--            permits 'pending' which is the NULL state, not a decision.
--
--            Strategy (option b — sidecar table, preserves anchor_drift_checks
--            append-only invariant): create
--            `anchor_drift_review_decisions` keyed by check_id with FK to
--            `anchor_drift_checks`. Row absence = pending; row presence =
--            decision committed.
--
--            The original CHECK on anchor_drift_checks.forced_review is left
--            in place for backward compatibility; new writers SHOULD set
--            forced_review.operator_decision = NULL until a decision is made,
--            then INSERT a row into anchor_drift_review_decisions.
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 4.5 Q5 lines 530-540.
--
-- Dependencies:
--   - 010_v3_drift_detection (anchor_drift_checks table + check_id PK)
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U equity_research_admin -d equity_research \
--        -f db/migrations/018_v3_forced_review_blocked_pending.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS anchor_drift_review_decisions (
    check_id                    UUID PRIMARY KEY
                                  REFERENCES anchor_drift_checks(check_id)
                                  ON DELETE RESTRICT,

    -- Terminal-only enum: pending is encoded by row absence, not by enum value.
    operator_decision           TEXT NOT NULL
                                  CHECK (operator_decision IN
                                    ('reaffirm', 'revise_with_rationale', 'cut')),

    operator_acknowledged_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    operator_id                 TEXT NOT NULL DEFAULT 'operator',

    -- Free-text rationale required when revising or cutting (CHECK ensures
    -- non-empty for those branches).
    rationale                   TEXT,

    parameters_version          UUID,                      -- FK to parameters.version_id
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT anchor_drift_review_rationale_required
        CHECK (operator_decision = 'reaffirm'
               OR (rationale IS NOT NULL AND length(trim(rationale)) > 0))
);

CREATE INDEX IF NOT EXISTS idx_anchor_drift_review_decision_committed_at
    ON anchor_drift_review_decisions(operator_acknowledged_at DESC);

CREATE INDEX IF NOT EXISTS idx_anchor_drift_review_decision_kind
    ON anchor_drift_review_decisions(operator_decision);

-- Append-only: once a decision is committed it is immutable. Reversals are
-- implemented by writing a new anchor_drift_checks row + decision.
CREATE OR REPLACE FUNCTION anchor_drift_review_decisions_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'anchor_drift_review_decisions is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS anchor_drift_review_decisions_no_modify
    ON anchor_drift_review_decisions;
CREATE TRIGGER anchor_drift_review_decisions_no_modify
BEFORE UPDATE OR DELETE ON anchor_drift_review_decisions
FOR EACH ROW EXECUTE FUNCTION anchor_drift_review_decisions_guard();

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

SELECT schemaname, tablename FROM pg_tables
WHERE tablename = 'anchor_drift_review_decisions';

SELECT indexname, tablename FROM pg_indexes
WHERE tablename = 'anchor_drift_review_decisions'
ORDER BY indexname;

SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'anchor_drift_review_decisions'::regclass
  AND contype IN ('c', 'f', 'p')
ORDER BY conname;

SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'anchor_drift_review_decisions' AND NOT t.tgisinternal;
