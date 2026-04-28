# Academic frontier — regime detection methods

**Scope.** Survey of post-2020 advances in regime detection that go beyond the classical Hamilton (1989) Markov-switching / Bridgewater 4-box vocabulary that already underpins D1/D5 of our S0 sidecar. Goal is to (a) identify methods worth borrowing for v0.5+, (b) flag NEW regime *dimensions* that the frontier has surfaced (and that may belong in S0), and (c) draw a line between research-only ideas and what a sub-$1M operator can actually run.

**Operator constraints.** Same as the rest of `data-sources/`: <$1M AUM equivalent, $250/mo non-LLM budget, no Bloomberg, no institutional data feeds, no GPU cluster. Methods are graded on *implementability* under these constraints, not their academic novelty.

**Anti-hallucination note.** Every arxiv paper cited below was fetched (abstract or HTML rendering) — second-hand summaries are not used. When the abstract was opaque or the PDF unrenderable, this is flagged inline.

---

## Section A — Curated sources (tier-labeled)

Tiers:
- **T1 — Foundational / canonical** (cite when establishing terminology; not novel post-2020)
- **T2 — Recent empirical advance** (post-2020 paper with concrete out-of-sample evidence)
- **T3 — Promising but unreplicated / single-author / niche** (read for ideas, do not implement on the strength of one paper)
- **T4 — Survey / review article** (use to map the field)

### Markov-switching and HMM family

| Source | Tier | Year | Why it matters |
|---|---|---|---|
| Hamilton, "A new approach to the economic analysis of nonstationary time series and the business cycle," *Econometrica* 57(2) | T1 | 1989 | Foundational MS model. Two-state filter (expansion/recession) on GNP growth. Still the reference point for "regime-switching." |
| Krolzig, *Markov-Switching Vector Autoregressions* (Springer monograph) | T1 | 1997 | Multivariate MS-VAR; the macro-regime workhorse before deep-learning era. |
| Ang & Timmermann, "Regime Changes and Financial Markets," *Annual Review of Financial Economics* 4: 313–337 | T4 | 2012 | The standard survey. Coverage: regime-switching can capture fat tails, time-varying corr, heteroskedasticity, skewness; documents that means/vols/cross-covariances differ across regimes consistently across asset classes. SSRN: `papers.ssrn.com/sol3/papers.cfm?abstract_id=1919497`. |
| Ardia, Bluteau, Boudt, Catania & Trottier, "Markov-Switching GARCH Models in R: The MSGARCH Package," *Journal of Statistical Software* 91(4) | T2 | 2019 | Reference implementation of MS-GARCH. R-only but free; ML and Bayesian MCMC estimation; conditional density / VaR / ES forecasts. CRAN: `cran.r-project.org/package=MSGARCH`. |
| Pohle, Langrock, van Beest & Schmidt, "Selecting the Number of States in Hidden Markov Models — Pitfalls, Practical Challenges and Pragmatic Solutions" (arxiv 1701.08673) | T2 | 2017 (last rev) | Practical warning: AIC/BIC are commonly mis-applied for HMM order selection; both criteria tend to over-state state count under model misspecification. Use cross-validation or held-out likelihood instead. |
| Issa & Horvath, "Non-parametric online market regime detection and regime clustering for multidimensional and path-dependent data structures" (arxiv 2306.15835) | T3 | 2023 | Path-signature + MMD two-sample test for online regime detection. Works on equity baskets and crypto. No HMM / no parametric assumption. Computationally heavy; relevant as a *concept* (signature features) more than a deployable tool at our scale. |

### Statistical jump models — the post-2020 successor to HMM

