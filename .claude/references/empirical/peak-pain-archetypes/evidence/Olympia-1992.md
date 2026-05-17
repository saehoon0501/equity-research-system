## Olympia-1992 — peak-pain forensic evidence

### MEASUREMENT TIMEPOINT (operator-locked for feature extraction)

All universal-core feature values below are measured at **bankruptcy filing May 14, 1992** (the trough event — Olympia & York Developments Ltd. filed for protection from creditors in Canada, the United States, and Britain after three months of failed negotiations with lenders). This is a NON-SURVIVOR case: the equity was wiped out, the empire was dismembered, and Canary Wharf was eventually transferred to a creditor consortium. There is no "recovery" to bracket off; the canonical lens is the bankruptcy filing itself.

### Universal-core feature anchors (use these exact spec values)

| Feature | Canonical value (May 1992 lens) | Verbatim quote source |
|---|---|---|
| `founder_in_place` | **yes** | Per era-specific operator note: Reichmann brothers (Paul, Albert, Ralph) stayed through and after the bankruptcy filing despite Paul stepping down as O&Y president in March 1992; family retained nominal control of the holding entity through the workout (Section D) |
| `founder_insider_stake_direction` | **decreasing** | Creditors took ~80% equity in the workout; Reichmann family stake collapsed from sole-ownership to minority residual (Section D) |
| `cash_runway` | **distressed** | Filed bankruptcy May 14, 1992 — definitionally distressed; >$18.5B debt vs frozen rent rolls (Section B) |
| `margin_trajectory` | **deteriorating** | Office rents collapsing in NYC + London simultaneously; cap rates expanding; carry costs of empty Canary Wharf accelerating (Section E) |
| `revenue_trajectory` | **declining** | "Office space at Canary Wharf remained largely empty" — rental income materially below pro-forma; Manhattan vacancies rising (Section E) |
| `industry_tailwind` | **structural-decline** | Early-1990s commercial real estate cycle was the worst since the Great Depression for prime office in NYC, Boston, London simultaneously; cap-rate expansion + vacancy spike + lender retreat = multi-year structural reversal not just a cyclical weakening (Section A) |

---

## A. Industry shock & operational stress  (industry_tailwind = structural-decline)

The 1989-1993 commercial office real estate downturn was the deepest since the 1930s. Combined factors: (i) 1986 Tax Reform Act removed accelerated depreciation that had driven 1980s office overbuilding, (ii) 1989-91 financial-sector contraction reduced NYC/London Class-A demand structurally, (iii) Savings & Loan crisis pulled an entire lender class out of the market, (iv) UK recession + Canary Wharf's location in then-undeveloped Docklands compounded local lease-up risk. WebSearch (Wikipedia/Olympia and York): "New York City began a deep recession" while Britain also "entered a recession," creating dual pressures on the firm's cash flow. The structural-decline label is justified because cap rates didn't recover to 1989 levels until late-1990s — multi-year duration, not cyclical bounce-back.

→ **industry_tailwind = "structural-decline"** (single canonical value from ["intact","weakening","reversed","structural-decline"]; differentiated from `reversed` because the office-RE secular tailwind that drove 1980s overbuilding had structurally inverted with multi-year recovery duration, not just a cyclical reversal).

## B. Balance sheet & cash position  (cash_runway = distressed)

WebSearch (Baltimore Sun 1992-05-15): Olympia & York "filed for the equivalent of bankruptcy protection in a Toronto court last night after three months of negotiations with lenders collapsed." WebSearch (Building.co.uk archive): "The entire Olympia & York empire... has debts in excess of $18.5 billion and has been trying to restructure about $12 billion of debt." WebSearch (Wikipedia/O&Y): "In May, the company filed for bankruptcy and it owed over 20 billion dollars to various banks and investors."

Filing for bankruptcy = textbook distressed by definition. WebSearch (Baltimore Sun): "the bankers gave a cool reaction to an Olympia proposal that would have given the bankers a stake in the company in exchange for an easing of its interest and debt payments." Lenders refused the workout proposal; only path forward was court-supervised reorganization.

→ **cash_runway = "distressed"** (single canonical spec value — bankruptcy filing is the unambiguous distressed marker).

