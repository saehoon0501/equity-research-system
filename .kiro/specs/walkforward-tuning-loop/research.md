# Research & Design Decisions — walkforward-tuning-loop

## Summary
- **Feature**: `walkforward-tuning-loop`
- **Discovery Scope**: Complex Integration (a non-daemon, markdown-orchestrated after-market LLM loop sitting on four landed/landing specs)
- **Key Findings**:
  - Per P1 + §14.10 this loop is a **markdown slash-command orchestrator** (`.claude/commands/`) with Python only as **leaf skill-helpers** (`src/skills/walkforward_tune/`, first user of `src/skills/`) + an HG validator (`src/eval/gates/`) — *unlike* its four sibling specs, which are Python leaf modules / a daemon. The `/research-company` command is the canonical orchestration pattern to adopt.
  - The promotion-gate statistics (**DSR, PSR/MinTRL, PBO, CPCV, MinBTL**) do **not exist anywhere in the codebase** — they must be built as a pure deterministic leaf. Everything else reuses landed/established patterns.
  - The two open cross-seams with `execution-daemon` are **resolved by its approved design**: the event queue is `execution_daemon_event_queue` (mig 051, SELECT + `drained_at` watermark), and the daemon re-sources the advanced `walk_forward_window` at hot-swap. This loop owns the window-advance forward contract and the queue-drain.
  - **Architecture decision (operator, 2026-05-30): out-of-sample evidence = in-process CPCV replay**, not a live-forward paper window (amends §14.6). Surfaced at design time: a just-fit candidate has zero ledger rows under its `param_version`, AND the mandated PBO diagnostic (R5.1) needs multiple IS/OOS partitions a single live window cannot supply. Consequence: a **replay harness** that drives the landed reactive + survival pure cores over CPCV partitions is required; the cycle is intra-cycle (no cross-boundary ratify); requirements R2/R4/R1.4 were revised.

## Research Log

### Read substrate (decision-trace + ledger) — LANDED
- **Sources**: `src/reactive/telemetry/{schema.py,reader.py,trace_writer.py}`; `db/migrations/048_decision_trace_telemetry.sql`.
- **Findings**: `CorrelationKeys{run_id, code_version, param_version, walk_forward_window(nullable)}` (schema.py:19-33). `reader.query_trace(filters, conn=None)` accepts equality filters on the 4 keys + `kind`, and **inclusive `since`/`until` on `event_ts`** (reader.py:67-156) — exactly the temporal-firewall predicate. `counterfactual_ledger` gained nullable `code_version/param_version/walk_forward_window` (insert-set-only) + index `(code_version,param_version,walk_forward_window)` (mig 048:130-138); existing 4-bin scoring columns untouched.
- **Implications**: the firewall-read leaf wraps the landed reader (no new read primitive); version-attributed OOS P&L is a direct ledger SELECT on the three version columns. The firewall is **consumer-enforced** via `since/until` + `walk_forward_window` (decision-trace R5.2) — this loop is that consumer.

### P2 param-version machinery — REUSE (no new registry table)
- **Sources**: `db/migrations/034_run_parameters_snapshot.sql` (LANDED); `execution-daemon/design.md` `params` component; `/research-company` §1.5.
- **Findings**: `run_parameters_snapshot` (LANDED) stores per-epoch `effective_parameters_jsonb` + `effective_parameters_hash` (= the param_version) + `parameters_version_max`; resolver reads `parameters_active` (reactive + survival namespaces) under one REPEATABLE-READ txn, hashes → param_version. The daemon ADOPTS a newly-published version at atomic hot-swap (daemon R8/R9.4) and re-sources `walk_forward_window` then.
- **Implications**: "publish a validated version" = write the fitted values into the `parameters` rows (reactive/survival namespaces) so `parameters_active` resolves to them + stamp the advanced window; the daemon picks them up at its next hot-swap. No bespoke registry table is built — reuse P2. The daemon's REPEATABLE-READ resolver itself is DESIGNED-not-landed; this loop depends on it landing (revalidation trigger).

### Fit targets — DESIGNED
- **Sources**: `reactive-signal-model/design.md` (`ParamSnapshot{weights, temperature, threshold, calibration_evidence, version}`); `survival-gate/design.md` (`SurvivalParameters{stop_out_level_pct, safe_mode_buffer_pct, per_order_size_max, speculative_sleeve_cap_pct, flatten_lead_seconds, exclusion_enabled}`).
- **Implications**: the fit produces candidate values for these exact shapes — edge/return params (reactive) fit rolling, tail/risk params (survival) fit anchored. A shape change on either is a revalidation trigger.

