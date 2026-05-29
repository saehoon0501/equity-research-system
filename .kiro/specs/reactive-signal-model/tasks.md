# Implementation Plan

> **Scope: Phase 1 (inner ring) only.** Per `design.md`, this builds the pure, deterministic leaf module — data contracts + pinned parameters + the daily-bar feature adapter + the probability/decision pipeline + inner-ring unit tests — runnable against **synthetic daily bars on module-constant `DEFAULTS`**, with **no LLM / MCP / live DB** (P14, R8). **Out of scope for this spec's tasks:** market-data fetch (caller-side); the `execution-daemon` wiring that assembles the `DecisionTraceRow`, injects `run_id` + `walk_forward_window`, and persists the trace (`decision-trace-telemetry`, already landed); and the `walkforward-tuning-loop` that fits `weights`/`temperature`/`threshold` and computes calibration metrics (Brier / reliability) over realized outcomes. The reused cores (`src/overlays/*`, `src/micro/indicators.py`) already exist — no build task; the reversion core's missing inner-ring coverage is folded into the feature-adapter tests (P14).

- [ ] 1. Foundation: data contracts and pinned parameters
- [x] 1.1 Define the decision contracts and fixed vocabularies
  - The daily-bar input bar shape (OHLCV); the caller-supplied direction (LONG/SHORT) and the decision vocabulary (LONG/SHORT/HOLD); the failure-reason vocabulary (insufficient_history, invalid_direction, degenerate_features); the reactive-decision output (decision, echoed direction, probability, advisory sizing-scalar hint, non-final flag, optional reason, decision substrate).
  - The decision substrate (feature values, probability, effective threshold, code version, parameter-snapshot version, calibration evidence) and the calibration-evidence shape (a Brier score and a reliability measure).
  - Observable: the full set of typed contracts imports cleanly and type-checks; the decision and failure-reason vocabularies equal the design's fixed literals; the reactive-decision object exposes the non-final flag, the advisory sizing-hint field, and an inspectable substrate.
  - _Requirements: 2, 3, 4, 5, 7, 8_
- [x] 1.2 Define the pinned parameter snapshot, defaults, and the tighten-only threshold resolver
  - The frozen, by-value parameter snapshot (near-equal weights normalized to Σ=1, temperature, threshold, carried calibration evidence, code version, parameter-snapshot version); module-constant defaults for the inner ring with calibration evidence unestablished (None); a tighten-only effective-threshold resolver that returns the higher of the snapshot threshold and any runtime override and never returns below the snapshot threshold.
  - The model consumes the snapshot by value, never re-resolves it against live state mid-run, and never fits/tunes/computes parameters (calibration is exposed, never computed here).
  - Observable: the defaults instantiate frozen with every field present and calibration evidence None; a higher runtime threshold returns the higher value while a lower runtime threshold returns the snapshot threshold unchanged.
  - _Requirements: 2, 6_
  - _Depends: 1.1_

- [ ] 2. Core: feature adapter and probability/decision pipeline
- [x] 2.1 (P) Build the daily-bar feature adapter
  - Reduce supplied daily-bar history (plus SPY close and the risk-free yield) to the days-to-weeks family votes by importing the existing tactical / flow / reversion overlay cores + the ATR indicator and mapping each core's output to a signed directional vote in [−1, +1] under the documented sign convention: tactical bin → ±1/0; flow composite passed through; reversion **oversold → +1 and overbought → −1** (the contrarian sign); any unavailable core → 0 (abstain).
  - ATR-normalize magnitude features and expose the raw component values for the substrate; exclude intraday-microstructure and fundamental/slow-layer inputs by construction; own the history-length and ATR-computability checks, returning a typed feature-failure (insufficient_history / degenerate_features) and never raising.
  - Observable: given synthetic daily bars the adapter returns family votes in [−1, +1] with trend-strength = |flow vote| in [0, 1] and a populated raw-values map; a too-short history returns the insufficient-history failure rather than raising.
  - _Requirements: 1_
  - _Boundary: features_
  - _Depends: 1.1_
- [x] 2.2 Aggregate the family votes and project onto the caller direction
  - Combine the votes into a directional score with near-equal normalized weights (Σ=1) and the mean-reversion term dampened by trend strength (`s = w_t·trend + w_f·flow + w_m·(meanrev·(1−trend_strength))`), keeping the score in [−1, +1]; project onto the caller-supplied direction (signed = s for LONG, −s for SHORT). The model accepts but never selects or flips the direction.
  - Observable: aligned families produce a decisive score while a cross-family conflict that survives damping produces s≈0; with synthetic votes the projection sign follows the caller direction.
  - _Requirements: 1, 3_
  - _Boundary: signal_model_
  - _Depends: 2.1, 1.2_