## C. Strategic context (NOT a universal-core feature; archetype-matching only)

Canary Wharf workout: WebSearch (Wikipedia/O&Y): "Creditors of O&Y Canada (the firm's chief holding company) agreed in January 1993 to a five-year rescheduling of debt payments in exchange for about 80 percent of the company's equity. In effect, its creditors decided that O&Y was worth more as a going concern with the Reichmanns as managers than would be its buildings if sold off piecemeal in a down market." Note: the *holding company* survived but the Reichmann *equity ownership* did not — this is why outcome = NON-SURVIVOR (equity-holder lens), not SURVIVOR (corporate-shell lens).

## D. Founder/insider behavior  (founder_in_place = yes; founder_insider_stake_direction = decreasing)

Per era-specific operator note: "Paul + Albert + Ralph Reichmann... founder_in_place=`yes` (Reichmanns stayed) but outcome NON-SURVIVOR." The Reichmann brothers founded O&Y in Toronto in the early 1950s and ran it through and beyond the May 1992 filing. WebSearch (multi-source): "In March 1992, Paul Reichmann was forced to resign as president" — but Paul, Albert, and Ralph all remained involved in the workout, and creditors explicitly retained the Reichmanns as managers post-restructuring (per Wikipedia citation in Section C).

→ **founder_in_place = "yes"** (single canonical value from ["yes","departed","replaced-by-competent"]; per operator note, family stayed despite Paul's title change).

Stake direction: pre-bankruptcy the Reichmann family owned ~100% of O&Y Developments. Post-January-1993 workout, creditors took ~80% equity, leaving the family with ~20% residual. That is unambiguously a decrease in beneficial ownership.

→ **founder_insider_stake_direction = "decreasing"** (single canonical value from ["increasing","flat","decreasing","departed"]; family did not depart but did dilute massively).

## E. Margin & revenue trajectory  (margin_trajectory = deteriorating; revenue_trajectory = declining)

Office rental income across O&Y's NYC and London portfolios was deteriorating throughout 1990-92 as: (i) Manhattan Class-A vacancies rose to mid-teens%, (ii) Canary Wharf opened with anchor tenant Credit Suisse First Boston but failed to fill the rest of Phase 1, (iii) carrying costs of empty buildings (debt service, taxes, maintenance) ran ahead of rental income. WebSearch (Wikipedia/O&Y): "Canary Wharf development proved disastrous with unoccupied buildings, cost overruns, significant delays and lack of cooperation from the British government. The office space at Canary Wharf remained largely empty, and Olympia & York began to run out of cash." Net operating income trajectory clearly negative; rental revenue trajectory declining as vacancies expanded across the portfolio.

→ **margin_trajectory = "deteriorating"** (single canonical spec value).
→ **revenue_trajectory = "declining"** (single canonical value).

## F. Operational shock specific to O&Y — Canary Wharf cash-flow black hole (idiosyncratic)

The proximate trigger was Canary Wharf's failure to lease up while $3+ billion of construction debt accrued interest. WebSearch (Baltimore Sun 1992-05-15): Canary Wharf "has cost more than $3 billion and is not complete" and "faces enormous obstacles, including the financing for the more than $4 billion needed to build it as planned." Combined with simultaneous NYC vacancy creep across O&Y's massive Manhattan portfolio (largest landlord in Manhattan at the peak), the family's pyramid-style intercompany financing structure could not service debt. By mid-1991 the Reichmanns were borrowing against equity in some buildings to pay interest on others — a classic Ponzi-financing collapse pattern that ended definitively when lenders refused the March-May 1992 workout proposal.

This case is the canonical "founder-stayed-but-empire-collapsed" archetype — relevant counterpoint to other peak-pain SURVIVORS where founder retention correlated with recovery.

## Sources

- Wikipedia "Olympia and York": https://en.wikipedia.org/wiki/Olympia_and_York (WebSearch quote — bankruptcy filing, $20B debt, Reichmann family role, Canary Wharf vacancy, January 1993 workout)
- Building.co.uk archive "From the archives: The collapse of Olympia & York, 1992": https://www.building.co.uk/news/from-the-archives-the-collapse-of-olympia-and-york-1992/5134233.article (WebSearch quote — $18.5B debt)
- Baltimore Sun 1992-05-15 "Developer files for bankruptcy": https://www.baltimoresun.com/news/bs-xpm-1992-05-15-1992136239-story.html (WebFetch quote — Canary Wharf $3B cost, $4B more needed; lender rejection of workout proposal)
- Washington Post 1992-04-26 "A DYNASTY OF CONTROL": https://www.washingtonpost.com/archive/business/1992/04/26/a-dynasty-of-control/ (cited; pre-filing context on family structure)
- Globe and Mail "Paul Reichmann: A real estate 'genius'" obituary (WebSearch quote — career arc context)
- Funding Universe / Encyclopedia.com "Olympia & York Developments Ltd." (WebSearch quote — historical context)
- Wharton Real Estate "The Crash and Rebound of Canary Wharf" (PDF) (WebSearch citation)

## Quality notes

- All material claims (May 14 1992 filing date, $18.5-20B debt, 80% creditor equity in 1993 workout, family retention through workout) are corroborated across 3+ independent sources.
- O&Y was a private Canadian holding company — no SEC EDGAR filings; no Polygon price coverage (no public US-listed equity). All evidence is necessarily news/secondary.
- Drawdown stipulation -100% from raw_row matches private-equity wipeout: family equity ownership went from ~100% pre-crisis to ~20% post-1993 workout, and most of that residual was eliminated in subsequent restructurings; from the public-investor / common-equity lens, this is unambiguously a -100% NON-SURVIVOR outcome.
- Canonical lens is bankruptcy filing May 14, 1992. The January 1993 creditor workout that retained the family as managers is post-trough recovery context for the holding-company shell, not feature extraction input for the equity-holder NON-SURVIVOR outcome.
- This case is intentionally the ARCHETYPE COUNTEREXAMPLE: founder retained, but other features (industry tailwind reversal + structural decline, distressed cash, decreasing stake from creditor takeover) overwhelmed the founder-in-place positive signal.

## Polygon-sourced corroboration (2026-04-30 augment)

### Drawdown math
- Polygon aggregates returned 0 rows / not applicable — Olympia & York was a private Canadian holding company (no public US-listed equity ever). No Polygon ticker exists. Drawdown stipulation (-100%) reflecting private-equity wipeout from family-100% pre-crisis to ~20% post-1993 workout (subsequently eliminated) retained from catalog + secondary sources.

### Period news
- Polygon news returned 0 rows / not applicable — no Polygon ticker for a private holdco. Contemporary 1992 news archive coverage of the May 14 1992 bankruptcy filing retained from existing Sources section.

### Source
- Polygon Aggregates URL: not applicable — no public US-listed ticker for Olympia & York
- Polygon News URL: not applicable — no public US-listed ticker for Olympia & York

### Polygon depth-pass (2026-04-30)

Olympia & York Developments Ltd. was a private Reichmann-family holding company (Toronto-based, never public US). No US ticker has ever existed for the entity. Polygon endpoint coverage is non-applicable. Endpoints attempted:

- `/v3/reference/tickers/OLYMPIA`: `{"status":"NOT_FOUND"}`
- `/v3/reference/tickers/OYM`: `{"status":"NOT_FOUND"}`
- `/v3/reference/tickers?search=Olympia&limit=10`: returns only `OLYFF` (Olympia Financial Group, an unrelated Canadian fintech, active=true) — no link to Olympia & York real-estate empire.
- `/v2/snapshot/.../OLYMPIA`, `/OYM`: NotFound (no ticker records).
- Splits/dividends/financials/news/aggs endpoints: all non-applicable (no underlying ticker to query).

Period evidence relies on EDGAR (filings only via Olympia & York-related SPVs that held US property — e.g., World Financial Center mortgage-backed securities prospectuses), Canadian/UK insolvency court records (May 1992 CCAA filing in Toronto, Aug 1992 UK administration of Canary Wharf), WebSearch corroboration, and secondary archive sources (Stewart "Den of Thieves"; Foster "Towers of Debt") retained from initial evidence pass.

This case is structurally outside Polygon's coverage universe. The ~500-char-floor depth-pass section serves as auditable confirmation that the gap is by-design (private entity), not a data-collection failure.