### Event-queue drain — DESIGNED (mig 051)
- **Sources**: `execution-daemon/design.md` Data Models + System Flows.
- **Findings**: `execution_daemon_event_queue{event_id, run_id, event_type∈(decision|fill|lifecycle|command|safe_mode|kill_switch), payload(jsonb), created_at, drained_at}`. Append-only EXCEPT `drained_at` (whitelist guard, mig-034 style). Drain = `SELECT … WHERE drained_at IS NULL ORDER BY created_at` → process → `UPDATE … SET drained_at=NOW()`.
- **Implications**: the drain leaf consumes anomaly/decision/fill events; anomaly events (safe_mode/kill_switch/lifecycle) feed the behavioral analysis (R10.5). Idempotent re-drain is safe.

### Promotion-gate statistics — BUILD (gap confirmed)
- **Sources**: `docs/research-walkforward-tuning-loop-2026-05-29.md` (Bailey & López de Prado: DSR/PSR/MinTRL/MinBTL; PBO via CSCV); codebase search.
- **Findings**: no DSR/PSR/PBO/CPCV/walk-forward code exists; `src/micro/signal_model.py` (softmax) + `src/calibration/metrics.py` (Brier/reliability) are partially reusable for calibration scoring. Formulas are well-specified in the cited primary sources.
- **Implications**: build `gate.py` (+ `oos.py` for evidence assembly) as a pure, deterministic, inner-ring-tested leaf. CPCV-vs-single-window is parameterized in `oos.py`.

### Orchestration + HG-validator + migration patterns — ADOPT
- **Sources**: `.claude/commands/research-company.md`; `src/eval/gates/{_registry.py,__init__.py,*_shape.py}`; `db/migrations/048…sql`, `db/README.md`.
- **Findings**: orchestrator threads `run_id` (P3), pins `PARAMETERS_USED` (P2), persists envelopes to `memos/envelopes/<agent>__<run_id>.json` (P4) with `.degraded` skip sidecars, dispatches the `evaluator` subagent for the rubric gate, and is governed by `scripts/post_agent_validate.sh` → `orchestrator_step.py` (3-strike + $60/(run_id,agent) ceiling). HG validators are pure `*_shape.py` functions registered in `REGISTRY[artifact_type]` and run via `python -m src.eval.gates`. Migrations are hand-applied numbered `.sql`; append-only = BEFORE UPDATE/DELETE row trigger + BEFORE TRUNCATE statement trigger sharing one RAISE function.

## Architecture Pattern Evaluation
| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Markdown orchestrator + pure leaf-tool pipeline (CHOSEN) | Slash command sequences; `src/skills/walkforward_tune/*` leaves do computation + bounded I/O; `src/eval/gates` validates the audit | P1-clean; P14 inner-ring testable; mirrors `/research-company` | First `src/skills/` resident — establishes the convention | Adopted |
| Python orchestrator service | A `src/` module driving the loop | Single language | **Forbidden by P1/Decision-6** (Python making routing/dispatch decisions) | Rejected |
| Fold into execution-daemon | Daemon runs the tuning batch | Fewer seams | Violates §14.1/§14.10 (daemon never dispatches LLM); multi-hour fit can't run in hot path | Rejected |

## Design Decisions

### Decision: Promotion gate is deterministic + layered; the evaluator is separate
- **Context**: R5/R6 reference both a statistical gate AND "the evaluator"; conflating them would make promotion non-reproducible.
- **Selected Approach**: a deterministic leaf `gate.py` runs, over the CPCV matrix, (1) PSR/MinTRL sufficiency → (2) DSR + PBO superiority over incumbent on survival-net risk-adjusted return (MinBTL caps search breadth; never IS-Sharpe) → (3) operator-calibrated decision-rule (margin/consecutive-partitions/hysteresis) → (4) §13 lexicographic guard. The LLM-authored tuner-action-audit hypothesis is graded by the **HG-validator's falsifiability/derived-metrics gate** (5) — the existing per-output-type `/evaluate` hard gates, e.g. HG-4 Evidence-Index-per-claim, do NOT fit a statistical audit, so R6's "evaluator" is realized by the HG validator; a dedicated `/evaluate` rubric is a follow-on. The **full inner-ring suite** is an additional gate for the code track (6). All must pass; failure ⇒ retain incumbent (P7).
- **Rationale**: keeps the numeric verdict reproducible (P15) and reuses the evaluator for the qualitative hypothesis (P11).
- **Trade-offs**: two gate surfaces to maintain, but each is single-purpose.

