# D5 — Bridgewater 4-box (Growth × Inflation) data sources

**Sidecar:** S0 regime context — Bridgewater 4-box (rising/falling growth × rising/falling inflation = 4 cells)
**Operator constraint:** $250/mo non-LLM budget; FRED + free public sources preferred.

---

## Growth indicators table

| Signal | Definition | Cost | Access | Latency | Existing MCP? | FRED series / endpoint |
|---|---|---|---|---|---|---|
| **ISM Manufacturing PMI** | Diffusion survey of ~400 manufacturing purchasing managers; >50 expansion, <50 contraction. Composite of new orders, production, employment, deliveries, inventories. | Free headline (paid for full historic deep-dive) | Direct from ISM press release (1st business day, 10:00 ET); FRED removed ISM series in 2016 (paywall dispute). Free mirror via Trading Economics, Investing.com, YCharts. | Monthly | No (FRED removed) | None on FRED. Source: ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/ |
| **ISM Services PMI** | Services-sector equivalent of manufacturing PMI; survey of non-manufacturing supply executives. >50 expansion. | Free headline | Direct from ISM press release (3rd business day, 10:00 ET); same FRED-removal status as manufacturing. | Monthly | No | None on FRED. Source: same ISM URL. |
| **S&P Global US Manufacturing PMI (flash)** | Alternative manufacturing PMI; **earlier release** (~3rd-to-last business day of month) than ISM. Headline diffusion >50/<50. | Free headline; paid sub-indices/history | Press release at pmi.spglobal.com (free); full history paywalled (contact economics@spglobal.com). | Monthly (flash + final) | No | Not on FRED. URL: pmi.spglobal.com |
| **S&P Global US Services PMI (flash)** | Services counterpart; same release cadence as manufacturing flash. | Free headline | Same as above. | Monthly (flash + final) | No | pmi.spglobal.com |
| **Conference Board LEI** | 10-component composite leading index (avg weekly hours, jobless claims, ISM new orders, building permits, S&P 500, Leading Credit Index, 10y-FFR spread, consumer expectations, etc.). Predicts business-cycle turns ~7 months ahead. | Press release free; data feed paid (member-only Data Central) | Monthly press release on conference-board.org. Historical full series requires membership. | Monthly | No | Not on FRED (Conference Board does not authorize redistribution). State-level proxy USSLIND (Philly Fed) is on FRED. |
| **Atlanta Fed GDPNow** | Real-time nowcast of current-quarter GDP growth, updated multiple times per quarter as new data arrives. Bridge between data releases and BEA's official release. | Free | FRED `GDPNOW` (free API via mcp__fred); Atlanta Fed page atlantafed.org/cqer/research/gdpnow; ALFRED for vintages. | Updated 6–7x per month within current quarter | **Yes — mcp__fred** | `GDPNOW` |
| **NY Fed Staff Nowcast** | Alternative GDP nowcast using dynamic factor model on broad set of macro/financial data. Resumed in 2023 after COVID-suspension. Active for 2026. | Free | xlsx download: newyorkfed.org/medialibrary/Research/Interactives/Data/NowCast/Downloads/New-York-Fed-Staff-Nowcast_download_data.xlsx; main page newyorkfed.org/research/policy/nowcast | Weekly (Friday) | No (need direct download) | Not on FRED. Direct xlsx URL. |
| **St. Louis Fed Economic News Index** | Third nowcast (text-mining of economic news). Published on FRED. | Free | FRED `STLENI` | Monthly | **Yes — mcp__fred** | `STLENI` |
| **Earnings revisions breadth (S&P 500)** | Net % of analysts revising EPS estimates up minus down. Measures consensus growth direction. Yardeni publishes a free 3-month moving-average composite (NERI) using I/B/E/S/Refinitiv data. | Free (Yardeni public PDFs); native I/B/E/S/FactSet/Refinitiv = paid | Yardeni weekly PDF: yardeni.com/pub/peacocksp500revisions.pdf (and archive.yardeni.com mirror). 4-week free trial then paid for full chart library. | Weekly | No | Yardeni "S&P 500 Sectors Net Earnings Revisions" PDF |
| **Coincident Economic Index (CEI)** | Conference Board: payroll employment + personal income less transfers + manufacturing & trade sales + industrial production. Indicates current state of economy. | Press release free; data feed paid | conference-board.org. Free FRED proxies: components individually (`PAYEMS`, `INDPRO`, `RPI`, real M&T sales). Philly Fed publishes alternative real-time **ADS Business Conditions Index** (free). | Monthly (CEI); daily (ADS) | **Yes for components** (mcp__fred) | Components: `PAYEMS`, `INDPRO`, `W875RX1`. ADS at philadelphiafed.org/surveys-and-data/real-time-data-research/ads |
| **Industrial Production Index (INDPRO)** | Real output of US manufacturing (73%), mining (16%), utilities (11%). Base 2017=100, seasonally adjusted, 100+ years of data. NBER recession-aligned. | Free | FRED `INDPRO` | Monthly | **Yes — mcp__fred** | `INDPRO` |

