-- =============================================================================
-- Migration: 036_test_parameter_sweep_2026_05_18
-- Purpose:   Seed TEST-row parameter sets (tag != NULL) for /research-company
--            sweep experiments. Each tag = one coherent design alternative to
--            the production baseline seeded by mig 033 (all tag IS NULL).
--
--            Source: operator-directed parameter inventory from the cf-01 v2
--            redesign /review-me convergence (v4-final, 2026-05-18) +
--            companion alternative knob values for the broader inventory of
--            28 load-bearing /research-company parameters.
--
--            The TEST rows do NOT surface in `parameters_active` (the view
--            filters tag IS NULL per mig 033). They are reserved for sweep
--            runs gated via /research-company --as-of-tag <tag> through the
--            HMAC-gated entry hook (scripts/research_company_as_of_tag_gate.sh).
--
-- Schema choice:
--   - parameter_key reused from mig 033 where applicable (sleeve caps,
--     outside_view, etc.) — same key, different (value, tag) pair.
--   - NEW parameter_keys introduced under namespaces `cf01.*`, `cf07.*`,
--     `conviction.*` where mig 033 did not externalize the threshold. These
--     are NET-NEW keys with no `tag IS NULL` baseline row yet. Companion
--     follow-up: when /grill-me approves cf-01 v2 cutover, a successor
--     migration seeds the tag IS NULL production rows for these keys.
--
-- Dependencies:
--   - 033_parameters_seed_research_company (parameters table, tag column,
--     parameters_active view, append-only trigger)
--
-- Apply order:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/036_test_parameter_sweep_2026_05_18.sql
--   (must run AFTER mig 033/034/035 commit and apply)
--
-- Idempotency: safe to re-run. Each INSERT guards on (parameter_key, tag)
--   match using NOT EXISTS so re-application after partial commit is safe.
--
-- Rollback procedure: TEST rows can be marked stale by a successor INSERT
--   under the same tag (append-only honors that semantically). Hard-delete
--   is blocked by the append-only trigger; this is by design (test history
--   is auditable like production parameter history).
-- =============================================================================

BEGIN;

