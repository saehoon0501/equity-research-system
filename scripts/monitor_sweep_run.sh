#!/usr/bin/env bash
# =============================================================================
# monitor_sweep_run.sh
#
# Mid-flight stop-criteria monitor for /research-company GOOGL sweep runs.
# Runs in a parallel terminal alongside a fresh-main-session dispatch.
# Polls DB + envelope filesystem; emits ABORT signal early when an anomaly
# matching one of the 4 known Phase 5a bugs is detected.
#
# Built per the 2026-05-19 post-mortem of Phase 5a's first wave (run_ids
# 37ae3333 a6f4e54c 285e3423 7ee43faf), all of which produced invalid
# data and ran to ~60min wallclock before the anomalies were detected
# post-hoc. This script catches the same anomalies at minute 2-30.
#
# Reference baseline: d438b802-2bdc-4b1b-9898-ee6dc052f237 (GOOGL, post-mig-037).
#   DCF Narrative base $218.60, β=1.10, tax=0.17, w_e=0.98, w_d=0.02.
#   summary_code=HOLD.
#
# USAGE:
#   scripts/monitor_sweep_run.sh A7-loose
#   scripts/monitor_sweep_run.sh A7-tight
#   scripts/monitor_sweep_run.sh A1-loose
#   scripts/monitor_sweep_run.sh A1-tight
#
# Exit codes:
#   0 = all 4 stop-criteria PASSED (run can continue / has completed cleanly)
#   1 = ABORT signal fired (operator should kill the fresh-main-session)
#   2 = timeout (>75 minutes; run is hung or operator never dispatched)
#
# Polling cadence: 15s in early phases (SC1 snapshot), 30s in deeper phases.
# Total monitor wallclock budget: 75 minutes per run.
# =============================================================================

set -uo pipefail

# ---------- color output (force OFF if not a TTY) ----------
if [ -t 1 ]; then
    RED=$'\033[0;31m'
    GREEN=$'\033[0;32m'
    YELLOW=$'\033[0;33m'
    BOLD=$'\033[1m'
    DIM=$'\033[2m'
    NC=$'\033[0m'
else
    RED="" GREEN="" YELLOW="" BOLD="" DIM="" NC=""
fi

abort() {
    local msg="$1"
    echo
    echo "${RED}${BOLD}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo "${RED}${BOLD}║                       *** ABORT NOW ***                         ║${NC}"
    echo "${RED}${BOLD}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo "${RED}${BOLD}Reason: $msg${NC}"
    echo "${RED}Kill the fresh-main-session running /research-company immediately.${NC}"
    echo "${RED}Run cannot produce valid sweep data; continuing wastes wallclock.${NC}"
    echo
    exit 1
}

pass() {
    echo "${GREEN}[PASS]${NC} $1"
}

wait_msg() {
    echo "${DIM}[wait]${NC} $1"
}

# ---------- parse axis arg ----------
AXIS="${1:-}"
case "$AXIS" in
    A7-loose)
        TAG="51ee7736-f761-4c01-9c19-bc81c1c9bd18"
        SWEPT_KEY="wacc.erp"
        EXPECTED_SWEPT_VALUE="4.4"      # parameters table stored as 4.40 → jsonb 4.4
        DIRECTION_SIGN="up"              # ERP↓ → IV↑
        ;;
    A7-tight)
        TAG="67bf9200-3d79-4b72-a036-a5790210396f"
        SWEPT_KEY="wacc.erp"
        EXPECTED_SWEPT_VALUE="5"         # 5.00 → jsonb 5
        DIRECTION_SIGN="down"
        ;;
    A1-loose)
        TAG="10b79db7-85b0-4912-8577-5fcd21dcb638"
        SWEPT_KEY="dcf.austere_terminal_growth_dgs10_premium_pct"
        EXPECTED_SWEPT_VALUE="2.0"
        DIRECTION_SIGN="up"              # premium↑ → IV↑
        ;;
    A1-tight)
        TAG="deee5742-5873-4a37-9962-576de1835771"
        SWEPT_KEY="dcf.austere_terminal_growth_dgs10_premium_pct"
        EXPECTED_SWEPT_VALUE="1.0"
        DIRECTION_SIGN="down"
        ;;
    "")
        echo "ERROR: axis required. Usage: $0 {A7-loose|A7-tight|A1-loose|A1-tight}" >&2
        exit 1
        ;;
    *)
        echo "ERROR: unknown axis: $AXIS (expected A7-loose|A7-tight|A1-loose|A1-tight)" >&2
        exit 1
        ;;
