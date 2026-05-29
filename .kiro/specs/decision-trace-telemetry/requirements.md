# Requirements Document

> Generated 2026-05-29 (decision-trace fork) from the settled brief. **Model-trace-only** scope (LLM-action audit owned per-spec, P11). Schema specifics — the single append-only `decision_process_trace` table (typed identity/version/window columns + a JSONB `trace` blob) and the additive ledger migration (number **048**) — are recorded in the brief and finalized at design; the acceptance criteria below stay WHAT-not-HOW.

## Introduction

The reactive CFD layer's after-market tuner (`walkforward-tuning-loop`) and in-session monitor (§15) must analyze **how the model behaves**, not just its P&L — without a structured, replayable per-decision trace the tuner is "P&L-staring" (§14.8). And without a model-version dimension on the outcome ledger, forward P&L cannot be attributed per-version-per-window, making walk-forward promotion unscoreable and opening a temporal-leakage hazard (§14.6).

Decision-Trace Telemetry provides two surfaces: (1) a per-decision **process trace** — a durable, append-only record of every decision the `execution-daemon` makes (which lexicographic gate link triggered, the signal values + derived probability at fire, expected-vs-actual fill/slippage, liquidation proximity, stop-outs, and **declined/missed entries**), keyed by correlation identifiers; and (2) an additive **model-version dimension** on the existing `counterfactual_ledger` *outcome* side, so forward P&L attributes per-(code version, parameter version)-per-walk-forward-window without disturbing the existing 4-bin sector-ETF-excess scoring.

This is the **model trace only**: the LLM-action/reasoning audit (why the tuner promoted a version, why the monitor intervened) is owned per-spec by those components (P11) and joined back to this trace via the shared **correlation keys**. The daemon writes the trace directly (the daemon speaks the database directly, §14.10); this spec owns the schema, the append-only write path, and the correlation-key contract — **not** the emission calls. Records persist append-only as durable database rows (P4), never in-context. The schema, append-only enforcement, and the additive migration are the **inner-ring surface built first** (P14): the version dimension is precisely what makes the outer-ring (eval-loop) scoreable per-version, so the trace must exist before any version-attributed scoring is wired.

Consumers: `walkforward-tuning-loop` (reads the trace + version-attributed ledger; its temporal firewall depends on the version+window dimension), the in-session monitor (reads recent trace for behavioral/anomaly judgment, §15), and the existing eval loop (continues scoring the 4-bin label, now version-aware).

## Boundary Context

- **In scope**: durable, append-only per-decision process-trace records (including declined/missed entries); the correlation-key contract (run identifier, code version, parameter version, walk-forward window); the additive `counterfactual_ledger` model-version dimension preserving existing scoring; a queryable read/replay surface filterable by the correlation keys; inner-ring tests for append-only enforcement + migration safety.
- **Out of scope**: the LLM-action/reasoning audit (owned per-spec by `walkforward-tuning-loop` + the in-session monitor, P11); the emission CALLS (made by the `execution-daemon`); analysis, tuning, or calibration aggregates (downstream); reimplementing the existing 4-bin outcome scoring (extend-only); the daemon's decision logic itself.
- **Adjacent expectations**: extends `counterfactual_ledger` (migrations 003/011/030 — append-only trigger, 4-bin sector-ETF-excess scoring at 90d/1y/3y/5y); reuses the repo's append-only-table + flexible-payload conventions (e.g. `system_errors`, `counterfactual_retrievals`); the `execution-daemon` (§14.10) invokes the write path directly; per-spec LLM-action audits join to this trace via the shared correlation keys.

## Requirements

### Requirement 1: Per-decision process-trace capture
**Objective:** As the after-market tuner and the in-session monitor, I want every daemon decision recorded as a replayable trace, so that analysis rests on process detail, not just the P&L curve.

#### Acceptance Criteria
1. When the execution-daemon reaches a decision, the Decision-Trace Telemetry shall persist a durable trace record for that decision.
2. The trace record shall capture which lexicographic gate link determined the outcome.
3. The trace record shall capture the signal values and the derived probability present at the moment of decision.
4. When a decision results in an executed order, the trace record shall capture the expected-versus-actual fill, including slippage measured against counterparty prices.
5. The trace record shall capture the liquidation proximity and any stop-out in effect at the time of the decision.
6. When a decision is a declined or missed entry (no order), the Decision-Trace Telemetry shall still persist a trace record for it.

