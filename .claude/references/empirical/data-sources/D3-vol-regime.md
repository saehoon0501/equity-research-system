# D3 — Vol-regime data sources

Scope: data sources for the **Volatility regime** dimension of the S0 regime context sidecar.
Operator constraints: total non-LLM budget $250/mo; free preferred.

Existing project integration baseline:
- `mcp__market_data` — yfinance fallback chain in `src/mcp/market_data/server.py`. yfinance handles VIX-family tickers (`^VIX`, `^VIX9D`, `^VIX3M`, `^VIX6M`, `^VVIX`, `^SKEW`, `^MOVE`, `^OVX`, `^EVZ`, `^GVZ`) at EOD with no extra subscription. Real-time on these caret-prefixed indices is NOT reliable through yfinance (intraday lags, occasional gaps).
- `mcp__fred` — `get_series(series_id)` covers FRED VIX-family series for free at EOD.
- VIX futures (VX1, VX2) — NOT covered by either MCP today; need Cboe CFE CSVs or a paid feed.

---

## Signal-by-signal table

| Signal | Definition | Empirical edge | Cost | Access | Latency | Existing MCP? | Source endpoint |
|---|---|---|---|---|---|---|---|
| **VIX (spot)** | Cboe 30-day implied vol on S&P 500 (variance-swap-style) | Canonical fear gauge; level + 1-day change drive risk-on/off, vol-targeting flows. VIX > 30 → elevated stress; > 40 → crisis. | Free | FRED API (`VIXCLS`, daily 1990–present); yfinance `^VIX`; Cboe CSV `cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv` | EOD on FRED/Cboe; intraday on yfinance (delayed ~15 min) | Yes — `mcp__fred.get_series("VIXCLS")` and `mcp__market_data.get_prices("^VIX")` | `https://fred.stlouisfed.org/series/VIXCLS`, `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv` |
| **VIX9D** | Cboe 9-day implied vol on S&P 500 | Front-of-curve stress. VIX9D > VIX (inversion at the very-front) precedes near-term shocks (FOMC, NFP, CPI weeks). | Free | yfinance `^VIX9D`; Cboe CSV `cdn.cboe.com/api/global/us_indices/daily_prices/VIX9D_History.csv` | EOD | Partial — yfinance via `mcp__market_data` works; not on FRED | `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX9D_History.csv` |
| **VIX3M (VXV)** | Cboe 3-month implied vol on S&P 500 | Anchor for VIX/VIX3M term-structure ratio. Slow-moving long leg; less noisy than VIX in calm regimes. | Free | FRED `VXVCLS` (2007-12-04 → present, daily); yfinance `^VIX3M`; Cboe CSV `VIX3M_History.csv` | EOD | Yes — `mcp__fred.get_series("VXVCLS")` | `https://fred.stlouisfed.org/series/VXVCLS`, `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv` |
| **VIX6M** | Cboe 6-month implied vol on S&P 500 | Long anchor for term structure; useful for triangulating slope shape (curve linear vs. kinked). | Free | yfinance `^VIX6M`; Cboe CSV `VIX6M_History.csv` | EOD | Partial — yfinance only; not directly on FRED | `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX6M_History.csv` |
| **VIX term-structure ratio** | VIX / VIX3M | > 1.0 = backwardation = acute stress (regime shift signal); < 0.92 = deep contango = complacency. Documented as one of the more reliable single-indicator regime flags. | Free (derived) | Computed from VIXCLS/VXVCLS via FRED; or `^VIX/^VIX3M` via yfinance | EOD | Yes (derive from existing FRED + market_data) | Derived |
| **VVIX** | Vol-of-vol; implied vol of VIX itself | Stress amplifier. VVIX > 110 in calm regime is unusual and often presages VIX spikes; VVIX/VIX ratio is a tail-hedging signal. | Free | yfinance `^VVIX`; Cboe CSV `VVIX_History.csv` (history from 2006-03) | EOD | Partial — yfinance `^VVIX` via `mcp__market_data.get_prices`; NOT on FRED | `https://cdn.cboe.com/api/global/us_indices/daily_prices/VVIX_History.csv` |
| **SKEW index** | Cboe SKEW; implied tail-risk pricing in S&P options | Measures relative cost of OTM puts; SKEW > 145 historically associated with elevated tail-event probability (though weak edge as standalone). Useful as confirming signal alongside VIX/VVIX. | Free | yfinance `^SKEW`; Cboe CSV `SKEW_History.csv` (history from 1990) | EOD | Partial — yfinance only; NOT on FRED | `https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv` |
| **Realized volatility (S&P 500)** | Rolling-window historical vol of SPX returns (10d / 20d / 30d / 60d annualized) | Implied-realized spread (VIX – RV20) is a vol-risk-premium proxy; positive = sellers paid for vol; negative spread = panic regime. | Free (derived) | Compute from SPX or SPY daily closes via yfinance / FRED `SP500` | EOD | Yes (derive locally) | Derived from `mcp__market_data.get_prices("SPY")` |
| **VIX futures basis (VX1/VX2)** | Front-month VIX future vs. next-month future; or VX1 vs. VIX spot | Simon & Campasano (Journal of Derivatives 2014, 21(3): 54–69) — basis has substantial predictive power for VIX-futures price changes (β ≈ −0.79 on lagged basis); profitable short-vol-in-contango / long-vol-in-backwardation strategy after costs. | Free with effort | Cboe CFE: `cboe.com/us/futures/market_statistics/historical_data/` — per-contract CSVs (Trade Date, OHLC, Settle, Volume, OI). Each contract month = separate file; needs roll logic to construct VX1/VX2 continuous series. Free aggregator: vixcentral.com (visualization, no bulk export) | EOD | **No** — neither MCP exposes this; would require new fetcher or paid feed | `https://www.cboe.com/us/futures/market_statistics/historical_data/` |
| **MOVE index** | ICE BofA US Bond Market Option Volatility Estimate; Treasury yield-curve implied vol | Cross-asset stress confirmation. MOVE-VIX divergence is a canonical signal: MOVE rising while VIX flat → rates-driven shock (e.g., 2022 Mar SVB precursor); both rising together → broad risk-off. | Free (with caveat) | yfinance `^MOVE`; investing.com / TradingView `TVC:MOVE`. Not on FRED. ICE proper requires institutional license. | EOD via yfinance; institutional feed for real-time | Partial — yfinance via `mcp__market_data.get_prices("^MOVE")`; quality variable | `https://finance.yahoo.com/quote/%5EMOVE/history/` |
| **EVZ** | Cboe EuroCurrency Volatility Index (FXE-based, VIX-style 30d implied) | Cross-asset FX stress; useful when DXY moves are accompanied by EVZ spikes (FX-driven regime flag). Less load-bearing than VIX/MOVE. | Free | FRED `EVZCLS`; yfinance `^EVZ`; Cboe CSV | EOD | Yes — `mcp__fred.get_series("EVZCLS")` | `https://fred.stlouisfed.org/series/EVZCLS` |
| **OVX** (bonus cross-asset) | Cboe Crude Oil ETF Volatility Index (USO-based, 30d implied) | Cross-asset commodity stress; correlates with energy-sector beta during oil shocks (2020 Mar, 2022 Feb). | Free | FRED `OVXCLS` (2007-05-10 → present); yfinance `^OVX` | EOD | Yes — `mcp__fred.get_series("OVXCLS")` | `https://fred.stlouisfed.org/series/OVXCLS` |
| **GVZ** (bonus cross-asset) | Cboe Gold ETF Volatility Index (GLD-based) | Safe-haven flow tell — GVZ spike concurrent with VIX spike confirms broad-risk-off; GVZ flat while VIX rises = equity-only event. | Free | FRED `GVZCLS`; yfinance `^GVZ` | EOD | Yes — `mcp__fred.get_series("GVZCLS")` | `https://fred.stlouisfed.org/series/GVZCLS` |
| **VXEEM** (bonus cross-asset) | Cboe EM ETF Volatility Index (EEM-based) | EM-specific stress; useful for non-US-equity regime confirmation. | Free | FRED `VXEEMCLS` (2011-03-16 →); yfinance `^VXEEM` | EOD | Yes — `mcp__fred.get_series("VXEEMCLS")` | `https://fred.stlouisfed.org/series/VXEEMCLS` |