---

## Inflation indicators table

| Signal | Definition | Cost | Access | Latency | Existing MCP? | FRED series / endpoint |
|---|---|---|---|---|---|---|
| **Core CPI YoY** | CPI All Urban Consumers, less food & energy. BLS. Year-over-year % change. | Free | FRED `CPILFESL` (level); compute YoY = pct_change(12). | Monthly (mid-month BLS release) | **Yes — mcp__fred** | `CPILFESL` |
| **Core PCE YoY** | Fed's preferred inflation gauge. PCE chain-type price index ex food & energy. BEA. | Free | FRED `PCEPILFE` (level); compute YoY. | Monthly (last week of month, BEA release) | **Yes — mcp__fred** | `PCEPILFE` |
| **5y inflation breakeven (T5YIE)** | 5y Treasury nominal yield minus 5y TIPS yield = market-implied 5y avg inflation. Range 2003-present. | Free | FRED `T5YIE` | Daily | **Yes — mcp__fred** | `T5YIE` |
| **10y inflation breakeven (T10YIE)** | Same construction over 10y horizon. As of 2026-03-13: 2.36%. | Free | FRED `T10YIE` | Daily | **Yes — mcp__fred** | `T10YIE` |
| **5y5y forward inflation (T5YIFR)** | Avg expected inflation over the 5-year period beginning 5 years from today. Tracks long-run inflation expectations anchoring. As of 2026-03-13: 2.11%. | Free | FRED `T5YIFR` | Daily | **Yes — mcp__fred** | `T5YIFR` |
| **Trimmed-Mean PCE (Dallas Fed)** | Robust-to-outliers core PCE: trims 24% lower-tail, 31% upper-tail. Smoother signal than core PCE. | Free | FRED `PCETRIM12M159SFRBDAL` (12m % chg) | Monthly | **Yes — mcp__fred** | `PCETRIM12M159SFRBDAL` |
| **16% Trimmed-Mean CPI (Cleveland Fed)** | Cleveland Fed's robust core CPI. | Free | FRED `TRMMEANCPIM159SFRBCLE` | Monthly | **Yes — mcp__fred** | `TRMMEANCPIM159SFRBCLE` |
| **Median CPI (Cleveland Fed)** | Median monthly price change across CPI components. | Free | FRED `MEDCPIM159SFRBCLE` (Cleveland Fed page) | Monthly | **Yes — mcp__fred** | `MEDCPIM159SFRBCLE` |
| **Atlanta Fed Sticky-Price CPI (core)** | CPI subset of goods/services that change price infrequently → embeds inflation expectations. Range 1968-present. | Free | FRED `CORESTICKM159SFRBATL` (12m %); also `STICKCPIM159SFRBATL` (headline). | Monthly | **Yes — mcp__fred** | `CORESTICKM159SFRBATL` |
| **Producer Price Index (PPIFIS)** | PPI Final Demand — upstream price pressure that often leads consumer prices. | Free | FRED `PPIFIS` (Nov-2009 onwards); `PPIACO` (All Commodities, 1913-present). | Monthly (BLS) | **Yes — mcp__fred** | `PPIFIS`, `PPIACO` |
| **U Michigan 1y inflation expectations** | Median 1y-ahead inflation expectation from monthly Surveys of Consumers. | Free | FRED `MICH` | Monthly (preliminary mid-month + final) | **Yes — mcp__fred** | `MICH` |
| **ISM Manufacturing Prices Paid** | Diffusion subindex from ISM survey: % responding higher prices + ½ same. Direct inflation-direction signal from purchasing managers. | Free headline | Trading Economics, Investing.com, YCharts (FRED removed). Released same-day as ISM Manufacturing PMI. | Monthly | No | tradingeconomics.com/united-states/ism-manufacturing-prices |

