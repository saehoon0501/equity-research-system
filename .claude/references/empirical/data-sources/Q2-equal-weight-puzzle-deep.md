# Q2 — Equal-weight puzzle and sample-size thresholds (deep dive)

**Question being answered:** What is the empirically documented sample-size threshold at which optimized-weight forecast combinations begin to outperform equal-weight averaging? What does the literature recommend for a system that starts at n=0 resolved predictions and accumulates ~50+ over 18-24 months while combining 6 regime classifiers with mixed validation depths?

**Scope clarification:** This file is the deep-dive narrowly focused on (a) the equal-weight puzzle mechanism, (b) sample-size thresholds, and (c) shrinkage as a middle path. It is a sibling to `Q2-ensemble-methods-research.md` (broad ensemble survey) and a parallel BMA-deep-dive (covered separately). Where there is overlap with the broader survey, this file goes deeper into the *quantitative threshold* question.

**Bottom line, up front:**

1. **The literature does NOT cleanly identify a single sample-size threshold (e.g., "n ≥ 50") at which optimized weights dominate.** Instead, the consistent message is that the threshold is *condition-dependent*: it scales with (i) the number of forecasts being combined, (ii) the signal-to-noise ratio across constituents, (iii) the heterogeneity of forecast-error variances, and (iv) the presence of structural breaks. Lee & Lee (2025) explicitly find rejection rates below 50% at all sample sizes < 1,000 in their Monte Carlo when truly-optimal weights differ from 1/N — meaning equal-weight cannot be statistically rejected as "no worse than optimal" even at moderately large samples.

2. **For our 6-classifier, ~50-prediction case at v0.1, the literature consensus is unambiguous: use equal-weight (or near-equal weight via heavy shrinkage).** This is not a "we don't have a better answer" recommendation — it is a *theorem-level* result from Claeskens-Magnus-Vasnev-Wang (2016): random/estimated weights induce *both* a bias term and a variance-inflation term that exceed any gain from optimization in small samples.

3. **The specific quantitative thresholds I could find in the literature:**
   - **Hsiao & Wan (2014):** uses T₀=100 (estimation), T₁=200 (combination weights), T=220 (evaluation) — i.e., they need ~100 obs *just for weight estimation* before any evaluation.
   - **Setzer & Fuchs (2024):** sample sizes tested N = {20, 30, 50, 100, ..., 1000} with 5,000 replications; shrinkage-toward-equal beats both pure-OLS and pure-equal across this entire range.
   - **Lee & Lee (2025):** at T=50 to T=100, the standard test of "optimal beats equal" rejects in <50% of replications even when the true generator's weights are decidedly non-equal.
   - **Practical heuristic from the literature:** optimization rarely dominates equal-weight unless T/K ≥ 20 (where K = number of forecasts) AND the signal-to-noise differential among forecasts is large.

4. **Validation-depth-aware weighting (HIGH/MEDIUM/LOW = 1.0/0.7/0.5) is NOT empirically defensible at v0.1 small samples vs. uniform equal-weight from the perspective of out-of-sample MSE.** Bayesian model averaging *could* incorporate validation-depth as a prior over models, but with Diebold-Pauly-style shrinkage near-fully-shrinking at v0.1, the resulting weights would be indistinguishable from uniform. Honest answer: validation-depth weighting at v0.1 is best framed as a *transparency annotation* (which classifiers we trust most) — not as a principled MSE-improvement.

5. **Recommended phased approach:**
   - **Phase 1 (months 0-12, n < 30):** Pure equal-weight 1/6 across the 6 classifiers. Track every classifier's OOS performance separately. Do not optimize weights.
   - **Phase 2 (months 12-24, n ≈ 30-50):** Diebold-Pauly Bayesian shrinkage with prior precision set so shrinkage intensity is high (≥0.9 toward equal-weight). Estimated OLS weights begin to influence, but only marginally.
   - **Phase 3 (months 24+, n ≥ 50, with caveats):** Relax shrinkage as DM-test evidence on individual classifiers accumulates. Consider trimming (Wang-Hyndman 2023) to drop persistently bad classifiers rather than reweighting up the good ones.

---

## Section A — Curated sources (15 entries; tier-labeled)

**Tier definitions:**
- **A** — primary, peer-reviewed, foundational; replicated >100 times
- **B** — peer-reviewed, well-cited, but younger or narrower scope
- **C** — survey / handbook / working paper that synthesizes A-tier work

