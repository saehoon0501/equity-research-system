-- =============================================================================
-- Migration: 054_in_session_monitor_params_seed
-- Purpose:   Seed the `monitor.*` parameter namespace for the In-Session Monitor
--            (.kiro/specs/in-session-monitor). These are the drift-rule knobs the
--            monitor pins BY VALUE at run start (P2) from `parameters_active`
--            under REPEATABLE READ, consumed via a future
--            `src/reactive/monitor/params.py` resolver into the
--            `MonitorParams` dataclass (`src/reactive/monitor/types.py`), never
--            re-resolved mid-tick. This migration establishes the NAMESPACE +
--            SHAPE only — it does NOT write a `run_parameters_snapshot` row
--            (Rev 2.1 anti-contamination: the monitor never touches the
--            /research-company LLM-run lifecycle; design §Owned — MonitorParams).
--
--            Reference: .kiro/specs/in-session-monitor/design.md
--                       §"Owned — MonitorParams" (the six structural knobs) and
--                       §"Baseline-ownership decision (corrected 2026-05-30)".
--            Requirements: 1.1 (scheduled cadence — cadence_seconds), 2.1/2.2/2.3
--                       (drift diagnostic + classification rule — window_W,
--                       margin_M, severity_cutoffs, in_sample_baseline,
--                       min_observations), 8.3 (per-(run_id, agent) cost ceiling —
--                       the monitor's pin stays in `monitor.*`, no aggregate cap).
--
--            Rows: 1 namespace, 6 rows = the COMPLETE `MonitorParams` field set:
--              monitor.min_observations    (int   — sufficiency window floor)
--              monitor.window_W            (int   — rolling closed-decision count)
--              monitor.margin_M            (float — baseline-exclusion margin)
--              monitor.severity_cutoffs    (object{mild,severe} — banded grade)
--              monitor.in_sample_baseline  (object — per-version reference, SHAPE)
--              monitor.cadence_seconds     (int   — supervisory tick interval)
--            Leaf names align 1:1 with `MonitorParams` fields so the resolver maps
--            cleanly (severity_cutoffs / in_sample_baseline are single dict fields
--            → single JSON-object keys, not split scalars).
--
-- PROVISIONAL VALUES (P15): the numeric placeholders below are NOT calibrated
--   figures. min_observations / window_W / margin_M / severity_cutoffs are tuning
--   knobs (bootstrap-distance + window thresholds) seeded with sane provisional
--   defaults — each row's change_rationale says PROVISIONAL. They are superseded
--   by a later effective_at INSERT once empirically calibrated (the table is
--   append-only; rows are not DELETEd, mig 004 trigger). `in_sample_baseline` is
--   deliberately seeded SHAPE-ONLY (per-metric nulls), NOT a literal: the v0.1
--   monitor computes the baseline per-(code_version, param_version) at runtime
--   from that version's in-sample window (design §Baseline-ownership). Seeding a
--   plausible `{"brier": 0.18}` would be an ASSERTED calibration figure (the P15
--   trap) that the runtime computation silently overrides anyway.
--
-- Schema choice (mirrors mig 050 / 033 EXACTLY):
--   - All rows tag=NULL (launch_default production governance; `tag` added mig 033).
--   - parameter_namespace='monitor' to satisfy the mig-004
--     `parameters_namespace_prefix` CHECK (parameter_key LIKE namespace||'.%') —
--     every key is `monitor.*`.
--   - parameters table append-only (mig 004 trigger unchanged); no DDL here (the
--     `tag` column + `parameters_active` tag-filter already landed in mig 033).
--   - Idempotent: each INSERT guarded by NOT EXISTS on (parameter_key, tag IS NULL).
--   - JSONB typing: ints as JSONB integers (`'400'::jsonb`), the float as a JSONB
--     decimal (`'2.0'::jsonb`), and the two compound knobs as JSONB objects
--     (`'{...}'::jsonb`), so psycopg3 decodes them to native int / float / dict
--     and a strict per-field resolver accepts them.
--
-- Dependencies:
--   - 004_v3_parameters (parameters table + parameters_active view + append-only
--     trigger + namespace-prefix CHECK).
--   - 033_parameters_seed_research_company (`tag` column + tag-filtered
--     parameters_active view).
--   - 049-053 are reserved by the parallel survival-gate / daemon / walkforward
--     session; this is the deliberate next number (054), not a renumber.
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/054_in_session_monitor_params_seed.sql
--
-- Idempotency: safe to re-run. Forward-only (no down-migration).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- monitor.* namespace (6 rows = the complete MonitorParams field set).
-- 3 ints + 1 float + 2 JSON objects. PROVISIONAL values (P15) — namespace +
-- shape only; numbers are placeholders, in_sample_baseline is shape-only.
-- -----------------------------------------------------------------------------

-- min_observations: sufficiency window floor (R2.4). Below this, the version-
-- scoped window is INSUFFICIENT → no verdict, no intervention (incl. the
-- expected post-hot-swap blind window).
INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'monitor.min_observations', 'monitor', '200'::jsonb,
       'Minimum count of closed reactive decisions in the version-scoped window required before the drift diagnostic emits a verdict (R2.4 sufficiency floor). Below this the judge returns INSUFFICIENT — never an intervention.',
       'In-Session Monitor v0.1 PROVISIONAL placeholder (P15) — NOT calibrated; establishes the monitor.* namespace + shape. Tune empirically once the reactive realized-directional-label source lands; supersede via a later effective_at INSERT.',
       'launch_default_2026-05-30', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'monitor.min_observations' AND tag IS NULL);

