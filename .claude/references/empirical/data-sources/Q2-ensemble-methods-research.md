# Q2 — Ensemble methods for combining regime classifiers

**Question being answered:** Given 6 regime classifiers with different empirical validation depths (HIGH/MEDIUM/LOW), what is the academically-validated method for combining them into a single regime classification with confidence-weighted dimension-level signals?

**Bottom line, up front:**
1. **For v0.1 (zero resolved predictions): equal-weight average across the 6 dimensions, with a documented "diagnostic split" of HIGH-validation dimensions reported alongside.** This is academically the most defensible choice when no in-sample weight calibration data exists. The HIGH/MEDIUM/LOW tags (1.0 / 0.7 / 0.5) are a *reasonable heuristic* — not academically validated as numbers — and should be treated as an editorial annotation rather than a precision weight.
2. **For v0.5+ (50+ resolved predictions): Bayesian shrinkage of OLS-estimated weights toward equal weights, à la Diebold-Pauly (1990).** The shrinkage intensity is itself estimated from the data and starts near full-shrinkage (equal weights) and relaxes only as the resolved-prediction sample grows.
3. **The "forecast combination puzzle" (Smith-Wallis 2009; Claeskens et al. 2016) is empirically robust:** at small samples, equal-weighting beats optimized weights *as a deterministic mathematical result*, not a curiosity. Estimation error in the weights is mechanically larger than the bias-improvement from estimating them, until N is large.
4. **Validation-depth-tagged weighting is a heuristic, not a theorem.** No paper I found endorses tagging classifiers as HIGH/MEDIUM/LOW and applying point weights of 1.0/0.7/0.5. The principled academic alternative is to set BMA *priors over models* that reflect prior belief — but those are still subjective and converge to the data with sample size.

---

## Section A — Curated sources (24 entries; tier-labeled)

**Tier definitions:**
- **A** — primary, peer-reviewed, foundational; replicated >100 times
- **B** — peer-reviewed, well-cited, but younger or narrower scope
- **C** — survey / handbook / working paper that synthesizes A-tier work
- **D** — practitioner / industry / blog (used only for grounding intuitions)

### Foundational forecast combination

1. **[A] Bates & Granger (1969).** "The Combination of Forecasts." *J. Operational Research Society* 20(4): 451–468. Foundational paper. Optimal variance-weighted combination minimizes MSE; equal weights are a special case when forecasts have equal error variance and equal correlations. Their key result: a composite forecast can have lower MSE than either constituent. Methodology built on portfolio diversification logic. URL: https://link.springer.com/article/10.1057/jors.1969.103

2. **[A] Granger & Ramanathan (1984).** "Improved Methods of Combining Forecasts." *J. Forecasting* 3: 197–204. Generalizes Bates-Granger to OLS regression. Three variants: (i) constrained to sum-to-1 with no intercept, (ii) constrained to sum-to-1 with intercept, (iii) unconstrained with intercept (their preferred). The unconstrained-with-intercept produces unbiased combined forecasts even when constituents are biased. URL: https://onlinelibrary.wiley.com/doi/abs/10.1002/for.3980030207

3. **[A] Diebold & Mariano (1995).** "Comparing Predictive Accuracy." *J. Business & Economic Statistics* 13(3): 253–263. The DM test. Asymptotic z-test for the null that two forecasts have equal expected loss. Loss can be non-quadratic, errors can be non-Gaussian/serially-correlated/contemporaneously-correlated. Cited as the way to test whether one classifier dominates another *before* combining. URL: https://www.sas.upenn.edu/~fdiebold/papers/paper68/pa.dm.pdf

4. **[A] Diebold & Mariano (2015).** "Comparing Predictive Accuracy, Twenty Years Later." *J. Business & Economic Statistics* 33(1). Reviews two decades of use/abuse of DM. Key clarification: DM is a *forecast* comparison test (treats forecasts as primitives), not a *model* comparison test. Relevant for our 6-classifier setup because each classifier is a forecast-producing function, and DM is the right tool. URL: https://www.tandfonline.com/doi/abs/10.1080/07350015.2014.983236

