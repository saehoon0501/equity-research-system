#!/usr/bin/env bash
# post_agent_validate.sh — PostToolUse hook for Claude Code's Agent tool.
#
# Layer 2 wiring (2026-05-16): replaces the explicit per-dispatch Bash
# validation blocks (§2.9 / §3.8 / §4.1 of research-company.md) with a
# runtime-enforced hook. Fires automatically after every `Agent()` call
# regardless of whether the orchestrator remembers to invoke validation.
#
# Contract:
#   - Reads PostToolUse JSON from stdin (Claude Code hook protocol).
#   - Extracts `tool_input.subagent_type` and the dispatch prompt.
#   - Pulls `run_id: <uuid>` from the prompt (orchestrator MUST include).
#   - Locates the envelope at memos/envelopes/<agent_type>__<run_id>.json.
#   - Invokes src.shared.agent_harness.orchestrator_step for validation.
#   - Exit semantics (per Claude Code hook docs):
#       0  — silent success, orchestrator proceeds.
#       2  — block with stderr fed to LLM as feedback. Used for both
#            RETRY (with delta_prompt in stderr) and ESCALATE (with
#            halt instructions in stderr).
#       other non-zero — surfaced to user but does not block tool use.
#
# Defensive defaults (fail-safe, not fail-secure):
#   - Tool name not in {"Task","Agent"} → silent exit 0 (other tools untouched).
#   - subagent_type ∈ {evaluator, general-purpose} → silent exit 0
#     (don't recurse into our own validator; don't gate ad-hoc agents).
#   - Missing run_id in prompt → exit 2 with a "you must include run_id"
#     feedback message so the orchestrator gets corrected.
#   - Missing envelope file AND no .degraded sidecar → exit 2 with a
#     "subagent forgot to persist envelope" feedback message.
#   - .degraded sidecar present → exit 0 (recognized valid-skip state,
#     e.g., catalyst-scout halted on polygon offline).
#
# Environment overrides (mostly for tests):
#   POST_AGENT_VALIDATE_ENVELOPE_DIR — override envelope root (default memos/envelopes)
#   POST_AGENT_VALIDATE_STATE_DIR    — override state dir (default logs/validation_state)
#   POST_AGENT_VALIDATE_AUDIT_PATH   — override audit jsonl (default logs/validation_attempts.jsonl)
#   POST_AGENT_VALIDATE_PYTHON       — python interpreter (default python3)
#   POST_AGENT_VALIDATE_DRY_RUN=1    — log decision to stderr, always exit 0 (test mode)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

ENVELOPE_DIR="${POST_AGENT_VALIDATE_ENVELOPE_DIR:-memos/envelopes}"
STATE_DIR="${POST_AGENT_VALIDATE_STATE_DIR:-logs/validation_state}"
AUDIT_PATH="${POST_AGENT_VALIDATE_AUDIT_PATH:-logs/validation_attempts.jsonl}"
PY="${POST_AGENT_VALIDATE_PYTHON:-python3}"
DRY_RUN="${POST_AGENT_VALIDATE_DRY_RUN:-0}"

mkdir -p "$STATE_DIR" "$ENVELOPE_DIR" "$(dirname "$AUDIT_PATH")"

# ---------------------------------------------------------------------------
# Read PostToolUse payload from stdin.
# ---------------------------------------------------------------------------
PAYLOAD="$(cat)"

# Empty stdin → not a real hook invocation, silent exit.
if [ -z "$PAYLOAD" ]; then
    exit 0
fi

TOOL_NAME="$(printf '%s' "$PAYLOAD" | jq -r '.tool_name // empty')"
# Subagent-dispatch tool is "Task" in current Claude Code; accept legacy "Agent" too.
# Must stay in sync with the PostToolUse `matcher` in .claude/settings.json.
if [ "$TOOL_NAME" != "Task" ] && [ "$TOOL_NAME" != "Agent" ]; then
    exit 0
fi

SUBAGENT_TYPE="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.subagent_type // empty')"
PROMPT="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.prompt // empty')"

# Skip-list: don't gate our own validator, the catch-all agent, or any
# explorer/planner agents whose output isn't part of the research pipeline.
case "$SUBAGENT_TYPE" in
    ""|evaluator|general-purpose|Explore|Plan|claude|claude-code-guide|statusline-setup|research-skill-executor)
        exit 0
        ;;
