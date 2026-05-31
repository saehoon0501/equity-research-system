---
description: One after-market walk-forward tuning cycle over the reactive CFD layer (§14). Reads the model trace up to an in-sample boundary (firewalled) + drains the after-market event queue, LLM-fits a non-trivial trial set of candidate configs, re-simulates each (and the incumbent) over CPCV partitions via the consumed reactive-replay-harness, scores them on the survival-net risk-adjusted metric + calibration, runs a deterministic overfitting-corrected gate (DSR + PSR/MinTRL + PBO + §13 guard, no human sign-off), and on a promote publishes the validated version into the P2 parameter machinery + advances the IS boundary — then emits a falsifiable, key-correlated tuner-action audit on promote AND decline. Never deploys/hot-swaps; never fits in-session; paper-only v0.1; always under the operator kill switch.
argument-hint: (none — dispatched at a walk-forward boundary by a scheduler or a drained event, not interactively)
---

# /walkforward-tune

**Goal:** run ONE after-market walk-forward tuning cycle — read+drain → fit → CPCV replay → score → gate → publish → audit — over the reactive CFD layer's decision-trace + outcome history, autonomously selecting and (when the overfitting-corrected gate passes) promoting the best candidate config into the shared P2 parameter-version registry the `execution-daemon` later adopts at hot-swap, while emitting a falsifiable, correlation-keyed tuner-action audit on every cycle (promote or decline).

**Architecture:** the after-market **slow clock** (exploration §14) — a main-session markdown orchestrator (P1) driving pure leaf modules in `src/skills/walkforward_tune/` (`read`, `fit`, `cpcv`, `metric`, `gate`, `publish`, `audit`) plus the audit HG validator in `src/eval/gates/`. The loop **consumes** the `reactive-replay-harness` (`src.reactive.replay.replay_candidate`) for the point-in-time CPCV re-simulation — it owns the CPCV partitioning + the metric + the gate, NOT the backtest engine. It is the **only** component that *fits* new reactive/survival parameters and code; the in-session fast clock stays apply-only (§14.4) and never waits on this batch. Out of boundary: deploy / atomic hot-swap (`execution-daemon`); in-session selection / halt (`in-session-monitor`); the trace/ledger schema (`decision-trace-telemetry`, read-only here); the replay engine itself (`reactive-replay-harness`, consumed).

## Dispatch contract (Req 1.1 / 9.2)

This command is **dispatched at a walk-forward boundary by a scheduler or a drained event, NOT interactively** (Req 9.2). It runs **only after market close** and **never during market hours** (Req 1.1) — it fits, tunes, and modifies parameters/code exclusively after-market. The cadence host (cron / `/schedule` / event-queue trigger) is harness-level infrastructure **out of this spec's boundary**; this spec defines the per-cycle behavior. One invocation = one cycle (Req 1.2). The hours-long batch runs **asynchronously**, such that the in-session trading loop never blocks on or waits for it (Req 1.3).

## Standing invariants (hold for the whole cycle)