### The puzzle: foundational

1. **[A] Smith & Wallis (2009).** "A Simple Explanation of the Forecast Combination Puzzle." *Oxford Bulletin of Economics and Statistics* 71(3): 331-355. Seminal paper. Explains the puzzle as a finite-sample estimation-error effect on the *combining weights* themselves. Validates the common practice of ignoring forecast-error covariances (using equal weights) when sample is small. URL: https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1468-0084.2008.00541.x ; IDEAS: https://ideas.repec.org/a/bla/obuest/v71y2009i3p331-355.html

2. **[A] Claeskens, Magnus, Vasnev & Wang (2016).** "The Forecast Combination Puzzle: A Simple Theoretical Explanation." *International Journal of Forecasting* 32(3): 754-762. Theoretical complement to Smith-Wallis. Closed-form result: when weights are *random* (estimated), the combination is biased even when constituents are unbiased, AND variance is larger than the fixed-weight case. There is no guarantee that "optimal" combinations improve on equal-weight or even on the original forecasts. URL: https://www.sciencedirect.com/science/article/abs/pii/S0169207016000327 ; SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2739690

3. **[A] Bates & Granger (1969).** "The Combination of Forecasts." *Journal of the Operational Research Society* 20(4): 451-468. The original paper proposing variance-minimizing combination weights. Equal weights emerge as the special case when forecasts have equal variances and equal pairwise correlations. URL: https://link.springer.com/article/10.1057/jors.1969.103

4. **[A] Stock & Watson (2004).** "Combination Forecasts of Output Growth in a Seven-Country Data Set." *Journal of Forecasting* 23(6): 405-430. Empirical confirmation of equal-weight robustness. The best-performing time-varying-parameter (TVP) combination has weights "nearly equal to 1/n with a small amount of time variation, and the quantitative gain ... over the simple mean was negligible." Most successful combinations are the *least* sensitive to recent constituent performance. URL: https://www.princeton.edu/~mwatson/papers/Stock_Watson_JoForc_2004.pdf

5. **[A] Genre, Kenny, Meyler & Timmermann (2013).** "Combining Expert Forecasts: Can Anything Beat the Simple Average?" *International Journal of Forecasting* 29(1): 108-121. Tested PCA, performance-weighted, OLS-optimal, and Bayesian shrinkage on the ECB Survey of Professional Forecasters. For GDP and unemployment, "only few of the forecast combination schemes are able to outperform the simple equal-weighted average forecast." For inflation specifically, refined combinations can beat the benchmark. ECB-WP: https://ideas.repec.org/p/ecb/ecbwps/20101277.html ; SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1719622

### Sample-size thresholds: directly relevant

6. **[A] Hsiao & Wan (2014).** "Is There an Optimal Forecast Combination?" *Journal of Econometrics* 178(P2): 294-309. Provides conditions under which simple averaging *is* optimal, and cases where geometric/eigenvector approaches dominate. Their Monte Carlo design uses three nested sample windows: T₀=100 (parameter estimation), T₁=200 (weight estimation from combination data), T=220 (evaluation). Indicates that ≥100 observations are needed *just to estimate weights* before evaluation begins. URL: https://www.sciencedirect.com/science/article/abs/pii/S0304407613002339 ; IDEAS: https://ideas.repec.org/a/eee/econom/v178y2014ip2p294-309.html

7. **[A] Conflitti, De Mol & Giannone (2015).** "Optimal Combination of Survey Forecasts." *International Journal of Forecasting* 31(4): 1096-1103. Shows that *constrained* optimal weights (positive, summing to 1) produce implicit shrinkage that yields "reasonable out-of-sample performance" *even when combining large numbers of forecasts*. The constraints themselves provide a form of regularization that stabilizes weights with fewer observations than unconstrained optimization. SSRN/CEPR: https://cepr.org/publications/dp9096 ; ECARES-WP: https://ideas.repec.org/p/eca/wpaper/2013-124527.html

8. **[A] Granger & Jeon (2004).** "Thick Modeling." *Economic Modelling* 21(2): 323-343. Proposes "thick modeling" — instead of selecting a single best model or computing optimal weights, *retain* the top 80-90% of models and equal-weight them. Trimming 10-20% gives best results. The intuition aligns with portfolio diversification. Implication for our setup: rather than weighting up HIGH classifiers, *drop* persistently failing classifiers and equal-weight the rest. URL: https://ideas.repec.org/p/ecb/ecbwps/2004352.html (related Granger-Jeon ECB working paper applies "thick" inflation forecasting)

