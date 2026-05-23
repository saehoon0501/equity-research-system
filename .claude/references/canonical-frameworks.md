# Canonical Frameworks Reference

Citation source of truth for `cdd-lead`, `quantitative-analyst`, `strategic-analyst`, and `bear-case` agents. Every framework invocation in a memo MUST cite one of these entries by short key (e.g., `mauboussin_moat_2024`).

## Always-apply core (5 frameworks)

### damodaran_narrative_dcf

**Source:** Damodaran, "Narrative and Numbers: The Value of Stories in Business" (Columbia Business School Publishing, 2017). PDF: https://pages.stern.nyu.edu/~adamodar/pdfiles/eqnotes/narrativeandnumbers.pdf — and Damodaran's post-2017 evolution applying the framework to AI/hyperscaler narratives (NVDA, TSLA, hyperscaler valuations on his blog https://aswathdamodaran.blogspot.com/).

Bind a defensible business narrative to a numerical DCF. Stress test 3 cases (bear/base/bull). Use NYU Stern data for ERP, country risk, industry betas, and multiples by sector: https://pages.stern.nyu.edu/~adamodar/

**Bull-case (and bear-case) structural-distinctiveness requirement (Overlay 5 / v0.2):** the bear/base/bull cases must be three *qualitatively distinct narrative arcs*, not a sensitivity-band perturbation on a single path. Specifically, the bull and bear cases each MUST cite:
1. **Helmer Power anchor** — for bull case: a specific Helmer Power from the strategic-analyst memo's `helmer_powers_evidence[]` that is the structural differentiator driving the bull revenue/margin trajectory. For bear case: a specific structural impairment (moat fade, Power lost, capital-allocation misstep, regulatory shift) — with a specific mechanism (Power-evidence-floor failure / capital-allocation grade collapse / quality-gate degradation / reinvestment-moat label drop) and a falsifying observable + resolution date. (peak_pain_archetypes analog-citation requirement deprecated 2026-05-17 per docs/superpowers/plans/2026-05-17-remove-peak-pain-archetypes-and-counterfactual-veto.md.)
2. **Distinct narrative arc** — a qualitatively different business outcome from base (e.g., bull: "AWS becomes platform tax for AI economy at $50B+ AI run-rate by 2027"; bear: "AWS AI run-rate stalls below $20B as CSP capex bubble deflates and Trainium yields slip behind TSMC competitors"). NOT "base ± 10% on growth/margin sensitivity."
3. **Forward-observable falsifying condition** — a specific, dated, observable that would invalidate this narrative arc within 12-36 months. The falsifier feeds pm-supervisor's `reevaluation_triggers` block and the dashboard's monitoring queue.

A bull or bear case lacking any of (1)/(2)/(3) is a process failure — the cases collapse to sensitivity analysis and the multi-framework-convergence value of the DCF is lost. Evaluator HG-15 catches this.

**Speculative tier exempt:** DCF is skipped entirely for `speculative_optionality` tier per the tier-conditional rule in `quantitative-analyst.md` §4; the structural-distinctiveness requirement does not apply (the milestone-tree framework in cdd-lead memo carries the speculative-tier narrative discipline instead).

### austere_dcf

**Bug 8 cross-reference (2026-05-15):** the AMZN 2026-05-13 cold-start vs 2026-05-14 15:55 fresh-re-run variance — same v0.2-2026-05-12 engine, same name, BUY @ HIGH @ 4.5% vs HOLD @ MEDIUM @ 0.0% — was driven by which DCF reconstructions were engaged. The cold-start engaged only the inherited narrative DCF; the fresh re-run engaged both inherited + austere and surfaced a 53-65% base-value gap. `austere_dcf` is the second DCF mandated by the dual-DCF framework-engagement floor (see `quantitative-analyst.md` §4 "Dual-DCF mandate," evaluator HG-20, pm-supervisor §2.7 R4).

**Methodological lineage:** Damodaran's "mean reversion" frame applied throughout his sector papers and industry data pages (https://pages.stern.nyu.edu/~adamodar/), combined with Mauboussin's "fade rate" concept on excess returns. The austere DCF is the disciplined counterweight to the inherited narrative DCF: where the narrative DCF embeds the analyst's frame about what management can sustain, the austere DCF mean-reverts growth, margin, and ROIC to industry/macro reference levels over the explicit horizon. The two reconstructions converging is informative (the price-discipline signal is consistent); the two diverging by >30% is informative (the inherited narrative is sustaining a meaningful premium over the mean-reverted base case, which MUST be reconciled with evidence — see `## Inherited-vs-Austere Reconciliation` requirement in quantitative-analyst.md §4).