-- window_W: rolling closed-decision count the drift rule evaluates the block-
-- bootstrap CI over (design §Leaf — judge drift-decision rule).
INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'monitor.window_W', 'monitor', '500'::jsonb,
       'Rolling window of closed reactive decisions (W) over which calibration (Brier / reliability / ECE) and its block-bootstrap CI are computed for the drift rule (R2.2/R2.3).',
       'In-Session Monitor v0.1 PROVISIONAL placeholder (P15) — NOT calibrated; namespace + shape only. Must be >= min_observations to ever clear sufficiency; tune empirically and supersede via a later effective_at INSERT.',
       'launch_default_2026-05-30', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'monitor.window_W' AND tag IS NULL);

-- margin_M: baseline-exclusion margin. A metric is DRIFTED when its bootstrap
-- CI excludes the pinned in_sample_baseline by AT LEAST this margin (design
-- §Leaf — judge). A bootstrap-distance threshold, NOT an asserted probability.
INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'monitor.margin_M', 'monitor', '0.02'::jsonb,
       'Baseline-exclusion margin (M): a metric is DRIFTED only when its block-bootstrap CI excludes that version''s pinned in_sample_baseline by at least M (design drift-decision rule). A distance threshold on the metric scale, not a probability.',
       'In-Session Monitor v0.1 PROVISIONAL placeholder (P15) — NOT calibrated; namespace + shape only. A tuning knob (bootstrap-distance margin), tune empirically and supersede via a later effective_at INSERT.',
       'launch_default_2026-05-30', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'monitor.margin_M' AND tag IS NULL);

-- severity_cutoffs: the {mild, severe} bands on the bootstrap-distance-from-
-- baseline that map the verdict's Severity grade (design §Leaf — judge / Severity
-- IntEnum). Single JSON object → maps 1:1 to MonitorParams.severity_cutoffs: dict.
INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'monitor.severity_cutoffs', 'monitor', '{"mild": 0.02, "severe": 0.05}'::jsonb,
       'Banded drift-severity cutoffs on the bootstrap-distance from baseline: >= mild grades MILD (→ SELECT/TIGHTEN), >= severe grades SEVERE (→ HALT). One JSON object so it maps 1:1 to the single MonitorParams.severity_cutoffs dict field. Distance thresholds, not probabilities (P15).',
       'In-Session Monitor v0.1 PROVISIONAL placeholders (P15) — NOT calibrated; namespace + shape only (band ORDER mild < severe is the load-bearing part). Tune empirically and supersede via a later effective_at INSERT.',
       'launch_default_2026-05-30', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'monitor.severity_cutoffs' AND tag IS NULL);

