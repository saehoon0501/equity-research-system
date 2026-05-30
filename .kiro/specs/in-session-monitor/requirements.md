# Requirements Document

> Generated 2026-05-30 from the reconciled `brief.md` (Path C own-spec per §15; placement confirmed at discovery). Seams reconciled against the landed `execution-daemon` (requirements + design approved) and `walkforward-tuning-loop` (requirements): command-surface semantics, the selects-vs-deploys split, and the tuner-owned event queue. Requirements stay WHAT-not-HOW. **Carried open items (design/operator follow-up, not blockers):** (1) **command transport** — the daemon exposes *in-process* command seams but this monitor is an *out-of-process* orchestration; the inbound channel (especially for `select-validated-config`) is undefined and may warrant an `execution-daemon` follow-up; (2) **trigger model** — fixed cadence vs. a hybrid that *reads* (never drains) daemon-emitted events (the mig-051 queue is the tuner's after-market drain target); (3) **`select-validated-config` direction-of-change guard** — daemon-enforced vs. carried as the monitor's P7 obligation alone; (4) **audit-store shape + migration number** (≥ 054 if a DB table); (5) the **operational restart/clear-state seam** is not among the daemon's three named seams. The P2 parameter-version registry *shape* is deferred to `walkforward-tuning-loop` design.

## Introduction

The In-Session Monitor is the scheduled, in-session supervisory LLM loop of the reactive CFD layer's two-clock architecture (exploration §15 — the §14.3 revision; committed build per §15). The fast-clock execution daemon trades on a deterministic gate with **no LLM in the hot path**; the after-market walk-forward tuning loop fits and validates new versions only at **weeks-apart boundaries** (§14.6). Between those boundaries a model can drift out of its calibrated behavior envelope — e.g. its softmax probabilities stop being calibrated — **while still inside hard-survival limits**, and nothing in the live session would catch it.

§15 overturns the original "no LLM in-session" rule for *monitoring and intervention* (never fitting): the In-Session Monitor runs on a regular in-session cadence, reads the decision-trace telemetry and the calibration diagnostic, judges whether the model is behaving inside its envelope, and — when it is not — intervenes by commanding the **existing deterministic mechanisms** (kill switch, safe mode, versioned-config selection), then resumes. It **never fits** new values (fitting stays after-market under out-of-sample discipline, §14.4) and it is **never the survival mechanism** (the deterministic reflex fires first and independently). Because this places autonomous LLM authority inside the live levered session — stacked on the autonomous between-session promotion of the tuning loop — the kill switch and the deterministic survival gate remain the *entire* backstop (§15 blast-radius note); the system is **paper-only v0.1** until that apparatus is proven green (P14 / §11.5).

## Boundary Context

- **In scope**: the scheduled in-session supervisory cadence; behavioral judgment over the landed telemetry (calibration / behavior-envelope drift while still inside survival limits); the two operator-locked intervention classes (§15 reading #2) — *operational* (halt new entries / tightened-up-to-flatten safe mode / restart-or-clear a wedged component) and *apply-a-pre-validated-config* (select among validated versions / tighten to a safer one); the command-and-confirm obligation through existing mechanisms; the conservative-only (never-loosen) rule; its own falsifiable intervention audit correlated via the four shared keys.
- **Out of scope**: fitting, validating, or publishing any parameter/code version (`walkforward-tuning-loop`, §14.4); the hard-survival deterministic reflex and the survival decision logic (`survival-gate` / `execution-daemon` — fires first, independently); owning the kill-switch / safe-mode / versioned-config mechanisms' state (commands them, owns none); the model-trace schema, the correlation-key contract, and the outcome ledger (`decision-trace-telemetry`, landed — reader only); order-trigger / fill mechanics and the atomic hot-swap itself (`execution-daemon` / `broker-cfd-adapter`); real-time per-instrument halt / gap detection (`survival-gate`, out of boundary per its R7); any live fitting (§14.4 — no out-of-sample exists intra-session).
- **Adjacent expectations**: `decision-trace-telemetry` provides the append-only model trace + calibration inputs through the landed read surface keyed on the four correlation keys (run identifier, code version, parameter version, walk-forward window); `execution-daemon` exposes gated command seams (engage-kill-switch / set-safe-mode-grade / select-validated-config) that it applies before and independently of any supervisory input, performs the atomic hot-swap on a selected version, and provides the channel the Operator uses to halt it (the channel this monitor reuses — its concrete transport is a design item, possibly a daemon follow-up); `walkforward-tuning-loop` publishes validated versions into the P2 parameter-version registry this monitor selects from; the operator kill switch (`survival-gate` / §11.5) overrides this monitor at all times.

## Requirements

### Requirement 1: Scheduled in-session supervisory cadence

**Objective:** As the operator of the reactive CFD layer, I want an LLM monitor that runs on a regular in-session cadence reading how the model behaves, so that behavioral drift is caught between the weeks-apart after-market tuning boundaries.

#### Acceptance Criteria
1. The In-Session Monitor shall be dispatched on a regular in-session cadence by a scheduler, not interactively.
2. While the market session is open, the In-Session Monitor shall, on each cadence tick, read the recent decision-trace telemetry and the calibration diagnostic for the active model version.
3. The In-Session Monitor shall not participate in the order-fire decision and shall not sit in the survival hot path, such that the deterministic gate decides and fires without waiting on the monitor.
4. The In-Session Monitor shall never fit, tune, or compute new parameter or code values during a session (fitting is after-market only, §14.4).

### Requirement 2: Behavioral judgment — derived drift detection

**Objective:** As the operator, I want the monitor to judge whether the model is inside its calibrated behavior envelope using derived diagnostics, so that intervention is triggered by evidence rather than an asserted confidence (P15).

#### Acceptance Criteria
1. The In-Session Monitor shall judge whether the model's behavior is within its calibrated envelope using diagnostics derived from the telemetry (e.g. calibration / reliability of the softmax probabilities, the declined-versus-fired distribution, slippage), not an asserted probability.
2. When the model exhibits behavioral drift while still inside hard-survival limits (for example a calibration breakdown), the In-Session Monitor shall classify it as an actionable anomaly.
3. The In-Session Monitor shall express every anomaly judgment as a derived figure or a structured scenario with observable falsifiers, and shall not assert a probability from qualitative reasoning (P15).
4. If the available telemetry is insufficient to judge the model's behavior, then the In-Session Monitor shall record the insufficiency and shall not assert an envelope verdict or intervene on an unsupported judgment.

### Requirement 3: Intervention authority — operational and apply-pre-validated-config only

**Objective:** As the operator, I want the monitor's authority bounded to operational recovery and selecting a safer pre-validated configuration, so that the in-session LLM can stop / fix / resume without ever fitting live (§15 reading #2).

#### Acceptance Criteria
1. When the In-Session Monitor intervenes operationally, it shall be limited to halting new entries, commanding a tightened (up to flatten-grade) safe mode, engaging the kill switch, or restarting / clearing a wedged component, and then resuming.
2. When the In-Session Monitor intervenes by configuration, it shall be limited to selecting among already-validated parameter-config versions or tightening to a safer validated version.
3. The In-Session Monitor shall never fit, validate, or publish a parameter or code version, and shall never select a configuration that the walk-forward tuning loop has not already validated and published.
4. The In-Session Monitor's interventions shall never block a true exit (a net-reducing close) or a flatten; a halt or tighten freezes new exposure only, consistent with the rule that getting flat is always permitted (§16.1 / daemon Req 7.2).

### Requirement 4: Commands flow only through existing mechanisms

**Objective:** As the operator guarding a single auditable halt path, I want every intervention expressed as a command into an existing deterministic mechanism, so that the monitor introduces no new mutation path into the live levered book (§15 invariant).

#### Acceptance Criteria
1. The In-Session Monitor shall express every intervention as a command into an existing mechanism — the kill switch, the safe-mode grade, or versioned-config selection — and shall not introduce any direct-mutation path.
2. If an intervention would directly mutate a position, a survival value, or an edge value rather than route through an existing mechanism, then the In-Session Monitor shall not issue it.
3. The In-Session Monitor shall rely on the execution-daemon to apply a commanded change (for example performing the atomic hot-swap on a selected version) and shall not itself deploy, hot-swap, or apply a version.

### Requirement 5: Conservative-only and reflex-first

**Objective:** As the operator, I want the monitor able only to make the system safer and never to pre-empt the deterministic survival reflex, so that survival is never traded for any in-session convenience (P7 / §13 / §15).

#### Acceptance Criteria
1. The In-Session Monitor shall only ever move the system to an equal or more conservative state (halt, tighten, or select a more conservative version) and shall never loosen safe mode, increase exposure, or select a looser configuration.
2. While the deterministic reflex (kill switch / safe mode) is engaged, the In-Session Monitor shall not override or relax it; loosening occurs only through the explicit operator / after-market path.
3. The In-Session Monitor shall act as a second-line supervisor such that the deterministic survival reflex remains authoritative and fires first and independently of any monitor judgment.

### Requirement 6: Command delivery and fail-safe (no fire-and-forget)

**Objective:** As the operator, I want the monitor to confirm its interventions take effect and to fail safe when it cannot, so that a drifted model is never left trading on the assumption that an unconfirmed command worked.

#### Acceptance Criteria
1. When the In-Session Monitor issues an intervention command, it shall confirm the command was received and took effect before treating the intervention as applied.
2. If the In-Session Monitor cannot confirm an intervention took effect, then it shall escalate to the always-available halt and surface the failure to the operator rather than assume success.
3. The In-Session Monitor shall not resume normal monitoring of an intervened component until it has verified the component returned to a healthy, responsive state.

### Requirement 7: Intervention audit — own surface, falsifiable, correlated

**Objective:** As the operator and the calibration loop, I want a falsifiable record of why each intervention happened, joinable to the model trace, so that in-session interventions are auditable and later checkable against outcomes (P11 / P15 / §14.8).

#### Acceptance Criteria
1. When the In-Session Monitor intervenes, or declines to intervene on a flagged anomaly, it shall emit its own intervention-audit record stating the triggering diagnostic and the intervention rationale.
2. The In-Session Monitor shall express the intervention rationale as a falsifiable hypothesis with observable falsifiers, and the triggering figures as derived diagnostics, not asserted probabilities (P15).
3. The In-Session Monitor shall tag each audit record with the four correlation keys (run identifier, code version, parameter version, walk-forward window) so it joins to the model trace and the outcome ledger.
4. The In-Session Monitor shall own this audit surface and its validation, separate from the decision-trace telemetry (which owns the model trace) and from the daemon's command-event record (which records that a command was applied) — the audit owns the *why*, not a duplicate of the *what*.

### Requirement 8: Dispatch, autonomy, and cost

**Objective:** As the operator, I want the monitor scheduled and autonomous yet always under the kill switch and the existing cost regime, so that in-session supervision runs unattended in paper without an aggregate-cost backstop being assumed (§14.11 #2/#4, §11.5).

#### Acceptance Criteria
1. The In-Session Monitor shall act autonomously without per-intervention human sign-off.
2. The In-Session Monitor shall remain subject to the operator kill switch and the survival gate at all times (autonomy removes per-intervention approval, not the emergency halt).
3. The In-Session Monitor shall remain subject to the existing per-`(run_id, agent)` cost ceiling; an aggregate cost ceiling across its cadence is not required for v0.1 (T4 / §14.11 #4, accepted eyes-open).
4. While the system is in the paper-only phase, the In-Session Monitor shall act only on the paper/challenger track and shall not enable or assume live real-money routing.

### Requirement 9: Consumption boundary and dependency contracts

**Objective:** As the operator maintaining the cross-spec seams, I want the monitor to consume the upstream contracts as a reader and commander, so that it never duplicates or owns the trace, the mechanisms, or the config menu (P11).

#### Acceptance Criteria
1. The In-Session Monitor shall read the model trace and calibration inputs through the landed read surface and the four shared correlation keys, and shall not reimplement or own them.
2. The In-Session Monitor shall command the execution-daemon only through its exposed kill-switch / safe-mode / versioned-config-select seams, and shall not own those mechanisms' state logic.
3. The In-Session Monitor shall select only among versions published in the parameter-version registry by the walk-forward tuning loop, and shall not own or write that registry.
4. The In-Session Monitor shall deliver its interventions to the execution-daemon only through a defined command channel; where that channel is not yet established, the monitor shall not be relied upon for intervention and the operator's manual kill switch shall remain the interim backstop.
5. If a consumed upstream contract changes shape (a correlation key, the command-seam surface, the command channel, or the parameter-version registry shape), then the In-Session Monitor shall be revalidated against the new shape.