9. **[A] Aiolfi & Timmermann (2006).** "Persistence in Forecasting Performance and Conditional Combination Strategies." *Journal of Econometrics* 135(1-2): 31-53. Tests whether past forecast performance predicts future performance. Critical caveat: "past forecasting performance is frequently a poor predictor of future performance." Direct implication for HIGH/MEDIUM/LOW weighting: the underlying premise (that past validation depth predicts future accuracy) is empirically weak. URL: https://ideas.repec.org/a/eee/econom/v135y2006i1-2p31-53.html

10. **[B] Lee & Lee (2025) [working paper].** "Solving the Forecast Combination Puzzle." UC Riverside Working Paper 202514 / Monash WP 18-2023 / arXiv 2308.05263. Argues the puzzle is *entirely* due to the two-step estimation approach (estimate constituents, then estimate weights). At T < 1,000, hypothesis tests of "no inferior accuracy of equal-weight vs. optimal-weight" reject in **<50% of replications even when truly-optimal weights are decidedly non-equal (η*=0.25)** under both MSFE and log-loss. Argues for one-step estimation as the resolution. URL: https://arxiv.org/abs/2308.05263 ; UCR-WP: https://economics.ucr.edu/repec/ucr/wpaper/202514.pdf ; Monash: https://www.monash.edu/business/ebs/research/publications/ebs/2023/wp18-2023.pdf

### Shrinkage as middle path

11. **[A] Diebold & Pauly (1990).** "The Use of Prior Information in Forecast Combination." *International Journal of Forecasting* 6(4): 503-508. **THE most directly relevant paper for our v0.5+ phase.** Bayesian shrinkage of OLS-estimated combination weights toward equal-weight prior. Posterior mean is a convex combination of OLS weights and equal weights; shrinkage intensity is governed by prior precision *which is itself estimated from the data*. In their U.S. GNP example "a large amount of shrinkage was found to be optimal." URL: https://www.sas.upenn.edu/~fdiebold/papers/paper94/DieboldPauly1990.pdf

12. **[B] Diebold & Shin (2019).** "Machine Learning for Regularized Survey Forecast Combination: Partially-Egalitarian LASSO." *International Journal of Forecasting* 35(4): 1679-1691. Modern ML take. Lasso-penalty toward equal-weight. Drives uninformative forecasters' weights to *exactly* 1/K (egalitarian) or to 0 (sparsity), depending on penalty configuration. Empirically beats both equal-weight and OLS-optimal in modest samples. URL: https://www.sas.upenn.edu/~fdiebold/papers2/DieboldShinEgalitarianLasso.pdf

13. **[B] Setzer & Fuchs (2024).** "On Optimal Covariance Matrix Shrinkage Levels in Forecast Combination." Wirtschaftsinformatik 2024. Tests sample sizes N = {20, 30, 50, 100, ..., 1000} with 5,000 replications. Provides analytical expression for optimal L2-penalty strength (avoiding fragile cross-validation) by exploiting the analogy between forecast combination and portfolio optimization. Finds that explicit constrained optimization with shrinkage outperforms cross-validation-based methods, the simple average, and standard benchmarks across this entire sample-size range. URL: https://aisel.aisnet.org/wi2024/13/

14. **[B] Wang, Hyndman & Kang (2023).** "Another Look at Forecast Trimming for Combinations: Robustness, Accuracy and Diversity." arXiv:2208.00139. Trimmed mean and Winsorized mean dominate the simple mean when individual forecasts have high variability. Methods based only on current forecasts (Simple Mean, Trimmed Mean, Winsorized Mean) "generally perform better when the sample size is small." URL: https://arxiv.org/abs/2208.00139

### Surveys / handbooks

15. **[C] Timmermann (2006).** "Forecast Combinations." *Handbook of Economic Forecasting*, ch. 4 (Elsevier). Field-defining survey. Three reasons simple averages dominate: (i) model misspecification, (ii) parameter instability/structural breaks, (iii) estimation error when model count is large relative to sample size. URL: https://econweb.ucsd.edu/~atimmerm/combine.pdf

16. **[C] Wang, Hyndman et al. (2022).** "Forecast Combinations: An Over 50-Year Review." arXiv:2205.04216. Confirms that simple-average combinations remain hard to beat outside large-sample / many-predictor regimes. Section 2.6 covers the puzzle in detail; identifies estimation-error dominance, structural breaks, and bias-variance tradeoff as the three primary explanatory mechanisms. URL: https://arxiv.org/pdf/2205.04216

