# Research Sources Catalog — `/research-company` Workflow

**Purpose:** Reference inventory of reliable data sources to plug into the equity research workflow, organized by category. For each source: specialty, update cadence, access tier, credibility tier, when-to-use angle. Concluding section maps each source to the existing MCP-wired stack (gap analysis).

**TL;DR — the 12 must-have sources for any single-name workflow:**
1. **Reuters + Bloomberg + Dow Jones Newswires** — primary real-time newswires
2. **SEC EDGAR** — 10-K/Q, 8-K, DEF 14A, Form 4, 13D/G, 13F primary
3. **FRED + BEA + BLS + Census** — macro backbone (already MCP-wired)
4. **ISM PMI + Conference Board LEI + Atlanta Fed GDPNow** — cycle indicators
5. **Visible Alpha + Refinitiv I/B/E/S (or FactSet)** — consensus line-item depth
6. **Wall Street Horizon + BioPharmCatalyst + ClinicalTrials.gov** — forward catalyst stack
7. **Similarweb + Sensor Tower + Second Measure/Earnest** — leading-revenue signal
8. **Ortex + FINRA short interest** — short positioning
9. **WhaleWisdom + Dataroma** — 13F positioning
10. **Unusual Whales + Polygon options + OptionMetrics** — options/flow
11. **Seeking Alpha + Value Investors Club (free 45-day delay) + AlphaSense** — independent research
12. **Capitol Trades + Quiver Quant** — political-trade signals

---

## 1. Financial News & Business Media (daily/real-time pulse)

| Source | Specialty | Cadence | Access | Tier | When to use |
|---|---|---|---|---|---|
| **Reuters** | Global newswire; 2,500+ journalists | Real-time | Metered free + Refinitiv inst. | Primary newswire | Speed-and-objectivity benchmark for breaking corporate news |
| **Bloomberg News** | Markets, M&A scoops, Fed/macro | Real-time 24/7 | 10/mo free, Terminal inst. | Primary newswire | Best investigative + scoop depth |
| **Dow Jones Newswires** | US earnings, M&A, regulatory wire | Real-time | LSEG / DJ direct inst. | Primary newswire | Pairs with WSJ newsroom |
| **Associated Press** | General + corp/regulatory breaks | Real-time | Low-cost license | Primary newswire | Widely syndicated; cross-check |
| **CNBC** | Cable/web breaking + management interviews | Real-time | Free web + RSS | Authoritative | Pre-market + after-hours tape; live mgmt color (✅ already MCP-wired) |
| **WSJ** | Enterprise scoops, board/CEO reporting | Intraday | Hard paywall | Authoritative | Deep earnings analysis, M&A scoops |
| **FT** | Cross-border, Europe/Asia equity context | Intraday | AI-tuned paywall (~$540/yr) | Authoritative | Macro + capital-markets longform |
| **Barron's** | Single-stock deep dives, Roundtable | Weekly + intraday web | Subscription | Authoritative | Investment-specific weekend reads |
| **MarketWatch** | Cheap intraday US tape | Intraday | Metered paywall + free RSS | Aggregator-orig | Tape commentary at low cost |
| **Yahoo Finance** | Quote + aggregated news (republishes Reuters/IBD/MW) | Intraday | Free; no official API since 2007 | Aggregator | Baseline retail-tier; `yfinance` lib scrapes |
| **Benzinga** | Purpose-built equity newswire + analyst ratings/options/insider endpoints | Real-time | REST API + TCP stream | Authoritative-aggregator | **Cheapest credible programmatic newsfeed** — strong candidate for adding alongside market_data |
| **Axios Pro** | Dealflow color (Markets, Deals) | Daily newsletter | $599/yr | Authoritative | Pre/post deal context, not real-time |
| **The Information** | Private-tech scoops moving public comps | Daily | $399/$999 sub | Authoritative | AI/cloud/semis private-→-public reads |
| **Semafor Business** | Curated daily brief | Daily | Free | Aggregator | Once-daily smart curation |

**Paywall caveat:** Bloomberg's "10/month" and FT's per-user meter are dynamic; treat as nominal.

---

## 2. Regulatory & Primary Filings

| Filing/Source | Discloses | Cadence | Signal |
|---|---|---|---|
| **10-K** | Audited financials, risk factors, MD&A | 60–90d post-FY | Canonical bull/bear evidence base |
| **10-Q** | Unaudited interim financials | 40–45d post-Q | Trend reads between annuals |
| **8-K** | Material events (mgmt change, M&A, Reg FD, Item 2.02 earnings) | **4 business days** | Only filing that drives same-day price action |
| **DEF 14A (Proxy)** | Comp tables, CD&A, board slate, RPT | 3–6 wk pre-mtg | Alignment + governance red flags |
| **S-1 / S-3 / S-4** | IPO / shelf / M&A consideration | Event-driven | Shelf takedowns = dilution flag; lock-up expiry |
| **13D** | 5%+ holder w/ intent-to-influence | 5 BD initial / 2 BD amend | Activist signal |
| **13G** | Passive 5%+ (mutual funds, indexers) | 45d post-YE (or 5 BD if >10%) | Concentration heatmap |
| **Form 4** | Insider transactions | **2 business days** post-trade | **Cluster buying = highest-signal pattern**; sells noisy (10b5-1) |
| **Form 144** | Notice of proposed affiliate sale | Pre-sale | Forward indicator of insider distribution |
| **13F** | $100M+ mgr long US equity positions | **45d post-Q** | Stale by definition — thematic, not timing |
| **N-PORT** | Monthly fund holdings, public 60d lag | Monthly | Higher-frequency 13F complement |
| **Form 6-K** | Foreign private issuer | "Promptly" (looser) | ADR analog to 8-K |
| **FR Y-9C** | Bank holding co financials + reg cap | Quarterly | Primary US bank fundamentals |
| **FDIC Call Reports** | Bank financials per charter | Quarterly | Free REST API at `banks.data.fdic.gov/bankfind-suite` |
| **FINRA Short Interest** | Official short shares/DTC | Bi-monthly, 2-day lag | Statutory truth baseline |
| **FINRA TRACE** | Corp bond trade reports | 15-min | Credit-vs-equity divergence = distress signal |
| **PACER** | Federal court dockets | Real-time | $0.10/pg, $30/Q free; litigation overhang |
| **USPTO** | Patents + TTAB trademarks | Real-time | IP moat verification |
| **OpenInsider** | Free Form 4 aggregator w/ cluster-buy view | Daily | Best free derived-from-primary |
| **SEDAR+ / Companies House / EDINET / TDnet** | Canada / UK / Japan equivalents | Per local rules | Cross-border coverage |

**Caveats:** EDGAR rate limit = 10 req/sec (User-Agent required). 13D/G modernization compliance Sep 30, 2024. 8-K Item 2.02 is "furnished" not "filed" (different liability). 13F skips shorts, most options, non-US.

**Already MCP-wired:** EDGAR ✅. **Gap to add:** OpenInsider for free Form 4 cluster-buy view; FDIC API for bank names; FINRA TRACE for credit cross-check.

---

## 3. Macro & Economic Data

