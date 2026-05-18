#!/usr/bin/env bash
# =============================================================================
# reconcile_orphan_snapshots.sh
#
# Finalizes orphan run_parameters_snapshot rows whose inline terminal UPDATE
# (per /research-company §1.5/§4.5/§6.5) never fired due to orchestrator halt
# between Step 4 INSERT and any terminal UPDATE site.
#
# Per /review-me v7 convergence 2026-05-18: this is the operational fallback
# for H1 (validator-throw orphan window) and the catch-all for any uncaught
# orchestrator halt in §2-§4 between snapshot INSERT and §4.5/§6.5 terminal
# UPDATEs. Reference: docs/superpowers/audits/2026-05-18-parameter-externalization-phase3-audit-checklist.md
#
# DESIGN:
#   - 3-hour recency carve-out protects in-flight runs (tightenable when P99
#     wall-clock empirically observed). Carve-out heuristic; not empirically
#     measured.
#   - Atomic CAS via `WHERE run_status IS NULL RETURNING run_id` — race-safe
#     against late §6.5 'completed' or §4.5 named UPDATE.
#   - Idempotent: only operates on `run_status IS NULL` rows.
#   - Logs to system_errors with full triage payload (run_id, ticker,
#     orphaned_at, reconciled_at, age_seconds).
#
# CONVENTION ESTABLISHED (per /review-me v7 — first DB-touching standalone
# script in /scripts/; previously all DB went through MCP):
#   Reads libpq env vars: PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD.
#   Operator typical invocation (subshell, so env vars do not persist):
#     (set -a; source .env; set +a; ./scripts/reconcile_orphan_snapshots.sh)
#
#   Stack-trace env leak: if this script crashes mid-execution, error
#   messages may include env values from `set -x` traces. Recommend
#   PGPASSFILE (chmod 600) over PGPASSWORD for production cron.
#
# DIAGNOSTIC DISCOVERABILITY:
#   `'failed_uncaught'` is a status marker only — the original cause-of-death
#   is NOT in-band captured (orchestrator halt = no stderr capture path).
#   Operator triage for a 'failed_uncaught' row:
#     1. Note run_id + run_started_at from `system_errors.error_detail`.
#     2. Open Claude Code session log at:
#          ~/.claude/projects/<project-hash>/<session>.jsonl
#        (Local disk; no auto-rotation. Weekly reconciliation cadence is safe.)
#     3. Grep for run_id timestamp window.
#     4. Pre-halt error is the last orchestrator-emitted line before halt.
#
# MANUAL-TRIGGER APPENDIX (one repeatable mechanism per terminal status, for
# smoke validation of C3/C4/C7 — invoke against a sweep parameter set, not
# production):
#   'failed_uncaught': kill orchestrator (Ctrl+C) after §1.5 Step 4 INSERT
#     and before any §1.5/§4.5/§6.5 terminal UPDATE site. Wait 3h+1m, run
#     this script. Verify row finalized to 'failed_uncaught'.
#   'failed_INV-1': INSERT parameter row with monotonicity-violating
#     reinvestment_moat values (sweep tag), invoke `/research-company TICKER
#     --as-of-tag <sweep_uuid>`. Verify row terminates to 'failed_INV-1'.
#   'failed_INV-3': same pattern with austere DCF fade violation.
#   'failed_contamination': mutate sidecar memo JSON between subagent
#     completion and evaluator dispatch. Test-harness only; not live-
#     orchestrator achievable since orchestrator runs back-to-back atomically.
#   'failed_evaluator_dispatch': temporarily revoke evaluator agent Task
#     grants in .claude/settings.json. Invoke /research-company.
#   'rejected': inject contradictory subagent envelopes via mocked memos to
#     force HG fail through all 3 revision rounds. Expensive: $30+ per
#     forced rejection (full subagent chain runs 4 times).
#   'completed': normal happy-path invocation.
# =============================================================================

set -euo pipefail