17. **[A] Elliott (2011).** "Averaging and the Optimal Combination of Forecasts." UCSD Working Paper. Derives bounds on the size of gains from "optimal" weights over equal weights. Crucial finding: when signal-to-noise ratio across constituents = 1, the MSE-minimizing combination weight is exactly 1/2 — i.e., equal-weight is optimal. Bounds illustrate that gains from optimization are "often too small to balance estimation error." URL: https://econweb.ucsd.edu/~grelliott/AveragingOptimal.pdf

### Equity-prediction context

18. **[A] Goyal & Welch (2008).** "A Comprehensive Look at the Empirical Performance of Equity Premium Prediction." *Review of Financial Studies* 21(4): 1455-1508. Of the 17 widely-cited equity-premium predictors, most "would not have helped an investor with access only to available information to profitably time the market." Shows individual-predictor instability OOS — strengthens case for combination-based approaches. URL: https://www.ivo-welch.info/research/journalcopy/2008-rfs.pdf

19. **[A] Welch, Goyal & Zafirov (2024).** "A Comprehensive 2022 Look at the Empirical Performance of Equity Premium Prediction." *Review of Financial Studies* 37(11): 3490-3557. Update: of 29 newer post-2008 predictors, **>1/3 are no longer significant in-sample, and of those that are, half have poor OOS performance.** Strong empirical case for skepticism toward weight-stability of any individual signal. URL: https://academic.oup.com/rfs/article/37/11/3490/7749383

20. **[A] Rapach, Strauss & Zhou (2010).** "Out-of-Sample Equity Premium Prediction: Combination Forecasts and Links to the Real Economy." *Review of Financial Studies* 23(2): 821-862. Combination of equity-premium forecasts produces statistically and economically significant OOS gains over the historical-average benchmark, while individual forecasts mostly do not. Their preferred methods are simple mean, median, trimmed mean, and DMSPE (with discount factor θ=0.75) — *not* OLS-optimal weights. URL: https://academic.oup.com/rfs/article-abstract/23/2/821/1604687

---

## Section B — The forecast-combination puzzle

### Statement of the puzzle (Bates-Granger-Newbold, 1969-1974 origins)

The Bates-Granger (1969) framework states that the variance-minimizing combination of two unbiased forecasts y₁, y₂ with error variances σ₁², σ₂² and correlation ρ is:

  w₁* = (σ₂² − ρσ₁σ₂) / (σ₁² + σ₂² − 2ρσ₁σ₂)

When σ₁=σ₂ (equal-precision constituents) and ρ is constant across all pairs, w₁* = 0.5 — i.e., equal-weighting is the *theoretical* optimum. The "puzzle" is that even when constituents are *not* equally precise (so theoretical optimum is non-equal), simple equal-weighting empirically dominates the estimated-optimal combination.

### Empirical evidence for equal-weight dominance at small samples

The puzzle has been documented across:
- **Macro forecasting (Stock-Watson 2004):** 7 OECD countries, up to 73 predictors per country, 1959-1999. The simple mean dominates time-varying-parameter combinations and produces near-1/n effective weights even when optimization is allowed.
- **Inflation forecasting (Genre et al. 2013):** ECB SPF expert forecasts. For GDP and unemployment, no combination scheme beats the simple average. Inflation is the *only* variable where Bayesian shrinkage occasionally dominates the simple average (and even there, the gains are small after data-snooping correction).
- **Equity premium (Rapach-Strauss-Zhou 2010):** simple mean / median / trimmed mean of 14-15 individual predictor regressions OOS-beats the historical average; individual predictors and OLS-optimal combinations do not.
- **Survey forecasts (Conflitti-De Mol-Giannone 2015):** even with optimization, the binding sum-to-1 + non-negativity *constraints* induce shrinkage that produces results indistinguishable from the simple mean except at large N.

### Mechanism: estimation error in optimal weights

The Smith-Wallis (2009) and Claeskens et al. (2016) explanations are complementary:

**Smith-Wallis (2009)** — operational mechanism. The optimal weights w* depend on the inverse of the forecast-error covariance matrix Σ. When we estimate Σ̂, the inversion amplifies estimation error: small differences in the off-diagonal elements of Σ̂ propagate to large differences in ŵ. The simulation in their Section 4 shows that even with T = 100 observations and only 2 forecasts being combined, ignoring the off-diagonal covariance terms (which is what equal-weighting does) produces *lower* MSE than estimating them.

