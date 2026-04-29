# Q1 Section 5 Synthesis — P3 Hybrid Scorer Architecture

**Date:** 2026-04-29
**Purpose:** Synthesize 3 parallel research subagents (LLM rubric design + mechanical scoring + hybrid systems) into the final P3 hybrid-scorer architecture for L3 candidate evaluation.

**Predecessors:**
- 3 lane files at `.claude/references/empirical/data-sources/Q1-Section5-{llm-rubric-design,mechanical-scoring,hybrid-systems}.md`
- Section 5 Q1 lock = (c) hybrid (operator confirmed)

---

## 1. Three-stage architecture (locked)

```
Candidate name + facts
        ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 1 — Mechanical gate (deterministic, fast, cheap)      │
│                                                              │
│ 1A. Multiplicative knockout (any fail → REJECT):            │
│     - Fraud-signature 3+/6 (charismatic CEO + board lacks   │
│       domain + novel accounting + secrecy + dismissed bear  │
│       + related-party; missing data = flag raised)          │
│     - Era-fit binary (right-thing-right-decade match)       │
│                                                              │
│ 1B. Additive equal-weight 4-criterion Tier-A composite      │
│     (among Stage-1A survivors):                             │
│     - Founder/CEO duration ≥15 years                        │
│     - Per-share-value primary management metric             │
│     - ROIIC > 15% sustained                                 │
│     - Pivot-creates-multi-bag (not original product)        │
│     Threshold: ≥3 = A / 2 = WATCH / ≤1 = REJECT             │
│     Missing data: LEI-style proportional re-weighting       │
└─────────────────────────────────────────────────────────────┘
        ↓ (only if A or WATCH passes)
┌─────────────────────────────────────────────────────────────┐
│ STAGE 2 — LLM rubric (info-isolated from Stage 1)            │
│                                                              │
│ Per-pattern SINGLE-ATTRIBUTE LLM call (NEVER bundle):       │
│                                                              │
│ For each L3-e pattern requiring qualitative judgment:       │
│   - Forced JSON output:                                     │
│     {                                                        │
│       rating: "LOW" | "MEDIUM" | "HIGH" → {0.0, 0.5, 1.0}  │
│       confidence: float                                     │
│       evidence_quotes: [verbatim with source_id]            │
│       rationale: ≤2 sentences                               │
│       defer_to_human: bool                                  │
│       tie_break_applied: bool                               │
│     }                                                        │
│   - Required verbatim evidence citation                     │
│     (no quote → defaults to LOW)                            │
│   - Self-consistency: N=5 samples at temp=0.7,              │
│     median rating; dispersion = empirical confidence        │
│   - Locked behavioral anchors per level (Moody's pattern)   │
│                                                              │
│ Patterns scored:                                             │
│   - L3-e #4 pivot-creates-multi-bag                         │
│   - L3-e #20 right-thing-right-decade                       │
│   - L3-e #5 founder equity stake (qualitative parts)        │
│   - L3-e #16 narrative reflexivity (CONTESTED)              │
│   - Other contestable patterns                              │
│                                                              │
│ INFORMATION ISOLATION: Stage 2 LLM sees only candidate      │
│ facts + L3 lane reference. **Does NOT see Stage 1 outputs.**│
│ (Anchoring-bias mitigation per O'Leary 2025; CALM framework)│
└─────────────────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 3 — Deterministic linter                               │
│                                                              │
│ Cross-checks LLM output against Stage-1-known-true facts:   │
│ - Did LLM contradict Stage-1 mechanical fact?               │
│ - Did LLM rate HIGH without evidence quote?                 │
│ - Did LLM exhibit round-number defaulting?                  │
│ - Did LLM exhibit position bias / verbosity bias?           │
│                                                              │
│ Flags contradictions; sets `contradictions_with_stage1`     │
│ field; routes to operator review if confidence-conflict     │
└─────────────────────────────────────────────────────────────┘
        ↓
   COMPOSITE OUTPUT
   - Stage-1 numeric score (multiplicative + composite)
   - Stage-2 per-pattern ratings (LOW/MEDIUM/HIGH)
   - Stage-3 lint flags
   - Disagreement bool
   - Final decision: PROCEED to P4 / WATCH / PASS
```

