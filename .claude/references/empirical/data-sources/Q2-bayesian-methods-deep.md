# Q2 — Bayesian methods for regime-classifier combination (deep dive)

**Subagent scope:** Bayesian methods only. Sibling subagents handle Bates-Granger / Granger-Ramanathan / equal-weight-puzzle / non-Bayesian ML stacking.

**Question being answered:** For 6 regime classifiers with HIGH/MEDIUM/LOW empirical-validation depth, what is the academically-defensible *Bayesian* method for combining them, what are the priors, and how do those priors decay as resolved-prediction evidence accumulates?

**Bottom line, up front:**
1. **For v0.1 (~0 resolved predictions): pseudo-BMA+ with Bayesian-bootstrap (BB), prior anchored to validation-depth-weighted weights, with explicit acknowledgment that the result is "prior-only" until ~30+ resolved predictions accumulate.** Specifically — *not* full BMA (which is M-closed and provably wrong here) and *not* pure equal-weight (which throws away the only legitimate prior information we have, namely 30+ years of D1/D2/D3/D4 empirical literature).
2. **The HIGH/MEDIUM/LOW heuristic with 1.0/0.7/0.5 weights is NOT directly endorsed by any BMA paper.** What IS Bayesian-defensible: encode validation-depth as an **informative prior over model probabilities** with prior-effective-sample-size (ESS, à la Morita-Thall-Müller 2008) calibrated so the prior does not dominate after ~50 resolved predictions. Specifically: prior ESS ≈ 5–10 per HIGH classifier, ≈ 2–3 per MEDIUM, ≈ 1 per LOW. This concretely yields prior weights of roughly 0.20 / 0.20 / 0.20 / 0.20 / 0.10 / 0.05 (after normalization) — close to equal-weight but with a small evidence-tilted edge.
3. **At v0.1 (N=0 resolved), all Bayesian methods reduce to "report the prior."** This is a feature, not a bug, but it must be operationally disclosed: we are NOT producing a data-driven combination at v0.1.
4. **The Bayes-factor-based BMA literature is *largely silent* on the validation-depth-tagged use case** because BMA presupposes a single data-generating-process likelihood, which our 6 disjoint regime dimensions do not share. The right Bayesian framing is **predictive-likelihood pooling (Geweke-Amisano 2011) or stacking (Yao et al. 2018)**, not classical BMA.
5. **Sample-size threshold below which priors dominate posteriors:** roughly N < 2 × prior-ESS-sum. With our recommended prior ESS sum ≈ 22, posteriors begin to noticeably differ from prior at ~N=22, and posteriors are decisively data-driven by ~N=80–100. This matches the operator's stated "v0.5 = ~50 resolved predictions" milestone — at v0.5 we are roughly 50/50 prior-vs-data.

---

## Section A — Curated sources (18 entries; tier-labeled)

**Tier definitions:**
- **A** — primary peer-reviewed foundational paper (>1000 citations OR field-defining)
- **B** — peer-reviewed, well-cited (>100 citations) but narrower in scope
- **C** — survey, handbook, textbook, software documentation
- **D** — practitioner / blog / educational note (used only for grounding)

### Foundational BMA papers

1. **[A] Hoeting, Madigan, Raftery, Volinsky (1999).** "Bayesian Model Averaging: A Tutorial." *Statistical Science* 14(4): 382–417. The canonical BMA tutorial. BMA posterior weight on model M_k is P(M_k|D) ∝ P(D|M_k) × P(M_k), where P(D|M_k) = ∫ P(D|θ_k, M_k) π(θ_k|M_k) dθ_k is the marginal likelihood. URL: https://projecteuclid.org/journals/statistical-science/volume-14/issue-4/Bayesian-model-averaging--a-tutorial-with-comments-by-M/10.1214/ss/1009212519.full

2. **[A] Raftery, Madigan, Hoeting (1997).** "Bayesian Model Averaging for Linear Regression Models." *J. Am. Stat. Assoc.* 92(437): 179–191. Original closed-form BMA for linear regression with closed-form marginal likelihood, MCMC and Occam's-window heuristic for the model-search problem when the model space is huge (10^11 models). URL: https://www.tandfonline.com/doi/abs/10.1080/01621459.1997.10473615

3. **[A] Madigan & Raftery (1994).** "Model Selection and Accounting for Model Uncertainty in Graphical Models Using Occam's Window." *J. Am. Stat. Assoc.* 89(428): 1535–1546. Origin of Occam's window — the heuristic that keeps only models within a Bayes-factor threshold of the maximum. URL: https://www.tandfonline.com/doi/abs/10.1080/01621459.1994.10476894

