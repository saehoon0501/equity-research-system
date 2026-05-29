# Requirements Document

## Introduction

The Reactive Signal Model is the **Edge** link of the reactive CFD layer's lexicographic chain (exploration §13). On the fast clock, at a days-to-weeks horizon, it converts deterministic market features into a **calibrated probability** and a **thresholded LONG/SHORT/HOLD decision** that downstream gates can veto and size against. Today the chain has a Survive gate but no Edge link: nothing turns fast-clock features into a thresholded signal. This model fills that gap as a reproducible, non-LLM leaf module (P1), mirroring the established intraday softmax-plus-threshold pattern but anchored to daily bars with daily-ATR horizon scaling.

The directional side (long or short) is **caller-supplied** (§12.3): the reactive layer decides direction, not this model. The model's job is to emit a *calibrated confidence that the caller-supplied direction is the correct side over the days-to-weeks, daily-ATR-anchored horizon*, and to decide, against a tunable threshold, whether that confidence is strong enough to act on. Clearing the threshold is **necessary-but-not-sufficient** (§13): the signal is a candidate Edge that higher links in the chain (Survive, Preserve) can veto downstream; a sub-threshold signal is HOLD (P9). Probability magnitude above the threshold may be surfaced as an advisory sizing hint for the Return layer, but this model never enforces a size or a cap.

Feature substance is reused from the system's existing days-to-weeks deterministic cores rather than recomputed; the fundamental/slow-layer prior is dropped because direction now comes from the reactive layer (the slow layer is veto-only). All probabilities are derived from the model and exposed with their pinned calibration evidence, never asserted (P15). The model **exposes** calibration evidence and the per-decision substrate (feature values and derived probability) from which calibration is later computed; it does not itself compute Brier or reliability — that batch computation over realized outcomes is owned by the after-market tuner (§14.7). The deterministic core is built first as an inner-ring, unit-testable unit (P14): same inputs produce the same outputs in isolation, with no LLM, MCP, or live database.

## Boundary Context

- **In scope**: daily-bar feature computation at a days-to-weeks horizon with daily-ATR anchoring; derivation of a calibrated probability for the caller-supplied direction; the thresholded LONG/SHORT/HOLD decision; an advisory probability-derived sizing-scalar hint; consumption of the active, pinned parameter-snapshot version; honoring a runtime threshold *tightening*; exposure of the calibration evidence carried in the active snapshot and of the per-decision substrate (feature values, derived probability, effective threshold, consumed parameter version) as a first-class output; deterministic, isolatable, fast inner-ring behavior.
- **Out of scope**: threshold and feature *tuning* (owned by `walkforward-tuning-loop` — this model only consumes the active parameter version, it does not fit or compute it); computation of calibration metrics such as Brier and reliability over realized outcomes (owned by `walkforward-tuning-loop`); the Survive/Preserve veto and any survival-state inspection (`survival-gate`); position sizing, sizing-cap enforcement, and the order-trigger decision (`execution-daemon` / Return layer); order routing (`broker-cfd-adapter`); selection of the directional side (the reactive caller supplies it, §12.3); any authority of the Edge signal over higher chain links (§13 — Survive and Preserve precede Edge).
- **Adjacent expectations**: feature substance is reused from the existing `src/overlays/*` days-to-weeks deterministic cores; pure indicator math is reused from `src/micro/indicators.py`; the softmax-plus-threshold *pattern* is reused from `src/micro/signal_model.py`; the live `/micro` intraday model and its intraday-microstructure features (VWAP, session, SPY first-30-min, BVC, opening-range, spread) are left untouched and are not reused; the LLM overlay *agents* are not invoked. Downstream consumers are `execution-daemon` (acts at the Edge step), `decision-trace-telemetry` (logs signal values and probabilities at fire, §14.8), and `walkforward-tuning-loop` (tunes against telemetry and the ledger).

## Requirements

### Requirement 1: Daily-bar feature computation
**Objective:** As the reactive execution layer, I want fast-clock market data reduced to a stable days-to-weeks feature set, so that the Edge decision rests on horizon-appropriate, reproducible signals rather than ad-hoc or intraday noise.

#### Acceptance Criteria
1. When supplied with daily-bar price and volatility history for an instrument, the Reactive Signal Model shall compute its feature set on a days-to-weeks horizon.
2. The Reactive Signal Model shall normalize magnitude-type features (e.g. distance-from-moving-average, drawdown) into daily-ATR units, and shall scale its decision horizon to a daily-ATR-anchored days-to-weeks band, so that feature magnitudes and the horizon are volatility-comparable across regimes. (The reused sub-signal lookback windows retain their canonical fixed lengths; daily-ATR anchors normalization and horizon, not the window lengths — corrected 2026-05-29 to match the confirmed reuse stance.)
3. The Reactive Signal Model shall exclude intraday-microstructure inputs from its feature set.
4. The Reactive Signal Model shall exclude any fundamental or slow-layer prior from its feature set.
5. The Reactive Signal Model shall weight its features with near-equal influence so that no single feature dominates the combined signal.
6. If the supplied history is insufficient to compute the feature set over the required lookback, then the Reactive Signal Model shall emit a decision of HOLD.
7. If the supplied history is insufficient to compute the feature set over the required lookback, then the Reactive Signal Model shall report the insufficiency as the reason for the decision.

### Requirement 2: Calibrated probability derivation
**Objective:** As a downstream consumer, I want a probability that is genuinely derived from the model and checkable, so that confidence figures carry calibration rather than asserted conviction (P15).

