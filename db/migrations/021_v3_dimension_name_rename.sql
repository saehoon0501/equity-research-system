-- =============================================================================
-- Migration: 021_v3_dimension_name_rename
-- Purpose:   Update the deployed CHECK constraint on
--            regime_classification_history.dimension_name to reflect the
--            v0.1 rename of dim 2: 'cycle_ntfs' → 'cycle_2y3m_slope'.
--
--            Migration 005 source-of-truth was edited to use the new name
--            (the implementation uses DGS2 - DGS3MO CMT slope, not the
--            Engstrom-Sharpe NTFS), but the CHECK constraint was applied
--            from the pre-rename version of 005. This migration brings the
--            deployed schema in line with the source.
--
--            Deployed has: cycle_ntfs (legacy)
--            Source has:   cycle_2y3m_slope (canonical)
--            Net effect:   any INSERT with dimension_name='cycle_2y3m_slope'
--                          would fail the deployed CHECK without this fix.
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 4.1 dimension #2 (operator-locked rename per Remediation Y).
--            BUILD_LOG.md notes the dim2 rename + Engstrom-Sharpe NTFS deferral.
--
-- Backfill:  No deployed rows yet (regime_classification_history is empty
--            at v0.1 launch readiness). If this migration runs against a
--            populated table, the safety net at the bottom WILL detect
--            legacy rows and instruct operator to backfill before retry.
--
-- Dependencies:
--   - 005_v3_regime (creates the table + the legacy CHECK we're replacing).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U equity_research_admin -d equity_research \
--        -v ON_ERROR_STOP=1 \
--        -f db/migrations/021_v3_dimension_name_rename.sql
--
-- Idempotency: safe to re-run. DROP CONSTRAINT IF EXISTS pattern.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Safety net: refuse to drop the legacy CHECK if there are still rows using
-- the old 'cycle_ntfs' name. Forces operator to backfill explicitly.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    legacy_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO legacy_count
    FROM regime_classification_history
    WHERE dimension_name = 'cycle_ntfs';

    IF legacy_count > 0 THEN
        RAISE EXCEPTION 'Migration 021 aborted: % rows in regime_classification_history still use legacy dimension_name=cycle_ntfs. Backfill them to cycle_2y3m_slope before applying this migration: UPDATE regime_classification_history SET dimension_name=''cycle_2y3m_slope'' WHERE dimension_name=''cycle_ntfs'';', legacy_count;
    END IF;
END;
$$;

-- -----------------------------------------------------------------------------
-- Drop the legacy CHECK and add the canonical one.
-- We have to query the deployed name dynamically because Postgres auto-named
-- it (pg_constraint.conname), which differs from a named constraint.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    cname TEXT;
BEGIN
    -- Find the existing CHECK that contains 'cycle_ntfs' (legacy) — there should be exactly one.
    SELECT conname INTO cname
    FROM pg_constraint
    WHERE conrelid = 'regime_classification_history'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%cycle_ntfs%';

    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE regime_classification_history DROP CONSTRAINT %I', cname);
        RAISE NOTICE 'Dropped legacy constraint: %', cname;
    ELSE
        RAISE NOTICE 'No legacy cycle_ntfs CHECK found — already migrated or never deployed.';
    END IF;
END;
$$;

-- Add the canonical CHECK with the post-rename name.
ALTER TABLE regime_classification_history
    ADD CONSTRAINT regime_classification_history_dimension_name_check
    CHECK (dimension_name IN (
        'credit_ebp',
        'cycle_2y3m_slope',
        'vol_vrp',
        'mp_liquidity',
        'dollar_dtwexbgs',
        'stock_bond_corr'
    ));

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

-- The new CHECK should be present with cycle_2y3m_slope.
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'regime_classification_history'::regclass
  AND contype = 'c'
  AND pg_get_constraintdef(oid) LIKE '%cycle_2y3m_slope%';

-- The legacy cycle_ntfs CHECK should be gone.
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'regime_classification_history'::regclass
  AND contype = 'c'
  AND pg_get_constraintdef(oid) LIKE '%cycle_ntfs%';