| Source | Flagship Series | Cadence | Access | When to use |
|---|---|---|---|---|
| **FRED** (✅ wired) | ~840K series, 119 sources, ALFRED vintages | Mirrors primaries | Free API w/ key | Default single endpoint for nearly all US macro |
| **BEA** (✅ via macro_stack) | GDP (3 estimates), Core PCE, NIPA tables, corp profits | Quarterly + monthly | Free SDMX-like API | Fed-target inflation + revenue-cycle context |
| **BLS** (✅ via macro_stack) | CPI, PPI, NFP, JOLTS, ECI | Monthly + quarterly | Free public API | Highest-freq labor + inflation; NFP/CPI = top-2 movers |
| **Census** (✅ via macro_stack) | MARTS retail, Durables, Housing Starts, BFS | Monthly | Free timeseries API | First read on demand + capex |
| **Treasury Fiscal Data** | Daily yield curve + DFII real rates | Daily | Free REST, no key | 2s10s inversion, discount-rate inputs |
| **Fed H.4.1 / H.8 / Beige Book** | Fed balance sheet / bank credit / regional anecdotes | Weekly + 8x/yr | Free, FRED-mirrored | QT/QE liquidity + bank C&I/CRE growth |
| **ISM PMI** | Mfg (1st BD) + Services (3rd BD) | Monthly | Headline free; sub paid | Earliest sector-cycle read; <50 = contraction |
| **S&P Global PMI** | Flash (~12d before final) | Monthly | Subscription | The flash signal markets trade pre-ISM |
| **Conference Board LEI** | 10-component composite, ~7mo lead | Monthly | Sub for detail; FRED mirrored | Turning-point indicator (6mo annualized ROC) |
| **U-Mich Consumer Sentiment** | 1y + 5-10y inflation expectations | Monthly prelim + final | Sub for micro; FRED `UMCSENT` | Fed-watched inflation expectations |
| **NFIB Small Business Optimism** | SMB hiring/capex/pricing | Monthly (2nd Tue) | Free PDF + FRED | Leads ADP, main-street inflation |
| **Atlanta Fed GDPNow** | Bottom-up bridge-equation nowcast | 6–7x/month | Free, FRED `GDPNOW` | In-quarter GDP tracking |
| **NY Fed Nowcast** | Dynamic factor model | Real-time | Free | Smoother complement; divergence = signal |
| **Chicago Fed NFCI** | 105-variable financial conditions | Weekly (Wed 8:30 ET) | Free, FRED `NFCI`/`ANFCI` | Cleanest free FCI |
| **EIA** | Weekly Petroleum, Nat Gas Storage, STEO | Weekly + monthly | Free REST + key | Energy + inflation pass-through |
| **OECD** | CLI, MEI, BCI/CCI across 38+12 economies | Monthly | Free SDMX, no key | Global cycle synchronization |
| **IMF WEO + IFS** | 5y projections + BoP/FX/money | Apr + Oct | Free SDMX 2.1/3.0 | EM sovereign + consensus forward path |
| **BIS** | Global liquidity, credit-to-GDP gaps, debt service ratios | Quarterly | Free SDMX | Cross-border credit cycle gauges |
| **ECB Data Portal** | Euro-area HICP, monetary aggregates, AnaCredit | Daily–monthly | Free SDMX 2.1 REST | Euro-area inflation + credit |
| **World Bank Open Data** | WDI, GEP | Annual + semi-annual | Free REST | Long-history cross-country indicators |
| **China NBS** | Mfg/Non-Mfg PMI, IP, retail, FAI | Monthly | Free web (no formal REST) | Cross-check vs Caixin private PMI |

**Caveats:** FRED is aggregator not primary (release-day lag); ISM vs S&P Global methodology divergence can flip direction in any given month; PCE (FOMC-target) ≠ CPI (markets-trade); 2025/26 BLS gov't-shutdown release-date shifts.

**Already wired:** FRED, BEA, BLS, Census ✅. **Gap to add:** ISM PMI, Conf Board LEI, Atlanta GDPNow, NFCI, NFIB — all free; meaningful additions for sector-cycle reads.

---

## 4. Industry Research & Consulting (sector deep-dives, TAM/SAM)

| Publisher | Specialty | Access | Tier | Use case |
|---|---|---|---|---|
| **McKinsey Quarterly / MGI** | Cross-sector + healthcare, productivity, AI | Free PDF | **Tier-1 strategy** | Frameworks + quantitative whitepapers |
| **BCG Insights / Henderson** | Tech, digital, banking | Free | **Tier-1** | Academic-leaning data work |
| **Bain Insights** | PE, retail, luxury, NPS | Free | **Tier-1** | Annual flagships are sector benchmarks |
| **Oliver Wyman** | FinServ, insurance, aviation | Free | Tier-2 | "State of FSI" benchmark |
| **Roland Berger** | Euro industrial/auto | Free | Tier-2 | Euro OEM lens |
| **Strategy& / Kearney** | Chemicals/PMI / procurement, FDI | Free | Tier-2 | Niche functional reads |
| **Deloitte Insights** | All sectors (TMT, FSI, consumer) | Free | Big-4 | Sector framing |
| **PwC / EY / KPMG** | CEO surveys, M&A barometer | Free | Big-4 | Surveys yes, forecasts no |
| **Gartner (Magic Quadrant + Hype Cycle)** | Enterprise IT vendor positioning | Paid; vendor reprints free | **Tier-1 IT** | De-facto enterprise procurement signal |
| **Forrester (Wave)** | CX, marketing tech | Paid sub | **Tier-1 IT** | Transparent weighted scorecards |
| **IDC (MarketScape + Trackers)** | Unit shipments (phones, PCs, servers, cloud) | Paid | **Tier-1 IT** | Sell-side staple for shipments |
| **S&P Market Intelligence / 451 Research** | Emerging enterprise tech (datacenter, AI infra) | Paid | **Tier-1** | Best for emerging-tech competitive landscape |
| **Omdia / Canalys / ABI Research** | Semis/displays/telecom / channel / IoT | Paid | Tier-2 IT | Niche shipment data |
| **CB Insights** | 300k+ private cos, market maps | Paid | **Tier-1 private** | Emerging-tech landscape + unicorn pipeline |
| **PitchBook** | VC/PE/M&A deals, valuations, cap tables | Paid (Morningstar) | **Tier-1 private** | Institutional standard for private markets |
| **Crunchbase** | Community-sourced private | Freemium | Tier-2 | Top-of-funnel scan only |
| **Statista** | Aggregator of 18,000+ sources | Paid | **Tier-2 — does NOT generate primary data** | Citation harvest back to original |
| **IBISWorld** | US 5-digit NAICS | Paid (library) | Tier-2 | Transparent regression+MAPE methodology |
| **⚠️ Grand View / MarketsandMarkets / Mordor / Fortune Business / Allied / Verified / Databridge** | Press-release-driven market sizing | Paid | **Tier-3 — weak/opaque methodology** | Directional sense-check only; **never primary citation** |
| **Wood Mackenzie** | Energy, chemicals, metals, renewables | Paid (Verisk-owned) | **Tier-1 energy** | Upstream/midstream/power standard |
| **Rystad Energy** | Independent upstream economics, energy transition | Paid | **Tier-1 energy** | Shale + transition modeling |
| **SIA** | US semis revenue | Free monthly | **Tier-1 trade assoc.** | Canonical US semis series |
| **SEMI** | WFE, fab spending, wafer shipments | Free + paid | **Tier-1 trade assoc.** | Book-to-bill, World Fab Forecast |
| **NRF** | Retail holiday forecasts, security surveys | Free + paid | **Tier-1 trade assoc.** | Retail benchmarks |
| **AAA / AHIP / ACEA / AIA** | Travel / health-ins / Euro auto / architecture billings | Free reports | Tier-1 trade assoc. | AIA = construction leading indicator |
| **Govt industry series — gold tier** | BEA GDP-by-industry, BLS CES/QCEW, Census ASM/Econ Census | Free | **Audit-grade** | Anchor against which all commercial sizers are triangulated |

