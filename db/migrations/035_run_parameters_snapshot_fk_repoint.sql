-- =============================================================================
-- Migration: 035_run_parameters_snapshot_fk_repoint
-- Purpose:   Add run_parameters_snapshot_id FK column to every downstream
--            table currently carrying a parameters_version column. The new
--            column is the canonical run-snapshot pin (one row in
--            run_parameters_snapshot per /research-company run); the legacy
--            parameters_version column is kept for backwards compatibility
--            but deprecated via column COMMENT.
--
--            Per /review-me v7-final C14 + C17: each affected table gets:
--              (a) ADD COLUMN run_parameters_snapshot_id UUID REFERENCES
--                  run_parameters_snapshot(run_id);
--              (b) CHECK constraint: (parameters_version IS NULL OR
--                  run_parameters_snapshot_id IS NULL) — blocks rows that
--                  attempt to populate both;
--              (c) BEFORE INSERT trigger requiring
--                  run_parameters_snapshot_id NOT NULL when created_at >=
--                  mig 035 apply timestamp AND parameters_version IS NULL;
--              (d) BEFORE UPDATE trigger rejecting NULL-ing of
--                  run_parameters_snapshot_id on post-apply_ts rows.
--                  CARVE-OUT (C17): tables already protected by an
--                  append-only no_modify trigger SKIP the UPDATE trigger
--                  (defensive redundancy). The Phase 3 audit checklist
--                  records the carve-out per-table so future migs that
--                  loosen the append-only guard re-trigger this review.
--
-- Reference: /review-me v7-final convergence 2026-05-18.
-- Audit doc:  docs/superpowers/audits/2026-05-18-parameter-externalization-phase3-audit-checklist.md
--
-- Affected tables (14 total, from Phase 0 inventory + live-DB correction
-- 2026-05-18 — audit_provenance dropped from scope because it stores
-- parameters_version inside a `versions` JSONB blob, not as a column):
--   APPEND-ONLY (UPDATE trigger skipped — existing no_modify guard covers):
--     - regime_classification_history (mig 005; guard: regime_classification_no_modify)
--     - execution_recommendations     (mig 008; guard: exec_recs_no_modify)
--     - mode_classifications          (mig 008; guard: mode_classifications_no_modify)
--     - daily_refresh_log             (mig 009; guard: daily_refresh_log_no_modify)
--     - materiality_events            (mig 009; guard: materiality_events_no_modify)
--     - anchor_drift_checks           (mig 010; guard: anchor_drift_no_modify)
--     - materiality_classifier_drift  (mig 010; guard: materiality_drift_no_modify)
--     - counterfactual_retrievals     (mig 011; guard: counterfactual_retrievals_no_modify)
--     - premortem                     (mig 012; guard: premortem_no_modify)
--     - operator_overrides            (mig 013; guard: operator_overrides_no_modify)
--     - calibration_test_results      (mig 015; guard: calibration_test_results_no_modify)
--     - anchor_drift_review_decisions (mig 018; guard: anchor_drift_review_decisions_no_modify)
--
--   STATE TABLES (UPDATE trigger required):
--     - scenarios (mig 006; mutable for narrative refresh)
--     - watchlist (mig 007; mutable for position state)
--
-- Sunset slot: mig 036+ will DROP the legacy parameters_version columns
-- after operator-declared backfill window. The DROP also needs to handle
-- the existing FK constraints on scenarios, watchlist, counterfactual_retrievals
-- (these three migs declared `REFERENCES parameters(version_id)` — others
-- are convention-only).
--
-- Dependencies:
--   - 034_run_parameters_snapshot (FK target).
--   - All 12 migrations carrying parameters_version columns.
--
-- Idempotency: ADD COLUMN IF NOT EXISTS, CREATE OR REPLACE FUNCTION,
--   DROP TRIGGER IF EXISTS, COMMENT ON COLUMN (idempotent).
--
-- Apply timestamp: captured into the schema_migrations table convention
-- (or, lacking one, into a dedicated GUC parameter that the triggers read).
-- For simplicity here we embed the apply timestamp as a literal in the
-- trigger function body. The operator can re-run the migration to refresh
-- the apply_ts if a re-apply is needed; new rows inserted between original
-- and refresh will be grandfathered (their created_at < new apply_ts and
-- thus fall into legacy-row carve-out).
-- =============================================================================