---

## Composite construction

### Bridgewater's actual methodology (public-domain summary)

Bridgewater's All-Weather framework, developed by Ray Dalio, Bob Prince, and Greg Jensen (formalized late 1990s), classifies the macro environment along **two axes only**: **growth** and **inflation**, each measured as **deviation from market-discounted expectations**, not absolute level. The four quadrants:

|  | Growth ↑ vs expectations | Growth ↓ vs expectations |
|---|---|---|
| **Inflation ↑ vs expectations** | Stocks ≈ neutral; commodities, IL bonds, EM debt favored | Cash, commodities, IL bonds favored (stagflation) |
| **Inflation ↓ vs expectations** | Stocks, credit favored (Goldilocks) | Nominal bonds favored (deflation/recession) |

Bridgewater specifically does NOT classify on raw level (e.g., "GDP > 2% = rising") because asset prices already reflect consensus. The classifier is **direction of surprise** — actuals/nowcasts vs. consensus or vs. trailing trend. Risk-parity sizing then puts equal risk-budget on each of the four cells.

Sources: Bridgewater "All Weather Story" white paper (bridgewater.com); Dalio's *Principles for Navigating Big Debt Crises*; Prince's interviews on cyclical machine.

### Practical composite for our system (simplified)

**Growth direction (rising / falling):**
1. **Composite-of-nowcasts** (z-score average): GDPNow + NY Fed Nowcast + STLENI. If Δ(7d) > 0 → growth-rising tilt.
2. **Survey breadth**: ISM Manufacturing PMI level vs 50, ISM Services PMI level vs 50, S&P Global flash PMI level vs 50. Count ≥2-of-3 above 50 → expansion.
3. **Hard-data trend**: INDPRO 3m/3m annualized; PAYEMS 3m moving average. If both rising → expansion.
4. **Forward-looking**: Conference Board LEI 6m % change (from press release). LEI declining ≥0.3% → recession risk per Conference Board's own decision rule.
5. **Earnings revisions** (Yardeni NERI 3m MA): >0 → growth-rising tilt; <0 → growth-falling. Cross-validates surveys.

**Aggregation rule**: weighted-majority of the 5 buckets (each contributes one vote: rising / falling / neutral). Output: **rising | falling | neutral**.

**Inflation direction (rising / falling):**
1. **Realized core**: 3m annualized of core CPI (`CPILFESL`) and core PCE (`PCEPILFE`). Both accelerating → rising.
2. **Robust core**: 3m annualized of Trimmed-Mean PCE (`PCETRIM12M159SFRBDAL`) and Sticky-Price core CPI (`CORESTICKM159SFRBATL`). Cross-checks signal isn't outlier-driven.
3. **Upstream**: PPIFIS 3m annualized; ISM Manufacturing Prices Paid level (>50 = upstream pressure rising).
4. **Expectations**: T5YIE Δ(30d), T10YIE Δ(30d), MICH Δ(monthly). Breakeven curves widening → rising.
5. **Long-run anchor**: T5YIFR (5y5y forward) — anchor check; only flag if it breaks out of 1.8-2.5% historical range.