esac

# ---------------------------------------------------------------------------
# Map subagent_type → artifact_type for the validator dispatcher.
# Unknown agent types exit silent: hook only enforces the pipeline it knows.
# ---------------------------------------------------------------------------
case "$SUBAGENT_TYPE" in
    quantitative-analyst)    ARTIFACT_TYPE="quant_memo" ;;
    strategic-analyst)       ARTIFACT_TYPE="strategic_memo" ;;
    catalyst-scout)          ARTIFACT_TYPE="catalyst_memo" ;;
    pm-supervisor)           ARTIFACT_TYPE="pm_envelope" ;;
    tactical-overlay)        ARTIFACT_TYPE="tactical_envelope" ;;
    mean-reversion-overlay)  ARTIFACT_TYPE="reversion_envelope" ;;
    *)                       exit 0 ;;
esac

# ---------------------------------------------------------------------------
# Extract run_id from the dispatch prompt. The orchestrator MUST embed it
# as a substring "run_id: <uuid>" or "run_id=<uuid>". We accept hex UUIDs
# and short slug forms (e.g., "abc-123") because tests use slugs.
# ---------------------------------------------------------------------------
# grep returns 1 on no-match which would abort the pipeline under
# pipefail; trap it explicitly so the empty-RUN_ID branch can fire.
RUN_ID_RAW="$(printf '%s' "$PROMPT" | grep -oE 'run_id[[:space:]]*[:=][[:space:]]*[A-Za-z0-9._-]+' | head -1 || true)"
RUN_ID="$(printf '%s' "$RUN_ID_RAW" | sed -E 's/^run_id[[:space:]]*[:=][[:space:]]*//')"

if [ -z "$RUN_ID" ]; then
    cat >&2 <<EOF
[post_agent_validate] BLOCK: missing run_id in dispatch prompt to ${SUBAGENT_TYPE}.

The Layer 2 PostToolUse hook requires every Agent() dispatch in the
research pipeline to include a "run_id: <uuid>" line in the prompt body
so the hook can locate the persisted envelope. Add the line to your
dispatch prompt and re-dispatch.

Example:
  Agent(${SUBAGENT_TYPE}, "run_id: 7f3c2b14-...\\n<rest of prompt>")
EOF
    exit 2
fi

# Canonical envelope path.
ENVELOPE_PATH="${ENVELOPE_DIR}/${SUBAGENT_TYPE}__${RUN_ID}.json"
DEGRADED_PATH="${ENVELOPE_DIR}/${SUBAGENT_TYPE}__${RUN_ID}.degraded"

# Recognized valid-skip: subagent halted on degraded-but-valid input
# (e.g., catalyst-scout on polygon offline). The sidecar's mere
# existence is the signal.
if [ -f "$DEGRADED_PATH" ]; then
    echo "[post_agent_validate] SKIP (degraded valid): ${SUBAGENT_TYPE} run_id=${RUN_ID}" >&2
    exit 0
fi

if [ ! -f "$ENVELOPE_PATH" ]; then
    cat >&2 <<EOF
[post_agent_validate] BLOCK: ${SUBAGENT_TYPE} returned but did not persist
its envelope to the canonical path.

Expected: ${ENVELOPE_PATH}

Every research-pipeline subagent MUST atomically write its structured
envelope to memos/envelopes/<agent_type>__<run_id>.json before returning.
If the agent halted on a degraded-but-valid upstream state, it should
write an empty sidecar at ${DEGRADED_PATH} instead.

Re-dispatch ${SUBAGENT_TYPE} with the persistence instruction reinforced.
EOF
    exit 2
fi