BEGIN;

-- Lock-hold convoy mitigation: this migration acquires ACCESS EXCLUSIVE on
-- 14 tables for the entire transaction. On a shared dev DB with active
-- worktrees, fail fast rather than convoy-blocking concurrent writers.
-- Per /review-me iteration 1 SQL review (2026-05-18) defect #5.
SET LOCAL lock_timeout = '5s';

-- -----------------------------------------------------------------------------
-- Apply-timestamp capture: store the apply moment so triggers can distinguish
-- pre-mig-035 (legacy, grandfathered) rows from post-mig-035 (must use new
-- column) rows. We keep it as a settings GUC for runtime accessibility.
-- -----------------------------------------------------------------------------

DO $$
DECLARE
    apply_ts_iso TEXT := to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"');
BEGIN
    -- Stash in a settings GUC so trigger functions can read it.
    PERFORM set_config('app.mig_035_apply_ts', apply_ts_iso, false);

    -- Also persist into pg_description on the run_parameters_snapshot table
    -- so post-hoc auditors can read it without setting the GUC.
    EXECUTE format('COMMENT ON TABLE run_parameters_snapshot IS %L',
                   'Per-run parameter snapshot. mig_035_apply_ts = ' || apply_ts_iso
                   || '. Rows in downstream tables with created_at >= this ts MUST populate '
                   || 'run_parameters_snapshot_id.');
END $$;

-- -----------------------------------------------------------------------------
-- Reusable trigger functions.
-- We define two functions (one for INSERT, one for UPDATE) parameterized by
-- the column name conventions; each affected table installs both triggers.
-- -----------------------------------------------------------------------------

-- BEFORE INSERT: post-apply_ts rows must populate run_parameters_snapshot_id
-- when parameters_version is also NULL. This forces NEW writers to use the
-- new column without breaking legacy backfills (which would populate
-- parameters_version and leave run_parameters_snapshot_id NULL).
--
-- Table-agnostic via TG_ARGV[0] = name of timestamp column to consult for the
-- grandfathering check. 12 of 14 affected tables use 'created_at'; watchlist
-- (mig 007) uses 'added_at'; mode_classifications (mig 008) uses
-- 'classified_at'. Each CREATE TRIGGER below passes the right column name.
-- Per /review-me iteration 2 SQL review (2026-05-18) — original implementation
-- hardcoded NEW.created_at, which would raise 'record "new" has no field
-- "created_at"' on watchlist and mode_classifications.
CREATE OR REPLACE FUNCTION enforce_run_parameters_snapshot_on_insert() RETURNS TRIGGER AS $$
DECLARE
    apply_ts TIMESTAMPTZ := COALESCE(
        -- current_setting(..., true) returns '' (empty string) when GUC unset,
        -- not NULL. Cast of '' to timestamptz raises 'invalid input syntax'.
        -- NULLIF converts '' → NULL so COALESCE can advance to the fallback
        -- literal in subsequent sessions where the GUC isn't set. Per
        -- /review-me iteration 1 SQL review (2026-05-18) defect #2.
        NULLIF(current_setting('app.mig_035_apply_ts', true), '')::timestamptz,
        '2026-05-18T00:00:00Z'::timestamptz  -- conservative fallback
    );
    ts_col_name TEXT;
    row_ts TIMESTAMPTZ;
