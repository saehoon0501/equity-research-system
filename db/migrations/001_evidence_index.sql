-- =============================================================================
-- Migration: 001_evidence_index
-- Purpose:   Create the Evidence Index table — the load-bearing data substrate
--            under Path A (per v2-final §4.2.5). Every claim made by every
--            agent populates a row here; the mechanical contamination check
--            validates against this index before output release.
--
-- Reference: .claude/references/evidence-index-schema.md
--
-- Dependencies:
--   - PostgreSQL 13+ (gen_random_uuid() ships in core 13+; pgcrypto extension
--     also provides it on older versions — we rely on the core function here).
--   - pgcrypto: not strictly required on PG13+, but enabled in the dev image
--     and harmless if present.
--   - timescaledb: NOT used by this migration. evidence_index is a normal
--     Postgres table, not a hypertable.
--
-- How to apply (one-line psql, run from repo root):
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research -f db/migrations/001_evidence_index.sql
--
-- Idempotency: safe to re-run. Uses CREATE ... IF NOT EXISTS for table and
-- indexes, CREATE OR REPLACE FUNCTION for the trigger function, and
-- DROP TRIGGER IF EXISTS + CREATE TRIGGER for the trigger (Postgres has no
-- CREATE TRIGGER IF NOT EXISTS).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: evidence_index
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence_index (
    evidence_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id             TEXT NOT NULL,           -- 'company-deep-dive', 'bear-case', etc.
    agent_run_id         UUID NOT NULL,           -- groups all claims from one agent invocation
    claim_text           TEXT NOT NULL,           -- the actual claim sentence
    claim_type           TEXT NOT NULL CHECK (claim_type IN
                            ('numerical', 'qualitative', 'prediction', 'dated_fact')),
    source_uri           TEXT NOT NULL,           -- URL or filing reference (e.g., 'sec://10-K/AAPL/2024-Q4')
    source_date          DATE NOT NULL,           -- date of source document (filing date, etc.)
    source_quality_tier  SMALLINT NOT NULL CHECK (source_quality_tier IN (1, 2, 3, 4)),
                                                  -- 1=primary filing/regulatory
                                                  -- 2=company IR/transcript
                                                  -- 3=sell-side/established financial press
                                                  -- 4=retail/blog
    surfaced_date        DATE NOT NULL DEFAULT CURRENT_DATE,
    related_position_id  UUID,                    -- optional FK; null for non-position research
    related_thesis_id    UUID,                    -- optional FK; null for ad-hoc claims
    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    storage_tier         TEXT NOT NULL DEFAULT 'hot'
                            CHECK (storage_tier IN ('hot', 'warm', 'cold'))
);

-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_evidence_agent_run
    ON evidence_index(agent_run_id);

CREATE INDEX IF NOT EXISTS idx_evidence_position
    ON evidence_index(related_position_id)
    WHERE related_position_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_evidence_source_date
    ON evidence_index(source_date);

CREATE INDEX IF NOT EXISTS idx_evidence_surfaced
    ON evidence_index(surfaced_date);

-- -----------------------------------------------------------------------------
-- Append-only enforcement
--
-- The Evidence Index is append-only. Storage tier transitions (hot → warm →
-- cold) happen via a separate "shadow" mechanism (move row to a _warm
-- partition), not by mutating the original row. This trigger blocks any
-- UPDATE or DELETE attempted directly against evidence_index.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION prevent_modify() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'evidence_index is append-only — UPDATE/DELETE not permitted';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS evidence_index_no_update ON evidence_index;
CREATE TRIGGER evidence_index_no_update
BEFORE UPDATE OR DELETE ON evidence_index
FOR EACH ROW EXECUTE FUNCTION prevent_modify();

COMMIT;

-- =============================================================================
-- VERIFY: run these after applying to confirm the migration took effect.
-- Each query should return the expected row(s); zero rows = migration failed.
-- =============================================================================

-- VERIFY: evidence_index table exists in the public schema.
SELECT schemaname, tablename
FROM pg_tables
WHERE tablename = 'evidence_index';

-- VERIFY: all four indexes are present.
SELECT indexname, tablename
FROM pg_indexes
WHERE tablename = 'evidence_index'
  AND indexname IN (
      'idx_evidence_agent_run',
      'idx_evidence_position',
      'idx_evidence_source_date',
      'idx_evidence_surfaced'
  )
ORDER BY indexname;

-- VERIFY: append-only trigger is wired to evidence_index.
SELECT t.tgname AS trigger_name,
       c.relname AS table_name,
       p.proname AS function_name
FROM pg_trigger t
JOIN pg_class c    ON c.oid = t.tgrelid
JOIN pg_proc  p    ON p.oid = t.tgfoid
WHERE c.relname = 'evidence_index'
  AND t.tgname  = 'evidence_index_no_update'
  AND NOT t.tgisinternal;
