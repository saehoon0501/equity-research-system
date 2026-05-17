-- =============================================================================
-- Migration: 025_v3_system_vs_operator_brier_view
-- Purpose:   Calibration-circularity defense (v3 spec §6.0).
--
--            Adds the `system_vs_operator_brier` Postgres view that joins
--            execution_recommendations + recommendation_outcomes +
--            operator_overrides + override_outcomes per (mode, materiality,
--            recommendation_type) cell so v0.5+ formulas can detect cells
--            where the OPERATOR outperforms the SYSTEM and invert the
--            calibration sign convention.
--
--            Per spec §6.0 calibration sign convention:
--              system_brier  > operator_brier → calibration regresses TOWARD
--                                                operator behavior
--              system_brier  < operator_brier → calibration regresses AGAINST
--                                                operator bias (inverts default)
--
--            The view is read-only and computed on demand. v0.5
--            /parameters-review consumes it monthly per Section 6.3.
--
-- Dependencies:
--   - 008_v3_recommendations (execution_recommendations)
--   - 013_v3_calibration_capture (operator_overrides, recommendation_outcomes,
--                                  override_outcomes)
--
-- How to apply:
--   psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
--        -f db/migrations/025_v3_system_vs_operator_brier_view.sql
--
-- Idempotency: safe to re-run (DROP VIEW IF EXISTS pattern).
-- =============================================================================

BEGIN;

DROP VIEW IF EXISTS system_vs_operator_brier;

CREATE VIEW system_vs_operator_brier AS
WITH system_outcomes AS (
    -- Per-cell system Brier at T+90d. Mirrors src/calibration/brier._favorable
    -- mapping; we compute it inline here so the view is dependency-free.
    SELECT
        er.mode,
        COALESCE(er.trigger_metadata->>'triggered_by', 'cadence') AS materiality_proxy,
        er.recommendation,
        er.conviction,
        ro.delta_vs_benchmark_90d AS delta,
        -- favorable_y per recommendation type
        CASE
            WHEN ro.delta_vs_benchmark_90d IS NULL THEN NULL
            WHEN er.recommendation IN ('BUY', 'TRIM') THEN
                CASE WHEN ro.delta_vs_benchmark_90d > 0 THEN 1 ELSE 0 END
            WHEN er.recommendation = 'SELL' THEN
                CASE WHEN ro.delta_vs_benchmark_90d < 0 THEN 1 ELSE 0 END
            WHEN er.recommendation = 'HOLD' THEN
                CASE WHEN ABS(ro.delta_vs_benchmark_90d) < 0.02 THEN 1 ELSE 0 END
            ELSE NULL
        END AS y,
        -- Conviction prior: HIGH=0.70 / MEDIUM=0.50 / LOW=0.30
        CASE er.conviction
            WHEN 'HIGH'   THEN 0.70
            WHEN 'MEDIUM' THEN 0.50
            WHEN 'LOW'    THEN 0.30
        END AS p
    FROM execution_recommendations er
    JOIN recommendation_outcomes ro
        ON ro.recommendation_id = er.recommendation_id
    WHERE ro.delta_vs_benchmark_90d IS NOT NULL
),
override_outcomes_typed AS (
    -- For each override, recover (mode, materiality_proxy, recommendation)
    -- from the linked execution_recommendation. Only overrides tied to a
    -- recommendation can be cell-attributed; standalone overrides
    -- (recommendation_id NULL) drop out at the JOIN.
    SELECT
        er.mode,
        COALESCE(er.trigger_metadata->>'triggered_by', 'cadence') AS materiality_proxy,
        er.recommendation,
        ovo.actual_outcome_t90d,
        ovo.counterfactual_outcome_t90d,
        -- Treat the actual operator outcome as if it were the relevant
        -- delta (positive operator alpha vs counterfactual = operator
        -- "won" the override). Brier here is computed on the OPERATOR's
        -- realized outperformance over their counterfactual.
        CASE
            WHEN ovo.actual_outcome_t90d IS NULL OR ovo.counterfactual_outcome_t90d IS NULL THEN NULL
            WHEN ovo.actual_outcome_t90d - ovo.counterfactual_outcome_t90d > 0 THEN 1
            ELSE 0
        END AS operator_y
    FROM override_outcomes ovo
    JOIN operator_overrides oo  ON oo.override_id = ovo.override_id
    JOIN execution_recommendations er ON er.recommendation_id = oo.recommendation_id
    WHERE oo.recommendation_id IS NOT NULL
)
SELECT
    s.mode,
    s.materiality_proxy AS materiality,
    s.recommendation,
    -- N counts
    COUNT(*) AS n_system,
    COUNT(o.operator_y) AS n_overrides,
    -- System Brier per cell
    AVG(POWER(s.p - s.y, 2))::NUMERIC AS system_brier,
    -- Operator Brier per cell — uses 0.5 prior (operator is treated as a
    -- coin-flip until v0.5+ recalibrates them). The metric is computed
    -- with the operator's actual outperformance binary outcome.
    AVG(POWER(0.5 - o.operator_y, 2))::NUMERIC AS operator_brier,
    -- Direction-of-better flag: TRUE = operator beats system at this cell
    CASE
        WHEN COUNT(o.operator_y) = 0 THEN NULL
        WHEN AVG(POWER(0.5 - o.operator_y, 2)) < AVG(POWER(s.p - s.y, 2)) THEN TRUE
        ELSE FALSE
    END AS operator_better
FROM system_outcomes s
LEFT JOIN override_outcomes_typed o
    ON s.mode = o.mode
   AND s.materiality_proxy = o.materiality_proxy
   AND s.recommendation = o.recommendation
WHERE s.y IS NOT NULL
GROUP BY s.mode, s.materiality_proxy, s.recommendation;

COMMENT ON VIEW system_vs_operator_brier IS
    'v3 spec §6.0 calibration-circularity defense. Per-cell Brier comparison '
    'between the system''s recommendations and operator overrides. Cells where '
    'operator_better=TRUE drive sign-inversion in v0.5+ formula calibration.';

COMMIT;

-- =============================================================================
-- VERIFY
-- =============================================================================
SELECT viewname, definition
FROM pg_views
WHERE viewname = 'system_vs_operator_brier';
