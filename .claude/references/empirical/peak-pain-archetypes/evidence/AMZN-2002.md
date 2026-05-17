## AMZN-2002 — peak-pain forensic evidence

### MEASUREMENT TIMEPOINT (operator-locked for feature extraction)

All universal-core feature values below are measured at **fiscal-year close FY2001** (calendar Dec 31, 2001 — the dot-com trough fiscal year for Amazon). Feature extraction uses the FY2001 10-K (filed 2002-01-24); the FY2002 recovery year is downstream context only.

### Universal-core feature anchors (use these exact spec values)

| Feature | Canonical value (FY2001 lens) | Verbatim quote source |
|---|---|---|
| `founder_in_place` | **yes** | 10-K Bezos bio (Section D) |
| `founder_insider_stake_direction` | **flat** | No Form-4 share-count delta in 10-K window (Section D) |
| `cash_runway` | **>24mo** | $997M cash + securities, Q4 pro-forma profit (Section B) |
| `margin_trajectory` | **improving** | Gross profit $799M FY01 vs $656M FY00 (Section E) |
| `revenue_trajectory` | **growing** | Net sales $3.12B FY01 vs $2.76B FY00 = +13% (Section E) |
| `industry_tailwind` | **weakening** | Dot-com bust cyclical reset; e-commerce secular intact (Section A) |

---

## A. Industry shock & operational stress  (industry_tailwind = weakening)

10-K Risk Factors verbatim: "Our success depends in significant part on the continued growth in the use of the Internet and online commerce. Acceptance and use of the Internet may not continue to develop at historical rates and a sufficiently broad base of consumers may not adopt or continue to use the Internet as a medium of commerce."

The dot-com collapse cut online ad/retail growth rates and killed peer dot-coms (Pets.com, Webvan, eToys liquidations 2000-01). Amazon's annual net sales growth rate slowed from 68% (FY00) to 13% (FY01) — clear cyclical weakening. Not "reversed" or "structural-decline": e-commerce penetration thesis remained intact, and Amazon's customer base/mix expanded.

## B. Balance sheet & cash position  (cash_runway = >24mo)

10-K verbatim: "Our cash and cash equivalents balance was $540 million and $822 million, and our marketable securities balance was $456 million and $278 million at December 31, 2001 and 2000, respectively. Combined cash, cash equivalents, and marketable securities were $997 million and $1.1 billion."

10-K verbatim (forward-looking): "we expect to have positive operating cash flow, and possibly free cash flow, for fiscal year 2002… we believe that our existing cash, cash equivalents and marketable securities balances will be sufficient to meet our anticipated operating cash needs for at least the next 12 months."

This is the famous Bezos position. Amazon also had ~$2.16B long-term debt (10% Senior Discount Notes due 2008, convertibles) — meaningful leverage — but the runway from $997M liquidity plus inflecting operating cash flow comfortably exceeds 24 months.

## C. Strategic context (NOT a universal-core feature; archetype-matching only)

Amazon achieved its first pro-forma operating profit in Q4 2001. 10-K verbatim: "notwithstanding our recent performance in the fourth quarter of 2001, we may continue to incur such losses for the foreseeable future." Operating loss FY01 of -$412M improved from -$864M FY00 (-52%). Bezos's 2001 shareholder letter ("we have all the cash we need") reflects the shift from growth-at-any-cost to operating-leverage extraction.

## D. Founder/insider behavior  (founder_in_place = yes; founder_insider_stake_direction = flat)

10-K verbatim: "Mr. Bezos has been Chairman of the Board of Amazon.com since founding it in 1994 and Chief Executive Officer since May 1996. Mr. Bezos served as President from founding until June 1999 and again from October 2000 to the present."

→ **founder_in_place = "yes"**.

10-K verbatim Risk Factors: "We depend on the continued services and performance of our senior management and other key personnel, particularly Jeffrey P. Bezos, our President, Chief Executive Officer and Chairman of the Board."

No documented Form-4 share-count delta during FY01 in the 10-K disclosure window. → **founder_insider_stake_direction = "flat"**.

## E. Margin & revenue trajectory  (margin_trajectory = improving; revenue_trajectory = growing)

10-K Selected Financial Data: Net sales $3,122,433K (FY01) vs $2,761,983K (FY00) vs $1,639,839K (FY99) — +13% y/y; Gross profit $798,558K (FY01) vs $655,777K (FY00) — gross margin 25.6% FY01 vs 23.7% FY00. 10-K verbatim: "Excluding the results of our Services segment, gross margin would have been 23%, 21% and 17%, respectively" — improvement from product/inventory management.

→ **margin_trajectory = "improving"**, **revenue_trajectory = "growing"** (slowing but positive +13% y/y).

