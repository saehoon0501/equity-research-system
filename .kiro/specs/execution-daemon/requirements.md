# Requirements Document

## Introduction

The Execution Daemon is the persistent, non-LLM **fast-clock process** of the reactive CFD execution layer. It is the only component that *runs* the four foundation modules — the **broker adapter** (Route), the **reactive signal model** (Edge), the **survival gate** (Survive), and the **decision-trace store** (the trace). On each evaluation tick it enforces the lexicographic value chain **Survive ⊳ Preserve ⊳ Edge ⊳ Return**, drives the paper-mode order lifecycle, and assembles the complete per-decision telemetry record — including the correlation-key injection and substrate→trace mapping that no other module owns. It is a **leaf executor and event emitter only**: it never dispatches an agent and never re-computes the survival, edge, or sizing logic its dependencies own. v0.1 is **paper-only**.

Primary roles: the **Operator** (starts / monitors / halts the daemon, reads telemetry), the **reactive CFD trading system** (the automated flow itself), and the **downstream consumers** (the walk-forward tuning loop and the in-session monitor).

## Boundary Context
- **In scope**: the persistent single-evaluation-at-a-time loop + scheduling cadence; §13 orchestration of the four dependencies; the paper-mode submit→poll→reconcile order lifecycle incl. double-send guard and resize-on-advisory; complete telemetry row assembly (decision + linked fill, full correlation keys, derived gate fields); persist-then-act ordering + operational-state freshness; flat-before-close action + verify-flat handshake; the full version-pinned position lifecycle + atomic hot-swap; after-market event-queue emission; exposure of kill-switch / safe-mode / versioned-config command seams.
- **Out of scope**: live real-money routing (paper/dry-run only); the survival, edge, and sizing *logic* (owned by the dependencies — the daemon orchestrates, never recomputes); parameter fitting/tuning + calibration; the trace store's schema and write primitives; the in-session supervisory loop itself; any dispatch or orchestration of LLM workers.
- **Adjacent expectations**: the broker adapter exposes place/readout/history operations and surfaces fill/swap/forced-liquidation data; the signal model emits a directional decision plus a decision substrate carrying its two version keys; the survival gate emits admit/assess verdicts, operational-state transitions, and events, and declares the persist-then-act, assess-cadence, and single-threaded-loop contracts ON the daemon; the decision-trace store provides an idempotent, append-only write surface keyed on a client-minted trace identifier and a four-key correlation set; the tuning loop supplies versioned parameters the daemon hot-swaps and drains the daemon's event queue; the in-session monitor issues commands only through the daemon's exposed kill-switch / safe-mode / versioned-config seams.

## Requirements

### Requirement 1: Persistent fast-clock evaluation loop
**Objective:** As the reactive CFD trading system, I want a persistent process that evaluates on a bounded cadence, one evaluation at a time, so that survival and edge decisions are made continuously and free of race conditions.

#### Acceptance Criteria
1. While the daemon is running, the Execution Daemon shall perform at most one evaluation at a time, completing each evaluation's read-modify-write of operational state before beginning the next.
2. While the daemon is running and no order is contemplated, the Execution Daemon shall invoke the survival standing-monitor at least once every configured maximum-latency interval.
3. When a margin-material event occurs, the Execution Daemon shall invoke the survival standing-monitor without waiting for the next scheduled interval.
4. When an evaluation cycle begins, the Execution Daemon shall use a parameter set pinned by value for the duration of that cycle and shall not re-resolve parameters from live state mid-cycle.
5. If an evaluation cannot complete because of a dependency error or malformed input, then the Execution Daemon shall fail toward minimum exposure — reject any opening order, never block a true exit or a reduce/flatten directive — and record the failure.

### Requirement 2: Lexicographic §13 orchestration
**Objective:** As the reactive CFD trading system, I want every action gated in Survive ⊳ Preserve ⊳ Edge ⊳ Return order, so that no edge or return consideration can override survival.

#### Acceptance Criteria
1. When an order is contemplated, the Execution Daemon shall obtain a survival admit verdict before requesting any directional decision or placing any order.
2. If the survival gate returns a reject verdict, then the Execution Daemon shall not place the order and shall record the binding constraint.
3. When the survival gate admits an order, the Execution Daemon shall obtain the directional decision from the signal model and, only if the decision is actionable, size it using the advisory sizing hint capped by survival limits.
4. The Execution Daemon shall not re-compute, override, or increase any survival, edge, or sizing value produced by a dependency.
5. When the signal model returns HOLD or a sub-threshold decision, the Execution Daemon shall place no order and shall record a declined decision.

### Requirement 3: Paper-mode order lifecycle
**Objective:** As the Operator, I want orders driven through a paper-mode submit→poll→reconcile lifecycle with no live transmission, so that v0.1 can be exercised without real-money risk.

#### Acceptance Criteria
1. The Execution Daemon shall route orders in paper/dry-run mode only and shall not enable any live real-money transmission path in v0.1.
2. When an order is placed, the Execution Daemon shall drive the asynchronous submit→poll→reconcile lifecycle until the order reaches a terminal outcome (filled, simulated, rejected, or unconfirmed).
3. If an order outcome is unconfirmed, then the Execution Daemon shall surface it as unconfirmed and shall not treat it as filled.
4. While a submitted order's confirmation is pending, the Execution Daemon shall not issue a duplicate submission for the same order intent.
5. When the survival gate rejects an order for a size breach and returns an advisory maximum volume, the Execution Daemon shall resize to at most that advisory maximum and resubmit, rather than transmit the original volume.

