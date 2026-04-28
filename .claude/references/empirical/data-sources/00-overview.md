# S0 Data Sources — Master Overview

**Purpose.** Map every signal that feeds the S0 (regime context) sidecar to a concrete data source — free vs paid, API vs scrape, latency, reliability. Produced by 5 parallel research subagents (one per S0 dimension) per the Section 3 data-architecture review.

**Headline finding: the entire Tier 1 stack across all 5 dimensions is achievable at $0/mo of new tooling spend.** Existing MCP servers (`mcp__fred` + `mcp__market_data` + `mcp__edgar` + `mcp__fundamentals`) cover ~85% of must-have signals. The remaining ~15% needs trivial fetcher wrappers (CSV / xlsx / PDF / scrape) — no new vendor relationships, no new costs.

---

## 1. Cost summary by dimension

| Dimension | Total signals covered | Tier 1 must-have count | Incremental cost | Existing MCP coverage |
|---|---|---|---|---|
| D1 — Economic-cycle | 9 | 6 | $0/mo | 5 of 6 via `mcp__fred`; EBP needs CSV fetcher |
| D2 — Credit-stress | 10 | 5 | $0/mo | 8 of 10 via `mcp__fred`; EBP shared from D1 |
| D3 — Vol regime | 14 | 7 | $0/mo | All Tier 1 via `mcp__fred` + `mcp__market_data` (yfinance) |
| D4 — Dollar regime | 17 (8 primary + sub-variants) | 6 | $0/mo | All Tier 1 via existing MCPs; no new infrastructure |
| D5 — 4-box (growth × inflation) | 23 (11 growth + 12 inflation) | 12 | $0/mo | 10 via `mcp__fred`; ISM scrape + NY Fed Nowcast xlsx + Yardeni NERI PDF |
| **Combined** | **73 signals across dimensions** | **36 Tier 1** | **$0/mo new spend** | ~85% existing-MCP coverage |

(LLM API costs covered by Claude Code Max subscription. The original $250/mo budget for tooling remains untouched and is available as runway for v0.5+ upgrades.)

---

## 2. Per-dimension deliverables

| Lane file | Coverage |
|---|---|
| [D1 — Economic-cycle](D1-economic-cycle.md) | Yield curves (10y-3m, 2y-10y, NTFS), EBP, Sahm Rule, LEI, CFNAI, ISM PMI, GDPNow, NY Fed Nowcast |
| [D2 — Credit-stress](D2-credit-stress.md) | HY-OAS, IG-OAS, EBP, swap spreads, TED (deprecated), CDX HY, MOVE, NFCI, STLFSI, SOFR-Tbill |
| [D3 — Vol regime](D3-vol-regime.md) | VIX (spot + 9D/3M/6M term structure), VIX/VIX3M ratio, VVIX, SKEW, realized vol, VIX futures basis, MOVE, plus cross-asset vol (OVX oil, GVZ gold, EVZ euro, VXEEM EM) |
| [D4 — Dollar regime](D4-dollar-regime.md) | DXY, trade-weighted broad dollar (DTWEXBGS), advanced-foreign / emerging-market trade-weighted indices, FX crosses (EUR/JPY/GBP/CNY), real broad effective exchange rate, BBDXY (skip), carry-trade indices (DBV ETF substitute), DXY 200d MA |
| [D5 — 4-box (growth × inflation)](D5-bridgewater-4box.md) | Growth: ISM Mfg/Svcs PMI, S&P Global flash PMI, LEI, GDPNow, NY Fed Nowcast, INDPRO, ADS index, earnings revisions (Yardeni). Inflation: Core CPI, Core PCE, T5YIE/T10YIE/5y5y breakevens, Trimmed-Mean PCE, Sticky-Price CPI, PPI, U-Mich expectations |

---

## 3. New wrappers needed (all trivial, all free)

These are the only NEW pieces of code/infrastructure needed beyond what's wired today:

| Wrapper | Purpose | Effort | Shared by |
|---|---|---|---|
| **EBP CSV fetcher** | Single HTTPS-GET to `federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv`; cache + parse | ~30 lines Python | D1, D2 |
| **ISM PMI scraper** | Monthly press-release scrape OR free DBnomics aggregator at `api.db.nomics.world/v22/series/ISM/pmi/pm` | ~50 lines Python | D1, D5 |
| **NY Fed Nowcast xlsx fetcher** | Weekly Friday xlsx download from `newyorkfed.org/medialibrary/Research/Interactives/Data/NowCast/Downloads/...` | ~40 lines Python | D1, D5 |
| **Yardeni NERI PDF parser** | Weekly PDF parse at `archive.yardeni.com/pub/peacocksp500revisions.pdf` (substitute for paid I/B/E/S earnings-revisions feed) | ~60 lines Python | D5 (Tier 2) |
| **VIX futures basis (Cboe CFE)** | Per-contract CSV download + front/next-month roll logic | ~80 lines Python | D3 (Tier 2 — adds Simon-Campasano signal) |

Total new code: ~260 lines across 5 wrappers, all reading from free public sources. These could be implemented as a single new MCP server (e.g., `mcp__macro_extras`) or as in-process helpers in skills that consume these signals.

---

## 4. Critical traps surfaced (must encode in skill prompts)

These are silent-failure risks that subagents flagged across dimensions. Skills that consume these signals must use the correct series IDs / methodologies or get stale or wrong data:

### Series-ID traps (FRED has retired or replaced multiple canonical series)

| Trap | Wrong (deprecated/dead) | Right (current) | Impact if missed |
|---|---|---|---|
| Sahm Rule (D1) | `SAHMCURRENT` | `SAHMREALTIME` | Backtests use revised data not knowable at decision time → look-ahead bias |
| St. Louis FSI (D2) | `STLFSI` | `STLFSI4` | Silent stale data — `STLFSI` discontinued |
| Swap rates (D2) | `DSWP10` / `MSWP10` / `WSWP10` | `ICERATES1100USD{tenor}Y` family | All old IDs DISCONTINUED |
| Money-market stress (D2) | `TEDRATE` (DEAD post-LIBOR 2022-01-31) | `SOFR` − `DTB3` spread | Old TED returns NaN |
| Conference Board LEI (D1, D5) | Paid Conference Board feed | Philly Fed `USSLIND` proxy + 10 free FRED components | Avoids subscription cost; minor correlation slip |

### Vintage-discipline traps (data revises)

- **EBP entire history revises monthly.** Backtesting framework needs either (a) 1-quarter lag to avoid look-ahead, or (b) use `gz_spread` from ALFRED (vintage-preserved). Federal Reserve does not publish EBP's own vintage history.
- **Conference Board LEI** components similarly revise; `USSLIND` from Philly Fed is real-time but not vintage-corrected.

### Data-availability traps

- **ISM PMI is NOT on FRED post-2016** (licensing dispute). FRED's old `NAPM` IDs are dead. Use ISM scrape, DBnomics, or Trading Economics free mirror.
- **NY Fed Nowcast had a Sep-2021 to Sep-2023 suspension gap.** Resumed; weekly Friday xlsx since.
- **VIX9D and VIX6M are NOT on FRED** — only `^VIX9D` / `^VIX6M` via yfinance + Cboe CDN CSVs. FRED only carries VIXCLS (spot) and VXVCLS (3M).
- **VIX futures basis requires Cboe CFE per-contract data + roll logic.** Not pre-rolled anywhere free.
- **MOVE official ICE feed is institutional-only.** yfinance `^MOVE` is the only free path; reliable for daily but unstable for real-time.

### Methodology traps

- **DXY excludes CNY.** Built in 1973 and frozen; the 6-currency basket misses China entirely. **`DTWEXBGS` (Fed broad-dollar) is structurally better** for measuring global dollar-stress per L1 patterns #23 and #25. DXY remains useful for risk-on/risk-off retail behavior tracking but should not be the primary dollar regime signal.
- **Bridgewater actually classifies growth × inflation on `actual − expectation`**, not raw level. Computing PMI > 50 = expansion is a *crude* approximation; PMI > consensus = surprise is what Bridgewater documents using. Build the classifier on surprises (deltas vs consensus or vs trailing trend) not raw levels — materially improves classifier accuracy.

---

## 5. Skip recommendations (paid sources NOT worth buying at <$1M scale)

