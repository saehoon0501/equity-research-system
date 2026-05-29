# Requirements Document

> Generated 2026-05-30 from the discovery brief. §14.11's six operator questions are all RESOLVED (2026-05-29), grounded in `docs/research-walkforward-tuning-loop-2026-05-29.md`; the requirements below are faithful to those decisions and stay WHAT-not-HOW. The promotion gate is named at the methodology level (DSR + PSR/MinTRL + PBO on the survival-net risk-adjusted return metric); thresholds, effective-N computation, the event-queue substrate, the parameter-version registry shape, and connection/checkpoint mechanics are deferred to design. **Carried open items (design/operator follow-up, not blockers):** (1) whether to formally amend §14.6 / reconsider this spec's name now that CPCV is preferred over a single walk-forward window; (2) the provisional numeric values of the decision-rule knobs (OOS margin, consecutive-window count, anti-churn hysteresis) — calibrated empirically; (3) the two cross-seams with `execution-daemon` are now **resolved by its approved design (2026-05-30)** — the event queue is the append-only `execution_daemon_event_queue` table (mig 051) drained by SELECT+watermark (this loop sets `drained_at`), and the daemon re-sources the advanced walk-forward window at hot-swap (this loop owns the window-advance forward contract); the residual is design-local to this spec (how the advanced window is published with the version, and claiming migration 053+ for the tuner-action-audit table, since 048/049-050/051-052 are taken); (4) champion/challenger mechanics designed first-principles (the ML-ops definition was refuted in research).

## Introduction

The Walk-Forward Tuning Loop is the after-market, asynchronous **slow clock** of the reactive CFD layer's two-clock architecture (exploration §14, committed build per §15). The in-session fast clock only *applies* pre-validated parameters and code (§14.4); it never fits new ones, and a multi-hour fit cannot run inside a session (§14.3/§14.4). The Tuning Loop closes that gap: fired at a walk-forward boundary, it reads how the model behaved (the decision-trace + version-attributed outcome ledger), fits a new parameter and/or code version under out-of-sample discipline, evaluates it as a challenger against the incumbent on a Survive-first risk-adjusted metric, and — through an overfitting-corrected gate with **no human sign-off** (§14.11 #2) — promotes it by writing a validated version into the parameter-version registry the fast clock later deploys and the in-session monitor later selects from.

Because promotion is fully autonomous, the gate's rigor and the §11.5 kill switch are the *entire* defense between an LLM-authored change and the levered book (§14.11 #2). The system is **paper-only v0.1** until the survival apparatus is proven green on the inner ring (P14 / §11.5); full autonomy is acceptable in the paper/challenger phase, but the gate and kill switch must be proven green before any live real-money cutover.

## Boundary Context