### Requirement 2: Append-only integrity
**Objective:** As the operator, I want trace records immutable once written, so that the behavioral record cannot be silently altered or deleted.

#### Acceptance Criteria
1. The Decision-Trace Telemetry shall persist trace records append-only.
2. If a modification or deletion of a persisted trace record is attempted, then the Decision-Trace Telemetry shall reject it.

### Requirement 3: Correlation-key contract
**Objective:** As the downstream consumers and the per-spec LLM-action audits, I want every record tagged with its version and window context, so that the model trace, the LLM audits, and the outcome ledger can all be joined.

#### Acceptance Criteria
1. Every trace record shall carry the run identifier, code version, parameter version, and walk-forward window under which the decision was made.
2. The Decision-Trace Telemetry shall expose these correlation keys as queryable fields, so that the per-spec LLM-action audits and the outcome ledger can be joined to the trace.

### Requirement 4: Counterfactual-ledger model-version dimension
**Objective:** As the walk-forward tuner, I want forward P&L attributable per version per window, so that promotion decisions are scoreable and free of temporal leakage.

#### Acceptance Criteria
1. The Decision-Trace Telemetry shall extend the existing `counterfactual_ledger` with code-version, parameter-version, and walk-forward-window attribution, added additively.
2. The extension shall preserve the existing 4-bin label scoring (sector-ETF-excess returns at 90d / 1y / 3y / 5y) and all existing ledger columns and behavior.
3. After the extension, the Decision-Trace Telemetry shall make forward P&L attributable per code-version, per parameter-version, and per walk-forward window.
4. The extension shall preserve the ledger's existing append-only integrity.

### Requirement 5: Temporal-firewall support
**Objective:** As the tuner, I want to restrict my read to telemetry up to an in-sample boundary, so that I never fit on the forward window's own outcomes (§14.6).

#### Acceptance Criteria
1. Each trace record and each ledger record shall carry the decision/measurement timestamp and walk-forward window needed for a consumer to restrict its read to records up to a given in-sample boundary.
2. The Decision-Trace Telemetry shall not itself enforce the firewall; it shall provide the window and timestamp attribution that lets a consumer enforce it.

### Requirement 6: Replay and read surface
**Objective:** As the tuner and the in-session monitor, I want to reconstruct the decisions for a given run, version, or window, so that I can analyze behavior and diagnose anomalies.

#### Acceptance Criteria
1. The Decision-Trace Telemetry shall expose a read surface that lets a consumer retrieve the trace records for a given run, code version, parameter version, or walk-forward window.
2. The read surface shall let a consumer filter records by the correlation keys.

### Requirement 7: Model-trace scope boundary
**Objective:** As the operator enforcing P11 and §14.8, I want this surface limited to the model trace, so that the LLM-action audits stay per-spec and the eval loop is not duplicated.

#### Acceptance Criteria
1. The Decision-Trace Telemetry shall record the model decision trace only and shall not record the LLM-action or reasoning audit (owned per-spec by the tuner and the in-session monitor).
2. The Decision-Trace Telemetry shall own the trace schema and the write path and shall not own the emission calls, which are made by the execution-daemon.
3. The Decision-Trace Telemetry shall not compute analysis, tuning, or calibration aggregates.
4. The Decision-Trace Telemetry shall not reimplement the existing 4-bin outcome scoring; it shall only extend the ledger additively.

### Requirement 8: Durable, schema-stable persistence
**Objective:** As the operator, I want trace persistence durable and resilient to new signal fields, so that adding a feature does not force a schema migration and nothing is lost to in-context handoff.

#### Acceptance Criteria
1. The Decision-Trace Telemetry shall persist trace records as durable database rows, not as in-context or in-memory handoff.
2. The Decision-Trace Telemetry shall accommodate additional per-decision signal detail without requiring a schema change for each new field, while keeping the correlation keys as typed, queryable fields.

### Requirement 9: Inner-ring test surface and build order
**Objective:** As the operator maintaining the system, I want the append-only enforcement and the additive migration verified before any version-attributed scoring, so that an outer-ring miss is interpretable (P14).

#### Acceptance Criteria
1. The append-only enforcement (rejecting modification and deletion) shall be verifiable by inner-ring tests without LLM or MCP access.
2. The additive migration shall be verifiable by an inner-ring test confirming the existing 4-bin scoring and all existing ledger columns are preserved.
3. The version-attributed outer-ring scoring shall not be wired against the ledger until the trace and migration inner-ring tests are in place.
