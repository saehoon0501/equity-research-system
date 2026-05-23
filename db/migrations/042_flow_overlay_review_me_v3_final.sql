-- =============================================================================
-- Migration: 042_flow_overlay_review_me_v3_final
-- Purpose:   /review-me v3-final calibration updates from the 2026-05-23
--            adversarial review of 8 deferred Open Items shipped in v0.2 (040)
--            and v0.3 (041).
--
--            Reference: plans/first-let-s-plan-the-serialized-hanrahan.md
--                       + /review-me convergence record (3 iterations)
--
--            Rows: 4 INSERTs (3 overrides + 1 new param) in `flow.*` namespace.
--            The parameters table is APPEND-ONLY per migration 004 trigger —
--            "updates" are INSERTs with later effective_at; the parameters_active
--            view surfaces the latest row per parameter_key.
--
-- v3-final summary (full record in /Users/sehoonbyun/.claude/plans/ ...):
--
--   OI-1 dealer_sign            — KEEP (spotgamma; Brogaard 2024 + Garleanu 2009)
--   OI-2 gex normalization      — CHANGE formula `net_gex_per_1pct / notional_ADV_30d`
--                                 + thresholds ±0.25 + winsorize bin-classification at ±2.0
--                                 (Vasquez 2025 own ADV-normalization + SpotGamma GEX/ADV)
--   OI-3 erp_add_bps.gamma_neg  — CHANGE +50 → +25bp; rationale shifts FROM Bonelli
--                                 (orthogonal unconditional VIX null) TO Barberis 2018
--                                 episode-conditional + ACM 2013 90th-pctile
--   OI-4 regime_flip method     — KEEP (zero_gamma_inflection; Tier1Alpha 2024 overlap)
--   OI-5 DTC threshold          — KEEP (5.0; S3 Partners Tier-2 + Hong-Kubik-Fishman 2012)
--   OI-6 SI/float threshold     — KEEP (0.20; Asquith-Pathak-Ritter 2005 + FINRA Reg-SHO)
--   OI-7 logic_operator         — KEEP (AND; defer severity-tier escape to v0.4 alongside
--                                 §7.6 cutoff recalibration; observed-data backing required)
--   OI-8 stale_max_days         — KEEP (21; FINRA bi-weekly cadence)
--
-- v0.4 punch-list (for follow-on review-me + spec):
--   - §7.6 BUY cutoff recalibration (compound v3 effect ~20-25% BUY fire-rate drop)
--   - OI-7 severity-tier: `(SI/float ≥ 0.30) OR (DTC ≥ 5.0 AND SI/float ≥ 0.20)`
--     pending observed-data backing for the new 0.30 threshold
--
-- Idempotency: each INSERT guarded by NOT EXISTS on (parameter_key, approved_by)
--              — this specific override row keyed by approved_by tag; re-running
--              this migration is safe.
--
-- Dependencies:
--   - 040_flow_overlay_v02_gamma_erp (overrides 2 rows from 040)
--   - 041_flow_overlay_v03_crowding   (no row touched — all 4 v0.3 items KEEP)
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U <user> -d equity_research \
--        -f db/migrations/042_flow_overlay_review_me_v3_final.sql
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- OI-2: gex bin thresholds (formula change + magnitude change)
--
-- v1 (040): ±0.05 with formula `net_gex / (spot^2 * 100)` — produced AAPL smoke
--           normalized_gex=24.6, a dimensionally-incoherent 490× gap.
-- v3-final: ±0.25 with formula `net_gex_per_1pct_move / notional_ADV_30d`.
--           Winsorize bin-classification only at ±2.0; raw value retained +
--           telemetry-alerted when raw > 2.0 so true squeeze episodes surface
--           as named events rather than getting silently absorbed.
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.gex_positive_bin_threshold_normalized', 'flow', '0.25'::jsonb,
       'Normalized net-GEX threshold above which gamma_bin = positive (dampening regime). Normalization formula updated to net_gex_per_1pct_move / notional_ADV_30d per Vasquez 2025 own usage + SpotGamma GEX/ADV ratio convention. Bin classification winsorized at ±2.0 (see flow.gex_bin_winsorize_at); raw ratio retained for telemetry alerting.',
       'v3-final override per /review-me 2026-05-23; HIGH severity — original ±0.05 + `net_gex/(spot^2*100)` formula produced dimensionally-incoherent AAPL smoke result (normalized_gex=24.6, 490× over threshold). Anchored in Vasquez 2025 (own ADV-normalization) + SpotGamma published GEX/ADV ratio (regime flips 0.5-1.0) + Tier1Alpha 2024 backtests (SPX July 2023, NVDA May 2024 cluster at 0.3-0.8). Single-name dispersion wider than index; threshold +30-day telemetry re-baseline plan. Bin classification winsorized at ±2.0 (see flow.gex_bin_winsorize_at); raw retained for alerting.',
       'review_me_v3_final_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.gex_positive_bin_threshold_normalized' AND approved_by = 'review_me_v3_final_2026-05-23');

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.gex_negative_bin_threshold_normalized', 'flow', '-0.25'::jsonb,
       'Normalized net-GEX threshold below which gamma_bin = negative (procyclical regime). Mirrors positive threshold per the new ADV-normalization (see flow.gex_positive_bin_threshold_normalized change_rationale).',
       'v3-final override per /review-me 2026-05-23. See flow.gex_positive_bin_threshold_normalized change_rationale for full reasoning.',
       'review_me_v3_final_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.gex_negative_bin_threshold_normalized' AND approved_by = 'review_me_v3_final_2026-05-23');

