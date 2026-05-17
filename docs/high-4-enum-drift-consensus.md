# HIGH-4 Enum-Drift Consensus

**Session date:** 2026-05-16
**Session purpose:** Resolve the `summary_code` enum drift across `research-company.md`, `pm-supervisor.md`, and the inventerd `summary_code_operator_semantic` field that surfaced in the MSFT 2026-05-15 run audit. Lock the 4-bin vs 5-bin question, decide the fate of the WATCH/PASS lifecycle semantics, and specify the redesigned `counterfactual_ledger` schema with market-standard parameter values.
**Status:** **LOCKED** — all Tier A claims have parameter values; push-back #1 overridden, push-back #2 confirmed.
**Companion artifact:** the 4-subagent research dispatch (Phase 3 of `/research`) produced citation-backed defaults for the ledger schema; sources listed at end.

---

## 1. Operator profile (captured this session)

| Dimension | Value |
|---|---|
| Decision style | Simplicity-first. Picked the simplest valid option at every multiple-choice juncture (Q1=a, Q3=a, Q5=a). |
| Tradeoff stance | Accepts cost / complexity tradeoffs in favor of architectural simplicity even when proposed alternatives (e.g., lighter-cadence sentinel for distress names; bin-specific formulas) would be defensible. |
| Evidence threshold | Rejected my Q5 initial defaults and demanded market-standard research before locking. Confirmed the research-grounded revision (push-back #2). Will not lock parameter values without a citable source when a source exists. |
| Override pattern | Issued one explicit override (push-back #1 — strict uniform monitoring even for distress names) and one explicit confirm (push-back #2 — research-backed sector-ETF + uniform-formula + bin-metadata). |
| Domain-jargon literacy | Engaged with schema fields and engineering analogies (ordinal vs tag-list; Brinson-Fachler) without requesting plain-language re-statement. Did not need term-by-term definition this session. |
| Stated session principle | **"All monitoring should be applied to marked tickers no matter the outcomes."** First-order rule for the lifecycle redesign. |
| Data-availability discipline | Explicit caveat: "If the formula requires non-obtainable data input should reject." Applied across the research dispatch. |

---

## 2. The position / thesis (refined)

The HIGH-4 audit finding identified three spec drift surfaces:

1. **`pm-supervisor.md` line 417** declares the canonical JSON envelope `summary_code` enum as **4-bin** (`BUY | HOLD | TRIM | SELL`).
2. **`research-company.md` §7 line 346** declares the operator-facing output template as **5-bin** (`ADD | WATCH | HOLD | PASS | REJECT`).
3. **`pm-supervisor.md` line 307** contains a stray "WATCH" reference that doesn't appear in either enum.

The MSFT 2026-05-15 run papered over this by inventing a `summary_code_operator_semantic: "WATCH"` field with no spec basis — flagged HIGH by the audit.

**Refined resolution thesis:** the JSON envelope is canonically 4-bin; the 5-bin operator vocabulary is dissolved (not bridged); the lifecycle concept that the 5-bin tried to express (WATCH ≠ HOLD ≠ PASS) is **deleted from the system** rather than relocated. Monitoring becomes uniform across every ticker that completes `/research-company`, regardless of `summary_code`. The `counterfactual_ledger` is redesigned to write a row for every research run, with research-backed defaults (sector-ETF benchmark, 90d/1y/3y/5y windows, uniform raw active-return formula, bin info preserved as `summary_code` column for stratified postmortem queries).

---

## 3. Locked consensus items

### Consensus Item #1 — `summary_code` canonical 4-bin

**Claim:** The JSON envelope `summary_code` field is canonically the 4-bin enum `BUY | HOLD | TRIM | SELL` per `pm-supervisor.md` §8 line 417. No other values are permitted. The invented `summary_code_operator_semantic` field (MSFT 2026-05-15 surface) is forbidden.

**Parameter values:**
- Canonical enum: `{BUY, HOLD, TRIM, SELL}` — case-sensitive.
- `summary_code_operator_semantic` field: **deleted from the system.** Evaluator HG-23 (envelope-shape) is updated to REJECT any envelope containing this field.
- `pm-supervisor.md` line 307 stray "WATCH" → replaced with "HOLD" with `sleeve_cap_check.status = VIOLATION_DEFENSIVE_CHECK`.

**Reasoning:** the 4-bin already exists in the spec and matches the action-axis semantic that downstream execution code naturally consumes. Bridging to 5-bin via the invented field created an unbounded surface for synthesizer judgment-creep (the same failure mode as HIGH-1). Killing the field forces the system to express any "lifecycle" semantics in spec-sanctioned places only.

### Consensus Item #2 — Uniform monitoring (lifecycle redesign mandate)

**Claim:** Every ticker that completes a `/research-company` run and receives a `summary_code` emission is continuously monitored by `/daily-monitor` and downstream sweeps, regardless of which bin it received. There is no "drops off the watchlist" semantic.

**Parameter values:**
- Monitoring trigger: existence of any row in `counterfactual_ledger` (i.e., the ticker was ever researched).
- Cadence: uniform daily sweep for all monitored tickers.
- No bin-conditional exemption — including distress-name (Piotroski F<3 OR Altman Z''<1.1) cases. See push-back #1 below.

**Reasoning:** uniform monitoring eliminates confirmation bias in the calibration loop — the system learns equally from "we said NO and the name 10x'd" cases as from "we said YES and the name 2x'd." This is the operator's stated principle for the redesign.

### Consensus Item #3 — Lifecycle concept eliminated

**Claim:** The 5-bin operator vocabulary (`ADD | WATCH | HOLD | PASS | REJECT`) is fully dissolved. No `monitoring_cadence`, `monitoring_tags`, `lifecycle_state`, or similar auxiliary lifecycle fields are added to the envelope. `summary_code` + `conviction` + `position_held` (existing fields) are the only state any downstream consumer reads.

**Parameter values:**
- Removed concepts: ADD, WATCH, PASS, REJECT (as bins). Their semantics are absorbed into `summary_code` (action axis only) and `counterfactual_ledger` (universal trigger).
- No replacement fields. Strict deletion.
- `research-company.md` §7 operator-output template collapses to 4-bin display: outputs are `BUY / HOLD / TRIM / SELL` for human eyes too.

**Reasoning:** the operator chose deletion (Q3 option a) over derived-display (b), tag-list (c), or cadence-dial (d) — explicitly to avoid expressing the same information twice in different vocabularies. Risk of drift between canonical and operator-facing surfaces is eliminated by having only one.

### Consensus Item #4 — `counterfactual_ledger` universal trigger

**Claim:** A `counterfactual_ledger` row is written for **every** `/research-company` run that emits a `summary_code` (i.e., every BUY/HOLD/TRIM/SELL outcome). The previous PASS/REJECT-conditional trigger is fully retired.

**Parameter values:**
- Trigger condition: `summary_code IS NOT NULL` on the pm-supervisor envelope at run completion.
- Row count per run: 4 (one per window — see Consensus Item #5).
- No exemption for any `summary_code` value.

**Reasoning:** the old trigger was bin-conditional; under Consensus Item #2's uniform-monitoring principle the trigger generalizes to universal. Ledger row growth ~5-10× vs prior assumption; this is accepted per push-back #1 override (operator chose strict uniform over cost-management exception).

### Consensus Item #5 — `counterfactual_ledger` schema (research-grounded)

**Claim:** The ledger uses research-backed defaults for benchmark, windows, formula, and risk-adjustment. The math is uniform across `summary_code` bins; bin-conditional interpretation lives at the postmortem-query layer, not the schema layer.

**Parameter values:**

| Field | Value | Source |
|---|---|---|
| Benchmark | Sector ETF (SPDR sector series mapped from GICS sector) | Brinson-Fachler attribution [⁷]; isolates stock-picking from sector-allocation skill |
| Secondary benchmark | SPY (sanity reference, nullable) | Cross-check only; not load-bearing for calibration |
| Windows | `90d / 1y / 3y / 5y` (4 rows per run) | GIPS, Morningstar, CFA, Carhart 1997 — canonical trio is 1y/3y/5y; 90d added for catalyst tracking |
| Row-level formula | `vs_sector_etf_return_pct = ticker_return_over_window − sector_etf_return_over_window` (uniform across bins) | CFA convention: ONE formula + bin as metadata; single-name attribution uses raw active return [¹][⁵] |
| Risk adjustment (row-level) | None — raw active return | CFA Level III reserves Sharpe/IR/Jensen's for portfolio-level [¹²][¹³]; single-name single-window risk-adjusted measures are statistically unreliable |
| Risk adjustment (aggregate-level) | Information Ratio computed in `/parameters-review` ACROSS rows, not per-row | Goodwin (1998) [¹²]; IR's denominator needs a multi-decision time series |
| Bin-specific interpretation | At postmortem-query layer (`WHERE summary_code = '...'`) | Inalytics random-counterfactual approach rejected: requires unobtainable "random alternative" baseline; Perold Implementation Shortfall rejected: requires intraday execution data we don't have |

**Schema:**

```sql
CREATE TABLE counterfactual_ledger (
  ledger_id            UUID PRIMARY KEY,
  ticker               TEXT NOT NULL,
  run_id               UUID NOT NULL,
  research_date        DATE NOT NULL,
  summary_code         TEXT NOT NULL,                     -- BUY | HOLD | TRIM | SELL
  conviction           TEXT NOT NULL,                     -- HIGH | MEDIUM | LOW
  gics_sector          TEXT NOT NULL,
  benchmark_etf        TEXT NOT NULL,                     -- e.g. 'XLK'
  window               TEXT NOT NULL,                     -- 90d | 1y | 3y | 5y
  measurement_date     DATE NOT NULL,                     -- research_date + window
  ticker_return_pct          NUMERIC NOT NULL,
  benchmark_return_pct       NUMERIC NOT NULL,
  vs_sector_etf_return_pct   NUMERIC NOT NULL,            -- primary calibration signal
  spy_return_pct             NUMERIC,                     -- nullable
  vs_spy_return_pct          NUMERIC,                     -- nullable; sanity reference
  envelope_id          UUID,                              -- ref to pm-supervisor envelope row
  UNIQUE (ticker, run_id, window)
);
```

**Reasoning:** per Subagent A's research, bin-specific formulas are NOT canonical for single-name postmortem — the CFA-canonical pattern is uniform formula + bin metadata. Per Subagent B, the canonical window trio is 1y/3y/5y (plus 90d for catalyst tracking); 30d and 6mo are firm-internal only. Per Subagent C, sector-ETF benchmark is the Brinson-Fachler convention for isolating stock-picking from sector-allocation skill. Per Subagent D, raw active return is the single-name single-window convention; risk-adjusted measures are reserved for portfolio aggregation. The `summary_code` column already preserves bin info for stratified queries; no separate `bin_conditional_metric` field is needed.

### Postmortem-query interpretation map (queryside, not schema-side)

Same uniform `vs_sector_etf_return_pct` value, different interpretation by bin:

| `WHERE summary_code = ` | Positive value means | Negative value means |
|---|---|---|
| `'BUY'` | Executed position outperformed sector — good call | Executed position underperformed — bad entry |
| `'TRIM'` | Trim was premature; held would have outperformed (trim regret) | Trim was justified — sector caught up |
| `'HOLD'` | Missed opportunity — would-be position would have outperformed | Correct hold — would-be position underperformed |
| `'SELL'` | Sold too early — held would have outperformed (sell regret) | Sell was justified — name underperformed sector |

---

## 4. Push-backs resolved

### Push-back #1 — overridden by operator

**The push-back:** distress names (Piotroski F<3 OR Altman Z''<1.1) should get a lighter sentinel monitoring cadence (e.g., monthly) instead of daily, because their base-rate probability of becoming a buy candidate is structurally low.

**Operator's override:** strict uniform daily monitoring even for distress names. Linear cost growth (~$55k/year at 300 monitored names with daily Sonnet sweeps) is accepted as a values judgment in favor of architectural simplicity. Learning signal preserved via uniform `counterfactual_ledger` write — "we screened it out, the name 5x'd anyway" is still captured at the same cadence as all other rows.

**Status:** push-back closed by override. No cadence-gradient handling in the schema. Archive policy for genuinely-inactive tickers deferred (see §6 deferred items).

### Push-back #2 — confirmed by operator (research-grounded)

**The push-back:** the operator's Q4(c) hybrid choice (uniform `vs_spy_return_pct` + per-bin `bin_conditional_metric`) was based on my Q4 options that assumed bin-specific formulas were canonical. The research-dispatch refuted this:

- CFA / Brinson-Hood-Beebower attribution: ONE formula across all bins, bin stored as metadata [¹]
- Inalytics / Akepanidtaworn random-counterfactual approach: requires a "random alternative" baseline that's complex to construct and doesn't fit our "every research run" trigger model [³][⁴]
- Perold Implementation Shortfall: bin-specific but requires intraday execution data we don't have [⁶]
- Mauboussin: prescribes process-tracking, NOT formulas [⁵]

**Proposed fix:** revert to Q4(a)-shape (single uniform formula, bin info preserved as `summary_code` column) but with sector-ETF benchmark instead of SPY (Brinson-Fachler convention).

**Operator confirmed.** Push-back #2 closed. Schema reflects the revised structure (Consensus Item #5).

---

## 5. Critical architectural findings

**AF-1 — Lifecycle concept dissolution is irreversible.** Once the 5-bin operator vocab is removed and the lifecycle concept deleted, re-introducing it would require either (a) re-expanding the canonical enum (5-bin or 6-bin) or (b) adding auxiliary fields the operator explicitly rejected. Future requirements for "name-on-watch-with-explicit-triggers" semantics will need to live in `tl_dr.reevaluation_triggers` (existing field) or in dashboard-side query logic, not as a first-class envelope field.

**AF-2 — `counterfactual_ledger` is now the system's universal observation surface.** Every research run produces 4 ledger rows. The ledger is the single source of truth for calibration / `/parameters-review` aggregation / postmortem queries. Schema stability is load-bearing; future changes require migration discipline.

**AF-3 — Sector-ETF benchmark requires GICS sector mapping discipline.** The `gics_sector` and `benchmark_etf` columns are populated at ledger-write time and must remain consistent over the row's lifetime (no point-in-time sector reclassification). Tickers that change sector (rare but real) get a new sector mapping prospectively; historical rows retain the original mapping.

**AF-4 — IR computation deferred to `/parameters-review` layer.** Row-level math is raw active return only. Information Ratio aggregation across rows (per Goodwin 1998) happens in the quarterly recalibration pass, not at row-write time. This keeps the ledger schema cheap and the calibration math statistically valid (IR's denominator needs multi-row tracking error).

---

## 6. Design changes from prior baseline

| Surface | Before (pre-session) | After (locked) | Driver |
|---|---|---|---|
| `summary_code` enum | 4-bin in `pm-supervisor.md` but 5-bin in `research-company.md` §7 | 4-bin everywhere | Consensus Item #1 |
| `summary_code_operator_semantic` | Invented field in MSFT 2026-05-15 run | Field forbidden; HG-23 REJECTs | Consensus Item #1 |
| `pm-supervisor.md` line 307 "WATCH" | Stray reference inconsistent with enum | Replaced with HOLD + VIOLATION_DEFENSIVE_CHECK | Consensus Item #1 |
| `research-company.md` §7 operator-template | Lists ADD/WATCH/HOLD/PASS/REJECT | Collapses to BUY/HOLD/TRIM/SELL | Consensus Item #3 |
| `/daily-monitor` ticker scope | Implicitly bin-conditional (e.g., PASS drops off) | Universal — every ticker that ever completed `/research-company` | Consensus Item #2 |
| `counterfactual_ledger` trigger | PASS or REJECT only | Every research run | Consensus Item #4 |
| `counterfactual_ledger` benchmark | (implicit) SPY | Sector ETF via GICS mapping | Consensus Item #5 + research |
| `counterfactual_ledger` windows | (implicit) ad hoc | 90d / 1y / 3y / 5y (industry-canonical) | Consensus Item #5 + research |
| `counterfactual_ledger` formula | (none defined) | Uniform raw `ticker_return − sector_etf_return` | Consensus Item #5 + research |
| `counterfactual_ledger` risk-adjustment | (none defined) | None at row level; IR at aggregate (`/parameters-review`) | Consensus Item #5 + research |

---

## 7. Deferred items

| Item | Activation trigger |
|---|---|
| **Archive policy for inactive monitored tickers.** Tickers with no material activity for N years could be demoted to a lighter sentinel sweep. Not blocking; cost growth from uniform monitoring is linear and currently manageable at ~$55k/year at 300 names. | Trigger: total monitored-ticker count exceeds 500 OR annualized monitoring cost exceeds $100k. Re-open as a separate `/grill-me` session at that point. |
| **`/parameters-review` Information Ratio aggregation logic.** The aggregate-level risk-adjusted measure (Goodwin 1998 IR formula across ledger rows) is research-supported but not currently load-bearing for calibration. Can be added when calibration signal explicitly needs risk adjustment. | Trigger: operator observes that raw-alpha calibration history is producing miscalibrated forecast distributions OR `/parameters-review` recommends risk-adjusted re-weighting. |
| **Peer-median benchmark as secondary cross-check.** Subagent C noted peer median is theoretically tighter than sector ETF (better sub-industry control) but introduces peer-set construction risk. Currently not in the schema; can be added as a third optional benchmark column. | Trigger: postmortem analysis shows sector-ETF benchmark systematically misclassifies a specific name type (e.g., mega-cap conglomerates where sector mapping is ambiguous). |
| **Mauboussin-style process journaling integration.** Subagent A flagged that Mauboussin prescribes process-tracking (ex-ante expectations + ex-post review) rather than outcome formulas. The current ledger is outcome-only; a process-journal column could capture the ex-ante decision rationale for richer postmortem comparison. | Trigger: operator observes that ledger postmortems lack the "what did we believe at the time" context needed to distinguish bad-process-good-outcome from good-process-bad-outcome. |

---

## 8. What's locked vs what's open

**Locked (this session):**
- All 5 Tier A claims have explicit parameter values (Consensus Items #1-#5).
- All push-backs resolved (one override, one confirmation).
- `counterfactual_ledger` schema is fully specified in DDL form.
- Postmortem-query interpretation map is documented.

**Open (next sessions / implementation):**
- Implementation of the spec changes across `research-company.md`, `pm-supervisor.md`, `evaluator.md` (HG-23 update), and the `counterfactual_ledger` migration. These are mechanical edits driven by this consensus; no further design decisions required.
- The 4 deferred items in §7 are scoped to specific triggers; none are blocking.

**No open items remain in scope for the HIGH-4 enum-drift section.** This section closes.

---

## 9. Source citations (from the Phase 3 research dispatch)

[¹] Carl Bacon, *Performance Attribution* — CFA Institute Research Foundation lit review (2019) — https://rpc.cfainstitute.org/sites/default/files/-/media/documents/book/rf-lit-review/2019/rflr-performance-attribution.pdf
[²] Brinson-Hood-Beebower (1986) / Performance attribution overview — https://en.wikipedia.org/wiki/Performance_attribution
[³] Akepanidtaworn, Di Mascio, Imas, Schmidt — *Selling Fast and Buying Slow*, NBER WP 29076 — https://www.nber.org/papers/w29076
[⁴] *Selling Fast and Buying Slow*, Journal of Finance 2023 — https://onlinelibrary.wiley.com/doi/10.1111/jofi.13271
[⁵] Mauboussin on decision-making under uncertainty, CFA Institute interview — https://rpc.cfainstitute.org/blogs/enterprising-investor/2012/decision-making-for-investors-under-uncertainty
[⁶] Perold (1988), *Implementation Shortfall* — https://www.cis.upenn.edu/~mkearns/finread/impshort.pdf
[⁷] Brinson-Fachler attribution mechanics — https://breakingdownfinance.com/finance-topics/modern-portfolio-theory/brinson-model/
[⁸] CFA Institute GIPS overview (2026 refresher) — https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/overview-of-the-global-investment-performance-standards
[⁹] Morningstar Rating for Funds methodology (Aug 2021) — https://www.morningstar.com/content/dam/marketing/shared/research/methodology/771945_Morningstar_Rating_for_Funds_Methodology.pdf
[¹⁰] Birru et al., *Who Benefits from Analyst "Top Picks"*, NBER WP 28038 — https://www.nber.org/system/files/working_papers/w28038/w28038.pdf
[¹¹] Carhart (1997), *On Persistence in Mutual Fund Performance*, J. Finance 52(1):57–82 — https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1997.tb03808.x
[¹²] Goodwin (1998), *The Information Ratio*, Financial Analysts Journal — https://rpc.cfainstitute.org/research/financial-analysts-journal/1998/the-information-ratio
[¹³] Sharpe ratio single-stock limitations — https://en.wikipedia.org/wiki/Sharpe_ratio
[¹⁴] Berk & van Binsbergen (2015), *Measuring Skill in the Mutual Fund Industry*, JFE 118(1):1–20 — https://www.sciencedirect.com/science/article/abs/pii/S0304405X15000628
[¹⁵] Kenneth R. French Data Library (daily FF factors) — https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html

**Source-quality note:** Subagent C's primary-source ratio came in at 29% (below the 70% target) because the CFA Institute primary PDFs returned binary content on WebFetch. The Brinson-Fachler convention claim is at "convention-level, not citation-level" rigor — well-attested via secondary sources and the formula matches canonical form, but a follow-up read of the CFA primary curriculum would strengthen the attribution. All other subagents passed the 70% bar.

---

## 10. Implementation handoff

This consensus document is the spec for the following mechanical edits (no further design decisions required):

1. **`pm-supervisor.md` line 307** — replace "WATCH" with "HOLD + sleeve_cap_check.status = VIOLATION_DEFENSIVE_CHECK".
2. **`research-company.md` §7** — collapse operator-output template to 4-bin (BUY/HOLD/TRIM/SELL); remove ADD/WATCH/PASS/REJECT vocabulary.
3. **`evaluator.md` HG-23** — extend envelope-shape validator to REJECT envelopes containing the forbidden `summary_code_operator_semantic` field.
4. **`/daily-monitor` skill** — verify it sweeps every ticker with a row in `counterfactual_ledger` (universal monitoring per Consensus Item #2).
5. **`counterfactual_ledger` migration** — DDL per §3 Consensus Item #5. The existing PASS/REJECT-conditional trigger logic is replaced with universal-on-every-run; ledger schema migrated to the new column layout.
6. **`/parameters-review` skill** — read the new `vs_sector_etf_return_pct` column for calibration aggregation; IR computation as a cross-row aggregate is deferred per §7.

Each of these is a small, tightly-scoped change. No new `/grill-me` rounds needed.

---

*Section closed. Ready for implementation pass or next consensus topic.*
