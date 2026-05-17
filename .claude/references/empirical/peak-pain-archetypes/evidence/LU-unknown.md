## LU-2006 — peak-pain forensic evidence

### MEASUREMENT TIMEPOINT (operator-locked for feature extraction)

All universal-core feature values below are measured at **fiscal-year close FY2002** (Lucent fiscal year ends Sept 30; FY2002 ended Sept 30, 2002 — the dot-com trough year for telecom-equipment names). Feature extraction uses the FY2002 10-K (filed 2002-12-12, accession 0000950117-02-003045) plus its Exhibit 13 (financial statements). The FY2003-2006 stabilization arc and Dec 2006 Alcatel-Lucent merger are downstream context — the case_id "LU-2006" denotes the multi-year arc; the trough-year measurement timepoint is FY2002.

### Universal-core feature anchors (use these exact spec values)

| Feature | Canonical value (FY2002 lens) | Verbatim quote source |
|---|---|---|
| `founder_in_place` | **departed** | Bell Labs/AT&T heritage entity; McGinn out Oct 2000; Schacht→Russo (Section D) |
| `founder_insider_stake_direction` | **departed** | No founder; legacy spin (1996 IPO from AT&T) (Section D) |
| `cash_runway` | **distressed** | $4.42B cash + securities vs $11.75B FY02 net loss; pension/debt overhang (Section B) |
| `margin_trajectory` | **deteriorating** | Gross margin 12.6% FY02 vs 9.7% FY01 vs 40.5% FY00 (Section E) |
| `revenue_trajectory` | **declining** | Revenue $12.32B FY02 vs $21.29B FY01 vs $28.90B FY00 = -42% y/y (Section E) |
| `industry_tailwind` | **structural-decline** | Service-provider capex -40%; bandwidth glut multi-year (Section A) |

---

## A. Industry shock & operational stress  (industry_tailwind = structural-decline)

Ex-13 verbatim: "service provider capital spending declined by about 40%. Additional capital spending reductions may occur during 2003. Reasons for this reduction include the general economic slowdown, network overcapacity, customer bankruptcies, network build-out delays and limited capital availability."

10-K Risk Factors verbatim: "We rely on a few large customers to provide a substantial portion of our revenues. These customers include: AT&T, AT&T Wireless, BellSouth, Cingular, SBC, Sprint, Verizon and Verizon Wireless." Several of these customers cut capex 40-60% in 2001-2002; CLEC customer base (NorthPoint, Rhythms, Winstar) entered bankruptcy. The fiber overcapacity from 1998-2000 build-out (Global Crossing, 360networks, Williams Communications) created a multi-decade glut — the "structural-decline" classification is appropriate: this was not a 12-month cyclical reset but a 5-7+ year unwind of a capex bubble.

## B. Balance sheet & cash position  (cash_runway = distressed)

Ex-13 verbatim: "Cash and cash equivalents $2,894 [million]" + "Short-term investments $1,526" at Sep 30 2002 = ~$4.42B liquidity. FY02 net loss $11.75B (vs FY01 $16.20B). Even backing out non-cash impairments and restructuring charges ($2.32B FY02 + $11.4B FY01), cash burn from operations was significant.

10-K Risk Factors verbatim: "We have substantial cash requirements in connection with our operations, capital expenditures, restructuring programs, debt service obligations, pension and post-retirement obligations…"

10-K Risk Factors verbatim: "we may have less liquidity and a more limited access to the capital markets as a result of our credit ratings than some of our competitors. Therefore, these competitors may be better positioned to withstand a prolonged downturn in the industry or in the economy as a whole."

10-K verbatim: "in fiscal 2002 we recorded a $2.9 billion charge to equity on account of our employee benefit plans" — pension liability unfunded position became material. Debt-rated junk during this window. The catalog row "distressed" anchors here: liquidity sufficient for ~24 months at then-current burn but pension/debt overhang plus dependency on union concessions (negotiations through May 31, 2003) made the going-concern question real.

## C. Strategic context (NOT a universal-core feature; archetype-matching only)