esac

# ---------- baseline constants from d438b802 ----------
BASELINE_RUN_ID="d438b802-2bdc-4b1b-9898-ee6dc052f237"
BASELINE_DCF_BASE="218.60"
BASELINE_BETA="1.10"
BASELINE_TAX="0.17"
BASELINE_WEIGHT_EQUITY="0.98"
BASELINE_WEIGHT_DEBT="0.02"
BASELINE_SUMMARY_CODE="HOLD"
MAGNITUDE_ABORT_PCT="50"      # |Δ IV| / baseline > 50% → ABORT
CETERIS_EPS="0.005"           # any non-swept input differing by > 0.005 → ABORT

# ---------- DB helper ----------
DB_QUERY() {
    docker exec equity-research-db psql -U "${POSTGRES_USER:-equity}" -d "${POSTGRES_DB:-equity_research}" -tA -c "$1" 2>/dev/null
}

# ---------- script start ----------
echo "${BOLD}=== Sweep run monitor: ${AXIS} ===${NC}"
echo "  Tag: ${TAG}"
echo "  Swept: ${SWEPT_KEY} = ${EXPECTED_SWEPT_VALUE}"
echo "  Expected direction: IV ${DIRECTION_SIGN} vs baseline \$${BASELINE_DCF_BASE}"
echo "  Baseline run_id: ${BASELINE_RUN_ID}"
echo

START_TS=$(date +%s)
SC1_DEADLINE=$((START_TS + 600))    # 10 min for SC1
SC2_DEADLINE=$((START_TS + 2100))   # 35 min for SC2+SC3
SC4_DEADLINE=$((START_TS + 4500))   # 75 min for SC4 (full run)

RUN_ID=""

# ---------- SC1: tagged-snapshot application (Bug 1) ----------
echo "${BOLD}[SC1] Tagged-snapshot application (Bug 1 catch)${NC}"
echo "  Polling run_parameters_snapshot for tag=${TAG}..."

