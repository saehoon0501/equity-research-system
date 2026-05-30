# Gap Analysis — in-session-monitor

> Generated 2026-05-30 (`/kiro-validate-gap`). Brownfield analysis of the gap between the 9 EARS requirements and the existing codebase. Information-over-decisions: options + effort/risk + research items for design, not final choices. Findings verified on disk (paths spot-checked, not just subagent-reported).

## 1. Current State Investigation

The monitor is an **LLM orchestration** (markdown slash-command + Python leaf helpers, per P1), and a **consumer/commander** of other specs. It splits cleanly into a **read+judge+audit half** (buildable today against landed code) and an **intervene half** (blocked on unbuilt dependencies). Two architectural layers exist in the repo; this matters for integration (see ⚠️ below):

- **Slow research layer** — `/research-company`, `.claude/agents/*`, the `memos/envelopes/*` envelopes (quant/strategic/catalyst/pm), the `post_agent_validate.sh` PostToolUse hook. Per-call, operator-triggered.
- **Fast reactive layer** (being built, §11–§16) — the `execution-daemon` (persistent process, **not built**), the `decision_process_trace` telemetry (**landed**), `survival-gate` + command seams (**spec-only**). This monitor watches *this* layer.

### Landed assets the monitor REUSES or CONSUMES (verified on disk)

| Asset | Path | Use | Reusability |
|---|---|---|---|
| **Telemetry reader** | `src/reactive/telemetry/reader.py::query_trace(filters, conn)` | R1.2/R9.1 — read recent trace; filters: `run_id, code_version, param_version, walk_forward_window, kind, since, until`; returns `list[dict]` ordered by `event_ts` | **CONSUME (live)** |
| **Correlation keys + row types** | `src/reactive/telemetry/schema.py::CorrelationKeys` / `DecisionTraceRow` / `FillOutcomeRow` | R7.3 — the 4 keys (`run_id, code_version, param_version, walk_forward_window`); decision-row `trace` JSONB carries softmax `probability`, `signal_values`, `threshold`, `gate_link`, `declined`; fill-row carries `slippage` | **CONSUME (live)** |
| **Calibration metrics** | `src/calibration/metrics.py` — `brier_score`, `reliability_diagram`, `expected_calibration_error`, `log_loss` (+ block-bootstrap CIs) | R2.1 — the derived behavioral diagnostic (the §14.7 named diagnostic). **Directly importable** | **REUSE (direct)** |
| **4-bin vocabulary** | `src/calibration/scorer.py::Label` (BUY/HOLD/TRIM/SELL), `score()` | P9 vocabulary alignment | **REUSE (direct)** |
| **HG-validator framework** | `src/eval/gates/` — `_hybrid_gate.py`, `_registry.py`, `_outcome.py`, `envelope_shape.py` (+ ~12 per-agent shape validators) | R7 — template for a NEW `intervention_audit_shape.py` (deterministic spine; advisory judge may downgrade, never upgrade) | **TEMPLATE** |
| **Orchestration + run_id threading** | `.claude/commands/research-company.md` §1.5 | R1 — run_id mint, `PARAMETERS_USED` block, REPEATABLE-READ param snapshot + INV gate (P2/P3) | **TEMPLATE** |
| **Envelope persistence** | `memos/envelopes/<agent>__<run_id>.json` + `.context.json` sidecar + `.degraded` sentinel | R7 — the audit-record-as-envelope option (avoids a migration) | **REUSE (pattern)** |
| **Leaf DB-write convention** | `src/shared/regime_sidecar/persistence.py` (`_dsn()` + `.transaction()` + `conn=None` dry-run); `src/supervisor/emitter.py` (+ HMAC) | R7 — if the audit is a DB table | **REUSE (direct)** |
| **Cost ceiling** | `src/shared/agent_harness/orchestrator_step.py` (per-`(run_id, agent)` $60) | R8.3 — the only cost control (no aggregate cap, T4) | **REUSE (as-is)** |
| **Param machinery (P2)** | `parameters` + `parameters_active` view (mig 004); `run_parameters_snapshot` (mig 034) | R3.2/R9.3 — the substrate the "validated-version menu" rides on | **CONSUME** |

