# LLM rubric design for hybrid scoring systems

**Scope:** the LLM-narrative-scoring portion of the P3 (name discovery) hybrid scoring system. This subagent does NOT cover the deterministic mechanical-gate side. It covers ONLY the qualitative/cross-era patterns where rules don't reduce cleanly (e.g., "pivot creates the multi-bag," "founder skin-in-the-game," "right thing in right decade").

**Goal:** design an LLM rubric that is (1) consistent across runs (low variance), (2) auditable (traceable WHY a rating was given), (3) calibrated (HIGH/MEDIUM/LOW maps to actual hit rates), and (4) resistant to LLM failure modes.

**Today's date:** 2026-04-29.

---

## Section A — Curated sources (tier-labeled)

Tier convention: **T1 = peer-reviewed academic foundational**, **T2 = academic but newer / pre-print well-cited**, **T3 = high-quality industry / production engineering write-up**, **T4 = regulatory or rating-agency methodology**, **T5 = practitioner / fund methodology**.

### Foundational LLM-as-judge papers

1. **[T1] Zheng et al. 2023 — "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena"** (NeurIPS 2023). The seminal paper. Documents three core biases (position, verbosity, self-enhancement) plus limited-reasoning failure mode. Reports GPT-4 reaches >80% agreement with human evaluators (the same level humans agree with each other). https://arxiv.org/abs/2306.05685
2. **[T1] Liu et al. 2023 — "G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment"** (EMNLP 2023). Defines the "form-filling + chain-of-thought" rubric paradigm: feed Task Introduction + Evaluation Criteria → ask LLM to generate CoT eval steps → re-prompt with the steps to issue ratings → refine with token-level probabilities. Spearman 0.514 with humans on summarization. https://arxiv.org/abs/2303.16634
3. **[T1] Chiang & Lee 2023 — "Can Large Language Models Be an Alternative to Human Evaluations?"** (ACL 2023). Empirical guideline: rate-explain or explain-rate ordering produces higher correlation with human ratings than rate-only. https://aclanthology.org/2023.acl-long.870/
4. **[T1] Chan et al. 2024 — "ChatEval: Towards Better LLM-based Evaluators through Multi-Agent Debate"** (ICLR 2024). Multi-agent referee team with **diverse role prompts** (homogeneous personas degrade performance). Already in the L8 lane in our project. https://arxiv.org/abs/2308.07201
5. **[T1] Liang et al. 2022 — "Holistic Evaluation of Language Models" (HELM)**. Top-down taxonomy approach: define the space of scenarios × metrics first; only then evaluate. Multi-metric (7 metrics across 16 scenarios). https://arxiv.org/abs/2211.09110
6. **[T1] Wang et al. 2023 — "Self-Consistency Improves Chain of Thought Reasoning"** (ICLR 2023). The sample-and-marginalize procedure: sample N reasoning paths, take majority answer. +17.9% on GSM8K, +12.2% on AQuA. The single most cited variance-reduction technique. https://arxiv.org/abs/2203.11171
7. **[T1] Bai et al. 2022 — "Training a Helpful and Harmless Assistant with RLHF"** (Anthropic). HHH Evaluation framework (Helpful, Honest, Harmless). 86% PM agreement vs 75% human. https://arxiv.org/abs/2204.05862

### Bias-documentation literature

