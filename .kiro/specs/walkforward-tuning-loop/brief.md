# Brief: walkforward-tuning-loop

> Re-entry brief (roadmap.md already lists this spec). Boundaries here are largely **pre-decided**: §14.11's six operator questions are all RESOLVED (2026-05-29), grounded in `docs/research-walkforward-tuning-loop-2026-05-29.md`. This brief synthesizes those into a spec boundary; it does not re-open them. Canonical strategic record: `docs/exploration-systematic-flow-architecture-2026-05-28.md` §14 (committed build per §15), §16.1.

## Problem

The reactive CFD layer's in-session model (softmax + threshold, §14.7) is a *fixed* set of params/code once a session starts — runtime only **applies** validated values, it never **fits** new ones (§14.4, the safety axis). Without an after-market process that fits new versions under out-of-sample discipline and promotes them, the model can never improve, adapt to regime shift, or have its calibration corrected. A multi-hour fit cannot run in-session (§14.3/§14.4), so adaptation must live on a separate, asynchronous clock.

## Current State

- **Slow-clock side does not exist yet.** §14 is a committed build (§15) but un-built.
- **Upstream substrate is landing:** `decision-trace-telemetry` is in implementation (mig `048` landed) and owns the model process trace + the version-attributed `counterfactual_ledger` + the 4-key correlation contract (`run_id, code_version, param_version, walk_forward_window`). That is the read substrate this loop depends on.
- **The fit targets exist as specs:** `reactive-signal-model` (its `ParamSnapshot` — weights / temperature / threshold) and `survival-gate` (its `SurvivalParameters`). Both are tunables this loop fits; neither is reimplemented here.
- **`execution-daemon` requirements + design are now approved** (2026-05-30, landed via git) — the consumer of promoted versions and owner of deploy/atomic hot-swap; it took the **full version-pinned lifecycle + hot-swap IN scope** (operator override of the §14.11 #1 "moot-for-paper" default). It *emits* the after-market event queue this loop **drains**, and reads the trace via `decision-trace-telemetry`'s landed `reader.query_trace` — the same read substrate this loop uses.
- The two-loop separation is fixed (§15): this loop **populates and validates** the config menu; the in-session monitor **selects** from it.

## Desired Outcome

When done, an after-market, scheduled, LLM-driven batch can:
1. Read the model process trace + version-attributed ledger **up to the IS-window boundary only** (temporal firewall, §14.6 — no forward-window leakage).
2. Fit a new (param and/or code) version, producing a hashed, P2-versioned snapshot.
3. Run it as a **challenger over a forward window** on paper data and score it against the incumbent on the **survival-net risk-adjusted return** metric.
4. Decide promotion **autonomously (no human sign-off, §14.11 #2)** through the resolved gate — **DSR + PSR/MinTRL + PBO** (§14.11 #6), never on in-sample Sharpe.
5. On a pass, **promote = advance the walk-forward window = write the validated version to the P2 param-version table**, and emit a **falsifiable tuner-action audit** (P11/P15) joinable to the model trace via the shared keys.

## Approach

A vanilla Claude Code **markdown orchestration** (P1 / §14.10): scheduler/queue-fired → read telemetry + ledger → fit → challenger forward-eval → gated promotion → P2 version write + audit envelope. No Python orchestrator; Python only as leaf tools (statistical gate math, fit harness). Promotion bar = the research-resolved **DSR + PSR/MinTRL + PBO** gate on survival-net risk-adjusted return; the **operator-calibrated decision-rule knobs** (OOS margin over incumbent, consecutive-window count, anti-churn hysteresis) are set provisionally and calibrated empirically — literature is silent on them (§14.11 #6). Anchored/rolling split-memory (§14.6) adopted **provisionally, as a hypothesis to validate** (§14.11 #5), not established practice.

## Scope

- **In**: the IS→fit→challenger→forward-OOS→promote walk-forward cycle (§14.6); the temporal firewall on the tuner's read; the autonomous promotion gate (DSR + PSR/MinTRL + PBO, survival-net metric); the **fit** of `reactive-signal-model` params (rolling, edge/return) and `survival-gate` params (anchored, tail/risk); both promotion tracks — param-snapshot FIT and code/structure deploy (differ in gate weight, not authority, §14.4); writing the validated version to the P2 param-version table; this loop's **own tuner-action audit** (why a version was promoted, as a falsifiable hypothesis — P11/P15); checkpoint/resume for the hours-long batch (§14.9).
- **Out**: see Out of Boundary.

## Boundary Candidates

- The walk-forward cycle controller (IS-boundary roll-over = advance = deploy-handoff)
- The fit step (LLM proposes new param/code version → hashed P2 snapshot)
- The temporal-firewall read surface (telemetry + ledger, IS-boundary-capped)
- The promotion gate (DSR + PSR/MinTRL + PBO; effective-N logged; MinBTL search-breadth cap; never IS-Sharpe)
- The validated-version writer into the P2 param-version table (= the menu the in-session monitor selects from)
- This loop's tuner-action audit envelope + its own HG validator (P11)

## Out of Boundary

- **The model process trace, the correlation-key schema, and the `counterfactual_ledger` version dimension** — owned by `decision-trace-telemetry`; this loop is a *reader* of them, not their owner.
- **The live fire/order decision, the hot path, order placement, atomic hot-swap, deploy-at-clean-boundary, and the full version-pinned position lifecycle** — owned by `execution-daemon` (§14.5; took the full lifecycle + hot-swap IN scope per operator override 2026-05-30) / `broker-cfd-adapter`. This loop hands a validated version to the P2 table and *advances the walk-forward window*; it does not deploy. **Seam resolved (daemon design, 2026-05-30):** the window-advance is confirmed this loop's **forward contract** (daemon design puts it explicitly out of daemon scope); the daemon **bootstraps** the window in v0.1 and **re-sources it at hot-swap** when this loop lands — so the daemon learns the advanced window at adoption time. Residual on this side: define *how* the advanced window travels with the published version (design-level, this spec).
- **The in-session monitor's select-from-menu + halt/tighten + its own intervention audit** — owned by `in-session-monitor` (§15). This loop only *populates* the menu.
- **Runtime application of params** (regime-select + survival-tighten) — that is the daemon/monitor's apply-only path (§14.4), never a fit.
- **The §13 lexicographic ordering and the survival one-way tighten-only rule at runtime/version-transition** (global-tightest across pinned + current, §14.5; P7) — owned by `survival-gate` / `execution-daemon` / §13. This loop fits survival params (anchored) but the never-loosen-at-runtime guarantee is not its to enforce. *(Whether a fit may propose looser survival params for new positions is a design-level question, not resolved here.)*
- **Reimplementing the softmax/threshold model or the survival gate** — this loop tunes their snapshots; it does not own their logic (`reactive-signal-model`, `survival-gate`).

## Upstream / Downstream

- **Upstream**: `decision-trace-telemetry` (the model trace + version-attributed ledger read substrate via the landed `reader.query_trace` + the landed 4-key correlation contract); `execution-daemon` (now briefed 2026-05-30 — emits the after-market event queue this loop drains; assembles the trace rows incl. `run_id` / `walk_forward_window` injection; produces the paper/challenger forward performance this loop scores); the P2 `parameters` / `parameters_active` / `run_parameters_snapshot` machinery; the evaluator (`src/eval/`) gate + the `orchestrator_step.py` cost ledger.
- **Downstream**: the P2 param-version table — written here, consumed by `execution-daemon` (deploy) and `in-session-monitor` (§15 select). The version-attributed ledger A/B (filter-gated-vs-pure-reactive, §12.5) runs *across* the walk-forward steps this loop advances.

## Existing Spec Touchpoints

- **Extends**: nothing schema-wise. *Reads* the `counterfactual_ledger` version dimension (mig 048, owned by `decision-trace-telemetry` — additive, must not be reimplemented). Rides existing P2 versioning as the tune→roll-over mechanism.
- **Adjacent**: `decision-trace-telemetry` (joins its trace/ledger via the 4 shared keys — the seam is the *landed* mig-048 contract, not a re-described one); `in-session-monitor` (sibling — this loop writes the menu, the monitor reads it; shared seam = P2 table); `execution-daemon` (requirements + design approved 2026-05-30 — promote/deploy split confirmed: this loop publishes the version + advances the window, the daemon adopts via atomic hot-swap + owns the full version-pinned lifecycle; seams now resolved — the event queue is the append-only `execution_daemon_event_queue` table (mig 051) drained by SELECT+watermark with this loop setting `drained_at`, and the daemon re-sources the advanced window at hot-swap); `reactive-signal-model` + `survival-gate` (their param snapshots are the fit targets); the `src/eval/gates/` HG-validator pattern (this loop gets its own per P11).

## Constraints

- **P1 / §14.10** — markdown orchestration, fired by scheduler/queue; Python only as leaf tools (gate math, fit harness). Not a Python orchestrator.
- **P2** — a fit produces a new hashed, versioned snapshot; this *is* the roll-over mechanism. Pin-by-value semantics; no live re-resolution.
- **P7 / §13** — downstream-only-more-conservative; survival params one-way-tightenable at runtime (this loop respects, does not own, that guarantee). §13 lexicographic precedence (Survive ⊳ Preserve ⊳ Edge ⊳ Return) is invariant — the survival-net metric reflects it; never trade a higher link for a lower one.
- **P11** — owns its own tuner-action-audit envelope + HG validator (the *why* of a promotion); not folded into `decision-trace-telemetry`.
- **P14** — a **code/structure** deploy must clear the **full inner-ring suite green** before promotion; a **param** fit clears forward-window OOS-beat + evaluator + §13 guard (lighter gate, same authority — §14.4). Outer-ring scoring of any promoted version sits on the version-attributed ledger.
- **P15** — the promotion rationale is a **falsifiable hypothesis**; the gate metrics (DSR / PSR / MinTRL / PBO) are *derived*, not asserted. **Never gate on in-sample Sharpe** (§14.11 #6).
- **§14.4 fitting-vs-applying** — ALL fitting of new values (param or code) happens here, after-market, under OOS discipline. The loop never fits live.
- **§14.11 #2 autonomy** — no human sign-off on any promotion. The autonomous gates + the §11.5 kill switch / survival gate are the *entire* backstop between an LLM-authored change and the levered book; their rigor is correspondingly load-bearing. (No-sign-off removes per-promotion approval, not the operator kill switch.)
- **§16.1 interaction** — paper phase is intraday-flat-by-close, so the book is flat at the after-market deploy boundary → §14.11 #1 deemed **version-pinned lifecycle (§14.5) moot for paper**. *Note (2026-05-30):* `execution-daemon` nonetheless took the **full version-pinned lifecycle + hot-swap in scope** as a first-principles target (operator override) — but it remains **the daemon's** concern; this loop only writes the validated version, so no pinning machinery is built here regardless.
- **T4 / §14.11 #4** — **no aggregate cost cap** (accepted, eyes-open). Only the per-`(run_id, agent)` $60 ceiling exists; a code-gen + full inner-ring pass is the repo's most expensive job, and a runaway tuning batch has no aggregate halt.
- **v0.1 paper-only** (§11.5 / §15) until the survival apparatus is proven green (P14).

## Open Items (carry to requirements — do NOT block this brief)

- **CPCV vs. walk-forward (headline, touches the spec name).** Research found walk-forward is the *weakest* OOS validator on overfitting metrics and recommends preferring **CPCV** in the promotion gate "where feasible" (§14.11 #5 cross-cutting, #6). §14.6 frames a single forward window as the OOS test. Requirements must decide: keep walk-forward primary with PBO/CPCV as diagnostic, or move CPCV to primary and **amend §14.6**. Record now; resolve in requirements.
- **Operator-calibrated decision-rule knobs** (literature-silent, §14.11 #6): required OOS *margin* over the incumbent, *consecutive-window* count, *anti-churn / hysteresis*. Set provisionally, calibrate empirically.
- **Anchored/rolling split-memory** (§14.11 #5): adopt provisionally as a validate-on-the-book hypothesis (no trading precedent); consider data-driven / recency-based window selection rather than a static commitment.
- **Champion/challenger mechanics**: the ML-ops champion/challenger promotion definition was *refuted* in research (0-3) — design from first principles + the resolved gate, not from a cited ML-ops pattern.
- **Seams with `execution-daemon` — RESOLVED by its approved design (2026-05-30):** the event queue is the append-only `execution_daemon_event_queue` table (mig 051), drained by SELECT + watermark with this loop setting the `drained_at` column; the walk-forward-window advance is this loop's forward contract and the daemon re-sources it at hot-swap (bootstraps until this loop lands). Residual on this side: define *how* the advanced window + validated version are published together (design).
- **Migration-number coordination:** 048 (telemetry), 049/050 (survival-gate), 051/052 (execution-daemon) are claimed — this loop's tuner-action-audit table (P11) must take **053+**.
