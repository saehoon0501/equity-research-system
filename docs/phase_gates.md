# Phase gates — tactical-overlay durable artifact

**Status:** v1 locked 2026-05-22 (closes G-CHECK-5 + G-CHECK-6 from observability-readiness-v5-final; G-CHECK-2 ack-construct lock pending operator decision).
**Purpose:** single durable artifact carrying phase-related decisions and dates that must outlive operator memory + calendar entries. Append-only by convention.

---

## §1 — G-CHECK-6: Phase 2 trigger + Phase 3 deadline dates

Phase 2 trigger condition: `envelope_count ≥ 50 AND ticker_count ≥ 5` across persisted `tactical-overlay__*.json` envelopes since 2026-05-22 (tactical-overlay launch).

Phase 3 deadline: 18 months from Phase 2 trigger date (Section 2.1 v5).

| Phase | Status | Date | Notes |
|---|---|---|---|
| Phase 1 acceptance window opened | OPEN | 2026-05-22 | Acceptance gate spec at `docs/phase_1_acceptance_spec.md` |
| Phase 2 trigger | NOT YET FIRED | TBD until trigger condition met | Update this row with the exact YYYY-MM-DD on the first envelope that crosses both 50+ AND 5-ticker thresholds |
| Phase 3 deadline | NOT YET SET | TBD = Phase 2 trigger date + 18mo | Calculate and write the exact date when Phase 2 trigger row is filled in |
| Phase 3 closeout | NOT YET FIRED | TBD ≤ Phase 3 deadline | Update with the exact closeout date and outcome (re-merge / keep split) |

**Update protocol:** when the Phase 2 trigger condition is mechanically detected (operator ad-hoc SQL per F4), commit a doc patch to this file with the exact date.

**Complementary check (v2 — Reviewer D iteration-1 catch):** because doc-patch-as-event is unbounded against feature-branch-never-merged or operator forgetting, the `/research-company` orchestrator §1.5 (parameter snapshot block) MUST include a one-line pre-flight check on EVERY run:

```
1. SELECT count(*), count(distinct ticker) FROM counterfactual_ledger
   WHERE run_id IN (SELECT run_id FROM run_parameters_snapshot ORDER BY created_at DESC LIMIT 50).
2. IF envelope_count >= 50 AND ticker_count >= 5 AND the Phase 2 row above is still
   marked "NOT YET FIRED": surface a system alert ("Phase 2 trigger condition met but
   phase_gates.md row not yet updated; commit the doc patch").
```

This complementary check uses EXISTING surfaces (postgres + this doc file); no new tables. The doc patch remains the canonical event; the check exists only to prevent silent omission. Implementation: 5 lines of /research-company §1.5 SQL + a stderr surfacing in the post-snapshot validator. Recorded as a v0.2 /research-company spec patch dependency (NOT bundled with this G-CHECK landing).

Operator + future-self both rely on this row being current.

---

## §2 — G-CHECK-5: ESCALATE resolution-row schema (spec-only; implementation deferred)

When the PostToolUse hook emits `decision: "ESCALATE"` (max attempts exceeded), the operator unblocks the run manually. The resolution outcome must be persisted so the JSONL ledger has paired open/close events. Spec:

### Resolution-row appended to `logs/validation_attempts.jsonl`

```json
{
  "run_id": "<uuid matching the original ESCALATE row>",
  "agent_type": "<string matching the original>",
  "attempt_n": <int matching the original>,
  "resolution_event": true,
  "resolution_outcome": "operator_override_accept | operator_override_reject | retry_succeeded_offline | run_abandoned",
  "resolution_notes": "<free-form operator note, ≤500 chars>",
  "resolution_timestamp_unix": <int>,
  "resolution_by": "<operator-id>"
}
```

### Linkage rule

The resolution row's `(run_id, agent_type, attempt_n)` triple MUST match the ESCALATE row's same triple. A SELECT/grep over the JSONL filtering on `run_id` + `agent_type` returns BOTH the ESCALATE row (`resolution_event` absent) AND the resolution row (`resolution_event: true`). Operator queries for "all ESCALATE events without resolution" use this asymmetric pair.

### Writer implementation (v2 — Reviewer D iteration-1 catch: stub now, not later)

v1 said "defer writer until first ESCALATE fires." Iteration-1 caught that manual-append friction is exactly when verbal-only resolution wins for the highest-information event of the system's lifetime. v2 ships the stub now.

**Stub script:** `scripts/append_escalate_resolution.py` (10 lines) — opens `logs/validation_attempts.jsonl` in append mode, writes a row matching the schema above with `resolution_event: true`, fsyncs, exits 0. Operator invokes when unblocking:

```bash
python3 scripts/append_escalate_resolution.py \
    --run-id <uuid> --agent-type <name> --attempt-n <int> \
    --outcome operator_override_accept --notes "<reason>"
```