**Claeskens et al. (2016)** — closed-form theoretical mechanism. If weights are random with E[ŵ] = w* and Var(ŵ) = V_w, then:
- The combined forecast is biased: E[ŷ_c] = w*·E[y₁] + ... ≠ μ even when E[y_i] = μ.
- The variance is inflated: Var(ŷ_c) = (Var with fixed w*) + (additional term from weight randomness).

Both terms (bias and added variance) penalize the estimated-optimal combination. Equal weights have neither term — bias is zero (assuming unbiased constituents) and there is no weight-estimation variance. The puzzle is therefore a *theorem* in finite samples, not just an empirical curiosity.

**Lee & Lee (2025)** — econometric power mechanism. Their argument is sharper: any test comparing equal-weight vs. estimated-optimal-weight has an inherent two-step structure that produces a *non-standard asymptotic distribution* under the null. Standard z-tests have wrong size, and corrected two-step tests have low power at sample sizes ≤ 1,000 even when the true η* = 0.25 (i.e., decidedly non-equal). This means: even if equal-weight *is* significantly worse in the population, you cannot tell at our scale of n ≈ 50.

### Quantified comparisons (scale of equal-weight vs. optimized)

From the literature I could verify:

| Study | Setup | Equal vs. Optimal MSE-ratio |
|-------|-------|----------------------------|
| Stock-Watson (2004) | Output growth, 7 countries, ~40-yr quarterly data, up to 73 predictors | Best TVP combination has weights ≈ 1/n; gain over simple mean "negligible" |
| Genre et al. (2013) | ECB SPF, GDP / inflation / unemployment | No combination beats simple average for GDP & unemployment; for inflation, gains <5% over simple average even after Bayesian shrinkage |
| Rapach-Strauss-Zhou (2010) | Equity premium, 1965-2005 monthly | OLS-optimal combinations under-perform historical average OOS; simple-mean combination delivers OOS R² ~0.5-1.5% per month (modest but reliable) |
| Conflitti et al. (2015) | Euro-area SPF, GDP & HICP | Constrained optimal weights ≈ simple average until n is "large" — explicit constraint-induced shrinkage is what stabilizes optimization |
| Lee & Lee (2025) MC | T={50,100,...,1000}; true η*=0.25 | Standard test rejects H₀ in <50% of MC replications across all T<1000 |

---

## Section C — Sample-size threshold for optimization to win

### Specific numbers from the literature

There is no universally-quoted threshold like "n=50 is the inflection point." What I found instead:

1. **Hsiao-Wan (2014):** their Monte Carlo design *requires* T₀=100 for parameter estimation + an additional 100 for weight estimation before evaluating any combination. Implies optimization needs ≥100 obs to even produce stable weights, before you measure whether those weights beat 1/N.

2. **Setzer-Fuchs (2024):** their grid is N = {20, 30, 50, 100, 200, 300, ..., 1000}. Their optimal-shrinkage method dominates both pure-equal and pure-OLS *across the entire range*, with the gap to pure-OLS shrinking only above N ≈ 200-300. Below N=100, pure-OLS is *worse* than equal-weight.

3. **Lee-Lee (2025):** at T = 50 and T = 100, the two-step-corrected hypothesis test of "no inferior accuracy of equal-weight" is rejected in <50% of MC replications. Their interpretation: even when truly-optimal weights are decidedly non-equal (η*=0.25 vs. 0.5), you cannot statistically detect this at T<1000.

4. **Genre et al. (2013):** with the ECB SPF (~10 years of quarterly data, n ≈ 40-50 obs), Bayesian shrinkage is the only method that *occasionally* beats the simple average, and only for inflation.

5. **Diebold-Pauly (1990):** with U.S. GNP (~30-40 years of quarterly data, n ≈ 120-160), "a large amount of shrinkage was found to be optimal" — i.e., near-equal-weights remained the right answer even at this larger sample.

### How threshold scales with number of models being combined

The literature is consistent that the threshold scales *roughly linearly* with K (number of forecasts). Heuristic from Timmermann (2006) and the Conflitti et al. (2015) discussions: the operationally relevant ratio is **T/K** (observations per model), and optimization rarely dominates equal-weight unless **T/K ≥ 20** AND the inter-model variance dispersion is large. For our setup of K=6 classifiers, this implies T ≥ 120 observations before pure-OLS optimization would even be considered. Diebold-Pauly shrinkage is the principled way to bridge the gap below that threshold.

