# Peak-Pain Archetype Catalog v0.1

**Date:** 2026-04-29
**Purpose:** Counterfactual matching catalog for Section 6 Q6 (d') counterfactual VETO authority. When a watchlist name hits >2× cut threshold drawdown, P8 retrieves top-3 archetype matches from this catalog using structural features at peak-pain moment. ≥2 SURVIVOR matches with NDCG@3 ≥0.7 → cut requires explicit operator override.

**Source:** 14 parallel research subagents (2026-04-29) covering tech/SaaS, semis/hardware, consumer-discretionary, consumer-brands, fintech, healthcare/biotech, industrial, energy, comms/media, international/EM, EV/autos, REITs, recent-IPO/SPAC, crypto-adjacent, financials/banks. ~110 cases total.

**Outcome taxonomy:**
- **SURVIVOR** — recovered to multi-bag from trough OR back to prior high within 36 months
- **DILUTED-SURVIVOR** — entity recovered, per-share value did not (massive equity issuance at trough)
- **NON-SURVIVOR** — bankrupt OR still >50% below prior high 24+ months post-trough
- **TBD** — pending; ≤24 months since trough

**TBD handling (LOCKED):** TBD cases are kept in the catalog as observation log but **EXCLUDED from active retrieval** until outcome resolves. Retrieval pipeline filters `outcome ∈ {SURVIVOR, DILUTED-SURVIVOR, NON-SURVIVOR}` only. When TBD resolves (24+ months post-trough OR definitive event like Ch.11 / acquisition / full-recovery to prior peak), case auto-graduates to active retrieval via Section 5 Q4 event-driven adds. This preserves observation work while keeping training data clean.

---

## Schema — TWO-LAYER

Each case is annotated against a two-layer schema. Features are evaluated AT THE PEAK-PAIN MOMENT, not entry time.

### Layer 1 — Universal core (sector-agnostic, mandatory for every case)

These 6 features are sector-agnostic and ALWAYS populated. Cross-sector retrieval operates on this layer alone.

| Field | Values | Cross-sector validity |
|---|---|---|
| founder_insider_stake_direction | increasing / flat / decreasing / departed | All sectors — net-buy/sell at trough is universal signal |
| cash_runway | >24mo / 12-24mo / <12mo / distressed | All sectors — solvency math is universal (banks: liquidity-runway proxy) |
| founder_in_place | yes / departed / replaced-by-competent | All sectors — leadership continuity is universal |
| margin_trajectory | improving / stable / deteriorating | All sectors (biotech pre-revenue: cash-burn-trajectory proxy) |
| revenue_trajectory | growing / flat / declining / pre-revenue | All sectors |
| industry_tailwind | intact / weakening / reversed / structural-decline | All sectors |

### Layer 2 — Sector-specific extensions (used only when candidate ↔ case match sector)

These features add precision within a sector. Used as tie-breaker; do NOT apply across sectors.

| Sector | Extensions |
|---|---|
| Tech/SaaS | customer_engagement (holding/eroding/collapsed), engagement_decoupling_from_price (yes/no), NDR_trend |
| Semis/hardware | moat_state (intact/weakening/leapfrogged), cycle_state (cyclical-trough/secular-decline), customer_concentration |
| Consumer-discretionary | repeat_purchase_trajectory, brand_equity_state, distribution_channel_integrity |
| Consumer-brands | brand_equity_state, leverage_level, leadership_replacement_quality |
| Fintech | take_rate_trajectory, credit_quality (for lenders), regulatory_standing |
| Healthcare/biotech | pipeline_depth (diversified/concentrated), trial_status_at_trough, TAM_state |
| Industrial | backlog_quality (contracted/aspirational), litigation_state (open-ended/contained/resolved), CEO_change_quality (Culp-pattern/caretaker/founder-entrenched) |
| Energy | net_debt_at_trough, hedge_book, reserve_quality, cost_curve |
| Comms/media | content_IP_moat_state, subscriber_DAU_trajectory, leverage_multiple |
| International/EM | regulatory_overhang_state, geopolitical_state, capital_controls_FX_exposure |
| EV/autos | production_trajectory, vehicle_margin, capital_structure (public-only / sovereign-backed) |
| REITs | property_tier (A/B/C), debt_maturity_wall, asset_class_tailwind, tenant_credit_concentration |
| Recent-IPO/SPAC | redemption_rate, lockup_behavior, deck_vs_actual_revenue_gap |
| Crypto-adjacent | counterparty_exposure, cost_curve (miners), regulatory_standing |
| Financials/banks | capital_ratio, uninsured_deposit_pct, dilution_at_trough, asset_quality |

---

## Cases

### Tech / SaaS

| Ticker | Peak DD | Outcome | Founder stake | Cash runway | Engagement | Decoupling | Tailwind | Founder | Margin | Revenue |
|---|---|---|---|---|---|---|---|---|---|---|
| SHOP (2021-22) | -85% | SURVIVOR | flat | >24mo | holding | yes | weakening | yes | improving | growing |
| PLTR (2021-22) | -85% | TBD/SURVIVOR | holding (Karp+Thiel) | >24mo (~$2.5B; FCF+) | holding (gov sticky) | yes | weakening (post-SPAC + gov-IT choppy) | yes (Karp) | improving (post-cost-cuts) | growing (slowing+) |
| ZM (2020-23) | -89% | NON-SURVIVOR | decreasing | >24mo | eroding | no | reversed | yes | stable | flat/decel |
| DOCU (2021-22) | -87% | NON-SURVIVOR | departed | >24mo | eroding | no | reversed | departed | improving | flat/decel |
| ROKU (2021-22) | -92% | NON-SURVIVOR | decreasing | >24mo | holding | yes | weakening | yes | deteriorating | growing |
| TWLO (2021-22) | -91% | TBD | departed | >24mo | eroding | no→yes | weakening | departed | improving | flat |
| SQ/XYZ (2021-23) | -86% | TBD/SURVIVOR | flat-incr (Dorsey return) | >24mo | holding | yes | weakening | yes | improving | growing |
| MDB (2021-22) | -77% | SURVIVOR | flat | >24mo | holding | yes | intact | yes | improving | growing |
| OKTA (2021-22) | -85% | NON-SURVIVOR | flat | >24mo | eroding | no | intact | yes | improving | decel |
| SPLK (2020-22) | -69% | NON-SURVIVOR (forced sale) | departed | >24mo | eroding | no | intact | departed | deteriorating | decel |

### Semis / Hardware

| Ticker | Peak DD | Outcome | Founder stake | Cash | Customer-conc | Moat | Cycle | Founder | Margin | Revenue |
|---|---|---|---|---|---|---|---|---|---|---|
| NVDA (2007-08) | -85% | SURVIVOR | flat-incr | >24mo | moderate | intact | cyclical-trough | yes (Huang) | improving | trough |
| AMD (2014-16) | -80% | SURVIVOR | replaced-by-competent | 12-24mo | fragile→mod | intact (Zen pipeline) | cyclical-trough | replaced (Su) | stable | mixed |
| MU (2014-16) | -70% | SURVIVOR | flat | 12-24mo | moderate | intact (oligopoly) | cyclical-trough | replaced | improving | trough |
| AMAT (2007-08) | -85% | SURVIVOR | flat | >24mo | strong | intact | cyclical-trough | flat | stable | trough |
| MRVL (2014-16) | -60% | SURVIVOR | replaced | >24mo | fragile | weakening→intact | mixed | replaced | improving | mixed |
| CSCO (2000-02) | -85% | TBD (entity ok, investor stuck) | flat | >24mo | moderate | intact (operationally) | secular-valuation-reset | yes | stable | mixed |
| SUNW (2000-08) | -95% | NON-SURVIVOR | departed | 12-24mo | fragile | leapfrogged | structural-decline | departed | deteriorating | declining-secular |
| NOK (2007-12) | -90% | NON-SURVIVOR | departed | 12-24mo | strong-but-irrel | leapfrogged | structural-decline | departed | deteriorating | declining-secular |
| BBRY (2008-13) | -95% | NON-SURVIVOR | new-equity-grant | 12-24mo | fragile | leapfrogged | structural-decline | replaced-too-late | deteriorating | declining-secular |
| INTC (2021-25) | -75% | TBD/NON-SURVIVOR-leaning | departed | <24mo | fragile | leapfrogged | structural-decline + late-cycle | replaced | deteriorating | declining-secular |

### Consumer Discretionary

| Ticker | Peak DD | Outcome | Insider | Cash | Repeat | Decoupling | Tailwind | Founder | Margin | Revenue |
|---|---|---|---|---|---|---|---|---|---|---|
| PTON (2021-24) | -98% | TBD | sold-pre-drop | <12mo | eroding | no | reversed | departed | improving | declining |
| CVNA (2021-22) | -99% | SURVIVOR | bought-trough ($42M) | <12mo | holding (NPS 70+) | yes | weakening→intact | yes | improving | declining→growing |
| BBBY (2021-23) | -100% | NON-SURVIVOR | Cohen exit | <12mo | collapsed | no | weakening | departed | deteriorating | declining |
| W (2021-22) | -93% | SURVIVOR | flat (founders aligned) | 12-24mo | eroding | no | reversed | yes | stable | declining |
| BYND (2019-24) | -98% | TBD/NON-SURVIVOR | flat (creditibility) | 12-24mo | collapsed | no | reversed | yes | deteriorating | declining |
| NCLH (2020) | -85% | SURVIVOR | N/A (PE) | <12mo→raised | holding (forward bookings) | yes | reversed→recovered | N/A | deteriorating→improving | declining→growing |
| ETSY (2021-24) | -85% | SURVIVOR | N/A | >24mo | eroding | no | weakening | N/A | stable | flat |
| TUP (2013-24) | -99% | NON-SURVIVOR | none | <12mo | collapsed | no | reversed | N/A | deteriorating | declining |
| EXPR (2018-24) | -99% | NON-SURVIVOR | none | <12mo | collapsed | no | reversed | N/A | deteriorating | declining |
| RH (2021-23) | -71% | SURVIVOR | levered-buyback (mixed) | 12-24mo | holding (luxury) | yes | weakening | yes | stable | declining |
| SFIX (2021-23) | -97% | TBD | partial-return-distress | 12-24mo | eroding | no | reversed | partial | stable | declining |
| BIRD (2021-26) | -99% | NON-SURVIVOR | departed | <12mo | collapsed | no | reversed | departed | deteriorating | declining |

### Consumer Brands

| Ticker | Peak DD | Outcome | Insider | Cash/Lev | Brand | Engagement | Tailwind | CEO | Margin | Revenue |
|---|---|---|---|---|---|---|---|---|---|---|
| CROX (2007-08) | -99% | SURVIVOR | new operator | distressed | eroding-but-recognizable | holding | weakening→reversed | replaced (McCarvel/Rees) | deteriorating→improving | declining→growing |
| KHC (2017-19) | -72% | SURVIVOR (chronic) | flat (Berkshire/3G no-add) | stretched | eroding | eroding | weakening | replaced (mixed) | deteriorating | flat-decline |
| EL (2022-24) | -78% | TBD/SURVIVOR | family-aligned | stretched | intact | eroding-China | reversed-luxury-China | replaced TBD | deteriorating | declining |
| NKE (2021-24) | -57% | TBD (turnaround) | family-aligned | healthy | eroding-China | eroding-DTC | intact-global | replaced (Hill) | deteriorating | declining |
| LULU (2023-25) | -66% | TBD | flat | healthy | eroding-US | eroding-women | weakening | flat | stable | growing |
| HSY (2023-25) | -50% | SURVIVOR | controlling-trust | healthy | intact | holding | weakening (cocoa) | flat | deteriorating (cocoa) | flat |
| TUP (2013-24) | -99% | NON-SURVIVOR | none | distressed | collapsed | eroded | reversed | multiple-failed | deteriorating | declining |
| REV (2010s-22) | -95%+ | NON-SURVIVOR | levered-control | distressed | collapsed | eroded | reversed | multiple-failed | deteriorating | declining |
| HBI (2015-23) | -87% | SURVIVOR (asset-sale) | limited | distressed | eroding | eroding | weakening | replaced (mixed) | deteriorating | declining |
| BUD (2023) | -21% (parent) | SURVIVOR (Bud Light brand impaired) | flat | stretched | brand-impaired | -26% off-prem | weakening-beer | reshuffled | stable | $1B brand-loss |
| CPRI (2023-24) | -70% | TBD (failed M&A) | CEO-retained | stretched | eroding | eroding | weakening | flat (criticized) | deteriorating | declining |
| TPR/Coach (2012-14) | -58% | SURVIVOR | new (Luis+Vevers) | healthy | eroding→stabilizing | eroding→stable | weakening | replaced (high-quality) | improving | declining |

### Fintech

| Ticker | Peak DD | Outcome | Founder | Cash | Take-rate | Credit-quality | Regulatory | CEO | Unit econ | Revenue |
|---|---|---|---|---|---|---|---|---|---|---|
| PYPL (2021-23) | -83% | SURVIVOR (stuck) | sold | $10B+ | eroding | N/A | intact | departed (Schulman→Chriss) | stabilizing | growing-low |
| SQ (2021-23) | -80% | SURVIVOR | flat (Dorsey) | strong | holding | N/A | overhang→weakening | yes | improving | growing |
| AFRM (2021-22) | -95% | SURVIVOR | flat (Levchin) | rebuilt | holding | improving | intact | yes | improving | growing 30%+ |
| UPST (2021-23) | -97% | TBD | flat | strained | eroding | deteriorating | intact | yes | deteriorating | declining |
| SOFI (2021-22) | -83% | SURVIVOR | flat (Noto) | bank-charter | stable | stable | tailwind | yes | improving | growing 30%+ |
| HOOD (2021-22) | -90% | SURVIVOR | flat (Tenev) | $6B+ | holding | N/A | intact | yes | improving | growing |
| LMND (2021-23) | -93% | TBD (stuck) | flat (Wininger) | ~$900M | N/A | loss-ratio-elevated | intact | yes | deteriorating | growing-uneconomic |
| HIPO (2021-23) | -99% | TBD | replaced | ~$500M | N/A | loss-ratio>100% | intact | replaced | deteriorating | mixed |
| MARQ (2021-23) | -88% | SURVIVOR | replaced | $1B+ | eroding (concentration) | N/A | intact | replaced | mixed | growing |
| COIN (2021-23) | -91% | SURVIVOR | flat (Armstrong) | $5B+ | mixed | N/A | hostile→resolving | yes | improving (rate-tailwind) | growing |

### Healthcare / Biotech

| Ticker | Peak DD | Outcome | Founder | Cash | Pipeline | Trial-status | TAM | Founder | Margin | Revenue |
|---|---|---|---|---|---|---|---|---|---|---|
| TDOC (2021-24) | -97% | TBD-impaired | departed | >24mo | diversified | N/A | weakening | departed | improving (cuts) | flat |
| MRNA (2021-24) | -94% | TBD-survivor | flat (Bancel) | >24mo (~$9B) | diversified | mixed (RSV approved) | weakening | yes | deteriorating | declining-sharp |
| NVAX (2021-24) | -99% | NON-SURVIVOR | departed | <12mo (Sanofi rescue) | concentrated | mixed | closed | departed | deteriorating | declining |
| BLUE (2018-25) | >99% | NON-SURVIVOR (private) | departed | <12mo | concentrated | positive-but-commercial-flop | intact-but-reimburse-broken | departed | deteriorating | growing-slow |
| ATEA (2020-24) | -97% | NON-SURVIVOR (zombie) | flat | >24mo (~$450M) | concentrated | negative | closed | yes | deteriorating | pre-revenue |
| GBIO/DNA (2021-24) | -97% | TBD | flat (Kelly) | 12-24mo | diversified-platform | N/A | weakening | yes | deteriorating | declining |
| TWST (2021-23) | -93% | SURVIVOR | flat (Leproust) | 12-24mo | diversified | N/A | intact | yes | improving | growing 25%+ |
| PACB (2021-24) | -97% | TBD | departed | 12-24mo | concentrated | N/A | intact-but-competitive | departed | deteriorating | declining |
| ME (23andMe) (2021-25) | -98% | NON-SURVIVOR (Ch11 2025) | departed-at-bk | <12mo | concentrated | divested | weakening | departed | deteriorating | declining |

### Industrial / Capital Goods

| Ticker | Peak DD | Outcome | Insider | BS/Lev | Backlog | Litigation | CEO-change | Margin | Revenue | End-market |
|---|---|---|---|---|---|---|---|---|---|---|
| GE (2017-18) | -80% | SURVIVOR (Culp) | bought ($2.5M) | distressed | strong (Aviation LTSA) | contained | yes-competent | deteriorating→reverting | declining | mid-bust |
| BA (2019-24) | -71% (extended -60%+) | TBD-distressed | minimal | stretched | strong ($500B) | open-ended | yes-TBD | deteriorating | flat-decline | end-of-bust possible |
| MMM (2018-23) | -67% | SURVIVOR (post-spin) | limited | stretched | moderate | contained-2023 | yes-improving | improving | flat | mid-bust |
| ENR.DE (Siemens E.) (2023) | -75% | SURVIVOR | govt-backstop | stretched | strong (€120B) | contained | partial (Gamesa) | deteriorating→improving | growing-orders | end-of-bust |
| PLUG (2021-24) | -97% | NON-SURVIVOR-leaning | dilutive (no buy) | distressed | fragile (aspirational) | contained | NO (founder-entrenched) | deteriorating | declining | structural-decline |
| ENPH (2022-24) | -82% | TBD-survivor | limited | healthy (net cash) | fragile | contained | NO | deteriorating | declining-sharp | mid-bust |
| SEDG (2022-25) | -97% | NON-SURVIVOR-leaning | departed | distressed | fragile | contained | yes-late | deteriorating | collapsed | mid-late-bust |
| GNRC (2021-23) | -83% | SURVIVOR | flat (Jagdfeld) | healthy IG | moderate | contained | NO | deteriorating→improving | declining→growing | end-of-bust |
| RUN (2021-25) | -92% | TBD-NON-SURVIVOR-leaning | limited | stretched | moderate | contained | yes-TBD | deteriorating | declining | mid-bust |
| CAT (2012-16) | -50% | SURVIVOR | flat (Oberhelman) | healthy IG | moderate | contained | NO | deteriorating | declining | end-of-bust |

### Energy / Commodities

| Ticker | Peak DD | Outcome | Insider | Net-debt | Hedge | Reserve | Cost-curve | Cycle | OCF |
|---|---|---|---|---|---|---|---|---|---|
| OXY (2019-20) | -87% | SURVIVOR (Buffett rescue) | Hollub bought | distressed | moderate | tier-1 (Permian) | median | trough-forward | deteriorating→improving |
| CHK (2014-20) | -99% | NON-SURVIVOR (Ch11) | none | distressed | strong-PV (insufficient) | tier-2 | high | structural-headwind (gas) | deteriorating |
| WLL (2014-20) | -99% | NON-SURVIVOR (Ch11) | none | distressed | unhedged | tier-2 | high | trough-forward | deteriorating |
| EOG (2018-20) | -79% | SURVIVOR | bought | healthy | moderate | tier-1 | low (~$35-40 BE) | trough-forward | stable→improving |
| DO (2013-20) | -99% | NON-SURVIVOR (Ch11) | controlling-non-protective | distressed | N/A | marginal (aging) | high | structural-headwind | deteriorating |
| BTU (2011-16) | -99% | NON-SURVIVOR (Ch11×2) | none | distressed (top-of-cycle M&A) | N/A | tier-1-but-stranded | median | structural-headwind | deteriorating |
| FCX (2011-16) | -94% | SURVIVOR | Icahn-activist | distressed | unhedged | tier-1 | median | trough-forward | improving |
| HAL (2014-20) | -93% | SURVIVOR | moderate | stretched | N/A | N/A | low (#1 NA frac share) | trough-forward | improving |
| CRC (2014-20) | -98% | NON-SURVIVOR (Ch11) | none | distressed | moderate | tier-2 | high | structural-headwind | deteriorating |
| CLR (2014-20) | -90% | SURVIVOR (taken private) | Hamm bought $4.7M shr | stretched | unhedged-at-pain | tier-1/2 | median | trough-forward | deteriorating→improving |

### Communications / Media

| Ticker | Peak DD | Outcome | Founder | Sub-traj | Decoupling | Content-moat | Cash/Lev | Tailwind | CEO | Margin |
|---|---|---|---|---|---|---|---|---|---|---|
| NFLX (2011) | -80% | SURVIVOR | yes (Hastings) | rebound | yes | intact (HoC greenlit) | stretched | intact | yes | deteriorating→stabilizing |
| NFLX (2021-22) | -75% | SURVIVOR | yes (Hastings→co-CEOs) | -1.2M→growing | yes | intact | healthy | weakening | transition | stable→improving (ads) |
| SPOT (2021-22) | -80% | SURVIVOR | yes (Ek) | growing | yes | intact (network+podcast) | stretched | intact | yes | deteriorating→sharp turn |
| PINS (2021-22) | -81% | SURVIVOR | partial-departure | declining | partial | weakening | healthy | weakening | replaced (Ready) | deteriorating→stable |
| RBLX (2021-22) | -83% | SURVIVOR | yes (Baszucki) | DAU growing | yes | intact (UGC NW) | healthy ($3B) | weakening | yes | deteriorating |
| WBD (2022-24) | -74% | TBD-distressed | none (Zaslav post-merger) | flat-declining | no | intact-underutilized | stretched (5x) | reversed | flat | deteriorating |
| PARA (2021-24) | -90% | NON-SURVIVOR-direction | sold (Redstone) | growing-but-losing | no | eroding | stretched | reversed | departed | deteriorating |
| LUMN (2007-23) | -97% | NON-SURVIVOR | none | declining | no | commoditized | distressed (-$18B) | reversed | replaced-late | deteriorating |
| IHRT (2019-24) | -95% | NON-SURVIVOR | PE-owned | declining | no | commoditized | distressed (6.2x) | reversed | flat | deteriorating |
| AMC (2021-24) | -96% | NON-SURVIVOR-direction | none | declining | no | commoditized | distressed | reversed | flat | deteriorating |
| MTCH (2021-24) | -84% | TBD-survivor | founder-suit | declining | no | weakening (Gen-Z) | stretched | weakening | multiple-changes | stable |

### International / EM

| Ticker | Peak DD | Outcome | Founder | Cash/FX | Regulatory | Concentration | Geopolitical | Founder-active | Margin | Revenue |
|---|---|---|---|---|---|---|---|---|---|---|
| BABA (2020-24) | -79% | SURVIVOR | sidelined→returned (Ma bought) | $85B-NC | resolving (Ant settled) | China-domestic | deteriorating→stabilizing | sidelined | improving | flat-low-grow |
| TCEHY (2021-22) | -74% | SURVIVOR | active (Pony Ma) | strong-RMB | resolving | China-dom | stable | yes | improving | flat→growing |
| JD (2021-22) | -80%+ | SURVIVOR | Liu sidelined→returned | strong | contained | China-dom | stable | sidelined→hands-on | improving | decel→reaccel |
| PDD (2021-22) | -88% | SURVIVOR (re-rated higher) | Huang departed-controlling | very-strong | contained-China; new-US-Temu | China+global | deteriorating-Temu-target | departed-aligned | improving-sharp | growing-fast |
| SE (2021-22) | -89% | SURVIVOR | active (Forrest Li) | $6B-USD | contained | SEA+LatAm | stable | yes | improving-sharp | flat→growing |
| PBR (2014-16) | -87% | SURVIVOR | govt-controlling | levered-FX-stress | open-ended | Brazil+oil | improving-post-2016 | reset (Parente) | deteriorating→improving | declining |
| VALE (2011-16) | -94% | SURVIVOR | controlling-stable | stretched | contained-2016; Brumadinho-2019 | China-iron | stable | flat | deteriorating→improving | declining→recovering |
| ADYEN (2023) | -75% | SURVIVOR | yes (van der Does+Schuijff) | strong-EUR | contained | global-diversified | stable | yes | deteriorating | growing-decel |
| MELI (2021-22) | -70% | SURVIVOR | yes (Galperin) | strong | contained | LatAm-diversified | stable | yes | improving-sharp | growing 30%+ |
| CPNG (2021-22) | -87% | SURVIVOR | yes (Bom Kim) | $3B-KRW | contained | Korea→expanding | stable | yes | improving-sharp | growing |

### EV / Autos

| Ticker | Peak DD | Outcome | Founder | Cash | Production | Vehicle-margin | Moat | Tailwind | Founder-active | Order-book |
|---|---|---|---|---|---|---|---|---|---|---|
| TSLA (2018-19) | -54% | SURVIVOR (multi-bag) | flat (Musk) | 12-24mo (raised $2.7B) | growing (Model 3) | improving | intact | intact | yes | strong |
| TSLA (2021-23) | -74% | SURVIVOR | sold-$40B-Twitter | >24mo ($22B) | growing | deteriorating (price cuts) | intact | weakening | yes | moderate |
| RIVN (2021-24) | -95% | TBD (VW $5B 2024) | flat (Scaringe) | 12-24mo→saved | growing-slow | catastrophic-negative | weakening | weakening | yes | moderate-cancellations |
| LCID (2021-24) | -96% | TBD (Saudi PIF) | departed (Rawlinson 2025) | sovereign-backed only | growing-slow | catastrophic | weakening | weakening | departed | declining |
| FSR (Fisker) (2021-24) | -100% | NON-SURVIVOR | flat (committed) | <12mo | declining | catastrophic | none | weakening | yes | declining-cancellations |
| RIDE (2021-23) | -100% | NON-SURVIVOR | departed (fraud-allegations) | <12mo | minimal | never-commercial | none | weakening | departed | declining |
| GOEV (2020-25) | -100% | NON-SURVIVOR (Ch7) | flat | <12mo (<$50K) | minimal | never-commercial | none | weakening | yes (during Ch7) | token |
| GM (2000-09) | -100% | NON-SURVIVOR (Ch11; New GM IPO'd) | N/A | <12mo (TARP) | declining | deteriorating | weakening | reversed | replaced (Wagoner) | declining |

### REITs / Real Estate

| Ticker | Peak DD | Outcome | Insider | Debt-wall | LTV | Property-tier | Tenant-traj | Asset-tailwind | CEO | AFFO |
|---|---|---|---|---|---|---|---|---|---|---|
| CBLAQ (2016-20) | -99% | NON-SURVIVOR (Ch11) | wiped | immediate | distressed | Class B/C mall | collapsed | structural-decline | departed | zero |
| PEI (2007-20) | -99% | NON-SURVIVOR (Ch11×2) | wiped×2 | immediate | distressed | Class B mall | collapsed | structural-decline | departed | zero |
| WPG (2014-21) | -93% | NON-SURVIVOR (Ch11) | wiped | immediate | distressed | Class B/C | collapsed | structural-decline | departed | zero |
| SPG (2020) | -72% | SURVIVOR (recovered to ATH 2022) | flat (Simon) | distant IG | stretched-IG | Class A premium | holding | weakening (not structural for A) | yes | cut-then-restored |
| SLG (2019-23) | -79% | TBD-SURVIVOR | net-seller-2025 | near | stretched | Class A NYC office | holding | weakening | yes | cut |
| VNO (2015-23) | -88% | TBD | flat (Roth) | near | stretched | Class A NYC+DC | eroding | weakening/structural-NYC-office | yes | suspended |
| HPP (2022-24) | -89% | TBD (recapped) | diluted | extended | distressed | Class A West-Coast tech | eroding (tech-layoffs) | structural-decline | yes | cut-sharply |
| OPI (2019-24) | >95% | NON-SURVIVOR-trajectory | RMR-external | immediate | distressed | Class B suburban | collapsed | structural-decline | external | 99%-cut |
| MPW (2022-24) | -87% | TBD-impaired | net-seller-2022 | near ($10.1B) | distressed | hospital | collapsed (Steward) | weakening | flat-but-selling | 2-cuts |
| OPEN (2021-23) | -96% | TBD-NON-SURVIVOR | departed | warehouse-line | distressed | SFR iBuy | N/A | structural-decline | departed | never-prof |
| COMP (2021-23) | -92% | SURVIVOR | flat (Reffkin) | low-debt | cash-light | brokerage-platform | agent-roster-stab | weakening (cyclical) | yes | never-paid |
| HOV (2005-09) | -98% | SURVIVOR (no Ch11) | family-control | extended-distressed-exch | distressed | SFR-builder | N/A | cyclical | yes | paused |

### Recent IPO / SPAC

| Ticker | Peak DD | Outcome | SPAC-redemption | Founder/Insider | Cash | Revenue | Unit-econ | Founder-CEO | Lockup | Tailwind |
|---|---|---|---|---|---|---|---|---|---|---|
| PATH (2021-22) | -87% | SURVIVOR | N/A IPO | mixed-early-lockup | >24mo | growing-decel | improving | partial-step-aside | pressure | weakening |
| TOST (2021-22) | -81% | SURVIVOR | N/A IPO | flat (3 co-founders) | >24mo | growing | improving (adj-EBITDA-be) | yes | pressure | intact |
| CHPT (2021-24) | -96% | TBD/zombie | low-at-merger | departed | 12-24mo (~$220M) | declining | deteriorating | departed | pressure | reversed |
| MTTR (2021-23) | -95% | NON-SURVIVOR (acquired) | moderate | selling+lockup-suit | >24mo | flat (deck-miss) | deteriorating (60%→38% GM) | departed | pressure+lit | reversed |
| COMP (2021-22) | -90% | SURVIVOR | N/A IPO | SoftBank-flat | 12-24mo | declining | deteriorating | yes (Reffkin) | pressure | reversed |
| ASAN (2020-22) | -91% | SURVIVOR | N/A direct-listing | bought-aggressively (Moskovitz) | >24mo | growing-decel | improving | yes (until 2025-retire) | clean | weakening |
| GTLB (2021-23) | -80% | SURVIVOR | N/A IPO | flat (Sijbrandij) | >24mo | growing 30%+ | improving | yes (until 2024-health) | pressure | intact |
| SG (2021-23) | -87% | TBD | N/A IPO | flat (Neman) | 12-24mo | growing-slow | deteriorating | yes | pressure | weakening |
| HIMS (2021-22) | -88% | SURVIVOR (massive 2024-25) | low | flat (Dudum) | >24mo | growing 75% | improving | yes | pressure | intact→accelerating |
| BLND (2021-23) | -96% | TBD/zombie | N/A IPO | flat (Ghamsari) | 12mo (going-concern) | declining | deteriorating | yes | pressure | reversed |
| BETR (2023-) | -99% | NON-SURVIVOR | 92.6% | flat (Garg) | <12mo | declining | deteriorating | yes | N/A | reversed |

### Crypto-Adjacent

| Ticker | Peak DD | Outcome | Founder | Cash | Hedging | Cost-curve | Regulatory | Counterparty | Customer-flight | CEO |
|---|---|---|---|---|---|---|---|---|---|---|
| COIN (2021-22) | -91% | SURVIVOR | flat (Armstrong) | >24mo ($5B) | direct-exposure | N/A | contested→resolving | contained | stable | yes |
| MSTR (2021-22) | -89% | SURVIVOR (multi-bag-recovery) | flat-buyer (Saylor) | 12-24mo (legacy SaaS CF) | direct-exposure | N/A | clean | none (self-custody) | N/A | step-down→Chair |
| SI (2021-23) | -97% | NON-SURVIVOR (liquidation) | sold-reduced | run-on-deposit | N/A | N/A | under-investigation | large (FTX) | run | departed |
| SBNY (2022-23) | -100% | NON-SURVIVOR (FDIC) | mismanagement | run-on-deposit | N/A | N/A | under-investigation | large | run | departed |
| MARA (2021-22) | -95% | SURVIVOR | flat (Thiel) | 12-24mo (ATM) | direct | median | contested (SEC subpoena) | contained (Compute North) | stable | yes |
| RIOT (2021-22) | -96% | SURVIVOR | flat (Les) | >24mo | direct | low (Rockdale TX) | clean (EPA scrutiny) | none | stable | yes |
| CLSK (2021-22) | -92% | SURVIVOR | flat (Bradford) | 12-24mo (low-debt) | direct | low (Sandersville GA) | clean | none | stable | yes |
| GLXY (2021-22) | -89% | SURVIVOR (with reg-tail) | flat (Novogratz) | 12-24mo | mixed | N/A | under-investigation (NYAG-LUNA) | large ($76.8M FTX) | stable | yes |
| CORZ (2022) | -99% | NON-SURVIVOR (Ch11; emerged-diluted) | diluted | <12mo | direct | median (heavy capex-debt) | clean | large (Celsius+BlockFi) | stable | departed |
| Voyager (2021-22) | -99% | NON-SURVIVOR (Ch11) | wiped (CFTC charges) | run | N/A | N/A | under-investigation | large ($650M 3AC) | run | departed |

### Financials / Banks

| Ticker | Peak DD | Outcome | Insider | Capital | Liquidity | Asset-quality | Deposit-flight | Regulatory | CEO | Dilution |
|---|---|---|---|---|---|---|---|---|---|---|
| C (2006-09) | -98% | DILUTED-SURVIVOR (no per-share recovery) | n/a | inadequate (TARP+ring-fence) | run-prone-wholesale | impaired (CDO) | accelerating | govt-conditions | replaced (Pandit) | extreme (10x sh-ct, 1:10 RS) |
| BAC (2006-09) | -94% | DILUTED-SURVIVOR | n/a | adequate-on-paper (TARP $45B) | stressed-retail-deposits | impaired (Countrywide+Merrill) | stable | SEC-suit | replaced (Lewis→Moynihan) | extreme |
| JPM (2007-09) | -72% | SURVIVOR (full per-share recovery) | flat (Dimon) | strong (T1 ~10.9%) | strong (fortress) | contested-absorbed | stable | clean | yes | moderate (TARP repaid early) |
| AIG (2000-09) | -99.7% | DILUTED-SURVIVOR (no recovery) | n/a | catastrophic | death-spiral | impaired-CDS | n/a | govt-79.9% | replaced | extreme (1:20 RS) |
| LEH (2007-08) | -100% | NON-SURVIVOR (Ch11) | wiped | inadequate (~30x lev, Repo-105) | run-tri-party-repo | impaired (CRE 30x) | run | pre-bk | flat-Fuld | n/a |
| WM (2007-08) | -100% | NON-SURVIVOR (FDIC) | wiped | inadequate | 9-day run -$16.7B | impaired | run | seized | n/a | n/a |
| SIVB (2021-23) | -100% | NON-SURVIVOR (FDIC) | n/a | T1 12% (HTM-loss-mask) | 94% uninsured (run) | rate-mark-loss | run | clean→terminal | flat-Becker | n/a |
| FRC (2021-23) | -100% | NON-SURVIVOR (FDIC) | n/a | well-cap-on-paper | 67% uninsured; -40.8% Q1 | clean credit; rate-marks | run | $30B-private-failed | flat | n/a |
| FLG/NYCB (2024) | -82% | DILUTED-SURVIVOR (TBD) | Mnuchin-led raise | bolstered-via-extreme-dilution | deposit-pressure | rent-stab-multifam-CRE+Signature-stress | mixed | consent-order | replaced (Cangemi→Otting) | extreme |
| MS (2007-08) | -87% | SURVIVOR | flat (Mack) | stressed | wholesale-run-prone (BHC-conv) | mixed | mixed | clean | replaced (→Gorman) | moderate (MUFG) |

---

## Cross-sector discriminating-feature themes

These are the features that consistently separated SURVIVORS from NON-SURVIVORS across all 14 sectors. They form the priority weights for the Section 6 Q6 (d') counterfactual matching.

### Tier-1 discriminators (appear in every sector)

1. **Cash runway at trough** — binary across nearly every sector. Survivors had >12mo (often >24mo); zeros had <12mo with no credible path to raise. Most predictive single feature in EV/auto, biotech, fintech, recent-IPO/SPAC, energy, REITs.

2. **Founder/insider stake direction at peak pain** — the SHARPEST signal across consumer-discretionary, recent-IPO/SPAC, fintech, comms/media. Buying or holding correlates with survival; net-selling at trough correlates with continued decline. Special case: founder-CEO continuity OR replacement-by-competent-engineer (Lisa Su pattern) is survivor signal in semis/industrial.

3. **Engagement/customer decoupling from price** — when usage/GMV/MAU/cohort retention HOLDS while price collapses → recovery follows (SHOP, NFLX, RBLX, MDB, SE, MELI). When engagement falls with price → no recovery (DOCU, ZM, BYND, BBBY). Universal across tech/SaaS, consumer, comms/media.

4. **Industry tailwind state** — "intact-but-saturating" recovers; "structurally reversed" doesn't. Universal across sectors.

### Tier-2 discriminators (sector-specific but powerful within sector)

5. **Property/asset tier** (REITs) — Class A survives, B/C bankrupts in identical macro shock.

6. **Cost-curve position** (energy, semis, miners) — low-cost survives cycle troughs; high-cost dies even when macro recovers.

7. **Counterparty exposure** (crypto, banks, fintech) — single-counterparty concentration is kill-switch when upstream fails.

8. **Uninsured deposit %** (banks) — >50% uninsured with duration mismatch = receivership in days regardless of regulatory tier-1 ratio.

9. **Backlog quality** (industrial) — contracted (LTSA, government) survives; aspirational (hydrogen offtake, SPAC-deck projections) dies.

10. **Pipeline depth** (biotech) — diversified pipeline survives single-asset trial failure; concentrated pipeline doesn't.

### Tier-3 modifiers (context-shaping)

11. **Self-inflicted vs cyclical** — pure-multiple-compression (MDB, SHOP, NFLX-2011) recovers; self-inflicted (OKTA-Auth0, Splunk-cloud-fumble, DocuSign-overhire) doesn't.

12. **Regulatory contagion lag** (crypto, banks) — under-investigation status precedes terminal events by 30-90 days.

13. **Dilution at trough** (banks) — distinguishes SURVIVOR from DILUTED-SURVIVOR. Forced equity issuance saves enterprise but kills per-share value.

14. **CEO change quality** — replaced-by-competent (Culp at GE, Su at AMD, Niccol at SBUX, Hill at NKE, Luis at Coach) = recovery; caretaker replacement (Patricio at KHC, Bratspies at HBI) = chronic underperformance; founder-entrenched-through-pain (Marsh at PLUG, Fuld at LEH) = anti-survivor.

15. **Top-of-cycle debt-financed M&A** (energy, brands) — canonical destroyer (Peabody-Macarthur 2011, Freeport-McMoRan 2013, Oxy-Anadarko 2019, Kraft-Heinz 2015). 2 of 3 file BK.

---

## Implementation notes for Section 6 Q6 (d')

### Catalog → matching pipeline

When a watchlist name hits >2× cut threshold, P8:

1. Extracts candidate's peak-pain features using Section 5 Q3 3-LLM iterative-consensus pipeline (single-attribute LLM calls per feature with verbatim quote requirement)
2. Runs mechanical Hamming/Jaccard similarity against this catalog (Section 5 Q2 mechanical retrieval)
3. Returns top-3 matches with similarity scores
4. Counts SURVIVOR vs NON-SURVIVOR archetype matches in top-3
5. Computes NDCG@3 for ranking quality
6. Routes per Q6 (d') veto rules

### Calibration test set

Add 10-15 cases from this catalog to the Section 5 Q6 stratified-similarity test set, balancing:
- 5 SURVIVOR cases (varied sectors): NVDA-2008, AMD-2014, NFLX-2011, MELI-2022, CVNA-2022
- 5 NON-SURVIVOR cases (varied sectors): BBBY-2023, FSR-2024, CHK-2020, NOK-2012, OPI-2024
- 5 TBD/edge cases: PLTR-2022 (the motivating case), MRNA-2024, SLG-2023, INTC-2024, RIVN-2024

### Validation metric — Archetype-coverage (LOCKED)

Instead of NDCG@3, validate retrieval using **archetype-coverage agreement** — directly measures what the (d') veto rule actually consumes (archetype counts in top-3, not position-discounted ranking).

For each test case in the calibration set, operator pre-annotates the EXPECTED archetype distribution in top-3 (e.g., "NVDA-2008 should retrieve 3 SURVIVOR matches"; "BBBY-2023 should retrieve 3 NON-SURVIVOR matches"; "PLTR-2022 should retrieve 2-3 SURVIVOR + 0-1 NON-SURVIVOR").

**Pass criteria for veto authority enablement:**
- ≥80% of test cases have retrieved-top-3 archetype-distribution within ±1 of expected (e.g., expected 3 SURVIVOR, retrieved 2 SURVIVOR + 1 NON-SURVIVOR = within tolerance)
- ≥90% of canonical SURVIVOR test cases (NVDA-2008, AMD-2014, NFLX-2011 type) retrieve ≥2 SURVIVOR matches in top-3
- ≥90% of canonical NON-SURVIVOR test cases (BBBY, FSR, NOK type) retrieve ≥2 NON-SURVIVOR matches in top-3

**Why archetype-coverage (not NDCG@3):**
- Veto rule consumes archetype COUNTS in top-3, not ranking quality. Position 1/2/3 are treated equivalently in (d') logic. NDCG measures something the rule doesn't use.
- NDCG@3 ≥0.7 was carried over from Section 5 Q6 fraud-signature catalog context (different use case, larger curated set). Per Section 3 Q2 small-N research (Smith-Wallis 2009), high-precision metrics break at small per-archetype subset sizes.
- Archetype-coverage is robust at small N — counting agreement passes/fails cleanly.
- Validation is single-pass per test case (annotate expected distribution; check retrieved distribution); no hairsplitting on ranking quality.

**Per-test-case schema:**
```yaml
test_case:
  ticker: PLTR
  peak_pain_date: 2022-12
  expected_archetype_distribution_top_3:
    survivor_min: 2
    survivor_max: 3
    non_survivor_min: 0
    non_survivor_max: 1
    rationale: "Founder-led + sticky enterprise customers + intact tailwind suggests SURVIVOR-dominant retrieval; some ambiguity allows 1 NON-SURVIVOR (e.g., thematic-narrative-collapse) match"
  validated: pending
```

Pre-launch gate: 15 test cases annotated, 80%+ archetype-coverage agreement, 90%+ canonical-case correctness → veto authority enabled at v0.1.

### Retrieval scoring — TWO-LAYER architecture

Composite similarity score:
```
similarity(candidate, case) = 0.7 × universal_core_similarity
                            + 0.3 × sector_extension_similarity   IF sector(candidate) == sector(case)
                            + 0     × sector_extension_similarity   IF sector(candidate) ≠ sector(case)
```

This means cross-sector retrieval IS meaningful — PLTR-2022 (software) can retrieve AMD-2014 (semis) and MELI-2022 (intl/EM) on universal-core features alone (founder-in-place, cash-runway, margin/revenue trajectory, industry-tailwind). Sector extensions only fire as tie-breakers when sectors align.

**Layer 1 — Universal core similarity (Hamming over 6 features, equal-weight per Section 3 Q2 + Section 5 Q2):**

```yaml
universal_core_v0.1:
  hamming_features:
    founder_insider_stake_direction: 1/6   # ~0.167
    cash_runway:                     1/6
    founder_in_place:                1/6
    margin_trajectory:               1/6
    revenue_trajectory:              1/6
    industry_tailwind:               1/6
  Bayesian_shrinkage_lambda: 1.0   # full shrinkage to equal-weight at v0.1
```

**Layer 2 — Sector extension similarity (Hamming over sector-specific features, equal-weight within sector):**

Each sector's extension features get equal weight inside their sector bucket. Activated only when `sector(candidate) == sector(case)`. Examples:

```yaml
banks_extensions_v0.1:
  hamming_features:
    capital_ratio:          1/4
    uninsured_deposit_pct:  1/4
    dilution_at_trough:     1/4
    asset_quality:          1/4

energy_extensions_v0.1:
  hamming_features:
    net_debt_at_trough: 1/4
    hedge_book:         1/4
    reserve_quality:    1/4
    cost_curve:         1/4
```

(Same equal-weight + Bayesian-shrinkage approach per Section 3 Q2; sector-extension upgrade to optimized weights deferred to v0.5+ when N within each sector reaches ≥30.)

**Why two-layer (not unified, not sector-gated):**
- Unified single-schema forces sector-agnostic features only → loses cost-curve, property-tier, capital-ratio precision (real signal)
- Sector-gated retrieval (sector-match required) → PLTR-2022 (software) could never retrieve AMD-2014 (semis), losing strongest founder-led-recovery analogs
- Two-layer captures both: cross-sector retrieval on what's universally meaningful (Layer 1) + within-sector precision when sectors align (Layer 2)

### Drift monitoring + catalog hygiene (LOCKED — hybrid annual + event-driven)

Catalog gets new entries when:
- Watchlist name hits >50% drawdown AND outcome resolves (24+ months post-trough) — auto-add via Section 5 Q4 event-driven adds
- Operator-curated additions for historical cases not in initial 14-sector sweep

Catalog gets reclassified when:
- TBD case ages past 24 months and outcome confirms (TBD → SURVIVOR / NON-SURVIVOR)
- Materially-relevant new evidence emerges (Section 6 Q5 anchor-drift channels apply)

**Catalog hygiene cadence (hybrid):**

1. **Recently-touched marker (event-driven):** Whenever a watchlist name retrieves against a catalog case in active retrieval, that case is auto-marked `last_touched_in_retrieval: <date>`. Frequently-touched cases are implicitly validated by being load-bearing in real decisions.

2. **Annual full audit (Jan 1 each year):** Operator reviews 10% sample of catalog (~16 cases) for label accuracy + outcome reclassification. Stratification rule:
   - 50% sample drawn from cases NOT touched in retrieval in past 12 months (these are most likely stale)
   - 25% sample from TBD cases approaching 24-month age boundary
   - 25% random sample across remainder
   - Aligns with Section 5 Q4 annual signature audit cadence

3. **M-3-event-driven re-validation:** When a watchlist name's M-3 event triggers veto re-fire (Section 6 Q6 layer-3 re-fire policy), the cases retrieved as new top-3 matches auto-promote to "recently-touched" + queue for accuracy spot-check before next annual audit.

4. **Drift-detection escalation:** If annual audit finds ≥20% of sampled cases need reclassification, full catalog audit escalates (operator reviews remaining 90%); flagged as M-2 system-level event triggering /parameters-review.

Schema additions per case:
```yaml
case_metadata:
  last_touched_in_retrieval: 2026-09-15
  last_audit_date: 2026-01-01
  audit_findings: { label_changes: [], outcome_reclassifications: [] }
  audit_priority: low/medium/high   # high = not-touched-in-12mo OR TBD-near-24mo
```

**Why hybrid (not annual-only, not event-only):** annual floor catches silent drift on stale cases; event-driven captures the cases that matter most (load-bearing in actual retrievals); together they prevent the Yao et al. 2018 BB-pseudo-BMA+ failure mode (stale prior data + non-stationary world = silent calibration failure) that Section 3 Q2 already locked against in regime ensembles.

---

## Pre-2008 expansion (completed, 2026-04-29)

**Rationale:** Catalog v0.1 initial sweep skewed 2020-2024. Expansion adds pre-2008 cases for cross-regime breadth (regime-blind insurance, NOT regime forecast).

### Era 1 — Dot-com bust (2000-2002)

| Ticker | Peak DD | Outcome | Founder stake | Cash | Founder | Margin | Revenue | Tailwind | Layer-2 highlights |
|---|---|---|---|---|---|---|---|---|---|
| AMZN | -94% | SURVIVOR (multi-bag long-horizon) | flat (Bezos) | 12-24mo (2000 convert) | yes | improving | growing-decel | intact | engagement_decoupling=yes; concentration=very-low |
| PCLN | -99% | SURVIVOR (multi-100-bag post-Booking acq) | departed | <12mo | departed (Walker) | improving-post-pivot | growing-post-2003 | intact | post-pivot agency-model decoupling=yes |
| AKAM | -99.8% | SURVIVOR | departed (Lewin killed 9/11) | <12mo | replaced-by-competent (Leighton) | improving | growing | intact | moat=strengthening (consistent-hashing IP) |
| CSCO (2000-02) | -90% | DILUTED-SURVIVOR (25yr to reclaim peak) | flat (Chambers) | >24mo | yes | stable→improving | declining→growing | weakening (telco capex permanent reset) | moat=intact; cycle=trough |
| JDSU | -99% | NON-SURVIVOR-equivalent | decreasing | 12-24mo ($44.8B goodwill writedown) | replaced | deteriorating | declining-hard | reversed | moat=eroding (commoditized optics) |
| LU (Lucent) | -99.3% | DILUTED-SURVIVOR (merged Alcatel-Lucent 2006) | n/a | distressed (vendor-financing-blowup) | replaced | deteriorating ($16B loss) | declining | reversed | leverage=very-high |
| WCOM | -99.9% | NON-SURVIVOR (BK; fraud) | increasing-by-loan ($400M co-loan to Ebbers) | distressed | yes-then-fraud | fictitious | fictitious ($11B overstatement) | reversed | leverage=very-high; moat=none |
| GBLX | -99.5% | NON-SURVIVOR (BK; capacity-swap fraud) | decreasing aggressively ($420M Winnick + $900M execs) | distressed ($12.4B debt) | yes-pre-BK | deteriorating + circular | fictitious | reversed (fiber glut) | leverage=extreme; moat=none |
| Pets/Webvan/eToys (composite) | -98 to -100% | NON-SURVIVOR (all 3 BK <2yr post-IPO) | decreasing | <12mo at peak | yes-to-BK | structurally-negative | growing-fast (CAC-subsidy) | intact-secular but capital-mkts-reversed | engagement_decoupling=NO (price-promo driven) |
| HGSI | -95% | DILUTED-SURVIVOR (acq GSK 2012 below capital) | flat | >24mo | replaced | pre-revenue | pre-revenue | intact (genomics) but timing-reversed | pipeline=broad-thin |

### Era 2 — GFC non-financial (2007-2009)

| Ticker | Peak DD | Outcome | Founder stake | Cash | Founder | Margin | Revenue | Tailwind | Layer-2 highlights |
|---|---|---|---|---|---|---|---|---|---|
| SBUX (2007-08) | -82% | SURVIVOR (multi-bag) | Schultz return Jan-2008 | 12-24mo | replaced-by-competent (Schultz) | deteriorating→improving | declining (closed 600 stores) | weakening | brand=intact; repeat=holding |
| CC (Circuit City) | -100% | NON-SURVIVOR (Ch11 Nov-2008→liq) | dumped-exec-talent | <12mo | departed | deteriorating | declining | weakening + structurally-leapfrogged | brand=eroding (BBY-leapfrog) |
| LNT (Linens 'n Things) | -100% | NON-SURVIVOR (Ch11 May-2008→liq) | Apollo-LBO-controlling | <12mo | PE-installed | deteriorating | declining | reversed | leverage=distressed (LBO debt) |
| CAT (2007-09) | -68% | SURVIVOR (full recovery 2010-11) | flat (Owens) | >24mo | flat | deteriorating | declining | reversed→recovering (China stim) | backlog=contracted (LTSA + dealer); leverage=healthy IG |
| DE (2007-09) | -58% | SURVIVOR | flat | >24mo | flat | deteriorating | declining | weakening (ag held better) | backlog=contracted; leverage=healthy IG |
| F (Ford 2008-09) | -94% | SURVIVOR (no Ch11 / no TARP) | Ford-family aligned; Mulally hired-2006 | 12-24mo (pre-funded $23.6B Nov-2006) | replaced-by-competent (Mulally) | deteriorating→improving | declining | reversed | production=declining→stabilizing; capital_structure=public-only-pre-funded |
| LEN (Lennar 2005-09) | -88% | SURVIVOR (full recovery 2013) | Miller-family aligned (insider buying) | 12-24mo | yes (Stuart Miller) | deteriorating | declining | reversed | lots=tier-1+JV-Rialto-distressed-arm; debt-wall=extended |
| BZH (Beazer 2005-09) | -98% | DILUTED-SURVIVOR (massive equity issuance) | controlling-fragile (DOJ probe) | <12mo | replaced (mortgage-fraud) | deteriorating | declining | reversed | lots=tier-2/3-entry; debt-wall=near (covenant-breaches) |
| LVS (Las Vegas Sands 2007-09) | -99% | SURVIVOR (multi-bag — Macau/Singapore engine) | Adelson-family $1B+ rescue equity Nov-2008 | <12mo→saved | yes (Adelson) | deteriorating | declining | reversed→recovering (Macau intact) | occupancy=LV~78%/Macau-holding; brand=premium |
| MGM (2008-09) | -95% | DILUTED-SURVIVOR (Dubai World JV CityCenter rescue) | Kerkorian-flat-aligned + Dubai 50/50 | <12mo→rescued | yes (Murren) | deteriorating | declining | reversed | leverage=~9x-distressed; brand=A-tier |
| GGP (General Growth 2007-09) | -99% | DILUTED-SURVIVOR (Ch11 Apr-2009; Ackman-led recap) | Bucksbaum-family wiped (margin loans) | <12mo (debt-wall) | replaced post-BK | deteriorating | declining | weakening (A-mall not structural) | property_tier=A; debt-wall=$1.2B-Nov-2008 |

### Era 3 — 1989-1992 (deep recession + S&L + LBO fallout)

| Ticker (era) | Peak DD | Outcome | Founder/insider | Cash | Founder | Margin | Revenue | Tailwind | Layer-2 highlights |
|---|---|---|---|---|---|---|---|---|---|
| Citicorp (1990-91) | -65% | SURVIVOR | Reed-fought-board | distressed-liq | flat (Reed retained) | deteriorating→improving | flat | reversed (CRE+LDC) | capital_ratio=<4% Tier-1 (sub-reg); dilution=massive (Alwaleed $590M then $4.5B) |
| BankAmerica (1985-87 + 1990) | -70% | SURVIVOR | Clausen-returned | stressed | replaced-by-competent (Clausen return) | deteriorating→improving | declining→growing | reversed→intact | capital_ratio=weak; asset=LDC+ag-impaired |
| Bank of New England (1989-91) | -100% | NON-SURVIVOR (FDIC) | departed | distressed-deposit-flight | departed (Hancock fired) | deteriorating | declining | reversed-NE-CRE | capital_ratio=insolvent; uninsured-flight |
| HomeFed Bank (1988-92) | -100% | NON-SURVIVOR | departed | deposit-flight | departed | deteriorating | declining | reversed | sub-regulatory; CA-CRE |
| CenTrust S&L (1988-90) | -100% | NON-SURVIVOR | Paul-indicted | distressed | departed-fraud | deteriorating | declining | reversed-S&L-crisis | insolvent + junk-bond + fraud |
| R.H. Macy & Co (1988-92) | -100% | NON-SURVIVOR | LBO-insiders-wiped | distressed | departed (Finkelstein) | deteriorating | declining | reversed (89-91 recession) | leverage=distressed (Finkelstein LBO + Bullock's bolt-on); brand=intact-but-stretched |
| Federated Dept Stores (Campeau 1988-90) | -100% (Campeau equity) | NON-SURVIVOR (Ch.11 1990) → reorg-survivor | Campeau-wiped | distressed | replaced (post-BK) | deteriorating | flat | reversed | leverage=distressed (Bloomingdale LBO debt) |
| RJR Nabisco (post-KKR 1989-92) | -50% PIK | DILUTED-SURVIVOR | KKR-stayed | distressed-PIK-reset | replaced (Gerstner→Harper) | stable | flat | weakening (tobacco-litig) | leverage=distressed-PIK |
| Pan Am (1989-91) | -100% | NON-SURVIVOR | depleted | distressed (Lockerbie + Gulf War) | multiple-failed | deteriorating | declining-secular | reversed | route=premium-intl-but-irrel-domestic; labor=high-legacy |
| Eastern Air Lines (1988-91) | -100% | NON-SURVIVOR | Lorenzo-extracted-via-Texas-Air | distressed | departed (Lorenzo discredited) | deteriorating | declining | reversed | labor=hostile (IAM strike '89) |
| Continental Airlines (1990 2nd Ch.11) | -95% | DILUTED-SURVIVOR | Lorenzo-out | distressed | replaced (Bonderman-led-recap '93) | deteriorating→improving | declining→growing | reversed | labor=improving-post-strike |
| TWA (1992 1st Ch.11) | -95% | DILUTED-SURVIVOR (later BK 2001) | Icahn-extracted | distressed (Icahn LBO 1988) | departed (Icahn) | deteriorating | declining | reversed | route=weakening; labor=high |
| Northwest Airlines (1992-93) | -90% | SURVIVOR | new-PE (Checchi-Wilson + KLM) | distressed→restructured | retained-Checchi | deteriorating→improving | declining→growing | reversed→intact | route=strong (Pacific); wage-concession-1993 |
| Olympia & York (1992) | -100% | NON-SURVIVOR | Reichmann-wiped | distressed (Canary Wharf cross-collat) | departed | deteriorating | declining | reversed (UK CRE bust) | property=A-quality-but-illiquid; concentration=London+Toronto+NYC |
| Drexel Burnham Lambert (1990) | -100% | NON-SURVIVOR | Milken-indicted | distressed (junk-inventory unhedged) | departed (Milken/Joseph) | deteriorating | collapsed | reversed (junk-mkt frozen post-DOJ) | moat=leapfrogged (junk-mkt frozen) |
| IBM (1987-93) | -75% | SURVIVOR | Akers-departed→Gerstner | healthy (cash-cow services) | replaced-by-competent (Gerstner '93) | deteriorating→improving | flat-then-growing | reversed (mainframe) → reset (services) | platform=mainframe-leapfrogged-by-PC; services-pivot intact |
| Compaq (1990-91) | -80% | SURVIVOR | Canion-replaced | healthy | replaced-by-competent (Pfeiffer) | deteriorating→improving | declining→growing | weakening→intact | moat=PC-cost-leader-post-reset |
| DEC (1989-98) | -90% | NON-SURVIVOR (acq Compaq '98) | Olsen-departed-too-late | stretched | replaced-too-late (Palmer) | deteriorating | declining-secular | structural-decline | platform=mini-leapfrogged; Alpha-too-late |
| Maxwell Communications (1991) | -100% | NON-SURVIVOR | Maxwell-fraud-died-1991 | distressed (£3B+ pension-raid) | departed (death) | deteriorating | declining | reversed | fraud-impaired |

### Era 4 — 1973-1982 stagflation

| Ticker | Peak DD | Outcome | Founder/insider | Cash | Founder | Margin | Revenue | Tailwind | Layer-2 highlights |
|---|---|---|---|---|---|---|---|---|---|
| Polaroid (1972-74) | -91% | NON-SURVIVOR (eventual BK 2001) | flat-then-departed | healthy-at-trough | yes (Land) | deteriorating-slow | flat-decline | weakening (then digital-leapfrog 1990s+) | brand=eroding-slowly; platform=vulnerable-future |
| Avon Products (1973-74) | -87% | SURVIVOR (multi-decade slow decline) | flat | healthy | flat | deteriorating | flat | weakening (women entering workforce → DTC model strained) | distribution=structurally-impaired; brand=stable-mass |
| IBM (1973-74) | -58% | SURVIVOR (recovered fully late-70s) | flat | healthy (fortress) | flat | stable | growing | intact (mainframe dominance) | platform=dominant-incumbent; leverage=conservative |
| Eastman Kodak (1973-74) | -65% | SURVIVOR-then-NON-SURVIVOR (BK 2012) | flat | healthy | flat | stable | growing | intact-1970s; will-reverse-1990s | platform=will-be-disrupted-digital; brand=peak-then-erosion |
| MCD/DIS/KO (composite 1973-74) | -65 to -80% | SURVIVOR (all multi-bag within 5-7 years) | flat | healthy | flat | stable→improving | growing | weakening (recession) | brand=compounding; leverage=conservative; FCF=intact |
| Chrysler (1976-81) | -95% near-BK | SURVIVOR (government-rescued $1.5B loan guarantees 1979 + Iacocca turnaround + K-car) | depleted-then-restored | distressed→saved | replaced-by-competent (Iacocca) | deteriorating→improving | declining→growing | reversed | production=collapsing→recovering; government_rescue=YES (jobs/strategic) |
| International Harvester (1979-85) | -85%+ | NON-SURVIVOR (broken up; ag biz sold to Tenneco/J.I. Case 1985 → Navistar truck-only) | depleted | distressed | flat-failed | deteriorating | declining | reversed (172-day UAW strike + farm-collapse) | backlog=evaporating; leverage=fatal; government_rescue=NO |
| Braniff International Airways (1981-82) | -100% | NON-SURVIVOR (BK May 1982) | depleted | distressed (post-deregulation expansion + fuel-shock + fleet-leverage) | flat-to-BK | deteriorating | declining | reversed | leverage=fatal; deregulation-shock |
| W.T. Grant (1975-76) | -100% | NON-SURVIVOR (BK 1976; 2nd-largest US BK at the time) | depleted | distressed (subprime-credit-extension blew working-capital) | flat-to-BK | deteriorating | declining | reversed | leverage=fatal; brand=undifferentiated; location=B-malls |
| A&P (1970s decline) | -severe | SURVIVOR-then-NON-SURVIVOR (BK 2010, 2015) | flat | stretched | flat | deteriorating | declining | weakening (suburban-flight + WEO price-war 1972 failure) | location=urban-legacy-poor; brand=fading; distribution=impaired |

---

## 3-LLM iterative-consensus validation (LOCKED — priority-subset before v0.1 launch)

Section 5 Q3 mandates 3-LLM iterative-consensus pipeline with 5-iteration cap until HIGH confidence for catalog feature extraction. The current catalog annotations are single-subagent-pass (initial sweep + expansion), which does NOT meet that bar.

**Resolution: priority-subset 3-LLM consensus pass before v0.1 launch + lazy validation for tail.**

### Priority subset (must validate before launch)

**Calibration test set (15 cases) — airtight required:**
- 5 SURVIVOR canonical: NVDA-2008, AMD-2014, NFLX-2011, MELI-2022, CVNA-2022
- 5 NON-SURVIVOR canonical: BBBY-2023, FSR-2024, CHK-2020, NOK-2012, OPI-2024
- 5 TBD/edge cases: PLTR-2022 (motivating case), MRNA-2024, SLG-2023, INTC-2024, RIVN-2024

**Top 30 canonical archetypes — load-bearing for veto authority:**
- Founder-led cyclical-trough survivors: AMD-2014, NVDA-2008, MU-2016, AMAT-2008, Compaq-1991
- Replaced-by-competent-operator survivors: GE-2018-Culp, AMD-2014-Su, IBM-1993-Gerstner, SBUX-2008-Schultz, NKE-2024-Hill, TPR/Coach-2014-Luis
- Pre-funded liquidity survivors: Ford-2008-Mulally, NWA-1992
- Government-rescue survivors: Chrysler-1979-Iacocca, OXY-2020-Buffett, Citicorp-1991-Alwaleed
- Brand-led recovery: Crocs-2008-Rees, MELI-2022, Coach-2014, AAPL-1997-equiv (if added in audit)
- Multi-bag-from-trough internet survivors: AMZN-2001, eBay-2001, PCLN-2002, AKAM-2002
- Capacity-glut/leverage non-survivors: Lucent-2002, GBLX-2002, JDSU-2002, Pan-Am-1991, IH-1985
- Top-of-cycle debt-financed M&A non-survivors: Peabody-2016, Olympia-York-1992, Macy's-Finkelstein-1992
- Fraud-impaired non-survivors: WCOM-2002, Drexel-1990 (overlap with fraud catalog — confirm)
- Platform-leapfrog non-survivors: Sun-2008, Nokia-2012, BlackBerry-2013, DEC-1998, Polaroid-eventual
- A/B-tier divergence: SPG-2020 vs CBL-2020 vs WPG-2021

(Final 30-case list selected by operator; above is suggestive coverage of the 11 archetype clusters.)

### Validation pipeline (per case, per feature)

Per Section 5 Q3:
1. 3 LLMs (e.g., 3 independent Sonnet runs OR Sonnet + Opus + cross-check) extract feature value with verbatim source quote
2. Compare outputs:
   - Unanimous → record value with `consensus: HIGH`
   - 2/3 agreement → run iteration 2 with surfaced disagreement; up to 5 iterations
   - Persistent disagreement after 5 iterations → flag `consensus: LOW`, surface to operator for manual decision
3. Each feature carries:
   ```yaml
   feature: founder_in_place
   value: departed
   consensus: HIGH
   iterations_to_consensus: 1
   verbatim_quote: "..."
   source_id: "..."
   validated_at: 2026-04-30
   ```

### Lazy validation for tail (non-priority ~115 cases)

Tail cases stay in catalog with single-subagent-pass annotations marked `validation_status: pending`. **First time** a tail case appears in active retrieval (any watchlist name retrieves it in top-N), trigger 3-LLM consensus pass on that case before retrieval result is committed to veto evaluation.

Mechanics:
- If consensus pass passes (HIGH on all features) → case promotes to `validation_status: validated`; retrieval proceeds
- If consensus pass surfaces material disagreement → case flagged for operator review; retrieval falls back to top-N excluding this case for current event; case enters validation queue

This front-loads rigor on the load-bearing path (calibration + canonical) and amortizes the long tail across actual usage. Maps to Section 5 Q4 event-driven mechanics.

### Cost estimate

- Priority subset: ~45 cases × ~10 universal-core + sector-extension features × 3 LLMs × up-to-5 iterations ≈ 6,750 calls (bounded; ~$50-150 depending on Sonnet/Opus mix)
- Lazy tail: marginal — only fires on first-retrieval per case
- Annual audit per Pushback #6 catalog hygiene: ~16 cases × full feature set re-validation per year ≈ ~2,400 calls/year

### Pre-launch gate (updated)

Before v0.1 veto authority enables:
1. Priority subset (~45 cases) all show `consensus: HIGH` on universal-core features (sector-extensions can be MEDIUM if necessary)
2. Calibration test set (15 cases) shows ≥80% archetype-coverage agreement
3. Canonical SURVIVOR/NON-SURVIVOR test cases retrieve ≥2 same-archetype matches in 90% of cases
4. Operator explicit sign-off on priority-subset validation results

---

## Updated v0.1 status (post-expansion)

**Total cases: ~160** (110 initial + ~50 pre-2008 expansion, with some overlap)
- Recent (2020-2024): ~85
- 2014-2016 era: ~10
- 2007-2009 GFC: ~22
- 2000-2002 dot-com: ~10
- 1989-1992: ~19
- 1973-1982: ~10

**Cycle/era coverage now substantially more balanced.** Active retrieval pool (excluding TBD) approximately ~110-120 cases.

**Key archetypes now in catalog:**
- Founder-led cyclical-trough survivor (NVDA-2008, AMD-2014, IBM-1973-74)
- Pre-funded liquidity survivor (Ford-2008, NWA-1992)
- Government-rescue survivor (Chrysler-1979, OXY-2020)
- Brand-led recovery (Crocs-2008, SBUX-2008, Coach-2014)
- Replaced-by-competent operator survivor (IBM-Gerstner, AMD-Su, GE-Culp, Compaq-Pfeiffer)
- Multi-bag-from-trough internet survivor (AMZN, eBay, PCLN, AKAM)
- Diluted-survivor banks (Citi-1991, Citi-2009, BofA-2009, AIG-2009, NYCB-2024)
- Capacity-glut/leverage non-survivor (LU, GBLX, JDSU, Pan Am, IH)
- Top-of-cycle debt-financed M&A non-survivor (Peabody-Macarthur, Olympia & York, Macy's-Finkelstein-LBO, JDSU-E-Tek/SDL)
- Fraud-impaired non-survivor (WCOM, Drexel, Maxwell, Centrust)
- Platform-leapfrog non-survivor (Sun, Nokia, BlackBerry, DEC, Polaroid-eventual, Kodak-eventual)
- A/B-tier asset-class divergence (SPG-2020 A-mall vs CBL/PEI/WPG B/C-mall; LEN-2008 tier-1 vs Beazer tier-2/3)

---

## v0.1 status

**Total cases: ~110 (initial sweep), expansion sprint pending**
- Tech/SaaS: 9
- Semis/hardware: 10
- Consumer-discretionary: 12
- Consumer-brands: 12
- Fintech: 10
- Healthcare/biotech: 9
- Industrial: 10
- Energy: 10
- Comms/media: 11
- International/EM: 10
- EV/autos: 8
- REITs: 12
- Recent-IPO/SPAC: 11
- Crypto-adjacent: 10
- Financials/banks: 10

**Outcome distribution:**
- SURVIVOR: ~38
- DILUTED-SURVIVOR: ~5
- NON-SURVIVOR: ~37
- TBD: ~30

**Coverage check:**
- ✓ All major sectors represented
- ✓ Both bankruptcies and recoveries documented
- ✓ Multiple decades covered (2000s, 2008-09, 2014-16, 2020, 2021-23 all represented)
- ✓ Domestic + international
- ✓ Founder-led + professional-management
- ✓ Public + de-SPAC + receivership outcomes

**Ready for: ** Section 6 Q6 (d') counterfactual VETO authority pipeline integration. Pre-launch validation: run mechanical retrieval against 15 known cases (operator-annotated expected matches), verify NDCG@3 ≥0.7, then enable veto authority.