### Requirement 4: Complete telemetry row assembly
**Objective:** As the downstream tuning loop and the Operator, I want every decision and fill recorded as a complete, correlatable trace record, so that model behavior is fully reconstructable and attributable.

#### Acceptance Criteria
1. When the Execution Daemon reaches any decision — including a declined or HOLD decision — it shall record a decision trace carrying a complete correlation key set comprising a run identifier, a code version, a parameter version, and a walk-forward window.
2. When assembling a decision trace, the Execution Daemon shall supply the run identifier and the walk-forward window that the signal model does not provide, in addition to the code version and parameter version the model emits.
3. When assembling a decision trace, the Execution Daemon shall mint a client-side trace identifier and stamp the event time as of the decision (not as of the write).
4. When an order produces a confirmed fill, the Execution Daemon shall record a fill record linked to its originating decision trace and attributed to that originating decision's walk-forward window.
5. If a trace record is re-submitted for an already-recorded decision or fill, then the Execution Daemon shall not create a duplicate record.
6. The Execution Daemon shall record a decision substrate — signal values, probability, effective threshold, the triggering survival link, and derived liquidation-proximity / stop-out / declined indicators — sufficient to reconstruct the decision.

### Requirement 5: Persist-then-act and operational-state freshness
**Objective:** As the reactive CFD trading system, I want safety-state transitions persisted before any action, so that a just-engaged kill switch or safe-mode escalation can never be bypassed by an in-flight action.

#### Acceptance Criteria
1. When the survival gate emits an operational-state transition, the Execution Daemon shall durably persist the transition before executing any directive or admitting any order.
2. While the daemon is running, the Execution Daemon shall read operational state fresh at the start of every admit or assess evaluation and shall never use a pinned copy of operational state.
3. When the kill switch becomes engaged, the Execution Daemon shall observe it on every subsequent admit evaluation within the same run.
4. The Execution Daemon shall persist every survival event and operational-state transition the gate emits to an append-only record.

### Requirement 6: Flat-before-close action
**Objective:** As the Operator, I want the book flattened before any non-traded window, so that no levered exposure is held across a close.

#### Acceptance Criteria
1. When a closure is within the configured flatten-lead window and levered exposure is open, the Execution Daemon shall execute the survival gate's flatten directives.
2. When flatten directives have been executed, the Execution Daemon shall re-check the flat post-condition before the close.
3. If the flat post-condition is not met after executing flatten directives, then the Execution Daemon shall escalate per the survival gate and record a verify-flat failure.

### Requirement 7: Kill switch and safe-mode reflex
**Objective:** As the Operator, I want a deterministic safety reflex that halts new exposure immediately without waiting on any LLM, so that survival actions are never latency-bound by deliberation.

#### Acceptance Criteria
1. While the kill switch is engaged, the Execution Daemon shall route no order that opens or increases net exposure.
2. While the kill switch is engaged or safe mode halts new entries, the Execution Daemon shall still permit a true exit (a net-reducing close) and any reduce or flatten directive.
3. The Execution Daemon shall apply the deterministic survival / kill-switch / safe-mode reflex before, and independently of, any LLM-driven supervisory input.
4. While safe mode is at a tightened grade, the Execution Daemon shall reflect that grade and shall not loosen it except through the explicit operator / after-market path.

### Requirement 8: Version-pinned position lifecycle and atomic hot-swap
**Objective:** As the reactive CFD trading system, I want each position managed under the parameter and code version it was opened with, and parameter swaps applied atomically, so that a mid-run version change cannot corrupt an open position's management.

#### Acceptance Criteria
1. When the Execution Daemon reads parameters for an evaluation cycle, it shall read the whole versioned parameter object once and swap it as a single atomic unit, never field-by-field.
2. When a position is opened, the Execution Daemon shall associate it with the code version and parameter version in effect at open time.
3. While a position remains open after a parameter hot-swap, the Execution Daemon shall continue to manage that position under its opening version and shall not retroactively re-manage it under the new version.
4. While positions opened under more than one version are open simultaneously, the Execution Daemon shall apply survival constraints at the globally tightest level across all open positions.

### Requirement 9: Event-queue emission and command-surface exposure
**Objective:** As the downstream tuning loop and in-session monitor, I want the daemon to emit drainable events and to accept commands only through defined safety seams, so that after-market tuning and in-session supervision can act without bypassing survival.

#### Acceptance Criteria
1. The Execution Daemon shall emit decision and lifecycle events to an after-market queue that the tuning loop can drain.
2. The Execution Daemon shall expose command seams for engaging the kill switch, setting the safe-mode grade, and selecting among validated parameter-config versions.
3. When a supervisory command is received, the Execution Daemon shall apply it only through the kill-switch / safe-mode / versioned-config-select paths and shall reject any command that would directly mutate a position or a survival or edge value.
4. When the tuning loop publishes a new validated parameter-config version, the Execution Daemon shall adopt it via the atomic hot-swap path defined in Requirement 8.

### Requirement 10: Leaf-executor boundary
**Objective:** As the system maintainer, I want the daemon constrained to executing and emitting, so that it never becomes an orchestrator of LLM agents or a re-implementation of dependency logic.

#### Acceptance Criteria
1. The Execution Daemon shall not dispatch, spawn, or orchestrate any LLM agent or subagent.
2. The Execution Daemon shall not compute any probability, margin-distance, sleeve-cap, or liquidation value of its own; it shall consume each from its owning dependency.
3. The Execution Daemon shall obtain directional decisions, survival verdicts, sizing hints, and venue actions exclusively from their owning dependencies.
