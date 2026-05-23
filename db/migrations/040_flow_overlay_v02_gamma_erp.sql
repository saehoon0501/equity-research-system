-- =============================================================================
-- Migration: 040_flow_overlay_v02_gamma_erp
-- Purpose:   Seed parameter rows for the v0.2 flow-overlay activation —
--            gamma-regime sub-signal config + ERP injection magnitudes
--            consumed by quantitative-analyst + externalized TECH-axis cutoff.
--
--            Reference: plans/first-let-s-plan-the-serialized-hanrahan.md
--                       (v0.2 plan, /review-me-approved 2026-05-23)
--
--            Rows split across 2 namespaces:
--            - flow.*    (11 rows: 8 gamma-regime config + 3 erp_add_bps)
--            - sizing.*  (1 row: tech_axis_bullish_score_min externalized)
--
-- Schema choice:
--   - All rows tag=NULL (launch_default production governance).
--   - parameters table append-only (mig 004 trigger unchanged).
--   - Idempotent: each INSERT guarded by NOT EXISTS on (parameter_key, tag IS NULL).
--   - String enum values stored as JSONB strings ('"spotgamma"'::jsonb).
--
-- Scope discipline:
--   - v0.2 ships placeholder values where /review-me will deliver the final
--     calibrated values (mirrors v0.1's POSITIVE_BIN_THRESHOLD discipline).
--   - 4 forced choices are explicitly flagged in change_rationale:
--     1. Dealer-sign convention (SpotGamma vs SqueezeMetrics)
--     2. Regime-flip signal method (zero-gamma inflection vs Volatility Trigger)
--     3. erp_add_bps magnitudes per gamma_bin (Bonelli 2025 caveat)
--     4. gex_*_bin_threshold normalization formula (Vasquez 2025 caveat)
--
-- Dependencies:
--   - 033_parameters_seed_research_company (base seed + tag column).
--   - 038_tactical_overlay_parameters (sister tactical overlay).
--   - 039_flow_overlay_parameters (v0.1 CTA-proximity params; required because
--     v0.2 extends the flow.* namespace).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U <user> -d equity_research \
--        -f db/migrations/040_flow_overlay_v02_gamma_erp.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- flow.* gamma-regime classifier params (8 rows)
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.gex_dealer_sign_convention', 'flow', '"spotgamma"'::jsonb,
       'Dealer-sign convention for per-strike GEX aggregation. spotgamma = dealers long calls (+1) / short puts (-1). Alternative: squeezemetrics convention.',
       'v0.2 default; Amaya 2025 (Cboe) does NOT resolve dealer-sign for OPRA feeds (paper uses Cboe-internal trade-capacity flags); SpotGamma chosen as closer to Amaya finding "aggregate OMM gamma typically positive". FORCED CHOICE per /review-me iter-1 research.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.gex_dealer_sign_convention' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.gex_regime_flip_signal_method', 'flow', '"zero_gamma_inflection"'::jsonb,
       'Regime-flip signal construction method. zero_gamma_inflection = BS-repriced spot where aggregate GEX crosses zero. Alternative: volatility_trigger (last positive-gamma support strike).',
       'v0.2 default; no published empirical preference between methods. FORCED CHOICE per /review-me iter-1 research.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.gex_regime_flip_signal_method' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.gex_dte_bucket_boundaries', 'flow', '"0,7,30,90"'::jsonb,
       'DTE bucket boundaries (days) — aggregator buckets: 0DTE / 1-7d / 8-30d / 31-90d / 90d+. 0DTE separation mandatory per Vasquez 2025 (Cboe Jan): 0DTE is ~57% of SPX volume Q3 2025.',
       'v0.2 lock; Cboe Q3 2025 0DTE share grounds the separation.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.gex_dte_bucket_boundaries' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.gex_positive_bin_threshold_normalized', 'flow', '0.05'::jsonb,
       'Normalized net-GEX threshold above which gamma_bin = positive (dampening regime). Ticker-normalized (net_gex / (spot^2 * 100)) per Vasquez 2025 finding that absolute OMM gamma is 0.04-0.17% of S&P futures daily liquidity.',
       'v0.2 PLACEHOLDER per plan Open Items; final value via /review-me after Phase 1 observation. Normalization formula (vs trailing-30d notional? vs avg daily futures volume?) is itself a /review-me choice.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.gex_positive_bin_threshold_normalized' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.gex_negative_bin_threshold_normalized', 'flow', '-0.05'::jsonb,
       'Normalized net-GEX threshold below which gamma_bin = negative (procyclical regime). Ticker-normalized per Vasquez 2025.',
       'v0.2 PLACEHOLDER per plan Open Items; final value via /review-me.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.gex_negative_bin_threshold_normalized' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.gex_zero_gamma_grid_pct', 'flow', '0.10'::jsonb,
       'BS re-pricing spot grid range (fractional, ±10%) for zero-gamma level construction.',
       'v0.2 lock; 10% covers all but extreme intraday moves.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.gex_zero_gamma_grid_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.gex_zero_gamma_grid_steps', 'flow', '20'::jsonb,
       'Number of linear spot grid points for BS re-pricing (incl endpoints). Higher = finer zero-gamma estimate; 20 gives ~1% resolution across the ±10% range.',
       'v0.2 lock; matches practitioner conventions.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.gex_zero_gamma_grid_steps' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.gex_bs_risk_free_rate_series', 'flow', '"DGS3MO"'::jsonb,
       'FRED series for BS risk-free rate input (3-month T-bill matches typical sub-90DTE options book duration).',
       'v0.2 lock; matches standard BS practitioner convention.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.gex_bs_risk_free_rate_series' AND tag IS NULL);

