---
description: One scheduled in-session supervisory tick over the reactive CFD execution layer (§15). Reads decision-trace telemetry, judges whether the model is inside its calibrated behavior envelope via derived calibration diagnostics (P15), and — when it has drifted while still inside hard-survival limits — commands an EXISTING deterministic mechanism (kill switch / safe mode / select-validated-config), then emits a falsifiable intervention audit. Phase-1 is ADVISORY (no live command channel yet; the audit records the would-be intent, applied=false). Never fits; never the survival reflex; paper-only v0.1.
argument-hint: (none — dispatched on a cadence by a scheduler, not interactively)
---

# /in-session-monitor

**Goal:** run ONE cadence tick of the in-session supervisory loop — sense → judge → act → audit — over the reactive CFD execution layer's decision-trace telemetry, and (when the model has drifted out of its calibrated envelope while still inside hard-survival limits) intervene by commanding an **existing** mechanism, conservative-only, then emit a falsifiable, key-correlated audit.

**Architecture:** a scheduled **sense → judge → act → audit supervisory loop** (exploration §15), a main-session markdown orchestrator (P1) driving pure leaf modules — `src/reactive/monitor/{diagnostic,judge,intervene,audit,command_writer}.py` — that import the landed telemetry reader + calibration metrics and never recompute them. The monitor is a **second-line supervisor**: the deterministic survival reflex (kill switch / safe mode in `execution-daemon` / `survival-gate`) fires first and independently; this loop only ever makes the system **equal-or-more conservative**, and it **never fits** new values (fitting is after-market, `walkforward-tuning-loop`, §14.4).

## Phasing (Option C — Phase 1 buildable now; Phase 2 gated)

- **Phase 1 (this spec, ADVISORY):** sense + judge + decide-intent + audit, against the landed telemetry + calibration. The intervention is **advisory** — `command_writer.submit_command()` is a no-op that records the would-be intent; the audit always carries `applied=false`. No live mutation of the levered book.
- **Phase 2 (DEFERRED — blocked on the `execution-daemon` intake poll/apply-loop):** the live command write + confirm + single-flight into the daemon-owned `execution_daemon_command_intake` table. The intake-table **contract is landed** (mig 052: `execution_daemon_command_intake` with `issued_by IN ('monitor','operator')` + set-once `applied_at`/`status`/`reject_reason`), **but the daemon has not yet implemented the intake poll/apply-loop** (no `src/reactive/daemon/loop.py` — only scaffolding), so a command written today would never be consumed. **Do NOT perform any live daemon-intake write in this orchestration.** §5 below states the deferred contract only.

## Cadence dispatch contract (Req 1.1)

This command is **dispatched on a regular in-session cadence by a scheduler, not interactively** (Req 1.1). The cadence host (the cron/scheduler) is harness-level infrastructure **out of this spec's boundary** — this spec defines the per-tick behavior, not the scheduler. The cadence period is `monitor.cadence_seconds` (pinned in Step 2). One invocation = one tick.

## Procedure

### 0. Run-level identity + invariants

**Mint the monitor's own `run_id`** (`uuidgen` or any UUID source; record as `RUN_ID`, P3). This orchestration `RUN_ID` **only NAMES the audit envelope file** (`memos/envelopes/in-session-monitor__<RUN_ID>.json`). It is **distinct from the four correlation keys** carried inside the audit, which are the daemon-epoch keys of the analyzed `(code_version, param_version)` read off the trace (Step 3; Rev 2.1 — do not conflate).

Standing invariants for the whole tick:
- **Not in the survival hot path / never order-fire (Req 1.3):** the deterministic gate decides and fires without ever waiting on this monitor; the monitor only reads telemetry + (Phase 2) writes a gated command — it never participates in an order-fire decision.
- **Never fit in-session (Req 1.4):** no tuning, no fitting, no computing of new parameter/code values. The only "new value" the monitor may select is an **already-validated** config version (Step 3, `intervene`).
- **Reflex-first / second-line (Req 5.3):** the deterministic survival reflex remains authoritative and fires first and independently; this loop is supervisory only.
- **Autonomous (Req 8.1):** runs without per-intervention human sign-off.
- **Always under the kill switch (Req 8.2):** the operator kill switch + survival gate override this monitor at all times (autonomy removes per-intervention approval, NOT the emergency halt).
- **Cost (Req 8.3):** the tick runs under the existing per-`(run_id, agent)` cost ceiling (`orchestrator_step.py`); no aggregate-cadence cost cap is assumed in v0.1 (T4, accepted eyes-open).
- **Paper-only (Req 8.4):** acts only on the paper/challenger track; never enables or assumes live real-money routing.

### 1. Pre-flight

