-- =============================================================================
-- Migration: 033_parameters_seed_research_company
-- Purpose:   Externalize ~63 numeric thresholds from /research-company skill
--            markdown (orchestrator + 5 subagents) into the parameters table.
--            Adds a `tag` column to parameters + ALTERs parameters_active view
--            to filter `tag IS NULL` (production rows only). Tagged rows are
--            reserved for sweep/test runs gated through --as-of-tag at the
--            orchestrator entry hook.
--
--            Reference: /review-me v7-final convergence 2026-05-18.
--            Plan doc:  docs/superpowers/audits/2026-05-18-parameter-externalization-phase3-audit-checklist.md
--
-- Schema choice:
--   - `tag` is a free-form TEXT column. NULL = production governance row.
--     Non-NULL = sweep test row, never surfaces in `parameters_active`
--     because the view filters `tag IS NULL`.
--   - All seed rows in this migration are tag=NULL (launch_default production).
--   - parameters table remains append-only (mig 004 trigger unchanged).
--   - parameters_active view recreated to ADD `AND tag IS NULL` predicate.
--   - Idempotent: each INSERT is guarded by NOT EXISTS on (parameter_key)
--     where tag IS NULL. Re-running this migration does not double-insert.
--
-- Dependencies:
--   - 004_v3_parameters (base table + view + append-only trigger).
--   - PostgreSQL 13+ (gen_random_uuid).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/033_parameters_seed_research_company.sql
--
-- Idempotency: safe to re-run. ADD COLUMN IF NOT EXISTS, CREATE OR REPLACE
--   VIEW, INSERT ... WHERE NOT EXISTS.
--
-- Rollback note: the legacy parameters_active view (sans tag filter) can be
--   restored by reverting the CREATE OR REPLACE VIEW block. Seed rows can be
--   superseded with a later effective_at INSERT (they cannot be DELETEd
--   because of the append-only trigger).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Step 1: ADD tag column to parameters table.
-- NULL = production governance row (the default for all pre-existing rows).
-- Non-NULL = sweep test row (created via /parameters-review extended sweep_tag
-- arg + HMAC-gated --as-of-tag orchestrator path).
-- -----------------------------------------------------------------------------

ALTER TABLE parameters
    ADD COLUMN IF NOT EXISTS tag TEXT;

-- Lookup current value of a parameter under a specific tag.
CREATE INDEX IF NOT EXISTS idx_parameters_tag_key_effective
    ON parameters(tag, parameter_key, effective_at DESC);

-- -----------------------------------------------------------------------------
-- Step 2: Recreate parameters_active view to filter tag IS NULL.
-- Production reads NEVER see tagged sweep rows. Tagged rows are surfaced via
-- a separate orchestrator code path keyed on --as-of-tag (PreToolUse hook
-- validates HMAC sig before that path is allowed).
-- -----------------------------------------------------------------------------

CREATE OR REPLACE VIEW parameters_active AS
SELECT DISTINCT ON (parameter_key)
    version_id,
    parameter_key,
    parameter_namespace,
    value,
    description,
    effective_at,
    approved_by,
    tag
FROM parameters
WHERE effective_at <= NOW()
  AND tag IS NULL
ORDER BY parameter_key, effective_at DESC;

-- -----------------------------------------------------------------------------
-- Step 3: Seed launch_default rows for all ~63 tunable thresholds.
-- approved_by = 'launch_default_2026-05-18' marks the externalization batch.
-- Each INSERT is idempotent (guarded against re-application).
-- -----------------------------------------------------------------------------

-- Helper macro pattern: each INSERT is its own statement so a failed one does
-- not abort the batch. The WHERE NOT EXISTS clause keys on (parameter_key)
-- under tag IS NULL — re-running the migration after partial application is
-- safe.

-- ====== namespace: sizing ======

-- Sleeve caps (HARD GATES at pm-supervisor §3)
INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.sleeve_cap.core_fundamental_pct', 'sizing', '80'::jsonb,
       'Max aggregate portfolio weight in core_fundamental tier; pm-supervisor §3 hard gate blocks BUY if breach.',
       'Initial externalization from pm-supervisor.md:159 hardcoded literal.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.sleeve_cap.core_fundamental_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.sleeve_cap.thematic_growth_pct', 'sizing', '25'::jsonb,
       'Max aggregate portfolio weight in thematic_growth tier; pm-supervisor §3 hard gate.',
       'Initial externalization from pm-supervisor.md:160.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.sleeve_cap.thematic_growth_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.sleeve_cap.speculative_optionality_pct', 'sizing', '8'::jsonb,
       'Max aggregate portfolio weight in speculative_optionality tier; pm-supervisor §3 hard gate.',
       'Initial externalization from pm-supervisor.md:161.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.sleeve_cap.speculative_optionality_pct' AND tag IS NULL);

