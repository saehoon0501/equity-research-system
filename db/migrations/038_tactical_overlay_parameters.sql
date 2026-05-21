-- =============================================================================
-- Migration: 038_tactical_overlay_parameters
-- Purpose:   Seed 29 parameter rows for the Section 2 + Section 2.1 tactical
--            overlay implementation.
--
--            Reference: docs/superpowers/plans/2026-05-21-section2-tactical-overlay-v3-final.md
--                       docs/superpowers/consensus/2026-05-21-section2.1-label-vocabulary.md
--                       docs/superpowers/plans/2026-05-21-section3-tactical-overlay-impl.md
--
--            Rows split across 3 namespaces:
--            - tactical.*               (12 rows; Plan B v6 bin classifier)
--            - tactical_disposition.*   (13 rows; 12 mapping cells + surface flag)
--            - tactical_cell.*          (4 rows; disagreement alert + auto-review trigger)
--
-- Schema choice:
--   - All rows tag=NULL (launch_default production governance).
--   - parameters table append-only (mig 004 trigger unchanged).
--   - Idempotent: each INSERT guarded by NOT EXISTS on (parameter_key, tag IS NULL).
--   - mapping enum values stored as JSONB strings (e.g., '"BUY-HIGH"'::jsonb).
--
-- Dependencies:
--   - 033_parameters_seed_research_company (base seed + tag column).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/038_tactical_overlay_parameters.sql
--
-- Idempotency: safe to re-run.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- tactical.* namespace (12 rows; Plan B v6 — Antonacci dual-momentum classifier)
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical.positive_min', 'tactical', '0.0'::jsonb,
       'Antonacci canonical positive threshold: both relative AND absolute 12mo return >= this.',
       'Section 2 v3-final Plan B v6 lock; canonical binary at zero.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical.positive_min' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical.negative_max', 'tactical', '0.0'::jsonb,
       'Antonacci canonical negative threshold: both relative AND absolute 12mo return <= this.',
       'Section 2 v3-final Plan B v6 lock; canonical binary at zero.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical.negative_max' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical.lookback_trading_days', 'tactical', '252'::jsonb,
       'Antonacci 12-month lookback in trading days (~21 days/month × 12).',
       'Section 2 v3-final Plan B v6 lock.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical.lookback_trading_days' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical.skip_recent_month', 'tactical', 'false'::jsonb,
       'False = 12-0 convention (Antonacci canon). 12-1 (Jegadeesh-Titman) explicitly rejected.',
       'Section 2 v3-final Plan B v6 Q6 fix; canon-fidelity preserved.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical.skip_recent_month' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical.benchmark_symbol', 'tactical', '"SPY"'::jsonb,
       'Benchmark for relative momentum leg (Antonacci canonical).',
       'Section 2 v3-final Plan B v6 lock.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical.benchmark_symbol' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical.risk_free_series', 'tactical', '"DGS1"'::jsonb,
       'FRED series for absolute momentum leg (Antonacci 12-month T-bill prescription).',
       'Section 2 v3-final Plan B v6 lock.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical.risk_free_series' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical.risk_free_method', 'tactical', '"resolve_rf_at_helper"'::jsonb,
       'Method for resolving rf yield at window start (vs naive avg-of-window).',
       'Section 2 v3-final Plan B v6 Q2 fix; start-of-window yield, not average.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical.risk_free_method' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical.risk_free_max_staleness_calendar_days', 'tactical', '7'::jsonb,
       'Max calendar-day staleness for DGS1 lookup before rejecting as unavailable.',
       'Section 2 v3-final Plan B v6 lock; INV-B6 couples with WEEKEND_HOLIDAY_BUFFER_DAYS.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical.risk_free_max_staleness_calendar_days' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical.risk_free_degenerate_threshold_pct', 'tactical', '0.5'::jsonb,
       'rf_yield_pct < this threshold → tactical_rf_degenerate=true flag (ZIRP regime).',
       'Section 2 v3-final Plan B v6 Q4 fix; surfaces zero-rate regime.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical.risk_free_degenerate_threshold_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical.recompute_frequency', 'tactical', '"monthly"'::jsonb,
       'Antonacci canonical monthly rebalance discipline.',
       'Section 2 v3-final Plan B v6 lock.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical.recompute_frequency' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical.recompute_anchor', 'tactical', '"first_trading_day_of_month_using_prior_month_close"'::jsonb,
       'Intra-month timing anchor: first trading day, prior-month close prices.',
       'Section 2 v3-final Plan B v6 Q5 fix.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical.recompute_anchor' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical.unavailable_handling', 'tactical', '"emit_distinct_value_for_plan_c"'::jsonb,
       'Plan B emits unavailable as distinct return; Plan C gives it 4th column (band.min fallback).',
       'Section 2 v3-final Plan B v6 Q3 fix.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical.unavailable_handling' AND tag IS NULL);

