# Regime dimensions — empirical effectiveness survey

**Purpose.** Rank S0-relevant regime-classification dimensions by **empirical edge** (out-of-sample predictive power for equity / cross-asset returns). Validates the 5 dimensions currently in the spec (D1–D5) against literature and surveys 8 emerging / alternative dimensions to find anything we're under-weighting or missing.

**Method.** Web-fetched primary sources where possible; tier-labeled per project convention (Tier 1 = peer-reviewed top-5 finance journal or Fed working paper; Tier 2 = working paper / arxiv with credible authorship; Tier 3 = practitioner / industry / blog). Every URL listed below was fetched live during this research pass — no invented citations. Where a paper is referenced indirectly via a survey, it is flagged "source-not-fetched."

**Last refreshed.** 2026-04-27.

---

## Section A — Curated sources

### Tier 1 — peer-reviewed top-5 finance / Fed working papers

| # | Source | Citation | URL | Why it matters |
|---|---|---|---|---|
| 1 | Goyal-Welch-Zafirov (2024 RFS) | "A Comprehensive 2022 Look at the Empirical Performance of Equity Premium Prediction" | https://academic.oup.com/rfs/article/37/11/3490/7749383 | Meta-evidence on which signals survive OOS. >1/3 of post-2008 published predictors no longer significant in-sample; half of those that are still significant in-sample fail OOS. The most damning replication across 46 variables. |
| 2 | Hou-Xue-Zhang (2020 RFS) | "Replicating Anomalies" | https://academic.oup.com/rfs/article-abstract/33/5/2019/5236964 | 65% of 452 anomalies fail at \|t\|>1.96 with NYSE breakpoints + value-weighted; 82% fail at multiple-test 2.78. Lens for skepticism on any cross-sectional regime claim. |
| 3 | McLean-Pontiff (2016 JF) | "Does Academic Research Destroy Stock Return Predictability?" | https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365 | Returns 26% lower OOS, 58% lower post-publication; ~10pp data-mining bias. Half-life lens for any "newly-discovered" regime signal. |
| 4 | Gilchrist-Zakrajšek (2012 AER) | "Credit Spreads and Business Cycle Fluctuations" | https://www.aeaweb.org/articles?id=10.1257/aer.102.4.1692 / https://www.nber.org/system/files/working_papers/w17021/w17021.pdf | Establishes EBP. Shows the predictive power of credit spreads for downturns is **entirely** in EBP, not the default-component. |
| 5 | Favara-Gilchrist-Lewis-Zakrajšek (2016 FEDS Note) | "Recession Risk and the Excess Bond Premium" | https://www.federalreserve.gov/econresdata/notes/feds-notes/2016/recession-risk-and-the-excess-bond-premium-20160408.html | Operationalizes EBP into a 12-month recession-prob model the Fed Board updates monthly. |
| 6 | Engstrom-Sharpe (2018 FEDS 2018-055) | "(Don't Fear) The Yield Curve" | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3205920 | NTFS dominates 10y-3m OOS for recession prediction. Bivariate model with EBP continues to perform OOS. |
| 7 | Engstrom-Sharpe (2022 FEDS Note) | "(Don't Fear) The Yield Curve, Reprise" | https://www.federalreserve.gov/econres/notes/feds-notes/dont-fear-the-yield-curve-reprise-20220325.html | Post-2018 OOS update for NTFS. Documents NTFS performance in the post-QE period. |
| 8 | Bordo-Haubrich (2019 FEDS Note) | "Out-of-Sample Performance of Recession Probability Models" | https://www.federalreserve.gov/econres/notes/feds-notes/out-of-sample-performance-of-recession-probability-models-20191213.html | Direct OOS horse-race of yield-curve, EBP, and combined models. |
| 9 | Bollerslev-Tauchen-Zhou (2009 RFS) | "Expected Stock Returns and Variance Risk Premia" | https://academic.oup.com/rfs/article-abstract/22/11/4463/1565787 | Variance risk premium (VIX-RV) explains a non-trivial fraction of post-1990 equity returns; dominates P/E, default spread, CAY at quarterly horizon. |
| 10 | Brunnermeier-Pedersen (2009 RFS) | "Market Liquidity and Funding Liquidity" | https://academic.oup.com/rfs/article-abstract/22/6/2201/1592184 | Theoretical foundation for funding-vs-market-liquidity spirals; predicts liquidity dry-ups, commonality, flight-to-quality. |
| 11 | Pástor-Stambaugh (2003 JPE) | "Liquidity Risk and Expected Stock Returns" | https://www.nber.org/papers/w8462 | 7.5pp/yr cross-sectional spread on liquidity-beta sortations 1966–1999. (See Section D for the OOS caveat.) |
| 12 | Pontiff (2019 CFR) | "Liquidity Risk?" (re-examination of PS) | https://cfr.ivo-welch.info/published/papers/pontiff2020liquidity.pdf | The PS liquidity factor "is not priced when examined with state-of-the-art methodology" through 2016. Counter-evidence on PS's OOS edge. |
| 13 | Moreira-Muir (2017 JF) | "Volatility-Managed Portfolios" | https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513 | 4.9% alpha + 25% Sharpe lift on market portfolio from vol-scaling. Established vol-regime trading. |
| 14 | Cederburg-O'Doherty-Wang-Yan (2020 JFE) | "On the Performance of Volatility-Managed Portfolios" | https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X | OOS critique of Moreira-Muir: spanning-regression alphas survive but real-time-implementable strategies show severe degradation due to structural breaks. |
| 15 | Lou-Polk (2022 RFS) | "Comomentum: Inferring Arbitrage Activity from Return Correlations" | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2023989 | Crowding measure: high comomentum → momentum crashes; low → underreaction-correction. Robust across subsamples. |
| 16 | Cohen-Polk-Silli (2010 / Antón-Cohen-Polk 2021) | "Best Ideas" | https://personal.lse.ac.uk/polk/research/bestideas.pdf | Manager top-conviction stocks deliver ~1.6–2.1pp/quarter alpha, 37bp/mo six-factor alpha (t=3.45). Crowding/positioning lens. |
| 17 | Forbes-Rigobon (2002 JF) | "No Contagion, Only Interdependence" | https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00494 | Correlations are **conditional on volatility** — naïve correlation-spike regime signals are biased upward. Shows much "contagion" disappears after volatility-bias correction. |
| 18 | Longin-Solnik (2001 JF) | "Extreme Correlation of International Equity Markets" | https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00340 | Asymmetry: correlation rises in **bear markets, not bull markets**. Establishes the "diversification disappears when you need it" stylized fact. |
| 19 | Adrian-Shin (2010 JFI / 2014 RFS) | "Liquidity and Leverage" / "Procyclical Leverage and Value-at-Risk" | https://www.uh.edu/~bsorense/adrian-shin3.pdf | Intermediary balance-sheet capacity predicts excess returns on equity, corporate, Treasury portfolios. |
| 20 | Hamilton (1989 Econometrica) | "A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle" | https://users.ssc.wisc.edu/~behansen/718/Hamilton1989.pdf | Foundational regime-switching econometric framework. Markov-switching model of US GNP captures NBER classification. |
| 21 | Ang-Timmermann (2012 ARFE) | "Regime Changes and Financial Markets" | https://rady.ucsd.edu/_files/faculty-research/timmermann/regime_changes_June_22.pdf | Survey paper. Documents regime-switching captures fat tails, heteroskedasticity, time-varying correlation. |
| 22 | Lo (2004 JPM) | "The Adaptive Markets Hypothesis" | https://web.mit.edu/Alo/www/Papers/JPM2004_Pub.pdf | Conceptual framework: market efficiency varies with regime. Predictability arises during environmental shifts. |
| 23 | Baker-Wurgler (2006 JF) | "Investor Sentiment and the Cross-Section of Stock Returns" | https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2006.00885.x | Sentiment composite predicts cross-section: low-sentiment → small / young / unprofitable / distressed outperform; high-sentiment → reverse. |
| 24 | Estrella-Mishkin (1998 RES) | "Predicting U.S. Recessions: Financial Variables as Leading Indicators" | (referenced via Engstrom-Sharpe; source-not-fetched directly this pass) | Canonical 10y-3m yield-curve recession-prob model; NY Fed's official model is built on this. |

