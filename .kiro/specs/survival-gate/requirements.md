# Requirements Document

## Introduction

The Survival Gate is a mandatory, account-aware, deterministic hard-rule gate at the top of the reactive CFD layer's lexicographic value chain (exploration §13: **Survive ⊳ Preserve ⊳ Edge ⊳ Return**). It sits upstream of every order on a levered Gate TradFi book (fixed ~5x, **cross-margin**, account-level liquidation at margin level ≤ 50%, **no negative-balance protection**) and exists to keep the account alive: nothing below Survive in the chain is allowed to matter until the gate says yes. It is the **highest-blast-radius node in the repo** (§11.5) and is blocking + pre-build.

Per the **C-now / B-pre-live** decision (§16.1), the Gate CFD vehicle is **provisional-for-paper**: the gate must not assume the vehicle survives the pre-live gate (defined-risk instruments are the pre-live target if the Gate User Agreement confirms no-GSLO / no-cap). The gate must be proven green on the inner ring (P14) before any live cutover.

## Boundary Context

- **In scope**: account-level liquidation-distance / margin-level computation; the mandatory pre-order blocking decision (reject / reduce, never upsize); sleeve-cap + capitalization (funding-cap) enforcement; per-order size limit; a mandatory per-order protective stop-loss; entry eligibility (hard universe restriction + a toggleable ex-ante exclusion stage); the flat-before-closure invariant with a verifiable post-condition; the safe-mode state machine + anomaly queue; the kill switch; consumption of pinned survival parameters; deterministic, isolatable decision logic.
- **Out of scope**: the order *trigger* itself (execution-daemon); the timed flatten *action* (execution-daemon — the gate owns the *invariant + verification + escalation*, not the cron); the Edge signal (reactive-signal-model); broker transport / order placement (broker-cfd-adapter); fitting / tuning / computation of survival or calibration parameters (walkforward-tuning-loop); the core/thematic sleeve allocation across the whole book (slow layer — the Gate account *is* the speculative sleeve, §16.1); **real-time per-instrument trading-halt detection** (operator decision 2026-05-29 — no feed exists; `broker-cfd-adapter` confirmed NOT the source, `c79738f`). Survival-gate neither senses nor responds in real time to an intraday halt on a held name; the intraday-halt/reopen residual is an **accepted, eyes-open** tail bounded by the continuous account-level margin monitor + venue stop-out + the §16 funding cap (Requirement 7).
- **Adjacent expectations**: it consumes existing screens (`catalyst-scout` event proximity + the quality gate's distress metrics) for the exclusion stage — it does not build a new gap-risk screen; it reads account assets + open positions from `broker-cfd-adapter`; it consumes the active survival parameters pinned by the run, and emits anomaly events to the after-market batch.
- **Known limitation (eyes-open)**: a protective stop-loss bounds **normal-case** adverse moves only — it is **non-guaranteed through gaps** (gap-through-stop finding, `gap-through-stop-findings-2026-05-29.md`): on a halted-name reopen gap it fills *beyond* the stop. Gap-tail protection therefore comes from the flat-before-closure invariant (closure gaps), the ex-ante entry exclusion + universe restriction (base-rate reduction), the continuous account-level margin monitor + venue stop-out, and the **§16 funding cap** — never from the stop-loss alone. The **intraday-halt/reopen** tail (a held name halts mid-session and reopens *before* any closure) is **not** covered by the closure-keyed flat-before-closure invariant and — with real-time halt detection out of scope (Requirement 7) — is an accepted residual bounded only by the account-level stop-out + §16 funding cap.

## Requirements

### Requirement 1: Account-aware liquidation-distance model

**Objective:** As the operator of a cross-margin levered account, I want the gate to reason about survival at the account level, so that liquidation risk is measured against the real (account-wide) threshold rather than a misleading per-position percentage.

#### Acceptance Criteria
1. The Survival Gate shall compute account margin level as account equity divided by aggregate used margin (cross-margin, account-level), not as a fixed per-position distance.
2. The Survival Gate shall treat the configured stop-out margin level (≤ 50%, from the active parameters) as the liquidation threshold.
3. The Survival Gate shall maintain a configured safe-mode margin buffer strictly above the stop-out threshold.
4. The Survival Gate shall treat the §16 funding cap (the funded balance), not any stop-loss distance, as the hard account-level loss bound for its survival computations.
5. While the account margin level is at or below the safe-mode buffer, the Survival Gate shall enter safe-mode (Requirement 8).

### Requirement 2: Mandatory pre-order blocking, lexicographic and tighten-only

**Objective:** As the reactive execution layer, I want every order screened by Survive before anything else, so that no Edge or Return consideration can ever route an order that threatens survival (§13, P7).

#### Acceptance Criteria
1. The Survival Gate shall evaluate every proposed order before it is routed.
2. If a proposed order would violate any survival constraint, then the Survival Gate shall reject it.
3. The Survival Gate shall only ever reject a proposed order or require it reduced; it shall never increase the size of a proposed order.
4. The Survival Gate shall evaluate survival constraints before any Edge or Return consideration; an order that has cleared downstream conviction or sizing shall still be rejected when it violates a survival constraint.
5. The Survival Gate shall not loosen any survival constraint at runtime; a runtime adjustment shall be applied only when it tightens.

### Requirement 3: Sleeve cap and capitalization (funding-cap) enforcement

**Objective:** As the operator, I want the speculative sleeve enforced at the account-funding level, so that the funded balance is the account-level defined-risk envelope that substitutes for instrument-level defined risk.

#### Acceptance Criteria
1. The Survival Gate shall enforce that the Gate account's funded balance does not exceed the speculative-sleeve cap (≤ 8%) of total book equity.
2. If a proposed order would cause aggregate account exposure to exceed the speculative-sleeve cap, then the Survival Gate shall reject it.
3. The Survival Gate shall use the shared sleeve-cap vocabulary (core / thematic / speculative) without introducing a parallel definition.
4. The Survival Gate shall not manage core or thematic allocation across the whole book; those sit with the slow layer.

### Requirement 4: Per-order size limit and mandatory protective stop-loss

**Objective:** As the operator, I want every position to carry an order-level loss bound, so that the normal-case downside of each position is defined at entry.

#### Acceptance Criteria
1. If a proposed order exceeds the configured per-order size limit, then the Survival Gate shall reject it (or require it reduced to the limit).
2. The Survival Gate shall require every order to specify a protective stop-loss at entry.
3. If a proposed order cannot attach a protective stop-loss, then the Survival Gate shall reject it.
4. The Survival Gate shall not treat the protective stop-loss as protection against a reopen-gap; the stop-loss is necessary-but-not-sufficient and does not relax any other survival constraint.

### Requirement 5: Entry eligibility — universe restriction and toggleable exclusion stage

**Objective:** As the operator, I want entries restricted to a low-base-rate universe with an optional event/distress screen, so that the catastrophic gap base rate is removed while the screen's value remains measurable.

#### Acceptance Criteria
1. If a proposed entry names an instrument outside the S&P 500 ∩ Gate-441 universe, then the Survival Gate shall reject it.
2. Where the ex-ante exclusion stage is enabled, if a proposed entry names an instrument flagged by the consumed screens (event proximity or distress), then the Survival Gate shall reject the entry.
3. The Survival Gate shall consume existing screens for the exclusion stage and shall not compute its own gap-risk screen.
4. The Survival Gate shall allow the ex-ante exclusion stage to be enabled or disabled independently, without affecting any other survival constraint.

### Requirement 6: Flat-before-closure invariant

**Objective:** As the operator, I want no levered exposure carried across any market closure, so that the dominant (closure-gap) unbounded path is removed for tradable names.

#### Acceptance Criteria
1. The Survival Gate shall require that no levered exposure is held across any market closure (overnight, weekend, or holiday).
2. Before each market closure, the Survival Gate shall verify a flat post-condition (confirming the account is actually flat), rather than relying on a flatten instruction having been issued.
3. If the flat post-condition is not satisfied as a closure approaches, then the Survival Gate shall escalate (re-issue the flatten request, then drive safe-mode or the kill switch) until the account is flat or the closure is reached.
4. The Survival Gate shall own the invariant, its verification, and its escalation; the timed flatten action itself is performed by the execution layer.

### Requirement 7: Intraday-halt/reopen residual — detection out of boundary, residual accepted

**Objective:** As the operator, I accept that real-time per-instrument trading-halt detection is out of scope (no feed exists; `broker-cfd-adapter` is confirmed not the source — `c79738f`), so the intraday-halt/reopen tail is bounded by always-on account-level mechanisms rather than a halt-specific response (operator decision 2026-05-29). This replaces the prior alert-only halt-while-holding behavior.

#### Acceptance Criteria
1. The Survival Gate shall not require a real-time per-instrument trading-halt signal, and shall not implement a halt-triggered entry freeze, alert, or held-position de-risk.
2. The Survival Gate shall bound the intraday-halt/reopen residual through the account-level margin model evaluated continuously by the standing monitor (Requirement 1, Requirement 8), the venue account-level stop-out, and the §16 funding cap; it shall not rely on the per-order stop-loss (which does not fill through a reopen gap, Requirement 4.4) nor on the flat-before-closure invariant (Requirement 6, which addresses only exposure carried across a closure — not a mid-session halt that reopens before close).
3. The Survival Gate shall record post-hoc forced-liquidation outcomes (`broker-cfd-adapter` `get_history` `close_reason`) to the after-market anomaly queue; this is a historical record, not real-time detection.
4. Ex-ante reduction of the halt base rate remains in scope via the entry-exclusion stage (Requirement 5) and the S&P 500 ∩ Gate-441 universe restriction; those are entry-time screens, not real-time halt sensing of a held position.

### Requirement 8: Safe-mode state machine and anomaly queue

**Objective:** As the operator, I want a reproducible graded response to any survival breach, so that the account de-risks deterministically rather than ad hoc.

#### Acceptance Criteria
1. While a survival breach or anomaly condition holds, the Survival Gate shall enter a reproducible safe-mode whose graded responses are tighten, halt-new-entries, and flatten.
2. When safe-mode is entered, the Survival Gate shall queue the triggering anomaly event for the after-market batch.
3. Given identical account state and active parameters, the Survival Gate shall make the same safe-mode entry and grade (deterministic and reproducible).

### Requirement 9: Kill switch

**Objective:** As the operator, I want an emergency halt that cannot be removed by automation, so that order routing can always be stopped regardless of promotion level.

#### Acceptance Criteria
1. Where the kill switch is engaged, the Survival Gate shall halt all new order routing.
2. The Survival Gate shall retain the kill switch under all promotion levels, including full-autonomous operation (it is the emergency halt, not a per-promotion approval).
3. The Survival Gate shall require explicit operator action to re-enable order routing after the kill switch has been engaged.

### Requirement 10: Pinned-parameter consumption (no fit, tighten-only override)

**Objective:** As the operator, I want the gate to act on parameters fixed at run start, so that decisions are reproducible and never silently re-resolved against drifting live state (P2).

#### Acceptance Criteria
1. The Survival Gate shall consume the active survival parameters pinned at the start of the run, by value.
2. The Survival Gate shall not re-resolve survival parameters from live state mid-run.
3. The Survival Gate shall not fit, tune, or compute survival parameters.
4. If supplied a runtime parameter override that would loosen a survival constraint, then the Survival Gate shall reject the override and retain the pinned value; an override that tightens shall be applied.

### Requirement 11: Determinism and inner-ring isolation

**Objective:** As the operator, I want the gate's decision logic provably reproducible in isolation, so that the highest-blast-radius node can be verified before any live cutover (P14).

#### Acceptance Criteria
1. Given identical account state, proposed order, and active parameters, the Survival Gate shall produce an identical decision.
2. The Survival Gate's decision logic shall be exercisable in isolation, without an LLM, external services, or a live database.
3. The Survival Gate shall expose its decision and the constraint(s) that drove it in a form the operator and downstream consumers can inspect.