# ---------------------------------------------------------------------------
# Cost computation — measured from tool_response.usage when available, with
# per-agent constants as fallback. Pricing assumes Sonnet 4.6 for the
# research pipeline (see research-company.md §"Cost estimate"). The
# circuit-breaker ceiling and cumulative_cost_usd field downstream rely on
# this value; flat per-agent constants meant identical recorded cost for
# 3-tool-use retries vs 31-tool-use first attempts (e.g., quant attempt 1
# at 160K tokens recorded the same $14 as the 83K-token passing retry).
# ---------------------------------------------------------------------------
USAGE_TOTAL="$(printf '%s' "$PAYLOAD" | jq -r '.tool_response.totalTokens // 0' 2>/dev/null || echo 0)"
USAGE_INPUT="$(printf '%s' "$PAYLOAD" | jq -r '.tool_response.usage.input_tokens // 0' 2>/dev/null || echo 0)"
USAGE_CACHE_CREATE="$(printf '%s' "$PAYLOAD" | jq -r '.tool_response.usage.cache_creation_input_tokens // 0' 2>/dev/null || echo 0)"
USAGE_CACHE_READ="$(printf '%s' "$PAYLOAD" | jq -r '.tool_response.usage.cache_read_input_tokens // 0' 2>/dev/null || echo 0)"
USAGE_OUTPUT="$(printf '%s' "$PAYLOAD" | jq -r '.tool_response.usage.output_tokens // 0' 2>/dev/null || echo 0)"

if [ "${USAGE_TOTAL:-0}" -gt 0 ] 2>/dev/null && [ "${USAGE_OUTPUT:-0}" -gt 0 ] 2>/dev/null; then
    # Anthropic Sonnet 4.6 pricing per million tokens (USD):
    #   input            = $3.00
    #   cache_create_5m  = $3.75  (1.25× base; 5-min ephemeral is the default)
    #   cache_read       = $0.30
    #   output           = $15.00
    # Tactical-overlay may run on Haiku ($1 / $5) — overestimation is fine
    # for a circuit-breaker tripwire, not for finance-grade accounting.
    COST_ESTIMATE_USD="$(python3 -c "
in_t=int(${USAGE_INPUT:-0})
cc=int(${USAGE_CACHE_CREATE:-0})
cr=int(${USAGE_CACHE_READ:-0})
out=int(${USAGE_OUTPUT:-0})
cost = (in_t * 3.0 + cc * 3.75 + cr * 0.30 + out * 15.0) / 1_000_000
print(f'{cost:.4f}')
" 2>/dev/null || echo "")"

    if [ -z "$COST_ESTIMATE_USD" ]; then
        # python3 failure or unexpected non-numeric input — fall through to constants.
        USAGE_TOTAL=0
    fi
fi

if [ "${USAGE_TOTAL:-0}" -le 0 ] 2>/dev/null || [ -z "${COST_ESTIMATE_USD:-}" ]; then
    # Fallback: tool_response.usage not present or extraction failed.
    case "$SUBAGENT_TYPE" in
        quantitative-analyst)    COST_ESTIMATE_USD="14.0" ;;
        strategic-analyst)       COST_ESTIMATE_USD="14.0" ;;
        catalyst-scout)          COST_ESTIMATE_USD="18.0" ;;
        pm-supervisor)           COST_ESTIMATE_USD="11.0" ;;
        tactical-overlay)        COST_ESTIMATE_USD="1.0" ;;
        mean-reversion-overlay)  COST_ESTIMATE_USD="1.0" ;;
        *)                       COST_ESTIMATE_USD="5.0" ;;
    esac
    COST_SOURCE="fallback_constant"
else
    COST_SOURCE="measured(tot=${USAGE_TOTAL},in=${USAGE_INPUT},cc=${USAGE_CACHE_CREATE},cr=${USAGE_CACHE_READ},out=${USAGE_OUTPUT})"
fi

echo "[post_agent_validate] cost source=${COST_SOURCE} cost_usd=${COST_ESTIMATE_USD} agent=${SUBAGENT_TYPE}" >&2

# ---------------------------------------------------------------------------
# Optional context sidecar:
#   memos/envelopes/<agent>__<run_id>.context.json
# carries optional --case-ids / --catalyst-indicators payloads written by
# the orchestrator before the Agent() dispatch. Absence is fine.
# ---------------------------------------------------------------------------
CONTEXT_PATH="${ENVELOPE_DIR}/${SUBAGENT_TYPE}__${RUN_ID}.context.json"
EXTRA_ARGS=()
if [ -f "$CONTEXT_PATH" ]; then
    CASE_IDS="$(jq -r '.case_ids // empty' "$CONTEXT_PATH" 2>/dev/null || true)"
    if [ -n "$CASE_IDS" ] && [ "$CASE_IDS" != "null" ]; then
        EXTRA_ARGS+=(--case-ids "$CASE_IDS")
    fi
    CAT_IND="$(jq -r '.catalyst_indicators // empty' "$CONTEXT_PATH" 2>/dev/null || true)"
    if [ -n "$CAT_IND" ] && [ "$CAT_IND" != "null" ]; then
        EXTRA_ARGS+=(--catalyst-indicators "$CAT_IND")
    fi
    RESOLVE_DB="$(jq -r '.resolve_evidence_db // empty' "$CONTEXT_PATH" 2>/dev/null || true)"
    if [ "$RESOLVE_DB" = "true" ]; then
        EXTRA_ARGS+=(--resolve-evidence-db)
    fi