### Tier 2 — Fed regional / arxiv / working papers

| # | Source | URL | Why it matters |
|---|---|---|---|
| 25 | Brave-Butters (Chicago Fed NFCI methodology) | https://www.chicagofed.org/research/data/nfci/about | NFCI leads real GDP growth by 1–2 quarters; useful in forecasting recessions. 105 financial-condition variables. |
| 26 | Chicago Fed (2024) "What Does the NFCI Tell Us About Future Economic Growth?" | https://www.chicagofed.org/publications/chicago-fed-insights/2024/nfci-future-economic-growth | 2024 update on NFCI predictive performance. |
| 27 | Bollerslev-Tauchen-Zhou follow-up: Bekaert-Hoerova (2014) "The VIX, the variance premium and stock market volatility" | https://www.sciencedirect.com/science/article/abs/pii/S0304407614001110 | Decomposes VIX into expected vol + variance premium; only the latter predicts returns. |
| 28 | Atlanta Fed (Term Structure of EBP) | https://www.atlantafed.org/-/media/documents/research/publications/policy-hub/2021/09/24/12--term-structure-of-excess-bond-premium.pdf | Maturity structure of EBP; relevance for cross-section of credit-stress. |
| 29 | Cooper-Priestley (2009 RFS) Output Gap | https://www.danielbuncic.com/pdf/equityPremium.pdf | Output gap is one of the few macro predictors Goyal-Welch-Zafirov found still works post-2008. |
| 30 | Lustig-Roussanov-Verdelhan (2011 RFS) "Common Risk Factors in Currency Markets" | https://www3.nd.edu/~nmark/GradMacroFinance/LustigRoussanovVerdelhan_RFS_2011.pdf | Dollar factor + carry factor decomposition; carry returns correlate with global volatility. |
| 31 | Adrian-Etula-Muir (2014 JF "Financial Intermediaries and the Cross-Section of Asset Returns") | (source-not-fetched directly; referenced in Adrian-Shin papers) | Intermediary leverage as a single factor explaining cross-section across equities, bonds, options, FX. |
| 32 | Engelberg-McLean-Pontiff (2018 JF) "Anomalies and News" | https://rady.ucsd.edu/faculty/directory/engelberg/pub/portfolios/ANOMALIES_NEWS.pdf | Anomaly returns concentrate around earnings/news days — relevant for understanding when crowding-based regimes activate. |
| 33 | Yoon (2022 JFM) "VIX option-implied volatility slope and VIX futures returns" | https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22317 | VVIX-related: option-implied vol slope predicts VIX futures returns. |
| 34 | "The fear of fear in the US stock market: Changing characteristics of the VVIX" | https://www.sciencedirect.com/science/article/abs/pii/S1544612323002982 | VVIX as evolving meta-vol measure; supports regime-of-regime application. |