8. **[T1] Sharma et al. 2023 — "Towards Understanding Sycophancy in Language Models"** (ICLR 2024). Five SOTA assistants consistently sycophantic across four free-form generation tasks. Both humans and preference models prefer convincingly-written sycophantic responses over correct ones a non-negligible fraction of the time. Mitigations: synthetic-data finetuning, activation steering, debate. https://arxiv.org/abs/2310.13548
9. **[T2] "Anchoring Bias in Large Language Models: An Experimental Study"** (Springer J. Comp. Soc. Sci. 2025). Forecasts significantly influenced by prior mention of high or low values; chain-of-thought and "ignore previous" prompts have limited and varying effectiveness. https://arxiv.org/abs/2412.06593
10. **[T2] Saito et al. — "Verbosity Bias in Preference Labeling by Large Language Models"**. Documents that LLMs prefer longer answers in creative writing tasks; discrepancy with human verbosity preferences. https://openreview.net/pdf?id=magEgFpK1y
11. **[T2] "Self-Preference Bias in LLM-as-a-Judge"** (2024/2025). LLMs assign higher evaluations to outputs with lower perplexity; advanced capability is uncorrelated or negatively correlated with low self-preference. Structured multi-dimensional decomposition reduces self-preference bias by 31.5% on average. https://arxiv.org/html/2410.21819v2
12. **[T2] "Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge"**. Quantifies position bias and order-permutation mitigation. https://arxiv.org/html/2406.07791v9
13. **[T2] "Large Language Models are Inconsistent and Biased Evaluators"** (2024). Documents central-tendency bias on broad scales — argues for narrow (3-5 level) Likert scales with concrete behavioral anchors. https://arxiv.org/html/2405.01724v1

### Rubric-engineering literature

14. **[T1] Hashemi et al. 2024 — "LLM-Rubric: A Multidimensional, Calibrated Approach"** (ACL 2024). Manual rubric → multiple-choice questions per dimension → LLM produces probability distribution per question → small feed-forward NN with judge-specific + judge-independent params learns to map dimension distributions → overall judgment. RMSE 0.396 (synthetic) / 0.422 (real); 2× improvement over uncalibrated. Microsoft repo. https://arxiv.org/abs/2501.00274
15. **[T2] "RULERS: Locked Rubrics and Evidence-Anchored Scoring for Robust LLM Evaluation"** (Jan 2026). Compiles rubrics into versioned immutable bundles; enforces structured decoding with deterministic evidence verification + lightweight Wasserstein-based post-hoc calibration. +0.17 QWK over pure inference prompts, high adversarial robustness. https://arxiv.org/abs/2601.08654
16. **[T2] "Autorubric: A Unified Framework for Rubric-Based LLM Evaluation"** (2026). https://arxiv.org/html/2603.00077
17. **[T2] "A Survey on LLM-as-a-Judge"** (2024-2026, ongoing). https://arxiv.org/html/2411.15594v6
18. **[T2] "Overconfidence in LLM-as-a-Judge: Diagnosis and Confidence-Driven Solution"** (2025). LLM judges systematically express higher confidence than empirical accuracy supports. Introduces TH-Score metric for confidence-accuracy alignment. https://arxiv.org/html/2508.06225v2
19. **[T2] "Calibrating LLM Judges: Linear Probes for Fast and Reliable Uncertainty Estimation"** (Dec 2025). Brier-loss linear probes on hidden states; ~10× compute savings vs alternatives. https://arxiv.org/html/2512.22245
20. **[T2] "How to Correctly Report LLM-as-a-Judge Evaluations"** (Nov 2025). https://arxiv.org/html/2511.21140v3

### Production engineering write-ups

21. **[T3] OpenAI Evals framework documentation** — split checks into outcome / process / style / efficiency goals; rubric-graders score on 1–7; structured outputs are essential. https://platform.openai.com/docs/guides/evaluation-best-practices and https://github.com/openai/evals
22. **[T3] Evidently AI — "LLM-as-a-judge: a complete guide to using LLMs for evaluations"**. https://www.evidentlyai.com/llm-guide/llm-as-a-judge
23. **[T3] Confident AI / DeepEval documentation**. Rate-categorical-integer with very clear per-category descriptions; force JSON output schema. https://www.confident-ai.com/blog/why-llm-as-a-judge-is-the-best-llm-evaluation-method
24. **[T3] Promptfoo "LLM as a Judge Evaluation Guide"**. https://www.promptfoo.dev/docs/guides/llm-as-a-judge/
25. **[T3] Monte Carlo Data — "LLM-as-Judge: 7 Best Practices & Evaluation Templates"**. https://www.montecarlodata.com/blog-llm-as-judge/
26. **[T3] Andrey Chauzov — "Mitigating positional bias: the swapping technique"**. Reports observed position-bias rate reduced from 68% → 51%, tie rate 8% → 19% with order-swap. https://avchauzov.github.io/blog/2025/llm-judge-position-bias-swapping/
27. **[T3] Sebastian Sigl — "The 5 Biases That Can Silently Kill Your LLM Evaluations"**. https://www.sebastiansigl.com/blog/llm-judge-biases-and-how-to-fix-them/
28. **[T3] LangChain — "How to Calibrate LLM-as-a-Judge with Human Corrections"**. https://www.langchain.com/articles/llm-as-a-judge
29. **[T3] GoDaddy — "Calibrating Scores of LLM-as-a-Judge"**. https://www.godaddy.com/resources/news/calibrating-scores-of-llm-as-a-judge
30. **[T3] Kinde — "LLM-as-a-Judge, Done Right: Calibrating, Guarding & Debiasing"**. https://www.kinde.com/learn/ai-for-software-engineering/best-practice/llm-as-a-judge-done-right-calibrating-guarding-debiasing-your-evaluators/