| Source | Tier | Year | Why it matters |
|---|---|---|---|
| Nystrup, Madsen & Lindström, "Stylised facts of financial time series and hidden Markov models in continuous time" (and related 2017–2021 line) | T1 | 2017–2021 | Origin of statistical jump models (JMs) as alternative to HMMs in finance — adds a *jump penalty* to enforce regime persistence, addressing HMMs' chronic over-segmentation problem. |
| Shu, Yu & Mulvey, "Downside Risk Reduction Using Regime-Switching Signals: A Statistical Jump Model Approach" (arxiv 2402.05272) | T2 | 2024 | Out-of-sample 1990–2023 on US/Germany/Japan equities with realistic transaction costs. JM-guided strategy "consistently reduced volatility and max drawdown, enhanced Sharpe ratio, and outperformed both HMM-guided and buy-and-hold." Single research group, but methodology is well-specified and replicable. |
| Shu, Yu & Mulvey, "Dynamic Asset Allocation with Asset-Specific Regime Forecasts" (arxiv 2406.09578) | T2 | 2024 | Two-stage hybrid: unsupervised JM labels regimes, supervised gradient-boosted decision tree predicts them from cross-asset macro features. 12-asset universe, 1991–2023. Reports outperformance vs minimum-variance, mean-variance, naive benchmarks (specific Sharpe figures not in abstract). Implementable on commodity hardware. |
| Shu & Mulvey, "Dynamic Factor Allocation Leveraging Regime-Switching Signals" (arxiv 2410.14841) | T2 | 2024 | Sparse jump model on 6 style factors (value, size, momentum, quality, low-vol, growth). Black-Litterman overlay. **Concrete reported numbers:** information ratio improves from 0.05 (EW benchmark) to ~0.4 vs market; IR 0.4–0.5 vs EW. Single-author group (Mulvey lab); awaits independent replication, but the result is one of the cleanest factor-timing-via-regime numbers in the recent literature. |

### Change-point detection

| Source | Tier | Year | Why it matters |
|---|---|---|---|
| Adams & MacKay, "Bayesian Online Change-Point Detection" (arxiv 0710.3742) | T1 | 2007 | The original BOCPD algorithm. O(T) per-step; gives full posterior over run-length. Plenty of reference Python implementations (e.g. `bayesian-changepoint-detection` on PyPI). |
| Romano, Eckley, Fearnhead & Rigaill, "Fast Online Changepoint Detection via Functional Pruning CUSUM Statistics" (FOCuS), *JMLR* 24 | T2 | 2023 | High-frequency / streaming-aware CUSUM. Equivalent to running CUSUM simultaneously for all window sizes via functional pruning. Crucial when you don't know the change magnitude ex ante. JMLR: `jmlr.org/papers/v24/21-1230.html`. |
| Tsaknaki, Lillo & Mazzarisi, "Online Learning of Order Flow and Market Impact with Bayesian Change-Point Detection Methods" (arxiv 2307.02375; published *Quantitative Finance* 24, 2024) | T2 | 2023–2024 | New "MBOC" (Markovian BOCPD for Correlated data) algorithm extending BOCPD to Markovian within-regime dynamics + score-driven time-varying parameters. Empirical: NASDAQ MSFT/TSLA order-flow; ~94–95% of within-regime observations satisfy Gaussianity, ~98–99% no serial correlation in residuals at 3-min aggregation. MBOC beats BOCPD/MBO/ARMA(1,1) in MSE for one-step prediction. |
| Tsaknaki, Lillo & Mazzarisi, "Bayesian Autoregressive Online Change-Point Detection with Time-Varying Parameters" (arxiv 2407.16376) | T3 | 2024 | Companion paper extending the MBOC framework with time-varying autoregressive params. Same group; not yet replicated externally. |

### Network and graph-based regime methods