BEGIN
    -- Argument must be passed by every CREATE TRIGGER (see below).
    IF TG_NARGS < 1 THEN
        RAISE EXCEPTION 'enforce_run_parameters_snapshot_on_insert: missing TG_ARGV[0] timestamp column name (table=%)',
            TG_TABLE_NAME;
    END IF;
    ts_col_name := TG_ARGV[0];

    -- Dynamic column access via JSON serialization. Required because the 15
    -- affected tables use 3 different timestamp column names (created_at,
    -- added_at, classified_at) and PL/pgSQL has no syntax for variable column
    -- access on a record without dynamic SQL or this JSON detour.
    --
    -- Fail loud if a future ALTER TABLE drops/renames the timestamp column
    -- (otherwise the missing-key NULL would silently bypass the grandfathering
    -- guard). Per /review-me iteration 3 SQL review polish (2026-05-18).
    IF NOT (to_jsonb(NEW) ? ts_col_name) THEN
        RAISE EXCEPTION 'enforce_run_parameters_snapshot_on_insert: timestamp column "%" not found on table % — was it dropped or renamed? Update the CREATE TRIGGER arg.',
            ts_col_name, TG_TABLE_NAME;
    END IF;
    row_ts := (to_jsonb(NEW) ->> ts_col_name)::timestamptz;

    IF row_ts IS NOT NULL
       AND row_ts >= apply_ts
       AND NEW.run_parameters_snapshot_id IS NULL
       AND NEW.parameters_version IS NULL
    THEN
        RAISE EXCEPTION 'post-mig-035 rows MUST populate run_parameters_snapshot_id (got NULL on both legacy parameters_version and new run_parameters_snapshot_id; table=%, %=%)',
            TG_TABLE_NAME, ts_col_name, row_ts;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- BEFORE UPDATE: reject any UPDATE that sets run_parameters_snapshot_id = NULL
-- on a post-apply_ts row. Prevents drift back into the legacy column path.
-- Only installed on STATE tables (scenarios, watchlist); append-only tables
-- have their own no_modify trigger that blocks UPDATE entirely.
CREATE OR REPLACE FUNCTION enforce_run_parameters_snapshot_on_update() RETURNS TRIGGER AS $$
DECLARE
    apply_ts TIMESTAMPTZ := COALESCE(
        -- See enforce_run_parameters_snapshot_on_insert above for the NULLIF
        -- rationale (per /review-me iteration 2 SQL review, 2026-05-18 — the
        -- v1→v2 fix was applied only to the INSERT fn; v2→v3 propagates here).
        NULLIF(current_setting('app.mig_035_apply_ts', true), '')::timestamptz,
        '2026-05-18T00:00:00Z'::timestamptz
    );
    ts_col_name TEXT;
    row_ts TIMESTAMPTZ;
BEGIN
    -- Per /review-me v2→v3, this trigger is also table-agnostic. Currently
    -- installed only on STATE tables (scenarios, watchlist); scenarios uses
    -- 'created_at' and watchlist uses 'added_at'.
    IF TG_NARGS < 1 THEN
        RAISE EXCEPTION 'enforce_run_parameters_snapshot_on_update: missing TG_ARGV[0] timestamp column name (table=%)',
            TG_TABLE_NAME;
    END IF;
    ts_col_name := TG_ARGV[0];

    -- Same future-proof check as the INSERT fn (per /review-me iter 3 polish).
    IF NOT (to_jsonb(OLD) ? ts_col_name) THEN
        RAISE EXCEPTION 'enforce_run_parameters_snapshot_on_update: timestamp column "%" not found on table % — was it dropped or renamed? Update the CREATE TRIGGER arg.',
            ts_col_name, TG_TABLE_NAME;
    END IF;
    row_ts := (to_jsonb(OLD) ->> ts_col_name)::timestamptz;

    IF row_ts IS NOT NULL
       AND row_ts >= apply_ts
       AND OLD.run_parameters_snapshot_id IS NOT NULL
       AND NEW.run_parameters_snapshot_id IS NULL
    THEN
        RAISE EXCEPTION 'post-mig-035 rows: run_parameters_snapshot_id is immutable to NULL (table=%, row %=%)',
            TG_TABLE_NAME, ts_col_name, row_ts;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------------------------
-- Per-table ADD COLUMN + CHECK + INSERT trigger (+ UPDATE trigger for STATE).
-- -----------------------------------------------------------------------------

-- Each block is wrapped in a small per-table DO to keep failures isolated.

-- ===== regime_classification_history (mig 005, append-only) =====
ALTER TABLE regime_classification_history
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE regime_classification_history
    DROP CONSTRAINT IF EXISTS regime_classification_history_pv_xor_rpsi;
