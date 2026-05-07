# Flow B v1 — Frameworks-and-yfinance Design

**Date:** 2026-05-07
**Author:** equity-research-system operator + Claude (brainstorming session)
**Scope:** Expand `/research-company` (Flow B) along two axes — (1) encode named, citable analytical frameworks into CDD and BearCase agent prompts; (2) wire in `yfinance` as a new MCP for consensus estimates, target prices, and holders data. Establish a `tier` classification discipline that routes which frameworks apply.
**Status:** Approved 2026-05-07; v1.1 architectural amendment 2026-05-07 (see §16).
**Out of scope:** CatalystScout subagent, Polygon/Massive options MCP, macro-stack MCP (BLS/BEA/Census/EIA), PMSupervisor changes beyond reading the new `tier` field, evidence_index producer fix.

> **2026-05-07 v1.1 amendment** — see §16 below. Single-CDD architecture replaced by 4-agent ensemble (`cdd-lead` + `quantitative-analyst` + `strategic-analyst` + `search-agent`); per-sector static reference files replaced by dynamic brief generation + two persistent caches: `research_essentials` (atemporal cross-company learnings, migration `027_research_essentials.sql`) and `analyst_briefs` (per-ticker time-stamped brief history with cold/warm-start delta detection, migration `028_analyst_briefs.sql`). Sections 1–15 retained as the framework canon foundation; the agent topology in §3 is superseded by §16.

---

## 1. Background and motivation

The current Flow B (`/research-company` → CDD → BearCase → PMSupervisor) is a credible fundamental engine, but a 2026-05-07 audit + deep research surfaced three gaps:

1. **No named frameworks.** CDD applies §3.25 D-1..D-4 disciplines but doesn't instruct the model to cite Mauboussin / Damodaran / Helmer / Koller by name. Outputs are not reproducible.
2. **No consensus estimate awareness.** Existing MCPs (edgar, market_data, fundamentals, postgres) cover filings, news, prices, and EDGAR XBRL — but nothing surfaces sell-side consensus EPS, target prices, or peer comps. CDD cannot answer "is the implied growth rate above or below consensus?"
3. **No discipline boundary by company maturity.** A pre-revenue quantum-computing name and a mature large-cap get the same treatment. Applying DCF to IonQ produces confidently wrong output.

Research methodology and findings are documented in the conversation transcript (9 parallel research subagents covering source layer, bull frameworks, catalyst frameworks).

The v1 design closes the framework + consensus gap and introduces the tier discipline. CatalystScout (per-name catalyst calendar + positioning panel) is intentionally deferred to v2 to keep v1 scope tight.

## 2. Decision summary (locked via Q&A)

| # | Decision | Choice |
|---|---|---|
| Q1 | Catalyst/sentiment lens role | (B) Sidecar inside `/research-company` — **deferred to v2** |
| Q2 | v1 scope | (b) α (CDD + BearCase prompt rewrite) + β (yfinance MCP) |
| Q3 | Always-apply core framework set | (b) Standard core — 5 frameworks |
| Q4 | Tier classification | (a) Hard branch — first-action classification routes framework application |

## 3. Architecture

Three artifact changes, no schema changes:

```
/research-company TICKER
        │
        ▼
   ┌─────────────────────────────────────────────┐
   │ CDD subagent (.claude/agents/                │
   │  company-deep-dive.md — REWRITTEN)           │
   │   Step 1: classify tier (rubric §6)          │
   │   Step 2: pull data — edgar, market_data,    │
   │            fundamentals, postgres,           │
   │            yfinance (NEW)                    │
   │   Step 3: apply 5-framework core             │
   │            (tier-conditional on DCF)         │
   │   Step 4: sector addenda if classification   │
   │            matches                           │
   │   Step 5: emit memo with required citations  │
   └────────────┬─────────────────────────────────┘
                │
                ▼
   ┌─────────────────────────────────────────────┐
   │ BearCase subagent (.claude/agents/           │
   │  bear-case.md — REWRITTEN)                   │
   │   Same 5 frameworks, applied adversarially   │
   │   Same tier discipline                       │
   │   Independent data re-pull (existing rule)   │
   │   MUST cite different historical analogs     │
   │     than CDD                                 │
   └────────────┬─────────────────────────────────┘
                │
                ▼
   ┌─────────────────────────────────────────────┐
   │ PMSupervisor (main context)                  │
   │   Reads new `tier` field from CDD memo       │
   │   Tier-aware sizing constraint:              │
   │     speculative_optionality → sleeve cap     │
   │     reference (≤8% of book aggregate)        │
   │   Existing synthesis logic otherwise         │
   │     unchanged                                │
   └─────────────────────────────────────────────┘
```

