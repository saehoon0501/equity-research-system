# Section 3 Consensus — L1 / S0 (Regime Capture Sidecar)

**Date:** 2026-04-29
**Session:** Q&A consensus review with operator (saehoon0501) — Section 3 of the consensus-documentation-protocol series
**Status:** **FULLY LOCKED** — Q1 / Q2 / Q3 / Q4 all closed
**Purpose:** Capture S0 sidecar architecture decisions: which dimensions, what signals, what data sources, what weighting method, when to fire shift events, refresh cadence.

**Predecessors:**
- [Section 1 consensus](section-1-consensus.md) — bet, modes, 5-style debate, lanes L1-L8.
- [Section 2 consensus](section-2-consensus.md) — funnel control flow wiring; sidecars S0/S1/S2/S4 (S3 removed).

---

## 1. Section 3 scope (clarified)

Originally framed as "L1 lane review." Expanded during Q&A into the broader question: **how does S0 (regime context sidecar) actually work?** This has 4 sub-questions (Q1-Q4). Q1 is locked; Q2 is in progress; Q3 and Q4 are pending.

S0's job: produce regime classifications (probability distribution per dimension) consumed by every phase of the funnel — P1 trend capture, P3 name discovery (era-fit), P4 Macro-Regime style agent, P6 disposition (vol regime), P8 daily refresh (regime-shift detection).

---

## 2. Q1 LOCKED — Which output dimensions does S0 produce?

**Locked decision: 6 Tier-1 dimensions + 4 method overlays.** Original framing (3 / 4 / 5 dimensions) was wrong. Research surfaced that the 2-axis 4-box should be replaced with a 3-axis decomposition AND a 6th correlation-regime dimension is empirically critical.

### The 6 Tier-1 dimensions

| # | Dimension | Primary signal (locked) | Empirical anchor |
|---|---|---|---|
| **1** | Credit regime | **Excess Bond Premium (EBP)** | Gilchrist-Zakrajšek 2012 AER. **Single highest-edge dimension across all 14 surveyed.** Survives post-QE; survives Bordo-Haubrich 2019 OOS horserace. |
| **2** | Economic-cycle regime | **Near-Term Forward Spread (NTFS)** — NOT 10y-3m | Engstrom-Sharpe 2018 FEDS + 2022 reprise. NTFS dominates 10y-3m OOS for both recession AND 4-quarter equity returns. Correctly handled 2022-23 (no false positive). |
| **3** | Vol regime | **Variance Risk Premium (VRP) = VIX² − realized variance** — NOT VIX-level | Bollerslev-Tauchen-Zhou 2009 RFS. VRP dominates VIX / P/E / default-spread / CAY at quarterly horizons. VIX-level alone is coincident not predictive. |
| **4** | Monetary-policy / liquidity regime | **Composite: Fed balance sheet (H.4.1) + bank reserves + RRP balance + M2 + FF futures path** | Bridgewater MP1/2/3 (Bob Prince framing) + Druckenmiller "liquidity primary" framework + Macrosynergy CB-liquidity backtests. |
| **5** | Dollar regime | **Trade-Weighted Broad Dollar (DTWEXBGS)** — NOT DXY | DXY's 1973-frozen 6-currency basket excludes CNY; structurally inferior for global dollar stress. DTWEXBGS is Fed's broader 26-currency measure. |
| **6** | Stock-bond correlation regime | Rolling 60-day correlation of S&P 500 returns vs 10y Treasury returns, **Forbes-Rigobon vol-corrected** | Recent academic literature flagged this as the single most important missing S0 feature. First sustained sign-flip to positive since late-1990s — captures real regime shift. Trivially derivable. |

### 4 method overlays (not new dimensions)

1. **BOCPD (Bayesian Online Change-Point Detection, Adams-MacKay 2007)** — open-source Python; ~1-2 day build. Calibrated probability of regime change at any point. Overlay across all 6 dimensions.
2. **Forbes-Rigobon vol-conditional correlation correction** — one-line math. **MUST apply to dimension #6 explicitly** to prevent spurious correlation-regime triggers in high-vol periods (well-documented bias).
3. **Surprises (actual − consensus / trailing trend) instead of raw levels** — applied to macro inputs in dimensions #1, #2, #4 (PMI, GDP, CPI, breakevens). Bridgewater's actual methodology classifies on surprises, not raw levels. Consensus data via DBnomics or scraped Bloomberg/Reuters previews.
4. **MSGARCH (R)** — production-grade vol-regime detection for advanced VaR/ES at v0.5+.

### Drops (folklore — explicitly NOT in S0)

