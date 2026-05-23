-- =============================================================================
-- Migration: 039_flow_overlay_parameters
-- Purpose:   Seed parameter rows for the v0.1 flow-overlay (CTA-proximity
--            sub-signal). Mirrors migration 038 (tactical-overlay parameters)
--            in structure and idempotency discipline.
--
--            Reference: plans/first-let-s-plan-the-serialized-hanrahan.md
--                       src/p9_flow_overlay/bin_classifier.py (defaults)
--
--            Rows split across 4 namespaces (3 flow-overlay-specific + 1 cross-cutting sizing.*):
--            - flow.*               (10 rows; CTA-proximity classifier params)
--            - flow_disposition.*   (13 rows; 12 mapping cells + surface flag)
--            - flow_cell.*          (1 row;  disagreement alert method)
--            - sizing.*             (4 rows; catalyst+flow composition scalers — consumed by pm-supervisor)
--
-- Schema choice:
--   - All rows tag=NULL (launch_default production governance).
--   - parameters table append-only (mig 004 trigger unchanged).
--   - Idempotent: each INSERT guarded by NOT EXISTS on (parameter_key, tag IS NULL).
--   - mapping enum values stored as JSONB strings (e.g., '"BUY-HIGH"'::jsonb).
--
-- Scope discipline:
--   - v0.1 = CTA-proximity sub-signal only (price-only inputs).
--   - v0.2 will add `flow.gamma_*` keys + ERP-injection params after observing
--     real-data behavior of v0.1.
--   - v0.3 will add `flow.crowding_*` keys (SI / DTC / 13F).
--   - POSITIVE_BIN_THRESHOLD / NEGATIVE_BIN_THRESHOLD ship at +0.5 / -0.5 as
--     placeholder defaults; /review-me delivers final calibrated values after
--     Phase 1 observation.
--
-- Dependencies:
--   - 033_parameters_seed_research_company (base seed + tag column).
--   - 038_tactical_overlay_parameters (sister overlay; shares
--     sizing.conviction_band.* params).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/039_flow_overlay_parameters.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- flow.* namespace (10 rows; v0.1 CTA-proximity composite classifier)
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.lookback_trading_days', 'flow', '252'::jsonb,
       '12-month lookback in trading days for TSMOM sub-signal (Antonacci canonical).',
       'v0.1 lock; matches tactical.lookback_trading_days for cross-overlay consistency.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.lookback_trading_days' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.ma_short_window', 'flow', '50'::jsonb,
       'Short moving-average window for MA-distance sub-signal (classic 50-day SMA).',
       'v0.1 lock per Goldman PB reverse-engineering convention for CTA trigger proxies.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.ma_short_window' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.ma_long_window', 'flow', '200'::jsonb,
       'Long moving-average window for MA-distance sub-signal (classic 200-day SMA).',
       'v0.1 lock per Goldman PB reverse-engineering convention.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.ma_long_window' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.donchian_high_window', 'flow', '55'::jsonb,
       'Donchian high-channel window (Turtle 55-day breakout entry).',
       'v0.1 lock per classic Turtle trader codification (Hurst/Ooi/Pedersen century-of-evidence basis).',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.donchian_high_window' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.donchian_low_window', 'flow', '20'::jsonb,
       'Donchian low-channel window (Turtle 20-day breakdown exit).',
       'v0.1 lock per classic Turtle trader codification.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.donchian_low_window' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.donchian_bullish_fraction', 'flow', '0.75'::jsonb,
       'Position-in-range fraction at/above which Donchian sub-signal votes BULLISH (upper quartile).',
       'v0.1 placeholder; /review-me may diverge.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.donchian_bullish_fraction' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.donchian_bearish_fraction', 'flow', '0.25'::jsonb,
       'Position-in-range fraction at/below which Donchian sub-signal votes BEARISH (lower quartile).',
       'v0.1 placeholder; /review-me may diverge.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.donchian_bearish_fraction' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.positive_bin_threshold', 'flow', '0.5'::jsonb,
       'Normalized composite_score at/above which flow_signal_bin = positive. Range [-1.0, +1.0].',
       'v0.1 PLACEHOLDER per plan Open Items; final value via /review-me after Phase 1 observation.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.positive_bin_threshold' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.negative_bin_threshold', 'flow', '-0.5'::jsonb,
       'Normalized composite_score at/below which flow_signal_bin = negative. Range [-1.0, +1.0].',
       'v0.1 PLACEHOLDER per plan Open Items; final value via /review-me after Phase 1 observation.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.negative_bin_threshold' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow.benchmark_symbol', 'flow', '"SPY"'::jsonb,
       'Benchmark symbol for market-level CTA-proximity context (mirrors tactical.benchmark_symbol).',
       'v0.1 lock; cross-overlay consistency with tactical-overlay benchmark.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow.benchmark_symbol' AND tag IS NULL);