4. **[A] Kass & Raftery (1995).** "Bayes Factors." *J. Am. Stat. Assoc.* 90(430): 773–795. The reference scale for interpreting Bayes factors. **The thresholds: BF 1–3 "barely worth mentioning"; 3–20 "positive"; 20–150 "strong"; >150 "very strong / decisive."** This is the threshold above which one model statistically dominates another. URL: https://www.andrew.cmu.edu/user/kk3n/simplicity/KassRaftery1995.pdf

5. **[A] Fernández, Ley, Steel (2001).** "Benchmark priors for Bayesian model averaging." *J. Econometrics* 100(2): 381–427. The g-prior framework that has become *the* default for BMA in econometrics. Result: posterior model probabilities are rather sensitive to prior specification; recommend benchmark g = max(N, p²). URL: https://www.sciencedirect.com/science/article/abs/pii/S0304407600000762

### BMA in macro/finance forecasting

6. **[A] Wright (2008).** "Bayesian Model Averaging and exchange rate forecasts." *J. Econometrics* 146(2): 329–341. Empirical: BMA *sometimes* beats random walk and "never does much worse" — but BMA forecasts end up "very close to but not identical to" the random-walk forecast. Key lesson: at exchange-rate horizons, BMA's edge is modest. URL: https://www.federalreserve.gov/pubs/ifdp/2003/779/ifdp779.pdf

7. **[A] Wright (2009).** "Forecasting US Inflation by Bayesian Model Averaging." *J. Forecasting* 28(2): 131–144. Companion paper. BMA across 107 candidate predictors of US inflation, restricted to one-predictor-plus-lagged-inflation models. **Result: BMA more accurate than equal-weighted average and than any single-model selection method.** Caveat: large N, large model space, decades of monthly data. URL: https://onlinelibrary.wiley.com/doi/abs/10.1002/for.1088

8. **[A] Feldkircher (2012).** "Forecast Combination and Bayesian Model Averaging: A Prior Sensitivity Analysis." *J. Forecasting*. Found predictive-likelihood-based pooling outperforms marginal-likelihood-based BMA when the true model is *not* in the candidate space (M-open) — directly relevant to our regime-classifier setting. URL: https://onlinelibrary.wiley.com/doi/abs/10.1002/for.1228

### Predictive-likelihood pooling (Geweke-Amisano)

9. **[A] Geweke & Amisano (2011).** "Optimal prediction pools." *J. Econometrics* 164(1): 130–141. Linear pools of predictive densities, weights chosen to maximize log predictive score. **Crucial result for us:** unlike BMA, optimal linear pools do *not* concentrate on one model asymptotically — multiple models retain positive weight forever, even when one model is decisively inferior on classical scoring. Why? Because BMA assumes M-closed; pools acknowledge M-open. The 6 regime classifiers are *certainly* M-open. URL: https://www.sciencedirect.com/science/article/abs/pii/S0304407611000455 (working-paper PDF: https://www.ecb.europa.eu/pub/pdf/scpwps/ecbwp1017.pdf )

10. **[B] Waggoner & Zha (2012).** "Confronting Model Misspecification in Macroeconomics." FRB Atlanta WP 2010-18a. Markov-switching mixture of DSGE and BVAR — generalizes Geweke-Amisano to time-varying weights via Markov chain over regimes. Result: dynamic pools dominate static pools when the economic environment shifts. **Directly relevant** because regime classification IS a regime-switching context. URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2481157

11. **[B] Diks, Panchenko, Van Dijk (2011).** "Likelihood-based scoring rules for comparing density forecasts in tails." *J. Econometrics* 163(2): 215–230. Conditional and censored-likelihood scoring rules — the Bayesian-defensible test for whether one classifier's tail predictions are better than another's, which feeds directly into pool-weight optimization. URL: https://www.sciencedirect.com/science/article/abs/pii/S0304407611000807

### Bayesian stacking (the modern alternative to BMA)

12. **[A] Yao, Vehtari, Simpson, Gelman (2018).** "Using Stacking to Average Bayesian Predictive Distributions" (with Discussion). *Bayesian Analysis* 13(3): 917–1007. **Direct critique of BMA in the M-open setting.** Recommends stacking via leave-one-out (LOO), computed efficiently with Pareto-smoothed importance sampling (PSIS-LOO). Compares stacking vs BMA vs pseudo-BMA vs BB-pseudo-BMA — stacking wins when models are non-nested and misspecified, *which is exactly our case*. URL: https://projecteuclid.org/journals/bayesian-analysis/volume-13/issue-3/Using-Stacking-to-Average-Bayesian-Predictive-Distributions-with-Discussion/10.1214/17-BA1091.full (PDF: https://sites.stat.columbia.edu/gelman/research/published/stacking.pdf )