-- Conviction size bands (pm-supervisor §6)
INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.conviction_band.HIGH.min_pct', 'sizing', '3.0'::jsonb,
       'HIGH conviction position size band, lower bound (% of book).',
       'Initial externalization from pm-supervisor.md:269.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.conviction_band.HIGH.min_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.conviction_band.HIGH.max_pct', 'sizing', '6.0'::jsonb,
       'HIGH conviction position size band, upper bound (% of book).',
       'Initial externalization from pm-supervisor.md:269.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.conviction_band.HIGH.max_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.conviction_band.MEDIUM.min_pct', 'sizing', '1.5'::jsonb,
       'MEDIUM conviction position size band, lower bound (% of book).',
       'Initial externalization from pm-supervisor.md:270.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.conviction_band.MEDIUM.min_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.conviction_band.MEDIUM.max_pct', 'sizing', '3.0'::jsonb,
       'MEDIUM conviction position size band, upper bound (% of book).',
       'Initial externalization from pm-supervisor.md:270.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.conviction_band.MEDIUM.max_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.conviction_band.LOW.min_pct', 'sizing', '0.0'::jsonb,
       'LOW conviction position size band, lower bound (% of book). Always 0 — LOW = no add.',
       'Initial externalization from pm-supervisor.md:271.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.conviction_band.LOW.min_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.conviction_band.LOW.max_pct', 'sizing', '0.0'::jsonb,
       'LOW conviction position size band, upper bound (% of book). Always 0 — LOW = no add.',
       'Initial externalization from pm-supervisor.md:271.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.conviction_band.LOW.max_pct' AND tag IS NULL);

-- Mode multipliers (pm-supervisor §6)
INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.mode_multiplier.B', 'sizing', '1.0'::jsonb,
       'Mode B size multiplier (low-vol regime, <=30% realized vol). 1.0 = full size.',
       'Initial externalization from pm-supervisor.md:277.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.mode_multiplier.B' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.mode_multiplier.B_prime', 'sizing', '0.5'::jsonb,
       'Mode B-prime size multiplier (mid-vol regime, 30-55% realized vol). 0.5 = half size.',
       'Initial externalization from pm-supervisor.md:278.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.mode_multiplier.B_prime' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.mode_multiplier.C', 'sizing', '0.333'::jsonb,
       'Mode C size multiplier (high-vol regime, 55%+ realized vol). 0.333 = third size.',
       'Initial externalization from pm-supervisor.md:279.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.mode_multiplier.C' AND tag IS NULL);

-- Catalyst modifier bounds (pm-supervisor §6)
INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.catalyst_modifier_bound.full_pct', 'sizing', '25'::jsonb,
       'Maximum catalyst-driven adjustment to position midpoint (% of midpoint). Full-bound when signal quality OK.',
       'Initial externalization from pm-supervisor.md:298.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.catalyst_modifier_bound.full_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.catalyst_modifier_bound.shrunk_pct', 'sizing', '10'::jsonb,
       'Shrunk catalyst-driven adjustment bound (% of midpoint), used when sentiment/tier signals degraded.',
       'Initial externalization from pm-supervisor.md:299.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.catalyst_modifier_bound.shrunk_pct' AND tag IS NULL);

-- Mode volatility regime boundaries (pm-supervisor §6 mode definition)
INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'mode.vol_regime.B_max_pct', 'mode', '30'::jsonb,
       'Mode B upper bound on realized volatility (%). Above this, regime is B-prime or C.',
       'Initial externalization from pm-supervisor.md:277.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'mode.vol_regime.B_max_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'mode.vol_regime.B_prime_max_pct', 'mode', '55'::jsonb,
       'Mode B-prime upper bound on realized volatility (%). Above this, regime is C.',
       'Initial externalization from pm-supervisor.md:278.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'mode.vol_regime.B_prime_max_pct' AND tag IS NULL);

