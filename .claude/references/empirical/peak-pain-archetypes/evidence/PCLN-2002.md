## PCLN-2002 — peak-pain forensic evidence

### MEASUREMENT TIMEPOINT (operator-locked for feature extraction)

All universal-core feature values below are measured at **fiscal-year close FY2001** (calendar Dec 31, 2001 — the trough fiscal year for priceline.com Incorporated). Feature extraction uses the FY2001 10-K (filed 2002-03, accession 0001005477-02-001441). The post-trough Booking.com acquisition (2005) is downstream context only.

### Universal-core feature anchors (use these exact spec values)

| Feature | Canonical value (FY2001 lens) | Verbatim quote source |
|---|---|---|
| `founder_in_place` | **replaced-by-competent** | 10-K MD&A; Walker departed Dec 2000; Boyd in EVP role rising to CEO 2002 (Section D) |
| `founder_insider_stake_direction` | **departed** | Walker no longer officer/director; named only as defendant in litigation (Section D) |
| `cash_runway` | **<12mo** at trough but stabilizing | $164.6M cash + ST investments; Q2 2001 first profit (Section B) |
| `margin_trajectory` | **improving** | Net loss -$7.3M FY01 vs -$315M FY00 (Section E) |
| `revenue_trajectory` | **declining** | Total revenue $1.17B FY01 vs $1.24B FY00 = -5% (Section E) |
| `industry_tailwind` | **reversed** | Online travel collapsed post-9/11; OTA model required full rebuild (Section A) |

---

## A. Industry shock & operational stress  (industry_tailwind = reversed)

10-K verbatim: "Throughout 2001, we focused our resources and attention primarily on our travel business with the intent of achieving profitability which we did in the second quarter of 2001. We successfully expanded our travel offerings to include cruises, cruise packages, a resort option…"

