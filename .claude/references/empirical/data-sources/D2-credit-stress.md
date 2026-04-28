# D2 — Credit-stress data sources

**Sidecar:** S0 (Regime context) — Credit-stress dimension.
**Purpose:** identify funding/credit-market dislocation that historically precedes or accompanies equity drawdowns. Read by MacroCycleAgent + sized through PositionSizingModel risk-off taper.
**Operator constraints:** total non-LLM budget $250/mo; $75/mo already spent on Sharadar. Free preferred.

---

## TL;DR

10 signals investigated. **9/10 are obtainable free** via FRED (already-integrated `mcp__fred`) plus two direct-URL pulls (Federal Reserve EBP CSV, ICE CDX settlement page). The only signal requiring a non-free feed is the **MOVE index** real-time, but daily/EOD MOVE is free via Yahoo Finance (`^MOVE`). **No paid signal is recommended** — every credit-stress signal with documented edge is reachable inside the existing budget without adding new vendors.

---

## Signal-by-signal table

| # | Signal | Definition | Empirical edge | Cost | Access | Latency | Existing MCP? | FRED ID / endpoint |
|---|---|---|---|---|---|---|---|---|
| 1 | **HY-OAS** | ICE BofA US High Yield Index option-adjusted spread vs spot Treasury curve | Practitioner trigger: +300bp from rolling 1y low → de-risk equity. Strong empirical link to forward-12m equity drawdowns; widening regimes coincide with bear markets (2008, 2015 energy, 2020 COVID, 2022). | Free | FRED REST API | Daily, ~1d lag | **Yes** — `mcp__fred.get_series('BAMLH0A0HYM2')` | `BAMLH0A0HYM2` |
| 2 | **IG-OAS** | ICE BofA US Investment Grade Corporate Index OAS | Less sensitive than HY but cleaner signal of "real economy" funding cost. Crosses ~150bp during stress; ~80bp normal. Subset signal: BBB-only (`BAMLC0A4CBBB`) for credit-cliff risk. | Free | FRED REST API | Daily, ~1d lag | **Yes** — `mcp__fred` | `BAMLC0A0CM` (also `BAMLC0A4CBBB` for BBB sub-index) |
| 3 | **Excess Bond Premium (EBP)** | Gilchrist-Zakrajšek decomposition of corp credit spread net of expected default. Captures investor risk appetite. | Best-in-class recession predictor (12m-ahead probability published alongside). Outperforms term spread in some specs. EBP > 0 = stressed; > +0.5σ = caution. Caveat: monthly only, history can revise. | Free | Direct CSV download from Federal Reserve | Monthly, posted ~10am 4th business day | **No MCP** — direct HTTPS GET | `https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv` (cols: `date, gz_spread, ebp, est_prob`) |
| 4 | **Swap spreads** | Treasury yield minus matched-tenor swap rate (sign convention varies). Negative-and-widening = bank balance-sheet/dealer-capacity stress (post-2015 negative regime). | Information-rich during dealer-stress events (2019 repo, March 2020). Less binary than HY-OAS. Compute as `DGS10 − ICERATES1100USD10Y`. | Free | FRED REST API (compute spread from two series) | Daily | **Yes** — `mcp__fred` | `ICERATES1100USD10Y` (10y USD ICE swap rate) minus `DGS10` (10y Treasury). 2/5/30y tenors also available under `ICERATES1100USD{2,5,30}Y`. |
| 5 | **TED spread** | 3M LIBOR vs 3M T-bill (legacy unsecured-vs-risk-free). | **Discontinued post-LIBOR.** FRED `TEDRATE` series flagged DISCONTINUED (LIBOR removed 2022-01-31). Modern equivalent: SOFR-Tbill spread (signal #10). Skip TEDRATE; track #10 instead. | Free (legacy only) | FRED | n/a (frozen) | `mcp__fred` (read-only of historical) | `TEDRATE` (DISCONTINUED) |
| 6 | **CDX HY index spread** | Markit/IHS credit-default-swap index for North American high-yield (CDX.NA.HY); rolls every 6 months. | Faster-moving cousin of cash-bond HY-OAS. Often leads cash spreads by 1-3 days during dislocations. **For our system, HY-OAS (signal #1) suffices** — CDX adds little above what BAMLH0A0HYM2 already shows for an equity-research sidecar. | Daily settlement freely available from ICE; intraday/real-time = paid | ICE web (manual scrape) or paid Markit/Bloomberg feed | EOD free; intraday paid | No | `https://www.theice.com/cds/MarkitIndices.shtml` (manual). Bloomberg/Markit pricing on request. |
| 7 | **MOVE index** | ICE BofA U.S. Bond Market Option Volatility Estimate — implied vol of 1m ATM options on 2/5/10/30y Treasuries. Bond-market VIX. | Spikes during rate-shock regimes (March 2020, Sep 2022 gilt-crisis spillover, March 2023 SVB). Useful as confirmation when HY-OAS ambiguous. Normal range 55-130; >120 = stress. | Free EOD via Yahoo; paid for real-time/historical bulk | Yahoo Finance `^MOVE` (page is free; programmatic download unreliable since Yahoo deprecated CSV). Real-time = ICE/Cboe subscription. | EOD daily (delayed) | No | `https://finance.yahoo.com/quote/%5EMOVE/`. **NOT** on FRED (confirmed by FRED Volatility Indexes catalog enumeration — VIX, VXV, VXN are present; MOVE is not). |
| 8 | **Chicago Fed NFCI** | Composite financial conditions index, 105 inputs across money/debt/equity/banking/shadow-banking. Weekly. | Headline composite — convenient one-number read. Subindexes (`NFCICREDIT`, `NFCIRISK`, `NFCILEVERAGE`, `NFCINONFINLEVERAGE`) decompose the signal. **Adjusted version `ANFCI`** strips out the part correlated with current macro, leaving idiosyncratic financial-conditions signal — usually preferred for forward-looking work. | Free | FRED REST API | Weekly (Wednesday release, prior-Friday data) | **Yes** — `mcp__fred` | `NFCI`, plus `ANFCI`, `NFCICREDIT`, `NFCIRISK`, `NFCILEVERAGE`, `NFCINONFINLEVERAGE` |
| 9 | **STLFSI** | St. Louis Fed Financial Stress Index (current version: STLFSI4). 18-component weekly composite (interest rates, yield spreads, other indicators). Mean-zero by construction. | Redundant with NFCI for our purposes — both are composites of similar inputs. Include only if cross-checking NFCI (rare divergences are themselves a signal). | Free | FRED REST API | Weekly | **Yes** — `mcp__fred` | `STLFSI4` (note: original `STLFSI` discontinued; use `STLFSI4`) |
| 10 | **Repo / SOFR spreads** | SOFR (Secured Overnight Financing Rate) is the post-LIBOR risk-free rate. Spread vs 3M T-bill (`DTB3`) or vs IORB approximates the modern "TED-equivalent" funding-stress signal. | Caught Sep-2019 repo spike, March-2020 dash-for-cash. Spread normally <10bp; >25bp = funding stress. | Free | FRED REST API; raw NY Fed data also free at `newyorkfed.org/markets/reference-rates/sofr` | Daily | **Yes** — `mcp__fred` | `SOFR` (overnight), `SOFR30DAYAVG`, `SOFRINDEX`. Compute `SOFR − DTB3` for the spread. |

---

## Recommended priority

### Tier 1 — must-have (wire into MacroCycleAgent S0 sidecar)

1. **HY-OAS** (`BAMLH0A0HYM2`) — primary credit-stress trigger. The +300bp-from-low rule is the operator's stated heuristic; this series is the canonical implementation.
2. **NFCI** (`NFCI` + `ANFCI`) — composite anchor. Weekly is fine for a regime sidecar that doesn't need intraday.
3. **EBP** (`ebp_csv.csv` from federalreserve.gov) — best forward-looking recession signal. Monthly cadence dovetails with the operator's macro-cycle review.
4. **IG-OAS BBB** (`BAMLC0A4CBBB`) — credit-cliff cusp tracker; specifically the "fallen-angel" risk that matters for equity-research-by-name.
5. **SOFR-Tbill** (`SOFR` − `DTB3`) — modern funding-stress; replaces TED. Daily.

All five are FRED-via-existing-`mcp__fred` except EBP (one direct-HTTPS-GET to a permanent CSV URL — trivial to add).

### Tier 2 — nice-to-have (add when bandwidth allows)

6. **Swap spreads** (`ICERATES1100USD10Y` − `DGS10`) — only fires during dealer-stress events; expensive in attention-budget for a low-base-rate signal.
7. **MOVE index** (Yahoo `^MOVE`, manual / occasional scrape) — confirmatory, not primary. Worth a weekly manual check; not worth scraping infrastructure.
8. **STLFSI4** — already redundant with NFCI; track only when divergence is itself the signal.
9. **NFCI subindexes** (`NFCICREDIT` etc.) — useful for *attributing* an NFCI move; add when post-mortem'ing a regime call.

### Skip / unaffordable

- **TED spread** (`TEDRATE`) — discontinued, replaced by SOFR-Tbill (Tier 1 #5). Do not track.
- **CDX HY real-time / intraday** — requires Bloomberg or Markit feed (pricing on request, almost certainly >$1k/mo). HY-OAS gives ~95% of the equity-research signal at $0/mo. **Skip.**
- **CDX HY EOD via ICE manual page** — daily settlement is technically free but requires manual scrape; HY-OAS already covers this dimension. Skip unless a credit-specific use case emerges.
- **MOVE real-time** — ICE/Cboe direct feed pricing on request; equity-research sidecar does not need intraday Treasury vol. EOD via Yahoo is sufficient.

---

## Notes & caveats

### Existing MCP coverage is excellent

8 of 10 signals are reachable today via `mcp__fred.get_series(<series_id>)`. No new MCP server is needed for Tier 1. The only non-FRED Tier-1 source is the EBP CSV, which is a single permanent URL (`https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv`, public, no auth) — wirable as a 10-line `httpx.get` inside MacroCycleAgent or as a thin extension to `mcp__fred` if we want to keep "macro data" surface uniform.

### MOVE is genuinely not on FRED

Confirmed via FRED's Volatility Indexes catalog (release `rid=209` and category `32425`) — VIX (`VIXCLS`), VXV (`VXVCLS`), VXN (`VXNCLS`), GVZ, OVX are listed; MOVE is not. (`VXTYN`, the CBOE 10y T-Note Volatility Futures, is the closest FRED proxy but is itself **DISCONTINUED**.) Yahoo `^MOVE` is delayed/EOD; CSV download was historically free but Yahoo has deprecated programmatic CSV access — expect manual or scrape if we want it. Worth waiting until a use case emerges before building scrape infra.

### Swap-rate FRED series gotcha

The legacy daily/weekly/monthly swap-rate series `DSWP10`, `WSWP10`, `MSWP10` are all DISCONTINUED (Oct 2016) — they were ISDA-LIBOR-based. The active replacement on FRED is the **ICE Swap Rate** family `ICERATES1100USD{1,2,3,5,7,10,15,20,30}Y` (USD, 11:00 London fixing). Use these going forward. Sign convention: traditional "swap spread" = swap rate − Treasury. Persistently negative at long tenors since 2015 (BIS WP 705 explanation: balance-sheet costs).

### STLFSI version warning

The original `STLFSI` was discontinued; current version is `STLFSI4`. Skill prompts and any cached references must use `STLFSI4` — `STLFSI` will silently return stale data through the discontinuation date.

### EBP revision behavior

EBP entire history can revise each month (firms revise balance-sheet inputs; quarterly→monthly disaggregation). For backtesting, treat EBP as a *vintage* series — the current CSV is the latest revision, not what was knowable at past dates. **This matters for the BacktestingFramework contamination check**: if MacroCycleAgent uses EBP as a feature, walk-forward must use the as-of vintage, not the current revision. The Federal Reserve does NOT publish a public ALFRED-equivalent vintage history for EBP; this is a known limitation. Mitigation: lag the signal by 1 quarter when used in backtest, or fetch ALFRED's `gz_spread` proxy.

### CDX-HY: free-EOD claim verification

Public reporting (multiple sources) says ICE publishes daily settlement prices on CDX indices and 5y single-name CDS free at `theice.com/cds/MarkitIndices.shtml`. Page is browser-accessible but our `WebFetch` returned 403 against ice.com domains, suggesting JS-rendered or anti-scrape. Manual collection only at this stage — not practical to wire as a continuous feed without a different vendor. **Verdict: skip CDX entirely; HY-OAS is the cash-bond cousin and is fully automated via FRED.**

### Pricing notes

All FRED data: free, no rate-limit issue at our usage volume (free key, ~120 calls/day max under FRED's posted policy). EBP CSV: free, no auth. Bloomberg: pricing on request (typically $24k+/seat/yr — out of budget). Markit/IHS direct CDX feed: pricing on request. ICE direct feeds (MOVE real-time, CDX intraday): pricing on request. **No paid signal recommended for inclusion.**

---

## Sources

- HY-OAS: [FRED BAMLH0A0HYM2](https://fred.stlouisfed.org/series/BAMLH0A0HYM2)
- IG-OAS: [FRED BAMLC0A0CM](https://fred.stlouisfed.org/series/BAMLC0A0CM); BBB: [BAMLC0A4CBBB](https://fred.stlouisfed.org/series/BAMLC0A4CBBB)
- EBP: [Federal Reserve FEDS Note (Updating Recession Risk and the EBP)](https://www.federalreserve.gov/econres/notes/feds-notes/updating-the-recession-risk-and-the-excess-bond-premium-20161006.html); CSV at `https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv` (verified 200, March 2026 latest observation, no auth).
- Swap rates: [FRED Interest Rate Swaps category](https://fred.stlouisfed.org/categories/32299); active series e.g. `ICERATES1100USD10Y` ([TradingView mirror](https://www.tradingview.com/symbols/FRED-ICERATES1100USD10Y/)).
- TED: [FRED TEDRATE (DISCONTINUED)](https://fred.stlouisfed.org/series/TEDRATE).
- CDX: [ICE Markit Indices](https://www.theice.com/cds/MarkitIndices.shtml); [Markit CDX product page](https://www.ice.com/products/28687609/Markit-CDXNAHY).
- MOVE: [Yahoo Finance ^MOVE](https://finance.yahoo.com/quote/%5EMOVE/); [FRED Volatility Indexes category 32425](https://fred.stlouisfed.org/categories/32425) (MOVE absent).
- NFCI: [FRED NFCI](https://fred.stlouisfed.org/series/NFCI); [Chicago Fed NFCI About](https://www.chicagofed.org/research/data/nfci/about); subindexes `ANFCI`, `NFCICREDIT`, `NFCIRISK`, `NFCILEVERAGE`, `NFCINONFINLEVERAGE`.
- STLFSI: [FRED STLFSI4](https://fred.stlouisfed.org/series/STLFSI4); legacy `STLFSI` discontinued.
- SOFR: [FRED SOFR](https://fred.stlouisfed.org/series/SOFR); [NY Fed SOFR reference rate page](https://www.newyorkfed.org/markets/reference-rates/sofr/); averages `SOFR30DAYAVG`, `SOFR90DAYAVG`, `SOFR180DAYAVG`, `SOFRINDEX`.