### 3.1 Artifacts changed

| Path | Change | Notes |
|---|---|---|
| `.claude/agents/company-deep-dive.md` | Rewrite | Add tier rubric, 5-framework core, sector-addenda routing, banned outputs, MCP grants for yfinance |
| `.claude/agents/bear-case.md` | Rewrite | Symmetric framework canon applied adversarially; MCP grants for yfinance; analog-non-overlap rule |
| `.claude/references/canonical-frameworks.md` | New | Citation source of truth — paper titles, URLs, one-paragraph definitions |
| `src/mcp/yfinance/` | New | New MCP server wrapping `yfinance` Python lib (6 endpoints) |
| `.mcp.json` | Updated | Register yfinance MCP server |
| `.claude/commands/research-company.md` | Minor edit | PMSupervisor section reads `tier` field; sleeve-cap reference for speculative |
| `tests/yfinance_mcp/` | New | Smoke + integration tests for the new MCP |

## 4. The 5-framework core (always-apply)

Each framework gets a one-paragraph definition in the agent prompt + a required citation when invoked. Reference paths point to `.claude/references/canonical-frameworks.md`.

| Framework | What CDD must produce | What BearCase must produce |
|---|---|---|
| **Damodaran narrative-DCF** | Bound narrative + 3 stress cases (bear/base/bull); explicit growth/margin/duration assumptions; ERP from NYU Stern data | Where the narrative breaks: which assumption is too aggressive; historical analog arguing for compression |
| **Mauboussin reverse-DCF / expectations investing** | `implied_growth`, `implied_margin`, `implied_duration` from current price | Whether implied expectations are achievable; comparable's MEROI vs ROIIC |
| **Mauboussin "Measuring the Moat" 2024** | Source of advantage (production / consumer / external); expected fade pattern over next decade | Why the moat is narrower than claimed; specific erosion vectors |
| **Helmer 7 Powers** | Which of 7 Powers held; for each, Benefit (cash flow effect) AND Barrier (why arbitrage fails) | Which "Power" is actually a switching cost or scale economy in disguise; counter-positioning vulnerability |
| **Mauboussin Capital Allocation 5-bucket** | Grade past 5y allocation (CapEx, R&D, M&A, dividends, buybacks, debt) against ROIC vs WACC | Where allocation destroyed value; misaligned incentives |

### 4.1 Quality gate (precondition, not a "framework")

Run before any framework analysis. If either fails, memo gates to `disposition: REJECT` with reason in the gate field. Sloan accruals reported as a flag only (anomaly has decayed since 2003).

- **Piotroski F-Score ≥ 6** (Piotroski 2000; 9-point checklist)
- **Altman Z'' > 1.1** for non-manufacturers (Altman 1968 + revisions)

## 5. Canonical reading list (`.claude/references/canonical-frameworks.md`)

Citation source of truth. Each entry: short key, full title, author, year, URL, one-paragraph definition. Top 10 entries (initial v1):

1. **mauboussin_capital_allocation_2024** — Mauboussin & Callahan, "Capital Allocation: Results, Analysis, and Assessment" (Counterpoint Global / Morgan Stanley, 2022/2024) — https://www.morganstanley.com/im/publication/insights/articles/article_capitalallocation.pdf
2. **mauboussin_moat_2024** — Mauboussin & Callahan, "Measuring the Moat" (Counterpoint Global, 2024) — https://www.morganstanley.com/im/publication/insights/articles/article_measuringthemoat.pdf
3. **mauboussin_meroi** — Mauboussin & Callahan, "Market-Expected Return on Investment" — https://www.morganstanley.com/im/publication/insights/articles/article_marketexpectedreturnoninvestment_en.pdf
4. **rappaport_mauboussin_expectations_investing_2021** — Rappaport & Mauboussin, "Expectations Investing" rev. ed. — https://www.expectationsinvesting.com/
5. **damodaran_narrative_numbers_2017** — Damodaran, "Narrative and Numbers" — https://pages.stern.nyu.edu/~adamodar/pdfiles/eqnotes/narrativeandnumbers.pdf
6. **damodaran_data** — Damodaran NYU Stern data hub (annual ERP, country risk, industry betas, multiples) — https://pages.stern.nyu.edu/~adamodar/
7. **helmer_7_powers** — Hamilton Helmer, "7 Powers: The Foundations of Business Strategy" (2016) — https://7powers.com/
8. **koller_valuation_7e** — Koller, Goedhart, Wessels, "Valuation" 7th ed. (McKinsey/Wiley 2020)
9. **piotroski_2000** — Piotroski, "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers," J. Accounting Research 38 (2000) — https://www.ivey.uwo.ca/media/3775523/value_investing_the_use_of_historical_financial_statement_information.pdf
10. **altman_1968** — Altman, "Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy," J. Finance 23(4) (1968) — https://www.calctopia.com/papers/Altman1968.pdf