fi

# ---------------------------------------------------------------------------
# Invoke the Python validator.
# ---------------------------------------------------------------------------
TMP_OUT="$(mktemp -t post_agent_validate.XXXXXX.json)"
trap 'rm -f "$TMP_OUT"' EXIT

set +e
"$PY" -m src.shared.agent_harness.orchestrator_step \
    --envelope "$ENVELOPE_PATH" \
    --run-id "$RUN_ID" \
    --agent-type "$SUBAGENT_TYPE" \
    --artifact-type "$ARTIFACT_TYPE" \
    --attempt-cost-usd "$COST_ESTIMATE_USD" \
    --state-dir "$STATE_DIR" \
    --audit-path "$AUDIT_PATH" \
    ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} \
    > "$TMP_OUT"
PY_EXIT=$?
set -e

DECISION="$(jq -r '.decision // "UNKNOWN"' "$TMP_OUT" 2>/dev/null || echo "UNKNOWN")"

# Dry-run mode (test harness): always exit 0, log decision.
if [ "$DRY_RUN" = "1" ]; then
    echo "[post_agent_validate] DRY_RUN decision=${DECISION} py_exit=${PY_EXIT} agent=${SUBAGENT_TYPE} run_id=${RUN_ID}" >&2
    cat "$TMP_OUT" >&2
    exit 0
fi

case "$DECISION" in
    PASS)
        echo "[post_agent_validate] PASS ${SUBAGENT_TYPE} run_id=${RUN_ID}" >&2
        exit 0
        ;;
    RETRY)
        # Block with delta_prompt as feedback. The LLM will see this on
        # its next turn and is expected to re-dispatch Agent() with the
        # delta_prompt as the new prompt body.
        ATTEMPT_N="$(jq -r '.attempt_n // 1' "$TMP_OUT")"
        FAILED_GATES="$(jq -r '.failed_gate_ids // [] | join(",")' "$TMP_OUT")"
        DELTA_PROMPT="$(jq -r '.delta_prompt // ""' "$TMP_OUT")"
        {
            echo "[post_agent_validate] RETRY ${SUBAGENT_TYPE} run_id=${RUN_ID} attempt=${ATTEMPT_N} failed=${FAILED_GATES}"
            echo ""
            echo "TIER-1 VALIDATION FAILED — re-dispatch ${SUBAGENT_TYPE} with the"
            echo "delta-prompt below as the new prompt body. Do NOT mutate the"
            echo "delta-prompt; pass it verbatim. The hook will fire again on the"
            echo "next dispatch."
            echo ""
            echo "--- BEGIN DELTA PROMPT ---"
            echo "$DELTA_PROMPT"
            echo "--- END DELTA PROMPT ---"
        } >&2
        exit 2
        ;;
    ESCALATE)
        REASON="$(jq -r '.escalation_reason // "unknown"' "$TMP_OUT")"
        ATTEMPTS="$(jq -r '.attempt_n // 0' "$TMP_OUT")"
        {
            echo "[post_agent_validate] ESCALATE ${SUBAGENT_TYPE} run_id=${RUN_ID} reason=${REASON} attempts=${ATTEMPTS}"
            echo ""
            echo "TIER-1 VALIDATION HALTED — terminal failure for ${SUBAGENT_TYPE}."
            echo "Reason: ${REASON}"
            echo "Audit trail: logs/validation_attempts.jsonl (filter run_id=${RUN_ID})"
            echo ""
            echo "Halt /research-company. Do NOT persist the non-conforming"
            echo "envelope to execution_recommendations. Surface this to the"
            echo "operator for triage."
        } >&2
        exit 2
        ;;
    *)
        # Unparseable validator output — surface but don't block.
        echo "[post_agent_validate] WARN unparseable validator output (py_exit=${PY_EXIT}); see ${TMP_OUT}" >&2
        cat "$TMP_OUT" >&2 || true
        exit 0
        ;;
esac
