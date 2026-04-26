# L5 — Technical Execution Playbooks (Empirical Lane)

Empirical evidence on technical execution: trend / momentum, volume confirmation, volatility-regime signals, stop methodology, mean reversion thresholds, and the chart-pattern / candlestick / Elliott folklore that doesn't survive scrutiny.

Scope: This is a knowledge library for the equity-research-system's entry/exit and risk-management modules. It is **not** a charting tutorial — patterns appear here only with their empirical pedigree (sample, methodology, p-value or out-of-sample test) attached, OR as warnings that the pattern fails empirical scrutiny.

---

## Section A — Curated sources

Tier 1 = peer-reviewed academic papers in top finance journals (JF, JFE, RFS, JFQA) plus practitioners with externally verifiable track records (AQR firm research, Man Group / Man AHL, CTA pioneers) where they describe specific tested techniques. Tier 2 = practitioner research notes / well-cited industry papers without strict peer review. Tier 3 = secondary aggregators / educational summaries useful for cross-checking.

### Tier 1 — academic and rigorous practitioner

1. [Jegadeesh & Titman (1993), "Returns to Buying Winners and Selling Losers", JF](https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf) — the seminal cross-sectional momentum paper; J=K=3-12 month winners-minus-losers earns ~1% / month, 1965-1989. [Tier 1]
2. [Jegadeesh & Titman 30-year retrospective (Springer, 2022)](https://link.springer.com/article/10.1007/s11408-022-00417-8) — survey of how the original cross-sectional momentum result has held up out of sample, internationally, and through factor crowding. [Tier 1]
3. [Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum", JFE 104(2), 228-250](http://docs.lhpedersen.com/TimeSeriesMomentum.pdf) — TSMOM (own-asset 12-month sign) generates positive abnormal returns across 58 instruments / 4 asset classes, 1985-2009. Distinct from cross-sectional momentum. [Tier 1]
4. [Asness, Moskowitz & Pedersen (2013), "Value and Momentum Everywhere", JF](https://www.aqr.com/Insights/Research/Journal-Article/Value-and-Momentum-Everywhere) — value and momentum premia exist across 8 markets / asset classes; common factor structure; momentum negatively correlated with value. [Tier 1]
5. [Asness, Frazzini, Israel & Moskowitz (2014), "Fact, Fiction, and Momentum Investing", JPM](https://www.aqr.com/Insights/Research/Journal-Article/Fact-Fiction-and-Momentum-Investing) — refutes 10 myths (sporadic, short-side only, small-cap only, killed by transaction costs) using 212 years (1801-2012) of US data plus 40 international markets. [Tier 1]
6. [Hurst, Ooi & Pedersen (2017), "A Century of Evidence on Trend-Following Investing", JPM](https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing) — TSMOM positive in every decade 1880-2016, performed in 8 of 10 worst 60/40 drawdowns. The empirical bedrock for crisis-alpha claims. [Tier 1]
7. [Daniel & Moskowitz (2016), "Momentum Crashes", JFE 122, 221-247](https://www.nber.org/system/files/working_papers/w20439/w20439.pdf) — momentum has severe negative skew; 14 of 15 worst months had panic-state precondition (negative 2yr market + positive contemporaneous return); dynamic vol-scaling roughly doubles Sharpe. [Tier 1]
8. [Novy-Marx (2012), "Is Momentum Really Momentum?", JFE 103(3), 429-453](https://rnm.simon.rochester.edu/research/MOM.pdf) — predictive power concentrated in months t-12 to t-7 (the "echo"), not the most recent six months — affects how momentum signals should actually be constructed. [Tier 1]
9. [Hong & Stein (1999), "A Unified Theory of Underreaction, Momentum and Overreaction", JF 54(6)](http://www.columbia.edu/~hh2679/jf-mom.pdf) — gradual-information-diffusion model that gives momentum a behavioral foundation; predicts stronger momentum in stocks with slow information flow (small, low-coverage). [Tier 1]
10. [Cooper, Gutierrez & Hameed (2004), "Market States and Momentum", JF](https://rogutierrez.net/files/States_and_Momentum.pdf) — momentum profits are conditional: +0.93% / mo following positive market state vs −0.37% / mo following negative state, 1929-1995. Regime-dependence is real. [Tier 1]
11. [Lo, Mamaysky & Wang (2000), "Foundations of Technical Analysis", JF 55(4), 1705-1765](https://www.nber.org/papers/w7613) — kernel-regression-based pattern recognition on 31 years of US stocks; finds *some* patterns add incremental information (statistically), but the economic magnitudes are small and the most-touted patterns are not the strongest. [Tier 1]
12. [Brock, Lakonishok & LeBaron (1992), "Simple Technical Trading Rules and the Stochastic Properties of Stock Returns", JF 47(5)](https://finance.martinsewell.com/stylized-facts/dependence/BrockLakonishokLeBaron1992.pdf) — original empirical case for moving averages and trading-range breakouts on the DJIA 1897-1986 using bootstrap inference. [Tier 1]
13. [Sullivan, Timmermann & White (1999), "Data-Snooping, Technical Trading Rule Performance and the Bootstrap", JF 54(5)](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00163) — applies White's Reality Check to BLL 1992: best in-sample rule survives data-snooping correction in original sample BUT fails in the 10-year out-of-sample period. The standard cautionary tale. [Tier 1]
14. [Park & Irwin (2007), "What Do We Know About the Profitability of Technical Analysis?", J. Econ. Surveys 21(4)](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1467-6419.2007.00519.x) — survey of 95 modern studies: 56 positive, 20 negative, 19 mixed; positive results concentrated in FX/futures, weaker in equities; data-snooping caveats throughout. [Tier 1]
15. [Lehmann (1990), "Fads, Martingales, and Market Efficiency", QJE 105(1)](https://www.researchgate.net/publication/24091219_Fads_Martingales_and_Market_Efficiency) — short-term (weekly) reversal documents 1.79%/wk gross profit on contrarian trades; surviving spreads but largely a liquidity-provision premium. The mean-reversion lookback foundation. [Tier 1]
16. [Avellaneda & Lee (2010), "Statistical Arbitrage in the U.S. Equities Market", Quant Finance 10(7)](https://traders.studentorg.berkeley.edu/papers/Statistical%20arbitrage%20in%20the%20US%20equities%20market.pdf) — PCA / ETF-residual mean-reversion strategy: Sharpe 1.44 (1997-2007) but only 0.9 (2003-2007) — clear alpha decay; volume-adjusted version recovers 1.51 in 2003-2007. [Tier 1]
17. [Marshall, Young & Rose (2006), "Candlestick Technical Trading Strategies: Can They Create Value for Investors?", JBF 30(8)](https://ideas.repec.org/a/eee/jbfina/v30y2006i8p2303-2323.html) — bootstrap test on 35 DJIA stocks 1992-2001: candlestick patterns have **no value** for DJIA stocks. [Tier 1]
18. [Marshall, Young & Cahan (2008), candlesticks on TSE](https://www.researchgate.net/publication/5157791_Are_candlestick_technical_trading_strategies_profitable_in_the_Japanese_equity_market) — same methodology, top 100 Tokyo Stock Exchange names 1975-2002: candlesticks have **no value** in their market of origin either. [Tier 1]
19. [Lo (2004), "The Adaptive Markets Hypothesis", JPM 30(5)](https://web.mit.edu/Alo/www/Papers/JPM2004_Pub.pdf) — framework for why anomaly profitability is regime-dependent and decays: relations between risk and reward shift with population dynamics, not stable. [Tier 1]
20. [McLean & Pontiff (2016), "Does Academic Research Destroy Stock Return Predictability?", JF 71(1)](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365) — 97 anomalies: 26% lower out-of-sample, **58% lower post-publication**. Critical for any signal in production: assume meaningful crowding decay. [Tier 1]
21. [Harvey, Liu & Zhu (2016), "...and the Cross-Section of Expected Returns", RFS 29(1)](https://people.duke.edu/~charvey/Research/Published_Papers/P118_and_the_cross.PDF) — multiple-testing correction for the factor zoo; argues t-stat threshold should be ~3.0, not 2.0. Most published anomalies are likely false. [Tier 1]
22. [Moreira & Muir (2017), "Volatility-Managed Portfolios", JF](https://amoreira2.github.io/alan-moreira.github.io/VolPortfolios_published.pdf) — scaling factor exposures inversely to realized volatility produces alpha and Sharpe improvements; works for risk assets, weak/null for bonds-currencies-commodities. [Tier 1]
23. [Llorente, Michaely, Saar & Wang (2002), "Dynamic Volume-Return Relation of Individual Stocks", RFS 15(4)](http://web.mit.edu/~wangj/www/pap/LlorenteMichaelySaarWang02.pdf) — empirically separates volume that signals continuation (informed trading) from volume that signals reversal (liquidity / risk-sharing). Volume's meaning is conditional, not unconditional. [Tier 1]
24. [Bollen & Pool (2009), "Do Hedge Fund Managers Misreport Returns?", JF](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2009.01500.x) — establishes the data-quality problem in alleging trader-survivor track records; ~10% of monthly returns appear misreported. [Tier 1]
25. [Simon & Campasano (2014), "The VIX Futures Basis: Evidence and Trading Strategies", J. Derivatives 21(3)](https://jod.pm-research.com/content/21/3/54.abstract) — VIX basis does not predict spot VIX changes BUT predicts VIX futures returns: −0.79 coefficient on lagged basis, profitable hedged strategy survives transaction costs. [Tier 1]

### Tier 2 — practitioner research and applied notes

26. [Lou & Polk (2022), "Comomentum: Inferring Arbitrage Activity from Return Correlations", RFS](https://personal.lse.ac.uk/loud/comomentum.pdf) — measures momentum-strategy crowding via abnormal correlation among long/short legs; high comomentum predicts ~25pp lower 2-year forward momentum returns. [Tier 2 — peer-reviewed but younger / less-replicated than the Tier 1 core]
27. [Aronson (2007), "Evidence-Based Technical Analysis"](https://www.amazon.com/Evidence-Based-Technical-Analysis-Scientific-Statistical/dp/0470008741) — book-length application of bootstrap / Monte Carlo to 6,400+ technical rules on the S&P 500; explicitly demonstrates head-and-shoulders has **no statistically significant predictive power**. [Tier 2]
28. [Kahn & Lemmon (2016), "The Asset Manager's Dilemma", FAJ](https://rpc.cfainstitute.org/sites/default/files/-/media/documents/book/rf-publication/2018/future-of-investment-management-kahn.pdf) — frames factor crowding and alpha decay from the institutional-allocator side; useful counterpoint to academic momentum optimism. [Tier 2]
29. [Macrosynergy, "VIX term structure as a trading signal" (2024)](https://macrosynergy.com/research/vix-term-structure-as-a-trading-signal/) — practitioner replication: backwardation in VIX term structure predicts positive forward S&P returns (effect strengthens to quarterly horizon); contango is **not** a meaningful timing signal. [Tier 2]

### Tier 3 — secondary aggregators / educational

30. [AlphaArchitect, "Momentum Research Summary"](https://alphaarchitect.com/momentum-research-summary/) — curated reading list of high-quality momentum papers, useful as cross-check on what the academic consensus looks like. [Tier 3]
31. [Bulkowski, "Head-and-Shoulders Top Statistics" (Pattern Site, updated 2020)](https://www.thepatternsite.com/hst.html) — practitioner pattern statistics: 19% break-even failure rate, 16% average decline, 68% pullback rate, n≈2,800. **No statistical inference / no random benchmark — useful only as the practitioner-folklore claim that the academic literature contradicts.** [Tier 3]
32. [Wikipedia, "Elliott wave principle" — citing Batchelor & Ramyar Fibonacci-test critique](https://en.wikipedia.org/wiki/Elliott_wave_principle) — finance professor Roy Batchelor and Richard Ramyar found "no significant difference" between Fibonacci-ratio frequencies in DJIA cycles and what would be expected at random. [Tier 3 — entry into the formal critique]

---

## Section B — Distilled patterns

Each bullet cites the Section A entry by number. "Survives" / "doesn't survive" is the load-bearing distinction.

### Patterns that DO survive empirical scrutiny

1. **Cross-sectional momentum (12-1 winners minus losers, monthly rebalance) earns ~1%/month gross over 3-12-month holding periods** in US equities, originally documented over 1965-1989 (1) and replicated/extended through 2012 over 212 years of US data plus 40 international markets (5). Magnitude has compressed post-publication but remains positive (2, 20).
2. **Time-series momentum (own-asset 12-month sign, vol-scaled) is positive in every decade since 1880 and across 8 of 10 worst 60/40 drawdowns** (6). Diversifying versus 60/40, distinct from cross-sectional momentum (3). This is the empirical foundation for "trend following provides crisis alpha."
3. **Momentum's predictive content is concentrated in t-12 through t-7 ("the echo"), not t-6 through t-2 — and the most recent month is a short-term reversal contributor** (8). Implication: the standard "12 minus 1" signal works partly because it accidentally truncates short-term reversal noise; an explicit 12-7 or "skip-the-recent-month" signal is cleaner.
4. **Momentum profits are regime-conditional: +0.93%/mo following positive market state vs −0.37%/mo following negative state (1929-1995)** (10). This is not a statistical artifact — it is reproducible across decades and is consistent with a behavioral overreaction story (9).
5. **Momentum has severe left-tail risk concentrated in panic-rebound regimes** — 14 of 15 worst momentum months had a negative trailing-2-year market combined with a positive contemporaneous return (7). Static momentum allocations therefore require either dynamic vol-scaling or explicit crash-state filters.
6. **Vol-managed portfolios (scale exposure inversely to realized vol) generate positive alphas and Sharpe improvements for risk assets — but not for bonds, FX, or commodities** (22). The mechanism is a leverage effect on the negative correlation between returns and volatility changes; this is asymmetric across asset classes.
7. **Short-term (weekly) cross-sectional reversal earns ~1.79%/week gross in US equities and survives plausible transaction costs**, but the source is mostly liquidity-provision rent rather than a pricing-error correction (15). Use case: market-making / inventory strategies, not a directional signal for a multi-month equity book.
8. **PCA-residual / ETF-residual mean-reversion (the Avellaneda-Lee statistical arbitrage framework) achieved Sharpe ~1.44 in 1997-2002 but only ~0.9 in 2003-2007** (16) — concrete example of a mean-reversion strategy decaying as the trade got crowded. Volume-conditioning recovered some performance.
9. **Volume's meaning is conditional, not unconditional**: high-volume days followed by continuation correspond to informed-trading regimes; high-volume days followed by reversal correspond to liquidity / risk-sharing regimes (23). Empirically, the same volume number can mean opposite things — naive "volume confirms breakout" reasoning ignores this.
10. **VIX term-structure backwardation predicts positive forward equity returns at horizons up to a quarter; contango carries essentially no equity timing information** (29, 25). The asymmetry is real and is a regime classifier, not a tactical timing oscillator.
11. **The VIX futures basis predicts VIX-futures returns with a ~−0.79 coefficient (futures price reverts ~79% of basis over the next month)**, supporting the volatility-risk-premium short-VIX-in-contango / long-VIX-in-backwardation trade with S&P hedge — survives realistic transaction-cost assumptions on 2006-2011 data (25). This is a genuine premium, not a TA signal.
12. **Volatility-targeting reduces left-tail drawdowns** because crashes coincide with elevated realized vol so the vol-scaled book is already de-leveraged when they hit (22). This is an empirically documented mechanism, not a theoretical hope.

### Patterns that DON'T survive empirical scrutiny (equally important)

13. **Candlestick patterns have no statistically significant predictive value in the markets where they were tested most rigorously** — null result in DJIA 1992-2001 (17) and null result in the largest 100 TSE names 1975-2002 (18) using bootstrap-with-randomized-OHLC inference. The Japanese-equity origin story does not survive testing on Japanese equities.
14. **The classic head-and-shoulders pattern fails academic scrutiny.** Aronson's Monte-Carlo / bootstrap testing on the S&P 500 shows no significant predictive power (27). Bulkowski's practitioner statistics (31) do not constitute a test — they have no random benchmark and no out-of-sample protocol.
15. **Elliott Wave / Fibonacci-ratio claims fail empirical tests**: Batchelor & Ramyar found Fibonacci ratios in DJIA cycles are indistinguishable from random (32); Aronson and others note the framework is unfalsifiable in practice because the wave-count rules can be retroactively re-fitted (32, 27). The "theory" is a story with non-objective rules.
16. **The best in-sample technical trading rule from Brock-Lakonishok-LeBaron (12) failed in the subsequent 10-year out-of-sample period** once data-snooping corrections were applied (13). This is the canonical demonstration that selecting "the rule that worked best on history" does not survive forward.
17. **Most cross-sectional anomalies decay roughly 58% post-publication and 26% out-of-sample** (20). Any technical pattern that has been written about extensively should be assumed to have lost most of its edge unless there is a fresh out-of-sample replication. The momentum factor is one of the few exceptions and even it has compressed.
18. **Multiple-testing correction (Harvey-Liu-Zhu) raises the required t-stat for a new factor from ~2.0 to ~3.0** (21) — a large fraction of "discovered" technical signals would not survive this hurdle.
19. **High comomentum (crowded momentum trades) predicts ~25pp lower 2-year forward momentum returns** (26). The "trend-following crowding decay" story is empirically grounded — momentum is not regime-stable when arbitrageurs pile in.
20. **ATR-based stops vs fixed-percentage stops: there is no peer-reviewed comparison with a clean experimental design.** The widely-cited "15% improvement" claims trace to vendor blog posts, not journals. The defensible statement is conceptual: ATR-based stops adapt to volatility regime and so produce more uniform stop-out probabilities, which volatility-scaling literature (22) supports indirectly. Treat ATR-vs-fixed as a sensible default, not as an empirically validated alpha source.

---

## Section C — Open questions / disagreements

1. **Is cross-sectional momentum still alive at original magnitudes, or has it been mostly arbitraged away?** AQR (5, 6) argues yes-still-alive net of costs; McLean-Pontiff (20) and Lou-Polk (26) argue significant decay; Lo's adaptive-markets framework (19) predicts time-varying profitability. Likely-correct synthesis: positive but compressed, with state-dependence (4, 10) more important than the unconditional mean.
2. **Time-series momentum vs cross-sectional momentum — same factor or different?** Moskowitz-Ooi-Pedersen (3) argue distinct; Goyal-Wahal and others have re-examined and questioned how independent the two really are after controlling for the asset-allocation effect of own-asset trend signals. Open.
3. **Does intraday or sub-daily TA actually work?** The empirical evidence summarized in Park-Irwin (14) is strongest at daily-and-above horizons. Intraday positive results in the literature lean heavily on FX/futures and have not been systematically replicated in equities under a strict data-snooping framework.
4. **How crowded is "too crowded" for trend-following allocators?** Comomentum (26) gives a measure but the threshold for materially compromised forward returns is debated; CTA AUM peaked in 2014 and the post-2014 decade was famously poor for the category.
5. **ATR vs vol-targeting vs Kelly-style sizing for stop placement** — these are conceptually closely related but the literature on which produces the best risk-adjusted outcome on a per-name discretionary book (vs a quant book) is thin.
6. **Volume-confirms-breakout at the academic level**: Llorente-Michaely-Saar-Wang (23) makes volume's meaning conditional, but the practitioner literature still treats volume confirmation as nearly axiomatic. The honest answer is that *abnormal* volume conditional on a directional move predicts continuation more often than not, but the unconditional "rising volume + rising price = bullish" rule is too coarse.
7. **Mean-reversion thresholds**: Avellaneda-Lee (16) used z-score thresholds of roughly ±1.25 to ±1.5 on 60-day residual lookbacks for entry; the optimal lookback drifted as crowding increased. There is no universal threshold — it is regime- and crowding-dependent.

---

## Section D — What survived empirical scrutiny vs. what didn't

| Pattern / signal | Empirical evidence base | Survives scrutiny? | Confidence | Notes |
| --- | --- | --- | --- | --- |
| Cross-sectional momentum (12-1, 3-12 mo holding) | (1, 2, 5) — 212 years, 40 markets | Y, but compressed | High | Magnitude lower post-2000; severe crashes (7); regime-conditional (10). |
| Time-series (own-asset) momentum, vol-scaled | (3, 6) — every decade 1880-2016 | Y | High | Crisis-alpha behavior in 8/10 worst 60/40 drawdowns. |
| 12-7 ("echo") momentum vs 6-2 momentum | (8) — JFE peer-reviewed | Y, signal cleaner | Med-High | Skip-the-recent-month is a real free improvement. |
| Vol-targeted / vol-managed equity exposure | (22) — JF peer-reviewed | Y, for risk assets only | High | Null/weak for bonds, FX, commodities. |
| VIX backwardation as forward equity-return signal | (25, 29) — peer + practitioner | Y, asymmetric only | Med-High | Contango carries no signal. |
| VIX futures basis trade (short contango, long backwardation, hedged) | (25) — peer-reviewed | Y | High | Survives transaction costs in published sample. |
| Short-term (weekly) cross-sectional reversal | (15) — QJE peer-reviewed | Y, but it's a liquidity rent | High | Not a directional alpha for a multi-month book. |
| PCA / ETF-residual mean reversion (stat arb) | (16) — QF peer-reviewed | Conditional — decayed substantially after 2002 | Med | Post-2007 returns require active research; volume-conditioning helps. |
| Volume-as-confirmation (conditional version) | (23) — RFS peer-reviewed | Y, conditional on context | Med | Same volume = continuation in informed regimes, reversal in liquidity regimes. |
| Moving-average trend rules on indexes (BLL '92 best rule) | (12, 13) — JF peer reviewed both ways | N (failed out of sample after data-snooping correction) | High | The original anomaly did not survive forward. |
| Head-and-shoulders pattern | (11, 27) — JF + Aronson | N — fails formal statistical tests | High | Bulkowski's practitioner statistics (31) lack a random benchmark. |
| Candlestick patterns (DJIA, TSE) | (17, 18) — peer-reviewed bootstrap tests | N | High | Null even in Japanese equities, the market of origin. |
| Elliott Wave / Fibonacci ratios in price | (32) — Batchelor-Ramyar | N | High | Frequencies indistinguishable from random; framework is non-objective (Aronson 27). |
| Generic chart patterns selected by data mining | (13) — STW Reality Check | N once snooping is corrected | High | Best in-sample rule failed out of sample. |
| Generic anomaly published in a finance journal | (20, 21) — McLean-Pontiff, Harvey-Liu-Zhu | Conditional — assume ~58% post-publication decay | High | Plan around decay rather than ignore it. |
| ATR-based stops vs fixed-% stops | Vendor blogs only — no peer-reviewed comparison | Inconclusive (sensible default, not validated alpha) | Low | Indirect support from vol-targeting literature (22). |
| Trader "track records" cited in popular books | (24) — Bollen-Pool | Treat with skepticism | High | ~10% of hedge fund monthly returns show signs of misreporting. |

---

## Use notes for the system

- When encoding entry/exit rules: prefer signals from the **green rows** above (cross-sectional momentum with skip-month, time-series momentum with vol-scaling, VIX-backwardation regime flag, vol-managed equity sizing, conditional volume context).
- When the discretionary research process surfaces a thesis grounded in **head-and-shoulders, candlesticks, Elliott Waves, Fibonacci retracements, or generic "chart patterns"**: the system should treat these as zero-evidence inputs and require an independent fundamental or empirically validated technical justification.
- Any backtest of a technical signal **must** apply a multiple-testing / data-snooping correction (13, 21) and must reserve a strict out-of-sample window. Assume ~58% post-publication decay (20) when sizing.
- Momentum sizing should incorporate dynamic vol-scaling (7, 22) and an explicit panic-state filter (10), not a static long-only allocation.
