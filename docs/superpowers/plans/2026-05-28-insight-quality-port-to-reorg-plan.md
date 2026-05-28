# Insight-Quality → main-reorg Port: Resolution Plan

> Goal: land the insight-quality work (branch `feature/insight-quality-impl`, 4 commits + review fixes,
> +320 tests green on the OLD layout) onto `main`, which was reorganized after this branched.
> Status: PLAN (not yet executed). PR #6 already preserves the work on origin; main is untouched.

## Recommended resolution (TL;DR)

main deliberately diverged architecturally, so this is **not a full port** — it's a **partial landing of
the foundation-intact subset, dropping the superseded half.**

**LAND (port onto main's taxonomy → clean PR → merge):** the coherent, foundation-intact chain whose
dependencies all still exist on main:
- Envelope schema extension (`axis_a`/`axis_b`/`gate_decision`/`reasoning_trace`) → `shared/agent_harness/envelopes/`
- Gate registry refactor + **WS-6 hybrid gate** → `eval/gates/`
- Orchestrator post-step (persist `gate_decision`, opt-in scoring) → `shared/agent_harness/`
- Evidence persistence + market-data PIT/total-return fix → `mcp/`
- **WS-1 articulation + WS-2 sophistication scorers** → `eval/scoring/`; **WS-4 calibration** → `eval/calibration/`; **WS-3 conformal** → `overlays/conformal/`; **`llm_cache`** → `shared/llm_cache/` (consumed by WS-1)
- Migrations 045/046/047 (no collision; main is at 044)

**DROP as superseded (do NOT re-introduce — main removed/deferred the foundation):**
- **WS-5 BoN-MAV** — main has no synthesis subsystem (only deterministic `conviction_rollup`)
- **WS-7 sizing dims + `risk_overlay`** — main's `supervisor/sizing.py` explicitly defers the composable formula
- **P0-5/A1 rubric cache wiring** — main has no LLM rubric scorer (the `llm_cache` module still ports; only its rubric wiring is dropped)

**Sequence:** Phase 0 (freeze the old→new map — done) → Phase 1 (new branch from `origin/main`; relocate LAND set + import rewrites + place new pkgs) → Phase 3 (re-establish main's regression baseline, port the LAND set's tests) → Phase 4 (clean PR → merge). Each implementation phase: advisor-before / review-after. **No force-merge; main is written only via a normal clean-merge of a green branch.**

**Operator decisions before execution:** (1) confirm DROP set is acceptable (vs. wanting main to adopt the composable formula / a synthesis subsystem later); (2) confirm Class-3 taxonomy homes; (3) authorize execution (last explicit instruction was "plan," so a port-and-merge needs an explicit go).

**Lower-effort alternative:** keep PR #6 as the reference and cherry-port only the envelope-schema + WS-6 gate later, if even the LAND set isn't worth the porting cost now.

## The situation (verified)

`main` (`a1b3f2e`) diverged from our branch point (`94c23b8`) by **400 files / +3398 / −52273** — a
**move-based reorganization** into a new `src/` taxonomy, NOT a functionality rewrite (most renames are
R094–R100 = near-identical content). 8 of our 10 core target files no longer exist at their old paths.

**main's new taxonomy:**
```
src/eval/        gates/ (was src/evaluator_gates/) + scorer.py
src/mcp/         (≈ intact)
src/micro/       (new micro-feature work — not ours)
src/overlays/    flow/ tactical/ reversion/ (was src/p9/p8/p10_*_overlay/)
src/shared/      agent_harness/ (was src/agent_harness/), regime_sidecar/
src/supervisor/  emitter.py, sizing.py, continuous_conviction.py, conviction_rollup.py, … (was src/p7_recommendation_emitter/)
```

Migrations: main's highest is **044**; our **045/046/047 do not collide** (safe as-is).

## Three classes of work

### Class 1 — Clean relocation (mechanical: move + import-rewrite, our diffs re-apply)
Main moved these intact; re-apply our changes at the NEW path and rewrite imports.

| Our file (old path) | New path on main | Sim |
|---|---|---|
| `src/agent_harness/envelopes/{_base,flow,tactical,pm_supervisor,catalyst,quantitative,strategic}.py` | `src/shared/agent_harness/envelopes/…` | R095–099 |
| `src/agent_harness/envelopes/reversion.py` (NEW, ours) | `src/shared/agent_harness/envelopes/reversion.py` | — |
| `src/agent_harness/orchestrator_step.py` | `src/shared/agent_harness/orchestrator_step.py` | R098 |
| `src/evaluator_gates/__init__.py` + our NEW `_registry/_outcome/_fingerprints/_hybrid_gate/_judge/_anchor_set.py` | `src/eval/gates/…` | R097–100 |
| `src/p7_recommendation_emitter/emitter.py` | `src/supervisor/emitter.py` | R098 |
| `src/p9_flow_overlay/liquidity_profile.py` (NEW, ours) | `src/overlays/flow/liquidity_profile.py` | — |
| `src/mcp/{edgar,fundamentals,market_data}/*` + our NEW `evidence_persistence.py` | `src/mcp/…` (≈intact) | — |

Import rewrites required everywhere (src + tests): `src.evaluator_gates`→`src.eval.gates`,
`src.agent_harness`→`src.shared.agent_harness`, `src.p7_recommendation_emitter`→`src.supervisor`,
`src.p8_tactical_overlay`→`src.overlays.tactical`, `src.p9_flow_overlay`→`src.overlays.flow`,
`src.p10_reversion_overlay`→`src.overlays.reversion`.

### Class 2 — Reconcile-with-refactor (main deleted/replaced our base; per-module judgement)
Main has **no** `composable.py`, `phase_d_pm_supervisor.py`, or `stage2_llm_rubric.py`. Our work on
these must be re-based onto main's replacement. **Phase 0 of execution must first locate + read each
target**; initial findings:

| Our work | Old base (deleted on main) | Main's apparent replacement | Action |
|---|---|---|---|
| WS-7 sizing dims (liquidity/correlation) | `src/sizing/composable.py` | `src/supervisor/sizing.py` (+ `src/eval/gates/sizing_math.py`) | Inspect `supervisor/sizing.py` API; re-base the 2 new dims onto its model (it may not be the `CalibratedWeights`/`composable_size` shape — confirm before porting). |
| WS-5 BoN-MAV + P2-D | `src/p4_debate/phase_d_pm_supervisor.py` | **TBD** — no debate/ dir on main; synthesis likely folded into `src/supervisor/` (conviction_rollup) | Locate where Phase-D synthesis lives on main; re-base BoN there, or land BoN as a new `src/supervisor/` module. |
| P0-5 cache wiring + A1 cache-miss fix | `src/p3_mechanical_scorer/stage2_llm_rubric.py` | **TBD** — no p3_mechanical_scorer on main | Determine if rubric scoring still exists on main; if removed, the LLM-cache wiring + A1 fix may be obsolete or relocate to wherever LLM calls now live. |
| WS-4 placeholder replacement | `src/eval/scorer.py` (shared-origin placeholder) | `src/eval/scorer.py` (main kept the SAME placeholder) | Shared-origin collision → make `calibration/scorer.py` canonical; keep `src/eval/scorer.py` as the shim (clean reconcile, both descend from the same file). |

### Class 3 — New packages (ours; assign to main's taxonomy — DECISIONS NEEDED)
No main equivalent; land fresh. Proposed homes (confirm before porting):

| Our package | Proposed new home | Rationale |
|---|---|---|
| `src/scoring/` (articulation, sophistication, contracts, enrichment) | `src/eval/scoring/` | scoring is an eval-layer concern |
| `src/calibration/` | `src/eval/calibration/` | calibration is eval-layer |
| `src/conformal/` | `src/overlays/conformal/` | wraps overlay classifier outputs |
| `src/risk_overlay/` | `src/overlays/risk/` | matches `overlays/{flow,tactical,reversion}` |
| `src/credit_stress/` | `src/eval/credit_stress/` *(or quant area)* | analytic block; confirm |
| `src/llm_cache/` | `src/shared/llm_cache/` | cross-cutting infra |

## Execution phases (when authorized — NOT this turn)

- **Phase 0 — Map Class-2 targets.** Read `src/supervisor/sizing.py`, locate main's synthesis path, and the
  mechanical-scorer fate. Confirm Class-3 landing homes. Output: a frozen old→new path + import map.
- **Phase 1 — Rebuild on main.** Branch from `origin/main`; apply Class-1 relocations (re-create our
  changes at new paths) + global import rewrite; land Class-3 packages at chosen homes; renumber nothing
  (045/046/047 stay).
- **Phase 2 — Class-2 reconciliation.** Per-module re-base (sizing dims, BoN synthesis, cache/A1) onto
  main's replacements, advisor-before each, code-review-after.
- **Phase 3 — Verify on the new layout.** Re-establish the regression baseline ON main (its pre-existing
  failures differ from ours — main touched test_orchestrator_step / test_agent_harness_dispatcher);
  port our +320 tests into main's test taxonomy; confirm zero NEW regressions vs main's baseline.
- **Phase 4 — Land.** Open a fresh PR from the rebuilt branch → main (now cleanly mergeable, non-
  destructive); merge.

## Phase-0 recon findings (2026-05-28) — Class-2 bases were DELIBERATELY removed

Reading main's replacements changes Class-2 from "reconcile" to "main intentionally diverged":

- **WS-7 sizing → DROP/defer (recommended).** main's `src/supervisor/sizing.py` is the v0.1 overlay
  model (`compute_sizing`/`SizingSuggestion`) and **explicitly comments "v0.5+ deferred: composable
  formula (weighted multipliers — conviction…)"**. Our WS-7 extended the v0.5 `composable.py` formula —
  which main has NO copy of and explicitly deferred. Porting WS-7 re-introduces a formula main chose not
  to adopt. `risk_overlay` (Class-3) depends on it → same fate.
- **WS-5 BoN-MAV → DROP/re-scope (recommended).** main has no `p4_debate` / phase-D synthesis at all —
  only deterministic `conviction_rollup.roll_up_conviction`. Our BoN built on `phase_d_pm_supervisor.py`,
  which main removed. Re-basing BoN would graft a synthesis subsystem main doesn't have.
- **P0-5/A1 rubric wiring → OBSOLETE; but `llm_cache` itself → PORT.** No `p3_mechanical_scorer` / LLM
  rubric exists on main (`rubric|mechanical|llm` → ∅), so the *stage2-rubric-specific* cache wiring + the
  A1 cache-miss fix are obsolete. BUT `llm_cache` is also consumed by the **WS-1 articulation scorer**
  (RAGAS self-consistency), which is foundation-intact → so `llm_cache` ports (its live consumer is
  scoring, not the removed rubric).

**Net:** a *correct* push-to-main is NOT a mechanical port. ~half the work rests on subsystems main
deliberately removed/deferred; porting it fights main's architecture. Only **Class-1 relocations**
(envelopes, gates, emitter, overlays) and the **foundation-intact Class-3 packages** (scoring,
calibration, conformal — their deps envelopes/mcp/overlays still exist) could land cleanly; WS-5, WS-7,
P0-5/A1, risk_overlay, llm_cache should likely be **dropped as superseded**, pending operator confirmation.

## Risks / decisions for the operator

1. **Class-2 is the real risk** — main may have *intentionally removed* `composable.py`/`p4_debate`/
   `p3_mechanical_scorer`; re-basing our work onto the replacement could conflict with WHY they were
   removed. Each needs a judgement call (port vs. drop-as-obsolete).
2. **Class-3 homes** are proposals — operator should confirm the taxonomy fit.
3. **Effort**: Class-1 + Class-3 + import-rewrite is mechanical (~1 focused pass). Class-2 + test-baseline
   reconciliation is the bulk and the uncertainty.
4. **Lower-effort alternative**: leave the work on PR #6 as a documented reference and re-implement only
   the still-relevant pieces directly on main — viable if much of Class-2 is obsolete post-reorg.
