# D1 — Economic-cycle data sources

Research dimension: **Economic-cycle** sub-block of the S0 regime context sidecar.
Last refreshed: 2026-04-27.
Operator constraint: total non-LLM tooling budget $250/mo; $75/mo already spent on Sharadar via `mcp__fundamentals`.
This document covers **only** the source-of-truth question (where does the data come from, can we get it, what does it cost, is it already wired). Empirical-edge claims point back to the L1 regime-capture lit review for receipts.

---

## Signal-by-signal table

| # | Signal | Definition | Empirical edge (per L1 lit) | Cost | Access | Latency | Existing MCP? | FRED series / endpoint |
|---|---|---|---|---|---|---|---|---|
| 1 | **10y–3m Treasury spread** | 10-year constant-maturity Treasury yield minus 3-month T-bill yield | Estrella-Mishkin 1996/1998: spread 4Q-ahead is the single best single-variable recession predictor pre-2007; still the spread the NY Fed's official recession-prob model uses | Free | FRED API via `mcp__fred.get_series` | Daily (T+1) | Yes | `T10Y3M` (daily) / `T10Y3MM` (monthly) |
| 2 | **2y–10y Treasury spread** | 10-year minus 2-year constant-maturity Treasury yield | Popularly cited; tends to invert earlier than 10y-3m and stays inverted longer; weaker out-of-sample edge than 10y-3m per Engstrom-Sharpe 2018 | Free | FRED API via `mcp__fred.get_series` | Daily (T+1) | Yes | `T10Y2Y` (daily) / `T10Y2YM` (monthly) |
| 3 | **Near-Term Forward Spread (NTFS)** | 6-quarter-ahead forward 3-month Treasury yield minus current 3-month T-bill yield (Engstrom-Sharpe 2018, Fed FEDS 2018-055) | Engstrom-Sharpe argue NTFS dominates 10y-3m on out-of-sample recession prediction and also predicts 4Q GDP growth & equity returns | Free | (a) Fed Board H.15 + Gürkaynak-Sack-Wright zero curve (compute ourselves), or (b) `neartermforwardspread.com` Google Sheets link | Weekly (Wed 8am ET, after Fed Board H.15 weekly release) | **No — not on FRED**; would need to compute from `DGS3MO` + GSW forward-rate parameters, or scrape the Engstrom site | n/a — not a single FRED series |
| 4 | **Excess Bond Premium (EBP)** | Gilchrist-Zakrajšek 2012 corporate-bond credit-spread residual after pricing default risk; Fed Board updates monthly | GZ 2012: EBP has predictive power for IP, employment, and recession that traditional credit spreads lack; Fed Board updates also publish a model-implied recession-prob alongside | Free | Public CSV at `https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv` | Monthly, posted ~10am ET on the 4th business day of each month | **No** — would need a thin HTTP fetcher or store as a static CSV pull (not a FRED series) | n/a — direct Fed Board CSV |
| 5 | **Sahm Rule** | 3-month MA of U-3 unemployment rate ≥ 0.5pp above its trailing-12m low | Sahm 2019: trips at recession start with ~zero false positives historically (1959–2019, 2 false positives across 11 recessions); 2024 print ≥0.5 known to have weakened slightly post-COVID due to labor-supply distortions | Free | FRED API via `mcp__fred.get_series` | Monthly (BLS Employment Situation, first Friday) | Yes | `SAHMREALTIME` (real-time vintages, preferred for backtest contamination control) and `SAHMCURRENT` (latest-revision) |
| 6 | **Conference Board LEI** | Composite of 10 leading indicators (avg weekly hours mfg, initial claims, ISM new orders, building permits, S&P 500, leading credit index, 10y-FF spread, consumer expectations, etc.) | Long history of leading turning points by ~7 months; degraded somewhat in last cycle but still standard | **Paid** for the official series — Conference Board myTCB membership / Data Central; no public price (pricing on request, contact `customer.service@tcb.org`) | Conference Board portal / data feed (paid) **or** free FRED proxy `USSLIND` (Philly Fed leading index, NOT identical but conceptually overlapping) | Monthly | **No (official)**; FRED proxy `USSLIND` reachable via `mcp__fred` | Proxy: `USSLIND` (Philly Fed); official LEI not on FRED |
| 7 | **CFNAI** | Chicago Fed National Activity Index — weighted avg of 85 monthly indicators across 4 categories (production, employment, sales/orders/inventories, consumption/housing) | Threshold-based recession signal: CFNAI-MA3 < -0.7 has historically marked recession onset | Free | FRED API via `mcp__fred.get_series` | Monthly (~3-week lag from reference month) | Yes | `CFNAI` (monthly), `CFNAIMA3` (3-month MA — the recession-signal version), `CFNAIDIFF` (diffusion) |
| 8 | **ISM Manufacturing PMI** | ISM survey of ~400 mfg purchasing executives; >50 expansion / <50 contraction | PMI < 45 has high predictive power for recession; new orders sub-index leads headline | **Paid** — ISM revoked FRED licensing in June 2016, all ISM series deleted from FRED. Public news release is free; bulk historical data + components are paid via ISM (price on request) | (a) Free: scrape `ismworld.org` PMI press release on release day at 10am ET; (b) Free aggregator: DBnomics (`db.nomics.world/ISM/pmi`) — redistributed under provider terms; (c) Paid: ISM direct or vendor (TradingEconomics, etc.) | Monthly (1st business day, 10am ET) | **No** — would need DBnomics fetcher or HTML scrape | n/a — not on FRED. DBnomics path: `https://api.db.nomics.world/v22/series/ISM/pmi/pm` |
| 9 | **GDP nowcasts (Atlanta Fed GDPNow + NY Fed Staff Nowcast)** | Real-time GDP-growth tracking estimates from regional Feds | GDPNow tends to converge to BEA advance within ~0.3pp; NY Fed Nowcast suspended Sep 2021 (COVID), relaunched Sep 2023 with v2.0 | Free | (a) GDPNow: FRED series `GDPNOW`, plus Atlanta Fed page with PDF/Excel; (b) NY Fed Nowcast: direct XLSX download `https://www.newyorkfed.org/medialibrary/Research/Interactives/Data/NowCast/Downloads/New-York-Fed-Staff-Nowcast_download_data.xlsx` | GDPNow: ~6–8x per quarter on data releases; NY Fed: weekly Friday 11:45am ET | GDPNow: yes (`mcp__fred`); NY Fed Nowcast: **no** (XLSX scrape) | `GDPNOW` (Atlanta Fed); NY Fed = direct XLSX |

