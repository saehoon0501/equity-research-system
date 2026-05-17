-- =====================================================================
-- Migration 031: analyst_briefs TTL + invalidation columns
-- Drift-fix Phase 3 Step 7 (2026-05-17)
--
-- Purpose
-- -------
-- Add cache-lifecycle columns to analyst_briefs so the quarterly-stable
-- layer (Helmer Powers, capital-allocation grades, F-Score, Z'', WACC
-- components, DCF bear/base/bull anchors) can be reused across runs
-- instead of re-derived every /research-company invocation. The brief
-- itself is the unit of caching; pm-supervisor + cdd-lead consult the
-- TTL fields before triggering a full re-derivation.
--
-- Pre-fix behaviour: every /research-company run re-derived the slow
-- layer from scratch, contributing to run-to-run drift (see audit memo
-- 2026-05-17). yfinance_cache (migration 029) already proves the TTL
-- pattern; this migration extends it to the synthesised analytical
-- layer.
--
-- Stale-detection: invalidated_by_event taxonomy lets event-trigger
-- code (daily-monitor materiality classifier, M&A 8-K parser) mark
-- specific briefs invalidated on new filings without nuking the entire
-- ticker's brief history. The append-only history is preserved; the
-- linked-list (prior_brief_id) and warm-start logic are unaffected.
--
-- Schema-version stamp lives in evaluator.md HG-32 / pm-supervisor.md;
-- this migration introduces the columns the gates depend on.
-- =====================================================================

BEGIN;

ALTER TABLE analyst_briefs
    ADD COLUMN IF NOT EXISTS cached_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS ttl_days INTEGER NOT NULL DEFAULT 90,
    ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS invalidated_by_event TEXT NULL
        CHECK (invalidated_by_event IN (
            'new_10k',           -- annual filing supersedes prior fundamentals
            'new_10q',           -- quarterly filing supersedes
            'material_8k',       -- 8-K with material event (M&A, restatement, etc.)
            'cap_alloc_event',   -- buyback announcement, dividend change, large M&A
            'guidance_revision', -- forward-guidance update
            'manual'             -- operator-triggered
        )),
    ADD COLUMN IF NOT EXISTS invalidated_by_event_ref TEXT NULL;
        -- Optional pointer to the triggering event (e.g., 8-K accession
        -- number, news item URL, operator note). Free-text; not enum-
        -- constrained because event-trigger sources vary.

-- Constraint: invalidated_at and invalidated_by_event are paired.
-- Either both NULL (brief still active) or both NOT NULL (invalidated).
-- ttl_days is always > 0 (no immediately-expired briefs).
ALTER TABLE analyst_briefs
    ADD CONSTRAINT analyst_briefs_invalidation_pair CHECK (
        (invalidated_at IS NULL AND invalidated_by_event IS NULL)
        OR
        (invalidated_at IS NOT NULL AND invalidated_by_event IS NOT NULL)
    ),
    ADD CONSTRAINT analyst_briefs_ttl_positive CHECK (ttl_days > 0);

-- Partial index for the hot path: "most recent active brief for ticker/type".
-- The warm-start CTE in /research-company.md §2 step 3 uses this index
-- to find co-emitted pairs without scanning invalidated rows.
CREATE INDEX IF NOT EXISTS analyst_briefs_active_lookup
    ON analyst_briefs(ticker, brief_type, created_at DESC)
    WHERE invalidated_at IS NULL;

-- View: active briefs only (convenience for callers).
-- Combines: not invalidated AND within TTL window from cached_at.
CREATE OR REPLACE VIEW analyst_briefs_active AS
SELECT *
FROM analyst_briefs
WHERE invalidated_at IS NULL
  AND (cached_at + (ttl_days || ' days')::interval) > now();

-- Function: mark briefs invalidated by a triggering event.
-- Idempotent: if a brief is already invalidated, this is a no-op.
-- Caller: daily-monitor materiality classifier (new 10-K/10-Q/material 8-K),
-- operator via /resolve-outcomes, /research-company orchestrator on
-- detection of brief.cached_at + ttl_days < now() (lazy expiry).
CREATE OR REPLACE FUNCTION mark_briefs_invalidated(
    p_ticker TEXT,
    p_event TEXT,
    p_event_ref TEXT DEFAULT NULL,
    p_brief_types TEXT[] DEFAULT ARRAY['quantitative','strategic']::TEXT[]
) RETURNS TABLE(brief_id UUID, brief_type TEXT, ticker TEXT) AS $$
BEGIN
    -- Validate event taxonomy (CHECK constraint catches it too, but
    -- fail fast with a clearer error from the function).
    IF p_event NOT IN ('new_10k','new_10q','material_8k','cap_alloc_event','guidance_revision','manual') THEN
        RAISE EXCEPTION 'invalid event %; must be in canonical taxonomy', p_event;
    END IF;

    RETURN QUERY
    UPDATE analyst_briefs ab
       SET invalidated_at = now(),
           invalidated_by_event = p_event,
           invalidated_by_event_ref = p_event_ref
     WHERE ab.ticker = p_ticker
       AND ab.brief_type = ANY(p_brief_types)
       AND ab.invalidated_at IS NULL
    RETURNING ab.brief_id, ab.brief_type, ab.ticker;
END;
$$ LANGUAGE plpgsql;

COMMENT ON COLUMN analyst_briefs.cached_at IS
    'When this brief became the active cache entry (defaults to created_at on insert; can be refreshed by guidance-revision invalidation).';
COMMENT ON COLUMN analyst_briefs.ttl_days IS
    'TTL in days from cached_at after which the brief is considered stale even without an explicit invalidation event. Default 90d for core_fundamental; orchestrator may override per-tier.';
COMMENT ON COLUMN analyst_briefs.invalidated_at IS
    'When invalidation fired; NULL means brief is active subject to TTL.';
COMMENT ON COLUMN analyst_briefs.invalidated_by_event IS
    'Canonical event taxonomy (enum) — required when invalidated_at is set.';
COMMENT ON COLUMN analyst_briefs.invalidated_by_event_ref IS
    'Free-text pointer to the triggering event (8-K accession, news URL, operator note).';
COMMENT ON VIEW analyst_briefs_active IS
    'Briefs that are neither explicitly invalidated nor past their TTL. Use this view for warm-start CTE in /research-company.md §2 step 3 instead of querying analyst_briefs directly.';
COMMENT ON FUNCTION mark_briefs_invalidated IS
    'Bulk-invalidate active briefs for a ticker by event. Idempotent; returns the rows that were invalidated by this call. Caller: daily-monitor materiality classifier, operator via /resolve-outcomes, orchestrator on lazy-expiry detection.';

COMMIT;
