# Section 5 Consensus — L3 / P3 (Successful-Company Patterns + Counterfactuals)

**Date:** 2026-04-29
**Session:** Q&A consensus review with operator (saehoon0501) — Section 5 of the consensus-documentation-protocol series
**Status:** **FULLY LOCKED** — Q1 / Q2 / Q3 / Q4 / Q5 / Q6 all closed
**Purpose:** Capture how P3 (name discovery phase) uses L3 (cross-era patterns + 32-name counterfactual catalog) to score candidates: PASS / WATCH / promote-to-P4.

**Predecessors:**
- [Section 1](section-1-consensus.md), [Section 2](section-2-consensus.md), [Section 3](section-3-consensus.md), [Section 4](section-4-consensus.md)

---

## 1. Section 5 scope

P3 is the funnel phase that takes a candidate (from L7 smart-money event, P2 scenario theme, or operator manual `/research-company`) and decides whether to PASS / WATCH / promote-to-P4. Inputs:
- L3-e cross-era patterns (28 patterns categorized HIGH/MEDIUM/CONTESTED)
- L3-d counterfactual catalog (32 named "looked like a multi-bagger but failed" cases)
- Tier-A signal definitions (founder tenure, per-share-value, ROIIC, pivot)
- Fraud signature checklist (6-criteria)

Why it cascades: P3 is THE filter that determines what gets to P4 deep-dive (expensive 5-style debate). Wrong P3 logic = either survivorship bias (look-alike candidates passed) or over-conservatism (genuine multi-baggers killed at Gate 1).

---

## 2. Q1 LOCKED — Three-stage hybrid scorer architecture

**Locked: sequential rule-then-LLM with strict information isolation + Stage-3 deterministic linter.**

### Stage 1 (mechanical, deterministic, fast, cheap)

**1A. Multiplicative knockout** (any single fail → REJECT):
- Fraud signature 3+/6 (charismatic CEO + board lacks domain + novel accounting + secrecy + dismissed bear research + related-party; missing data = flag raised conservatively)
- Era-fit binary (right-thing-right-decade match)

**1B. Additive equal-weight 4-criterion Tier-A composite** (among Stage-1A survivors):
- Founder/CEO duration ≥15 years
- Per-share-value primary management metric
- ROIIC > 15% sustained
- Pivot-creates-multi-bag (not original product)
- Threshold: ≥3 = A / 2 = WATCH / ≤1 = REJECT
- Missing data: LEI-style proportional re-weighting

Equal-weight per Q2-Section3 lock (Smith-Wallis 2009 small-sample finding) and Q1-Section5 mechanical-scoring research.

### Stage 2 (LLM rubric, INFORMATION-ISOLATED from Stage 1)

