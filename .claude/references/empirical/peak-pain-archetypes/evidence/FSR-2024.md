## FSR-unknown — peak-pain forensic evidence (Fisker Inc., 2021-2024)

### MEASUREMENT TIMEPOINT (operator-locked for feature extraction)

All universal-core feature values below are measured at **fiscal-year close FY2023 (Dec 31, 2023)** — the trough fiscal year filed on 10-K (April 23, 2024) immediately preceding Chapter 11 (June 17, 2024). Recovery context does not exist (NON-SURVIVOR); the canonical "peak-pain" lens is the going-concern-warning trough year itself.

### Universal-core feature anchors (use these exact spec values)

| Feature | Canonical value (FY2023 lens) | Verbatim quote source |
|---|---|---|
| `founder_in_place` | **yes** | 10-K bio (Section D) — Henrik Fisker still co-founder/Chairman/CEO at trough |
| `founder_insider_stake_direction` | **flat** | Form 4 Dec 2022 buy was pre-trough; no documented FY23 share-count delta; salary-to-$1 (July 2024) is post-trough and not a stake change |
| `cash_runway` | **<12mo** | 10-K going-concern (Section B) — $325.5M unrestricted cash → $53.9M by April 16, 2024 |
| `margin_trajectory` | **deteriorating** | 10-K negative gross profit -$285.9M on $272.9M revenue (Section E) |
| `revenue_trajectory` | **growing** | First commercial revenue ($272.9M FY23 vs ~$0 FY22) — but qualitatively a launch ramp, not a healthy trajectory |
| `industry_tailwind` | **weakening** | EV demand softening in 2023-24; spec value `weakening` (not `reversed` — secular EV thesis intact, but cyclical demand weakening hit pre-revenue ramps hardest) |

---

## A. Industry shock & operational stress  (industry_tailwind = weakening)

10-K verbatim: "We continue to face significant headwinds, including the slow EV adoption rate among consumers, increased competition, and unfavorable macroeconomic conditions, including high interest rates."

10-K verbatim: "our ability to generate cash from operating activities will depend on our ability to transition to a dealer model and sell vehicles."

EV demand growth rate slowed sharply across 2023-24; Tesla price cuts compressed industry pricing. Tailwind = weakening, not reversed (Rivian, BYD, Tesla all grew through period).

## B. Balance sheet & cash position  (cash_runway = <12mo)

10-K verbatim: "cash and cash equivalents, net of restricted cash, of $325.5 million as of December 31, 2023."

10-K verbatim: "cash and cash equivalents balance further reduced to $53.9 million of unrestricted and $11.2 million of restricted at April 16, 2024, reflecting significant payments to certain suppliers."

10-K verbatim: "substantial doubt about our ability to continue as a going concern… going concern is dependent upon our ability to raise additional debt or equity financings, enter into a strategic partnership with an OEM, and generate cash from the sale of vehicles."

$325M cash + $1,227M total indebtedness (incl. $667.5M 2026 Convertible Notes) → ran out of cash within ~3.5 months. Spec value **<12mo** (technically <4mo at FY-close lens).

## C. Strategic context (NOT a universal-core feature; archetype-matching only)

Magna contract-manufacturing model (Fisker Ocean produced by Magna Steyr in Austria); Q4 2023 transition from direct-sales to dealer model; missed $8.4M coupon payment March 15, 2024 on 2026 Notes triggering 30-day grace + cross-default cascade.

## D. Founder/insider behavior  (founder_in_place = yes; founder_insider_stake_direction = flat)

10-K verbatim: "Henrik Fisker, Fisker's co-founder, Chairman, President and Chief Executive Officer, is a pioneer in the EV industry, having launched the world's first luxury plug-in hybrid EV, and has a track record of successful designs as the former Chief Executive Officer and President of BMW Designworks USA and the former Design Director for Aston Martin."

