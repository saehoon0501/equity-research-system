## Chrysler-1981 — peak-pain forensic evidence

### MEASUREMENT TIMEPOINT (operator-locked for feature extraction)

All universal-core feature values below are measured at **fiscal-year close 1980 (record $1.71B loss, largest annual loss for any U.S. firm at that time)** with the trough-event anchor at **Loan Guarantee Act signed Jan-7-1980 + K-car launch 1981**. Recovery context (1982 return to profit; loans repaid 7 years early) provided only for archetype matching — do NOT use it for trajectory-feature extraction at the trough lens. Catalog outcome = SURVIVOR (government-rescued, Iacocca turnaround).

### Universal-core feature anchors (use these exact spec values)

| Feature | Canonical value (1980 lens) | Verbatim quote source |
|---|---|---|
| `founder_in_place` | **replaced-by-competent** | Iacocca hired Nov-1978 → CEO Sep-1979 (Section D) |
| `founder_insider_stake_direction` | **flat** | Iacocca took $1 salary 1980 (alignment, not equity-stake purchase) (Section D) |
| `cash_runway` | **distressed** | Required $1.5B federal loan guarantees Jan-1980 to avoid imminent Ch11 (Section B) |
| `margin_trajectory` | **deteriorating** | -$1.71B 1980 (record U.S. loss); -$476M 1981 (Section E) |
| `revenue_trajectory` | **declining** | Sales pressure from 2nd Arab oil crisis + gas-guzzler product mix; only Big-3 OEM with 1981 unit-sales increase due to K-car launch (Section E) |
| `industry_tailwind` | **reversed** | 1979 Iranian oil crisis + Volcker rate shock crushed large-car demand; structural shift to fuel-efficient compacts (Section A) |

---

## A. Industry shock & operational stress  (industry_tailwind = reversed)

Late-1970s the U.S. auto industry faced a double-shock: (1) 1979 Iranian Revolution / second Arab oil crisis spiked gasoline prices and crushed demand for large gas-guzzling cars exactly the segment Chrysler had specialized in; (2) Volcker rate shock 1979-1981 sent prime to 20%+, destroying auto-loan affordability + dealer floor-plan financing. Japanese imports (Toyota, Honda, Datsun) accelerated share gains. This is `reversed` — the entire competitive structure shifted toward fuel-efficient compacts and away from Chrysler's incumbent product mix. Not `weakening` (cycle was a regime change), not `structural-decline` (the auto industry as a whole survived; the gas-guzzler subcategory died).

## B. Balance sheet & cash position  (cash_runway = distressed)

Chrysler in 1979 was the 10th largest U.S. corporation, smallest of Big 3, on track for a half-billion-dollar 1979 loss. Without federal intervention, Ch11 was projected within months. Congress passed the Chrysler Corporation Loan Guarantee Act in December 1979; President Carter signed Jan-7-1980 authorizing $1.5B in federal loan guarantees. Without the guarantees the firm would have been month-to-month insolvent. `distressed` = single canonical spec value (the bailout itself is the disambiguating evidence: distressed firms get rescued; `<12mo` firms can self-fund through cycle).

## C. Strategic context (NOT a universal-core feature)

K-car platform (Dodge Aries, Plymouth Reliant) launched 1981 — front-wheel-drive compact, fuel-efficient, hit the post-oil-crisis consumer where they actually shopped. ~1M Aries sold + ~1M Reliants. Iacocca's "If you can find a better car, buy it" advertising. By 1982 firm was profitable; loans repaid 7 years early; federal government earned ~$500M profit on stock-warrant component of the rescue.

## D. Founder/insider behavior  (founder_in_place = replaced-by-competent; founder_insider_stake_direction = flat)

