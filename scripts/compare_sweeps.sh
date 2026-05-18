#!/usr/bin/env bash
# =============================================================================
# compare_sweeps.sh
#
# Side-by-side comparison of two /research-company parameter regimes by tag.
# Pull this for: "what does swapping parameter X do to the recommendation
# distribution on basket B?"
#
# Emits 3 reports:
#   (1) Aggregate decision distribution per regime (BUY/HOLD/TRIM/SELL counts)
#   (2) Per-ticker side-by-side (recommendation + conviction + initial size)
#   (3) Parameter diff between the two effective_parameters_jsonb snapshots
#
# Per /review-me v7 + sign_sweep_tag wrapper convention: read-only against
# run_parameters_snapshot + execution_recommendations + parameters. No writes,
# no risk to live data.
#
# USAGE:
#   ./scripts/compare_sweeps.sh production <SWEEP_TAG>
#   ./scripts/compare_sweeps.sh <TAG_A> <TAG_B>
#   ./scripts/compare_sweeps.sh production <SWEEP_TAG> --basket "AAPL,MSFT,NVDA"
#   ./scripts/compare_sweeps.sh production <SWEEP_TAG> --since "2026-05-01"
#
# ENV CONTRACT (libpq — same as reconcile_orphan_snapshots.sh):
#   PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD (or PGPASSFILE).
#   Typical subshell invocation:
#     (set -a; source .env; set +a; ./scripts/compare_sweeps.sh production <TAG>)
# =============================================================================

set -euo pipefail

if [[ $# -lt 2 ]]; then
    sed -n '2,29p' "$0" | sed 's/^# *//'
    exit 1
fi

TAG_A="$1"; shift
TAG_B="$1"; shift
BASKET=""
SINCE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --basket) BASKET="$2"; shift 2 ;;
        --since)  SINCE="$2";  shift 2 ;;
        *) echo "ERROR: unknown arg: $1" >&2; exit 1 ;;
    esac
done

# Validate env contract.
: "${PGHOST:?PGHOST env var required — typical: 'set -a; source .env; set +a'}"
: "${PGPORT:?PGPORT env var required}"
: "${PGDATABASE:?PGDATABASE env var required}"
: "${PGUSER:?PGUSER env var required}"
if [[ -z "${PGPASSWORD:-}" && -z "${PGPASSFILE:-}" ]]; then
    echo "ERROR: neither PGPASSWORD nor PGPASSFILE is set." >&2
    exit 1
fi

# --- normalize tag args ---
# 'production' / '-' / 'NULL' → SQL NULL match (filters tag IS NULL)
# anything else → matched as literal tag value
sql_tag_predicate() {
    local raw="$1"
    case "$raw" in
        production|PRODUCTION|-|NULL|null) echo "tag IS NULL" ;;
        *) echo "tag = '${raw//\'/\'\'}'" ;;
    esac
}

display_label() {
    local raw="$1"
    case "$raw" in
        production|PRODUCTION|-|NULL|null) echo "PRODUCTION (tag IS NULL)" ;;
        *) echo "$raw" ;;
    esac
}

PRED_A=$(sql_tag_predicate "$TAG_A")
PRED_B=$(sql_tag_predicate "$TAG_B")
LABEL_A=$(display_label "$TAG_A")
LABEL_B=$(display_label "$TAG_B")

# --- basket filter (optional) ---
BASKET_PREDICATE=""
if [[ -n "$BASKET" ]]; then
    # Convert "AAPL,MSFT" → "'AAPL','MSFT'"
    QUOTED=$(echo "$BASKET" | sed "s/[^,]*/'&'/g")
    BASKET_PREDICATE=" AND s.ticker IN (${QUOTED})"
fi

# --- since filter (optional) ---
SINCE_PREDICATE=""
if [[ -n "$SINCE" ]]; then
    SINCE_PREDICATE=" AND s.run_started_at >= '${SINCE//\'/\'\'}'::timestamptz"
fi

echo "================================================================================"
echo "Comparing two parameter regimes:"
echo "  A: ${LABEL_A}"
echo "  B: ${LABEL_B}"
[[ -n "$BASKET" ]] && echo "  basket: $BASKET"
[[ -n "$SINCE"  ]] && echo "  since:  $SINCE"
echo "================================================================================"
echo

# =============================================================================
# Report 1 — Aggregate decision distribution per regime.
# =============================================================================
echo "[1/3] AGGREGATE DECISION DISTRIBUTION"
echo "--------------------------------------------------------------------------------"
psql -P pager=off -c "
WITH labeled AS (
  SELECT
    CASE
      WHEN s.${PRED_A} THEN 'A: ${LABEL_A}'
      WHEN s.${PRED_B} THEN 'B: ${LABEL_B}'
    END AS regime,
    er.recommendation,
    er.conviction
  FROM run_parameters_snapshot s
  JOIN execution_recommendations er ON er.run_parameters_snapshot_id = s.run_id
  WHERE (s.${PRED_A} OR s.${PRED_B})
    AND s.run_status = 'completed'
    ${BASKET_PREDICATE}
    ${SINCE_PREDICATE}
)
SELECT
  regime,
  COUNT(*) AS total_runs,
  COUNT(*) FILTER (WHERE recommendation = 'BUY')  AS buy,
  COUNT(*) FILTER (WHERE recommendation = 'HOLD') AS hold,
  COUNT(*) FILTER (WHERE recommendation = 'TRIM') AS trim,
  COUNT(*) FILTER (WHERE recommendation = 'SELL') AS sell,
  ROUND(100.0 * COUNT(*) FILTER (WHERE recommendation = 'BUY') / NULLIF(COUNT(*),0), 1) AS buy_pct,
  COUNT(*) FILTER (WHERE conviction = 'HIGH')     AS conv_high,
  COUNT(*) FILTER (WHERE conviction = 'MEDIUM')   AS conv_med,
  COUNT(*) FILTER (WHERE conviction = 'LOW')      AS conv_low