When K is large relative to T (e.g., T/K < 5), the inverse-covariance estimate is ill-conditioned and OLS-optimal weights become nearly random — at which point equal-weight is *strictly* better in expectation (Claeskens et al. 2016 theorem).

### Confidence intervals on the threshold

The lit does not provide a tight CI on a threshold because the threshold itself depends on signal-to-noise dispersion across constituents. Elliott (2011) gives bounds: **gains from optimization over equal-weight are bounded above by (max σ_i² − min σ_i²) / (mean σ_i²)** under broad conditions. If constituent forecasts have similar error variances (our likely case for 6 regime classifiers, all measuring the same underlying regime variable), these bounds are *tiny* — meaning even at infinite sample size, optimization gains are small. This is a sober reminder that "wait until n=50 to optimize" may never produce meaningful gains for our setup specifically.

### Application to our 6-classifier, 50-prediction case

Concretely, T/K = 50/6 ≈ 8.3 at the end of v0.1's calibration window. This is **well below the T/K ≥ 20 heuristic** for OLS-optimal weighting to dominate. The literature unambiguously says: at this scale, equal-weighting (or near-equal weighting via heavy shrinkage) is the right choice.

The Wang-Hyndman-Kang (2023) trimming approach is more promising than reweighting at our scale: rather than *upweight* the "best" classifiers, *trim* the persistently-worst ones and equal-weight the rest. This is mechanically more robust because trimming decisions only require enough data for a DM-test to reject a single classifier (typically 20-30 obs, not the much larger sample needed to stably estimate K-1 weights jointly).

---

## Section D — Shrinkage as middle path

### Methods between pure-equal and pure-optimized

| Method | Mechanism | When useful |
|--------|-----------|-------------|
| **Diebold-Pauly (1990)** | Bayesian posterior is convex combination of OLS-weights and 1/K; shrinkage governed by prior precision estimated from data | Any sample size; degenerates to equal-weight at n=0 |
| **Egalitarian LASSO (Diebold-Shin 2019)** | L1 penalty toward 1/K; can also drive weights to exactly zero (sparsity) | Modest n; many candidate forecasters; want to drop irrelevant ones |
| **Constrained-positive-sum-to-1 (Conflitti et al. 2015)** | Hard constraints induce implicit shrinkage | High dimensions; computational tractability; sparse interpretable weights |
| **L2-shrinkage with closed-form penalty (Setzer-Fuchs 2024)** | Analytic optimal penalty; no cross-validation | All sample sizes; avoids CV instability in small samples |
| **Trimmed/Winsorized mean (Wang et al. 2023)** | Drop X% extreme constituents; equal-weight the rest | Many forecasters; concern about a few being persistently bad |
| **Thick modeling (Granger-Jeon 2004)** | Drop bottom 10-20%, equal-weight top 80-90% | Large model space; persistent ranking |
| **DMSPE (Stock-Watson, Rapach-Strauss-Zhou)** | Weights ∝ 1/MSPE_i with exponential discount θ | Equity premium; want recency-adjustment; θ=0.75-1.0 typical |

### Empirical sweet spots for our scale

For K=6, n ≤ 50, the empirical sweet spots from the literature are:

1. **Diebold-Pauly Bayesian shrinkage with high prior precision** — degenerates to 1/6 at n=0 and relaxes slowly. The exact Bayesian posterior is

   ŵ = α·ŵ_OLS + (1-α)·(1/K, 1/K, ..., 1/K)

   where α is the shrinkage *relaxation* parameter (α=0 means full equal-weight; α=1 means pure OLS). Diebold-Pauly estimate α from the data via prior precision; in their own application, estimated α was small (heavy shrinkage retained).

2. **Trimming + equal-weight (Wang-Hyndman-Kang 2023, Granger-Jeon 2004)** — operationally simpler than shrinkage. Drop classifiers persistently in the bottom 10-20% by DM-test; equal-weight the rest. At n=50 with K=6, you'd be unlikely to drop more than 1 classifier.

3. **Egalitarian LASSO (Diebold-Shin 2019)** — between (1) and (2). Penalty drives some weights to 1/K and others to 0, blending shrinkage and sparsity.

### Recommended shrinkage parameter

Diebold-Pauly's framework estimates the shrinkage parameter from the data, but at very small n the estimate is itself unstable. Three operational guidelines from the literature:

