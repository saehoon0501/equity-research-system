-- First-boot initialization for the equity_research database.
-- Runs once, on first container init, against the database named in
-- POSTGRES_DB (= equity_research). Subsequent migrations are NOT
-- driven by this script — see db/README.md.
--
-- At Tier 1 (substrate), we install only the extensions the rest of
-- the system will need. The actual application schemas (Evidence Index,
-- Predictions DB, Counterfactual Ledger) land in Tier 2 (conventions)
-- per BUILD_LOG.md.

-- TimescaleDB: hypertable support for time-series tables (prices, etc.
-- in Tier 4). Not needed by Evidence Index itself but required system-wide
-- per docs/v2-final-spec.md infrastructure spine.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- gen_random_uuid() is built-in to Postgres 13+ (no extension required).
-- pgcrypto is enabled here only as a defensive fallback in case a future
-- query relies on additional pgcrypto functions (digest, hmac, etc.).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Sanity-check log line so first-boot success is visible in container logs.
DO $$
BEGIN
    RAISE NOTICE 'equity_research first-boot init complete: timescaledb + pgcrypto loaded';
END
$$;
