# L1 — Regime capture from cross-asset signals

Empirical knowledge library for identifying regime via rates, credit, FX, commodities, and equity-vol signals. Focus is on practitioner-relevant lead-lag relationships validated across 50+ years of data.

---

## Section A — Curated sources

1. [Estrella & Mishkin — The Yield Curve as a Predictor of U.S. Recessions (NY Fed, 1996)](https://www.newyorkfed.org/research/current_issues/ci2-7.html) — Foundational paper establishing 10y-3m spread as recession leading indicator with calibrated probability mapping. [Tier 1]
2. [Bauer & Mertens — Information in the Yield Curve about Future Recessions (FRBSF Econ Letter, 2018)](https://www.frbsf.org/research-and-insights/publications/economic-letter/2018/08/information-in-yield-curve-about-future-recessions/) — Updated empirical case that 10y-3m spread is the most reliable inversion measure; AUC ~0.85-0.89. [Tier 1]
3. [Engstrom & Sharpe — The Near-Term Forward Yield Spread as a Leading Indicator (FEDS, 2018)](https://www.federalreserve.gov/econres/feds/files/2018055pap.pdf) — Argues 6-quarter-forward minus 3m bill (NTFS) dominates 10-2 spread for predicting recessions and equity returns. [Tier 1]
4. [Engstrom & Sharpe — (Don't Fear) The Yield Curve, Reprise (FEDS Notes, 2022)](https://www.federalreserve.gov/econres/notes/feds-notes/dont-fear-the-yield-curve-reprise-20220325.html) — Direct comparison of NTFS vs 2-10 in real time during the 2022 inversion debate. [Tier 1]
5. [Gilchrist & Zakrajšek — Credit Spreads and Business Cycle Fluctuations (AER, 2012)](https://www.aeaweb.org/articles?id=10.1257/aer.102.4.1692) — Constructs the GZ spread and decomposes into expected default + excess bond premium (EBP); EBP carries virtually all forecasting power. [Tier 1]
6. [Favara, Gilchrist, Lewis & Zakrajšek — Recession Risk and the Excess Bond Premium (FEDS Notes, 2016)](https://www.federalreserve.gov/econresdata/notes/feds-notes/2016/recession-risk-and-the-excess-bond-premium-20160408.html) — Real-time application: 50bp EBP rise → ~15pp recession-probability rise over 12 months. [Tier 1]
7. [Cochrane & Piazzesi — Bond Risk Premia (AER, 2005)](https://www.aeaweb.org/articles?id=10.1257%2F0002828053828581) — Tent-shaped factor in forward rates predicts bond excess returns with R² up to 0.44; factor is countercyclical and forecasts equity returns. [Tier 1]
8. [Cieslak & Povala — Expected Returns in Treasury Bonds (RFS, 2015)](https://academic.oup.com/rfs/article-abstract/28/10/2859/1580557) — Decomposition of yields into inflation expectations + cycle factor; cycle factor proxies time-varying risk premium and links to macro regimes. [Tier 1]
9. [Adrian, Crump & Moench — Treasury Term Premia (NY Fed)](https://www.newyorkfed.org/research/data_indicators/term-premia-tabs) — ACM term-premium model; term premium is countercyclical and rises with uncertainty. [Tier 1]
10. [Goyal, Welch & Zafirov — Comprehensive 2022 Look at Empirical Performance of Equity Premium Prediction (RFS, 2024)](https://academic.oup.com/rfs/article/37/11/3490/7749383) — Crucial out-of-sample audit: most predictors fail to beat historical mean OOS; flags spurious vs robust signals. [Tier 1]
11. [Asness, Moskowitz & Pedersen — Value and Momentum Everywhere (JF, 2013)](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12021) — Cross-asset commonality: value/momentum factors share global common factor structure linked to funding-liquidity risk. [Tier 1]
12. [Asness, Frazzini & Pedersen — Quality Minus Junk (RAS, 2019)](https://www.aqr.com/Insights/Research/Working-Paper/Quality-Minus-Junk) — QMJ outperforms during market downturns; price of quality is a regime indicator. [Tier 1]
13. [Brunnermeier & Pedersen — Market Liquidity and Funding Liquidity (RFS, 2009)](https://academic.oup.com/rfs/article-abstract/22/6/2201/1592184) — Theory of liquidity spirals and flight-to-quality; basis for understanding cross-asset stress transmission. [Tier 1]
14. [Pástor & Stambaugh — Liquidity Risk and Expected Stock Returns (JPE, 2003)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=279804) — Aggregate liquidity is a priced state variable; sharp drops align with crisis regimes (2008). [Tier 1]
15. [Hamilton — A New Approach to the Economic Analysis of Nonstationary Time Series (Econometrica, 1989)](https://users.ssc.wisc.edu/~behansen/718/Hamilton1989.pdf) — Foundational Markov regime-switching model used widely in regime detection. [Tier 1]
16. [Schwert — Why Does Stock Market Volatility Change Over Time? (JF, 1989)](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1989.tb02647.x) — 1857-1987 dataset establishing volatility countercyclicality; vol rises in recessions and after price falls. [Tier 1]
17. [Brunnermeier, Nagel & Pedersen — Carry Trades and Currency Crashes (NBER Macro Annual, 2008)](https://www.nber.org/system/files/chapters/c7286/c7286.pdf) — VIX spikes coincide with carry-trade unwinds and FX risk-off; quantifies daily P&L impact when correlation regimes shift. [Tier 1]
18. [Lo — The Adaptive Markets Hypothesis (JPM, 2004)](https://web.mit.edu/Alo/www/Papers/JPM2004_Pub.pdf) — Theoretical framework for why risk-reward relationships shift across regimes; relevant for signal-decay arguments. [Tier 1]
19. [Marks — Mastering the Market Cycle (Howard Marks, 2018)](https://www.amazon.com/Mastering-Market-Cycle-Getting-Odds/dp/1328479250) — Practitioner case: credit cycle as the most volatile cycle; sentiment-extreme markers used at Oaktree's five major turning points. [Tier 1]
20. [Adrian & Shin — Liquidity and Leverage / Procyclical Leverage (NY Fed Staff Reports)](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr690.pdf) — Documents broker-dealer leverage as procyclical; financial-conditions tightening transmits to risk assets. [Tier 1]
21. [Parnes — Copper-to-gold ratio as a leading indicator for the 10-Year Treasury yield (NA J Econ Fin, 2024)](https://www.sciencedirect.com/science/article/abs/pii/S1062940823001390) — Empirical study: ratio leads 10y yield by a few days; correlation ~0.85; signal degrades around macro shocks. [Tier 1]
22. [Federal Reserve Bank of Chicago — National Financial Conditions Index documentation](https://www.chicagofed.org/research/data/nfci/about) — 105-component weekly index of risk/credit/leverage; leads economic activity by 1-2 months. [Tier 1]
23. [Bridgewater — The All Weather Story](https://www.bridgewater.com/research-and-insights/the-all-weather-story) — Practitioner framework mapping growth × inflation regimes to asset behaviors; basis for risk-parity. [Tier 1]
24. [Cboe — Inside Volatility Trading: Is VIX Backwardation Necessarily a Sign of a Future Down Market?](https://www.cboe.com/insights/posts/inside-volatility-trading-is-vix-backwardation-necessarily-a-sign-of-a-future-down-market/) — Practitioner counter-evidence: backwardation not a reliable forward-return predictor outside outright crises. [Tier 2]
25. [Wellington Management — Equity volatility and credit spreads](https://www.wellington.com/en/insights/equity-volatility-credit-spreads-harmony) — Practitioner discussion of Merton-model linkage; documents 2020-22 divergence and 2022+ reconvergence. [Tier 2]
26. [Real Investment Advice — Credit Spreads: The Markets Early Warning Indicators](https://realinvestmentadvice.com/resources/blog/credit-spreads-the-markets-early-warning-indicators/) — Practitioner aggregation: 300bp HY-spread widening from recent low as actionable warning threshold. [Tier 2]
27. [San Francisco Fed — Sahm Rule Recession Indicator (FRED documentation)](https://fred.stlouisfed.org/series/SAHMREALTIME) — Specification: 3m-MA unemployment ≥0.5pp above prior-12m low triggers signal; one false positive since 1959. [Tier 1]
28. [Conference Board — US Leading Economic Indicators](https://www.conference-board.org/topics/us-leading-indicators/) — Composite index leading turning points by ~7 months; 3Ds rule (six-month diffusion ≤50 + −4.3% growth-rate threshold). [Tier 2]
29. [Pring Turner Capital — Oil Shocks & Recessionary Outcomes (Advisor Perspectives)](https://realinvestmentadvice.com/resources/blog/oil-shocks-recessionary-outcomes/) — Late-cycle oil signal: rate-of-change >+75% closely precedes recession onset. [Tier 2]
30. [BIS Bulletin No. 90 — Market Turbulence and Carry Trade Unwind of August 2024](https://www.bis.org/publ/bisbull90.pdf) — Real-world case study of cross-asset transmission speed when funding-liquidity flips. [Tier 1]
31. [Federal Reserve — Financial Stability Monitoring (Adrian, Covitz, Liang)](https://www.federalreserve.gov/pubs/feds/2013/201321/index.html) — Framework for ex-ante vulnerability monitoring across pricing-of-risk / leverage / maturity / interconnectedness. [Tier 1]
32. [NY Fed — The Yield Curve as a Leading Indicator: FAQ](https://www.newyorkfed.org/research/capital_markets/ycfaq) — Maintained reference summarizing the operational use of the 10y-3m model. [Tier 1]

---

## Section B — Distilled patterns

1. **The 10y-3m Treasury spread has preceded every U.S. recession since 1960 with no false positives in that window.** Average lead is ~12 months, but the empirical range is 6-24 months across cycles, and equities often continued rising 12-18 months after initial inversion (sources: [1], [2], [32]).

2. **Estrella-Mishkin probability calibration is the practitioner-grade mapping.** Spread > +1.2pp ≈ <5% recession probability over next 12m; spread = 0 ≈ 25%; spread = -0.8pp ≈ 50%. Useful as a real-time scorecard rather than a binary flag (source: [1]).

3. **The near-term forward spread (NTFS = 6q-fwd minus 3m bill) dominates the 2-10 spread for forecasting both recession and 4-quarter equity returns.** When the two diverge — as in 2022 (2-10 inverted while NTFS did not) — NTFS gives the cleaner signal because it directly impounds expected Fed policy 12-18 months out (sources: [3], [4]).

4. **All recessionary forecasting power of credit spreads loads on the excess bond premium (EBP), not the default-risk component.** A 50bp rise in EBP → ~15pp rise in 12-month recession probability. The default-component contribution is statistically indistinguishable from zero (sources: [5], [6]).

5. **Credit spreads typically widen 2-8 weeks before equity peaks in an acute episode, and 3-9 months before recessions in a slower-moving cycle.** HY OAS broke 500bp in Sept-Nov 2007 (S&P peaked Oct 2007), and again in late Feb 2020 just ahead of the March SPX low. A widening of HY-OAS by ~300bp from recent low is the practitioner trigger (sources: [5], [6], [26]).

6. **EBP false positives are rare but real.** The most-cited is 2002 (Enron/WorldCom accounting scandals lifted credit spreads without producing a recession). This argues for using EBP alongside — not instead of — yield-curve signals (source: [6]).

7. **VIX is a coincident, not leading, indicator of equity drawdowns.** VIX peaked in late 2008 while SPX bottomed March 2009. VIX is best read as a regime *state* variable, not a turning-point predictor (source: VIX-SPX divergence research consensus + [24]).

8. **VIX term-structure backwardation is a regime *confirmation*, not a forward-return signal.** Backwardation has accompanied every SPX drawdown ≥10% since 2008, but unconditional forward returns following backwardation are not negative — many of the best forward returns occurred immediately *after* peak backwardation. Combining VIX level with curve slope reduces false-positive flags vs level alone (source: [24]).

9. **Bond volatility (MOVE) tends to lead equity volatility (VIX) in macro-driven regime shifts.** Bond markets price macro/policy risk earlier; cross-asset vol co-movement (VIX-MOVE) is itself a tradable signal for monthly bond and equity returns (per the volatility co-movement literature surfaced in research; primary published support: [13] on the funding-liquidity transmission mechanism that drives this lead).

10. **Term premium (ACM model) is countercyclical: it rises during stress / disagreement and compresses during calm.** This makes the term premium a regime-context variable, not a turning-point forecaster — useful for sizing rather than timing (source: [9]).

11. **The Cochrane-Piazzesi factor (tent-shaped combination of forward rates) forecasts bond excess returns with R² up to 0.44 and is countercyclical.** It also forecasts equity returns and long-run output, embedding it in the broader regime-signal stack (source: [7]).

12. **Cieslak-Povala cycle factor — yield variation orthogonal to expected inflation — outperforms forward-rate-only models for bond risk premia.** The decomposition formalizes that "rates regime" and "inflation regime" are separable signals (source: [8]).

13. **The copper-to-gold ratio leads the 10y Treasury yield by a few days at correlation ~0.85, but the relationship breaks around major macro shocks.** Use as a directional confirmation, not a primary signal. The signal degraded post-2020 with extraordinary monetary policy (source: [21]).

14. **The Sahm Rule (3m-MA unemployment ≥0.5pp above prior-12m low) has triggered in every U.S. recession since 1950 with one ambiguous false positive (1959).** Lead is typically zero — it identifies recessions ~3 months *into* them. Coincident, not leading, but more timely than NBER dating. Susceptible to supply-side false positives (source: [27]).

15. **The Conference Board LEI leads turning points by ~7 months on average, but is prone to recent false-positive episodes (2022-23).** The 3Ds rule (six-month diffusion ≤50 + ≤−4.3% six-month growth rate annualized) is the standard recession trigger (source: [28]).

16. **Chicago Fed NFCI leads economic activity by 1-2 months and is a 105-component weekly real-time read on financial-conditions tightness.** Positive readings = tighter than average; the index leads many narrower FCIs because it spans risk/credit/leverage simultaneously (source: [22]).

17. **Cross-asset value and momentum strategies share a global common factor structure tied to funding-liquidity risk.** Implication: when funding stress shows up (rising EBP, widening swap spreads, VIX/MOVE jointly elevated), expect simultaneous drawdowns in cross-asset carry, momentum, and risk-parity portfolios — i.e. classic risk-off (sources: [11], [13], [17]).

18. **VIX-driven carry-trade unwinds: a one-standard-deviation rise in VIX (when FX correlations also flip from low to high regime) corresponds to a measured ~34bp/day carry-trade drawdown.** Carry P&L is a high-frequency regime indicator for global risk appetite (source: [17]).

19. **Equity volatility and credit spreads are tied via Merton-style mechanics, but the link broke 2020-2022 (Fed liquidity compressed credit spreads disproportionately) and reconverged from 2022 onward.** Divergences between the two are themselves regime markers — when they decouple, look for non-fundamental drivers (Fed flow, regulatory, technical) (source: [25]).

20. **Most "predictors" in the equity-premium literature fail out-of-sample.** Goyal-Welch (and Goyal-Welch-Zafirov 2024) document that of 29 post-2008 candidate predictors plus the original 17, more than a third lose in-sample significance and half of the rest fail OOS. Yield-curve and credit-spread signals survive this test better than valuation-based predictors. Default treatment for any new "regime signal": demand OOS evidence and survival across multiple cycles (source: [10]).

21. **Dollar (DXY) is a regime *filter*, not a turning-point signal for U.S. equities.** Cleaner read: DXY relative to 200d MA. DXY-up regime → growth-leadership and EM headwinds; DXY-down regime → value leadership and EM/commodity tailwind. Dollar–S&P contemporaneous correlation is unstable (sign-flips across cycles) (source: practitioner consensus surfaced via DXY research review).

22. **Oil rate-of-change >+75% YoY has historically clustered close to recession onset (late-cycle indicator), but oil signals can lead, coincide, or lag equity peaks across cycles.** S&P 500 has typically peaked ~5 months before recessions while the GSCI has topped ~2 months *after* recession start, so commodities are not a reliable equity-peak leading indicator (source: [29]).

---

## Section C — Open questions / disagreements

1. **2-10 vs near-term-forward spread.** Engstrom & Sharpe argue NTFS dominates 2-10 ([3], [4]). Bauer & Mertens argue the choice of spread doesn't matter much — all yield-curve measures perform similarly ([2]). The 2022 episode was a real-world test (2-10 inverted, NTFS did not; no recession followed in 2023) which the NTFS camp claims as vindication, but the 2024-25 economic ambiguity leaves the verdict unsettled.

2. **Is the yield-curve signal still operative after QE/QT?** Some researchers argue compressed term premia from large-scale asset purchases mechanically distort the spread and that the 2019 inversion / pandemic-recession sequence was lucky timing. Others (Bauer & Mertens [2]) find the signal robust through 2018. The 2022-23 inversion-without-recession is the central piece of contradicting evidence.

3. **VIX backwardation: predictive or just confirmatory?** Cboe's own analysis ([24]) finds backwardation does *not* reliably predict subsequent negative returns outside outright crises. Other practitioner sources treat it as a regime trigger. The empirical question — does conditioning forward-return strategies on backwardation add alpha after fees — remains contested.

4. **Credit-equity divergence interpretations.** When credit spreads tighten while equity vol stays elevated (or vice versa), some argue this is a Fed-flow distortion ([25]) and the underlying signal is unchanged; others argue the divergence itself is the actionable signal because it reveals which market is being mispriced. No agreed-upon adjudication.

5. **Copper-gold ratio post-2020.** The historical 0.85 correlation with 10y yields has weakened materially since 2021 ([21]). Whether this is a temporary structural break (China stimulus dynamics, gold ETF flows, energy-transition copper demand) or a permanent decay of the signal is unresolved.

6. **Sahm Rule supply vs demand sensitivity.** The Sahm Rule triggered in 2024 but Claudia Sahm herself argued the 2024 trigger was driven by labor-supply growth (immigration) rather than demand collapse — a regime mismatch. The rule's historical reliability may be conditional on demand-driven unemployment cycles ([27]).

7. **Adaptive-markets implication for any signal.** Per Lo ([18]), risk-reward relationships are not stable over time; signals decay as they're arbitraged. This puts a cap on how much weight any single regime signal should bear. Practitioners disagree on how much decay to assume — Marks ([19]) emphasizes recurring patterns of greed/fear; quants like AQR build in factor-decay assumptions explicitly.

8. **Single-factor regime models vs multi-factor frameworks.** Bridgewater's growth × inflation 4-box ([23]) is parsimonious; Hamilton-style HMM models with multiple latent states ([15]) fit data better but are prone to overfitting. The practitioner / academic gap on regime granularity remains open.

9. **Causation vs correlation in yield-curve recessions.** Bauer & Mertens explicitly flag this ([2]) — does an inverted curve *cause* a recession (via tight monetary policy compressing credit) or merely *signal* market participants' aggregate expectations? Different causal stories imply different operational use.

10. **EBP signal in low-volatility regimes.** The 2002 false positive ([6]) suggests the EBP can fire on idiosyncratic credit shocks (corporate-governance scandals) that don't generalize. No consensus on filtering these out ex-ante.

---

## Section D — Lead-lag relationship table

| Signal | Asset class affected | Typical lead/lag | Cycles validated in | Confidence | Source |
|---|---|---|---|---|---|
| 10y-3m Treasury spread inversion | U.S. economy (recession onset) | Leads 6-24 months (avg ~12m) | Every recession since 1960 (no false positives in that window); 2022-23 inversion may be first false positive | High | [1], [2], [32] |
| 10y-3m Treasury spread inversion | U.S. equities (S&P drawdown) | Leads 12-18 months but equities often rise post-inversion | Same as above; 2019, 2006, 2000, 1989 | Medium (timing too loose for tactical use) | [1], [2] |
| Near-term forward spread (NTFS) | U.S. recession | Leads ~4-6 quarters; cleaner than 2-10 | Validated 1972-2018; correctly stayed positive through 2022 episode | Medium-High (newer; less out-of-sample data) | [3], [4] |
| Excess Bond Premium (GZ-EBP) | U.S. economy (recession risk) | 50bp rise → ~15pp recession prob over 12m | Every recession 1973-2015 with limited false positives; 2002 false positive | High | [5], [6] |
| HY OAS widening (≥300bp from recent low) | U.S. equities | Leads 2-8 weeks before equity peaks; 3-9 months before recession | 2000, 2007, 2020 (and earlier per RIA aggregation) | High (but timing window broad) | [5], [6], [26] |
| Credit spread widening generally | Real economic activity | Excess bond premium predicts at 1q and 1y horizons | Every U.S. recession since 1973 | High | [5] |
| MOVE (bond vol) spike | VIX (equity vol) | MOVE leads VIX by days-to-weeks in macro/policy stress | Multiple Fed-driven episodes (2013 taper, 2022 hike cycle) | Medium | [13] (mechanism); cross-asset literature |
| VIX spike | S&P 500 bottom | Coincident-to-lagging (VIX often peaks before SPX bottom in protracted bears, e.g. Oct '08 vs Mar '09) | 2008, 2020, 2018 | High that VIX is *not* a forward signal | [24] |
| VIX backwardation (term-structure inversion) | S&P 500 forward returns | Coincident with drawdowns ≥10%; not a leading signal for forward returns | 2008, 2011, 2018, 2020 | Low-Medium (works only in outright crises) | [24] |
| ACM term premium rise | Risk assets broadly | Coincident regime indicator (rises in stress) | All cycles since 1961 in ACM data | Medium (regime context, not timing) | [9] |
| Cochrane-Piazzesi factor | U.S. Treasury bonds (excess returns) | Predicts ~12 months ahead; R² up to 0.44 | 1964-2003 sample; mixed OOS post-2008 | Medium | [7], [10] |
| Copper/gold ratio | 10y Treasury yield | Leads by a few days; corr ~0.85 | Pre-2020 strong; weakened post-2020 | Medium pre-2020 / Low post-2020 | [21] |
| Chicago Fed NFCI tightening | Real economic growth | Leads ~1-2 months | Validated weekly 1971-present | High | [22] |
| Conference Board LEI | Recession onset | Leads ~7 months | Most U.S. recessions since 1959; recent false positives 2022-23 | Medium (declining reliability) | [28] |
| Sahm Rule trigger | Recession onset | Coincident-to-slightly-lagging (~3m into recession) | All 11 recessions since 1950; 1 ambiguous false positive (1959) | High historically; weakened by 2024 supply-driven trigger | [27] |
| FX carry-trade drawdown | Global risk-off regime | Coincident; daily resolution | 1998 (LTCM), 2008, 2011, 2020, Aug 2024 | High as confirmation, not lead | [17], [30] |
| DXY trend (vs 200d MA) | EM equities, commodities | Coincident regime filter | Multi-decade | Medium (sign of relationship varies) | DXY research consensus |
| DXY trend | U.S. equity style (value vs growth) | Coincident: weak USD → value leadership; strong USD → growth | Post-1990 cycles | Medium | DXY research consensus |
| Oil price ROC > +75% YoY | U.S. recession | Late-cycle coincident with onset | 1973, 1979, 1990, 2008 | Medium (regime-conditional on capacity tightness) | [29] |
| S&P 500 peak | Commodities (GSCI) peak | S&P leads commodities by ~7 months on avg | Last 6 recessions | Medium | [29] |
| QMJ price (low) | Forward QMJ returns / market regime | Predicts high QMJ returns; QMJ rises in drawdowns | Multi-decade global sample | Medium | [12] |
| Cross-asset funding-liquidity stress (Pástor-Stambaugh liquidity factor decline) | All risk assets | Coincident with crises (sharp drop 2008) | 1968-present | High as state variable; less predictive lead | [13], [14] |

---

## Notes on methodology

- "Confidence" reflects the joint criteria of: (a) cross-cycle replication (≥3 cycles), (b) survival of out-of-sample tests where available, (c) practitioner adoption with verifiable track record.
- The yield-curve and credit-spread signals are the two strongest survivors of the Goyal-Welch-Zafirov 2024 ([10]) OOS audit and dominate the table accordingly.
- VIX-based signals are demoted from "leading" to "coincident" or "regime-state" status — VIX confirms regime, it does not predict it.
- Practitioner sources (Marks, Bridgewater, AQR) are used for *frameworks*; academic sources are used for *empirical magnitudes and lead times*.
