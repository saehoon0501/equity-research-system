# Section 5 Consensus — L3 / P3 (Successful-Company Patterns + Counterfactuals)

**Date:** 2026-04-29 (in progress)
**Session:** Q&A consensus review with operator (saehoon0501) — Section 5 of the consensus-documentation-protocol series
**Status:** Partially locked — Q1 / Q2 closed; further sub-questions pending
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

## 4. Pending sub-questions for Section 5 closure

- **Q3** — How are the structural feature vectors extracted from L3-d catalog? (Manual annotation vs LLM-extracted vs hybrid)
- **Q4** — How does L3 catalog get updated when new failures or successes emerge? (Annual cadence vs event-driven; who annotates new entries)
- **Q5** — Mode-classification using L3 archetypes (B / B' / C placement). Section 1 locked the AI classification rule on quantitative thresholds; does L3 inform mode placement beyond that?
- **Q6** — Calibration: how do we validate that mechanical similarity finds the RIGHT counterfactuals? (Gold-standard test set?)

---

## 5. What's locked so far in Section 5

- Hybrid 3-stage scorer architecture (mechanical → LLM with information isolation → linter)
- Counterfactual catalog used via mechanical structural-feature retrieval + LLM narrative on top-3 (NOT embeddings)
- Versioned audit trail with disagreement flag first-class
- Calibration metrics (Cohen's kappa ≥ 0.61, ECE < 0.10, position-bias flip-rate < 10%, etc.)

Sections 1-4 fully locked. Section 5 partially locked. Sections 6-8 pending.

---

**Section 5 partial consensus committed. Q3-Q6 to follow.**
