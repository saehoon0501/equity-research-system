# Q1 Refined Recommendation — S0 Output Dimensions

**Date:** 2026-04-29
**Purpose:** Reshape Section 3 Q1 ("which output dimensions does S0 produce?") with empirically-justified, API-availability-gated recommendations after 4-subagent breadth-then-depth research.

**Predecessor:** Original Q1 framed S0 as 3 / 4 / 5-dimension trade-off. Operator pushed back with "why not (b)?" → research surfaced that the question was wrong: it's not "how many of the original 5" but **"which dimensions are empirically validated AND independently informative AND implementable at our scale."** Answer is different.

---

## 1. Research process recap

Four parallel subagents:

| # | Subagent | Output |
|---|---|---|
| 1 | Empirical effectiveness survey | 14 dimensions ranked by OOS edge; identified VRP, NFCI, output gap, bear-asymmetric correlation as additions; identified Pástor-Stambaugh liquidity, CFTC COT, AAII bearish, raw VIX-level as folklore-to-drop |
| 2 | Practitioner methodology survey | 9 named practitioners; **3-axis (growth × inflation × monetary-policy/liquidity) better validated than 2-axis 4-box** ; consensus dimensions are growth + inflation + MP/liquidity + credit |
| 3 | Academic frontier (post-2020) | BOCPD, Diebold-Yilmaz, MSGARCH, Forbes-Rigobon implementable at our scale; deep-learning regime classifiers don't survive cost-after-2010; **stock-bond correlation regime flagged as single most important missing S0 feature** |
| 4 | Public API landscape | Tiingo Power $30/mo highest $/value; Polygon $79/mo only if D3 real-time options needed; Schwab Trader API free real-time options if operator opens Schwab brokerage; Databento institutional-overkill |

---

## 2. The reshaped Q1 answer — 6 Tier-1 dimensions (not 4 or 5)

The original Q1 (3 / 4 / 5 dimensions) was framed against my initial 5-candidate list (cycle / credit / vol / dollar / 4-box). Research shows that list had two problems:

1. **The 2-axis 4-box should be replaced with a 3-axis decomposition** (growth × inflation × monetary-policy/liquidity) — practitioner consensus + Bob Prince MP1/2/3 overlay + Druckenmiller treating liquidity as primary
2. **A correlation-regime dimension is missing** — both #19 and #21 independently surfaced this; #21 specifically called stock-bond correlation regime the single most important missing S0 feature

After reshaping:

### Tier-1 (6 dimensions, all must be in S0)

| # | Dimension | Primary signal | Why this signal (over alternatives) | Empirical anchor |
|---|---|---|---|---|
| **1** | **Credit regime** | Excess Bond Premium (EBP) | EBP is the part of credit spreads NOT explained by default risk; pure stress signal. Single highest-edge dimension across 14 surveyed. Survives post-QE; survives Bordo-Haubrich 2019 OOS horserace; bivariate with NTFS is Fed's strongest model | Gilchrist-Zakrajšek 2012 AER; Favara et al. 2016 FEDS; Bordo-Haubrich 2019 |
| **2** | **Economic-cycle regime** | Near-Term Forward Spread (NTFS) | Engstrom-Sharpe show NTFS dominates 10y-3m for recession AND 4-quarter equity returns; 2022-23 episode validated NTFS while 10y-3m gave false positive | Engstrom-Sharpe 2018 FEDS; "(Don't Fear) The Yield Curve, Reprise" 2022 FEDS Notes |
| **3** | **Vol regime** | Variance Risk Premium (VRP = VIX² − realized variance) | NOT VIX-level (which is coincident, not predictive). VRP dominates VIX / P/E / default-spread / CAY at quarterly horizons; orthogonal information | Bollerslev-Tauchen-Zhou 2009 RFS |
| **4** | **Monetary-policy / liquidity regime** | Bank reserves + RRP balance + M2 velocity + Fed balance-sheet trajectory | 3rd axis surfaced by practitioner consensus. Druckenmiller treats as primary, not derivative. Bob Prince MP1/2/3 framework adds explicitly to Bridgewater 4-box | Bridgewater "All Weather" + Prince MP1/2/3; Druckenmiller "Hard Lessons" 2026; Macrosynergy CB-liquidity backtests |
| **5** | **Dollar regime** | Trade-Weighted Broad Dollar (DTWEXBGS), NOT DXY | DXY's 1973-frozen 6-currency basket excludes CNY; structurally inferior for measuring global dollar-stress. DTWEXBGS is Fed's broad measure including 26 currencies | D4 subagent finding (already in spec); confirms L1 patterns #23, #25 |
| **6** | **Stock-bond correlation regime** | Rolling 60-day stock-bond return correlation, sign-flagged | Trivially derivable from existing data. First sustained sign-flip to positive since late-1990s. Highest-conviction missing S0 feature per #21 academic-frontier subagent | Recent academic literature on correlation regimes; #21 subagent |

