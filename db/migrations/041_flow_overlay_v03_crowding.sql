-- =============================================================================
-- Migration: 041_flow_overlay_v03_crowding
-- Purpose:   Seed parameter rows for the v0.3 flow-overlay extension —
--            crowded_warning BOOLEAN sub-signal (asymmetric soft -1 vote).
--            Driven by Polygon /stocks/v1/short-interest endpoint (Basic+ tier).
--
--            Reference: plans/first-let-s-plan-the-serialized-hanrahan.md
--                       (v0.3 plan, /review-me-approved 2026-05-23)
--
--            Rows in 1 namespace:
--            - flow.crowding_* (4 rows: 2 thresholds + 1 logic_operator + 1 stale_max_days)
--
-- Schema choice:
--   - All rows tag=NULL (launch_default production governance).
--   - parameters table append-only (mig 004 trigger unchanged).
--   - Idempotent: each INSERT guarded by NOT EXISTS on (parameter_key, tag IS NULL).
--   - String enum value stored as JSONB string ('"AND"'::jsonb).
--
-- Scope discipline:
--   - v0.3 ships placeholder values where /review-me will deliver the final
--     calibrated values (mirrors v0.1/v0.2 placeholder discipline).
--   - 4 forced choices are explicitly flagged in change_rationale:
--     1. days_to_cover_threshold (Wikipedia folk-wisdom; no academic anchor)
--     2. short_pct_float_threshold (practitioner rule-of-thumb)
--     3. logic_operator (AND vs OR; conservative AND chosen)
--     4. stale_data_max_days (~1.5 FINRA bi-weekly reporting cycles)
--
-- Empirical grounding (literature establishes informativeness; no published threshold):
--   - Diether, Lee, Werner (2009) "Short-Sale Strategies and Return Predictability"
--   - Boehmer, Jones, Zhang (2008) "Which Shorts Are Informed?"
--   - Engelberg, Reed, Ringgenberg (2018) "Short-Selling Risk"
--   - Cohen, Diether, Malloy (2007) "Supply and Demand Shifts in the Shorting Market"
--
-- Architectural invariant:
--   - crowded_warning is ASYMMETRIC: contributes -1 to tech_axis_score when True,
--     contributes 0 (never +1) when False. This preserves the tech_axis ceiling
--     so sizing.tech_axis_bullish_score_min (v0.2 lock = 4) needs NO recalibration.
--
-- Dependencies:
--   - 033_parameters_seed_research_company (base seed + tag column).
--   - 039_flow_overlay_parameters (v0.1 flow.* namespace base).
--   - 040_flow_overlay_v02_gamma_erp (v0.2 flow.gex_* + flow.erp_add_bps + sizing.tech_axis_bullish_score_min).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U <user> -d equity_research \
--        -f db/migrations/041_flow_overlay_v03_crowding.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- flow.crowding_* classifier params (4 rows)
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.crowding_days_to_cover_threshold', 'flow', '5.0'::jsonb,
       'Days-to-cover breach threshold (float, days). When breached (per logic_operator with short_pct_float_threshold), contributes to crowded_warning=True.',
       'v0.3 PLACEHOLDER per plan Open Items. Wikipedia folk-wisdom cites days_to_cover >= 5 as bearish but with NO academic citation. Literature (Diether 2009, Boehmer 2008, Engelberg 2018, Cohen 2007) establishes short-interest informativeness but does NOT specify thresholds. FORCED CHOICE for /review-me.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.crowding_days_to_cover_threshold' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.crowding_short_pct_float_threshold', 'flow', '0.20'::jsonb,
       'Short-interest as fraction of float (computed: short_interest / shares_outstanding). When >= threshold (per logic_operator with days_to_cover_threshold), contributes to crowded_warning=True. Stored as fractional (0.20 = 20%); helper expects fractional.',
       'v0.3 PLACEHOLDER per plan Open Items. Practitioner rule-of-thumb (20%) per Cohen-Diether-Malloy 2007 supply/demand shifts framework, but the paper does NOT pin a specific cutoff. FORCED CHOICE for /review-me.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.crowding_short_pct_float_threshold' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.crowding_logic_operator', 'flow', '"AND"'::jsonb,
       'Logic combining the two threshold breaches. AND = both must breach (conservative; lower false-positive). OR = either breaches (looser; higher fire rate). Enum: AND | OR.',
       'v0.3 default AND (conservative). FORCED CHOICE per plan Open Items; /review-me may flip to OR after observing Phase 1 fire rates.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.crowding_logic_operator' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.crowding_stale_data_max_days', 'flow', '21'::jsonb,
       'Max age (days) of short-interest settlement_date before classifier treats it as stale (warning forced False, unavailable_reason=short_interest_stale). FINRA reports bi-weekly so 21 days = ~1.5 cycles.',
       'v0.3 default 21d. FINRA settlement cadence is bi-weekly; 1.5 cycles allows for one missed report without false-firing. FORCED CHOICE per plan Open Items; /review-me may tighten/loosen.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.crowding_stale_data_max_days' AND tag IS NULL);

-- -----------------------------------------------------------------------------
-- Expected row count after this migration: 4 (all rows above).
-- Idempotent re-run will INSERT 0 additional rows.
-- -----------------------------------------------------------------------------

COMMIT;
