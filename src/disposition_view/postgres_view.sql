-- =============================================================================
-- View: current_disposition
-- Purpose:   One-row-per-watchlist-name disposition rollup. Joins watchlist
--            with the latest-per-ticker projections of execution_recommendations,
--            daily_refresh_log, mode_classifications, and mode_vol_checks; left-
--            joins positions (cold names have no position row). Aggregates
--            positions across accounts so the same ticker held in taxable + IRA
--            collapses to one disposition line.
--
-- Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
--            Section 4.6 Q2 (multi-horizon disposition view);
--            Section 5.4 (/disposition slash command);
--            Section 2.2 / Phase 4 Q5 (mode-fit dashboard data).
--
-- Materialization: read-side VIEW (NOT a MATERIALIZED VIEW). Per task scope:
-- materialize-on-read; no ongoing maintenance / refresh job. The Python loader
-- in src/disposition_view/loader.py issues per-name fetches by default; this
-- view is the single-shot equivalent that callers can SELECT against directly
-- (e.g., for ad-hoc psql sessions or downstream dashboards).
--
-- Idempotency: CREATE OR REPLACE VIEW; safe to re-run.
-- =============================================================================

BEGIN;

CREATE OR REPLACE VIEW current_disposition AS
WITH latest_rec AS (
    SELECT DISTINCT ON (ticker)
           ticker,
           recommendation_id,
           date                    AS rec_date,
           recommendation,
           conviction,
           conviction_breakdown,
           sizing_suggestion,
           execution_context,
           trigger_metadata,
           audit_available,
           created_at              AS rec_created_at
    FROM execution_recommendations
    ORDER BY ticker, date DESC, created_at DESC
),
latest_refresh AS (
    SELECT DISTINCT ON (ticker)
           ticker,
           date                    AS refresh_date,
           materiality,
           materiality_label,
           recommended_action,
           events                  AS refresh_events,
           regime_context_at_eval,
           created_at              AS refresh_created_at
    FROM daily_refresh_log
    ORDER BY ticker, date DESC, created_at DESC
),
latest_class AS (
    SELECT DISTINCT ON (ticker)
           ticker,
           classification_id,
           final_mode              AS classified_mode,
           company_quality_flag    AS classified_quality,
           classification_method,
           recheck_status,
           classified_at
    FROM mode_classifications
    ORDER BY ticker, classified_at DESC
),
last_confirmed AS (
    SELECT DISTINCT ON (ticker)
           ticker,
           classified_at           AS last_confirmed_at
    FROM mode_classifications
    WHERE recheck_status = 'confirmed'
    ORDER BY ticker, classified_at DESC
),
latest_vol AS (
    SELECT DISTINCT ON (ticker)
           ticker,
           check_date,
           realized_vol_252d,
           mode_band_low,
           mode_band_high,
           within_band,
           consecutive_outside_count,
           flagged                 AS vol_flagged
    FROM mode_vol_checks
    ORDER BY ticker, check_date DESC
),
agg_positions AS (
    SELECT ticker,
           SUM(shares_held)        AS total_shares,
           CASE WHEN SUM(shares_held) > 0
                THEN SUM(shares_held * cost_basis) / SUM(shares_held)
                ELSE NULL
           END                     AS avg_cost_basis,
           MIN(first_acquired)     AS first_acquired,
           COUNT(*)                AS account_count
    FROM positions
    GROUP BY ticker
)
SELECT  w.ticker                                  AS ticker,
        w.mode                                    AS mode,
        w.company_quality_flag                    AS company_quality_flag,
        w.conviction_threshold                    AS conviction_threshold,
        w.regime_sensitivity                      AS regime_sensitivity,
        w.added_at                                AS watchlist_added_at,
        w.last_reunderwritten_at                  AS last_reunderwritten_at,

        -- Latest recommendation envelope (NULL for cold names).
        lr.recommendation_id                      AS recommendation_id,
        lr.rec_date                               AS recommendation_date,
        lr.recommendation                         AS recommendation,
        lr.conviction                             AS conviction,
        lr.conviction_breakdown                   AS conviction_breakdown,
        lr.sizing_suggestion                      AS sizing_suggestion,
        lr.execution_context                      AS execution_context,
        lr.trigger_metadata                       AS trigger_metadata,
        lr.audit_available                        AS audit_available,

        -- Latest daily-monitor refresh (NULL when never refreshed).
        lf.refresh_date                           AS last_refresh_date,
        lf.materiality                            AS last_refresh_materiality,
        lf.materiality_label                      AS last_refresh_materiality_label,
        lf.recommended_action                     AS last_refresh_action,
        lf.refresh_events                         AS last_refresh_events,

        -- Mode classifier state (Phase 4 Q5).
        lc.classified_mode                        AS classified_mode,
        lc.classified_quality                     AS classified_quality,
        lc.classification_method                  AS classification_method,
        lc.recheck_status                         AS recheck_status,
        lc.classified_at                          AS last_classified_at,
        conf.last_confirmed_at                    AS last_confirmed_at,

        -- Mode-implied-vol (Phase 4 Q5).
        lv.check_date                             AS last_vol_check_date,
        lv.realized_vol_252d                      AS realized_vol_252d,
        lv.mode_band_low                          AS mode_band_low,
        lv.mode_band_high                         AS mode_band_high,
        lv.within_band                            AS within_vol_band,
        lv.consecutive_outside_count              AS consecutive_outside_count,
        COALESCE(lv.vol_flagged, FALSE)           AS vol_flagged,

        -- Position rollup across accounts.
        ap.total_shares                           AS shares_held,
        ap.avg_cost_basis                         AS cost_basis,
        ap.first_acquired                         AS first_acquired,
        COALESCE(ap.account_count, 0)             AS account_count,

        -- Derived flag_status per Phase 4 Q5 + mode_fit_dashboard.derive_flag_status.
        -- Most-severe-first precedence; mirrors Python derivation so SQL and
        -- application stay in sync.
        CASE
            WHEN lc.recheck_status = 'reclassification_proposed' THEN 'pending_reclassification'
            WHEN lc.recheck_status = 'pending_review'            THEN 'rule_output_mismatch'
            WHEN lv.vol_flagged IS TRUE                          THEN 'vol_band_inconsistency'
            ELSE 'none'
        END                                        AS flag_status,

        -- Derived primary-horizon mapping (B → long, B' → mid, C → short).
        CASE w.mode
            WHEN 'B'       THEN 'long'
            WHEN 'B_prime' THEN 'mid'
            WHEN 'C'       THEN 'short'
            ELSE NULL
        END                                        AS primary_horizon

FROM watchlist w
LEFT JOIN latest_rec      lr   ON lr.ticker = w.ticker
LEFT JOIN latest_refresh  lf   ON lf.ticker = w.ticker
LEFT JOIN latest_class    lc   ON lc.ticker = w.ticker
LEFT JOIN last_confirmed  conf ON conf.ticker = w.ticker
LEFT JOIN latest_vol      lv   ON lv.ticker = w.ticker
LEFT JOIN agg_positions   ap   ON ap.ticker = w.ticker
ORDER BY w.mode, w.ticker;

COMMENT ON VIEW current_disposition IS
  'Per v3 Section 4.6 Q2 + Phase 4 Q5: one row per watchlist name, joining '
  'latest execution_recommendations, daily_refresh_log, mode_classifications, '
  'mode_vol_checks, and aggregated positions. Backs /disposition.';

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================

-- VERIFY: view exists.
SELECT viewname
FROM pg_views
WHERE viewname = 'current_disposition';

-- VERIFY: smoke select against the view (zero rows is fine — proves the
-- query plan compiles cleanly against the joined tables).
SELECT COUNT(*) AS row_count FROM current_disposition;

-- VERIFY: column list matches the v3 Section 4.6 Q2 schema (smoke).
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'current_disposition'
ORDER BY ordinal_position;
