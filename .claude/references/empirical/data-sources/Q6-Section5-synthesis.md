# Q6 Section 5 Synthesis — Counterfactual Similarity Calibration (Cross-Domain)

**Date:** 2026-04-29
**Purpose:** Synthesize 4 parallel research subagents (recommender/IR + threat-intel + legal precedent + medical CBR) into the calibration architecture for the L3 counterfactual mechanical-similarity step locked in Q2.

---

## 1. Convergent findings across 4 domains

### Test set design — all 4 converge on stratified curated test sets

| Domain | Test set design |
|---|---|
| IR/recsys | 15 cases stratified 5+5+5 (clear / ambiguous / designed-near-miss) |
| Threat-intel | 3-set: canaries (3-5) + known-good (8-15) + training-DB-not-test |
| Medical CBR | FDA GMLP P3 representative-data — span sector × era × failure-mode × cap |
| Legal | 3-SME majority-vote stratified sampling; per-instance rubrics |

**Convergence: ~25 total test cases, stratified across coverage axes; 32-case catalog itself is training set NOT test set.**

### Weight optimization at small N — universal "don't"

| Domain | Recommendation |
|---|---|
| IR/recsys | Bayesian shrinkage toward equal-weights (Diebold-Pauly); never gradient-LTR until n≥500 |
| Threat-intel | K-of-N constraint conjunctions (boolean-mechanical only) |
| Medical CBR | Cost-asymmetric thresholds, not learned weights |
| Legal | Per-instance rubrics; mechanical features + LLM rerank |

**Convergence: at N<100, equal-weight or shrinkage-protected weights beat optimization. Same architectural principle as Section 3 Q2 lock — already in our system.**

### Drift monitoring — multi-trigger + closed taxonomy

| Domain | Drift monitoring |
|---|---|
| IR/recsys | Annual gold-standard refresh (5-of-15 cases/year) |
| Threat-intel | 3-trigger: PM-override sightings ≥3, regime-shift events, annual audit |
| Medical CBR | FDA P10 postmarket monitoring + distribution-shift detection |
| Legal | Shepard's-style closed-taxonomy treatment classifications |

**Convergence: drift monitoring is multi-signal + auto-surfacing for operator review (matches our Q4 lock).**

### Multiple metrics, never single score

| Domain | Metrics |
|---|---|
| IR/recsys | NDCG@3 primary + Precision@3 + MRR + Recall@10 sanity floor |
| Threat-intel | Separate FP-rate-on-known-good + canary-coverage + alert-fatigue tracking |
| Medical CBR | Steyerberg ABCD (calibration-in-large / slope / discrimination / decision curve) |
| Legal | Existence + faithfulness + relevance separately (Stanford RegLab) |

**Convergence: report a metric vector, never collapse to F-score.**

### Cost asymmetry — favor sensitivity at retrieval, recover specificity downstream

| Domain | Pattern |
|---|---|
| Medical CBR | Screening-then-confirmatory architecture |
| Threat-intel | Tiered review (mechanical → analyst) |
| IR | Query expansion at retrieval; precision-tuning at rerank |
| Legal | Multiple-citator parity check |

**Convergence: same architectural pattern as our Q1 lock — Stage 1 mechanical (high sensitivity) → Stage 2 LLM rerank (specificity recovery) → Stage 3 linter.**

### Most-cited failure mode — confidence without grounding

| Domain | Dominant failure mode |
|---|---|
| IR | Test-set contamination via weight-tuning feedback loop |
| Threat-intel | Signature drift + alert fatigue + tightening-creates-blind-spots |
| Medical CBR | Synthetic case bases (Watson for Oncology failure) |
| Legal | **Misgrounding** — citation exists but case doesn't say what system claims (Lexis+ AI 17%, Westlaw AI 33%, GPT-4 43% per Stanford RegLab) |

**Convergence: confidence-without-grounding is the universal failure mode.** Mitigation: pinpoint-citation enforcement + periodic hand-audit.

---

## 2. Recommended Q6 lock — Calibration architecture

### Test set design (3-set, ~25 cases total)

```yaml
test_sets:
  canaries:
    size: 5
    cases: [Enron, Theranos, Wirecard, Luckin, FTX]
    purpose: "Pipeline-validation; every variant MUST flag these"
    stored_at: "tests/canaries/"
    separate_from: "32-case signature DB"
    metric: "Canary-coverage = 100% required (any miss = system broken)"

  known_good:
    size: 10
    cases: [historically-validated multi-baggers at superficially-failure-like conditions]
    examples: ["NVDA in 2024 (extreme valuation but real product)",
               "AAPL in 2018 (capex high, China risk)",
               "MA in 2013 (regulatory overhang)",
               "TSLA in 2020 (concentration risk + governance concerns)",
               ...]
    purpose: "FP-rate calibration; must NOT trigger fraud signature kill"
    metric: "FP rate on known-good set = HEADLINE calibration metric"

  stratified_similarity:
    size: 10
    cases: [historical cases with operator-annotated expected top-3 counterfactual matches]
    purpose: "Precision@3 / NDCG@3 measurement"
    coverage_axes: [sector, era, failure-mode, market-cap]
    metric: "NDCG@3, Precision@3, Recall@10"
```

### Evaluation metrics (vector, not single score)

| Metric | Target | Source |
|---|---|---|
| Canary coverage | 100% | All 5 canaries flagged |
| FP-rate on known-good set | <15% | At-most 1-2 of 10 mis-flagged |
| NDCG@3 on stratified set | ≥0.7 | Position-discounted relevance |
| Precision@3 on stratified set | ≥70% | ≥2 of 3 expected counterfactuals appear in mechanical top-3 |
| Recall@10 on stratified set | ≥90% | Sanity floor |
| Misgrounding rate (LLM outputs) | <10% | Quarterly hand-audit; tied to verbatim-evidence rule |
| Inter-rater kappa (operator vs system) | ≥0.61 | Substantial agreement (McHugh 2012) |