Founder Walter Chrysler founded the corporation Jun-6-1925 from the Maxwell Motor Company reorganization; he died 1940. By 1979 there was no founder-in-place — the relevant axis is professional-management succession. John Riccardo (Chairman/CEO through Sep-1979) abruptly retired at age 55 amid bailout negotiations. Lee Iacocca, fired as Ford President Jul-1978, was hired by Chrysler Nov-1978 as President with succession-to-CEO understanding; promoted to CEO upon Riccardo's Sep-1979 retirement. Iacocca took a $1 salary in 1980 as alignment gesture. Spec values: `founder_in_place = replaced-by-competent` (Iacocca, single canonical value from the spec domain — the catalog explicitly tags this case as the canonical example); `founder_insider_stake_direction = flat` ($1 salary is a compensation gesture, not a documented share-count or beneficial-ownership delta — same logic as the NVDA option-repricing case).

## E. Margin & revenue trajectory  (margin_trajectory = deteriorating; revenue_trajectory = declining)

Washington Post 1981-02-28: 1980 net loss $1.71B (then-record largest annual loss for any U.S. firm) on revenues ~$9.23B. Washington Post 1982-02-25: 1981 net loss $475.6M ($7.18/share) on revenues $10.82B. UPI Archives 1982-02-24: Q4-1981 loss $66.9M vs >$200M Q4-1980 = sequential improvement, but trajectory at the FY1980 anchor lens is `deteriorating`. Notable: Chrysler was the only Big-3 OEM with 1981 unit-sales increase (+10.5% deliveries) — the K-car was already pulling. Top-line revenues actually grew nominally 1980→1981 ($9.23B → $10.82B), but the trough lens at FY1980 close still reads `declining` for the multi-year run-rate that produced the bailout, with margin_trajectory `deteriorating` from the loss magnitude.

## F. Operational shock specific to Chrysler — bailout politics + K-car bet

The Loan Guarantee Act was politically contested (Heritage Foundation called it "The Chrysler Bail-Out Bust"); ultimately the federal government earned ~$500M profit on warrants. Iacocca-narrative-led turnaround is the canonical "replaced-by-competent + government-rescue + product-pivot" SURVIVOR archetype — direct precedent for Ford-2009 and a structural counterexample for Drexel-1990 (no rescue, no product pivot, departed founder).

## Sources

- Wikipedia: Chrysler Corporation Loan Guarantee Act of 1979; Walter Chrysler; Lee Iacocca
- Washington Post 1981-02-28 "Chrysler Lost $1.71 Billion in '80, Largest Annual Loss for U.S. Firm"
- Washington Post 1982-02-25 "Chrysler Loses $476 Million in 1981"
- UPI Archives 1982-02-24 "Chrysler reports $475.6 million loss for 1981"
- NPR 2008-11-12 "Examining Chrysler's 1979 Rescue"
- Heritage Foundation "The Chrysler Bail-Out Bust"
- Business History Conference "The Last Automotive Entrepreneur? Lee Iacocca Saves Chrysler, 1978-1986"
- Automotive News "John Riccardo, Chrysler CEO who helped recruit Iacocca, dies at 91"
- WardsAuto "Former Chrysler CEO Riccardo Linked to Iacocca, K-Car Success"

## Quality notes

- No EDGAR coverage (pre-1993 EDGAR mandate; Chrysler was independent until 1998 Daimler merger). Primary sources are contemporary press + congressional record + business-history archives. MEDIUM primary-source confidence vs NVDA baseline.
- Drawdown stipulation (-95% near-bankruptcy) per catalog; cross-check via stock-history references confirms peak-to-trough magnitude in the late-1970s window.
- Polygon API: 401/Unknown + era predates Polygon coverage entirely.
- Founder-axis treatment: catalog explicitly maps this case to `replaced-by-competent` (Iacocca) — single load-bearing spec value, not ambiguous.

## Polygon-sourced corroboration (2026-04-30 augment)

### Coverage status: NOT APPLICABLE — Chrysler was private during 1976-1981 trough

Per task spec: Chrysler was private during the 1976-1981 trough (LeRoy/Iacocca era; federal loan guarantees of 1979-80). No public-equity ticker existed during the window, so Polygon has no coverage by definition. No probes attempted.

### Action
Skip — case narrative is built on bond-market and government-guarantee primary sources, which is appropriate given the private-equity status. Polygon augmentation not feasible regardless of plan tier.

## Polygon-sourced corroboration (2026-04-30 augment)