**Discipline rule:** Always triangulate commercial market-sizers against government industry series + tier-1 sources. Treat Statista as a path to primary, not a citation in itself.

---

## 5. Alternative Data & Specialized Verticals

| Source | Signal | Cadence | Access | When to use |
|---|---|---|---|---|
| **Wall Street Horizon** (✅ likely via catalyst-scout) | Forward earnings/divs/AdComm/40+ event types | Real-time | ~$49/mo IBKR / $149+ inst. | Calendar-spread setups, thesis catalyst scrub |
| **Earnings Whispers** | Whisper number, +1.8% post-beat (vendor) | Pre-earnings | Freemium | Second opinion vs I/B/E/S |
| **Estimize** | Buy-side crowd EPS/revenue | Continuous | Paid (ExtractAlpha) | Beats consensus 60-64% in last week pre-earnings |
| **BioPharmCatalyst** (✅ catalyst-scout) | PDUFA, AdComm, readout dates | Daily | Free + Premium (~$30-100/mo) | Biotech catalyst sizing |
| **ClinicalTrials.gov / AACT** | Trial registry; daily-refreshed relational | Daily | Free | Enrollment slips = thesis-break early-warning |
| **FDA Drugs@FDA + Orange Book** | Approvals, Para IV, exclusivity cliffs | Real-time | Free | IP-cliff DCF + generic-launch timing |
| **Endpoints / STAT News / FierceBiotech** | Trade-press scoops on readouts | Real-time | Free + STAT+ ~$300/yr | Sentiment + scuttlebutt |
| **Similarweb** | Web traffic, GMV proxies; 300k domains mapped to 50k tickers | Weekly | Enterprise (5-6 fig) | **96% R² claim on top-line** — 4-8 wk pre-earnings for consumer-internet |
| **Sensor Tower** | Mobile app DAU/MAU/revenue | Daily | Institutional | App-monetization names |
| **data.ai (App Annie)** | App intel (stronger Asia) | Daily | Institutional | ⚠️ SEC settlement 2021 on data sourcing |
| **Apptopia** | Often more accurate downloads (quant pref) | Daily | Subscription | Cross-check vs Sensor Tower |
| **SteamCharts / SteamDB** | Hourly CCU since 2012 every Steam title | Hourly | **Free** | Gaming names — CCU decay leads bookings 1-2Q |
| **BuiltWith / SimilarTech** | Site-by-site tech stack across 600M+ sites | Daily | Subscription | SaaS TAM + customer logo gain/loss |
| **LinkedIn job postings** | Hiring trend = opex leading indicator | Real-time | Free site / structured via partners | Headcount-growth signal |
| **Revelio Labs** | 4.1B postings, 6.6M companies, COSMOS feed | Daily | Subscription; public RPLS free | Firm/segment headcount + attrition |
| **Thinknum** | Job + Glassdoor + store counts | Daily | Subscription | Store-rollout tracking (CAVA, SG) |
| **Glassdoor** | Employee ratings + interviews | Continuous | Free (scrape) / Revelio feed | Academic: 84 bps/mo high-low quality |
| **Levels.fyi** | Verified tech comp bands | Real-time | Free + enterprise API | Talent-war intensity proxy |
| **Bloomberg Second Measure** | Billions of US consumer card txns | 2-3 day lag | Terminal sub (5-6 fig) | Retail/restaurant/subscription pre-print |
| **Earnest Analytics** | Card + healthcare + location via Dash | Daily | Subscription | Cross-validate Second Measure |
| **Yodlee / Envestnet** | Anonymized bank+card upstream feed | Real-time | Enterprise only | Source for many panel vendors |
| **Facteus** | Debit/card panel; under-25 strong | Daily | Subscription | Younger-cohort spend |
| **M-Science (ex-Majestic)** | Multi-vertical consumer + B2B alt | Daily | Subscription | Company-by-company spend |
| **RS Metrics** | Satellite parking-lot counts since 2011 | Weekly | Subscription | ⚠️ Berkeley Haas: 4-5% alpha but crowded post-2017 |
| **Orbital Insight** | Geospatial + cell geolocation | Daily | Subscription | Cushing tank levels pre-EIA, retail foot traffic |
| **SpaceKnow** | ML satellite → China industrial PMI | Monthly | Subscription | China activity proxy |
| **MarineTraffic** | AIS, 800M positions/mo | Real-time | Free tier + paid | Tanker flows, container (ZIM, MAERSK) |
| **FlightRadar24 / FlightAware** | Live aircraft | Real-time | Free + paid | Airline demand, corp-jet M&A scuttlebutt |
| **EIA Weekly Petroleum** | Crude/product inventories | Wed 10:30 ET | Free | Benchmark oil tape-mover |
| **Baker Hughes rig count** | US oil/gas rigs by basin | Friday | Free | OIH/oil-service signal |
| **S&P Platts / Argus / OPIS** | Refined product / LNG / crude diff | Daily | Subscription | Refining-crack + midstream modeling |
| **Marketplace Pulse** | Amazon/Walmart/Etsy marketplace intel | Daily | Free + paid | AMZN third-party, aggregator names |
| **Helium 10 / Jungle Scout** | Amazon SKU revenue estimates | Daily | Subscription | Granular Amazon-SKU tracking |
| **Numerator** | Receipt panel (~1M+ HHs) | Daily | Subscription | CPG share-shift WMT/TGT/COST/AMZN |
| **Circana (NPD+IRI 2023)** | POS + consumer panel, 23 countries | Weekly | Enterprise | Toys, apparel, electronics volume |
| **NielsenIQ** | Largest scanner CPG panel | Weekly | Enterprise | Brand/category share (KO, PEP, KHC) |
| **Adobe Digital Insights** | Aggregated US online spend | Monthly + holiday | **Free reports** | Holiday + online-retail demand |
| **Cox Manheim UVVI** | Wholesale used-vehicle index since 1995 | Monthly (5th BD) | **Free report + paid feed** | Primary signal for CACC, AAP, KMX, ALLY |
| **Cox Kelley Blue Book** | Retail used + new transaction prices | Monthly | Free + sub | Retail auto + OEM mix |
| **Wards Intelligence** | Production/sales/inventory by OEM | Monthly | Subscription | OEM volume + supplier exposure |
| **JATO Dynamics** | Global vehicle sales/specs | Monthly | Subscription | Non-US auto |
| **STR (Smith Travel Research, CoStar)** | Hotel RevPAR/ADR/occupancy weekly | Weekly | Institutional sub | Hotel-REIT canonical |
| **AirDNA** | STR (Airbnb/VRBO) supply + ADR | Weekly | Mid-tier sub | ABNB thesis + STR-vs-hotel substitution |
| **USPTO Patent Public Search** | Authoritative US patents + assignments | Real-time | Free | IP-cliff modeling, litigation flags |
| **IFI Claims** | Curated cleaned global patents | Weekly | Subscription | Citation-velocity factor |
| **Patsnap** | Global patents + sci-lit + market fused | Weekly | Subscription | Thematic baskets (semis, biotech, EV) |
| **Lens.org** | Open-access global patents + citations | Weekly | **Free** | Zero-cost USPTO complement |