- Raw VIX-level as primary (replaced by VRP)
- Bridgewater 2-axis 4-box standalone (replaced by 3-axis with monetary-policy as own dimension)
- Pástor-Stambaugh aggregate liquidity (failed Pontiff 2019 replication)
- CFTC COT as return predictor
- AAII bull-bear sentiment
- Network/graph regime detection (research-only)
- Deep-learning regime classifiers (Krauss-Fischer EJOR: Sharpe 5.8 pre-cost (1992-2009) → ~0 after costs post-2010)

### Tier-2 (defer to Phase 2, not in v0.1 S0)

- Cross-asset connectedness (Diebold-Yilmaz spillover index) — ~1 week build; correlated with #6 + #1 in v0.1
- Bear-asymmetric correlation (Longin-Solnik 2001) — different specific signal than #6; defer to learn from #6 first
- Factor crowding regime (Lou-Polk comomentum) — requires 13F ingestion + factor exposures
- NFCI as standalone dimension — highly correlated with EBP-anchored credit; redundant in v0.1
- Output gap (Cooper-Priestley 2009) — folds into Bridgewater 3-axis growth dimension

### Data-source mapping per dimension

All 6 Tier-1 dimensions buildable on free data. Total v0.1 incremental cost: $0/mo. See `.claude/references/empirical/data-sources/Q1-refined-recommendation.md` for full mapping.

| Dimension | Primary source | Cost | Existing project integration |
|---|---|---|---|
| 1 — EBP | Fed CSV at federalreserve.gov | Free | New trivial wrapper |
| 2 — NTFS | Compute from FRED zero-coupon curve OR neartermforwardspread.com | Free | `mcp__fred` + small computation |
| 3 — VRP | VIXCLS² (FRED) − realized variance from S&P daily returns | Free | `mcp__fred` + `mcp__market_data` + small computation |
| 4 — MP/liquidity | FRED (WALCL, RESBALNS, RRPONTSYD, M2SL, M2V) + Cboe FF futures | Free | `mcp__fred` + existing market data |
| 5 — DTWEXBGS | FRED `DTWEXBGS` | Free | `mcp__fred` already wired |
| 6 — Stock-bond correlation | Compute from `mcp__market_data` (S&P) + `mcp__fred` (10y yield) | Free | Small computation module |

### Recommended optional v0.1 spend

- **Tiingo Power $30/mo** — highest $/value in survey; news + IEX real-time + fundamentals (relevant to L4 catalyst tracking + L7 smart-money news flow)
- **Defer Polygon $79/mo** — only if v0.5+ requires real-time options chain
- **Schwab Trader API at v0.5+** — replaces Polygon at $0 if operator opens Schwab brokerage (free real-time options chains post-TDA)

Total v0.1 recommendation: **$75 Sharadar + $30 Tiingo = $105/mo; $145/mo headroom against $250 cap.**

---

## 3. Q2 LOCKED — How does S0 weight the 6 dimensions?

**Initial framing (REJECTED by operator):** HIGH / MEDIUM / LOW validation-depth tags with placeholder weights 1.0 / 0.7 / 0.5.

**Operator's pushback:** "Old is not proof of efficiency, young is not proof of evolution." Validation depth conflates "how long has this been studied" with "how well does it currently work" — these diverge.

**Empirical confirmation across 3 parallel Q2 subagents:** weighting decisions are scientifically inferior to equal-weight at our sample size by every major measure.

### Why equal-weight wins empirically at our scale

- **Smith-Wallis 2009** (forecast-combination puzzle): at small N, estimation error in optimal weights exceeds bias-reduction benefit
- **Claeskens-Magnus-Vasnev-Wang 2016** (theorem-level result): random/estimated weights induce both bias and variance inflation that exceed any optimization gain at small n
- **Hsiao-Wan 2014**: ≥100 observations needed just to estimate weights stably
- **Setzer-Fuchs 2024**: pure-OLS only outperforms equal-weight above N ≈ 200-300
- **Lee-Lee 2025 Monte Carlo**: even at T=1000, test rejects "equal-weight is no worse" in <50% of replications when truly-optimal weights are non-equal
- **Aiolfi-Timmermann 2006**: past forecasting performance is "frequently a poor predictor" of future performance (validation-depth is a stronger version of that premise — even worse)
- **T/K ≥ 20 rule**: for K=6 classifiers we'd need T ≥ 120 observations. Our 18-24 month timeline yields ~50.

### Q2 LOCKED — final architecture

**1. v0.1 weighting: pure 1/6 equal-weight** for the headline regime score across all 6 dimensions.