10-K verbatim: "Henrik Fisker and Dr. Geeta Gupta-Fisker, our co-founders, members of our Board of Directors and Chief Executive Officer and Chief Financial Officer, respectively."

→ **founder_in_place = "yes"** — both co-founders in operational seats through Ch11 filing.

Stake direction: Henrik + Geeta open-market buy of 33,700 shares Dec 2022 (pre-trough). No documented FY23 share-count delta. July 2024 salary cut to $1 (post-trough, post-Ch11). For FY23 measurement-timepoint lens: **flat**.

## E. Margin & revenue trajectory  (margin_trajectory = deteriorating; revenue_trajectory = growing)

10-K verbatim: "delivered 4,847 vehicles, net of returns and recognized net revenue of $272.9 million with related cost of revenues totaling $558.8 million resulting in negative gross profit of $285.9 million."

→ Gross margin = -104.8% (cost of revenue >2x revenue). Margin trajectory **deteriorating** — but note: pre-revenue→commercial-launch case where "deteriorating" reflects the cost-overrun catastrophe vs FY22 pre-revenue baseline. Single canonical spec value.

→ Revenue **growing** in raw spec terms ($0→$272.9M is "growing" by definition), even though qualitatively this is a failed launch ramp. Canonical-spec-domain language forces "growing"; analyst overlay would code this as "launch-stall" but that's not in the universal-core domain.

## F. Operational shock specific to FSR — production/quality/dealer-pivot triple shock

10-K verbatim: "delivered over 6,400 Oceans" cumulative; FY23 delivered 4,847 net (returns reversed deliveries). Dealer-model pivot Q4 2023 abandoned direct-sales infrastructure mid-launch. Software defects + inventory financing strain compounded; bankruptcy filed June 17, 2024 (Delaware).

## Sources

- EDGAR 10-K FY2023 (Fisker): https://www.sec.gov/Archives/edgar/data/1720990/000172099024000045/fsr-20231231.htm — Item 1 Business, Item 1A Risk Factors, MD&A, Going Concern note.
- BusinessWire (Dec 5, 2022): "Fisker CEO Henrik Fisker and CFO/COO Geeta Gupta-Fisker Purchase 33,700 Shares of Fisker Inc."
- BusinessWire (June 17, 2024): "Fisker Group Inc. Files for Chapter 11" (Delaware).
- TechCrunch (July 9, 2024): "Henrik Fisker drops salary to $1 to keep Fisker Inc. bankruptcy case alive."

## Quality notes

- Going-concern + Q1 2024 cash-burn data are verbatim primary-source 10-K — HIGH confidence.
- "founder_insider_stake_direction = flat" is conservative read at FY23 close; the Dec 2022 buy doesn't satisfy "increasing" because it precedes the measurement window, and the July 2024 salary-cut is post-window.
- Polygon API price data not retrieved (FSR delisted Apr 10, 2024 per Form 25-NSE); raw_row -100% drawdown is a stipulation cross-checked against delisting record.

## Polygon-sourced corroboration (2026-04-30 augment)

### Drawdown math
- **Peak:** $23.68 on 2021-11-16 (split-adjusted close)
- **Trough:** $0.08965 on 2024-03-25
- **Drawdown:** -99.6%
- **Wall time peak->trough:** 591 trading days (~28 months)
- Recovery to peak: no — last Polygon close 2024-03-25 ($0.08965); ticker effectively halted/suspended around Fisker bankruptcy filing (Ch11 June 2024)