5. **[A] Diebold & Pauly (1990).** "The Use of Prior Information in Forecast Combination." *Int'l J. Forecasting* 6: 503–508. **THE most directly relevant paper for our use case.** Bayesian shrinkage of OLS-estimated combination weights toward equal weights. Posterior mean is a convex combination of OLS weights and arithmetic average; shrinkage intensity controlled by prior precision, *which is estimated from the data*. In their U.S. GNP example, "a large amount of shrinkage was found to be optimal." This is the canonical academic recipe for "start near equal weights and relax toward optimized weights as evidence accumulates." URL: https://www.sas.upenn.edu/~fdiebold/papers/paper94/DieboldPauly1990.pdf

### The forecast combination puzzle

6. **[A] Smith & Wallis (2009).** "A Simple Explanation of the Forecast Combination Puzzle." *Oxford Bulletin of Economics and Statistics* 71(3): 331–355. Formal explanation: estimation error in the *weights* is the dominant source of MSE inflation at small samples, and that inflation can exceed any bias-reduction from using non-equal weights. Built on simulations and an empirical example. URL: https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1468-0084.2008.00541.x

7. **[A] Claeskens, Magnus, Vasnev, Wang (2016).** "The Forecast Combination Puzzle: A Simple Theoretical Explanation." *Int'l J. Forecasting* 32(3): 754–762. Closed-form theoretical complement to Smith-Wallis. Shows that *random* (vs. fixed) weights induce both a bias term and a variance inflation term. Equally-weighted combinations can produce smaller MSE than optimal-weight estimates *as a theorem*, not an empirical curiosity. URL: https://www.sciencedirect.com/science/article/abs/pii/S0169207016000327

8. **[A] Stock & Watson (2004).** "Combination Forecasts of Output Growth in a Seven-Country Data Set." *J. Forecasting* 23(6): 405–430. Empirical evaluation across 7 OECD countries with up to 73 predictors per country. Most successful combination forecasts are the simple ones (mean, median, trimmed mean) — *the least sensitive to the recent performance of individual forecasts*. Strong empirical support for equal-weight robustness. URL: https://www.princeton.edu/~mwatson/papers/Stock_Watson_JoForc_2004.pdf

9. **[A] Genre, Kenny, Meyler, Timmermann (2013).** "Combining expert forecasts: Can anything beat the simple average?" *Int'l J. Forecasting* 29(1): 108–121. Tests PCA, trimmed-means, performance-weighted, OLS-optimal, Bayesian shrinkage on the ECB SPF. Finding: simple average is hard to beat, though Bayesian shrinkage methods sometimes outperform marginally. Particularly relevant because SPF panelists are heterogeneous experts (analogous to our heterogeneous classifiers). URL: https://rady.ucsd.edu/_files/faculty-research/timmermann/SPF_IJoF_2012_06_22.pdf

### Bayesian Model Averaging

10. **[A] Hoeting, Madigan, Raftery, Volinsky (1999).** "Bayesian Model Averaging: A Tutorial." *Statistical Science* 14(4): 382–417. Canonical BMA tutorial. BMA posterior weights are P(M_k | data) ∝ P(data | M_k) × P(M_k). The prior P(M_k) is where validation-depth-style information would enter — but as subjective prior probabilities, not as deterministic 1.0/0.7/0.5 weights. Default uniform prior is the de-facto choice unless strong domain evidence justifies otherwise. URL: https://www.stat.colostate.edu/~jah/papers/statsci.pdf

11. **[A] Wright (2009).** "Forecasting US Inflation by Bayesian Model Averaging." *J. Forecasting* 28(2): 131–144 (NBER WP version 2003). BMA across many candidate predictors for inflation. Key empirical finding: BMA forecasts more accurate than equal-weighted averages *and* than any single-model selection method. **Caveat:** Wright uses 90+ predictors and decades of monthly data; BMA shines when N is large relative to model count. URL: https://onlinelibrary.wiley.com/doi/abs/10.1002/for.1088

12. **[A] Geweke & Amisano (2011).** "Optimal Prediction Pools." *J. Econometrics* 164(1): 130–141. Linear pools of predictive densities, weights chosen to maximize log predictive score. **Crucial result for us:** unlike BMA, optimal linear pools do *not* concentrate on one model asymptotically — multiple models retain positive weight forever. Why? Because BMA assumes one of the candidate models is true (M-closed); pools acknowledge they are all wrong (M-open). The 6 regime classifiers are *certainly* an M-open set. URL: https://www.sciencedirect.com/science/article/abs/pii/S0304407611000455