**Aggregation rule**: weighted-majority across 5 buckets. Output: **rising | falling | neutral**.

**Final output**: 4-cell classification (Growth × Inflation), updated daily for breakeven/nowcast components and monthly on PMI/CPI/PCE release dates.

---

## Recommended priority

### Tier 1 — must-have (all free, all on mcp__fred or one direct download)
1. `GDPNOW` (Atlanta Fed nowcast) — mcp__fred
2. `INDPRO` (Industrial Production) — mcp__fred
3. `CPILFESL` (Core CPI level) — mcp__fred
4. `PCEPILFE` (Core PCE level) — mcp__fred
5. `T5YIE`, `T10YIE`, `T5YIFR` (breakevens & forward) — mcp__fred
6. `PCETRIM12M159SFRBDAL` (Trimmed-Mean PCE) — mcp__fred
7. `CORESTICKM159SFRBATL` (Sticky-Price core CPI) — mcp__fred
8. `MICH` (UMich 1y expectations) — mcp__fred
9. `PPIFIS` (PPI Final Demand) — mcp__fred
10. **ISM Manufacturing PMI headline** — direct scrape from Trading Economics or ISM press-release page (monthly, scriptable)
11. **ISM Services PMI headline** — same
12. **NY Fed Nowcast** — direct xlsx download (weekly, scriptable)

### Tier 2 — nice-to-have
- `STLENI` (St. Louis Fed Economic News Index) — mcp__fred — adds nowcast diversity
- `PPIACO` (PPI All Commodities) — mcp__fred — long history for cycle work
- `MEDCPIM159SFRBCLE`, `TRMMEANCPIM159SFRBCLE` (Cleveland Fed median + trimmed CPI) — mcp__fred
- **ADS Business Conditions Index** (Philly Fed) — free, daily — direct download — substitutes for paywalled CEI
- **S&P Global flash PMI headline** — free press release — earlier release than ISM, useful for time-sensitivity
- **Yardeni NERI** — free weekly PDF scrape — best free earnings-revisions substitute
- **ISM Manufacturing Prices Paid subindex** — free Trading Economics scrape — direct inflation-direction signal
- **Conference Board LEI** — free press-release scrape (1 number per month: 6m % change)

### Skip / unaffordable / defer
- **FactSet / Refinitiv / IBES native earnings revisions** — paid (~$1k+/mo). Replaced by Yardeni free PDF. Skip.
- **Conference Board CEI/LEI deep dataset (Data Central)** — member-only paid. Replaced by FRED component reconstruction (`PAYEMS`+`INDPRO`+`RPI`+real M&T sales) or ADS index. Skip the paid version.
- **S&P Global PMI sub-indices and full history** — paid. Headline alone is sufficient. Skip sub-indices.
- **ISM historical deep-archive** — paid. Headline is free. Skip.
- **Estimize** — service status uncertain (acquired by Nasdaq, free tier degraded post-2021). Skip.

---

## Notes & caveats

- **Earnings revisions data is the only paid-by-default signal.** Best free substitute found: **Yardeni Research's "S&P 500 Sectors Net Earnings Revisions" weekly PDF** at archive.yardeni.com/pub/peacocksp500revisions.pdf. Yardeni computes NERI = (estimates-up − estimates-down) / total estimates, with a 3-month moving average. Built on I/B/E/S/Refinitiv data but published publicly. Yardeni also offers a 4-week free trial of the full chart library at yardeni.com. Other free fallbacks: Zacks Rank pages (per-ticker, not breadth), AAII screens (top-30 lists, not aggregate). FactSet's free public weekly "Earnings Insight" PDF (factset.com/earningsinsight) is also useful but emphasizes EPS growth rates rather than revision breadth.

