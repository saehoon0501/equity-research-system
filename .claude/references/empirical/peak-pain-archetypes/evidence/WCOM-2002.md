## WCOM-2002 — peak-pain forensic evidence

### MEASUREMENT TIMEPOINT (operator-locked for feature extraction)

All universal-core feature values below are measured at **fiscal-year close FY2002 (year ended December 31, 2002)** — the trough year coinciding with WorldCom's accounting-fraud disclosure (June 2002), Chapter 11 filing (July 21, 2002), and the post-bankruptcy reset. The 10-K filed March 12, 2004 (accession 0001193125-04-039709) is the restated annual report covering 2002 — the only primary source for verbatim FY2002 figures because original filings were withdrawn after the fraud was uncovered.

### Universal-core feature anchors (use these exact spec values)

| Feature | Canonical value (FY2002 lens) | Source |
|---|---|---|
| `founder_in_place` | **departed** | 10-K verbatim: Bernard J. Ebbers "resigned as a director on April 29, 2002" — fired April 2002 ahead of fraud disclosure (Section C) |
| `founder_insider_stake_direction` | **departed** | Mirrors departure; Ebbers's loans-against-stock collateral arrangement (Bank of America loans collateralized by WCOM shares) collapsed |
| `cash_runway` | **distressed** | Chapter 11 filing July 21, 2002 — definitionally distressed; $30.7B of debt subject to compromise |
| `margin_trajectory` | **deteriorating** | Operating loss persisted; restatements aggregating in excess of $9 billion (Section E) |
| `revenue_trajectory` | **declining** | Net revenues fell from $37.7B (2001) to $32.2B (2002), a -15% decline driven by overcapacity and pricing pressure (Section E) |
| `industry_tailwind` | **structural-decline** | 10-K verbatim: "intense competition caused, in large part, by overcapacity in the industry which resulted in pricing pressure" — long-distance/telco overbuild was secular |

---

## A. Industry shock & operational stress  (industry_tailwind = structural-decline)

10-K verbatim: revenue decreases "were primarily due to intense competition caused, in large part, by overcapacity in the industry which resulted in pricing pressure." The post-bubble long-distance/IP-transit overbuild left structural margin compression that persisted across the entire telco sector through the mid-2000s — competitors "exited the market and, in some cases, been forced to liquidate." This is **structural-decline** territory: the pricing pressure was not a single-cycle credit shock but a multi-year secular reset.

## B. Balance sheet & cash position  (cash_runway = distressed)

10-K verbatim: "On July 21, 2002, (the 'Petition Date'), we and substantially all of our direct and indirect domestic subsidiaries (the 'Initial Filers') filed voluntary petitions for relief in the United States Bankruptcy Court for the Southern District of New York" under Chapter 11.

10-K verbatim: "$30.7 billion of outstanding debt that is subject to compromise as a result of our bankruptcy filing on July 21, 2002."

→ **cash_runway = distressed** (single canonical spec value). Chapter 11 filing is the definitional anchor for distressed; no further computation needed. Plan of reorganization confirmed October 31, 2003; emerged 2004 as MCI, Inc.

## C. Founder/insider behavior  (founder_in_place = departed; founder_insider_stake_direction = departed)

10-K verbatim: "Bernard J. Ebbers, our former President and Chief Executive Officer, resigned as a director on April 29, 2002, and did not stand for election at the Annual Meeting of Shareholders."

10-K verbatim: "Beginning on or about September 1995, Mr. Ebbers and companies under his control entered into various loan agreements with Bank of America, N.A." — these stock-collateralized loans collapsed when WCOM shares became worthless.

10-K verbatim: "Capellas joined MCI as our Chairman and Chief Executive Officer." Michael Capellas appointed Chairman in December 2002; new President/COO, CFO, General Counsel, Chief Ethics Officer, Treasurer, and Corporate Controller all installed → complete management turnover post-fraud.

→ **founder_in_place = "departed"** and **founder_insider_stake_direction = "departed"** are unambiguous spec values; Ebbers convicted of fraud (Mar 2005), 25-year sentence.

## D. Margin & revenue trajectory  (margin_trajectory = deteriorating; revenue_trajectory = declining)

10-K verbatim: 2002 revenues "$32.2 billion in 2002, which reduced our operating margins" — vs "operating loss of $11.4 billion on revenues of $37.7 billion in 2001"; vs 2000 revenues of $39.3B with $49.1B operating loss (massively impaired). Revenue trajectory: $39.3B → $37.7B → $32.2B = sustained decline.

→ **revenue_trajectory = "declining"** and **margin_trajectory = "deteriorating"** unambiguous.

## E. Operational shock specific to WCOM — accounting fraud (idiosyncratic)

10-K verbatim: "restated our previously reported consolidated financial statements for the fiscal years ended December 31, 2001 and 2000... [SEC] alleging fraud committed by some of our former officers and employees and the resulting bankruptcy reorganization."

10-K verbatim: restatements "could total in excess of $9 billion." (Final restatement $74B+ across all categories per court records.)

