# Public API landscape for regime classification

**Scope:** Public APIs (free + paid) that provide raw data for the project's regime-classification dimensions D1–D5 (economic cycle, credit stress, vol regime, dollar regime, Bridgewater 4-box). Complements the project's existing `mcp__fred` + `mcp__edgar` + `mcp__market_data` + Sharadar (`mcp__fundamentals`) servers.

**Operator constraints (recap):**
- Total non-LLM budget: $250/mo
- Already paid: Sharadar Core Fundamentals (~$75/mo via Nasdaq Data Link)
- Headroom: ~$170/mo
- Preference order: free → paid only if unreplaceable

**Anti-hallucination policy:** every pricing number below is anchored to a fetched URL in Section A. Where a vendor refuses to publish prices ("contact us"), this doc says so explicitly rather than inventing a number.

---

## Section A — Curated sources

### Mass-market institutional APIs
1. Databento pricing — https://databento.com/pricing
2. Polygon.io stocks — https://polygon.io/pricing?product=stocks (now redirects to massive.com/pricing)
3. Polygon.io options — https://polygon.io/pricing?product=options
4. Polygon.io 3rd-party review — https://tradingtoolshub.com/review/polygon-io/
5. Alpha Vantage premium — https://www.alphavantage.co/premium/
6. Tiingo pricing — https://www.tiingo.com/about/pricing
7. Tiingo review (Find My Moat) — https://www.findmymoat.com/tools/tiingo
8. Twelve Data pricing — https://twelvedata.com/pricing

### Aggregator / open-source platforms
9. OpenBB GitHub (AGPLv3) — https://github.com/OpenBB-finance/OpenBB
10. OpenBB Workspace (paid) — https://pro.openbb.co/
11. yfinance (Python, unofficial Yahoo) — https://github.com/ranaroussi/yfinance
12. Stooq help / data — https://stooq.com/help/?s=api  •  https://stooq.com/db/h/

### Quandl / Nasdaq Data Link
13. Nasdaq Data Link — https://data.nasdaq.com/
14. Sharadar SF1 (Core Fundamentals) — https://data.nasdaq.com/databases/SF1
15. Sharadar via QuantRocket — https://www.quantrocket.com/pricing/data/sharadar/

### Broker APIs
16. Tradier market data docs — https://docs.tradier.com/docs/market-data
17. Schwab Trader API (individuals) — https://developer.schwab.com/products/trader-api--individual
18. Alpaca market data API — https://docs.alpaca.markets/docs/about-market-data-api
19. Interactive Brokers TWS API — https://www.interactivebrokers.com/en/trading/ib-api.php

### Specialized macro data (free / public)
20. DBnomics about — https://db.nomics.world/about
21. DBnomics ISM provider page — https://db.nomics.world/ISM
22. OECD data API — https://www.oecd.org/en/data/api.html
23. World Bank developer help — https://datahelpdesk.worldbank.org/knowledgebase/topics/125589
24. BIS Data Portal — http://www.bis.org/statistics/dataportal/index.htm
25. ECB SDMX 2.1 web service — https://data.ecb.europa.eu/help/api/overview
26. IMF data home — https://www.imf.org/en/Data

### News / sentiment APIs
27. NewsAPI pricing — https://newsapi.org/pricing
28. Tiingo News (within Tiingo Power plan) — https://www.tiingo.com/about/pricing
29. Benzinga API product suite — https://www.benzinga.com/apis/data/
30. Benzinga Basic News (AWS Marketplace free tier) — https://aws.amazon.com/marketplace/pp/prodview-xwgvhwowjmw3g

---

## Section B — Per-API summary table