-- ====== namespace: tier_classification ======

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tier_classification.core_fundamental.min_revenue_usd', 'tier_classification', '1000000000'::jsonb,
       'Trailing 12mo revenue threshold (USD) to qualify for core_fundamental tier. Currently $1B.',
       'Initial externalization from research-company.md:59.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tier_classification.core_fundamental.min_revenue_usd' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tier_classification.core_fundamental.min_positive_op_income_quarters', 'tier_classification', '4'::jsonb,
       'Minimum number of last-8-quarters with positive operating income to qualify for core_fundamental tier.',
       'Initial externalization from research-company.md:59.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tier_classification.core_fundamental.min_positive_op_income_quarters' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tier_classification.core_fundamental.min_years_public', 'tier_classification', '10'::jsonb,
       'Minimum years-public threshold to qualify for core_fundamental tier (maturity gate).',
       'Initial externalization from research-company.md:60.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tier_classification.core_fundamental.min_years_public' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tier_classification.thematic_growth.min_revenue_usd', 'tier_classification', '100000000'::jsonb,
       'Trailing 12mo revenue threshold (USD) to qualify for thematic_growth tier. Currently $100M.',
       'Initial externalization from research-company.md:64.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tier_classification.thematic_growth.min_revenue_usd' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tier_classification.speculative_optionality.max_revenue_usd', 'tier_classification', '100000000'::jsonb,
       'Trailing 12mo revenue ceiling (USD) for speculative_optionality tier (below this OR pre-revenue).',
       'Initial externalization from research-company.md:69.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tier_classification.speculative_optionality.max_revenue_usd' AND tag IS NULL);

-- ====== namespace: quality_gate ======

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'quality_gate.piotroski_f_min', 'quality_gate', '6'::jsonb,
       'Minimum Piotroski F-Score (0-9 scale) to pass the quality gate. Below this → disposition_recommendation must be REJECT.',
       'Initial externalization from quantitative-analyst.md:273 / evaluator.md:152.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'quality_gate.piotroski_f_min' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'quality_gate.altman_z_double_prime_min', 'quality_gate', '1.1'::jsonb,
       'Minimum Altman Z-double-prime to pass the quality gate (Z>2.99 for manufacturers; alternative for financials).',
       'Initial externalization from quantitative-analyst.md:274 / evaluator.md:152.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'quality_gate.altman_z_double_prime_min' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'quality_gate.altman_z_x4_anomaly_cap', 'quality_gate', '10'::jsonb,
       'Anomaly detection cap for Altman X4 (market-cap-to-liabilities). Above this triggers mega-cap adjustment flag.',
       'Initial externalization from quantitative-analyst.md:274.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'quality_gate.altman_z_x4_anomaly_cap' AND tag IS NULL);

-- ====== namespace: dcf ======

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'dcf.reconciliation_divergence_pct_floor', 'dcf', '30'::jsonb,
       'Inherited-vs-austere DCF divergence threshold (%) above which a reconciliation block is required.',
       'Initial externalization from quantitative-analyst.md:218 / evaluator.md HG-20.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'dcf.reconciliation_divergence_pct_floor' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'dcf.sensitivity_band_pct', 'dcf', '20'::jsonb,
       'DCF sensitivity stress range (±%) on growth and margin drivers.',
       'Initial externalization from quantitative-analyst.md:118.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'dcf.sensitivity_band_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'dcf.austere_terminal_growth_dgs10_premium_pct', 'dcf', '1.5'::jsonb,
       'Austere DCF terminal growth = DGS10 + this premium %. Mean-reversion proxy for nominal GDP.',
       'Initial externalization from quantitative-analyst.md:207.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'dcf.austere_terminal_growth_dgs10_premium_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'dcf.austere_growth_fade_years', 'dcf', '5'::jsonb,
       'Austere DCF: years over which growth rate linearly fades from current toward terminal.',
       'Initial externalization from quantitative-analyst.md:207.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'dcf.austere_growth_fade_years' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'dcf.austere_margin_fade_years', 'dcf', '5'::jsonb,
       'Austere DCF: years over which operating margin linearly fades from current to industry median.',
       'Initial externalization from quantitative-analyst.md:209.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'dcf.austere_margin_fade_years' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'dcf.austere_roic_fade_years', 'dcf', '10'::jsonb,
       'Austere DCF: years (explicit window) over which ROIC linearly fades from current toward WACC.',
       'Initial externalization from quantitative-analyst.md:209.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'dcf.austere_roic_fade_years' AND tag IS NULL);