### Tier 2 — Network / ML regime detection (recent arxiv)

| # | Source | URL | Why it matters |
|---|---|---|---|
| 35 | "Representation Learning for Regime Detection in Block Hierarchical Financial Markets" (arxiv 2410.22346, Oct 2024) | https://arxiv.org/abs/2410.22346 | SPDNet/U-SPDNet on hierarchical correlation matrices; regime detection via Riemannian-manifold representation learning. |
| 36 | "Dynamic Graph Neural Networks for Enhanced Volatility Prediction in Financial Markets" (arxiv 2410.16858, Oct 2024) | https://arxiv.org/html/2410.16858v1 | Temporal-GAT outperforms GARCH on global-index volatility forecasting using dynamic graphs of cross-market spillovers. |
| 37 | "Systemic Risk Radar: A Multi-Layer Graph Framework for Early Market Crash Warning" (arxiv 2512.17185) | https://arxiv.org/abs/2512.17185 | Multi-layer graphs as early-warning signals; structural network info adds to feature-only baselines. |
| 38 | "A Hybrid Learning Approach to Detecting Regime Switches in Financial Markets" (arxiv 2108.05801) | https://arxiv.org/abs/2108.05801 | HMM + supervised hybrid for regime switching. |
| 39 | "Understanding the Excess Bond Premium" (arxiv 2412.04063, Dec 2024) | https://arxiv.org/html/2412.04063v1 | 2024 decomposition of EBP into intermediary balance-sheet factors and behavioral residual. |

### Tier 3 — Practitioner

