# Brief: survival-gate

## Problem

At 4x leverage with a −10% to −12.5% worst-case stop-out distance and **cross-margin (account-level) liquidation**, an unmanaged levered book gets liquidated. Survival is the top of the lexicographic chain (§13) — if it fails, nothing below it exists. This is the **highest-blast-radius node in the repo** (§11.5).

## Current State

No survival gate exists. §11.3 verified: Gate CFD liquidation = MT5 stop-out at margin level ≤ 50%, cross-margin only (no isolated), so true liquidation distance is **account-level** (equity vs aggregate used margin), not a fixed per-position %. Worst case (zero free-margin buffer): −12.5% @4x, −10% @5x. §11.5 names the required apparatus (survival gate · sleeve caps · per-order size limit · kill switch) as blocking and pre-build.

## Desired Outcome

A mandatory, account-aware blocking gate upstream of every order that: computes account-level liquidation distance (equity vs aggregate used margin), enforces sleeve caps (core ≤80% / thematic ≤25% / speculative ≤8%) and per-order size limits, and exposes a kill switch — **rejecting (never upsizing)** anything that threatens Survive. Per §16 (operator 2026-05-29), the `speculative_optionality` cap is also enforced at **capitalization**: the Gate account is funded with at most the sleeve's dollars (≤8% of book), so the **funded balance is the account-level defined-risk envelope** — substituting for instrument-level defined risk, since a Gate CFD has **no negative-balance protection**.

## Approach

A deterministic **hard-rule** gate — no softmax (§14.7: you don't "probably" dodge liquidation; it's a margin-distance test). Account-aware: models account equity vs aggregate used margin (cross-margin), not a fixed per-position percentage. One-way **tighten only** (P7). Lexicographic: Survive is evaluated **before** Edge and can veto any signal regardless of softmax probability (§13). Runtime survival-tighten is auto-applied; loosening survival params is after-market gated only (§14.4). On breach it drives a reproducible **safe-mode** (tighten / flatten / halt-new-entries) and queues the anomaly event for the after-market batch (§14.3).

## Scope

- **In**: account-level liquidation-distance / margin-level computation; sleeve-cap enforcement; per-order size limit; kill switch; safe-mode state machine + anomaly event queue; **flat-before-closure invariant** (force-flatten levered exposure ahead of any market closure — §16.1).
- **Out**: the order trigger itself (daemon); the Edge signal (reactive-signal-model); broker transport (broker-cfd-adapter); walk-forward tuning of survival params (tuning-loop — this spec only *consumes* the active param version).

## Boundary Candidates

- Liquidation-distance / margin-level model (account-aware)
- Sleeve-cap + per-order-size enforcement
- Kill switch + safe-mode state machine

## Out of Boundary

- Edge / Return decisions (threshold-clearing is necessary-but-not-sufficient and sits downstream of Survive)
- Anchored fitting of survival params (tuning-loop owns the fit; this gate cannot loosen at runtime)

## Upstream / Downstream

- **Upstream**: broker-cfd-adapter (account assets + open positions readout).
- **Downstream**: execution-daemon (the gate sits in the hot path at the top of the lexicographic walk); walkforward-tuning-loop (tunes survival params anchored, but can never loosen them at runtime).

## Existing Spec Touchpoints

- **Extends**: none (new). Reuses the sleeve-cap concept from `pm-supervisor` (CLAUDE.md) — must share the same caps vocabulary (P9), not a parallel table.
- **Adjacent**: the `src/eval/gates/` HG-validator pattern (this gate gets its own HG validator per P11).

## Constraints

Highest blast radius (§11.5) — must be proven green on the inner ring (P14) before any live cutover. Cross-margin ⟹ account-level, not per-trade. P7 (only ever tightens). §13 (Survive precedence; lexicographic; never traded for any amount of Return). Survival params fit **anchored** — all history, never forget a tail / gap / stop-out (§14.6). The kill switch is retained even under full-autonomous promotion (§14.11 #2 — "no sign-off" removes per-promotion approval, not the emergency halt). **No negative-balance protection** (research 2026-05-29 — Gate CFDs can "lose more than invested"; plausibly unsecured-creditor / offshore): the gate must assume NO NBP, treat the §16 funding cap as the primary structural loss bound, and treat the **gap-through-stop** risk as CONFIRMED and effectively unbounded (deep-research 2026-05-29, `gap-through-stop-findings-2026-05-29.md`): the 50%-margin-level stop-out is **non-guaranteed** (fills at next-available bid/ask on a reopen gap), there is **no GSLO / no max-loss cap**, and leverage is fixed (not user-reducible). ⟹ the survival model must NOT assume the stop holds; the **§16 funding cap is the only hard loss bound**. **Flat-before-closure is therefore a HARD survival invariant** (operator decision 2026-05-29, §16.1 — *C-now / B-pre-live*): **no levered exposure may be held across any non-traded window** (overnight / weekend / holiday); this gate **force-flattens before close** — not merely "reduces" — which *operationally* eliminates the dominant (closure-gap) unbounded path (**procedural** — conditional on the flatten reliably firing; **not** structural the way a spread is). Per **P6**, this invariant cannot reduce to a bare timed order: the gate needs a **verifiable pre-close post-condition — *am I actually flat?*, not "I fired the order"** — plus a fallback (re-fire / kill-switch / safe-mode) if it is not; the timed flatten *action* itself lives in `execution-daemon` (rule here, trigger there), and a broker-side resting/bracket exit or time-based auto-close — if the MT5/CFD product supports it — would push this back toward *structural* (survives daemon death); to verify against `broker-cfd-adapter`. The standing residual is the **bounded-but-nonzero intraday-halt-reopen** case, addressed by consuming the **`gap-risk-veto-filter`** (name-specific forward gap-sight: earnings/halt/going-concern proximity, §12.2/§12.3). Under §13 this is a small, named, **paper-only relaxation**, not compliance: the Gate CFD vehicle is **provisional-for-paper** and the survival model must **not assume it survives the pre-live gate** — **defined-risk instruments (spreads/LEAPs, structurally gap-proof) are the pre-live target (B)** if the User Agreement confirms no-GSLO/no-cap. Pre-live: the Gate TradFi User Agreement (403, unretrieved) must be read to confirm/deny a GSLO + the `fill_negative` clawback mechanics before any real-money cutover.
