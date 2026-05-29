# Brief: reactive-signal-model

## Problem

The reactive CFD layer (exploration §12–§14) needs a reproducible, non-LLM way to decide the **Edge** — is the system on the right side, and with what *calibrated* confidence — on the fast clock at a days-to-weeks horizon. Without it the lexicographic chain (§13) has a Survive gate but no Edge link to gate entries: nothing converts fast-clock features into a thresholded LONG/SHORT/HOLD signal that Survive can veto and Return can size against.

## Current State

The deterministic features this model needs **already exist as pure, P14-tested code** — this is reuse, not greenfield:
- **`src/overlays/*/bin_classifier.py`** — the overlays' deterministic cores (TSMOM, MA-distance 50/200, Donchian, Antonacci dual-momentum, drawdown-252d, Wilder-RSI, Bollinger, MA200-distance, relative-strength), **already days-to-weeks/months horizon** — the natural primary feature source.
- **`src/micro/indicators.py`** — horizon-agnostic pure math (RSI / MACD / ATR / Bollinger / EMA).
- **`src/micro/signal_model.py`** — a pure softmax-3 + threshold for the INTRADAY layer; the **pattern** to reuse, but its intraday-microstructure features (VWAP, session, SPY first-30min, BVC, opening-range, spread) do **not** transfer to days-to-weeks.

The LLM overlay **agents** (`.claude/agents/overlays/`) are slow-clock and cannot run in the hot loop — this model reuses their deterministic `src/` cores, **not** the agents. No days-to-weeks reactive signal model exists yet.

## Desired Outcome

A reproducible, non-LLM leaf module (mirroring `src/micro/signal_model.py`) that, given fast-clock features, emits a **calibrated softmax probability** + a **thresholded decision** (the Edge link of §13). Clearing the threshold is **necessary-but-not-sufficient**: Survive can veto any signal (§14.7); sub-threshold = HOLD (P9). Probability magnitude above threshold may scale Return-layer sizing (Survive-capped). Calibration (Brier / reliability) is a first-class diagnostic the after-market tuner optimizes against.

## Approach

A new `src/reactive/` leaf module (**sibling to `/micro`, leaving it untouched**) that **reuses the existing pure feature functions** rather than recomputing (operator-confirmed 2026-05-29): the feature *substance* comes from the **`src/overlays/*` deterministic cores** (already the right horizon), the *math* from `src/micro/indicators.py`, and the **softmax+threshold pattern** from `signal_model.py` — but **not** `/micro`'s intraday-microstructure features. Features compute on **daily bars with daily-ATR horizon anchoring** (the intraday seed anchors by √(horizon/bar); same idea, daily unit). The **fundamental/slow-layer prior is dropped** — per §12.3 the directional side comes from the reactive features, not fundamentals (slow layer is veto-only). Softmax over a small, **near-equal-weighted** feature set (anti-overfit, DeMiguel) → calibrated probability per direction; a tunable threshold gates the decision. The threshold is the **canonical tunable AND the runtime tighten-only lever** (§14.7, P7): raise → fewer / higher-conviction entries (runtime auto-apply); lower → after-market gated fit only. Probabilities are derived (P15) and calibration-checked.

## Scope

- **In**: a `src/reactive/` module that reuses the `src/overlays/*` deterministic cores + `src/micro/indicators.py` math + the softmax/threshold pattern; daily-bar feature computation with daily-ATR anchoring; the calibrated probability output; the LONG/SHORT/HOLD decision (P9-aligned; direction caller-supplied per §12.3); a Survive-capped sizing-scalar hint; inner-ring unit tests (P14) for the deterministic core.
- **Out**: threshold/feature TUNING (owned by `walkforward-tuning-loop` — this spec only *consumes* the active param version); the Survive veto (`survival-gate`); sizing enforcement and order-trigger (daemon / Return layer); order routing (`broker-cfd-adapter`); any authority of the directional side over Survive (§13 — Survive precedes Edge).

## Boundary Candidates

- The feature set + computation
- The softmax + threshold core
- The calibration-metric surface (Brier / reliability) as a diagnostic output

## Out of Boundary

- Parameter fitting / threshold tuning (`walkforward-tuning-loop`)
- The lexicographic Survive gate (`survival-gate`)
- Any LLM in the hot path (§14.1)

## Upstream / Downstream

- **Upstream**: fast-clock market data (price / vol); the active `(code_version, param_version)` snapshot (P2).
- **Downstream**: `execution-daemon` (consumes the thresholded decision + probability at the Edge step of the lexicographic walk); `decision-trace-telemetry` (logs signal values + softmax probs at fire, §14.8); `walkforward-tuning-loop` (tunes threshold/features, anchored on telemetry + ledger).

## Existing Spec Touchpoints

- **Extends / reuses**: primary feature source = the **`src/overlays/*` deterministic cores** (TSMOM / drawdown / MA / Donchian / Antonacci / RSI / Bollinger / RS — already days-to-weeks); borrows the **pure indicator math** (`src/micro/indicators.py`) and the **softmax+threshold pattern** (`src/micro/signal_model.py`).
- **Adjacent**: leaves the live `/micro` intraday model **untouched** (sibling `src/reactive/` module, no refactor); does **not** reuse `/micro`'s intraday-microstructure features or its slow-layer prior; does **not** consume the LLM overlay *agents* (only their `src/` deterministic cores).

## Constraints

P1 (leaf `src/` module, not an orchestrator). P14 (inner-ring unit tests first — deterministic, <1s, no LLM/MCP/live-DB; build before any outer-ring scoring). P15 (softmax probabilities derived + calibration-checked, never asserted). §13 (Edge is below Survive — threshold-clear is necessary-but-not-sufficient; Survive vetoes; sub-threshold = HOLD). §14.7 (threshold = canonical tunable + runtime tighten-only lever; calibration is a primary behavioral diagnostic). Reproducible **non-LLM** — the latency (§14.1) and fitting-vs-applying (§14.4) arguments ride on this.