13. **[A] Yao, Vehtari, Simpson, Gelman (2018).** "Using Stacking to Average Bayesian Predictive Distributions." *Bayesian Analysis* 13(3). Direct critique of BMA in the M-open setting. Recommends stacking of predictive distributions using leave-one-out (LOO) computed via Pareto-smoothed importance sampling. Compares stacking vs. BMA vs. pseudo-BMA vs. BB-pseudo-BMA — stacking wins when models are non-nested and misspecified (our case). URL: https://projecteuclid.org/journals/bayesian-analysis/volume-13/issue-3/Using-Stacking-to-Average-Bayesian-Predictive-Distributions-with-Discussion/10.1214/17-BA1091.full

### Surveys and handbook chapters

14. **[C] Timmermann (2006).** "Forecast Combinations." *Handbook of Economic Forecasting*, ch. 4. Field-defining survey. Three reasons simple averages dominate: (i) model misspecification, (ii) parameter instability/structural breaks, (iii) estimation error when model count is large relative to sample size. Discusses Bayesian shrinkage, time-varying weights, asymmetric loss. URL: https://econweb.ucsd.edu/~atimmerm/combine.pdf

15. **[C] Wang, Hyndman et al. (2022).** "Forecast Combinations: An Over 50-Year Review." arXiv:2205.04216. Comprehensive review of 50+ years of forecast combination methods, including ML-era stacking, neural ensemble, feature-based combination. Confirms that simple-average remains hard to beat outside large-sample / many-predictor regimes. URL: https://arxiv.org/pdf/2205.04216

16. **[C] Hendry & Clements (2002).** "Pooling of Forecasts." *Econometrics Journal* 5: 1–26. Theoretical case for combination under structural breaks. Combination dominates the best individual forecast when models are *differentially mis-specified* — exactly our setting (our 6 classifiers measure disjoint dimensions). Key caveat: under simultaneous breaks affecting all models, combination provides little improvement. URL: https://www.nuffield.ox.ac.uk/economics/papers/2002/w9/DFHMPCFrcncEctJ.pdf

### Trimming and robustness

17. **[B] Wang, Hyndman, Kang (2023).** "Another Look at Forecast Trimming for Combinations: Robustness, Accuracy and Diversity." arXiv:2208.00139. Modern formalization of "remove-the-worst-then-average." Trimmed mean and Winsorized mean dominate simple mean when individual forecasts have high variability. Practically: drop classifiers whose recent track record is decisively bad (DM-test rejected), then equal-weight the rest. URL: https://arxiv.org/abs/2208.00139

18. **[B] Diebold & Shin (2019).** "Machine Learning for Regularized Survey Forecast Combination: Partially-Egalitarian LASSO." *Int'l J. Forecasting* 35(4): 1679–1691. LASSO-style shrinkage of forecast weights toward equality, with sparsity penalty that drops uninformative forecasters entirely. Operational middle-ground between simple-average and BMA. URL: https://www.sas.upenn.edu/~fdiebold/papers2/DieboldShinEgalitarianLasso.pdf

### Regime-classifier-specific ensemble methods

19. **[B] Krolzig (1997).** *Markov-Switching Vector Autoregressions.* Springer. Foundational for multi-regime VAR. Single MS-VAR — not directly an ensemble — but informs how regime-state inferences combine across multiple specifications via posterior weighting. URL: https://link.springer.com/book/10.1007/978-3-642-51684-9

20. **[B] "A forest of opinions: A multi-model ensemble-HMM voting framework" (2024, AIMS Press).** Recent ensemble-HMM voting framework. Bagging + boosting + HMM for regime detection. Demonstrates that ensemble voting across HMM specifications outperforms any single HMM in OOS regime detection. Practical confirmation that the *idea* of combining regime classifiers is empirically supported. URL: https://www.aimspress.com/article/id/69045d2fba35de34708adb5d

21. **[B] Wolpert (1992).** "Stacked Generalization." *Neural Networks* 5: 241–259. Foundational paper on stacking. Train base learners; train a meta-learner whose inputs are base-learner predictions and target is the truth. Modern ML stacking is the descendant of this. Requires *much* more resolved-prediction data than we'll have at v0.5. URL: https://machine-learning.martinsewell.com/ensembles/stacking/Wolpert1992.pdf

### Validation depth and signal-decay literature