### ⚠️ Two integration pitfalls (subagent exploration surfaced both; both are layer conflations — DO NOT adopt)

1. **Do NOT trigger the monitor from `post_agent_validate.sh`.** That hook fires after `/research-company` `Agent()` dispatches (slow research layer). The monitor's trigger is the **fast reactive layer's in-session cadence**, independent of the research pipeline. The hook's *patterns* (envelope, HG-gate, run_id) are reusable; its *trigger point* is the wrong layer.
2. **Do NOT write the monitor's audit into `decision_process_trace`.** P11 + R7.4 require the audit to be the monitor's **own surface** (the *why*), separate from the model trace (the *what*). The daemon already emits the command *what* as a `command`/`safe_mode`/`kill_switch` event; the monitor owns only the *why*, joined via the 4 keys.

## 2. Requirement-to-Asset Map (gaps tagged)

| Req | Needs | Asset / Gap |
|---|---|---|
| **R1** scheduled cadence + read | orchestration + scheduler + reader | reader **LIVE**; orchestration **TEMPLATE**; **scheduler trigger = MISSING** (net-new; no cron/APScheduler/daemon-scheduler in repo — harness `/schedule`,`/loop`,`CronCreate` are the likely host, a design choice) |
| **R2** derived drift detection | calibration metrics + envelope/threshold definition | metrics **REUSE (direct)**; **"calibrated envelope" + drift threshold = CONSTRAINT/Unknown** (the core behavioral-model design — what Brier/reliability/ECE delta over what window = actionable) |
| **R3** intervention authority (op + select-config) | the daemon command seams | **SPEC-ONLY** (execution-daemon `commands.py` designed, not built); the **operational restart/clear-state** action is *not* among the daemon's 3 named seams → **Unknown** |
| **R4** commands-through-existing-mechanisms | kill-switch / safe-mode / versioned-config-select | mechanisms **SPEC-ONLY** (survival-gate migs 049/050 + daemon `commands.py`, none built) |
| **R5** conservative-only / reflex-first | `survival_gate_state` op-state + reflex | **SPEC-ONLY** (mig 049 not created; reflex lives in the unbuilt daemon loop) |
| **R6** command delivery + fail-safe | inbound command transport | **🔴 MISSING — net-new, no precedent.** The single hardest gap (see §3) |
| **R7** intervention audit | HG-validator + calibration + keys + audit store | validator **TEMPLATE**; calibration/keys **REUSE/CONSUME**; **audit store = net-new** (envelope on disk OR mig **≥054** — 048 on disk, 049–053 claimed by survival-gate/daemon/walkforward) |
| **R8** dispatch / autonomy / cost | cost ceiling + autonomy policy | cost ceiling **REUSE (as-is)**; autonomy = policy; paper-only = **Constraint** |
| **R9** consumption boundary | reader + seams + registry contracts | reader **LIVE**; seams **SPEC-ONLY**; **validated-version "menu" semantics = Unknown** (walkforward reuses `run_parameters_snapshot` — no bespoke registry; "which version is validated-and-selectable" is deferred to walkforward design) |

**Dependency-order constraint (load-bearing):** the monitor is **last** in the build order and its *intervene* half cannot be end-to-end built or tested until `execution-daemon` (the command target + reflex) and the `survival-gate` seams land, and the `select-validated-config` target depends on `walkforward-tuning-loop`'s registry semantics. Only the **read+judge+audit** half has a complete landed substrate today (telemetry reader + calibration).

## 3. The critical gap — command transport (R6/R3/R4)

**Status: ABSENT, no repo precedent.** Everything today is per-call MCP servers (request/response) or slash commands. There is no persistent process, no IPC, no control/command table, and no socket. The daemon's `commands.py` seams are **in-process** (called from inside its single-threaded loop); the monitor is an **out-of-process markdown orchestration** and the daemon is explicitly **not an MCP server** (§14.10). So there is no path for the monitor to invoke those seams.

