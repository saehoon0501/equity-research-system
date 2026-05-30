-- =============================================================================
-- Migration: 050_survival_params_seed
-- Purpose:   Seed the `survival.*` parameter namespace for the survival-gate.
--            These are the pinned survival-domain thresholds consumed BY VALUE
--            at run start (P2, R10): snapshotted into `run_parameters_snapshot`
--            and resolved via `src/survival/params.py::resolve()`, which fails
--            CLOSED if any key is absent/malformed. Seed = the pinned production
--            defaults (`params.DEFAULTS`).
--
--            Reference: .kiro/specs/survival-gate/design.md
--                       §"Data Models → `survival.*` parameters"
--                       §"Allowed Dependencies" (the parameters / parameters_active
--                       / run_parameters_snapshot machinery, P2).
--                       src/survival/params.py (the SurvivalParameters dataclass
--                       + DEFAULTS + resolve()/_FLOAT_KEYS/_BOOL_KEYS).
--            Requirements: R10 (pinned params consumed by value; no fit).
--
--            Rows: 1 namespace, 7 rows (the COMPLETE set resolve() consumes):
--            - survival.*  (6 float thresholds + 1 bool toggle)
--
-- 7-vs-6 RECONCILIATION (LOAD-BEARING): design.md §Data Models's narrative seed
-- list enumerates only 6 keys — it OMITS `survival.assess_max_latency_seconds`.
-- `params.resolve()` requires ALL 7 survival-domain fields by value and fails
-- closed on any missing one, so the COMPLETE set (the keys in `_FLOAT_KEYS` ∪
-- `_BOOL_KEYS`) is seeded here, NOT the doc's 6. The two run-identity fields
-- (`code_version` / `param_version`) are DELIBERATELY NOT in this namespace —
-- they are run-level identity (bare snapshot keys threaded into the trace
-- four-key contract, P3), not survival-domain thresholds, and are not
-- tightenable.
--
-- Schema choice (mirrors mig 038 / 039 EXACTLY):
--   - All rows tag=NULL (launch_default production governance; `tag` added mig 033).
--   - parameter_namespace='survival' to satisfy the mig-004
--     `parameters_namespace_prefix` CHECK (parameter_key LIKE namespace||'.%').
--   - parameters table append-only (mig 004 trigger unchanged).
--   - Idempotent: each INSERT guarded by NOT EXISTS on (parameter_key, tag IS NULL).
--   - JSONB scalar typing: floats as JSONB decimals (`'50.0'::jsonb`) and the
--     toggle as `'true'::jsonb`, so psycopg3 decodes them to native float / bool
--     and resolve()'s strict per-field type coercion accepts them.
--   - Values == src/survival/params.py::DEFAULTS (the seed is the pinned default).
--
-- Dependencies:
--   - 004_v3_parameters (parameters table + parameters_active view + trigger).
--   - 033_parameters_seed_research_company (`tag` column).
--   - 049_survival_gate_state_and_events (the prior survival-gate migration in
--     this feature; this is the distinct next sequence number).
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/050_survival_params_seed.sql
--
-- Idempotency: safe to re-run. Forward-only (no down-migration).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- survival.* namespace (7 rows; the complete pinned survival-parameter set).
-- 6 float thresholds + 1 bool toggle. NO version keys (run-identity, not domain).
-- Seed values == src/survival/params.py::DEFAULTS.
-- -----------------------------------------------------------------------------

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'survival.stop_out_level_pct', 'survival', '50.0'::jsonb,
       'Venue stop-out / liquidation margin-level threshold (<=50, R1.2). Higher = more liquidation distance = safer; gate uses the tighter of this vs the broker venue readout (P7).',
       'survival-gate v0.1 launch default; pinned to params.DEFAULTS (R10, consumed by value).',
       'launch_default_2026-05-30', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'survival.stop_out_level_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'survival.safe_mode_buffer_pct', 'survival', '100.0'::jsonb,
       'Margin-level buffer at/below which safe-mode escalates, STRICTLY ABOVE the stop-out level (R1.3). 2x the stop-out: enter safe-mode well before liquidation.',
       'survival-gate v0.1 launch default; pinned to params.DEFAULTS (strictly > stop_out_level_pct).',
       'launch_default_2026-05-30', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'survival.safe_mode_buffer_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'survival.per_order_size_max', 'survival', '1.0'::jsonb,
       'Per-order volume / exposure cap (R4.1). Lower = tighter; a size breach REJECTs with an advisory_max (no mutated order).',
       'survival-gate v0.1 launch default; pinned to params.DEFAULTS (conservative single-order cap).',
       'launch_default_2026-05-30', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'survival.per_order_size_max' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'survival.speculative_sleeve_cap_pct', 'survival', '8.0'::jsonb,
       'Speculative-sleeve funding cap as a percent of total book (R3.1, fixed at 8.0). Capitalization-time precondition, not per-order. Lower = tighter.',
       'survival-gate v0.1 launch default; pinned to params.DEFAULTS (R3.1 fixed funding cap).',
       'launch_default_2026-05-30', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'survival.speculative_sleeve_cap_pct' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'survival.flatten_lead_seconds', 'survival', '300.0'::jsonb,
       'Closure lead time for flat-before-close (R6): begin flattening levered positions this many seconds before session closure. Higher = tighter (flatten earlier).',
       'survival-gate v0.1 launch default; pinned to params.DEFAULTS (5 min ahead of closure).',
       'launch_default_2026-05-30', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'survival.flatten_lead_seconds' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'survival.assess_max_latency_seconds', 'survival', '5.0'::jsonb,
       'Max gap between standing-monitor assess invocations (daemon cadence bound). Lower = tighter (check more frequently). OMITTED from design.md''s 6-key narrative list but REQUIRED by resolve() (fail-closed), so seeded here.',
       'survival-gate v0.1 launch default; pinned to params.DEFAULTS; completes the 7-key set resolve() consumes.',
       'launch_default_2026-05-30', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'survival.assess_max_latency_seconds' AND tag IS NULL);

INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'survival.exclusion_enabled', 'survival', 'true'::jsonb,
       'Toggleable ex-ante universe-exclusion stage (R5.4). On by default (safer). enable (False->True) is the tighten direction; disable is a loosen (rejected by the tighten-only override resolver).',
       'survival-gate v0.1 launch default; pinned to params.DEFAULTS (exclusion on).',
       'launch_default_2026-05-30', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'survival.exclusion_enabled' AND tag IS NULL);

COMMIT;

-- Verify row count: 7 INSERTs above (6 float + 1 bool; NO version keys).
-- Confirm via:
--   SELECT COUNT(*) FROM parameters_active WHERE parameter_namespace = 'survival';
-- Expected: 7.
--
-- Confirm the value types round-trip (no bool-in-float, no float-in-bool):
--   SELECT parameter_key, jsonb_typeof(value) FROM parameters_active
--   WHERE parameter_namespace = 'survival' ORDER BY parameter_key;
-- Expected: 6 'number' + 1 'boolean' (survival.exclusion_enabled).
