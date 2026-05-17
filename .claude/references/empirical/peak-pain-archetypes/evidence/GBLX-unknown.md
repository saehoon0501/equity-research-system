## GBLX-2002 — peak-pain forensic evidence

### MEASUREMENT TIMEPOINT (operator-locked for feature extraction)

All universal-core feature values below are measured at **fiscal-year close FY2002** (calendar Dec 31, 2002 — the trough fiscal year for Global Crossing Ltd.; the company filed Chapter 11 on Jan 28, 2002, then emerged Dec 9, 2003). Feature extraction uses the FY2002 10-K (filed 2003-04-22, accession 0001193125-03-090817). This is a NON-SURVIVOR case at the equity level: pre-bankruptcy common stock was canceled in the plan of reorganization; ST Telemedia + Hutchison Whampoa took 61.5% of post-emergence equity for $250M.

### Universal-core feature anchors (use these exact spec values)

| Feature | Canonical value (FY2002 lens) | Verbatim quote source |
|---|---|---|
| `founder_in_place` | **departed** | Winnick chairman through Dec 2002, then exited; Legere CEO (Section D) |
| `founder_insider_stake_direction` | **decreasing** | All pre-bankruptcy equity cancelled in Plan of Reorganization (Section D) |
| `cash_runway` | **distressed** | Chapter 11 debtor-in-possession; pre-petition runway breached Q4 2001 (Section B) |
| `margin_trajectory` | **deteriorating** | $17.18B asset impairment FY01; ongoing operating losses FY02 (Section E) |
| `revenue_trajectory` | **declining** | Total revenue $3.12B FY02 vs $3.66B FY01 = -15% (Section E) |
| `industry_tailwind` | **structural-decline** | Telecom bandwidth glut + customer bankruptcies + price collapse (Section A) |

---

## A. Industry shock & operational stress  (industry_tailwind = structural-decline)

10-K verbatim: "Total revenues decreased $543 million, or 15%, in 2002 versus 2001. Our bankruptcy filing in January 2002, the continued worsening of the macroeconomic environment throughout 2002, bankruptcy filings by several of our carrier customers, the overcapacity in the telecommunications industry…"

The 1998-2000 fiber over-build (Global Crossing, 360networks, Williams Communications, Qwest, Level 3, McLeodUSA) created a multi-year bandwidth glut. Customer bankruptcies cascaded: Exodus Communications (Sept 2001 — referenced in 10-K as "filed for bankruptcy protection on September 26, 2001, and our equity interest in Exodus was written off in its entirety"), Asia Global Crossing (Nov 2002), McLeodUSA, Williams Comm, etc. Wholesale long-haul bandwidth pricing collapsed 80-90% across 2001-2003. **structural-decline** is the unambiguous classification — this was not a cyclical pause but a multi-year capacity unwind that destroyed every pure-play long-haul carrier.

## B. Balance sheet & cash position  (cash_runway = distressed)

GBLX filed Chapter 11 on Jan 28, 2002 — pre-petition liquidity was exhausted at trough. The FY2002 10-K reports operations under Bankruptcy Code, with debtor-in-possession financing maintaining operations through reorganization. Cash flow data (5-year selected): Net cash provided by operating activities (FY01) $(1,087)M, (FY02) recovered to positive $330M as restructuring concluded major capex obligations. The Plan of Reorganization, confirmed by the Bankruptcy Court Aug 2003 / closed Dec 9, 2003, transferred 61.5% of equity to Singapore Technologies Telemedia Pte Ltd for $250M cash + $200M senior secured notes assumption.

10-K verbatim: "We have determined that we are required to implement the 'fresh start' accounting provisions of AICPA Statement of Position 90-7, 'Financial Reporting by Entities in Reorganization Under the Bankruptcy Code'…"

→ **cash_runway = "distressed"** is the canonical spec value (the catalog row stipulates "distressed").

## C. Strategic context (NOT a universal-core feature; archetype-matching only)