### Drawdown math
- Polygon aggregates returned NOT_AUTHORIZED for window 1976-01-01..1981-12-31 — the Polygon plan in use covers only ~2022-04-29 forward (rolling ~2yr window from current date 2026-04-29), and Chrysler-as-independent ceased to exist after the 1998 Daimler merger / 2009 Ch11 / 2014 Fiat merger. The 1976-1981 trough window predates Polygon coverage by ~25 years regardless of plan. Drawdown stipulation (-95% near-bankruptcy) per catalog + congressional record + business-history archives retained.

### Period news
- Polygon news returned 0 rows for window 1976..1981 — pre-Benzinga-partnership era + period predates the Polygon news index entirely (news index starts ~2010s). Contemporary press + congressional record coverage from existing Sources section retained.

### Source
- Polygon Aggregates URL: https://api.polygon.io/v2/aggs/ticker/C/range/1/day/1976-01-01/1981-12-31?adjusted=true&apiKey=... → NOT_AUTHORIZED (plan window) + ticker discontinuity (modern C = Citigroup, not Chrysler)
- Polygon News URL: https://api.polygon.io/v2/reference/news?...1976..1981 → 0 results

### Polygon depth-pass (2026-04-30)

Chrysler Corp's 1981 ticker `C` was discontinued via the 1998 DaimlerChrysler merger (DCX), the 2007 Cerberus carve-out (private), the 2009 Ch11 + Fiat acquisition, the 2014 FCA restructuring (FCAU), and finally the 2021 Stellantis merger (STLA). The 1981 trough's underlying entity is now subsumed in STLA. Endpoints attempted:

- `/v3/reference/tickers/STLA`: `{"name":"Stellantis N.V.", "active":true, "list_date":"2010-06-09", "market_cap":$22.77B}` — list_date 2010 reflects Fiat's original Borsa Italiana listing predating the 2021 Peugeot merger; the modern STLA NYSE listing post-dates the 2021 amalgamation.
- `/v2/snapshot/.../STLA`: prevDay close $7.70 (2026-04-28). Note the 2025-2026 derating reflects post-Tavares restructuring + securities-class-action filings (per news pull below) — not 1981 conditions.
- `/v3/reference/tickers/DDAIF`, `/FCAU`: both NotFound (legacy DaimlerChrysler ADR + FCA pre-Stellantis ticker; not retained in Polygon reference).
- `/v3/reference/tickers/DCX`: returns a UNRELATED active ticker — `{"name":"Digital Currency X Technology Inc. Class A Ordinary Shares", "list_date":"2023-06-02", "market_cap":$5.1M}` — DO NOT confuse with the legacy DaimlerChrysler DCX ADR (delisted 2007). Ticker reuse hazard.
- `/v3/reference/tickers?search=Chrysler`: zero results.
- `/v2/aggs/.../STLA/2021-01-04/2024-12-31`: 923 bars; range $11.57-$29.40 — captures the 2021 Stellantis-merger debut through 2024 derating. Irrelevant to 1981 trough.
- `/v3/reference/dividends?ticker=STLA`: annual €/$ payments 2021-2025 ($0.32 → $1.55 → $1.34 → $0.68) — Stellantis-era; no link to legacy Chrysler dividend history.
- `/v2/reference/news?ticker=STLA`: latest items 2026-04-27 to 2026-04-29 (multiple class-action announcements re: hidden restructuring needs).
- `/vX/reference/financials?ticker=STLA`: 0 results — financials endpoint does not return data for STLA (foreign-private-issuer 20-F filer; outside Polygon's vX financials coverage).

Net: Polygon's STLA gives current-state successor context but no period-relevant data for 1979-1982 Chrysler trough. The ticker discontinuity (legacy C → DCX → DDAIF → FCAU → STLA) plus the 1981 timeframe (45 years pre-Polygon-news-corpus) means the depth-pass adds zero direct evidence; period materials remain Iacocca/Reginald-Jones era congressional testimony, 1979 Chrysler Loan Guarantee Act docket, and secondary archive sources retained from initial pass.