### Inter-rater reliability / calibration

31. **[T1] McHugh 2012 — "Interrater reliability: the kappa statistic"** (PMC). Cohen's interpretation cutoffs: ≤0 none, 0.01–0.20 slight, 0.21–0.40 fair, 0.41–0.60 moderate, 0.61–0.80 substantial, 0.81–1.00 almost-perfect. https://pmc.ncbi.nlm.nih.gov/articles/PMC3900052/
32. **[T2] "Investigation of the Inter-Rater Reliability between Large Language Models and Human Raters in Qualitative Analysis"** (Aug 2025). https://arxiv.org/abs/2508.14764

### Production rubrics in finance / decision-support (tier-labeled separately)

33. **[T4] Moody's Corporates Rating Methodology** (Nov 2021). Scorecard approach with explicit per-sub-factor anchor descriptions by alpha rating category (Aaa, Aa, A, Baa, ...). Qualitative factors include management quality, governance, financial controls, regulatory exposure. https://ratings.moodys.com/api/rmc-documents/356428
34. **[T4] FINRA Rule 2241 — Research Analysts and Research Reports**. Mandates: (a) consistent rating system across all reports; (b) plain-English definition of each rating; (c) disclosure of % of all-rated names in each bucket; (d) disclosure of % of investment-banking-conflict names in each bucket. https://www.finra.org/rules-guidance/rulebooks/finra-rules/2241
35. **[T5] Pershing Square SPARC acquisition criteria** — "simple, predictable, free-cash-flow-generative, minimal capital-markets dependency, large cap, attractive valuation, exceptional management." Concrete pre-stated qualitative anchors. https://pershingsquaresparcholdings.com/acquisition-criteria/
36. **[T5] Yartseva 2025 — "The Alchemy of Multibagger Stocks"** (CAFÉ Working Paper No. 33, Birmingham City U.). Empirical multi-bagger patterns: out-of-favour value stocks, low analyst coverage at start (mean 3.1 → 7.3), simple/scalable models, strong management. https://www.open-access.bcu.ac.uk/16180/1/The%20Alchemy%20of%20Multibagger%20Stocks%20-%20Anna%20Yartseva%20-%20CAFE%20Working%20Paper%2033%20(2025).pdf
37. **[T5] BoI AXA "The Anatomy of a Multi-Bagger"** — practitioner methodology emphasizing >90% weight to management quality. https://www.boimf.in/docs/default-source/insighthub/boi-axa-research/the-anatomy-of-a-multi-bagger--am.pdf
38. **[T5] Stockopedia — "Makings of a Multibagger"**. https://assets.stockopedia.com/books/makings-of-a-multibagger.pdf

Total surveyed: **38 sources** across foundations, biases, rubric engineering, production engineering, calibration, and finance methodology.

---

## Section B — Rubric design principles (synthesized)

### B.1 Structure: dimensions × scales