---

## Recommended priority

### Tier 1 — must-have (all free, all already in `mcp__fred` or trivial to add)
- **10y–3m spread (`T10Y3M`)** — canonical, NY Fed's own model uses it.
- **2y–10y spread (`T10Y2Y`)** — popular alternative, cheap to track alongside.
- **Sahm Rule (`SAHMREALTIME`)** — real-time vintage already on FRED; use real-time variant for backtest hygiene (avoid look-ahead from BLS revisions).
- **CFNAI / CFNAIMA3** — composite of 85 indicators, condenses a lot of info into one number.
- **GDPNow (`GDPNOW`)** — already on FRED, free, real-time GDP read.
- **Excess Bond Premium** — strong empirical edge per GZ 2012 + post-2008 lit; only friction is it's not on FRED, but it's a single Fed Board CSV refreshed monthly. Add a tiny CSV fetcher next to `mcp__fred` (or even just curl it into postgres).

### Tier 2 — nice-to-have (free but more wiring)
- **NTFS** — Engstrom-Sharpe argue it dominates 10y-3m. Two implementation paths:
  1. Compute from `DGS3MO` + Gürkaynak-Sack-Wright zero-curve (the GSW dataset is itself a public Fed Board CSV). This is the academically rigorous path.
  2. Scrape the Google Sheet linked from `neartermforwardspread.com` (Engstrom-maintained). Faster, but adds an external single-author dependency.
  For v0.1 a single weekly scrape is fine; if NTFS earns a meaningful weight in regime detection, do path (1) for reproducibility.
- **NY Fed Staff Nowcast** — relaunched 2023, weekly XLSX from `newyorkfed.org`. Worth pairing with GDPNow for consensus across regional Feds.
- **ISM Manufacturing PMI** — empirically valuable but not on FRED post-2016. Use DBnomics free aggregator; document provenance and accept that DBnomics may carry redistribution restrictions.

### Skip / not worth it
- **Conference Board LEI (official)** — paid, opaque pricing, and the components are mostly things we already pull free (initial claims, ISM new orders, S&P 500, building permits, 10y-FF spread, consumer expectations). Either reconstruct LEI ourselves from the 10 free components or use the Philly Fed `USSLIND` proxy. Do not pay Conference Board.

---

## Notes & caveats

- **Sahm Rule vintage discipline**: `SAHMREALTIME` is the variant that uses the unemployment rate **as known at each historical point**. `SAHMCURRENT` uses the latest-revised number and **will look-ahead** in a backtest. The backtest framework (`src/backtesting/`) must use `SAHMREALTIME` to satisfy the contamination check; flag this in `tests/test_contamination_check.py`.
- **EBP revision**: Federal Reserve Board notes that *the entire history of EBP may revise each month* (firm balance-sheet updates feed back into the GZ model). This is a vintage problem similar to `SAHMCURRENT`. For backtests, snapshot the EBP CSV monthly into `db/` rather than always re-pulling latest.
- **ISM licensing past**: ISM pulled all 22 ISM series from FRED on June 24, 2016 over licensing/copyright. Don't trust any old code that hard-codes `NAPM` or `NAPMNOI` against FRED — those endpoints are dead. DBnomics is the cleanest free path today; ISM's own press release HTML is the canonical source on release day.
- **NY Fed Nowcast outage**: was dark Sep 2021 → Sep 2023. Any backtest that uses NY Fed Nowcast must account for the ~2-year gap; otherwise treat it as a 2023+ signal only.
- **NTFS without FRED**: there is **no FRED series** for NTFS. The Engstrom-Sharpe FEDS 2018-055 paper provides the formula; the Fed's GSW zero-coupon yield-curve dataset (publicly downloadable, refreshed weekly) provides the ingredients. Do not invent a FRED series ID.
- **Conference Board pricing**: official LEI access is gated behind myTCB / Data Central; no public price page exists, hence "pricing on request" — do not invent a number. Almost certainly outside the $175/mo remaining tooling budget per anecdotes from peers.
- **Atlanta Fed GDPNow URL behavior**: `atlantafed.org` blocks generic web fetchers. Use the FRED `GDPNOW` mirror via `mcp__fred` rather than scraping the Atlanta page directly.
- **MCP integration delta vs. existing scope**: Of the 9 signals, 6 are already reachable via `mcp__fred` (signals 1, 2, 5, 7, 9-Atlanta). The 3 that need new wiring are **EBP** (single CSV), **ISM PMI** (DBnomics or scrape), and optionally **NTFS** + **NY Fed Nowcast** (both XLSX/sheet pulls). All 3 fit a single new tool — call it `mcp__macro_supplements` — that exposes a handful of `get_csv(source)` calls. No paid feeds needed if we drop official Conference Board LEI.