| Source | Tier | Year | Why it matters |
|---|---|---|---|
| Diebold & Yilmaz, "Better to give than to receive: Predictive directional measurement of volatility spillovers," *International Journal of Forecasting* 28(1) | T1 | 2012 | Foundational variance-decomposition spillover index (also Diebold-Yilmaz 2014 *Journal of Econometrics*). Time-varying total connectedness from a rolling-window VAR. |
| Diebold & Yilmaz, "On the Past, Present, and Future of the Diebold-Yilmaz Approach to Dynamic Network Connectedness" (arxiv 2211.04184; published *Journal of Econometrics* 2023) | T4 | 2022–2023 | Authors' own retrospective + roadmap. Useful as a literature anchor; full content of the survey not extractable from the abstract page. |
| Greenwood-Nimmo, Nguyen, Rafferty et al. "Detecting statistically significant changes in connectedness: A bootstrap-based technique," *Economic Modelling* (Elsevier, 2024) | T2 | 2024 | Bootstrap test for whether the Diebold-Yilmaz total spillover index has *statistically* shifted — turns the spillover index from a descriptive series into a hypothesis-testable regime indicator. ScienceDirect: `S0264999324002001`. |
| Mantegna, "Hierarchical structure in financial markets," *European Physical Journal B* 11 | T1 | 1999 | Origin of MST-on-correlation method; n−1 edges. |
| Tumminello, Aste, Di Matteo & Mantegna, "A tool for filtering information in complex systems," *PNAS* 102(30) | T1 | 2005 | Origin of Planar Maximally Filtered Graph (PMFG); 3(n−2) edges, retains more structure than MST. |
| Wang & Xie, "Understanding Changes in the Topology and Geometry of Financial Market Correlations during a Market Crash," *Entropy* 23(9): 1211 | T3 | 2021 | Applies PMFG-derived topological measures to market-crash regimes. Single paper; concept is sound but not a generalized regime-detection tool. |
| Orton & Gebbie, "Representation Learning for Regime detection in Block Hierarchical Financial Markets" (arxiv 2410.22346) | T3 | 2024 | Riemannian-manifold deep learning (SPDNet, SPD-NetBN, U-SPDNet) on block-hierarchical SPD correlation matrices. JSE Top 60 (2000–2023). **Honest author finding:** "using a singular performance metric is misleading … models overfit in learning spatio-temporal correlation dynamics." Useful as a *negative result* — argues against optimism on deep-correlation-manifold methods at small-operator scale. |
| Dolfin, Kapetanios, Leonida & De Leon Miranda, "Investor behavior and multiscale cross-correlations: Unveiling regime shifts in global financial markets" (arxiv 2408.17200) | T3 | 2024 | Detrended cross-correlation cost (DCCC) on G7 + Russia + China daily prices. Sharp DCCC spikes around COVID-19, Russia–Ukraine 2022, Brexit. Methodology specified; replication in single paper. |
| Zlotnikov, Liu, Halperin, He & Huang, "Model-Free Market Risk Hedging Using Crowding Networks" (arxiv 2306.08105) | T3 | 2023 | Network-of-fund-holdings → crowding scores per stock → distribution-free long-short hedge. Requires only public 13F-style holdings data. Plausibly implementable on a small operator if 13F ingest is built. |

### Cross-asset / multi-asset and correlation breakdown

| Source | Tier | Year | Why it matters |
|---|---|---|---|
| Forbes & Rigobon, "No Contagion, Only Interdependence: Measuring Stock Market Comovements," *Journal of Finance* 57(5): 2223–2261 | T1 | 2002 | Foundational: standard correlation estimates upward-biased during high-vol regimes; "contagion" often disappears once you correct for volatility. The reference test for distinguishing regime-shift from amplified-noise. |
| Longin & Solnik, "Extreme correlation of international equity markets," *Journal of Finance* 56(2) | T1 | 2001 | Tail-correlation result: equity-market correlations rise sharply in tail regimes (left tail more than right). Defining empirical fact about correlation regimes. |
| Asness, Moskowitz & Pedersen, "Value and Momentum Everywhere," *Journal of Finance* 68(3) | T1 | 2013 | Cross-asset commonality of factor regimes — value/momentum span 8 markets/asset classes; value-momentum negative correlation persists across asset classes; common global funding-liquidity risk explains part of the joint regime structure. AQR maintains updated monthly factor data. |
| Bucci & Ciciretti, "Market Regime Detection via Realized Covariances: A Comparison between Unsupervised Learning and Nonlinear Models" (arxiv 2104.03667) | T2 | 2021 | Head-to-head: VLSTAR (vector logistic smooth-transition AR) vs agglomerative hierarchical clustering on monthly realized covariance matrices. **Finding:** VLSTAR wins for regime labelling. Useful negative result against naive clustering. |
| (Various 2024 reviews on stock-bond correlation regime flip) | T2 | 2024 | Stock-bond correlation went persistently positive 2022 onward (driven by inflation regime). Documented in Vanguard / BIS / Financial Analysts Journal pieces; this is a *macro fact* not a method, but it is the most consequential cross-asset regime shift of the post-2020 period. |
| arxiv 2604.17251 "ORCA — Online Regime Correlation Analyzer" | T3 | 2026 | 127 spectral / eigenvector / graph-topological features extracted from cross-asset correlation networks at multiple time scales; produces calibrated 10-day rally/crash probabilities. Note: paper is dated past current cutoff in our research window — treat as a frontier *direction*, not a tool to deploy. |
| arxiv 2510.20868 "CRISP — Crisis-Resilient Portfolio Management via Graph-based Spatio-Temporal Learning" | T3 | 2025 | GCN + attention; filters 92.5% of asset-asset connections as noise while preserving "crisis-relevant" edges. Single-paper, large model; not implementable at our scale. |

