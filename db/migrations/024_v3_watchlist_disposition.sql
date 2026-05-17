-- =============================================================================
-- Migration: 024_v3_watchlist_disposition
-- Purpose:   Allow WATCH rows in `watchlist` (currently the table assumes
--            ADDED-and-HELD names). Per operator decision 2026-05-04, the
--            daily pipeline needs to track names that are researched but not
--            held — e.g., PLTR after the 2026-05-01 /research-company
--            invocation came back WATCH (P50 fair value $74; current $139;
--            sub-threshold for ADD).
--
-- Effect:    Adds a `disposition` column with three valid values:
--              - HELD       : actual position; default; legacy semantics
--              - WATCH      : researched, monitored, no current position
--              - TRIGGERED  : monitored name where price/event has hit the
--                             entry trigger from /research-company; awaiting
--                             operator confirmation to convert to HELD
--
--            Existing watchlist rows default to HELD on column add. New WATCH
--            rows still require HMAC-signed pillars + projections per the
--            HMAC contract — the disposition field is semantic, not a way to
--            bypass auditability. CDD outputs ARE thesis pillars even for
--            WATCH; we just track them without claiming an active position.
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 4.6 (P5 watchlist) + first operational /research-company
--            invocation 2026-05-01 (PLTR case).
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

ALTER TABLE watchlist
    ADD COLUMN IF NOT EXISTS disposition TEXT NOT NULL DEFAULT 'HELD'
    CHECK (disposition IN ('HELD', 'WATCH', 'TRIGGERED'));

CREATE INDEX IF NOT EXISTS idx_watchlist_disposition
    ON watchlist(disposition, ticker);

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name='watchlist' AND column_name='disposition';

SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'watchlist'::regclass
  AND pg_get_constraintdef(oid) LIKE '%disposition%';