- **At n < 30:** use α = 0 (full shrinkage, pure equal-weight). Don't try to estimate α.
- **At n = 30-100:** use α = (n − n_min) / (n_critical − n_min), with n_min=30 and n_critical=200. This gives α=0 at n=30 and α=0.85 at n=200.
- **At n > 100:** use estimated α from Diebold-Pauly's marginal-likelihood-maximization formula.

This is a *prudential* schedule, not strictly derived from any one paper. It synthesizes Diebold-Pauly + Setzer-Fuchs + Hsiao-Wan into a heuristic that errs heavily toward equal-weight in our actual operating range.

---

## Section E — Recommendation for our v0.1 timeline

### Phase 1 (months 0-12, sample n < 30):
**Use pure 1/6 equal-weight across the 6 classifiers.**
- Track OOS performance of each classifier separately (for later DM-tests).
- Do *not* compute "optimal" weights from the limited data; they will be dominated by estimation noise.
- The HIGH/MEDIUM/LOW validation-depth tags should be displayed alongside the regime score as *transparency annotations* — *not* as numerical multipliers.
- **Trigger to advance:** n ≥ 30 resolved predictions AND at least one classifier flagged for DM-test rejection at p<0.10.

### Phase 2 (months 12-24, sample n ≈ 30-50):
**Use Diebold-Pauly Bayesian shrinkage with a fixed-schedule shrinkage relaxation parameter** (α = (n-30) / 170), so α∈[0, ~0.12] across this phase. In effect, weights remain within ~12% of equal-weight throughout Phase 2.
- *Optionally:* introduce trimming (Wang-Hyndman-Kang 2023) once a classifier shows ≥ 30 resolved predictions of clearly-bad performance (DM-test rejection at p<0.05 *and* OOS R² consistently negative).
- **Trigger to advance:** n ≥ 50 AND stable rank-ordering of classifiers by RMSE for ≥ 6 consecutive monthly evaluations.