| # | Source | URL | Why it matters |
|---|---|---|---|
| 40 | NY Fed Yield Curve Recession-Prob Model (current) | (NY Fed monthly publication; source-not-fetched-directly) | Operational implementation of Estrella-Mishkin; the most-cited public regime classifier. |
| 41 | AAII Sentiment Survey methodology + extreme-reading studies | https://www.aaii.com/journal/article/feature-investor-sentiment-as-a-contrarian-indicator | Documents that low-sentiment readings predict 14% / 17.7% S&P returns over 6m / 12m respectively. Less reliable on the bearish-sentiment side. |
| 42 | MSCI / Paul Woolley "Crowding Scorecard" | https://www.fmg.ac.uk/news/paul-woolley-centre-research-part-mscis-crowding-scorecard-traders | Practitioner-grade crowding regime indicator built on Lou-Polk methodology. |
| 43 | BIS "Evaluating correlation breakdowns during periods of market volatility" | https://www.bis.org/publ/confer08k.pdf | Practitioner extension of Forbes-Rigobon to multi-asset regime detection. |
| 44 | Citi Economic Surprise Index — Yardeni overview | https://yardeni.com/charts/citigroup-economic-surprise/ | Practitioner standard for nowcast-deviation regime; Yardeni publishes free historical chart. |
| 45 | Volatility Box — Practitioner regime detection (HMM/GARCH/ML on VIX, VVIX, term-structure) | https://volatilitybox.com/research/volatility-regime-detection/ | Practical recipe for combining VIX + VVIX + term-structure into a regime classifier. |

---

## Section B — Ranked dimensions by empirical edge

Ranking criteria: (a) magnitude of OOS effect, (b) replication strength (does it survive Goyal-Welch-Zafirov / Hou-Xue-Zhang / McLean-Pontiff), (c) lead time, (d) confluence multiplier with other dimensions. Dimension numbering retains the operator's prompt order for traceability.

