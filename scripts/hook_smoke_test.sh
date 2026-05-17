#!/usr/bin/env bash
# hook_smoke_test.sh — verify the PostToolUse hook is correctly wired.
#
# Layer 2 ships with a Python validator + a Bash hook + a settings.json
# registration. All three have to line up for the hook to actually fire.
# This smoke test verifies the Bash + Python pieces end-to-end with
# synthetic stdin (the same JSON shape Claude Code sends on PostToolUse).
#
# It does NOT verify that the settings.json registration is actually
# loaded by Claude Code at runtime — that requires an actual session.
# For that final piece, see the post-install verification note at the
# end of this script.
#
# Exits 0 on success, 1 on any assertion failure.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

HOOK="$SCRIPT_DIR/post_agent_validate.sh"

if [ ! -x "$HOOK" ]; then
    echo "FAIL: hook script not executable at $HOOK" >&2
    exit 1
fi

TMPDIR="$(mktemp -d -t hook_smoke.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

ENV_DIR="$TMPDIR/envelopes"
STATE_DIR="$TMPDIR/state"
AUDIT_PATH="$TMPDIR/audit.jsonl"
mkdir -p "$ENV_DIR" "$STATE_DIR"

export POST_AGENT_VALIDATE_ENVELOPE_DIR="$ENV_DIR"
export POST_AGENT_VALIDATE_STATE_DIR="$STATE_DIR"
export POST_AGENT_VALIDATE_AUDIT_PATH="$AUDIT_PATH"

PASS_COUNT=0
FAIL_COUNT=0

pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    echo "  PASS  $1"
}

fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "  FAIL  $1" >&2
}

# ---------------------------------------------------------------------------
# Helper: run the hook with a PostToolUse-shaped payload.
# Prints stdout/stderr and captures exit code into $LAST_EXIT.
# ---------------------------------------------------------------------------
run_hook() {
    local payload="$1"
    set +e
    HOOK_STDERR="$(printf '%s' "$payload" | "$HOOK" 2>&1 >/dev/null)"
    set -e
    set +e
    HOOK_STDOUT="$(printf '%s' "$payload" | "$HOOK" 2>/dev/null)"
    LAST_EXIT=$?
    set -e
}

# ---------------------------------------------------------------------------
# Test 1: tool_name != "Agent" → silent exit 0 (other tools untouched).
# ---------------------------------------------------------------------------
echo "Test 1: non-Agent tool call is ignored"
run_hook '{"tool_name":"Read","tool_input":{"file_path":"/x"}}'
if [ "$LAST_EXIT" = "0" ] && [ -z "$HOOK_STDERR" ]; then
    pass "exit 0 + silent stderr on non-Agent tool"
else
    fail "expected exit 0 silent; got exit=$LAST_EXIT stderr=$HOOK_STDERR"
fi

# ---------------------------------------------------------------------------
# Test 2: skip-listed subagent_type (evaluator) → silent exit 0.
# ---------------------------------------------------------------------------
echo "Test 2: evaluator subagent_type is skip-listed"
run_hook '{"tool_name":"Agent","tool_input":{"subagent_type":"evaluator","prompt":"run_id: smoke-1"}}'
if [ "$LAST_EXIT" = "0" ]; then
    pass "exit 0 on evaluator dispatch"
else
    fail "expected exit 0; got exit=$LAST_EXIT"
fi

# ---------------------------------------------------------------------------
# Test 3: missing run_id in prompt → exit 2 with feedback.
# ---------------------------------------------------------------------------
echo "Test 3: missing run_id in prompt → block + feedback"
run_hook '{"tool_name":"Agent","tool_input":{"subagent_type":"pm-supervisor","prompt":"do stuff"}}'
if [ "$LAST_EXIT" = "2" ] && printf '%s' "$HOOK_STDERR" | grep -q "missing run_id"; then
    pass "exit 2 + 'missing run_id' feedback"
else
    fail "expected exit 2 with 'missing run_id'; got exit=$LAST_EXIT stderr=$HOOK_STDERR"
fi

# ---------------------------------------------------------------------------
# Test 4: missing envelope file → exit 2 with persistence feedback.
# ---------------------------------------------------------------------------
echo "Test 4: missing envelope → block with persistence feedback"
RID="smoke-test-missing-envelope-$$"
run_hook "$(jq -nc --arg p "run_id: $RID" '{tool_name:"Agent",tool_input:{subagent_type:"pm-supervisor",prompt:$p}}')"
if [ "$LAST_EXIT" = "2" ] && printf '%s' "$HOOK_STDERR" | grep -q "did not persist"; then
    pass "exit 2 + 'did not persist' feedback"