ALTER TABLE regime_classification_history
    ADD CONSTRAINT regime_classification_history_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS regime_classification_enforce_snapshot_insert ON regime_classification_history;
CREATE TRIGGER regime_classification_enforce_snapshot_insert
    BEFORE INSERT ON regime_classification_history
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('created_at');
COMMENT ON COLUMN regime_classification_history.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead. Will be DROPped at mig 036+ after backfill window.';

-- ===== scenarios (mig 006, STATE) =====
ALTER TABLE scenarios
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE scenarios
    DROP CONSTRAINT IF EXISTS scenarios_pv_xor_rpsi;
ALTER TABLE scenarios
    ADD CONSTRAINT scenarios_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS scenarios_enforce_snapshot_insert ON scenarios;
CREATE TRIGGER scenarios_enforce_snapshot_insert
    BEFORE INSERT ON scenarios
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('created_at');
DROP TRIGGER IF EXISTS scenarios_enforce_snapshot_update ON scenarios;
CREATE TRIGGER scenarios_enforce_snapshot_update
    BEFORE UPDATE ON scenarios
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_update('created_at');
COMMENT ON COLUMN scenarios.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead. Existing FK to parameters(version_id) will be dropped at mig 036+ after backfill window.';

-- ===== watchlist (mig 007, STATE) =====
ALTER TABLE watchlist
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE watchlist
    DROP CONSTRAINT IF EXISTS watchlist_pv_xor_rpsi;
ALTER TABLE watchlist
    ADD CONSTRAINT watchlist_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS watchlist_enforce_snapshot_insert ON watchlist;
CREATE TRIGGER watchlist_enforce_snapshot_insert
    BEFORE INSERT ON watchlist
    -- watchlist (mig 007) uses 'added_at', not 'created_at'.
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('added_at');
DROP TRIGGER IF EXISTS watchlist_enforce_snapshot_update ON watchlist;
CREATE TRIGGER watchlist_enforce_snapshot_update
    BEFORE UPDATE ON watchlist
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_update('added_at');
COMMENT ON COLUMN watchlist.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead. Existing FK to parameters(version_id) will be dropped at mig 036+ after backfill window.';

-- NOTE: audit_provenance (mig 008) DOES NOT carry parameters_version as a
-- column — instead it lives inside the `versions` JSONB blob per mig 008
-- schema comment. The original Phase 0 audit (which grepped migration
-- source files) matched the schema comment, not an actual column. Per
-- live-DB verification 2026-05-18 during mig 035 application: there is
-- no audit_provenance.parameters_version column, so no XOR CHECK or
-- INSERT trigger is needed here. Calls querying audit_provenance for
-- parameter lineage should extract `versions->>'parameters_version'`
-- and follow that to run_parameters_snapshot_id on the recommendation
-- row instead.

-- ===== execution_recommendations (mig 008, append-only) =====
ALTER TABLE execution_recommendations
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE execution_recommendations
    DROP CONSTRAINT IF EXISTS execution_recommendations_pv_xor_rpsi;
ALTER TABLE execution_recommendations
    ADD CONSTRAINT execution_recommendations_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS execution_recommendations_enforce_snapshot_insert ON execution_recommendations;
CREATE TRIGGER execution_recommendations_enforce_snapshot_insert
    BEFORE INSERT ON execution_recommendations
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('created_at');
COMMENT ON COLUMN execution_recommendations.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead.';

-- ===== mode_classifications (mig 008, append-only) =====
ALTER TABLE mode_classifications
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE mode_classifications
    DROP CONSTRAINT IF EXISTS mode_classifications_pv_xor_rpsi;
ALTER TABLE mode_classifications
    ADD CONSTRAINT mode_classifications_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS mode_classifications_enforce_snapshot_insert ON mode_classifications;
CREATE TRIGGER mode_classifications_enforce_snapshot_insert
    BEFORE INSERT ON mode_classifications
    -- mode_classifications (mig 008) uses 'classified_at', not 'created_at'.
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('classified_at');
COMMENT ON COLUMN mode_classifications.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead.';

