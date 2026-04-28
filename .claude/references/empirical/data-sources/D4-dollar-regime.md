# D4 — Dollar-regime data sources

Data-source map for the **Dollar regime** dimension of the S0 regime context sidecar (per L1-regime-capture.md). Anchored on the empirical findings that DXY-vs-200d is the practitioner regime filter (pattern #21), DXY rising 10%+ over 12m has triggered EM funding stress in every cycle since the float (pattern #23), and dollar regime modulates US equity *style* leadership (pattern #26).

Project budget excl. LLM: **$250/mo**. All Tier 1 sources below are free; Tier 2 only consumes budget if real-time intraday FX is needed for entry timing.

## Signal-by-signal table

| # | Signal | Definition | Empirical edge | Cost | Access | Latency | Existing MCP? | Source endpoint |
|---|---|---|---|---|---|---|---|---|
| 1 | **DXY (US Dollar Index)** — primary | ICE-listed dollar index vs 6-major basket (EUR 57.6%, JPY 13.6%, GBP 11.9%, CAD 9.1%, SEK 4.2%, CHF 3.6%). ICE owns the underlying; futures real-time on ICE. | DXY-up regime → growth/large-cap leadership; DXY-down → value/EM/commodity tailwind. Sign of contemp. correlation w/ S&P unstable; 200d MA filter is the cleaner read (L1 #21). | Free (EOD) | yfinance via `mcp__market_data` ticker `DX-Y.NYB` or `^NYICDX` | EOD daily | YES (`mcp__market_data.get_prices`) | https://finance.yahoo.com/quote/DX-Y.NYB/ |
| 1b | DXY backup feed | Same series via Stooq, ICE futures continuous contract | Identical data; redundancy if Yahoo throttles or symbol gaps | Free | HTTP CSV download, no key | EOD daily | NO | https://stooq.com/q/d/?s=dx.f |
| 1c | DXY ETF proxy | UUP — Invesco DB US Dollar Index Bullish Fund — long DX futures | Tracks DXY 1:1 (futures-roll noise small at monthly horizon); useful when index symbol behaves oddly | Free | yfinance ticker `UUP` | EOD daily | YES (`mcp__market_data`) | https://finance.yahoo.com/quote/UUP/ |
| 2 | **Trade-weighted broad dollar (DTWEXBGS)** | Fed's daily nominal broad dollar index vs ~26 currencies, weighted by trade flows. Goods+services basis. | Better measure of "synthetic global tightening" than DXY (which over-weights EUR). L1 patterns #23, #25 cite the broad-trade-weighted concept as the funding-stress driver. | Free | FRED API via `mcp__fred.get_series('DTWEXBGS')` | Daily, ~1d lag | YES (`mcp__fred`) | https://fred.stlouisfed.org/series/DTWEXBGS |
| 2a | TWD — Advanced Foreign Economies | Sub-index: DTWEXAFEGS (DM only) | Decomposes DXY effect from EM stress | Free | FRED `mcp__fred.get_series('DTWEXAFEGS')` | Daily | YES | https://fred.stlouisfed.org/series/DTWEXAFEGS |
| 2b | TWD — Emerging Market Economies | Sub-index: DTWEXEMEGS (EM only) | Direct read on EM-FX stress per L1 patterns #25, #35, #36 (DXY→EM transmission). Inverse correlate of MSCI EM. | Free | FRED `mcp__fred.get_series('DTWEXEMEGS')` | Daily | YES | https://fred.stlouisfed.org/series/DTWEXEMEGS |
| 3 | **EUR/USD (DEXUSEU)** | USD per EUR, Fed noon NYC fixing | Largest weight in DXY (57.6%); ECB-Fed policy-divergence signal | Free | FRED `mcp__fred.get_series('DEXUSEU')` | Daily, ~1d lag | YES | https://fred.stlouisfed.org/series/DEXUSEU |
| 3a | **USD/JPY (DEXJPUS)** | JPY per USD | Carry-funding currency proxy; spike up = global risk-off / yen-carry unwind (L1 #17, #18) | Free | FRED `mcp__fred.get_series('DEXJPUS')` | Daily | YES | https://fred.stlouisfed.org/series/DEXJPUS |
| 3b | **GBP/USD (DEXUSUK)** | USD per GBP | Cross-check on DXY EUR-dominance; Brexit-era dispersion vector | Free | FRED `mcp__fred.get_series('DEXUSUK')` | Daily | YES | https://fred.stlouisfed.org/series/DEXUSUK |
| 3c | **USD/CNY (DEXCHUS)** | CNY per USD, Fed noon fixing | PBoC-managed; break of 7.0 = signal of capital-account stress, EM contagion vector | Free | FRED `mcp__fred.get_series('DEXCHUS')` | Daily | YES | https://fred.stlouisfed.org/series/DEXCHUS |
| 3d | EUR/USD intraday (optional) | Live tick / intraday bars for entry timing | Same series as 3 but real-time | Free tier: 25 req/day on Alpha Vantage; OANDA 7-day free trial; Polygon Currencies starter ~$29/mo | Alpha Vantage `FX_INTRADAY` / OANDA REST / Polygon `C:EURUSD` | Real-time | NO | https://www.alphavantage.co/documentation/ ; https://developer.oanda.com/exchange-rates-api/ ; https://polygon.io/pricing |
| 4 | **EM-FX basket — DTWEXEMEGS proxy** | Same as 2b. JPM EMCI / DB EM-FX are Bloomberg-only. | Replaces JPM EMCI for free; correlates ~0.95 with EMCI on monthly | Free | FRED via `mcp__fred` | Daily | YES | https://fred.stlouisfed.org/series/DTWEXEMEGS |
| 4a | EM-FX basket — ETF proxy | CEW (WisdomTree EM Currency Strategy Fund) — actively-managed but tradeable EM-FX basket | Tradeable proxy for EMCI exposure; small AUM but liquid enough for signal | Free | yfinance ticker `CEW` | EOD daily | YES (`mcp__market_data`) | https://finance.yahoo.com/quote/CEW/ |
| 4b | EM-FX individual majors | Pulls for the 4 biggest EM exposures: BRL (DEXBZUS), MXN (DEXMXUS), KRW (DEXKOUS), THB (DEXTHUS) | Decomposition when basket move is dispersion-driven; surfaces "Fragile Five" (L1 #35) | Free | FRED `mcp__fred` | Daily | YES | https://fred.stlouisfed.org/series/DEXBZUS ; https://fred.stlouisfed.org/series/DEXMXUS |
| 5 | **Real broad effective exchange rate** | BIS REER for US (RBUSBIS) — adjusted for relative CPI vs trade partners | Filters out pure inflation differential; truer "real" dollar level. Useful for multi-decade regime calls (L1 #36 Setser frame). | Free | FRED `mcp__fred.get_series('RBUSBIS')` | Monthly, mid-month release | YES | https://fred.stlouisfed.org/series/RBUSBIS |
| 5a | BIS direct REER feed | All 64 economies' REER data | Cross-section view (e.g., compare USD vs EUR vs JPY REER simultaneously) | Free | BIS Data Portal CSV download (no auth) | Monthly | NO | https://www.bis.org/statistics/eer.htm |
| 6 | **Bloomberg Dollar Spot (BBDXY)** | Bloomberg's broader 10-currency basket; rebalanced annually by trade-weighted FX liquidity | Sometimes preferred over DXY for global view (CNY exposure not in DXY). But: paid-only direct. | Paid (Bloomberg Terminal $24k+/yr) for direct; **skip at v0.1**. Use DTWEXBGS (#2) as functional equivalent. | Bloomberg Terminal only for license-clean ticks; web quote at bloomberg.com/quote/BBDXY:IND is delayed and unsuitable for systematic use | EOD | NO | https://www.bloomberg.com/quote/BBDXY:IND |
| 6a | BBDXY ETF proxy | USDU — WisdomTree Bloomberg US Dollar Bullish Fund (tracks BBDXY) | Tradeable proxy; smaller AUM than UUP but BBDXY-aligned | Free | yfinance ticker `USDU` | EOD daily | YES (`mcp__market_data`) | https://finance.yahoo.com/quote/USDU/ |
| 7 | **Carry-trade indices — DBV ETF proxy** | Invesco DB G10 Currency Harvest Fund (DBV) — long 3 highest-yielding G10, short 3 lowest. Tracks DB G10 Currency Harvest. | Carry-premium proxy; carry P&L drawdown is high-freq risk-off signal (L1 #18, ~34bp/day on VIX-spike days). DB DBCR/Currency Carry indices direct require DBIQ subscription. | Free | yfinance ticker `DBV` | EOD daily | YES (`mcp__market_data`) | https://etfdb.com/index/deutsche-bank-g10-currency-future-harvest-index---excess-return/ ; https://finance.yahoo.com/quote/DBV/ |
| 7a | Carry — alt construction | Build synthetic carry from FRED: long high-yielders (BRL, MXN, ZAR via inverse 1/DEXBZUS, 1/DEXMXUS, 1/DEXSFUS) vs short low-yielders (JPY, CHF via 1/DEXJPUS, 1/DEXSZUS) | Custom; transparent; no rebalance lag from ETF wrapper | Free | FRED daily series via `mcp__fred` | Daily | YES (compute layer) | (multiple FRED series) |
| 8 | **DXY 200-day MA regime filter** | DXY close vs trailing 200-trading-day simple MA. Above = strong-dollar regime, below = weak. | Practitioner consensus regime filter (L1 #21). Cleaner read than raw level since DXY range varies by decade. | Free | Compute from #1 (yfinance DXY series) | EOD daily | YES (compute layer in agent code) | derived from https://finance.yahoo.com/quote/DX-Y.NYB/ |

## Recommended priority

### Tier 1 (must-have, free, already-integrated MCP)
- **#1 DXY (DX-Y.NYB / UUP)** via `mcp__market_data` — primary regime indicator
- **#2 DTWEXBGS (broad TWD)** via `mcp__fred` — Fed's broader trade-weighted, the "true" funding-stress measure
- **#2b DTWEXEMEGS** via `mcp__fred` — direct EM-FX read, replaces JPM EMCI for free
- **#3-3c EUR/USD, USD/JPY, GBP/USD, USD/CNY (DEXUSEU, DEXJPUS, DEXUSUK, DEXCHUS)** via `mcp__fred` — major crosses, daily
- **#5 RBUSBIS (real broad REER)** via `mcp__fred` — multi-decade real-dollar context (monthly)
- **#8 DXY 200-day MA** — derived signal (no new data; just compute)

All Tier 1 signals require **zero new MCP servers, zero budget**. The two existing MCP servers (`mcp__market_data`, `mcp__fred`) already deliver everything needed.

### Tier 2 (nice-to-have, free or low-cost)
- **#1b Stooq DXY backup** — redundancy feed; thin scraper if Yahoo gaps. Marginal value.
- **#2a DTWEXAFEGS (DM-only TWD)** via FRED — useful for decomposing DXY moves (DM vs EM)
- **#4a CEW ETF (EM-FX tradeable)** via yfinance — when basket dispersion matters
- **#4b Individual EM majors (BRL, MXN, KRW, THB)** via FRED — for "Fragile Five" surveillance
- **#6a USDU ETF (BBDXY proxy)** via yfinance — secondary basket cross-check
- **#7 DBV (DB G10 Carry ETF)** via yfinance — carry-regime proxy
- **#7a synthetic carry** — only if DBV liquidity proves insufficient for signal extraction
- **#3d Polygon Currencies starter ($29/mo)** — only if v0.5+ entry-timing requires intraday FX. Free tiers (Alpha Vantage 25 req/day, OANDA 7-day trial) are insufficient for production polling.

### Skip (paid-only, marginal incremental value)
- **#6 Bloomberg BBDXY direct ticks** — Terminal-only, $24k/yr; functionally replaced by DTWEXBGS (#2) and USDU ETF (#6a). The 0.95+ correlation between BBDXY and DTWEXBGS at monthly horizon makes the direct feed a luxury, not a necessity.
- **JPM EMCI direct** — Bloomberg/JPM Markets-only; replaced by DTWEXEMEGS + CEW.
- **DB DBCR/Currency Carry direct** — DBIQ subscription required; replaced by DBV ETF + synthetic carry from FRED.
- **OANDA paid tier / Alpha Vantage paid** — Tier 1 doesn't need them; only enable if entry-timing intraday FX becomes a v1.0+ requirement.

## Notes & caveats

- **DXY index symbol gotcha:** `DX-Y.NYB` is the ICE futures symbol surfaced by Yahoo; `^NYICDX` is the index quote. Both work via yfinance. Stooq uses `dx.f` (continuous futures contract). When verifying signal calculations against multiple feeds, expect tiny (<5bp) differences from roll convention.
- **DXY composition is *fixed* (since 1973):** EUR 57.6%, JPY 13.6%, GBP 11.9%, CAD 9.1%, SEK 4.2%, CHF 3.6%. Notably **no CNY**. This is why DTWEXBGS (#2) is the better measure of "is the dollar tightening global financial conditions" — it includes CNY weight. Practitioners often cite "DXY" loosely when they mean broad dollar; our signals should use both and cross-check.
- **Trade-weighted broad dollar (DTWEXBGS):** Fed series, daily, free at FRED. Live since 2006-01-02. Pre-2006 history requires the legacy series (TWEXBGSMTH, monthly only). For multi-decade backtests, RBUSBIS (BIS REER) goes back further (1994 monthly) and is recommended.
- **FRED FX crosses:** All `DEX*` series are Fed H.10 noon NYC fixings, **not real-time spot**. They publish ~1 trading day after-the-fact. Adequate for daily regime work; insufficient for intraday entry timing.
- **CNY (DEXCHUS) is PBoC-managed:** the daily fixing is policy-driven, not market-clearing. Spot CNH (offshore) sometimes diverges. For regime work the onshore CNY is the right read because it represents the policy regime.
- **EM-FX baskets:** JPM EMCI and DB EM-FX indices are commercial; **DTWEXEMEGS is the Fed's free equivalent**, ~0.95 monthly correlation with EMCI per practitioner cross-checks. CEW ETF gives tradeable proxy if you want a market-cleared basket.
- **BBDXY (Bloomberg Dollar Spot Index):** Direct feed is Bloomberg-Terminal-only ($24k+/yr/seat). The web quote is delayed and per-Bloomberg-TOS not for systematic use. Skip at v0.1 — DTWEXBGS + USDU ETF cover the same regime question.
- **Carry-trade indices:** Direct DB DBCR / DB Currency Carry / BNP Carry indices require DBIQ or paid Bloomberg subscription. **DBV ETF** (Invesco DB G10 Currency Harvest, NYSE-listed since 2006) is the practical free proxy. Alternatively a synthetic carry can be computed from FRED daily FX series — transparent, no ETF wrapper friction, but more code to maintain.
- **OANDA free trial caveat:** 7-day key only, then paid. Alpha Vantage free is 25 requests/day (insufficient for any systematic poll). For real-time / intraday FX at production cadence, Polygon Currencies starter (~$29/mo) is the realistic option — well within the $250/mo budget.
- **Existing MCP coverage is excellent for this dimension:** all Tier 1 signals are already wired through `mcp__fred.get_series` and `mcp__market_data.get_prices`. **No new MCP server is needed**, and **no new env vars or API keys** beyond the existing `FRED_API_KEY`.
- **200-day MA is a derived signal**, not a data feed. The agent code that consumes DXY EOD prices computes the rolling MA — no extra data integration needed.

## Open questions / unclear pricing

- **Polygon Currencies tier exact pricing:** The pricing page (https://polygon.io/pricing) lists Stocks Starter at $29/mo but Currencies-specific tier prices were not surfaced cleanly in web search; should be verified via direct page visit if/when v0.5+ entry-timing intraday FX becomes a priority. Estimate $29-49/mo based on Stocks-tier analogue.
- **OANDA paid pricing:** Beyond 7-day free trial, OANDA's Exchange Rates API monthly cost was not transparently listed on public marketing pages — quote-by-firm-size. Likely $50-200/mo for retail/small-fund usage; would need direct contact.
- **DBV ETF tracking integrity:** DBV's tracking of DB G10 Currency Harvest has historical roll-cost slippage and (per CXO Advisory's review) negative absolute returns through 2020. The ETF still serves as a *signal* (carry-regime direction) but should not be treated as investable carry exposure.