else
    fail "expected exit 2 with 'did not persist'; got exit=$LAST_EXIT stderr=$HOOK_STDERR"
fi

# ---------------------------------------------------------------------------
# Test 5: .degraded sidecar → silent exit 0 (recognized valid-skip).
# ---------------------------------------------------------------------------
echo "Test 5: .degraded sidecar is recognized as valid-skip"
RID="smoke-test-degraded-$$"
touch "$ENV_DIR/catalyst-scout__${RID}.degraded"
run_hook "$(jq -nc --arg p "run_id: $RID" '{tool_name:"Agent",tool_input:{subagent_type:"catalyst-scout",prompt:$p}}')"
if [ "$LAST_EXIT" = "0" ] && printf '%s' "$HOOK_STDERR" | grep -q "SKIP (degraded valid)"; then
    pass "exit 0 + degraded-valid log"
else
    fail "expected exit 0 with SKIP log; got exit=$LAST_EXIT stderr=$HOOK_STDERR"
fi

# ---------------------------------------------------------------------------
# Test 6: broken envelope → exit 2 with RETRY + delta_prompt in stderr +
# audit row written.
# ---------------------------------------------------------------------------
echo "Test 6: broken envelope → RETRY with delta_prompt + audit row"
RID="smoke-test-retry-$$"
# Empty JSON envelope fails pm_envelope shape gate.
echo "{}" > "$ENV_DIR/pm-supervisor__${RID}.json"
run_hook "$(jq -nc --arg p "run_id: $RID" '{tool_name:"Agent",tool_input:{subagent_type:"pm-supervisor",prompt:$p}}')"
RETRY_OK=1
if [ "$LAST_EXIT" != "2" ]; then
    fail "expected exit 2 on broken envelope; got $LAST_EXIT"
    RETRY_OK=0
fi
if ! printf '%s' "$HOOK_STDERR" | grep -q "RETRY"; then
    fail "expected RETRY in stderr; got: $HOOK_STDERR"
    RETRY_OK=0
fi
if ! printf '%s' "$HOOK_STDERR" | grep -q "BEGIN DELTA PROMPT"; then
    fail "expected delta_prompt fence in stderr"
    RETRY_OK=0
fi
if [ ! -f "$AUDIT_PATH" ]; then
    fail "audit row not written to $AUDIT_PATH"
    RETRY_OK=0
elif ! grep -q "$RID" "$AUDIT_PATH"; then
    fail "audit row missing run_id $RID"
    RETRY_OK=0
fi
if [ "$RETRY_OK" = "1" ]; then
    pass "exit 2 + RETRY feedback + audit row written"
fi

# ---------------------------------------------------------------------------
# Test 7: settings.local.json contains a PostToolUse → Agent hook entry
# pointing at post_agent_validate.sh.
# ---------------------------------------------------------------------------
echo "Test 7: settings.local.json has PostToolUse → Agent → post_agent_validate.sh"
SETTINGS="$REPO_ROOT/.claude/settings.local.json"
if [ ! -f "$SETTINGS" ]; then
    fail "settings file not found: $SETTINGS"
else
    HOOK_REGISTERED="$(jq -r '
        (.hooks.PostToolUse // [])
        | map(select(.matcher == "Agent"))
        | map(.hooks // [])
        | flatten
        | map(.command // "")
        | map(select(test("post_agent_validate")))
        | length
    ' "$SETTINGS")"
    if [ "$HOOK_REGISTERED" != "0" ] && [ -n "$HOOK_REGISTERED" ]; then
        pass "settings.local.json registers post_agent_validate hook on Agent"
    else
        fail "settings.local.json does NOT register post_agent_validate on Agent — hook will NOT fire"
    fi
fi

# ---------------------------------------------------------------------------
echo ""
echo "=========================================="
echo "Smoke test results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "=========================================="

if [ "$FAIL_COUNT" -gt "0" ]; then
    cat >&2 <<'EOF'

POST-INSTALL VERIFICATION NOTE
-----------------------------
This smoke test verifies the hook script + validator integration. To
verify Claude Code actually invokes the hook at runtime, run a real
`/research-company <ticker>` and check that logs/validation_attempts.jsonl
gains rows for each Agent() dispatch. Absence of rows after a real run
means the settings.local.json hook registration is not being loaded —
restart Claude Code after editing settings.

EOF
    exit 1
fi

exit 0
