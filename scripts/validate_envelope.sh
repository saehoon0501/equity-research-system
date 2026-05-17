#!/usr/bin/env bash
# validate_envelope.sh — orchestrator-side per-attempt validation hook.
#
# The /research-company orchestrator calls this script after every
# subagent dispatch. The script wraps src.agent_harness.orchestrator_step
# with thin shell ergonomics:
#
#   - Ensures logs/ + logs/validation_state/ exist.
#   - Resolves repo root from this script's path so the orchestrator can
#     call it with a relative path or absolute path indifferently.
#   - Splits the Python CLI's JSON stdout into:
#       (a) a short status line on stderr for the orchestrator's tool-call
#           log readability ("PASS attempt 1 cost $4.20", etc.)
#       (b) the full structured JSON payload on stdout for the orchestrator
#           to parse and (on RETRY) extract `.delta_prompt`.
#
# Exit codes (passed through from orchestrator_step):
#    0  PASS — orchestrator proceeds to next step.
#   10  RETRY — stdout `.delta_prompt` is the next Agent prompt body.
#   11  ESCALATE — terminal failure; orchestrator halts.
#    2  usage error.
#
# Usage:
#   scripts/validate_envelope.sh \
#       --envelope <path-to-envelope.json> \
#       --run-id <uuid> \
#       --agent-type pm-supervisor \
#       --attempt-cost-usd 4.20 \
#       [--case-ids id1,id2,id3] \
#       [--catalyst-indicators <path>] \
#       [--resolve-evidence-db] \
#       [--max-attempts 3] \
#       [--cost-ceiling-usd 60]
#
# The script forwards every flag to the Python CLI; this wrapper exists
# for setup (dir creation, repo-root resolution) and human-readable
# stderr status — not for arg munging.

set -euo pipefail

# Resolve repo root from the script's location: scripts/ is one level
# below the repo root, so dirname twice. Use BASH_SOURCE to handle the
# `bash scripts/foo.sh` invocation form as well as direct `./foo.sh`.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

mkdir -p logs/validation_state
mkdir -p logs/escalations

# Forward everything to the Python CLI. The Python module's argparse
# is the single source of truth for argument validation.
PY="${PYTHON:-python3}"

# Capture stdout to a temp file so we can both (a) re-emit it on the
# wrapper's stdout for the orchestrator, AND (b) extract a short status
# line for the wrapper's stderr.
TMP_OUT="$(mktemp -t validate_envelope.XXXXXX.json)"
trap 'rm -f "$TMP_OUT"' EXIT

set +e
"$PY" -m src.agent_harness.orchestrator_step "$@" > "$TMP_OUT"
PY_EXIT=$?
set -e

# Re-emit the structured JSON on this script's stdout regardless of the
# Python exit code — even ESCALATE produces a valid JSON payload the
# orchestrator may want to surface to the operator.
cat "$TMP_OUT"

# Build the short status line on stderr (orchestrator tool-call log
# legibility). We use python -c instead of jq to avoid a hard dep on jq;
# everyone already has the system python that ran the CLI.
"$PY" - <<EOF >&2 || true
import json, sys
try:
    with open("$TMP_OUT") as f:
        d = json.load(f)
    fields = [
        f"decision={d.get('decision')}",
        f"attempt_n={d.get('attempt_n')}",
        f"failed_gates={d.get('failed_gate_ids') or 'none'}",
        f"cumulative_cost=USD{d.get('cumulative_cost_usd', 0):.2f}",
    ]
    er = d.get("escalation_reason")
    if er:
        fields.append(f"escalation_reason={er}")
    print("[validate_envelope] " + " ".join(fields))
except Exception as exc:
    print(f"[validate_envelope] could not parse Python CLI output: {exc}")
EOF

exit "$PY_EXIT"