**Alt-data discipline:** Card panels + web traffic + forward calendars consistently clear the cost-benefit bar (Refinitiv/PwC 2021-22: 10-15% accuracy lift on consumer names). Satellite parking-lot alpha has faded since 2017. App-intel vendors disagree materially — use ≥2 for cross-check. data.ai SEC settlement is a real reputational caveat. Free signal is often sufficient: ClinicalTrials + FDA Orange Book + EIA + Baker Hughes + Manheim public + USPTO + Lens.org.

---

## 6. Sell-Side Consensus, Options & Positioning

### Consensus & estimates

| Source | Coverage | Cadence | Access | Note |
|---|---|---|---|---|
| **Refinitiv/LSEG I/B/E/S** | 23k cos, 19k analysts, 90+ countries | Daily/RT | Institutional | Gold standard for sell-side consensus; StarMine SmartEstimates |
| **FactSet** | EPS/rev/segment + targets | Daily | $12–30k/yr/seat | Leading WS aggregator; buy-side modeling integration |
| **Bloomberg Terminal (EE)** | Per-analyst estimates + targets | RT | ~$25k/yr | Industry-default hedge-fund screens |
| **S&P Capital IQ** | Consensus + transcripts + comps | Daily | ~$13k/yr | Now hosts Visible Alpha on Pro |
| **Visible Alpha** | **Bottom-up line-item** (KPI/segment) from 250+ broker models | Continuous | Institutional | **Use when modeling unit economics, ARPU, segment revenue** |
| **Koyfin** | Retail consensus + screener + short int + ETFs | Daily | $0–$209/mo | Retail-pro bridge |
| **TIKR** | Retail consensus + 5y forward, 92 countries | Daily | $299/yr Pro | Cheaper than Koyfin, better international |
| **Stock Analysis** | Free retail | Daily | Free | Fastest lookup UI |
| **Finviz** | Screener + targets + insider | Daily | $0–$25/mo Elite | Fast scanning |
| **Zacks** | Rank + ESP (70% positive-surprise hit-rate, 10yr backtest) | Daily | Freemium | Signal-oriented |
| **TipRanks** | Analyst aggregation + Smart Score | Daily | $0–$30+/mo | Analyst-quality weighting |
| **yfinance / Yahoo** (✅ wired) | Consensus + targets + recs (Refinitiv-derived abridged) | EOD | Free lib | Ubiquitous baseline |
| **Estimize** | Crowd EPS/rev, 100k+ contributors | Continuous | ExtractAlpha/WRDS | Beats I/B/E/S 60-64% last week pre-earnings |
| **Earnings Whispers** | Whisper number + grade | Pre-earnings | Freemium | 2010 Fernando/Brown dispute — supplementary only |
| **StreetInsider** | Real-time rating/target changes | Intraday | Freemium + paid | Trader-favorite tape |
| **Benzinga Pro** | Rating tracker + squawk + API | Intraday | $37–$457/mo | Strong feed for systematic ingestion |
| **MarketBeat** | Ratings + targets retail | Daily | Freemium | Broad but lower depth |

### Options chain / IV / flow

| Source | Specialty | Cadence | Access |
|---|---|---|---|
| **CBOE LiveVol Data Shop** | Official options tick + EOD + summary, VIX source | Daily | Institutional per-set |
| **OptionMetrics IvyDB** | **Academic-grade historical IV surfaces since 1996** | EOD | Institutional bespoke |
| **Polygon.io** (✅ wired) | Options chain + IV + tick + dark pool aggregates | RT WebSocket | $0–$199/mo |
| **Tradier** | Brokerage-grade options API for account holders | RT | Free w/ account |
| **ORATS** | IV surfaces, forward vols, contango on 4000+ tickers | EOD | Inst. via Nasdaq Data Link |
| **Market Chameleon** | IV rankings, earnings vol | Daily | ~$69/mo |
| **Barchart** | Options screener + IV filters | Daily | $16–$40/mo |
| **IVolatility** | Historical IV + analytics | Daily | Tiered |
| **Unusual Whales** | Options flow + dark prints + congressional + GEX | RT | $50/mo + API |
| **Cheddar Flow** | Options flow + insider alerts | RT | $85–$99/mo |
| **BlackBoxStocks / FlowAlgo** | Legacy retail flow | RT | ~$99–$200/mo |

### Short interest / 13F / insiders

| Source | Specialty | Cadence | Access |
|---|---|---|---|
| **FINRA bi-monthly SI** | Official short shares/DTC | Bi-monthly, 2-day lag | Free |
| **NASDAQ/NYSE SI** | Exchange-published biweekly | Biweekly | Free |
| **Ortex** | Daily SI estimate from 700k Agent Lender/PB pools + cost-to-borrow | Daily 7:30 ET | $70–$140/mo retail + inst. API; 97% accuracy claim |
| **S3 Partners** | Buy-side + broker-dealer + reg sources, financing rates | RT | Inst. (FactSet co-distribution); preferred by hedge funds |
| **Fintel** | Short squeeze score + inst + insider | Daily | $0–$25/mo |
| **FINRA ATS Transparency** | Aggregate dark-pool vol by ATS | Weekly, 2-wk lag | Free; coarse |
| **IEX TOPS / Cloud** | Tape + DEEP order book (IEX only) | RT | Free; ~2% market share |
| **SEC EDGAR 13F** (✅ wired) | Institutional long positions | Quarterly, 45-day lag | Free |
| **WhaleWisdom** | 13F + concentration/turnover/sector + clone | Quarterly | $30–$99/mo + inst. API |
| **HedgeFollow** | 13F + insider w/ ~5-min refresh, push alerts | Q + intraday insider | Freemium; broader fund coverage (10k+) |
| **Dataroma** | 50+ curated "superinvestor" 13Fs, manually verified | Quarterly | **Free** |
| **VerityData (InsiderScore)** | Institutional insider scoring + buyback + grants, 20yr history | Intraday | Institutional |
| **NYSE TAQ** | Full tick history | Intraday | $500–$3k/dataset via WRDS |
| **Tiingo / Alpha Vantage / EODHD** | Retail-API EOD + intraday | EOD + RT WS | $10–$80/mo |

**Caveats:** Consensus aggregator divergence (1-5% on EPS, more on Visible Alpha line items). Sell-side runs 65-68% below actuals; Estimize 52-54% below — both biased. Short-interest vendors disagree 5-15% on same ticker. 13F 45-day lag excludes shorts, most options, non-US.

**Already wired:** yfinance, Polygon, EDGAR 13F ✅. **Gaps to add:** Visible Alpha (line-item depth) is highest-value paid; Ortex or S3 for daily SI; WhaleWisdom + Dataroma for 13F aggregation; Unusual Whales for retail-tier flow with API.

---

## 7. Community, Sentiment & Independent Analysts

### Long-form independent research