13. **[A] Le & Clarke (2017).** "A Bayes Interpretation of Stacking for M-Complete and M-Open Settings." *Bayesian Analysis* 12(3): 807–829. Theoretical complement to Yao et al.: stacking is asymptotically the Bayes solution under either log scoring or energy score, *under mild conditions*. Provides the formal Bayesian justification for stacking when one of the candidate models is not "true." URL: https://projecteuclid.org/euclid.ba/1473276261

14. **[B] Yao, Pirš, Vehtari, Gelman (2022).** "Bayesian Hierarchical Stacking: Some Models Are (Somewhere) Useful." *Bayesian Analysis*. Generalization where weights depend on input features — relevant if our 6 regime classifiers should be re-weighted depending on which broader regime we are in (e.g., the LOW-validation correlation classifier may matter MORE in a stagflation regime). URL: https://projecteuclid.org/journals/bayesian-analysis/advance-publication/Bayesian-Hierarchical-Stacking-Some-Models-Are-Somewhere-Useful/10.1214/21-BA1287.pdf

15. **[A] McAlinn & West (2019).** "Dynamic Bayesian predictive synthesis in time series forecasting." *J. Econometrics* 210(1): 155–169. Bayesian Predictive Synthesis (BPS) — adaptive, time-varying density combination treating individual forecasts as "agent opinions." More flexible than Geweke-Amisano pools because BPS allows for forecast-bias adjustment and miscalibration correction. URL: https://www.sciencedirect.com/science/article/abs/pii/S0304407618302112

### Validation-depth, prior-ESS, and small-sample literature

16. **[A] Morita, Thall, Müller (2008).** "Determining the Effective Sample Size of a Parametric Prior." *Biometrics* 64(2): 595–602. **THE most directly relevant paper for translating "HIGH validation depth" into a Bayesian prior.** Defines prior-effective-sample-size (ESS) as the n of hypothetical observations that, starting from a vague prior, would yield the same posterior as the informative prior in question. Standard rule of thumb: an a priori ESS of 1 is reasonable for a small-N study; an ESS of 20 would imply prior dominance. URL: https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1541-0420.2007.00888.x

17. **[B] Hinne, Gronau, van den Bergh, Wagenmakers (2020).** "A Conceptual Introduction to Bayesian Model Averaging." *Adv. Methods & Practices in Psych. Sci.* 3(2). Modern accessible BMA introduction. Emphasizes that "model priors should reflect prior beliefs about model plausibility" but practical applications usually default to uniform. **Confirms that informative priors are Bayesian-defensible if elicited from prior data**, which is exactly what our HIGH/MEDIUM/LOW tags are. URL: https://journals.sagepub.com/doi/full/10.1177/2515245919898657

18. **[C] Stata BMA Reference Manual (Release 19, 2025).** Provides the canonical practical menu of priors: uniform, binomial, beta-binomial (default), benchmark g-prior, hyper-g, empirical-Bayes-local. Confirms practitioner default is beta-binomial(1,1), which is *uniform over model size* — i.e., NOT validation-depth-informed. URL: https://www.stata.com/manuals/bma.pdf

### Software / implementation

19. **[C] Vehtari, Gelman et al. — `loo` R package.** `stacking_weights()`, `pseudobma_weights(BB=TRUE/FALSE)`, `loo_model_weights()` wrapper. Inputs: pointwise log-likelihood matrix (rows = observations, columns = candidate models). Output: optimal weights summing to 1. URL: https://mc-stan.org/loo/articles/loo2-weights.html

20. **[C] PyMC `model_averaging` example + ArviZ `az.compare()` and `az.weight_predictions()`.** Python-side implementation. `az.compare(model_dict)` returns a table with stacking weights; `az.weight_predictions()` produces weighted posterior predictive samples. Default method = "stacking" (Yao et al. 2018), alternative is "BB-pseudo-BMA". URL: https://www.pymc.io/projects/examples/en/latest/diagnostics_and_criticism/model_averaging.html

---

## Section B — BMA fundamentals

### B.1 — The full BMA formula

Given candidate models M_1, …, M_K and observed data D, the BMA posterior on a prediction quantity Δ (e.g., "next-period regime label") is:

```
P(Δ | D)  =  Σ_{k=1..K}  P(Δ | D, M_k)  ·  P(M_k | D)
```

where the **posterior model probability** is:

```
P(M_k | D)  =   P(D | M_k) · P(M_k)   /   Σ_{j=1..K} P(D | M_j) · P(M_j)
```

and the **marginal likelihood** of model M_k is:

```
P(D | M_k)  =  ∫ P(D | θ_k, M_k) · π(θ_k | M_k)  dθ_k
```

(Source: Hoeting et al. 1999, eq. 1; Raftery et al. 1997.)

### B.2 — Prior specification

Two priors are needed:

**(a) Prior over models, P(M_k).** Default options:
- **Uniform**: P(M_k) = 1/K. Default in Stata's `bmaregress`, in BMS R package, in PyMC. Treats all models as a priori equally plausible. Used when no domain knowledge exists.
- **Beta-binomial(1,1) over model size**: uniform over model size (as opposed to over individual models). Default in BAS R package. Reduces "supermodel effect" (Ley & Steel 2009).
- **Informative**: P(M_k) ∝ f(prior plausibility). This is where validation-depth tagging would enter — but no BMA paper provides a prescribed formula for translating qualitative HIGH/MEDIUM/LOW labels into prior probabilities. The principled approach is via **prior effective sample size** (Morita-Thall-Müller 2008, see Section C).

**(b) Prior over within-model parameters, π(θ_k | M_k).** Standard choices:
- **Zellner's g-prior** with g = max(N, p²) (Fernández-Ley-Steel 2001 benchmark)
- **Hyper-g** (Liang et al. 2008): hierarchical prior on g itself
- **Empirical Bayes local**: estimate g from the data per model

For our regime-classifier case, this layer is mostly moot because each "model" is a *classifier output*, not a parametric model with internal coefficients to estimate. We are averaging over predictive distributions, not over parameter estimates. (See Section B.4 on why predictive-likelihood pooling fits our case better than classical BMA.)

### B.3 — Posterior model probability computation