### Decision: Out-of-sample evidence via in-process CPCV replay (operator, 2026-05-30)
- **Context**: a just-fit candidate has no ledger rows (never ran); the design must specify where its OOS evidence comes from. Requirements embedded an unresolved tension (R4.1 live-forward vs R4.3 CPCV-preferred), and §14.6 (live-forward) disagreed with the research doc (CPCV is the stronger validator). The PBO diagnostic the gate mandates needs multiple IS/OOS partitions.
- **Alternatives Considered**:
  1. Live-forward adopt-and-validate (§14.6 as written) — deploy challenger to paper, ratify next cycle. No replay engine, but cannot compute PBO from one window; weeks of latency; cross-boundary state.
  2. **In-process CPCV/replay [CHOSEN]** — re-simulate the candidate over purged CV partitions of realized history; gate in-process; promote = publish on pass.
  3. Hybrid (replay pre-screen + live ratify) — most defensible, most to build.
- **Selected Approach**: option 2. Build a replay harness that drives the landed reactive + survival pure cores (with candidate params/code) + the broker paper sim over CPCV partitions, producing the OOS matrix the DSR/PSR/PBO gate consumes.
- **Rationale**: satisfies the mandated PBO; statistically strongest (research: walk-forward is the weakest OOS validator); simplest cycle (intra-cycle). Operator chose it over the committed §14.6 live-forward path.
- **Trade-offs**: amends §14.6 + likely a spec rename; replay reconstruction fidelity (param-feature reuse vs code re-fetch) becomes an implementation concern; depends on the reactive/survival cores' signatures (revalidation trigger).
- **Follow-up**: §14.6 doc edit + rename (operator); replay reconstruction detail at implementation.

### Decision: Reuse P2 `run_parameters_snapshot`; no bespoke version registry
- **Context**: R7 "write the validated version into the parameter-version registry."
- **Selected Approach**: publish = write fitted values to `parameters` (reactive/survival namespaces) → `parameters_active` resolves them; the daemon adopts at hot-swap. Stamp the advanced `walk_forward_window` alongside.
- **Rationale**: the daemon already resolves+hashes `parameters_active` into `run_parameters_snapshot`; a parallel table would duplicate P2 and break the daemon's adopt path.
- **Follow-up**: confirm the daemon's resolver landed shape at implementation (revalidation trigger).

### Decision: Checkpoint/resume via run_id-keyed phase artifacts (P4), not a framework
- **Context**: R9.1 — hours-long batch must survive a crash.
- **Selected Approach**: each phase (read-set → candidate → OOS-evidence → gate-verdict → publish → audit) persists to `memos/envelopes/walkforward-tune__<run_id>.<phase>.json`; resume = re-fire same run_id, skip phases whose artifact exists.
- **Rationale**: mirrors `/research-company` envelope persistence + Workflow resume; no new infra.

### Decision: tuner-action-audit owns its table (mig 053) + envelope + HG validator (P11)
- **Context**: R8 — the audit is this loop's, not decision-trace's.
- **Selected Approach**: append-only `walkforward_tuner_audit` (mig **053**; coordinate — 048/049-050/051-052 claimed), an envelope `memos/envelopes/walkforward-tune__<run_id>.json`, and `src/eval/gates/tuner_action_audit_shape.py`. Tagged with the 4 correlation keys for join-to-trace.

## Risks & Mitigations
- **Autonomous promotion with no human backstop** (§14.11 #2) — mitigated by the layered gate + the operator kill switch retained at all times + paper-only until apparatus green (P14/§11.5).
- **Upstream DESIGNED-not-landed dependencies** (daemon resolver/event-queue/position-version; reactive ParamSnapshot; survival SurvivalParameters) — mitigated by `conn=None` dry-run leaves + shape-pinned types + revalidation triggers; inner-ring tests run against fixtures, not live upstreams.
- **Temporal leakage** (LLM carrying forward-window context into the fit) — mitigated by the firewall-read leaf being the *only* read path + tests asserting no `event_ts > IS-boundary` rows reach the fit.
- **No aggregate cost cap** (T4) — accepted, eyes-open; per-(run_id,agent) $60 ceiling still applies.
- **CPCV-vs-walk-forward / spec rename** — design keeps the gate evidence-assembly-agnostic so adopting CPCV is config, not redesign; the §14.6 amendment + possible rename stays an operator/design open item.

## References
- `docs/exploration-systematic-flow-architecture-2026-05-28.md` §14, §15, §16.1 — the committed two-clock build.
- `docs/research-walkforward-tuning-loop-2026-05-29.md` — DSR/PSR/MinTRL/PBO/MinBTL/CPCV grounding (Bailey, Borwein, López de Prado, Zhu).
- `.claude/commands/research-company.md` — adopted orchestration pattern.
- `src/reactive/telemetry/` (reader/schema/writer), `db/migrations/048…sql`, `db/migrations/034…sql` — landed seams.