#### Acceptance Criteria
1. When the feature set has been computed, the Reactive Signal Model shall derive a probability from those features using the active model parameters.
2. The Reactive Signal Model shall derive every probability it reports from the active model rather than asserting it.
3. The Reactive Signal Model shall report the derived probability as the confidence that the caller-supplied direction is the correct side over the days-to-weeks, daily-ATR-anchored horizon. (This is the *prediction* horizon; the *hold* lifecycle is intraday-flat-by-close — see design §Horizon-semantics and exploration §16.1. The downstream calibration target is therefore the intraday-with-daily-reentry realization, not a days-to-weeks buy-and-hold outcome.)
4. Where calibration evidence is carried in the active parameter snapshot, the Reactive Signal Model shall expose it alongside the derived probability.

### Requirement 3: Thresholded decision and decision vocabulary
**Objective:** As the reactive execution layer, I want a single thresholded act-or-hold decision in the canonical vocabulary, so that the Edge link emits a clear candidate the rest of the chain can act on or reject (P9, §13).

#### Acceptance Criteria
1. The Reactive Signal Model shall accept the directional side as a caller-supplied input.
2. The Reactive Signal Model shall not select the directional side itself.
3. When the derived probability for the caller-supplied direction is strictly greater than the active threshold, the Reactive Signal Model shall emit a decision of LONG or SHORT matching that caller-supplied direction.
4. When the derived probability for the caller-supplied direction is less than or equal to the active threshold, the Reactive Signal Model shall emit a decision of HOLD.
5. The Reactive Signal Model shall emit a decision drawn only from the vocabulary LONG, SHORT, and HOLD.
6. If the caller-supplied direction is missing or is not a valid side, then the Reactive Signal Model shall emit a decision of HOLD and report the invalid-direction reason.
7. When the derived probability clears the active threshold, the Reactive Signal Model shall flag the emitted decision as non-final.

### Requirement 4: Subordination to higher chain links
**Objective:** As the lexicographic chain, I want the Edge signal to remain a vetoable candidate that can only become more conservative downstream, so that Survive and Preserve retain precedence over Edge and the model cannot escalate a decision past them (§13, P7).

#### Acceptance Criteria
1. The Reactive Signal Model shall emit each decision flagged as non-final and subject to veto by any higher link in the lexicographic chain (Survive and Preserve).
2. The Reactive Signal Model shall not inspect, enforce, or override survival state or any higher chain-link state.
3. The Reactive Signal Model shall not escalate or flip the caller-supplied direction; it shall only confirm the caller-supplied direction when the threshold is cleared, or emit HOLD when it is not.

### Requirement 5: Advisory sizing-scalar hint
**Objective:** As the Return layer, I want an advisory hint that scales with how far the probability clears the threshold, so that sizing has a calibrated input without this model owning the size or its cap.

#### Acceptance Criteria
1. When the derived probability clears the active threshold, the Reactive Signal Model shall emit a sizing-scalar hint that increases with the probability magnitude above the threshold.
2. When the decision is HOLD, the Reactive Signal Model shall not emit an actionable sizing-scalar hint.
3. The Reactive Signal Model shall mark the sizing-scalar hint as advisory.
4. The Reactive Signal Model shall not enforce a position size.
5. The Reactive Signal Model shall not apply a sizing cap.

### Requirement 6: Parameter consumption and tighten-only runtime lever
**Objective:** As the operator, I want the model to run only against pinned, versioned parameters and to accept de-risking but not loosening at runtime, so that ground truth is propagated by value and risk can only tighten in-flight (P2, §14.7, P7).

#### Acceptance Criteria
1. When a decision is requested, the Reactive Signal Model shall use the active, pinned parameter-snapshot version supplied for the run.
2. The Reactive Signal Model shall not re-resolve its parameters against live state mid-run.
3. When supplied a runtime threshold that is higher than the snapshot threshold, the Reactive Signal Model shall apply the higher threshold for the decision.
4. If supplied a runtime threshold that is lower than the snapshot threshold, then the Reactive Signal Model shall reject the lower threshold and retain the snapshot threshold.
5. The Reactive Signal Model shall not fit, tune, or compute threshold or feature parameters.

### Requirement 7: Calibration evidence and decision substrate exposure
**Objective:** As the after-market tuner and telemetry consumer, I want the calibration evidence and the per-decision substrate exposed as a first-class output, so that the fire is reconstructable and threshold and feature tuning can be optimized against observed reliability (§14.7, §14.8, P3).

#### Acceptance Criteria
1. The Reactive Signal Model shall expose the calibration evidence carried in the active, pinned parameter snapshot, including a Brier score and a reliability measure, as a first-class output.
2. When emitting a decision, the Reactive Signal Model shall make available the feature values and the derived probability associated with that decision.
3. When emitting a decision, the Reactive Signal Model shall make available the effective decision threshold actually applied and the parameter-snapshot version consumed.
4. The Reactive Signal Model shall not compute calibration metrics over realized outcomes; that computation is owned by the after-market tuning loop.

### Requirement 8: Deterministic, isolatable core
**Objective:** As a developer, I want the core to be reproducible and testable in isolation, so that it forms a reliable inner-ring foundation before any outer-ring scoring is wired against it (P1, P14).

#### Acceptance Criteria
1. When given identical inputs and the same parameter snapshot, the Reactive Signal Model shall produce identical features, probability, decision, sizing-scalar hint, and exposed calibration evidence.
2. The Reactive Signal Model shall produce its outputs without invoking an LLM, an MCP server, or a live database.
3. The Reactive Signal Model shall remain executable as an isolated leaf unit and shall not orchestrate or dispatch other components.