### Macro-finance

| Source | Tier | Year | Why it matters |
|---|---|---|---|
| Lo, "The Adaptive Markets Hypothesis," *Journal of Portfolio Management* 30 | T1 | 2004 | Frames market efficiency as time-varying / regime-dependent. |
| Bernanke, Boivin & Eliasz, "Measuring the Effects of Monetary Policy: A Factor-Augmented Vector Autoregressive (FAVAR) Approach," *Quarterly Journal of Economics* 120(1) | T1 | 2005 | Foundational FAVAR — combines structural VAR with large-N factor extraction; the framework underlying most modern macro nowcasting. |
| Stock & Watson, "Dynamic Factor Models, Factor-Augmented Vector Autoregressions, and Structural Vector Autoregressions in Macroeconomics" (chapter, *Handbook of Macroeconomics* vol. 2A) | T1 | 2016 | The macro-nowcasting reference; basis for the NY Fed Nowcast and most factor-extraction-based recession indicators. |
| (multiple 2022–2024 AMH replications, e.g. Cambridge / Tandfonline / Emerald 2024) | T2 | 2022–2024 | AMH support holds in updated samples through 2023; SR-based / SMA-based timing strategies beat buy-and-hold during inefficient sub-periods. Useful as an empirical underpin for *why* regime methods work at all. |

---

## Section B — Methods table