- **In scope**: the after-market walk-forward cycle (in-sample fit → challenger forward evaluation → promote = window advance) fired by a boundary scheduler/event queue; a temporal firewall on the tuner's read (in-sample-boundary-capped, never the forward window under test); after-market fitting of new versions for both tracks — the reactive `ParamSnapshot` (edge/return, rolling memory) and the `SurvivalParameters` (tail/risk, anchored memory) and structural code; the autonomous overfitting-corrected promotion gate (DSR + PSR/MinTRL + PBO on the survival-net risk-adjusted return metric, never in-sample Sharpe), preferring combinatorial purged cross-validation over a single forward window; writing the promoted version into the parameter-version registry (P2) and advancing the walk-forward window; this loop's own falsifiable tuner-action audit (P11/P15); checkpoint/resume of the hours-long batch.
- **Out of scope**: the live fire/order decision, the hot path, order placement, atomic hot-swap, deploy-at-clean-boundary, and the full version-pinned position lifecycle (`execution-daemon` — took the full lifecycle + hot-swap in scope per operator override 2026-05-30); the in-session **selection** among validated versions and the halt/tighten intervention plus its own audit (`in-session-monitor`, §15); the decision-trace schema, the correlation-key contract, and the `counterfactual_ledger` version dimension (`decision-trace-telemetry`, landed — this loop is a reader); runtime application/selection of parameters and any live fitting (§14.4 — fitting is after-market only); the enforcement of the survival one-way tighten-only guarantee at runtime/version-transition (`survival-gate` / `execution-daemon` / §13); reimplementing the softmax/threshold model or the survival logic (this loop tunes their snapshots).
- **Adjacent expectations**: it reads the model trace and the version-attributed outcome ledger through the landed read surface and the four shared correlation keys (run identifier, code version, parameter version, walk-forward window); it drains the after-market event queue emitted by `execution-daemon`; it writes promoted versions into the P2 parameter-version registry that `execution-daemon` deploys and `in-session-monitor` selects from; the version-attributed outcome ledger (`decision-trace-telemetry`) is the substrate for both the challenger score and the §12.5 filter-gated-vs-pure-reactive A/B that runs *across* walk-forward steps; the operator's kill switch (`survival-gate` / §11.5) overrides this loop's autonomy at all times.
- **Known limitation (eyes-open)**: there is **no aggregate cost ceiling** across a tuning batch (T4 / §14.11 #4) — only the existing per-`(run_id, agent)` ceiling applies, and a code-generation + full inner-ring pass is the most expensive job in the repo; a runaway batch has no aggregate halt. This is an accepted, eyes-open risk for v0.1.

## Requirements

### Requirement 1: After-market walk-forward cycle

**Objective:** As the operator of the reactive CFD layer, I want adaptation to run only after the close on a walk-forward boundary, so that fitting never enters the latency-bound in-session hot path (§14.1/§14.4) and the trading loop never waits on it.

#### Acceptance Criteria
1. The Walk-Forward Tuning Loop shall run only after market close (after-market), and shall not fit, tune, or modify any parameter or code during market hours.
2. When fired at a walk-forward boundary by a scheduler or drained event, the Walk-Forward Tuning Loop shall execute one cycle of in-sample fit, challenger forward evaluation, and a promotion decision.
3. The Walk-Forward Tuning Loop shall run asynchronously such that the in-session trading loop never blocks on or waits for it.
4. When a cycle completes a promotion, the Walk-Forward Tuning Loop shall advance the walk-forward window so the completed forward period folds into the next in-sample window.

### Requirement 2: Temporal firewall on the tuner read

**Objective:** As the operator guarding against leakage, I want the tuner to see only data up to the in-sample boundary, so that it can never fit on the very forward window its promotion is scored against (§14.6).

#### Acceptance Criteria
1. While fitting a candidate version, the Walk-Forward Tuning Loop shall read trace and outcome records only up to the in-sample boundary of the cycle.
2. The Walk-Forward Tuning Loop shall not read the forward window's own outcomes when fitting the candidate evaluated over that window.
3. The Walk-Forward Tuning Loop shall use the walk-forward-window and timestamp attribution provided by the decision-trace and outcome ledger to enforce this firewall.

### Requirement 3: After-market fitting of new versions (param and code tracks)

**Objective:** As the operator, I want new parameter and code versions fit only after-market under out-of-sample discipline, so that every promoted change was validated against data it was not fit on (§14.4).

#### Acceptance Criteria
1. The Walk-Forward Tuning Loop shall fit new candidate values for the reactive parameter snapshot (edge/return parameters and the decision threshold) and for the survival parameters (tail/risk).
2. The Walk-Forward Tuning Loop shall fit edge/return parameters on a rolling (recent-regime) in-sample memory and survival parameters on an anchored (all-history) in-sample memory, as a provisional split to be validated on the book (§14.11 #5).
3. Where the structural code track is exercised, the Walk-Forward Tuning Loop shall produce a candidate code/structure version in addition to, or instead of, a parameter version.
4. When a fit completes, the Walk-Forward Tuning Loop shall produce a single hashed, versioned snapshot of the candidate (P2), so the candidate is identifiable and reproducible.
5. The Walk-Forward Tuning Loop shall never apply or select a fitted version at runtime; runtime application and in-session selection are owned downstream.

### Requirement 4: Out-of-sample challenger evaluation on the survival-net metric

**Objective:** As the operator, I want a candidate proven on live-forward paper performance against the incumbent, so that promotion is earned out-of-sample and ranked by a Survive-first metric, not by backtest fit (§14.6/§13).

#### Acceptance Criteria
1. The Walk-Forward Tuning Loop shall evaluate each candidate as a challenger over a forward window on paper data, against the incumbent champion.
2. The Walk-Forward Tuning Loop shall score candidate and incumbent on the survival-net risk-adjusted return metric (reflecting the §13 ordering Survive ⊳ Preserve ⊳ Edge ⊳ Return).
3. The Walk-Forward Tuning Loop shall prefer combinatorial purged cross-validation over a single walk-forward window as the out-of-sample validator where feasible, and shall treat a single forward window as necessary-but-weak evidence.
4. The Walk-Forward Tuning Loop shall include the calibration of the model's derived probabilities (e.g. reliability over the forward window) as a behavioral evaluation input, not only hit-rate or P&L.
5. The Walk-Forward Tuning Loop shall never use the in-sample Sharpe (or any in-sample-only fit score) as a promotion criterion.

### Requirement 5: Autonomous overfitting-corrected promotion gate

**Objective:** As the operator, I want promotion decided autonomously through an overfitting-corrected, multiple-testing-aware gate, so that no human sign-off is required yet a plausible-but-overfit candidate is still rejected (§14.11 #2/#6).

#### Acceptance Criteria
1. The Walk-Forward Tuning Loop shall promote a candidate only when it passes the gate comprising the Deflated Sharpe Ratio (multiple-testing-corrected), the Probabilistic Sharpe Ratio / Minimum Track Record Length significance test against a non-trivial benchmark, and a Probability-of-Backtest-Overfitting diagnostic.
2. The Walk-Forward Tuning Loop shall log the effective number of independent trials used to deflate the gate.
3. The Walk-Forward Tuning Loop shall bound the breadth of its parameter search to the available history (a minimum-backtest-length constraint), and shall reduce correlated parameter sweeps to an effective trial count before applying the gate.
4. If the out-of-sample evidence is statistically insufficient for the candidate's distribution (minimum track record length not met), then the Walk-Forward Tuning Loop shall not promote and shall retain the incumbent.
5. The Walk-Forward Tuning Loop shall require the candidate to beat the incumbent by a configured out-of-sample margin over a configured number of consecutive windows, with configured anti-churn hysteresis (values set provisionally and calibrated empirically).
6. The Walk-Forward Tuning Loop shall promote without human sign-off, and shall remain subject to the operator kill switch and the survival gate at all times (autonomy removes per-promotion approval, not the emergency halt).
7. While the system is in the paper-only phase, the Walk-Forward Tuning Loop shall promote only into the paper/challenger track and shall not enable live real-money routing.

### Requirement 6: Conservatism guard — track gate weights and the §13 ordering

**Objective:** As the operator, I want code changes gated more heavily than parameter fits and the lexicographic ordering preserved, so that the largest-blast-radius change clears the strongest gate and survival is never traded for return (P7/P14/§13).

#### Acceptance Criteria
1. When a structural code/structure version is a promotion candidate, the Walk-Forward Tuning Loop shall require the full inner-ring test suite to pass before promotion, in addition to the out-of-sample gate, the evaluator, and the §13 lexicographic guard.
2. When a parameter version is a promotion candidate, the Walk-Forward Tuning Loop shall require the out-of-sample gate, the evaluator, and the §13 lexicographic guard before promotion.
3. The Walk-Forward Tuning Loop shall not promote a candidate that ranks higher on Edge or Return at the cost of a lower Survive or Preserve score (the lexicographic ordering is never traded).
4. The Walk-Forward Tuning Loop shall not enforce the survival one-way tighten-only guarantee at runtime; that guarantee is owned downstream (survival-gate / execution-daemon).

### Requirement 7: Promotion handoff — write to the parameter-version registry

**Objective:** As the in-session fast clock and the in-session monitor, I want a promoted version published to the shared parameter-version registry, so that the daemon can deploy it and the monitor can select it without the tuner ever deploying anything itself (§14.5/§15).

#### Acceptance Criteria
1. When a candidate passes the gate, the Walk-Forward Tuning Loop shall write the validated, versioned snapshot into the parameter-version registry (P2).
2. The Walk-Forward Tuning Loop shall not deploy, hot-swap, or apply the promoted version; deployment is owned by the execution-daemon and in-session selection by the in-session monitor.
3. The Walk-Forward Tuning Loop shall make the advanced walk-forward window discoverable to downstream consumers alongside the promoted version, such that the execution-daemon re-sources it at its next hot-swap.

### Requirement 8: Tuner-action audit (own surface, falsifiable, correlated)

**Objective:** As the operator and the calibration loop, I want a falsifiable record of why each promotion happened, joinable to the model trace, so that promotion reasoning is auditable and later checkable against outcomes (P11/P15/§14.8).

#### Acceptance Criteria
1. When the Walk-Forward Tuning Loop promotes (or declines to promote) a candidate, it shall emit its own tuner-action audit record stating the gate metrics and the promotion rationale.
2. The Walk-Forward Tuning Loop shall express the promotion rationale as a falsifiable hypothesis with observable falsifiers (P15), and shall express the gate figures as derived metrics, not asserted probabilities.
3. The Walk-Forward Tuning Loop shall tag each audit record with the four correlation keys (run identifier, code version, parameter version, walk-forward window) so it joins to the model trace and the outcome ledger.
4. The Walk-Forward Tuning Loop shall own this audit surface and its validation, separate from the decision-trace telemetry (which owns the model trace only).

### Requirement 9: Operational resilience of the hours-long batch

**Objective:** As the operator, I want the long-running batch to survive a crash and to be dispatched on schedule, so that a mid-fit failure does not lose the run and the trading loop is never coupled to the batch (§14.9).

#### Acceptance Criteria
1. The Walk-Forward Tuning Loop shall checkpoint its progress such that a crash mid-fit can resume without losing the run.
2. The Walk-Forward Tuning Loop shall be dispatched by a scheduler or event queue (not interactively), fired at the walk-forward boundary.
3. The Walk-Forward Tuning Loop shall remain subject to the existing per-`(run_id, agent)` cost ceiling; an aggregate cost ceiling across the batch is not required for v0.1 (T4 / §14.11 #4, accepted eyes-open).

### Requirement 10: Consumption boundary and dependency contracts

**Objective:** As the operator maintaining the cross-spec seams, I want the tuning loop to consume the landed upstream contracts as a reader, so that it never duplicates or owns the trace, ledger, deploy, or selection surfaces (P11).

#### Acceptance Criteria
1. The Walk-Forward Tuning Loop shall read the model trace and the version-attributed outcome ledger through the landed read surface and the four shared correlation keys, and shall not reimplement them.
2. The Walk-Forward Tuning Loop shall consume (drain) the after-market event queue emitted by the execution-daemon, and shall not own the queue's emit side.
3. The Walk-Forward Tuning Loop shall consume the reactive parameter snapshot and the survival parameters as the versioned objects it tunes, and shall not reimplement the softmax/threshold model or the survival decision logic.
4. If a consumed upstream contract changes shape (a correlation key, the parameter snapshot, the survival parameters, or the ledger version dimension), then the Walk-Forward Tuning Loop shall be revalidated against the new shape.
5. When the Walk-Forward Tuning Loop drains a queued anomaly event (e.g. a survival breach or behavior-envelope violation queued in-session for the after-market batch, §14.3), it shall incorporate that event into the behavioral analysis informing the cycle's fit.