- **After-market only (Req 1.1):** never fit/tune/modify any parameter or code during market hours; this loop runs only after the close.
- **Async, never blocks the hot path (Req 1.3):** the in-session trading loop never waits on this batch; fitting never enters the latency-bound hot path (§14.4).
- **Never deploys/applies/selects at runtime (Req 3.5 / 7.2):** this loop PUBLISHES a validated version into the P2 registry; deploy/hot-swap is the `execution-daemon`'s and in-session selection is the `in-session-monitor`'s. It never applies or selects a fitted version itself.
- **Autonomous, no human sign-off (Req 5.6):** promotion is decided by the deterministic gate without per-promotion approval. The gate's rigor + the kill switch are the *entire* defense between an LLM-authored change and the levered book.
- **Always under the operator kill switch + survival gate (Req 5.6):** the operator kill switch (`survival-gate` / §11.5) and the survival gate override this loop's autonomy at ALL times — autonomy removes per-promotion approval, NOT the emergency halt. If the kill switch is engaged, decline-and-audit (`kill_switch_engaged`) and END without fitting or publishing.
- **Paper-only (Req 5.7):** promote ONLY into the paper/challenger track; never enable or assume live real-money routing (the `publish` leaf's `approved_by` defaults to the paper track).
- **Conservative-by-default / decisions only ever tighten (P7):** every failure path retains the incumbent and records the binding reason in the audit; the gate fails toward not-promoting; the §13 lexicographic ordering (Survive ⊳ Preserve ⊳ Edge ⊳ Return) is never traded.
- **Reader-only consumption (Req 10.1–10.3):** reads the model trace + drains the event queue (sets `drained_at`, never owns the emit side); consumes the `ParamSnapshot`/`SurvivalParameters` it tunes and the `reactive-replay-harness` contract — it never reimplements the softmax/threshold model or the survival logic, and **never reads `counterfactual_ledger`** for the gate (reactive P&L comes from the harness's `OutcomeRecord`s).
- **Cost (Req 9.3):** runs under the existing per-`(run_id, agent)` cost ceiling (`scripts/post_agent_validate.sh` → `orchestrator_step.py`, $60 default, 3-strike). There is **no aggregate cost cap** across the batch (T4 / §14.11 #4, accepted eyes-open); `|trial set| × |CPCV partitions| × replay` is the runaway-risk locus — bound it via the trial-set size + partition count (this loop's knobs).

## Allowed dependencies (the import firewall — the reviewer keys on this)

This orchestration references ONLY:
- the 7 leaves `src/skills/walkforward_tune/{read,fit,cpcv,metric,gate,publish,audit}.py`;
- the consumed `reactive-replay-harness` contract — `src.reactive.replay.replay_candidate` + the imported `OutcomeRecord` / `ReplayResult` / `ReplayWindow` / `Candidate` (never re-declared);
- the reused compute `src/calibration/metrics.py` (Brier/reliability, *inside* the `metric` leaf) + `src/calibration/scorer.py` (`Label`);
- the audit HG validator `src/eval/gates/tuner_action_audit_shape.py` (`artifact_type="tuner_action_audit_envelope"`, HG-41);
- the P2 machinery (`parameters` / `parameters_active` / `run_parameters_snapshot`, mig 034) and the audit table (`walkforward_tuner_audit`, mig 053).

**FORBIDDEN (never import / drive):** the `execution-daemon` or `in-session-monitor` modules; the reactive / survival / broker cores **directly** (the consumed harness drives them — this loop does not); `counterfactual_ledger` for the gate's P&L; any Python that dispatches subagents (P1); writes to the trace/ledger schemas; live / in-session fitting.

## Procedure

### 0. Run-level identity + parameter pin (P2/P3)

**Mint the cycle's `run_id`** (`uuidgen` or any UUID source; record as `RUN_ID`, P3). This single key threads everything: it names the audit envelope file (`memos/envelopes/walkforward-tune__<RUN_ID>.json`), the per-phase checkpoint artifacts (§ Checkpoint/resume), and the four correlation keys on the audit. Embed it in every leaf call that takes a `run_id` (`publish`, `audit`).

**Kill-switch pre-check (Req 5.6):** before any fit, resolve the operator kill switch / survival-gate halt state (`survival-gate` / §11.5). If engaged, write a decline audit (`kill_switch_engaged`, incumbent retained, P7) per §S7 and END — do not fit, replay, or publish.

**Pin `GateParams` by value (P2 — single REPEATABLE READ; NO `run_parameters_snapshot` row).** Resolve every gate knob from the `parameters_active` view, namespace **`walkforward`** (`dsr_threshold`, `psr_threshold`, `min_trl`, `pbo_threshold`, `min_btl`, `benchmark_sharpe`, `oos_margin`, `consecutive_required`, `hysteresis`) plus the CPCV partition knobs (`n_groups`, `k_test`, `embargo`) and the trial-set/partition cost bounds, in a **single REPEATABLE READ** transaction, and consume them **by value** for the rest of the cycle (P2 — never re-resolve mid-cycle; the block wins over any prose numeric). Build the typed `GateParams` (`src/skills/walkforward_tune/types.py::GateParams`) from the resolved rows; the resolved knobs are the cycle's `PARAMETERS_USED` block, carried in the cycle context/envelope only.

```sql
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT parameter_key, value, version_id
FROM parameters_active
WHERE parameter_namespace = 'walkforward';
COMMIT;
```

**Anti-contamination (load-bearing — mirrors `in-session-monitor` §2):** this loop **does NOT write a `run_parameters_snapshot` row**. That table is the `/research-company` slow-layer LLM-run lifecycle surface — `ticker` is `NOT NULL` (this after-market batch has no ticker) and the row carries a mutable `run_status` finalized by a terminal UPDATE; a ticker-less row with no terminal status is precisely the stuck-`in_progress` orphan `scripts/reconcile_orphan_snapshots.sh` flags to `failed_uncaught` (P6). P2's by-value propagation does NOT require a table row — pin `GateParams` into THIS cycle's context/envelope only (the `PARAMETERS_USED` block above), exactly as `in-session-monitor` pins `MonitorParams` without a snapshot row. The landed `publish` leaf likewise writes only `parameters` rows, never `run_parameters_snapshot`.

### 1 (S1). Read firewalled trace + drain the event queue (Req 2.1 / 10.1 / 10.2 / 10.5)

Determine the cycle's **in-sample boundary** `IS_BOUNDARY` (the walk-forward-window / timestamp attribution from the trace + outcome ledger, Req 2.3). Then:

- `read.read_firewalled(keys, is_boundary=IS_BOUNDARY, conn)` → `ReadSet` — the **temporal firewall** (part 1 of 2): the boundary becomes the reader's `until` edge, so the read **excludes `event_ts > IS_BOUNDARY`** and no out-of-sample observation can leak into the fit (Req 2.1). This reads ONLY the model trace + the event queue — it does **not** read `counterfactual_ledger` and does not fetch replay inputs (the consumed harness fetches its own historical data, Req 10.1).
- `read.drain_events(conn)` (also driven inside `read_firewalled`) → `list[Event]` — drain the after-market `execution_daemon_event_queue` (`SELECT … WHERE drained_at IS NULL` → process → `UPDATE … SET drained_at=NOW()`), surfacing anomaly events (safe_mode / kill_switch / lifecycle) onto the `ReadSet` for the fit's behavioral analysis (Req 10.5). The watermark makes the drain idempotent (a re-drain returns `[]`). This loop drains + sets `drained_at`; it never owns the emit side (Req 10.2).

Persist the `ReadSet` as the S1 checkpoint artifact under `RUN_ID`.

### 2 (S2). LLM fit — propose the trial set (Req 3.1 / 3.2 / 3.4 / 10.5)

This is the orchestrator's **LLM judgment step** (the §14.2 grid-search/optimizer role): from the firewall-bounded behavioral read + the drained anomaly events, **propose a non-trivial trial set (≥2 configs)** of candidate `ParamSnapshot` (reactive: edge/return) and/or `SurvivalParameters` (survival: tail/risk) configs, and articulate the **falsifiable promotion hypothesis** + its observable falsifiers (carried into the §S7 audit, P15). Incorporate the drained anomaly events into the behavioral analysis informing the fit (Req 10.5).

Then hand the proposals to the deterministic assembler:

- `fit.assemble_trial_set(proposed_configs, base=INCUMBENT, memory)` → `TrialSet` — validates each proposal against its pinned shape, applies **rolling** (edge/return) vs **anchored** (tail/risk) in-sample memory (Req 3.2), and produces one **hashed `Candidate`** (with a content-derived `param_version`) per config (Req 3.4). It RAISES on a degenerate (<2) or shape-invalid proposal — the trial set must be non-trivial so the gate's DSR/PBO deflation is non-degenerate (Req 5.2/5.3).
- **Code track (Req 3.3):** where the structural code track is exercised, the orchestrator produces a candidate code/structure version (a diff) IN ADDITION to (or instead of) a parameter version — the *diff* is the LLM's product here, gated by the full inner-ring suite at §S5 (it is NOT assembled by `fit`). The `publish` leaf raises on a code-only candidate (its deploy is the daemon's seam — see §S6); v0.1 exercises the param track as the publish path.

On a fit/LLM failure or a cost-ceiling hit (the per-`(run_id,agent)` $60 / 3-strike from `orchestrator_step.py`): no candidate is produced → decline-and-audit (`fit_failed`, incumbent retained) per §S7 and END. Persist the `TrialSet` as the S2 checkpoint artifact.

### 3 (S3). CPCV partition + call the consumed replay harness per config per partition (Req 2.2 / 2.3 / 4.1 / 4.2 / 4.6 / 10.3)

**Partition (firewall part 2 of 2):** `cpcv.make_partitions(history, n_groups, k_test, embargo)` → `list[Partition]` — combinatorial purged cross-validation: **purge label-overlapping observations + embargo after each test block** (the leakage-firewall realization, Req 2.2/2.3). The firewall invariant: **no OOS observation appears in the matching IS set**. Each `Partition` carries its OOS span mapped to a consumed harness `ReplayWindow` (the two specs share ONE window type — `Partition.oos_window`).

**Re-simulate via the consumed harness (Req 4.1/4.2 — owned by `reactive-replay-harness`):** for **each trial candidate AND the incumbent**, once **per partition**, call the consumed contract with the partition's OOS window:

```
result = replay_candidate(candidate, partition.oos_window)   # -> ReplayResult{records, fidelity}
```

The harness drives the landed reactive signal-model + survival-gate cores over point-in-time inputs, reconstructing each candidate's own divergent decision-and-account path (Req 4.2) — this loop NEVER reimplements those cores (Req 10.3). The harness knows nothing of CPCV; the orchestrator supplies each partition's window.

**Fidelity precondition (Req 4.6):** read `result.fidelity` from the **incumbent's** replay. `status == "fail"` (tolerance not met → engine distrust) ⇒ **no-promote this cycle**: decline-and-audit (`replay_failed`, incumbent retained) per §S7 and END. `status == "not_evaluable"` (sparse / cold-start baseline) is **distinct from fail** — record it but do not treat it as an engine defect. A `replay_candidate` call error or an `OutcomeRecord` contract mismatch likewise aborts that candidate → `replay_failed` (also a revalidation signal: the harness contract changed shape).

Persist the per-(config, partition) `ReplayResult.records` lists as the S3 checkpoint artifact.

### 4 (S4). Score the survival-net metric + calibration over the returned OutcomeRecords (Req 4.3 / 4.4)

For each (config, partition), thread the harness's returned `OutcomeRecord`s into the metric leaf:

```
sample = metric.score(result.records)   # -> OOSSample{survival_net_return, skew, kurtosis, n_obs}
```

`metric.score` computes the **survival-net risk-adjusted return** reflecting the §13 ordering — a survival breach / stop-out **dominates** an edge gain (Req 4.3) — and folds the model's derived-probability **calibration** (Brier/reliability via `src/calibration/metrics.py`) into the scalar as a behavioral input, not only hit-rate or P&L (Req 4.4). It is computed over the harness's `OutcomeRecord`s, **NOT** the `counterfactual_ledger`.

Assemble the `OOSMatrix`:

```
matrix = OOSMatrix(
    per_config={config_id: [OOSSample per partition, partition-ordered]},
    incumbent=[OOSSample per partition for the incumbent],
    trial_metadata=trial_set.trial_metadata,   # what the gate deflates effective_n against
)
```

Partition order MUST be consistent across configs and the incumbent (the gate pairs partitions positionally for PBO/CSCV and the OOS-margin comparison). Persist the `OOSMatrix` as the S4 checkpoint artifact.

### 5 (S5). Deterministic gate — select best + deflate (Req 4.5 / 5.1–5.5 / 6.2 / 6.3)

```
verdict = gate.evaluate_gate(matrix, GATE_PARAMS)   # -> GateVerdict
```

The gate is **pure + deterministic** (identical inputs ⇒ identical verdict); no I/O, no LLM. It runs, IN ORDER over the CPCV matrix:

1. **Select best** — pick the highest survival-net config from the trial set.
2. **PSR/MinTRL sufficiency** (skew/kurtosis-aware, vs a non-trivial benchmark Sharpe). If the OOS evidence is statistically insufficient (MinTRL not met) ⇒ `promote=false`, retain incumbent (Req 5.4) → §S7 reason `insufficient_oos`.
3. **DSR + PBO/CSCV** (overfitting-corrected over the trial set; **deflate by `effective_N`**; MinBTL caps the trial-set breadth to available history → reduce correlated sweeps to an effective trial count, Req 5.2/5.3). A **degenerate trial set (N=1) ⇒ no-promote**, never a spurious pass.
4. **Decision rule** — the selected candidate must beat the incumbent by the configured `oos_margin` across the partitions, sustained over `consecutive_required` cycles, with `hysteresis` anti-churn (Req 5.5).
5. **§13 lexicographic guard** — reject any Edge/Return gain bought at the cost of a worse Survive/Preserve score (Req 6.3); `lexicographic_ok` records it.

The gate **NEVER consults an in-sample Sharpe** (Req 4.5 / 5.5) — `GateVerdict` carries no IS-Sharpe field. Any insufficiency / degeneracy / malformed matrix ⇒ `promote=false` (fail toward not-promoting, P7). The gate figures are DERIVED (P15), surfaced on `GateVerdict{promote, selected_config, reasons, dsr, psr, min_trl_met, pbo, effective_n, lexicographic_ok}`.

**Track-weighted gate (Req 6.1/6.2 — conservatism, P7/P14):**
- **Param track (Req 6.2):** the out-of-sample gate above + the §13 lexicographic guard are the promotion gate; the audit HG validator's falsifiability check (§S7) realizes R6's evaluator obligation for the statistical audit.
- **Code track (Req 6.1):** a structural code/structure candidate requires the **full inner-ring test suite to pass** before promotion, IN ADDITION to the OOS gate + the §13 guard. Run it from the worktree root:

  ```bash
  pytest tests/                          # full inner ring; must be green
  ```

  A **red** inner ring ⇒ `promote=false` for the code candidate (the largest blast-radius change clears the strongest gate, Req 6.1). A param candidate in the same cycle may still promote on its own gates.

Persist the `GateVerdict` as the S5 checkpoint artifact.

### 6 (S6). Publish on promote + advance the IS boundary (Req 1.4 / 5.7 / 7.1 / 7.2 / 7.3)

ON `verdict.promote == True` (and, for a code candidate, the inner ring green):

```
result = publish(
    verdict, candidate=SELECTED_CANDIDATE,
    run_id=RUN_ID,
    advanced_window=ADVANCED_WINDOW_LABEL,   # the advanced walk_forward_window the daemon re-sources at hot-swap
    conn=conn,                               # conn=None ⇒ dry-run (no DB write)
)
```

`publish` writes the validated values into the `parameters` rows (reactive + survival namespaces) so `parameters_active` resolves to them (Req 7.1; `approved_by` defaults to the **paper/challenger track** — Req 5.7, paper-only does not enable live routing), and stamps the **advanced `walk_forward_window` label** so the `execution-daemon` re-sources it at its next hot-swap (Req 7.3) — folding newly-realized champion history into the next cycle's in-sample data (Req 1.4). It is **idempotent on `run_id`** (deterministic `version_id` + `ON CONFLICT DO NOTHING`), so a resume re-fire is a no-op.

`publish` **NEVER deploys, hot-swaps, or applies** the version (Req 7.2) — it only writes the P2 rows the daemon adopts later. It **raises on a code-only candidate** (a code candidate's git-landed-diff + `code_version` bump + clean-boundary load deploy is the `execution-daemon`'s seam, out of scope here — do not invent a code-deploy path).

ON DECLINE: skip publish entirely; the incumbent is retained (P7) — the boundary does not advance. On a publish failure: do not advance the boundary; audit `publish_failed`; the next cycle re-attempts (idempotent on `run_id`).

### 7 (S7). Emit the tuner-action audit — on promote AND decline (Req 8.1 / 8.2 / 8.3)

Emitted on **every** cycle (promote OR decline, Req 8.1). Build the `TunerActionAudit` (`src/skills/walkforward_tune/types.py::TunerActionAudit`):

- `audit_id` = `audit.mint_audit_id(run_id=RUN_ID)` (deterministic uuid5 → idempotent on resume).
- The **four correlation keys**: `run_id=RUN_ID`, `code_version`, `param_version` (the candidate's version), `walk_forward_window` (the advanced label — `None` until promoted) — so every row joins to `decision_process_trace` + the outcome ledger (Req 8.3).
- `promoted` = `verdict.promote`; `track` ∈ {`param`, `code`, `both`}.
- `gate_metrics` = `audit.gate_metrics_from_verdict(verdict)` — the DERIVED gate figures (dsr, psr, min_trl_met, pbo, effective_n, lexicographic_ok), a pure projection of the gate's output, NOT asserted probabilities (P15 / Req 8.2).
- `hypothesis` = the **falsifiable** `{statement, falsifiers: [...]}` from §S2 (the promotion rationale as a falsifiable hypothesis with observable falsifiers, P15 / Req 8.2). On a decline, the binding decline reason (`insufficient_oos` / `fit_failed` / `replay_failed` / `publish_failed` / `kill_switch_engaged`) is the rationale (drawn from `verdict.reasons` / the failing phase).

Then persist:

```
out = audit.write_audit(audit, conn=conn)   # conn=None ⇒ dry-run: envelope written, NO DB row
```

`write_audit` ALWAYS persists the envelope-on-disk at `memos/envelopes/walkforward-tune__<RUN_ID>.json` (P4 — unconditional, even dry-run), and appends the `walkforward_tuner_audit` (mig 053) row only with a live `conn` (append-only + idempotent on `run_id` via the deterministic `audit_id`).

**Validate the audit envelope (P10 manual seam — exactly as `research-company` §2.5.7 / `in-session-monitor` §4c).** This loop is a main-session orchestration with no `Agent()` to hook (T1/P10), so validate the emitted envelope manually:

```bash
scripts/validate_envelope.sh \
    --envelope memos/envelopes/walkforward-tune__<RUN_ID>.json \
    --artifact-type tuner_action_audit_envelope \
    --run-id <RUN_ID> \
    --agent-type walkforward-tune \
    --attempt-cost-usd 0.10
```

This routes the envelope to the HG-41 `tuner_action_audit_shape` validator, which enforces the envelope shape + the **P15 falsifiability / derived-metrics check** + the four correlation keys (rejects an envelope missing any of the 4 keys / the hypothesis / the falsifiers / the derived gate metrics). On **RETRY** (exit 10), the orchestrator's own LLM patches the envelope per the `--- BEGIN DELTA PROMPT ---` fence on stderr and re-validates (same 3-attempt cap; the main session is the "agent"). On **ESCALATE** (exit 11), halt the cycle and surface the audit trail — a structural defect, not a mechanical retry.

The audit owns the **why** of the promotion decision only — it does NOT write the model-trace / ledger schemas (Req 8.4, owned by `decision-trace-telemetry`).

## Checkpoint / resume (Req 9.1)

The hours-long batch survives a crash without losing the run (Req 9.1): **each phase persists its artifact under `RUN_ID`** (P4 — `ReadSet` @ S1, `TrialSet` @ S2, per-(config,partition) `OutcomeRecord` lists @ S3, `OOSMatrix` @ S4, `GateVerdict` @ S5, the published rows @ S6, the audit envelope @ S7). A crash mid-cycle **resumes by re-firing the SAME `RUN_ID`**; a phase whose artifact already exists on disk is **skipped** (loaded, not recomputed). The deterministic `version_id` (publish) and `audit_id` (audit) keys make the resumed publish + audit writes idempotent (`ON CONFLICT DO NOTHING`), so a resume after a partial S6/S7 write is a safe no-op.

## Error handling (conservative-by-default — every failure retains the incumbent, P7)

| Failure | Disposition | Audit reason |
|---------|-------------|--------------|
| Kill switch engaged (§0) | no fit/replay/publish; END | `kill_switch_engaged` |
| Fit/LLM failure or cost-ceiling hit (S2) | no candidate; retain incumbent | `fit_failed` |
| Insufficient OOS data — MinTRL not met (S5) | `promote=false`; retain incumbent | `insufficient_oos` |
| `replay_candidate` error / `OutcomeRecord` mismatch / incumbent fidelity `fail` (S3) | abort candidate; retain incumbent (a revalidation signal) | `replay_failed` |
| Gate exception / malformed matrix (S5) | `promote=false` (fail toward not-promoting) | (gate `reasons`) |
| Publish failure (S6) | do not advance boundary; next cycle re-attempts (idempotent) | `publish_failed` |
| Code-track inner-ring red (S5) | `promote=false` for the code candidate; a param candidate may still promote | (inner-ring red) |
| Crash mid-cycle | resume re-fires same `RUN_ID`; persisted phases skipped | (none — resume) |

Every cycle emits a `walkforward_tuner_audit` row + envelope; the HG-41 validator gates the envelope before release; promote/decline + the binding reason are the primary observability signal. Drained anomaly events are reflected in the audit's behavioral-analysis rationale.

## Requirements coverage

| Req | Where covered |
|-----|---------------|
| 1.1 after-market only, no in-hours fit | Dispatch contract + §0 invariants |
| 1.2 one cycle: fit → CPCV replay → decision | Procedure S1–S7 |
| 1.3 async, never blocks the hot path | §0 invariants |
| 3.3 code-track candidate version | §S2 (code track) + §S5 (inner-ring gate) |
| 5.6 autonomous, always under the kill switch | §0 invariants + §0 kill-switch pre-check |
| 6.1 code track full inner-ring before promote | §S5 (track-weighted gate, `pytest tests/`) |
| 9.1 checkpoint / resume mid-fit | § Checkpoint/resume |
| 9.2 scheduled / event dispatch, not interactive | Dispatch contract + frontmatter |
| 9.3 per-`(run_id, agent)` ceiling, no aggregate cap | §0 invariants (cost) |

(Reqs 2.x / 4.x / 5.1–5.5 / 5.7 / 7.x / 8.x / 10.x are realized by the leaves the loop drives — `read` / `cpcv` / `metric` / `gate` / `publish` / `audit` + the HG validator — and the consumed `reactive-replay-harness`, wired in §S1–§S7.)

## When to use
- Fired at a walk-forward boundary by the scheduler / a drained event, after the (paper) market close.

## When NOT to use
- During market hours, or as an in-session mechanism (the apply-only fast clock + the supervisory `in-session-monitor` own that). To deploy/hot-swap a version (the `execution-daemon`'s seam). To fit live / in-session (fitting is after-market only, §14.4). As a survival reflex (the deterministic kill switch / safe mode is — §11.5/§13).

## Architecture references
- `.kiro/specs/walkforward-tuning-loop/design.md` (§Overview, §Boundary Commitments, §Architecture + System-Flows mermaid, §Components and Interfaces, §Error Handling).
- `.kiro/specs/walkforward-tuning-loop/requirements.md` (R1–R10).
- Consumed contract: `src/reactive/replay/` (`reactive-replay-harness`) — `replay_candidate` + `OutcomeRecord` / `ReplayResult` / `ReplayWindow` / `Candidate`.
- Convention precedents: `.claude/commands/research-company.md` (run_id P3 §1.5 Step 1, PARAMETERS_USED P2 §1.5, P10 validate seam §2.5.7); `.claude/commands/in-session-monitor.md` (the reactive-layer markdown-orchestrator-over-pure-leaves template + the P10 validate seam §4c).
- Exploration §14 (the after-market slow clock); §13 (the lexicographic Survive ⊳ Preserve ⊳ Edge ⊳ Return chain this loop never trades); §11.5 (the operator kill switch).