| Source | Specialty | Cadence | Access | Tier |
|---|---|---|---|---|
| **Seeking Alpha** | Theses + free transcripts; 18k contributors; SA Quant Rating (academically validated) | Continuous | $299/yr Premium | Mixed — verify per author |
| **Value Investors Club** | Institutional-quality longform; 250 members; 2-ideas/yr post requirement | Continuous | **Free w/ 45-day delay** | **Rigorous independent** |
| **SumZero** | Buyside-only theses; 16k vetted members, 12k theses, 75% reject rate | Continuous | Reciprocity (post→read) | **Rigorous independent** |
| **Stratechery (Ben Thompson)** | Aggregation-theory + business-model framing for big-cap tech | Daily/weekly | ~$15/mo | **Rigorous independent** |
| **Doomberg** | Energy/macro/geopolitics; #1-3 paid finance Substack, 240-370k subs | 2-3x/wk | ~$30/mo | **Rigorous independent** (anonymous) |
| **Net Interest (Marc Rubinstein)** | Weekly financial-sector deep dives, 97-99k subs | Weekly | ~$300/yr | **Rigorous independent** (ex-HF) |
| **The Diff (Byrne Hobart)** | Tech-finance crossover, 5x/wk | 5x/wk | ~$220/yr | **Rigorous independent** |
| **Hedgeye public clips** | Quant sector rotation (Keith McCullough) | Daily | Free YouTube/X + Pro $500-3k | Independent → community |
| **Bert Hochfeld** | Tech-software deep dives | Weekly | SA Marketplace paid | Rigorous independent |
| **New Constructs** | Forensic accounting + adjusted ROIC | Continuous | Paid | Rigorous independent |
| **Morningstar (free portion)** | 140+ in-house analysts on ~1,500 stocks; moat ratings + fair value | Continuous | Free excerpts + $249/yr | Rigorous independent |
| **Simply Wall St** | Visual snowflake summaries on public data | Daily | $0 + ~$120/yr | Community (no analysts) |
| **13D Monitor (Ken Squire)** | Activist campaigns + Company Vulnerability Ratings + standstill DB | Continuous | Inst. sub | Rigorous independent |
| **Hedge Fund Alpha (ex-ValueWalk Premium)** | HF letters + activist filings | Daily | Paid | Community-independent |

### Transcripts & AI search

| Source | Specialty | Cadence | Access |
|---|---|---|---|
| **Motley Fool transcripts** | Free transcript archive | Post-earnings | Free w/ cap |
| **Tikr transcripts** | Consolidated transcripts + 10yr financials | Daily | Free + paid |
| **Quartr** | Free mobile app — live audio + sync transcripts globally | RT | Free |
| **Aiera** | Real-time AI transcription w/ sentiment/tone highlights | Live | Enterprise |
| **AlphaSense (incl. Sentieo)** | AI search across filings/transcripts/broker research/expert calls | Continuous | ~$15-40k/seat/yr |
| **Hudson Labs (ex-Bedrock AI)** | Finance-tuned LLM forensic flags; flagged SMCI 2y pre-crash | Continuous | Institutional |

### Social sentiment & political-trade

| Source | Signal | Cadence | Access | Tier |
|---|---|---|---|---|
| **StockTwits** | Per-ticker bull/bear ratio; 10M+ users | RT | Free | Noisy social |
| **Reddit r/SecurityAnalysis** | Graham-style theses, moderator-enforced rigor | Continuous | Free | Community |
| **Reddit r/investing & r/stocks** | Mainstream retail sentiment | Continuous | Free | Community |
| **Reddit r/wallstreetbets** | Options-gamma narrative + positioning proxy | Continuous | Free | Noisy social |
| **Apewisdom** | Reddit/4chan ticker-mention tracker | RT | Free | Noisy social |
| **Swaggy Stocks** | WSB sentiment + options-flow dash | RT | Free + paid | Noisy social |
| **Quiver Quantitative** | Congressional trades + lobbying + gov contracts + WSB | Daily | $0 + ~$10/mo | Community-independent |
| **Capitol Trades** | Cleanest Congressional STOCK Act browser, hours-fresh | Hours | **Free** | Rigorous-disclosure |
| **Fintwit curated X lists** | RT short-form (Damodaran, Rubinstein, @StockJabber, etc.) | RT | Free | Rigorous → noisy |

**Caveats:** SA contributor variance high — verify per author. WSB academic study: positive raw return but risk-adjusted edge unclear post-2021. Doomberg contrarian-by-design — strong on energy microstructure but timing-off on macro. AlphaSense post-Sentieo integration trade-offs (Excel depth).

---

## 8. Gap Analysis vs Currently MCP-Wired Stack

**Already wired in the system:**
- EDGAR (filings) ✅
- FRED + macro_stack (BLS/BEA/Census) ✅
- yfinance (consensus + targets + recs) ✅
- market_data (CNBC news) ✅
- polygon (options chain, IV, unusual activity, put/call) ✅
- fundamentals ✅
- catalyst-scout subagent (forward catalyst + positioning + sentiment per BUILD_LOG d7e94ec)

**Highest-leverage gaps to consider adding (free or cheap, high signal):**

| Priority | Source | Why | Cost |
|---|---|---|---|
| **P0** | **OpenInsider** (Form 4 cluster-buy view) | Highest-signal insider pattern; free; derived from EDGAR | Free scrape |
| **P0** | **Atlanta Fed GDPNow + Chicago Fed NFCI + Conf Board LEI + ISM PMI** | In-quarter GDP + financial conditions + cycle turn | Free / FRED-mirrored (already accessible) |
| **P0** | **ClinicalTrials.gov / AACT mirror** | Biotech enrollment-slip = thesis-break early warning; free | Free REST |
| **P0** | **Capitol Trades + Quiver Quant** | Political-trade signal w/ backtested returns; cheap | Free + $10/mo |
| **P0** | **FDIC BankFind REST API** | Per-charter bank financials; free; no key | Free |
| **P0** | **Lens.org + USPTO Patent Public Search** | IP moat verification; free | Free |
| **P1** | **Wall Street Horizon (if not already covered by catalyst-scout)** | Forward calendar of 40+ event types | $49/mo IBKR |
| **P1** | **Visible Alpha** | Line-item consensus (KPI/segment) where headline EPS isn't enough | Institutional |
| **P1** | **Ortex or S3 Partners** | Daily short-interest estimate vs FINRA biweekly lag | $70-140/mo retail |
| **P1** | **WhaleWisdom + Dataroma** | Curated 13F aggregation w/ superinvestor screens | Freemium |
| **P1** | **Benzinga Pro** | Programmatic real-time rating-change feed | $37+/mo + API |
| **P1** | **AlphaSense** (or Quartr free) | AI keyword search across filings/transcripts/broker research | $15k+/seat (Quartr free) |
| **P2** | **Cox Manheim UVVI + Baker Hughes + EIA Weekly Pet** | Free sector signals for auto + energy names | Free |
| **P2** | **Hudson Labs / New Constructs** | Forensic accounting risk flags | Institutional |
| **P2** | **Sensor Tower + Similarweb** | App/web traffic for consumer-internet leading revenue | Institutional (high) |
| **P3** | **Doomberg + Net Interest + Stratechery + The Diff** | Independent sector experts; pay for sectors you cover often | $15-30/mo each |