Pre-bankruptcy peak market cap ~$47B (Feb 2000). Pre-bankruptcy common stock CANCELED in Plan of Reorganization — equity holders received nothing. Hutchison + ST Telemedia investment was structured as new-money DIP-converted equity. Legere stayed as CEO post-emergence; later co-founded T-Mobile US (the famed "Un-Carrier" turnaround) in 2012. The accounting-fraud overhang (Olofson whistleblower letter Aug 2001 → Special Committee → SEC investigation → restatement of FY2000 + FY2001 quarterlies for "concurrent transactions" capacity-swap accounting) compounded the operational distress.

## D. Founder/insider behavior  (founder_in_place = departed; founder_insider_stake_direction = decreasing)

Gary Winnick founded Global Crossing in 1997 (via Pacific Capital Group). 10-K verbatim: "PCG is controlled by Gary Winnick, former chairman of our board of directors from our inception through December 2002."

So Winnick was Chairman at the FY2002 measurement timepoint (Sep 30 / Dec 31), departed by year-end. Beneficial-ownership table: "Gary Winnick 68,929,867 [shares]… 7.35%" — but these shares were CANCELED via Plan of Reorganization (consummated Dec 9, 2003). Pusloskie v. Winnick (Apr 30, 2002) and dozens of related shareholder/employee class actions named Winnick + co-chairman Lodwrick Cook + other PCG-affiliated insiders for breach of fiduciary duty and accounting fraud claims.

→ **founder_in_place = "departed"** (Winnick exited Dec 2002; CEO Legere was a turnaround hire from Asia Global Crossing in Oct 2001 — not a founder, not a "replaced-by-competent" anchor at the trough since the equity was wiped).