-- -----------------------------------------------------------------------------
-- flow.erp_add_bps.* — ERP regime-adjustment magnitudes (3 rows)
-- Consumed by quantitative-analyst at line 96: erp_adjusted = wacc.erp + flow_modifier.erp_add_bps / 100
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.erp_add_bps.gamma_positive', 'flow', '0'::jsonb,
       'Basis-points added to ERP when gamma_regime.bin = positive. 0 = no adjustment (positive gamma is stabilizing, no risk premium uplift).',
       'v0.2 PLACEHOLDER per plan Open Items; final value via /review-me. Bonelli SSRN 5227231 (2025) finds VIX has no statistical significance in 2015-2025 ERP determination — the entire gamma->ERP linkage is ungrounded conjecture, not academically validated.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.erp_add_bps.gamma_positive' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.erp_add_bps.gamma_neutral', 'flow', '0'::jsonb,
       'Basis-points added to ERP when gamma_regime.bin = neutral. 0 = no adjustment.',
       'v0.2 PLACEHOLDER per plan Open Items. Bonelli 2025 caveat applies (ungrounded linkage).',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.erp_add_bps.gamma_neutral' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.erp_add_bps.gamma_negative', 'flow', '50'::jsonb,
       'Basis-points added to ERP when gamma_regime.bin = negative (procyclical / dealer-short-gamma regime). +50bp = conservative midpoint of Damodaran historical stress range (+14bp Mar 2026 Middle East to +400bp+ 2008 GFC).',
       'v0.2 PLACEHOLDER per plan Open Items. THE ENTIRE gamma->ERP LINKAGE IS ACADEMICALLY UNGROUNDED per Bonelli SSRN 5227231 (2025); /review-me should consider whether to ship this adjustment AT ALL in v0.2 or defer to v0.3 with more empirical foundation.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.erp_add_bps.gamma_negative' AND tag IS NULL);

-- -----------------------------------------------------------------------------
-- sizing.* — TECH-axis cutoff externalized (1 row)
-- Was hardcoded "+3" in pm-supervisor.md prose for v0.1 5-signal world.
-- v0.2 6-signal world needs recalibration; externalizing means future recalibrations
-- become parameter updates, not markdown PRs.
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.tech_axis_bullish_score_min', 'sizing', '4'::jsonb,
       'TECH axis BULLISH cutoff: tech_axis_score >= this value triggers BULLISH verdict. v0.2 default 4 per uniform-distribution math (6 signals where each is +1/0/-1 with p(+1)~=p(-1)~=0.25; adding a 6th vote roughly doubles P(score>=+3) at the prior cutoff, so cutoff bumps to +4 to preserve prior fire rate). Real CTA-proximity + gamma signals are correlated under stress so actual calibration may need >=+5.',
       'v0.2 atomic flip (per pm-supervisor.md §7.6 HTML-comment checklist from v0.1). Externalized from prose so /review-me recalibrations become parameter updates.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.tech_axis_bullish_score_min' AND tag IS NULL);

COMMIT;

-- Verify row count: 12 INSERTs above (8 flow.gex_* + 3 flow.erp_add_bps.* + 1 sizing.tech_axis_bullish_score_min).
-- Confirm via:
--   SELECT COUNT(*) FROM parameters_active
--   WHERE parameter_key IN (
--     'flow.gex_dealer_sign_convention',
--     'flow.gex_regime_flip_signal_method',
--     'flow.gex_dte_bucket_boundaries',
--     'flow.gex_positive_bin_threshold_normalized',
--     'flow.gex_negative_bin_threshold_normalized',
--     'flow.gex_zero_gamma_grid_pct',
--     'flow.gex_zero_gamma_grid_steps',
--     'flow.gex_bs_risk_free_rate_series',
--     'flow.erp_add_bps.gamma_positive',
--     'flow.erp_add_bps.gamma_neutral',
--     'flow.erp_add_bps.gamma_negative',
--     'sizing.tech_axis_bullish_score_min'
--   );
-- Expected: 12.
