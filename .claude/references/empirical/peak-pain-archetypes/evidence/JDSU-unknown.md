## JDSU-2002 — peak-pain forensic evidence

### MEASUREMENT TIMEPOINT (operator-locked for feature extraction)

All universal-core feature values below are measured at **fiscal-year close FY2002 (year ended June 30, 2002)** — the trough fiscal year for JDS Uniphase Corporation. The case period (2000-02) describes peak-to-trough; lock to FY2002 close (calendar mid-2002), not the multi-year recovery / split into Lumentum + Viavi (2015) which is downstream archetype-context only.

### Universal-core feature anchors (use these exact spec values)

| Feature | Canonical value (FY2002 lens) | Source |
|---|---|---|
| `founder_in_place` | **departed** | Original Uniphase founder Kevin Kalkhoven stepped down as CEO in 2000; by FY2002 close Jozef Straus (JDS FITEL co-founder) was Chairman/CEO, but the catalog locks "departed" because the *Uniphase-side* founder anchor is gone |
| `founder_insider_stake_direction` | **departed** | Mirrors founder_in_place departure; Kalkhoven's beneficial ownership not retained at the relevant peak-to-trough lens |
| `cash_runway` | **distressed** | Massive goodwill impairments + sustained operating losses; though absolute cash exists, the magnitude of cumulative impairments ($5.98B FY2002 + $50.09B FY2001) signals balance-sheet distress |
| `margin_trajectory` | **deteriorating** | 10-K Item 7 (Section E) — net sales -66% y/y, deep operating losses, contract cancellation revenue propping up GAAP |
| `revenue_trajectory` | **declining** | 10-K verbatim: "Net sales of $1,098.2 million in fiscal 2002 represents a decrease of $2,134.6 million, or 66%, from net sales of $3,232.8 million in fiscal 2001" |
| `industry_tailwind` | **structural-decline** | 10-K verbatim "severe decline in overall demand for new fiberoptic networks and the components and modules used therein" — telecom optical glut post fiber overbuild was secular, not cyclical |

---

## A. Industry shock & operational stress  (industry_tailwind = structural-decline)

10-K verbatim: "severe decline in overall demand for new fiberoptic networks and the components and modules used therein. During 2001 and continuing into 2002, our telecommunications systems manufacturing customers worked to reduce their inventories of components and modules."

The 2000 fiber overbuild and post-bubble carrier capex collapse left optical-component inventories that took years to clear. This is a **structural-decline** call (not cyclical "weakening") because: (a) the over-capacity in long-haul fiber persisted through the 2000s, (b) JDSU's end-market never re-attained FY2001 peak revenues at the legacy product mix, and (c) the eventual 2015 break-up into Lumentum + Viavi confirmed the long-haul commodity-component business was structurally impaired.

## B. Balance sheet & cash position  (cash_runway = distressed)

10-K verbatim: "impairment charges of $5,979.4 million in fiscal 2002 and $50,085.0 million in fiscal 2001" — cumulative ~$56B in goodwill/intangibles wiped (vs FY2002 net sales of $1.1B). While absolute cash on hand was non-trivial, the scale of value destruction + sustained losses makes the cash position **distressed** rather than the looks-like-it accounting cash balance. The $43.3M IBM optical-transceiver acquisition revenue contribution and $44.9M of contract-cancellation receipts indicate revenue quality stress.

## C. Founder/insider behavior  (founder_in_place = departed; founder_insider_stake_direction = departed)

10-K verbatim: "Jozef Straus, Ph.D. — Chairman and Chief Executive Officer". Straus co-founded JDS FITEL in 1981 and became JDSU CEO upon the 1999 merger of Uniphase + JDS FITEL. The Uniphase-side founder Kevin Kalkhoven (who built the company through the late-1990s acquisition spree) stepped down as CEO in 2000 — the era-specific catalog note locks this case to **founder_in_place = departed** to reflect the Uniphase founder departure that preceded the trough. Kalkhoven fully exited by 2003.

## D. Margin & revenue trajectory  (margin_trajectory = deteriorating; revenue_trajectory = declining)

10-K verbatim: "Net sales of $1,098.2 million in fiscal 2002 represents a decrease of $2,134.6 million, or 66%, from net sales of $3,232.8 million in fiscal 2001."

Operating performance further deteriorated by impairment charges of $187.3M (Nortel) + $13.9M (ADVA) for receivables, layered on FY2001's $511.8M (Nortel) + $744.7M (ADVA). Revenue mix included $44.9M cancellation revenue (one-off) — true demand worse than headline. **revenue_trajectory = declining** and **margin_trajectory = deteriorating** are unambiguous.

## E. Strategic / structural context (NOT a universal-core feature)

The 1999 Uniphase + JDS FITEL merger and rapid roll-up (OCLI 2000, E-TEK 2000, SDL 2001) created enormous goodwill at peak valuations; FY2001's $50B impairment + FY2002's $5.98B impairment marked the largest goodwill write-downs in tech history at that time. The structural overhang persisted through the 2010s, culminating in the 2015 Lumentum/Viavi spin-out — confirming the NON-SURVIVOR catalog classification (corporate identity dissolved).

## Sources

- EDGAR 10-K FY2002 (JDS Uniphase): https://www.sec.gov/Archives/edgar/data/912093/000089161802004336/f84311e10vk.htm — filed 2002-09-17
- Era-specific note: Kalkhoven CEO departure (2000), industry context per 10-K Item 7 MD&A
- Successor entities: Lumentum Holdings (NASDAQ: LITE) + Viavi Solutions (NASDAQ: VIAV, CIK 912093) post 2015 split