- **Per-pattern single-attribute call** — never bundle dimensions (anchoring-bias mitigation)
- **3-level ordinal {LOW, MEDIUM, HIGH} → {0.0, 0.5, 1.0}** with locked behavioral anchors per level (Moody's scorecard pattern)
- **Forced JSON output:**
  ```
  { rating, confidence, evidence_quotes[], rationale ≤2 sentences,
    defer_to_human, tie_break_applied }
  ```
- **Required verbatim evidence citation** — no quote → defaults to LOW (sycophancy mitigation)
- **Self-consistency** — N=5 samples at temp=0.7; median rating; dispersion = empirical confidence
- **Information isolation** — Stage 2 LLM does NOT see Stage 1 mechanical output (anchoring-bias mitigation per O'Leary 2025 / CALM framework). Matches Section 1 finding "PMSupervisor must NOT force consensus" + L8 "judge stays outside debate"

Patterns scored at Stage 2:
- L3-e #4 pivot-creates-multi-bag (qualitative parts beyond Stage 1's binary)
- L3-e #20 right-thing-right-decade (Coral test — structural-capture vs trade-exposure)
- L3-e #5 founder equity stake (qualitative dynamics)
- L3-e #16 narrative reflexivity (CONTESTED)
- Other contested L3-e patterns

### Stage 3 (deterministic linter)

Cross-checks LLM output against Stage-1-known-true facts:
- Did LLM contradict a Stage-1 mechanical fact?
- Did LLM rate HIGH without evidence quote?
- Did LLM exhibit round-number defaulting / position bias / verbosity bias?

Flags routed to operator review; logged to S2 counterfactual ledger.

### Audit trail

Per-stage structured log with versioning at every layer:
- `stage1_rule`: rule_engine_version, parameters_version, rules_evaluated[], gate_outcome, fail_reason
- `stage2_llm`: model_id, model_version, prompt_version, rubric_version, **`saw_rule_output: false`** (enforced isolation flag), patterns_scored[], evidence_citations[]
- `stage3_linter`: linter_version, findings[], contradictions_with_stage1[]
- `composition`: final_decision, **`disagreement: bool`** (first-class field), resolution_policy_applied, human_review_required

Versioning enables `/parameters-review` drift detection across rule/prompt/model upgrades.

### Calibration plan

| Component | Method | Targets |
|---|---|---|
| Mechanical (Stage 1) | Walk-forward backtest in `src/backtesting/framework.py` | DSR > 0.5; PBO < 50%; multi-bag-prediction OOS |
| LLM rubric (Stage 2) | 30-50 gold-standard companies per pattern; cross-model validation | Cohen's kappa ≥ 0.61; HIGH hit-rate ≥ 80%; ECE < 0.10; cross-model kappa ≥ 0.61; position-bias flip-rate < 10%; quarterly drift watch |
| Linter (Stage 3) | Production logs review | Catches contradictions; flags routed to operator |

### Library deliverables (Q1)

4 files in `.claude/references/empirical/data-sources/`:
- `Q1-Section5-llm-rubric-design.md` (328 lines, 38 sources)
- `Q1-Section5-mechanical-scoring.md` (565 lines, 25 sources)
- `Q1-Section5-hybrid-systems.md` (440 lines, 42 sources)
- `Q1-Section5-synthesis.md` (synthesis of the 3)

---

## 3. Q2 LOCKED — Counterfactual catalog usage = hybrid mechanical retrieval + LLM narrative on top-3

**Locked: (e) hybrid mechanical retrieval + LLM narrative judgment on top-3 most-similar counterfactuals.**

### Why mechanical (not embedding-based)

Operator's pushback on initial RAG-with-embeddings proposal was correct: embeddings capture text/semantic similarity, NOT structural pattern. Two companies can have similar text descriptions ("growing losses, concentration risk") but completely different structural failure modes. Structural features are **hardcoded boolean/categorical attributes**, not learned vectors.

### Counterfactual catalog feature schema

Each of 32 counterfactuals has structured feature vector:

```
counterfactual_features:
  theranos:
    features: {
      fraud_signature_count: 5,           # of 6
      sector: "med_tech",
      era: "2010s",
      charismatic_CEO: true,
      board_lacks_domain_expertise: true,
      novel_accounting: true,
      secrecy: true,
      dismissed_bear_research: true,
      related_party_transactions: false,
      customer_data_fabrication: true,
      pre_revenue: false,
      multi_bagger_lookalike_period_years: 4,
    }
  hyzon_motors:
    features: { customer_fabrication: true, SPAC_mechanism: true, pre_revenue: true, ... }
  pets_com:
    features: { right_business_wrong_decade: true, cash_burn_no_clear_path: true, sector: ecommerce, era: 1999-2000, infrastructure_immature: true, ... }
  ...
```

### Three-stage retrieval + judgment

```python
# Stage 1 (already running): extract candidate features
candidate_features = stage1_mechanical_extraction(candidate)

# Mechanical similarity: weighted Hamming/Jaccard, NO embeddings
similarities = [
    hamming_jaccard_weighted(candidate_features, cf.features)
    for cf in counterfactual_catalog
]
top_3 = argmax_top_3(similarities)  # deterministic, auditable

# Stage 2: LLM narrative pairwise comparison on top-3 only
for cf in top_3:
    llm_call(
        candidate_features=candidate_features,
        comparison_target=cf,
        prompt_template=structural_similarity_rubric,
    )
    # → { rating: LOW/MED/HIGH, confidence, evidence_quotes, rationale }

# Stage 3 linter:
if any(top_3_ratings == HIGH):
    flag_to_operator_review
```

### Why this scales correctly

- 3 LLM calls per candidate (not 32) — bounded cost
- Mechanical retrieval is deterministic + auditable
- Aligns with Q1 hybrid pattern (mechanical filter → LLM judgment)
- Aligns with Q1 single-attribute rule (one counterfactual per LLM call)

### Schema additions to Stage 2 output

```
counterfactual_similarity: [
  {
    counterfactual_name: "Hyzon Motors",
    rating: "MEDIUM",
    confidence: 0.7,
    evidence_quotes: [...],
    rationale: "..."
  },
  ...
]
```

---

## 4. Q3 LOCKED — 3-LLM iterative-consensus catalog extraction

**Locked: (b-modified) 3-LLM consensus extraction with iteration to HIGH consensus + 5-iteration cap.**

### Mechanism

3 separate subagent dispatches (parallel) on the same L3-d counterfactual catalog. Each extracts structured features per counterfactual to its own JSON output.

```
iteration = 0
remaining_fields = all_fields_to_extract  # 32 cases × ~15 features = ~480

while remaining_fields and iteration < 5:
  iteration += 1
  parallel dispatch with INFORMATION ISOLATION:
    sub_1: Opus, temp varies by iter, prompt varies by iter
    sub_2: Opus, different seed
    sub_3: Opus, different seed
  for each field in remaining_fields:
    if all_3_agree:
      commit(value, confidence="HIGH")
    # else stay in remaining_fields

if remaining_fields after iter 5:
  → escalate to operator with full attempt-history
```

Iteration variance via temp/prompt rotation (0.5/0.7/0.3/0.5/0.3 + framing variations).

### Information isolation guarantee

Each iteration's LLMs do NOT see prior iteration outputs. Prevents sycophantic convergence (matches Q1 Stage 2 isolation principle).

### Audit log per field

```yaml
theranos.charismatic_CEO:
  extraction_history: [iter_1: sub_1=true, sub_2=true, sub_3=false; iter_2: all true]
  final_value: true
  final_confidence: HIGH (converged at iter 2)
  iterations_required: 2
```

---

## 5. Q4 LOCKED — Event-driven adds + automated drift detection

**Locked: event-driven both for adds and recalibrations.**

### Event-driven adds

Triggers: catastrophic failure / quarterly review surfacing / operator domain judgment.
Process: 3-LLM iterative-consensus extraction (per Q3) on ONLY new entry; commits.

### Automated drift detection (post-add)

Triggered automatically on every successful catalog add. Drift-detector LLM analyzes:
- Vintage drift (does new entry's feature distribution differ systematically from older entries?)
- Recategorization candidates (does new entry's framing reveal an existing entry should change archetype?)
- Schema fitness (does new entry require new feature fields?)
- Inconsistency surfacing (old entries where features were ambiguously coded)

Output: structured `drift_detection_report` with proposed-changes list. Operator reviews each: ACCEPT / MODIFY / REJECT. Approved changes write to versioned `parameters` table.

### Recursion guard

Stops at depth=1 (single round of drift detection per add). Prevents infinite loops; logs "next-iteration recalibration candidates" for next add event.

---

## 6. Q5 LOCKED — L3 archetype is orthogonal tag, NOT mode-classification input

**Locked: (a) L3 doesn't affect mode classification.**

Mode is purely Section 1's quantitative classification rule (vol / cap / profitability / growth thresholds). L3 archetype is a separate orthogonal **tag** feeding Stage 2 LLM rubric (Q1) and the Macro-Regime style agent in P4 (Section 4 Q7).

Reasoning:
- Mode = "what is this name NOW" (current financial profile). Section 1's rule captures this quantitatively for auditable reproducibility.
- L3 archetype = "what does this name LOOK LIKE structurally" (pattern fit). Different question.
- Edge cases (NVDA mega-cap with C-mode-shaped risk) handled correctly within-mode via mode-conditional discipline + L3 archetype tag in Stage 2 rubric. Macro-Regime agent in P4 sees both and applies tighter scrutiny without changing mode label.

Engineering analogy: orthogonal `category` and `tags` columns. NVDA can be `mode=B'` AND `archetype=narrative-driven-AI-cycle` simultaneously.

---

## 7. Q6 LOCKED — Calibration architecture + lean ~50 test set

### Calibration architecture (cross-domain synthesis)

Per `Q6-Section5-synthesis.md` (4 parallel subagents: recommender/IR + threat-intel + legal precedent + medical CBR):

**Test set design (3-set):**
- Canaries (must always flag) — coverage = 100% required
- Known-good (must NOT flag) — FP rate < 15% = HEADLINE metric
- Stratified similarity (operator-annotated expected top-3) — NDCG@3 ≥ 0.7; Precision@3 ≥ 70%; Recall@10 ≥ 90%

**Weight calibration:** Bayesian shrinkage toward equal-weight (Diebold-Pauly; same as Section 3 Q2). v0.1 λ ≈ 1.0; v0.5 λ ≈ 0.8; v1.0 λ ≈ 0.5. Never gradient-LTR until n≥500. Per-instance rubrics from legal-tech LRAGE.

**Drift monitoring (3-trigger, MISP + Shepard's):**
1. PM-override sightings ≥3 consecutive same-direction → review
2. Regime-shift events (Section 3 Q3 BOCPD) → review regime-tied signatures
3. Annual audit (Jan 1) + 5-of-15 test-case rotation

**Misgrounding mitigation** (universal failure mode across 4 domains):
- Pinpoint-cite enforcement (verbatim quote required for non-LOW ratings)
- Quarterly hand-audit of random 10 retrievals
- Multi-evaluator parity check on HIGH ratings

### Test set: LEAN ~50 cases (NOT the 175-case research expansion)

12 parallel subagents researched ~120 named cases across 9 sectors × 10 archetypes. Operator confirmed lean test set (avoiding maintenance burden + diminishing returns past 50).

| Set | Count | Role |
|---|---|---|
| **Canaries** | 20 | 2 per archetype × 10 archetypes |
| **Known-good** | 15 | 1 per surface-similarity-to-canary cluster (anti-FP coverage) |
| **Stratified similarity** | 15 | 1-2 per archetype with operator-annotated expected top-3 |
| **Total** | **~50** | Manageable upfront + annual rotation; covers all 10 archetypes |

#### Canary set (20)
Theranos, Wirecard, FTX, Luckin Coffee, Enron, Adelphia, Tyco, Toshiba, WorldCom, SVB, Lehman, AIG, Cisco-2000, Pets.com, WeWork, Hyzon, Cazoo, Evergrande, Didi, JCPenney.

#### Known-good set (15)
PLTR (anti-Theranos), NVDA (anti-Cisco-2000), AMZN 2001 (anti-Pets.com), MSFT 2014-16 (anti-tech-decay), JPM 2008 (anti-Lehman), MS Sep-Oct 2008 (anti-SVB), WFC 2016-2024 (anti-governance), Snap (anti-zero-vote), BABA (anti-regulatory-edict), CMG 2015-18 (anti-retail-decline), LLY (anti-patent-cliff), DPZ 2010 (anti-brand-erosion), ABBV (anti-biotech-blockbuster-cliff), XOM 2014-20 (anti-energy-debt-cycle), ABNB (anti-recent-IPO-collapse).

#### Stratified similarity set (15)
1-2 cases per archetype with operator-annotated expected top-3 counterfactual matches.

### 10 newly-surfaced structural archetypes

A. Funding-side monoculture (vs asset-side); B. Long-fuse vs short-fuse failure timescales; C. Ch.22 retail (re-bankruptcy in 2-3y); D. SPAC sponsor-favorable + 90%+ redemptions; E. Real-estate Ponzi-like; F. Regulatory-edict (sovereign/political); G. Single-product → multi-franchise pivot (success); H. Captured-board looting vs founder-control RPT extraction; I. Long auditor tenure + dismissed short-seller; J. M&A-driven blowups.

### Reference catalog vs test fixtures

The other ~125 cases researched but not in test set become **reference material** stored in `L3-d-counterfactuals/` (extended catalog) and `L3-survivors/` with structured features. Used by Q2 mechanical-similarity retrieval; NOT gating tests; NOT validated against calibration metrics. Annual rotation pulls from this reservoir into the active 50-case test set.

This separates **the catalog the system retrieves from** (large, comprehensive ~125 cases) from **the test set that gates calibration** (small, manageable ~50 cases).

### Pre-launch validation gate

Before v0.1 launches:
1. Build 50-case test set
2. Run mechanical similarity
3. Validate: canary coverage 100% / FP rate <15% / NDCG@3 ≥0.7 / all audit-log fields populated / HMAC signature validates
4. If any target missed → recalibrate weights or refine catalog feature schema
5. Operator final approval before launch

### Library deliverables for Q6 (committed)

7 files in `.claude/references/empirical/data-sources/`:
- `Q6-Section5-rec-sys-calibration.md` (4 calibration domains synthesis input)
- `Q6-Section5-threat-intel-matching.md`
- `Q6-Section5-legal-precedent-retrieval.md`
- `Q6-Section5-medical-cbr.md`
- `Q6-Section5-synthesis.md` (calibration architecture)
- `Q6-Section5-test-set-expanded.md` (12-subagent research; 175-case proposal)
- Plus 10 lane files (Q6-Section5-test-cases-*) covering 12 sector/archetype dimensions

---

## 8. Section 5 — fully closed

All 6 questions locked:
- **Q1** Three-stage hybrid scorer (mechanical → LLM with info-isolation → linter)
- **Q2** Mechanical structural-feature retrieval + LLM narrative on top-3 (NOT embeddings)
- **Q3** 3-LLM iterative-consensus catalog extraction with 5-iteration cap
- **Q4** Event-driven adds + automated drift detection on every add
- **Q5** L3 archetype is orthogonal tag, NOT mode-classification input
- **Q6** Calibration architecture (Bayesian shrinkage; 3-trigger drift; misgrounding mitigation) + lean ~50 test set

Sections 1-5 fully locked. Sections 6-8 pending (L4 view-refresh discipline; L5+L6 technical execution + multi-horizon disposition; coexistence with v2-final).

Ready for Section 6 (L4 — View-refresh discipline review).