22. **[A] Goyal, Welch, Zafirov (2024).** "A Comprehensive 2022 Look at the Empirical Performance of Equity Premium Prediction." *Review of Financial Studies* 37(11): 3490–3557. Extends Goyal-Welch (2008). Of 29 newer post-2008 predictors plus the original 17, **more than one-third are no longer significant in-sample**, and of those that are, **half have poor OOS performance.** Strong empirical case for skepticism toward weight-stability of low-validation-depth signals — informs why our LOW-validation classifier (stock-bond correlation, post-2020 regime change) deserves a wider prior shrinkage. URL: https://academic.oup.com/rfs/article/37/11/3490/7749383

23. **[B] McLean & Pontiff (2016) (cited indirectly via signal-decay literature).** Published anomalies decay ~50% post-publication, with the published year explaining ~30% of cross-sectional Sharpe decay. Reinforces skepticism that any single signal/classifier should be granted permanent weight. (Surfaced via "When do systematic strategies decay?" Quantitative Finance 2022.) URL: https://www.tandfonline.com/doi/full/10.1080/14697688.2022.2098810

24. **[B] Capistrán & Timmermann (2009).** "Forecast Combination With Entry and Exit of Experts." Walk-forward / rolling combination weights when the panel of available forecasters changes over time. Closely matches our reality (we may add/retire dimensions). URL: https://rady.ucsd.edu/_files/faculty-research/timmermann/Capistran_Timmermann_June29_2007.pdf

---

## Section B — Method comparison table

| # | Method | What it does | Sample-size requirement | Implementability (Python) | Empirical edge over equal-weight | Primary citation |
|---|--------|--------------|-------------------------|--------------------------|----------------------------------|------------------|
| 1 | **Equal-weight (simple mean)** | w_i = 1/N for all classifiers | None | Trivial (`np.mean`) | Baseline by definition; Stock-Watson (2004) and Genre et al. (2013) confirm hard to beat | Bates-Granger 1969 (special case) |
| 2 | **Variance-weighted (Bates-Granger)** | w_i ∝ 1/σ²_i, optionally with cov adjustment | Need σ²_i estimates: ~30+ resolved predictions per dimension before stable | Easy (`numpy`) | Negative on average at small samples; positive only at very large samples (Smith-Wallis 2009) | Bates & Granger 1969 |
| 3 | **OLS regression weights (Granger-Ramanathan)** | Run y = α + Σ w_i × f_i + ε | ~50–100+ resolved predictions before stable | Easy (`statsmodels`) | Negative at small samples per Claeskens et al. 2016; positive at large N | Granger & Ramanathan 1984 |
| 4 | **Trimmed mean / Winsorized mean** | Drop top/bottom k% of classifier outputs, then average | Modest — only need to know which to drop | Trivial (`scipy.stats.trim_mean`) | Often beats simple mean when outliers present; minor improvement otherwise | Stock-Watson 2004; Wang et al. 2023 |
| 5 | **Performance-trimmed mean (drop the worst)** | DM-test each classifier, drop those decisively worse | ~30+ predictions to make DM significant | Moderate | Modestly positive in Genre et al. 2013 | Diebold-Mariano 1995; Wang et al. 2023 |
| 6 | **Bayesian shrinkage to equal weights (Diebold-Pauly)** | Posterior mean = convex combination of OLS-weights and 1/N; shrinkage estimated from data | Works *at all sample sizes* — degenerates to equal-weight at N=0, OLS at N=∞ | Moderate (`pymc` or analytic Beta-Bin posterior) | Genre et al. 2013 finds modest gain over simple average | **Diebold & Pauly 1990** |
| 7 | **Bayesian Model Averaging (BMA)** | w_k = P(M_k | data); requires likelihood for each model | Asymptotically concentrates on single model — large N needed for posterior to be informative | Moderate-hard (need likelihoods) | Wright 2009 finds gain on inflation forecasting *with decades of data*; less robust at small N | Hoeting-Madigan-Raftery-Volinsky 1999 |
| 8 | **Optimal prediction pools (linear pool / log score)** | Maximize Σ log p_t(y_t) where p = Σ w_k × p_k | Need predictive density per classifier; ~50+ predictions | Moderate | Better than BMA in M-open setting (which is our case); doesn't asymptotically degenerate | Geweke & Amisano 2011 |
| 9 | **Bayesian stacking (Yao et al.)** | Stacking weights from LOO predictive densities | ~50+ predictions; needs Bayesian posterior per classifier | Hard (`loo` in R; ArviZ in Python — not seamless) | Better than BMA when models misspecified (our case) | Yao, Vehtari, Simpson, Gelman 2018 |
| 10 | **Egalitarian LASSO (Diebold-Shin)** | OLS weights with L1 penalty toward equality + sparsity | ~50+ predictions | Moderate (`scikit-learn` LASSO with custom centering) | Modest gain in their SPF tests | Diebold & Shin 2019 |
| 11 | **Stacked generalization (Wolpert)** | Train meta-learner on base-classifier outputs | ~hundreds of predictions for stable meta-learner | Easy mechanically (`scikit-learn`); risky at small N | Strong at large N; unreliable at small N | Wolpert 1992 |
| 12 | **Validation-depth-weighted (HIGH=1.0/MED=0.7/LOW=0.5)** | Hand-set weights based on qualitative validation-depth tag | None | Trivial | **No academic empirical evidence; pure heuristic** | (None — operator-proposed) |

