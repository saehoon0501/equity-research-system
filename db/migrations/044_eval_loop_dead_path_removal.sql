-- =============================================================================
-- Migration 044: research-company eval loop dead-path removal
-- (Renamed from 041 to resolve number collision with 041_flow_overlay_v03_crowding.sql.
--  Originally applied to live DB as 041 on 2026-05-23; rename is filesystem-only.)
-- Date:    2026-05-23
-- Spec:    docs/superpowers/specs/2026-05-23-eval-loop-deletion-design.md
-- Plan:    /Users/sehoonbyun/.claude/plans/async-yawning-owl.md (D0–D4)
-- Pairs:   none. The companion CREATE migration is intentionally separated.
--
-- D0 verification done 2026-05-23:
--   Confirmed-dead (§2.1):
--     recommendation_outcomes, predictions, counterfactual_retrievals,
--     peak_pain_archetypes_retired_20260517, calibration_test_results,
--     materiality_classifier_drift, system_vs_operator_brier (view).
--   Verify-before-drop (§2.2) — D0 outcome:
--     operator_overrides           → DROP (0 rows, no live writer)
--     override_outcomes            → DROP (0 rows, no live writer)
--     fill_divergence              → DROP (0 rows, no writers found)
--     debate_consensus_history     → KEEP (live writer: src/p4_debate/orchestrator.py)
--     materiality_events           → KEEP (live writer: src/l4_daily_monitor/refresh_emitter.py)
--     mode_classifications         → KEEP (live writers in src/p4_debate, src/mode_classifier)
--   Added by D0 (not in spec):
--     veto_lifecycle               → DROP (0 rows, writers all in dead src/counterfactual_veto/;
--                                          FK to counterfactual_retrievals → drop FIRST)
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Pre-flight verification — abort if any to-be-dropped table is non-empty.
--
-- WAIVER: peak_pain_archetypes_retired_20260517 is excluded from the empty
-- check. The 2026-05-17 rename to `_retired_<DATE>` is itself the explicit
-- retirement gate (mig 032). Its preserved rows (45 historical archetypes)
-- are reference data for the resurrection-procedure documented in
-- src/peak_pain_catalog/DEPRECATED.md; the operator-approved decision in
-- the deletion spec (§2.1) is to discard them. A NOTICE surfaces the
-- discard count for auditability.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  v_table TEXT;
  v_rows  INTEGER;
BEGIN
  -- Surface the waived discard count.
  EXECUTE 'SELECT count(*) FROM peak_pain_archetypes_retired_20260517' INTO v_rows;
  RAISE NOTICE 'mig 041 waiver: dropping % rows from peak_pain_archetypes_retired_20260517 (explicitly retired 2026-05-17; spec §2.1 authorized discard).', v_rows;

  FOR v_table IN SELECT unnest(ARRAY[
    'recommendation_outcomes',
    'predictions',
    'counterfactual_retrievals',
    'calibration_test_results',
    'materiality_classifier_drift',
    'operator_overrides',
    'override_outcomes',
    'fill_divergence',
    'veto_lifecycle'
  ])
  LOOP
    EXECUTE format('SELECT count(*) FROM %I', v_table) INTO v_rows;
    IF v_rows > 0 THEN
      RAISE EXCEPTION 'mig 041 abort: % is non-empty (rowcount=%). Investigate before re-running.', v_table, v_rows;
    END IF;
  END LOOP;
END $$;

-- -----------------------------------------------------------------------------
-- Pre-flight verification — abort if any unexpected incoming FK references a
-- to-be-dropped table. Expected FKs (which mig 041 handles by drop ordering):
--   veto_lifecycle → counterfactual_retrievals
--   override_outcomes → operator_overrides
-- Any FK NOT in the expected set is an unexpected dependency and halts.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  v_fk RECORD;
  v_ref_table TEXT;
BEGIN
  FOR v_fk IN
    SELECT conrelid::regclass::text AS referencing_table,
           confrelid::regclass::text AS referenced_table,
           conname
    FROM pg_constraint
    WHERE contype = 'f'
      AND confrelid::regclass::text IN (
        'recommendation_outcomes', 'predictions',
        'counterfactual_retrievals', 'peak_pain_archetypes_retired_20260517',
        'calibration_test_results', 'materiality_classifier_drift',
        'operator_overrides', 'override_outcomes', 'fill_divergence',
        'veto_lifecycle'
      )
  LOOP
    -- Whitelist expected internal FKs (within the drop set, handled by ordering)
    IF (v_fk.referencing_table = 'veto_lifecycle' AND v_fk.referenced_table = 'counterfactual_retrievals')
       OR (v_fk.referencing_table = 'override_outcomes' AND v_fk.referenced_table = 'operator_overrides')
    THEN
      CONTINUE;
    END IF;
    RAISE EXCEPTION 'mig 041 abort: unexpected FK %.% references to-be-dropped %.', v_fk.referencing_table, v_fk.conname, v_fk.referenced_table;
  END LOOP;
END $$;

-- -----------------------------------------------------------------------------
-- DROP block — order respects FK dependencies (children first).
-- -----------------------------------------------------------------------------

-- 1. View (no dependents)
DROP VIEW  IF EXISTS system_vs_operator_brier;

-- 2. FK-bound pairs (drop child first)
DROP TABLE IF EXISTS veto_lifecycle;                            -- child of counterfactual_retrievals
DROP TABLE IF EXISTS counterfactual_retrievals;

DROP TABLE IF EXISTS override_outcomes;                         -- child of operator_overrides
DROP TABLE IF EXISTS operator_overrides;

-- 3. Standalone tables
DROP TABLE IF EXISTS recommendation_outcomes;
DROP TABLE IF EXISTS predictions;
DROP TABLE IF EXISTS peak_pain_archetypes_retired_20260517;
DROP TABLE IF EXISTS calibration_test_results;
DROP TABLE IF EXISTS materiality_classifier_drift;
DROP TABLE IF EXISTS fill_divergence;

COMMIT;

-- =============================================================================
-- VERIFY: run these after applying.
-- =============================================================================

-- All 10 tables should be gone.
SELECT table_name FROM information_schema.tables
WHERE table_schema='public'
  AND table_name IN (
    'recommendation_outcomes','predictions','counterfactual_retrievals',
    'peak_pain_archetypes_retired_20260517','calibration_test_results',
    'materiality_classifier_drift','operator_overrides','override_outcomes',
    'fill_divergence','veto_lifecycle'
  );
-- Expected: 0 rows.

-- The view should be gone.
SELECT table_name FROM information_schema.views
WHERE table_schema='public' AND table_name = 'system_vs_operator_brier';
-- Expected: 0 rows.

-- Survivors that were considered for drop but kept (live writers).
SELECT table_name FROM information_schema.tables
WHERE table_schema='public'
  AND table_name IN ('debate_consensus_history','materiality_events','mode_classifications');
-- Expected: 3 rows (all KEPT).