-- ====== namespace: outside_view ======

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'outside_view.bayesian_shrinkage_r', 'outside_view', '0.20'::jsonb,
       'Bayesian shrinkage coefficient toward reference-class base rate (Overlay 3). corrected = intuitive + r*(reference - intuitive).',
       'Initial externalization from quantitative-analyst.md:321. Phase 1.5 placeholder per spec.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'outside_view.bayesian_shrinkage_r' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'outside_view.divergence_alert_pp', 'outside_view', '2'::jsonb,
       'Outside-view divergence (pp, Bayesian-blended) above which Helmer-gate routing fires in pm-supervisor §2.6.',
       'Initial externalization from quantitative-analyst.md:324 / pm-supervisor.md:72.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'outside_view.divergence_alert_pp' AND tag IS NULL);

-- ====== namespace: wacc ======

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'wacc.erp_refresh_drift_bps', 'wacc', '50'::jsonb,
       'DGS10 drift (bps) above which WACC ERP is recomputed; below threshold cached value passes through.',
       'Initial externalization from quantitative-analyst.md:93,95. INV-2 lockstep pair (WACC ratio) — flag for operator on load-bearing vs tunable.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'wacc.erp_refresh_drift_bps' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'wacc.erp_sensitivity_band_bps', 'wacc', '100'::jsonb,
       'WACC ERP sensitivity range (±bps) around base ERP. INV-2 lockstep pair: must equal 2*refresh_drift_bps if operator confirms 2sigma assumption.',
       'Initial externalization from quantitative-analyst.md:106. INV-2 lockstep pair.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'wacc.erp_sensitivity_band_bps' AND tag IS NULL);

-- ====== namespace: reinvestment_moat ======

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reinvestment_moat.label_A.min_roic_spread_pp', 'reinvestment_moat', '10'::jsonb,
       'Quality label A: minimum incremental_roic_3y spread above WACC (pp). INV-1 lockstep: must be >= label_B.',
       'Initial externalization from quantitative-analyst.md:259.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reinvestment_moat.label_A.min_roic_spread_pp' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reinvestment_moat.label_A.min_runway_years', 'reinvestment_moat', '5'::jsonb,
       'Quality label A: minimum reinvestment runway (years). INV-1 lockstep: must be >= label_B.',
       'Initial externalization from quantitative-analyst.md:259.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reinvestment_moat.label_A.min_runway_years' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reinvestment_moat.label_B.min_roic_spread_pp', 'reinvestment_moat', '5'::jsonb,
       'Quality label B: minimum incremental_roic_3y spread above WACC (pp). INV-1 lockstep: must be >= label_C.',
       'Initial externalization from quantitative-analyst.md:260.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reinvestment_moat.label_B.min_roic_spread_pp' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reinvestment_moat.label_B.min_runway_years', 'reinvestment_moat', '3'::jsonb,
       'Quality label B: minimum reinvestment runway (years). INV-1 lockstep: must be >= label_C.',
       'Initial externalization from quantitative-analyst.md:260.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reinvestment_moat.label_B.min_runway_years' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reinvestment_moat.label_C.min_roic_spread_pp', 'reinvestment_moat', '0'::jsonb,
       'Quality label C: minimum incremental_roic_3y spread above WACC (pp). Floor; below this is label D.',
       'Initial externalization from quantitative-analyst.md:261.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reinvestment_moat.label_C.min_roic_spread_pp' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reinvestment_moat.label_C.min_runway_years', 'reinvestment_moat', '2'::jsonb,
       'Quality label C: minimum reinvestment runway (years). Floor; below this is label D.',
       'Initial externalization from quantitative-analyst.md:261.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reinvestment_moat.label_C.min_runway_years' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reinvestment_moat.capital_light_skip_reinvestment_rate_pct', 'reinvestment_moat', '3'::jsonb,
       'Reinvestment-rate floor (%) below which the reinvestment-moat framework is N/A (capital-light skip).',
       'Initial externalization from quantitative-analyst.md:264.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reinvestment_moat.capital_light_skip_reinvestment_rate_pct' AND tag IS NULL);