**Methodology (mean-reversion reconstruction):**

- **Horizon:** same FCF projection horizon as the inherited_dcf (typically 10 years explicit period + terminal value)
- **Growth fades to GDP-plus-inflation by year 5:** terminal growth = (current 10Y Treasury yield + 1.5%) as a proxy for nominal GDP growth. The 10Y Treasury yield comes from FRED `DGS10` series via `mcp__fred__get_series` (per §3.9 of quantitative-analyst.md). The `+ 1.5%` premium is `dcf.austere_terminal_growth_dgs10_premium_pct` from the PARAMETERS_USED block. (Historical note: previously documented as cached at `.claude/references/damodaran_implied_erp_cache.json`; that cache was non-existent on disk and retired by mig 037 / /review-me 2026-05-19 — DGS10 was always a FRED pull, never actually cached.) Year-1 growth is anchored to recent 3-5y realized revenue CAGR (NOT the inherited narrative). Linear fade from year-1 to terminal by year 5; flat thereafter.
- **Margins revert to industry median by year 5:** linear fade from current operating margin to industry median operating margin by year 5. Industry median margin comes from Damodaran's industry data pages (https://pages.stern.nyu.edu/~adamodar/) — cite which industry-median source you used (e.g., `damodaran_industry_data_<year>_<sector>`). If Damodaran's industry data is unavailable for the relevant sector, a Bloomberg-style sector median is an acceptable fallback (cite inline).
- **ROIC fades linearly to WACC over the explicit-period horizon:** over the 10-year explicit window, ROIC declines from current ROIC to WACC by year 10. This collapses the competitive-advantage period (CAP) to zero by terminal year — the mean-reversion assumption that no business sustains excess returns indefinitely (the Mauboussin fade-rate operationalization).
- **Terminal value:** uses the SAME WACC as the inherited_dcf (computed in §3.9 `wacc_regime`) but applied to the mean-reverted FCF — same discount rate, mean-reverted cash flow.
- **Reverse-DCF cross-check at year 5:** compute the implied growth rate at year 5 that would justify the year-5 cash flow under the fade assumption; verify it matches the input fade rate. If not, flag `austere_dcf.reverse_check_inconsistent: true` in the output schema.

**Operational invocation:** see `quantitative-analyst.md` §4 "Dual-DCF mandate" for the integrated workflow, output schema (`austere_dcf_base`, `dcf_divergence_pct`, `## Inherited-vs-Austere Reconciliation` evidenced-reconciliation requirement). The gate enforcement lives in evaluator HG-20 + pm-supervisor §2.7 R4.

**Tier-conditional applicability:** core_fundamental + thematic_growth tiers ONLY. Speculative_optionality EXEMPT (per Overlay 3 C-4 skip rule — DCF is correctly skipped for speculative names; the milestone-tree framework carries the speculative-tier narrative discipline instead).

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

### buffett_2007_inevitables

**Source:** Berkshire Hathaway 2007 Shareholder Letter, "Businesses — The Great, the Good and the Gruesome." https://www.berkshirehathaway.com/letters/2007ltr.pdf — operationalized for public-equity analysis by Christopher Bloomstran's Semper Augustus annual letters (https://www.semperaugustus.com/clientletter).

The reinvestment-moat math: a great business reinvests large amounts of capital at high incremental ROIC. A growth-rate-only valuation collapses two distinct dimensions — (1) **incremental ROIC** on deployed capital (capex + ΔNWC + acquisitions), and (2) **deployable runway** (dollar size of the addressable reinvestment opportunity at the maintained ROIC level) — into one number, and is wrong for high-reinvestment compounders. The framework is operationalized in `quantitative-analyst.md` §4 `reinvestment_moat` block: report `incremental_roic_3y_trailing`, `incremental_roic_5y_trailing`, `current_reinvestment_rate_pct`, `deployable_runway_years_est`, and a composite `quality_label`:

- **A**: incremental_roic_3y > WACC + 10pp AND deployable_runway_years_est ≥ 5
- **B**: incremental_roic_3y > WACC + 5pp AND deployable_runway_years_est ≥ 3
- **C**: incremental_roic_3y > WACC AND deployable_runway_years_est ≥ 2
- **D**: incremental_roic_3y ≤ WACC OR deployable_runway_years_est < 2

Cite alongside `koller_valuation_7e` (ROIC × growth value-driver tree) when a business has capex/revenue ≥ 3%. Capital-light businesses (capex/revenue < 3%) skip the dimension — the framework applies only where reinvestment economics meaningfully drive value. Speculative-tier names skip entirely (no trailing reinvestment history).

The pm-supervisor §2.6 stress-test consumes `quality_label`: label A reinforces structural justification for above-base-rate growth divergence (alongside the Helmer-Power gate); label D contradicts moat-narrative bull cases (the math says reinvestment economics don't support the growth story regardless of which Power is claimed) and forces `stress_failed` even when Powers are evidenced.

## Quality gate (precondition, not a "framework")

### piotroski_2000

**Source:** Piotroski, "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers," J. Accounting Research 38 (2000), pp. 1–41. PDF: https://www.ivey.uwo.ca/media/3775523/value_investing_the_use_of_historical_financial_statement_information.pdf

9-point F-Score across profitability, leverage/liquidity, operating efficiency. Memo gates to REJECT if F-Score < 6.

### altman_1968

**Source:** Altman, "Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy," J. Finance 23(4) (1968), pp. 589–609. PDF: https://www.calctopia.com/papers/Altman1968.pdf

Z-score (manufacturers) or Z'' (non-manufacturers/EM). Memo gates to REJECT if Z'' < 1.1.

### sloan_1996

**Source:** Sloan, "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows About Future Earnings?" The Accounting Review 71(3) (1996), pp. 289–315. PDF: https://www.stern.nyu.edu/sites/default/files/assets/documents/con_032093.pdf

TATA = (NI − CFO) / Total Assets. High-positive TATA = earnings outrunning cash; high-negative TATA = cash outrunning earnings. Sloan 1996 used cross-sectional deciles; the |TATA| > 0.05 cutoff is a folk-canonical operationalization (also appears in Richardson/Sloan/Soliman/Tuna 2005 in some specifications). **Phase 1 status: OBSERVATION-ONLY.** Agent computes and emits the value; no disposition consequence. Promotion to gating gated on operator-validated thresholds via Phase 2 calibration workstream.

### beneish_1999_dsri

**Source:** Beneish, "The Detection of Earnings Manipulation," Financial Analysts Journal 55(5) (1999), pp. 24–36. https://en.wikipedia.org/wiki/Beneish_M-score (canonical restatement of the 8-ratio formula; original paywalled at FAJ).

DSRI = (Receivables_t / Sales_t) / (Receivables_{t-1} / Sales_{t-1}). Days-Sales-in-Receivables Index — catches channel-stuffing and premature revenue recognition that aggregate Sloan TATA misses (because TATA can wash out at firm level even when receivables drift). DSRI is robust to cycle-state (channel-stuffing into a peak quarter still pumps DSRI directionally). **Phase 1 status: OBSERVATION-ONLY** alongside Sloan TATA. Beneish's full 8-ratio M-Score and Dechow F-Score deferred until calibration cohort exists. Beneish 1999 threshold M > −1.78 ("manipulator") and DSRI > 1.465 component-threshold are NOT enforced at Phase 1 — values surfaced only.

### damodaran_implied_erp

**Source:** Damodaran, monthly implied equity risk premium data. https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/implprem.html (published monthly; canonical store is the `wacc.erp` parameter row in postgres `parameters` table, externalized via mig 037 / /review-me 2026-05-19 — supersedes the previously-documented `.claude/references/damodaran_implied_erp_cache.json` which was non-existent on disk).

Implied ERP backed out from S&P 500 dividend+buyback yield + analyst growth + 10Y Treasury. Replaces static ERP in WACC build. Per /review-me 2026-05-19 consumer-wiring convergence (Design 1): quantitative-analyst reads ERP from the PARAMETERS_USED block (snapshot of `wacc.erp` from `parameters_active` under tag=NULL, or from sweep-tag-filtered snapshot under `--as-of-tag`). Refresh is out-of-band: an operator-runbook script (cron or manual) WebFetches Damodaran's monthly table when DGS10 drift exceeds `wacc.erp_refresh_drift_bps` and INSERTs a new `wacc.erp` row with `supersedes_version` chain (same pattern as the INV-2 override applied 2026-05-19 01:52 UTC). The runtime path no longer refreshes per-run.

### lovallo_kahneman_2003

**Source:** Lovallo & Kahneman, "Delusions of Success: How Optimism Undermines Executives' Decisions," Harvard Business Review (July 2003). https://hbr.org/2003/07/delusions-of-success-how-optimism-undermines-executives-decisions

Outside-view / reference-class forecasting. Five-step procedure: (1) select reference class, (2) assess outcome distribution, (3) make intuitive prediction (inside view), (4) assess predictability (correlation r between predictor and outcome), (5) corrected = intuitive + r × (reference_mean − intuitive).

**Phase 1.5 (Overlay 3 / 2026-05 update):** the full r-correction is now applied with placeholder **r = 0.20**. Quantitative-analyst computes `corrected_growth_pct = intuitive + 0.20 × (reference − intuitive)` and emits all three values (intuitive, reference, corrected). pm-supervisor routes on `corrected_divergence_pp` (corrected − reference), not on raw `outside_view_divergence_pp`. Raw divergence is preserved in `conviction_rationale` for audit.

**Justification for r = 0.20** (from 2026-05 /research synthesis, canonical-citations-only):
- Mauboussin Base Rate Book (S&P 1500, 1994-2014): year-over-year sales-growth correlation r = 0.27; correlations decline at longer horizons (Mauboussin's own guidance: "base rate should receive the majority of the weight for forecasts of three years or longer")
- Chan, Karceski & Lakonishok 2003 (J. Finance): "no persistence in long-term earnings growth beyond chance"; IBES long-term-growth forecasts "overly optimistic and add little predictive power"
- Kahneman 2011 *Thinking, Fast and Slow* Ch.18: uses r = 0.30 as "most optimistic guess" for a more-predictable single-feature toy domain — 10y revenue CAGR on mega-cap equities should sit *below* 0.27
- IBES LTG forecasts run 2-5× realized growth (systematic optimism in the inside view we're shrinking) — asymmetric loss (capital loss > opportunity cost) favors the low end of LK's canonical 0.20-0.40 range

**Phase 2 calibration**: r = 0.20 is a placeholder pending empirical recalibration from the system's own forecast-vs-realized cohort once 8+ quarters of post-overlay data accumulate. The Phase 2 path replaces 0.20 with a per-cohort empirical r estimated from the realized-CAGR distribution of the system's own predictions over the post-2026 calibration window. Until then, 0.20 is the locked value; do not vary per-name.

### mauboussin_base_rates_2016

**Source (generic bucket — 2016 Base Rate Book):** Mauboussin, Callahan & Majd, "The Base Rate Book — Integrating the Past to Better Anticipate the Future" (Credit Suisse Plus 2016; Counterpoint Global mirrors). Primary PDFs returned 403 in research; reference numbers below sourced from secondary aggregators citing the same tables and consistent across sources. **Replace with Primary citations when source acquired.**

**Source (cohort refinement — Overlay 4 / v0.2):** AQR/Bessembinder/Shumway methodology — Asness, Frazzini & Pedersen "Quality Minus Junk" (2018); Bessembinder "Do Stocks Outperform Treasuries?" (J. Financial Economics 2018) + 2023 64,000-stock global update (CFA Institute Financial Analysts Journal); Shumway 1997 "The Delisting Bias in CRSP Data" (J. Finance) for exit-treatment convention. The 2016 BRB is itself survivors-only (10y survival ~59%, 20y ~38%) — for high-skew cohorts that fact inflates 10y CAGR means by an estimated 200-400 bps and the cohort-refined table corrects this.

**2-tier lookup procedure** (used in `quantitative-analyst.md` §4.5 outside-view emission):
1. Attempt sector-and-scale match against `base_rates_cohort_refined` (table below + JSON at `.claude/references/base_rates_cohort_refined.json`). If matched → use the cohort's mean as `reference_class_growth_mean_pct` and emit `reference_source: "base_rates_cohort_refined.<cohort_name>"`.
2. If no cohort match → fall back to the generic revenue-bucket table below. Emit `reference_source: "mauboussin_base_rates_2016_generic_fallback"` so pm-supervisor §2.6 applies slightly more skepticism to the divergence routing (the survivors-only construction is known to overstate by 200-400 bps for high-skew cohorts).

#### base_rates_cohort_refined (cohort-matched, AQR/Bessembinder-aware construction)

**Cohort construction rule (load-bearing):**
- **Entry:** at t=0 of the cohort window, include every US-listed firm meeting the reference-class entry criteria. Entry is based on observable t=0 characteristics — NOT on what happened next (no survivorship filter at entry).
- **Tracking:** follow each entity 10y forward or until exit, whichever comes first.
- **Exit treatment (per Shumway 1997 / AQR convention, adapted for revenue-space):**
  - Acquired/merged → partial-period CAGR through last reported quarter; residual period assumed at cohort median CAGR.
  - Bankruptcy / delisted for cause → partial-period CAGR through last 10-Q; residual revenue assumed at last-reported level with 0% growth (revenue-space analog of Shumway's −30% equity convention).
  - Spin-off / split → track larger remainco for residual window; smaller spin-off exits cohort.
  - Going-private / strategic exit → treat as acquired.
- **Aggregation:** equal-weight every cohort entity's hybrid 10y revenue CAGR. Report mean AND p10/p25/p50/p75/p90 distribution.

| Cohort key | Entry criteria | Cohort windows | 10y rev CAGR — mean | Median | p10 | p90 |
|---|---|---|---|---|---|---|
| `mega_cap_tech_compounders` | $50B+ market cap + GICS Software/Internet/Semis + R&D/sales ≥ 8% | 2004, 2009, 2014 (3 windows) | **~11%** | ~9% | ~−2% | ~22% |
| `mega_cap_consumer_retail` | $50B+ market cap + GICS Consumer Discretionary/Staples | 2004, 2009, 2014 | **~5%** | ~4% | ~−3% | ~12% |
| `mega_cap_financials` | $50B+ market cap + GICS Financials | 2004, 2009, 2014 | **~4%** | ~3% | ~−5% | ~10% |
| `biopharma_at_scale` | $20B+ market cap + GICS Biotech/Pharma | 2004, 2009, 2014 | **~6%** | ~5% | ~−4% | ~15% |

`source_confidence: low (initial release)` — table values above are placeholders pending empirical population in `.claude/references/base_rates_cohort_refined.json` via a one-time Sharadar PIT backfill script using `mcp__fundamentals__get_fundamentals(kind='PIT')`. The JSON file is the source of truth; the markdown table is a human-readable summary. The cohort-construction rule above is locked; the numerical values will tighten once the backfill completes. **Until backfill, agents should cite this entry but flag `cohort_values_placeholder: true` in the outside_view block.**

#### Generic revenue-bucket fallback (preserved from 2016 BRB; survivors-only — use only when no cohort match)

Reference-class distributions for 10-year forward revenue CAGR conditioned on starting-revenue bucket:

| Starting revenue bucket | 10y revenue CAGR — historical mean | 10y revenue CAGR — historical median |
|---|---|---|
| <$1B | ~11% | ~8% |
| $1B–$5B | ~9% | ~7% |
| $5B–$10B | ~7% | ~6% |
| $10B–$50B | ~6% | ~5% |
| $50B+ | ~4% | ~3.5% |

Operating margin and ROIC-fade base rates available in the same source; not embedded here for Phase 1 (only revenue-CAGR outside-view is wired into the prompt). `source_confidence: medium` — values are directionally consistent across secondary citations but specific decile thresholds not Primary-verified. **Known limitation:** survivors-only construction inflates 10y mean by an estimated 200-400 bps for high-skew cohorts (Brown-Goetzmann 1995 found 20-80 bps for mutual funds; scaled up for equity-level skew per Bessembinder). When this fallback is used, pm-supervisor §2.6 should apply marginally more skepticism to the divergence routing.

## Supporting references

### damodaran_data

**Source:** Aswath Damodaran, NYU Stern data hub. https://pages.stern.nyu.edu/~adamodar/

Annual ERP, country risk, industry betas, multiples by sector. Load-bearing for any DCF or relative valuation. Cite when using ERP, beta, or sector multiples in `damodaran_narrative_dcf` or peer-comp analysis.

### koller_valuation_7e

**Source:** Koller, Goedhart, Wessels, "Valuation: Measuring and Managing the Value of Companies," 7th ed. (McKinsey/Wiley, 2020). ~896 pages.

ROIC × growth value-driver tree; operating-leverage decomposition. Empirical chapter showing top-quintile ROIC firms persist ~5pp above average 15 years out (US 1963–2017). Cite when invoking ROIC > WACC framing or sector-level operating-leverage analysis.

## Anchor-framework empirical priors (v2.1 — 2026-05-23)

These short-keys back the tier-conditional anchor guidance in `pm-supervisor.md` §7.6 v2.1. They are in-track anchor priors (cited inside `fundamental_track` / `technical_track` free-form text via the existing `framework_keys[]` channel), NOT synthesis short-keys for `structural_theory.framework_keys[]` / `reasoning.framework_keys[]` framework-balance enforcement. The §8 framework-balance enumeration in pm-supervisor.md (quant: 7 keys, strategic: 3 keys) is NOT extended by this section.

### aqr_buffetts_alpha

**Source:** Frazzini, Kabiller, Pedersen, "Buffett's Alpha," NBER Working Paper w19681. http://docs.lhpedersen.com/BuffettsAlpha.pdf

Berkshire's 1976-2011 alpha decomposes into a 3-factor exposure (Quality + Safety + Cheap-vs-Quality), not P/E mean-reversion. Cite when justifying **forward P/E compression via EPS growth as the PRIMARY core_fundamental anchor** over historical P/E mean-reversion (which the paper's regressions empirically demote to a noisy single-name signal). The forward-P/E-compression anchor maps onto the paper's "Cheap-vs-Quality" factor: pay a fair multiple for a high-quality compounder and let EPS grow into the price.

### aqr_vol_targeting_2020

**Source:** Harvey, Hoyle, Rattray, Sargaison, Sinclair, Van Hemert, "The Best Strategies for the Worst Crises," Financial Analysts Journal 2020. https://www.tandfonline.com/doi/full/10.1080/0015198X.2020.1790853

Conditional volatility targeting formula: `position_size = (target_vol / realized_vol) × baseline_size`. Empirical max-drawdown reduction averages ~6.6pp across equity markets when applied as a position-sizing overlay. Cite when **thematic_growth tier DCA legs are sized via vol-scaling** rather than equal-weight (high-vol names like ARKK-cohort 2021-2022 demonstrated the value of vol-scaled legs — equal-weight legs over-allocated capital into the -77% drawdown). Reference the formula by short-key inside `technical_track` text; do not re-derive inline.

### aqr_factor_timing_is_hard

**Source:** AQR Capital Management, "Factor Timing is Hard." https://www.aqr.com/Insights/Perspectives/Factor-Timing-is-Hard

AQR's standing position: valuation measures (P/E, P/B, CAPE) are NOT effective single-name market-timing signals — they describe rich/cheap conditions but do not generate entry timing. Cite when **demoting historical P/E mean-reversion from PRIMARY anchor to SECONDARY rich/cheap rail** in core_fundamental tier guidance. The implication: a "P/E is at 5y high" reading informs sizing discipline (be smaller / wait for compression) but does NOT trigger entry on its own.

### vanguard_lsi_vs_dca_2023

**Source:** Vanguard, "Cost averaging: Invest now or temporarily hold your cash?" 2023. https://corporate.vanguard.com/content/dam/corp/research/pdf/cost_averaging_invest_now_or_temporarily_hold_your_cash.pdf

Lump-sum investing (LSI) beats dollar-cost averaging (DCA) on expected-return basis approximately 68% of the time across US/UK/Australia equity markets, 1976-2022. Cite when **framing DCA grids in `technical_track` as RISK-MANAGEMENT framing rather than return-optimal entry**. The honest framing: DCA is the operator's hedge against being wrong about entry timing (drawdown insurance under uncertain conviction); it is not a mathematically optimal entry strategy.

### easton_peg_2004

**Source:** Easton, "PE Ratios, PEG Ratios, and Estimating the Implied Expected Rate of Return on Equity Capital," SSRN 423601. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=423601

PEG ratios are mathematically undefined or structurally noisy for companies with negative, near-zero, or volatile earnings — the denominator collapses or oscillates and the ratio loses signal value. Cite when **excluding PEG from thematic_growth tier anchor list** for names with negative or near-zero FY+1/FY+2 EPS consensus (which describes the bulk of high-growth pre-profitability software, biotech, and platform names that populate the thematic_growth tier).

### damodaran_young_growth

**Source:** Aswath Damodaran, "Valuing Young, Start-Up and Growth Companies: Estimation Issues and Valuation Challenges." https://pages.stern.nyu.edu/~adamodar/pdfiles/papers/younggrowth.pdf

Damodaran's canonical framework for pre-revenue and early-stage names: traditional DCF/multiple anchors fail when the going-concern assumption is itself the open question. Recommends milestone-tree gating (phase-by-phase probability-of-success factors per biotech analog), Hall steady-state EV (intangibles capitalization), and real-options framing (Trigeorgis, Copeland-Antikarov) over USD-price triggers. Cite when **speculative_optionality tier emits `fundamental_track = null` with `null_reason = "milestone-tree gated — see report.reasoning.detail"`** as the canonical emission. The substantive narrative (phase POS factors, real-options framing) routes to `report.reasoning.detail`; the fundamental_track stays null because price-anchored entry triggers do not apply to binary-outcome names.

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

---

## Canonical §2.6 stress-test claim list by tier (drift-fix 2026-05-17)

The §2.6 adversarial stress-test pass in pm-supervisor.md previously allowed the LLM to "select 6-9 load-bearing claims" per run, which produced run-to-run drift (MSFT 5-14/15/16 inverted 6/6/9 claims with different verdicts; MU 5-12 → 5-14 inverted 6 → 7 with stress_failed 0 → 3 catastrophic in 48h despite no material data change). This section pins the claim list per tier; pm-supervisor must mark **every** canonical claim with one of `{stress_passed, stress_open, stress_failed}` — selection of which claims to invert is forbidden.

**Enforcement:** evaluator HG-28 verifies that the `adversarial_stress_test.canonical_claims_evaluated` list emitted by pm-supervisor matches the canonical list for the cdd-lead tier (set-equality, not subset). Missing or extra claims are a hard fail.

**Grandfathering:** rows in `analyst_briefs` / `execution_recommendations` with `created_at < 2026-05-17T00:00:00Z` are exempt from HG-28 (old schema).

### core_fundamental (10 claims)

For tier `core_fundamental`, pm-supervisor MUST invert and mark each of the following 10 claims:

| claim_id | claim_text | framework_anchor |
|---|---|---|
| `cf-01` | Damodaran narrative-DCF base midpoint > spot (positive margin of safety to base case) | `damodaran_narrative_dcf` |
| `cf-02` | ≥1 Helmer Power held at strict evidence floor (≥2 primary-source citations, source_quality_tier ≤ 2) | `helmer_7_powers` |
| `cf-03` | Capital-allocation overall grade ∈ {A, A-, B+, B} (no C/D) | `mauboussin_capital_allocation_2024` |
| `cf-04` | Piotroski F-Score ≥ 5 of 9 (quality signals dominant) | `piotroski_2000` |
| `cf-05` | Altman Z'' > 1.1 (above distress threshold; book-equity X4 path acceptable) | `altman_1968` |
| `cf-06` | reinvestment_moat quality_label ∈ {A, B} (incremental_roic ≥ WACC for B; ≥ WACC+10pp for A) | `mauboussin_moat_2024` |
| `cf-07` | Reverse-DCF implied growth ≤ 2× Mauboussin cohort mean (no extreme-overpricing signal) | `mauboussin_reverse_dcf` + `mauboussin_base_rates_2016` |
| `cf-08` | Outside-view corrected_divergence_pp ≤ +2pp OR Helmer-Power gate cleared | `lovallo_kahneman_2003` |
| `cf-09` | WACC sensitivity ±25bp does not flip base-case MoS sign (β stability) | `damodaran_narrative_dcf` + `damodaran_implied_erp` |
| `cf-10` | Counterfactual top-3 has ≥2 SURVIVOR matches AND <2 NON-SURVIVOR | `peak_pain_archetypes` |

### thematic_growth (10 claims)

For tier `thematic_growth`, pm-supervisor MUST invert and mark each of the following 10 claims:

| claim_id | claim_text | framework_anchor |
|---|---|---|
| `tg-01` | Damodaran + austere dual-DCF gap < 30% OR conditional reconciliation via ≥3 evidenced pillars (switching_costs, reinvestment_moat A, cohort base rate ≥ austere terminal) | `damodaran_narrative_dcf` + `austere_dcf` |
| `tg-02` | ≥2 Helmer Powers held at evidence floor; for capital-light (`reinvestment_moat: N/A capital-light`), ≥1 must be operating-leverage-relevant (switching_costs / network_economies / branding) | `helmer_7_powers` |
| `tg-03` | Capital-allocation overall grade ∈ {A, A-, B+, B} | `mauboussin_capital_allocation_2024` |
| `tg-04` | reinvestment_moat quality_label A (incremental_roic_3y > WACC+10pp; runway ≥ 5y) OR capital-light with operating-leverage Powers cited | `mauboussin_moat_2024` |
| `tg-05` | Reverse-DCF implied growth ≤ 2× cohort mean (no `reverse_dcf_implied_growth_double_cohort_mean_signal` fire) | `mauboussin_reverse_dcf` + `mauboussin_base_rates_2016` |
| `tg-06` | Outside-view corrected_divergence_pp ≤ +2pp OR (Helmer-gate cleared AND reinvestment_moat quality_label A reinforces) | `lovallo_kahneman_2003` |
| `tg-07` | Net Dollar Retention ≥ 105% OR module attach ≥ 25% OR sector-equivalent KPI from brief §2.0 anchor (NRR / cohort retention / unit economics) | sector-conditional: `bessemer_cloud_100`, `skok_saas_metrics` |
| `tg-08` | FCF margin trajectory positive (YoY improvement OR consistent above 20%) | `mauboussin_meroi` + `sacks_burn_multiple` |
| `tg-09` | Counterfactual top-3 has ≥2 SURVIVOR matches | `peak_pain_archetypes` |
| `tg-10` | No `hyperscaler_capex_outlier_cisco_1999_trigger` active OR named watch-condition resolvable within 12mo | `peak_pain_archetypes` |

### speculative_optionality (10 claims)

For tier `speculative_optionality`, pm-supervisor MUST invert and mark each of the following 10 claims (DCF + reverse-DCF + outside-view skipped per C-4; milestone-tree carries discipline):

| claim_id | claim_text | framework_anchor |
|---|---|---|
| `so-01` | Cash runway ≥ 12mo at current burn rate | `sacks_burn_multiple` |
| `so-02` | Milestone tree has ≥3 dated falsifiable resolutions in next 24mo | milestone-tree (cdd-lead framework) |
| `so-03` | ≥1 Helmer Power emerging (Provisional acceptable; evidence-floor relaxed to ≥1 primary citation) | `helmer_7_powers` |
| `so-04` | No Altman Z'' < 0.5 (catastrophic distress) | `altman_1968` |
| `so-05` | Cumulative-dilution baseline anchored to a SINGLE share-count baseline (no quant-vs-strategic dilution-baseline disagreement) | cross-agent consistency rule |
| `so-06` | Counterfactual top-3 has ≥2 SURVIVOR matches AND <2 NON-SURVIVOR | `peak_pain_archetypes` |
| `so-07` | Primary-source citation ≥1 for the bull-case structural anchor (single-source allowed at speculative tier) | evidence_index discipline |
| `so-08` | No D-rated bucket in capital-allocation grading (R&D, M&A, capex specifically) | `mauboussin_capital_allocation_2024` |
| `so-09` | Regulatory / scientific / commercial pathway has a named resolution event in next 36mo | milestone-tree (cdd-lead framework) |
| `so-10` | Partner / customer concentration ≤ 50% of revenue OR contracted ≥3y forward | sector-conditional |

### Procedure for pm-supervisor.md §2.6

1. Read `cdd-lead.tier` from the integrated memo.
2. Load the canonical 10-claim list for that tier from this section.
3. For each canonical claim:
   - Invert (1-line falsification check).
   - Categorize as `stress_passed` / `stress_open` / `stress_failed` (catastrophic if terminal-thesis-impairing).
   - Emit `{claim_id, claim_text, verdict, falsification_check_note}` in the envelope's `adversarial_stress_test.canonical_claims_evaluated[]` array.
4. Compute totals from the marked list — `claims_inverted_count` MUST equal 10; `stress_passed + stress_open + stress_failed` MUST sum to 10. Mismatch → process failure.
5. Do NOT add extra claims. Do NOT skip canonical claims. The list is exhaustive and exclusive for the tier.

### When to update this list

Pre-plan parameter changes (claim addition/removal/edit) require operator approval via `/grill-me` followed by a versioned bump (record `canonical_claims_version` in the envelope so audit can pin which list was applied). The current version is `v1-2026-05-17`.