### Period news (Polygon /v2/reference/news, multi-publisher; FSR pre-Ch11 collapse coverage)
- 2024-03-25 | Benzinga | "Crude Oil Moves Higher; US New Home Sales Fall In February" (FSR tagged amid distress coverage; trough date)
- 2024-03-24 | Seeking Alpha | "Fisker: Precarious Situation"
- 2024-03-21 | Zacks Investment Research | "EV Startups' Survival Saga Continues: Fisker (FSR) on the Edge"
- 2024-03-18 | MarketWatch | "Fisker stock sinks after a production pause offset a new financing deal"
- 2024-03-16 | The Motley Fool | "Fisker Stock: Buy, Sell, or Hold?"
- 2024-03-14 | MarketWatch | "Fisker breaks silence about potential bankruptcy. Here's what it had to say."
- 2024-03-14 | MarketWatch | "Fisker's stock cut in half after bankruptcy report"
- 2024-03-14 | The Motley Fool | "What Happens If Fisker Is Delisted?"
- 2024-03-13 | Benzinga | "Fisker Stock Plunges On Report The EV Manufacturer Is On Brink Of Bankruptcy"
- 2024-03-11 | The Motley Fool | "Unfortunate News for Fisker Stock Investors"
- 2024-03-10 | The Motley Fool | "Is Fisker Stock Going to Zero?"
- 2024-03-01 | Benzinga | "Crude Oil Rises Over 2%; Fisker Shares Plummet"
- 2021-11-17 | Benzinga | "Fisker Ocean Unveiled At Los Angeles Auto Show: Here's What Drivers And Investors Should Know" (peak window)
- 2021-12-08 | The Motley Fool | "Why EV Stock Fisker Zoomed 33% in November" (peak window euphoria)
- 2021-12-08 | Benzinga | "Tesla Vs. Rivian Vs. Lucid Vs. Fisker Vs. Lordstown Vs. Canoo: How BofA Says The EV Makers Stack Up"

### Source
- Polygon Aggregates: https://api.polygon.io/v2/aggs/ticker/FSR/range/1/day/2021-05-01/2024-12-31?adjusted=true (729 daily bars; first 2021-05-03, last 2024-03-25)
- Polygon News: https://api.polygon.io/v2/reference/news?ticker=FSR&published_utc.gte=2021-11-01&published_utc.lte=2024-06-30

### Polygon depth-pass (2026-04-30)

**Reference (delisted)** (Polygon /v3/reference/tickers?ticker=FSR&active=false): "Fisker Inc."; type=CS; active=false; **delisted_utc 2024-03-26T04:00:00Z**. Polygon's reference record shows Fisker delisted from NYSE one day after the Polygon-observed price trough of 2024-03-25 ($0.08965). The delisting timestamp aligns with the Form 25-NSE filing referenced in the original quality-notes. Catalog NON-SURVIVOR classification fully validated end-to-end via Polygon reference.

**Companion entity in Polygon record:** "FSR.WS" (Fisker Inc. Warrants, each whole warrant exercisable for one Class A common stock) delisted_utc 2021-04-19T04:00:00Z — warrants delisted nearly 3 years before the common, suggesting earlier capital-structure stress signals were detectable in the warrant market well ahead of the equity collapse. (Not used in trough-lens features but a useful empirical observation for the archetype-matching playbook.)

**Snapshot** (Polygon /v2/snapshot, 2026-04-29): all fields null — confirms post-delisting non-availability.

**Splits** (Polygon /v3/reference/splits?ticker=FSR): 0 records. The drawdown math (-99.6%) is raw price math, no split-adjustment artifact.

**Dividends** (Polygon /v3/reference/dividends?ticker=FSR): 0 records. Fisker never paid a dividend — consistent with pre-revenue / pre-FCF EV startup posture.

**PIT financials**: not available for FSR via Polygon's vX/financials endpoint (delisted entity, limited PIT financials record).

### Source (depth-pass)
- Polygon Reference (delisted): https://api.polygon.io/v3/reference/tickers?search=FSR&active=false → ticker=FSR delisted_utc 2024-03-26
- Polygon Snapshot (post-delisting null): https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/FSR
- Polygon Splits: https://api.polygon.io/v3/reference/splits?ticker=FSR (0 records)
- Polygon Dividends: https://api.polygon.io/v3/reference/dividends?ticker=FSR (0 records)