**2. Validation-depth tags retained ONLY in 3 narrow roles** (NOT as numerical multipliers):
   - Transparency annotations on each dimension's output ("validated 60yr / 15yr / 5yr" — INFO, not weight)
   - Trim-priority ordering — if pseudo-BMA+ later recommends trimming a classifier, LOW gets trimmed before HIGH
   - Differential monitoring cadence — LOW reviewed monthly, MEDIUM quarterly, HIGH semi-annually

**3. Per-dimension OOS performance tracked from day 1** in S2 (counterfactual ledger), enabling DM-tests at v0.5+.

**4. Shadow-run pseudo-BMA+ starting N≈30** (~12 months) for comparison only; promote to live weighting only if Bayes-factor > 20 vs equal-weight (Kass-Raftery 1995 strong-evidence threshold; ~5 correct calls in a row).

**5. At v0.5+ (N≈50): BB-pseudo-BMA+ with Diebold-Pauly shrinkage:**
```
w_final = (38 / (38 + N)) · w_equal_1/6  +  (N / (38 + N)) · w_pseudoBMA+
```
where `w_equal_1/6 = uniform 1/6` (NOT validation-depth-anchored, per operator's pushback). The shrinkage formula and prior-effective-sample-size = 38 (Morita-Thall-Müller 2008) framework retained from Bayesian-methods deep-dive.

**6. Classical BMA REJECTED** — assumes M-closed (one classifier IS the truth), empirically false for our 6 disjoint regime dimensions per Yao et al. 2018. pseudo-BMA+ and stacking handle the M-open case correctly.

**7. Pre-launch backtest on 2015-2025 data — OPTIONAL diagnostic, NOT a weight source.** It validates that each dimension *individually* classifies regimes correctly (sanity check). At our scale, backtested weights would be statistically indistinguishable from equal-weight.

### Sample-size phase transitions (locked)

- **N=0 to ~30 (months 0-12):** pure 1/6 equal-weight; per-dimension OOS performance accumulating in S2 ledger
- **N≈30 to ~50 (months 12-24):** equal-weight live; pseudo-BMA+ shadow-running; promote if BF > 20
- **N≥50 (months 18+):** BB-pseudo-BMA+ with Diebold-Pauly shrinkage formula above; equipoise at N≈38; data-dominance (>67%) at N≈75
- **`/parameters-review` annual:** weights updated based on live performance, NOT on validation depth

### Library deliverables for Q2 (all committed)

- `.claude/references/empirical/data-sources/Q2-ensemble-methods-research.md` (broad survey; 12 methods)
- `.claude/references/empirical/data-sources/Q2-bayesian-methods-deep.md` (374 lines; 7 Bayesian methods; BB-pseudo-BMA+ recommendation)
- `.claude/references/empirical/data-sources/Q2-equal-weight-puzzle-deep.md` (292 lines; 20 sources; strongest empirical case for equal-weight at our scale)

---

## 4. Q3 LOCKED — When does S0 fire a regime-shift event?

**Locked: hybrid materiality-tiered firing using BOCPD probability per dimension.**

BOCPD (Q1 method overlay #1) outputs calibrated change-point probability per dimension at every time step. Q3 specifies thresholds and confluence rules:

| Trigger | S0 action | Materiality | Downstream effect |
|---|---|---|---|
| 1 dimension's BOCPD > 0.7 sustained 2+ days | Push notification to P8 | M-2 | Targeted memo update on sensitivity-HIGH names |
| 2+ dimensions' BOCPD > 0.7 sustained 2+ days | Push notification to P8 + force re-underwrite queue | M-3 | Full P4 re-underwrite on sensitivity-HIGH names |
| Any catastrophic dimension event (BOCPD > 0.95 single-day) | Push notification to P8 + immediate operator alert | M-3 | Full re-underwrite + operator-attention flag |

**Why this design:**
- Aligns with Section 2's already-locked materiality-1/2/3 framework in P8
- Single-dimension shifts get operator awareness without expensive re-underwrites (M-2)
- Confluence (2+ dimensions) reserves expensive re-underwrite cost for high-conviction regime changes (M-3)
- Catastrophic single-day events bypass duration-smoothing for fast-acting events (March 2020 Treasury dysfunction; Aug 2024 carry unwind)

**Threshold values (informed by BOCPD literature):**
- 0.5 = "any change" baseline (too noisy)
- **0.7 = conventional sweet spot for live deployment** (locked)
- 0.9+ = "strong evidence" (used for catastrophic single-day flag at 0.95)

**Sustained-duration filter (2+ days):** prevents single-day BOCPD spikes from triggering re-underwrites; reserves immediate action for catastrophic events at 0.95+.

---

## 5. Q4 LOCKED — How often does L1 re-classify (refresh cadence)?

**Locked: daily refresh.**

S0 re-classifies every trading day using the latest available data per input. Slow inputs (monthly EBP, weekly H.4.1) use last published value; fast inputs (daily rates, VIX, DXY) use yesterday's close.

**Why daily:**
- Free MCP data (FRED, market_data) makes daily-pull marginal cost ~zero
- Aligns with Section 2's `/daily-monitor` cadence
- BOCPD is *online* by design — daily updates are its native cadence
- Daily classification produces meaningful output for fast-moving inputs (rates / vol / dollar / stock-bond correlation are 4 of 6 dimensions)
- Avoids weekly-cadence staleness risk during fast regime transitions
- Avoids event-driven threshold-tuning complexity

**Per-input cadence reality (S0 daily classification consumes whatever's latest):**

| Cadence | Inputs |
|---|---|
| Daily | FRED rates (DGS3MO, DGS10, T10Y3M, T10Y2Y, T5YIE, T10YIE), VIXCLS, S&P daily returns, 10y Treasury daily, DTWEXBGS, FX crosses |
| Weekly | NY Fed Staff Nowcast (Fridays), Fed H.4.1 balance sheet (Wednesdays), Sahm Rule revisions |
| Monthly | EBP CSV, ISM PMI, Core CPI / PCE, M2, INDPRO, U-Mich expectations |
| Quarterly | GDP, NBER recession dating revisions |

S0 daily classification combines all inputs at their respective freshness; BOCPD runs on the daily classification stream.

---

## 6. Library deliverables produced for Section 3

Under `.claude/references/empirical/data-sources/`:

- `00-overview.md` — Master overview of S0 data architecture
- `D1-economic-cycle.md` — Cycle dimension data sources
- `D2-credit-stress.md` — Credit dimension data sources
- `D3-vol-regime.md` — Vol dimension data sources
- `D4-dollar-regime.md` — Dollar dimension data sources
- `D5-bridgewater-4box.md` — Original 4-box research (folded into 3-axis monetary-policy + growth + inflation post-Q1 lock)
- `regime-dimensions-empirical-survey.md` — 14 dimensions ranked by edge
- `regime-dimensions-practitioner-survey.md` — 9 named PMs' methodologies
- `regime-detection-academic-frontier.md` — post-2020 methods (BOCPD, MSGARCH, etc.)
- `public-api-landscape.md` — 25 APIs surveyed
- `Q1-refined-recommendation.md` — locked Q1 recommendation
- `Q2-ensemble-methods-research.md` — first Q2 subagent's output

In flight (will be added on completion):
- `Q2-bayesian-methods-deep.md`
- `Q2-equal-weight-puzzle-deep.md`

---

## 7. Section 3 — fully closed

All 4 questions locked:
- **Q1 LOCKED:** 6 Tier-1 dimensions + 4 method overlays
- **Q2 LOCKED:** equal-weight at v0.1 → BB-pseudo-BMA+ with Diebold-Pauly shrinkage at v0.5+; validation-depth retained as annotations only, NOT numerical multipliers
- **Q3 LOCKED:** BOCPD-based hybrid materiality-tiered firing (M-2 single-dim; M-3 confluence; M-3 catastrophic single-day)
- **Q4 LOCKED:** daily refresh

Ready for Section 4 (L2 — Probabilistic scenario writing).

---

## 8. Implementation handoff (so far)

For the engineer building S0:

1. Read this document + `Q1-refined-recommendation.md` first.
2. Build trivial wrappers per dimension (most are FRED-direct; EBP needs CSV-fetch; stock-bond correlation needs 60-day rolling computation; MP/liquidity is multi-input composite).
3. Implement BOCPD as overlay (open-source Python implementations exist).
4. Apply Forbes-Rigobon correction to dimension #6 explicitly.
5. For dimension #4: build composite from Fed H.4.1 + bank reserves + RRP + M2 + FF futures path; document composite formula.
6. S0 outputs probability distribution per dimension (per Section 3 implicit lock — granular probabilities per Tetlock superforecaster discipline + Section 1 cross-lane synthesis S6).
7. Cache outputs in Postgres `regime_state` table; daily refresh; push events when Q3 logic locks.
8. **Drop HIGH/MEDIUM/LOW validation-depth tagging from architecture** (per operator's Q2 pushback).
9. **Add backtest step before launch** — score each dimension on 2015-2025 data; use as initial weighting priors at v0.5+ if pre-backtest path is locked in Q2.

---

**Section 3 is partially locked. Q1 is final. Q2 / Q3 / Q4 close after in-flight Q2 subagents return.**