---

## Recommended priority

### Tier 1 (must-have, all free, all integrate via existing MCPs)
1. **VIX spot** — FRED `VIXCLS` via `mcp__fred`
2. **VIX3M** — FRED `VXVCLS` via `mcp__fred`
3. **VIX/VIX3M term-structure ratio** — derived from #1 and #2
4. **VVIX** — yfinance `^VVIX` via `mcp__market_data` (or Cboe CSV nightly cache)
5. **SKEW** — yfinance `^SKEW` via `mcp__market_data` (or Cboe CSV nightly cache)
6. **Realized vol (SPX 20d annualized)** — derived locally from SPY daily closes
7. **MOVE index** — yfinance `^MOVE` via `mcp__market_data` (cross-asset confirmation)

These seven cover the canonical vol-regime dashboard at zero marginal cost. EOD is sufficient for an S0 sidecar that refreshes daily.

### Tier 2 (nice-to-have, free)
- **VIX9D** — yfinance `^VIX9D` or Cboe CSV; useful for inversion signal
- **VIX6M** — yfinance `^VIX6M` or Cboe CSV; rounds out the term-structure curve
- **EVZ / OVX / GVZ / VXEEM** — FRED `EVZCLS / OVXCLS / GVZCLS / VXEEMCLS`; cross-asset corroboration when modeling sector-specific regimes (energy beta = OVX; FX-sensitive names = EVZ; safe-haven plays = GVZ)
- **VIX futures basis (VX1/VX2)** — Cboe CFE CSV downloads; requires per-contract roll logic. Justified if backtesting Simon-Campasano basis strategy or wanting "live" contango/backwardation. Build cost: small one-time fetcher + roll module. Operationally cheap.

