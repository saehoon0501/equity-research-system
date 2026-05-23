-- =============================================================================
-- Migration: 043_reversion_overlay_parameters
-- Purpose:   Seed parameter rows for the v0.4.0 mean-reversion-overlay (standalone
--            mean-reversion sub-signal). Mirrors migration 039 (flow-overlay
--            parameters) in structure and idempotency discipline.
--
--            Reference: /Users/sehoonbyun/.claude/plans/no-pm-supervisor-integration-yet-smooth-cascade.md
--                       src/p10_reversion_overlay/bin_classifier.py (defaults)
--
--            Single namespace (no disposition / cell rows in v0.4.0 standalone scope):
--            - reversion.*  (10 rows; technical mean-reversion classifier params)
--
-- Schema choice:
--   - All rows tag=NULL (launch_default production governance).
--   - parameters table append-only (mig 004 trigger unchanged).
--   - Idempotent: each INSERT guarded by NOT EXISTS on (parameter_key, tag IS NULL).
--
-- Scope discipline (twice-narrowed per operator directive):
--   - v0.4.0 = STANDALONE subagent only. No pm-supervisor integration. No
--     /research-company orchestrator integration.
--   - Therefore NO `reversion_disposition.*` mapping rows (would be needed for
--     pm-supervisor cell completion in v0.4.2+).
--   - Therefore NO `reversion_cell.*` rows.
--   - Therefore NO `sizing.*` new rows (existing conviction-band rows untouched).
--   - v0.4.1 will add /research-company Stage 1 dispatch (no new params).
--   - v0.4.2 will add disposition + cell namespaces when wiring to pm-supervisor.
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- reversion.* namespace (10 rows; v0.4.0 standalone mean-reversion classifier)
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reversion.lookback_trading_days', 'reversion', '252'::jsonb,
       '12-month lookback in trading days for drawdown-from-high computation.',
       'v0.4.0 lock; matches flow.lookback_trading_days + tactical.lookback_trading_days for cross-overlay consistency.',
       'launch_default_2026-05-24', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reversion.lookback_trading_days' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reversion.drawdown_252d_threshold_pct', 'reversion', '40'::jsonb,
       'Drawdown-from-252d-high percentage threshold for MR_OVERSOLD bin trigger (all-three-fire AND-gate).',
       'v0.4.0 PLACEHOLDER per plan Open Questions; calibrated by CRWD-2026-03 case study (CRWD bottomed at $343, 50% off $700 peak — must fire).',
       'launch_default_2026-05-24', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reversion.drawdown_252d_threshold_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reversion.rsi_14_oversold_threshold', 'reversion', '30'::jsonb,
       'RSI(14) at/below this threshold votes oversold sub-signal (standard Wilder).',
       'v0.4.0 lock per Wilder 1978 canonical threshold.',
       'launch_default_2026-05-24', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reversion.rsi_14_oversold_threshold' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reversion.rsi_14_overbought_threshold', 'reversion', '70'::jsonb,
       'RSI(14) at/above this threshold votes overbought sub-signal (standard Wilder).',
       'v0.4.0 lock per Wilder 1978 canonical threshold.',
       'launch_default_2026-05-24', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reversion.rsi_14_overbought_threshold' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reversion.bollinger_lower_band_pct', 'reversion', '-2.0'::jsonb,
       'Bollinger Band position (in σ-units) at/below this votes lower-band-extreme sub-signal.',
       'v0.4.0 lock; standard 2σ band.',
       'launch_default_2026-05-24', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reversion.bollinger_lower_band_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reversion.bollinger_upper_band_pct', 'reversion', '2.0'::jsonb,
       'Bollinger Band position (in σ-units) at/above this votes upper-band-extreme sub-signal.',
       'v0.4.0 lock; symmetric 2σ band.',
       'launch_default_2026-05-24', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reversion.bollinger_upper_band_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reversion.ma_distance_overbought_pct', 'reversion', '25'::jsonb,
       'Distance from MA200 (percentage above) at/above which MR_OVERBOUGHT sub-signal fires.',
       'v0.4.0 PLACEHOLDER per plan Open Questions; calibrate against CRWD 2025-10 peak when distance was ~30-35%.',
       'launch_default_2026-05-24', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reversion.ma_distance_overbought_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reversion.ma_short_window', 'reversion', '20'::jsonb,
       'Short MA window for Bollinger Band centerline (standard).',
       'v0.4.0 lock.',
       'launch_default_2026-05-24', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reversion.ma_short_window' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reversion.ma_long_window', 'reversion', '200'::jsonb,
       'Long MA window for trend-distance sub-signal (standard 200-day).',
       'v0.4.0 lock; matches flow.ma_long_window.',
       'launch_default_2026-05-24', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reversion.ma_long_window' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'reversion.rsi_window', 'reversion', '14'::jsonb,
       'RSI lookback period (standard Wilder 14-day).',
       'v0.4.0 lock per Wilder 1978; v0.4.1 backtest can revisit 21d alternative.',
       'launch_default_2026-05-24', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'reversion.rsi_window' AND tag IS NULL);

COMMIT;