-- ============================================================================
-- TAG INVENTORY (this migration ships 18 sweep tags, ~30 test rows total)
-- ============================================================================
--
-- Single-knob sweeps (test ONE alternative against production baseline):
--   sweep_sleeve_caps_conservative_2026_05_18      → 70/20/5
--   sweep_sleeve_caps_aggressive_2026_05_18        → 90/30/12
--   sweep_outside_view_r_higher_2026_05_18         → r=0.30
--   sweep_outside_view_r_lower_2026_05_18          → r=0.10
--   sweep_divergence_tighter_2026_05_18            → 1.0pp
--   sweep_divergence_looser_2026_05_18             → 3.0pp
--   sweep_dual_dcf_tighter_2026_05_18              → 20pct gap
--   sweep_dual_dcf_looser_2026_05_18               → 40pct gap
--   sweep_cohort_multiplier_tighter_2026_05_18     → 1.5x
--   sweep_helmer_relaxed_2026_05_18                → gte_1 citation
--   sweep_piotroski_strict_2026_05_18              → gte_6
--   sweep_altman_z_strict_2026_05_18               → gt_1_8
--   sweep_mode_bands_tight_2026_05_18              → 25/50
--   sweep_mode_bands_loose_2026_05_18              → 35/60
--
-- Multi-knob coherent sweeps (one design = multiple keys under same tag):
--   sweep_cf01_v2_damodaran_aligned_2026_05_18     → 4 NEW cf01.* keys
--   sweep_cf07_symmetric_coupling_2026_05_18       → 1 NEW cf07.* key
--   sweep_conviction_gates_externalized_2026_05_18 → 5 NEW conviction.* keys
--                                                    (baseline-value externalization)
--   sweep_helmer_strict_2026_05_18                 → gte_3 citations + tier=1 only
--
-- All approved_by = 'sweep_test_2026-05-18' (distinguishable from
-- mig 033's launch_default_2026-05-18 production seed marker).
-- ============================================================================

-- ============================================================================
-- MULTI-KNOB SWEEP: cf01_v2_damodaran_aligned (cf-01 v2 v4-final convergence)
-- 4 NEW parameter_keys; no `tag IS NULL` baseline yet.
-- Operator approval gate: /grill-me cf-01 v2 cutover (deferred per plan).
-- ============================================================================

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'cf01.verdict_mechanism', 'cf01', '"scenario_range_with_cf07_and_optionality"'::jsonb,
       'cf-01 verdict computation mechanism. Production v1 = binary_base_gt_spot; this sweep tests the cf-01 v2 v4-final 3-step procedure (scenario range + cf-07 reconciliation + optionality carve-out) per Damodaran framework alignment.',
       'cf-01 v2 redesign /review-me v4-final convergence 2026-05-18; empirically validated on GOOGL S5 hard gate (post-Step-3 verdict = stress_open, not stress_failed).',
       'sweep_test_2026-05-18', 'sweep_cf01_v2_damodaran_aligned_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'cf01.verdict_mechanism' AND tag = 'sweep_cf01_v2_damodaran_aligned_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'cf01.bull_case_midpoint_fallback', 'cf01', '"stress_open_with_audit_flag"'::jsonb,
       'cf-01 v2 Step 1 fallback when quant memo omits damodaran_dcf.bull_case_midpoint. Defensible default that does not hide missing emission; companion quant-memo HG hard-rejects missing field on next cycle.',
       'cf-01 v2 v4-final F1 fix; rejected alternatives base_times_two (arbitrary) + revert_v1_binary (re-creates removed bias) + hard_reject (too harsh on first run).',
       'sweep_test_2026-05-18', 'sweep_cf01_v2_damodaran_aligned_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'cf01.bull_case_midpoint_fallback' AND tag = 'sweep_cf01_v2_damodaran_aligned_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'cf01.optionality_carveout_evidence_floor', 'cf01', '"all_refs_tier_1_strict"'::jsonb,
       'cf-01 v2 Step 3 condition 4. ALL evidence_index_refs per qualifying segment must have source_quality_tier == 1. Strict reading prevents tier-2 sell-side laundering.',
       'cf-01 v2 v4-final S3 fix (iter 3).',
       'sweep_test_2026-05-18', 'sweep_cf01_v2_damodaran_aligned_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'cf01.optionality_carveout_evidence_floor' AND tag = 'sweep_cf01_v2_damodaran_aligned_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'cf01.optionality_segment_de_minimis_pct', 'cf01', '1.0'::jsonb,
       'cf-01 v2 Step 3 qualification rule: ebitda_positive_de_minimis qualifies if segment EBITDA below 1.0 pct of group EBITDA AND not separately 10-K-reported. Basket-rollup match (e.g., Waymo inside Other Bets) takes precedence and routes to ebitda_negative classification.',
       'cf-01 v2 v4-final qualification rule. Pressure-tested against AAPL Services (would have qualified pre-scale-up; now too large; behavior correct).',
       'sweep_test_2026-05-18', 'sweep_cf01_v2_damodaran_aligned_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'cf01.optionality_segment_de_minimis_pct' AND tag = 'sweep_cf01_v2_damodaran_aligned_2026_05_18');

-- ============================================================================
-- MULTI-KNOB SWEEP: cf07_symmetric_coupling
-- Damodaran's "complementary not substitutable" symmetric extension.
-- ============================================================================

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'cf07.cf01_cross_coupling', 'cf07', '"symmetric_demote_clamp"'::jsonb,
       'Symmetric cf-01 ↔ cf-07 cross-coupling: cf-01 passes demote cf-07 verdict by one level; cf-07 fails clamp cf-01 ceiling at stress_open. Closes the v2 asymmetry where only cf-07 affects cf-01.',
       'Follow-on review-me cycle from cf-01 v2 convergence; matches Damodaran 2025 substack complementary-not-substitutable framing applied symmetrically.',
       'sweep_test_2026-05-18', 'sweep_cf07_symmetric_coupling_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'cf07.cf01_cross_coupling' AND tag = 'sweep_cf07_symmetric_coupling_2026_05_18');

-- ============================================================================
-- MULTI-KNOB SWEEP: conviction_gates_externalized (5 NEW keys at v1 values)
-- These thresholds are currently hardcoded in
-- src/p7_recommendation_emitter/conviction_rollup.py. This sweep externalizes
-- them at production-equivalent values so future sweeps can A/B against the
-- baseline without code edits. Companion task: code-side parameter reads.
-- ============================================================================

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'conviction.high_gate.kills_max', 'conviction', '0'::jsonb,
       'HIGH gate kills_fired upper bound. Production v1 = 0 (any kill disqualifies). conviction_rollup.py _is_high().',
       'Baseline externalization; matches code default. Future sweeps can test lte_1 (one non-catastrophic kill allowed).',
       'sweep_test_2026-05-18', 'sweep_conviction_gates_externalized_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'conviction.high_gate.kills_max' AND tag = 'sweep_conviction_gates_externalized_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'conviction.high_gate.debate_min', 'conviction', '4'::jsonb,
       'HIGH gate debate_add_count lower bound (out of 5). Production v1 = 4. conviction_rollup.py _is_high().',
       'Baseline externalization; matches code default. Future sweeps can test gte_3 (more permissive).',
       'sweep_test_2026-05-18', 'sweep_conviction_gates_externalized_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'conviction.high_gate.debate_min' AND tag = 'sweep_conviction_gates_externalized_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'conviction.high_gate.drift_max', 'conviction', '1'::jsonb,
       'HIGH gate anchor_drift_channels_triggered upper bound (of 3). Production v1 = 1. conviction_rollup.py _is_high().',
       'Baseline externalization; matches code default.',
       'sweep_test_2026-05-18', 'sweep_conviction_gates_externalized_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'conviction.high_gate.drift_max' AND tag = 'sweep_conviction_gates_externalized_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'conviction.low_gate.kills_min', 'conviction', '2'::jsonb,
       'LOW gate kills_fired lower trigger (≥). Production v1 = 2. conviction_rollup.py _is_low().',
       'Baseline externalization; matches code default. Future sweeps can test gte_1_catastrophic.',
       'sweep_test_2026-05-18', 'sweep_conviction_gates_externalized_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'conviction.low_gate.kills_min' AND tag = 'sweep_conviction_gates_externalized_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'conviction.low_gate.debate_max', 'conviction', '3'::jsonb,
       'LOW gate debate_add_count upper trigger (< this fires LOW). Production v1 = 3 (i.e., <3 fires LOW). conviction_rollup.py _is_low().',
       'Baseline externalization; matches code default.',
       'sweep_test_2026-05-18', 'sweep_conviction_gates_externalized_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'conviction.low_gate.debate_max' AND tag = 'sweep_conviction_gates_externalized_2026_05_18');

-- ============================================================================
-- SINGLE-KNOB SWEEPS: sleeve caps (3 alternative designs)
-- ============================================================================

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.sleeve_cap.core_fundamental_pct', 'sizing', '70'::jsonb,
       'Conservative sleeve cap for core_fundamental. Leaves more room for thematic + speculative + cash.',
       'Single-knob alternative to 80 production baseline.',
       'sweep_test_2026-05-18', 'sweep_sleeve_caps_conservative_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.sleeve_cap.core_fundamental_pct' AND tag = 'sweep_sleeve_caps_conservative_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.sleeve_cap.thematic_growth_pct', 'sizing', '20'::jsonb,
       'Conservative sleeve cap for thematic_growth.',
       'Single-knob alternative to 25 production baseline.',
       'sweep_test_2026-05-18', 'sweep_sleeve_caps_conservative_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.sleeve_cap.thematic_growth_pct' AND tag = 'sweep_sleeve_caps_conservative_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.sleeve_cap.speculative_optionality_pct', 'sizing', '5'::jsonb,
       'Conservative sleeve cap for speculative_optionality.',
       'Single-knob alternative to 8 production baseline.',
       'sweep_test_2026-05-18', 'sweep_sleeve_caps_conservative_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.sleeve_cap.speculative_optionality_pct' AND tag = 'sweep_sleeve_caps_conservative_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.sleeve_cap.core_fundamental_pct', 'sizing', '90'::jsonb,
       'Aggressive sleeve cap for core_fundamental. Appropriate if cash high-cost-of-carry.',
       'Single-knob alternative to 80 production baseline.',
       'sweep_test_2026-05-18', 'sweep_sleeve_caps_aggressive_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.sleeve_cap.core_fundamental_pct' AND tag = 'sweep_sleeve_caps_aggressive_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.sleeve_cap.thematic_growth_pct', 'sizing', '30'::jsonb,
       'Aggressive sleeve cap for thematic_growth. Appropriate during thematic regime favorability.',
       'Single-knob alternative to 25 production baseline.',
       'sweep_test_2026-05-18', 'sweep_sleeve_caps_aggressive_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.sleeve_cap.thematic_growth_pct' AND tag = 'sweep_sleeve_caps_aggressive_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.sleeve_cap.speculative_optionality_pct', 'sizing', '12'::jsonb,
       'Aggressive sleeve cap for speculative_optionality. Appropriate with high conviction in milestone-tree resolutions.',
       'Single-knob alternative to 8 production baseline.',
       'sweep_test_2026-05-18', 'sweep_sleeve_caps_aggressive_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.sleeve_cap.speculative_optionality_pct' AND tag = 'sweep_sleeve_caps_aggressive_2026_05_18');