This is the canonical distinction from cyclical NON-SURVIVOR cases (LU, GBLX, Northwest): WCOM is **fraud-driven** NON-SURVIVOR. Sector extension `accounting_quality` should be flagged red — the universal-core features above capture cyclical/structural stress, but the proximate cause was deliberate fraud (~$11B of capitalized line costs misclassified as PP&E from 1999-2002). Ebbers convicted March 15, 2005 of securities fraud and conspiracy.

## Sources

- EDGAR 10-K FY2002 (MCI Inc., post-bankruptcy restated): https://www.sec.gov/Archives/edgar/data/723527/000119312504039709/d10k.htm — filed 2004-03-12 (CIK 723527)
- Chapter 11 filing: U.S. Bankruptcy Court SDNY, July 21, 2002
- Ebbers conviction: Mar 15, 2005 (S.D.N.Y. Crim. No. 02-cr-1144); 25-year sentence
- Successor entity: MCI, Inc. emerged 2004; acquired by Verizon 2006

## Quality notes

- 10-K is the post-bankruptcy restated filing — figures verbatim but reflect post-fraud accounting reset; original FY2002 filings were withdrawn.
- Polygon API not used (pre-2003 not in coverage; ticker delisted at bankruptcy).
- Catalog NON-SURVIVOR classification confirmed: corporate identity dissolved; survivor entity (Verizon) is acquirer not WCOM continuation.

## Polygon-sourced corroboration (2026-04-30 augment)

### Drawdown math
- 0 rows for window 2000-01-01 → 2003-12-31 — Polygon plan returns NOT_AUTHORIZED for pre-2022 aggregates. WCOM was delisted Jul-2002 on Ch 11 filing, so Polygon would not carry post-delisting history regardless. Drawdown stipulation stands per case-brief.

### Period news
- 0 rows for window 2002-01-01 → 2003-06-30 — Polygon news API returns empty (Benzinga partnership coverage starts ~2018; ticker delisted before then).

### Source
- Polygon Aggregates v2 (NOT_AUTHORIZED): https://api.polygon.io/v2/aggs/ticker/WCOM/range/1/day/2000-01-01/2003-12-31
- Polygon Reference News (0 results): https://api.polygon.io/v2/reference/news?ticker=WCOM&published_utc.gte=2002-01-01&published_utc.lte=2003-06-30

### Polygon depth-pass (2026-04-30)

**Ticker WCOM** (Polygon /v3/reference/tickers/WCOM): no record returned (active or inactive). The original WorldCom WCOM ticker is not retained in Polygon's reference universe — consistent with the 2002 Ch11 / NASDAQ delisting wiping the original ticker out of post-delisting reference data.

**Post-emergence MCI Inc (MCIP)** (Polygon /v3/reference/tickers?search=MCIP&active=false): "MCI INC"; type=null; active=false; **delisted_utc 2006-01-09T05:00:00Z**. Polygon record corroborates the post-Ch11 emergence (April 2003 plan-of-reorganization confirmed → traded as MCIP ~2003-2006) → Verizon acquisition close (Jan 2006). The full WCOM-Ch11 → MCIP-emergence → Verizon-acquisition trajectory is Polygon-traceable via the MCIP delisted_utc record.

**Aggregates for MCIP** 2003-01-01 → 2006-01-09: NOT_AUTHORIZED (pre-2022 plan limit). MCIP daily price history during the Verizon-acquisition close window cannot be retrieved on this plan.

**Splits for WCOM, MCIP**: 0 records — confirms no corporate-action artifacts (other than the delisting/emergence themselves).

**Dividends for WCOM, MCIP**: not retrieved (delisted entities; Polygon's dividends endpoint typically does not return data for pre-2010 delisted issuers).

**News for WCOM, MCIP**: 0 records each (Polygon's Benzinga news coverage starts ~2018, well after both entities' delistings — WCOM Jul-2002, MCIP Jan-2006).

**Surviving acquirer Verizon (VZ)**: VZ is not the WCOM/MCIP-continuation entity per the catalog NON-SURVIVOR classification; it is the acquirer. Therefore VZ Polygon data is NOT used as substitute trough-lens evidence — including it would conflate "surviving entity" with "acquirer".

### Source (depth-pass)
- Polygon Reference (WCOM not in reference): https://api.polygon.io/v3/reference/tickers/WCOM (null result both active and inactive)
- Polygon Reference (MCIP delisted): https://api.polygon.io/v3/reference/tickers?search=MCIP&active=false → MCIP delisted_utc 2006-01-09
- Polygon MCIP Aggregates (NOT_AUTHORIZED): https://api.polygon.io/v2/aggs/ticker/MCIP/range/1/day/2003-01-01/2006-01-09
- Polygon WCOM Splits: https://api.polygon.io/v3/reference/splits?ticker=WCOM (0 records)
- Polygon MCIP News: https://api.polygon.io/v2/reference/news?ticker=MCIP (0 records)