- **Decompose into independent dimensions**, not a single global rating. Single-rating prompts collapse multiple judgments into one scalar and lose interpretability. The LLM-Rubric (Hashemi et al. 2024) and HELM (Liang et al. 2022) approaches both make this canonical: define the space first (taxonomy of dimensions), then evaluate each.
- **Predict ONE attribute per generation call** (Anchoring-bias mitigation literature). Do not ask for {coherence, consistency, fluency, relevance} in a single call — the answer to dimension 1 anchors dimensions 2–4. For our system: each L3-e pattern (founder duration, pivot, equity stake, fraud signature, era-fit) gets its own LLM call.
- **Use narrow ordinal scales (3–5 levels)** with concrete behavioral anchors. Broad scales (1–10) trigger LLM central-tendency bias; everything clusters at 6–7. Recommended for our use case: a 3-level ordinal {LOW, MEDIUM, HIGH} mapped to {0.0, 0.5, 1.0} — matches Moody's scorecard alpha-bucket logic and FINRA's three-bucket rating taxonomy.
- **Force structured JSON output** with a fixed schema: `{rating: enum, evidence_quotes: [{source, quote}], rationale: string, confidence: enum}`. Reduces ambiguity, enables programmatic auditing (Comet, Cleanlab, Confident AI all converge on this).

### B.2 Anchor descriptions per rating level

Every rating level needs a **plain-English behavioral anchor** of what evidence/observation would warrant that rating — not just a label. From Twine's rubric guide and the Moody's scorecard pattern:

> ❌ Bad: "HIGH = strong founder skin-in-the-game"
> ✅ Good: "HIGH = founder/CEO direct equity stake ≥5% of shares outstanding, sustained for ≥10 years, with no material selling in the last 3 years (verified via Form 4 / DEF 14A). MEDIUM = stake 2–5% OR sustained 5–10 years OR mixed selling pattern. LOW = stake <2% OR <5 years sustained OR material selling > 25% of position in trailing 3 years."

This pattern is what RULERS (2026) calls "locked rubrics" — the anchor descriptions are versioned and immutable across runs.

### B.3 Required-evidence-citation

- Every non-LOW rating must include **verbatim quotes with source identifiers** (e.g., 10-K page, DEF 14A, news article). LLM-Rubric and RULERS both enforce this.
- The rubric prompt should explicitly say: *"Cite at least one direct quotation from the supplied evidence pack supporting the rating. If you cannot cite, the rating defaults to LOW."*
- Define **what evidence the LLM may use**. Tight evidence rules (only the supplied pack; no external knowledge) reduce disagreement (Twine 2026). For our system: only the L3-e dossier + 10-K/DEF 14A excerpts; no general LLM knowledge.

### B.4 Self-consistency / multi-sampling

- Wang et al. 2023's sample-and-marginalize: sample N=5 paths at temperature 0.7, take the majority rating. This is the variance-reduction workhorse.
- For ordinal ratings, use **median** instead of majority (more robust to outlier samples).
- Track and surface the **inter-sample agreement** — if 5 samples produce {HIGH, HIGH, HIGH, MEDIUM, HIGH}, confidence = HIGH-confident; if {HIGH, HIGH, MEDIUM, MEDIUM, LOW}, confidence = LOW-confident. The dispersion IS the confidence signal.
- ChatEval-style multi-agent debate (Chan et al. 2024) is overkill for a single-pattern evaluation; use it only for the synthesis step that combines patterns into a final P3 verdict.

### B.5 Tie-breaker rules

When LLM judgment is on the boundary:
1. **Default-to-conservative tie-break**: ambiguous cases default to the LOWER rating (HIGH↔MEDIUM ambiguity → MEDIUM; MEDIUM↔LOW → LOW). This mirrors credit-rating committees' practice of preferring the more conservative bucket on close calls.
2. **If evidence pack is sparse, force LOW + flag for human review.** The rubric should produce a `defer_to_human=true` flag rather than guess.
3. **If two patterns give contradictory directional readings** (e.g., founder-duration HIGH but founder-equity LOW), do NOT auto-resolve in the LLM rubric — return the conflict to the deterministic gate or the human PM.

---

## Section C — LLM failure modes documented

### C.1 Sycophancy (Sharma et al. 2023)

- Five SOTA assistants exhibit sycophancy across four free-form generation tasks.
- Both humans AND preference models prefer convincingly-written sycophantic responses over correct ones a non-negligible fraction of the time — this is a deep training-data artifact, not a prompt issue.
- **Mechanism**: when a user-stated opinion is in the prompt, the LLM tilts its judgment toward that opinion. Highly relevant for our system if a CompanyDeepDive memo bullishly characterizes a CEO and the rubric LLM reads that memo before scoring.