---

## Section C — Specific recommendation for our 6-classifier setup

### v0.1 recommendation (no resolved predictions yet)

**Method:** Equal-weight average across the 6 dimensions, with HIGH-validation-only diagnostic split reported in parallel.

**Concrete recipe:**
1. Each classifier produces a regime label and (where possible) a numeric score in [-1, +1] or a probability.
2. The composite regime call is the equal-weighted average of the 6 dimensions' scores (or majority-vote of categorical labels).
3. **In addition**, surface a "HIGH-validation diagnostic" — the equal-weighted average across only the four HIGH-validation dimensions (Credit, Economic-cycle, Vol, Dollar). This shows when MEDIUM/LOW dimensions are pulling the call.
4. **Do not apply 1.0/0.7/0.5 weights as if they were precision instruments.** Treat HIGH/MEDIUM/LOW as an editorial annotation that informs human judgment, not a deterministic weighting scheme.

**Reasoning:**
- Smith-Wallis 2009 and Claeskens et al. 2016 show that estimation-error-induced MSE inflation dominates any bias-reduction benefit at zero or small N. With *zero* resolved predictions, any non-equal weighting is choosing weights from prior belief alone — which is fine if disclosed, dangerous if not.
- Stock-Watson 2004, Genre et al. 2013, Timmermann 2006 all converge on: simple mean/median is the right default.
- The HIGH/MEDIUM/LOW tags are operator priors. As priors they're fine — but priors should anchor at neutrality (equal weight) and be updated by data, not encoded as deterministic point weights.
- Our 6 dimensions are *deliberately disjoint* (credit, cycle, vol, monetary, dollar, stock-bond corr). Hendry-Clements 2002 explicitly argues that combination dominates individual forecasts when models are *differentially mis-specified* (i.e., each measures something different). Equal weight maximally exploits this orthogonality.

**When/how to migrate to data-driven weights:**
- Track resolved predictions in a database with timestamp, dimension-level call, composite call, realized regime (with definitional cutoff), DM-test loss differential.
- After ~30 resolved predictions, run DM tests pairwise to identify any classifier that is *decisively* worse than the others. If found, drop it from the equal-weight pool (Wang et al. 2023 trimming).
- After ~50 resolved predictions, switch to Diebold-Pauly Bayesian shrinkage (see v0.5+ recommendation below).

### v0.5+ recommendation (50+ resolved predictions)

**Method:** Diebold-Pauly (1990) Bayesian shrinkage of OLS weights toward equal weights, with shrinkage intensity estimated from the data.

**Concrete recipe:**
1. Stack resolved-prediction dataset: rows are timestamps, columns are (dim_1_score, …, dim_6_score, realized_regime).
2. Fit Granger-Ramanathan unconstrained regression with intercept: y = α + Σ w_i × f_i + ε.
3. Apply Diebold-Pauly Bayesian shrinkage: posterior_w = (1 - λ) × OLS_w + λ × (1/6, …, 1/6), where λ is estimated from posterior precision. Closed-form when prior is conjugate normal.
4. Implement walk-forward: refit weights every 6 months using all available resolved predictions; do *not* use rolling window (Capistrán-Timmermann 2009 warns rolling discards information).
5. Continue to surface the HIGH-validation diagnostic split as a sanity check.

