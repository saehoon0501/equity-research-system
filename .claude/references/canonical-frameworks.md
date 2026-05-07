# Canonical Frameworks Reference

Citation source of truth for `cdd-lead`, `quantitative-analyst`, `strategic-analyst`, and `bear-case` agents. Every framework invocation in a memo MUST cite one of these entries by short key (e.g., `mauboussin_moat_2024`).

## Always-apply core (5 frameworks)

### damodaran_narrative_dcf

**Source:** Damodaran, "Narrative and Numbers: The Value of Stories in Business" (Columbia Business School Publishing, 2017). PDF: https://pages.stern.nyu.edu/~adamodar/pdfiles/eqnotes/narrativeandnumbers.pdf

Bind a defensible business narrative to a numerical DCF. Stress test 3 cases (bear/base/bull). Use NYU Stern data for ERP, country risk, industry betas, and multiples by sector: https://pages.stern.nyu.edu/~adamodar/

### mauboussin_reverse_dcf

**Source:** Rappaport & Mauboussin, "Expectations Investing: Reading Stock Prices for Better Returns," rev. ed. (Columbia Business School Publishing, 2021). https://www.expectationsinvesting.com/

Translate the current price into implied growth, margin, and competitive-advantage period. Compare implied expectations to historical ROIIC (via Mauboussin & Callahan's MEROI: https://www.morganstanley.com/im/publication/insights/articles/article_marketexpectedreturnoninvestment_en.pdf).

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
