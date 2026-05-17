#!/usr/bin/env bash
# audit_run.sh — post-run inspection for Layer 2 wiring.
#
# Usage:
#   scripts/audit_run.sh <run_id>           # summary
#   scripts/audit_run.sh <run_id> --full    # + state file dump per agent
#   scripts/audit_run.sh --list             # recent run_ids from audit log
#
# Reports:
#   - Envelopes persisted at canonical path (which agents wrote, which didn't)
#   - Validation attempts per agent (PASS / RETRY / ESCALATE history)
#   - Cumulative cost across all attempts in this run
#   - Final decision per agent (with failed gates on retries)
#
# This is the operator's "did the hook actually fire" check after a real
# /research-company invocation. Empty output for a run that supposedly
# completed = settings.local.json hook is not loading; restart Claude Code.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

ENV_DIR="memos/envelopes"
STATE_DIR="logs/validation_state"
AUDIT_PATH="logs/validation_attempts.jsonl"

if [ "${1:-}" = "--list" ]; then
    if [ ! -f "$AUDIT_PATH" ]; then
        echo "No audit log yet: $AUDIT_PATH"
        echo "(hook has never fired — first /research-company run is pending)"
        exit 0
    fi
    echo "Recent run_ids in $AUDIT_PATH:"
    jq -r '.run_id' "$AUDIT_PATH" | awk '!seen[$0]++' | tail -10
    exit 0
fi