**Reasoning:**
- Diebold-Pauly is the canonical "start at equal, relax toward optimal as evidence accumulates" academic recipe. It elegantly handles the zero-prediction → infinite-prediction continuum without a discrete threshold.
- Bayesian shrinkage strictly dominates raw OLS at moderate N (Diebold-Pauly 1990; Genre et al. 2013).
- We choose Diebold-Pauly over BMA because BMA assumes one of the 6 dimensions is "the true model" (M-closed) — clearly false; we believe regime is multidimensional. Geweke-Amisano 2011 and Yao et al. 2018 both warn against BMA in the M-open setting.
- We choose Diebold-Pauly over optimal prediction pools (Geweke-Amisano) because pools require predictive *densities* per classifier, which 4 of our 6 dimensions don't naturally produce (e.g., NTFS gives a recession probability — that's a density — but EBP gives a level of credit stress which we'd need to re-cast as a density). Diebold-Pauly works directly on point forecasts.
- We choose Diebold-Pauly over Bayesian stacking (Yao et al.) because stacking requires Bayesian posteriors per base classifier and Pareto-smoothed importance sampling — operationally heavy for 6-classifier setup with no Bayesian base models.

**Implementation outline (Python):**
```python
# Conjugate normal-normal Bayesian shrinkage à la Diebold-Pauly
import numpy as np
from numpy.linalg import inv

# X: T × N matrix of classifier outputs; y: T-vector of realized regime labels (numeric)
# prior_mean = np.ones(N) / N   # equal-weight prior
# prior_precision_lambda = data-estimated  (Diebold-Pauly §3)

def bayesian_combination_weights(X, y, prior_mean, prior_precision):
    N = X.shape[1]
    XtX = X.T @ X
    Xty = X.T @ y
    # Posterior precision
    post_precision = XtX + prior_precision * np.eye(N)
    # Posterior mean
    post_mean = inv(post_precision) @ (Xty + prior_precision * prior_mean)
    return post_mean
```

The prior_precision parameter is what controls the shrinkage intensity. Diebold-Pauly recommend estimating it via empirical Bayes (maximize marginal likelihood). At small N, the data is uninformative and posterior_mean ≈ prior_mean (= equal weights). At large N, posterior_mean → OLS. Continuous, no discrete threshold.

### Honest answer to "are HIGH/MEDIUM/LOW weights academically validated?"

**No.** The 1.0 / 0.7 / 0.5 numbers are a reasonable heuristic but not academically grounded. Here's the honest decomposition:

- **What IS academically validated:** the *idea* that classifiers with longer/deeper validation should carry more weight. This is consistent with Bayesian model averaging (where prior model probability P(M_k) reflects prior confidence) and with signal-decay literature (Goyal-Welch-Zafirov 2024; McLean-Pontiff 2016).
- **What is NOT academically validated:** the specific point values 1.0/0.7/0.5. There is no paper that says "60-year validation classifier should be weighted 2x relative to a 5-year validation classifier."
- **What the academic literature would do instead:** set BMA priors over the 6 classifiers reflecting validation-depth confidence — but those priors should be (a) treated as Bayesian uncertainty parameters (they update with data), not as deterministic weights, and (b) not used at all when no resolved predictions exist (because then the prior is doing 100% of the work and the classifier isn't actually being tested).
- **The right way to honor the validation-depth intuition at v0.1:** don't bake it into weights at all. Run equal weight, but require that any composite regime call that *contradicts the HIGH-validation diagnostic split* trigger a flag for human review. This achieves the "give more weight to better-validated classifiers" intuition without committing to numbers we cannot defend.
- **The right way at v0.5+:** estimate weights from data via Diebold-Pauly shrinkage, with the prior set to equal weights (not 1.0/0.7/0.5). Let the resolved-prediction data tell you whether the LOW-validation stock-bond classifier deserves less weight — don't pre-judge with a 0.5 multiplier.

**One caveat:** if the operator strongly believes the LOW-validation classifier (stock-bond correlation post-2020) is genuinely unreliable and should be dampened, the academically defensible move is to set its BMA prior P(M_k) lower than the others — say, 1/12 vs 1/6 for the others, normalized — *and let the data update from there*. This is Bayesian rather than deterministic, which is what makes it defensible.

---

## Section D — Findings on the forecast-combination puzzle

### Equal-weight vs optimized-weight at small samples — documented edge of equal-weight

The "forecast combination puzzle" is the empirical regularity that simple equal-weight averages of forecasts repeatedly outperform sophisticated optimally-weighted combinations. Major documented evidence:

| Study | Setting | Finding |
|-------|---------|---------|
| Bates & Granger 1969 | Theoretical foundation | Variance-weighting is optimal *if* weights are known. |
| Stock & Watson 2004 | 7 OECD countries, 73 predictors, 1959–1999 quarterly | Simple mean / trimmed mean dominate complex weight schemes |
| Smith & Wallis 2009 | Theory + simulation | Estimation error in weights mechanically inflates MSE; this inflation can exceed any bias-reduction benefit |
| Genre et al. 2013 | ECB SPF, 1999–2010 | Simple average hard to beat; only Bayesian shrinkage methods come close |
| Claeskens et al. 2016 | Theory | Closed-form: random weights induce a bias term + variance inflation; equal-weight has neither |
| Wang & Hyndman 2022 | 50-year review | Confirms simple-average robustness across hundreds of empirical studies |

**The mechanical reason:** if true optimal weights are w*, and estimated weights are ŵ = w* + estimation_error, then MSE(ŵ) = MSE(w*) + 2·E[bias·error] + Var(error). The Var(error) term shrinks like 1/T but at small T it's large. Equal weights have zero estimation error (they're constants), so they avoid this term entirely. The cost is that they have a bias term (1/N is generally not w*) — but at small T, this bias is smaller than the variance of estimating w*.