Stub is intentionally minimal — no validation of run_id existence in JSONL (premature), no audit-trail signature (also premature). When the first ESCALATE fires, operator invokes the stub; refinements (validation, signature) added based on observed friction.

The spec exists pre-launch + the stub script exists pre-launch so the FIRST ESCALATE event is captured at the moment it happens, not after verbal resolution loses the data.

---

## §3 — G-CHECK-2: operational "ack" definition (decision surface for operator)

Phase 2 quadrant matrix requires an `ack-rate diff` axis (BUY-HIGH vs BUY-MED ack-rates). "Ack" has no canonical operational definition; the choice changes what is measured. Operator must lock construct + candidate before Phase 2 ack-rate tracking can be designed.

### Construct dimensions

1. **Discipline** — did the operator record a decision? (Independent of execution.)
2. **Deployment** — did the operator deploy capital? (Independent of decision-rigor.)
3. **Attention-floor** — did the operator read the envelope at all? (Independent of both.)

The construct is a *measurement-design* choice, not a *value* choice; different constructs yield different Phase 2 quadrant interpretations.

### Candidate menu (described, not prescribed)

| # | Candidate | Construct | Latency | Denominator effect |
|---|---|---|---|---|
| 1 | Broker fill (`mcp__broker__poll_for_fills`) | Deployment | Execution clock | Excludes paper/watchlist-only validation |
| 2 | Watchlist add | Deployment (partial) | Hours-days | **Shifts** (excludes deliberate SKIP/AVOID acks-by-inaction) |
| 3 | Position size > 0 (`mcp__broker__get_positions` per run) | Deployment | Trading session | Loses no-position-but-acted-as-decided |
| 4 | Structured run-notes (decision field, not free text) | Discipline | Same-session | "Share of runs with recorded decision" |
| 5 | Verbal / git-log | None (defeats trackability) | N/A | Leave only if ack-rate is willing to be judgment-call |
| 6 | Revealed-attention / envelope-read (file-access ts / mark-as-read toggle) | Attention-floor | Real-time | **Denominator-of-denominators**: separates "ignored" from "read-and-rejected" |
| 7 | Re-invocation of /research-company on same ticker within N days (v2 — iteration-1 catch) | Consequence | N-day window | Behavioral signal — "operator took rec seriously enough to re-research"; distinct from execution AND from attention |

### Pairing structure

Candidate 6 is a *precondition for interpretability* of any of 1-4. Without an attention-floor measurement, low Phase 2 ack-rate is ambiguous between "envelopes bad" and "envelopes unread" — different corrective actions. Operator likely locks one of {1,2,3,4} AND 6.

### Lock decision (PENDING — operator to fill in)

```
Locked construct:    <discipline | deployment | attention-floor | consequence>
Locked candidate(s): <#N> (+ #6 if floor measurement desired)
Locked by:           <operator-id>
Locked date:         <YYYY-MM-DD>
Rationale:           <1-2 sentences>
```

**Forcing function (v2 — Reviewer D iteration-1 catch):** if the lock-block is still blank at `envelope_count >= 25` (half the Phase 2 window), the /research-company orchestrator §1.5 pre-flight check (see §1 above) surfaces a stderr alert: "F2 ack-construct still unlocked at envelope 25; lock before envelope 50 or accept Phase 2 ack-rate axis becomes judgment-call only."

If still unlocked at envelope_count = 50: Phase 2 ack-rate analysis halts (no retro-relabeling) until the operator locks. Phase 2 returns-spread (the other quadrant axis) proceeds independently.

Default-if-never-locked: NO default. Retro-labeling at the 18-month Phase 3 boundary would bias the result; better to surface the unlocked state honestly. Operator can lock at any time before envelope 50; locking after envelope 25 is permitted (the forcing function is alert-only, not hard-block).

Once locked, the tracking schema design (table additions / file naming / persistence path) flows from the chosen candidate(s).

---

## §4 — Deferred / post-launch items (ranked v2 per iteration-1 catch)

Ranked by precedence; do F4 before F1, F1 before G3-OPEN, etc. F4 dominates because Phase 2 detection reliability gates Phase 1→Phase 2 transition.

| # | Item | Reason | Trigger to revisit |
|---|---|---|---|
| 1 | F4 — Phase 2 trigger detection automation | If §1 complementary check fires false-positive or never fires, doc-patch-as-event is fragile; automation gates Phase 2 reliability | Earlier of: ad-hoc SQL becomes burdensome OR Phase 2 trigger date approaches |
| 2 | F1 — counterfactual_ledger schema add for tactical_disposition column | Only needed if JSON-scan latency proves slow at scale | Phase 2 trigger fires + scan latency > 5min |
| 3 | G3-OPEN — counterfactual_ledger.envelope_id column purpose | Possibly vestigial; no launch-blocking consequence | Quarterly housekeeping |
| 4 | Section 2.1 Phase 3 default action at deadline | Spec'd as "re-merge to single BUY" but reversible if evidence emerges | Phase 3 deadline approach |