10-K verbatim: "On September 30, 2002, we had approximately 47,000 employees." (Down from peak ~123,000 FY00 — cumulative ~62% workforce reduction during the trough.) Total restructuring charges aggregated $13.7B across FY01-02. Russo's strategy: focus on tier-1 service providers (AT&T/Verizon/SBC) + Bell Labs research + targeted gross-margin recovery to mid-30%. The Dec 2006 Alcatel-Lucent merger crystallized the "diluted-survivor" outcome: Lucent shareholders received 0.1952 ALU ADRs per LU share, locking in massive permanent dilution vs the 1999 peak.

## D. Founder/insider behavior  (founder_in_place = departed; founder_insider_stake_direction = departed)

Lucent Technologies was spun off from AT&T in April 1996 (IPO), inheriting Bell Labs (founded 1925) — there is no individual founder to track. Henry Schacht (former AT&T Vice Chairman) was first CEO 1996-1997; Rich McGinn 1997-Oct 2000 (forced out after Q4 FY2000 miss); Schacht returned as interim CEO/Chairman Oct 2000; Patricia Russo became CEO Jan 2002.

10-K verbatim: "Patricia F. Russo 50 President and Chief Executive Officer 01 / 02… Ms. Russo held executive officer positions with us from our formation in 1996 until August 2000. Prior to becoming our President and Chief Executive Officer in January 2002, Ms. Russo was Chairman of Avaya Inc. from December 2000 to January 2002 and President and Chief Operating Officer of Eastman Kodak Company from January 2001 to January 2002."

→ **founder_in_place = "departed"** (legacy entity; original CEO McGinn departed pre-trough; spec domain ["yes","departed","replaced-by-competent"] — "departed" anchors here because there is no founder to "replace by competent" — Russo is a returning insider, not a founder-substitute).

→ **founder_insider_stake_direction = "departed"** (no individual founder reference point).

## E. Margin & revenue trajectory  (margin_trajectory = deteriorating; revenue_trajectory = declining)

Ex-13 verbatim: "Years ended September 30, 2002 2001 2000… Total revenues $ 12,321 $ 21,294 $ 28,904… Gross margin $ 1,552 $ 2,058 $ 11,714 Gross margin rate 12.6 % 9.7 % 40.5 %."

→ Revenue: $12.32B FY02 vs $21.29B FY01 vs $28.90B FY00 — **-42% y/y FY02**, -26% y/y FY01. Cumulative -57% from FY00 peak.

→ **revenue_trajectory = "declining"** unambiguously.

Gross margin rate FY02 12.6% vs FY01 9.7% vs FY00 40.5% — note FY02 actually improved sequentially over FY01's collapse. Operator interpretation per spec ["improving","stable","deteriorating"]: the 28-percentage-point GM collapse from FY00 to FY01 dominates the trough-year lens; FY01→FY02 +2.9pp recovery is from a deeply impaired base. Anchor at FY02-vs-FY00 framing → **margin_trajectory = "deteriorating"** (compressed from 40.5% → 12.6% over two years).

Operating loss FY02 $(6,979)M vs FY01 $(19,029)M; net loss FY02 $(11,753)M vs FY01 $(16,198)M.

## Sources

- EDGAR 10-K for fiscal year ended Sept 30, 2002 (Lucent Technologies Inc.), accession 0000950117-02-003045, filed 2002-12-12: https://www.sec.gov/Archives/edgar/data/1006240/000095011702003045/a33915.htm — body of 10-K (Risk Factors, Item 10 Officers).
- Exhibit 13 (consolidated financial statements + MD&A): https://www.sec.gov/Archives/edgar/data/1006240/000095011702003045/ex13.htm — Selected Financial Data, Revenue/Gross Margin tables, Cash/Restructuring detail.
- CIK 1006240 (Lucent Technologies Inc. → renamed Alcatel-Lucent USA Inc. post-Dec 2006 merger).

## Quality notes

- Revenue, gross margin, cash position, employee count, and CEO transition language verbatim from FY2002 10-K + Ex-13 — HIGH primary-source confidence.
- Drawdown stipulation -99% peak (Dec 1999 ~$84) → trough (Oct 2002 ~$0.55) per case-brief / MacroTrends.
- "Distressed" cash_runway aligns with the catalog stipulation; technically Lucent had >12-month cash but pension/debt/credit-rating constraints + going-concern-adjacent risk language put it in the distressed category.
- "diluted-survivor" outcome label is FY2006 context (Alcatel-Lucent merger); the FY2002 trough-lens features are what matter for archetype matching.