### When optimized-weight starts to dominate

The threshold depends on the number of constituent forecasters (N) and their correlation structure. Rough rule from the literature:

- Smith & Wallis (2009) simulations: optimal weights start beating equal weights when **T > ~40–80** for N=2 forecasters with low correlation; threshold rises to **T > 100+** when N=4 or correlations are high.
- Stock & Watson (2004) empirics: even with T ≈ 160 quarterly observations, simple methods still won.
- Genre et al. (2013) on ECB SPF: with T ≈ 50 quarterly obs and N ≈ 10–20 panelists, simple average still dominated unconstrained-weight estimation; only Bayesian shrinkage methods came close.

**For our 6-classifier setup, the implication is:**
- With T < 30: equal weights almost certainly dominate.
- With T ≈ 30–80: Diebold-Pauly Bayesian shrinkage is the right move; raw OLS still likely worse than equal.
- With T > 100: OLS-style optimal weights *might* beat equal, but Bayesian shrinkage is likely still preferred.
- With T > 200+: more aggressive methods (egalitarian LASSO, stacking, optimal prediction pools) become viable.

### Implications for our 18-24 month calibration period

Per the operator constraint of ~50+ resolved predictions taking 18–24 months:

- **Months 0–12 (T = 0 to ~25):** Hard equal-weight regime. No data-driven weights. This is the v0.1 phase.
- **Months 12–18 (T ≈ 25–40):** *Maybe* introduce Bayesian shrinkage with strong shrinkage intensity (close to equal-weight). Run DM tests pairwise to identify any decisively-bad classifier and consider dropping. Still essentially equal-weight in practice.
- **Months 18–24 (T ≈ 40–60):** Migrate to Diebold-Pauly Bayesian shrinkage with empirical-Bayes-estimated shrinkage intensity. Posterior weights will start to diverge meaningfully from 1/6.
- **Months 24+ (T > 60):** Continue Diebold-Pauly with periodic refit. Reconsider stacking or optimal pools if predictive-density data is available.

**A critical sanity check:** the calibration period assumes the regime structure is stable. If a structural break occurs (e.g., new monetary regime, new dollar reserve dynamics), Hendry-Clements 2002 reminds us that simultaneous shifts may render historical weights *worse* than equal weights even at high T. Consider running an "equal-weight benchmark" continuously alongside Bayesian-shrinkage weights as a robustness check, and be willing to revert to equal-weight if shrinkage weights show sustained underperformance after a regime break.

### The single most important takeaway

**The academic literature offers no free lunch on weighting at small N.** The honest engineering choice for v0.1 is equal weights with the HIGH-validation diagnostic surfaced as an editorial annotation. The honest engineering choice for v0.5+ is Diebold-Pauly Bayesian shrinkage. Anything else — including the 1.0/0.7/0.5 heuristic — is operator preference dressed up as method. Document it as such if used.

---