- **ISM PMI**: ISM removed all 22 series from FRED in June 2016 over a redistribution dispute. Headline figures remain free direct from ISM press releases (1st business day of month for manufacturing, 3rd for services). Deep historical access (>5 years) requires paid ISM membership. Trading Economics, Investing.com, and YCharts mirror current and recent values for free. Operationally: scrape the ISM press release page on release day, or use Trading Economics' public table.

- **PMI Prices Paid subindex** is a genuinely useful inflation-direction signal not covered in the original 18-signal scope but worth including. It appears in the ISM press release alongside the headline; free via Trading Economics' page tradingeconomics.com/united-states/ism-manufacturing-prices.

- **Conference Board LEI/CEI**: Press release with the headline 6-month % change is free; the underlying full data series requires Data Central membership. For LEI, the press-release headline suffices for regime classification. For CEI, FRED-based reconstruction from components (`PAYEMS`, `INDPRO`, real personal income `W875RX1`, real M&T sales) gives equivalent signal for free. **Philly Fed's ADS Business Conditions Index** is a strong free real-time substitute, updated daily as new component data arrives.

- **GDPNow vs NY Fed Nowcast**: Both are free; using both gives ensemble robustness and divergence-as-signal. GDPNow is on FRED (`GDPNOW`); NY Fed publishes weekly Friday xlsx at a static URL.

- **Breakeven inflation expectations** (T5YIE, T10YIE, T5YIFR) start in 2003 (TIPS-implied). For pre-2003 macro regime work, use survey-based UMich expectations (`MICH`, 1978+) and/or 10y nominal Treasury yield − rolling realized core CPI as proxy.

- **Bridgewater's "deviation from expectations" framing**: To approximate Bridgewater's actual methodology (rather than raw-level classification), each indicator should be evaluated as `actual − consensus_or_trend`. For nowcasts, this is automatic (nowcast revisions are themselves surprise). For CPI/PCE, compare BLS/BEA release to Bloomberg consensus (paid) or to a trailing 6m moving average (free proxy). For PMI, compare to consensus from FX street/Investing.com economic calendar (free). This refinement materially improves classifier accuracy vs. raw-level rules.

- **Update frequency mismatch**: Breakevens are daily, PMI/CPI/PCE are monthly, GDPNow is sub-monthly. Run the classifier daily but only fire regime-change alerts when a slow-moving indicator (CPI, PCE, PMI) confirms a fast-moving one (breakevens, nowcast). Avoid whipsaws.

---

## Sources cited

- FRED series pages (St. Louis Fed): fred.stlouisfed.org/series/{INDPRO, GDPNOW, STLENI, CPILFESL, PCEPILFE, T5YIE, T10YIE, T5YIFR, PCETRIM12M159SFRBDAL, CORESTICKM159SFRBATL, STICKCPIM159SFRBATL, TRMMEANCPIM159SFRBCLE, MEDCPIM159SFRBCLE, PPIFIS, PPIACO, MICH, USSLIND, PAYEMS, W875RX1}
- St. Louis Fed announcement on ISM data removal (2016): news.research.stlouisfed.org/2016/06/institute-for-supply-management-data-to-be-removed-from-fred/
- Atlanta Fed GDPNow: atlantafed.org/cqer/research/gdpnow
- NY Fed Nowcast: newyorkfed.org/research/policy/nowcast (weekly xlsx download)
- Philly Fed ADS index: philadelphiafed.org/surveys-and-data/real-time-data-research/ads
- Conference Board US Leading Indicators: conference-board.org/topics/us-leading-indicators/
- ISM PMI Reports: ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/ (login-walled for full archive)
- S&P Global PMI: pmi.spglobal.com
- Yardeni Net Earnings Revisions PDF: archive.yardeni.com/pub/peacocksp500revisions.pdf
- FactSet Earnings Insight (alt free weekly): factset.com/earningsinsight
- Bridgewater All Weather Story: bridgewater.com/_document/the-all-weather-story
- Trading Economics ISM Prices Paid mirror: tradingeconomics.com/united-states/ism-manufacturing-prices
