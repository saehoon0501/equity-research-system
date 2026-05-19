# GOOGL Consensus-Divergence Perturbation Plan — v11-final (CONVERGED)

**Status:** Execution-ready. /review-me adversarial loop converged at v11 with reviewer's explicit "v11 looks solid, no substantive issues" signal (2026-05-19). 11 iterations + Phase A reality-check + plumbing execution + 3 post-Phase-A iterations. ~30 substantive catches. Terminated decisively.

**Date converged:** 2026-05-19
**Plumbing readiness commit:** f2ae53d (`feat: phase A plumbing readiness + sweep-script env-free walk-up`)
**Baseline canary:** GOOGL e76a0750-6828-4698-86cc-0b7f9c196d4e (2026-05-18, HOLD @ MEDIUM, DCF base $218.60 vs consensus target_mean $427.89 ≈ 49% gap)

---

## Purpose

Attribute the ~49% gap (system DCF base $218.60 vs sell-side target_mean $427.89 for GOOGL) to specific parameter axes via pre-registered single-axis sweeps where source, range, position-within-range, runtime-readback, AND interpretation-certification are all disciplined.

**Anti-anchoring discipline (load-bearing):** the plan deliberately does NOT optimize parameters until system output replicates consensus. Each sweep result routes to /grill-me for "is this disagreement intentional (framework discipline) or accidental (parameter mis-set)?" adjudication. Operator must explicitly acknowledge when re-anchoring closes the consensus gap from a consensus-implied value.

**Out of scope:**
- Consensus calibration (the anti-pattern the entire 8-link discipline chain defends against)
- A5 `outside_view.bayesian_shrinkage_r` (meta-parameter — overfits if swept on a single ticker; deferred to a separate cross-ticker study)
- A8 capex normalization (not externalized; verified 0c)
- Cross-ticker validation (separate plan)

---

## Phase 0 — Pre-sweep sanity (STOP-the-line on any fail)

### 0a — Production-tag baseline
`/research-company GOOGL` with NO `--as-of-tag`, in a fresh session, post-mig-037. Establishes the production-tag baseline against which sweep deltas are measured. Required because the pre-mig-037 canary e76a0750 ran on improvised ERP (cache file was absent on disk).

### 0b — Two-tier baseline comparison

**Tier 1 — Wiring correctness (~0.01% FP tolerance):**
Analytic recomputation from PARAMETERS_USED inputs via §3.9 closed-form WACC formula:
- `r_e = r_f + β × ERP` (with `r_f` = current DGS10 from FRED, `β` = yfinance trailing, `ERP` = `wacc.erp` from PARAMETERS_USED block = 4.60 production default)
- `WACC = w_e × r_e + w_d × r_d × (1 − t)`
- Compute DCF base value analytically given the parameters

The 0a run's emitted DCF base MUST match the analytic recomputation within ~0.01% (floating-point rounding only). Any larger drift indicates a wiring or formula bug — NOT LLM stochasticity. STOP-the-line.

**Tier 2 — LLM extraction (±1% tolerance):**
Reserved for envelope numerics downstream of LLM's narrative pass (revenue projection wording, margin-fade interpolation rounding). These tolerate ±1% benign drift. NOT used for the DCF wiring check itself.

**Audit-trail citation:**
Parse 0a's quantitative-analyst envelope (`memos/envelopes/quantitative-analyst__<run_id>.json`) for explicit citation of `wacc.erp` from PARAMETERS_USED. If absent OR Tier-1 outside ±0.01%, sweep determinism for A7 is BROKEN. STOP-the-line.

### 0c — A8 externalization status
Confirmed dropped (2026-05-19 verification): zero capex-normalization parameters exist in `parameters_active`. v11-final scope holds.

### 0d — Source-of-record traceability + source-type classification

All 7 axes verified traceable via parameters table `change_rationale` pointers (2026-05-19 verification). Per-axis classification:

| Axis | parameter_key | Source type | Cited authority |
|---|---|---|---|
| A1 | `dcf.austere_terminal_growth_dgs10_premium_pct` | METHODOLOGICAL | canonical-frameworks.md austere_dcf entry → Damodaran mean-reversion frame + Mauboussin fade-rate concept |
| A2 | `dcf.austere_growth_fade_years` | METHODOLOGICAL | canonical-frameworks.md austere_dcf entry → "competitive advantage period" |
| A3 | `dcf.austere_margin_fade_years` | METHODOLOGICAL | canonical-frameworks.md austere_dcf entry → "industry median margin" mean-reversion |
| A4 | `dcf.austere_roic_fade_years` | METHODOLOGICAL | canonical-frameworks.md austere_dcf entry → "Mauboussin fade-rate operationalization" |
| A6a | `wacc.erp_refresh_drift_bps` | METHODOLOGICAL | quantitative-analyst.md §3.9 cache-refresh heuristic (DGS10 weekly vol empirics) |
| A6b | `wacc.erp_sensitivity_band_bps` | METHODOLOGICAL | quantitative-analyst.md §3.9 output sensitivity (Damodaran ERP monthly 1σ) |
| A7 | `wacc.erp` | **TABULAR** | **Damodaran monthly implied-ERP table at https://pages.stern.nyu.edu/~adamodar/** (per mig 037 + canonical-frameworks.md damodaran_implied_erp entry) |

**A6 runtime decoupling test — DEFERRED:**
Runs only if Phase 5a/5b results show A6a OR A6b moves IV by ≥ pre-registered materiality threshold (operator-set in 5a pre-registration). Test design: mint synthetic sweep with `wacc.erp_refresh_drift_bps = 50` (prod) but `wacc.erp_sensitivity_band_bps = 80` (perturbed). Verify emitted `wacc_at_erp_plus_<X>bp` reflects ±80bps (swept band), NOT ±100 (drift-keyed coupling) NOR ±50 (drift-equals-band coupling). If band tracks drift, A6 split is illusory; A6a/A6b must be rejoined.

---

## Phase 1 — Candidate axes (7 final post A6-split per INV-2 TUNABLE verdict)

| ID | parameter_key | Prod default | Plausibility |
|---|---|---|---|
| A1 | `dcf.austere_terminal_growth_dgs10_premium_pct` | 1.5pp | HIGH (terminal value ~70-80% of mega-cap IV; 0.5pp ≈ 6-9% IV for GOOGL) |
| A2 | `dcf.austere_growth_fade_years` | 5y | MED-HIGH (Cloud +63% YoY makes Phase-1 fade duration load-bearing) |
| A3 | `dcf.austere_margin_fade_years` | 5y | MEDIUM (OM 36.1% above peer median) |
| A4 | `dcf.austere_roic_fade_years` | 10y | MEDIUM (inc-ROIC 23.87% vs WACC 9.48%) |
| A6a | `wacc.erp_refresh_drift_bps` | 50bps | LOW-MED (cache-policy axis; independent per INV-2) |
| A6b | `wacc.erp_sensitivity_band_bps` | 100bps | LOW-MED (output-band axis; independent per INV-2) |
| A7 | `wacc.erp` | 4.60% | HIGH (discount-rate dominates mega-cap duration IV; tabular Damodaran source) |