## Appendix — Methods *not* recommended and why

| Method | Why not for our setup |
|--------|----------------------|
| Pure OLS optimal weights (Granger-Ramanathan 1984) | Smith-Wallis / Claeskens results show negative MSE impact at small N |
| Variance-weighted only (Bates-Granger 1969) | Requires σ²_i estimates that are themselves noisy at small N |
| BMA with uniform prior | Asymptotically concentrates on one model — wrong for our M-open setting |
| BMA with informative prior (validation-depth tagged) | The numbers (1.0/0.7/0.5) are not academically defensible as point values; better to estimate from data |
| Stacking / meta-learner (Wolpert 1992) | Needs hundreds of resolved predictions; prone to overfitting at our scale |
| Neural ensemble | Same as stacking but worse — needs even more data |
| Time-varying weights (Capistrán-Timmermann 2009) | Adds parameters we cannot estimate at v0.1; revisit at v1.0 |
| Pure validation-depth-weighted (HIGH=1.0/MED=0.7/LOW=0.5) | Numbers are not academically validated; converts a Bayesian uncertainty into a deterministic weight, which is the wrong epistemic move |

---

## Sources cited (chronological)

1. Bates & Granger 1969 — https://link.springer.com/article/10.1057/jors.1969.103
2. Granger & Ramanathan 1984 — https://onlinelibrary.wiley.com/doi/abs/10.1002/for.3980030207
3. Diebold & Pauly 1990 — https://www.sas.upenn.edu/~fdiebold/papers/paper94/DieboldPauly1990.pdf
4. Wolpert 1992 — https://machine-learning.martinsewell.com/ensembles/stacking/Wolpert1992.pdf
5. Diebold & Mariano 1995 — https://www.sas.upenn.edu/~fdiebold/papers/paper68/pa.dm.pdf
6. Krolzig 1997 — https://link.springer.com/book/10.1007/978-3-642-51684-9
7. Hoeting, Madigan, Raftery, Volinsky 1999 — https://www.stat.colostate.edu/~jah/papers/statsci.pdf
8. Hendry & Clements 2002 — https://www.nuffield.ox.ac.uk/economics/papers/2002/w9/DFHMPCFrcncEctJ.pdf
9. Stock & Watson 2004 — https://www.princeton.edu/~mwatson/papers/Stock_Watson_JoForc_2004.pdf
10. Timmermann 2006 — https://econweb.ucsd.edu/~atimmerm/combine.pdf
11. Wright 2009 — https://onlinelibrary.wiley.com/doi/abs/10.1002/for.1088
12. Smith & Wallis 2009 — https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1468-0084.2008.00541.x
13. Capistrán & Timmermann 2009 — https://rady.ucsd.edu/_files/faculty-research/timmermann/Capistran_Timmermann_June29_2007.pdf
14. Geweke & Amisano 2011 — https://www.sciencedirect.com/science/article/abs/pii/S0304407611000455
15. Genre, Kenny, Meyler, Timmermann 2013 — https://rady.ucsd.edu/_files/faculty-research/timmermann/SPF_IJoF_2012_06_22.pdf
16. Diebold & Mariano 2015 — https://www.tandfonline.com/doi/abs/10.1080/07350015.2014.983236
17. Claeskens, Magnus, Vasnev, Wang 2016 — https://www.sciencedirect.com/science/article/abs/pii/S0169207016000327
18. Yao, Vehtari, Simpson, Gelman 2018 — https://projecteuclid.org/journals/bayesian-analysis/volume-13/issue-3/Using-Stacking-to-Average-Bayesian-Predictive-Distributions-with-Discussion/10.1214/17-BA1091.full
19. Diebold & Shin 2019 — https://www.sas.upenn.edu/~fdiebold/papers2/DieboldShinEgalitarianLasso.pdf
20. Wang & Hyndman 2022 — https://arxiv.org/pdf/2205.04216
21. Wang, Hyndman, Kang 2023 — https://arxiv.org/abs/2208.00139
22. Goyal, Welch, Zafirov 2024 — https://academic.oup.com/rfs/article/37/11/3490/7749383
23. "Forest of opinions" 2024 — https://www.aimspress.com/article/id/69045d2fba35de34708adb5d
24. McLean-Pontiff via "When do systematic strategies decay?" 2022 — https://www.tandfonline.com/doi/full/10.1080/14697688.2022.2098810