-- ============================================================================
-- SINGLE-KNOB SWEEPS: outside-view Bayesian shrinkage
-- ============================================================================

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'outside_view.bayesian_shrinkage_r', 'outside_view', '0.30'::jsonb,
       'Higher r-coefficient pulls intuitive growth closer to cohort base rate; more Bayesian shrinkage.',
       'Single-knob alternative to 0.20 production baseline (Lovallo-Kahneman 2003 Phase 1.5 placeholder).',
       'sweep_test_2026-05-18', 'sweep_outside_view_r_higher_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'outside_view.bayesian_shrinkage_r' AND tag = 'sweep_outside_view_r_higher_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'outside_view.bayesian_shrinkage_r', 'outside_view', '0.10'::jsonb,
       'Lower r-coefficient; analyst inside-view dominates more; closer to pre-blend behavior.',
       'Single-knob alternative to 0.20 production baseline.',
       'sweep_test_2026-05-18', 'sweep_outside_view_r_lower_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'outside_view.bayesian_shrinkage_r' AND tag = 'sweep_outside_view_r_lower_2026_05_18');

-- ============================================================================
-- SINGLE-KNOB SWEEPS: outside-view divergence alert
-- ============================================================================

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'outside_view.divergence_alert_pp', 'outside_view', '1.0'::jsonb,
       'Tighter divergence alert; flags Helmer-gate routing on smaller corrected_divergence_pp.',
       'Single-knob alternative to 2.0 production baseline.',
       'sweep_test_2026-05-18', 'sweep_divergence_tighter_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'outside_view.divergence_alert_pp' AND tag = 'sweep_divergence_tighter_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'outside_view.divergence_alert_pp', 'outside_view', '3.0'::jsonb,
       'Looser divergence alert; fewer false alerts on high-growth thematic names.',
       'Single-knob alternative to 2.0 production baseline.',
       'sweep_test_2026-05-18', 'sweep_divergence_looser_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'outside_view.divergence_alert_pp' AND tag = 'sweep_divergence_looser_2026_05_18');

