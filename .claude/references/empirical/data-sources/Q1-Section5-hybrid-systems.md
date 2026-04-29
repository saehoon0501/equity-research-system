# Hybrid rule-based + LLM systems — architectural patterns

**Research scope:** Production hybrid systems combining deterministic rule-based scoring with LLM-judgment scoring, for high-stakes decision-making contexts. Synthesized for P3 (name discovery phase) two-stage scoring design.

**Date:** 2026-04-29
**Author:** subagent (Section 5, Q1 hybrid systems sub-research)

---

## Section A — Curated sources (tier-labeled)

Tiers: **A** = peer-reviewed / regulatory / vendor primary engineering blog. **B** = reputable trade publication / well-cited analysis. **C** = practitioner blog / vendor marketing (use only for descriptive claims, not load-bearing evidence).

### Production hybrid systems (case-study sources)

1. **[Stripe — How we built it: Stripe Radar](https://stripe.dev/blog/how-we-built-it-stripe-radar)** — Tier A. Primary engineering blog: rules + ML + DNN architecture, 100ms latency budget.
2. **[Stripe — Using AI to create dynamic, risk-based Radar rules](https://stripe.com/blog/using-ai-dynamic-radar-rules)** — Tier A. ML-suggested rules, human-in-the-loop, hybrid approach.
3. **[ByteByteGo — How Stripe Detects Fraudulent Transactions Within 100 ms](https://blog.bytebytego.com/p/how-stripe-detects-fraudulent-transactions)** — Tier B. Architecture deep-dive (XGBoost → DNN migration).
4. **[PayPal — Rules-Based vs Machine Learning in Fraud Protection](https://www.paypal.com/us/brc/article/fraud-prevention-with-rules-vs-machine-learning)** — Tier A. Vendor-primary on hybrid layered detection.
5. **[PayPal Tech Blog — Deploying Large-scale Fraud Detection ML at PayPal](https://medium.com/paypal-tech/machine-learning-model-ci-cd-and-shadow-platform-8c4f44998c78)** — Tier A. Shadow-mode deployment platform engineering.
6. **[PayPal — Machine Learning Fraud Detection Technologies](https://www.paypal.com/us/brc/article/payment-fraud-detection-machine-learning)** — Tier A. Risk Score architecture, allowlist/blocklist/reviewlist filter design.
7. **[Litera/Kira — Foundations of ML-Based Contract Review](https://kirasystems.com/resources/buyers-guide/foundations-of-machine-learning-contract-review-software/)** — Tier A. ML vs rules architecture choices in contract review.
8. **[Cohubicol — Casetext's CoCounsel through the lens of the Typology](https://www.cohubicol.com/blog/casetext-cocounsel-openai-typology/)** — Tier B. Multi-model + retrieval architecture analysis.
9. **[ZenML LLMOps DB — Casetext: From Early Testing to Production Deployment](https://www.zenml.io/llmops-database/building-an-ai-legal-assistant-from-early-testing-to-production-deployment)** — Tier B. CoCounsel architecture, eval harness, trust team.
10. **[Abridge — Pioneering the Science of AI Evaluation](https://www.abridge.com/ai/science-ai-evaluation)** — Tier A. Vendor-primary on medical logic guardrails + evidence-anchored notes.
11. **[arXiv 2512.04118 — Patient Safety Risks from AI Scribes](https://arxiv.org/html/2512.04118)** — Tier A (peer-reviewed, recent). End-user feedback failure-mode evidence.
12. **[Upstart — How AI Drives More Affordable Credit Access](https://info.upstart.com/how-ai-drives-more-affordable-credit-access)** — Tier B. 2,500-variable hybrid model + rule eligibility floor.
13. **[FDIC — Upstart RFI submission on AI in lending](https://www.fdic.gov/system/files/2024-06/2021-rfi-financial-institutions-ai-3064-za24-c-032.pdf)** — Tier A (regulatory). Rule-floor + ML-overlay underwriting structure.
14. **[Epic — Artificial Intelligence](https://www.epic.com/software/ai/)** — Tier A vendor-primary. CDS-Hooks rules + AI overlay.
15. **[PMC 12482788 — Rule-Based CDSS Scoping Review](https://pmc.ncbi.nlm.nih.gov/articles/PMC12482788/)** — Tier A peer-reviewed.
16. **[PMC 12318031 — Multi-model assurance: LLMs vulnerable to adversarial hallucination in clinical decision support](https://pmc.ncbi.nlm.nih.gov/articles/PMC12318031/)** — Tier A. **83% error elaboration rate** (single most cited failure mode).
17. **[GitHub Changelog — Linter integration with Copilot code review (public preview)](https://github.blog/changelog/2025-11-20-linter-integration-with-copilot-code-review-now-in-public-preview/)** — Tier A. Deterministic linter + LLM hybrid in production.
18. **[GitHub Changelog — Copilot code review: AI reviews that see the full picture](https://github.blog/changelog/2025-10-28-new-public-preview-features-in-copilot-code-review-ai-reviews-that-see-the-full-picture/)** — Tier A. ESLint + CodeQL + LLM blend.
19. **[ComplyAdvantage — AML/KYC Screening & Monitoring](https://complyadvantage.com/aml-kyc-screening-monitoring/)** — Tier A vendor-primary. Rules-based screening + LLM match-review review tier.
20. **[Persona — KYC/AML use case](https://withpersona.com/use-case/compliance/kyc-aml)** — Tier C vendor marketing. Rule-screen + LLM document analysis flow.

### Architectural & theoretical sources

21. **[Irving, Christiano, Amodei (2018) — AI safety via debate](https://arxiv.org/abs/1805.00899)** — Tier A. Theoretical foundation: rules-as-judge between LLMs.
22. **[Anthropic — Constitutional AI: Harmlessness from AI Feedback](https://www.anthropic.com/research/constitutional-ai-harmlessness-from-ai-feedback)** — Tier A. Rules-as-constitution constraining LLM judgment.
23. **[Anthropic — Constitutional Classifiers](https://www.anthropic.com/research/constitutional-classifiers)** — Tier A. Rule-based classifier guarding LLM outputs.
24. **[Wikipedia — Neuro-symbolic AI](https://en.wikipedia.org/wiki/Neuro-symbolic_AI)** — Tier B. Survey of integration approaches.
25. **[ScienceDirect — Review of neuro-symbolic AI integrating reasoning and learning](https://www.sciencedirect.com/science/article/pii/S2667305325000675)** — Tier A peer-reviewed survey.
26. **[arXiv 2410.02736 — Justice or Prejudice? Quantifying Biases in LLM-as-a-Judge](https://arxiv.org/html/2410.02736v1)** — Tier A. CALM framework, 12 bias types.
27. **[arXiv 2506.22316 — Evaluating Scoring Bias in LLM-as-a-Judge](https://arxiv.org/html/2506.22316v1)** — Tier A. Empirical anchoring in scoring.
28. **[arXiv 2601.08654 — RULERS: Locked Rubrics and Evidence-Anchored Scoring](https://arxiv.org/pdf/2601.08654)** — Tier A. Evidence-anchored checklists.
29. **[arXiv 2604.16339 — Semantic Consensus: Conflict Detection for Multi-Agent LLMs](https://arxiv.org/abs/2604.16339)** — Tier A. **Failure rates 41–86.7% in production multi-agent.**
30. **[arXiv 2504.00180 — Contradiction Detection in RAG Systems](https://arxiv.org/html/2504.00180v1)** — Tier A. Context-memory vs context-context conflicts.
31. **[arXiv 2511.07585 — LLM Output Drift: Cross-Provider Validation for Financial Workflows](https://arxiv.org/abs/2511.07585)** — Tier A. **Empirical: GPT-OSS-120B 12.5% consistency at T=0.0** vs Granite-3-8B 100%.
32. **[Giskard — Sycophancy in LLMs](https://www.giskard.ai/knowledge/when-your-ai-agent-tells-you-what-you-want-to-hear-understanding-sycophancy-in-llms)** — Tier B. Sycophant collapse mechanics.
33. **[Guardrails AI — Deterministic Validators as GenAI Scorers](https://guardrailsai.com/blog/guardrails-mlflow)** — Tier A vendor-primary. Composing deterministic + judge-based scoring.
34. **[MLflow — Deterministic Safety Checks with Guardrails AI](https://mlflow.org/blog/mlflow-guardrails-scorers)** — Tier A. Production composition pattern.
35. **[Promptfoo — LLM Rubric documentation](https://www.promptfoo.dev/docs/configuration/expected-outputs/model-graded/llm-rubric/)** — Tier A vendor docs. Rubric anchoring API.
36. **[arXiv 2410.02916 — LLM Safeguard is a Double-Edged Sword: False-Positive DoS](https://arxiv.org/html/2410.02916v3)** — Tier A. Over-conservative-gate failure mode evidence.
37. **[arXiv 2512.01037 — When Safety Blocks Sense: Semantic Confusion in LLM Refusals](https://www.arxiv.org/pdf/2512.01037)** — Tier A. False Rejection Rate metrology.
38. **[JFrog ML / Qwak — Shadow deployment vs canary release](https://www.qwak.com/post/shadow-deployment-vs-canary-release-of-machine-learning-models)** — Tier B. Operational pattern reference.
39. **[MarkTechPost — Safely Deploying ML Models: A/B, Canary, Interleaved, Shadow](https://www.marktechpost.com/2026/03/21/safely-deploying-ml-models-to-production-four-controlled-strategies-a-b-canary-interleaved-shadow-testing/)** — Tier B. Comparative survey.
40. **[FINOS AIR Governance — Agent Decision Audit and Explainability](https://air-governance-framework.finos.org/mitigations/mi-21_agent-decision-audit-and-explainability.html)** — Tier A (consortium standard). Audit-trail field schema.
41. **[Swept AI — The Compliance-Ready AI Audit Trail field spec](https://www.swept.ai/post/compliance-ai-audit-trail-specification-insurance)** — Tier B. Concrete schema example.
42. **[SSRN 5315021 — An Anchoring Effect in Large Language Models (O'Leary, 2025)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5315021)** — Tier A peer-reviewed. Empirical anchoring in LLM judgment.

---

## Section B — Production case studies

### B1. Stripe Radar — fraud detection

**Architecture (sequential with parallel scoring):**
- ML model (since mid-2022, pure DNN; previously XGBoost + DNN ensemble) produces a Risk Score on every payment.
- Custom rules layer runs alongside / on top: merchants author rules in a DSL ("`risk_score > 75 AND :card_country: != :ip_country:` → block").
- Issuer signals (CVC, postal code response) join the rule context in real time.
- Hard gates: rules can `block`, `request_3ds`, or `allow`. ML produces a continuous risk score.

**Disagreement resolution:** Rules win — merchant-authored rules can override the ML score (block low-risk-scored payment, or allow high-risk if a custom rule says so). Stripe added "AI-suggested dynamic rules" that propose new rules from ML patterns, but a human approves before activation.

**Latency budget:** 100ms end-to-end including rules evaluation.

**Source:** [stripe.dev/blog/how-we-built-it-stripe-radar](https://stripe.dev/blog/how-we-built-it-stripe-radar), [stripe.com/blog/using-ai-dynamic-radar-rules](https://stripe.com/blog/using-ai-dynamic-radar-rules).

### B2. PayPal — fraud detection

**Architecture (parallel scoring, hybrid composition):**
- Adaptive ML engine emits a Risk Score from card details, buyer info, purchasing patterns, device fingerprint.
- Filters (rules) classify decisions into Allowlist / Blocklist / Reviewlist.
- Real-time stream processing on Kafka/Flink.
- ML and rules run in parallel; outputs combine via a policy engine.

**Disagreement resolution:** Documented as "rules for compliance, ML for adaptability" — i.e., **rules veto for compliance reasons; ML can flag for review even when rules pass**. Reviewlist is the soft-flag bucket where humans intervene.

**Engineering pattern:** PayPal's tech blog documents a CI/CD platform where new models are deployed in **shadow mode** (predictions logged, not actioned) before being promoted. This is a direct production reference for our use case.

**Source:** [paypal.com/us/brc/article/fraud-prevention-with-rules-vs-machine-learning](https://www.paypal.com/us/brc/article/fraud-prevention-with-rules-vs-machine-learning), [PayPal Tech Blog on shadow platform](https://medium.com/paypal-tech/machine-learning-model-ci-cd-and-shadow-platform-8c4f44998c78).

### B3. Kira (Litera) — contract review

**Architecture (ML-first, narrow rules):**
- Originally pure ML for clause detection (1,400+ clauses, 40+ areas).
- Rule-based fallback for highly-structured fields (dates, parties, governing law).
- Now adds GenAI layer for summarization on top of the established ML extraction.

**Important contrast:** Kira's marketing explicitly contrasts ML against "rule-based" competitors. Rule-based competitors do exist (some vendors use manually-written rules). The lesson: **rules dominate where structure is high (date format, entity names); ML/LLM dominates where semantic understanding is needed (clause meaning).**

**Disagreement:** Not formally documented; in practice the ML model is sole authority for clause detection. GenAI summarizer reads ML extractions.

**Source:** [kirasystems.com/resources/buyers-guide/foundations-of-machine-learning-contract-review-software](https://kirasystems.com/resources/buyers-guide/foundations-of-machine-learning-contract-review-software/).

### B4. Casetext CoCounsel — legal AI

**Architecture (retrieval + multi-model LLM):**
- Parallel Search (transformer-based concept retrieval) provides grounding.
- Multi-model: routes between Claude, GPT-5, GPT-4o, Mistral by task.
- 4,000 hours of attorney-driven trust-team fine-tuning + 30,000 legal-question eval set.

**Hybrid pattern here is "retrieval-as-rule":** the deterministic component is the legal database lookup (Parallel Search), not classical if/then rules. The LLM is constrained to cite from retrieved sources.

**Disagreement:** Hallucination on cite is a known failure; mitigation is the deterministic retrieval enforcing grounding rather than a separate rule veto.

**Source:** [cohubicol.com/blog/casetext-cocounsel-openai-typology](https://www.cohubicol.com/blog/casetext-cocounsel-openai-typology/), [zenml.io/llmops-database/building-an-ai-legal-assistant-from-early-testing-to-production-deployment](https://www.zenml.io/llmops-database/building-an-ai-legal-assistant-from-early-testing-to-production-deployment).

### B5. Abridge — medical AI scribe

**Architecture (LLM with evidence anchoring + medical-logic rules):**
- LLM generates clinical notes from ambient conversation audio.
- Every word in the generated note is **timestamp-linked back to source audio** — deterministic citation.
- "Medical logic guardrails" constrain the LLM (drug-dose ranges, allergen-conflict checks).

**Disagreement:** The clinician is the final arbiter — UX forces fact-check before sign-off. Audit trail (audio + timestamp) is the resolution mechanism.

**Documented failure modes (arXiv 2512.04118):** medication and treatment safety concerns surface in real end-user feedback. The deterministic timestamp anchor mitigates but does not eliminate.

**Source:** [abridge.com/ai/science-ai-evaluation](https://www.abridge.com/ai/science-ai-evaluation), [arXiv 2512.04118](https://arxiv.org/html/2512.04118).

### B6. Upstart — credit underwriting

**Architecture (rule-floor + ML-overlay):**
- Hard rule floor: credit score ≥ 300 (state-dependent), basic eligibility checks.
- ML model with 2,500+ variables produces creditworthiness score above the floor.
- Rule failures are hard-gates (you cannot be approved); ML score determines pricing/limit above the floor.

**Disagreement:** Rule wins on the floor; ML is sole authority above it. This is the cleanest "**hard-gate-then-LLM/ML**" pattern in the survey.

**Outcomes:** "101% more applicants approved than traditional methods" — the ML model improves approvals without lowering the rule floor. Lesson: **the rule floor is non-negotiable; the ML adds upside, never downside.**

**Source:** [info.upstart.com/how-ai-drives-more-affordable-credit-access](https://info.upstart.com/how-ai-drives-more-affordable-credit-access), [FDIC RFI submission](https://www.fdic.gov/system/files/2024-06/2021-rfi-financial-institutions-ai-3064-za24-c-032.pdf).

### B7. Epic — clinical decision support

**Architecture (CDS-Hooks rules + AI advisory):**
- CDS-Hooks: rule engine triggers contextual alerts at clinical workflow points.
- AI overlay (Cosmos data → predictive risk scoring) advises clinicians.
- AI Validation Suite (recently announced) — health systems audit AI outcomes locally.

**Disagreement:** Clinician override is required; AI is "advisory" by FDA design (it is not a Tier-2 device that bypasses clinician review). Rules are deterministic flag/alert; AI adds risk-score prediction.

**Source:** [epic.com/software/ai](https://www.epic.com/software/ai/), [PMC 12482788](https://pmc.ncbi.nlm.nih.gov/articles/PMC12482788/).

### B8. ComplyAdvantage / Persona — KYC/AML

**Architecture (rule screen + LLM document review):**
- Stage 1 (rule): screen against sanctions lists, PEP, adverse-media. Match generates a hit.
- Stage 2 (LLM): match review — LLM analyzes documents and adjudicates whether the hit is a true match (same person) or a false positive (similar name).
- Behavioral rules monitor transaction patterns separately.

**Disagreement:** False-positive rate on name matches is high (common names). LLM review reduces analyst workload; the rule still produces the alert. This is **rule-first sequential** with LLM as a downstream filter, not as an overrider.

**Source:** [complyadvantage.com/aml-kyc-screening-monitoring](https://complyadvantage.com/aml-kyc-screening-monitoring/), [withpersona.com/use-case/compliance/kyc-aml](https://withpersona.com/use-case/compliance/kyc-aml).

### B9. GitHub Copilot Code Review

**Architecture (deterministic linters + LLM semantic review):**
- ESLint, Pylint, CodeQL, PMD run as deterministic detectors — they catch syntax, security, and rule-pattern issues.
- LLM (Copilot model) reads the linter output as context and adds semantic review (logic bugs, design smells, "did you mean X").
- LLM can suggest auto-applied fixes for safe corrections; risky ones are human-reviewed.

**Pattern:** The LLM **sees the linter output** — explicitly anchoring on it. GitHub's framing: "blends LLM detections, agentic tool calling, and deterministic engines." This is a **production reference for the "LLM-sees-rule-output" pattern** with explicit anchoring trade-off accepted in exchange for context-richer reviews.

**Source:** [github.blog/changelog/2025-11-20-linter-integration-with-copilot-code-review-now-in-public-preview](https://github.blog/changelog/2025-11-20-linter-integration-with-copilot-code-review-now-in-public-preview/), [github.blog/changelog/2025-10-28-new-public-preview-features-in-copilot-code-review](https://github.blog/changelog/2025-10-28-new-public-preview-features-in-copilot-code-review-ai-reviews-that-see-the-full-picture/).

---

## Section C — Architectural patterns

### C1. Sequential vs parallel ordering

Three observed orderings in production:

| Pattern | Examples | Trade-off |
|---|---|---|
| **Rule first → LLM** | Upstart (rule floor), ComplyAdvantage (screen → LLM review), Stripe (ML produces score; rules then evaluate) | Cheap (LLM only runs if rule passes/flags); rule output anchors LLM (anchoring risk) |
| **Parallel** | PayPal (rules + ML in parallel; policy engine combines), GitHub Copilot (linters + LLM semantic, both run, results merged) | Independence (no anchoring); detect disagreement; ~2× cost |
| **LLM first → Rule** | Abridge (LLM generates note, rule check on drugs/allergens after), most "linter on LLM output" patterns | LLM unconstrained = creative; rules veto unsafe outputs |

**Most-cited pattern in high-stakes production:** Parallel for high-stakes decisions where disagreement is information; sequential rule-first when the rule is a hard eligibility floor (Upstart, KYC).

### C2. Hard-gate vs soft-flag

- **Hard gate (veto):** Rule failure terminates the pipeline. Examples: Upstart credit-score floor, KYC sanctions-list match (must clear before any LLM review), ComplyAdvantage transaction blocking, FDA Tier-2 device gates.
- **Soft flag (review queue):** Rule failure routes to elevated review. Examples: PayPal Reviewlist, ComplyAdvantage match-review queue, code-review CI warnings.

**Design principle from Guardrails AI / MLflow blog:** "Use deterministic validators for **gating** + judge-based metrics for **qualitative scoring**." The two roles are complementary, not competitive — gates are pass/fail, scores are continuous.

### C3. LLM-sees-rule-output vs independent (anchoring trade-off)

This is the central architectural question for our P3.

**Evidence for "LLM should not see rule output":**
- O'Leary 2025 (SSRN 5315021): empirical anchoring effect in LLMs — when given a prior numerical score, LLM judgments cluster toward it.
- arXiv 2506.22316 (Scoring Bias): "when the model is inherently uncertain, strong linguistic or tonal cues act as an anchor."
- arXiv 2410.02736 (CALM): bandwagon-effect bias confirmed; LLMs shift judgments when told "X% of people prefer Y."
- Multi-agent practice: "self-critique suffers from anchoring bias: the agent that generated an answer has already committed."

**Evidence for "LLM should see rule output":**
- GitHub Copilot Code Review explicitly feeds linter output into the LLM prompt — accepted trade-off for context-rich review.
- Stripe Radar's AI rule suggestions read ML score patterns; humans review.
- RAG systems unavoidably condition LLM on retrieved context.

**Resolution from RULERS (arXiv 2601.08654):** evidence-anchored rubrics ("locked rubrics" + cite-the-evidence requirement) reduce score drift and anchoring. The trick is not "hide the rule output" but **force the LLM to cite independent evidence** for its score.

**Operational rule of thumb (synthesized):** if the rule is a **hard binary gate**, don't show its output to the LLM (waste of tokens; either gate passes or pipeline ends). If the rule produces **continuous signal**, decide by the question: does the LLM need it for context, or is it redundant with what the LLM independently sees?

### C4. Output structure: structured + narrative

Universal pattern across all production systems:

```
{
  "structured": {
    "rule_outputs": {...},       # deterministic gate outcomes
    "llm_score": float,          # rubric-graded
    "llm_score_components": {...} # subscores per rubric dimension
  },
  "narrative": "free-text LLM rationale citing evidence",
  "audit": {
    "rule_versions": [...],
    "model_id": "claude-opus-4-7",
    "prompt_version": "v0.3",
    "evidence_citations": [...]
  }
}
```

This composition lets downstream systems (linter, parameters-review) inspect deterministic fields without parsing prose, while preserving the qualitative judgment for humans.

---

## Section D — Failure modes documented in production hybrid systems

### D1. LLM elaborates on planted errors (most-cited failure)

**Source:** PMC 12318031 (Multi-model assurance, clinical decision support).
**Finding:** When given clinical vignettes containing a single planted fake lab value, sign, or disease, leading LLMs **repeated or elaborated on the error in up to 83% of cases**.
**Lesson:** LLM cannot reliably catch its own input contamination. A deterministic check on input data integrity is mandatory before LLM scoring.

### D2. Sycophant collapse

**Source:** Giskard knowledge base; reproduced in arXiv 2601.15652.
**Finding:** LLM generates reasoning trace to **support already-chosen output** rather than critique it. Once anchored on an answer, the model rationalizes rather than reconsiders.
**Lesson:** Don't ask the LLM "is this score right?" after showing it the score. Ask it to score independently, then compare.

### D3. Multi-agent failure rates

**Source:** arXiv 2604.16339 (Semantic Consensus paper).
**Finding:** Production multi-agent LLM systems show **failure rates of 41–86.7%**, primarily from specification and coordination issues ("Semantic Intent Divergence").
**Lesson:** Hybrid systems where rule and LLM are loosely coupled drift apart over time without a shared schema and joint evals.

### D4. Output drift across model versions

**Source:** arXiv 2511.07585 (LLM Output Drift, 2025).
**Finding:** GPT-OSS-120B achieves only **12.5% output consistency** across runs at T=0.0; smaller models (Granite-3-8B, Qwen2.5-7B) achieve 100%. Larger frontier models are *less* deterministic.
**Lesson:** Calibration drift is real and asymmetric — bigger models drift more. Rules stay fixed but LLM judgments shift, requiring versioned eval sets and regression checks on every model upgrade.

### D5. Over-conservative gates (false-positive blocking)

**Source:** arXiv 2410.02916 (LLM Safeguard is a Double-Edged Sword); arXiv 2512.01037 (When Safety Blocks Sense).
**Finding:** Adversarial fine-tuning or aggressive rules can be exploited as denial-of-service: legitimate inputs get blocked. False Rejection Rate is a tracked metric.
**Lesson:** Track FRR (false-reject rate) on every rule-gate change. A rule that blocks too much is as bad as one that passes too much.

### D6. Rule-LLM disagreement without resolution policy

**Source:** Industry practitioner reports across PayPal, Stripe, ComplyAdvantage.
**Finding:** When rule says block and LLM says approve (or vice versa), unspecified resolution policy → inconsistent behavior. Reviewlist queues balloon; review SLA collapses.
**Lesson:** Resolution policy must be specified upfront and audited.

### D7. Anchoring on prior context

**Source:** SSRN 5315021 (O'Leary 2025), arXiv 2506.22316.
**Finding:** Showing the LLM a prior score (rule output, peer score, "the consensus is X") biases its judgment toward that score.
**Lesson:** If parallel-running rule and LLM, do not feed rule score to LLM unless absolutely needed. If sequential rule-first, force LLM to **cite evidence independently** before reading the rule output.

### D8. Disagreement between context and parametric memory

**Source:** arXiv 2504.00180 (Contradiction Detection in RAG).
**Finding:** Two conflict types in RAG/hybrid systems: (1) context-memory conflict (retrieved context vs LLM training); (2) context-context conflict (retrieved sources disagree). Models default to parametric (training) memory under uncertainty.
**Lesson:** Force LLM to **state when its judgment differs from rule output** as a structured field, not buried in prose.

---

## Section E — Recommended architecture for our P3 case

### E1. Composition

```
Stage 1: Rule-based gate (Tier-A binary checks, fraud signature)
   └─ if FAIL → reject, log gate_outcome=FAIL_<reason>, exit pipeline
   └─ if PASS → continue (do not pass score forward)

Stage 2: LLM narrative scoring (independent, evidence-cited)
   └─ Input: same source data the rule saw, NOT the rule output
   └─ Output: structured rubric scores + narrative + cited evidence

Stage 3: Linter (post-LLM-write deterministic check)
   └─ Catches LLM failure modes (hallucinated tickers, missing citations,
      contradictions with Stage-1-known-true facts)

Stage 4: Compose final record
   └─ {rule_outcomes, llm_scores, llm_narrative, linter_findings, audit}
```

### E2. Disagreement resolution policy

When Stage-1 PASS but Stage-3 linter catches an LLM contradiction with a Stage-1 fact (e.g., LLM narrative says "fraud signature is mild" but rule found a Tier-A red flag):

- **Rule wins on factual matters** (fraud signature, era fit, eligibility).
- **LLM wins on qualitative judgment** (pattern recognition strength, conviction).
- **Disagreement is logged as a structured field**, not silently resolved. Operator sees `disagreement: true; rule=X; llm=Y; resolution=rule-wins-on-fact`.

This mirrors Upstart (rule floor non-negotiable, ML adds upside) and PayPal (rules veto for compliance, ML adapts).

### E3. Audit-trail structure (recommended)

Field schema synthesized from FINOS AIR Governance, Swept AI insurance spec, and MLflow Guardrails composition:

```yaml
trace_id: <uuid>
timestamp: <iso8601>
ticker: <symbol>
phase: P3-name-discovery

stage1_rule:
  rule_engine_version: <semver>
  parameters_version: <semver>           # ties to /parameters-review
  rules_evaluated:
    - rule_id: tier_a_binary_check_1
      input_hash: <sha256>
      outcome: PASS | FAIL
      evidence_pointer: <data-source-cite>
  gate_outcome: PASS | FAIL
  fail_reason: <string|null>

stage2_llm:
  model_id: claude-opus-4-7
  model_version: <date>
  prompt_version: <semver>
  rubric_version: <semver>
  saw_rule_output: false            # KEY: enforce independence
  scores:
    pattern_recognition: <0-10>
    era_fit: <0-10>
    conviction: <0-10>
  narrative: <string>
  evidence_citations: [<doc-id>, ...]

stage3_linter:
  linter_version: <semver>
  failure_modes_checked: [...]
  findings: [{rule, severity, evidence}]
  contradictions_with_stage1: [...]   # populated only if any

composition:
  final_decision: ADD_WATCHLIST | REJECT | WATCH
  disagreement: <bool>
  resolution_policy_applied: <string>
  human_review_required: <bool>
```

### E4. Versioning and recalibration

- **Rules (deterministic)**: versioned in the parameters table; canary rollout per implementation-sequencing.md.
- **LLM (probabilistic)**: pin model_id + prompt_version. On model upgrade, run regression on a frozen eval set (per arXiv 2511.07585 — drift is real). Store `model_id` and `prompt_version` in every audit record so /parameters-review can detect cohort-vs-cohort drift.
- **Shadow mode for changes**: when adding/changing a rule or prompt, run new+old in parallel, log both outputs, do not act on the new for N memos. This is the PayPal pattern (CI/CD with shadow platform).
- **A/B testing**: only after shadow mode passes; canary at 10% → 50% → 100% with regression metrics gating each promotion.

### E5. Calibration drift defense

- Quarterly: re-run a frozen "canonical decisions" eval set through the current LLM. If outcomes drift > tolerance vs previous quarter on the same inputs, freeze the model version and investigate.
- Per arXiv 2511.07585: the larger the model, the more drift — Opus drifts more than smaller deterministic models. Budget for this.
- Rule changes: never silently. Every rule version carries a changelog and is git-tracked.

---

## Section F — Specific recommendation: Sequential (rule-then-LLM), with strict information-isolation

### F1. Recommendation

**Rule-engine runs BEFORE the LLM, sequentially, with the LLM blind to the rule's continuous output.**

The rule produces **only a binary gate result** (PASS / FAIL with reason). On FAIL, pipeline exits. On PASS, the LLM scores **independently** on the same source data the rule saw — but is **not given the rule's output** as context. After both run, a deterministic linter (Stage 3) reconciles.

### F2. Why sequential (not parallel)

1. **Cost.** Parallel doubles LLM token spend on every name. Most failures will be at the rule gate (Tier-A binary checks are designed to catch obvious disqualifiers cheaply). Don't pay LLM token costs to score a name we'll reject anyway.

2. **The rule is a hard eligibility gate, not a scorer.** Mirroring Upstart's credit-score floor: the rule's job is "this name is or isn't eligible to be considered." That is a binary verdict the LLM doesn't help with. The LLM's job is "given a candidate that passes the floor, how strong is it?" — a continuous judgment the rule doesn't help with. The two are doing different work.

3. **Rule output is high-confidence; LLM doesn't need it.** Tier-A binary checks are deterministic by design — there's nothing for the LLM to "re-evaluate" about a fraud signature. Showing the LLM the rule output adds anchoring risk (D7) with no benefit.

### F3. Why blind (LLM does not see rule output)

1. **Anchoring (O'Leary 2025, arXiv 2506.22316).** Showing the LLM the rule's score biases its independent judgment.

2. **Sycophant collapse (D2).** If LLM sees rule said "PASS, low concern," it tends to write a consistent narrative even if the data warrants skepticism.

3. **Independent signals are evidence; correlated signals are not.** Per the AI-safety-via-debate intuition (Irving et al. 2018): two genuinely independent reasoners disagreeing is informative; two reasoners where one anchors on the other are effectively one reasoner.

### F4. Why the post-write linter (Stage 3) is essential

The linter catches:
- Hallucinated tickers, dates, financial figures that contradict Stage-1-known-true facts.
- Internal contradictions in the LLM narrative.
- Missing required citations.
- Score / narrative inconsistency (narrative says "high conviction" but conviction score is low).

This is the GitHub Copilot pattern (linter on output) and the Abridge pattern (timestamp anchor on output) — **deterministic check on LLM output is the cheapest, most reliable failure-mode catch**.

### F5. Where parallel WOULD be the right call (for completeness)

If/when the rule-engine becomes itself probabilistic (e.g., we replace Tier-A binary checks with a soft fraud-probability score), then parallel becomes appropriate — both LLM and rule produce continuous signals; their disagreement is information; the policy engine combines them. This is the PayPal/Stripe state. We are not there yet; the rule is binary, so sequential is correct now. **Revisit when the rule engine evolves.**

### F6. Single most-cited failure mode (for the report)

**LLM elaborating on planted/contaminated input data — 83% rate in clinical decision support (PMC 12318031).** This is why Stage-1 must validate input integrity *before* LLM scoring, and why Stage-3 linter must verify LLM outputs against Stage-1-known-true facts. It is also why the LLM should be given source data, not summaries — summaries can hide contamination.

---

## Notes for /parameters-review and downstream skills

- Every audit record carries `rule_engine_version`, `parameters_version`, `prompt_version`, `model_id`, `model_version`, `rubric_version`, `linter_version`. /parameters-review can slice decisions by any of these and detect cohort drift.
- Disagreement events (`disagreement: true`) are first-class — they should be sampled for human review with priority over agreement events.
- Shadow-mode runs produce `mode: shadow` records that do not affect operational state but feed regression metrics.
- The A/B test infrastructure should compare rule-only, LLM-only, hybrid on the same input cohort to validate the hybrid is doing real work (not just a more expensive version of one component).