-- -----------------------------------------------------------------------------
-- tactical_disposition.* mapping (12 cells + 1 surface flag = 13 rows)
-- Section 2.1 v5-final lock: BUY-HIGH (HIGH × Positive); BUY-MED (MEDIUM × Positive)
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.mapping.HIGH_negative', 'tactical_disposition', '"HOLD"'::jsonb,
       'HIGH conviction × negative tactical bin → HOLD (no TRIM/SELL from overlay).',
       'Section 2.1 v5-final categorical mapping.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.mapping.HIGH_negative' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.mapping.HIGH_neutral', 'tactical_disposition', '"HOLD"'::jsonb,
       'HIGH conviction × neutral tactical bin → HOLD.',
       'Section 2.1 v5-final categorical mapping.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.mapping.HIGH_neutral' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.mapping.HIGH_positive', 'tactical_disposition', '"BUY-HIGH"'::jsonb,
       'HIGH conviction × positive tactical bin → BUY-HIGH (rare; high-conviction concurrent confirmation).',
       'Section 2.1 v5-final lock; INV-2.1-A: disjoint from canonical summary_code enum.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.mapping.HIGH_positive' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.mapping.HIGH_unavailable', 'tactical_disposition', '"HOLD"'::jsonb,
       'HIGH conviction × unavailable tactical bin → HOLD (data-insufficiency defers).',
       'Section 2.1 v5-final categorical mapping.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.mapping.HIGH_unavailable' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.mapping.MEDIUM_negative', 'tactical_disposition', '"HOLD"'::jsonb,
       'MEDIUM conviction × negative tactical bin → HOLD.',
       'Section 2.1 v5-final categorical mapping.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.mapping.MEDIUM_negative' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.mapping.MEDIUM_neutral', 'tactical_disposition', '"HOLD"'::jsonb,
       'MEDIUM conviction × neutral tactical bin → HOLD.',
       'Section 2.1 v5-final categorical mapping.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.mapping.MEDIUM_neutral' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.mapping.MEDIUM_positive', 'tactical_disposition', '"BUY-MED"'::jsonb,
       'MEDIUM conviction × positive tactical bin → BUY-MED (LOAD-BEARING; empirical 83% MEDIUM base rate).',
       'Section 2.1 v5-final lock; INV-2.1-A: disjoint from canonical summary_code enum.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.mapping.MEDIUM_positive' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.mapping.MEDIUM_unavailable', 'tactical_disposition', '"HOLD"'::jsonb,
       'MEDIUM conviction × unavailable tactical bin → HOLD (data-insufficiency defers).',
       'Section 2.1 v5-final categorical mapping.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.mapping.MEDIUM_unavailable' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.mapping.LOW_negative', 'tactical_disposition', '"AVOID"'::jsonb,
       'LOW conviction × negative tactical bin → AVOID (LOW-row discipline; tactical cannot rescue).',
       'Section 2.1 v5-final categorical mapping.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.mapping.LOW_negative' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.mapping.LOW_neutral', 'tactical_disposition', '"AVOID"'::jsonb,
       'LOW conviction × neutral tactical bin → AVOID.',
       'Section 2.1 v5-final categorical mapping.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.mapping.LOW_neutral' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.mapping.LOW_positive', 'tactical_disposition', '"AVOID"'::jsonb,
       'LOW conviction × positive tactical bin → AVOID (LOW-row veto; surfaces via LOW-CONVICTION VETO label).',
       'Section 2.1 v5-final categorical mapping; v3 reframe.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.mapping.LOW_positive' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.mapping.LOW_unavailable', 'tactical_disposition', '"HOLD"'::jsonb,
       'LOW conviction × unavailable tactical bin → HOLD (v4 fix: data-insufficiency defers; no double-penalty).',
       'Section 2.1 v4 → v5-final lock; addresses v3 reviewer Finding #3.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.mapping.LOW_unavailable' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.surface_with_summary_code', 'tactical_disposition', 'true'::jsonb,
       'Operator-facing report surfaces both tactical_disposition AND pm-supervisor summary_code (Section 1 #4 soft-modulator).',
       'Section 2 v3-final lock.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.surface_with_summary_code' AND tag IS NULL);

-- -----------------------------------------------------------------------------
-- tactical_cell.* namespace (4 rows; disagreement alert + auto-review trigger)
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_cell.disagreement_alert_pp_method', 'tactical_cell', '"half_band_width"'::jsonb,
       'Disagreement threshold = 0.5 × band_width (HIGH: 1.5pp; MEDIUM: 0.75pp). Fires meaningfully inside both bands.',
       'Section 2.1 v4 fix per A-Q2 review (2pp absolute could not fire within MEDIUM 1.5pp band).',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_cell.disagreement_alert_pp_method' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.review_trigger.envelope_count', 'tactical_disposition', '50'::jsonb,
       'Phase 2 auto-review trigger: envelope_count >= this AND ticker_count >= 5.',
       'Section 2 v3-final Plan C v5 lock per Section 2.1 v3 Q3 fix.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.review_trigger.envelope_count' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.review_trigger.ticker_count', 'tactical_disposition', '5'::jsonb,
       'Phase 2 auto-review trigger: ticker_count >= this AND envelope_count >= 50.',
       'Section 2 v3-final Plan C v5 lock.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.review_trigger.ticker_count' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'tactical_disposition.review_trigger.calendar_fallback_days', 'tactical_disposition', '180'::jsonb,
       'Phase 2 calendar fallback: trigger fires 180d after Section 2.1 lock if envelope/ticker counts not met (ticker_count >= 3 required).',
       'Section 2 v3-final Plan C v5 lock; Section 2.1 v4 added min_tickers=3 gate.',
       'launch_default_2026-05-21', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'tactical_disposition.review_trigger.calendar_fallback_days' AND tag IS NULL);

COMMIT;

-- Verify row count: 29 INSERTs above (12 tactical + 13 tactical_disposition + 4 tactical_cell).
-- Confirm via:
--   SELECT COUNT(*) FROM parameters_active
--   WHERE parameter_namespace IN ('tactical', 'tactical_disposition', 'tactical_cell');
-- Expected: 29.
