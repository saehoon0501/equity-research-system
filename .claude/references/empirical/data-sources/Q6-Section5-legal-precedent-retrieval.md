# Legal precedent retrieval calibration patterns

**Research scope:** How legal-tech systems (Westlaw, LexisNexis, Casetext CoCounsel, Bloomberg Law, ROSS) calibrate "similar past case" retrieval, evaluate retrieval quality, monitor drift (overruled cases), and build practitioner trust. Treated as the closest real-world analog to our 32-case counterfactual catalog problem (curated historical case database; new candidate retrieved-against; precision and recall both matter; downstream user uses the retrieved cases as reference for judgment).

**Date:** 2026-04-29
**Author:** subagent (Section 5, Q6 legal-precedent-retrieval sub-research)

---

## Section A — Curated sources (tier-labeled)

Tiers: **A** = peer-reviewed / regulatory / vendor primary engineering blog / formal evaluation track. **B** = reputable trade publication / well-cited analysis / law-library guide. **C** = practitioner blog / vendor marketing (use only for descriptive claims, not load-bearing evidence).

### Vendor primary + product documentation

1. **[LexisNexis — Lexis+ AI: Legal Research Platform + AI Assistant](https://www.lexisnexis.com/en-int/products/lexis-plus-ai)** — Tier A vendor-primary. Describes Shepard's Knowledge Graph + GraphRAG architecture and the "minimum five checkpoints" RAG pipeline.
2. **[LexisNexis — RAG Enhancements Including GraphRAG (Legal IT Insider, July 2024)](https://legaltechnology.com/2024/07/22/lexisnexis-announces-new-capabilities-for-lexis-ai-including-rag-enhancements/)** — Tier B trade. Multi-model selection (Claude + OpenAI per task), Shepard's-graph augmentation.
3. **[LexisNexis — Shepard's Editorial Phrases Alphabetical List (PDF)](https://www.lexisnexis.com/pdf/lexis-advance/Shepards-Editorial-Phrases-Alphabetical-List.pdf)** — Tier A vendor-primary. The full taxonomy of treatment classifications ("overruled", "questioned", "criticized", "distinguished", "limited", "followed") that drive citator drift signals.
4. **[Bloomberg Law — Smart Code Help Documentation](https://help.bloomberglaw.com/docs/blh-030-litigation-intelligence-center.html)** — Tier A vendor-primary. ML-classified statute citations into ~90 topics with strong/moderate/weak "Strength of Discussion" rating (mechanical-feature scoring).
5. **[Zarin (SSRN 2017) — Bloomberg Law Smart Code vs Curated Annotated Codes](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2998805)** — Tier A peer-reviewed empirical comparison. Direct mechanical-vs-editorial calibration study.
6. **[Westlaw KeyCite (Wikipedia, Westlaw entry)](https://en.wikipedia.org/wiki/Westlaw)** — Tier B. KeyCite flag taxonomy (red / yellow / blue-H), depth-of-treatment ranking.
7. **[Hellyer (2018) — Evaluating Shepard's, KeyCite, and BCite for Case Validation](https://www.aallnet.org/wp-content/uploads/2018/12/LLJ_110n4_02_hellyer.pdf)** — Tier A peer-reviewed (Law Library Journal). Head-to-head citator-coverage benchmark; finds non-trivial disagreement across the three citators.
8. **[ROSS Intelligence — How ROSS AI Turns Legal Research On Its Head](https://blog.rossintelligence.com/post/how-ross-ai-turns-legal-research-on-its-head)** — Tier C vendor blog. Word-embeddings-over-passages architecture; trained on ~1M Q-A pairs by lawyers.
9. **[Cohubicol — Casetext's CoCounsel through the Typology lens](https://www.cohubicol.com/blog/casetext-cocounsel-openai-typology/)** — Tier B analysis. Multi-model + retrieval architecture, Trust Team manual eval over 30,000 legal questions / ~4,000 hours.

### Empirical evaluations of legal-tech retrieval

10. **[Magesh, Surani, Dahl, Suzgun, Manning, Ho (2024/2025) — Hallucination-Free? Assessing the Reliability of Leading AI Legal Research Tools (Stanford RegLab/HAI; J. Empirical Legal Studies)](https://dho.stanford.edu/wp-content/uploads/Legal_RAG_Hallucinations.pdf)** — Tier A peer-reviewed. **Lexis+ AI hallucinated 17%, Westlaw AI-Assisted Research 33%, GPT-4 baseline 43%, Lexis+ accuracy 65%.** First preregistered eval. **Single most-cited source for legal RAG calibration failures.**
11. **[Stanford HAI — AI on Trial: Legal Models Hallucinate in 1-out-of-6+ Queries](https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-or-more-benchmarking-queries)** — Tier A. Companion press release with methodology summary.
12. **[Dahl, Magesh, Suzgun, Ho (2024) — Large Legal Fictions: Profiling Legal Hallucinations in LLMs (J. Legal Analysis, Oxford)](https://academic.oup.com/jla/article/16/1/64/7699227)** — Tier A peer-reviewed. Vanilla-LLM baseline: **58% (GPT-4) to 88% (Llama 2) hallucination rate** on direct verifiable federal-case queries; lower-court hallucination > higher-court.
13. **[arXiv 2510.20941 — Do LLMs Truly "Understand" When a Precedent Is Overruled?](https://arxiv.org/pdf/2510.20941)** — Tier A. 236-case-pair benchmark on overruling-relationship detection; documents "era sensitivity" failure mode (LLMs fail on older precedent-pair overruling chains).

### Formal evaluation tracks + benchmarks

14. **[TREC Legal Track Overview Page](https://trec-legal.umiacs.umd.edu/)** — Tier A. Master landing for the canonical legal-IR evaluation track (2006-2011).
15. **[Hedin et al. — TREC 2009 Legal Track Overview (PDF)](https://trec.nist.gov/pubs/trec18/papers/LEGAL09.OVERVIEW.pdf)** — Tier A. Canonical methodology: stratified-sampling for relevance assessment, 3-reviewer adjudication, recall-focused F1.
16. **[Tomlinson — TREC 2007 Legal Track Overview (PDF)](https://trec.nist.gov/pubs/trec16/papers/LEGAL.OVERVIEW16.pdf)** — Tier A. Boolean-vs-statistical-IR comparison evidence.
17. **[Springer — Measuring Effectiveness in the TREC Legal Track](https://link.springer.com/chapter/10.1007/978-3-662-53817-3_6)** — Tier A. Methodological retrospective: how to estimate recall when gold-standard is incomplete.
18. **[COLIEE 2025 Overview (ACM)](https://dl.acm.org/doi/10.1145/3769126.3785016)** — Tier A peer-reviewed. Annual case-law / statute-law IR + entailment competition; 4 tasks (case retrieval, case entailment, statute retrieval, statute entailment).
19. **[arXiv 2401.03551 — CAPTAIN at COLIEE 2023](https://arxiv.org/abs/2401.03551)** — Tier A. BM25 + transformer hybrid for legal case retrieval.
20. **[arXiv 2505.20743 — UQLegalAI@COLIEE2025: LLMs + GNNs for Legal Case Retrieval](https://arxiv.org/html/2505.20743v1)** — Tier A. State-of-art combines citation-graph (GNN) signals + LLM reranking. Hybrid mechanical-feature + LLM mirrors our Q2 lock.
21. **[Guha et al. (2023) — LegalBench: Collaboratively Built Benchmark for Measuring Legal Reasoning in LLMs](https://arxiv.org/abs/2308.11462)** — Tier A. **162 tasks across 6 reasoning types** (issue-spotting, rule-recall, rule-application, rule-conclusion, interpretation, rhetorical-understanding); built by ~40 SME contributors.
22. **[arXiv 2504.01840 — LRAGE: Legal Retrieval Augmented Generation Evaluation Tool](https://arxiv.org/html/2504.01840v1)** — Tier A. Holistic legal-RAG eval framework: retriever + reranker + generator under instance-level custom rubrics.

### Citation-network + similarity methodology

23. **[arXiv 2209.12474 — Legal Case Document Similarity: You Need Both Network and Text](https://arxiv.org/abs/2209.12474)** — Tier A peer-reviewed. **Best combined method beats best text-only by 11.8% and best network-only by 20.6%.** Single most cited "hybrid wins" empirical paper.
24. **[arXiv 2004.12307 — Methods for Computing Legal Document Similarity: A Comparative Study](https://arxiv.org/pdf/2004.12307)** — Tier A. Bibliographic coupling, co-citation, Node2Vec, BERT-style head-to-head.
25. **[Springer Article — Legal Information Retrieval and Entailment Based on BM25, Transformer and Semantic Thesaurus Methods](https://link.springer.com/article/10.1007/s12626-022-00103-1)** — Tier A. BM25-as-strong-baseline, with transformer rerankers as the gain layer.
26. **[arXiv 2105.05686 — Yes, BM25 is a Strong Baseline for Legal Case Retrieval](https://arxiv.org/abs/2105.05686)** — Tier A. Empirical: well-tuned BM25 beats many neural-only retrievers in legal case retrieval. Mechanical baseline floor.
27. **[law.co blog — Graph-Structured Retrieval for Legal Precedent Networks](https://law.co/blog/graph-structured-retrieval-for-legal-precedent-networks)** — Tier B practitioner. GraphSAGE on 10,000+ cases / 150,000+ citation edges.
28. **[ACL Anthology — Legal Case Retrieval: A Survey of the State of the Art (2024)](https://aclanthology.org/2024.acl-long.350.pdf)** — Tier A peer-reviewed (ACL 2024 long paper). The most-recent comprehensive survey.

### Structured legal-case databases

29. **[Spaeth Supreme Court Database (Washington University)](http://scdb.wustl.edu/about.php?s=3)** — Tier A. **60 variables × 2,633 elements per case; 157,980 data points across all SCOTUS decisions since 1791.** Reference benchmark for "what structured features should a curated legal-case dataset contain".
30. **[Spaeth — Online Codebook](https://scdb.la.psu.edu/online-codebook/)** — Tier A. Variable definitions: 6 categories (identification, background, chronological, substantive, voting, opinion).
31. **[Spaeth — Formal Alteration of Precedent Variable Documentation](http://scdb.wustl.edu/documentation.php?var=precedentAlteration)** — Tier A. Drift-monitoring schema (formal overrule variable).

### Trust calibration + production lessons

32. **[Legal Cheek (Feb 2026) — Lawyers Use AI Despite Lacking Trust](https://www.legalcheek.com/2026/02/lawyers-are-using-ai-despite-lacking-trust-in-it-research-finds/)** — Tier B. **1-in-5 lawyers report high trust in AI; 67% have had to override AI legal output.**
33. **[Artificial Lawyer (Mar 2026) — Legal AI Access at 83%, but Trust Issues Remain](https://www.artificiallawyer.com/2026/03/23/legal-ai-access-at-83-but-trust-issues-remain/)** — Tier B. Adoption-trust gap quantified.
34. **[Knovos — Chapter 9: Technology Assisted Review (TAR 1.0, TAR 2.0, CAL)](https://www.knovos.com/guides/ediscovery-guide/chapter-9-tar-technology-assisted-review/)** — Tier B vendor-curated guide. Iterative-training calibration loop standard in legal e-discovery.
35. **[arXiv 2106.09866 — On Minimizing Cost in Legal Document Review Workflows (Yang)](https://arxiv.org/pdf/2106.09866)** — Tier A. Formal cost-asymmetric optimization for legal review (false-negative cost typically >> false-positive cost in production / privilege review; reverses for litigation strategy).

### Boolean vs natural-language baseline studies

36. **[Wikipedia — Legal Information Retrieval](https://en.wikipedia.org/wiki/Legal_information_retrieval)** — Tier B. Survey w/ classic Blair-Maron 1985 finding: lawyers using Boolean recovered ~20% recall but believed they had ~75% recall — a **calibration miscalibration** finding.
37. **[Springer — Natural Language vs Boolean Query Evaluation: A Comparison of Retrieval Performance (PDF)](https://link.springer.com/content/pdf/10.1007/978-1-4471-2099-5_22.pdf)** — Tier A peer-reviewed.
38. **[Allegheny County Law Library — AND, OR, NOT & Beyond: Natural Language vs Boolean Searching with Proximity in Westlaw](https://www.acllib.org/and-or-not-beyond-natural-language-vs-boolean-searching-with-proximity-in-westlaw/)** — Tier B law-library guide. Practitioner framing of the trade-off.

### Drift / overruling / update cadence

39. **[USC Gould Law Library — Shepardizing: How to Confirm a Case Is Good Law](https://lawlibguides.usc.edu/c.php?g=542695&p=3718771)** — Tier B. Workflow standard: how lawyers monitor precedent drift in practice.
40. **[UNC Faculty Scholarship — Describing Negative Legal Precedent in Citators](https://scholarship.law.unc.edu/cgi/viewcontent.cgi?article=1020&context=faculty_publications)** — Tier A. Editorial taxonomy theory for negative-treatment classification.
41. **[Duke Judicature — How Courts Do — and Don't — Respond to Statutory Overrides](https://judicature.duke.edu/articles/how-courts-do-and-dont-respond-to-statutory-overrides/)** — Tier A. Empirical: lower courts adjust within ~5-10 yrs of formal SCOTUS overrules; partial-override cases show longest decay.

---

## Section B — Methodology landscape

### B1. Boolean / proximity-operator retrieval (1970s-2000s baseline)

**Architecture:** Lawyer-authored AND/OR/NOT/proximity (`/s` same sentence, `/p` same paragraph, `/n` within n words) over a structured field index (case caption, court, date, headnote, full-text).

**Calibration paradigm:** Mechanical, deterministic, fully auditable. Recall is whatever the query expression captures; no learning.

**Empirical performance:** Blair-Maron (1985) classic finding — lawyers' Boolean searches achieved ~20% recall while lawyers believed they had ~75% recall. The original "calibration miscalibration" result in legal IR. ([Wikipedia — Legal IR](https://en.wikipedia.org/wiki/Legal_information_retrieval))

**Trade-off geometry:** AND-heavy → high precision / low recall; OR-heavy → low precision / high recall; no satisfactory middle ground. ([Allegheny County Law Library](https://www.acllib.org/and-or-not-beyond-natural-language-vs-boolean-searching-with-proximity-in-westlaw/))

**Why it persists:** Even with neural retrieval, boolean is preserved as a fallback because exact-citation lookup ("Section 420 IPC", "*Chevron* footnote 9") must hit the literal token; semantic embeddings sometimes drop the exact reference. ([Redis — Full-text search for RAG apps](https://redis.io/blog/full-text-search-for-rag-the-precision-layer/))

### B2. Natural-language / probabilistic retrieval (BM25-era, ~2000-2020)

**Architecture:** TF-IDF / BM25 over full text + headnote index + secondary fields. Westlaw and Lexis natural-language modes have been BM25-style since ~2000.

**Empirical baseline:** Yes, BM25 is a Strong Baseline for Legal Case Retrieval ([arXiv 2105.05686](https://arxiv.org/abs/2105.05686)) — well-tuned BM25 beats many neural-only models in legal case retrieval. Two-thirds-or-more weight on BM25 remains optimal even in 2024-25 hybrid systems for highly technical domains like law. ([Emergent Mind — Hybrid BM25 Retrieval](https://www.emergentmind.com/topics/hybrid-bm25-retrieval))

### B3. Citation-network retrieval (2010s onward)

**Architecture:** Build a directed citation graph (case→cited-case). Compute structural similarity via:
- **Bibliographic coupling** — overlap of out-citations (two cases that cite the same set of precedents are similar).
- **Co-citation** — overlap of in-citations (two cases cited together by the same later case are similar).
- **Node2Vec / GraphSAGE / GNN embeddings** — learned vector representations from graph structure.

**Empirical:** [arXiv 2209.12474](https://arxiv.org/abs/2209.12474) — citation-network alone underperforms text alone, but **best combined (network + text) beats best text-only by 11.8% and best network-only by 20.6%**. The closest published quantification of "hybrid wins" in legal precedent retrieval.

**Production analog:** LexisNexis Shepard's Knowledge Graph and Westlaw KeyCite embed citation-graph signals into the relevance score (depth-of-treatment field is essentially a graph-derived feature). LexisNexis 2024 GraphRAG launch made this explicit. ([Legal IT Insider](https://legaltechnology.com/2024/07/22/lexisnexis-announces-new-capabilities-for-lexis-ai-including-rag-enhancements/))

### B4. LLM-augmented retrieval (2023-2026 frontier)

**Architecture:** Multi-stage RAG.
1. **Query expansion / decomposition** — LLM rewrites the natural-language question into focused sub-queries.
2. **Hybrid retrieval** — BM25 + dense embedding + citation-graph candidates retrieved in parallel.
3. **Reranking** — cross-encoder reranker (often a fine-tuned transformer) scores top-K candidates.
4. **Generation with citation** — LLM drafts response, citing retrieved passages.
5. **Citator/Shepard's overlay** — drift signal applied to flag "this case has negative treatment" before surfacing.

**Lexis+ AI specifics:** "minimum five checkpoints" RAG pipeline; multi-model selection (Anthropic Claude + OpenAI per-task); GraphRAG over Shepard's knowledge graph. ([LexisNexis](https://www.lexisnexis.com/en-int/products/lexis-plus-ai), [Legal IT Insider](https://legaltechnology.com/2024/07/22/lexisnexis-announces-new-capabilities-for-lexis-ai-including-rag-enhancements/))

**Casetext CoCounsel specifics:** Trust-Team manual eval over **30,000 legal questions and ~4,000 hours** of fine-tuning before launch; per-skill regression suite. ([Cohubicol](https://www.cohubicol.com/blog/casetext-cocounsel-openai-typology/))

**ROSS Intelligence specifics:** Word-embeddings over case *passages* (not whole cases) trained on ~1M lawyer-authored Q-A pairs. ([ROSS blog](https://blog.rossintelligence.com/post/how-ross-ai-turns-legal-research-on-its-head)) Note: company shut down in 2021 due to litigation costs.

### B5. State-of-art hybrid (COLIEE 2024-25 winners)

[UQLegalAI@COLIEE2025](https://arxiv.org/html/2505.20743v1) and JNLP (COLIEE 2025 best) explicitly combine:
- **BM25 lexical filter** (mechanical, recall-focused first stage).
- **GNN over citation network** (structural similarity).
- **LLM semantic reranker** (judgment layer).

This is the most direct analog to our Q2 lock (mechanical-feature + LLM-rubric hybrid).

---

## Section C — Calibration patterns

### C1. Test-set design

**TREC Legal Track methodology** ([Hedin 2009 Overview](https://trec.nist.gov/pubs/trec18/papers/LEGAL09.OVERVIEW.pdf)) — the canonical legal-IR test-set design:

1. **Stratified sampling for relevance assessment.** For each topic, sample ~2,720 documents using extreme stratified sampling (sample more heavily from likely-relevant strata, downweight low-prior strata, then re-weight when computing recall).
2. **Three-reviewer adjudication.** Each sampled document is assessed by 3 independent volunteer reviewers. Majority vote = ground-truth relevance. Inter-annotator agreement is measured and reported.
3. **Reviewer qualification.** Reviewers had legal training; majority were 3L law students earning pro bono credit. Domain expertise is required, not optional.
4. **Recall-focused F1.** In document production for civil litigation, recall (missing-a-key-precedent cost) is typically more important than precision; F1 weighting reflects this.
5. **Reusable test collection.** Corpus + topics + qrels (relevance judgments) released so subsequent retrieval methods can benchmark against the same gold standard. This is the analog to a *frozen, version-tagged* counterfactual catalog.

**LegalBench methodology** ([Guha 2023](https://arxiv.org/abs/2308.11462)) — **162 tasks built by ~40 SME (lawyer) contributors**, organized along 6 reasoning types: issue-spotting, rule-recall, rule-application, rule-conclusion, interpretation, rhetorical-understanding. Each task is hand-crafted and labeled by lawyers; no automated relevance judgment.

**LRAGE methodology** ([arXiv 2504.01840](https://arxiv.org/html/2504.01840v1)) — instance-level custom rubrics. Each test case carries its own rubric (not a global one) tailored to the legal sub-domain. This is the closest published analog to per-case rubric calibration in our use-case.

**Stanford RegLab methodology** ([Magesh 2024/2025](https://dho.stanford.edu/wp-content/uploads/Legal_RAG_Hallucinations.pdf)) — **preregistered evaluation protocol** before running queries through Lexis+/Westlaw AI; queries spanned issue-spotting, factual-recall, citation-verification, and counterfactual ("what if X were different") types. Each output was manually verified for: (a) cited case exists, (b) cited case says what tool claims, (c) cited case is actually relevant to the query. Three failure dimensions, not one.

### C2. Mechanical-feature scoring patterns

**Bloomberg Law Smart Code** assigns each citing-court extract a "Strength of Discussion" rating (strong/moderate/weak) based on mechanical features: length of discussion, density of legal terminology, presence of citations to other case law, structural position (holding vs dicta). This is a **pure-mechanical-feature scoring** layer applied *before* any LLM. ([Help Bloomberg](https://help.bloomberglaw.com/docs/blh-030-litigation-intelligence-center.html))

**KeyCite depth-of-treatment** is a 4-bar mechanical feature: examined / discussed / cited / mentioned. Westlaw's default sort is by descending depth, surfacing cases that engage substantively before passing-mention citations.

**Shepard's treatment classifications** ([editorial phrase list](https://www.lexisnexis.com/pdf/lexis-advance/Shepards-Editorial-Phrases-Alphabetical-List.pdf)) — closed taxonomy of ~40 phrases ("followed", "distinguished", "criticized", "limited", "questioned", "overruled"). These are *editorial* (lawyer-assigned) but act as fixed-vocabulary mechanical features once assigned.

### C3. Practitioner trust development

**Calibration loop is iterative, not one-shot.**

- **TAR / predictive coding** ([Knovos Chapter 9](https://www.knovos.com/guides/ediscovery-guide/chapter-9-tar-technology-assisted-review/)) — workflow is *Continuous Active Learning* (CAL): lawyer reviews seed batch, model retrains, lawyer reviews next batch, repeat until stable. Standard cadence in e-discovery for ~15+ years; courts have explicitly approved.
- **Statistical validation step is required.** Random sampling of both the "relevant" set (precision check) and "discarded" set (recall check) post-classification, with formal recall/precision/F1 reporting. This is the legal-tech standard for defensibility and trust.

**Adoption-trust gap (2026 data).**
- 83% of legal professionals now have AI access ([Artificial Lawyer Mar 2026](https://www.artificiallawyer.com/2026/03/23/legal-ai-access-at-83-but-trust-issues-remain/)).
- Only **1-in-5 lawyers report high trust** in AI-generated work ([Legal Cheek Feb 2026](https://www.legalcheek.com/2026/02/lawyers-are-using-ai-despite-lacking-trust-in-it-research-finds/)).
- **67% have had to override or correct AI legal output.**
- Top concern: accuracy/hallucinations (57%), then data security (51%), liability (45%), ethics (44%).

**Lesson:** Trust is built by making override-and-correct *cheap* (one-click flag, retraining), not by claiming the model is correct out of the box.

### C4. False-positive vs false-negative cost asymmetry

**The asymmetry is context-dependent, not universal:**

- **Document production / e-discovery:** false-negative cost dominates. Missing a privileged or responsive document → sanctions, malpractice. → recall-weighted F1, often F2 or F-beta with beta>1. ([arXiv 2106.09866 — Yang](https://arxiv.org/pdf/2106.09866))
- **Litigation strategy / brief-writing:** false-positive cost can dominate. Citing a non-existent or overruled case → judicial sanction (now common — see [EDRM AI Hallucination Sanctions 2025](https://edrm.net/2025/08/reasonable-or-overreach-rethinking-sanctions-for-ai-hallucinations-in-legal-filings/)). → high-precision-required, low-tolerance for misgrounded citation.
- **Legal research / "find me similar precedents":** symmetric concern. Missing the controlling case is bad; surfacing 50 irrelevant cases wastes lawyer time and risks the lawyer skipping the relevant one. → MAP, MRR, Recall@K all reported.

**Production lesson:** Legal-tech vendors do *not* publish a single F-score. They publish *recall*, *precision*, *MRR*, *MAP*, *citation-existence rate*, *misgrounding rate*, *overruled-flag-coverage* separately, because the cost weighting depends on the use case.

### C5. Drift monitoring

**Update cadence in legal databases:**
- **Daily updates.** Westlaw, Lexis, and Bloomberg Law re-run citator computation on a daily schedule. New opinions are ingested, parsed for citations to existing cases, classified for treatment (positive/negative/neutral) by an editorial team (Shepard's, KeyCite editors) augmented by ML triage (BCite is more ML-heavy; KeyCite and Shepard's remain editorial-primary).
- **Citator-coverage divergence is real.** Hellyer (2018) — Shepard's, KeyCite, and BCite disagree non-trivially on coverage and treatment-classification of the same case. → use multiple citators when stakes are high; never trust a single citator. ([Hellyer 2018](https://www.aallnet.org/wp-content/uploads/2018/12/LLJ_110n4_02_hellyer.pdf))

**Overruling detection is hard:**
- Formal overrule (SCOTUS explicit "we overrule X") is detected reliably.
- *Implicit* overrule (later case's reasoning forecloses earlier case's holding without explicit overrule language) is detected unreliably even by lawyer-editors. → uncertainty must be flagged, not hidden.
- LLMs are particularly bad at this: [arXiv 2510.20941](https://arxiv.org/pdf/2510.20941) — state-of-art LLMs show "era sensitivity" (fail on older overruling chains), 236-pair benchmark.

**Lower-court adoption lag:** [Duke Judicature](https://judicature.duke.edu/articles/how-courts-do-and-dont-respond-to-statutory-overrides/) — lower courts typically adjust to formal SCOTUS overrules within 5-10 years; partial-overrules show the longest decay tail. → drift propagates, doesn't snap.

### C6. Disambiguation of similar-but-different precedents

The hardest problem in legal retrieval is two cases with surface-similar fact patterns but different outcomes due to a doctrinal distinction the user didn't think of.

**Mitigations used in production:**
- Surface *both* cases with explicit "distinguishing fact" headnotes (Westlaw and Lexis editorial).
- Show citation-graph context (does case A cite case B as distinguishing, following, or criticizing?).
- For LLM systems: cite passages, not just cases; force the lawyer to read the pinpoint cite.
- **Failure mode:** LLMs that summarize without pinpointing tend to elide doctrinal distinctions. Stanford RegLab's misgrounding metric specifically catches this.

---

## Section D — Lessons applicable to our case (32-case counterfactual catalog)

### D1. 32-case-catalog parallels

The legal-tech analog is striking:
- A **curated** historical case database (Spaeth = 60-variable structured DB; Westlaw/Lexis = full-text + editorial tags).
- A **new query** (legal question / fact pattern) needs the most-similar past cases retrieved.
- **Both precision and recall matter** — missing a controlling precedent is bad; surfacing irrelevant ones is bad.
- **Downstream user (lawyer / portfolio manager) uses retrieved cases as reference for judgment**, not as the answer itself.

**Direct mapping:**
- Our 32-case counterfactual catalog ↔ Spaeth Supreme Court Database (curated, structured, version-tagged).
- Our new candidate company ↔ a new fact pattern needing precedent retrieval.
- Our mechanical similarity score ↔ KeyCite depth-of-treatment / Bloomberg Smart Code Strength-of-Discussion.
- Our LLM rubric judgment ↔ Casetext CoCounsel / Lexis+ AI semantic reranker.
- Our retrieved-cases-as-reference workflow ↔ exactly what lawyers do with KeyCite/Shepard's results.

### D2. Hybrid mechanical-feature + LLM approach (matches our Q2 lock)

The legal-tech evidence strongly validates the Q2-lock decision:

- **BM25 / mechanical features remain a strong baseline.** Even in 2024-26, well-tuned BM25 plus citation-graph features beats neural-only models on COLIEE legal case retrieval ([arXiv 2105.05686](https://arxiv.org/abs/2105.05686)). Two-thirds-or-more weight on BM25 is optimal for highly technical domains like law.
- **LLM as reranker, not as primary retriever.** State-of-art systems (UQLegalAI@COLIEE2025, Lexis+ AI GraphRAG, Casetext CoCounsel) use LLM at the *reranking and generation* stage, not as the primary retriever. The mechanical-feature layer is the recall-floor; the LLM is the precision-judge.
- **Hybrid wins over either alone.** [arXiv 2209.12474](https://arxiv.org/abs/2209.12474) quantifies it: best combined > best text-only by 11.8%, > best network-only by 20.6%. **This is the most directly cited empirical justification for our Q2 hybrid lock.**

### D3. Recommended test-set methodology for our 32-case catalog

Adapted from TREC Legal Track + LegalBench + LRAGE:

1. **Lock the gold standard with multiple SME annotators.** For each of our 32 cases, get 3 independent operator-quality similarity judgments to the most-recent candidate; majority-vote ground truth. Report inter-annotator agreement (kappa).
2. **Stratified sampling.** When evaluating retrieval over 32 cases vs N candidate companies, don't sample uniformly — stratify by sector / regime / outcome (TARGET / KILL) and sample more heavily from likely-relevant strata; reweight on aggregation. (This becomes increasingly important as the catalog grows past 32.)
3. **Per-instance rubrics, not a global rubric.** LRAGE pattern: each test case carries its own similarity rubric (e.g., "for this 2008-financial-crisis-bank case, similarity is dominated by leverage + funding-mix + concentration, not by sector"). Global rubric → underspecified.
4. **Three failure dimensions, separately measured** (Magesh 2024 pattern):
   - **Existence** — did the retrieval surface a case from the catalog at all? (recall floor)
   - **Faithfulness** — does the retrieved case actually say what the rubric/LLM claims? (no misgrounding)
   - **Relevance** — is the retrieved case actually similar on the dimensions that matter for the new candidate? (precision)
5. **Pre-register the eval protocol** before running candidates through the system. Stanford RegLab's 2024 study showed how much vendors over-claim when no preregistration constrains them.
6. **Multiple metrics, not a single F-score.** Recall@K, MAP@K, MRR, citation-existence-rate, misgrounding-rate, overruled-flag-coverage — separately. Cost asymmetry is context-dependent; collapsing to one number hides the failure mode that matters.

### D4. Drift-monitoring patterns for our catalog

The legal-tech analog of "case got overruled" is "case got reclassified" (e.g., what we labeled a TARGET in 2018 turns out, with 2024 hindsight, to have been a KILL — facts emerged, accounting fraud surfaced, etc.).

**Recommended drift schema (adapted from Shepard's/KeyCite):**

1. **Closed-taxonomy treatment classifications per case.** Define a fixed vocabulary: `confirmed`, `partially-confirmed`, `weakened-by-new-evidence`, `reclassified-target-to-kill`, `reclassified-kill-to-target`, `superseded-by-similar-case`, `formally-retired`. Apply per-case at each refresh.
2. **Daily-or-weekly re-citator.** Whenever new earnings, new filings, or new candidate research surfaces evidence touching any of the 32 cases, re-run treatment classification. Don't wait for quarterly review; drift propagates.
3. **Multi-citator parity check.** Hellyer (2018) — Shepard's, KeyCite, BCite disagree non-trivially. Run our drift classification with 2 independent classifiers (e.g., LLM-A + mechanical-rule-set) and flag disagreement. Never trust a single classifier on high-stakes retirement-or-keep decisions.
4. **Implicit-drift detection is hard.** Formal drift (operator explicitly retires a case) is reliable. *Implicit* drift (the case's reasoning is now incompatible with new evidence but no one's flagged it) is unreliable. → require periodic full audit, not just incremental flags.
5. **Era-sensitivity warning.** [arXiv 2510.20941](https://arxiv.org/pdf/2510.20941) — LLMs fail on older case-pair drift detection. As our catalog ages past 5-10 years, increase human-review frequency on the older cases.

### D5. Most-cited calibration pitfall

**Single most-cited pitfall: misgrounding (the citation exists and the case exists, but the case doesn't say what the system claims it says).**

This is the dominant failure mode in Stanford RegLab's evaluation of Lexis+ AI and Westlaw AI-Assisted Research ([Magesh 2024/2025](https://dho.stanford.edu/wp-content/uploads/Legal_RAG_Hallucinations.pdf)). It is more common than "case doesn't exist" hallucination, harder to catch, and the specific failure mode that drives the lawyer adoption-trust gap (67% override rate; only 1-in-5 high-trust).

**Why this matters for our case:** when our retrieval surfaces "this candidate is most similar to historical-case-K" and the LLM rubric explains "because both have leverage > 4x and funding-mix concentration", the failure mode is *not* "case K doesn't exist in the catalog" — that's catchable. The failure mode is "case K's actual leverage was 2.5x and the rubric misread it" or "case K's outcome wasn't driven by leverage — it was driven by an unrelated factor the rubric ignored". This is misgrounding, and it requires:

- **Pinpoint-cite enforcement.** The rubric's claim "leverage > 4x" must be backed by a literal datum from the case record, not a paraphrase.
- **Manual sample audit.** Stanford-RegLab-style: hand-verify a random sample of LLM rubric outputs against the case record before trusting the system at scale.
- **Cross-encoder reranker on faithfulness.** The reranker scores not just topical similarity but whether the rubric's justification is grounded in retrievable facts.

---

## Closing summary

The legal-precedent retrieval analog is a near-perfect fit for the 32-case counterfactual catalog problem. **Three top takeaways:**

1. **Hybrid mechanical-feature + LLM is the legal-tech consensus** (BM25/citation-graph for recall floor; LLM for precision-rerank). Quantified gains: +11.8-20.6% over either alone.
2. **TREC + LegalBench + Stanford RegLab give a ready-made test-set design**: stratified sample, 3-reviewer adjudication, preregistered protocol, three failure dimensions (existence/faithfulness/relevance) measured separately.
3. **The dominant failure mode is misgrounding, not nonexistence.** Defending against it requires pinpoint-cite enforcement and periodic hand-audit — not just citation-existence checks.