-- NOTE: flow.unavailable_handling was DROPPED post /review-me iteration 1 polish
-- review — the value was documentation-as-parameter (no code path read it).
-- The unavailable handling is enforced in bin_classifier.py (distinct return
-- value) + overlay.py (band.min fallback), both of which are code-level
-- invariants, not parameter-table tunables.

-- -----------------------------------------------------------------------------
-- flow_disposition.* mapping (12 cells + 1 surface flag = 13 rows)
-- v0.1 default mapping mirrors tactical_disposition for cross-overlay
-- consistency. /review-me may diverge specific cells once flow signal
-- behavior is observed.
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_disposition.mapping.HIGH_negative', 'flow_disposition', '"HOLD"'::jsonb,
       'HIGH conviction × negative flow_bin → HOLD (no TRIM/SELL from overlay).',
       'v0.1 default; mirrors tactical_disposition.mapping.HIGH_negative.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_disposition.mapping.HIGH_negative' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_disposition.mapping.HIGH_neutral', 'flow_disposition', '"HOLD"'::jsonb,
       'HIGH conviction × neutral flow_bin → HOLD.',
       'v0.1 default; mirrors tactical_disposition.mapping.HIGH_neutral.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_disposition.mapping.HIGH_neutral' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_disposition.mapping.HIGH_positive', 'flow_disposition', '"BUY-HIGH"'::jsonb,
       'HIGH conviction × positive flow_bin → BUY-HIGH (high-conviction concurrent flow confirmation).',
       'v0.1 lock; INV-FLOW-2.1-A: disjoint from canonical summary_code enum.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_disposition.mapping.HIGH_positive' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_disposition.mapping.HIGH_unavailable', 'flow_disposition', '"HOLD"'::jsonb,
       'HIGH conviction × unavailable flow_bin → HOLD (data-insufficiency defers).',
       'v0.1 default; mirrors tactical pattern.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_disposition.mapping.HIGH_unavailable' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_disposition.mapping.MEDIUM_negative', 'flow_disposition', '"HOLD"'::jsonb,
       'MEDIUM conviction × negative flow_bin → HOLD.',
       'v0.1 default; mirrors tactical_disposition.mapping.MEDIUM_negative.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_disposition.mapping.MEDIUM_negative' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_disposition.mapping.MEDIUM_neutral', 'flow_disposition', '"HOLD"'::jsonb,
       'MEDIUM conviction × neutral flow_bin → HOLD.',
       'v0.1 default; mirrors tactical_disposition.mapping.MEDIUM_neutral.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_disposition.mapping.MEDIUM_neutral' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_disposition.mapping.MEDIUM_positive', 'flow_disposition', '"BUY-MED"'::jsonb,
       'MEDIUM conviction × positive flow_bin → BUY-MED. Open question: whether flow signal warrants the same load-bearing case as tactical (review after Phase 1).',
       'v0.1 default; INV-FLOW-2.1-A: disjoint from canonical summary_code enum.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_disposition.mapping.MEDIUM_positive' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_disposition.mapping.MEDIUM_unavailable', 'flow_disposition', '"HOLD"'::jsonb,
       'MEDIUM conviction × unavailable flow_bin → HOLD (data-insufficiency defers).',
       'v0.1 default.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_disposition.mapping.MEDIUM_unavailable' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_disposition.mapping.LOW_negative', 'flow_disposition', '"AVOID"'::jsonb,
       'LOW conviction × negative flow_bin → AVOID (LOW-row discipline; flow cannot rescue).',
       'v0.1 default; mirrors tactical pattern.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_disposition.mapping.LOW_negative' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_disposition.mapping.LOW_neutral', 'flow_disposition', '"AVOID"'::jsonb,
       'LOW conviction × neutral flow_bin → AVOID.',
       'v0.1 default; mirrors tactical pattern.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_disposition.mapping.LOW_neutral' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_disposition.mapping.LOW_positive', 'flow_disposition', '"AVOID"'::jsonb,
       'LOW conviction × positive flow_bin → AVOID (LOW-row veto; surfaces via LOW-CONVICTION VETO label).',
       'v0.1 default; mirrors tactical_disposition.mapping.LOW_positive.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_disposition.mapping.LOW_positive' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_disposition.mapping.LOW_unavailable', 'flow_disposition', '"HOLD"'::jsonb,
       'LOW conviction × unavailable flow_bin → HOLD (data-insufficiency defers; no double-penalty).',
       'v0.1 default; mirrors tactical_disposition.mapping.LOW_unavailable.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_disposition.mapping.LOW_unavailable' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_disposition.surface_with_summary_code', 'flow_disposition', 'true'::jsonb,
       'Operator-facing report surfaces both flow_disposition AND pm-supervisor summary_code (soft-modulator).',
       'v0.1 lock; mirrors tactical_disposition.surface_with_summary_code.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_disposition.surface_with_summary_code' AND tag IS NULL);