-- ============================================================================
-- SINGLE-KNOB SWEEPS: dual-DCF gap (tg-01 thematic_growth)
-- ============================================================================

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'dcf.reconciliation_divergence_pct_floor', 'dcf', '20'::jsonb,
       'Tighter dual-DCF convergence required between Damodaran narrative + austere.',
       'Single-knob alternative to 30 production baseline (tg-01).',
       'sweep_test_2026-05-18', 'sweep_dual_dcf_tighter_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'dcf.reconciliation_divergence_pct_floor' AND tag = 'sweep_dual_dcf_tighter_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'dcf.reconciliation_divergence_pct_floor', 'dcf', '40'::jsonb,
       'Looser dual-DCF gap; accepts wider scenario-discipline range.',
       'Single-knob alternative to 30 production baseline.',
       'sweep_test_2026-05-18', 'sweep_dual_dcf_looser_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'dcf.reconciliation_divergence_pct_floor' AND tag = 'sweep_dual_dcf_looser_2026_05_18');

-- ============================================================================
-- SINGLE-KNOB SWEEPS: cohort multiplier (cf-07 / tg-05 reverse-DCF)
-- ============================================================================

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'dcf.thematic_growth_implied_vs_historical_cagr_cap_ratio', 'dcf', '1.5'::jsonb,
       'Tighter reverse-DCF implied-growth cap; flags more names as overpricing-signal (1.5x cohort mean vs 2x baseline).',
       'Single-knob alternative to 2.0 production baseline. Aligns with Mauboussin 2016 1.5x outlier threshold.',
       'sweep_test_2026-05-18', 'sweep_cohort_multiplier_tighter_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'dcf.thematic_growth_implied_vs_historical_cagr_cap_ratio' AND tag = 'sweep_cohort_multiplier_tighter_2026_05_18');