FROM labeled
GROUP BY regime
ORDER BY regime;
"
echo

# =============================================================================
# Report 2 — Per-ticker side-by-side.
# Latest completed run per (ticker, regime) under the window.
# =============================================================================
echo "[2/3] PER-TICKER SIDE-BY-SIDE (latest completed run per regime)"
echo "--------------------------------------------------------------------------------"
psql -P pager=off -c "
WITH ranked AS (
  SELECT
    s.ticker,
    CASE WHEN s.${PRED_A} THEN 'A' WHEN s.${PRED_B} THEN 'B' END AS regime,
    er.recommendation,
    er.conviction,
    er.mode,
    (er.sizing_suggestion->>'initial_pct')::numeric AS initial_pct,
    s.run_started_at,
    ROW_NUMBER() OVER (
      PARTITION BY s.ticker, CASE WHEN s.${PRED_A} THEN 'A' WHEN s.${PRED_B} THEN 'B' END
      ORDER BY s.run_started_at DESC
    ) AS rn
  FROM run_parameters_snapshot s
  JOIN execution_recommendations er ON er.run_parameters_snapshot_id = s.run_id
  WHERE (s.${PRED_A} OR s.${PRED_B})
    AND s.run_status = 'completed'
    ${BASKET_PREDICATE}
    ${SINCE_PREDICATE}
)
SELECT
  ticker,
  MAX(CASE WHEN regime = 'A' THEN recommendation END)                  AS a_rec,
  MAX(CASE WHEN regime = 'A' THEN conviction     END)                  AS a_conv,
  MAX(CASE WHEN regime = 'A' THEN initial_pct    END)                  AS a_size,
  MAX(CASE WHEN regime = 'B' THEN recommendation END)                  AS b_rec,
  MAX(CASE WHEN regime = 'B' THEN conviction     END)                  AS b_conv,
  MAX(CASE WHEN regime = 'B' THEN initial_pct    END)                  AS b_size,
  CASE
    WHEN MAX(CASE WHEN regime = 'A' THEN recommendation END) IS DISTINCT FROM
         MAX(CASE WHEN regime = 'B' THEN recommendation END) THEN '** FLIP **'
    ELSE ''
  END AS rec_diff
FROM ranked
WHERE rn = 1
GROUP BY ticker
ORDER BY rec_diff DESC NULLS LAST, ticker;
"
echo

# =============================================================================
# Report 3 — Parameter diff between effective_parameters_jsonb snapshots.
# Picks the latest snapshot row per regime to extract the parameter map.
# =============================================================================
echo "[3/3] PARAMETER DIFF (latest snapshot per regime; keys differing in value)"
echo "--------------------------------------------------------------------------------"
psql -P pager=off -c "
WITH latest_per_regime AS (
  SELECT DISTINCT ON (regime)
    CASE WHEN ${PRED_A} THEN 'A' WHEN ${PRED_B} THEN 'B' END AS regime,
    effective_parameters_jsonb
  FROM run_parameters_snapshot
  WHERE (${PRED_A} OR ${PRED_B})
    ${SINCE_PREDICATE//s\./}
  ORDER BY regime, run_started_at DESC
),
a_map AS (
  SELECT key, value AS value_a
  FROM latest_per_regime, jsonb_each(effective_parameters_jsonb)
  WHERE regime = 'A'
),
b_map AS (
  SELECT key, value AS value_b
  FROM latest_per_regime, jsonb_each(effective_parameters_jsonb)
  WHERE regime = 'B'
)
SELECT
  COALESCE(a.key, b.key) AS parameter_key,
  a.value_a AS regime_a_value,
  b.value_b AS regime_b_value,
  CASE
    WHEN a.key IS NULL THEN 'only in B'
    WHEN b.key IS NULL THEN 'only in A'
    ELSE 'differs'
  END AS diff_kind
FROM a_map a
FULL OUTER JOIN b_map b ON a.key = b.key
WHERE a.value_a IS DISTINCT FROM b.value_b
ORDER BY diff_kind, parameter_key;
"
echo

echo "================================================================================"
echo "Done. To export full payloads:"
echo "  psql -c \"SELECT effective_parameters_jsonb FROM run_parameters_snapshot WHERE ${PRED_A} ORDER BY run_started_at DESC LIMIT 1;\""
echo "================================================================================"
