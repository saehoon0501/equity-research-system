-- =============================================================================
-- Migration: 023_v3_launch_readiness_log
-- Purpose:   Postgres mirror of docs/superpowers/launch-readiness-log.md so the
--            orchestrator's `/run launch-gates` view can render gate status
--            from a queryable source. Markdown log remains the canonical
--            HMAC-attested record (append-only, human-readable); this DB
--            table is a dual-write index for renderers.
--
-- Reference: src/orchestrator/v01_launch_status.py::_query_launch_readiness_log
--            queries SELECT gate_name, status, evidence_link, detail.
--
-- Schema:
--   - gate_name: TEXT (matches Appendix H names from v0.1-launch-readiness-audit.md)
--   - status: 'PASS' / 'FAIL' / 'PENDING' / 'DEFERRED'
--   - evidence_link: optional URL or file path to evidence
--   - detail: free-form note from /launch-confirm
--   - hmac_signature: HMAC-SHA256 from launch_confirm CLI (canonical_payload contract)
--   - signed_at: when /launch-confirm was invoked
--   - operator: who attested
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS launch_readiness_log (
    log_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gate_name       TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL', 'PENDING', 'DEFERRED')),
    evidence_link   TEXT,
    detail          TEXT,
    hmac_signature  TEXT NOT NULL,
    operator        TEXT NOT NULL,
    signed_at       TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Each gate_name should have exactly one row (re-attestations UPSERT).
    CONSTRAINT launch_readiness_log_gate_name_unique UNIQUE (gate_name)
);

CREATE INDEX IF NOT EXISTS idx_launch_readiness_log_status
    ON launch_readiness_log(status, signed_at DESC);

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================
SELECT to_regclass('public.launch_readiness_log') IS NOT NULL AS table_exists;
SELECT conname FROM pg_constraint WHERE conname = 'launch_readiness_log_gate_name_unique';