Sector-specific addenda references (added under §6 addenda):

11. **bessemer_cloud_100** — Bessemer State of the Cloud + Cloud 100 Benchmarks — https://www.bvp.com/atlas/the-cloud-100-benchmarks-report
12. **skok_saas_metrics** — David Skok, "SaaS Metrics 2.0" — https://www.forentrepreneurs.com/saas-metrics-2-definitions-2/
13. **a16z_marketplace_metrics** — a16z, "13 Metrics for Marketplaces" + "GMV Retention" — https://a16z.com/13-metrics-for-marketplace-companies/
14. **sequoia_ai_ascent_2025** — Sequoia AI Ascent 2025 — https://inferencebysequoia.substack.com/p/insights-from-ai-ascent-2025
15. **bain_ai_trillion_dollar_2024** — Bain Tech Report 2024 — https://www.bain.com/insights/ais-trillion-dollar-opportunity-tech-report-2024/

## 6. Tier classification rubric

CDD's first action. Heuristic, agent decides. **Ambiguous cases default to the more conservative tier** (thematic_growth over core_fundamental; speculative_optionality over thematic_growth).

```
core_fundamental
  - trailing 12mo revenue > $1B
  - AND positive operating income in ≥4 of last 8 quarters
  - AND public for ≥10 years
  - examples: AAPL, MSFT, JPM, KO, JNJ

thematic_growth
  - trailing 12mo revenue > $100M
  - AND (volatile/negative op income
         OR <10y public
         OR sector ∈ {high-growth tech, EV, semis with cyclicality,
                      biotech with approved products})
  - examples: TSLA, PLTR, MRVL, COIN, ARM

speculative_optionality
  - trailing 12mo revenue < $100M OR pre-revenue
  - OR sector ∈ {quantum, fusion, pre-clinical biotech, frontier autonomy,
                 neuromorphic}
  - examples: IONQ, QUBT, RGTI, JOBY, PLUG
```

### 6.1 Tier-conditional framework application

| Tier | DCF | Reverse-DCF | Moat | 7 Powers | Capital Allocation | Output constraint |
|---|---|---|---|---|---|---|
| core_fundamental | ✓ point + bands | ✓ | ✓ | ✓ | ✓ | Standard memo |
| thematic_growth | ✓ **ranges only** | ✓ | ✓ | ✓ | ✓ | Sensitivity bands required, no point targets |
| speculative_optionality | **SKIP** | **SKIP** | ✓ qualitative | ✓ qualitative | N/A acceptable | Milestone-tree + probability-weighted payoffs only |

### 6.2 Speculative-tier output schema

For `tier: speculative_optionality`, replace the DCF section with:

```
milestone_tree:
  - milestone: <description>
    target_date: <YYYY-Q#>
    probability: <0..1>
    conditional_payoff_if_met: <multiple of current price, range>
    conditional_payoff_if_missed: <multiple, range>
expected_value_decomposition:
  - sum of (probability × conditional_payoff_if_met)
  - vs sum of (1 - probability) × conditional_payoff_if_missed
sleeve_reference:
  - aggregate speculative sleeve cap: ≤8% of book
  - intra-sleeve diversification rule: no single thematic sub-sleeve >40%
```

## 7. Sector addenda (classification-triggered)

Three v1 addenda. Agent invokes the matching addendum after step 4. Multiple addenda can fire (e.g., an AI-native SaaS triggers SaaS + AI-stack).

### 7.1 SaaS / B2B subscription addendum

Triggers: company self-classifies as subscription / SaaS, or revenue model is recurring software.