→ **founder_insider_stake_direction = "decreasing"** (all pre-bankruptcy founder equity was cancelled in reorganization; Winnick's 7.35% beneficial ownership at filing date became 0% post-emergence). Spec value from ["increasing","flat","decreasing","departed"] — "decreasing" most accurately captures the ZIRP-to-zero equity-holder destruction; "departed" also defensible since Winnick formally left the chairmanship Dec 2002.

## E. Margin & revenue trajectory  (margin_trajectory = deteriorating; revenue_trajectory = declining)

10-K Selected Financial Data (5-year): Total revenues $3,116M (FY02) vs $3,659M (FY01) = -15%. Asset impairment charges $17,181M FY01 (essentially a complete writedown of goodwill $8,573M and tangible long-lived assets $8,608M). FY02 operating expenses $3,550M vs FY01 $23,371M (-$19,821M y/y, almost entirely from the absence of the FY01 impairment).

→ **revenue_trajectory = "declining"** (-15% y/y; cumulative -15-25% trajectory from FY00).

→ **margin_trajectory = "deteriorating"** at the FY02 trough lens — even excluding non-cash impairments, the wholesale bandwidth pricing collapse meant gross margins on the core business were structurally impaired. The catalog stipulation "structural" tailwind aligns: revenue per circuit / per gigabit collapsed faster than fixed-cost reductions could keep pace.

Net cash provided by operations: $(1,087)M FY01 → $330M FY02 (recovery driven by restructuring closure of capex obligations + Ch11 protection from interest payments, NOT margin recovery).

## Sources

- EDGAR 10-K for FY2002 (Global Crossing Ltd.), accession 0001193125-03-090817, filed 2003-04-22: https://www.sec.gov/Archives/edgar/data/1061322/000119312503090817/d10k.txt — Chapter 11 disclosure, Selected Financial Data, MD&A revenue + impairment detail, Restatements + Olofson letter narrative, Item 10 (Legere bio + Cook/Winnick), Beneficial Ownership.
- CIK 1061322 (Global Crossing Ltd. — Bermuda parent; emerged Dec 9, 2003 as "New GCL").
- Plan of Reorganization (filed as exhibit; ST Telemedia / Hutchison Whampoa investment structure).

## Quality notes

- Revenue, impairment, Chapter 11, Winnick chairmanship dates, and restatement language are verbatim from FY2002 10-K — HIGH primary-source confidence.
- Drawdown stipulation -100% (equity holders wiped) per case-brief / Plan of Reorganization.
- This case is the canonical NON-SURVIVOR exemplar in the dot-com cohort — the operating company survived (under ST Telemedia ownership, eventually acquired by Level 3 in 2011) but pre-bankruptcy equity holders were zeroed out. Archetype-matching downstream should treat this as the "structural-decline + accounting-fraud + founder-CEO-out" combination prior, not as a survivor playbook.
- Olofson whistleblower → SEC investigation → restatement is a specific governance-failure marker distinct from operational distress; operator may want a sector-extension feature `accounting_integrity` to capture this.

## Polygon-sourced corroboration (2026-04-30 augment)

### Drawdown math
- 0 rows for window 2000-01-01 → 2003-12-31 — Polygon plan returns NOT_AUTHORIZED for pre-2022 aggregates. GBLX was delisted (Ch 11 Jan-2002), so Polygon would not carry post-delisting history regardless. Drawdown stipulation stands per case-brief.

### Period news
- 0 rows for window 2002-01-01 → 2003-06-30 — Polygon news API returns empty (Benzinga partnership coverage starts ~2018; ticker delisted before then).

### Source
- Polygon Aggregates v2 (NOT_AUTHORIZED): https://api.polygon.io/v2/aggs/ticker/GBLX/range/1/day/2000-01-01/2003-12-31
- Polygon Reference News (0 results): https://api.polygon.io/v2/reference/news?ticker=GBLX&published_utc.gte=2002-01-01&published_utc.lte=2003-06-30

### Polygon depth-pass (2026-04-30)

**Ticker GBLX re-issued** (Polygon /v3/reference/tickers/GBLX): the GBLX ticker today belongs to "GB SCIENCES INC" (type=CS; active=true) — completely different company from the original Global Crossing. As with LU/Lufax, this is a Polygon-side ticker-rebrand gotcha: a naive Polygon GBLX query today returns GB Sciences, NOT historical Global Crossing.

**Post-emergence Global Crossing entity (GLBC)** (Polygon /v3/reference/tickers?search=GLBC&active=false): "GLOBAL CROSSING LTD NEW (BERMUDA)"; type=null; active=false; **delisted_utc 2011-10-05T04:00:00Z**. Polygon record corroborates Level 3 Communications' acquisition of Global Crossing closing Oct-2011. Companion record "GLBC.E" (the original Bermuda-listed line) delisted 2004-10-15. The post-Ch11 emergence ticker (GLBC) is therefore Polygon-traceable from emergence (~2003) through Level3 acquisition (Oct-2011) — the entire diluted-survivor → ultimate-acquisition trajectory is visible in Polygon's reference record, even though pre-2022 aggregates are NOT_AUTHORIZED on this plan.

**Aggregates for GLBC** 2010-01-01 → 2011-10-05: NOT_AUTHORIZED (pre-2022 plan limit). GLBC daily price history during the Level3-acquisition close window cannot be retrieved on this plan.

**News for GBLX/GLBC**: 0 records (Polygon's Benzinga news coverage starts ~2018, well after both delistings).

**Splits / Dividends**: 0 records for both GBLX and GLBC — confirms no corporate-action artifacts in the drawdown stipulation.

**Snapshot for current GBLX (GB Sciences)**: not relevant to the case; documented only to make explicit that the ticker is reused.

### Source (depth-pass)
- Polygon Reference (GBLX reused): https://api.polygon.io/v3/reference/tickers/GBLX → GB Sciences Inc
- Polygon Reference (GLBC delisted): https://api.polygon.io/v3/reference/tickers?search=GLBC&active=false → delisted_utc 2011-10-05
- Polygon Reference (GLBC.E delisted): same search → GLBC.E delisted_utc 2004-10-15
- Polygon GLBC Aggregates (NOT_AUTHORIZED): https://api.polygon.io/v2/aggs/ticker/GLBC/range/1/day/2010-01-01/2011-10-05
- Polygon GLBC Splits: https://api.polygon.io/v3/reference/splits?ticker=GLBC (0 records)