-- ============================================================================
-- MULTI-KNOB SWEEP: Helmer strict (tier=1 only + >=3 citations)
-- ============================================================================

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'evaluator.gate.helmer_min_primary_source_citations', 'evaluator', '3'::jsonb,
       'Strict Helmer evidence floor: >=3 primary citations per Power. Tighter than production gte_2.',
       'Reduces vibes-based bull claims; raises bar on Helmer-Power gate clearance.',
       'sweep_test_2026-05-18', 'sweep_helmer_strict_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'evaluator.gate.helmer_min_primary_source_citations' AND tag = 'sweep_helmer_strict_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'evaluator.gate.helmer_max_source_quality_tier', 'evaluator', '1'::jsonb,
       'Strict Helmer source-quality floor: tier=1 only (10-K/10-Q/8-K/earnings transcripts). Tighter than production lte_2.',
       'Excludes tier-2 sell-side reports from Helmer evidence base; eliminates consensus-narrative laundering.',
       'sweep_test_2026-05-18', 'sweep_helmer_strict_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'evaluator.gate.helmer_max_source_quality_tier' AND tag = 'sweep_helmer_strict_2026_05_18');

-- ============================================================================
-- SINGLE-KNOB SWEEPS: Helmer relaxed
-- ============================================================================

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'evaluator.gate.helmer_min_primary_source_citations', 'evaluator', '1'::jsonb,
       'Relaxed Helmer evidence floor: >=1 primary citation per Power. Matches speculative-tier so-03 standard.',
       'Single-knob alternative to gte_2 production baseline.',
       'sweep_test_2026-05-18', 'sweep_helmer_relaxed_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'evaluator.gate.helmer_min_primary_source_citations' AND tag = 'sweep_helmer_relaxed_2026_05_18');