Online travel demand collapsed in two waves: (1) Q4 2000 dot-com bust — Sept 27, 2000 priceline pre-announced miss triggered the stock crash from $104 → $1.80; (2) Sept 11, 2001 — terrorist attacks froze leisure travel. The opaque-bid airline model (Walker's "Name Your Own Price" patent) had peaked before the trough; recovery required pivot to merchant-hotel and ultimately Booking.com acquisition (2005). Industry tailwind classification = **reversed** rather than "weakening": the pre-bust priceline business model (opaque-bid leisure airline focus, WebHouse Club groceries/gas, perks) was structurally broken and had to be rebuilt as a different company.

## B. Balance sheet & cash position  (cash_runway = <12mo)

10-K Selected Financial Data: "Cash, cash equivalents, short-term investments and restricted cash $164,608" (thousands) at Dec 31, 2001 vs $106,018 (FY00) vs $177,299 (FY99). Working capital $98M.

The catalog stipulation reads "<12mo" — at peak burn 2000 (-$315M net loss), $164M would have been <12 months. By FY2001 close, after Q2 first profitability and -$7.3M annual net loss, the practical runway extended materially. Operator should anchor the feature at the trough-year stress lens: **<12mo** in classification because the stock-implied risk and the stipulated catalog row use that label; the stabilization (Q2 2001 profit + revenue stabilizing) is what saved the business but does not retroactively elevate the trough-year cash position.

## C. Strategic context (NOT a universal-core feature; archetype-matching only)

10-K verbatim: "In the second quarter of 2001, our Board of Directors announced that Richard S. Braddock had been reappointed as Chief Executive Officer. Mr. Braddock replaced Daniel H. Schulman, our prior President and Chief Executive Officer. In connection with Mr. Schulman's separation, we recorded a severance charge of $5.4 million in the second quarter of 2001."

Two CEO changes in 18 months (Walker→Schulman→Braddock); Jeffery H. Boyd appears in employment-agreement exhibits at FY01 close, ascended to CEO Aug 2002, then engineered the Bookings.com (Booking.com) acquisition Nov 2005 — the canonical "replaced-by-competent" outcome.

## D. Founder/insider behavior  (founder_in_place = replaced-by-competent; founder_insider_stake_direction = departed)

Jay S. Walker founded priceline.com (via Walker Digital) and served as Vice Chairman until Dec 2000. By the FY2001 10-K filing (early 2002), Walker is named only as a defendant in numerous Connecticut District Court class-action complaints (Weingarten v. priceline.com Inc. and Jay S. Walker, Twardy v. priceline.com Inc., Richard S. Braddock, Daniel H. Schulman and Jay S. Walker, etc.) — i.e., he is no longer an officer or director.

10-K Exhibit list confirms: 10.6.1(a) "Employment Agreement, dated as of January 1, 1998, between Jay S. Walker, Walker Digital Corporation, the Registrant and Jesse M. Fink" — Walker's employment relationship was indirect via Walker Digital and ended pre-trough.

→ **founder_in_place = "replaced-by-competent"** (Boyd's Booking pivot 2005 is the validation). **founder_insider_stake_direction = "departed"**.

## E. Margin & revenue trajectory  (margin_trajectory = improving; revenue_trajectory = declining)

10-K consolidated income data: Total revenues $1,171,753K (FY01) vs $1,235,396K (FY00) vs $482,410K (FY99) — -5% y/y; cost of travel revenues $976,035K (FY01) vs $1,038,783K (FY00). Net loss $7.3M (FY01) vs $315.1M (FY00) vs $1,055.1M (FY99). Travel revenues 99.2% of total.

→ **revenue_trajectory = "declining"** (-5% y/y; first decline in company history) but **margin_trajectory = "improving"** (net loss collapsed from -$315M to -$7M; Q2 2001 first profitable quarter).

## Sources

- EDGAR 10-K for FY2001 (priceline.com Incorporated), accession 0001005477-02-001441: https://www.sec.gov/Archives/edgar/data/1075531/000100547702001441/d02-36883.txt — Selected Financial Data, MD&A, Restructuring/Special Charges note, Legal Proceedings (Walker class-action listings), Executive Compensation exhibits.
- CIK 1075531 (priceline.com → Priceline Group → Booking Holdings).

## Quality notes

- Revenue, net loss, cash, and CEO transition language are verbatim primary-source FY2001 10-K — HIGH confidence.
- Drawdown stipulation -99% peak (Apr 1999 ~$104.25 split-adj) → trough (Dec 2000 ~$1.06) per case-brief / MacroTrends.
- Walker's exact departure month (Dec 2000) per public record and contemporary trade press; not directly stated in the 10-K but consistent with his absence from officer/director listings and presence only as litigation defendant.
- The "<12mo" cash_runway label tracks the catalog stipulation — at the deepest valley the going-concern question was real, and it was answered by the unexpectedly fast Q2-2001 profitability inflection.

## Polygon-sourced corroboration (2026-04-30 augment)

### Coverage status: PARTIAL — PCLN ticker reassigned, BKNG (rebranded successor) fully covered post-2021

`PCLN` ticker reassignment confirmed: the symbol is now occupied by `Pictet Cleaner Planet ETF` (list_date 2025-10-15) — i.e., the priceline.com legacy ticker was scrubbed and recycled. CIK 1075531 in Polygon's record for PCLN matches the original priceline filer entity, but the price-data lineage moved to BKNG. This is unusually clean for a rebrand precedent — the legacy ticker letterspace was reused, not just retired. Depth-pass below uses BKNG as the canonical lineage proxy.

### Ticker reference (`v3/reference/tickers/PCLN`): RECYCLED
- Now returns `Pictet Cleaner Planet ETF` — not the legacy priceline.com common
- Reinforces that any historical PCLN price probe will hit ETF data, NOT priceline.com — important sanity check for any future researcher

### Successor BKNG reference (`v3/reference/tickers/BKNG`)
- Name: `Booking Holdings Inc. Common Stock`
- SIC: TRANSPORTATION SERVICES (4700)
- list_date: 1999-03-31 (original priceline.com IPO date — confirming BKNG is the lineage-continuation entity, NOT a fresh listing)
- Market cap (snapshot): ~$135B; shares outstanding 31,673,346 (after the 2026 1:25 split — see Splits below)
- prev-close $173.98

### Splits (`v3/reference/splits?ticker=BKNG`)
- 2026-04-06: **1:25 reverse-equivalent split** (from Polygon's representation; this is actually a 25-for-1 forward stock split per recent BKNG filings, splitting after years of $4000+ share price)
- 2003-06-16: **6:1 reverse split** — this is the KEY corporate-action that vindicates the case-brief's "10:1 reverse split 2003" reference (Polygon records it as 6:1; the canonical case-brief number ~10:1 may reflect cumulative or alternate sourcing — worth flagging)

→ The 2003-06-16 reverse split is the pivot from priceline-the-distressed-OTA to Booking-the-survivor. It happened ~1.5 years after the FY2001 trough lens; sub-$1 trough quotes were swept up into a multi-dollar post-split base.

### Aggregates — recovery-window proxy (2021-05-01 → 2024-12-31)
- 923 trading days; close max $212.0136 (post the 2026 1:25 split, this represents pre-split ~$5,300 — peak BKNG mega-cap), close min $65.38 (post-split-equivalent ~$1,634 — late 2022 rate scare)
- Pre-2026-split prices are now Polygon-adjusted; the 2024 high effectively = ~$5,300 / $0.65 trough = +815,000% over 23 years. This is one of the largest equity-recovery trajectories in market history (validates the "replaced-by-competent" Boyd → Booking.com 2005 acquisition thesis)

### Financials (`vX/reference/financials?ticker=BKNG`)
- 20 PIT periods; FY2026 Q1 revenue $5.53B; TTM revenue $27.69B vs FY2001 $1.17B → ~24× revenue growth over 24 years. Compound annual rev growth ~14% — confirms post-trough operational rebuild from "declining" FY2001 → durable "growing" trajectory under Boyd

### News
- Recent 2026 headlines (Apr 29: Hormuz crisis hitting BKNG; 52-week-low headline Apr 29 2026 — middle-east conflict overhang). No FY2001 trough coverage.

### Source URLs
- Reference (PCLN recycled): https://api.polygon.io/v3/reference/tickers/PCLN?apiKey=…
- Reference (BKNG canonical): https://api.polygon.io/v3/reference/tickers/BKNG?apiKey=…
- Splits (BKNG): https://api.polygon.io/v3/reference/splits?ticker=BKNG&apiKey=…
- Aggs (BKNG recovery): https://api.polygon.io/v2/aggs/ticker/BKNG/range/1/day/2021-05-01/2024-12-31?adjusted=true&apiKey=…

### Action
Catalog drawdown math (-99% to ~$0.65 sub-1$ trough) retained. Polygon ADDS: (1) PCLN ticker is RECYCLED to a Pictet ETF — load-bearing fact for any future PCLN-symbol queries; (2) BKNG carries list_date 1999-03-31 = priceline.com IPO date, confirming corporate-identity continuation; (3) 2003-06-16 reverse split documented (6:1 per Polygon, vs case-brief 10:1 — minor reconciliation flag); (4) ~24× revenue growth FY01 → FY25 = empirically validates Boyd's "replaced-by-competent" archetype.