| # | API | Free tier | Paid entry | Coverage | Latency | Regime-classification value | Free substitute exists? |
|---|---|---|---|---|---|---|---|
| 1 | **Databento** | $125 one-time credits (6-mo expiry) | $199/mo "Standard" → $1,399/mo "Plus" → $3,500/mo "Unlimited" | Equities/options/futures, 45+ exchanges, MBO/MBP/L1-L3. **No macro.** | Microsecond live; tick history | Limited for our use — overkill. Useful only if D3 vol regime needed sub-second OPRA depth. | Yes — Polygon $79/mo or Alpaca free covers our resolution |
| 2 | **Polygon.io** | 5 req/min, EOD/delayed | Starter $29 (delayed unlimited); **Developer $79** (real-time + options); Advanced $199 | US stocks, options, FX, crypto, indices; some fundamentals | Real-time WS at $79+ | Strong: real-time options chain → IV term structure (D3); index OHLC; corporate actions | Partial. yfinance covers EOD; options chain real-time has no free equivalent |
| 3 | **Alpha Vantage** | 25 req/day (recently tightened from 5/min, 500/day) | $49.99 → $249.99/mo (75 → 1,200 req/min, no daily cap) | Equities, FX, crypto, ~20 macro endpoints, technicals | EOD + 15-min delay; some real-time at premium | Good for D1 (CPI, GDP, Fed Funds, treasuries); D4 (DXY components via FX) | Mostly yes — FRED covers all macro endpoints free |
| 4 | **Tiingo** | Starter free, ~500 sym/hr, 50/day for unique tickers | **Power $30/mo** (100k req/day, news included); Commercial $50/mo (same data, business license) | EOD US stocks, IEX real-time, fundamentals, news, crypto, FX | EOD + IEX real-time delayed-ish (~ms) | Strong $/value: news API + EOD prices + fundamentals at $30. News useful for sentiment regime overlay. | News not easily — yfinance prices yes; news no |
| 5 | **Twelve Data** | Free: 800 calls/day, 8 req/min | Grow $66/mo, Pro $191/mo, Ultra $832/mo | Stocks, FX, crypto, indices, fundamentals (paid), 100+ technicals | Real-time WS on paid | Multi-asset breadth; FX coverage useful for D4 dollar regime | Yes — FRED + yfinance + Polygon free combine to cover |
| 6 | **OpenBB Platform (Python)** | 100% free, AGPLv3 | N/A — bring your own keys | Aggregator over FRED, EDGAR, Polygon, Tiingo, Yahoo, Alpha Vantage, Benzinga, etc. | Whatever underlying provider gives | High — useful as a substrate to swap providers behind a unified API. AGPLv3 license is a constraint. | Itself is the substitute |
| 7 | **OpenBB Workspace (Pro)** | Free hub tier exists; pricing page non-public on tested URL | "Contact us" / pricing on request | UI on top of Platform | Same as Platform | Marginal for headless/API-driven research system | Yes — use raw Platform |
| 8 | **yfinance** | Unlimited (TOS personal use only) | N/A | EOD + delayed quotes, fundamentals (best-effort), options chain (delayed) | Delayed | Critical fallback layer — already in our `mcp__market_data` chain | Self |
| 9 | **Stooq** | Free EOD bulk + light HTTP `q=...&i=d` endpoint | None | EOD US/UK/JP/EU/PL/HK + indices/FX/crypto/bonds | EOD only | Useful free EOD backup for D4 (DXY history) and indices | Self |
| 10 | **Investing.com** | None official | Scraping only — TOS-violating | Broad | Varies | Skip — TOS risk, no public API | yfinance covers |
| 11 | **Nasdaq Data Link (free)** | Free macro datasets (FRED mirror, BIS, OECD subsets, World Bank) | Per-dataset paid | Free macro datasets + paid premium (Sharadar, Zacks, etc.) | EOD typical | Useful free aggregator; but FRED + DBnomics already cover | Yes — FRED + DBnomics |
| 12 | **Sharadar SF1 (paid)** | None | Pricing gated behind login on Nasdaq Data Link / QuantRocket — **public price-page does NOT show $; "$75/mo" project figure is operator-internal, not vendor-published** | Point-in-time fundamentals back to 1990, 14k+ tickers | EOD | Critical for backtests — survivorship + PIT; we have it | No equivalent free PIT fundamentals |
| 13 | **Tradier** | Sandbox: 15-min delayed | Real-time options chain free for **Tradier Brokerage account holders**. Non-brokerage developer pricing on request. | Equities + real-time OPRA options for brokerage clients | Real-time (brokerage) / delayed (sandbox) | High value if used as broker — free real-time OPRA is rare | Polygon $79 is paid alternative |
| 14 | **Interactive Brokers TWS API** | Free for IBKR clients; free socket API; market data subscriptions per exchange (~$1.50–$5/mo each, à la carte) | Free | Global multi-asset; OPRA, ICE, CME, etc. | Real-time | Best institutional coverage if held as broker. Socket API steep learning curve. | Polygon paid alt |
| 15 | **Schwab Trader API** | Free for Schwab account holders; ~120 req/min data | Free | US equities, options chains real-time, futures L1/L2, 15y daily / 6mo intraday history | Real-time | Strong if account already held; OAuth + manual approval (1–3 days) | Tradier/IBKR substitutes |
| 16 | **Alpaca** | Basic: IEX real-time only, 200 req/min, last 15 min historical | Algo Trader Plus **$99/mo**: full SIP + OPRA options | US equities, options (paid), crypto | Real-time | Cheapest full-SIP + OPRA standalone (no brokerage account required) | Polygon Developer $79 is similar |
| 17 | **DBnomics** | 100% free, no auth | N/A | Aggregates FRED, ECB, OECD, IMF, BIS, **ISM Manufacturing + Non-Manufacturing**, World Bank | EOD / monthly | **Critical** — only public free source for ISM PMI (left FRED in 2016). Direct value for D1 economic cycle | Self (uniquely covers ISM) |
| 18 | **OECD API** | Free, no auth (returns 403 to AI fetcher but is publicly accessible via SDMX-JSON) | N/A | Composite Leading Indicators, BCI, CCI | EOD/monthly | High — D1 cycle (CLI) + cross-country | Self |
| 19 | **World Bank API** | Free, no auth | N/A | WDI: GDP, inflation, EM macro | Annual/quarterly | Modest — D1 only at country aggregate level | Self |
| 20 | **BIS SDMX API** | Free, no auth | N/A | Cross-border banking, credit-to-GDP, FX, debt service ratios | Quarterly | Useful for D2 credit stress (cross-border channels) and D4 (effective FX) | Self |
| 21 | **ECB SDMX 2.1** | Free, no auth | N/A | EUR rates, credit spreads, EMU macro | Daily / monthly | Useful for D2 (Euro IG/HY spreads) + D4 (DXY = 57.6% EUR) | Self |
| 22 | **IMF SDMX API** | Free, no auth | N/A | IFS, BOP, fiscal | Monthly/quarterly | Modest overlap with OECD/WB | Self |
| 23 | **NewsAPI** | 100 req/day, **24-hr delay**, 1-mo history, localhost only | Business **$449/mo** (real-time, 5-yr history, 250k req); Advanced $1,749/mo | Aggregated news | Real-time on paid | Limited — 24-hr delay on free tier kills regime sentiment use | Tiingo News at $30/mo is dramatically cheaper |
| 24 | **Tiingo News** | Bundled in Power $30/mo | $30/mo | Curated financial news, sentiment-tagged | Real-time | Cheapest credible news API for sentiment overlay | yfinance news is messy/delayed |
| 25 | **Benzinga** | "Basic Financial News" free tier on AWS Marketplace (headlines + teasers, links to bz.com) | Pricing **on request** — not publicly listed | Real-time financial news, analyst ratings, earnings calendar | Real-time (paid) | Strong if budget allows; pricing opacity is a friction | Tiingo News at $30 |