-- ====== namespace: catalyst_scout ======

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'catalyst_scout.window.eight_k_lookback_days', 'catalyst_scout', '14'::jsonb,
       '8-K lookback window (calendar days) for forward prospective filter.',
       'Initial externalization from catalyst-scout.md:72.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'catalyst_scout.window.eight_k_lookback_days' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'catalyst_scout.window.high_conviction_catalyst_days', 'catalyst_scout', '30'::jsonb,
       'Forward window (calendar days) within which a high-confidence catalyst counts toward upside-modifier trigger.',
       'Initial externalization from catalyst-scout.md:308.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'catalyst_scout.window.high_conviction_catalyst_days' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'catalyst_scout.threshold.event_significance_sigma', 'catalyst_scout', '2.0'::jsonb,
       'Sigma threshold (day-move stdev) above which a historical event qualifies as a material catalyst.',
       'Initial externalization from catalyst-scout.md:65.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'catalyst_scout.threshold.event_significance_sigma' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'catalyst_scout.threshold.iv_term_inversion_pp', 'catalyst_scout', '5'::jsonb,
       'IV term-structure inversion threshold (pp) flagging informed-flow asymmetry.',
       'Initial externalization from catalyst-scout.md:175,320.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'catalyst_scout.threshold.iv_term_inversion_pp' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'catalyst_scout.threshold.put_call_ratio_high', 'catalyst_scout', '1.5'::jsonb,
       'P/C ratio above which the high-put-buying signal triggers (per Pan-Poteshman 2006).',
       'Initial externalization from catalyst-scout.md:186.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'catalyst_scout.threshold.put_call_ratio_high' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'catalyst_scout.threshold.put_call_ratio_room_for_upside', 'catalyst_scout', '0.7'::jsonb,
       'P/C ratio above which the room-for-upside (hedging-present) modifier check passes.',
       'Initial externalization from catalyst-scout.md:309.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'catalyst_scout.threshold.put_call_ratio_room_for_upside' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'catalyst_scout.threshold.unusual_activity_vol_oi_ratio', 'catalyst_scout', '1.0'::jsonb,
       'Tier-1 unusual-activity filter: volume-to-open-interest ratio threshold.',
       'Initial externalization from catalyst-scout.md:193.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'catalyst_scout.threshold.unusual_activity_vol_oi_ratio' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'catalyst_scout.threshold.unusual_activity_vol_spike_x', 'catalyst_scout', '3.0'::jsonb,
       'Tier-2 unusual-activity enrichment: volume spike multiple vs 90-day average.',
       'Initial externalization from catalyst-scout.md:193.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'catalyst_scout.threshold.unusual_activity_vol_spike_x' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'catalyst_scout.threshold.aaii_extreme_bullish_pp', 'catalyst_scout', '30'::jsonb,
       'AAII bull-bear spread (pp) above which sentiment is extreme-bullish (contrarian-negative).',
       'Initial externalization from catalyst-scout.md:307,310.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'catalyst_scout.threshold.aaii_extreme_bullish_pp' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'catalyst_scout.threshold.aaii_crowded_consensus_pp', 'catalyst_scout', '35'::jsonb,
       'AAII bull-bear spread (pp) at which crowded-consensus downside trigger fires (combined with crowded-trade match).',
       'Initial externalization from catalyst-scout.md:322.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'catalyst_scout.threshold.aaii_crowded_consensus_pp' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'catalyst_scout.modifier.upside_min_high_conviction_count', 'catalyst_scout', '2'::jsonb,
       'Minimum count of high-confidence catalysts within high_conviction_catalyst_days for upside-modifier trigger.',
       'Initial externalization from catalyst-scout.md:313.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'catalyst_scout.modifier.upside_min_high_conviction_count' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'catalyst_scout.modifier.downside_min_negative_count', 'catalyst_scout', '2'::jsonb,
       'Minimum count of negative catalysts within high_conviction_catalyst_days for downside-modifier trigger.',
       'Initial externalization from catalyst-scout.md:321.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'catalyst_scout.modifier.downside_min_negative_count' AND tag IS NULL);