### Skip / paywalled (not needed within $250/mo budget)
- **Cboe DataShop on-demand** — paid (per-dataset, $50–$500+); bulk historical for proprietary indices like SKEW intraday, custom term structures. Skip — Cboe CDN free CSVs cover EOD.
- **ICE MOVE official feed** — institutional only, four-figure monthly. Skip — yfinance `^MOVE` is adequate for sidecar.
- **firstratedata intraday VIX/VX (15+ years tick)** — paid one-time license; nice for backtesting but not needed for daily S0 sidecar.
- **dxFeed CFE** — paid market-data feed; skip.

### Paid sources to consider only if real-time becomes load-bearing (v0.5+)
- **Polygon.io Indices Starter** — $29/mo, 15-min delayed indices including VIX. Cheap upgrade path if intraday is needed.
- **Polygon.io Indices Advanced** — $199/mo, real-time. Borderline within budget; only if intraday vol-regime triggers become part of execution layer.
- **Tradier Pro** — free real-time options/index data IF used as brokerage; otherwise no real-time. If brokerage is Tradier (v0.5+ entry), this is a free bonus.

---

## Notes & caveats

### VIX term structure: free coverage
- VIXCLS (spot) and VXVCLS (3M) are on FRED — fully free, EOD, daily 1990 / 2007 starts respectively.
- VIX9D and VIX6M are NOT on FRED but ARE on yfinance (`^VIX9D`, `^VIX6M`) and as free Cboe CDN CSVs.
- **Recommendation:** primary fetch via FRED for VIX/VIX3M; secondary fetch via yfinance for VIX9D/VIX6M. Build a small nightly job that pulls Cboe CDN CSVs as cross-check / backup (and to get VVIX/SKEW history past yfinance's spotty coverage).

### VVIX and SKEW: free historical from Cboe
- Both have free CSV downloads on Cboe CDN at the documented URL pattern: `https://cdn.cboe.com/api/global/us_indices/daily_prices/{INDEX}_History.csv`. SKEW history goes back to 1990; VVIX to 2006. No subscription needed. Note: Cboe CDN files are EOD and may lag intraday by hours.
- yfinance `^VVIX` and `^SKEW` work but have occasional gaps; treat Cboe CDN as authoritative.

### VIX futures basis — only signal NOT covered by existing MCPs
- VX1/VX2 daily settlement data is free from Cboe CFE (`cboe.com/us/futures/market_statistics/historical_data/`), but distributed as one CSV per contract month. Building VX1 (front month) and VX2 (next month) continuous series requires roll logic (use the futures expiration calendar Cboe also publishes).
- If backtesting Simon-Campasano (2014) basis strategy is desired (Tier 2), build a small `mcp__market_data` extension or a one-off `src/data/cfe_vix_futures.py` module that downloads + rolls. No additional cost.
- vixcentral.com gives a live visualization for free, but no bulk export — useful for spot-checking but not a programmatic source.

### MOVE index caveat
- `^MOVE` on yfinance is reliable enough for sidecar use (daily levels) but NOT for tick-by-tick. ICE official feed is institutional-only. For an S0 daily sidecar this is fine; for a real-time execution-layer signal it would need an upgrade path (likely a Bloomberg or ICE direct license, well outside $250 budget — skip).

### yfinance reliability
- yfinance is the only path to several of these (^VVIX, ^SKEW, ^VIX9D, ^VIX6M, ^MOVE) without a paid feed. It is brittle: silent gaps, occasional ticker remappings, and rate-limit issues on heavy use. **Mitigation:** dual-source where possible (FRED + Cboe CDN where available), cache locally in TimescaleDB, alert on stale data > 2 trading days.

### FRED vintage / revision behavior
- FRED VIX-family series are EOD reported and not revised (Cboe-published index values). Safe for backtests; no point-in-time reconstruction needed.

### SKEW interpretive caveat
- SKEW has weak standalone predictive power for SPX returns in the academic literature; treat as a confirming signal alongside VIX/VVIX/term-structure rather than a primary regime trigger.