### Tier-2 (defer to Phase 2, not in v0.1 S0)

| # | Dimension | Why defer |
|---|---|---|
| 7 | Cross-asset connectedness (Diebold-Yilmaz spillover index) | ~1 week build; medium conviction; correlated with #6 stock-bond + #1 credit; add only if signal-divergence emerges |
| 8 | Bear-asymmetric correlation (Longin-Solnik 2001) | Different specific signal than #6; #19 surveyed but #21 didn't elevate; defer to learn from #6 first |
| 9 | Factor crowding regime (Lou-Polk comomentum) | Requires 13F ingestion + factor exposures in strategy — neither exists yet |
| 10 | NFCI as standalone dimension | Highly correlated with EBP-anchored credit regime; redundant in v0.1; revisit if EBP-only credit dimension proves blind to a specific regime |
| 11 | Output gap (Cooper-Priestley 2009) | Survived OOS but is a slower / lower-frequency signal; folds into Bridgewater 3-axis growth dimension |

### Drop (folklore — explicitly NOT in S0)

| Signal | Why drop |
|---|---|
| **Raw VIX-level as primary** | Coincident not leading; replaced by VRP |
| **Bridgewater 2-axis 4-box as standalone** | Replaced by 3-axis growth × inflation × monetary-policy/liquidity |
| **Pástor-Stambaugh aggregate liquidity** | Failed Pontiff 2019 replication |
| **CFTC COT as return predictor** | No documented edge that survives modern OOS |
| **AAII bull-bear sentiment** | No edge as price predictor |
| **Network/graph-based regime detection** | Research-only; awaits replication |
| **Deep-learning regime classifiers** (LSTM/Transformer/SPDNet/CRBM/ORCA) | Krauss-Fischer EJOR: Sharpe 5.8 pre-cost (1992-2009) → ~0 after costs post-2010 |

---

## 3. Method additions (S0 architecture, not new dimensions)

These apply to multiple dimensions and add signal-quality without adding a dimension count:

| Method | Applies to | Effort | Why add |
|---|---|---|---|
| **BOCPD (Bayesian Online Change-Point Detection)** | Overlay on all 6 dimensions | ~1-2 day build (open-source) | Calibrated probability of regime change at any point; supplements per-dimension classification with cross-dimension regime-shift detection |
| **Forbes-Rigobon vol-conditional correlation correction** | Dimension #6 (stock-bond correlation) and any future correlation-regime add | One-line math | Without this, correlation regime triggers spuriously during high-vol periods (well-documented bias); MUST apply to dimension #6 |
| **Surprises (actual − consensus / trailing trend) instead of raw levels** | Dimensions #1, #2, #4 (regimes that involve macro inputs like PMI, GDP, CPI, breakevens) | Trivial; consensus data via DBnomics or scraped from Bloomberg/Reuters previews | Bridgewater's actual methodology classifies on surprises, not raw levels. PMI > 50 is crude; PMI > consensus is what the 4-box framework actually uses |
| **MSGARCH** | Dimension #3 (vol regime) for state-of-art VaR/ES | R package, production-grade | Vol-regime detection beyond simple thresholding; useful when D3 needs to size positions by vol regime |

---

## 4. Data-source mapping per dimension

| Dimension | Primary source | Latency | Cost | Existing project integration |
|---|---|---|---|---|
| 1 — Credit (EBP) | Fed CSV at federalreserve.gov | Monthly | Free | Trivial CSV-fetch wrapper (already flagged in D2 + D1 reports); shared dependency |
| 2 — Cycle (NTFS) | Compute from FRED zero-coupon curve OR neartermforwardspread.com sheet | Daily | Free | `mcp__fred` for inputs; small computation module |
| 3 — Vol (VRP) | Compute: VIXCLS² (FRED) − realized variance from S&P 500 daily returns | Daily | Free | `mcp__fred` (VIXCLS) + `mcp__market_data` (SPY/^GSPC daily prices) |
| 4 — Monetary policy / liquidity | Multi-input: Fed H.4.1 (balance sheet), bank reserves (FRED WALCL, RESBALNS), RRP (FRED RRPONTSYD), M2 (M2SL, M2V), policy-rate path (FF futures from Cboe) | Weekly to daily | Free for FRED inputs; FF futures need market_data | `mcp__fred` for most; Cboe FF futures via existing market-data |
| 5 — Dollar (DTWEXBGS) | FRED `DTWEXBGS` | Daily | Free | `mcp__fred` — already wired |
| 6 — Stock-bond correlation regime | Compute: rolling 60-day correlation of S&P 500 daily returns vs 10-year Treasury daily returns | Daily | Free | `mcp__market_data` (S&P 500) + `mcp__fred` (10y yield → derive returns); small computation module |

