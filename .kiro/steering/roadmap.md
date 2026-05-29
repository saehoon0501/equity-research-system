# Roadmap

## Overview

The reactive CFD execution layer + adaptive walk-forward tuning loop for the equity-research system. A persistent, non-LLM **fast clock** trades a Gate TradFi CFD account at retail latency under a lexicographic **Survive ⊳ Preserve ⊳ Edge ⊳ Return** gate; an asynchronous after-market LLM **slow clock** monitors how that model behaves, fits new params/code, and promotes them via walk-forward window advance.

Full design lives in `docs/exploration-systematic-flow-architecture-2026-05-28.md` §11–§14 (**EXPLORATION** status). This roadmap is the per-feature build-spec layer *below* that strategic record — it does not replace BUILD_LOG.md, phasing-plan.md, or v2-final-spec.md.

## Approach Decision

- **Chosen**: Two-clock decomposition — a non-LLM softmax+threshold inner loop (fast, in-session, hot path) plus an async hours-long LLM outer-loop optimizer (after-market), meeting **only** at the P2 param-version table and the telemetry log.
- **Why**: retail-latency order triggers forbid an LLM in the hot path; multi-hour fits forbid it in-session; the lexicographic value chain (§13) + reactive epistemics (§12) make the inner loop deterministic-valued and the LLM a walk-forward tuner with judgment.
- **Rejected alternatives**: LLM-in-hot-path (latency break); predictive thesis-driven CFD layer (§12 — path risk is the killer at 4x); runtime *fitting* of new values (no out-of-sample intra-session — §14.4).

## Scope

- **In**: Gate CFD execution adapter; account-aware survival gate; reactive softmax signal model; decision-trace telemetry + ledger version dimension; persistent execution daemon; after-market walk-forward tuning loop.
- **Out (v0.1)**: live real-money routing (paper/dry-run only per §11.5); structural LLM self-modification beyond the gated after-market code track; index/multi-asset; anything that relaxes the §13 chain.

## Constraints

Paper-only v0.1 (§11.5). P1 (markdown orchestrates; Python = leaf tools/daemon — the daemon is a leaf executor + event emitter, never an agent dispatcher). P7 (downstream only more conservative). P14 (inner-ring tests before outer-ring scoring). P15 (derived probabilities). §13 lexicographic precedence is invariant. T4 (no aggregate cost cap today — must be added for the tuning batch).

## Boundary Strategy

- **Why this split**: each boundary owns one seam of the two-clock architecture; the survival gate is isolated as the highest-blast-radius node (§11.5) so it can be hardened and inner-ring-proven independently (Survive-first).
- **Shared seams to watch**: the param-version table (P2) between daemon and tuning loop; the telemetry schema between daemon and tuning loop; the version-pinned position lifecycle (§14.5) across daemon ↔ tuning-loop promotions.

## Specs (dependency order)

- [ ] broker-cfd-adapter — Gate TradFi CFD REST adapter (place/positions/assets; leverage + hours + symbol enforcement). Dependencies: none
- [ ] reactive-signal-model — softmax classifier + decision threshold (the Edge link), generalizing `src/micro/signal_model.py`. Dependencies: none
- [ ] decision-trace-telemetry — per-decision **model** trace (process side) + `counterfactual_ledger` model-version dimension (outcome side); owns the shared correlation keys. **MODEL trace only — LLM-action audit owned per-spec** (operator 2026-05-29). Dependencies: none
- [ ] survival-gate — account-aware liquidation/survival gate + sleeve caps + per-order size limit + kill switch (the Survive link). Dependencies: broker-cfd-adapter
- [ ] execution-daemon — persistent fast-clock process: lexicographic gate, version-pinned lifecycle, atomic hot-swap, safe-mode + event queue. Dependencies: broker-cfd-adapter, reactive-signal-model, decision-trace-telemetry, survival-gate
- [ ] walkforward-tuning-loop — async after-market LLM batch: fit → champion/challenger → autonomous walk-forward promote. **Owns its tuner-action audit (P11)** — why a version was promoted (falsifiable hypothesis per P15), correlated to the model trace via shared keys. Dependencies: decision-trace-telemetry, execution-daemon
- [ ] in-session-monitor — scheduled LLM supervisory loop (§15): reads telemetry on a regular in-session cadence, can halt / tighten / select-among-validated-configs (NEVER fits — fitting stays after-market). Commands flow only through existing kill-switch / safe-mode / versioned-config paths; deterministic reflex fires first. **Owns its intervention audit (P11)** — why it halted/tightened/selected a config, correlated via shared keys. Dependencies: decision-trace-telemetry, execution-daemon, walkforward-tuning-loop. *(Placement — own spec vs. folded — confirmed at its own discovery.)*

> Build order: **broker-cfd-adapter, reactive-signal-model, decision-trace-telemetry in parallel → survival-gate → execution-daemon → walkforward-tuning-loop → in-session-monitor.**

## Brief status (foundation-first, operator decision 2026-05-29)

**Five specs now have briefs:** `broker-cfd-adapter`, `survival-gate` (Survive-first foundation), plus `reactive-signal-model` and `decision-trace-telemetry` (the two "Dependencies: none" inner-ring foundation specs — briefed 2026-05-29 once §11–§14 was committed; they are NOT gated by the §14.11 questions) — plus `execution-daemon`, briefed 2026-05-30 (see below). Still un-briefed: `walkforward-tuning-loop` and the new `in-session-monitor` — **now UNBLOCKED.** The §14.11 operator questions are **all resolved (2026-05-29):** #1 version-pinned lifecycle (first-principles target; moot for paper phase per §16.1 intraday-flat), #2 fully-autonomous promotion, #3 no trade-count floor → PSR/MinTRL, #4 no aggregate cost cap, #5 anchored/rolling adopt-and-validate, #6 promotion gate = DSR + PSR + PBO (research-confirmed; see `docs/research-walkforward-tuning-loop-2026-05-29.md`). The remaining two briefs can be discovered next (build order: `walkforward-tuning-loop` → `in-session-monitor`). **`execution-daemon` briefed 2026-05-30** — Path C (single spec); full version-pinned lifecycle + atomic hot-swap IN scope (operator override of the §14.11 #1 "moot-for-paper" default); it claims the previously-floating telemetry row-assembly + `run_id`/`walk_forward_window` injection seam.

**Update 2026-05-29 — broker-cfd-adapter UNBLOCKED.** Was briefly blocked when the Gate TradFi API looked under-specified; the operator then supplied the **full official TradFi API spec**, now captured as `.kiro/specs/broker-cfd-adapter/gate-tradfi-api-reference.md`. `requirements.md` was revised against the verified endpoints/fields (phase `requirements-generated`, awaiting operator approval). Material shape changes vs the first draft: orders are **async** (queue reference, poll for fill), TRIM/SELL are **close-by-position-id** (partial close = TRIM), **leverage is not a per-order param** (exposure via volume), account **activation** is a precheck, **trade_mode** restricts actions, and there is **no native paper mode** (simulate in-adapter). Long+short both in scope (operator-confirmed 2026-05-29; direction comes from the reactive layer per §12.3). How leverage is configured is under a deep-research pass (with the secondary residuals). True residuals (gap/oracle behavior, insolvency/T&C, rate limits, `close_type` semantics) are tracked in `gate-api-gaps.md` and don't block. `survival-gate` is correspondingly unblocked on its account/position-readout dependency (it still carries the gap/oracle + insolvency residuals as its own risk-modeling concerns).