**Excluded:**
- `dcf.sensitivity_band_pct` (controls bear/bull range, not central case)
- `quality_gate.piotroski_f_min` (binary gate; F=6 clears)
- `reinvestment_moat.label_A.min_roic_spread_pp` (binary moat label assigned with margin)
- `sizing.*` (controls size, not direction)
- `evaluator.gate.helmer_min_primary_source_citations` (gate behavior, not IV magnitude — this was the 722b46e5 sweep tag's axis, citation-floor test only)
- A5 `outside_view.bayesian_shrinkage_r` (meta-parameter; deferred to cross-ticker study)
- A8 capex normalization (not externalized; v11-final scope drop)

---

## Phase 2 — Pre-registration (source-type-aware + interpretation-certified)

`docs/superpowers/sweeps/GOOGL-perturbation-preregistration.md` (append-only, git-committed BEFORE sweep tag mint). Per axis, 8 fields:

1. **Cited source** — MUST match parameter's source-of-record from original /review-me commit (anti-cherry-pick anchor on source).
2. **Source type** — TABULAR or METHODOLOGICAL (per Phase 0d classification table).
3. **Published range OR methodology framing:**
   - TABULAR (A7 only): record published range directly from cited table. Closed-interval admissibility; boundary values admissible.
   - METHODOLOGICAL (A1-A4, A6a, A6b): record (a) methodology's conceptual framing verbatim from source, (b) operator's INTERPRETATION STEP translating methodology → numerical range, (c) defense for the interpretation citing a specific page/section that explicitly bounds the numerical range OR explicit acknowledgment that no such bound exists with first-principles justification.
4. **Production-default position** within the range.
5. **Swept values** (loosening + tightening), each within range.
6. **Selection principle** for each swept value — one of: "range-midpoint" / "1σ from prod-default" / "framework-cited boundary case" / "operator judgment" / "consensus-implied value FLAGGED".
7. **Consensus-distance arithmetic audit** — numeric distance from consensus-implied value of THIS axis (back-solved from $427.89 *ceteris paribus at production defaults*). Required regardless of declared selection principle.
8. **Interpretation certification** (METHODOLOGICAL axes only):
   - `interpretation_certified_by`: <git commit hash of the /review-me cycle that ratified this pre-registration entry>
   - `interpretation_certified_at`: <ISO timestamp of /review-me convergence>
   - Certification happens at sweep-design time during the SAME /review-me cycle that ratifies the full pre-registration document.

Post-sweep admissibility = binary. No post-hoc source or interpretation revision.

---

## Phase 3 — Sweep workflow (per axis)

1. Mint sweep tag UUID
2. Seed 64 rows in `parameters` (63 prod defaults + 1 perturbation, tag=UUID)
3. Sign tag via `scripts/sign_sweep_tag.sh --tag <uuid> --format env`
4. Dispatch `/research-company GOOGL --as-of-tag=<uuid> --as-of-tag-sig=<sig> --as-of-tag-issued-at=<unix>` in fresh session
5. Pull pm-supervisor envelope; extract continuous effect size (Δ base / austere / bull / conviction)

---

## Phase 4 — Decision matrix (2 buckets + 2 falsifiability gates)

| Bucket | Observed | Decision |
|---|---|---|
| inadmissible | Swept value outside pre-registered range OR (METHODOLOGICAL) `interpretation_certified_by` field empty OR `git show <hash>` does NOT textually touch the axis parameter_key on a `^+` added line within a `parameter_registry` row/INSERT block | Discard or re-anchor via fresh /review-me |
| admissible | Inside range; for METHODOLOGICAL, cert hash valid + diff contains parameter_key on `^+` added line | Report continuous effect size + consensus-distance + selection principle + interpretation step + cert-hash. Route to /grill-me. |

**Cert-hash falsifiability test (operationalized per v11):**
- `git show <interpretation_certified_by>` runs
- Diff grep'd for parameter_key on `^+` added lines only
- Excludes `^+--` SQL comments, `^+#` Python comments, unrelated context
- Match must be within `parameter_registry` row insertion or `INSERT INTO parameter_registry` SQL block
- If match fails → certification invalid → admissibility = inadmissible

**Escalation rule for prod-default re-anchoring:**
If /grill-me proposes re-anchoring prod-default based on a sweep result, AND swept value was either (a) declared consensus-implied-FLAGGED, or (b) consensus-distance ≤5% of production-default value (axis-specific; integer params like fade-years: ≤1 unit) — operator MUST explicitly acknowledge in writing:

> "I am aware this re-anchoring closes the consensus gap because the swept value is at-or-near consensus-implied. The framework discipline is being relaxed in this direction by operator choice, not by framework evidence."

Re-anchoring without acknowledgment is inadmissible.

---

## Phase 5 — Execution gate (phased)

**5a:** A7 + A1 only, both directions = 4 runs ≈ 4hrs orchestrator time.
- Rationale: A7 highest-leverage on discount-rate gap AND tabular source (no interpretation step required); A1 highest-plausibility for DCF terminal-value with methodological-but-tractable interpretation step.
- Operator pre-registers materiality threshold for both axes before sweep execution (e.g., "≥2% base-case IV shift = material").

**5b:** Operator-gated expansion to A2 / A3 / A4 / A6a / A6b based on 5a results.
- Each axis requires its own pre-registration + cert hash before sweep.
- A6 runtime decoupling test (Phase 0d) fires if A6a OR A6b moves IV ≥ materiality threshold.

---

## Phase 6 — Risks

**R1 — Consensus-anchoring (central anti-pattern).** Mitigation chain — 8 links:
1. Phase 0d source-of-record traceability verification (7 axes, all verified pre-execution)
2. Phase 2.1 source anchor (anti-cherry-pick on source)
3. Phase 2.2 source-type classification (tabular vs methodological)
4. Phase 2.3 published range OR interpretation step with falsifiability test
5. Phase 2.6 selection principle (anti-cherry-pick within range)
6. Phase 2.7 consensus-distance arithmetic audit (anti-relabeling)
7. Phase 4 inadmissible-bucket enforcement
8. Phase 4 escalation rule + cert-hash falsifiability test (anti-quiet-adoption)

**R2 — Multiple comparisons.** Report raw effects; no Bonferroni correction (theatre at this sample size). Pre-declare which axes are hypothesis-testing (A1, A7) vs exploratory (A2, A3, A4, A6a, A6b).

---

## Convergence Record (full /review-me arc)

| Iteration | Substantive issues caught | Direction |
|---|---|---|
| v1 → v2 | 7 (WACC central missing; capex norm missing; A5 meta-overfit; ERP drift coupling; P1/P2 false dichotomy; post-hoc defensibility figleaf; Phase 0 lenient) | **added + reframed** |
| v2 → v3 | 5 (source-shopping; A7 mechanically incomplete; A8 indecision; bucket 1/2 illusory; Phase 0 confounders) | **cut + tightened** |
| v3 → v4 | 4 (Phase 0 value-assertion; provenance demo; 5% threshold magic; conviction-flip half-state) | **cut** |
| v4 → v5 | 1 substantive + 3 polish (within-range selection-shopping; boundary; partial-override; orphan multi-comp count) | tightened |
| v5 → v6 | 3 (consensus-distance arithmetic; partial-override escape; flagged-admissible cosmetic) | tightened |
| v6 | 0 substantive | **converged-conditional** |
| v6 → v7 | 4 empirical findings (F1 A7 not externalized; F2 sources methodological; F3 INV-2 open; F4 tabular-range assumption falsified) | **reframe verdict** |
| Phase A executed | INV-2 TUNABLE adjudication + mig 037 wacc.erp externalization + consumer wiring | plumbing |
| v8 | 4 (Q1 audit-trail; Q2 A6 decoupling; Q3 falsifiability; Q4 tolerance) | tightened |
| v9 | 3 (hash unbound; citation-vs-use theater; grep static) | tightened |
| v10 | 1 blocker (Q3 ±1% tolerance conflation) + 2 tightenings | tightened |
| v11 | 0 substantive | **converged** |

Total: 11 iterations + Phase A reality-check, ~30 substantive catches, 2 explicit cutting iterations (v2→v3 + v3→v4), 1 reframe verdict followed by full plumbing execution. Terminated on reviewer's explicit "v11 looks solid, no substantive issues."

---

## Phase 0 status as of 2026-05-19

| Sub-check | Status | Evidence |
|---|---|---|
| 0a (production-tag baseline) | **OPEN** | Requires fresh `/research-company GOOGL` no-tag session (operator-side) |
| 0b (two-tier comparison) | **OPEN** | Requires 0a output |
| 0c (A8 externalization confirmed dropped) | ✅ DONE | `SELECT COUNT(*) FROM parameters_active WHERE parameter_key ILIKE '%capex%norm%'` = 0 |
| 0d (source-of-record traceability) | ✅ DONE | All 7 axes traceable via `change_rationale` pointers; 6 METHODOLOGICAL, 1 TABULAR (A7) |
| 0d (A6 runtime decoupling test) | **DEFERRED** | Runs only if A6a/A6b sweep results move IV ≥ pre-registered materiality threshold |

---

## Operator handoff — next steps to execute Phase 5a

1. **Complete 0a + 0b** — dispatch `/research-company GOOGL` in fresh session (no `--as-of-tag`), compare DCF numerics to e76a0750 baseline via Tier-1 analytic recomputation (~0.01%) + Tier-2 envelope check (±1%) + audit-trail citation parse.
2. **Pre-register Phase 5a** — A7 + A1 entries in `docs/superpowers/sweeps/GOOGL-perturbation-preregistration.md` with all 8 fields per axis. The interpretation_certified_by hash comes from THIS plan's commit (when persisted-and-committed).
3. **Pre-register materiality threshold** — operator-set value (e.g., ≥2% base-case IV shift) for "did this axis move materially" gate (downstream of decision matrix).
4. **Mint + sign + dispatch** A7 sweep (loosening + tightening directions) and A1 sweep (loosening + tightening directions) per Phase 3 workflow. 4 runs total ≈ 4hrs.
5. **Decision matrix application** — pull pm-supervisor envelopes per run, route admissible results to /grill-me with the full per-axis context (effect size + consensus-distance + selection principle + cert hash).

Outstanding side-quests (non-blocking):
- Out-of-band ERP refresh job (operator-runbook script with WebFetch + INSERT-supersedes_version pattern; deferred per /review-me convergence)
- Worktree merge to main (carries C2/C3/mig 037/wiring edits + this plan; operator/cadence-driven)
- Cross-ticker validation of axes that emerge as load-bearing in 5a (separate plan)

---

*This document is the durable artifact of the /review-me convergence on the GOOGL consensus-divergence perturbation plan. It supersedes the in-conversation v6-final draft. Operator may invoke any of its phases independently. Plan is execution-ready as of commit-time + this document's filesystem write.*
