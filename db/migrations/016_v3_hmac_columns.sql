-- =============================================================================
-- Migration: 016_v3_hmac_columns
-- Purpose:   Add dedicated hmac_signature + signed_at columns to:
--              - peak_pain_archetypes  (HMAC was previously embedded in `notes`
--                                        as a `[hmac=...;alg=sha256] ...` prefix
--                                        — moved to its own column for clean
--                                        column-stored verification)
--              - premortem             (HMAC was previously stored as a key
--                                        inside llm_assist_metadata JSONB —
--                                        moved to its own column)
--
--            Both columns are NOT NULL with a temporary default ('') so the
--            migration is non-disruptive for existing rows; application layer
--            backfills the signature on next write. The default is documented
--            for drop-after-backfill at v0.5+.
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 5 Q1 (audit-chain HMAC) + Section 6 Q5 (anchor-drift
--            HMAC). Each module's HMAC scope is independent (PEAK_PAIN_HMAC_KEY
--            vs PREMORTEM_HMAC_SECRET vs WATCHLIST_HMAC_SECRET vs
--            AUDIT_HMAC_KEY) but ALL share the canonical-payload contract
--            implemented in src/audit_trail/hmac_verify.py.
--
-- Dependencies:
--   - 011_v3_counterfactual_retrieval (peak_pain_archetypes)
--   - 012_v3_premortem (premortem)
--   - PostgreSQL 13+
--
-- How to apply:
--   PGPASSWORD=... psql -h 127.0.0.1 -p 5432 -U equity_research_admin \
--     -d equity_research -v ON_ERROR_STOP=1 \
--     -f db/migrations/016_v3_hmac_columns.sql
--
-- Idempotency: safe to re-run (ADD COLUMN IF NOT EXISTS / DROP IF EXISTS).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- peak_pain_archetypes — column-stored HMAC signature
-- -----------------------------------------------------------------------------
ALTER TABLE peak_pain_archetypes
    ADD COLUMN IF NOT EXISTS hmac_signature TEXT NOT NULL DEFAULT '';

ALTER TABLE peak_pain_archetypes
    ADD COLUMN IF NOT EXISTS signed_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

COMMENT ON COLUMN peak_pain_archetypes.hmac_signature IS
    'HMAC-SHA256 hex over canonical_payload_dict of the row payload, signed '
    'with PEAK_PAIN_HMAC_KEY. See src/audit_trail/hmac_verify.py for canonical '
    'contract. Default '''' will be dropped after v0.5 backfill.';

COMMENT ON COLUMN peak_pain_archetypes.signed_at IS
    'Timestamp at which hmac_signature was computed; allows operator to detect '
    'stale signatures vs last_updated_at when rotating PEAK_PAIN_HMAC_KEY.';

-- -----------------------------------------------------------------------------
-- premortem — column-stored HMAC signature (was inside llm_assist_metadata)
-- -----------------------------------------------------------------------------
ALTER TABLE premortem
    ADD COLUMN IF NOT EXISTS hmac_signature TEXT NOT NULL DEFAULT '';

ALTER TABLE premortem
    ADD COLUMN IF NOT EXISTS signed_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

COMMENT ON COLUMN premortem.hmac_signature IS
    'HMAC-SHA256 hex over canonical_payload_dict of the operator-authored '
    'JSONB blobs (operator_imagined_failure_modes + thesis_pillars_revisited), '
    'signed with PREMORTEM_HMAC_SECRET. Per v3 spec Section 5 Q1. Default '''' '
    'will be dropped after v0.5 backfill.';

COMMENT ON COLUMN premortem.signed_at IS
    'Timestamp at which hmac_signature was computed; allows secret-rotation '
    'tracking against created_at.';

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

-- Columns exist on both tables.
SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name IN ('peak_pain_archetypes', 'premortem')
  AND column_name IN ('hmac_signature', 'signed_at')
ORDER BY table_name, column_name;

-- Comments are attached.
SELECT c.relname AS table_name,
       a.attname AS column_name,
       pg_catalog.col_description(c.oid, a.attnum) AS comment
FROM pg_class c
JOIN pg_attribute a ON a.attrelid = c.oid
WHERE c.relname IN ('peak_pain_archetypes', 'premortem')
  AND a.attname IN ('hmac_signature', 'signed_at')
  AND a.attnum > 0
ORDER BY c.relname, a.attname;