-- -----------------------------------------------------------------------------
-- flow_cell.* namespace (1 row; disagreement alert method)
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'flow_cell.disagreement_alert_pp_method', 'flow_cell', '"half_band_width"'::jsonb,
       'Disagreement threshold method (matches tactical_cell.disagreement_alert_pp_method).',
       'v0.1 lock; same half-band-width discipline that fires meaningfully inside both HIGH and MEDIUM bands.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'flow_cell.disagreement_alert_pp_method' AND tag IS NULL);

-- -----------------------------------------------------------------------------
-- sizing.* additions (4 rows; consumed by pm-supervisor's catalyst+flow modifier
-- composition helper at src/p7_recommendation_emitter/catalyst_flow_modifier.py).
--
-- Convention: integer percent values (25 = 25%); pm-supervisor agent prose
-- documents the /100 conversion before passing into the helper.
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.catalyst_modifier_magnitude_scaler.low', 'sizing', '5'::jsonb,
       'Catalyst magnitude=low scaler (% of base_midpoint per unit of catalyst_direction). 5 = 5%.',
       'v0.1 deterministic catalyst+flow composition helper requires explicit magnitude scaling per /review-me #2.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.catalyst_modifier_magnitude_scaler.low' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.catalyst_modifier_magnitude_scaler.medium', 'sizing', '10'::jsonb,
       'Catalyst magnitude=medium scaler (% of base_midpoint per unit of catalyst_direction). 10 = 10%.',
       'v0.1 deterministic catalyst+flow composition helper.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.catalyst_modifier_magnitude_scaler.medium' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.catalyst_modifier_magnitude_scaler.high', 'sizing', '20'::jsonb,
       'Catalyst magnitude=high scaler (% of base_midpoint per unit of catalyst_direction). 20 = 20%.',
       'v0.1 deterministic catalyst+flow composition helper.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.catalyst_modifier_magnitude_scaler.high' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'sizing.flow_modifier_pp_per_unit', 'sizing', '5'::jsonb,
       'Flow modifier per-unit contribution (% of base_midpoint per unit of flow_sign in {-1, 0, +1}). 5 = 5%.',
       'v0.1 keep flow smaller than catalyst-high so flow remains a modulator, not dominant signal. /review-me delivers final tuning after Phase 1 observation.',
       'launch_default_2026-05-23', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'sizing.flow_modifier_pp_per_unit' AND tag IS NULL);

COMMIT;

-- Verify row count: 28 INSERTs above (10 flow + 13 flow_disposition + 1 flow_cell + 4 sizing).
-- Confirm via:
--   SELECT COUNT(*) FROM parameters_active
--   WHERE parameter_namespace IN ('flow', 'flow_disposition', 'flow_cell')
--     OR parameter_key IN (
--       'sizing.catalyst_modifier_magnitude_scaler.low',
--       'sizing.catalyst_modifier_magnitude_scaler.medium',
--       'sizing.catalyst_modifier_magnitude_scaler.high',
--       'sizing.flow_modifier_pp_per_unit'
--     );
-- Expected: 28.