| Method | Domain | Out-of-sample edge (where reported) | Implementability for <$1M operator | Replication status | Primary citation |
|---|---|---|---|---|---|
| **Hamilton 2-state MS-AR** | Macro / GDP regime | Standard NBER-recession alignment ~70-80% (depends on filter vs smoother). Recession smoothed-prob >0.5 historically lags NBER call by ~3 months. | **Yes — trivial.** Python `statsmodels.tsa.regime_switching.MarkovRegression`; one-day implementation on FRED data. | Replicated thousands of times. | Hamilton 1989 |
| **MS-VAR (Krolzig)** | Multivariate macro regime | Modest improvement over linear VAR for crisis-period forecasting; sensitive to state-count choice. | **Yes — moderate effort.** Use `MSwM` in R or roll your own; 5–10 vars max for stability. | Replicated. | Krolzig 1997 |
| **MSGARCH** | Vol regime | Improved VaR / ES forecasts vs single-state GARCH in MSGARCH paper benchmarks; gains concentrated in crisis windows. | **Yes — moderate.** R `MSGARCH` package is production-grade; Bayesian MCMC option for small samples. | Replicated. | Ardia et al. 2019 |
| **Standard HMM (k-state Gaussian)** | Equity returns regime | Over-segments severely without persistence prior; CV-based state selection essential. | **Yes — trivial code, hard to use well.** `hmmlearn` in Python. | Replicated, with documented pitfalls (Pohle et al. 2017). | Hamilton, Rabiner |
| **Statistical jump model (JM)** | Equity / multi-asset regime | Out-of-sample 1990–2023 on US/DE/JP: lower vol, lower drawdown, higher Sharpe vs HMM and buy-and-hold (Shu et al. 2024). Specific numbers for factor IR: 0.05 → ~0.4 vs market. | **Yes — moderate.** No proprietary library; the JM is a clustering algorithm with a transition penalty — easy to implement (~200 lines Python). Feature engineering is the real work. | Single research group (Mulvey/Nystrup line) so far; methodology fully specified. **Awaits independent replication.** | Nystrup et al. 2017–2021; Shu, Yu & Mulvey 2024 (arxiv 2402.05272, 2406.09578, 2410.14841) |
| **Conditional Restricted Boltzmann Machine (CRBM)** | Multi-asset crisis regime | "Crisis regime" emerges as distinct learned representation, not high-variance noise. | **No.** Heavy training, opaque, single paper. | Single paper. | arxiv 2512.21823 |
| **SPDNet on block-hierarchical SPD** | Equity correlation regime | Authors explicitly find single-metric performance is misleading; overfitting common. | **No.** GPU + Riemannian-manifold expertise. | Single paper, with negative caveat from authors. | Orton & Gebbie 2024 (arxiv 2410.22346) |
| **LSTM/Transformer regime classifiers** | Equity regime / direction | Krauss/Fischer (EJOR 2017–2018): 0.46% daily return, Sharpe 5.8 *pre-cost* on S&P stocks 1992–2009; **alpha arbitraged away post-2010**, returns ~0 after costs. This is the canonical replication-failure of deep-learning trading at constituent-stock scale. | Possible but **not recommended** for regime detection — you'd be re-running a strategy whose edge died ~15 years ago. | Replicated; **out-of-sample failure documented**. | Krauss, Do & Huck 2017 (EJOR 259); Fischer & Krauss 2018 (EJOR 270) |
| **BOCPD (Adams-MacKay)** | Univariate / low-dim regime | Real-time detection of mean/variance shifts; lag depends on hazard rate λ choice. Tsaknaki et al. 2024 report empirical regimes align with major macro events on S&P 500 / CSI 300. | **Yes — easy.** PyPI `bayesian-changepoint-detection`; <100 lines of glue code. λ tuning is the only real choice. | Foundational paper has ~thousands of citations and many implementations. | Adams & MacKay 2007 |
| **MBOC (BOCPD with Markovian within-regime dynamics)** | Order flow / correlated regimes | Lower MSE vs BOCPD/MBO/ARMA(1,1) on NASDAQ MSFT/TSLA; ~95% Gaussianity inside regimes. | **Borderline.** Score-driven extension is mathematically nontrivial but specified; needs careful coding. | Single research group (Lillo lab); awaiting external replication. | Tsaknaki, Lillo & Mazzarisi 2024 (arxiv 2307.02375; QF 2024) |
| **FOCuS (functional online CUSUM)** | High-frequency online change-point | Equivalent to running CUSUM at all window sizes simultaneously; bounded per-step cost via functional pruning. | **Yes — easy.** Reference implementation; pure-Python or R. | JMLR 2023 — full algorithmic spec + benchmarks. | Romano et al. 2023 (JMLR 24) |
| **Diebold-Yilmaz spillover index** | Network / cross-asset connectedness | Time-varying total spillover index spikes around all major global crises 2007–2024. Bootstrap test (Greenwood-Nimmo et al. 2024) lets you call shifts statistically. | **Yes — moderate.** R `frequencyConnectedness` and Python ports exist; needs a daily VAR estimation routine. Shared MOVE / VIX / yield-curve inputs — fits our existing free MCP coverage. | Heavily replicated; survey by Diebold-Yilmaz 2023 is the field anchor. | Diebold-Yilmaz 2012, 2014; arxiv 2211.04184 |
| **MST / PMFG dynamics** | Correlation network regime | Topology metrics (e.g. avg path length, central-node degree) shift around crashes. | **Yes — easy** for daily data on liquid universe; `networkx` + `scipy.sparse.csgraph.minimum_spanning_tree`. | Heavy academic literature; few production pipelines. | Mantegna 1999; Tumminello et al. 2005 |
| **Path-signature + MMD non-parametric regime test** | Multi-dim path-dependent | "Swiftly indicated periods of turmoil" on equity baskets and crypto; no quantitative metric in abstract. | **No** at our scale — signature computation is expensive on long histories; tuning the kernel non-trivial. | Single paper. | Issa & Horvath 2023 (arxiv 2306.15835) |
| **Forbes-Rigobon adjusted-correlation contagion test** | Cross-asset / contagion | Decisive in distinguishing "true regime shift" from "vol amplification of stable correlations." 2023 Journal of Financial Markets paper documents bias when constant-beta assumption fails — recommends Spearman rank as alternative. | **Yes — easy.** Closed-form correction. | Original heavily cited; recent critique acknowledged. | Forbes & Rigobon 2002; recent critique 2023 (`S1057521923003794`) |

