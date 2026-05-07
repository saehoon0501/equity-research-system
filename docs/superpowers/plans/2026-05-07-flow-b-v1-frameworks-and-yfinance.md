# Flow B v1 Implementation Plan (v1.1 architecture)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Flow B v1.1 — 4-agent CDD ensemble (`cdd-lead` + `quantitative-analyst` + `strategic-analyst` + `search-agent`) plus updated `bear-case`/`evaluator`, with two persistent caches (`research_essentials` for cross-company learnings, `analyst_briefs` for per-ticker brief history with cold/warm-start delta detection), dynamic sector-agnostic brief generation, named 5-framework canon with citation-by-short-key, hard-branch tier classification, and `yfinance` MCP for consensus estimates.

**Architecture summary:**
- `cdd-lead`: 2-stage orchestrator. Stage 1 = tier classify, sector identify, read essentials + prior briefs, dispatch search-agent, build briefs (cold/warm path), persist briefs, dispatch parallel analysts. Stage 2 = integrate, search-verify, distill essentials, banned-output check, evidence_index, emit memo.
- `search-agent`: data finder with source-routing knowledge (CNBC for daily news, FRED for macro, McKinsey for industry, EDGAR for filings, yfinance for consensus, etc.). Reused across CDD/BearCase/daily-monitor.
- `quantitative-analyst`: Damodaran narrative-DCF + Mauboussin reverse-DCF + quality gate (Piotroski + Altman). Receives brief in prompt; dispatches search-agent for data pulls.
- `strategic-analyst`: Mauboussin Moat 2024 + Helmer 7 Powers + Mauboussin Capital Allocation. Receives brief; dispatches search-agent for evidence.
- `bear-case`: same 5 frameworks adversarially, reads recent analyst_briefs for longitudinal anchoring, dispatches search-agent.
- `evaluator`: hard gates on framework citation + tier + banned outputs + brief delta-detection quality.

**Tech Stack:** Python 3.11+, FastMCP, `yfinance>=0.2.40,<0.3`, Postgres (existing), pytest. Mirrors `src/mcp/fred/` package layout.

**Spec:** `docs/superpowers/specs/2026-05-07-flow-b-v1-frameworks-and-yfinance-design.md` (commit `70a9a55` original; v1.1 amendment in §16).

---

## File Structure

**New:**
- `db/migrations/027_research_essentials.sql` — atemporal cross-company learning cache
- `db/migrations/028_analyst_briefs.sql` — per-ticker time-stamped brief history
- `.claude/references/canonical-frameworks.md` — citation source of truth
- `.claude/references/analyst-context-templates/quantitative.md` — structure for quant briefs
- `.claude/references/analyst-context-templates/strategic.md` — structure for strategic briefs
- `.claude/agents/cdd-lead.md` — 2-stage orchestrator
- `.claude/agents/quantitative-analyst.md` — owns valuation + quality gate
- `.claude/agents/strategic-analyst.md` — owns moat + capital allocation
- `.claude/agents/search-agent.md` — data finder with source routing
- `src/mcp/yfinance/` — new MCP package (server.py, pyproject.toml, README.md, __init__.py)
- `tests/test_yfinance.py` — yfinance MCP integration tests

**Modified:**
- `.mcp.json` — register yfinance server
- `.claude/agents/bear-case.md` — adversarial 5-framework canon, search-agent dispatch, longitudinal brief reading
- `.claude/agents/evaluator.md` — new hard gates
- `.claude/commands/research-company.md` — orchestration: cdd-lead → cdd-lead Stage 2 → bear-case → evaluator → PMSupervisor

**Removed:**
- `.claude/agents/company-deep-dive.md` — replaced by cdd-lead + quantitative-analyst + strategic-analyst (file deleted with `git rm`)

---

## Task 1: Canonical frameworks reference

**Files:**
- Create: `.claude/references/canonical-frameworks.md`

(Same content as previous plan revision — content unchanged by amendment.)

- [ ] **Step 1: Write the file** (full content per spec §5; 17 short-key entries: 5 core frameworks + Piotroski + Altman + 8 sector-addendum sources + 3 banned-output references)

- [ ] **Step 2: Commit**

```bash
git add .claude/references/canonical-frameworks.md
git commit -m "Add canonical-frameworks citation source of truth

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

(See spec §5 for full content; reproduce verbatim.)

---

## Task 2: Migration `027_research_essentials.sql`

**Files:**
- Create: `db/migrations/027_research_essentials.sql`

- [ ] **Step 1: Write migration**

```sql
-- 027_research_essentials.sql
-- Per spec §16.6 — atemporal cross-company methodology learnings.
-- Lifecycle: written by cdd-lead Stage 2 (UPSERT 0-3 per run, increment confidence
-- on reaffirmation); read by cdd-lead Stage 1 (filter by topic_tags overlap).

CREATE TABLE IF NOT EXISTS research_essentials (
    key TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    topic_tags TEXT[] NOT NULL,
    source_run_ids TEXT[] NOT NULL,
    confidence INT NOT NULL DEFAULT 1,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS research_essentials_tags_idx
    ON research_essentials USING GIN (topic_tags);

COMMENT ON TABLE research_essentials IS
    'Durable cross-company methodology learnings extracted from /research-company runs. Read in cdd-lead Stage 1 brief generation.';
COMMENT ON COLUMN research_essentials.confidence IS
    'Count of distinct runs that reaffirmed this learning. <3 = preliminary; brief-generator must re-verify via search-agent.';
```

- [ ] **Step 2: Apply via psql**

```bash
psql "$DATABASE_URL" -f db/migrations/027_research_essentials.sql
```

Expected: `CREATE TABLE`, `CREATE INDEX`, `COMMENT`, `COMMENT` outputs.

- [ ] **Step 3: Verify**

```bash
psql "$DATABASE_URL" -c "\d research_essentials"
```

Expected: shows the table with all columns + the GIN index.

- [ ] **Step 4: Commit**

```bash
git add db/migrations/027_research_essentials.sql
git commit -m "Migration 027: research_essentials cache

Atemporal cross-company learnings cache per v1.1 spec §16.6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Migration `028_analyst_briefs.sql`

**Files:**
- Create: `db/migrations/028_analyst_briefs.sql`

- [ ] **Step 1: Write migration**

```sql
-- 028_analyst_briefs.sql
-- Per spec §16.6 — per-ticker time-stamped brief history.
-- Cold-start: no prior brief for ticker → search-agent does full sweep,
-- brief built from scratch.
-- Warm-start: prior brief exists → search-agent does delta-sweep,
-- brief built as delta against prior, prior_brief_id linked, delta_summary populated.

CREATE TABLE IF NOT EXISTS analyst_briefs (
    brief_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker TEXT NOT NULL,
    run_id TEXT NOT NULL,
    brief_type TEXT NOT NULL CHECK (brief_type IN ('quantitative', 'strategic')),
    tier TEXT NOT NULL CHECK (tier IN ('core_fundamental','thematic_growth','speculative_optionality')),
    sector_identification TEXT NOT NULL,
    content TEXT NOT NULL,
    sources_used JSONB NOT NULL,
    essentials_referenced TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    prior_brief_id UUID REFERENCES analyst_briefs(brief_id),
    delta_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS analyst_briefs_ticker_type_recent
    ON analyst_briefs(ticker, brief_type, created_at DESC);

CREATE INDEX IF NOT EXISTS analyst_briefs_ticker_recent
    ON analyst_briefs(ticker, created_at DESC);

COMMENT ON TABLE analyst_briefs IS
    'Per-ticker time-stamped analytical briefs delivered to quantitative-analyst and strategic-analyst by cdd-lead. Linked-list via prior_brief_id enables longitudinal drift audit and warm-start delta generation.';
COMMENT ON COLUMN analyst_briefs.delta_summary IS
    'Human-readable diff between this brief and prior_brief. NULL on cold-start. High-signal artifact for slow-layer monitoring.';
```

- [ ] **Step 2: Apply, verify, commit**

```bash
psql "$DATABASE_URL" -f db/migrations/028_analyst_briefs.sql
psql "$DATABASE_URL" -c "\d analyst_briefs"
git add db/migrations/028_analyst_briefs.sql
git commit -m "Migration 028: analyst_briefs cache

Per-ticker time-stamped brief history with cold/warm-start support.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: yfinance MCP package skeleton

(Per prior plan, unchanged.)

**Files:** Create `src/mcp/yfinance/server.py`, `pyproject.toml`, `__init__.py`, `README.md`.

- [ ] **Step 1**: Write `pyproject.toml`:

```toml
[project]
name = "equity-research-yfinance-mcp"
version = "0.1.0"
description = "yfinance MCP server. Wraps Yahoo Finance for consensus estimates, target prices, holders, calendar, peer comps. Personal research use only — Yahoo ToS prohibits automated commercial access."
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.0.0",
    "yfinance>=0.2.40,<0.3",
    "python-dotenv>=1.0.0",
]