**Total data-source cost:** $0/mo new spend. All 6 dimensions buildable on free data.

---

## 5. Recommended optional spend within budget

Operator's $250/mo budget is mostly uncommitted. Highest-leverage additions:

| Add | Cost | What it unlocks |
|---|---|---|
| **Tiingo Power** | $30/mo | News (for L4 catalyst tracking + L7 smart-money news flow) + IEX real-time + fundamentals; **highest $/value in survey** |
| **(Optional) Polygon Developer** | $79/mo | Real-time options chain + IV term structure; **only needed if D3 vol regime requires real-time options data**, which v0.1 doesn't (VRP works on daily VIX + realized variance) |

**Recommended v0.1 spend:** $30/mo Tiingo on top of $75/mo Sharadar = **$105/mo total, $145/mo headroom**.

**Defer Polygon** until v0.5+ when entry execution may need real-time options. **Schwab Trader API at v0.5+** would replace Polygon at $0 if operator opens a Schwab brokerage account (post-TDA, the API is high-quality with free real-time options chains + 15-year daily history).

---

## 6. Comparison to original Q1 framing

Original Q1 asked operator to pick (a) 3 / (b) 5 / (c) 4 dimensions out of {cycle, credit, vol, dollar, 4-box}.

**Research result:** none of those 3 options was right. The reshaped answer:

- **Drop the 4-box dimension as standalone**; replace with 3-axis (growth × inflation × monetary-policy/liquidity) where monetary-policy/liquidity is its own Tier-1 dimension #4
- **Add stock-bond correlation regime** as Tier-1 dimension #6 (not in original list)
- **Replace specific signals within dimensions:** NTFS not 10y-3m for cycle; VRP not VIX-level for vol; DTWEXBGS not DXY for dollar; EBP for credit (already correct)
- **Add 3 method overlays:** BOCPD, Forbes-Rigobon correction, surprises-not-levels for macro inputs

Net: **6 Tier-1 dimensions** (not 5; not 4; not 3) **with refined signal selection AND method overlays**. Implementable on free data + $30/mo Tiingo.

---

## 7. What's still open (Q2-Q4 of Section 3)

The research informs but doesn't decide:

- **Q2 (post-QE uncertainty caveat):** confidence haircut still recommended approach; data-source research validated that EBP survives post-QE and NTFS handles 2022-23 false positive — both reduce reliance on the haircut
- **Q3 (regime-shift event-fire threshold):** BOCPD finding is highly relevant — BOCPD outputs calibrated probabilities, so we can use a BOCPD-probability threshold (e.g., >0.7) instead of the rigid threshold+duration+confluence rule I proposed
- **Q4 (refresh cadence):** daily remains the recommendation; some inputs (M2, Fed balance sheet) are weekly, but most are daily and S0 should re-classify daily

---

## 8. Implementation handoff

For the engineer building the S0 sidecar:

1. Read `00-overview.md` master data-source overview first.
2. Build trivial wrappers per dimension (most are FRED-direct; EBP needs CSV-fetch; stock-bond correlation needs 60-day rolling computation).
3. Implement BOCPD as overlay (Adams-MacKay 2007; open-source Python implementations exist).
4. Apply Forbes-Rigobon correction to dimension #6 explicitly (one-line vol-normalization).
5. For dimension #4 monetary-policy/liquidity: build composite from Fed H.4.1 + bank reserves + RRP + M2 + FF futures path; document the composite formula in skill prompts.
6. S0 outputs probability distribution per dimension (per Section 3 Q3 lock — granular probabilities per Tetlock superforecaster discipline).
7. Cache outputs in Postgres `regime_state` table; daily refresh; push events on regime-shift confluence (BOCPD-probability > threshold).

---

**End of Q1 reshaped recommendation.**
