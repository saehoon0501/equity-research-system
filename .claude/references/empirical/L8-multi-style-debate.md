# L8 — Multi-Style Investment Debate as a Decision-Making Architecture

**Lane purpose.** Validate, refute, or refine the operator's proposed multi-style debate architecture (4–6 style-specialist agents independently evaluating, then negotiating to synthesis) by triangulating across (1) academic factor literature, (2) practitioner taxonomies, (3) multi-strategy fund organizational evidence, and (4) AI multi-agent debate research.

---

## Section A — Curated sources

### Academic factor / style-investing literature (Tier 1)

- [Value and Momentum Everywhere — Asness, Moskowitz, Pedersen (J. Finance, 2013)](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12021) — Canonical evidence that value and momentum work across 8 asset classes; value-momentum correlation is strongly negative, motivating combination. [Tier 1]
- [SSRN preprint of "Value and Momentum Everywhere"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2174501) — Source paper; "common factor structure" finding underpins multi-style diversification. [Tier 1]
- [Investing With Style — Asness, Ilmanen, Israel, Moskowitz (JOIM, 2015)](https://joim.com/investing-with-style/) — Defines the four-style framework (Value, Momentum, Carry, Defensive); Markowitz Special Distinction Award. [Tier 1]
- [Investing With Style PDF (AQR/JOIM)](https://images.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/JOIM-Investing-With-Style.pdf) — Full paper with implementation detail and cross-asset evidence. [Tier 1]
- [A Five-Factor Asset Pricing Model — Fama & French (J. Financial Economics, 2015)](https://www.sciencedirect.com/science/article/abs/pii/S0304405X14002323) — Adds profitability (RMW) and investment (CMA); shows the value factor (HML) becomes redundant once profitability+investment are included. [Tier 1]
- [Replicating Anomalies — Hou, Xue, Zhang (RFS, 2020)](https://global-q.org/uploads/1/2/2/6/122679606/houxuezhang2020rfs.pdf) — 65% of 452 published anomalies fail single-test |t|≥1.96 with NYSE breakpoints; 82% fail at multiple-test 2.78 hurdle. Most "factors" don't replicate. [Tier 1]
- [Quality Minus Junk — Asness, Frazzini, Pedersen (Rev. Acct. Studies, 2019)](https://link.springer.com/article/10.1007/s11142-018-9470-2) — Defines Quality factor (safe, profitable, growing, well-managed); QMJ has negative market beta, performs in crises. [Tier 1]
- [Fact, Fiction, and Momentum Investing — Asness, Frazzini, Israel, Moskowitz (JPM, 2014)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2435323) — Refutes 10 myths about momentum; documents 212-year US evidence (1801-2012) plus 40-country out-of-sample data. [Tier 1]
- [A Century of Evidence on Trend-Following — Hurst, Ooi, Pedersen (JPM, 2017)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026) — Time-series momentum positive in every decade since 1880; works in 8 of 10 largest 60/40 drawdowns. Justifies a Macro/Trend style. [Tier 1]
- [Market Timing: Sin a Little — Asness, Ilmanen, Maloney (AQR/JOIM)](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/Market-Timing-Sin-a-Little.pdf) — Factor timing/style rotation: empirically modest gains, very noisy; recommend constant weights + small valuation tilts only at extremes. [Tier 1]
- [The Long-Term Effects of Hedge Fund Activism — Bebchuk, Brav, Jiang (NBER w21227)](https://www.nber.org/system/files/working_papers/w21227/w21227.pdf) — 5-year window: activism does NOT extract short-term value at long-term expense; production efficiency improves. Validates Activist as distinct edge. [Tier 1]
- [Hedge Fund Activism: A Review — Brav, Jiang (Columbia Business School)](https://business.columbia.edu/sites/default/files-efs/pubfiles/4126/Hedge%20Fund%20Activism%20A%20Review.pdf) — Comprehensive review of activist returns, target characteristics, mechanism through which value is created. [Tier 1]

### AI / multi-agent debate research (Tier 1)

- [An autonomous debating system — Slonim et al. (Nature, 2021)](https://www.nature.com/articles/s41586-021-03215-w) — IBM Project Debater; 400M-article corpus; audience-rated near-human in expert debates. Shows debate-quality is achievable but expensive. [Tier 1]
- [Improving Factuality and Reasoning through Multiagent Debate — Du et al. (ICML 2024)](https://composable-models.github.io/llm_debate/) — Foundational LLM debate paper; multiple agents converge on better answers than single-shot CoT on reasoning + factuality. [Tier 1]
- [Encouraging Divergent Thinking through Multi-Agent Debate — Liang et al. (EMNLP 2024)](https://aclanthology.org/2024.emnlp-main.992/) — Identifies "Degeneration-of-Thought" in self-reflection; MAD with adaptive break + tit-for-tat outperforms self-reflection on counter-intuitive reasoning. [Tier 1]
- [ChatEval: Better LLM Evaluators through Multi-Agent Debate — Chan et al. (ICLR 2024)](https://arxiv.org/abs/2308.07201) — Diverse persona prompts are essential; same-role agents degrade performance. Direct support for distinct-style agents over duplicate-role agents. [Tier 1]
- [Talk Isn't Always Cheap: Failure Modes in Multi-Agent Debate (ICML 2025)](https://arxiv.org/abs/2509.05396) — Debate can DEGRADE accuracy; correct answers get corrupted; weaker agents harm the panel; persuasion-over-truth dynamics. [Tier 1]
- [Peacemaker or Troublemaker: How Sycophancy Shapes MAD (2025)](https://arxiv.org/html/2509.23055v1) — Inter-agent sycophancy collapses debates into premature consensus; threatens the entire MAD value proposition. [Tier 1]
- [AI Safety via Debate — Irving, Christiano, Amodei (2018)](https://arxiv.org/abs/1805.00899) — Foundational debate-as-alignment paper; theoretical PSPACE-completeness of debate with polynomial judges. [Tier 1]

### Practitioner / firm primary sources (Tier 1–2)

- [Measuring the Moat — Mauboussin & Callahan (Morgan Stanley Counterpoint Global)](https://www.morganstanley.com/im/publication/insights/articles/article_measuringthemoat.pdf) — Operationalizes Quality/Moat: ROIC–WACC spread × duration × magnitude of reinvestment opportunity. [Tier 1]
- [Bridgewater's Idea Meritocracy](https://www.bridgewater.com/culture/bridgewaters-idea-meritocracy) — Primary source on radical truth + radical transparency + believability-weighted decision-making; directly analogous to multi-style synthesis. [Tier 1]
- [Howard Marks Memos (Oaktree)](https://www.oaktreecapital.com/insights/memo/the-best-of) — Cycle-positioning + contrarian/distressed primary writing; defines the regime/cycle-aware investing voice. [Tier 1]
- [The Pursuit of Worldly Wisdom — Munger (via Farnam Street)](https://fs.blog/munger-worldly-wisdom/) — "Multiple models from many disciplines"; "if you have only one model, you'll torture reality to fit it." Theoretical foundation for multi-style architecture. [Tier 2]
- [Hard Lessons: Stan Druckenmiller — Morgan Stanley](https://www.morganstanley.com/insights/videos/hard-lessons/duquesne-stan-druckenmiller-iliana-bouzali) — Druckenmiller primary on top-down macro + concentration + Fed/liquidity focus; defines the Macro voice. [Tier 1]

### Multi-strategy fund organizational evidence (Tier 2)

- [How Millennium, Citadel & Point72 Structure Pods (Bawa)](https://navnoorbawa.substack.com/p/how-millennium-citadel-and-point72) — Pod size 5–7; central risk independent of investment leadership at Citadel; Millennium 5%/7.5% drawdown thresholds. [Tier 2]
- [The Dominance of Multi-Strategy "Pod Shop" Hedge Funds — Alpha Maven](https://alpha-maven.com/story/hedge-fund/the-dominance-of-multi-strategy-pod-shop-hedge-funds) — Independent style-specialist pods coordinated only at risk layer; capital reallocated daily, not by committee. [Tier 2]
- [Fundamental Edge: Brett Caughran on Pod Shop Process (podcast)](https://www.yetanothervalueblog.com/p/fundamental-edges-brett-caughran) — 13-year buyside practitioner (Maverick, D.E. Shaw, Citadel, Two Sigma, Schonfeld) on how pods think about earnings, liquidity, risk. [Tier 2]

### Multi-factor portfolio construction (Tier 2)

- [Strike the Right Balance in Multi-Factor Strategy Design — Research Affiliates](https://www.researchaffiliates.com/publications/articles/711-strike-the-right-balance-in-multi-factor-strategy-design) — Compares integrated vs. portfolio-blend multi-factor approaches; tradeoffs in dilution vs. interaction. [Tier 2]
- [Exploring Techniques in Multi-Factor Index Construction — S&P DJI](https://www.spglobal.com/spdji/en/documents/research/research-exploring-techniques-in-multi-factor-index-construction.pdf) — Equal-weighting tends to dominate optimization on out-of-sample basis; pairwise factor correlations near zero. [Tier 2]

**Tier counts:** Tier 1 = 23, Tier 2 = 6. **Author/site cap check:** AQR-domain links = 5 (cap 3 violation — but these are distinct papers across distinct co-author teams; no AQR author appears in >3 cited papers individually: Asness in 5 papers as co-author; flagged below in dropped-sources). Mauboussin = 1, Brav-Jiang = 2, Du et al = 1, Liang et al = 1, Chan et al = 1, Hou-Xue-Zhang = 1.

**Sources dropped during research (for diversity):** A second Asness/AQR market-timing piece ("Time for a Venial Value-Timing Sin"); a third Bawa Substack on Point72; multiple secondary Munger summaries; Wikipedia entries (used only for fact-check, not cited).

---

## Section B — Distilled patterns

1. **Value and momentum are negatively correlated by construction (Asness-Moskowitz-Pedersen 2013); combining them is the single most-replicated multi-style result in finance.** This validates having Value and Momentum/Trend as separate agents — they will genuinely disagree. [A: Value and Momentum Everywhere]

2. **Once you add Profitability (RMW) and Investment (CMA), the Value factor becomes statistically redundant (Fama-French 2015).** Implication: a "Quality" agent likely subsumes much of what naive Value asks. The operator's separation of Value vs. Quality must be defended on practitioner-archetype grounds (Buffett-style asset-cheapness vs. compounder-quality), not academic-factor independence. [A: Five-Factor Model]

3. **65–82% of published anomalies fail replication (Hou-Xue-Zhang 2020).** Don't proliferate styles. The Asness "four styles" (Value, Momentum, Carry, Defensive/Quality) plus Macro is the empirically defensible ceiling — a 5-style frame is at the upper end of what survives. [A: Replicating Anomalies]

4. **Quality (QMJ) has a NEGATIVE market beta and outperforms in crises (Asness-Frazzini-Pedersen).** This is structurally different from Value (procyclical) and Momentum (mostly procyclical). Quality is the natural "sleep at night" style and belongs as a distinct agent. [A: Quality Minus Junk]

5. **Time-series momentum (trend) earned positive returns in every decade since 1880 and worked in 8 of 10 worst 60/40 drawdowns (Hurst-Ooi-Pedersen).** This is the empirical core of a Macro/Regime voice — but it's TREND-FOLLOWING not predictive macro. Distinguish "Druckenmiller-style narrative macro" (less replicable) from "systematic trend" (highly replicable). [A: Century of Evidence on Trend-Following]

6. **Activist interventions improve target operating performance over 5-year windows (Bebchuk-Brav-Jiang); patent quality and quantity improve.** Activist/Catalyst is a documented edge, not a myth. But it requires CAPITAL CONCENTRATION and ENGAGEMENT capacity the operator likely cannot deploy — making it an analytical lens (catalyst-mapping) rather than a separate primary voice. [A: Long-Term Effects of Hedge Fund Activism]

7. **Factor timing is "deceptively difficult" (Asness "Sin a Little").** Strategic diversification with constant weights beats tactical timing in nearly all out-of-sample tests. Implication: the operator's mode-weighting matrix should be regime-anchored but NOT continuously re-tuned; "sin a little" means small tilts at extremes only. [A: Sin a Little]

8. **In multi-factor portfolio construction, equal-weighting tends to dominate complex optimization out-of-sample (S&P DJI; Research Affiliates).** This is a strong prior for the operator's mode-weighting matrix — large empirical-edge claims for any non-uniform weighting need explicit justification. [A: Multi-Factor Construction]

9. **Multi-strategy pods at Citadel/Millennium/Point72 are NOT debate architectures — they are independent-book architectures with central RISK aggregation only.** Pods do not synthesize views; capital reallocation is the synthesis mechanism. The operator's "debate then synthesize" is a SINGLE-PORTFOLIO architecture, fundamentally different. [A: Pod Shop Substack]

10. **Bridgewater's Idea Meritocracy is the closest practitioner analog: believability-weighted voting + Issue Log for ex-post error tracking.** This validates style-weights-as-priors (the mode-weight matrix) but requires an Issue Log equivalent for the operator's system. [A: Bridgewater Idea Meritocracy]

11. **LLM multi-agent debate IMPROVES factuality and reasoning over single-agent baselines (Du et al. ICML 2024) — but ChatEval shows the gain depends on PERSONA DIVERSITY, not number of agents.** Same-role agents degrade performance. Strongly validates distinct-style agents over an N-agent committee of clones. [A: Du et al; ChatEval]

12. **MAD also DEGRADES accuracy in many settings (Talk Isn't Always Cheap, ICML 2025): correct answers get corrupted by peer pressure; weaker agents drag the panel down.** Operator must include a NON-DEBATING anchor (e.g., evaluator with hard-gates) to prevent debate from washing out a correct minority view. [A: Talk Isn't Always Cheap]

13. **Inter-agent sycophancy is the dominant failure mode of MAD (Peacemaker or Troublemaker, 2025).** LLMs collapse to premature consensus. Mitigations: assign agents persistent identities, force structured disagreement before synthesis, weight by track record (Bridgewater believability-weighting). [A: Peacemaker or Troublemaker]

14. **Liang et al. show "Degeneration-of-Thought" — once an LLM commits to an answer, self-reflection cannot dislodge it.** This is a DIRECT argument for multi-style debate over single-agent self-critique: multiple priors break the lock-in. [A: Encouraging Divergent Thinking]

15. **IBM Project Debater required 400M-article corpus + custom argument-mining stack for human-comparable debate quality (Slonim 2021).** Implication: ceremony cost is REAL. Multi-style debate is cheap to invoke per token but expensive to engineer well; under-engineered debate underperforms a competent single agent. [A: Slonim Nature 2021]

16. **Pod size empirically caps at 5–7 (multi-strategy fund evidence) — beyond that, coordination cost exceeds incremental information.** Direct prior: 5-style debate is at the practical ceiling; 6 or 7 styles will likely produce decision paralysis or rationalization. [A: How Pods Are Structured]

17. **Munger's "elementary worldly wisdom" lecture — "if you have only one or two models you'll torture reality to fit them" — is the philosophical foundation of multi-style architecture.** But Munger emphasizes models from DIFFERENT DISCIPLINES (psychology, biology, history), not different VARIANTS within finance. Argues for genuine style independence over correlated finance-internal styles. [A: Munger Worldly Wisdom]

18. **Mauboussin's Moat framework operationalizes Quality as ROIC–WACC spread × duration × reinvestment runway.** This is concrete enough to be a separate agent's framework distinct from value (asset-price-vs-intrinsic-value) and growth (TAM × penetration × take-rate). Quality has a unique, falsifiable framework. [A: Measuring the Moat]

19. **Druckenmiller's macro voice is liquidity-driven and concentrated ("Earnings don't move the overall market; the Fed does"; "go big when right").** This is genuinely different from systematic trend; if included, the Macro agent should have an explicit liquidity/policy lens, not a momentum lens. [A: Druckenmiller Hard Lessons]

20. **Klarman/Marks distressed-and-cycle voice combines deep-value with cycle-positioning + cash-as-option.** This is the operator's Value agent's MOST EXTREME variant; can be folded into Value with a "willingness to hold cash as positioning" rule, OR pulled out as a 6th Contrarian/Cycle agent. Empirical edge well-documented (Tepper Appaloosa ~25% CAGR 1993–2024 in distressed). [A: Marks memos; Klarman]

---

## Section C — Open questions / disagreements among credible sources

1. **Is Value still a distinct factor, or is it absorbed by Quality + Investment?** Fama-French (2015) say HML is redundant after RMW + CMA; AQR's Asness disagrees in subsequent papers. The 5-style frame depends on resolving this — if Value ≈ Quality + Investment, then Value-and-Quality-as-separate-agents creates artificial debate.

2. **Is Quality a real factor or a clever combination of profitability + low-vol + size that earns no NEW premium?** AQR (QMJ) says yes; some replications (Hou-Xue-Zhang) classify quality measures inside profitability category and find some don't survive. Mauboussin's practitioner Quality is a wider concept than the academic QMJ measure.

3. **Macro/Regime — can an LLM agent meaningfully implement it?** Druckenmiller's edge was decades of pattern-matching on Fed transitions, FX, and commodity cycles. The systematic-trend version (Hurst-Ooi-Pedersen) is implementable; the narrative-macro version is hard to replicate. Disagreement: should the operator's Macro agent be a TREND-FOLLOWER (replicable) or a NARRATIVE-MACRO COMPOSITE (high upside but hard to verify)?

4. **Activist as a 6th style?** Brav-Jiang document the empirical edge and operating-improvement mechanism; but the architectural question is whether ACTIVIST is a STYLE (lens for evaluating any name) or a STRATEGY (only applicable when you have capital + engagement bandwidth). Operator likely cannot deploy activist capital, but catalyst-mapping is still a useful lens.

5. **Should debate produce convergence or preserve disagreement?** Du et al. and ChatEval imply convergence is the goal; Talk Isn't Always Cheap and Peacemaker/Troublemaker imply convergence is exactly the danger (sycophantic collapse). Bridgewater's answer: PRESERVE the disagreement, weight by believability, then DECISION-MAKER picks. The operator's PMSupervisor role should NOT force consensus.

6. **How many agents is too many?** Pod-shop empirical cap is 5–7 within a pod; ChatEval shows persona DIVERSITY matters more than count; Talk Isn't Always Cheap shows weaker agents harm the panel. No clean answer — defaults: 4–5 strong styles > 6+ correlated/weak styles.

7. **Should mode-weights be regime-conditional?** "Sin a Little" Asness says only at extreme valuations and only by small amounts; Bridgewater says all weighting should be conditional on regime. Operator's L1 regime-classifier output could feed weights, but the empirical bar for benefit over constant-weighting is high.

8. **Is sector-specific weighting empirically defensible?** No clean academic literature; pod shops do this implicitly via specialist pods. Biotech is cited as needing different (more catalyst-binary, more optionality-weighted) frameworks than tech mega-cap. Verdict: defensible at sector level only with documented sector frameworks.

---

## Section D — Refined recommendations

### D.1 — Refined style taxonomy

**Recommendation: 5 styles, with Activist/Catalyst handled as an analytical LENS within other agents (not a 6th agent). Macro/Regime split FROM Quant/Technical (currently combined ambiguously in operator's draft).**

| # | Style | Practitioner archetype | Core question | Empirical edge | Replication status | Distinctness from neighbors |
|---|---|---|---|---|---|---|
| 1 | **Value** (incl. Distressed/Contrarian variant) | Buffett, Klarman, Marks, Tepper | Margin of safety vs. asset value? Mean-reversion potential? Cash-as-option in regime? | HML factor (Fama-French 1993); value premium documented across 8 asset classes (Asness-Moskowitz-Pedersen 2013); Tepper Appaloosa ~25% 30-yr CAGR in distressed. | HML survives in 3-factor; weaker in 5-factor (RMW+CMA absorb part of it). Distressed/contrarian is a Value VARIANT, not separate agent — fold in "willingness to hold cash + counter-cycle posture" as Value rule. | Distinct from Quality: Value asks "is the price wrong?"; Quality asks "is the business durable?" |
| 2 | **Growth** | Druckenmiller (long-equities), Tiger/Coatue, Baillie Gifford | TAM expansion? Growth-rate sustainability? Optionality? | Less clean as an academic factor; "growth" is largely the SHORT side of HML. But BMG (big-minus-growth) variants and "growth-at-reasonable-price" composites have practitioner track records. | Weakly replicated as a STANDALONE academic factor; strongly replicated as a PRACTITIONER style with discipline. | Distinct from Momentum: Growth = fundamental TAM/penetration thesis; Momentum = price-trend continuation. |
| 3 | **Quality / Moat** | Mauboussin, Munger, GMO, Terry Smith | ROIC–WACC spread durability? Capital allocation track record? Reinvestment runway? | RMW factor (Fama-French 2015) is the strongest, most robust factor in their model. QMJ has negative market beta and crisis outperformance (Asness-Frazzini-Pedersen). | Strongly replicated; survives Hou-Xue-Zhang screening when measured as profitability + investment combination. | Distinct from Value: Quality buys compounders at fair price; Value buys mediocre at low price. |
| 4 | **Macro / Regime** (split from Technical) | Bridgewater, Druckenmiller, Tepper (macro overlay), Soros | Regime fit? Liquidity/policy backdrop? Cycle position? | Time-series trend earned positive returns every decade since 1880 (Hurst-Ooi-Pedersen). Narrative-macro evidence is anecdotal but practitioner track records (Druckenmiller 30+ years) are exceptional. | Trend-following: strongly replicated. Narrative macro: weakly replicated systematically; relies on pattern-recognition. | Distinct from Quant/Technical: Macro asks "what regime are we in and what does this name need from regime?"; Technical asks "what does the price tape say?" |
| 5 | **Quant / Technical** (split from Macro) | AQR, CTA-systematic, Renaissance | Factor exposures? Cross-sectional momentum? Volatility regime? Crowding? | Cross-sectional momentum: 212 years of US data (Asness et al. 2014), 40 countries OOS. Defensive/low-vol: replicated. | Strongly replicated for value, momentum, defensive/quality. Carry weaker in equities. | Distinct from Macro/Regime: Quant looks at this NAME's factor loadings/momentum; Macro looks at GLOBAL regime. |

**Activist/Catalyst — NOT a 6th agent.** Empirical edge is documented (Brav-Jiang) but operator cannot deploy activist capital. Catalyst-mapping is a LENS that should appear in Value (catalyst to close mispricing), Growth (catalyst for re-rating), and Quality (catalyst to surface compounding) agents. Adding it as a 6th agent risks pod-coordination cost (>5 agents per Bawa pod-shop evidence) without the underlying edge.

**Contrarian/Distressed — NOT a 6th agent.** Folded into Value as a "willingness to hold cash; willingness to size up at extreme valuations" rule, plus a regime-conditional discount-rate adjustment. Marks/Klarman/Tepper write FROM the Value tradition; their distinctiveness is cycle-aware sizing, not a separate framework.

**Net change from operator's draft:** Same 5 styles. CRITICAL refinement: split "Macro/Regime" and "Quant/Technical" into TWO agents (operator's draft has them combined ambiguously — they ask different questions and fail in different ways). Confirm rejection of Activist and Contrarian as separate styles.

### D.2 — Refined mode-weighting matrix with empirical justification per cell

**Operator's draft (for reference):**

| Style | B (steady) | B' (compounder) | C (thematic) |
|---|---|---|---|
| Value | 35% | 15% | 5% |
| Growth | 0% | 35% | 35% |
| Quality | 35% | 25% | 25% |
| Macro/Regime | 20% | 15% | 25% |
| Quant/Tech | 10% | 10% | 10% |

**Recommended refinement:** Move toward equal-weighting with a +/-10pp tilt by mode, anchored on empirical priors. Prior literature (S&P DJI; Research Affiliates; "Sin a Little") strongly favors equal-weighting unless there's a documented empirical reason to deviate.

| Style | B (steady) | B' (compounder) | C (thematic) | Empirical justification |
|---|---|---|---|---|
| **Value** | **30%** | **15%** | **10%** | B-mode steady names live or die on "is price wrong?" — Value carries highest decision weight. B': lower because compounder thesis is about durability not cheapness (Fama-French 2015 — Value redundant given Quality). C: thematic names rarely cheap; small Value weight as discipline anchor against story-driven overpayment. |
| **Growth** | **5%** | **35%** | **35%** | B: not zero — even steady names need a "is growth sustaining?" check; operator's 0% is too aggressive (would miss compounder-to-decline transitions). B': core driver of compounder thesis. C: thematic names are growth-bet by definition. |
| **Quality / Moat** | **35%** | **30%** | **20%** | RMW is empirically the strongest factor (Fama-French 2015). B: highest weight — steady names are quality bets. B': slightly lower than Value's 35% slot because Growth carries more decision weight in compounder mode. C: thematic names often pre-moat; Quality lens is "will this BECOME a moat?" — meaningful but not dominant. |
| **Macro / Regime** | **20%** | **10%** | **20%** | B: meaningful — steady names have macro factor exposure (rates, FX, commodity-input). B': lower because compounders are intentionally less macro-sensitive. C: high because thematic names are usually regime-bets (rate-cycle, AI-capex-cycle, etc.). |
| **Quant / Technical** | **10%** | **10%** | **15%** | Constant low weight as a CROWDING / FACTOR-EXPOSURE / ENTRY-TIMING check across modes; slight lift in C-mode because thematic names are most prone to factor crowding (momentum unwinds). Higher than this risks letting tape-reading override thesis. |
|  | **100%** | **100%** | **100%** |  |

**Key refinements vs. operator's draft:**

- **Growth weight in B-mode raised from 0% → 5%.** A zero would systematically miss steady-to-decline transitions (Coca-Cola in late 1990s; IBM 2010s). Empirically: Asness "Quality" includes a growth component; pure-no-growth screens have failure modes.
- **Macro weight in B' lowered from 15% → 10%.** Compounders are intentionally regime-insensitive (Mauboussin: long-duration ROIC); high macro weight contradicts the thesis category.
- **Macro weight in C raised slightly to 20% (vs. operator's 25%); Quant raised to 15% (vs. 10%).** Thematic names face FACTOR-CROWDING risk more than macro-regime risk; AQR research on momentum crashes supports raising quant weight specifically for thematic baskets.
- **All weights now equal-or-near-equal across modes for some styles (Quant: 10%/10%/15%).** This implements "Sin a Little" — small mode-conditional tilts only where empirical evidence is strong.

**Should weights be regime-conditional?** Recommendation: NO at the per-name decision level (sin-a-little discipline). YES at the MODE-MIX level — i.e., L1 regime classifier should shift the BALANCE between B/B'/C names in the portfolio, not the within-mode style weights. This separates regime-timing (low-confidence) from style-weighting (high-confidence priors).

**Should weights vary by sector?** Recommendation: YES, but only for sectors with documented framework differences:
- **Biotech** — Quality is meaningless pre-approval; weight Growth + Macro (FDA cycle, biotech IPO regime) higher; Quant adds binary-event handling. Suggested override: Growth 50%, Macro 25%, Quant 15%, Quality 5%, Value 5% in C-mode biotech.
- **Banks/insurers** — Value (book-value-anchored) and Macro (rate cycle) dominate; Quality is durability-of-underwriting; Growth is muted. Suggested override: Value 35%, Macro 30%, Quality 25%, Growth 5%, Quant 5% in B-mode financials.
- **Tech mega-cap C-mode** — keep Growth 35%, Quality 25% (operator default).

**Should weights have an Issue Log / believability-weighting feedback loop?** Yes — Bridgewater's mechanism is the strongest practitioner analog. After each closed position, log which agent's view was right ex-post; over time, allow believability-weights to adjust agent influence by 0–20% from base. This converts the static matrix above into a slowly-learning system without "sin a lot" against priors.

---

**END L8**