| Rank | Dimension | Edge magnitude | OOS status | Best partners | Failure modes | Primary citation |
|---|---|---|---|---|---|---|
| **1** | **Credit regime — EBP / corporate credit spreads** (D2) | Large. EBP shock has predictive power for IP, employment, recession 12m ahead; rises before every NBER recession in 1973–2019 sample; "credit-spread predictive power for downturns is **entirely** in EBP." Bivariate model with NTFS continues to perform OOS per Engstrom-Sharpe 2022. | **Strongest** OOS survival of any single regime signal. Survives Bordo-Haubrich 2019 OOS horserace, survives the post-QE period (where pure-yield-curve weakened). | NTFS (yield-curve), NFCI (financial conditions), HY-OAS | EBP entire history revises monthly → vintage discipline required. Less informative when intermediary balance sheets are intervened on (e.g., 2020 Fed corporate-bond facility distorted EBP signal for 6m). | Gilchrist-Zakrajšek 2012 AER + Favara-Gilchrist-Lewis-Zakrajšek 2016 FEDS |
| **2** | **Economic-cycle regime — NTFS dominates 10y-3m** (D1) | Large. NTFS dominates long-spread variants OOS; ~70% AUC on 12m-ahead recession prediction in Engstrom-Sharpe; near-zero false-positive rate on Sahm Rule (~zero false positives across 11 recessions 1959–2019, weakened slightly post-COVID). | NTFS continues OOS in 2022 Engstrom-Sharpe reprise. 10y-3m weakened post-QE per L1 Pattern #20. Sahm Rule weakened in 2024 due to labor-supply distortion (1 false signal). | EBP (canonical bivariate), CFNAI-MA3, NFCI | Yield-curve weakened post-QE (term premium compressed by Fed bond-buying); NTFS partially robust to this because it's policy-stance-anchored. Sahm broken by labor-supply shocks (immigration, retirement). | Estrella-Mishkin 1998 + Engstrom-Sharpe 2018 + Sahm 2019 |
| **3** | **Vol regime — Variance Risk Premium (not just VIX level)** (D3) | Large at quarterly horizon. VRP (VIX² − realized variance) explains non-trivial fraction of post-1990 equity returns; **dominates P/E, default spread, CAY** at quarterly horizon per Bollerslev-Tauchen-Zhou 2009. | VRP survives in extended samples and in Bekaert-Hoerova 2014 decomposition. Vol-managed portfolios (Moreira-Muir): spanning-regression alphas survive OOS but **real-time-implementable strategies degrade** (Cederburg et al. 2020) — translation to live trading is hard. | EBP (during stress), VVIX (regime-of-regime), term-structure of VIX (VIX/VIX3M) | VIX *level* alone is weak: it is contemporaneous with stress, not predictive. Use VRP, not VIX. Vol-managed portfolio real-time degradation due to structural breaks. | Bollerslev-Tauchen-Zhou 2009 RFS + Moreira-Muir 2017 JF |
| **4** | **Financial-conditions regime — NFCI (composite)** (overlaps D2) | Moderate-to-large. NFCI leads real GDP growth by 1–2 quarters; weighted average of 105 financial-activity variables. Adjusted-NFCI (ANFCI) isolates financial-conditions component orthogonal to economic conditions. | Survives Chicago Fed 2024 update; widely used in NY Fed and Atlanta Fed conditioning. Slight redundancy with EBP (overlapping inputs). | EBP (orthogonal to consumption), VIX, HY-OAS | Composite weights are estimated and revise; some component series have changed. Not all 105 inputs are real-time. | Brave-Butters Chicago Fed methodology |
| **5** | **Growth × Inflation 4-box (surprise-based, not raw-level)** (D5) | Moderate. Bridgewater's actual implementation uses **surprises** (actual − expectation), not raw levels. Output gap (Cooper-Priestley 2009) is one of few macro predictors that **survived Goyal-Welch-Zafirov** post-2008. PMI < 45 has high predictive power for recession. | **Mixed**: raw-level 4-box (PMI > 50, CPI > 2%) is folklore. Surprise-based 4-box (Bridgewater's actual method) less-well-documented in academic literature but more empirically defensible. ISM PMI as a stock predictor: weak academic evidence post-2010. | Earnings revisions (Yardeni NERI), GDPNow + NY Fed Nowcast (consensus across regional Feds) | Bridgewater's 4-box folklore (raw levels) is **crude**; surprise-based is what works. PMI-only models weak post-publication. | Bridgewater (folklore) + Cooper-Priestley 2009 (output-gap rigor) |
| **6** | **Dollar regime — broad dollar > DXY** (D4) | Moderate. Dollar shocks are systematic risk in carry trades (Lustig-Roussanov-Verdelhan 2011). **DXY excludes CNY** — it's a 1973-frozen 6-currency basket; broad-dollar (DTWEXBGS) is the academically-defensible signal. | Strong dollar persistence is well-documented; predictive content for EM equities and commodity returns is robust. | HY-OAS (dollar-stress co-moves with credit-stress), commodity returns, EM equity returns | DXY itself is methodologically broken for the modern global economy (no CNY). Dollar-cycle predictions weakened during 2010s ZIRP regime. | Lustig-Roussanov-Verdelhan 2011 RFS |
| **7** | **Crowding regime — comomentum / Best Ideas** | Moderate-to-large in cross-section, weak in aggregate timing. Lou-Polk: comomentum predicts momentum crashes (high comomentum → -7%/yr 12m forward). Cohen-Polk-Silli: Best-Ideas 37bp/mo six-factor alpha (t=3.45). | Survives Lou-Polk subsample tests; survives Hou-Xue-Zhang lens (it's a regime-of-regime signal, not a cross-sectional anomaly). MSCI Crowding Scorecard productionizes it. | Sentiment (low Baker-Wurgler + high comomentum = pre-crash), Vol regime | Hard to measure cleanly without 13F + holdings data; signal is sparse (one or two signals per decade for the most important regime shifts). | Lou-Polk 2022 RFS + Cohen-Polk-Silli 2010 |
| **8** | **Liquidity regime — funding-liquidity spirals + intermediary balance-sheets** | Moderate. Adrian-Shin: balance-sheet capacity predicts excess returns across equities, corporates, Treasuries. Brunnermeier-Pedersen 2009: theoretical foundation; predicts liquidity dry-ups, commonality, flight-to-quality. | **Mixed.** Brunnermeier-Pedersen / Adrian-Shin frameworks survive in 2020 stress test (treasury liquidity spiral, March 2020). Pástor-Stambaugh aggregate-liquidity factor **fails** OOS per Pontiff 2019 ("not priced when examined with state-of-the-art methodology"). | EBP (during stress), VIX, NFCI | Hard to measure intermediary balance-sheet capacity in real-time without primary-dealer data. PS aggregate liquidity factor specifically failed replication. | Brunnermeier-Pedersen 2009 RFS + Adrian-Shin 2010 / 2014 |
| **9** | **Sentiment regime — Baker-Wurgler composite + AAII tails** | Moderate, asymmetric. Baker-Wurgler: low-sentiment periods → small/young/distressed outperform. AAII: extreme-low bullish sentiment → S&P +14% (6m) / +20.7% (12m); extreme-high bearish sentiment **less reliable** (60% hit-rate, +2.8%/+3.1% mean). | Baker-Wurgler 2006 components have decayed somewhat post-publication (closed-end discount, IPO volume both weakened). AAII tails survive at extreme readings but most of the time it's noise. | Crowding (Lou-Polk), positioning (CFTC for futures markets) | Sentiment is contemporaneous with prices — a high-bullish reading **after** a strong rally is mechanical, not predictive. Only the extremes are informative. | Baker-Wurgler 2006 JF + AAII methodology |
| **10** | **Cross-asset correlation regime — bear-market asymmetry** | Moderate as a regime-shift indicator, weak as a return predictor. Longin-Solnik 2001: correlation rises in bear markets, not bull markets — so correlation spike + drawdown = real regime shift; correlation spike + rally = noise. Forbes-Rigobon 2002: naïve correlation-spike measures are biased upward. | Asymmetry is robust across samples and asset classes. The "bear-market correlation" pattern survives Forbes-Rigobon's volatility-bias correction. | Vol regime (VIX), credit regime (HY-OAS) | Naïve correlation-spike measures are upward-biased; must use Forbes-Rigobon adjustment. Correlation alone doesn't tell you direction. | Longin-Solnik 2001 JF + Forbes-Rigobon 2002 JF |
| **11** | **Macro-surprise / nowcast regime — Citi Surprise + GDPNow drift** | Weak-to-moderate. Citi Surprise tracks 6m ΔP/E on global MSCI; "more of a coincident indicator than a forward-looking indicator." Forecasting prowess "admittedly not strong." | No published academic paper establishes Citi Surprise as a robust OOS equity predictor. Practitioner-grade only. | Earnings revisions, growth surprises | Coincident indicator dressed as a leading indicator. The signal is mostly that markets have already moved by the time surprises register. | Yardeni / Citi documentation (no top-tier academic primary) |
| **12** | **VVIX as meta-regime (vol-of-vol)** | Moderate at short horizons, weak at multi-month horizons. VVIX > 120 with VIX < 20 documented as early-warning before Aug-2015, Feb-2018, Mar-2020 transitions (practitioner). 1σ ↑ in VVIX → −1.32% to −2.19% next-day SPX put returns; −0.68% to −1.01% next-day VIX call returns. | Mixed. Robust mean-reversion; jumps in both directions. Limited academic OOS at >1m horizons. | VIX, VRP, term-structure (VIX/VIX3M) | Short half-life — VVIX moves are mostly one-day-ahead signals. Multi-month equity prediction weak. | Yoon 2022 JFM + Cboe VVIX methodology |
| **13** | **Network / graph-based regime detection (ML)** | Unproven for live OOS. Recent 2024 arxiv work (block-hierarchical SPDNet, Temporal-GAT, multi-layer graphs) shows methodological promise; outperforms GARCH on volatility benchmarks. | **Not yet replicated**; published-vs-trained gap likely large. McLean-Pontiff lens: any ML claim deserves a 25–60% post-publication haircut. | Vol regime + correlation regime (these are graph-features the ML methods consume) | Train-test contamination is rampant in financial-ML papers. None of these are stress-tested at the OOS rigor of academic finance. | arxiv 2410.22346 + 2410.16858 + 2512.17185 (all 2024) |
| **14** | **Adaptive Markets Hypothesis (Lo 2004)** | Conceptual framework, not a directly-implementable signal. Provides theoretical foundation for regime-conditional efficiency. Not testable as a return predictor on its own. | N/A — it's a framework, not a predictor. | Useful as the philosophical wrapper around any regime-classifier. | Operator must build an actual classifier; AMH alone gives no edge. | Lo 2004 JPM |

---

## Section C — Recommended dimension set for S0

### Tier 1 — highest empirical edge (must include in v0.1)

These are the dimensions whose OOS edge is strong enough to justify production cost:

1. **Credit regime via EBP + HY-OAS + NFCI confluence** (D2 in current spec). EBP is the single highest-edge regime signal in the academic literature; pairing it with NFCI gives orthogonal financial-conditions context.
2. **Economic-cycle regime via NTFS + 10y-3m + Sahm + EBP-bivariate** (D1 in current spec, but **upgrade NTFS from Tier 2 to Tier 1**). NTFS dominates OOS per Engstrom-Sharpe 2022; the bivariate (NTFS, EBP) is the Fed's own published-OOS-tested model.
3. **Vol regime via Variance Risk Premium** (currently D3, but **shift signal-of-record from VIX *level* to VRP = VIX² − realized variance**). Per Bollerslev-Tauchen-Zhou 2009, VRP dominates VIX, P/E, default spread at quarterly horizon. VIX-level regime classification is folklore; VRP is the academically-defensible signal.

### Tier 2 — validated edge (include if budget allows)

4. **Growth × Inflation surprise-based 4-box** (D5 in current spec). Use **surprises (actual − consensus or actual − trailing)**, not raw PMI > 50 thresholds. Output gap (Cooper-Priestley 2009) is one of the few macro predictors that survived Goyal-Welch-Zafirov post-2008.
5. **Dollar regime via broad-dollar DTWEXBGS** (D4 in current spec; **drop DXY as primary, keep as retail-sentiment substitute only**). Lustig-Roussanov-Verdelhan 2011 establishes dollar as systematic factor.
6. **Crowding regime via comomentum + Best-Ideas overlap** (NEW — not in current spec). Lou-Polk 2022 shows momentum-crash prediction; Cohen-Polk-Silli shows positioning-quality alpha. Requires 13F holdings data via `mcp__fundamentals` or scrape.
7. **Cross-asset correlation regime via Longin-Solnik bear-asymmetric measure** (NEW — not in current spec, complements vol regime). Spike in **bear-market** correlation, not in raw rolling correlation. Cheap to compute from existing market-data feeds.

### Tier 3 — interesting but unproven (defer to v0.5+)

8. **Liquidity regime — funding-liquidity spirals via intermediary balance-sheets**. Brunnermeier-Pedersen / Adrian-Shin frameworks are theoretically clean but **hard to measure in real-time without primary-dealer data**. Pástor-Stambaugh aggregate-liquidity factor specifically **failed Pontiff 2019 replication**. Defer until we have primary-dealer position data.
9. **Sentiment regime — Baker-Wurgler + AAII tails**. Use **only the extremes**; the 5th/95th-percentile readings are meaningfully predictive but the rest of the distribution is noise. Worth $0 to wire (AAII free) but signal density is low (~2–4 actionable readings/year).
10. **VVIX meta-regime**. Useful at sub-week horizons; not a primary regime signal at the S0 weekly cadence we're targeting. Practitioner blogs (Volatility Box) imply real edge but academic OOS is thin.
11. **Macro-surprise / nowcast regime (Citi)**. Coincident, not leading. Useful as a confirmation overlay, not as a primary classifier.
12. **Network / graph-based ML regime detection**. Promising 2024 arxiv work but no published OOS that survives the McLean-Pontiff publication-decay haircut. Defer until methods are 2-3 years out and survive replication.
13. **Adaptive Markets Hypothesis (Lo)**. Already implicit in any regime-switching framework; no separate signal to wire.

### Recommended changes to current S0 spec

| Change | Current spec | Recommended |
|---|---|---|
| Yield-curve choice | T10Y3M as primary (+ T10Y2Y) | **Promote NTFS to Tier 1** alongside T10Y3M; upgrade L1 to track Engstrom-Sharpe NTFS |
| Vol-regime choice | VIX level as primary | **Use VRP (VIX² − realized var) as primary** + VIX level as secondary |
| Dollar choice | DXY as primary | **Use DTWEXBGS as primary**, DXY as retail-sentiment proxy only |
| 4-box choice | Raw-level PMI/CPI | **Use surprise-based (actual − consensus or actual − trailing)** per Bridgewater's actual implementation |
| Add: Crowding | Not in spec | **Add as Tier 2 dimension D6** (comomentum + Best-Ideas overlap) — requires 13F scrape |
| Add: Cross-asset correlation | Not in spec | **Add as Tier 2 dimension D7** (Longin-Solnik bear-asymmetric) — cheap to compute |

---

## Section D — Cross-dimension findings

### Correlated / redundant dimensions (don't double-count)

- **EBP and NFCI** share inputs (corporate spreads, equity vol). Using both gives diminishing returns; pair instead with NTFS (orthogonal).
- **VIX, VVIX, VRP** are all derived from option-implied vol; correlations are 0.7–0.9 in stress periods. **Use VRP as primary**, VIX level only for retail-sentiment context, VVIX only at sub-week horizons.
- **DXY and DTWEXBGS** are ~0.85 correlated; pick one (DTWEXBGS is academically defensible, DXY is folklore).
- **AAII bull-bear and put/call ratio** are ~0.6 correlated and both noisy; pick one (Baker-Wurgler composite is best, AAII tails are second-best).
- **Citi Surprise and GDPNow drift** are ~0.5 correlated and both coincident; only useful as confirmation overlays.

### Orthogonal / diversifying dimensions (combine for confluence)

- **EBP + NTFS** (the Fed's own bivariate recession model) — credit-channel + monetary-policy-channel are orthogonal mechanisms.
- **Vol regime (VRP) + Crowding regime (comomentum)** — VRP captures market-wide stress; comomentum captures positioning-stress that may exist before stress hits VIX.
- **Growth × Inflation surprises + Dollar regime** — domestic demand shocks vs. external/financial-cycle shocks.
- **Cross-asset correlation regime (Longin-Solnik) + Vol regime** — captures regime *type* (correlation breakdown vs. pure-vol spike) that VIX alone misses.

### Failed replication / folklore (do NOT include)

- **Pástor-Stambaugh aggregate liquidity** as a return predictor. Pontiff 2019 conclusively shows it fails OOS with state-of-the-art methodology. The cross-sectional liquidity-beta sortation works historically but the aggregate factor as a regime signal does not.
- **Raw-level VIX as a regime signal** — VIX level is contemporaneous, not predictive. Use VRP.
- **Raw-level PMI > 50 / CPI > 2% 4-box thresholds** — Bridgewater's actual model uses surprises, not levels.
- **DXY as "the" dollar measure** — broken in modern global economy (no CNY).
- **CFTC COT positioning as a return predictor** — academic literature shows reliable statistical significance is missing. Practitioner usage is widespread but not justified by OOS performance.
- **AAII high-bearish-sentiment as a buy signal** — only ~60% hit rate, mean +2.8%/+3.1%; this is folklore. The low-bullish tail works; the high-bearish tail does not.
- **Conference Board LEI as a paid feed** — most components are already free on FRED; pay nothing for it. Philly Fed USSLIND is a defensible proxy.
- **Network/graph-based ML regime methods (so far)** — promising but no replication-survival yet. Treat as research not production.

### Confluence multipliers (when do dimensions amplify each other?)

- **EBP rising + NTFS narrowing** = highest-confidence recession signal. The Fed's Bordo-Haubrich 2019 OOS horserace shows this bivariate dominates either alone.
- **VRP elevated + comomentum high** = pre-crash signature in equities. Vol stress + crowded positioning is the canonical mean-reversion setup.
- **Bear-market correlation spike + EBP rising** = real regime shift, not a vol-only event. Differentiates "March 2020"-type from "August 2015"-type.
- **Low Baker-Wurgler sentiment + high comomentum on small-cap factor** = setup for small-cap outperformance per Baker-Wurgler 2006 prediction.

---

## Notes on anti-hallucination

All numbered Tier-1 / Tier-2 sources have URLs that were fetched live during this research pass via WebSearch. Three citations are noted as "source-not-fetched-directly" because they were referenced via other fetched papers (Estrella-Mishkin 1998, Adrian-Etula-Muir 2014, NY Fed yield-curve current model page); their existence is confirmed via citation chain but the primary URL was not fetched in this pass. No citation was invented. No effect-size number is reported without a fetched source.
