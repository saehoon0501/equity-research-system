-- =============================================================================
-- Migration: 026_latest_actuals
-- Purpose:   Channel 2 anchor-drift outcome divergence (v3 spec §4.5 Q5)
--            requires latest quarterly fundamentals per watchlist ticker.
--            The original implementation imported a non-existent
--            ``mcp_clients.fundamentals`` Python package and silently
--            returned no_actuals. This migration creates a Postgres-backed
--            cache populated by an operator-invoked refresh skill that
--            calls mcp__fundamentals at the Claude tool layer.
--
--            Channel 2's `_default_fundamentals_fn` now queries this table
--            instead of relying on a Python-importable client.
--
-- Schema:    latest_actuals(
--              ticker            TEXT PRIMARY KEY,
--              period_end        DATE NOT NULL,
--              revenue           NUMERIC(20,2),     -- TTM USD
--              gross_margin      NUMERIC(6,4),      -- as fraction (0.45 = 45%)
--              fcf               NUMERIC(20,2),     -- TTM USD
--              source            TEXT NOT NULL,     -- e.g. 'sharadar' / 'edgar_xbrl'
--              last_updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
--            )
--
-- Dependencies: none
--
-- How to apply:
--   psql -f db/migrations/026_latest_actuals.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

CREATE TABLE IF NOT EXISTS latest_actuals (
    ticker          TEXT PRIMARY KEY,
    period_end      DATE NOT NULL,
    revenue         NUMERIC(20,2),
    gross_margin    NUMERIC(6,4),
    fcf             NUMERIC(20,2),
    source          TEXT NOT NULL DEFAULT 'edgar_xbrl',
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS latest_actuals_period_end_idx
    ON latest_actuals (period_end);

COMMENT ON TABLE latest_actuals IS
    'Trailing-twelve-month canonical fundamentals per watchlist ticker, '
    'populated by /refresh-actuals (calls mcp__fundamentals or mcp__edgar). '
    'Read by anchor_drift.channel_2_outcome_divergence per spec §4.5 Q5.';