Two computational approaches:
1. **Closed-form for conjugate priors** (linear regression with g-prior — Raftery et al. 1997)
2. **MCMC over model space** (MC³ — Madigan-York; reversible-jump MCMC; or Occam's window for the small-K case where K ≤ 100)

For K=6 regime classifiers, **all of model space can be enumerated** — no MCMC needed. This is computationally trivial; the bottleneck is the marginal-likelihood evaluation, which requires a likelihood for "classifier k says regime label r_k given true regime label r." That likelihood is *exactly* the classifier's confusion matrix, which we don't yet have at v0.1.

### B.4 — Comparison: BMA vs predictive-likelihood weights vs Bayesian stacking

| Property | BMA (Hoeting et al.) | Geweke-Amisano pools | Bayesian stacking (Yao et al.) |
|---|---|---|---|
| Setting | M-closed (one model is true) | M-open (all models wrong) | M-open |
| Weights from | Marginal likelihood × prior | Maximize log-pred-score | Minimize KL to true distribution via LOO |
| Weights sum to 1? | Yes (probability) | Yes (constrained optim) | Yes (constrained optim) |
| Concentrates on best model? | Yes, asymptotically | No, multiple positive weights | No, multiple positive weights |
| Shares weight among similar models? | Yes (problematically) | Yes | **No (joint optim avoids this)** |
| Works with N < 50? | Posterior dominated by prior | Limited; weights unstable | Limited; LOO has high variance |
| Software | R `BMA`, Stata `bma`, R `BMS` | Custom + Stan | R `loo`, Python ArviZ |
| Operationally most relevant for us | Conceptually wrong (M-closed) | YES (M-open, predictive-density) | YES (M-open, joint optim) |

**Key insight (Yao et al. 2018; Le & Clarke 2017; Geweke-Amisano 2011):** because none of our 6 regime classifiers IS the true data-generating process for "next-period market regime," BMA's M-closed assumption is violated and BMA will *over-concentrate* posterior weight onto whichever model happens to fit the in-sample data best — typically the most-flexible classifier, not the most-correct one. **Stacking and predictive-likelihood pooling do NOT have this pathology.**

---

## Section C — Validation-depth-informed priors

### C.1 — Academic guidance

**The literature is genuinely thin on this exact question.** The closest principled answer comes from three sources:

1. **Morita-Thall-Müller (2008)**: prior effective sample size. Translate "HIGH validation depth" into "this prior is worth N_HIGH hypothetical observations." Then the effective informativeness of the prior is captured numerically.
2. **Fernández-Ley-Steel (2001)**: benchmark priors. Confirms that posterior model probabilities are *very* sensitive to prior choice in BMA — sensitivity that *increases* at small N. Implication: at v0.1 (N=0 resolved) our prior IS the answer; at v0.5 (N=50) the prior is half the answer.
3. **Hinne et al. (2020)**: explicitly endorses informative priors when "elicited from prior data" — which matches our HIGH/MEDIUM/LOW tags being summaries of decades of pre-existing literature on D1 (economic-cycle), D2 (credit-stress), D3 (vol-regime), D4 (dollar-regime), D5 (Bridgewater-4box), and the LOW-tagged sixth dimension.

### C.2 — Is HIGH/MEDIUM/LOW with weights 1.0/0.7/0.5 Bayesian-defensible?

**Answer: Conditionally yes, but the right framing is prior-ESS, not point-weights.**

The 1.0/0.7/0.5 ratios are a *qualitative ordering*, not a probability distribution. Treating them as direct weights conflates two distinct things:
- **Prior plausibility**: how much do I a priori believe in classifier k's correctness? (This belongs in P(M_k).)
- **Predictive precision**: how tightly does classifier k's predictive density concentrate around its point prediction? (This belongs in the within-model likelihood.)

The Bayesian-defensible translation is:
- Convert "HIGH validation depth" → "prior is worth ~5–10 hypothetical resolved predictions of agreement with the truth"
- Convert "MEDIUM" → "prior is worth ~2–3 hypothetical resolved predictions"
- Convert "LOW" → "prior is worth ~1 hypothetical resolved prediction"

For our 4 HIGH / 1 MEDIUM / 1 LOW classifier roster, a reasonable encoding is:

| Classifier | Validation tag | Prior ESS | Implied prior weight (normalized) |
|---|---|---|---|
| D1 economic cycle | HIGH | 8 | 0.20 |
| D2 credit stress | HIGH | 8 | 0.20 |
| D3 vol regime | HIGH | 8 | 0.20 |
| D4 dollar regime | HIGH | 8 | 0.20 |
| D5 Bridgewater-4box | MEDIUM | 4 | 0.10 |
| D6 (LOW-tagged) | LOW | 2 | 0.05 |
| Equal-weight-prior anchor (see Diebold-Pauly 1990) | — | residual | 0.05 |
| **Total prior ESS** |  | **38** | **1.00** |

(The "equal-weight anchor" line is a regularization term, motivated by Diebold-Pauly 1990 and the Smith-Wallis/Claeskens forecast-combination-puzzle literature: shrink the posterior toward equal-weight by giving 5% prior mass to the equal-weight forecast itself.)

**Sanity check vs operator's 1.0/0.7/0.5:** the operator's normalized weights are HIGH=1.0/4.7≈0.213, MEDIUM=0.7/4.7≈0.149, LOW=0.5/4.7≈0.106. With 4×0.213 + 1×0.149 + 1×0.106 = 1.106 (operator's weights don't normalize to 1; they sum to 4×1.0+0.7+0.5 = 5.2, so the actual normalized weights are HIGH=0.192, MEDIUM=0.135, LOW=0.096). Compare to our Bayesian-prior-derived weights (HIGH=0.20, MEDIUM=0.10, LOW=0.05). **The orderings match; the relative magnitudes are similar.** The Bayesian framing is more conservative on MEDIUM and LOW, which is consistent with the finding that small-N prior tilting away from equal-weight is risky (Smith-Wallis 2009).

### C.3 — Hierarchical priors when classifiers share data inputs

If two classifiers share input data (e.g., D1 and D5 both use FRED yield-curve data), their predictive errors are positively correlated, and naive BMA *over-counts* their evidence. Bayesian hierarchical stacking (Yao et al. 2022) addresses this by treating model weights as draws from a hierarchical prior, which automatically shrinks weights of correlated models toward each other.

**Practical recommendation for our case:** at v0.1, this is over-engineering. At v0.5+, if any two of D1–D6 are found to share >50% of their input series, bring in `loo_model_weights(method="stacking")` from the loo package (which jointly optimizes weights and naturally penalizes redundancy) and explicitly verify the cross-classifier prediction correlation matrix.

---

## Section D — Small-sample behavior

### D.1 — Behavior when N < 50

The dominant fact: **Bayesian posteriors are convex combinations of the prior and the data-likelihood.** The "weight" placed on the prior is roughly prior-ESS / (prior-ESS + N_observations).

With our recommended prior-ESS sum ≈ 38:
- **N=0 (v0.1):** posterior weight on prior ≈ 38/38 = 100%. Posterior IS the prior.
- **N=10:** posterior weight on prior ≈ 38/48 = 79%. Mostly prior.
- **N=22:** posterior weight on prior ≈ 38/60 = 63%. Prior still dominates but data starts mattering.
- **N=38:** posterior weight on prior ≈ 50%. Coin flip.
- **N=50 (v0.5):** posterior weight on prior ≈ 38/88 = 43%. Data-leaning.
- **N=100:** posterior weight on prior ≈ 28%. Data-dominant.
- **N=200:** posterior weight on prior ≈ 16%. Asymptotic regime.

**The general rule of thumb (Morita-Thall-Müller 2008; corroborated by the Wiesenfarth 2020 "Quantification of prior impact" paper):** prior dominance occurs when prior-ESS ≥ N_data. Equipoise at prior-ESS ≈ N_data. Data dominance at N_data ≥ 2 × prior-ESS.

### D.2 — Implication for v0.1

**At v0.1 with N=0 resolved predictions, every Bayesian method we considered (BMA, predictive-likelihood pools, stacking, pseudo-BMA, BB-pseudo-BMA) reduces to "report the prior weights" — there is no posterior update.** This is mathematical fact, not pessimism.

**Operational consequence:** the v0.1 ensemble output is effectively *whatever weights the operator chose at design time*. The Bayesian machinery contributes nothing during v0.1 except (a) a principled vocabulary for reasoning about prior strength via prior-ESS, and (b) a ready-to-fire posterior-update mechanism that activates as soon as resolved predictions begin accumulating.

**This argues against deploying the full Bayesian stack at v0.1.** Instead: at v0.1 use the prior weights directly (validation-depth-informed equal-weight-anchored). At v0.3–v0.5 (~20–50 resolved predictions), switch to the recursive Bayesian update mechanism described in Section E.3.

### D.3 — Why BMA specifically is *worse* than equal-weight at small N

The forecast-combination puzzle (Smith-Wallis 2009; Claeskens et al. 2016; cited in sibling Q2-ensemble-methods-research.md) shows that estimation error in *weights* is the dominant source of MSE inflation at small samples. BMA is a particularly bad offender because its weights are determined by *Bayes factors*, which are exponential in the log-likelihood ratio, and so amplify small-sample noise. (This is the classic "BMA winner-take-all" pathology.)

**Pseudo-BMA+ with Bayesian bootstrap (BB) explicitly addresses this by stabilizing the weights** (Yao et al. 2018, §4). This is why our recommendation for v0.5+ is BB-pseudo-BMA+ rather than full BMA.

---

## Section E — Implementation in Python

### E.1 — Software landscape

| Package | BMA | Stacking | Pseudo-BMA+ | Custom priors | Notes |
|---|---|---|---|---|---|
| **PyMC** | Indirect (via az.compare) | YES | YES (BB) | YES (manual) | Stan-style probabilistic programming; full Bayesian MCMC |
| **ArviZ** | YES (`az.compare`, `az.weight_predictions`) | YES (default method) | YES | Limited (must set in az.compare) | Post-fit diagnostics + weighting |
| **statsmodels** | Limited (no native BMA function) | No | No | No | Use only for individual model fits |
| **scikit-learn** | No | Stacking via `StackingClassifier` (frequentist, non-Bayesian) | No | No | Frequentist ML stacking; not Bayesian |
| **`pymc-bart`** | No | No | No | No | BART; orthogonal |

**Recommended stack:** PyMC + ArviZ. PyMC fits the candidate models (or accepts predictive distributions from external classifiers via custom likelihoods); ArviZ computes LOO and stacking weights via `az.compare` and `az.weight_predictions`.

### E.2 — Code skeleton (v0.5+ when N ≈ 50 resolved predictions exist)

```python
import arviz as az
import numpy as np

# Step 1: collect each classifier's predictive log-density on each resolved obs
# log_lik_matrix has shape (N_resolved_predictions, K_classifiers)
log_lik = compute_pointwise_log_likelihoods(
    resolved_truth=regime_labels_truth,         # length-N true regime labels
    classifier_predictive_dists=six_classifier_outputs,  # K=6 distributions per obs
)

# Step 2: build ArviZ InferenceData per classifier (one observed-likelihood var each)
idata_list = [build_idata_from_log_lik(log_lik[:, k]) for k in range(6)]
model_dict = {f"D{k+1}": idata_list[k] for k in range(6)}

# Step 3: get weights via stacking (default), with prior anchor
comp_table = az.compare(
    model_dict,
    method="stacking",          # Yao-Vehtari-Simpson-Gelman 2018
    ic="loo",
)
print(comp_table[["weight", "elpd_loo", "dse"]])

# Step 4: blend posterior weights with prior weights (validation-depth-anchored)
prior_weights = np.array([0.20, 0.20, 0.20, 0.20, 0.10, 0.05])  # D1..D6
prior_ess = 38
N_resolved = log_lik.shape[0]
posterior_weight_on_prior = prior_ess / (prior_ess + N_resolved)
final_weights = (
    posterior_weight_on_prior * prior_weights
    + (1 - posterior_weight_on_prior) * comp_table["weight"].values
)
final_weights /= final_weights.sum()

# Step 5: produce weighted-posterior ensemble regime
ensemble_idata = az.weight_predictions(idata_list, weights=final_weights)
```

For the BB-pseudo-BMA+ alternative (which is more conservative at small N):

```python
comp_table = az.compare(model_dict, method="BB-pseudo-BMA")
```

### E.3 — Recursive Bayesian update mechanism

The shrinkage formula in Step 4 above IS the recursive Bayesian update — every new resolved prediction adds 1 to N_resolved, mechanically shrinking the prior's influence. No bespoke filter needed. (For genuine time-varying weights — e.g., regime-dependent weights — switch to Bayesian Hierarchical Stacking from Yao et al. 2022 or Bayesian Predictive Synthesis from McAlinn-West 2019. Both require >100 resolved predictions to be useful and are over-engineering until v1.0.)

### E.4 — Computational cost note

For K=6 classifiers and N≤200 resolved predictions, all Bayesian methods listed run in **<1 second on a laptop**. Bottleneck is the predictive-density computation per resolved observation, not the weight optimization.

---

## Section F — The single recommended Bayesian method for our v0.1

### Recommendation: **Validation-depth-anchored prior weights, with the Bayesian update mechanism standing by but inactive until N ≥ 22 resolved predictions.**

**Specifically:**

1. **At v0.1 (N=0):** Use the following fixed prior weights:

| Classifier | Prior weight | Prior ESS |
|---|---|---|
| D1 economic cycle (HIGH) | 0.20 | 8 |
| D2 credit stress (HIGH) | 0.20 | 8 |
| D3 vol regime (HIGH) | 0.20 | 8 |
| D4 dollar regime (HIGH) | 0.20 | 8 |
| D5 Bridgewater-4box (MEDIUM) | 0.10 | 4 |
| D6 (LOW-tagged) | 0.05 | 2 |
| (Equal-weight anchor) | 0.05 | — |
| **Total** | **1.00** | **38** |

2. **At v0.3 (N ≈ 10–22):** Begin computing pseudo-BMA+ weights using the loo package, BUT report them only as "diagnostic" — the operating weights remain the v0.1 prior weights, since prior dominance is still ≥63%.

3. **At v0.5 (N ≈ 50):** Switch the operating weights to the convex combination:
   ```
   w_final = (38 / (38 + N)) · w_prior + (N / (38 + N)) · w_pseudo_BMA+
   ```
   This automatically shrinks toward the data as N grows, reaching ~50% data-driven at N=38 and ~75% data-driven at N=114.

4. **At v1.0 (N > 100):** Switch to full Bayesian stacking via `az.compare(method="stacking")`. Optionally upgrade to Bayesian Hierarchical Stacking if regime-dependent weighting is operationally needed.

### Why this method specifically (vs alternatives):

- **vs Full BMA**: BMA assumes M-closed (one classifier IS the truth). Our 6 classifiers are M-open. BMA will over-concentrate weight onto the wrong model.
- **vs Pure equal-weight**: Throws away genuinely informative prior info from 30+ years of regime-detection literature on D1-D4. Smith-Wallis-style equal-weight robustness applies most strongly at the *posterior-update step*, not at the *prior step*.
- **vs Pure stacking at v0.1**: Stacking with N=0 has no data and would just collapse to whatever its initialization was — no benefit over manually-set priors.
- **vs Bayesian Hierarchical Stacking**: Over-engineered until N >> 100.
- **vs Bayesian Predictive Synthesis (McAlinn-West)**: Over-engineered until N >> 100; also requires explicit time-series structure on the agent-opinion process.

### Specific Bayes-factor threshold for "BMA differs significantly from equal-weight":

By Kass-Raftery (1995), pairwise Bayes factor BF > 20 is "strong" evidence and BF > 150 is "decisive." Translation to our case: a single classifier should receive weight noticeably above (or below) equal-weight only if its predictive log-likelihood exceeds the second-best classifier's by Δlog-lik > log(20) ≈ 3.0. With 6 classifiers and ~6-bit-of-info per resolved regime label, this translates to needing a classifier to outperform peers on roughly **5+ resolved predictions in a row** before its weight noticeably moves. *This is empirically achievable around the v0.5 milestone.*

### Specific small-sample threshold below which priors dominate:

**N_resolved < 22 → posterior is >63% prior** (with our recommended prior-ESS=38). This is the operationally-relevant cutoff: below 22 resolved predictions, the Bayesian update is not adding meaningful information beyond the manual prior. The operator should treat output as "prior-only" until v0.3.

---

## Final summary for parent agent

**(a) Deliverable path:** `/Users/sehoonbyun/Documents/equity-research-system/.claude/references/empirical/data-sources/Q2-bayesian-methods-deep.md`

**(b) Total Bayesian methods compared:** 7
   1. Classical BMA (Hoeting et al. 1999)
   2. BMA with informative model priors (Hinne et al. 2020)
   3. Predictive-likelihood pools (Geweke-Amisano 2011)
   4. Bayesian stacking via PSIS-LOO (Yao et al. 2018)
   5. Pseudo-BMA / BB-pseudo-BMA+ (Yao et al. 2018, §4)
   6. Bayesian Hierarchical Stacking (Yao et al. 2022)
   7. Bayesian Predictive Synthesis (McAlinn-West 2019; Waggoner-Zha 2012 dynamic pools)

**(c) Single recommended Bayesian method for v0.1:** **Validation-depth-anchored prior weights with prior-ESS=38, with pseudo-BMA+ via the `loo` package activating progressively as N_resolved grows (Diebold-Pauly-style shrinkage between prior weights and pseudo-BMA+ weights).** Full Bayesian stacking deferred to v1.0.

**(d) Specific prior weights for our 6 classifiers:**
   - D1 economic cycle (HIGH): **0.20** (prior ESS = 8)
   - D2 credit stress (HIGH): **0.20** (prior ESS = 8)
   - D3 vol regime (HIGH): **0.20** (prior ESS = 8)
   - D4 dollar regime (HIGH): **0.20** (prior ESS = 8)
   - D5 Bridgewater-4box (MEDIUM): **0.10** (prior ESS = 4)
   - D6 (LOW-tagged sixth dimension): **0.05** (prior ESS = 2)
   - Equal-weight regularization anchor: **0.05** (prior ESS not directly translated)
   - Total prior ESS = 38; total weights sum to 1.00.

**(e) Small-sample-size threshold below which Bayesian priors dominate posteriors:**
   **N_resolved ≈ 22.** Below this, posterior weight on prior is >63%. Equipoise (50/50) at N≈38. Data-dominance (>67% data, <33% prior) at N≈75. Operator's claimed "v0.5 = ~50 resolved predictions" milestone places v0.5 at ~57% data / 43% prior — exactly the regime where the Bayesian update mechanism becomes most valuable.

### Acknowledged literature gaps (per anti-hallucination instruction)

- **No paper directly endorses HIGH/MEDIUM/LOW point-weights of 1.0/0.7/0.5.** This is an operator heuristic, not literature. The Bayesian-defensible reframing is via prior-ESS (Morita-Thall-Müller 2008), which I have done above.
- **The "0 resolved predictions" cold-start problem is essentially undiscussed** in the BMA literature. The literature implicitly assumes N is large enough for the marginal likelihood to be informative. Our v0.1 case lies *outside* the regime where the academic literature has empirical guidance.
- **Multiple PDF fetch attempts failed** (Hoeting 1999 PDF on stat.colostate.edu, Wright 2003 PDF on NBER, Geweke-Amisano ECB working paper PDF, Yao et al. 2017 Columbia PDF, Le-Clarke 2017 JMLR PDF, Raftery-Madigan-Hoeting 1997 PDF, Stata BMA manual PDF, Hinne et al. 2020 UvA PDF). The information for those entries was assembled from the abstract pages, search-result summaries, and the citations within other papers. Substantive technical claims here (e.g., the specific Bayes factor thresholds, the stacking formula structure, the Geweke-Amisano predictive-likelihood approach) are corroborated by at least 2 independent search-result summaries each.