-- ============================================================================
-- SINGLE-KNOB SWEEPS: quality gates (Piotroski + Altman)
-- ============================================================================

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'quality_gate.piotroski_f_min', 'quality_gate', '6'::jsonb,
       'Strict Piotroski F-score floor: >=6 of 9. Higher quality bar than production gte_5.',
       'Single-knob alternative; reduces quality-borderline names.',
       'sweep_test_2026-05-18', 'sweep_piotroski_strict_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'quality_gate.piotroski_f_min' AND tag = 'sweep_piotroski_strict_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'quality_gate.altman_z_double_prime_min', 'quality_gate', '1.8'::jsonb,
       'Strict Altman Z-double-prime floor: >1.8 (Altman safe zone). Tighter than production 1.1 above-distress threshold.',
       'Single-knob alternative; only safe-zone names qualify.',
       'sweep_test_2026-05-18', 'sweep_altman_z_strict_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'quality_gate.altman_z_double_prime_min' AND tag = 'sweep_altman_z_strict_2026_05_18');

-- ============================================================================
-- SINGLE-KNOB SWEEPS: mode classifier vol bands
-- ============================================================================

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'mode.vol_regime.B_max_pct', 'mode', '25'::jsonb,
       'Tighter B-mode boundary; pulls more names into B-prime and C earlier.',
       'Single-knob alternative to 30 production baseline.',
       'sweep_test_2026-05-18', 'sweep_mode_bands_tight_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'mode.vol_regime.B_max_pct' AND tag = 'sweep_mode_bands_tight_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'mode.vol_regime.B_prime_max_pct', 'mode', '50'::jsonb,
       'Tighter B-prime-mode boundary; pulls more names into C earlier.',
       'Single-knob alternative to 55 production baseline.',
       'sweep_test_2026-05-18', 'sweep_mode_bands_tight_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'mode.vol_regime.B_prime_max_pct' AND tag = 'sweep_mode_bands_tight_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'mode.vol_regime.B_max_pct', 'mode', '35'::jsonb,
       'Looser B-mode boundary; more names stay in B.',
       'Single-knob alternative to 30 production baseline.',
       'sweep_test_2026-05-18', 'sweep_mode_bands_loose_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'mode.vol_regime.B_max_pct' AND tag = 'sweep_mode_bands_loose_2026_05_18');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'mode.vol_regime.B_prime_max_pct', 'mode', '60'::jsonb,
       'Looser B-prime-mode boundary; fewer names reach C.',
       'Single-knob alternative to 55 production baseline.',
       'sweep_test_2026-05-18', 'sweep_mode_bands_loose_2026_05_18'
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'mode.vol_regime.B_prime_max_pct' AND tag = 'sweep_mode_bands_loose_2026_05_18');

-- ============================================================================
-- VERIFICATION
-- ============================================================================
--
-- After applying mig 036, verify expected counts:
--   SELECT COUNT(*) FROM parameters WHERE approved_by = 'sweep_test_2026-05-18';
--   --> expected: 30 rows
--
--   SELECT DISTINCT tag FROM parameters WHERE approved_by = 'sweep_test_2026-05-18'
--   ORDER BY tag;
--   --> expected: 18 distinct sweep tags
--
--   SELECT COUNT(*) FROM parameters_active;
--   --> expected: 63 (unchanged from mig 033; test rows excluded by view)
--
--   SELECT parameter_key, COUNT(*) FROM parameters
--   WHERE approved_by = 'sweep_test_2026-05-18'
--   GROUP BY parameter_key
--   HAVING COUNT(*) > 1;
--   --> expected: parameter_keys with multiple sweep alternatives surface here
--     (sleeve caps, outside_view r, divergence_alert, dual_dcf, mode bands,
--      helmer citations). These are NOT primary-key violations - uniqueness
--      is on (parameter_key, tag) pair.

COMMIT;

-- =============================================================================
-- NOTE on test orchestration (out of scope for this migration):
--   /research-company --as-of-tag <tag> is the entry hook that activates a
--   sweep parameter set. The hook resolves all parameter_keys via the
--   parameters_active view AND a tag-specific UNION:
--     SELECT * FROM parameters_active
--     UNION ALL
--     SELECT * FROM parameters WHERE tag = '<sweep_tag>' AND effective_at <= NOW()
--   so a sweep tag's rows shadow the production baseline ONLY for keys
--   present under that tag. Keys absent from the sweep fall back to
--   production (tag IS NULL).
-- =============================================================================