### C.2 Position bias (Zheng et al. 2023; "Judging the Judges" 2024)

- Most LLM judges favor the FIRST position; for some pairwise tasks GPT-4 shows ~40% position bias (decision flips when answers swapped).
- Less directly relevant to single-pattern scoring, BUT highly relevant if our rubric ever does pairwise comparison (e.g., "is this name more like Microsoft 1995 or like Cisco 2000?").

### C.3 Verbosity bias (Saito et al.; Zheng et al. 2023)

- LLM judges prefer longer, more verbose answers — even when the shorter answer is more correct.
- For our system: if evidence packs vary in length across companies, longer packs may produce systematically higher scores. Length must be normalized OR the rubric must instruct "do not let length influence rating."

### C.4 Self-enhancement / self-preference bias

- LLMs assign higher scores to lower-perplexity outputs — i.e., to outputs that "look like what they would have written." Documented across 20+ mainstream LLMs.
- Particularly relevant if the same LLM that wrote the CompanyDeepDive memo also scores it. **Use a different model family for scoring than for memo-writing** (e.g., Sonnet writes memo, Opus scores; or vice versa).

### C.5 Anchoring (Anchoring Bias 2024)

- Forecasts significantly influenced by prior mention of high/low values in the prompt.
- For our system: any "example rating" few-shot in the prompt will pull subsequent ratings toward it. Few-shots must be **balanced across rating levels** (one HIGH example, one MEDIUM, one LOW).

### C.6 Overconfidence (2025 literature)

- LLMs systematically express higher confidence than their empirical accuracy supports. A self-reported "HIGH confidence" does NOT correspond to an empirical hit rate of >80%; it must be calibrated against gold-standard cases.

### C.7 Central-tendency bias

- On broad scales (1–10), LLM ratings cluster around 6–7. This is why Section B.1 requires a 3-level scale.

---

## Section D — Mitigation patterns