- [ ] 2.3 Derive the probability and expose the snapshot's calibration evidence
  - Derive the probability that the caller-supplied direction is the correct side from the projected score via the temperature-scaled 2-class logistic (`P = 1/(1+exp(−signed/temperature))`) — a model-derived score, monotonic in the projection, never asserted; the reference intraday hold-logit is deliberately dropped so HOLD comes only from the threshold, never from a probability term.
  - Expose the calibration evidence carried in the active snapshot (Brier + reliability) alongside the probability; never compute calibration metrics here.
  - Observable: a positive projection yields P > 0.5 and a negative projection P < 0.5, monotonic in the score; the exposed calibration evidence equals the snapshot's (None under defaults).
  - _Requirements: 2, 7_
  - _Boundary: signal_model_
  - _Depends: 2.2_
- [ ] 2.4 Emit the thresholded decision with sizing hint, non-final flag, and substrate
  - Apply the tighten-only effective threshold: when the probability strictly exceeds it, emit LONG/SHORT matching the caller direction, otherwise HOLD; map a missing/invalid direction to HOLD with the invalid-direction reason, and any feature-failure to HOLD with its reason (trusting the discriminator — no re-check of history/ATR); flag every decision non-final (vetoable; never escalates or flips the direction).
  - Emit an advisory sizing-scalar hint that increases with probability above the threshold and is absent / non-actionable on HOLD, enforcing no position size and no cap; assemble the decision substrate (feature values, probability, effective threshold, consumed parameter-snapshot version, calibration evidence).
  - Observable: P above the (tighten-only) threshold yields LONG/SHORT = direction with the non-final flag and an increasing sizing hint; P at/below yields HOLD with no actionable hint; an invalid direction and a feature-failure each yield HOLD with the matching reason; the substrate carries the effective threshold and the consumed version.
  - _Requirements: 1, 3, 4, 5, 6, 7_
  - _Boundary: signal_model_
  - _Depends: 2.3_

- [ ] 3. Validation: inner-ring unit tests
- [ ] 3.1 (P) Parameter tests
  - Defaults instantiate complete and frozen with calibration evidence None; the tighten-only resolver applies a higher runtime threshold and rejects a lower one (retaining the snapshot threshold); weights are normalized (Σ=1); determinism on identical inputs.
  - Observable: the suite passes with no LLM, MCP, or live-database access; the tighten-only higher-applied and lower-rejected cases are explicitly asserted.
  - _Requirements: 6, 8_
  - _Boundary: tests_
  - _Depends: 1.2_
- [ ] 3.2 (P) Feature-adapter tests
  - Core→vote mapping including the reversion **sign-mirror** (oversold → +1, overbought → −1 — guards against inversion); ATR normalization of magnitude features; trend-strength = |flow vote|; the insufficient-history and degenerate/zero-ATR failures; unavailable-core abstain (→ 0); exclusion of intraday/fundamental inputs; **coverage of the reused reversion core's exercised paths** (it lacks its own inner ring — P14) before any outer-ring scoring is wired against this model.
  - Observable: the suite passes; the reversion sign-mirror and the insufficient-history-failure cases are explicitly asserted.
  - _Requirements: 1, 8_
  - _Boundary: tests_
  - _Depends: 2.1_
- [ ] 3.3 (P) Signal-model tests
  - Aggregation with Σ=1 weights + trend-strength damping + conflict → s≈0 → HOLD; logistic-probability monotonicity; the thresholded decision (P > θ → LONG/SHORT, P ≤ θ → HOLD) under the tighten-only effective threshold; the advisory sizing hint increasing above θ and absent on HOLD; the non-final flag always set and the direction never flipped; invalid-direction → HOLD+reason and feature-failure → HOLD+reason; the substrate carrying feature values / probability / effective threshold / version / calibration; determinism on identical inputs; no LLM/MCP/DB.
  - Observable: the suite passes; the tighten-only threshold, conflict → HOLD, invalid-direction → HOLD, and determinism cases are explicitly asserted.
  - _Requirements: 2, 3, 4, 5, 6, 7, 8_
  - _Boundary: tests_
  - _Depends: 2.4_

## Implementation Notes
- 2.1: `compute_features`'s "never-raise" guarantee is **domain-scoped** to the design's stated failure-ownership (history-length + ATR-computability + ticker-`Bar` key validation). It can still raise on inputs outside the positive-daily-adj-close domain — a `None` inside `spy_close` (TypeError; Gate-0 validates ticker bars only) or a `0.0` close at the −252 anchor with nonzero high/low (ZeroDivisionError in 12mo-return math). Reviewer-flagged, non-blocking (real adj-close is strictly positive). The Phase-2 `execution-daemon` caller should sanitize market-data inputs, or a hardening task can extend the Gate-0 guard to `spy_close` / non-positive anchors.
- 2.1: reused cores consume **adj-close lists, not bars** — `compute_features` derives the close list via `indicators.closes(ticker_bars)` and feeds bars only to `indicators.atr`. All three cores gate at 252 = LONGEST_WINDOW, so flow/reversion `unavailable` is unreachable past the global insufficient-history gate (only tactical `rf_yield=None` abstain is reachable). `FeatureSet` lives in `features.py` (the internal features→signal_model contract), not `types.py`.