---

## Section C — Recommendations for our system

### Practical at our scale (consider for v0.5+ S0 sidecar)

**(a) BOCPD as a streaming overlay on the existing S0 series.** Strongest recommendation. Run BOCPD on a handful of canonical regime series we already pull (VIX/VIX3M ratio, HY-OAS, SOFR-Tbill, MOVE, EBP, stock-bond rolling correlation). It is:
- Free (open-source Python), <100 lines of glue
- Streaming and online — fits S0's daily refresh cadence
- Outputs a per-day posterior over run-length, which is a calibrated regime-shift probability — directly consumable by sizing logic
- Replicated foundational method with two decades of usage; not a single-paper bet

The only knob is the hazard rate λ; tune once on 1990–2015 history, lock for go-forward use. Adding BOCPD probabilities as an extra column in the S0 sidecar is the lowest-risk, highest-payoff frontier upgrade we can make.

**(b) Statistical jump model (JM) for the regime *labelling* layer.** Replace or supplement the implicit Hamilton-style HMM (which we haven't actually implemented yet — D5 is currently rule-based). The JM is essentially "k-means clustering with a transition penalty on a feature vector of return moments + macro signals." 200-line implementation, no GPU, no proprietary library. The Mulvey-lab papers (Shu et al. 2024, three papers) show consistent out-of-sample benefit, but **all three come from the same research group** — defer until either (i) we run our own replication on FRED + market-data, or (ii) an independent group replicates. Tag this for a Phase-2 backtest evaluation.

**(c) Diebold-Yilmaz spillover index as a *cross-asset stress* signal.** Compute it on an 8–12 asset universe (SPX, EFA, EEM, AGG, HYG, GLD, TLT, USD index, oil) using daily returns and a rolling-window VAR. Total spillover index spikes precede or coincide with all major regime breaks. Adds a single numeric feature to S0 with strong empirical pedigree. Use the bootstrap-significance test from Greenwood-Nimmo et al. 2024 to convert the index level into a p-value of "connectedness has shifted."

**(d) Forbes-Rigobon adjustment for any correlation-based signal we add.** Whenever we use rolling correlations (e.g. stock-bond regime, cross-asset correlation breakdown), apply the volatility-conditional correction. Otherwise we will mistake vol amplification for regime change. This is one line of math, not a model.

**(e) MST/PMFG topology metrics as cross-asset confirmation only, not as a primary signal.** Compute on a 20–30 ETF / sector universe. Track avg path length and centrality; these spike during crises. Useful as a *confirming* feature — will not be load-bearing on its own.

### Research-only at our scale (skip)

**(a) Deep-learning regime classifiers (LSTM, Transformer, SPDNet, CRBM, ORCA, CRISP).** Three-fold problem: (i) GPU/data infrastructure cost, (ii) the Krauss/Fischer (EJOR 2017/2018) replication lesson — deep-learning equity-direction alpha was arbitraged away post-2010 — gives strong prior that single-paper reported edges will not survive out-of-sample, (iii) opacity makes failure mode debugging hopeless. The Orton & Gebbie 2024 paper itself warns of overfitting in this exact class of methods. **Skip.**

**(b) Path-signature / MMD-based detection (Issa-Horvath).** Conceptually elegant; computationally expensive on long histories; tuning the kernel for finance is open research. Read for the idea, do not implement.

**(c) MBOC (Markovian BOCPD with score-driven within-regime params).** Single research group, complex implementation. Defer to v1.0+ if standard BOCPD proves insufficient.

**(d) Conditional Restricted Boltzmann Machines, SPDNet, generative-model regime detection.** Single-paper results, opaque, GPU-bound. Skip.

### Composes with our existing S0 dimensions

Our S0 covers D1 (econ-cycle), D2 (credit-stress), D3 (vol regime), D4 (dollar regime), D5 (Bridgewater 4-box). The frontier methods compose as follows:

- **BOCPD layer over each S0 dimension** — extracts regime-shift probabilities from the *existing* signal series. No new data needed; pure post-processing. **Highest-leverage upgrade.**
- **Diebold-Yilmaz total spillover index** — a *new* feature spanning all five dimensions; uses inputs we already have (cross-asset returns + vols).
- **Statistical jump model** — replaces the rule-based labels in D5 (4-box) with data-driven persistent labels. Same input universe, better persistence, more honest regime boundaries.

---

## Section D — Specific findings

### Hamilton MS-VAR vs HMM vs deep learning — practical comparison

| Dimension | Hamilton/MS-VAR | Standard HMM | Statistical jump model | Deep learning (LSTM/Transformer/SPDNet) |
|---|---|---|---|---|
| Implementation cost | ~1 day, `statsmodels` | ~1 day, `hmmlearn` | ~2–3 days, custom | weeks-months + GPU |
| State persistence | OK | Chronic over-segmentation (Pohle et al. 2017) | Strong (jump penalty) | Variable; opaque |
| State-count selection | AIC/BIC (mediocre); CV preferred | AIC/BIC unreliable; CV preferred | Hyperparameter, but fewer pathological behaviors | Architecture-dependent |
| Out-of-sample replication | Yes, decades | Yes | Single research group (Mulvey lab) | **Mostly fails** post-2010 (Krauss/Fischer EJOR replication) |
| Interpretability | High (state means/vols are economic quantities) | Medium | Medium | Low |
| Verdict for our system | Use as baseline (D5 currently does the rule-based version) | Don't use without persistence prior | Plan a Phase-2 backtest replication | Skip |

**Bottom line:** at our scale, the dominant strategy is "well-implemented Hamilton/MS or jump model + BOCPD overlay," not deep learning. The Krauss/Fischer story — Sharpe 5.8 pre-cost in 1992–2009 going to ~0 post-cost post-2010 — is the load-bearing cautionary tale. A small operator does not have a comparative advantage in deep learning; we have a comparative advantage in carefully chosen, stable, interpretable signals.

### Network / graph methods — useful or theoretical?

**Mostly theoretical, with two exceptions.**

Useful and implementable:
- **Diebold-Yilmaz spillover index** — well-defined, replicable, free. Should be added to S0 as a single cross-asset stress feature.
- **MST/PMFG topology metrics** — easy to compute; useful as *confirming* features (when the network restructures, regime is shifting).

Theoretical / not implementable at our scale:
- SPDNet / Riemannian deep learning — author's own caveat about overfitting argues against
- Graph neural networks for crisis detection (CRISP, ORCA) — heavy training, single-paper, GPU-bound
- Granger-causality networks with directed regime change — direction-of-causality estimation is fragile in finance; not enough out-of-sample evidence to deploy

**Recommendation:** add Diebold-Yilmaz as a feature; keep MST/PMFG in our back pocket as a Phase-2 confirming signal; skip the rest.

### Change-point detection — is BOCPD a practical addition to S0?

**Yes — strongest recommendation in this entire survey.** Specifically:

- BOCPD is the most pragmatically valuable post-2007 regime-detection method for an operator at our scale
- Adams-MacKay 2007 is a foundational, heavily-replicated method (not single-paper)
- Free open-source implementations exist
- Output is naturally probabilistic (posterior over run-length) — directly consumable by sizing logic
- Online / streaming — fits the daily S0 refresh cadence
- Single tuning knob (hazard rate λ); tunable on 1990–2015 history, locked thereafter
- Known limitation: Gaussian observation model under-fits fat tails. Two responses: (i) use Student-t observation likelihood (10-line code change), (ii) complement with FOCuS-CUSUM as a robustness cross-check

Run BOCPD against a small set of canonical S0 series (proposed: VIX/VIX3M ratio, HY-OAS, MOVE, stock-bond 60d rolling correlation, EBP) and surface the per-day posterior probability of a regime-shift-in-the-last-N-days as a new column in the sidecar. Total implementation cost: 1–2 days, $0 marginal.

### NEW regime dimensions surfaced by recent methods

The frontier has surfaced **four candidate regime dimensions that are not currently in S0** and merit consideration for a v0.5+ extension:

**1. Stock-bond correlation regime (high-conviction add).** Persistently positive since 2022 — first sustained sign-flip since the late 1990s. Driven by inflation regime. Consequences: (a) 60/40 portfolio properties have changed, (b) traditional flight-to-quality regime markers are dampened, (c) inflation-vs-growth shock decomposition matters more than recession-vs-expansion. **Implementation:** rolling 60d correlation of SPY vs TLT (or AGG); threshold-based regime label. Free, trivial, uses data we already have. This is the single most important missing feature in our current S0.

**2. Factor crowding regime (medium-conviction add).** Hua & Sun (2024 SSRN) and Zlotnikov et al. (2023 arxiv) frame factor crowding as a regime dimension distinct from cycle / vol / credit / dollar / 4-box. The signal: when factor exposures are crowded, factor-strategy returns decay rapidly; when uncrowded, returns persist. Practical implementation requires 13F data ingestion (not currently in our MCP stack). **Build cost moderate** (Form 13F XML parser + holdings dedup). High-payoff if we ever run factor-tilted exposures. Defer until factor exposure becomes a meaningful part of the strategy — but flag for future S0 extension.

**3. Term-structure-of-vol breakdown regime (already partly in S0; deepen).** D3 already has VIX/VIX3M ratio. Frontier work (MOVE term structure, VVIX/VIX, OVX-vs-VIX) suggests *cross-asset vol-term-structure inversions* are an under-used regime feature. Specifically, simultaneous inversion in VIX-curve AND MOVE-curve is a rarer, higher-conviction regime flag than either alone. **Implementation:** add MOVE term-structure inversion derivable from existing Cboe / yfinance data. Trivial.

**4. Cross-asset connectedness regime (Diebold-Yilmaz; medium-conviction add).** The total spillover index is itself a regime-state variable — high-connectedness regimes vs low-connectedness regimes have different return / vol / correlation properties. Adding the DY total index as a single S0 feature captures information that none of D1-D5 individually does. **Implementation cost:** moderate — needs a daily rolling-VAR routine. Returnable in 1 week of build time.

**Tier-2 candidates (not yet ready):**
- *Liquidity regime* (dealer-balance-sheet-driven) — frontier literature exists but free public proxies are weak; defer
- *Order-flow regime* (Tsaknaki-Lillo-Mazzarisi MBOC) — single research group, requires high-frequency data we don't have; defer
- *Smart-money-flow regime* — D3/L7 already touches this; the literature is mostly practitioner-grade not academic-frontier

---

## Anti-hallucination audit (what was *not* verifiable from primary sources)

Disclosed for transparency:

- **arxiv 2307.02375 PDF**: PDF rendering failed; relied on the HTML version of the paper (`arxiv.org/html/2307.02375v2`) which extracted cleanly. Author identification (Tsaknaki / Lillo / Mazzarisi) and MBOC algorithm description came from the HTML render, cross-checked against SSRN listing.
- **arxiv 2211.04184 (Diebold-Yilmaz 2022)**: only the abstract was directly extractable; the substantive survey content is paraphrased from the abstract + secondary sources (`financialconnectedness.org/research.html` and the published *Journal of Econometrics* listing). Marked T4 (survey) for that reason.
- **Krauss/Fischer EJOR replication-failure framing**: the "alpha arbitraged away post-2010" claim is from the EJOR 2018 abstract via SSRN/IDEAS, which I treat as primary because it is the authors' own statement.
- **arxiv 2604.17251 (ORCA) and arxiv 2510.20868 (CRISP)** carry future / very-recent dates relative to the survey's primary research window. Treated as T3 frontier-direction signals only; recommendations would not change if these papers were excluded.
- **HSBC / BlackRock institutional regime work** — referenced via firm whitepapers, not arxiv. Not load-bearing in any recommendation.

No claim in Section C or Section D depends on a single unreplicated paper.
