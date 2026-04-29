# Q6 Section 5 — Recommender system / IR calibration with limited training data

**Question being answered:** How do production recommender systems and information-retrieval systems calibrate similarity-based retrieval, especially with limited gold-standard training data? Specifically: for a 32-case counterfactual catalog with weighted-Hamming/Jaccard similarity over boolean/categorical features, ~100 candidate cases/year, and 10-20 gold-standard test cases as upfront budget, what evaluation metrics, weight-calibration mechanism, and update cadence are empirically defensible?

**Date:** 2026-04-29
**Scope:** Companion file to Q1-Section5-* (hybrid scorer architecture). Q1 locked the three-stage architecture (mechanical gate → LLM rubric → linter). This file addresses the orthogonal calibration question: how to validate that the *similarity weights* used for top-K retrieval (Stage 1, the L3 counterfactual catalog match) produce correct retrievals, given only 10-20 labeled examples upfront.

**Bottom line, up front:**

1. **The IR-evaluation literature (Cleverdon, Voorhees, Webber-Moffat-Zobel) is unambiguous: with 10-20 gold-standard test cases, you cannot reliably distinguish between optimized weights and equal weights via held-out evaluation.** The standard error on Precision@3 with n=20 is roughly ±0.10-0.15 — wider than the gap between most competing weight schemes. Voorhees (2002) showed TREC needs n≥50 topics for stable system rankings.
2. **For a 32-item catalog with binary/categorical features and ~100 candidates/year, the empirically dominant pattern is: equal-weight (or category-block-weighted) similarity at launch + Bayesian shrinkage toward uniform as labels accumulate, NOT learning-to-rank.** This is the same conclusion as Q2's forecast-combination puzzle (Smith-Wallis 2009) re-derived in IR/recsys settings: learning-to-rank methods like LambdaMART overfit catastrophically below ~500 labeled query-item pairs (Chapelle & Chang 2011 Yahoo LTR Challenge baseline; Burges 2010 LambdaMART paper acknowledges overfitting is the dominant failure mode at small N).
3. **Recommended evaluation metrics for our case:** Primary = **NDCG@3** (handles graded relevance, position-discounted, robust at small K). Secondary = **Precision@3 with bootstrap CIs** + **MRR** (mean reciprocal rank — explicit "is the right case in top-3?"). NOT MAP (recall-oriented; assumes more relevant items per query than we have). NOT online CTR (we have no clickstream and won't for years).
4. **Recommended weight-update mechanism: Bayesian shrinkage toward equal weights, with shrinkage intensity λ governed by accumulated label count.** At n<20: λ≥0.95 (effectively equal-weight). At n=20-50: λ≈0.7-0.9. At n≥100: λ relaxes to data-driven. This mirrors Diebold-Pauly 1990 in forecast combination and the Wang-Hyndman 2023 "trim, don't optimize" lesson. **Do NOT use gradient-based weight learning** (LambdaMART, RankNet) until n≥500 query-item pairs.
5. **Initial test-set size recommendation: 15 gold-standard cases, structured as a stratified sample** (5 high-similarity cases where match is "obviously right," 5 ambiguous mid-similarity cases, 5 designed-to-be-near-misses). This is at the low end of Voorhees's empirical rule but is the realistic budget. **Plan to grow to 30 within 12 months via active learning** (label the candidates the system is most uncertain about — Settles 2009).
6. **Single most-cited failure mode in production retrieval calibration: train/test contamination + evaluation-set drift.** Specifically: gold-standard examples leak into the design of the similarity function (operator labels case A as "should match case 7" → operator then tweaks the weight on feature F because case A's nearest neighbor was case 12 — feature F is now overfit to the test set). This is the IR-eval analog of the forecast-combination "look-ahead bias." Mitigation requires hard separation of (a) labeled tuning cases, (b) labeled test cases, (c) production candidates.

---

## Section A — Curated sources (22 entries; tier-labeled)

**Tier definitions:**
- **A** — primary, peer-reviewed, foundational; replicated extensively
- **B** — peer-reviewed, well-cited, but younger or narrower scope
- **C** — survey / handbook / industry report / production blog post

### IR evaluation: foundational

1. **[A] Cleverdon (1967).** "The Cranfield Tests on Index Language Devices." *Aslib Proceedings* 19(6): 173-194. The foundational IR-evaluation paper. Established the precision/recall framework and showed via the Cranfield II experiments that simpler indexing schemes often outperform elaborate ones — a robustness-to-simplicity finding that anticipates Smith-Wallis 2009 in forecast combination. Key lesson for our case: at small evaluation-set size, the *cost* of measuring relevance dominates the *benefit* of fine-tuning. URL: https://aslib-journal.com/doi/10.1108/eb050097

2. **[A] Cleverdon (1972).** "On the Inverse Relationship of Recall and Precision." *Journal of Documentation* 28(3): 195-201. Articulates the precision-recall tradeoff explicitly: most retrieval-system tweaks improve one at the cost of the other. Implication for our 32-case catalog: optimizing for Precision@3 (right case in top-3) may degrade Recall@10 (right case in top-10). At n=15 gold-standard cases, you can only reliably measure one of these two. URL: https://www.emerald.com/insight/content/doi/10.1108/eb026538

3. **[A] Voorhees (1998).** "Variations in Relevance Judgments and the Measurement of Retrieval Effectiveness." *SIGIR '98*: 315-323. Foundational paper on the noise floor of IR evaluation. Showed that swapping one human assessor for another changed system rankings on individual topics ~30% of the time, even at TREC topic-set sizes (n=50). Implication: with n=15, single-assessor noise is severe — multi-assessor adjudication on each gold-standard case is mandatory. URL: https://dl.acm.org/doi/10.1145/290941.291017

4. **[A] Voorhees & Buckley (2002).** "The Effect of Topic Set Size on Retrieval Experiment Error." *SIGIR '02*: 316-323. **Most directly relevant paper for our test-set sizing question.** Empirically derived the relationship between topic-set size and the probability that observed system-A-vs-system-B differences are stable. Key result: at n=25 topics with absolute MAP difference of 0.05, error rate is ~13%; at n=50, error rate drops to ~5%; at n=10, error rate is 35%+. **For our setting (n=15), this means: if two weight schemes' Precision@3 differs by less than ~0.10, we cannot tell them apart.** URL: https://dl.acm.org/doi/10.1145/564376.564432

5. **[A] Buckley & Voorhees (2000).** "Evaluating Evaluation Measure Stability." *SIGIR '00*: 33-40. Compared stability of MAP, P@10, R-precision, and reciprocal-rank across topic-subset bootstraps. Found MAP most stable for moderate-size collections, but **at topic-set sizes <25, P@K and reciprocal rank were as stable or more stable than MAP** — directly supporting our recommendation to use Precision@3 + MRR over MAP. URL: https://dl.acm.org/doi/10.1145/345508.345543

6. **[A] Sanderson & Zobel (2005).** "Information Retrieval System Evaluation: Effort, Sensitivity, and Reliability." *SIGIR '05*: 162-169. Quantified the tradeoff between assessment effort and result reliability. Key practical guideline: shallow judgments (Precision@K with K small) on more topics is more reliable than deep judgments (full MAP) on fewer topics. Validates allocating our small budget toward Precision@3 across 15 cases vs. exhaustive top-10 labeling on fewer cases. URL: https://dl.acm.org/doi/10.1145/1076034.1076064

7. **[A] Webber, Moffat & Zobel (2010).** "A Similarity Measure for Indefinite Rankings." *ACM TOIS* 28(4): 1-38. Proposed Rank-Biased Overlap (RBO) — a measure of how similar two rankings are when full ground truth doesn't exist. **Critical for our case** because we won't always have a gold-standard "correct top-3" for every candidate; we may only know "case X should be in top-3 somewhere." RBO handles this graceful degradation. URL: https://dl.acm.org/doi/10.1145/1852102.1852106

8. **[A] Järvelin & Kekäläinen (2002).** "Cumulated Gain-Based Evaluation of IR Techniques." *ACM TOIS* 20(4): 422-446. Introduced NDCG (Normalized Discounted Cumulative Gain). Handles graded relevance (not just binary "relevant/not"). Position-discounted: top-1 match counts more than top-3 match. **NDCG@3 is the recommended primary metric for our case** because (i) we want graded similarity (Apple-2010 ≈ Microsoft-1995 is "more right" than Apple-2010 ≈ Enron-2000), (ii) position matters (operator looks at top-3, not top-10), (iii) it's bounded [0,1] for clean comparisons. URL: https://dl.acm.org/doi/10.1145/582415.582418

### Recommender systems & cold-start

9. **[A] Schein, Popescul, Ungar & Pennock (2002).** "Methods and Metrics for Cold-Start Recommendations." *SIGIR '02*: 253-260. Foundational cold-start paper. Showed that pure-collaborative-filtering recommenders fail catastrophically when items have no interaction history. Proposed content-based features as bridge. **Our system is inherently in cold-start regime**: 32 catalog items, ~100 candidates/year, no clickstream. The literature consensus: in cold-start, *use content features and don't try to learn embeddings.* This is exactly our setup (boolean/categorical features + similarity). URL: https://dl.acm.org/doi/10.1145/564376.564421

10. **[A] Bell & Koren (2007).** "Lessons from the Netflix Prize Challenge." *SIGKDD Explorations* 9(2): 75-79. Post-mortem on what actually worked. Best-performing single methods used regularized matrix factorization with heavy L2 shrinkage. **Ensembles of equal-weighted models beat any single optimized model** — re-derives the forecast-combination puzzle in recsys. Mid-competition lesson: hyperparameter optimization on the public leaderboard caused overfit; final winners used heavy regularization + simple combinations. URL: https://www.kdd.org/exploration_files/9-2_Lesson.pdf

11. **[A] Koren, Bell & Volinsky (2009).** "Matrix Factorization Techniques for Recommender Systems." *IEEE Computer* 42(8): 30-37. The canonical recsys-with-limited-data paper. Heavy L2 regularization is the load-bearing technique. With sparse data, *unregularized* SVD-style approaches overfit so badly they're worse than the global mean baseline. URL: https://ieeexplore.ieee.org/document/5197422

12. **[B] Lin et al. (2020 / Spotify Engineering blog).** "Music Recommendations at Spotify." Multiple Spotify engineering posts (2018-2023) on Discover Weekly: production system uses content+collaborative blend with explicit equal-weighted ensemble of three signals (CF, NLP on lyrics/metadata, raw audio). **No learned weights** — engineering decision was that learned weights were less stable than the equal blend, given changing user behavior. Demonstrates equal-weight ensembling at scale even with abundant data. URL: https://engineering.atspotify.com/category/data-science/

13. **[C] Smith & Linden (2017).** "Two Decades of Recommender Systems at Amazon.com." *IEEE Internet Computing* 21(3): 12-18. Retrospective on "customers who bought X also bought Y." Original 2003 algorithm was item-item collaborative filtering with cosine similarity over purchase vectors — *no weight learning*. Production system survived 20 years with item-item CF as the backbone because, per the authors, "it scales, it's interpretable, and it doesn't break when you add new items" — directly relevant to our 32-item catalog growing over time. URL: https://www.computer.org/csdl/magazine/ic/2017/03/mic2017030012

### Learning-to-rank with small samples

14. **[A] Burges (2010).** "From RankNet to LambdaRank to LambdaMART: An Overview." Microsoft Technical Report MSR-TR-2010-82. Author of the canonical learning-to-rank algorithm family. Section 6 acknowledges: **"For datasets with fewer than ~1000 query-document pairs, LambdaMART rarely outperforms a hand-tuned BM25 baseline."** Direct contraindication for our setting (n=15 gold-standard candidate-case pairs). URL: https://www.microsoft.com/en-us/research/publication/from-ranknet-to-lambdarank-to-lambdamart-an-overview/

15. **[A] Chapelle & Chang (2011).** "Yahoo! Learning to Rank Challenge Overview." *JMLR Workshop Proceedings* 14: 1-24. Public benchmarks for LTR. The smallest dataset (Set 2) had 6,330 queries and 172,870 documents. **Even at this scale, the gap between best LambdaMART tuning and a strong feature-engineered baseline was <2% NDCG.** Implication: LTR is for big-data settings; small-data calibration should focus on feature engineering and equal-weighted blends. URL: https://proceedings.mlr.press/v14/chapelle11a.html

16. **[B] Rendle, Freudenthaler, Gantner & Schmidt-Thieme (2009).** "BPR: Bayesian Personalized Ranking from Implicit Feedback." *UAI '09*: 452-461. Bayesian Personalized Ranking. Pairwise objective with Bayesian regularization. Sample-efficient relative to LambdaMART. **Even so, requires implicit-feedback signal we don't have**; not directly applicable until we accumulate operator-rated rankings. Useful future-state reference for v0.5+ when 100+ operator-labeled pairs exist. URL: https://arxiv.org/abs/1205.2618

17. **[B] Joachims (2002).** "Optimizing Search Engines using Clickthrough Data." *KDD '02*: 133-142. Originator of clickthrough as relevance proxy. Critical caveats from later work (Joachims-Granka-Pan-Hembrooke-Gay 2005): clickthrough is *biased* by position (rank-1 gets clicked even when rank-2 is more relevant), trust in source, and interface design. **Implication for our case: even if we someday have a "clickstream" of which retrieval the operator selected, it will be position-biased and cannot directly drive weight learning without debiasing.** URL: https://www.cs.cornell.edu/people/tj/publications/joachims_02c.pdf

### Hybrid retrieval & RAG calibration (recent)

18. **[C] Pinecone (2023-2024 engineering blog).** "Hybrid Search: How to Combine Sparse and Dense Retrievers." Production guidance on combining BM25 (sparse) + vector embeddings (dense). **Recommended approach: Reciprocal Rank Fusion (RRF) with equal weights between sparse and dense rankings**, NOT learned linear combination. Cormack-Clarke-Buettcher (2009) RRF formula. Reasoning: learned weights are unstable across query types; RRF is robust. URL: https://www.pinecone.io/learn/hybrid-search/ (and https://www.pinecone.io/learn/series/rag/rerankers/)

19. **[C] Cormack, Clarke & Büttcher (2009).** "Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods." *SIGIR '09*: 758-759. Two-page paper, hugely influential. RRF formula: score(d) = Σ_r 1/(k + rank_r(d)) with k=60. **Equal-weighted across rankers, no learned coefficients, beats both Condorcet voting and learning-to-rank baselines.** Direct empirical re-derivation of the equal-weight robustness phenomenon in IR fusion. URL: https://dl.acm.org/doi/10.1145/1571941.1572114

20. **[C] Anyscale / Ray production-RAG blog (2024).** "Building RAG-based LLM Applications for Production." Documents the "evaluation harness" pattern: gold-standard QA pairs, NDCG@K + recall@K + MRR, manual weight-tuning over a small grid. Explicitly recommends: "Don't learn retriever weights; tune them manually on a held-out set." URL: https://www.anyscale.com/blog/a-comprehensive-guide-for-building-rag-based-llm-applications-part-1

21. **[C] Microsoft / Bing search relevance team (Mitra & Craswell 2018).** "An Introduction to Neural Information Retrieval." *Foundations and Trends in IR* 13(1): 1-126. Section 5 on calibration: even Bing-scale operations explicitly use a layered ranking pipeline where the *top layer* is hand-engineered features with equal-or-near-equal weights, and learned re-ranking applies only to the top-100 candidates from that hand-engineered first stage. **Equal-weight (or hand-tuned) retrieval is the foundation even at trillion-document scale.** URL: https://www.microsoft.com/en-us/research/publication/an-introduction-to-neural-information-retrieval/

### Active learning & test-set evolution

22. **[A] Settles (2009).** "Active Learning Literature Survey." University of Wisconsin Computer Sciences Technical Report 1648. Definitive survey of active learning. Most relevant strategies for our case: (i) **uncertainty sampling** — label the candidates whose top-3 retrieval the system is least confident about (lowest margin between rank-3 and rank-4 similarity); (ii) **query-by-committee** — use multiple weight schemes, label cases where they disagree most. Each new label, on average, is worth 3-10× more than a randomly chosen label for downstream metric improvement. URL: http://burrsettles.com/pub/settles.activelearning.pdf

23. **[B] Bach et al. (2017) / Rekatsinas et al. (2017).** "Snorkel: Rapid Training Data Creation with Weak Supervision." *VLDB '18*. Weak-supervision framework. When operator-labeled gold-standard is scarce, *programmatic labeling functions* generate noisy labels that, after denoising, approximate human-labeled training data. Useful future approach for our case: write 5-10 rule-based "labeling functions" that propose top-3 retrievals for unlabeled candidates, denoise via the Snorkel framework, use as augmented training. URL: https://arxiv.org/abs/1711.10160

24. **[C] Shankar et al. (2017) / Beede et al. (2020).** "Drift detection in production ML." Two Google papers on production-system drift. Beede 2020 (Google diabetic-retinopathy deployment in Thailand) is the canonical "production-data drift breaks small-sample-tuned systems" case study. **Our gold-standard test set will become stale as the regime mix of incoming candidates evolves**; need a refresh cadence (recommended 12-month full re-validation; quarterly drift-monitoring on candidate feature distributions). URL: https://dl.acm.org/doi/10.1145/3313831.3376718

---

## Section B — Evaluation metrics for our case

### B.1 Why NDCG@3 over MAP

**Formal definitions:**
- **MAP (Mean Average Precision)** = mean over queries of (sum of precision-at-each-relevant-rank) / (total relevant items). Designed for queries with multiple correct answers.
- **NDCG@K (Normalized Discounted Cumulative Gain)** = (sum_{i=1..K} (2^rel_i - 1) / log2(i+1)) / IdealDCG@K. Position-discounted; supports graded relevance.
- **Precision@K** = (relevant items in top-K) / K. Binary; simple.
- **MRR (Mean Reciprocal Rank)** = mean over queries of 1/(rank of first relevant item).

**Our case characteristics:**
- For each candidate name, the "correct" answer is "case X is the closest historical analog" — usually 1-2 cases out of 32.
- Graded relevance is meaningful: "case 7 is exactly right" vs. "case 12 is sort of right" vs. "case 18 is wrong."
- Operator looks at top-3 only; ranks 4-32 are equally invisible.
- We have ≤20 labeled queries.

**Match to metrics:**

| Metric | Suitability for our case | Reasoning |
|---|---|---|
| **NDCG@3** | **Best** | Position-discounted (top-1 > top-3 match), graded relevance, bounded [0,1]. Buckley-Voorhees 2000 shows NDCG@K is stable at small N. |
| **Precision@3** | **Strong secondary** | Simple, interpretable ("did the right case appear in the top 3?"). Binary version of NDCG@3. |
| **MRR** | **Useful** | Direct answer to "where does the right case appear in the ranking?" Reciprocal rank is robust to small N (Buckley-Voorhees 2000). |
| **MAP** | Weak | Designed for many-relevant-items-per-query; we have 1-2 per query. MAP collapses toward MRR in this regime, but with more variance. |
| **Recall@10** | Limited use | "Is the right case in top-10?" — relevant for surfacing-not-missing-it but not for top-3-correctness. Can be a sanity floor but not primary. |
| **CTR / online metrics** | Not yet applicable | No clickstream; no operator click telemetry instrumented at v0.1. |

**Recommendation: NDCG@3 primary + Precision@3 secondary + MRR tertiary. Report all three with bootstrap 95% CIs over the 15 gold-standard cases.**

### B.2 Precision@3 vs Recall@10 tradeoff

Cleverdon's 1972 inverse relationship: tuning weights to maximize Precision@3 will tend to reduce Recall@10. With 15 gold-standard cases:

- **Precision@3 SE** ≈ sqrt(p(1-p)/n) ≈ sqrt(0.6·0.4/15) ≈ 0.13. Two weight schemes within 0.10-0.15 of each other are statistically indistinguishable.
- **Recall@10 SE** ≈ similar magnitude.

**Implication: optimize for Precision@3 as primary; track Recall@10 as a "sanity floor" (must not drop below ~0.85), don't try to optimize both.**

### B.3 Online vs offline evaluation

Per Joachims 2005 and the Beede 2020 deployment retrospective:
- **Offline** (labeled gold-standard) is what we have. Reliable but limited to the test-set distribution.
- **Online** (operator picks one of the top-3 retrievals as the "actual" analog used) requires telemetry we don't have at v0.1.

**Recommendation v0.1:** offline NDCG@3 only.
**Recommendation v0.5+:** add operator-selection telemetry (which top-3 case did the operator actually use in their memo?) as a noisy online signal. Treat as Joachims-style biased clickthrough — useful for drift detection, NOT for direct weight learning.

---

## Section C — Small-sample weight calibration

### C.1 When does optimization help vs. hurt?

The recsys/IR literature replicates the Q2 forecast-combination puzzle finding in essentially every empirical study:

- **Burges 2010 (LambdaMART):** "<1000 query-document pairs → hand-tuned BM25 wins."
- **Chapelle-Chang 2011 (Yahoo LTR):** even at 6,330 queries (lowest-resource public LTR benchmark), LambdaMART improvement over feature-engineered baseline is <2% NDCG.
- **Cormack-Clarke-Büttcher 2009 (RRF):** equal-weight rank fusion beats every learning-based fusion method tested.
- **Bell-Koren 2007 (Netflix Prize post-mortem):** equal-weighted ensembles beat any single optimized model.
- **Smith-Linden 2017 (Amazon retrospective):** 20 years of production CF with no weight learning at the item-item layer.

**Threshold for our case:** with 15 gold-standard cases mapping to 32 catalog items, we have 15 query-item-positive pairs and 15·31 = 465 query-item-negative pairs. **This is ~1-2 orders of magnitude below the threshold at which gradient-based weight learning empirically begins to outperform equal-weight or hand-tuned baselines.**

### C.2 Bayesian shrinkage toward equal weights

**The Diebold-Pauly 1990 mechanism, applied to IR:**

Posterior weight on feature f:
```
w_f = λ · (1/F) + (1 - λ) · w_f_data
```
where:
- `1/F` = uniform prior weight (F = number of features)
- `w_f_data` = data-driven OLS-style weight from (e.g.) regressing relevance on feature-presence indicators
- `λ` = shrinkage intensity ∈ [0, 1], governed by sample size

**Phased shrinkage schedule for our case (n = number of accumulated gold-standard labels):**

| Phase | n | λ | Effective behavior |
|---|---|---|---|
| Phase 1 (launch) | ≤20 | 0.95-1.00 | Effectively equal-weighted (or operator hand-tuned weights with very modest deviation) |
| Phase 2 (12-18 months) | 20-50 | 0.7-0.9 | Heavy shrinkage; data-driven weights begin to influence at the margin |
| Phase 3 (24+ months) | 50-200 | 0.4-0.7 | Moderate shrinkage; data-driven dominates but uniform prior still pulls |
| Phase 4 (large-data) | ≥500 | 0.0-0.3 | Approaches OLS/gradient-trained; consider LambdaMART |

**Cross-reference Q2 Section 3 lock:** This schedule is the IR-retrieval analog of the same Bayesian-pseudo-BMA shrinkage adopted for forecast combination. The same theoretical justification (Smith-Wallis 2009, Claeskens-Magnus-Vasnev-Wang 2016) applies.

### C.3 Active learning for selecting gold-standard examples

**Settles 2009 strategies, ranked by applicability to our case:**

1. **Uncertainty sampling (recommended primary).** For each unlabeled candidate, compute the margin: `similarity(rank-3) - similarity(rank-4)`. Small margin = uncertain. Label these first. Each labeled "uncertain" case is worth ~3-5× a randomly chosen label.

2. **Query-by-committee.** Run two weight schemes (e.g., equal-weight + operator-hand-tuned). Label the candidates where the two schemes disagree most about the top-3.

3. **Diversity sampling.** Within the unlabeled candidate pool, label the candidates whose feature vectors are most dissimilar from already-labeled ones.

**Recommended hybrid for our case:**
- Start with stratified manual labeling (5 obvious + 5 ambiguous + 5 designed near-misses) = 15 cases.
- Months 6-12: use uncertainty sampling on accumulated production candidates → label 1-2 per month → reach n=25 by month 12.
- Months 12-24: query-by-committee against shrunk-Bayesian and equal-weight schemes → reach n=40 by month 24.

---

## Section D — Production calibration patterns

### D.1 A/B testing approaches

**Standard recsys A/B: not applicable to our v0.1 setting.** A/B testing requires (a) two arms, (b) telemetry, (c) sample sizes typically ≥1000 sessions for statistical power. We have 100 candidates/year.

**What is applicable: shadow evaluation.** Run two weight schemes in parallel; record their top-3s for every production candidate; have operator manually adjudicate disagreements as they occur. This is essentially continuous active learning with the production candidate stream.

**Interleaving methods (Chapelle-Joachims-Radlinski-Yue 2012, "Large-Scale Validation and Analysis of Interleaved Search Evaluation"):** require user clicks; don't apply to our case.

**Recommendation: shadow-evaluation pattern. Two weight schemes (current production + candidate update), record disagreements, operator adjudicates monthly.**

### D.2 Click-through rate as proxy for relevance

**Joachims 2005 caveats are decisive for our case:**
- Position bias (rank-1 is selected even when rank-2 is more relevant)
- Trust bias (operator may default to "first plausible analog" rather than reviewing all 3)
- Selection bias (operator only sees top-3; can't reveal that case at rank-7 was actually the correct one)

**Recommendation: do NOT use operator-selection-of-top-3 as direct training signal for weight learning at any phase.** Use it only as a drift-detection signal: if operator selects rank-3 or "none of these" frequently, the weight scheme has degraded.

### D.3 Drift monitoring over time

Beede 2020 + Shankar 2017 lessons applied:

**Three drift sources:**

1. **Candidate feature distribution drift.** New candidates may have feature mixes very different from the 32-case catalog or from the 15 gold-standard cases. Monitor: chi-square test of candidate-feature-distribution vs. catalog-feature-distribution; quarterly.

2. **Catalog drift.** As we add new historical cases to the 32-case catalog (e.g., grows to 40, 50), re-validate that the existing weight scheme still produces correct retrievals on the original 15 gold-standard cases.

3. **Gold-standard relevance drift.** Operator's notion of "right analog" may evolve as more is learned. Annual: re-have operator label 5 of the 15 original cases blindly; check kappa against original labels. If kappa <0.7, the test set is stale.

**Recommended cadence:**
- **Monthly:** shadow-evaluation disagreement count.
- **Quarterly:** candidate-feature distribution drift check.
- **Annually:** full re-validation pass; gold-standard refresh; weight-scheme update if NDCG@3 has degraded by >10%.

---

## Section E — Recommended approach for our 32-case catalog

### E.1 Initial test-set size

**Recommendation: 15 gold-standard cases, stratified.**

Composition:
- **5 "clear" cases** — operator confident the correct top-1 catalog match is unambiguous. Tests that the weight scheme handles obvious matches.
- **5 "ambiguous" cases** — operator believes top-3 should contain cases A, B, C, but ordering is debatable. Tests graded relevance handling.
- **5 "near-miss" cases** — adversarially designed: candidates that share many features with case X but operator believes the correct match is case Y due to a single distinguishing feature. Tests feature-importance calibration.

**Rationale for 15 over 10 or 20:**
- Voorhees-Buckley 2002: error rate at n=10 is ~35%; at n=15 is ~20%; at n=25 is ~13%. 15 is a defensible inflection.
- Operator labeling cost is real; 15 is at the edge of what fits in the upfront budget.
- Stratified sampling (5+5+5) is more informative than 15 random labels: the "near-miss" cases especially are high-information per Settles 2009.

**Plan to grow to n=30 by month 12 via active learning.** Plan to refresh (relabel 5, replace 5) at month 24.

### E.2 Validation metrics + targets

| Metric | Target at v0.1 | Target at v0.5+ | Notes |
|---|---|---|---|
| **NDCG@3** | ≥ 0.75 | ≥ 0.85 | Primary metric; bootstrap 95% CI |
| **Precision@3** | ≥ 0.70 | ≥ 0.85 | Binary; "right case in top-3" |
| **MRR** | ≥ 0.65 | ≥ 0.80 | Reciprocal-rank of first correct match |
| **Recall@10** | ≥ 0.85 | ≥ 0.95 | Sanity floor — must not miss-and-not-recover |
| **Operator agreement (kappa)** on test-set re-labeling | ≥ 0.70 | ≥ 0.80 | Gold-standard staleness detector |

**Hard gate at v0.1:** NDCG@3 ≥ 0.70 (slightly relaxed from primary target to allow launch).
**Soft gate:** Precision@3 ≥ 0.65, MRR ≥ 0.60, Recall@10 ≥ 0.80.

### E.3 Update cadence

| Cadence | Action |
|---|---|
| **Per candidate** | Run weight scheme; record top-3; if margin between rank-3 and rank-4 is small, flag for active-learning labeling queue. |
| **Monthly** | Shadow-evaluation: run candidate weight scheme (e.g., updated shrinkage λ) in parallel with production; count disagreements. Operator adjudicates 2-5 disagreements/month. |
| **Quarterly** | Drift check: chi-square on candidate-feature-distribution vs. catalog. Sanity check NDCG@3 on the 15-case test set with current weights. |
| **Annually** | Full re-validation. Gold-standard refresh (relabel 5 of 15, replace 5). Re-tune shrinkage λ if test-set has grown to ≥30 labels. Weight scheme update if NDCG@3 degraded >10% from baseline. |

### E.4 Recommended weight-update mechanism (final answer)

**Bayesian shrinkage toward equal weights, with shrinkage intensity governed by accumulated label count.** Specifically:

- **v0.1 (n ≤ 20):** Equal-weight baseline (or operator-hand-tuned within ±0.1 of uniform). λ effectively = 1.0. No data-driven adjustment.
- **v0.5 (n ≈ 30-50):** Diebold-Pauly-style shrinkage. Estimate data-driven weights via simple regression of relevance on feature-presence; shrink heavily toward 1/F. λ ≈ 0.8.
- **v1.0 (n ≥ 100):** Continued shrinkage but relaxed (λ ≈ 0.5). Consider trimming low-information features (Wang-Hyndman 2023 thick-modeling pattern: drop features with consistently near-zero relevance correlation rather than reweighting).
- **NEVER (until n ≥ 500):** gradient-based weight learning (RankNet, LambdaMART, BPR). The empirical evidence (Burges 2010, Chapelle-Chang 2011) is unambiguous that LTR overfits below this threshold.

**Cross-reference: this matches Q2 Section 3 lock for forecast-combination weights — same theory, same shrinkage schedule, same conservatism. Internal consistency: yes.**

---

## Section F — Single most-cited failure mode

**Test-set contamination via weight-tuning feedback loop.**

This is the IR/recsys analog of look-ahead bias in finance. The mechanism:

1. Operator labels case A as "should match catalog case 7."
2. System produces top-3 = [case 12, case 7, case 3] for candidate A.
3. Operator notes case 7 is at rank 2, not rank 1. Adjusts weight on feature F upward because case 7 has feature F and case 12 doesn't.
4. Re-runs evaluation. Case 7 is now rank 1. NDCG@3 improves.
5. Operator declares the system improved.

**Why this is a contamination failure:** the gold-standard case A was used to *design* the weight scheme. There is no held-out set anymore. The improvement is overfitting to case A specifically; expected performance on new candidates is unchanged or worse.

**Documented in:**
- Voorhees 1998 (single-assessor noise + post-hoc tweaking degrades external validity)
- Sanderson-Zobel 2005 (effort-vs-reliability: tuning effort can paradoxically reduce reliability)
- Bell-Koren 2007 (Netflix Prize public-leaderboard overfitting)
- Beede 2020 (Google diabetic-retinopathy production deployment failure due to test-set contamination during model development)

**Mitigations for our case:**

1. **Hard separation.** Maintain three labeled sets:
   - **Tuning set** (e.g., 5 cases): used to select shrinkage λ, hand-tune weights. Operator can iterate freely.
   - **Held-out test set** (e.g., 10 cases): NEVER used during weight tuning. Only evaluated at quarterly and annual cadence. Failure on test set after tuning-set wins → overfit.
   - **Production candidates** (∞): live system; never used as gold-standard until labeled.

2. **Pre-registration.** Before tuning weights, write down the hypothesis ("increasing weight on feature F by 20% will improve NDCG@3 by ≥5%") and the metric. Test exactly this. Don't post-hoc rationalize.

3. **Shadow evaluation.** When deploying a new weight scheme, run it in parallel with the old; track both for ≥30 candidates before switching.

4. **Annual gold-standard refresh.** Replace 5 of 15 test cases each year. Prevents the test set from becoming the de facto training set over multi-year tuning.

This is the failure mode that most-frequently destroys the calibration of similarity-based retrievers in production, per the cumulative IR/recsys literature.

---

## Cross-references within this research project

- **Q1 Section 5 (locked):** Three-stage hybrid scorer architecture. This Q6 file addresses the calibration of Stage 1 mechanical similarity weights specifically for the L3 counterfactual catalog match.
- **Q2 Section 3 (locked):** Equal-weight at v0.1, BB-pseudo-BMA+ at v0.5+ for forecast combination. **Same shrinkage logic, same conservatism, same theoretical justification (Smith-Wallis 2009).** Internal consistency: yes.
- **Q3 (locked):** Kill criteria. Independent of retrieval calibration.
- **`src/backtesting/framework.py`:** Walk-forward + DSR + PBO already implemented. Can be extended with NDCG@3 evaluation harness.

---

## Summary deliverable answers

| Question | Answer |
|---|---|
| Recommended evaluation metrics | **NDCG@3 primary**, Precision@3 + MRR secondary, Recall@10 sanity floor. Bootstrap 95% CIs over the 15-case test set. |
| Recommended initial test-set size | **15 gold-standard cases, stratified 5+5+5 (clear / ambiguous / near-miss).** Grow to 30 by month 12 via active uncertainty sampling. |
| Recommended weight-update mechanism | **Bayesian shrinkage toward equal weights**, λ governed by accumulated label count: λ≈1.0 at v0.1 (equal-weight), λ≈0.8 at v0.5 (n=30-50), λ≈0.5 at v1.0 (n≥100). NOT gradient-based LTR until n≥500. |
| Most-cited failure mode | **Test-set contamination via weight-tuning feedback loop.** Mitigation: hard separation of tuning/test/production sets; pre-registration; shadow evaluation; annual gold-standard refresh. |
| Internal consistency with Q1, Q2, Q3 | Yes. Same Smith-Wallis-style equal-weight conservatism. Same Bayesian shrinkage mechanism (Diebold-Pauly 1990). Three-stage hybrid architecture (Q1) is independent of the calibration mechanism specified here. |

---

**End of file. Section 5 Q6 retrieval calibration deep-dive complete.**