# --- env-var contract ---
: "${PGHOST:?PGHOST env var required — typical setup: 'set -a; source .env; set +a'}"
: "${PGPORT:?PGPORT env var required}"
: "${PGDATABASE:?PGDATABASE env var required}"
: "${PGUSER:?PGUSER env var required}"
# PGPASSWORD or PGPASSFILE — at least one must resolve via libpq
if [[ -z "${PGPASSWORD:-}" && -z "${PGPASSFILE:-}" ]]; then
    echo "ERROR: neither PGPASSWORD nor PGPASSFILE is set. libpq cannot authenticate." >&2
    exit 1
fi

# --- recency carve-out (heuristic; tighten when P99 measured) ---
RECENCY_THRESHOLD="3 hours"

# --- find orphans ---
ORPHANS=$(psql -A -t -F $'\t' <<SQL
SELECT run_id::text,
       ticker,
       run_started_at::text,
       EXTRACT(EPOCH FROM (NOW() - run_started_at))::int AS age_seconds
FROM run_parameters_snapshot
WHERE run_status IS NULL
  AND run_started_at < NOW() - INTERVAL '${RECENCY_THRESHOLD}'
ORDER BY run_started_at;
SQL
)

if [[ -z "$ORPHANS" ]]; then
    echo "reconciled 0 rows; no orphans within ${RECENCY_THRESHOLD} window"
    exit 0
fi

RECONCILED=0
SKIPPED_RACE=0
FINALIZED_IDS=()

while IFS=$'\t' read -r RID TICKER RUN_STARTED_AT AGE_S; do
    # Atomic CAS — RETURNING discriminates race vs. successful finalize.
    CAS_RESULT=$(psql -A -t <<SQL
UPDATE run_parameters_snapshot
SET run_ended_at = NOW(),
    run_status   = 'failed_uncaught'
WHERE run_id = '${RID}' AND run_status IS NULL
RETURNING run_id::text;
SQL
)
    if [[ -z "$CAS_RESULT" ]]; then
        # Lost the race — another session (orchestrator late terminal UPDATE,
        # or concurrent reconciler) finalized the row first. Skip the
        # system_errors INSERT to avoid phantom-orphan entries that would
        # distort the C9 weekly observability query.
        SKIPPED_RACE=$((SKIPPED_RACE + 1))
        continue
    fi

    # Successful finalize — log to system_errors with full triage payload.
    BLOCKED_DECISION_DATE=$(date -u -d "$RUN_STARTED_AT" "+%Y-%m-%dT%H:%M:%S" 2>/dev/null \
                          || date -u -j -f "%Y-%m-%d %H:%M:%S" "${RUN_STARTED_AT%.*}" "+%Y-%m-%dT%H:%M:%S")

    psql -q <<SQL
INSERT INTO system_errors (source, error_type, error_detail, blocked_decision) VALUES (
  'orphan_reconciler',
  'unfinalized_snapshot',
  json_build_object(
    'run_id',         '${RID}',
    'ticker',         '${TICKER}',
    'orphaned_at',    '${RUN_STARTED_AT}',
    'reconciled_at',  NOW()::text,
    'age_seconds',    ${AGE_S},
    'status_set_to',  'failed_uncaught'
  )::text,
  'research_company_${TICKER}_${BLOCKED_DECISION_DATE}'
);
SQL

    RECONCILED=$((RECONCILED + 1))
    FINALIZED_IDS+=("$RID")
done <<< "$ORPHANS"

# stdout signal — greppable for cron logs
if [[ $RECONCILED -gt 0 ]]; then
    echo "reconciled ${RECONCILED} rows; orphans: $(IFS=,; echo "${FINALIZED_IDS[*]}")"
fi
if [[ $SKIPPED_RACE -gt 0 ]]; then
    echo "skipped ${SKIPPED_RACE} rows (lost race to concurrent finalizer)"
fi
if [[ $RECONCILED -eq 0 && $SKIPPED_RACE -eq 0 ]]; then
    echo "reconciled 0 rows; all candidates were already finalized between SELECT and CAS"
fi
