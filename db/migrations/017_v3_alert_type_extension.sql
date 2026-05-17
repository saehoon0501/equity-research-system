-- =============================================================================
-- Migration: 017_v3_alert_type_extension
-- Purpose:   Extend `unread_alerts.alert_type` CHECK enum to add two values
--            previously missing from the closed set defined in migration 009:
--              - 'materiality_m2'    : daily-monitor M-2 events without a kill
--                                      criterion (Section 4.5 PB#4 — every M-2
--                                      MUST fire an alert; previously suppressed)
--              - 'calibration_drift' : materiality-classifier drift watch and
--                                      override-rate / conviction-flip-flop
--                                      surfacings (Phase 4 Q8 — distinct from
--                                      `system_error`)
--
--            Pattern: DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT, idempotent.
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 4.5 PB#4 (M-2 alert pipeline) + Phase 4 Q8 (drift detector
--            alerts).
--
-- Dependencies:
--   - 009_v3_daily_monitor (defines unread_alerts table + original CHECK)
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U equity_research_admin -d equity_research \
--        -f db/migrations/017_v3_alert_type_extension.sql
--
-- Idempotency: safe to re-run.
-- NOTE: 016 reserved for HMAC consolidation by parallel agent.
-- =============================================================================

BEGIN;

ALTER TABLE unread_alerts
    DROP CONSTRAINT IF EXISTS unread_alerts_alert_type_check;

ALTER TABLE unread_alerts
    ADD CONSTRAINT unread_alerts_alert_type_check
    CHECK (alert_type IN (
        'counterfactual_veto',
        'anchor_drift',
        'mode_reclass',
        'kill_criterion',
        'drawdown_2x_threshold',
        'materiality_m2',
        'materiality_m3',
        'calibration_drift',
        'system_error'
    ));

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'unread_alerts'::regclass
  AND contype = 'c'
  AND conname = 'unread_alerts_alert_type_check';