Bootstrap 95% CIs on all metrics.

### Weight calibration mechanism

**v0.1 (n ≤ 20):** Bayesian shrinkage λ ≈ 1.0 — effectively equal-weight initial similarity formula:
```
similarity = 0.4*hamming_fraud + 0.2*jaccard_sector + 0.2*jaccard_era + 0.2*hamming_business_model
```

**v0.5 (n = 30-50):** λ ≈ 0.8 — heavy shrinkage with marginal data influence

**v1.0 (n ≥ 100):** λ ≈ 0.5 — moderate shrinkage; consider feature trimming (Wang-Hyndman 2023 binary-inclusion via DM-test)

**Never:** gradient-based LTR (LambdaMART, RankNet, BPR) until n ≥ 500. Per Burges 2010 + Chapelle-Chang 2011 — empirically destructive at small samples.

**Per-instance rubrics adapted from legal-tech LRAGE:** each of 32 counterfactuals carries its own structural-similarity rubric definition (HIGH = matches archetype X; MEDIUM = matches some features; LOW = different archetype). Stage 2 LLM uses per-counterfactual rubric, not global.

### Drift monitoring (3-trigger, adapted from MISP + Shepard's)

```
trigger_1_pm_override_sightings:
  rule: "≥3 consecutive same-direction operator overrides on same signature → review"
  action: "Auto-surface to /parameters-review with override evidence"

trigger_2_regime_shift_events:
  rule: "Section 3 Q3 BOCPD escalates regime change → review regime-tied signatures"
  action: "Mark signatures as 'review-pending' until operator confirms"

trigger_3_annual_audit:
  rule: "Jan 1 each year, all signatures reviewed against latest year of evidence"
  action: "Replace 5 of 15 stratified test cases (drift-resistant test set rotation)"
```

Closed-taxonomy treatment classifications (Shepard's-style):
- `confirmed` — signature still active; latest evidence supports
- `partially-confirmed` — signature active but features modified
- `weakened-by-new-evidence` — signature active but probability/weight reduced
- `reclassified-target-to-kill` — added to kill-criteria templates as discredit-post-2020
- `superseded` — replaced by newer signature
- `formally-retired` — no longer active

### Audit trail (matches FDA GMLP P9 transparency)

Per P3 invocation:
```yaml
candidate_id: uuid
retrieval_log:
  candidate_features: { ... }
  catalog_similarity_scores: [ per-counterfactual ]
  top_3_retrieved: [ counterfactual_ids ]
  similarity_method: "weighted_hamming_jaccard_v0.1.0"
  weight_version: "params_v3"
llm_rubric_log:
  per_counterfactual:
    - cf_id: theranos
      rating: HIGH
      confidence: 0.85
      evidence_quotes: [...]
      rubric_version: "L3-rubric-theranos-v1"
operator_override:
  occurred: false
audit_signature: HMAC of above
```

### Misgrounding mitigation (most-cited failure mode)

- **Pinpoint-cite enforcement** (already in Q1 lock — strengthened): every LLM rating must cite verbatim text from candidate facts AND from counterfactual feature description. No quote = defaults to LOW.
- **Quarterly hand-audit** of random sample (10 retrieval cases / quarter): operator manually verifies the LLM's claim against the source material. Misgrounding rate logged; if >10% sustained, prompt revision required.
- **Multi-evaluator parity check** (legal-tech adoption): when LLM rates HIGH, run a second LLM cross-check (different prompt frame); flag disagreements for operator review. Cost-bounded — only fires on HIGH ratings.

### Pre-launch validation gate

Before v0.1 launches with the calibration system live:
1. Build the 25-case test set (5 canaries + 10 known-good + 10 stratified)
2. Run mechanical similarity on test set
3. Validate metrics meet targets (canary coverage 100%; FP rate <15%; NDCG@3 ≥0.7)
4. If any target missed → recalibrate weights manually OR refine catalog feature schema
5. Operator final approval before launch

Engineering analogy: like CI/CD gating tests — must pass test suite before deployment.

---

## 3. Implementation handoff

For the engineer building P3:
- Code in: `src/skills/p3-name-discovery/calibration/`
- `test_set.yaml` — 25 cases with expected-output annotations
- `metrics.py` — NDCG@3, Precision@3, Recall@10, FP-rate-on-known-good, misgrounding-rate
- `drift_monitor.py` — 3-trigger model
- `audit_log.py` — per-invocation structured log
- Weight versioning via existing `parameters` Postgres table

**Pre-launch:** run `pytest tests/p3_calibration_gate.py`. Must pass:
- Canary coverage 100%
- FP rate <15%
- NDCG@3 ≥0.7
- All audit-log fields populated
- HMAC signature validates

Post-launch: drift monitoring runs on `/daily-monitor` cycle.

---

## 4. Cross-references to locked architecture

- Q1 hybrid scorer (3-stage mechanical → LLM → linter) — calibration scheme aligns
- Q2 mechanical Hamming/Jaccard — equal-weight default consistent with shrinkage approach
- Q3 catalog feature extraction — informs which features get calibration weights
- Q4 event-driven recalibration — matches drift-monitoring multi-trigger design
- Section 3 Q2 (Diebold-Pauly shrinkage) — same mechanism applied here
- Section 1 PMSupervisor must NOT force consensus — informs misgrounding mitigation (independent evaluators)
- L8 multi-agent debate findings on persona diversity — supports multi-evaluator parity check

---

**Q6 calibration architecture fully specified. Ready for operator lock.**