The natural design (to validate, not decided): a **DB control row the daemon reads fresh each loop tick** — mirroring exactly how the daemon already reads `survival_gate_state` fresh every `admit`/`assess` (survival-gate's op-state freshness guarantee). The monitor writes an intent row; the daemon's reflex-first loop observes it on the next tick and applies it through its own gated seams. This keeps the daemon the sole mutator (R4), preserves reflex-first (R5.3), and reuses the append-only + state-guard table patterns already in the repo. **This is almost certainly an `execution-daemon` design follow-up** (the inbound table is the daemon's to own, like the outbound mig-051 queue) — coordinate cross-spec.

## 4. Implementation Approach Options

### Option A — Reuse-maximal, monitoring-only subset (thin orchestration over landed leaf libs)
Build `.claude/commands/in-session-monitor.md` + `src/skills/in-session-monitor/` (calibration-diagnostic wrapper over `src/calibration/metrics.py` + a `query_trace` read) + an audit **envelope** + a new `src/eval/gates/intervention_audit_shape.py`. Intervention is **advisory/surfaced-to-operator only** (no command transport). 
- ✅ Buildable now against 100% landed code; inner-ring testable in isolation (P14); no migration; no daemon dependency.
- ❌ Delivers only the read+judge+audit half — R3/R4/R5/R6 (actual intervention) are not realized.
- **Effort: M · Risk: Medium** (the drift-threshold model is the only hard part).

### Option B — Full build incl. net-new command transport
A + co-design the inbound command channel (control table) + wire the daemon to read it + the conservative-only enforcement + the audit store (mig ≥054).
- ✅ Realizes all 9 requirements end-to-end.
- ❌ **Blocked**: requires `execution-daemon` (unbuilt) + `survival-gate` seams (unbuilt) + a cross-spec transport co-design; safety-critical (commands into a live levered book) with no precedent.
- **Effort: L–XL · Risk: High** (net-new IPC, cross-spec, unbuilt dependencies).

### Option C — Phased / hybrid **(RECOMMENDED)**
**Phase 1 = Option A** now: read+judge+audit against landed telemetry+calibration; intervention = advisory record (envelope + HG validator); inner-ring tested standalone. Honors the roadmap build order (daemon precedes monitor) and P14 (inner ring before outer).
**Phase 2** when `execution-daemon` + `survival-gate` seams land: add the command-transport control table (co-designed with the daemon as its inbound counterpart to mig-051), flip intervention from advisory → commanding, add conservative-only enforcement + the audit-store migration if a DB table is chosen.
- ✅ Unblocks immediate value; isolates the high-risk transport into Phase 2 where its dependency exists; each phase independently testable.
- ❌ Two-phase coordination; Phase-1 "advisory-only" must be clearly labeled so it isn't mistaken for a live safety control.
- **Effort: M (Phase 1) + L (Phase 2) · Risk: Medium → High**.

## 5. Recommendations for Design Phase

- **Adopt Option C.** Design Phase 1 fully (it's unblocked); design Phase 2's transport as a **joint seam with `execution-daemon`** (likely an execution-daemon follow-up adding an inbound command/control table read each tick — symmetric to mig-051's outbound queue).
- **Audit store:** lean **envelope-on-disk** for v0.1 (reuses the agent-envelope + `src/eval/gates` pattern, no migration, and the daemon already persists the command *what*). Promote to a DB table (mig **≥054**) only if cross-session query of the *why* is needed — coordinate the number with `walkforward-tuning-loop` (claimed "053+").
- **Reuse, don't reimplement:** `src/calibration/metrics.py` for the diagnostic; `src/reactive/telemetry/reader.py` for the read; `src/eval/gates/_registry.py` + `envelope_shape.py` for the validator; the `_dsn()`/`.transaction()`/`conn=None` convention for any write.

### Research Needed (carry to design)
1. **Command transport mechanism** — DB control table (daemon polls each tick, mirroring `survival_gate_state` freshness) vs. socket/file. Cross-spec with `execution-daemon`. *(highest priority; the R6 blocker)*
2. **"Calibrated envelope" + drift threshold** — which metric (Brier delta / reliability divergence / ECE), over what window, at what value triggers which intervention class. The core behavioral model (P15-clean). *(blocks R2)*
3. **Validated-version "menu" semantics** — how the monitor enumerates selectable validated versions in `run_parameters_snapshot` (a `run_status`/tag convention?). Deferred to `walkforward-tuning-loop` design; revalidate when it lands. *(blocks R3.2/R9.3)*
4. **Scheduler/cadence host** — harness `/schedule` vs `/loop` vs `CronCreate` vs external cron; and the cadence value (T4: no aggregate cost cap → conservative). Arguably out of the code boundary but must be named. *(R1.1)*
5. **`select-validated-config` direction-of-change guard** — daemon-enforced toward-safer vs. carried as the monitor's P7 obligation alone. *(R3.2/R5.1)*
6. **Operational restart/clear-state seam** — not among the daemon's 3 named seams; decide whether it's a 4th seam or out of scope for v0.1. *(R3.1)*

---

## Design Synthesis (2026-05-30, `/kiro-spec-design`)

Light discovery (Extension / complex integration); no external deps to verify — all reuse is in-repo. Verified the integration surface against the landed code + the approved `execution-daemon` design.

### Generalization
The 9 requirements are one capability — a **scheduled sense→judge→act→audit supervisory loop** with a pluggable intervention sink. Phase 1 sink = advisory/audit; Phase 2 sink = the daemon command channel. The interface (`InterventionIntent` + `command_writer.submit_command`) is generalized so both phases share `types`/`judge`/`audit`/`intervene`; only the transport differs. (Pre-empts the review-gate split check — phasing is rollout, not two seams.)

### Build vs. Adopt
- **Adopt**: `src/calibration/metrics.py` (Brier/reliability/ECE — the §14.7 diagnostic); `src/reactive/telemetry/reader.py::query_trace` + `schema.py::CorrelationKeys`; `src/eval/gates` HG framework (`_registry.py` append); the `_dsn()`/`.transaction()`/`conn=None` convention; the per-`(run_id,agent)` cost ceiling; `parameters_active`/`run_parameters_snapshot` for the version menu.
- **Build (minimal)**: the markdown cadence orchestration; the pure `diagnostic/judge/intervene/audit` leaves; the `intervention_audit_shape` HG validator; (Phase 2) the `command_writer`.
- **Do NOT build**: a generic IPC layer — the inbound channel is a single daemon-owned append-only table the daemon polls (mirrors its outbound `execution_daemon_event_queue`).

### Key decisions (load-bearing)
1. **Command channel is daemon-owned, not monitor-owned.** A monitor-owned table the daemon reads would invert dependency direction; the daemon is the single reader-applier and already owns symmetric queues. This design specifies only the **writer-side `InterventionCommand` contract**; the table + poll are an **`execution-daemon` amendment** (Phase 2 cross-spec dependency — reopens its approved design).
2. **Audit validator invocation = P10 manual seam.** The monitor is a main-session scheduled orchestration (not an `Agent()` subagent), so `post_agent_validate.sh` does not fire on its self-emitted audit. It is validated via `scripts/validate_envelope.sh` with the orchestrator's LLM patching on RETRY — exactly the `/research-company` §2.5.7 CDD-memo pattern (P10).
3. **Audit store = envelope-on-disk for Phase 1; promote to a DB table (mig ≥054) only when the after-market tuner must join the "why"** (P11 cross-agent-state trigger). Avoids a Phase-1 migration; keeps the agent-envelope + HG-validator pattern.

### Simplification
- One `InterventionIntent` enum (4 bounded intents) instead of per-mechanism command objects.
- Envelope, not a table, for v0.1 (no migration).
- `command_writer` is an advisory no-op in Phase 1 (records would-be intent into the audit) rather than a separately-designed Phase-1 component.

### Risks / open items carried to tasks
- **Phase 2 is blocked on an `execution-daemon` amendment** (inbound channel) that does not exist — `/kiro-spec-tasks` must mark Phase-2 tasks blocked-on-daemon, not executable.
- **Operational restart/clear-state** (3.1) may need a 4th daemon seam (only 3 named today) — Open Question for the daemon amendment.
- **Validated-version menu semantics** (which `run_parameters_snapshot` row is "selectable") deferred to `walkforward-tuning-loop` design — Revalidation Trigger.
- **Drift threshold model** (which calibration delta over what window = which intent) is the core Phase-1 behavioral-model design item, set in `MonitorParams` (P2-pinned), calibrated empirically.

---

## Reconciliation vs execution-daemon design Revision 2 (2026-05-30, commit `2920570`)

The daemon closed the command-transport gap (its `/kiro-validate-gap` Refresh 2 follow-up). Net effect on this spec — **Phase 2 unblocked at the contract level; three carried open items resolved:**

- **Inbound channel = `execution_daemon_command_intake`** (daemon-owned, **mig 052** — co-located with `position_version` to avoid a 053+ renumber). Commander INSERTs a gated row; daemon polls it **first each cycle**, validates (gated + toward-safer), applies, marks `applied_at` / `rejected+reason`. This is the writer-side target for `command_writer`; the confirm (R6.1) = poll the marker.
- **OQ #5 (toward-safer guard) RESOLVED — daemon-enforced** (safe-mode tighten-only; select-config must be a registry member and not loosen survival). The monitor keeps its own conservative-only guard as defense-in-depth (P6).
- **OQ #6 (operational restart seam) RESOLVED — no seam.** The intake has only three command types (kill-switch / safe-mode / select-config). The monitor's wedged-component response is **engage-kill-switch + `operator_action_required` surface** (operator executes the restart), not a commanded restart. Design + R3.1 updated.
- **Trigger-model partial resolution:** the daemon sanctions a **read-only event view** of `execution_daemon_event_queue` for the monitor (never draining — the tuner is the sole drainer). The hybrid-trigger contention is gone; cadence-vs-hybrid remains a Phase-1 design choice.
- **Migration map reaffirmed:** 048 telemetry · 049/050 survival-gate · 051/052 daemon (incl. command_intake) · 053+ walkforward · **≥054 in-session-monitor audit** (if promoted to a table).

**Residual Phase-2 dependency:** the daemon design *contract* exists, but the daemon has not yet *implemented* mig 052 + the intake poll. Phase-2 tasks depend on that landing (build-order), not on any further design reopen.

---

## Reconciliation vs execution-daemon design Revision 2.1 (2026-05-30, commit `480f0a6`, APPROVED) + roadmap update

Rev 2.1 (the daemon's `/kiro-validate-design` GO) added three deltas touching this spec; all folded into `design.md`:

1. **Command-intake write-authorization (new seam).** The intake is a control channel into a levered session → every command row carries **`issued_by`**; the daemon validates it against an allowlist at apply-time; a **dedicated DB role/grant for the commander is mandated before live cutover** (v0.1 paper = permissive default). Residual halt-DoS via spurious `engage_kill_switch` accepted eyes-open (bounded to availability — the toward-safer guard prevents exposure increase). → `command_writer` adds `issued_by`; new §Security.
2. **Daemon mints `run_id` from its own `execution_daemon_epoch` table** (mig 052), deliberately NOT `run_parameters_snapshot` (keeps the `/research-company` LLM-run lifecycle + P6 reconciler uncontaminated). Consequences: (a) the audit's 4 correlation keys are the **daemon epoch keys read from the analyzed trace** (distinct from the monitor's own envelope-naming run_id); (b) the monitor's `MonitorParams` pin must **mirror this anti-contamination** — resolve `monitor.*` by value into its own context, never write a `run_parameters_snapshot` row. → audit + MonitorParams updated.
3. **Confirm columns** now explicit: `applied_at` / `status` / `reject_reason`. → `command_writer` confirm updated.

**Not a seam for this spec:** the new `reactive-replay-harness` (CPCV backtest engine, split from walkforward 2026-05-30) sits **upstream of walkforward**, not adjacent to in-session-monitor. in-session-monitor consumes walkforward's *published validated-version menu* (P2 registry), not the replay engine.

**Open (in-progress, not stable):** walkforward-tuning-loop's design + reactive-replay-harness requirements are uncommitted WIP in the working tree. The validated-version **menu contract** (`SELECT_SAFER_CONFIG` reads) is revalidate-on-land — added as a Revalidation Trigger.

---

## Validate-design round 2 — fan-out investigation + resolution (2026-05-30)

Re-validation of the post-Rev-2.1 design surfaced 3 issues; resolved via 3 parallel codebase investigations + an advisor pass. **Key correction: the advisor caught that my first single-flight scheme was actually only crash-idempotency** — fixed below.

**Issue 1 — version-scoped calibration (correctness).** The codebase already supports per-version attribution: `decision_process_trace` + `counterfactual_ledger` carry `code_version`/`param_version`/`walk_forward_window` (mig 048, indexed); `query_trace` filters on them; the walkforward tuner already scores calibration per-version-per-window; `src/calibration/metrics.py` is stateless (caller controls the population). **Resolution:** `diagnostic` filters to the active `(code_version, param_version)`; a hot-swap-crossing window uses only the current version; baseline is **per-version**. **Baseline ownership (deliberate):** v0.1 monitor computes it from the version's own in-sample ledger (self-contained, no dependency on the unstable walkforward menu); **revalidation trigger** to switch to the tuner's published baseline if/when it lands. Noted the correct post-hot-swap INSUFFICIENT/blind window.

**Issue 2 — advisory signal + single-flight.** *Idempotency ≠ single-flight* (advisor catch). My first idea (deterministic `command_id` over the rolling window) only gives crash-retry idempotency — the window edge moves each tick so the hash differs and `ON CONFLICT` never fires; escalation changes `intent_type`. **Resolution (two distinct mechanisms):** (a) idempotency = `command_id = uuid5(version-epoch-keys + intent_type)` — stable identity, **not** the window — dedups re-runs via `ON CONFLICT DO NOTHING` (mirrors `trace_id`); (b) single-flight = **skip-if-outstanding** (reuse the confirm-read to skip a tick if the writer's own unapplied row exists), with overlap additionally benign because the daemon serializes + applies toward-safer. **No new `monitor_state` table** (rejected — the intake read suffices). Advisory signal = explicit `applied:bool` on the audit (`false` = NO ACTION TAKEN).

**Issue 3 — write-auth pre-live.** Paper-only is a `RuntimeMode` flag today; **no automated paper→live gate exists** (cutover is operator-manual). **Resolution:** framed as a **documented pre-live precondition** (run under a dedicated `in_session_monitor_role`), not an "enforced gate"; the enforcement mechanism (a `BEFORE INSERT` auth trigger + `daemon_authorized_writers` control table, mirroring the mig 003/048 append-only guards) is the **daemon's to build** (cross-spec suggestion, out of boundary). Monitor owns only the `issued_by` stamp + the restricted-role precondition.

**Close-out:** remaining unknowns (tuner-published baseline contract, drift-threshold values, daemon mig-052 impl) are revalidation-triggers + task-brief items, not further design work. Design is done → `/kiro-spec-tasks`.

---

## Upstream-spec check post-tasks (2026-05-30)

Checked the dependency specs after task generation. Two upstream advances since the Rev-2.1 reconcile; neither forces a structural change.

- **execution-daemon Rev 2.2→2.4.1 (requirements + design APPROVED).** Entirely the **Edge order path** — new `candidate` (fast-clock fetch → `compute_features` → tactical-relative-strength bin→`direction`, reading `FeatureSet.raw['tactical_bin']` not `trend_vote`), `order_builder` (decision→`ProposedOrder`, ATR stop-loss price level, SHORT-open = BUY+Direction.SHORT), `PinnedParams.reactive_snapshot` (BL-2), and daemon-owned `ProposedOrder`/`Candidate` types. **None of it touches in-session-monitor's seams** — command-intake transport, the 3 command types, `issued_by`/`applied_at`/`status`/`reject_reason`, `select-validated-config`→hot-swap, and migs 051/052 are unchanged. No reconcile needed.
- **walkforward-tuning-loop design (landed).** Resolves two carried revalidation triggers: (1) the **validated-version menu = the P2 `parameters` machinery** ("publishes validated values into `parameters` rows so `parameters_active` resolves to them; no bespoke registry") — confirms the source `SELECT_SAFER_CONFIG` already reads; trigger resolved. (2) **No tuner-published per-version baseline** — walkforward computes calibration only for its own gate + tuner-action audit, so the Issue-1 v0.1 decision (monitor computes its own per-version baseline) **stands**; the tuner's per-version calibration lives in its audit (joinable via the 4 keys) as a potential future source.

tasks.md unaffected (the "validated-version menu" it references IS the now-confirmed P2 parameters machinery). Design revalidation triggers updated.