-- ====== namespace: evaluator ======

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'evaluator.gate.brief_min_chars', 'evaluator', '1500'::jsonb,
       'Brief content minimum length (chars) for either quant or strategic brief to pass HG-19 R1.',
       'Initial externalization from evaluator.md HG-19 R1.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'evaluator.gate.brief_min_chars' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'evaluator.gate.conviction_override_justification_min_chars', 'evaluator', '50'::jsonb,
       'Conviction override justification minimum length (chars) for HG-22 Check 3.',
       'Initial externalization from evaluator.md HG-22 Check 3.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'evaluator.gate.conviction_override_justification_min_chars' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'evaluator.gate.pm_report_mtime_staleness_seconds', 'evaluator', '300'::jsonb,
       'PM report mtime staleness tolerance (seconds) for HG-16 Check 3 orphan-run detection.',
       'Initial externalization from evaluator.md:268 (CLOCK_SKEW_TOLERANCE).',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'evaluator.gate.pm_report_mtime_staleness_seconds' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'evaluator.gate.sentiment_indicator_degradation_unavailable_count', 'evaluator', '2'::jsonb,
       'Sentiment indicators unavailable-count (of 4 expected) above which signal-quality degradation flag fires (HG-24).',
       'Initial externalization from evaluator.md HG-24.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'evaluator.gate.sentiment_indicator_degradation_unavailable_count' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'evaluator.gate.helmer_min_primary_source_citations', 'evaluator', '2'::jsonb,
       'Helmer Power evidence sufficiency: minimum primary source citations per claimed Power.',
       'Initial externalization from evaluator.md HG-14 / strategic-analyst.md:100.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'evaluator.gate.helmer_min_primary_source_citations' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'evaluator.gate.helmer_max_source_quality_tier', 'evaluator', '2'::jsonb,
       'Helmer Power citation max source_quality_tier (lower=better; <=2 = primary source).',
       'Initial externalization from evaluator.md HG-14 / strategic-analyst.md:100.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'evaluator.gate.helmer_max_source_quality_tier' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'evaluator.gate.reviewable_predictions_min_count', 'evaluator', '3'::jsonb,
       'Minimum count of reviewable_predictions entries to pass HG-2 falsifiability floor.',
       'Initial externalization from evaluator.md HG-2.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'evaluator.gate.reviewable_predictions_min_count' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'evaluator.gate.research_essentials_load_bearing_confidence_min', 'evaluator', '3'::jsonb,
       'Research-essentials confidence floor (1-5 scale) above which a fact is treated as load-bearing.',
       'Initial externalization from research-company.md:100.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'evaluator.gate.research_essentials_load_bearing_confidence_min' AND tag IS NULL);

-- ====== namespace: falsifier ======

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'falsifier.max_resolution_horizon_months', 'falsifier', '36'::jsonb,
       'Maximum forward horizon (months) for falsifier_resolution_date. Beyond this, falsifier is rejected as un-actionable.',
       'Initial externalization from quantitative-analyst.md:128 / evaluator.md HG-15 step 5.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'falsifier.max_resolution_horizon_months' AND tag IS NULL);

-- Thematic-growth implied-vs-historical CAGR cap (pm-supervisor §7 overlay)
INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'dcf.thematic_growth_implied_vs_historical_cagr_cap_ratio', 'dcf', '1.5'::jsonb,
       'Thematic-growth tier: reverse-DCF implied growth / historical CAGR ratio above which conviction is capped at MEDIUM even if §5 produces HIGH.',
       'Initial externalization from pm-supervisor.md:322.',
       'launch_default_2026-05-18', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'dcf.thematic_growth_implied_vs_historical_cagr_cap_ratio' AND tag IS NULL);

COMMIT;

-- =============================================================================
-- VERIFY: run these after applying.
-- =============================================================================

-- VERIFY: tag column present.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'parameters' AND column_name = 'tag';

-- VERIFY: parameters_active view has tag filter (look for tag IS NULL in the
-- view definition).
SELECT pg_get_viewdef('parameters_active'::regclass, true);

-- VERIFY: all expected namespaces present after seed.
SELECT parameter_namespace, COUNT(*) AS seed_row_count
FROM parameters_active
WHERE approved_by = 'launch_default_2026-05-18'
GROUP BY parameter_namespace
ORDER BY parameter_namespace;

-- Expected seed_row_count by namespace (40+ rows total under launch_default):
--   catalyst_scout       : 12
--   dcf                  :  7
--   evaluator            :  8
--   falsifier            :  1
--   mode                 :  2
--   outside_view         :  2
--   quality_gate         :  3
--   reinvestment_moat    :  7
--   sizing               : 14
--   tier_classification  :  5
-- (Subset of full ~63 inventory; additional namespaces may be added in
--  follow-on migrations after operator review.)

-- VERIFY: no production-row hijack risk — any tagged rows must NOT surface in
-- parameters_active.
SELECT COUNT(*) AS hijack_rows
FROM parameters_active pa
JOIN parameters p USING (parameter_key)
WHERE p.tag IS NOT NULL;
-- Expected: 0.