| Source | Why skip | Free substitute |
|---|---|---|
| Conference Board LEI direct feed | Paid; pricing-on-request | Philly Fed `USSLIND` + 10 FRED components |
| Bloomberg BBDXY | $24k/yr Terminal-only | `DTWEXBGS` + USDU ETF |
| JPM EMCI / DB EM-FX baskets | Bloomberg subscription | `DTWEXEMEGS` (~0.95 monthly correlation) |
| CDX HY intraday | Markit/Bloomberg subscription | `BAMLH0A0HYM2` HY-OAS covers the equity-research use case |
| ICE MOVE real-time | Institutional only | yfinance `^MOVE` daily — adequate for daily S0 sidecar |
| FactSet / IBES / Refinitiv earnings revisions | Paid-only | Yardeni Research weekly NERI PDF (free; uses I/B/E/S source data, publishes 3-month MA of analyst-up minus analyst-down) |

---

## 6. Paid upgrade paths if v0.5+ requires real-time

These are worth budget consideration only if specific use-cases at v0.5+ make them load-bearing:

| Source | Cost | What it adds | Trigger to consider |
|---|---|---|---|
| Polygon.io Indices Starter | $29/mo | 15-min delayed VIX + indices | If S0 daily sidecar needs sub-day latency |
| Polygon.io Indices Advanced | $199/mo | Real-time indices | If P7 entry execution becomes price-sensitive (consumes most of $250 budget alone) |
| Polygon.io Currencies Starter | $29-49/mo | Real-time FX crosses | Only if intraday FX signals matter |
| Tradier Pro | **Free** if used as brokerage | Real-time VIX + options chain | If broker selection at v0.5+ goes to Tradier — bonus, no incremental cost |
| Sharadar Core Fundamentals | $75/mo (already paid) | Point-in-time financials | Already wired via `mcp__fundamentals` |

The remaining ~$170/mo of headroom in the operator's $250/mo budget is **available runway** — not committed.

---

## 7. Implementation priority for v0.1 build

If implementing S0 today, here's the build order:

**Phase 1 — Wire FRED comprehensively (already done; validate):**
- Confirm `mcp__fred` covers the canonical series list (T10Y3M, T10Y2Y, BAMLH0A0HYM2, BAMLC0A4CBBB, NFCI, STLFSI4, SOFR, DTB3, VIXCLS, VXVCLS, DTWEXBGS, DTWEXEMEGS, FX crosses, INDPRO, CPILFESL, PCEPILFE, T5YIE, T10YIE, T5YIFR, MICH, USSLIND, GDPNOW, SAHMREALTIME, CFNAI, CFNAIMA3) and that the trap-list above is encoded in any helper.

**Phase 2 — Build the 5 trivial wrappers (~260 lines total):**
- EBP CSV fetcher (D1 + D2 dependency)
- ISM PMI scraper / DBnomics (D1 + D5 dependency)
- NY Fed Nowcast xlsx (D1 + D5 dependency)
- Yardeni NERI PDF (D5 only — earnings-revisions substitute)
- VIX futures basis (D3 Tier 2 — adds Simon-Campasano signal)

**Phase 3 — Wire `^MOVE`, `^VVIX`, `^SKEW` via `mcp__market_data` yfinance fallback** (D2 + D3 dependency).

**Phase 4 — S0 classifier service:**
- Reads from above sources daily
- Outputs probability distribution per dimension (Section 3 Q3 locked = probability-distribution form)
- Stores in Postgres `regime_state` table (versioned; supports replay)
- Fires push events on regime-shift confluence (Section 3 Q3 — TBD threshold logic)

---

## 8. Open architectural decisions deferred to Section 3 closure

These remain to be locked by operator decision; data-source research informs but doesn't decide:

- **Q1 (operator decision pending):** which output dimensions does S0 produce — minimum (3) / targeted (4) / practitioner-grade (5)?
- **Q2 (operator decision pending):** how to encode post-QE uncertainty caveat (Pattern #20) — confidence haircut / regime-of-regime tag / trust historical signal
- **Q3 (operator decision pending):** regime-shift event-fire threshold — probability / threshold+duration / threshold+duration+confluence
- **Q4 (operator decision pending):** refresh cadence — daily / weekly / event-driven

After these lock, the S0 sidecar specification is complete and skill-build can proceed.

---

## 9. Maintenance notes

- All FRED series IDs are stable but FRED occasionally retires or replaces series (the trap list above documents recent examples). Annually re-validate the canonical series list.
- ISM PMI scrape target page may change — wrap in defensive parser; alert on 404 or schema change.
- NY Fed Nowcast suspended 2021-2023; could suspend again. Have fallback to Atlanta Fed GDPNow.
- Yardeni publishes their NERI PDF weekly — file naming is stable but worth monitoring.
- Subagent-research date: 2026-04-29.
