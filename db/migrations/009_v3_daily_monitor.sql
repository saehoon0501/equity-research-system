-- =============================================================================
-- Migration: 009_v3_daily_monitor
-- Purpose:   Daily-monitor (slow-loop) audit + alerting tables for the v3
--            architecture. Captures every daily B/B'/C-mode refresh, every
--            materiality classification event the LLM judge produces, and
--            every operator-facing alert that fires off M-2/M-3 events.
--
--            Three artifacts:
--              - daily_refresh_log    (Section 4.5 Q1; append-only; one row
--                                      per (ticker, date) tuple)
--              - materiality_events   (Section 6 Q1 event log; append-only;
--                                      one row per LLM-classified event)
--              - unread_alerts        (Section 7 Playbook #4; STATE table;
--                                      operator acknowledges; never deleted)
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 4.5 Q1 (daily refresh modes B / B' / C);
--            Section 6 Q1 (materiality event log + LLM judge);
--            Section 7 Playbook #4 (unread-alert queue, M-2/M-3 fires only);
--            Section 8 Phase 4 cleanup #4 (materiality stored as int + derived
--            label column).
--
-- Schema notes:
--   - `daily_refresh_log.materiality` is SMALLINT (1/2/3); a GENERATED ALWAYS
--     column `materiality_label` exposes the canonical 'M-1'/'M-2'/'M-3'
--     string. Per Phase 4 cleanup #4: store int, derive label.
--   - LLM-call metadata records model id (Sonnet/Opus per spec — no Haiku
--     anywhere in v3) and prompt_version so calibration runs can re-bind
--     outcomes to exact prompts.
--   - `unread_alerts` is a STATE table: operator workflow updates ack /
--     email-send / claude-session-pushed columns. All other columns are
--     immutable after insert; DELETE is blocked.
--   - `unread_alerts.severity` ∈ {2, 3} only — alerts never fire on M-1.
--
-- Dependencies:
--   - 004_v3_parameters (parameters_version FK convention).
--   - Forward-refs to execution_recommendations.recommendation_id are
--     captured as plain UUID without FK constraint here, since that table
--     lands in a later migration.
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/009_v3_daily_monitor.sql
--
-- Idempotency: safe to re-run. CREATE TABLE IF NOT EXISTS, CREATE INDEX
-- IF NOT EXISTS, CREATE OR REPLACE FUNCTION, DROP TRIGGER IF EXISTS.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Table: daily_refresh_log
-- Section 4.5 Q1 — append-only daily slow-loop refresh log. One row per
-- (ticker, classification_date) tuple. Captures the mode the ticker was
-- evaluated in (B / B' / C), materiality verdict, the events the LLM judge
-- saw, the regime context at evaluation time, and the recommended action.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_refresh_log (
    log_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date                    DATE NOT NULL,
    ticker                  TEXT NOT NULL,

    -- Daily-refresh mode per Section 4.5 Q1:
    --   'B'       = full slow-loop refresh (held names + active watchlist).
    --   'B_prime' = lightweight delta refresh (cold watchlist).
    --   'C'       = catalog-only sweep (no LLM cost; flag-only).
    mode                    TEXT NOT NULL CHECK (mode IN ('B', 'B_prime', 'C')),

    -- Materiality classification per Phase 4 cleanup #4: store as SMALLINT,
    -- derive label. 1 = noise, 2 = watch, 3 = act.
    materiality             SMALLINT NOT NULL CHECK (materiality BETWEEN 1 AND 3),
    materiality_label       TEXT GENERATED ALWAYS AS (
        CASE materiality
            WHEN 1 THEN 'M-1'
            WHEN 2 THEN 'M-2'
            WHEN 3 THEN 'M-3'
        END
    ) STORED,

    -- Events the LLM judge classified for this (ticker, date). JSONB array of:
    --   {type, source_id, timestamp, verbatim_quote, impact, cited_kill_criterion_id}
    -- Verbatim_quote required per Section 6 Q1 audit-trail lock.
    events                  JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Snapshot of S0 regime classification + relevant dimensions at eval
    -- time. Lets calibration replay the exact regime context the system
    -- saw when issuing the materiality verdict. Schema:
    --   {S0_classification: {...}, relevant_dimensions: [...]}
    regime_context_at_eval  JSONB NOT NULL,

    -- One of: 'hold', 'reunderwrite', 'exit', 'size_up', 'size_down',
    -- 'add_to_watchlist', 'remove_from_watchlist', 'no_action'.
    -- Free-text rather than CHECK so playbook can evolve without migrations.
    recommended_action      TEXT NOT NULL,

    -- LLM-call metadata. Schema (per Section 6 Q1 + Phase 4 #6):
    --   {
    --     model: 'claude-sonnet-4-6' | 'claude-opus-4-7',  -- NO Haiku in v3
    --     prompt_version: 'daily_monitor_v0.1',
    --     tier_escalated_to_opus: true | false,
    --     input_tokens, output_tokens, latency_ms
    --   }
    llm_call_metadata       JSONB NOT NULL,

    -- Versioning per Section 5 Q1 audit-trail lock.
    rule_engine_version     TEXT NOT NULL,
    parameters_version      UUID,                      -- FK to parameters.version_id

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One row per ticker per day. Re-running the daily monitor for a ticker
    -- on the same date is a no-op (idempotent at app level via UPSERT-skip).
    CONSTRAINT daily_refresh_log_ticker_date_unique
        UNIQUE (ticker, date)
);

-- -----------------------------------------------------------------------------
-- Indexes — daily_refresh_log
-- -----------------------------------------------------------------------------

-- "What did we say about TICKER on DATE?" — primary access pattern.
CREATE INDEX IF NOT EXISTS idx_daily_refresh_log_ticker_date
    ON daily_refresh_log(ticker, date DESC);

-- "Show me all M-3 fires this week" / "all M-2+ today".
CREATE INDEX IF NOT EXISTS idx_daily_refresh_log_materiality
    ON daily_refresh_log(materiality DESC, date DESC);

-- Partial index for hot path: "what fired today at M-2 or M-3?"
CREATE INDEX IF NOT EXISTS idx_daily_refresh_log_actionable
    ON daily_refresh_log(date DESC, ticker)
    WHERE materiality >= 2;

-- Mode-scoped scans for cost-accounting + audit (B vs B' vs C).
CREATE INDEX IF NOT EXISTS idx_daily_refresh_log_mode_date
    ON daily_refresh_log(mode, date DESC);

-- -----------------------------------------------------------------------------
-- Append-only trigger — daily_refresh_log
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION daily_refresh_log_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'daily_refresh_log is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS daily_refresh_log_no_modify ON daily_refresh_log;
CREATE TRIGGER daily_refresh_log_no_modify
BEFORE UPDATE OR DELETE ON daily_refresh_log
FOR EACH ROW EXECUTE FUNCTION daily_refresh_log_guard();


-- -----------------------------------------------------------------------------
-- Table: materiality_events
-- Section 6 Q1 — append-only event log. One row per LLM-classified event.
-- This is the granular event store; daily_refresh_log.events is a
-- denormalized rollup of the same events for the (ticker, date) tuple.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS materiality_events (
    event_id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker                      TEXT NOT NULL,
    event_date                  TIMESTAMPTZ NOT NULL,

    -- Free-text event_type (filing_8k / earnings_miss / guidance_cut /
    -- exec_departure / regime_shift / etc.). Catalog evolves with playbook.
    event_type                  TEXT NOT NULL,

    -- Provenance — pointer into evidence_index or external doc store.
    source_id                   TEXT NOT NULL,

    -- Verbatim quote required per Section 6 Q1 audit-trail + Section 7 PB#4.
    -- Without verbatim, M-2/M-3 fires cannot be defended in a calibration
    -- replay or a /parameters-review session.
    verbatim_quote              TEXT NOT NULL,

    -- Materiality verdict for THIS event (event-level; the daily_refresh_log
    -- row carries the day-level rollup which may be max() across events).
    classification              SMALLINT NOT NULL CHECK (classification BETWEEN 1 AND 3),

    -- If this event tripped a previously-articulated kill-criterion, point
    -- to it. Nullable for events that don't map to a kill criterion (e.g.,
    -- positive surprises or non-thesis-relevant news).
    cited_kill_criterion_id     UUID,

    -- LLM-judge confidence [0, 1] — used by calibration to detect drift in
    -- judge confidence vs. realized materiality.
    llm_judge_confidence        NUMERIC NOT NULL CHECK (llm_judge_confidence BETWEEN 0 AND 1),

    parameters_version          UUID,                  -- FK to parameters.version_id
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Indexes — materiality_events
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_materiality_events_ticker_date
    ON materiality_events(ticker, event_date DESC);

CREATE INDEX IF NOT EXISTS idx_materiality_events_classification
    ON materiality_events(classification DESC, event_date DESC);

-- "Has this kill criterion ever fired?" — drives Section 6 hygiene scans.
CREATE INDEX IF NOT EXISTS idx_materiality_events_kill_criterion
    ON materiality_events(cited_kill_criterion_id, event_date DESC)
    WHERE cited_kill_criterion_id IS NOT NULL;

-- Calibration scans on judge confidence drift over time.
CREATE INDEX IF NOT EXISTS idx_materiality_events_confidence
    ON materiality_events(llm_judge_confidence, event_date DESC);

-- -----------------------------------------------------------------------------
-- Append-only trigger — materiality_events
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION materiality_events_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        RAISE EXCEPTION 'materiality_events is append-only — % not permitted', TG_OP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS materiality_events_no_modify ON materiality_events;
CREATE TRIGGER materiality_events_no_modify
BEFORE UPDATE OR DELETE ON materiality_events
FOR EACH ROW EXECUTE FUNCTION materiality_events_guard();


-- -----------------------------------------------------------------------------
-- Table: unread_alerts
-- Section 7 Playbook #4 — operator-facing alert queue. M-2 and M-3 fires
-- only (M-1 is informational, no alert). STATE table: ack / email / push
-- columns mutate as the alert moves through the operator workflow; all
-- other columns are immutable post-insert; DELETE is blocked.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS unread_alerts (
    alert_id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Severity ∈ {2, 3} — alerts never fire on M-1 per Section 7 PB#4.
    severity                    SMALLINT NOT NULL CHECK (severity BETWEEN 2 AND 3),

    -- Closed-set of alert types the playbook fires on. Add new types via
    -- migration when the playbook evolves (don't smuggle them in as data).
    alert_type                  TEXT NOT NULL CHECK (alert_type IN (
        'counterfactual_veto',
        'anchor_drift',
        'mode_reclass',
        'kill_criterion',
        'drawdown_2x_threshold',
        'materiality_m3',
        'system_error'
    )),

    -- Nullable: system-level alerts (e.g., 'system_error', portfolio-wide
    -- regime fires) carry no ticker.
    ticker                      TEXT,

    summary                     TEXT NOT NULL,
    payload                     JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Drill-down: link the alert back to a specific recommendation if one
    -- caused it. Nullable for system-level / regime-level alerts.
    drill_link_recommendation_id UUID,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- ----- Mutable workflow columns -----
    acknowledged_at             TIMESTAMPTZ,
    acknowledged_by             TEXT DEFAULT 'operator',

    email_sent_at               TIMESTAMPTZ,
    email_send_attempts         INTEGER NOT NULL DEFAULT 0,

    claude_session_pushed_at    TIMESTAMPTZ
);

-- -----------------------------------------------------------------------------
-- Indexes — unread_alerts
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_unread_alerts_severity
    ON unread_alerts(severity DESC, created_at DESC);

-- Hot path: "what alerts need operator attention right now?"
CREATE INDEX IF NOT EXISTS idx_unread_alerts_unacknowledged
    ON unread_alerts(created_at DESC)
    WHERE acknowledged_at IS NULL;

-- Per-ticker alert history.
CREATE INDEX IF NOT EXISTS idx_unread_alerts_ticker
    ON unread_alerts(ticker, created_at DESC)
    WHERE ticker IS NOT NULL;

-- Email-retry queue: "what alerts haven't been emailed yet?"
CREATE INDEX IF NOT EXISTS idx_unread_alerts_email_pending
    ON unread_alerts(created_at)
    WHERE email_sent_at IS NULL;

-- Alert-type rollups for /parameters-review (e.g., "how many anchor_drift
-- alerts last quarter?").
CREATE INDEX IF NOT EXISTS idx_unread_alerts_type_date
    ON unread_alerts(alert_type, created_at DESC);

-- -----------------------------------------------------------------------------
-- State-table guard — unread_alerts
--
-- UPDATE allowed only on workflow columns:
--   acknowledged_at, acknowledged_by, email_sent_at, email_send_attempts,
--   claude_session_pushed_at
-- All other columns are immutable post-insert. DELETE is blocked entirely.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION unread_alerts_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'unread_alerts: DELETE not permitted (state table; alerts are never removed)';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        -- Reject updates to any immutable column. We compare with IS DISTINCT
        -- FROM so NULL <-> NULL is treated as no-change.
        IF NEW.alert_id                     IS DISTINCT FROM OLD.alert_id
           OR NEW.severity                  IS DISTINCT FROM OLD.severity
           OR NEW.alert_type                IS DISTINCT FROM OLD.alert_type
           OR NEW.ticker                    IS DISTINCT FROM OLD.ticker
           OR NEW.summary                   IS DISTINCT FROM OLD.summary
           OR NEW.payload                   IS DISTINCT FROM OLD.payload
           OR NEW.drill_link_recommendation_id IS DISTINCT FROM OLD.drill_link_recommendation_id
           OR NEW.created_at                IS DISTINCT FROM OLD.created_at
        THEN
            RAISE EXCEPTION 'unread_alerts: only acknowledged_at, acknowledged_by, email_sent_at, email_send_attempts, claude_session_pushed_at are mutable';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS unread_alerts_state_guard ON unread_alerts;
CREATE TRIGGER unread_alerts_state_guard
BEFORE UPDATE OR DELETE ON unread_alerts
FOR EACH ROW EXECUTE FUNCTION unread_alerts_guard();

COMMIT;

-- =============================================================================
-- VERIFY: run these after applying.
-- =============================================================================

-- VERIFY: all 3 tables exist.
SELECT schemaname, tablename
FROM pg_tables
WHERE tablename IN ('daily_refresh_log', 'materiality_events', 'unread_alerts')
ORDER BY tablename;

-- VERIFY: indexes are present.
SELECT indexname, tablename
FROM pg_indexes
WHERE tablename IN ('daily_refresh_log', 'materiality_events', 'unread_alerts')
  AND indexname LIKE 'idx_%'
ORDER BY tablename, indexname;

-- VERIFY: append-only / state guards are wired.
SELECT t.tgname AS trigger_name, c.relname AS table_name, p.proname AS function_name
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_proc  p ON p.oid = t.tgfoid
WHERE c.relname IN ('daily_refresh_log', 'materiality_events', 'unread_alerts')
  AND NOT t.tgisinternal
ORDER BY c.relname, t.tgname;

-- VERIFY: CHECK constraints (mode, materiality, severity, alert_type).
SELECT conrelid::regclass AS table_name, conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid IN (
        'daily_refresh_log'::regclass,
        'materiality_events'::regclass,
        'unread_alerts'::regclass
    )
  AND contype = 'c'
ORDER BY conrelid::regclass::text, conname;

-- VERIFY: GENERATED ALWAYS column on daily_refresh_log.materiality_label.
SELECT column_name, is_generated, generation_expression
FROM information_schema.columns
WHERE table_name = 'daily_refresh_log'
  AND column_name = 'materiality_label';
