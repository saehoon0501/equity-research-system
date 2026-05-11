-- Migration 029: yfinance write-through cache
-- Reduces redundant API calls during warm-start CDD reruns.
-- Skips writes for ticker_not_found payloads.

CREATE TABLE IF NOT EXISTS yfinance_cache (
    endpoint TEXT NOT NULL,
    ticker TEXT NOT NULL,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ttl_seconds INTEGER NOT NULL,
    PRIMARY KEY (endpoint, ticker)
);

CREATE INDEX IF NOT EXISTS idx_yfinance_cache_fetched_at
    ON yfinance_cache (fetched_at DESC);

COMMENT ON TABLE yfinance_cache IS
    'Write-through cache for yfinance MCP endpoints. Stale rows (now - fetched_at > ttl_seconds) are recomputed on next call. Cleanup is lazy; no scheduled GC required for v0.5.';