Loss from operations -$412M (FY01) vs -$864M (FY00) = -52% improvement; net loss -$567M vs -$1.4B. Q4 FY01 first pro-forma profitable quarter — inflection point.

## Sources

- EDGAR 10-K for FY2001 (Amazon.com Inc.), accession 0001032210-02-000059, filed 2002-01-24: https://www.sec.gov/Archives/edgar/data/1018724/000103221002000059/d10k405.htm — Selected Financial Data, MD&A, Liquidity, Risk Factors, Bezos bio.
- Bezos 2000-01 shareholder letters (background on "all the cash we need" language and growth-through-trough commitment).

## Quality notes

- Net sales, gross profit, cash position, and Bezos bio are direct verbatim from FY2001 10-K — HIGH primary-source confidence.
- Drawdown stipulation ~-95% peak (Dec 1999 ~$106) → trough (Sept 2001 ~$5.50) per case-brief; cross-check vs MacroTrends/StatMuse summaries.
- Q4 2001 pro-forma profitability called out in 10-K but full Q4 segment economics rely on press release + earnings call (modern paywalls).

## Polygon-sourced corroboration (2026-04-30 augment)

### Coverage status: PARTIAL — 2001 trough denied, post-2021 recovery + 2022 split corporate action harvested

The dot-com trough is outside Polygon's plan window. Depth-pass extracts current entity reference + 2022 stock split (only post-1999 split in Polygon's record) + post-2021 recovery aggregates that show AMZN re-rated to mega-cap from the 2001 dot-com trough.

### Ticker reference (`v3/reference/tickers/AMZN`)
- Name: `Amazon.Com Inc`
- SIC: RETAIL-CATALOG & MAIL-ORDER HOUSES (5961)
- list_date: 1997-05-15 (NASDAQ IPO)
- Market cap (snapshot): ~$2.79T; shares outstanding 10,754,251,799 (≈10.75B post the 20-for-1 June-2022 split)
- prev-close $263.04 → ~$5,260 pre-2022-split equivalent → ~×880 vs the catalog $5.97 split-adjusted Sep-2001 trough (massive multi-decade compounding)

### Splits (`v3/reference/splits?ticker=AMZN`)
- 2022-06-06: 1:20 — only AMZN split in Polygon's recorded history (the 1998-1999 dot-com era splits 2:1, 3:1, 2:1 are aggregated into the case-brief "split-adjusted" trough $5.97 figure but predate Polygon's split-record catalog)
- The 2022 split is NOT material to the FY2001 trough lens (it happened 21 years post-trough), but it IS material for any current price-comparability work — current $263 ÷ ($5.97 ÷ 20-split-shadow) is the wrong calc; use $263 vs the pre-split-equivalent FY2001 trough

### Aggregates — recovery-window proxy (2021-05-01 → 2024-12-31)
- 923 trading days; close max $232.93 (late 2024 AI/AWS re-rate), close min $81.82 (late 2022 rate-spike scare; ~mega-cap-correction)
- The $81.82 2022 trough → $232 2024 high = +185% over 2 years; gives a recent-era "trough recovery slope" anchor for survivor-archetype calibration even though it's a different cycle from the 2001 dot-com trough

### Financials (`vX/reference/financials?ticker=AMZN`)
- 20 PIT periods; FY2025 TTM revenue $716.92B vs FY2001 $3.12B → ~230× growth over 24 years. Compound annual growth rate of revenue ~25% — operationally validates the "growing-not-declining" trajectory feature value at FY2001 lens that the case file marks; the 2001 inflection was real and durable.

### News
- Recent 2026 headlines (Apr 29 Big Tech earnings, MSFT vs AMZN comparison Apr 29). No FY2001 trough headlines (pre-Benzinga + 25yr gap).

### Source URLs
- Reference: https://api.polygon.io/v3/reference/tickers/AMZN?apiKey=…
- Splits: https://api.polygon.io/v3/reference/splits?ticker=AMZN&apiKey=…
- Aggs (recovery): https://api.polygon.io/v2/aggs/ticker/AMZN/range/1/day/2021-05-01/2024-12-31?adjusted=true&apiKey=…
- Financials: https://api.polygon.io/vX/reference/financials?ticker=AMZN&limit=20&apiKey=…

### Action
Catalog drawdown math (-95% peak/trough) retained as canonical. Polygon ADDS: (1) live entity reference confirming SURVIVOR mega-cap status; (2) 2022 1:20 split as corporate-action waypoint (NOT in FY2001 trough lens but documents the post-trough compounding journey); (3) revenue ~230× growth FY01 → FY25 = textbook empirical validation of the "growing trajectory through dot-com trough" universal-core feature value.