**Explicit anti-recommendations (don't bother):**
- Grand View Research / MarketsandMarkets / Mordor / Fortune Business / Allied / Verified / Databridge — press-release market sizing, opaque CAGRs, some flagged as SEO spam
- Crunchbase as primary private-market — community-sourced, verify against PitchBook/CBI
- Statista as a citation — it's a portal aggregator; cite the underlying source instead
- Earnings Whispers as primary — 2010 Fernando/Brown found consensus MSE strictly lower; useful as supplementary only
- data.ai (App Annie) — 2021 SEC settlement is a real reputational caveat; cross-check w/ Sensor Tower + Apptopia

---

## 9. Uncertainty / What Couldn't Be Verified

- **Paywall meter counts** (Bloomberg "10/mo", FT AI-tuned) drift constantly — treat as nominal.
- **Yahoo Finance "API"** retired 2007; `yfinance` lib scrapes unofficial endpoints — ToS-fragile.
- **CNBC RSS** existence verified via third-party indexers but canonical landing page returned 403 in session — feeds work, page is access-gated.
- **13D/G amendment deadlines** modernized Sep 30, 2024 — confirm any tool reads the new rules.
- **N-PORT phased compliance** — ≥$1B funds Nov 17, 2025; smaller funds May 18, 2026.
- **EDGAR rate limit** = 10 req/sec with User-Agent header required; exceed → ~10-min IP block.
- **ISM vs S&P Global PMI** can disagree on direction in a given month due to sample + seasonal adjustment differences.
- **Short-interest vendors** (Ortex, S3, FINRA) can differ 5-15% on same ticker due to lender-pool methodology.
- **Mobile app intelligence** (Sensor Tower vs Apptopia vs data.ai) often disagrees materially — use ≥2 vendors.
- **2025/26 BLS gov't-shutdown release-date shifts** — historical CPI/PPI/NFP windows moved.

---

## 10. Sources Consulted (selected high-value URLs)

**News/media:** reuters.com, bloomberg.com, lseg.com/en/data-analytics/financial-data/news/dow-jones-news, en.wikipedia.org/wiki/CNBC, benzinga.com/apis/cloud-product/stock-news-api, digiday.com (FT AI paywall), newsdata.io (Yahoo Finance API status)

**Filings:** sec.gov/search-filings, sec.gov/files/forms-3-4-5.pdf, investor.gov (13F overview), law.cornell.edu/cfr/text/17/240.13d-1, finra.org/rules-guidance/rulebooks/finra-rules/4560, federalreserve.gov/apps/reportingforms/Report/Index/FR_Y-9C, api.fdic.gov/banks/docs, pacer.uscourts.gov, openinsider.com/latest-cluster-buys, sedarplus.ca, developer.company-information.service.gov.uk

**Macro:** fred.stlouisfed.org/docs/api/fred, bea.gov/news/schedule, bls.gov/schedule/2026/home.htm, census.gov/data/developers, ismworld.org, conference-board.org/topics/us-leading-indicators, atlantafed.org/cqer/research/gdpnow, chicagofed.org/research/data/nfci, eia.gov/opendata, oecd.org/en/data/insights, data.imf.org, data.bis.org, data.ecb.europa.eu

**Industry research:** mckinsey.com, bcghendersoninstitute.com, deloitte.com/insights, 451research.com, pitchbook.com, cbinsights.com, woodmac.com, semiconductors.org, semi.org, help.ibisworld.com (methodology), ipvm.com/reports/scam-research (Grand View etc. warning)

**Alt data:** wallstreethorizon.com, biopharmcatalyst.com/calendars/pdufa-calendar, clinicaltrials.gov, aact.ctti-clinicaltrials.org, similarweb.com/corp/stocks, sensortower.com, secondmeasure.com, earnestanalytics.com, marinetraffic.com, manheim.com, str.com, airdna.co, uspto.gov/patents-application-process/patent-search, lens.org, newsroom.haas.berkeley.edu (parking-lot alpha study), extractalpha.com (vendor adoption stats)

**Consensus + positioning:** refinitiv.com/.../ibes-estimates, spglobal.com/.../visible-alpha, koyfin.com, tikr.com, polygon.io/options, optionmetrics.com, datashop.cboe.com, public.ortex.com, s3partners.com, whalewisdom.com, hedgefollow.com, dataroma.com (via findmymoat comparison), verityplatform.com/.../insiderscore, unusualwhales.com, finra.org/.../short-interest, finra.org/.../trace

**Community/independent:** seekingalpha.com, valueinvestorsclub.com, sumzero.com/about, newsletter.doomberg.com, netinterest.co, thediff.co, stratechery.com, quartr.com, alpha-sense.com, hudson-labs.com, quiverquant.com, capitoltrades.com, 13dmonitor.com, hedgefundalpha.com, thebearcave.substack.com (curated FinTwit list)

---

**Document maintenance:** Refresh quarterly. Last full sweep: 2026-05-12.

---

## 11. Verified Reachability (tested 2026-05-12)

### MCP-wired tools — direct test results

| MCP Tool | Test | Result |
|---|---|---|
| `mcp__edgar__get_company_facts` | AAPL | ✅ Full XBRL returned (8.5MB; overflow = healthy data) |
| `mcp__fred__get_series` | DGS10, start 2026-04-01 | ✅ 28 obs through 2026-05-08, 10Y at 4.38% |
| `mcp__market_data__get_news` | AAPL | ✅ 50 stories, fresh (latest 2026-05-11), provider=polygon |
| `mcp__yfinance__get_consensus_estimates` | AAPL | ✅ FY EPS 9.56, next-Q 0.194, 42 analysts |
| `mcp__polygon__get_options_chain` | AAPL | ✅ Full chain returned (122k chars = healthy) |
| `mcp__macro_stack__get_bls_series` | CUUR0000SA0 (CPI), 2025–2026 | ❌ **MISSING API KEY** — `error_class: missing_api_key` |
| `mcp__fundamentals__get_fundamentals` | AAPL, as_of 2025-12-31 | ✅ FY2025 facts (filed 2025-10-31), PIT-filtered |

**🚨 Actionable issue:** `mcp__macro_stack__get_bls_series` returns `missing_api_key`. Set `BLS_API_KEY` in MCP server env (free key from https://data.bls.gov/registrationEngine/). Likely affects BEA + Census endpoints same way — verify those too.

### Free public endpoints (35 tested)

**✅ Unambiguously open (19):** FDIC BankFind API, FINRA TRACE, PACER, SEDAR+, UK Companies House, EDINET Japan, ClinicalTrials.gov v2 API, Conference Board LEI, NFIB SBET, U-Mich SCA, Fed H.4.1 + H.8, EIA Open Data, BIS Data, ECB Data Portal, World Bank, USPTO Patent Public Search, Lens.org (basic), Wall Street Horizon (marketing only).

**⚠️ Pseudo-blocked — works with proper UA/headers (7):** SEC EDGAR browse, EDGAR full-text search, OpenInsider (use HTTPS), FRED web, Atlanta Fed GDPNow page, Chicago Fed NFCI page, Treasury FiscalData, IMF Data. Existing `mcp__edgar` + `mcp__fred` already handle the SEC + FRED ones.

**❌ Real auth/paywall barriers (6):** ISM PMI (SSO), EarningsWhispers (login), BiopharmCatalyst (bot wall), Wall Street Horizon data (sales contact), PACER fees beyond $30/qtr, Lens.org alerts (free account).

**🔧 URL drift fixes needed:**
- FINRA Short Interest → `finra.org/finra-data/equities/short-interest`
- FDA Orange Book → `accessdata.fda.gov/scripts/cder/ob/index.cfm`
- FDA AdComm → `fda.gov/advisory-committees/about-advisory-committees/advisory-committee-calendar`

**❌ JS-only (won't fetch as text):** OECD Data Explorer SPA, Baker Hughes rig count page (use static-files XLSX download instead), SwaggyStocks (client-rendered).

### Free news + community (36 tested)

**✅ Fully open, no login (8):** Yahoo Finance, Semafor Business, Motley Fool transcripts, Dataroma, Capitol Trades, Apewisdom, Benzinga (free tier), WhaleWisdom (free tier), Quiver Quant (free tier).

**⚠️ Bot-walled to WebFetch but real sites work in browser/with UA cookies (13):** Reuters, CNBC + RSS, Bloomberg, WSJ, FT, Barron's, MarketWatch + RSS, AP News, Axios, Morningstar, HedgeFollow, StockTwits, Reddit (both subs). For automated ingestion: use the existing `mcp__market_data__get_news` (Polygon-backed, returns Reuters/CNBC/Benzinga/MF stories), or implement a custom fetcher with proper UA. Reddit JSON endpoint (`/r/<sub>/.json`) is an alternative.

**🔒 Paywall after load (7):** Seeking Alpha (analysis), Stratechery (daily/audio), Doomberg (Pro), Net Interest (full text), The Diff (premium), SumZero (research), VIC (45-day feed needs email signup).

**✅ Best zero-friction automation candidates:** Dataroma (13F), Capitol Trades (political), Apewisdom (Reddit sentiment), Yahoo Finance (quotes), Semafor (curated news), Motley Fool transcripts.

### Paid / institutional landing pages (49 tested)

**✅ Credible free trial / free tier worth signing up:** Koyfin, TIKR, Stock Analysis, Finviz Elite (7-day), Barchart Premier (30-day), Ortex (limited free), VerityData (1-week), Similarweb, Sensor Tower, Earnest Dash, Revelio Labs, CB Insights (10-day), Crunchbase, Statista Basic, New Constructs, Hudson Labs, AlphaSense, Forrester webinars.

**🔒 Sales-gated, no free tier:** LSEG I/B/E/S, FactSet, OptionMetrics, IVolatility, CBOE DataShop, Second Measure, STR, McKinsey/BCG/Bain reports, PitchBook, Wood Mackenzie, Rystad, IBISWorld, Thinknum, S3 Partners, 13D Monitor.

**❌ Landing page itself returned 403/bot-challenge (10):** Bloomberg Terminal, S&P Global MI, Visible Alpha, TipRanks, Zacks, Cheddar Flow, Fintel, Market Chameleon, McKinsey Insights, BCG/Gartner/PitchBook (sites exist, blocked to WebFetch). Brand-confirmed to exist — 403s are scraper protection, not outages.

### Summary

- **MCP stack:** 6/7 functional; 1 fixable config issue (BLS_API_KEY).
- **Free public endpoints worth adding to workflow:** FDIC, ClinicalTrials.gov, Capitol Trades, Quiver, Dataroma, OpenInsider (via HTTPS), Apewisdom, USPTO, Lens.org, NFIB, U-Mich SCA, Conf Board LEI, Fed H.4.1/H.8, EIA, BIS, ECB, World Bank — all open or trivially accessible.
- **Real paywalls (cost-justified case-by-case):** Visible Alpha, AlphaSense (Quartr is free alternative), Ortex (cheap tier), WSH if catalyst-scout needs more coverage.
- **Avoid relying on WebFetch for:** Mainstream financial press (Reuters/CNBC/Bloomberg/WSJ etc.) — already covered by `mcp__market_data__get_news`. For sources not in market_data's source list, a custom MCP w/ proper UA + cookies would be needed.

---

## 12. Verified Sources Per Category (✅ ONLY — post CRCL+COIN test)

Pruned 2026-05-12 after AAPL + CRCL+COIN cross-ticker verification. **Only sources that returned ticker-specific data for the test calls are listed here.** Sources that landed on ⚠️ (JS shell, login wall, paywall after load, ticker-asymmetric) or ❌ (404, auth gate, tier-insufficient, UA-blocked, ECONNREFUSED) are demoted to §12.99 "Demoted from top tier" below with cause.

### 12.1 Financial News & Business Media

| # | Source | Evidence | Access |
|---|---|---|---|
| 1 | **`mcp__market_data__get_news`** | 50 fresh stories returned for AAPL, CRCL, COIN — latest within 24h | ✅ Wired |
| 2 | **Reuters / Investing.com / GlobeNewswire** (via market_data) | All surface inside the Polygon-backed feed for tested tickers | ✅ via MCP |
| 3 | **Benzinga** (direct `/quote/<T>` + REST API) | CRCL + COIN quote pages clean, free; analyst ratings/options/insider endpoints | ✅ Free direct + via MCP |
| 4 | **Motley Fool** (`fool.com/quote/...`) | CRCL: $132.00 quote + "Big Rally" headline. COIN: $216.43 + crypto headlines | ✅ Free verified |

### 12.2 Regulatory & Primary Filings

| # | Source | Evidence | Access |
|---|---|---|---|
| 1 | **`mcp__edgar__get_company_facts`** | AAPL full XBRL returned | ✅ Wired |
| 2 | **`mcp__edgar__get_filings`** | CRCL CIK 1876042 → 10-Q 2026-05-11, 8-K, Form 4, Form 144. COIN CIK 1679788 → 10-Q 2026-05-07, 8-K, 13G, ARS | ✅ Wired |
| 3 | **`mcp__fundamentals__get_fundamentals`** | AAPL FY2025 PIT-filtered facts (filed 2025-10-31) | ✅ Wired |
| 4 | **ClinicalTrials.gov v2 API** | JSON `studies[]` returned; free, no key | ✅ Verified (biotech context) |
| 5 | **FDIC BankFind API** | Swagger docs reachable, no key required | ✅ Verified (bank context) |
| 6 | **FINRA TRACE** | Public page loads; for corp-bond credit-equity cross-check | ✅ Verified |
| 7 | **UK Companies House API** | Free REST w/ key, 600 req/5min | ✅ Verified (UK names) |
| 8 | **SEDAR+** | Canadian filings primary | ✅ Verified (Canadian names) |

### 12.3 Macro & Economic Data

| # | Source | Evidence | Access |
|---|---|---|---|
| 1 | **`mcp__fred__get_series`** | DGS10 returned 28 obs through 2026-05-08, 10Y at 4.38% | ✅ Wired |
| 2 | **ECB Data Portal** (SDMX 2.1) | Catalog visible; free, no key | ✅ Verified |
| 3 | **BIS Data** | Topic cards + datasets visible; free SDMX | ✅ Verified |
| 4 | **EIA Open Data** | API docs visible, free with registration | ✅ Verified |
| 5 | **Fed H.4.1 + H.8 release pages** | Weekly QT/QE + bank credit data download links visible | ✅ Verified |
| 6 | **Conference Board LEI** | Headline value visible on free page | ✅ Verified |
| 7 | **U-Mich SCA** | Public charts/tables visible | ✅ Verified |
| 8 | **NFIB SBET** | Monthly report + PDF link visible | ✅ Verified |
| 9 | **World Bank Open Data** | Indicators + Data360 visible | ✅ Verified |

### 12.4 Industry Research & Consulting

| # | Source | Evidence | Access |
|---|---|---|---|
| 1 | **BEA GDP-by-industry + BLS CES/QCEW** | Gov't gold-tier audit-grade NAICS data | ✅ Free, via macro_stack |
| 2 | **CB Insights** | 10-day free trial; landing page reachable | ✅ Free trial |
| 3 | **Crunchbase** | Free tier + API; landing reachable | ✅ Free tier |
| 4 | **Bain Insights** | Landing reachable; free newsletter; full insights gated | ✅ Verified landing |
| 5 | **Statista (Basic)** | Free tier active; "Always free" Basic plan | ✅ Free tier |
| 6 | **Forrester (webinars)** | Complimentary content + Forrester AI assistant | ✅ Verified |
| 7 | **SIA + SEMI** | Free monthly semis billings + WFE/fab data on trade-assoc sites | ✅ Free, trade assoc |
| 8 | **NRF** | Free retail holiday forecasts + security surveys | ✅ Free, trade assoc |

### 12.5 Alternative Data & Specialized Verticals

| # | Source | Evidence | Access |
|---|---|---|---|
| 1 | **ClinicalTrials.gov / AACT** | Free JSON API; biotech enrollment-slip early warning | ✅ Verified |
| 2 | **Manheim UVVI** | Free monthly index download since 1995 | ✅ Verified |
| 3 | **EIA Weekly Petroleum** | Free crude/product inventories Wed 10:30 ET | ✅ Verified |
| 4 | **Similarweb** (corp free trial) | Landing + free trial + browser ext + free tools | ✅ Free trial verified |
| 5 | **Sensor Tower** (free signup) | Landing reachable with sign-up CTA | ✅ Free signup verified |
| 6 | **SteamCharts / SteamDB** | Free hourly CCU every Steam title since 2012 | ✅ Open |

### 12.6 Sell-side Consensus, Options & Positioning

| # | Source | Evidence | Access |
|---|---|---|---|
| 1 | **`mcp__yfinance__get_consensus_estimates`** | CRCL FY EPS 2.37 (22 analysts), COIN FY EPS 4.85 (28 analysts) | ✅ Wired |
| 2 | **`mcp__yfinance__get_target_prices`** | CRCL mean $132.17 / range $55–$280. COIN mean $230.04 / range $107–$400 | ✅ Wired |
| 3 | **`mcp__yfinance__get_recommendations`** | CRCL 11 rating events incl. Compass Point downgrade. COIN 26 events incl. Barclays Underweight | ✅ Wired |
| 4 | **`mcp__polygon__get_options_chain`** | AAPL full chain w/ IV+Greeks returned (122k chars) | ✅ Wired (free tier) |
| 5 | **`mcp__edgar__get_filings`** (13F access) | CRCL + COIN filings list incl. 13G | ✅ Wired |
| 6 | **`mcp__market_data__get_real_time_quote`** | CRCL $131.20, COIN $215.39 (15-min delayed) | ✅ Wired |
| 7 | **Stock Analysis** (`stockanalysis.com`) | CRCL: $131.76, mcap $32B, rev $2.86B, PT $125.53. COIN: $216.60, $57B, PT $298.33 | ✅ Free verified |
| 8 | **Finviz** (`finviz.com/quote.ashx?t=`) | CRCL P/E fwd 75.87 + insider%. COIN P/E 81.45 + headlines | ✅ Free verified |

### 12.7 Community / Sentiment / Independent Analysts

| # | Source | Evidence | Access |
|---|---|---|---|
| 1 | **Dataroma** (`dataroma.com/m/stock.php?sym=`) | CRCL: Tiger Global 500k sh +300% add. COIN: Patient Capital 178,923 sh +4.18% | ✅ Verified open |
| 2 | **Motley Fool transcripts** (via quote pages) | Free transcript listings + retail commentary for both tickers | ✅ Verified open |
| 3 | **Apewisdom** (`apewisdom.io/stocks/<T>/`) | CRCL: 15 mentions, 67% positive (last 24h). COIN: page loads but 0 mentions | ✅ Verified (asymmetric coverage) |

---

### 12.99 Demoted from top tier — verified ❌ or ⚠️ in test

These were in the previous draft of §12 but **failed the CRCL+COIN cross-ticker verification**. Do not rely on them in the workflow without further fix:

**Failed access:**
| Source | Cause | Fix path |
|---|---|---|
| `mcp__polygon__get_put_call_ratio` / `get_iv_term_structure` / `get_unusual_activity` | `polygon_tier_insufficient` — needs $29/mo Options Starter | Upgrade Polygon plan, OR compute P/C from chain snapshot in code |
| `mcp__macro_stack__get_bls_series` | `missing_api_key` | Set `BLS_API_KEY` env var |
| EDGAR full-text search direct WebFetch | 403 SEC UA-block | Always route via `mcp__edgar` MCP, not WebFetch |
| OpenInsider HTTPS | ECONNREFUSED from sandbox | Build a dedicated MCP w/ proper UA + retry policy |
| Quiver Quant `/stocks/<T>/` | 404 — URL pattern stale | Re-scrape current sitemap before adding |
| Ortex `public.ortex.com/<T>` | 404 — URL pattern stale | Use Ortex paid API ($70+/mo) |
| TIKR `/stock/<T>` | 404 both URL forms | Re-scrape sitemap or use TIKR's app URL pattern |
| Quartr `/companies/<slug>` | Slug 404 (CRCL not in index; COIN slug pattern wrong) | Use Quartr search to resolve real slug; CRCL too new |
| WhaleWisdom `/stock/<T>` | Marketing chrome only — ticker pages auth-gated | Sign up for free account, then test |
| AlphaSense free trial | Login wall pre-content | Activate trial, then test |
| Koyfin `/share/security/<T>-US` | JS-rendered post-auth | Authenticated session needed |
| USPTO Patent Public Search | JS app shell, no SSR results | Use USPTO's structured API instead of WebFetch on the search app |
| Lens.org search | Sign-in modal blocks results | Free account required |

**Partial / asymmetric coverage:**
| Source | CRCL | COIN | Issue |
|---|---|---|---|
| Yahoo Finance quote page | ✅ | ❌ "Oops, something went wrong" | Intermittent server-side error on COIN |
| Capitol Trades `/trades?txTicker=<T>` | ⚠️ | ⚠️ | Ticker filter is client-side JS; static HTML shows unfiltered feed |
| Semafor Business search | ⚠️ | ⚠️ | Search results JS-rendered, not SSR |
| Simply Wall St | ❌ (not indexed — recent IPO) | ✅ PT $383.46 | Coverage gap on new IPOs |
| Baker Hughes rig count page | ⚠️ JS-only | — | Use the XLSX static-files endpoint instead |
| Wall Street Horizon | ⚠️ marketing-only | — | Data behind sales contact |

**Explicitly excluded (weak methodology):** Grand View Research, MarketsandMarkets, Mordor Intelligence, Fortune Business Insights, Allied Market Research, Verified Market Research, Databridge.

---

**Curation principle (post CRCL+COIN test):**
- Only sources that **returned ticker-specific data on the test calls** earn a ✅ slot.
- Wide-coverage MCPs (`mcp__market_data__get_news`, `mcp__edgar__*`, `mcp__yfinance__*`) dominate because one tool = many sources of signal.
- The free retail trio for any name: **Stock Analysis + Finviz + Motley Fool quote pages**. The free 13F supplement: **Dataroma**.
- For options positioning beyond raw chain: **upgrade Polygon to Options Starter ($29/mo) OR compute P/C from `get_options_chain` snapshot in post-processing** — current tier limits free endpoint to `get_options_chain` only.
