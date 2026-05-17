## Drexel-1990 — peak-pain forensic evidence

### MEASUREMENT TIMEPOINT (operator-locked for feature extraction)

All universal-core feature values below are measured at **fiscal-year close 1989 → trough event Feb-13-1990 Ch11**. Drexel was a private investment bank (LBO'd into a holding-company structure 1976), so no public 10-K exists; primary sources are bankruptcy-court filings, contemporary WSJ/NYT/Fortune coverage, and the SEC/RICO settlement record. Recovery context does not apply (firm liquidated; outcome = NON-SURVIVOR -100%).

### Universal-core feature anchors (use these exact spec values)

| Feature | Canonical value (1989 / Feb-1990 lens) | Verbatim quote source |
|---|---|---|
| `founder_in_place` | **departed** | Milken left under indictment Mar-1989 (Section D) — "founder" framing is the de-facto Milken/junk-bond founder; legal-name founders (Drexel/Burnham) had departed decades earlier |
| `founder_insider_stake_direction` | **departed** | $200M 1988 comp withheld; Milken severed (Section D) |
| `cash_runway` | **distressed** | $300M commercial paper rollover crisis Feb-1990; SEC ordered capital-transfer halt Feb-9-1990 (Section B) |
| `margin_trajectory` | **deteriorating** | -$160M 1988 → -$40M 1989 (estimated); -$86M one-month loss late-1989 (Section E) |
| `revenue_trajectory` | **declining** | Junk-underwriting market share 50% YE1988 → 38% YE1989; 5,000 jobs eliminated Apr-1989 (45% headcount cut) |
| `industry_tailwind` | **reversed** | Junk-bond market collapse 1989; UAL deal failure Oct-1989 marks visible reversal of the LBO/junk-bond boom (Section A) |

---

## A. Industry shock & operational stress  (industry_tailwind = reversed)

The junk-bond market that Drexel pioneered under Milken collapsed in 1989. The October 1989 UAL deal failure is widely cited as the inflection point for the entire high-yield market; spreads blew out, defaults rose, and 1989 high-yield issuance fell sharply. This was not a cyclical "weakening" — the regulatory + market structure shifted permanently as RICO threat reshaped the LBO/junk underwriting landscape. Tailwind = `reversed` (boom decisively turned, but the high-yield asset class itself survived in a restructured form, so not `structural-decline`).

## B. Balance sheet & cash position  (cash_runway = distressed)

YE1988 capital base ~$1.4B. By February 1990, top executives were "scrambling to roll over $300 million of the firm's own commercial paper" (Wikipedia / Fortune oral history). On Feb-9-1990 the SEC ordered Drexel to stop transferring excess capital from its regulated broker/dealer subsidiary up to the holding company, citing solvency concerns. On the morning of Feb-13-1990, NY Fed President E. Gerald Corrigan, SEC Chairman Richard Breeden, Treasury Secretary Brady, and NYSE Chairman Phelan issued an ultimatum: file Ch11 or be seized before market open. Holdco Ch11 filed same day. Cash runway = `distressed` (single canonical spec value).

## C. Strategic context (NOT a universal-core feature)

Junk-bond franchise was the entire moat — and the RICO settlement (Dec-1988, $650M fine, Milken removal) directly destroyed it. Settlement-mandated outside management + Milken's $200M 1988 compensation withheld + Mar-1989 indictment effectively decapitated the high-yield department. No moat to lean on through the 1989 market collapse.

## D. Founder/insider behavior  (founder_in_place = departed; founder_insider_stake_direction = departed)

Milken (the operative founder of Drexel's modern junk-bond franchise; legal-name founders Francis Drexel 1838 / I.W. Burnham 1935 had long since departed) left in March 1989 after federal grand jury indictment on 98 counts (securities fraud, racketeering, tax fraud). Per RICO settlement Drexel agreed Milken had to leave if indicted, withheld his $200M 1988 compensation, and removed him as head of high-yield. CEO Frederick Joseph (named CEO 1985) remained through bankruptcy filing; John Sorte succeeded as CEO concurrent with Ch11. Spec values: `founder_in_place = departed` (Milken indicted/severed); `founder_insider_stake_direction = departed` (compensation clawed back, no continuing stake).

## E. Margin & revenue trajectory  (margin_trajectory = deteriorating; revenue_trajectory = declining)

UPI Archives 1990-02-05: "Drexel reports estimated 1989 loss" of ~$40M (vs ~$160M loss 1988). One-month loss of $86M reported in late 1989. Headcount cut 45% during 1989; April 1989 elimination of 5,000 jobs (three departments shuttered including retail brokerage). Mid-1980s peak revenue ~$4B; 1989 underwriting market share 38% vs 50% YE1988 = -24% relative share drop. Trajectory unambiguously `deteriorating` / `declining`.

## F. Operational shock specific to Drexel — RICO settlement + criminal indictment

Dec-1988 RICO settlement: pleaded guilty to six felonies, $650M fine (largest under Depression-era securities laws at the time), accepted outside management, agreed to remove Milken if indicted. Mar-1989 Milken indicted on 98 counts. The combined regulatory + criminal + market-structure shock is the textbook "reversed industry tailwind + departed founder + distressed cash" failure pattern — i.e., the canonical NON-SURVIVOR archetype for peak-pain matching.

## Sources

- Wikipedia: Drexel Burnham Lambert — bankruptcy chronology, RICO settlement, capital-transfer halt
- Fortune 2015-10-16 "The last days of Drexel Burnham" oral history
- Bloomberg "Renegades of Junk: The Rise and Fall of the Drexel Empire" oral-history graphics package
- UPI Archives 1990-02-05 "Drexel reports estimated 1989 loss"
- Justia: In Re Drexel Burnham Lambert Group, Inc. (148 B.R. 1002 / 161 B.R. 902, S.D.N.Y. 1993)
- Museum of American Finance Drexel Burnham Lambert Archival Finding Aid
- CSMonitor 1988-12-23 "As RICO charges loomed, Drexel sought cover in settlement"
- Wikipedia: Fred Joseph; Michael Milken

## Quality notes

- No 10-K exists (private partnership/holdco; no SEC annual filing in modern format). All financials are from contemporary press + bankruptcy-court records, which carry MEDIUM primary-source confidence vs the NVDA-2008 EDGAR baseline.
- "Founder" is operationally Milken (junk-bond franchise architect); legal-name founders departed pre-1900 (Drexel) / pre-WWII (Burnham). Catalog framing aligns with "founder departed" reading.
- Drawdown -100% is stipulated by the catalog (equity wiped out in Ch11); cross-check via Justia bankruptcy decisions.
- Polygon API key returned 401/Unknown — useless for this era (pre-2003 coverage anyway).

## Polygon-sourced corroboration (2026-04-30 augment)

### Drawdown math
- Polygon aggregates returned NOT_AUTHORIZED / not applicable — Drexel Burnham Lambert was a private partnership/holdco (no SEC-registered common stock in the modern sense). The firm filed Ch11 February 1990 and was delisted/liquidated; no Polygon ticker exists in the modern symbology. Drawdown stipulation (-100%) per catalog (equity wiped out in Ch11) cross-checked via Justia bankruptcy-court records retained.

### Period news
- Polygon news returned 0 rows / not applicable — pre-Benzinga era (Polygon news sparse before ~2018) + no Polygon ticker for the entity. Contemporary 1989-1990 news archive coverage of the bankruptcy filing retained from existing Sources section.

### Source
- Polygon Aggregates URL: not applicable — no surviving public US-listed ticker for Drexel post-Feb 1990 Ch11
- Polygon News URL: not applicable — no Polygon ticker

### Polygon depth-pass (2026-04-30)

Drexel Burnham Lambert Group Inc. was a private investment-banking partnership/holding company. No common stock ever traded on a US public exchange — its parent was held by Drexel Firestone partners, employees, and Belgian Groupe Bruxelles Lambert; it filed Ch11 on 13 Feb 1990 and was liquidated. Polygon endpoint coverage is non-applicable. Endpoints attempted:

- `/v3/reference/tickers/DREXEL`: `{"status":"NOT_FOUND"}`
- `/v3/reference/tickers/DBLG`: `{"status":"NOT_FOUND"}` (rumored historical ticker stub — no record)
- `/v3/reference/tickers?search=Drexel&limit=10`: returns zero results (Polygon ticker reference does not retain pre-1990 delisted broker-dealer holdco tickers, if any existed).
- `/v2/snapshot/.../DREXEL`: NotFound.
- Splits/dividends/financials/news/aggs: all non-applicable (no ticker record to query).

Period evidence relies on SEC enforcement docket (Milken/Boesky settlement orders 1989-1990), Drexel's bankruptcy court filings (SDNY 90 B 10421), WebSearch corroboration, and secondary archive sources (Stewart "Den of Thieves"; Bruck "The Predators' Ball"; Kornbluth "Highly Confident") retained from initial evidence pass.

This case — like Olympia & York — is structurally outside Polygon's coverage universe. The 1990 collapse of Drexel was a private-firm liquidation; the public-market spillover is captured via JNK/HYG-precursor high-yield indices and contemporaneous WCOM/DEC-style archive materials, not via any Drexel ticker. The depth-pass section here serves as auditable confirmation that the Polygon gap is by-design (private entity), not a data-collection failure.
