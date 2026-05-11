# Canonical Frameworks Reference

Citation source of truth for `cdd-lead`, `quantitative-analyst`, `strategic-analyst`, and `bear-case` agents. Every framework invocation in a memo MUST cite one of these entries by short key (e.g., `mauboussin_moat_2024`).

## Always-apply core (5 frameworks)

### damodaran_narrative_dcf

**Source:** Damodaran, "Narrative and Numbers: The Value of Stories in Business" (Columbia Business School Publishing, 2017). PDF: https://pages.stern.nyu.edu/~adamodar/pdfiles/eqnotes/narrativeandnumbers.pdf

Bind a defensible business narrative to a numerical DCF. Stress test 3 cases (bear/base/bull). Use NYU Stern data for ERP, country risk, industry betas, and multiples by sector: https://pages.stern.nyu.edu/~adamodar/

### mauboussin_reverse_dcf

**Source:** Rappaport & Mauboussin, "Expectations Investing: Reading Stock Prices for Better Returns," rev. ed. (Columbia Business School Publishing, 2021). https://www.expectationsinvesting.com/

Translate the current price into implied growth, margin, and competitive-advantage period. Compare implied expectations to historical ROIIC (via Mauboussin & Callahan's MEROI: https://www.morganstanley.com/im/publication/insights/articles/article_marketexpectedreturnoninvestment_en.pdf).

### mauboussin_meroi

**Source:** Mauboussin & Callahan, "Market-Expected Return on Investment (MEROI)" (Counterpoint Global / Morgan Stanley). https://www.morganstanley.com/im/publication/insights/articles/article_marketexpectedreturnoninvestment_en.pdf

Operational form of reverse-DCF: turns implied expectations into a single comparable number you can benchmark against the company's historical ROIIC. Use alongside `mauboussin_reverse_dcf` when the analyst wants a single-number summary of price-implied expectations.

### mauboussin_moat_2024

**Source:** Mauboussin & Callahan, "Measuring the Moat" (Counterpoint Global / Morgan Stanley, 2024 ed.). https://www.morganstanley.com/im/publication/insights/articles/article_measuringthemoat.pdf

Three sources of value-add: production advantages, consumer advantages (network effects, switching costs, search costs, habits), external (regulation, subsidy). For each, name the fade pattern (how excess returns compete away).

### helmer_7_powers

**Source:** Hamilton Helmer, "7 Powers: The Foundations of Business Strategy" (2016). https://7powers.com/

Power = superior + significant + sustainable. Seven types: Scale Economies, Network Economies, Counter-Positioning, Switching Costs, Branding, Cornered Resource, Process Power. Counter-Positioning and Process Power are diagnostically rarest and highest-signal. For each claimed Power, state the Benefit (cash-flow effect) AND the Barrier (why competitor arbitrage fails).

### mauboussin_capital_allocation_2024

**Source:** Mauboussin & Callahan, "Capital Allocation: Results, Analysis, and Assessment" (Counterpoint Global / Morgan Stanley, updated 2022/2024). https://www.morganstanley.com/im/publication/insights/articles/article_capitalallocation.pdf

Five-bucket framework graded against ROIC vs WACC: CapEx, R&D, M&A, dividends, buybacks, debt paydown (treat debt as a sixth lever where material). Rubric: past behavior, current ROIC, alignment of incentives, stated principles. Empirical data back to 1970.

## Quality gate (precondition, not a "framework")

### piotroski_2000

**Source:** Piotroski, "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers," J. Accounting Research 38 (2000), pp. 1–41. PDF: https://www.ivey.uwo.ca/media/3775523/value_investing_the_use_of_historical_financial_statement_information.pdf

9-point F-Score across profitability, leverage/liquidity, operating efficiency. Memo gates to REJECT if F-Score < 6.

### altman_1968

**Source:** Altman, "Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy," J. Finance 23(4) (1968), pp. 589–609. PDF: https://www.calctopia.com/papers/Altman1968.pdf

Z-score (manufacturers) or Z'' (non-manufacturers/EM). Memo gates to REJECT if Z'' < 1.1.

## Supporting references

### damodaran_data

**Source:** Aswath Damodaran, NYU Stern data hub. https://pages.stern.nyu.edu/~adamodar/

Annual ERP, country risk, industry betas, multiples by sector. Load-bearing for any DCF or relative valuation. Cite when using ERP, beta, or sector multiples in `damodaran_narrative_dcf` or peer-comp analysis.

### koller_valuation_7e

**Source:** Koller, Goedhart, Wessels, "Valuation: Measuring and Managing the Value of Companies," 7th ed. (McKinsey/Wiley, 2020). ~896 pages.

ROIC × growth value-driver tree; operating-leverage decomposition. Empirical chapter showing top-quintile ROIC firms persist ~5pp above average 15 years out (US 1963–2017). Cite when invoking ROIC > WACC framing or sector-level operating-leverage analysis.

## Sector addenda

### bessemer_cloud_100

**Source:** Bessemer State of the Cloud + Cloud 100 Benchmarks. https://www.bvp.com/atlas/the-cloud-100-benchmarks-report

NRR/GRR benchmarks (NRR >130% world-class; GRR >95% enterprise). Rule of 40 + Rule of X for AI-native (growth weighted 2×).

### skok_saas_metrics

**Source:** David Skok, "SaaS Metrics 2.0/3.0," For Entrepreneurs. https://www.forentrepreneurs.com/saas-metrics-2-definitions-2/

LTV/CAC, CAC payback, Magic Number, Burn Multiple. CAC payback target <12 months; magic number >1.0.

### sacks_burn_multiple

**Source:** David Sacks, "The Burn Multiple." https://sacks.substack.com/p/the-burn-multiple-51a7e43cb200

Net burn ÷ net new ARR. <1 amazing, 1–1.5 great, 1.5–2 OK, >2 watch, >3 bad.

### a16z_marketplace_metrics

**Source:** Andreessen Horowitz, "13 Metrics for Marketplaces" + "GMV Retention." https://a16z.com/13-metrics-for-marketplace-companies/ and https://a16z.com/gmv-retention-the-marketplace-metric-most-ignore/

GMV, take rate (typical 10–30%), GMV-cohort retention, frequency, liquidity.

### sequoia_ai_ascent_2025

**Source:** Sequoia AI Ascent 2025 (Sonya Huang). https://inferencebysequoia.substack.com/p/insights-from-ai-ascent-2025

AI-stack value-capture mapping: HW / cloud / model / tooling / vertical app. Sequoia view: value consolidates at infra (low-margin scale) and at vertical apps that "sell outcomes." Hold this view alongside a16z's barbell view; flag when they diverge.

### bain_ai_trillion_dollar_2024

**Source:** Bain Tech Report 2024, "AI's Trillion-Dollar Opportunity." https://www.bain.com/insights/ais-trillion-dollar-opportunity-tech-report-2024/

AI HW + SW TAM $780–990B by 2027. Use as upper-bound TAM prior; refuse to use as point estimate.

### tanay_ai_gross_margin_2025

**Source:** Tanay Jaipuria, "The Gross Margin Debate in AI." https://www.tanayj.com/p/the-gross-margin-debate-in-ai

AI-native gross margin median 50–60% with 84% reporting 6%+ erosion. Provider GMs vary widely (DeepSeek 85%, Anthropic 55%, Together 45%). For any AI-native name, scrutinize hosting/inference/third-party-model cost lines.

## Banned-output references

### molchanov_stangl_stovall_rejection_2024

**Source:** Molchanov & Stangl, "The Myth of Business Cycle Sector Rotation," International Journal of Finance & Economics (2024). https://onlinelibrary.wiley.com/doi/full/10.1002/ijfe.2882

Empirically rejects classical Stovall sector rotation (early/mid/late/recession map). Memos must NOT use this rotation framework as a positioning argument.

### nakamura_steinsson_2018

**Source:** Nakamura & Steinsson, "High-Frequency Identification of Monetary Non-Neutrality," QJE 2018. https://www.nber.org/system/files/working_papers/w19260/w19260.pdf

30-min HFI window around FOMC announcements. Required citation when memo discusses Fed-rhetoric or rate-action effects (otherwise banned per spec §8).

### cieslak_vissing_jorgensen_2019

**Source:** Cieslak, Morse & Vissing-Jorgensen, "Stock Returns over the FOMC Cycle," J. Finance 2019. https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12818

Entire post-1994 equity premium accrues in even FOMC-cycle weeks (0,2,4,6). Use as calendar prior, not as tradable factor.

## Positioning analytics

Citation source-of-truth for `catalyst-scout` (Flow B v2 Task 27) — options-implied positioning + cross-section sentiment.

### cremers_weinbaum_iv_spread_2008

**Source:** Cremers & Weinbaum, "Deviations from put-call parity and stock return predictability," J. Financial and Quantitative Analysis 45(2) (2010; WP 2008). https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/deviations-from-putcall-parity-and-stock-return-predictability/

IV term-structure inversion (front-month ATM IV above back-month ATM IV) is an event-pricing signal: the market is pricing higher near-term realized volatility, typically because of an upcoming dated catalyst (earnings, FDA decision, M&A vote). Used by `catalyst-scout` §3 to detect informed-flow asymmetry — if `front_back_spread > 5pp` but no catalyst surfaces in the §2 calendar sweep, the cdd-lead memo may be missing a load-bearing event.

### pan_poteshman_pcratio_2006

**Source:** Pan & Poteshman, "The information in option volume for future stock prices," Review of Financial Studies 19(3) (2006), pp. 871-908. https://academic.oup.com/rfs/article/19/3/871/1602169

Put/call volume ratio carries information about future stock returns: informed traders preferentially use options for directional bets, and aggregated P/C flow predicts returns over the following week. **Critical caveat:** high P/C is NOT mechanically bearish — direction is sector + situation specific (e.g., high P/C on a recently-rallied name = profit-taking hedge; high P/C on a flat name = informed bearish). Memo language must cite this contextually, not as a binary buy/sell rule. Used by `catalyst-scout` §3.

### bofa_fms

**Source:** Bank of America Global Fund Manager Survey (monthly). Coverage via BofA Research portal + aggregated summaries (ZeroHedge, MarketWatch, Reuters).

Monthly survey of ~250 institutional fund managers covering ~$700B AUM. Surfaces cash levels (contrarian-bullish below 4%, contrarian-bearish above 5%), most-crowded trades (contrarian-bearish on the named trade), biggest tail-risk identified (regime-context for catalyst impact). Used by `catalyst-scout` §4 sentiment sweep — calibrates whether the cdd-lead thesis is consensus or differentiated.