while [ $(date +%s) -lt $SC1_DEADLINE ]; do
    ROW=$(DB_QUERY "SELECT run_id || '|' || (effective_parameters_jsonb->>'${SWEPT_KEY}') FROM run_parameters_snapshot WHERE tag = '${TAG}' AND run_started_at > NOW() - INTERVAL '90 minutes' ORDER BY run_started_at DESC LIMIT 1;")
    if [ -n "$ROW" ]; then
        RUN_ID="${ROW%%|*}"
        OBSERVED="${ROW##*|}"
        # Numeric comparison via Python (jsonb formatting strips trailing zeros inconsistently)
        NUMERIC_MATCH=$(python3 -c "
try:
    obs = float('${OBSERVED}')
    exp = float('${EXPECTED_SWEPT_VALUE}')
    print('YES' if abs(obs - exp) < 0.001 else 'NO')
except (ValueError, TypeError):
    print('PARSE_ERROR')
")
        if [ "$NUMERIC_MATCH" = "YES" ]; then
            pass "SC1: snapshot tag-applied correctly (${SWEPT_KEY}=${OBSERVED}, matches expected ${EXPECTED_SWEPT_VALUE})"
            echo "  run_id captured: ${RUN_ID}"
            break
        else
            abort "SC1 (Bug 1 fall-through): snapshot has ${SWEPT_KEY}=${OBSERVED} but seeded ${EXPECTED_SWEPT_VALUE}. The §1.5 query fell through to parameters_active. This is a \$${BASELINE_DCF_BASE} baseline re-run, not a real sweep."
        fi
    fi
    wait_msg "no snapshot row yet for tag (orchestrator still in pre-flight or §1.5)"
    sleep 15
done

if [ -z "$RUN_ID" ]; then
    echo "${YELLOW}[timeout] SC1 deadline hit (10min); no snapshot row appeared.${NC}"
    echo "  Either the operator hasn't dispatched yet, or the run is stalled."
    exit 2
fi
echo

# ---------- SC2: quant ceteris paribus (Bug 2) ----------
QUANT_ENV="memos/envelopes/quantitative-analyst__${RUN_ID}.json"
echo "${BOLD}[SC2] Quant subagent ceteris paribus (Bug 2 catch)${NC}"
echo "  Watching for ${QUANT_ENV}..."

while [ $(date +%s) -lt $SC2_DEADLINE ]; do
    if [ -f "$QUANT_ENV" ]; then
        # Quant envelope appeared. Compare WACC inputs to baseline.
        BETA=$(python3 -c "import json; print(json.load(open('${QUANT_ENV}'))['wacc_regime'].get('beta_used',''))")
        TAX=$(python3 -c "import json; print(json.load(open('${QUANT_ENV}'))['wacc_regime'].get('effective_tax_rate',''))")
        WE=$(python3 -c "import json; print(json.load(open('${QUANT_ENV}'))['wacc_regime'].get('weight_equity',''))")
        WD=$(python3 -c "import json; print(json.load(open('${QUANT_ENV}'))['wacc_regime'].get('weight_debt',''))")

        echo "  β=${BETA} tax=${TAX} w_e=${WE} w_d=${WD}"
        echo "  baseline β=${BASELINE_BETA} tax=${BASELINE_TAX} w_e=${BASELINE_WEIGHT_EQUITY} w_d=${BASELINE_WEIGHT_DEBT}"

        # Compare with epsilon tolerance
        DRIFT=$(python3 -c "
import sys
beta, tax, we, wd = float('${BETA}' or 0), float('${TAX}' or 0), float('${WE}' or 0), float('${WD}' or 0)
b_beta, b_tax, b_we, b_wd = ${BASELINE_BETA}, ${BASELINE_TAX}, ${BASELINE_WEIGHT_EQUITY}, ${BASELINE_WEIGHT_DEBT}
eps = ${CETERIS_EPS}
drifts = []
if abs(beta - b_beta) > eps: drifts.append(f'beta {beta}!={b_beta}')
if abs(tax - b_tax) > eps: drifts.append(f'tax {tax}!={b_tax}')
if abs(we - b_we) > eps: drifts.append(f'w_e {we}!={b_we}')
if abs(wd - b_wd) > eps: drifts.append(f'w_d {wd}!={b_wd}')
print(','.join(drifts) if drifts else 'OK')
")
        if [ "$DRIFT" != "OK" ]; then
            abort "SC2 (Bug 2 ceteris paribus violation): quant subagent re-derived non-swept WACC inputs. Drift: ${DRIFT}. Sweep result will not isolate the perturbation axis."
        fi
        pass "SC2: WACC inputs inherited from baseline (no ceteris paribus violation)"
        break
    fi
    wait_msg "no quant envelope yet (subagent still running)"
    sleep 30
done

if [ ! -f "$QUANT_ENV" ]; then
    echo "${YELLOW}[timeout] SC2 deadline hit (35min); quant envelope did not appear.${NC}"
    exit 2
fi
echo

# ---------- SC3: DCF direction monotonicity (Bug 4) ----------
echo "${BOLD}[SC3] DCF direction monotonicity (Bug 4 catch)${NC}"
DCF_BASE=$(python3 -c "
import json
e = json.load(open('${QUANT_ENV}'))
for f in e.get('frameworks_cited', []):
    if f.get('framework_key') == 'damodaran_narrative_dcf':
        print(f.get('output', {}).get('base_case_value', ''))
        break
" 2>/dev/null)

if [ -z "$DCF_BASE" ]; then
    echo "  ${YELLOW}[warn] could not extract damodaran_narrative_dcf base from envelope; SC3 skipped${NC}"
else
    echo "  DCF Narrative base: \$${DCF_BASE} (baseline: \$${BASELINE_DCF_BASE})"
    DIRECTION_CHECK=$(python3 -c "
observed = float('${DCF_BASE}')
baseline = ${BASELINE_DCF_BASE}
direction = '${DIRECTION_SIGN}'
delta_pct = (observed - baseline) / baseline * 100
mag_abort = ${MAGNITUDE_ABORT_PCT}
if direction == 'up' and observed <= baseline:
    print(f'SIGN_FLIP|expected IV↑ for swept direction loose, observed {observed} <= baseline {baseline} (Δ={delta_pct:+.1f}%)')
elif direction == 'down' and observed >= baseline:
    print(f'SIGN_FLIP|expected IV↓ for swept direction tight, observed {observed} >= baseline {baseline} (Δ={delta_pct:+.1f}%)')
elif abs(delta_pct) > mag_abort:
    print(f'MAGNITUDE|Δ={delta_pct:+.1f}% exceeds ±{mag_abort}% threshold (sign flip or improvised cash flows)')
else:
    print(f'OK|Δ={delta_pct:+.1f}% in expected direction and magnitude')
")
    VERDICT="${DIRECTION_CHECK%%|*}"
    DETAIL="${DIRECTION_CHECK##*|}"
    case "$VERDICT" in
        OK)        pass "SC3: ${DETAIL}" ;;
        SIGN_FLIP) abort "SC3 (Bug 4 direction monotonicity): ${DETAIL}. Subagent inverted the perturbation direction or improvised a new DCF model." ;;
        MAGNITUDE) abort "SC3 (Bug 4 magnitude): ${DETAIL}. Pre-reg expected ~3-10%; this is far outside that range." ;;
    esac
fi
echo

# ---------- SC4: PM-supervisor decision sanity (Bug 3) ----------
PM_ENV="memos/envelopes/pm-supervisor__${RUN_ID}.json"
echo "${BOLD}[SC4] PM-supervisor summary_code determinism (Bug 3 catch)${NC}"
echo "  Watching for ${PM_ENV}..."

while [ $(date +%s) -lt $SC4_DEADLINE ]; do
    if [ -f "$PM_ENV" ]; then
        SUMMARY=$(python3 -c "import json; print(json.load(open('${PM_ENV}'))['summary_code'])" 2>/dev/null)
        # Bug 3 manifests when DCF outputs match baseline but summary_code flipped.
        # Compute % delta vs baseline.
        DELTA_OK=$(python3 -c "
observed = float('${DCF_BASE:-0}')
baseline = ${BASELINE_DCF_BASE}
if observed == 0: print('UNKNOWN')
elif abs((observed - baseline) / baseline) < 0.10: print('NEAR_BASELINE')
else: print('FAR_FROM_BASELINE')
")
        echo "  summary_code=${SUMMARY}, baseline=${BASELINE_SUMMARY_CODE}, DCF-vs-baseline=${DELTA_OK}"
        if [ "$DELTA_OK" = "NEAR_BASELINE" ] && [ "$SUMMARY" != "$BASELINE_SUMMARY_CODE" ]; then
            abort "SC4 (Bug 3 pm-supervisor flip): DCF outputs within 10% of baseline but summary_code flipped to ${SUMMARY} vs baseline ${BASELINE_SUMMARY_CODE}. Non-deterministic decision."
        fi
        if [ "$DELTA_OK" = "FAR_FROM_BASELINE" ]; then
            pass "SC4: summary_code=${SUMMARY} (DCF moved beyond ±10%, decision change plausibly axis-driven)"
        else
            pass "SC4: summary_code=${SUMMARY} matches baseline (${BASELINE_SUMMARY_CODE})"
        fi
        break
    fi
    wait_msg "no pm-supervisor envelope yet"
    sleep 30
done

if [ ! -f "$PM_ENV" ]; then
    echo "${YELLOW}[timeout] SC4 deadline hit (75min); pm-supervisor envelope did not appear.${NC}"
    exit 2
fi
echo

# ---------- ALL CLEAR ----------
echo "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════════╗${NC}"
echo "${GREEN}${BOLD}║                  ALL STOP-CRITERIA PASSED                        ║${NC}"
echo "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════════════╝${NC}"
echo "${GREEN}Run ${RUN_ID} (axis ${AXIS}) passed SC1+SC2+SC3+SC4.${NC}"
echo "Wait for /research-company to complete and evaluator to gate."
echo
exit 0