-- ===== daily_refresh_log (mig 009, append-only) =====
ALTER TABLE daily_refresh_log
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE daily_refresh_log
    DROP CONSTRAINT IF EXISTS daily_refresh_log_pv_xor_rpsi;
ALTER TABLE daily_refresh_log
    ADD CONSTRAINT daily_refresh_log_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS daily_refresh_log_enforce_snapshot_insert ON daily_refresh_log;
CREATE TRIGGER daily_refresh_log_enforce_snapshot_insert
    BEFORE INSERT ON daily_refresh_log
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('created_at');
COMMENT ON COLUMN daily_refresh_log.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead.';

-- ===== materiality_events (mig 009, append-only) =====
ALTER TABLE materiality_events
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE materiality_events
    DROP CONSTRAINT IF EXISTS materiality_events_pv_xor_rpsi;
ALTER TABLE materiality_events
    ADD CONSTRAINT materiality_events_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS materiality_events_enforce_snapshot_insert ON materiality_events;
CREATE TRIGGER materiality_events_enforce_snapshot_insert
    BEFORE INSERT ON materiality_events
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('created_at');
COMMENT ON COLUMN materiality_events.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead.';

-- ===== anchor_drift_checks (mig 010, append-only) =====
ALTER TABLE anchor_drift_checks
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE anchor_drift_checks
    DROP CONSTRAINT IF EXISTS anchor_drift_checks_pv_xor_rpsi;
ALTER TABLE anchor_drift_checks
    ADD CONSTRAINT anchor_drift_checks_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS anchor_drift_checks_enforce_snapshot_insert ON anchor_drift_checks;
CREATE TRIGGER anchor_drift_checks_enforce_snapshot_insert
    BEFORE INSERT ON anchor_drift_checks
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('created_at');
COMMENT ON COLUMN anchor_drift_checks.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead.';

-- ===== materiality_classifier_drift (mig 010, append-only) =====
ALTER TABLE materiality_classifier_drift
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE materiality_classifier_drift
    DROP CONSTRAINT IF EXISTS materiality_classifier_drift_pv_xor_rpsi;
ALTER TABLE materiality_classifier_drift
    ADD CONSTRAINT materiality_classifier_drift_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS materiality_classifier_drift_enforce_snapshot_insert ON materiality_classifier_drift;
CREATE TRIGGER materiality_classifier_drift_enforce_snapshot_insert
    BEFORE INSERT ON materiality_classifier_drift
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('created_at');
COMMENT ON COLUMN materiality_classifier_drift.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead.';

-- ===== counterfactual_retrievals (mig 011, append-only) =====
ALTER TABLE counterfactual_retrievals
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE counterfactual_retrievals
    DROP CONSTRAINT IF EXISTS counterfactual_retrievals_pv_xor_rpsi;
ALTER TABLE counterfactual_retrievals
    ADD CONSTRAINT counterfactual_retrievals_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS counterfactual_retrievals_enforce_snapshot_insert ON counterfactual_retrievals;
CREATE TRIGGER counterfactual_retrievals_enforce_snapshot_insert
    BEFORE INSERT ON counterfactual_retrievals
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('created_at');
COMMENT ON COLUMN counterfactual_retrievals.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead. Existing FK to parameters(version_id) will be dropped at mig 036+ after backfill window.';

-- ===== premortem (mig 012, append-only) =====
ALTER TABLE premortem
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE premortem
    DROP CONSTRAINT IF EXISTS premortem_pv_xor_rpsi;
ALTER TABLE premortem
    ADD CONSTRAINT premortem_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS premortem_enforce_snapshot_insert ON premortem;
CREATE TRIGGER premortem_enforce_snapshot_insert
    BEFORE INSERT ON premortem
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('created_at');
COMMENT ON COLUMN premortem.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead.';

-- ===== operator_overrides (mig 013, append-only) =====
ALTER TABLE operator_overrides
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE operator_overrides
    DROP CONSTRAINT IF EXISTS operator_overrides_pv_xor_rpsi;
ALTER TABLE operator_overrides
    ADD CONSTRAINT operator_overrides_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS operator_overrides_enforce_snapshot_insert ON operator_overrides;
