# Section 3 Consensus — L1 / S0 (Regime Capture Sidecar)

**Date:** 2026-04-29 (in progress)
**Session:** Q&A consensus review with operator (saehoon0501) — Section 3 of the consensus-documentation-protocol series
**Status:** Partially locked — Q1 closed; Q2 in progress; Q3 + Q4 pending
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

## 3. Q2 IN PROGRESS — How does S0 weight the 6 dimensions?

**Initial framing (REJECTED by operator):** HIGH / MEDIUM / LOW validation-depth tags with placeholder weights 1.0 / 0.7 / 0.5.

**Operator's pushback:** "Old is not proof of efficiency, young is not proof of evolution." Validation depth conflates "how long has this been studied" with "how well does it currently work" — these diverge (e.g., yield curve has 60-year validation but is degrading post-QE; stock-bond correlation has short attention but captures real recent regime shift).

**Replacement framing in development:** weight by **recent-OOS-accuracy** (last 5-10 years of resolved regime classifications), not historical validation depth.

### Implementation path being designed

- **v0.1 (zero resolved live predictions):** options under consideration:
  - Equal-weight at v0.1 (per first Q2 subagent finding: at small N, equal-weight dominates per Smith-Wallis 2009 / Claeskens 2016 / Stock-Watson 2004)
  - OR pre-launch backtest of each dimension on 2015-2025 data → use realized accuracy as initial Bayesian priors
- **v0.5+ (50+ resolved predictions):** Diebold-Pauly Bayesian shrinkage of OLS weights toward equal-weight (canonical academic recipe; first subagent's locked recommendation)
- **Annual `/parameters-review`:** weights updated based on live performance, NOT on validation depth

### Sample-size thresholds (literature-documented; first Q2 subagent)

- T < 30 → equal-weight dominates
- T ≈ 30-80 → Diebold-Pauly shrinkage with strong shrinkage intensity
- T > 100 → optimized weights become viable

### What's pending

Two depth subagents (Q2 Bayesian deep-dive + Q2 equal-weight puzzle) are still running. Once they return:
- Confirm or refine Diebold-Pauly recommendation
- Decide between (a) equal-weight at v0.1 with parallel backtest accumulating accuracy stats, OR (b) pre-backtest before launch with backtested-accuracy as initial priors, OR (c) further research on regime-classifier ground-truth measurement before locking

**Likely lock direction:** (a) or (b). Q2 closure expected after 2 in-flight subagents return.

### Library deliverables for Q2 so far

- `.claude/references/empirical/data-sources/Q2-ensemble-methods-research.md` (first Q2 subagent's output — 12 methods compared)
- `.claude/references/empirical/data-sources/Q2-bayesian-methods-deep.md` (in flight)
- `.claude/references/empirical/data-sources/Q2-equal-weight-puzzle-deep.md` (in flight)

---

## 4. Q3 PENDING — When does S0 fire a regime-shift event?

Section 2 Item 1 locked that S0 fires push events on regime shifts (forcing P1/P2 chain re-run on sensitivity-tagged-HIGH names + escalating P8 daily refresh). Section 3 specifies the **trigger threshold**.

Original options proposed (not yet locked):
- (a) Probability threshold (sensitive — fires on noise)
- (b) Threshold + duration (filters noisy flips)
- (c) Threshold + duration + signal-confluence (most conservative)

**Likely revision after Q1 lock:** **BOCPD probability threshold** (e.g., BOCPD > 0.7) — more principled than ad-hoc threshold+duration+confluence rule. BOCPD outputs calibrated change-point probabilities; meets the operator's preference for academically-grounded methods.

To be locked after Q2 closes.

---

## 5. Q4 PENDING — How often does L1 re-classify (refresh cadence)?

Section 2 set "≤5 trading days stale acceptable" but didn't lock cadence.

Original options proposed:
- (a) Daily — cleanest; matches `/daily-monitor`
- (b) Weekly — lower cost; staleness risk in fast markets
- (c) Event-driven — most efficient; complexity

**Likely lock:** **(a) daily.** Free MCP data sources (FRED, market_data) make daily-pull effectively zero-marginal-cost. Some inputs (M2, Fed balance sheet) are weekly, but most are daily. Locked when Q2 closes.

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

## 7. What's still open in Section 3

- **Q2 closure** — replace HIGH/MEDIUM/LOW framing with recent-OOS-accuracy framing; lock v0.1 weighting method (likely equal-weight or pre-backtest priors); lock v0.5+ method (Diebold-Pauly shrinkage)
- **Q3 closure** — likely BOCPD-probability threshold; lock specific threshold value
- **Q4 closure** — likely daily cadence with weekly inputs accepted as-they-publish

After Q2 / Q3 / Q4 lock, Section 3 closes and we move to Section 4 (L2 — Probabilistic scenario writing).

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