## Polygon-sourced corroboration (2026-04-30 augment)

### Drawdown math
- 0 rows for window 2001-01-01 → 2006-12-31 — Polygon plan returns NOT_AUTHORIZED for pre-2022 aggregates. LU ticker also delisted Dec-2006 at Alcatel-Lucent merger, so even with plan upgrade Polygon would not carry post-2006 history. Drawdown stipulation stands per case-brief.

### Period news
- 0 rows for window 2005-01-01 → 2006-12-31 — Polygon news API returns empty (Benzinga partnership coverage starts ~2018, well after this case window).

### Source
- Polygon Aggregates v2 (NOT_AUTHORIZED): https://api.polygon.io/v2/aggs/ticker/LU/range/1/day/2001-01-01/2006-12-31
- Polygon Reference News (0 results): https://api.polygon.io/v2/reference/news?ticker=LU&published_utc.gte=2005-01-01&published_utc.lte=2006-12-31

### Polygon depth-pass (2026-04-30)

**Ticker LU re-issued** (Polygon /v3/reference/tickers/LU): the LU ticker today is "Lufax Holding Ltd. American Depositary Shares" (CIK 0001816007, list_date 2020-10-30, type=ADRC) — i.e., the LU ticker was REUSED by Lufax 14 years after Lucent merged into Alcatel-Lucent. This is a critical Polygon-side gotcha for ticker-rebrand cases: a naive Polygon LU lookup today returns Lufax data, NOT historical Lucent. Documented for downstream consumers of the LU evidence file.

**Alcatel-Lucent ADR (ALU)** (Polygon /v3/reference/tickers?ticker=ALU&active=false): "ALCATEL-LUCENT ADR"; type=CS; active=false; **delisted_utc 2016-02-25T05:00:00Z**. Polygon record corroborates Nokia's acquisition close (Jan 2016 tender offer / Feb 2016 ADR delisting). Pre-cursor "ALCATEL ADS" (ALA) delisted 2006-12-01T05:00:00Z — the LU→ALU merger transition is cleanly visible in Polygon's reference record.
- News for ALU: 0 records (delisted before Polygon's Benzinga news coverage window).
- Aggregates for ALU: NOT_AUTHORIZED for the 2014-01-01 → 2016-02-25 ALU window (plan limit pre-2022).

**Surviving entity Nokia (NOK)** (Polygon /v3/reference/tickers/NOK): "Nokia Corporation"; CIK 0000924613; type=ADRC; active=true; list_date 1994-07-01; current market_cap ~$63.1B; share_class_shares_outstanding 5,742,239,696. NOK is the post-acquisition surviving entity carrying the Lucent legacy.
- NOK aggregates 2021-05-01 → 2024-12-31: 923 daily bars; max close $6.34, min close $3.00 — the post-2021 NOK price band confirms the diluted-survivor / structural-decline trajectory characteristic for the entire telco-equipment archetype (NOK trading 95%+ below its own 2000 peak ~$60).
- NOK dividends: 35 records, including $0.046816 quarterly ex-2026-04-28 — Nokia maintains a partial dividend, consistent with surviving-but-impaired post-merger profile.
- NOK splits: 0 records.
- NOK news: 20 records 2026-Q1/Q2 (recent operating coverage).
- NOK financials: 0 periods returned (Polygon's vX/financials does not carry foreign-issuer ADR PIT financials for NOK).

### Source (depth-pass)
- Polygon Reference (LU rebrand): https://api.polygon.io/v3/reference/tickers/LU
- Polygon Reference (ALU delisted): https://api.polygon.io/v3/reference/tickers?ticker=ALU&active=false → delisted_utc 2016-02-25
- Polygon Reference (ALA delisted): https://api.polygon.io/v3/reference/tickers?search=Alcatel&active=false → ALA delisted_utc 2006-12-01
- Polygon Reference (NOK survivor): https://api.polygon.io/v3/reference/tickers/NOK
- Polygon NOK Aggregates: https://api.polygon.io/v2/aggs/ticker/NOK/range/1/day/2021-05-01/2024-12-31?adjusted=true
- Polygon NOK Dividends: https://api.polygon.io/v3/reference/dividends?ticker=NOK&limit=50
- Polygon NOK News: https://api.polygon.io/v2/reference/news?ticker=NOK&limit=20