---

## 2. Why sequential rule-then-LLM (not parallel)

Hybrid systems subagent's analysis: **sequential is correct when one component is binary eligibility floor and the other is qualitative**. Parallel is correct only when both produce continuous probabilistic signals.

For our case:
- Stage 1 (rules) is a binary eligibility floor — same role as Upstart's credit-score floor before underwriting LLM
- Stage 2 (LLM) is qualitative pattern recognition — different work
- They do different jobs; sequential is the right composition
- Most names fail cheap rule gate; don't pay LLM cost for rejects

Parallel architecture (PayPal Radar / Stripe Radar pattern) is the right answer **only** when both components produce continuous probabilistic signals on the same dimension. Revisit at v0.5+ if rule engine evolves beyond binary.

---

## 3. Why information isolation (LLM blind to Stage-1 output)

Critical architectural choice. Hybrid-systems subagent finding:
- Anchoring bias: when LLM sees rule output, LLM tends to defer to it OR over-correct against it (O'Leary 2025; arXiv 2506.22316; CALM framework)
- Rule output is already high-confidence deterministic — feeding to LLM adds noise without information

Operationally:
- Stage 2 LLM rubric prompt does NOT include Stage 1 mechanical results
- Stage 1 evaluator and Stage 2 evaluator share the candidate facts only, not each other's conclusions
- Stage 3 linter is the "judge" that compares — separately and after both have produced output

This matches Section 1 finding "PMSupervisor must NOT force consensus" + L8 "judge stays outside the debate."

---

## 4. Single most important LLM mitigation pattern

LLM rubric subagent surfaced: **per-dimension single-attribute call + structured-output schema + verbatim-evidence-citation requirement**. This one combination simultaneously addresses 4 documented LLM failure modes:

| Failure mode | Mitigation |
|---|---|
| Anchoring | One dimension per call — no bleed-over from previous dim |
| Verbosity bias | Structured rationale forced ≤2 sentences |
| Sycophancy | Must cite verbatim evidence — can't fabricate to please |
| Auditability | Rationale + quotes + source_id are traceable |

Everything else (multi-model ensembling, post-hoc Wasserstein calibration, drift monitoring) is incremental on top.

---

## 5. Single most-cited hybrid-system failure mode

Hybrid-systems subagent: **LLM elaborating on planted/contaminated input data — 83% error-elaboration rate** (PMC 12318031, multi-model assurance study on clinical decision support).

If Stage-1-known-fact data is wrong, LLM doesn't catch it — instead elaborates on the wrong fact with confident reasoning. Mitigation:
- Stage 1 must validate input integrity (rule engine output is structurally checkable)
- Stage 3 linter cross-checks LLM output against Stage-1-known-true facts
- If LLM contradicts a Stage-1 mechanical fact → operator review required

---

## 6. Audit trail structure (locked)

Per-stage structured log with versioning at every layer:

```json
{
  "candidate_id": "uuid",
  "stage1_rule": {
    "rule_engine_version": "1.0.0",
    "parameters_version": "ref to parameters table version",
    "rules_evaluated": [
      { "rule_id": "fraud_signature", "outcome": "PASS", "flags_raised": 1, "of": 6 },
      { "rule_id": "era_fit", "outcome": "PASS", "explanation": "..." },
      { "rule_id": "tier_a_composite", "outcome": "A", "score": 3, "of": 4, "missing": [] }
    ],
    "gate_outcome": "PROCEED",
    "fail_reason": null
  },
  "stage2_llm": {
    "model_id": "claude-opus-4-7",
    "model_version": "claude-opus-4-7-1m",
    "prompt_version": "L3-rubric-v0.1.0",
    "rubric_version": "L3-rubric-v0.1.0",
    "saw_rule_output": false,  // enforced isolation flag
    "patterns_scored": [
      {
        "pattern_id": "L3-e-4-pivot-creates-multi-bag",
        "rating": "HIGH",
        "confidence": 0.85,
        "evidence_quotes": [
          { "quote": "...", "source_id": "..." }
        ],
        "rationale": "...",
        "defer_to_human": false,
        "self_consistency": { "samples": 5, "median": "HIGH", "unanimous": true }
      }
    ]
  },
  "stage3_linter": {
    "linter_version": "1.0.0",
    "findings": [],
    "contradictions_with_stage1": []
  },
  "composition": {
    "final_decision": "PROCEED_TO_P4",
    "disagreement": false,
    "resolution_policy_applied": null,
    "human_review_required": false
  }
}
```

Versioning every layer enables `/parameters-review` to detect cohort-vs-cohort drift and isolate whether drift originates from rule changes, prompt changes, or model upgrades. Frontier-model output drift is empirically larger than smaller-model drift (arXiv 2511.07585: GPT-OSS-120B at 12.5% consistency vs Granite-3-8B at 100%) — making versioning load-bearing.

---

## 7. Calibration & validation plan

### Mechanical (Stage 1)
- Walk-forward backtest in existing `src/backtesting/framework.py`
- Test: do Stage-1 PROCEED candidates outperform Stage-1 REJECT candidates over T+1 to T+3 years (multi-bag horizon)?
- Embargo + DSR validation per existing framework

### LLM rubric (Stage 2)
- Gold-standard test set: 30-50 historical companies per pattern, balanced HIGH/MEDIUM/LOW
- Decontaminated cutoffs (don't train on test)
- Validation metrics:

| Metric | Target |
|---|---|
| Cohen's kappa vs human gold standard | ≥0.61 (substantial; McHugh 2012) |
| HIGH-confidence empirical hit rate | ≥80% |
| MEDIUM hit rate | ≥60% |
| LOW hit rate | ≥40% |
| ECE (Expected Calibration Error) | <0.10 |
| Cross-model kappa (Claude vs GPT-4) | ≥0.61 |
| Position-bias flip-rate | <10% |
| Self-consistency unanimous on HIGH | ≥80% |

- Re-run on every prompt change AND every model upgrade
- Quarterly drift watch: 10 production samples re-rated by human; compute kappa vs production
- `defer_to_human` is first-class output, not fallback

### Linter (Stage 3)
- Catches: round-number defaulting, position bias, verbosity bias, contradiction-with-Stage-1
- Flag → operator review (logged to S2 counterfactual ledger)

---

## 8. Implementation handoff for skill-builder

**Where this lives:**
- Mechanical scorer: `src/skills/p3-name-discovery/mechanical_gate.py` (deterministic Python)
- LLM rubric: `src/skills/p3-name-discovery/llm_rubric.py` (structured prompt templates + JSON schema validation)
- Linter: `src/skills/p3-name-discovery/linter.py` (deterministic checks)
- Schema versions: `parameters` Postgres table

**Engineering analogy:** like designing a payment fraud-detection pipeline (Stripe Radar pattern) — rule gate first for cheap rejects; ML/LLM for nuanced cases; linter for output validation; full audit trail per request.

---

## 9. What this synthesis answers

| Question | Answer |
|---|---|
| Which architecture: parallel or sequential? | Sequential (binary gate + qualitative judgment do different work) |
| Should LLM see rule output? | NO (information isolation; anchoring-bias mitigation) |
| Mechanical scoring: additive or multiplicative? | BOTH in two-stage pipeline (multiplicative knockout + additive composite) |
| Equal-weight or optimized weights at Stage 1B? | Equal-weight (consistent with Section 3 Q2 lock; Smith-Wallis 2009 small-sample finding) |
| Single LLM call or per-pattern? | Per-pattern (anchoring-bias mitigation) |
| Output schema for LLM? | Forced JSON with rating/confidence/evidence_quotes/rationale/defer_to_human |
| Required evidence citation? | YES (no quote = defaults to LOW; sycophancy mitigation) |
| Self-consistency? | N=5 at temp=0.7; median rating; dispersion = confidence |
| Audit trail? | Per-stage structured log with version every layer |
| Calibration approach? | Mechanical: walk-forward backtest. LLM: 30-50 gold-standard cases per pattern; Cohen's kappa ≥0.61 |

---

**End of synthesis. Section 5 Q1 architecture fully locked.**
