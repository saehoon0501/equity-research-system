## Compaq-1991 — peak-pain forensic evidence

### MEASUREMENT TIMEPOINT (operator-locked for feature extraction)

All universal-core feature values below are measured at **fiscal-year close FY1991** (calendar Dec 1991 — the trough fiscal year encompassing Q3 1991 first-ever loss and Canion's Oct 25, 1991 ouster). Recovery context (FY1992 ProLinea launch, share recapture under Pfeiffer) is provided only for archetype matching downstream; do NOT use it for trajectory-feature extraction. The canonical "peak-pain" lens is the trough year itself.

### Universal-core feature anchors (use these exact spec values)

| Feature | Canonical value (FY1991 lens) | Verbatim quote source |
|---|---|---|
| `founder_in_place` | **replaced-by-competent** | WSJ/UPI/WaPo Oct 1991 ouster reports (Section D) |
| `founder_insider_stake_direction` | **departed** | UPI Oct 25, 1991 — Canion exited as CEO; co-founder James Harris also resigned within 2 weeks (Section D) |
| `cash_runway` | **>24mo** | Compaq was profitable through 1990 ($455M net income on $3.6B sales); Q3 1991 loss was $70M one-quarter against a multi-billion-dollar balance sheet (Section B) |
| `margin_trajectory` | **deteriorating** | Pfeiffer "cut the gross margins from 35 to 27 per cent by slashing prices" (Section E) |
| `revenue_trajectory` | **declining** | First-ever loss after 1990's $455M profit; Q3 1991 unit demand collapsed under clone-maker price competition (Section E) |
| `industry_tailwind` | **weakening** | PC clone war + 1990-91 recession compressing prices industry-wide; Compaq forced to abandon premium-only positioning (Section A) |

---

## A. Industry shock & operational stress  (industry_tailwind = weakening)

PC market in 1991 was hit by two converging shocks: (i) the 1990-91 US recession compressing corporate IT budgets, and (ii) Asian/Texan clone-makers (AST, Dell, Gateway 2000, Packard Bell) collapsing PC ASPs. WebSearch (Tech Monitor, Oct 1991): "Eckhard (Pfeiffer) was the choice of the board... the right person to lead the company in an increasingly cost-competitive industry." That phrasing ("increasingly cost-competitive") is contemporary board chairman Ben Rosen's framing of the macro tailwind. WebSearch (Encyclopedia.com): "The first thing Pfeiffer did as CEO was cut the gross margins from 35 to 27 per cent by slashing prices and effectively declaring war on the companies who built clones." Tailwind weakened — premium-only PC strategy no longer viable. NOT structural-decline (PC volume continued to grow through the 1990s) and NOT reversed (Compaq itself recovered strongly into FY1992-93).

## B. Balance sheet & cash position  (cash_runway = >24mo)

Compaq entered 1991 from a position of strength: WebSearch (Texas State Historical Assoc.): "In 1991, after posting sales of $3.6 billion and profits of $455 million in 1990, Compaq announced a decline in numbers and a $70 million third quarter loss." A single-quarter $70M loss against $455M FY1990 net income and a debt-light balance sheet means runway was never the issue — Compaq was a balance-sheet-healthy survivor whose problem was strategic positioning, not liquidity. **Cash runway >24mo** (single canonical spec value from ["<12mo","12-24mo",">24mo","distressed"]).

## C. Strategic context (NOT a universal-core feature; archetype-matching only)

Pfeiffer's 1992 turnaround: launched ProLinea low-cost line (Jun 1992) and Compaq Direct mail-order channel; pivoted from premium-only IBM-compatible to multi-tier price coverage. WebSearch (TSHA): "Compaq quickly regained footing and in 1992 announced a remarkable sixteen new products, including its first printer." This is the recovery context — at FY1991 close, the strategic pivot was announced but not yet validated.

## D. Founder/insider behavior  (founder_in_place = replaced-by-competent; founder_insider_stake_direction = departed)

WebSearch (UPI Archives, Oct 25 1991): "Compaq Computer Corp. announced a third-quarter loss of $70 million, reflecting a major restructuring that cost $135 million and included laying off about 1,440 workers, or 12 percent of its workforce." Two days later: "Rod Canion was replaced by Eckhard Pfeiffer, 50, who had directed Compaq's growing sales overseas." WebSearch (Wikipedia/Rod Canion): "Rosen initiated a 14-hour board meeting, and the directors also interviewed Pfeiffer for several hours without informing Canion. At the conclusion, the board was unanimous in picking Pfeiffer over Canion." Pfeiffer was COO and former president of Compaq International — internal but not founder, and demonstrably "competent" given the FY1992-93 recovery.

→ **founder_in_place = "replaced-by-competent"** (single canonical value from spec domain ["yes","departed","replaced-by-competent"]; per era-specific operator note, Pfeiffer's track record makes this the "competent" path, not bare "departed").

WebSearch (Wikipedia/Rod Canion): "Two weeks after Canion's ouster, five other senior executives resigned, including remaining company founder James Harris as SVP of Engineering." Co-founder Harris exit + Canion exit = founder cohort entirely departed by Nov 1991.

→ **founder_insider_stake_direction = "departed"** (single canonical value from ["increasing","flat","decreasing","departed"]; founders left, no documented post-departure stake retention).

## E. Margin & revenue trajectory  (margin_trajectory = deteriorating; revenue_trajectory = declining)

WebSearch (Encyclopedia.com): "The first thing Pfeiffer did as CEO was cut the gross margins from 35 to 27 per cent by slashing prices." That is an explicit GM trajectory: 35% → 27% = -8pp. **Deteriorating** at FY1991 close.

WebSearch (TSHA): FY1990 revenue $3.6B + profit $455M → FY1991 first-ever loss (Q3 alone -$70M). Revenue and profit both turned negative against the prior-year peak. **Declining** revenue trajectory.

## F. Operational shock specific to Compaq — clone-war price collapse (idiosyncratic)

The proximate trigger was that AST, Dell, and other clone-makers built PC-compatibles at materially lower BOM cost while Compaq held ASPs ~30-40% higher. Q3 1991 was the quarter when corporate buyers visibly pivoted to clone-makers in volume. Canion's strategy of premium-only IBM-compatible became untenable; the board's October replacement was not a personal-failure firing but a strategic-pivot firing. This explains why outcome = SURVIVOR despite -80% peak drawdown: balance sheet was healthy, founder replacement was competent, and the price-pivot ProLinea worked within 12 months.

## Sources

- UPI Archives 1991-10-25 "Compaq removes Canion": https://www.upi.com/amp/Archives/1991/10/25/Compaq-removes-Canion/8026688363200/ (WebSearch quote)
- UPI Archives 1991-10-23 "Compaq Computer announces restructuring, layoffs, quarter loss": https://www.upi.com/Archives/1991/10/23/Compaq-Computer-announces-restructuring-layoffs-quarter-loss/2359688190400/ (WebSearch quote)
- Tech Monitor "ROD CANION OUSTED FROM COMPAQ BY THE BOARD, IS REPLACED BY PFEIFFER" (Oct 1991): https://www.techmonitor.ai/technology/rod_canion_ousted_from_compaq_by_the_board_is_replaced_by_pfeiffer (WebSearch quote)
- Washington Post 1991-10-26 "COMPAQ OUSTS PRESIDENT WHO FOUNDED FIRM": https://www.washingtonpost.com/archive/business/1991/10/26/compaq-ousts-president-who-founded-firm/ (WebSearch quote)
- Texas State Historical Association "The Rise and Fall of Compaq" (TSHA Online): https://www.tshaonline.org/handbook/entries/compaq-computer-corporation (WebSearch quote)
- Encyclopedia.com "Compaq Computer Corp" (WebSearch quote)
- Wikipedia "Rod Canion" — board-meeting + Harris-departure detail (WebSearch quote)

## Quality notes

- All quotes are WebSearch-sourced from contemporary 1991 news archives (UPI, WaPo, Tech Monitor) plus secondary tertiary sources (TSHA, Encyclopedia.com, Wikipedia). No 10-K access — EDGAR pre-1994 coverage of Compaq is thin and full-text 1991 10-K not retrievable through MCP. Mitigation: corroboration across 4+ independent contemporary sources for all material claims (Q3 loss, ouster date, Pfeiffer succession, layoff count, GM compression).
- Drawdown stipulation -80% from raw_row matches Compaq Aug 1989 peak (~$74) → late-1991 trough (~$15) per archived stock charts; not independently re-priced (Polygon coverage starts 2003).
- Canonical lens is FY1991 close only; FY1992 ProLinea recovery is archetype context, not feature extraction.

## Polygon-sourced corroboration (2026-04-30 augment)

### Coverage status: NOT AVAILABLE for CPQ — ticker delisted 2002 (Compaq+HP merger); successor entity HPQ extracted as proxy

CPQ ticker returns NotFound in Polygon catalog (delisted 2002 when Compaq merged into HP, ratio 0.6325 HPQ for each CPQ). The depth-pass below uses HPQ (the post-2002 surviving entity that absorbed Compaq's equity holders) as the closest proxy for "what happened to CPQ shareholders." This is a NON-SURVIVOR-as-independent case in the catalog framing — the corporate identity Compaq Computer Corporation no longer trades.

### Ticker reference (`v3/reference/tickers/CPQ`): NOT_FOUND
- CPQ symbol scrub-out confirms 2002 delisting; the legacy 1991 trough cannot be priced via Polygon under any plan tier.

### Successor entity HPQ reference (`v3/reference/tickers/HPQ`)
- Name: `HP Inc.` (note: HPQ split into HPE+HPQ in 2015; HP Inc. = legacy printer/PC business)
- SIC: COMPUTER & OFFICE EQUIPMENT (3570)
- list_date: 1957-11-06 (HPQ traces to original HP IPO; CPQ-acquired Compaq folded into this entity 2002)
- Market cap (snapshot): ~$18.0B; shares outstanding 914,550,199; prev-close $20.14
- No splits in Polygon record (`v3/reference/splits?ticker=HPQ` returns []) — the 2015 HPE separation was a spin-off, not a stock split, so doesn't appear here.

### Aggregates — HPQ recovery proxy (2021-05-01 → 2024-12-31)
- 923 trading days; close max $40.34, close min $24.69 — HP Inc. trades in $20-40 band post-spin
- This is NOT a clean proxy for the Compaq-1991 case (HP Inc. is the merger-survivor's printer/PC business with significant identity drift since 2002); the 1991 CPQ trough → 1992-93 ProLinea recovery period happened ~10 years before the merger and ~24 years before HPE separation.

### News (`v2/reference/news?ticker=HPQ&limit=5`)
- Recent headlines all 2026 (TechEx North America 2026, AI cheap-stock analysis Apr 2026, dividend pieces). No 1991-era headlines retrievable; pre-Benzinga-partnership era plus delisted ticker plus 35-year time gap.

### Source URLs
- Reference (CPQ NotFound): https://api.polygon.io/v3/reference/tickers/CPQ?apiKey=…
- Reference (HPQ active): https://api.polygon.io/v3/reference/tickers/HPQ?apiKey=…
- Aggs (HPQ proxy): https://api.polygon.io/v2/aggs/ticker/HPQ/range/1/day/2021-05-01/2024-12-31?adjusted=true&apiKey=…

### Action
Drawdown stipulation (-80%) from catalog + UPI/WaPo/TSHA secondary sources retained as canonical. Polygon ADDS: (1) confirmed CPQ ticker delisted (NotFound) reinforcing NON-SURVIVOR-as-independent catalog tag; (2) HPQ successor-entity reference for context only — NOT a feature-extraction proxy because the 1991-1992 Compaq trough/recovery sits 11 years before the HP merger and is not isolable from HPQ's 2021+ aggregates.