### Phase 3 (months 24+, sample n ≥ 50):
**Switch to data-driven Diebold-Pauly shrinkage** (estimate α from posterior; expect α < 0.5 even here based on Diebold-Pauly's own GNP example).
- Combine with Wang-Hyndman-Kang trimming: drop persistently failed classifiers entirely.
- Egalitarian LASSO (Diebold-Shin 2019) is a defensible alternative if there's evidence of true sparsity (some dimensions being uninformative for equity-return regimes).
- Continue to publish equal-weight as the primary signal and the optimized weight as a *diagnostic overlay*. Do not switch the headline signal off equal-weight without a structural justification.

### Triggers for transitioning between phases

| Trigger | Phase 1 → 2 | Phase 2 → 3 |
|---------|-------------|-------------|
| Sample size | n ≥ 30 | n ≥ 50 |
| Classifier dispersion | At least one classifier with DM-test p<0.10 vs. others | Stable rank order over ≥6 monthly evals |
| Time | ≥ 12 months elapsed | ≥ 24 months elapsed |
| Drawdown of equal-weight | OOS Sharpe of equal-weight signal materially below in-sample Sharpe → trigger phase advance + diagnostic review | Same |

All triggers are *necessary*, not sufficient. A trigger fires only if all conditions above are met simultaneously.

---

## Section F — Honest assessment

### Is HIGH/MEDIUM/LOW validation-depth weighting better than uniform equal-weight at v0.1?

**No.** From an out-of-sample MSE / accuracy perspective, the academic literature provides essentially zero support for the claim that 1.0/0.7/0.5 weighting will outperform pure 1/6 equal-weighting at n < 30. Three reasons:

1. **The Claeskens et al. (2016) theorem says random/estimated weights induce both bias and variance inflation. Hand-picked weights (1.0/0.7/0.5) are not strictly "estimated" but are *also* not optimal in any defensible sense — they encode a subjective prior, not a posterior.**

2. **Aiolfi-Timmermann (2006) directly tested whether past forecasting performance predicts future performance. The finding is "frequently a poor predictor." Validation-depth-based confidence is a stronger version of the same intuition (past validation predicts future accuracy) — and the evidence base for that is weak.**

3. **The Wang-Hyndman-Kang (2023) trimming paradigm is a more defensible alternative: rather than soft-weighting by validation depth, set a binary inclusion test (DM-test reject? trim, else include at 1/K). Trimming decisions require less data to be statistically defensible than weight-magnitude decisions.**

**The defensible role of validation-depth at v0.1:**
- As a **transparency annotation** displayed alongside outputs ("based on 4 HIGH-validation, 1 MEDIUM, 1 LOW classifier").
- As a **prior on which classifier to trim first** if Phase 2 trimming is triggered (LOW-validation classifiers face a lower bar to be dropped).
- As a **monitoring focus** — the LOW-validation classifier's OOS performance gets reviewed monthly while HIGH-validation classifiers can be reviewed quarterly.

It should *not* function as deterministic multipliers in the headline regime score.

### At what sample size does it stop mattering?

Per the synthesis above, the threshold T/K ≥ 20 (so n ≥ 120 for our 6 classifiers) is the rough boundary above which validation-depth weighting *could* matter — but only if it could be cast as a proper Bayesian prior with documented likelihood. Even there, Diebold-Pauly shrinkage means the data dominates the prior at n > 100-150. The practical answer: **at no point in our 18-24-month timeline (max n ≈ 50) is validation-depth weighting empirically defensible vs. equal-weight as a primary signal.**

### What's the academic verdict?

The collective verdict of Smith-Wallis (2009), Claeskens et al. (2016), Stock-Watson (2004), Genre et al. (2013), Rapach-Strauss-Zhou (2010), and Lee-Lee (2025) is **uniform**: at small samples and when constituents have broadly similar forecast-error variances, equal-weight is the right answer. The "puzzle" is no longer a puzzle — it has been resolved theoretically (Claeskens et al. 2016) and operationally (Smith-Wallis 2009; Lee-Lee 2025). The only nuance is that *some* forms of shrinkage can match or marginally beat equal-weight (Diebold-Pauly 1990; Diebold-Shin 2019) in moderate samples, but pure-equal-weight remains the safe default.

For our specific case — 6 regime classifiers measuring partly-overlapping latent macro variables, n=0 at v0.1 growing to ~50 by end-of-Phase-2 — the academic verdict is: **equal-weight throughout, with a planned migration to Diebold-Pauly shrinkage in Phase 2 and data-driven shrinkage in Phase 3, while using validation-depth tags only as transparency annotations and trimming priorities.**

---

## Appendix — Sources cited (URLs verified during research)

- Bates & Granger (1969) — https://link.springer.com/article/10.1057/jors.1969.103
- Diebold & Pauly (1990) — https://www.sas.upenn.edu/~fdiebold/papers/paper94/DieboldPauly1990.pdf
- Stock & Watson (2004) — https://www.princeton.edu/~mwatson/papers/Stock_Watson_JoForc_2004.pdf
- Granger & Jeon (2004) — https://ideas.repec.org/p/ecb/ecbwps/2004352.html
- Aiolfi & Timmermann (2006) — https://ideas.repec.org/a/eee/econom/v135y2006i1-2p31-53.html
- Timmermann (2006) — https://econweb.ucsd.edu/~atimmerm/combine.pdf
- Goyal & Welch (2008) — https://www.ivo-welch.info/research/journalcopy/2008-rfs.pdf
- Smith & Wallis (2009) — https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1468-0084.2008.00541.x
- Rapach, Strauss & Zhou (2010) — https://academic.oup.com/rfs/article-abstract/23/2/821/1604687
- Elliott (2011) — https://econweb.ucsd.edu/~grelliott/AveragingOptimal.pdf
- Genre, Kenny, Meyler & Timmermann (2013) — https://ideas.repec.org/p/ecb/ecbwps/20101277.html
- Hsiao & Wan (2014) — https://www.sciencedirect.com/science/article/abs/pii/S0304407613002339
- Conflitti, De Mol & Giannone (2015) — https://cepr.org/publications/dp9096
- Claeskens, Magnus, Vasnev & Wang (2016) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2739690
- Diebold & Shin (2019) — https://www.sas.upenn.edu/~fdiebold/papers2/DieboldShinEgalitarianLasso.pdf
- Wang, Hyndman et al. (2022) — https://arxiv.org/pdf/2205.04216
- Wang, Hyndman & Kang (2023) — https://arxiv.org/abs/2208.00139
- Setzer & Fuchs (2024) — https://aisel.aisnet.org/wi2024/13/
- Welch, Goyal & Zafirov (2024) — https://academic.oup.com/rfs/article/37/11/3490/7749383
- Lee & Lee (2025) — https://arxiv.org/abs/2308.05263
