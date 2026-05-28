-- =============================================================================
-- Migration: 046_evidence_documents
-- Purpose:   Phase-0 (P0-3) evidence-persistence substrate. Stores the raw
--            source-document bodies that MCP fetch tools (edgar / market_data /
--            fundamentals) retrieve at fetch time, keyed to source_uri, so a
--            downstream scorer can fetch the actual grounding passage behind an
--            evidence_index reference (faithfulness / citation P-R scoring).
--
--            Why a separate table (not a column on evidence_index):
--              - evidence_index is append-only and one row per CLAIM; a single
--                fetched document grounds many claims. Normalize the body out.
--              - Fetch happens BEFORE the agent inserts evidence_index claim
--                rows (MCP tool fetches text -> agent later INSERTs claims).
--                So the FK to evidence_index must be NULLABLE / late-bound;
--                the durable join key at fetch time is source_uri + content_hash.
--
--            Lookup model:
--              - content_hash = sha256(raw_text) — lets a re-fetch dedupe to the
--                same row instead of piling up duplicates.
--              - UNIQUE (source_uri, content_hash) — a given URI at a given
--                content state is stored once; content drift (filing amended,
--                price window re-pulled with new data) creates a new row.
--              - evidence_id FK is nullable and back-filled later if/when an
--                agent ties a specific claim row to this document. Scorers JOIN
--                on source_uri until then.
--
-- Reference: docs/superpowers/plans/2026-05-27-insight-quality-enhancement-parallel-plan.md
--            Phase 0, deliverable P0-3 (half a).
--
-- Dependencies:
--   - 001_evidence_index (evidence_index.evidence_id — FK target).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/046_evidence_documents.sql
--
-- Idempotency: safe to re-run. CREATE TABLE / INDEX IF NOT EXISTS.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: evidence_documents
-- One row per (source_uri, content_hash) fetched-document body.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence_documents (
    document_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Optional, late-bound link to the claim row this body grounds. NULL at
    -- fetch time (MCP fetches before the agent inserts evidence_index claims);
    -- back-filled later. ON DELETE SET NULL is moot (evidence_index is
    -- append-only / never deletes) but stated for intent.
    evidence_id     UUID REFERENCES evidence_index(evidence_id) ON DELETE SET NULL,

    -- The canonical identifier the body was fetched under — e.g. an SEC
    -- Archives URL, 'sec://10-K/AAPL/2024-Q4', or a synthetic market_data URI
    -- like 'marketdata://prices/AAPL/2024-01-01/2024-12-31/1d'. Same vocabulary
    -- as evidence_index.source_uri so scorers can JOIN the two.
    source_uri      TEXT NOT NULL,

    -- The fetched body. For market_data/fundamentals this is a JSON-serialized
    -- payload string; for edgar it is the filing text.
    raw_text        TEXT NOT NULL,

    -- sha256(raw_text) lowercase hex. Computed by the persisting MCP server.
    content_hash    TEXT NOT NULL,

    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Which MCP server produced this body (audit / provenance). Optional.
    fetched_by      TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- A URI at a given content state is stored once; re-fetch dedupes.
    CONSTRAINT evidence_documents_uri_hash_unique
        UNIQUE (source_uri, content_hash)
);

-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------

-- Primary scorer lookup: "give me the body behind this source_uri".
CREATE INDEX IF NOT EXISTS idx_evidence_documents_source_uri
    ON evidence_documents(source_uri);

-- Resolve by evidence_id once the link is back-filled.
CREATE INDEX IF NOT EXISTS idx_evidence_documents_evidence_id
    ON evidence_documents(evidence_id)
    WHERE evidence_id IS NOT NULL;

-- Content-addressed lookup / dedupe checks.
CREATE INDEX IF NOT EXISTS idx_evidence_documents_content_hash
    ON evidence_documents(content_hash);

COMMIT;

-- =============================================================================
-- VERIFY: run these after applying.
-- =============================================================================

-- VERIFY: table exists.
SELECT schemaname, tablename
FROM pg_tables
WHERE tablename = 'evidence_documents';

-- VERIFY: FK to evidence_index, nullable.
SELECT a.attname AS column_name, a.attnotnull AS is_not_null
FROM pg_attribute a
WHERE a.attrelid = 'evidence_documents'::regclass
  AND a.attname = 'evidence_id';

SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'evidence_documents'::regclass
  AND contype = 'f';

-- VERIFY: UNIQUE (source_uri, content_hash) + the three indexes.
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'evidence_documents'
ORDER BY indexname;