-- -----------------------------------------------------------------------------
-- OI-2 (new): gex_bin_winsorize_at — bin-classification winsorization bound
--
-- New parameter introduced by v3-final. Applies only to bin classification
-- (i.e., the comparison against ±threshold); the raw normalized_gex value
-- is preserved in the envelope so true squeeze episodes (raw ratio > 2.0)
-- surface as named telemetry events rather than getting silently absorbed
-- into the bin.
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.gex_bin_winsorize_at', 'flow', '2.0'::jsonb,
       'Winsorization bound (absolute value) applied to normalized_gex BEFORE bin classification. Raw normalized_gex is retained in the envelope and telemetry-alerted when abs(raw) > this bound. Prevents single-name dispersion (raw can exceed 1.0 for ultra-illiquid + concentrated-OI names) from one-tail-dominating the ±0.25 threshold calibration.',
       'v3-final per /review-me 2026-05-23. Scoped to bin-classification only; preserves raw value + alerting on true squeeze episodes. Sized at ±2.0 to allow normal mid-cap dispersion without capping mid-range, but bound extreme excursions before they shift bin distribution. Tier1Alpha 2024 published extreme-gamma episodes top out 0.3-0.8 on the ADV-normalized metric for indices; single-name dispersion can reach 1.5-2.0 in normal regimes.',
       'review_me_v3_final_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.gex_bin_winsorize_at' AND approved_by = 'review_me_v3_final_2026-05-23');

-- -----------------------------------------------------------------------------
-- OI-3: erp_add_bps.gamma_negative — magnitude reduction + rationale correction
--
-- v1 (040): +50bp with rationale citing Bonelli 2025 (VIX→ERP null) as caveat.
-- v3-final: +25bp; rationale shifts to Barberis 2018 + ACM 2013 episode-
--           conditional anchors. Bonelli 2025 tested UNCONDITIONAL VIX→ERP
--           and is ORTHOGONAL (not in conflict) to the regime-conditional
--           gamma→ERP linkage — Bonelli citation in 040 was a category error.
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.erp_add_bps.gamma_negative', 'flow', '25'::jsonb,
       'ERP add-on (basis points) consumed by quantitative-analyst when flow-overlay reports gamma_regime.bin = negative. Reduced from launch_default +50 → +25 per /review-me v3-final. Conservative midpoint of Barberis 2018 extrapolative-beliefs framework (20-40bp around dealer de-leveraging episodes) + ACM 2013 90th-percentile VIX-correlated risk-premium moves (~30bp at high-vol shock). The magnitude is still partially a forced choice (neither paper publishes a calibrated regime-conditional gamma→ERP threshold); +25bp is the lower-bound consistent with both anchors. Precise magnitude awaits regime-conditional telemetry.',
       'v3-final override per /review-me 2026-05-23. Literature implies ~20-40bp episode-conditional, not +50. Bonelli 2025 tested UNCONDITIONAL VIX→ERP (null) and is ORTHOGONAL to regime-conditional gamma→ERP (Barberis 2018 + ACM 2013) — Bonelli citation in migration 040 was a category error and is REMOVED from this overriding rationale. Magnitude remains a forced choice within the published range.',
       'review_me_v3_final_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.erp_add_bps.gamma_negative' AND approved_by = 'review_me_v3_final_2026-05-23');

-- -----------------------------------------------------------------------------
-- Expected row count after this migration: 4 new rows (overrides + new param).
-- The parameters_active view surfaces the latest row per parameter_key;
-- after this migration, OI-2 + OI-3 active values are v3-final (above), the
-- v1 (040) launch_default rows remain in the table for audit lineage.
--
-- Idempotent re-run will INSERT 0 additional rows.
--
-- v0.4 punch-list (NOT in this migration; documented for follow-on PR):
--   - §7.6 BUY cutoff recalibration (compound v3 effect ~20-25% BUY fire-rate drop)
--   - OI-7 severity-tier escape: `(SI/float ≥ 0.30) OR (DTC ≥ 5.0 AND SI/float ≥ 0.20)`
--     pending observed-data backing for the new 0.30 SI/float severity threshold
-- -----------------------------------------------------------------------------

COMMIT;