[dependency-groups]
dev = ["pytest>=8.0"]
```

- [ ] **Step 2**: Write `__init__.py` (empty).

- [ ] **Step 3**: Write `server.py` skeleton:

```python
"""yfinance MCP server for the equity research system.

Wraps Yahoo Finance via the `yfinance` Python lib. Six endpoints per spec §9:
get_consensus_estimates, get_target_prices, get_recommendations, get_calendar,
get_holders, get_peer_comps.

ToS reality: Yahoo prohibits automated access for commercial use. Personal
research only.

Failure-mode contract per spec §9.4: ticker_not_found, available=False,
rate_limited, stale.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


mcp = FastMCP("yfinance")


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4**: Write `README.md` (per prior plan revision — endpoints summary, ToS note, failure modes, run command).

- [ ] **Step 5**: `cd src/mcp/yfinance && uv sync` — generates `uv.lock`.

- [ ] **Step 6**: Commit.

```bash
git add src/mcp/yfinance/
git commit -m "Add yfinance MCP package skeleton

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Tasks 5–10: yfinance endpoints (TDD, one per endpoint)

Per prior plan revision — content unchanged. Each task: write failing test, verify failure, implement endpoint, verify pass, commit.

- **Task 5:** `get_consensus_estimates` — see prior plan Task 3 for full code.
- **Task 6:** `get_target_prices` — see prior plan Task 4.
- **Task 7:** `get_recommendations` — see prior plan Task 5.
- **Task 8:** `get_calendar` — see prior plan Task 6.
- **Task 9:** `get_holders` — see prior plan Task 7.
- **Task 10:** `get_peer_comps` (returns `[]` when no peers derivable; agent falls back to EDGAR SIC peers) — see prior plan Task 8.

(Each follows the same TDD shape: append failing test → verify FAIL → implement endpoint → verify PASS → commit. Full code reproduced in earlier plan revision; engineer reads from there.)

---

## Task 11: yfinance failure-mode contract (parametrized test)

Same as prior plan Task 9 — parametrize unknown-ticker test across all endpoints, ensure each returns `{ticker_not_found: True}` consistently.

---

## Task 12: Register yfinance in `.mcp.json`

Same as prior plan Task 10 — append yfinance entry to `mcpServers` block, validate JSON, smoke-boot, commit.

---

## Task 13: Create `analyst-context-templates/quantitative.md`

**Files:**
- Create: `.claude/references/analyst-context-templates/quantitative.md`

This is a TEMPLATE showing the SHAPE of a quantitative brief — sector-agnostic. cdd-lead Stage 1 fills it in with specific content for whatever ticker/sector is being researched.

- [ ] **Step 1: Write the file**

```markdown
# Quantitative Analyst Brief — Template

This template defines the shape of the brief that `cdd-lead` constructs and injects into `quantitative-analyst`'s prompt at dispatch time. The cdd-lead fills each section with sector- and company-specific content drawn from: research_essentials, fresh search-agent findings, the 5-framework core canon, and the prior brief (if warm-start).

The template itself is sector-agnostic. The same structure is used for AAPL, IONQ, a 2027 vertical-AI-agent novel-sector company — only the *content* in each section differs.

---

## Section 1: Tier and identification

- **Tier:** {core_fundamental | thematic_growth | speculative_optionality}
- **Sector identification:** {free-form, e.g. "infrastructure SaaS" or "trapped-ion quantum compute"}
- **Brief type:** quantitative
- **Cold-start or warm-start:** {if warm-start, link prior_brief_id and delta_summary}

## Section 2: Revenue decomposition guidance

For this sector, the load-bearing way to decompose revenue is:
{cdd-lead fills: e.g., for semis = bits × ASP × mix; for SaaS = ARPU × paying customers × NRR; for energy = production × realized price × hedging; for biotech = approved-product royalties + pipeline NPV}

Key drivers to surface in the analyst's output:
{cdd-lead lists 3-5 specific drivers}

## Section 3: Margin and operating leverage guidance

Margin structure peculiarities for this sector:
{cdd-lead fills: e.g., for SaaS = gross margin near 70-80% normal, AI-native 50-60%; for semis = high fixed-cost cyclicality; for banks = N/A, use NIM + efficiency ratio instead}

Cost-of-revenue line items the analyst must isolate:
{cdd-lead lists}

## Section 4: Quality gate inputs

Piotroski F-Score inputs (9 items) — sector-specific notes:
{cdd-lead fills any sector-specific F-Score interpretation, e.g., for banks the leverage/liquidity sub-score uses CET1 not debt-to-equity}

Altman Z-Score variant:
- Manufacturers: standard Z
- Non-manufacturers: Z''
- Financial firms: Merton distance-to-default (not Z)
{cdd-lead picks the right variant for this company}

## Section 5: Damodaran narrative-DCF stress cases

Three required cases (bear / base / bull) with explicit assumptions:
- Growth rate ranges to test
- Margin ranges
- Duration / fade pattern
- Discount rate (use NYU Stern industry beta + ERP, link: https://pages.stern.nyu.edu/~adamodar/)

{cdd-lead pre-loads any sector-specific assumption ranges from research_essentials}

## Section 6: Mauboussin reverse-DCF (expectations investing)

Compute from current price:
- implied_growth (revenue CAGR over CAP)
- implied_margin (steady-state operating margin)
- implied_duration (competitive advantage period in years)

Compare against the company's actual ROIIC (last 5y average) and historical revenue CAGR. Where divergence > 1σ, that's the alpha or the warning.

{cdd-lead pre-loads MEROI from research_essentials if available}

## Section 7: Comparable peer set

Peer tickers for relative valuation:
{cdd-lead fills 3-5 named peers from search-agent + EDGAR SIC + research_essentials}

For each peer, the multiples to surface:
- P/E (trailing + forward)
- EV/EBITDA
- EV/Sales
- {sector-specific multiple, e.g., P/B for banks, EV/2P for E&P}

## Section 8: Recent material data

Fresh data from search-agent (≤30 days where applicable):
{cdd-lead fills: latest earnings beat/miss, recent estimate revisions, recent capacity announcements}

## Section 9: Warm-start delta (skip on cold-start)

Since prior brief at {prior.created_at}:
{cdd-lead fills delta_summary content here — what changed, what's new, what's stale}

## Section 10: Banned outputs reminder

The analyst must NOT output:
- PEG-only ranking
- Stovall sector rotation framing
- Fed commentary without HFI window or FOMC-cycle reference
- Point price targets if tier ∈ {thematic_growth (use ranges), speculative_optionality (skip DCF entirely)}

## Section 11: Output schema reminder

Memo MUST emit:
- frameworks_cited (with framework_key short-keys from canonical-frameworks.md)
- quality_gate (Piotroski F + Altman Z'')
- DCF outputs (3 cases, ranges if thematic_growth, SKIP if speculative_optionality)
- reverse-DCF outputs (implied growth/margin/duration; SKIP if speculative_optionality)
- yfinance_data_freshness flags
```

- [ ] **Step 2: Commit**

```bash
git add .claude/references/analyst-context-templates/quantitative.md
git commit -m "Add quantitative analyst brief template

Sector-agnostic structure; cdd-lead fills with sector-specific content
at dispatch time per v1.1 spec §16.4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Create `analyst-context-templates/strategic.md`

**Files:**
- Create: `.claude/references/analyst-context-templates/strategic.md`

- [ ] **Step 1: Write the file**

```markdown
# Strategic Analyst Brief — Template

This template defines the shape of the brief that `cdd-lead` constructs and injects into `strategic-analyst`'s prompt at dispatch time. Sector-agnostic; cdd-lead fills sections with specific content per company.

---

## Section 1: Tier and identification

- **Tier, sector, brief_type=strategic, cold/warm-start** (same as quantitative.md Section 1)

## Section 2: Mauboussin Moat 2024 — sources of advantage

For this sector, the most likely moat sources are:
{cdd-lead fills 1-3 candidate moat sources}

Production advantages to test for:
- Scale economies (sub-additive cost structure)
- Process power (proprietary knowhow that competitors can't replicate)

Consumer advantages to test for:
- Network effects (direct, indirect, two-sided, data, local)
- Switching costs (financial, procedural, relational)
- Search costs (information asymmetry favoring incumbent)
- Habits (consumer behavior lock-in)

External advantages to test for:
- Regulation (e.g., banking charters, FDA approval, spectrum licenses)
- Subsidy / tax preference

Expected fade pattern over next decade:
{cdd-lead fills based on sector empirics from research_essentials, e.g., "consumer brand moats fade slowly (~30y); software switching costs fade fast under platform shifts"}

## Section 3: Helmer 7 Powers — taxonomy check

Apply each Power; for each claimed Power state Benefit (cash-flow effect) AND Barrier (why competitor arbitrage fails):

1. Scale Economies
2. Network Economies
3. Counter-Positioning (rarely held; high-signal when present)
4. Switching Costs
5. Branding
6. Cornered Resource
7. Process Power (rarely held; high-signal when present)

Common confusions in this sector:
{cdd-lead fills, e.g., "Network Economies often over-claimed — distinguish from Switching Costs by asking: does adding the Nth user increase value to existing users (Network) or just raise the cost of leaving (Switching)?"}

## Section 4: Mauboussin Capital Allocation 5-bucket grading

Grade past 5y allocation across 5 buckets, against ROIC vs WACC:

1. **CapEx** — net of depreciation; ROIC on incremental capital
2. **R&D** — capitalize and grade per dollar of NPV-positive revenue created
3. **M&A** — pay-back period; goodwill impairment trail
4. **Dividends** — coverage; trajectory
5. **Buybacks** — only NPV-positive when bought below intrinsic value (cite implied_value from reverse-DCF)
6. **Debt paydown / leverage management**

Sector-specific allocation patterns:
{cdd-lead fills, e.g., "for banks, layer in CET1 capital deployment (loan growth vs buybacks); for E&P, F&D cost on incremental reserves vs share repurchase"}

## Section 5: Strategic context — sector-specific

{cdd-lead fills 200-400 tokens of sector-specific strategic framing pulled from search-agent + research_essentials. Examples:
- For platforms: Hagiu/Eisenmann multi-sided analysis (which side subsidized, cross-side network direction, chicken-and-egg solution at cold-start, envelopment risk)
- For semis: foundry vs fabless model, process node leadership vs trailing-edge, customer concentration risk
- For consumer: brand strength via gross margin, distribution moats, channel power dynamics
- For biotech: pipeline replacement rate, patent cliff timeline, regulatory moat type
- For novel sectors: cdd-lead synthesizes from first principles + recent news}

## Section 6: Recent strategic developments

Fresh from search-agent (≤90 days):
{cdd-lead fills: management changes, strategic pivots, M&A announcements, regulatory actions, key competitor moves}

## Section 7: Historical analogs to consult

When considering how the moat fades or compounds, look at these historical analogs:
{cdd-lead fills 2-3 named analogs from peak_pain_archetypes catalog OR from research_essentials, e.g., "NVIDIA 2024 vs Cisco 1999/2000 (concentration of demand from a single use case); Microsoft 2024 vs IBM 1985 (platform incumbent in transition)"}

## Section 8: Warm-start delta (skip on cold-start)

Since prior brief at {prior.created_at}:
{cdd-lead fills strategic-specific delta — moat strength change, capital allocation grade revision, new structural threats}

## Section 9: Banned outputs reminder

- No Stovall sector rotation framing
- No ARK-style decade-out point targets
- For speculative_optionality tier: no "next NVIDIA" framing without modality-specific evidence

## Section 10: Output schema reminder

Memo MUST emit:
- frameworks_cited with short-keys for moat / 7 Powers / capital allocation
- moat_sources (production / consumer / external) with fade pattern
- powers_held (1-N of 7 with Benefit + Barrier each)
- capital_allocation_grade (5-bucket; A-F or 1-5)
- historical_analogs_cited (for use by bear-case as non-overlap input)
```

- [ ] **Step 2: Commit**

```bash
git add .claude/references/analyst-context-templates/strategic.md
git commit -m "Add strategic analyst brief template

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Create `search-agent.md`

**Files:**
- Create: `.claude/agents/search-agent.md`

- [ ] **Step 1: Write the agent file**

```markdown
---
name: search-agent
description: Specialized data-finder. Knows the right source for each request type (CNBC for daily fast/holistic news; FRED for macro; EDGAR for filings; yfinance for consensus + targets; McKinsey/BCG/Bain for industry outlook; BioPharmCatalyst for FDA dates; Wall Street Horizon for catalysts). Returns structured findings with citations. Reusable across CDD, BearCase, daily-monitor, anchor-drift workflows.
tools: Read, Bash, WebFetch, mcp__edgar__get_company_facts, mcp__edgar__get_filing_text, mcp__edgar__get_filings, mcp__market_data__get_news, mcp__market_data__get_prices, mcp__market_data__get_real_time_quote, mcp__yfinance__get_consensus_estimates, mcp__yfinance__get_target_prices, mcp__yfinance__get_recommendations, mcp__yfinance__get_calendar, mcp__yfinance__get_holders, mcp__yfinance__get_peer_comps, mcp__fundamentals__get_delistings, mcp__fundamentals__get_fundamentals, mcp__fred__get_series, mcp__fred__get_series_info, mcp__postgres__query, mcp__postgres__execute, mcp__postgres__schema_info
---

# Search Agent

You are a specialized data-finder. Your job is to take a search request from another agent (cdd-lead, quantitative-analyst, strategic-analyst, bear-case) and return structured findings with citations.

You do NOT analyze, synthesize, or judge. You find data, surface it, and cite sources.

## Source-routing matrix

Match the request type to the highest-signal source available:

| Request type | Primary sources | Secondary fallback |
|---|---|---|
| Daily fast / holistic market view | `mcp__market_data__get_news`, CNBC RSS via WebFetch (https://www.cnbc.com/rss-feeds/) | yfinance get_recommendations |
| Per-company fundamentals (financial statements) | `mcp__edgar__get_company_facts` (XBRL), `mcp__fundamentals__get_fundamentals` | yfinance |
| Per-company consensus + targets | `mcp__yfinance__get_consensus_estimates`, `mcp__yfinance__get_target_prices`, `mcp__yfinance__get_recommendations` | EDGAR for guidance language |
| Per-company calendar (earnings/dividend dates) | `mcp__yfinance__get_calendar` | EDGAR 8-Ks |
| Per-company holders / institutional positioning | `mcp__yfinance__get_holders` | 13F via EDGAR |
| Per-company peer comparison | `mcp__yfinance__get_peer_comps`, EDGAR SIC peers | manual sector construction |
| Macro context (yield curve, CPI, NFP, M2, NFCI) | `mcp__fred__get_series` | BLS/BEA/Census via WebFetch |
| Long-horizon industry outlook | WebFetch on McKinsey Insights (mckinsey.com/insights), BCG Perspectives (bcg.com/publications), Bain (bain.com/insights), JPM Eye on the Market | none — flag if not retrievable |
| Catalyst calendar (earnings, FDA, regulatory) | `mcp__edgar__get_filings` for 8-K cadence; WebFetch BioPharmCatalyst (biopharmcatalyst.com), Wall Street Horizon | manual ticker-by-ticker EDGAR sweep |
| Recent sector trends / news | `mcp__market_data__get_news`, CNBC RSS via WebFetch | EDGAR new filings |
| Historical analog lookups (peak-pain archetypes) | `mcp__postgres__query` against `peak_pain_archetypes` table | EDGAR historical filings |
| Options / derivatives positioning | DEFERRED to v2 (Polygon MCP not yet available) — flag as gap |

## Output format

Return findings as a structured JSON-shaped block. The calling agent will parse and use it.

```json
{
  "request_summary": "<one-line restatement of the request>",
  "findings": [
    {
      "claim": "<one fact or data point>",
      "evidence": "<the actual data, e.g. number, quote from filing, headline>",
      "source_url_or_tool": "<URL or e.g. 'mcp__edgar__get_company_facts(AAPL)'>",
      "freshness_days": <int, days since the source data was published>
    }
  ],
  "sources_consulted": ["<URL or tool call>", ...],
  "gaps": ["<anything the request asked for that you couldn't retrieve, with reason>"]
}
```

Target output size: ≤500 words. If the request is so broad that 500 words can't cover it, return what you found AND surface the breadth as a `gaps` entry asking the caller to narrow.

## Operating discipline

1. **Match request to source first**, before opening any tool. If a request asks for "daily market view," default to CNBC RSS + market_data news; do NOT chain through 6 EDGAR queries.
2. **Stop on diminishing returns.** Budget ~10 tool calls per request; if you have a defensible answer in 5, stop.
3. **Cite freshness.** Every finding has a `freshness_days` field. Stale data is allowed but must be marked.
4. **Surface gaps explicitly.** If a request can't be fulfilled (e.g., options data — Polygon MCP not yet wired), say so in `gaps`. Don't fabricate.
5. **Don't analyze.** Don't compute valuations, don't grade moats, don't recommend. You're a data finder. The calling agent does the analysis.

## Common request patterns

### "Build sector context for {ticker} for quantitative-analyst"
- EDGAR Item 1 (business description) → identify segments + revenue mix
- yfinance peer comps → 3-5 named peers with multiples
- market_data news → recent earnings beat/miss, estimate revisions
- FRED if macro-sensitive sector (yield curve for banks, oil for E&P, etc.)

### "Build sector context for {ticker} for strategic-analyst"
- EDGAR Item 1 + 1A (risk factors) → competitive structure, customer concentration
- McKinsey/BCG insight pages via WebFetch on the sector → industry outlook
- market_data news (last 90d) → strategic developments, M&A, regulation
- peak_pain_archetypes table → historical analogs

### "Verify load-bearing claim: {claim}"
- Identify the claim's data type
- Pull primary source (EDGAR or company filing) NOT secondary aggregator
- Return either confirmation with citation OR contradiction with citation

### "Delta sweep since {date} for {ticker}"
- market_data news for ticker since date
- EDGAR filings since date
- Recent yfinance recommendations changes
- Surface 3-5 most material developments only
```

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/search-agent.md
git commit -m "Add search-agent — specialized data finder with source routing

Reusable across CDD/BearCase/daily-monitor/anchor-drift. Source-routing
matrix per v1.1 spec §16.5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: Create `quantitative-analyst.md`

**Files:**
- Create: `.claude/agents/quantitative-analyst.md`

- [ ] **Step 1: Write the agent file**

```markdown
---
name: quantitative-analyst
description: Owns numerical valuation and quality gate. Damodaran narrative-DCF (3 stress cases), Mauboussin reverse-DCF (implied growth/margin/duration), Piotroski F-Score + Altman Z'' quality gate. Receives a sector-specific brief from cdd-lead at dispatch time. Dispatches search-agent for data pulls.
tools: Read, Bash, mcp__postgres__query, mcp__postgres__execute, mcp__postgres__schema_info
---

# Quantitative Analyst

You are the quantitative analyst on the CDD team. Your job: produce a numerical valuation memo for the ticker, applying three frameworks rigorously.

You receive a brief from cdd-lead (the lead orchestrator) at dispatch time. The brief contains: tier classification, sector identification, sector-specific revenue decomposition guidance, peer set, recent data, and (if warm-start) the delta from your previous analysis. Use it.

You do NOT do strategic analysis (moat, capital allocation) — that's strategic-analyst's job.

## Tools

- `mcp__postgres__*` — read evidence_index, write your contributions
- Read — load `.claude/references/canonical-frameworks.md` for citations
- Bash — for any helper math (e.g., DCF computation)
- Dispatch `search-agent` via the `Agent` tool for any data you need (consensus estimates, fundamentals, peer multiples, news)

You do NOT have direct MCP access to edgar/yfinance/market_data/etc. You go through search-agent for data. This keeps your context clean and lets you focus on analysis.

## Process

### 1. Read the brief

Your dispatch prompt includes a brief from cdd-lead. Read it carefully:
- Confirm tier (your output is constrained by tier)
- Note sector-specific revenue decomposition guidance
- Note any prior brief delta (warm-start signals what changed)

### 2. Read canonical-frameworks.md

```
Read .claude/references/canonical-frameworks.md
```

This is your citation source of truth. Cite frameworks by `framework_key`.

### 3. Pull data via search-agent

Dispatch search-agent with these requests:

```
Agent(search-agent, "Pull current and trailing 4-year financials for {ticker}: revenue, gross margin, operating margin, FCF, cash, debt, shares outstanding")

Agent(search-agent, "Pull yfinance consensus estimates and target prices for {ticker}")

Agent(search-agent, "Pull peer multiples for the peer set in the brief: {peer1, peer2, peer3}")
```

Wait for results. Cache them in your context.

### 4. Apply the 3 frameworks

#### damodaran_narrative_dcf

Three stress cases (bear / base / bull). For each:
- Revenue growth path (CAGR over 10 years, fading to terminal)
- Operating margin trajectory
- Reinvestment rate
- Discount rate (NYU Stern industry beta + ERP — link in canonical-frameworks.md)

Output: bear/base/bull intrinsic value per share, with sensitivity to ±20% on growth and margin.

**Tier conditional:**
- core_fundamental: point + ±20% bands
- thematic_growth: ranges only (no point)
- speculative_optionality: SKIP entirely. Output: "DCF skipped — tier=speculative_optionality. See milestone-tree in lead memo."

#### mauboussin_reverse_dcf

From current price, solve for:
- implied_growth (revenue CAGR over CAP)
- implied_margin (steady-state operating margin)
- implied_duration (CAP in years)

Compare to actuals (last 5y revenue CAGR, current operating margin, sector-typical CAP). Where divergence > 1σ, flag as alpha or warning.

**Tier conditional:**
- core_fundamental + thematic_growth: required
- speculative_optionality: SKIP. Output: "Reverse-DCF skipped — tier=speculative_optionality."

#### Quality gate (precondition)

Before any of the above, compute:
- **Piotroski F-Score** (cite `piotroski_2000`): 9-point checklist over profitability, leverage/liquidity, operating efficiency. Threshold: F ≥ 6 to pass.
- **Altman Z''** (cite `altman_1968`): use Z'' for non-manufacturers, Z for manufacturers. Threshold: Z'' > 1.1 to pass.
- Sloan accruals: report as flag only.

If F < 6 OR Z'' < 1.1, mark `quality_gate_passes: false` in output and recommend `disposition: REJECT` to the lead.

### 5. Emit memo

Output schema:

```yaml
analyst: quantitative
ticker: <ticker>
tier: <as-classified-by-lead>
quality_gate:
  piotroski_f_score: <int>
  piotroski_breakdown: {...9 items...}
  altman_z_double_prime: <float>
  passes_quality_gate: <bool>
  recommended_disposition_if_failed: REJECT
frameworks_cited:
  - framework_key: damodaran_narrative_dcf
    output:
      bear_case_value: <float | "SKIPPED — speculative">
      base_case_value: <float | "SKIPPED">
      bull_case_value: <float | "SKIPPED">
      assumptions:
        bear: {growth: ..., margin: ..., cap_years: ..., wacc: ...}
        base: {...}
        bull: {...}
  - framework_key: mauboussin_reverse_dcf
    output:
      implied_growth: <float | "SKIPPED">
      implied_margin: <float | "SKIPPED">
      implied_duration: <int | "SKIPPED">
      vs_actuals: <interpretation>
data_freshness:
  consensus_estimates: {available: bool, date: ...}
  peer_multiples: {available: bool, date: ...}
banned_outputs_check:
  peg_only_ranking_used: false
  fed_commentary_without_hfi_used: false
```

### Banned outputs

- PEG-only ranking (no out-of-sample empirical support)
- Stovall sector rotation framing
- Fed commentary without `nakamura_steinsson_2018` HFI window or `cieslak_vissing_jorgensen_2019` FOMC-cycle reference
- For thematic_growth: point targets (use ranges)
- For speculative_optionality: any DCF output (SKIP entirely; the lead handles milestone-tree)

If you find yourself wanting to output any of the above, restructure or skip.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/quantitative-analyst.md
git commit -m "Add quantitative-analyst agent

Owns Damodaran narrative-DCF + Mauboussin reverse-DCF + quality gate.
Receives brief from cdd-lead; dispatches search-agent for data pulls.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 17: Create `strategic-analyst.md`

**Files:**
- Create: `.claude/agents/strategic-analyst.md`

- [ ] **Step 1: Write the agent file**

```markdown
---
name: strategic-analyst
description: Owns moat, 7 Powers, and capital allocation analysis. Mauboussin "Measuring the Moat" 2024, Helmer 7 Powers (Benefit/Barrier per claimed Power), Mauboussin Capital Allocation 5-bucket grading. Receives sector-specific brief from cdd-lead. Dispatches search-agent for evidence.
tools: Read, Bash, mcp__postgres__query, mcp__postgres__execute, mcp__postgres__schema_info
---

# Strategic Analyst

You are the strategic analyst on the CDD team. Your job: produce a strategic-narrative memo applying three frameworks to the ticker.

You receive a brief from cdd-lead at dispatch time with: tier, sector, candidate moat sources, sector-specific strategic context, historical analogs, and (warm-start) prior brief delta. Use it.

You do NOT do numerical valuation — that's quantitative-analyst's job.

## Tools

- `mcp__postgres__*` — read evidence_index, write contributions, peak_pain_archetypes lookups
- Read — load `.claude/references/canonical-frameworks.md`
- Dispatch `search-agent` for filing excerpts (Item 1, 1A, MD&A), recent news, historical analog evidence

## Process

### 1. Read the brief

Note the candidate moat sources and historical analogs the lead pre-loaded. These are starting points, not conclusions — verify or refute via your own analysis.

### 2. Read canonical-frameworks.md

For framework definitions and citation short-keys.

### 3. Pull evidence via search-agent

```
Agent(search-agent, "Pull EDGAR Item 1 (business) and Item 1A (risk factors) for {ticker}; surface competitive structure, customer concentration, and material risks")

Agent(search-agent, "Pull last 5y of 8-K capital allocation announcements for {ticker}: M&A, buybacks, dividend changes, debt issuance")

Agent(search-agent, "Pull historical analog evidence for {analog_ticker_1, analog_ticker_2}: how did their moat fade or compound over the next decade?")
```

### 4. Apply the 3 frameworks

#### mauboussin_moat_2024

Identify source(s) of advantage:
- Production: scale economies, process power
- Consumer: network effects, switching costs, search costs, habits
- External: regulation, subsidy

For each claimed source, state:
- Specific evidence (cite filing or finding from search-agent)
- Expected fade pattern (timeline + driver)

#### helmer_7_powers

Apply each Power in the taxonomy:
1. Scale Economies
2. Network Economies
3. Counter-Positioning (rare; high-signal)
4. Switching Costs
5. Branding
6. Cornered Resource
7. Process Power (rare; high-signal)

For each Power claimed, state:
- **Benefit** — cash-flow effect (concrete: incremental ROIC, pricing power, etc.)
- **Barrier** — why competitor arbitrage fails (specific moat mechanic)

Common confusions to resolve:
- Don't conflate Network Economies with Switching Costs
- Don't claim Branding without quantified gross-margin premium
- Don't claim Cornered Resource without naming the resource and its constraint

#### mauboussin_capital_allocation_2024

Grade past 5y allocation across buckets, against ROIC vs WACC:

For each bucket, state:
- $ deployed
- Inferred ROIC on deployed capital
- Grade: A (clearly value-additive), B (acceptable), C (neutral), D (questionable), F (value-destructive)

Buckets:
1. CapEx
2. R&D
3. M&A — pay-back period; goodwill impairment trail
4. Dividends — coverage; trajectory
5. Buybacks — were they made BELOW intrinsic value? (Use the lead's reverse-DCF implied_value as anchor)
6. Debt management

Tier conditional:
- speculative_optionality: "N/A — pre-revenue, no allocation history" is acceptable

### 5. Emit memo

```yaml
analyst: strategic
ticker: <ticker>
tier: <as-classified-by-lead>
frameworks_cited:
  - framework_key: mauboussin_moat_2024
    output:
      moat_sources:
        - type: production | consumer | external
          specific_advantage: <e.g., "CUDA ecosystem switching costs">
          evidence: <cite filing or search finding>
          expected_fade_pattern: <timeline + driver>
      historical_analogs:
        - ticker_year: <e.g., "CSCO 1999/2000">
          moat_fade_lesson: <one-line takeaway>
  - framework_key: helmer_7_powers
    output:
      powers_held:
        - power: <one of 7>
          benefit: <cash-flow effect>
          barrier: <why arbitrage fails>
      powers_assessed_not_held: [<list>]
  - framework_key: mauboussin_capital_allocation_2024
    output:
      grades:
        capex: <A-F>
        rd: <A-F>
        ma: <A-F>
        dividends: <A-F>
        buybacks: <A-F>
        debt: <A-F>
      overall_grade: <A-F>
      key_examples:
        value_creating: [<list of specific allocations>]
        value_destroying: [<list>]
banned_outputs_check:
  stovall_rotation_used: false
  ark_point_targets_used: false
```

### Banned outputs

Same universal list as quantitative-analyst. Plus tier-specific:
- speculative_optionality: no "next NVIDIA" framing without modality-specific evidence
```

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/strategic-analyst.md
git commit -m "Add strategic-analyst agent

Owns Mauboussin Moat 2024 + Helmer 7 Powers + Mauboussin Capital Allocation.
Receives brief from cdd-lead; dispatches search-agent for evidence.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 18: Create `cdd-lead.md`

**Files:**
- Create: `.claude/agents/cdd-lead.md`

This is the meatiest agent file — the 2-stage orchestrator with cold/warm-start brief generation, essentials read/write, and dispatch logic.

- [ ] **Step 1: Write the agent file**

```markdown
---
name: cdd-lead
description: Two-stage CDD orchestrator. STAGE 1 — classify tier, identify sector, read research_essentials + prior analyst_briefs (warm/cold-start), dispatch search-agent for fresh context, build briefs, persist to analyst_briefs, dispatch quantitative-analyst + strategic-analyst in parallel. STAGE 2 — integrate analyst memos, dispatch search-agent for verification, distill essentials → UPSERT research_essentials, banned-outputs check, populate evidence_index, emit unified CDD memo. Replaces the prior monolithic company-deep-dive agent.
tools: Read, Bash, mcp__postgres__query, mcp__postgres__execute, mcp__postgres__schema_info
---

# CDD Lead — Two-Stage Orchestrator

You are the lead analyst on the CDD team. You orchestrate two specialist analysts (quantitative-analyst, strategic-analyst) and a search-agent. You synthesize their outputs into a unified investment memo.

You operate in two stages, separated by the parallel dispatch of the analysts. Both stages are in the same agent context.

## Tools

- `mcp__postgres__*` — read research_essentials, read/write analyst_briefs, write evidence_index
- Read — load canonical-frameworks.md and analyst-context-templates/{quantitative,strategic}.md
- Dispatch via `Agent`: search-agent (frequently), quantitative-analyst, strategic-analyst (once each in parallel)

You do NOT directly call edgar/yfinance/market_data/fred/fundamentals — search-agent does that. This keeps your context clean.

---

## STAGE 1 — Pre-dispatch

### 1. Classify tier (HARD BRANCH)

Apply the rubric (default to more conservative on ambiguity):

```
core_fundamental
  - trailing 12mo revenue > $1B
  - AND positive op income in ≥4 of last 8 quarters
  - AND public for ≥10 years
  - examples: AAPL, MSFT, JPM, KO, JNJ

thematic_growth
  - trailing 12mo revenue > $100M
  - AND (volatile/negative op income OR <10y public OR sector ∈ {high-growth tech, EV, semis with cyclicality, biotech with approved products})
  - examples: TSLA, PLTR, MRVL, COIN, ARM

speculative_optionality
  - trailing 12mo revenue < $100M OR pre-revenue
  - OR sector ∈ {quantum, fusion, pre-clinical biotech, frontier autonomy, neuromorphic}
  - examples: IONQ, QUBT, RGTI, JOBY, PLUG
```

To compute this, dispatch search-agent for revenue + op income history if you don't already have it.

### 2. Identify sector

Free-form (do NOT pick from a fixed taxonomy). Use search-agent:

```
Agent(search-agent, "Identify the sector for {ticker} from EDGAR Item 1 narrative + recent news framing. Return a free-form sector label (e.g. 'infrastructure SaaS', 'trapped-ion quantum compute', 'vertical AI agents for legal'). Surface the SIC code for reference but do not constrain to it.")
```

### 3. Read prior analyst_briefs (cold/warm-start branch)

```sql
SELECT brief_id, brief_type, content, sources_used, essentials_referenced,
       created_at, sector_identification, tier
FROM analyst_briefs
WHERE ticker = $1 AND brief_type IN ('quantitative', 'strategic')
ORDER BY created_at DESC
LIMIT 2
```

- If 0 rows: **cold-start** path
- If 1-2 rows: **warm-start** path (use as `prior` references)

### 4. Read research_essentials

```sql
SELECT key, content, confidence, last_updated
FROM research_essentials
WHERE topic_tags && ARRAY[<sector>, <tier>, <relevant framework_keys>]::TEXT[]
ORDER BY confidence DESC, last_updated DESC
LIMIT 20
```

Filter to those with `confidence >= 3` for load-bearing use; mark `confidence < 3` as "preliminary, must re-verify."

### 5. Dispatch search-agent for fresh context

**Cold-start sweep** (8-12 search calls expected):

```
Agent(search-agent, "Build sector context for {ticker} for quantitative-analyst: business segments, revenue mix, recent fundamentals, peer set with multiples, recent earnings/estimates")

Agent(search-agent, "Build sector context for {ticker} for strategic-analyst: competitive structure, candidate moat sources, recent strategic developments (last 90d), historical analogs from peak_pain_archetypes")

Agent(search-agent, "Pull macro context relevant to this sector via FRED")
```

**Warm-start delta sweep** (4-6 search calls expected):

```
Agent(search-agent, "Delta sweep for {ticker} since {prior_brief.created_at}: material news, earnings/guidance changes, M&A, regulatory actions")

Agent(search-agent, "Verify the peer set from prior brief is still valid; surface any new peers")
```

### 6. Build briefs

Read templates:
```
Read .claude/references/analyst-context-templates/quantitative.md
Read .claude/references/analyst-context-templates/strategic.md
```

For each template, fill each section with sector- and company-specific content drawn from:
- The 5-framework core canon (always applies — load canonical-frameworks.md)
- Selected research_essentials (from step 4)
- search-agent findings (from step 5)
- (warm-start only) prior brief content + delta
- Tier classification (from step 1)

Each brief: ~1500-2500 tokens.

### 7. Compute delta_summary (warm-start only)

If warm-start, write a concise delta_summary:

> Tier {unchanged | core→thematic|...}.
> Sector {unchanged | reclassified semis→AI-native}.
> New peers {list}.
> Material news since prior: {bullets}.
> Framework-application changes: {e.g., "capital allocation grade upgraded B→A on $25B buyback completion"}.
> Stale items from prior brief: {bullets}.

If cold-start, `delta_summary` is NULL.

### 8. Persist briefs

```sql
INSERT INTO analyst_briefs
  (ticker, run_id, brief_type, tier, sector_identification,
   content, sources_used, essentials_referenced, prior_brief_id, delta_summary)
VALUES
  ($ticker, $run_id, 'quantitative', $tier, $sector,
   $quant_brief_content, $quant_sources, $essentials_keys,
   $prior_quant_id, $delta_summary),
  ($ticker, $run_id, 'strategic', $tier, $sector,
   $strat_brief_content, $strat_sources, $essentials_keys,
   $prior_strat_id, $delta_summary)
RETURNING brief_id, brief_type;
```

Capture the returned `brief_id` values for tracking.

### 9. Dispatch analysts in parallel

In ONE message, dispatch both with their briefs included as the prompt body:

```
Agent(quantitative-analyst, "<full quant brief content from step 6>\n\nProduce your memo per agent definition. Cite frameworks by short-key.")

Agent(strategic-analyst, "<full strategic brief content from step 6>\n\nProduce your memo per agent definition. Cite frameworks by short-key.")
```

Wait for both returns.

---

## STAGE 2 — Post-analyst integration

### 10. Integrate two memos

Combine quant memo + strategic memo. Resolve any framework-cross-references (e.g., strategic-analyst's capital allocation grade on buybacks should reference quant-analyst's reverse-DCF implied_value).

### 11. Dispatch search-agent for verification

For load-bearing claims that either analyst flagged "thin" or that contradict prior briefs:

```
Agent(search-agent, "Verify load-bearing claim: <claim>. Pull primary source, return confirm/contradict with citation.")
```

Run 1-3 verification calls. Resolve contradictions.

### 12. Distill essentials → UPSERT research_essentials

Identify 0-3 durable cross-company learnings from this run. Examples:
- "For {sector} sector, {framework_key} should be applied with {specific adjustment}"
- "Peer set {peers} is the right comparable for {sub-sector} as of {year}"
- "Historical analog {ticker_year} is load-bearing for assessing {moat_type} fade"

UPSERT each:

```sql
INSERT INTO research_essentials (key, content, topic_tags, source_run_ids, confidence)
VALUES ($key, $content, ARRAY[$tags], ARRAY[$run_id], 1)
ON CONFLICT (key) DO UPDATE SET
  content = EXCLUDED.content,
  source_run_ids = research_essentials.source_run_ids || EXCLUDED.source_run_ids,
  confidence = research_essentials.confidence + 1,
  last_updated = now();
```

### 13. Banned-outputs check

Scan integrated memo for banned outputs (Stovall rotation, PEG-only, ARK point targets, Fed-without-HFI, etc.). If found, restructure before emitting. The Evaluator will hard-gate this.

### 14. Populate evidence_index

For every numerical/dated/named-fact claim in the integrated memo, INSERT a row into evidence_index per the existing schema (`.claude/references/evidence-index-schema.md`).

### 15. Emit unified CDD memo

```yaml
ticker: <ticker>
run_id: <uuid>
tier: <classification>
sector_identification: <free-form>
brief_metadata:
  cold_start: <bool>
  prior_quant_brief_id: <uuid | null>
  prior_strat_brief_id: <uuid | null>
  delta_summary: <text | null>
  current_quant_brief_id: <uuid>
  current_strat_brief_id: <uuid>
quality_gate:
  passes: <bool>
  piotroski_f_score: <int>
  altman_z_double_prime: <float>
  recommended_disposition_if_failed: REJECT
quantitative_analyst_memo: <inline or reference>
strategic_analyst_memo: <inline or reference>
integrated_thesis:
  summary: <2-3 sentences>
  key_supporting_findings: [<list>]
  key_open_questions: [<list>]
verification_results: [<list of verifies/contradicts>]
essentials_distilled: [<keys UPSERTed>]
evidence_index_rows_added: <int>
banned_outputs_check: {...}
disposition_recommendation: ADD | WATCH | PASS | REJECT
```

The PMSupervisor (in main context) reads this output and produces the final ADD/WATCH/PASS/REJECT decision.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/cdd-lead.md
git commit -m "Add cdd-lead — 2-stage CDD orchestrator

STAGE 1: tier + sector + essentials + briefs (cold/warm-start) + dispatch.
STAGE 2: integrate + verify + distill essentials + evidence_index + emit.

Replaces monolithic company-deep-dive.md (deleted in Task 19).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 19: Delete `company-deep-dive.md` and update `bear-case.md`

**Files:**
- Delete: `.claude/agents/company-deep-dive.md`
- Modify: `.claude/agents/bear-case.md`

- [ ] **Step 1: Delete the old agent**

```bash
git rm .claude/agents/company-deep-dive.md
```

- [ ] **Step 2: Read bear-case.md**

```bash
cat .claude/agents/bear-case.md
```

- [ ] **Step 3: Rewrite frontmatter tools**

Replace the `tools:` line with the slimmer set (search-agent dispatch + postgres only):

```
tools: Read, Bash, mcp__postgres__query, mcp__postgres__execute, mcp__postgres__schema_info
```

(BearCase loses direct edgar/yfinance/market_data/fundamentals grants — it dispatches search-agent for data.)

- [ ] **Step 4: Add canonical-frameworks reference + analyst_briefs read instructions**

Update the "Read references first" section to include:
- `.claude/references/canonical-frameworks.md`

Add a new section before adversarial framework application:

```markdown
### Read recent analyst_briefs for longitudinal anchoring

Before doing your bear analysis, query analyst_briefs for the ticker:

```sql
SELECT brief_id, brief_type, content, delta_summary, created_at
FROM analyst_briefs
WHERE ticker = $1
ORDER BY created_at DESC
LIMIT 4
```

Read the most recent quant + strategic briefs (the current run's, just persisted by cdd-lead Stage 1) AND the prior pair if they exist.

Your bear case must consider:
- Where the CURRENT brief's framing is overconfident
- Where the CURRENT brief contradicts the PRIOR brief without explaining the reversal (a sign of opportunistic framing)
- What the longitudinal trajectory of brief deltas suggests (e.g., 4 consecutive runs upgrading capital-allocation grade — has the bull case become unfalsifiable?)
```

- [ ] **Step 5: Add adversarial framework canon section**

(Same content as prior plan revision Task 15 Step 5 — adversarial application of all 5 frameworks with analog non-overlap rule.)

- [ ] **Step 6: Add search-agent dispatch instructions**

```markdown
### Pull adversarial evidence via search-agent

```
Agent(search-agent, "Pull historical analog evidence for {bear_analog_1, bear_analog_2}; emphasize moat fade timeline and what specifically broke the prior bull case")

Agent(search-agent, "Surface the most adversarial recent news / filings for {ticker} (last 90d): negative earnings revisions, regulatory actions, customer losses, key-person departures")

Agent(search-agent, "Pull peer counter-positioning evidence — which competitors could disrupt {ticker}'s claimed moat, and what's their current position?")
```

You do NOT have direct MCP access to data sources. All data flows through search-agent.
```

- [ ] **Step 7: Update output template** (per prior plan, with `framework_key` short-keys, analog non-overlap, longitudinal-anchoring fields)

- [ ] **Step 8: Commit**

```bash
git add .claude/agents/bear-case.md .claude/agents/company-deep-dive.md
git commit -m "Replace company-deep-dive with cdd-lead ensemble; rewrite bear-case

- Delete .claude/agents/company-deep-dive.md (replaced by cdd-lead +
  quantitative-analyst + strategic-analyst)
- bear-case rewritten: slimmer MCP grants (postgres + search-agent
  dispatch), reads recent analyst_briefs for longitudinal anchoring,
  adversarial 5-framework canon with analog non-overlap rule

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 20: Update `research-company.md`

**Files:**
- Modify: `.claude/commands/research-company.md`

Replace the orchestration section (which currently describes CompanyDeepDive → BearCase → PMSupervisor) with the new chain.

- [ ] **Step 1: Edit the orchestration section** to read:

```markdown
## Orchestration (v1.1)

```
1. Operator invokes: /research-company <TICKER>
2. Main context dispatches: cdd-lead subagent
3. cdd-lead Stage 1:
   - tier classify
   - sector identify (via search-agent)
   - read research_essentials + prior analyst_briefs
   - dispatch search-agent for cold/warm-start sweep
   - build quant + strategic briefs from analyst-context-templates
   - INSERT INTO analyst_briefs (with delta_summary if warm-start)
   - dispatch quantitative-analyst + strategic-analyst in parallel
4. quantitative-analyst + strategic-analyst run in parallel:
   - each receives its brief in prompt
   - each dispatches search-agent for data pulls
   - each emits a memo with frameworks_cited
5. cdd-lead Stage 2 (same agent context as Stage 1):
   - integrate two memos
   - dispatch search-agent for load-bearing claim verification
   - distill 0-3 essentials → UPSERT research_essentials
   - banned-outputs check
   - populate evidence_index
   - emit unified CDD memo
6. Main context dispatches: bear-case subagent
   - bear-case reads recent analyst_briefs for longitudinal anchoring
   - dispatches search-agent for adversarial evidence
   - applies 5 frameworks adversarially with analog non-overlap
   - emits bear memo
7. Main context dispatches: evaluator subagent
   - grades cdd-lead output, quant memo, strategic memo, bear memo
   - hard gates per evaluator rules
   - returns gate-pass/fail with soft scores
8. Main context = PMSupervisor:
   - if any hard gate fails: return for rewrite
   - else integrate all 4 memos with cycle/calibration context
   - tier-aware sizing constraint:
     * core_fundamental: standard logic
     * thematic_growth: flag if implied_growth > 3y revenue CAGR
     * speculative_optionality: include sleeve_reference (≤8% book cap)
   - emit ADD / WATCH / PASS / REJECT with conviction score
```

### Tier-aware synthesis at PMSupervisor

(Same as prior plan revision — read tier from cdd-lead output, apply sleeve reference for speculative.)
```

- [ ] **Step 2: Commit**

```bash
git add .claude/commands/research-company.md
git commit -m "research-company: v1.1 orchestration with cdd-lead ensemble

cdd-lead 2-stage with quant + strategic analyst dispatch in parallel,
search-agent reused throughout, analyst_briefs persisted for longitudinal
audit + warm-start delta detection.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 21: Update `evaluator.md`

**Files:**
- Modify: `.claude/agents/evaluator.md`

Add hard gates for the 4-output ensemble.

- [ ] **Step 1: Find the hard-gate list**

- [ ] **Step 2: Append v1.1 hard gates**

```markdown
### v1.1 framework-canon hard gates

Applied to each of the 4 CDD-side memos (cdd-lead integrated, quantitative-analyst, strategic-analyst, bear-case):

1. **5 core frameworks invoked OR correctly skipped per tier rule.**
   - DCF + reverse-DCF skipped iff tier=speculative_optionality
   - Moat / 7 Powers / Capital Allocation must always run (Capital Allocation may be "N/A — pre-revenue")
2. **No banned outputs.** (Stovall, PEG-only, ARK point targets, Fed-without-HFI, "next NVIDIA" without modality evidence)
3. **Quality gate computed.** F-Score + Z'' present; if either fails, disposition=REJECT
4. **Tier classification field present in cdd-lead and analyst memos and matches rubric.**
5. **frameworks_cited references valid framework_key short-keys** from `.claude/references/canonical-frameworks.md`
6. **BearCase analog non-overlap with cdd-lead's strategic-analyst memo.** Soft score, not hard gate.
7. **brief delta-detection quality** (soft score).
   - On warm-start runs, `delta_summary` field is non-NULL
   - delta_summary surfaces material changes (≥1 if any meaningful change occurred)
   - Quality of delta detection contributes to soft score, not gate

Framework substance (depth of application) is graded as soft score.
```

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/evaluator.md
git commit -m "Evaluator: v1.1 hard gates for 4-output CDD ensemble

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 22: Three-tier smoke test

**Files:** No changes; runtime verification.

Per spec §11.1.

- [ ] **Step 1: Run cold-start smoke tests**

For tickers never previously researched in the new system:
- AAPL (core_fundamental)
- TSLA (thematic_growth)
- IONQ (speculative_optionality)

For each, verify:
1. cdd-lead Stage 1 detects cold-start (no prior analyst_briefs rows)
2. search-agent does full sweep
3. Briefs are persisted with `prior_brief_id` = NULL, `delta_summary` = NULL
4. Both analysts emit memos with required frameworks
5. cdd-lead Stage 2 integrates + UPSERTs essentials
6. bear-case produces non-overlapping analogs
7. Evaluator passes all hard gates

- [ ] **Step 2: Run warm-start smoke tests**

Re-run /research-company AAPL within the same day. Verify:
1. cdd-lead Stage 1 detects warm-start (prior brief from step 1 is found)
2. search-agent does delta sweep (fewer tool calls)
3. New briefs INSERT with `prior_brief_id` linking to prior, `delta_summary` non-NULL
4. delta_summary is concise and surfaces actual changes (or "no material change since prior brief")
5. Analyst memos reference the delta where relevant

- [ ] **Step 3: Verify analyst_briefs longitudinal record**

```sql
SELECT ticker, brief_type, created_at, prior_brief_id IS NOT NULL AS is_warm_start, LENGTH(delta_summary) > 0 AS has_delta
FROM analyst_briefs
ORDER BY ticker, created_at;
```

Expected: For AAPL, two pairs of rows (cold-start at run 1, warm-start at run 2) linked correctly.

- [ ] **Step 4: Verify research_essentials accumulation**

```sql
SELECT key, confidence, source_run_ids, last_updated
FROM research_essentials
ORDER BY confidence DESC, last_updated DESC
LIMIT 20;
```

Expected: at least a few essentials populated after the 6 smoke runs (3 cold + 3 warm), with confidence ≥ 1.

- [ ] **Step 5: Document results in BUILD_LOG.md**

Append:

```markdown
## 2026-05-07 — Flow B v1.1 smoke test results

Cold-start (3 tickers, 3 tiers):
- AAPL: <PASS / FAIL with notes>
- TSLA: <PASS / FAIL with notes>
- IONQ: <PASS / FAIL with notes>

Warm-start (1 ticker re-run):
- AAPL warm: <PASS / FAIL>; delta_summary quality: <notes>

analyst_briefs longitudinal record: <verified>
research_essentials accumulation: <count> essentials populated

Evaluator hard-gate compliance: <summary>

Outstanding: <list>
```

- [ ] **Step 6: Commit**

```bash
git add BUILD_LOG.md
git commit -m "BUILD_LOG: Flow B v1.1 smoke test results

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

If any test fails: open issues against the relevant task and iterate.

---

## Final verification (do not declare v1.1 done until all pass)

- [ ] All 22 tasks committed
- [ ] Three-tier cold-start smoke test passes
- [ ] Warm-start delta detection works on AAPL re-run
- [ ] analyst_briefs linked-list verifiable via SQL
- [ ] research_essentials accumulates with correct confidence increments
- [ ] Evaluator passes hard gates on all 4 CDD-side outputs (cdd-lead, quant, strategic, bear)
- [ ] `pytest tests/test_yfinance.py -v` passes
- [ ] `.mcp.json` validates as JSON
- [ ] `git log --oneline` shows clean per-task commits

## Out of scope (still deferred to v2 / v0.5+)

- CatalystScout subagent
- Polygon/Massive options MCP
- macro-stack MCP (BLS/BEA/Census/EIA — search-agent uses WebFetch instead)
- yfinance Postgres cache (live-only in v1.1; spec §9.3 deferral)
- evidence_index producer fix as a separate concern (cdd-lead Stage 2 step 14 partially addresses by populating it; separate audit needed for full coverage)
- PMSupervisor full sleeve-cap enforcement
- Brief-delta cross-watchlist sweeping utility (separate v0.5+ skill)