## Quality notes

- All financial line-items verbatim from FY2002 10-K — HIGH primary-source confidence.
- Polygon API does not cover pre-2003 daily price data; drawdown stipulation (-98%) per case-brief; cross-checked against secondary post-mortems.
- Period analyst/press transcripts not recovered in primary source; 10-K Item 7 demand-collapse language is strongest contemporary verbatim.

## Polygon-sourced corroboration (2026-04-30 augment)

### Drawdown math
- 0 rows for window 2000-01-01 → 2003-12-31 — Polygon plan returns NOT_AUTHORIZED for pre-2022 aggregates. JDSU also split into LITE+VIAV in 2015, so the JDSU ticker itself terminates pre-2022 coverage window regardless. Drawdown stipulation stands per case-brief.

### Period news
- 0 rows for window 2002-01-01 → 2003-06-30 — Polygon news API returns empty (Benzinga partnership coverage starts ~2018, well after this case window).

### Source
- Polygon Aggregates v2 (NOT_AUTHORIZED): https://api.polygon.io/v2/aggs/ticker/JDSU/range/1/day/2000-01-01/2003-12-31
- Polygon Reference News (0 results): https://api.polygon.io/v2/reference/news?ticker=JDSU&published_utc.gte=2002-01-01&published_utc.lte=2003-06-30

### Polygon depth-pass (2026-04-30)

**JDSU delisted reference** (Polygon /v3/reference/tickers?search=JDSU&active=false): "JDS UNIPHASE CANADA LTD COMMON STOCK (NEW)"; type=null; active=false; **delisted_utc 2015-08-04T04:00:00Z**. Polygon record corroborates the Aug-2015 split into Lumentum (LITE) + Viavi Solutions (VIAV). Companion record "JDSUD" (sub-line) delisted 2006-11-14. The JDSU ticker is therefore Polygon-recorded as terminated on 2015-08-04, providing a forensically auditable end-date for the legacy entity.

**JDSU corporate-action: 8:1 split 2006-10-17** (Polygon /v3/reference/splits?ticker=JDSU): "ratio: 8:1, date: 2006-10-17". This is a critical depth-pass datapoint missing from round 1: JDSU executed a **1-for-8 REVERSE split in Oct-2006** (Polygon notation 8:1 = 8 old → 1 new), four years after the trough. The famed "JDSU went from $150 to $2" magnitudes that pervade dot-com retrospectives must be quoted carefully because the post-2006 prices reflect the 8:1 reverse-split. The trough-lens MEASUREMENT TIMEPOINT (FY2002) is pre-reverse-split; case-brief drawdown -98% is thus the unadjusted magnitude. Polygon record makes the reverse-split visible.

**Successor entities still active:**
- Viavi Solutions (VIAV) (Polygon /v3/reference/tickers/VIAV): CIK 0000912093, type=CS, active=true, list_date 1993-11-01 (inherited the original JDSU CIK + listing date — VIAV is the "rump-network-test" continuation), market_cap ~$10.0B, share_class_shares_outstanding 231,389,345. SIC: SEMICONDUCTORS & RELATED DEVICES. Recent aggs (2021-2024): max close $17.94, min $6.66 — diluted-survivor profile.
- Lumentum (LITE) (Polygon /v3/reference/tickers/LITE): CIK 0001633978, type=CS, active=true, list_date 2015-07-23 (the spin-out date), market_cap ~$56.5B, shares_outstanding 71,400,000. SIC: COMMUNICATIONS EQUIPMENT, NEC. Recent aggs: max close $107.61, min $36.07 — Lumentum is the strong-survivor that captured the AI-optical-transceiver tailwind, current market cap >5x VIAV.
- VIAV financials (Polygon /vX/reference/financials, 12 periods): Q2-FY2026 (end 2025-12-27) revenues $369.3M, net loss $(48.1)M; trending revenue growth + occasional loss. LITE financials TTM (end 2025-12-27): revenues $2.11B, net income $251.6M — solidly profitable.
- VIAV splits: also records the 2006-10-17 8:1 (inherited via successor accounting). LITE: 0 splits. VIAV: 0 dividends. LITE: 3 records of 2003-2004 dividends ($0.04 quarterly) inherited from pre-spin JDSU.

### Source (depth-pass)
- Polygon Reference (JDSU delisted): https://api.polygon.io/v3/reference/tickers?search=JDSU&active=false → delisted_utc 2015-08-04
- Polygon JDSU Splits (8:1 reverse): https://api.polygon.io/v3/reference/splits?ticker=JDSU → 2006-10-17
- Polygon Reference (VIAV survivor): https://api.polygon.io/v3/reference/tickers/VIAV
- Polygon Reference (LITE survivor): https://api.polygon.io/v3/reference/tickers/LITE
- Polygon VIAV Aggs: https://api.polygon.io/v2/aggs/ticker/VIAV/range/1/day/2021-05-01/2024-12-31?adjusted=true (923 bars, max $17.94 / min $6.66)
- Polygon LITE Aggs: https://api.polygon.io/v2/aggs/ticker/LITE/range/1/day/2021-05-01/2024-12-31?adjusted=true (923 bars, max $107.61 / min $36.07)
- Polygon VIAV Financials: https://api.polygon.io/vX/reference/financials?ticker=VIAV&limit=12
- Polygon LITE Financials: https://api.polygon.io/vX/reference/financials?ticker=LITE&limit=12