Required outputs:
- **NRR / GRR** (cite company's footnoted definition; Bessemer benchmarks)
- **Rule of 40** (or Rule of X if AI-native — growth weighted 2×)
- **Magic Number, CAC payback, Burn Multiple** (Sacks)
- **AI gross margin** if applicable (Tanay Jaipuria 2025)

### 7.2 Marketplace / multi-sided platform addendum

Triggers: company business model has explicit multi-sided structure.

Required outputs:
- **GMV, take rate, GMV-cohort retention, frequency, liquidity** (a16z 13 metrics)
- **Hagiu/Eisenmann platform-side analysis** — list each side, cross-side network effect direction, chicken-and-egg solution at cold-start, envelopment risk

### 7.3 AI-native / AI-stack participant addendum

Triggers: company's revenue or value-prop materially derives from AI capability.

Required outputs:
- **AI-stack position** (HW / cloud / model / tooling / vertical app — Sequoia AI Ascent 2025 framing)
- **AI gross margin scrutiny** — break out hosting/inference/third-party-model costs from 10-K Item 7
- **Inference cost per active user** if disclosable
- **Margin pool location vs erosion** — Sequoia vs a16z framing comparison

## 8. Banned outputs

Enforced as agent-prompt rules. Evaluator agent grades compliance as a hard gate.

**Universal:**
- Stovall classical sector rotation (empirically rejected by Molchanov-Stangl 2024)
- PEG-only ranking (no out-of-sample empirical support; contradicts McKinsey ROIC > WACC finding)
- ARK-style decade-out point price targets

**Tier-specific:**
- `core_fundamental` + `thematic_growth`: Fed-action commentary without referencing HFI window (Nakamura-Steinsson QJE 2018) or FOMC-cycle position (Cieslak-Vissing-Jorgensen JoF 2019)
- `speculative_optionality`: any DCF with point target; "TAM × penetration" without sensitivity bands; comparison to "next NVIDIA" without modality-specific evidence

## 9. yfinance MCP

### 9.1 Endpoints (v1)

```python
get_consensus_estimates(ticker: str) -> dict
  # Returns: {fy_eps_mean, fy_eps_std, fy_revenue_mean, fy_revenue_std,
  #           next_q_eps_mean, next_q_revenue_mean, analyst_count}
  # Forward 4q + current FY consensus; sourced from Yahoo /v10/finance/quoteSummary
  # earningsTrend module

get_target_prices(ticker: str) -> dict
  # Returns: {target_high, target_low, target_mean, target_median,
  #           number_of_analyst_opinions, recommendation_mean,
  #           recommendation_key}

get_recommendations(ticker: str, days: int = 90) -> list
  # Returns recent upgrades/downgrades within window
  # [{firm, to_grade, from_grade, action, date}, ...]

get_calendar(ticker: str) -> dict
  # Returns: {next_earnings_date, ex_dividend_date, dividend_date}

get_holders(ticker: str) -> dict
  # Returns: {institutional_holders: [...], major_holders: {...},
  #           insider_holders: [...], institutional_pct, qoq_delta}

get_peer_comps(ticker: str) -> list
  # Returns peer tickers + their key multiples
  # [{ticker, pe, ev_ebitda, ev_sales, market_cap}, ...]
```

### 9.2 Tool grants in agent files

Both `.claude/agents/company-deep-dive.md` and `.claude/agents/bear-case.md` declare these MCP tools at tool-level (not server-level shorthand, per existing repo memory rule):

- `mcp__yfinance__get_consensus_estimates`
- `mcp__yfinance__get_target_prices`
- `mcp__yfinance__get_recommendations`
- `mcp__yfinance__get_calendar`
- `mcp__yfinance__get_holders`
- `mcp__yfinance__get_peer_comps`

### 9.3 Implementation notes

- Wrap `yfinance` Python lib (chosen over `yahooquery` for active maintenance and battle-testing).
- Pin version range: `yfinance >=0.2.40,<0.3` in `requirements.txt` or pyproject.
- Cache responses in Postgres with 24h TTL for non-realtime fields (calendar, holders, peer comps); 4h TTL for estimates and target prices; 1h TTL for recommendations.
- On stale cache hit beyond TTL, return `{stale: True, last_updated: <iso8601>, data: <cached>}`. Do not fail closed.
- Add `mcp__yfinance` to `.mcp.json` config.
- Yahoo ToS prohibits automated access; this is personal-research use only and must not be productized.

### 9.4 Failure modes and handling

| Failure | MCP behavior | Agent prompt instruction |
|---|---|---|
| Yahoo endpoint returns 404/empty | Return `{available: False, reason: "endpoint_dropped"}` | Surface gap in memo; continue with EDGAR-only path |
| Cached data > TTL but Yahoo unreachable | Return `{stale: True, last_updated: ..., data: ...}` | Surface staleness; do not pretend fresh |
| Rate limit hit (429) | Return `{rate_limited: True, retry_after: <seconds>}` | Pause, retry up to 2× then surface gap |
| Ticker not found | Return `{ticker_not_found: True}` | Surface gap; check if delisted via `mcp__fundamentals__get_delistings` |

## 10. Output template changes

Minimal additions to existing CDD memo output:

```yaml
tier: core_fundamental | thematic_growth | speculative_optionality
quality_gate:
  piotroski_f_score: <int>
  altman_z_double_prime: <float>
  passes_quality_gate: <bool>
  if_failed_gate_to_disposition: REJECT
frameworks_cited:
  - framework: damodaran_narrative_dcf
    source_ref: damodaran_narrative_numbers_2017
    output: <inline section>
  - framework: mauboussin_reverse_dcf
    source_ref: rappaport_mauboussin_expectations_investing_2021
    output: <inline section>
  - framework: mauboussin_moat
    source_ref: mauboussin_moat_2024
    output: <inline section>
  - framework: helmer_7_powers
    source_ref: helmer_7_powers
    output: <inline section>
  - framework: mauboussin_capital_allocation
    source_ref: mauboussin_capital_allocation_2024
    output: <inline section>
sector_addenda_invoked:
  - addendum: saas_unit_economics
    source_refs: [bessemer_cloud_100, skok_saas_metrics]
    output: <inline section>
  # ... or empty list if no match
yfinance_data_freshness:
  consensus_estimates: {stale: false, last_updated: ...}
  target_prices: {stale: false, last_updated: ...}
  # ...
banned_outputs_check:
  - stovall_rotation: not_used
  - peg_only_ranking: not_used
  - ark_point_targets: not_used
  - fed_commentary_without_hfi: not_used
```

## 11. Testing

### 11.1 Three-tier smoke test

Post-implementation, run `/research-company` against:

- **core_fundamental:** AAPL, JPM
- **thematic_growth:** TSLA, PLTR
- **speculative_optionality:** IONQ, RGTI

Each must produce a memo where:
1. Tier is correctly classified per §6.
2. All 5 core frameworks cited, OR correctly skipped per the §6.1 tier-conditional table (DCF + reverse-DCF skipped for `speculative_optionality`; Moat / 7 Powers / Capital Allocation still run qualitatively in all tiers, with "N/A — pre-revenue, no allocation history" acceptable for Capital Allocation on speculative names).
3. Sector addendum invoked if applicable (SaaS for any matching name; AI-stack mandatory for AI-native).
4. No banned outputs (per Evaluator hard-gate check).
5. yfinance data surfaced with `stale` flags where applicable.
6. BearCase produces non-trivial counter-arguments under each framework AND cites different historical analogs than CDD.

### 11.2 Evaluator gate

Existing `.claude/agents/evaluator.md` runs against each new memo. Add framework-citation compliance to the hard-gate set:

- All 5 core frameworks invoked OR correctly skipped per §6.1 tier-conditional table → hard gate
- No banned outputs → hard gate
- Quality gate (Piotroski + Altman) computed → hard gate
- Tier classification field present and matches §6 rubric → hard gate
- BearCase analog non-overlap with CDD → soft score

Framework *substance* (depth and quality of the application) graded as soft score, not hard gate.

### 11.3 yfinance MCP smoke tests

`tests/yfinance_mcp/test_endpoints.py`:
- All 6 endpoints return valid schemas for AAPL (golden test).
- Stale-cache path returns `{stale: True, ...}` not error.
- Ticker-not-found path returns `{ticker_not_found: True}` not exception.
- Rate-limit path retries with backoff.

## 12. Risk register

| Risk | Mitigation |
|---|---|
| yfinance ToS automated access | Personal research use only; pin version; do not productize |
| Yahoo kills endpoint unpredictably | Postgres cache; staleness flag; macro-stack MCP fallback in v2 for some metrics |
| Prompt soup (5 frameworks + addenda + tier rubric) | Use `### Section` headers; agent navigates by ToC; framework definitions kept under 80 words each |
| Speculative-tier output schema drift | Lock the milestone-tree + probability-payoff schema in `canonical-frameworks.md` |
| BearCase becomes too symmetric (just inverts CDD) | Rule: BearCase MUST cite different historical analogs; independent data re-pull stays mandatory |
| Evaluator over-grades on citation compliance | Citation compliance graded as gate; framework *substance* graded as soft score |
| Tier classification ambiguity (e.g., NVDA — core or thematic?) | Default to more conservative; document edge cases in `canonical-frameworks.md` |

## 13. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-07 | Q1 = (B) catalyst sidecar deferred to v2 | Research surfaced enough peer-reviewed-predictive signals (Cremers-Weinbaum, Pan-Poteshman, BofA FMS, AAII tails, VIX backwardation, Lowry thrusts) that skipping is no longer defensible — but designing CatalystScout requires Polygon options data and adds blast radius. Defer for v2. |
| 2026-05-07 | Q2 = (b) v1 = framework rewrite + yfinance | Framework rewrite is essentially free (prompt-only). yfinance is the highest-ROI source addition (consensus estimates not available from EDGAR). Polygon options can wait until CatalystScout actually needs it. |
| 2026-05-07 | Q3 = (b) 5-framework standard core | Three-framework lean version makes Capital Allocation grading optional, which underutilizes a broadly-applicable tool. Eight-framework full version causes prompt soup and box-checking behavior. Five is the load-bearing balance. |
| 2026-05-07 | Q4 = (a) hard branch tier classification | Soft-flag approach (b) doesn't actually solve the failure mode — agent still produces DCF on IONQ. Defer-to-v2 (c) leaves the v1 system misbehaving on speculative names. Hard branch is a one-step classification at the top that prevents the worst outputs. |

## 14. Out of scope (explicitly deferred to v2 or later)

- **CatalystScout subagent** — forward 90-day catalyst calendar + positioning panel (Cremers-Weinbaum IV-spread, Pan-Poteshman P/C, BofA FMS, GS prime extremes). Requires Polygon options MCP. Targeted v2.
- **Polygon/Massive options MCP** — full OPRA chains, intraday quotes, corporate actions. Pin version (experimental). Targeted v2 alongside CatalystScout.
- **macro-stack MCP** — wraps BLS / BEA / Census / EIA APIs. Useful for sector framing but not load-bearing for CDD v1.
- **PMSupervisor synthesis logic changes** beyond reading `tier`. Future work: tier-aware mode-fit dashboard integration.
- **Schema changes** — none in v1. Memo storage uses existing tables.
- **evidence_index producer fix** — separate deferred work item (CDD does not currently INSERT INTO evidence_index despite the schema implying it should). Tracked separately.
- **PMSupervisor sleeve-cap enforcement** beyond a reference note — full sleeve-cap accounting across multiple speculative-tier holdings is v0.5+ work.

## 15. Appendix: Sources for design decisions

Research conducted 2026-05-07 via 9 parallel research subagents. Full citations in conversation transcript. Key load-bearing references:

- Mauboussin papers (Counterpoint Global / Morgan Stanley) — capital allocation, moat, MEROI, expectations investing
- Damodaran NYU Stern — valuation primers, ERP data
- Helmer "7 Powers" (2016)
- Koller "Valuation" 7th ed. (McKinsey/Wiley 2020)
- Piotroski (J. Accounting Research 2000), Altman (J. Finance 1968)
- Bessemer State of Cloud, David Skok SaaS Metrics
- Sequoia AI Ascent 2025, a16z, Bain Tech Report 2024
- Molchanov-Stangl IJFE 2024 (Stovall rotation rejection)
- Nakamura-Steinsson QJE 2018, Cieslak-Vissing-Jorgensen JoF 2019 (Fed catalyst effect-size papers)

Failure-mode evidence:
- ARK TSLA target $7,000 (2020) vs actual ~$200-400 — methodology resets goalpost without retrospective accuracy reporting (Seeking Alpha 2024).
- WSB / BUZZ ETF -3.58% Apr 2021–Mar 2024 vs VOO +11.58% — retail sentiment bottom-tier signal (Alpha Architect 2024).

---

## 16. v1.1 Architectural Amendment (2026-05-07)

The single-CDD topology in §3 is superseded by a 4-agent ensemble. Sections 1, 2, 4–8, and 11–15 (the framework canon, tier rubric, banned outputs, quality gate, testing, risk register) are unchanged and remain load-bearing. Section 9 (yfinance MCP) is unchanged. Section 7 (sector addenda) is replaced by §16.4 below.

### 16.1 Why the rewrite

Three operator observations during plan implementation:

1. **CDD was overloaded** — single-agent single-context juggled tier classification + 5 frameworks + sector addenda + integration + evidence_index population.
2. **Static per-sector reference files violate sector-agnosticism** — a hardcoded sector taxonomy can't handle novel sectors (e.g., 2027 vertical-AI-agent companies) and goes stale fast.
3. **Source-routing knowledge belongs in one place** — knowing CNBC for daily news, FRED for macro, McKinsey for industry outlook, EDGAR for filings, etc., should be encoded once and reused across CDD, BearCase, daily-monitor, anchor-drift.

### 16.2 New agent topology

```
                  /research-company TICKER
                            │
                            ▼
                   ┌──────────────────────┐
                   │ cdd-lead (Stage 1)   │
                   │  - tier classify     │
                   │  - sector identify   │
                   │  - read essentials   │◀──┐
                   │  - dispatch search   │   │
                   │  - build briefs      │   │
                   │  - dispatch analysts │   │
                   └────┬───────┬─────────┘   │
                  parallel│       │parallel    │
                          ▼       ▼            │
              ┌───────────────┐ ┌──────────────┐│
              │ quantitative- │ │ strategic-   ││
              │   analyst     │ │   analyst    ││
              │ (calls search)│ │(calls search)││
              └───────┬───────┘ └──────┬───────┘│
                      └───────┬────────┘        │
                              ▼                 │
                   ┌──────────────────────┐     │
                   │ cdd-lead (Stage 2)   │     │
                   │  - integrate         │     │
                   │  - dispatch search   │     │
                   │    (verify claims)   │     │
                   │  - distill essentials├─────┘
                   │  - banned-out check  │ UPSERT to
                   │  - evidence_index    │ research_essentials
                   │  - emit memo         │
                   └──────────┬───────────┘
                              ▼
                          bear-case
                   (also dispatches search)
                              │
                              ▼
                          evaluator
                              │
                              ▼
                       PMSupervisor
```

### 16.3 Agent specs

| Agent | Direct MCP tools | Dispatches | Frameworks owned | Prompt size |
|---|---|---|---|---|
| `cdd-lead` | `mcp__postgres__*`, Read, Bash | search-agent, quantitative-analyst, strategic-analyst | None — orchestrator + integrator | ~6K |
| `search-agent` | edgar, market_data, yfinance, fundamentals, fred, postgres, WebFetch | none | None — data finder with source-routing knowledge | ~5K |
| `quantitative-analyst` | `mcp__postgres__*`, Read | search-agent | Damodaran narrative-DCF, Mauboussin reverse-DCF, Quality gate (Piotroski + Altman) | ~6K |
| `strategic-analyst` | `mcp__postgres__*`, Read | search-agent | Mauboussin Moat 2024, Helmer 7 Powers, Mauboussin Capital Allocation | ~6K |
| `bear-case` | `mcp__postgres__*`, Read | search-agent | Same 5 frameworks adversarially | ~7K |
| `evaluator` | `mcp__postgres__*`, `mcp__contamination_check__*` | none | Hard gates | unchanged |

### 16.4 Sector context — dynamic, not static

Static per-sector files (§7 of original spec) are eliminated. Replaced by:

**Templates (one each, structure only, ~1K tokens each):**
- `.claude/references/analyst-context-templates/quantitative.md`
- `.claude/references/analyst-context-templates/strategic.md`

**Dynamic brief generation** in cdd-lead Stage 1: for each analyst, populate the template with sector- and company-specific content drawn from (a) `research_essentials` (persistent learnings from prior runs), (b) fresh search-agent calls (latest news, filings, peers), (c) the 5-framework core canon. Briefs injected at analyst dispatch time.

This makes the system handle novel sectors via the same code path as known sectors. No taxonomy maintenance.

### 16.5 search-agent source-routing matrix

Embedded in `search-agent` prompt:

| Request type | Primary sources |
|---|---|
| Daily fast/holistic market view | CNBC RSS, market_data news |
| Per-company fundamentals | EDGAR XBRL, yfinance |
| Per-company consensus + targets | yfinance |
| Macro context | FRED, BLS/BEA/Census via WebFetch |
| Long-horizon industry outlook | McKinsey Insights, BCG Perspectives, JPM Eye on the Market (WebFetch) |
| Catalyst calendar | EDGAR 8-Ks, BioPharmCatalyst, Wall Street Horizon (WebFetch) |
| Recent sector trends | market_data news, CNBC RSS |
| Peer comparison | yfinance + EDGAR SIC peers |
| Options/derivatives positioning | DEFERRED to v2 (Polygon MCP) |

Output schema: `{findings: [{claim, evidence, source_url, freshness_days}], sources_consulted: [], gaps: []}` — designed for direct injection into another agent's prompt.

### 16.6 Two persistent caches

Two distinct tables. Two schema additions:

#### `research_essentials` (migration `027_research_essentials.sql`) — atemporal, cross-company

Durable methodology learnings. Informs HOW briefs are built across all tickers.

```sql
CREATE TABLE research_essentials (
  key TEXT PRIMARY KEY,
  content TEXT NOT NULL,
  topic_tags TEXT[] NOT NULL,
  source_run_ids TEXT[] NOT NULL,
  confidence INT NOT NULL DEFAULT 1,
  last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX research_essentials_tags_idx ON research_essentials USING GIN(topic_tags);
```

Lifecycle:
- **Read (Stage 1):** `SELECT FROM research_essentials WHERE topic_tags && {sector, tier, framework_keys}` injected into briefs.
- **Write (Stage 2):** cdd-lead distills 0–3 durable cross-company learnings per run, UPSERTs by `key`, increments `confidence` on reaffirmation.
- **Decay protection:** essentials with `confidence < 3` flagged "preliminary"; brief-generator must re-verify via search-agent before relying.

#### `analyst_briefs` (migration `028_analyst_briefs.sql`) — per-ticker, time-stamped

The actual briefs delivered to analysts on each run. Informs WHAT was the analytical frame last time for this specific ticker. Enables warm-start delta-generation and longitudinal drift audits.

```sql
CREATE TABLE analyst_briefs (
  brief_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticker TEXT NOT NULL,
  run_id TEXT NOT NULL,
  brief_type TEXT NOT NULL CHECK (brief_type IN ('quantitative', 'strategic')),
  tier TEXT NOT NULL CHECK (tier IN ('core_fundamental','thematic_growth','speculative_optionality')),
  sector_identification TEXT NOT NULL,
  content TEXT NOT NULL,
  sources_used JSONB NOT NULL,
  essentials_referenced TEXT[] NOT NULL,
  prior_brief_id UUID REFERENCES analyst_briefs(brief_id),
  delta_summary TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX analyst_briefs_ticker_type_recent
  ON analyst_briefs(ticker, brief_type, created_at DESC);
CREATE INDEX analyst_briefs_ticker_recent
  ON analyst_briefs(ticker, created_at DESC);
```

Lifecycle (cdd-lead Stage 1):
1. `SELECT * FROM analyst_briefs WHERE ticker=T AND brief_type IN ('quantitative','strategic') ORDER BY created_at DESC LIMIT 2` → **cold-start** if empty; **warm-start** otherwise.
2. Cold-start: search-agent runs full sweep (8–12 calls); brief built from canonical-frameworks + essentials + fresh search.
3. Warm-start: search-agent runs delta-sweep (4–6 calls), focused on the time window since `prior.created_at`; brief built as delta against prior (preserves continuity, surfaces what changed).
4. INSERT new row with `prior_brief_id` link + `delta_summary` (the human-readable diff: "Tier unchanged; sector reclassified semis→AI-native; new peer ARM; Q3 beat + guide raise; capital allocation grade B→A on $25B buyback").
5. Inject brief + delta_summary into analyst dispatch prompts.

What this unlocks:
- **Warm-run cost reduction** — token cost typically drops 30–50% on subsequent runs of the same ticker (search-agent does delta-sweep, not full sweep).
- **Material-event detection by construction** — `delta_summary` is itself a high-signal artifact for monitoring slow-layer changes.
- **Auditable analytical drift** — linked-list via `prior_brief_id` lets the operator walk the history of how a thesis framing evolved.
- **`/quarterly-reunderwrite` becomes a brief-delta exercise** — re-underwrite is fundamentally "regenerate the brief, surface the delta against last quarter's brief."
- **BearCase anchoring** — bear-case reads recent briefs for the ticker via search-agent and argues why prior framings were wrong, not just the current one.

Retention: keep all briefs indefinitely. Storage trivial (~5KB × 2 × 50 runs/yr ≈ 500KB/yr). Audit value dominates.

### 16.7 Risks introduced by amendment

| Risk | Mitigation |
|---|---|
| `research_essentials` accumulates bad content | Confidence counter; <3 reaffirmations = "preliminary" + re-verify rule |
| Dynamic brief generation hallucinates novel-sector context | Brief MUST cite ≥2 sources from search-agent; if zero, surface "thin sector knowledge" flag for bear-case attack |
| 4 agents = 4× evaluator workload | Evaluator grades each output independently; total grading cost rises ~30% but per-output grade is faster (smaller outputs) |
| search-agent drift / staleness on source list | Source-routing matrix is part of agent prompt; reviewed on each spec amendment |
| Token cost rises ~15-20% per memo from larger ensemble | Offset by analyst parallelism (latency drops ~50%) and brief-injection making analyst prompts smaller |

### 16.8 Out of scope (still)

Same as original §14, plus the explicit deferral of options/derivatives positioning data (search-agent flags but cannot retrieve in v1).