if [ $# -lt 1 ]; then
    cat >&2 <<EOF
usage: scripts/audit_run.sh <run_id> [--full]
       scripts/audit_run.sh --list

Inspect the Layer 2 wiring trail for a single research-company run.
EOF
    exit 2
fi

RUN_ID="$1"
FULL="${2:-}"

echo "============================================================"
echo "Audit for run_id: $RUN_ID"
echo "============================================================"

# ---------------------------------------------------------------------------
# Section 1: envelopes persisted
# ---------------------------------------------------------------------------
echo ""
echo "[1/4] Envelopes at $ENV_DIR/<agent>__${RUN_ID}.{json,degraded}"
echo "------------------------------------------------------------"
FOUND_ANY_ENV=0
for agent in quantitative-analyst strategic-analyst catalyst-scout pm-supervisor; do
    ENV_PATH="$ENV_DIR/${agent}__${RUN_ID}.json"
    DEG_PATH="$ENV_DIR/${agent}__${RUN_ID}.degraded"
    if [ -f "$ENV_PATH" ]; then
        SIZE="$(wc -c < "$ENV_PATH" | tr -d ' ')"
        echo "  PERSISTED   $agent  (${SIZE} bytes)"
        FOUND_ANY_ENV=1
    elif [ -f "$DEG_PATH" ]; then
        echo "  DEGRADED    $agent  (.degraded sidecar present — valid skip)"
        FOUND_ANY_ENV=1
    else
        echo "  MISSING     $agent  (no envelope, no .degraded sidecar)"
    fi
done

if [ "$FOUND_ANY_ENV" = "0" ]; then
    echo ""
    echo "  WARNING: no envelopes found for run_id=$RUN_ID."
    echo "  Either the run never happened OR no subagent wrote to the canonical path."
fi

# ---------------------------------------------------------------------------
# Section 2: validation attempts from audit log
# ---------------------------------------------------------------------------
echo ""
echo "[2/4] Validation attempts in $AUDIT_PATH"
echo "------------------------------------------------------------"
if [ ! -f "$AUDIT_PATH" ]; then
    echo "  Audit log does not exist — hook has never fired in this repo."
    echo "  If you just ran /research-company and see this, the hook is NOT installed."
    echo "  Action: verify .claude/settings.local.json has hooks.PostToolUse.Agent entry,"
    echo "          then restart Claude Code."
    exit 0
fi

ROW_COUNT="$(jq -r --arg rid "$RUN_ID" 'select(.run_id == $rid) | .run_id' "$AUDIT_PATH" 2>/dev/null | wc -l | tr -d ' ')"

if [ "$ROW_COUNT" = "0" ]; then
    echo "  No validation rows for run_id=$RUN_ID."
    echo ""
    echo "  This usually means:"
    echo "  (a) Hook is not installed / settings not loaded → check settings.local.json"
    echo "  (b) Orchestrator did not include 'run_id: $RUN_ID' in dispatch prompts"
    echo "  (c) Subagents did not persist envelopes → hook exited 2 on 'missing envelope'"
    echo "      (those exits would have surfaced as orchestrator feedback messages)"
else
    echo "  $ROW_COUNT validation attempts recorded for this run."
    echo ""
    printf '  %-22s %-10s %-10s %-6s %s\n' "AGENT" "DECISION" "ATTEMPT" "COST" "FAILED_GATES"
    printf '  %-22s %-10s %-10s %-6s %s\n' "-----" "--------" "-------" "----" "------------"
    jq -r --arg rid "$RUN_ID" '
        select(.run_id == $rid)
        | "\(.agent_type)\t\(.decision)\t\(.attempt_n)\t$\(.cumulative_cost_usd // 0 | tostring)\t\(.failed_gate_ids // [] | join(","))"
    ' "$AUDIT_PATH" | awk -F'\t' '{ printf "  %-22s %-10s %-10s %-6s %s\n", $1, $2, $3, $4, ($5 == "" ? "—" : $5) }'
fi

# ---------------------------------------------------------------------------
# Section 3: cumulative cost
# ---------------------------------------------------------------------------
echo ""
echo "[3/4] Cumulative validation-attempt cost"
echo "------------------------------------------------------------"
if [ "$ROW_COUNT" != "0" ]; then
    TOTAL="$(jq -r --arg rid "$RUN_ID" '
        [ select(.run_id == $rid) | .attempt_cost_usd // 0 ]
        | add // 0
    ' "$AUDIT_PATH" | jq -s 'add // 0')"
    # Per-agent breakdown.
    jq -r --arg rid "$RUN_ID" '
        select(.run_id == $rid)
        | "\(.agent_type)\t\(.attempt_cost_usd // 0)"
    ' "$AUDIT_PATH" | awk -F'\t' '{ totals[$1] += $2 } END { for (k in totals) printf "  %-22s $%.2f\n", k, totals[k] }'
    echo "  ----------------------------------"
    printf "  %-22s \$%.2f\n" "TOTAL" "$TOTAL"
else
    echo "  (no rows to sum)"
fi

# ---------------------------------------------------------------------------
# Section 4: state files (only with --full)
# ---------------------------------------------------------------------------
if [ "$FULL" = "--full" ]; then
    echo ""
    echo "[4/4] State files at $STATE_DIR/<run_id>__<agent>.json"
    echo "------------------------------------------------------------"
    SHOWN=0
    for f in "$STATE_DIR"/${RUN_ID}__*.json; do
        if [ -f "$f" ]; then
            echo ""
            echo "  $f"
            jq '.' "$f" 2>/dev/null | sed 's/^/    /' || cat "$f" | sed 's/^/    /'
            SHOWN=1
        fi
    done
    if [ "$SHOWN" = "0" ]; then
        echo "  (no state files for this run_id)"
    fi
else
    echo ""
    echo "[4/4] State files: pass --full to dump per-agent state JSON"
fi

echo ""
echo "============================================================"
echo "Done. Quick health check:"
if [ "$FOUND_ANY_ENV" = "1" ] && [ "$ROW_COUNT" != "0" ]; then
    echo "  GREEN — hook fired and envelopes were persisted."
elif [ "$FOUND_ANY_ENV" = "1" ] && [ "$ROW_COUNT" = "0" ]; then
    echo "  RED — envelopes persisted but hook never fired."
    echo "        settings.local.json registration is not loading. Restart Claude Code."
elif [ "$FOUND_ANY_ENV" = "0" ] && [ "$ROW_COUNT" != "0" ]; then
    echo "  YELLOW — hook fired but subagents did not persist."
    echo "          Check subagent spec edits took effect; restart Claude Code may be needed."
else
    echo "  GREY — nothing recorded. Run did not happen OR contracts are completely broken."
fi
echo "============================================================"
