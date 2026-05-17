-- =============================================================================
-- Migration: 019_v3_first_acquired_nullable
-- Purpose:   Drop NOT NULL on `positions.first_acquired`. Schwab's positions
--            endpoint does NOT return per-lot acquisition dates; we can only
--            infer first_acquired by replaying position_history. Until the
--            history replay backfills, the column must be nullable.
--
--            Long-term-capital-gains math (1-year holding test) defers until
--            the column is backfilled — callers should treat NULL as "unknown
--            holding period" and fall back to "short-term" when computing tax
--            cost (conservative).
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 4.6 (broker MCP) + Section 8.1 (cost-basis deferral).
--
-- Dependencies:
--   - 007_v3_watchlist_positions (defines positions table)
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U equity_research_admin -d equity_research \
--        -f db/migrations/019_v3_first_acquired_nullable.sql
--
-- Idempotency: safe to re-run (ALTER COLUMN DROP NOT NULL is no-op when
-- already nullable).
-- =============================================================================

BEGIN;

ALTER TABLE positions
    ALTER COLUMN first_acquired DROP NOT NULL;

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

SELECT column_name, is_nullable, data_type
FROM information_schema.columns
WHERE table_name = 'positions' AND column_name = 'first_acquired';
