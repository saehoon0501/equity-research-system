# Brief: decision-trace-telemetry

## Problem

The after-market tuner (`walkforward-tuning-loop`) and the in-session monitor (§15) must analyze **how the model behaves**, not just its P&L. Without a structured, replayable per-decision trace the tuner is "P&L-staring" (§14.8) and cannot diagnose calibration drift, slippage, or near-misses. And without a model-version dimension on the outcome ledger, forward P&L cannot be attributed per-version-per-window — making walk-forward promotion unscoreable and opening a temporal-leakage hazard (§14.6).

## Current State

`counterfactual_ledger` exists (`db/migrations/003`, `011`, `030`) and scores the final 4-bin label (P9 vocabulary) vs sector-ETF-excess returns at 90d / 1y / 3y / 5y (P14 outer ring). It has **no model-version dimension** and **no per-decision process trace**. The reactive CFD layer has no telemetry at all yet. Verified (2026-05-29): the ledger is **append-only** (trigger `counterfactual_ledger_no_modify` blocks DELETE, allows UPDATE only on window-closure fields); `counterfactual_retrievals` (mig 011) already carries a `parameters_version` UUID — precedent for a version column; migrations are idempotent expand-then-contract with no down-migrations; **next free migration number is 048**.

## Desired Outcome

Two complementary surfaces: (1) a per-decision **process trace** (replayable) capturing which lexicographic gate link triggered, signal values + softmax probabilities at fire, expected-vs-actual fill / slippage (§11.4 counterparty prices, not mid), liquidation proximity, stop-outs, and **declined / missed entries** (§14.8); and (2) a **model-version dimension** on `counterfactual_ledger` so forward P&L attributes per-`(code_version, param_version)`-per-walk-forward-window (§14.6) — added **additively** without breaking existing 4-bin scoring.

## Approach

Process trace → a **single append-only Postgres table** `decision_process_trace` (operator-chosen 2026-05-29). Schema: a few **typed identity/version columns** — `trace_id, run_id, decision_ts, code_version, param_version, walk_forward_window` — plus **one JSONB `trace` blob** holding the rest (which lexicographic gate link triggered, signal values + softmax probability at fire, expected-vs-actual fill / slippage, liquidation proximity, stop-outs, declined/missed entries, §14.8). Written directly by the daemon (§14.10 — daemon speaks DB directly, not MCP). **Trade-off accepted:** simplest schema + one write path, at the cost of native indexability on hot fields — mitigated where needed by **JSONB expression indexes**; `code_version/param_version/walk_forward_window` stay typed so the §14.6 temporal-firewall (per-version-per-window) attribution is queryable. Outcome → extend `counterfactual_ledger` with nullable `(code_version, param_version, walk_forward_window)` columns via an **additive** migration (next free number **048**; idempotent expand-then-contract; the append-only trigger updated to keep the new columns out of the immutability identity-check; preserves existing 4-bin scoring per the don't-break-eval-loop rule). The trace is the *process* side; the ledger is the *outcome* side.

## Scope

- **In**: the per-decision **model** trace schema + append-only persistence; the `counterfactual_ledger` model-version migration; the read surface the tuner + in-session monitor consume; **the shared correlation keys** (`run_id, code_version, param_version, walk_forward_window`, P3) that the per-spec LLM-action audits join against — this spec is the canonical model-trace those audits correlate to.
- **Out**: the analysis / tuning itself (`walkforward-tuning-loop`); the in-session monitoring logic (in-session monitor spec, §15); **the LLM-action / reasoning audit** — the *why* of tuner promotions + monitor interventions is owned **per-spec** by those components (P11), NOT folded here (operator decision 2026-05-29); the emission CALLS (the daemon emits — this spec defines the schema + write path, the daemon invokes it); the 4-bin outcome scoring logic (existing eval loop, extended-only here).

## Boundary Candidates

- The decision-trace schema + append-only writer
- The `counterfactual_ledger` version-dimension migration
- The replay / read query surface

## Out of Boundary

- Tuning / analysis (`walkforward-tuning-loop`)
- In-session anomaly judgment (in-session monitor)
- The existing 4-bin scoring (extend-only, don't reimplement)
- **The LLM-action / reasoning audit** — this spec is the *model* trace; the *why* of LLM tuner/monitor decisions is owned by those specs (P11), correlated here only via the shared keys (operator decision 2026-05-29)

## Upstream / Downstream

- **Upstream**: the `execution-daemon` (emits a trace row per decision); the active `(code_version, param_version)` (P2).
- **Downstream**: `walkforward-tuning-loop` (reads trace + version-attributed ledger; the temporal firewall depends on the version + window dimension, §14.6); the in-session monitor (reads recent trace for behavioral / anomaly judgment, §15); the existing eval loop (continues scoring the 4-bin label, now version-aware).

## Existing Spec Touchpoints

- **Extends**: `counterfactual_ledger` (mig 003/011/030) — additive version dimension; must not break existing 4-bin sector-ETF-excess scoring (P14 outer ring).
- **Adjacent**: the daemon's emission seam (this spec owns the schema + write path; the daemon owns the calls); P4 (persist between stages — DB rows here, not in-context).

## Constraints

P4 (persist via DB rows, never in-context handoff; append-only). P14 (the schema + migration are inner-ring; the version dimension is what makes the OUTER ring scoreable per-version — build the trace before wiring version-attributed scoring; don't break existing scoring). P1 (the writer is a leaf; the daemon is a leaf executor — no orchestration here). §14.6 (model-version dimension + temporal firewall — the tuner sees telemetry only up to the IS boundary). §14.8 (the trace is the process side; `counterfactual_ledger` is the outcome side). Don't add fields "later" — the schema is load-bearing for the tuner (cf. the Evidence-Index "don't" in CLAUDE.md).