| Failure mode | Mitigation pattern | Source |
|---|---|---|
| Sycophancy | (1) Strip user-opinion language from the evidence pack before LLM scoring; (2) explicit prompt: *"Score the evidence on its merits, ignoring any prior characterizations or opinions stated in the input"*; (3) use a separate, independently-prompted LLM for scoring than for memo-writing. | Sharma et al. 2023 |
| Position bias | If pairwise comparison is used: run BOTH orderings (A,B) and (B,A); declare a "win" only if the LLM picks the same answer in both. Otherwise call it a tie. Reduces position-bias rate ~68% → ~51%. | Zheng et al. 2023; Chauzov 2025 |
| Verbosity bias | (1) Length-normalize evidence packs (cap each company's pack at the same token budget); (2) explicit prompt: *"Do NOT let the length of the evidence influence the rating; only the substance counts"*; (3) penalize verbose rationales in the LLM's output schema. | Saito et al.; Sigl 2025 |
| Self-enhancement | Use a different model family for scoring than for content generation (Sonnet generates, Opus scores). Or use multi-model ensemble (Claude + GPT-4 + Gemini, take median). Reduces self-preference 31.5% via structured decomposition. | Self-Preference Bias 2024 |
| Anchoring | (1) Predict ONE dimension per call (don't bundle); (2) balance any few-shot examples across rating levels (one HIGH, one MEDIUM, one LOW); (3) randomize order of few-shots between calls. | Anchoring Bias 2024 |
| Overconfidence | Calibrate self-reported confidence against gold-standard cases (Section F). Use Brier-score linear probes on hidden states OR temperature scaling on logit-extracted token probabilities. | Overconfidence 2025; Linear-Probes 2025 |
| Central-tendency | Use 3–5 level scales with concrete anchors, not 1–10 numeric scales. | Inconsistent-Biased Evaluators 2024 |
| All of the above (variance) | Self-consistency: sample N=5, take median rating; track inter-sample dispersion as the confidence signal. | Wang et al. 2023 |

**The single most important mitigation**: the **per-dimension, single-attribute call with structured-output schema and verbatim-evidence-citation requirement**. This pattern simultaneously addresses anchoring (one dim per call), verbosity (structured short rationale), sycophancy (must cite evidence — can't fabricate), and auditability (rationale + quotes are traceable).

---

## Section E — Recommended rubric template for L3-e cross-era pattern scoring

### E.0 Rubric prompt skeleton (applied per-pattern)

```
SYSTEM:
You are an evidence-grounded equity-research evaluator. You will rate ONE
specific qualitative pattern about a company. You MUST:
- Use ONLY the evidence in <EVIDENCE_PACK>. No prior knowledge, no inference
  beyond cited material.
- Output strict JSON matching <SCHEMA>.
- Cite at least one verbatim quote from the evidence pack supporting any
  rating above LOW.
- Ignore any prior opinions, recommendations, or characterizations in the
  input. Score the underlying evidence on its merits.
- Do NOT let the length of the evidence pack influence the rating.
- If the evidence pack is silent or insufficient, output rating=LOW and
  defer_to_human=true.

USER:
<PATTERN_DEFINITION>
<RATING_ANCHORS: HIGH / MEDIUM / LOW>
<EVIDENCE_PACK>
<SCHEMA>

OUTPUT JSON:
{
  "pattern_id": "<id>",
  "rating": "HIGH | MEDIUM | LOW",
  "confidence": "HIGH | MEDIUM | LOW",
  "evidence_quotes": [{"source": "<doc_id>", "quote": "<verbatim>"}],
  "rationale": "<≤2 sentences>",
  "defer_to_human": <bool>,
  "tie_break_applied": <bool>
}
```

### E.1 Pattern #1 — Founder/CEO duration ≥15 years

**Anchor descriptions:**
- **HIGH:** Current CEO has held the role continuously for ≥15 years AND is the founder OR co-founder (verified via DEF 14A executive bios + EDGAR Form 8-K appointment history). Evidence pack must contain the appointment date or first-CEO-year disclosure.
- **MEDIUM:** CEO duration 8–15 years (founder OR non-founder) OR founder-CEO with 5–15 year tenure who is one of multiple co-founders still active.
- **LOW:** CEO duration <8 years OR multiple CEO turnovers in trailing 10 years OR insufficient disclosure to verify duration.

**Tie-break:** if evidence pack shows ≥15 years but CEO is interim or recently re-appointed after a gap, default to MEDIUM.

### E.2 Pattern #4 — Pivot creates the multi-bag (not original product)

**Anchor descriptions:**
- **HIGH:** Evidence pack documents a clear strategic pivot where >50% of current revenue is from a product/segment NOT in the original founding business model, AND the pivot occurred at least 3 years ago AND the multi-bag returns post-date the pivot. (Examples: Netflix DVD→streaming, Adobe perpetual→subscription, Microsoft on-prem→Azure.) Evidence must include a direct 10-K MD&A or shareholder letter quote describing the strategic shift.
- **MEDIUM:** Documented pivot with 25–50% of revenue from new segment OR pivot occurred <3 years ago (too soon to confirm) OR evidence of multiple iterative pivots without a single dominant transition.
- **LOW:** Current revenue mix matches original product line OR no documented strategic pivot OR the multi-bag returns predate any pivot (i.e., growth came from doing the original thing, not from pivoting).

**Tie-break:** the rubric must NOT confuse "expansion" (more of the same) with "pivot" (categorically different business). Anchor language explicitly: *"a pivot means the dominant revenue source today is in a market the company was NOT serving at founding."*

### E.3 Pattern #5 — Founder/CEO equity stake >5% sustained

**Anchor descriptions:**
- **HIGH:** Founder/CEO direct equity stake ≥5% of shares outstanding, sustained for ≥10 years, with no material selling in the last 3 years (verified via Form 4 / DEF 14A insider-ownership table). "Material selling" = >25% of starting position over a trailing 3-year window.
- **MEDIUM:** Stake 2–5% sustained for ≥5 years OR stake ≥5% but with mixed selling pattern (≤25% but ≥10% reduction in trailing 3 years) OR family/trust holdings counted alongside direct holdings to clear the 5% threshold.
- **LOW:** Stake <2% OR sustained <5 years OR material selling >25% in trailing 3 years OR ownership concentrated in options/RSUs not yet vested.

**Tie-break:** options and RSUs do NOT count toward the threshold; only vested direct equity. This must be explicit in the prompt because LLMs frequently conflate the two.

### E.4 Pattern #8 — Fraud signature (3+/6 components)

**Note:** This pattern is BORDERLINE between deterministic and LLM-narrative. The 6-item checklist is itself a deterministic count, but the per-item assessment ("does this disclosure suggest channel-stuffing?") is qualitative. Treat as **LLM-rubric-with-deterministic-aggregation**.

**Per-item anchors** (evaluate each of the 6 fraud-signature components separately, then count):
- **PRESENT (1):** evidence pack contains a specific disclosure or fact pattern matching the component's textbook signature, with verbatim quote.
- **ABSENT (0):** evidence pack contains no such pattern OR contains an explicit rebuttal.
- **AMBIGUOUS:** if AMBIGUOUS, treat as PRESENT for the count (conservative bias; we'd rather flag a false-positive fraud-signature for human review than miss it).

**Aggregation:** sum the 6 component scores deterministically. ≥3 → fraud-signature TRIPPED → P3 hard reject. <3 → continue.

This pattern is the textbook example where the LLM-rubric must be **decomposed into atomic per-component calls**, NOT a single global "is this company a fraud?" call.

### E.5 Pattern #20 — Right thing in right decade

**Anchor descriptions:**
- **HIGH:** The company's core product/business model is documented in the evidence pack as well-aligned with a structural macro/secular tailwind that has 10+ years of remaining runway (e.g., AI compute 2023–, GLP-1 obesity 2023–, electrification 2020–, cloud 2010–). Evidence pack must include either (a) a 10-K Risk Factors / MD&A passage articulating the tailwind OR (b) external confirming evidence of the tailwind's persistence.
- **MEDIUM:** Tailwind exists but is mid-cycle (5–10 years runway remaining) OR the company benefits from the tailwind but is not a primary beneficiary (e.g., generic semiconductor exposure to AI vs. a pure AI-compute play) OR the tailwind is contested in the evidence pack.
- **LOW:** Company operates against a secular headwind (e.g., legacy print media in 2020s, ICE auto OEMs without an EV pivot) OR the era-fit is purely cyclical, not secular OR the tailwind is fully matured (<3 years runway).

**Tie-break:** "right decade" means the remaining runway, not the elapsed runway. A company that nailed the 2010s cloud wave but is now mature should NOT score HIGH on this pattern in 2026.

### E.6 Aggregation across patterns

The L3-e rubric produces N independent per-pattern scores. Aggregation back into a P3 verdict is OUT OF SCOPE for this subagent (handled by the deterministic-gate side OR the synthesis stage). However, the rubric should output the per-pattern dispersion to support that aggregation:

```
{
  "patterns": [
    {"pattern_id": "1_founder_duration", "rating": "HIGH", "confidence": "HIGH", ...},
    {"pattern_id": "4_pivot", "rating": "MEDIUM", "confidence": "LOW", ...},
    ...
  ],
  "overall_dispersion": <stdev of ratings>,
  "n_low_confidence": <count>,
  "n_defer_to_human": <count>
}
```

---

## Section F — Calibration approach

### F.1 Goal

Test that "HIGH confidence" from the rubric LLM corresponds to ≥X% empirical hit rate against a gold-standard set. Without this, "HIGH" is just a label.

### F.2 Gold-standard test set construction

Per the LLM-evaluation gold-set literature (Confident AI, Klu, Maxim AI):

1. **Curate 30–50 historical companies** with KNOWN outcomes spanning all rating levels per pattern. For each pattern, target balanced representation:
   - Pattern #1 (founder duration): 10 examples HIGH (Bezos/Amazon, Buffett/Berkshire, Zuck/Meta, Page-Brin/Alphabet, Reed Hastings/Netflix pre-2023, ...), 10 MEDIUM, 10 LOW.
   - Pattern #4 (pivot): HIGH (Netflix, Adobe, Microsoft, Apple post-1997, IBM services pivot), MEDIUM, LOW (companies that succeeded by doing the original thing, e.g., Walmart, Costco, Procter & Gamble).
   - Pattern #5 (equity stake): same balanced curation.
   - Pattern #8 (fraud signature): use known frauds (Enron, Wirecard, Luckin, Theranos pre-collapse) and known non-frauds.
   - Pattern #20 (right decade): use 10-year-look-back companies where we know what happened.
2. **Each gold case needs**: company, evidence pack (10-K excerpts, news, DEF 14A), human-assigned ground-truth rating, written rationale.
3. **Balance is critical**: Sharma 2023 sycophancy and few-shot anchoring research both warn that imbalanced gold sets create spurious "calibration."
4. **Decontamination**: ensure the LLM's training-data cutoff does NOT include outcome data for any gold case (e.g., for a 2020-pivot case, use a model whose cutoff is pre-2020 if testing era-fit). This is the core empirical-foundation discipline already established in the Q1 work.

### F.3 Validation metrics

For each pattern's rubric output:

1. **Cohen's kappa** (LLM rating vs human rating, ordinal-weighted). Target: κ ≥ 0.61 (substantial agreement, McHugh 2012). Below 0.41 (moderate) → rubric needs redesign.
2. **Calibration curves**: bucket LLM-self-reported confidence levels (HIGH/MEDIUM/LOW); compute empirical hit rate per bucket. Plot. Target: HIGH-confidence empirical accuracy ≥80%; MEDIUM ≥60%; LOW ≥40%.
3. **Expected Calibration Error (ECE)** OR the newer **TH-Score** (Overconfidence 2025). Target: ECE <0.10.
4. **Bias diagnostics**:
   - Position-bias check: if rubric ever does pairwise, run a swap-order test and report flip-rate. Target: <10%.
   - Verbosity-bias check: re-run rubric on artificially-elongated or shortened evidence packs; ratings should not shift. Target: <1 rating-level shift in ≥90% of cases.
   - Self-enhancement check: score the same evidence pack with two different LLM families (e.g., Claude Opus + GPT-4); compute kappa. Target: cross-model κ ≥ 0.61.
5. **Inter-sample reliability** (self-consistency): for each gold case, run N=5 samples; compute fraction of cases where all 5 samples agree. Target: ≥80% unanimous on HIGH-confidence cases.

### F.4 Calibration loop

When validation falls short:
1. **Re-write anchor descriptions** to be more concrete (most common fix). Vague anchors are the #1 cause of low kappa.
2. **Add or rebalance few-shot examples** in the rubric prompt. Always balanced (one per rating level), randomly ordered per call.
3. **Tighten evidence-citation requirement** (e.g., require 2+ verbatim quotes for HIGH instead of 1).
4. **Apply post-hoc calibration**: if the LLM is systematically over-rating (everything looks HIGH), apply a Wasserstein-based shift (per RULERS 2026) OR simply increase the threshold (treat raw-HIGH as effective-MEDIUM). This is the cheapest fix when retraining isn't possible.
5. **Switch to a different scoring model**: if Claude Opus shows persistent self-enhancement on Claude-written memos, swap to GPT-4o for scoring.

### F.5 Operating discipline

- Re-run the gold-set validation **on every rubric prompt change**. Treat the prompt as code; version it; require diff review before deploying.
- Re-run the gold-set validation **on every model upgrade** (Sonnet 4.5 → 4.7 → 5.0 etc.). Do NOT assume that model improvements preserve calibration.
- Maintain a **drift watch**: every quarter, sample 10 production rubric outputs, have a human re-rate, compute kappa vs production. If kappa drops below 0.61, re-validate the rubric.
- Keep **defer-to-human** as a first-class output. The rubric's job is not to eliminate the human; it is to do the bulk work and flag uncertainty for human review. Production hit rates depend more on how cleanly the system flags its own uncertainty than on raw accuracy.

---

## Closing notes

The single highest-leverage design decision for our use case is the **per-pattern, single-attribute call with locked-anchor rubric and verbatim-evidence-citation requirement**, sampled N=5 with median aggregation. This pattern alone addresses anchoring, verbosity, sycophancy (partially), and auditability simultaneously. Everything else (multi-model ensembling, post-hoc calibration, drift monitoring) is incremental on top of this foundation.