CREATE TRIGGER operator_overrides_enforce_snapshot_insert
    BEFORE INSERT ON operator_overrides
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('created_at');
COMMENT ON COLUMN operator_overrides.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead.';

-- ===== calibration_test_results (mig 015, append-only) =====
ALTER TABLE calibration_test_results
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE calibration_test_results
    DROP CONSTRAINT IF EXISTS calibration_test_results_pv_xor_rpsi;
ALTER TABLE calibration_test_results
    ADD CONSTRAINT calibration_test_results_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS calibration_test_results_enforce_snapshot_insert ON calibration_test_results;
CREATE TRIGGER calibration_test_results_enforce_snapshot_insert
    BEFORE INSERT ON calibration_test_results
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('created_at');
COMMENT ON COLUMN calibration_test_results.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead.';

-- ===== anchor_drift_review_decisions (mig 018, append-only) =====
ALTER TABLE anchor_drift_review_decisions
    ADD COLUMN IF NOT EXISTS run_parameters_snapshot_id UUID REFERENCES run_parameters_snapshot(run_id);
ALTER TABLE anchor_drift_review_decisions
    DROP CONSTRAINT IF EXISTS anchor_drift_review_decisions_pv_xor_rpsi;
ALTER TABLE anchor_drift_review_decisions
    ADD CONSTRAINT anchor_drift_review_decisions_pv_xor_rpsi
    CHECK (parameters_version IS NULL OR run_parameters_snapshot_id IS NULL);
DROP TRIGGER IF EXISTS anchor_drift_review_decisions_enforce_snapshot_insert ON anchor_drift_review_decisions;
CREATE TRIGGER anchor_drift_review_decisions_enforce_snapshot_insert
    BEFORE INSERT ON anchor_drift_review_decisions
    FOR EACH ROW EXECUTE FUNCTION enforce_run_parameters_snapshot_on_insert('created_at');
COMMENT ON COLUMN anchor_drift_review_decisions.parameters_version IS
    'DEPRECATED (mig 035): use run_parameters_snapshot_id instead.';

COMMIT;

-- =============================================================================
-- VERIFY: run these after applying.
-- =============================================================================

-- VERIFY: all 14 tables now have run_parameters_snapshot_id column.
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE column_name = 'run_parameters_snapshot_id'
ORDER BY table_name;
-- Expected: 14 rows (regime_classification_history, scenarios, watchlist,
-- execution_recommendations, mode_classifications, daily_refresh_log,
-- materiality_events, anchor_drift_checks, materiality_classifier_drift,
-- counterfactual_retrievals, premortem, operator_overrides,
-- calibration_test_results, anchor_drift_review_decisions). audit_provenance
-- was dropped from mig 035 scope at live-DB apply time (parameters_version
-- is a JSONB key, not a column on that table — see audit checklist).

-- VERIFY: all 14 tables have the XOR CHECK constraint.
SELECT conrelid::regclass AS table_name, conname,
       pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conname LIKE '%_pv_xor_rpsi'
ORDER BY conrelid::regclass::text;
-- Expected: 14 rows.

-- VERIFY: all 14 tables have BEFORE INSERT trigger.
SELECT tgname AS trigger_name, c.relname AS table_name
FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE tgname LIKE '%_enforce_snapshot_insert'
ORDER BY c.relname;
-- Expected: 14 rows.

-- VERIFY: 2 STATE tables (scenarios, watchlist) have BEFORE UPDATE trigger.
SELECT tgname AS trigger_name, c.relname AS table_name
FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE tgname LIKE '%_enforce_snapshot_update'
ORDER BY c.relname;
-- Expected: 2 rows (scenarios, watchlist).

-- VERIFY: COMMENT on each legacy parameters_version column flags deprecation.
SELECT c.relname AS table_name, a.attname AS column_name,
       d.description
FROM pg_description d
JOIN pg_attribute a ON a.attrelid = d.objoid AND a.attnum = d.objsubid
JOIN pg_class c ON c.oid = a.attrelid
WHERE a.attname = 'parameters_version'
  AND d.description LIKE '%DEPRECATED (mig 035)%'
ORDER BY c.relname;
-- Expected: at least 14 rows (one COMMENT per affected table).