-- in_sample_baseline: the PER-VERSION reference baseline keyed by metric. Seeded
-- SHAPE-ONLY (per-metric nulls) — the v0.1 monitor COMPUTES this per
-- (code_version, param_version) at runtime from that version's in-sample window
-- (design §Baseline-ownership). NOT consumed as a literal; a seeded number here
-- would be an asserted calibration figure (the P15 trap) and is overridden anyway.
INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'monitor.in_sample_baseline', 'monitor', '{"brier": null, "reliability": null, "ece": null}'::jsonb,
       'Per-(code_version, param_version) in-sample reference baseline, keyed by metric (brier / reliability / ece). SHAPE-ONLY: the v0.1 monitor computes the actual baseline at runtime from the version''s in-sample window via the RealizedLabelSource seam — this row establishes the key set + object shape, not the values.',
       'In-Session Monitor v0.1 SHAPE-ONLY (P15) — deliberately per-metric NULL, NOT a literal: the monitor computes the baseline per-version at runtime (design Baseline-ownership 2026-05-30). Seeding a number would assert an uncalibrated probability. Re-fires when the reactive realized-directional-label source lands.',
       'launch_default_2026-05-30', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'monitor.in_sample_baseline' AND tag IS NULL);

-- cadence_seconds: the supervisory tick interval (R1.1 — the cadence requirement;
-- the scheduler host that fires the tick is out of boundary).
INSERT INTO parameters (parameter_key, parameter_namespace, value, description, change_rationale, approved_by, tag)
SELECT 'monitor.cadence_seconds', 'monitor', '900'::jsonb,
       'Supervisory tick interval (seconds) for the in-session monitor cadence loop (R1.1). The monitor pins this by value; the scheduler host that actually fires the tick is out of this spec''s boundary.',
       'In-Session Monitor v0.1 PROVISIONAL placeholder (P15) — NOT calibrated (15 min provisional). Namespace + shape only; tune empirically and supersede via a later effective_at INSERT.',
       'launch_default_2026-05-30', NULL
WHERE NOT EXISTS (SELECT 1 FROM parameters WHERE parameter_key = 'monitor.cadence_seconds' AND tag IS NULL);

COMMIT;

-- =============================================================================
-- VERIFY: run after applying. Expected: 6 monitor.* rows in parameters_active.
-- =============================================================================

-- VERIFY: all six seeded knobs are resolvable production rows.
--   SELECT parameter_key, value FROM parameters_active
--   WHERE parameter_namespace = 'monitor' ORDER BY parameter_key;
-- Expected 6 rows: monitor.cadence_seconds, monitor.in_sample_baseline,
--   monitor.margin_M, monitor.min_observations, monitor.severity_cutoffs,
--   monitor.window_W.

-- VERIFY: JSONB value types round-trip (no object-in-scalar, no scalar-in-object).
--   SELECT parameter_key, jsonb_typeof(value) FROM parameters_active
--   WHERE parameter_namespace = 'monitor' ORDER BY parameter_key;
-- Expected:
--   monitor.cadence_seconds    -> number
--   monitor.in_sample_baseline -> object
--   monitor.margin_M           -> number
--   monitor.min_observations   -> number
--   monitor.severity_cutoffs   -> object
--   monitor.window_W           -> number

-- VERIFY (idempotency): re-running this whole migration is a NO-OP — the row
-- count below is unchanged across a second apply.
--   SELECT COUNT(*) FROM parameters_active WHERE parameter_namespace = 'monitor';
-- Expected: 6 (before and after re-apply).