---

## Section C — Recommended subscriptions for v0.1

### Free-only stack (achievable; covers ~85% of regime needs)

| Need | Source | Notes |
|---|---|---|
| D1 — Yield curve, CPI, unemployment, Fed Funds | **FRED** (already wired) | Existing `mcp__fred` |
| D1 — ISM PMI Manufacturing + Services | **DBnomics** (new) | Free; only public source — ISM left FRED in 2016 |
| D1 — OECD Composite Leading Indicator | **OECD SDMX** | Free SDMX-JSON; cross-country leading-indicator complement |
| D2 — IG / HY OAS, BAA-AAA spread | **FRED** (BAMLC0A0CM, BAMLH0A0HYM2) | Existing |
| D2 — Cross-border banking, credit gap | **BIS API** | Free; quarterly |
| D3 — VIX, MOVE proxy (10y yield daily realized) | **FRED** + **yfinance** ^VIX | Existing chain |
| D3 — IV term structure, options chain real-time | **GAP** — yfinance gives delayed only | Free substitute is poor; see paid section |
| D4 — DXY, EUR, JPY, GBP daily | **FRED** (DTWEXBGS) + **yfinance** | Existing |
| D4 — Trade-weighted broad dollar | **FRED** | Existing |
| D5 — Real growth + inflation surprise | **FRED** + **OECD CLI** + **DBnomics ISM** | Composite indicator |
| Equity prices, fundamentals | **yfinance** + **EDGAR** XBRL + **Sharadar** (already paid) | Existing chain |
| News (sentiment overlay) | **Tiingo News $30/mo** OR **Benzinga free AWS tier** | News API gap if going pure-free |
| Open-source aggregation substrate | **OpenBB Platform (AGPLv3)** | Optional — wraps the above behind unified Python API |