Verify the consumed surfaces are reachable; halt-and-surface to the operator if any is missing (do not proceed on degraded data):
- `mcp__postgres` for `parameters_active` (mig 004) + the `decision_process_trace` read surface (mig 048).
- The landed monitor leaves import cleanly: `src/reactive/monitor/{diagnostic,judge,intervene,audit,command_writer}.py`, `src/reactive/telemetry/reader.py::query_trace`, `src/calibration/metrics.py`.
- `scripts/validate_envelope.sh` present (the P10 validate seam, Step 4).

### 2. Pin `MonitorParams` by value (P2/P3 — single REPEATABLE READ; NO snapshot row)

Resolve every drift-rule knob from the `parameters_active` view, namespace **`monitor`** (seeded by migration 054: `min_observations`, `window_W`, `margin_M`, `severity_cutoffs`, `in_sample_baseline`, `cadence_seconds`), in a **single REPEATABLE READ** transaction, and consume them **by value** for the rest of the tick (P2 — never re-resolve mid-tick; the block wins over any prose numeric).

**Anti-contamination (Rev 2.1 — load-bearing):** the monitor **does NOT write a `run_parameters_snapshot` row**. It pins `monitor.*` into its own tick context/envelope only, so it never touches the `/research-company` LLM-run lifecycle (`run_status`) or the P6 orphan reconciler (mirrors the daemon's `execution_daemon_epoch` decision). Build the typed `MonitorParams` (`src/reactive/monitor/types.py`) from the resolved rows.

### 3. The tick: sense → judge → decide-intent

**3a. Sense — `diagnostic.compute_drift(filters, params, label_source, conn)` →`DriftDiagnostic`.**
- `filters` select the **active `(code_version, param_version)`** cohort (read the current version off the most-recent trace rows via `query_trace`); a window that would cross a hot-swap is restricted to the current version (calibration across a hot-swap is meaningless).
- **`label_source` is the injected `RealizedLabelSource` seam.** The reactive per-decision realized **directional** label ("was `P(caller direction)` the correct side?") is **owned by `walkforward-tuning-loop`** and **has not landed** (it is NOT on `decision_process_trace`; `counterfactual_ledger` is the wrong-grain slow-layer eval ledger). **In v0.1 inject a source that yields NO reactive labels**, so the diagnostic returns **INSUFFICIENT** — the monitor is **correctly blind on calibration drift until that upstream source lands** (this is expected, not a defect; a Revalidation Trigger fires when the real source lands — wire it into the seam then).
- Below `params.min_observations` (including the post-hot-swap refill window) the diagnostic also returns `sufficient=False` → INSUFFICIENT.

**3b. Judge — `judge.classify(diag, params)` → `EnvelopeVerdict {state, severity, binding_metric}`.**
- `IN_ENVELOPE` (no drift) or `INSUFFICIENT` (the dominant v0.1 path, per 3a) → **no flagged anomaly**: skip to a no-op tick (no persisted audit — the audit is emitted only on a flagged anomaly, R7.1; this is the "leave no artifact" advisory tick) and END.
- `DRIFTED` is produced **only when the window is inside survival limits** (`diag.in_survival_band` is False) — the survival band belongs to the deterministic reflex, not the monitor (Req 5.3). A `DRIFTED` verdict is a **flagged anomaly** → continue to 3c + the audit (Step 4).
- All verdict figures are **derived** from the diagnostic; never assert a probability (P15).

**3c. Decide intent — `intervene.decide(verdict, active, menu, params)` → `InterventionIntent`** (only on `DRIFTED`).
- Bounded to the three daemon command types + NONE: `mild` DRIFTED → `SELECT_SAFER_CONFIG` (if a safer **validated** version exists in the menu) else `TIGHTEN_SAFE_MODE`; `severe` DRIFTED → `HALT_NEW_ENTRIES`. A wedged component → `HALT_NEW_ENTRIES` + an `operator_action_required` flag (the daemon exposes no restart seam — the restart is operator-executed).
- **Conservative-only (Req 5.1, defense-in-depth with the daemon's toward-safer guard):** any intent not equal-or-more-conservative than the `active` state is rejected to `NONE`. `SELECT_SAFER_CONFIG` reads **only** the validated-version menu (the P2 `parameters` machinery) and only toward-safer; it **never fits** (Req 1.4).

### 4. Act (Phase-1 advisory) + audit + validate

**4a. Advisory command (Phase 1).** Call `command_writer.submit_command(cmd, conn=None)` — in Phase 1 this is an **advisory no-op**: it mints the stable idempotency `command_id` and returns an ADVISORY result, **writing nothing live** (the daemon's intake poll/apply-loop is not yet implemented, so a live write would never be consumed — see Phasing). The audit records the **would-be** intent.

**4b. Emit the audit (`audit.emit_audit(audit, conn, run_id=RUN_ID)`).** Build the `InterventionAudit`:
- `keys` = the four daemon-epoch correlation keys of the single analyzed `(code_version, param_version)`, read off the analyzed trace (Req 7.3) — **distinct** from `RUN_ID` (which only names the file).
- `trigger_diagnostic` = the derived figure (metric / observed / threshold / window_n), never an asserted probability (P15 / Req 7.2).
- `verdict`, `intervention_intent`, optional `operator_action_required`.
- `rationale` = a **falsifiable** `{hypothesis, falsifiers: [...]}` (P15 / Req 7.2).
- **`applied=false` and `command_ref=null`** — the unmistakable Phase-1 advisory "NO ACTION TAKEN" signal (Req 7.1).
- Persist the envelope to `memos/envelopes/in-session-monitor__<RUN_ID>.json` (supply `conn` — note: per `audit.py`, `conn` is the persist switch; the envelope is a local file, not a DB row). The audit owns the **why** only — no model-trace write (Req 7.4).

**4c. Validate the audit envelope (P10 manual seam — exactly as `research-company` §2.5.7).** The monitor is a main-session orchestration with no `Agent()` to hook, so validate the emitted envelope manually:

```bash
scripts/validate_envelope.sh \
    --envelope memos/envelopes/in-session-monitor__<RUN_ID>.json \
    --artifact-type intervention_audit \
    --run-id <RUN_ID> \
    --agent-type in-session-monitor \
    --attempt-cost-usd 0.10
```

This routes the envelope to the HG-39 `intervention_audit_shape` validator (presence-only, P13 — the four correlation keys are read **nested under `keys`**, matching `emit_audit`). On **RETRY** (exit 10), the orchestrator's own LLM patches the envelope per the delta-prompt on stderr and re-validates (same 3-attempt cap; the main session is the "agent"). On **ESCALATE** (exit 11), halt the tick and surface the audit trail — a structural defect, not a mechanical retry.

### 5. Phase 2 (DEFERRED — blocked on the `execution-daemon` intake poll/apply-loop)

When the daemon **implements its intake poll/apply-loop** against the landed `execution_daemon_command_intake` table (mig 052), Phase 2 flips `submit_command` from advisory to live: INSERT the `InterventionCommand` row (with `issued_by`) idempotently on `command_id`; achieve single-flight by **skip-if-outstanding** (skip a tick if an unapplied own-row exists); confirm via `applied_at`/`status`/`reject_reason`; on no-confirm or rejection **escalate to the always-available halt** and surface to the operator; never block a true exit or flatten; set `applied=true` + `command_ref` in the audit only after the intake confirms `status=applied`. **None of this runs in v0.1 — it is documented here as the deferred contract only.**

## Requirements coverage

| Req | Where covered |
|-----|---------------|
| 1.1 scheduled cadence, not interactive | "Cadence dispatch contract" + frontmatter |
| 1.3 not order-fire / not survival hot path | §0 invariants |
| 1.4 never fit in-session | §0 invariants + §3c (`intervene` never fits) |
| 5.3 reflex-first / second-line | §0 invariants + §3b (survival-band gate) |
| 8.1 autonomous, no per-intervention sign-off | §0 invariants |
| 8.2 always under the kill switch | §0 invariants |
| 8.3 per-`(run_id, agent)` cost ceiling | §0 invariants |
| 8.4 paper-only | §0 invariants + Phasing note |

(Reqs 2.x / 3.x / 7.x are owned by the leaves the loop drives — `diagnostic` / `judge` / `intervene` / `audit` — and exercised in §3–§4; Reqs 4.x / 6.x / 9.2–9.4 are Phase-2, §5.)

## When to use
- Fired by the scheduler on each in-session cadence tick while the (paper) market session is open.

## When NOT to use
- As a survival mechanism (the deterministic reflex is — §0). As a fitter/tuner (after-market `walkforward-tuning-loop`). To issue a live command in v0.1 (Phase 2 is blocked on the daemon implementing its intake poll/apply-loop against the landed mig-052 table).

## Architecture references
- `.kiro/specs/in-session-monitor/design.md` (§Orchestration, §System Flows, §Leaf contracts, §Baseline-ownership — corrected 2026-05-30 for the `RealizedLabelSource` seam).
- `.kiro/specs/in-session-monitor/requirements.md` (R1–R9).
- P10 validate-seam precedent: `.claude/commands/research-company.md` §2.5.7.
- Exploration §15 (the scheduled supervisory loop); §13 (the lexicographic Survive ⊳ Preserve ⊳ Edge ⊳ Return chain this loop never violates).