**Free-only verdict:** **feasible for D1, D2, D4, D5**. **Partially-blocked for D3** (real-time options chain / IV term structure has no free public substitute at the resolution we'd want for vol-regime classification). Sentiment overlay also weak on pure-free.

### Recommended paid additions (≤ $170/mo headroom)

**Tier 0 — Highly recommended ($30/mo):**
- **Tiingo Power — $30/mo.** News API + EOD + IEX real-time + fundamentals. Best $/data ratio in the entire survey. Fixes the news/sentiment gap and adds a redundant EOD source.

**Tier 1 — Recommended if D3 vol regime is load-bearing ($79/mo):**
- **Polygon.io Developer — $79/mo.** Real-time options chain (IV term structure for D3), real-time WS, full options. Total subscription cost so far: $30 + $79 = $109/mo, well within headroom.

**Tier 2 — Skip unless brokerage relationship triggers it ($0 conditional):**
- **Schwab / IBKR / Tradier brokerage API** — free *if* operator already custodies there. No marginal subscription cost.

**Total recommended monthly add-on:** **$30** (Tiingo only) → **$109** (Tiingo + Polygon Developer if D3 demands real-time options).
**Plus existing Sharadar $75 → grand total $105–$184/mo, vs $250 cap.**

### Skip list (with reasons)

| API | Why skip |
|---|---|
| **Databento** | Sub-microsecond institutional latency; cheapest meaningful tier $199/mo; **no macro coverage**. Overkill for individual <$1M investor doing regime classification on daily/weekly/monthly bars. |
| **Alpha Vantage paid** | $49.99/mo entry buys what FRED gives free for macro; marginal value over Polygon/Tiingo for prices. |
| **Twelve Data Grow $66/mo** | Multi-asset is nice but redundant with Polygon Developer; no unique data. |
| **NewsAPI $449/mo** | 15× the price of Tiingo News for similar functionality. |
| **Benzinga paid** | Pricing opacity ("contact us") is a red flag for a $170/mo budget; Tiingo News is the public-priced equivalent. |
| **OpenBB Workspace (Pro)** | Pricing not public on tested URL; UI value is low for an agent-driven system. |
| **Investing.com** | TOS-violating scraping; no public API. |

---

## Section D — Specific verdicts

### Databento — **SKIP**
Lowest meaningful tier is $199/mo Standard; only L1 history (1y), no macro. The institutional microsecond latency and order-book depth solve a problem (HFT execution analytics) that this regime-classification system does not have. Daily/weekly bar resolution is what D1–D5 need. **Recommendation:** skip; the $199 buys nothing the $79 Polygon Developer doesn't already cover for our resolution.

### Polygon.io vs Tiingo head-to-head — **Tiingo wins entry-tier; Polygon wins real-time**
- For *EOD prices + fundamentals + news at $30/mo*: **Tiingo wins decisively**. Polygon Starter $29 has no news and no real-time.
- For *real-time options chain + WS + sub-second ticks*: **Polygon Developer $79/mo wins**. Tiingo's real-time is IEX-only and lacks options.
- **Best-of-both stack:** Tiingo $30 + Polygon $79 = $109/mo. They are complements, not substitutes. Avoid Twelve Data — its overlap with Polygon is high and price/value worse.

### OpenBB Platform — **Useful substrate, not unnecessary abstraction**
- The open-source Python platform (AGPLv3) is a productive substrate: it normalizes provider APIs (FRED, EDGAR, Polygon, Tiingo, Alpha Vantage, Yahoo, Benzinga, etc.) behind a unified `obb.equity.price.historical(...)` interface.
- **Caveat 1:** AGPLv3 propagates to dependent code if redistributed; for an internal/self-hosted research system this is fine, but be deliberate about it.
- **Caveat 2:** The Platform is Python-API only; the project's MCP architecture would need a thin MCP adapter layer to expose OpenBB calls as MCP tools. Not free engineering effort.
- **Verdict:** Use OpenBB Platform if/when we add a 4th-or-5th data provider and the per-provider client code starts proliferating. For 2–3 providers (current state), direct integration is simpler.

### DBnomics as ISM PMI substitute for FRED — **YES, complete substitute**
ISM withdrew the PMI series from FRED in 2016 (licensing dispute). DBnomics fetched-and-confirmed: provider page for ISM lists Manufacturing and Non-Manufacturing categories (https://db.nomics.world/ISM). DBnomics preserves original codes, daily-updates, and exposes a free SDMX-style HTTP+JSON API plus Python/R clients. **This is the public-free path to ISM PMI.** Wire it as a `mcp__dbnomics` server for D1.

### Best free substitute for paid I/B/E/S earnings revisions data — **Partial only**
- **Truly free + clean I/B/E/S data does not exist.** Refinitiv I/B/E/S is the gold standard and is paywalled at >$1k/mo levels.
- **Closest free approximations:**
  - **Yahoo Finance / yfinance** `Ticker.earnings_estimates` (delayed, sometimes stale, no PIT)
  - **EDGAR 8-K + Form 8-K guidance** parsing (yields hard-data revisions, not consensus)
  - **Sharadar SF3** (Insiders + Estimates) — paid, on Nasdaq Data Link
  - **Zacks via Nasdaq Data Link** — paid
- **Practical recommendation:** for v0.1 use yfinance estimates with explicit non-PIT caveat; if revision data becomes load-bearing, evaluate Sharadar's expanded bundle add-on rather than I/B/E/S.

### Best free substitute for ICE MOVE real-time — **None precise; constructible proxy**
- ICE BofA MOVE Index is a 1-month Treasury option-implied volatility index, licensed by ICE; not on FRED in real-time.
- **FRED carries** `BAMLC0A0CM` (credit OAS) and similar but the MOVE itself is delayed/end-of-day at best on free sources.
- **Constructible proxies (free):**
  1. yfinance `^MOVE` — exists but quote quality is unreliable
  2. **Built proxy:** rolling realized volatility of 10y Treasury yield + level of 10y yield, both free from FRED. Correlation with MOVE typically 0.7–0.85 depending on regime.
  3. CBOE TYVIX (discontinued in 2020, no replacement on free public sources)
- **Recommendation:** use a constructed proxy from FRED 10y yield realized vol for D3. If real-time MOVE is mission-critical, the cheapest paid path is via a Bloomberg/Refinitiv terminal — far above the $170 budget.

### Broker-API head-to-head for sub-$1M individual

| Broker API | Cost | Real-time options | Strengths | Weaknesses |
|---|---|---|---|---|
| **Schwab Trader API** | Free for clients | Yes (real-time chains) | 15y daily history, broad coverage, post-TDA legacy of API quality | OAuth + 1–3 day manual app approval; rate ~120 req/min |
| **Interactive Brokers TWS API** | Free + à-la-carte mkt-data subs (~$1.50–$5/exchange/mo) | Yes (paid mkt-data sub) | Best global coverage, futures, FX, OPRA | Steep socket-based API, TWS process required, market-data fees fragment |
| **Tradier** | Free real-time for brokerage clients (sandbox = delayed) | Yes (real-time OPRA) | Cleanest REST API, no daemon | US-only; thinner instrument coverage than IBKR |
| **Alpaca** | Free Basic (IEX only); $99/mo Algo Trader Plus for SIP+OPRA | Yes (paid only) | Cleanest API; no brokerage relationship needed | Free tier is IEX-only (limited fill quality reflected in quotes) |

**Verdict for our profile (sub-$1M, regime-classification, options-chain dependency for D3):**
- If operator already has Schwab → use Schwab Trader API (zero marginal cost, full options chains).
- If no broker relationship and want options-chain freedom → **Polygon Developer $79/mo** beats opening an Alpaca account at $99/mo.
- IBKR is best-in-class but the integration cost is high for a research-first system.

---

## Surprises and notes from this survey

1. **DBnomics is a sleeper.** Free, daily-updated, covers ISM PMI (which most operators assume requires a paid Bloomberg-style feed). Should have been wired earlier.
2. **Tiingo at $30/mo is the highest $/value paid product surveyed.** Bundles news, EOD, IEX real-time, and fundamentals at a price point cheaper than Alpha Vantage's *entry* tier.
3. **Polygon.io rebrand to "Massive"** — `polygon.io` URLs 301-redirect to `massive.com/pricing`. Pricing structure unchanged ($29 / $79 / $199), but operators should expect URL/branding flux.
4. **NewsAPI is overpriced relative to Tiingo News** by ~15×. No reason to use NewsAPI for a financial-news use case.
5. **Alpha Vantage tightened its free tier** from "5 calls/min, 500/day" to **25 calls/day total**. The brief says 5/min, 500/day; vendor page now says 25/day. Premium tiers replaced what was free.
6. **Schwab Trader API** is genuinely high-quality post-TDA acquisition — no extra entitlements needed for individual developers, real-time options chains, 15y daily history, all free for account holders. Underrated.
7. **Databento offers $125 in free credits** for new users (6-month expiry). Worth using to spot-validate any single dataset before committing — but don't subscribe.
8. **OpenBB is AGPLv3** (not MIT/Apache as some operators assume). For internal use this is fine; for any redistribution it propagates copyleft.
9. **Sharadar pricing is not publicly listed** on Nasdaq Data Link or QuantRocket — both gate it behind login + license selection. The "$75/mo" figure in the operator brief is an internal/historical number and should be reconfirmed at renewal.
10. **Real-time MOVE has no clean free substitute.** Constructed proxy from FRED 10y realized vol is the only public-free path; expect 0.7–0.85 correlation, not 1.0.

---

## Implementation hint — minimal MCP additions

To realize the recommended stack, the project would add:
- **`mcp__dbnomics`** (new, free) — for ISM PMI + OECD CLI
- **`mcp__tiingo`** (new, $30/mo) — for news API + redundant EOD
- *(optional)* **`mcp__polygon`** (replace/upgrade existing `mcp__market_data` Polygon link) at $79/mo Developer — for real-time options chain feeding D3
- BIS / ECB / IMF / OECD / World Bank can either get bespoke MCPs *or* be subsumed under a single `mcp__sdmx` adapter since they all speak SDMX 2.1.

Total monthly delta vs current state: **+$30** (free-only path with Tiingo) to **+$109** (with Polygon for D3 real-time options). Both are within the $170/mo headroom.
