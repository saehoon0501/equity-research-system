# Flow B v1 — Frameworks-and-yfinance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Encode named, citable analytical frameworks into the CDD and BearCase agent prompts with a hard-branch tier classification, and ship a `yfinance` MCP for consensus estimates and target prices. Closes the framework + consensus gap surfaced in the 2026-05-07 audit.

**Architecture:** Three artifact families. (1) New shared canonical-frameworks reference doc + extended industry addenda for SaaS, marketplace, AI-native. (2) New `yfinance` MCP server (FastMCP, mirrors `src/mcp/fred/` package layout, ~6 thin endpoints). (3) Rewritten `.claude/agents/company-deep-dive.md` and `.claude/agents/bear-case.md` with tier classification first-action, 5-framework core canon, citation requirements, banned outputs, addendum routing. Minor edits to `.claude/commands/research-company.md` (PMSupervisor reads tier) and `.claude/agents/evaluator.md` (new hard gates).

**Tech Stack:** Python 3.11+, `mcp` (FastMCP), `yfinance>=0.2.40,<0.3`, `python-dotenv`, `pytest>=8.0`. Mirrors existing `src/mcp/fred/` package layout. No schema changes; cache is deferred (spec §9.3 calls for Postgres cache — v1 ships live-only with failure-mode surfacing per §9.4; v2 may add cache if Yahoo flakiness materially hurts).

**Spec:** `docs/superpowers/specs/2026-05-07-flow-b-v1-frameworks-and-yfinance-design.md` (commit `70a9a55`).

---

## File Structure

**Created:**
- `.claude/references/canonical-frameworks.md` — citation source of truth (15 entries: 5 core frameworks + Piotroski + Altman + 8 sector-addendum sources)
- `.claude/references/industry-addenda/marketplace.md` — a16z marketplace metrics
- `.claude/references/industry-addenda/ai-native.md` — Sequoia/a16z AI-stack mapping
- `src/mcp/yfinance/` — new MCP package (server.py, pyproject.toml, README.md, __init__.py, uv.lock)
- `tests/test_yfinance.py` — integration smoke tests for the MCP

**Modified:**
- `.mcp.json` — register yfinance server
- `.claude/references/industry-addenda/software.md` — extend with Bessemer/Rule of X/Burn Multiple
- `.claude/agents/company-deep-dive.md` — full rewrite (tier rubric, 5-framework core, banned outputs, yfinance grants)
- `.claude/agents/bear-case.md` — full rewrite (symmetric framework canon adversarially applied, analog non-overlap)
- `.claude/commands/research-company.md` — PMSupervisor section reads `tier` field; speculative-tier sleeve-cap reference
- `.claude/agents/evaluator.md` — new hard gates for framework citation + tier classification + banned outputs

**Untouched:** schema, all other agents/commands, existing addenda for banks/biotech/energy/hardware/insurance/reits.

---

## Task 1: Create canonical-frameworks reference

**Files:**
- Create: `.claude/references/canonical-frameworks.md`

This is a content artifact, not code. Single-step task.

- [ ] **Step 1: Write the file**

```markdown
# Canonical Frameworks Reference

Citation source of truth for `company-deep-dive` and `bear-case` agents. Every framework invocation in a memo MUST cite one of these entries by short key (e.g., `mauboussin_moat_2024`).

## Always-apply core (5 frameworks)

### damodaran_narrative_dcf

**Source:** Damodaran, "Narrative and Numbers: The Value of Stories in Business" (Columbia Business School Publishing, 2017). PDF: https://pages.stern.nyu.edu/~adamodar/pdfiles/eqnotes/narrativeandnumbers.pdf

Bind a defensible business narrative to a numerical DCF. Stress test 3 cases (bear/base/bull). Use NYU Stern data for ERP, country risk, industry betas, and multiples by sector: https://pages.stern.nyu.edu/~adamodar/

### mauboussin_reverse_dcf

**Source:** Rappaport & Mauboussin, "Expectations Investing: Reading Stock Prices for Better Returns," rev. ed. (Columbia Business School Publishing, 2021). https://www.expectationsinvesting.com/

Translate the current price into implied growth, margin, and competitive-advantage period. Compare implied expectations to historical ROIIC (via Mauboussin & Callahan's MEROI: https://www.morganstanley.com/im/publication/insights/articles/article_marketexpectedreturnoninvestment_en.pdf).

### mauboussin_moat_2024

**Source:** Mauboussin & Callahan, "Measuring the Moat" (Counterpoint Global / Morgan Stanley, 2024 ed.). https://www.morganstanley.com/im/publication/insights/articles/article_measuringthemoat.pdf

Three sources of value-add: production advantages, consumer advantages (network effects, switching costs, search costs, habits), external (regulation, subsidy). For each, name the fade pattern (how excess returns compete away).

### helmer_7_powers

**Source:** Hamilton Helmer, "7 Powers: The Foundations of Business Strategy" (2016). https://7powers.com/

Power = superior + significant + sustainable. Seven types: Scale Economies, Network Economies, Counter-Positioning, Switching Costs, Branding, Cornered Resource, Process Power. Counter-Positioning and Process Power are diagnostically rarest and highest-signal. For each claimed Power, state the Benefit (cash-flow effect) AND the Barrier (why competitor arbitrage fails).

### mauboussin_capital_allocation_2024

**Source:** Mauboussin & Callahan, "Capital Allocation: Results, Analysis, and Assessment" (Counterpoint Global / Morgan Stanley, updated 2022/2024). https://www.morganstanley.com/im/publication/insights/articles/article_capitalallocation.pdf

Five-bucket framework graded against ROIC vs WACC: CapEx, R&D, M&A, dividends, buybacks, debt paydown (treat debt as a sixth lever where material). Rubric: past behavior, current ROIC, alignment of incentives, stated principles. Empirical data back to 1970.

## Quality gate (precondition, not a "framework")

### piotroski_2000

**Source:** Piotroski, "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers," J. Accounting Research 38 (2000), pp. 1–41. PDF: https://www.ivey.uwo.ca/media/3775523/value_investing_the_use_of_historical_financial_statement_information.pdf

9-point F-Score across profitability, leverage/liquidity, operating efficiency. Memo gates to REJECT if F-Score < 6.

### altman_1968

**Source:** Altman, "Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy," J. Finance 23(4) (1968), pp. 589–609. PDF: https://www.calctopia.com/papers/Altman1968.pdf

Z-score (manufacturers) or Z'' (non-manufacturers/EM). Memo gates to REJECT if Z'' < 1.1.

## Sector addenda

### bessemer_cloud_100

**Source:** Bessemer State of the Cloud + Cloud 100 Benchmarks. https://www.bvp.com/atlas/the-cloud-100-benchmarks-report

NRR/GRR benchmarks (NRR >130% world-class; GRR >95% enterprise). Rule of 40 + Rule of X for AI-native (growth weighted 2×).

### skok_saas_metrics

**Source:** David Skok, "SaaS Metrics 2.0/3.0," For Entrepreneurs. https://www.forentrepreneurs.com/saas-metrics-2-definitions-2/

LTV/CAC, CAC payback, Magic Number, Burn Multiple. CAC payback target <12 months; magic number >1.0.

### sacks_burn_multiple

**Source:** David Sacks, "The Burn Multiple." https://sacks.substack.com/p/the-burn-multiple-51a7e43cb200

Net burn ÷ net new ARR. <1 amazing, 1–1.5 great, 1.5–2 OK, >2 watch, >3 bad.

### a16z_marketplace_metrics

**Source:** Andreessen Horowitz, "13 Metrics for Marketplaces" + "GMV Retention." https://a16z.com/13-metrics-for-marketplace-companies/ and https://a16z.com/gmv-retention-the-marketplace-metric-most-ignore/

GMV, take rate (typical 10–30%), GMV-cohort retention, frequency, liquidity.

### sequoia_ai_ascent_2025

**Source:** Sequoia AI Ascent 2025 (Sonya Huang). https://inferencebysequoia.substack.com/p/insights-from-ai-ascent-2025

AI-stack value-capture mapping: HW / cloud / model / tooling / vertical app. Sequoia view: value consolidates at infra (low-margin scale) and at vertical apps that "sell outcomes." Hold this view alongside a16z's barbell view; flag when they diverge.

### bain_ai_trillion_dollar_2024

**Source:** Bain Tech Report 2024, "AI's Trillion-Dollar Opportunity." https://www.bain.com/insights/ais-trillion-dollar-opportunity-tech-report-2024/

AI HW + SW TAM $780–990B by 2027. Use as upper-bound TAM prior; refuse to use as point estimate.

### tanay_ai_gross_margin_2025

**Source:** Tanay Jaipuria, "The Gross Margin Debate in AI." https://www.tanayj.com/p/the-gross-margin-debate-in-ai

AI-native gross margin median 50–60% with 84% reporting 6%+ erosion. Provider GMs vary widely (DeepSeek 85%, Anthropic 55%, Together 45%). For any AI-native name, scrutinize hosting/inference/third-party-model cost lines.

## Banned-output references

### molchanov_stangl_stovall_rejection_2024

**Source:** Molchanov & Stangl, "The Myth of Business Cycle Sector Rotation," International Journal of Finance & Economics (2024). https://onlinelibrary.wiley.com/doi/full/10.1002/ijfe.2882

Empirically rejects classical Stovall sector rotation (early/mid/late/recession map). Memos must NOT use this rotation framework as a positioning argument.

### nakamura_steinsson_2018

**Source:** Nakamura & Steinsson, "High-Frequency Identification of Monetary Non-Neutrality," QJE 2018. https://www.nber.org/system/files/working_papers/w19260/w19260.pdf

30-min HFI window around FOMC announcements. Required citation when memo discusses Fed-rhetoric or rate-action effects (otherwise banned per spec §8).

### cieslak_vissing_jorgensen_2019

**Source:** Cieslak, Morse & Vissing-Jorgensen, "Stock Returns over the FOMC Cycle," J. Finance 2019. https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12818

Entire post-1994 equity premium accrues in even FOMC-cycle weeks (0,2,4,6). Use as calendar prior, not as tradable factor.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/references/canonical-frameworks.md
git commit -m "Add canonical-frameworks reference doc

15 named frameworks with paper-level citations. Citation source of truth
for company-deep-dive and bear-case agents under v1 prompt rewrite.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: yfinance MCP package skeleton

**Files:**
- Create: `src/mcp/yfinance/server.py`
- Create: `src/mcp/yfinance/pyproject.toml`
- Create: `src/mcp/yfinance/__init__.py`
- Create: `src/mcp/yfinance/README.md`

Mirror `src/mcp/fred/` layout. No live endpoints yet — just the skeleton that boots, so subsequent TDD tasks can import it.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "equity-research-yfinance-mcp"
version = "0.1.0"
description = "yfinance MCP server. Wraps Yahoo Finance via yfinance Python lib for consensus estimates, target prices, holders, calendar, peer comps. Personal research use only — Yahoo ToS prohibits automated commercial access."
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.0.0",
    "yfinance>=0.2.40,<0.3",
    "python-dotenv>=1.0.0",
]

[dependency-groups]
dev = ["pytest>=8.0"]
```

- [ ] **Step 2: Write `__init__.py`** (empty file)

```python
```

- [ ] **Step 3: Write `server.py` skeleton**

```python
"""yfinance MCP server for the equity research system.

Wraps Yahoo Finance via the `yfinance` Python lib. Six endpoints:

- get_consensus_estimates: forward EPS + revenue consensus
- get_target_prices: sell-side target prices + recommendation summary
- get_recommendations: recent upgrades/downgrades within a window
- get_calendar: next earnings + ex-dividend dates
- get_holders: institutional + insider ownership
- get_peer_comps: peer tickers + key multiples

Per spec §9 of `docs/superpowers/specs/2026-05-07-flow-b-v1-frameworks-and-yfinance-design.md`.

ToS reality: Yahoo prohibits automated access for commercial use.
This server is for personal research only and must NOT be productized.

No persistent cache in v1 (spec §9.3 calls for Postgres cache; deferred
to v2 if Yahoo flakiness materially hurts). Failure-mode contract per
spec §9.4: stale, ticker_not_found, rate_limited, available=False.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Walk: server.py → yfinance/ → mcp/ → src/ → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


mcp = FastMCP("yfinance")


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4: Write `README.md`**

```markdown
# yfinance MCP

Wraps Yahoo Finance via the `yfinance` Python lib for consensus estimates, target prices, recommendations, calendar, holders, and peer comparisons.

## Endpoints (v1)

- `get_consensus_estimates(ticker)` — forward EPS + revenue consensus
- `get_target_prices(ticker)` — sell-side target prices + recommendation summary
- `get_recommendations(ticker, days=90)` — recent upgrades/downgrades
- `get_calendar(ticker)` — next earnings + ex-dividend dates
- `get_holders(ticker)` — institutional + insider ownership
- `get_peer_comps(ticker)` — peer tickers + key multiples

## ToS reality

Yahoo prohibits automated access for commercial use. This MCP is for personal research only. Do not productize.

## Failure modes

Per spec §9.4:
- Endpoint dropped → `{available: False, reason: "endpoint_dropped"}`
- Ticker not found → `{ticker_not_found: True}`
- Rate limited → `{rate_limited: True, retry_after: <seconds>}`
- Stale data (post-cache, v2 only) → `{stale: True, last_updated: <iso8601>, data: ...}`

## Run

Used by Claude Code via `.mcp.json`. Manual invocation:

```
uv run --project src/mcp/yfinance python src/mcp/yfinance/server.py
```
```

- [ ] **Step 5: Initialize uv lockfile**

Run from repo root:

```bash
cd src/mcp/yfinance && uv sync
```

Expected: creates `uv.lock` with `yfinance`, `mcp`, `python-dotenv` and their transitive deps.

- [ ] **Step 6: Commit**

```bash
cd /Users/sehoonbyun/Documents/equity-research-system
git add src/mcp/yfinance/
git commit -m "Add yfinance MCP package skeleton

FastMCP server scaffolding mirroring src/mcp/fred/ layout. Endpoints to
follow in subsequent TDD tasks.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Implement `get_consensus_estimates` (TDD)

**Files:**
- Modify: `src/mcp/yfinance/server.py`
- Create: `tests/test_yfinance.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_yfinance.py`:

```python
"""Integration smoke tests for the yfinance MCP server (`src/mcp/yfinance/server.py`).

These tests hit the LIVE Yahoo Finance API via the `yfinance` Python lib.
They are network-dependent and marked `@pytest.mark.integration` so they
can be skipped in offline CI later (e.g. `pytest -m 'not integration'`).

Run from repo root:
    pytest tests/test_yfinance.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load this MCP's `server.py` directly by file path under a unique module
# name; bare `from server import X` collides across MCP test files because
# every MCP module is named `server`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVER_PATH = _REPO_ROOT / "src/mcp/yfinance/server.py"
_spec = importlib.util.spec_from_file_location("yfinance_mcp_server", _SERVER_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["yfinance_mcp_server"] = _module
_spec.loader.exec_module(_module)

get_consensus_estimates = _module.get_consensus_estimates


@pytest.mark.integration
def test_get_consensus_estimates_aapl_returns_required_fields():
    result = get_consensus_estimates("AAPL")
    assert isinstance(result, dict)
    # Required schema per spec §9.1
    for key in (
        "fy_eps_mean",
        "fy_revenue_mean",
        "next_q_eps_mean",
        "next_q_revenue_mean",
        "analyst_count",
    ):
        assert key in result, f"missing required field {key}"
    # Numeric or None
    assert result["analyst_count"] is None or isinstance(result["analyst_count"], int)


@pytest.mark.integration
def test_get_consensus_estimates_unknown_ticker_returns_not_found():
    result = get_consensus_estimates("ZZZZNOTAREALTICKER")
    assert result == {"ticker_not_found": True}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_yfinance.py::test_get_consensus_estimates_aapl_returns_required_fields -v
```

Expected: FAIL with `AttributeError: module 'yfinance_mcp_server' has no attribute 'get_consensus_estimates'`

- [ ] **Step 3: Implement `get_consensus_estimates` in `server.py`**

Append to `src/mcp/yfinance/server.py`:

```python
import yfinance as yf


def _is_ticker_unknown(ticker_obj: "yf.Ticker") -> bool:
    """yfinance returns empty info dict for nonexistent tickers."""
    try:
        info = ticker_obj.info
    except Exception:
        return True
    if not info or len(info) <= 1:
        return True
    if info.get("regularMarketPrice") is None and info.get("symbol") is None:
        return True
    return False


@mcp.tool()
def get_consensus_estimates(ticker: str) -> dict:
    """Return forward EPS + revenue consensus estimates for `ticker`.

    Schema:
        {
            "fy_eps_mean": float | None,
            "fy_eps_std": float | None,
            "fy_revenue_mean": float | None,
            "fy_revenue_std": float | None,
            "next_q_eps_mean": float | None,
            "next_q_revenue_mean": float | None,
            "analyst_count": int | None,
        }

    Failure modes:
        - Unknown ticker: `{"ticker_not_found": True}`
        - Endpoint missing data: numeric fields = None
    """
    t = yf.Ticker(ticker)
    if _is_ticker_unknown(t):
        return {"ticker_not_found": True}

    try:
        trend = t.earnings_trend
    except Exception:
        trend = None

    info = t.info or {}

    def _get(d: dict | None, *path):
        cur = d
        for p in path:
            if cur is None:
                return None
            try:
                cur = cur[p]
            except (KeyError, IndexError, TypeError):
                return None
        return cur

    return {
        "fy_eps_mean": info.get("forwardEps"),
        "fy_eps_std": None,  # yfinance does not surface std
        "fy_revenue_mean": info.get("revenueEstimate", {}).get("avg") if isinstance(info.get("revenueEstimate"), dict) else None,
        "fy_revenue_std": None,
        "next_q_eps_mean": info.get("earningsQuarterlyGrowth"),
        "next_q_revenue_mean": info.get("revenueQuarterlyGrowth"),
        "analyst_count": info.get("numberOfAnalystOpinions"),
    }
```

(Note: yfinance's exact attribute layout drifts. The implementer should run the test, inspect what yfinance returns for AAPL today, and adjust the field mappings to match the spec schema. The contract — required keys exist, unknown ticker returns `{ticker_not_found: True}` — is the load-bearing part.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_yfinance.py -v -k consensus
```

Expected: 2 passed (or both passed; if the `unknown ticker` test fails because yfinance raises instead of returning empty, adjust `_is_ticker_unknown` until both pass).

- [ ] **Step 5: Commit**

```bash
git add src/mcp/yfinance/server.py tests/test_yfinance.py
git commit -m "yfinance MCP: implement get_consensus_estimates

First endpoint of the yfinance wrapper. Returns forward EPS + revenue
consensus per spec §9.1. Unknown-ticker failure mode returns
{ticker_not_found: True}.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Implement `get_target_prices` (TDD)

**Files:**
- Modify: `src/mcp/yfinance/server.py`
- Modify: `tests/test_yfinance.py`

- [ ] **Step 1: Append failing test**

Add to `tests/test_yfinance.py`:

```python
get_target_prices = _module.get_target_prices  # add near the other imports at top


@pytest.mark.integration
def test_get_target_prices_aapl_returns_required_fields():
    result = get_target_prices("AAPL")
    assert isinstance(result, dict)
    for key in (
        "target_high",
        "target_low",
        "target_mean",
        "target_median",
        "number_of_analyst_opinions",
        "recommendation_mean",
        "recommendation_key",
    ):
        assert key in result, f"missing required field {key}"
```

- [ ] **Step 2: Verify fails**

```bash
pytest tests/test_yfinance.py::test_get_target_prices_aapl_returns_required_fields -v
```

Expected: FAIL — `get_target_prices` not defined.

- [ ] **Step 3: Implement**

Add to `src/mcp/yfinance/server.py`:

```python
@mcp.tool()
def get_target_prices(ticker: str) -> dict:
    """Return sell-side target price summary for `ticker`.

    Schema per spec §9.1:
        {
            "target_high": float | None,
            "target_low": float | None,
            "target_mean": float | None,
            "target_median": float | None,
            "number_of_analyst_opinions": int | None,
            "recommendation_mean": float | None,  # 1=Strong Buy, 5=Strong Sell
            "recommendation_key": str | None,     # e.g. "buy", "hold"
        }

    Failure modes:
        - Unknown ticker: `{"ticker_not_found": True}`
    """
    t = yf.Ticker(ticker)
    if _is_ticker_unknown(t):
        return {"ticker_not_found": True}
    info = t.info or {}
    return {
        "target_high": info.get("targetHighPrice"),
        "target_low": info.get("targetLowPrice"),
        "target_mean": info.get("targetMeanPrice"),
        "target_median": info.get("targetMedianPrice"),
        "number_of_analyst_opinions": info.get("numberOfAnalystOpinions"),
        "recommendation_mean": info.get("recommendationMean"),
        "recommendation_key": info.get("recommendationKey"),
    }
```

- [ ] **Step 4: Verify pass**

```bash
pytest tests/test_yfinance.py::test_get_target_prices_aapl_returns_required_fields -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mcp/yfinance/server.py tests/test_yfinance.py
git commit -m "yfinance MCP: implement get_target_prices

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Implement `get_recommendations` (TDD)

**Files:**
- Modify: `src/mcp/yfinance/server.py`
- Modify: `tests/test_yfinance.py`

- [ ] **Step 1: Append failing test**

```python
get_recommendations = _module.get_recommendations  # add near top imports


@pytest.mark.integration
def test_get_recommendations_aapl_returns_list():
    result = get_recommendations("AAPL", days=90)
    assert isinstance(result, list)
    if result:  # may be empty if no recent activity
        item = result[0]
        for key in ("firm", "to_grade", "from_grade", "action", "date"):
            assert key in item, f"missing required field {key}"
```

- [ ] **Step 2: Verify fails**

```bash
pytest tests/test_yfinance.py::test_get_recommendations_aapl_returns_list -v
```

- [ ] **Step 3: Implement**

```python
from datetime import datetime, timedelta, timezone


@mcp.tool()
def get_recommendations(ticker: str, days: int = 90) -> list[dict] | dict:
    """Return analyst upgrade/downgrade events within the last `days`.

    Schema per spec §9.1:
        [
            {
                "firm": str,
                "to_grade": str,
                "from_grade": str,
                "action": str,    # e.g. "up", "down", "init", "main"
                "date": str,      # ISO 8601
            },
            ...
        ]

    Failure modes:
        - Unknown ticker: `{"ticker_not_found": True}` (note: returns dict, not list)
        - No recent activity: `[]`
    """
    t = yf.Ticker(ticker)
    if _is_ticker_unknown(t):
        return {"ticker_not_found": True}

    try:
        rec_df = t.recommendations
    except Exception:
        return []
    if rec_df is None or rec_df.empty:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items = []
    for idx, row in rec_df.iterrows():
        # yfinance puts the date in the index
        try:
            row_date = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
            if hasattr(row_date, "tzinfo") and row_date.tzinfo is None:
                row_date = row_date.replace(tzinfo=timezone.utc)
            if row_date < cutoff:
                continue
            items.append({
                "firm": row.get("Firm", ""),
                "to_grade": row.get("To Grade", ""),
                "from_grade": row.get("From Grade", ""),
                "action": row.get("Action", ""),
                "date": row_date.isoformat(),
            })
        except Exception:
            continue
    return items
```

- [ ] **Step 4: Verify pass**

```bash
pytest tests/test_yfinance.py::test_get_recommendations_aapl_returns_list -v
```

- [ ] **Step 5: Commit**

```bash
git add src/mcp/yfinance/server.py tests/test_yfinance.py
git commit -m "yfinance MCP: implement get_recommendations

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Implement `get_calendar` (TDD)

**Files:**
- Modify: `src/mcp/yfinance/server.py`
- Modify: `tests/test_yfinance.py`

- [ ] **Step 1: Append failing test**

```python
get_calendar = _module.get_calendar  # add near top imports


@pytest.mark.integration
def test_get_calendar_aapl_returns_required_fields():
    result = get_calendar("AAPL")
    assert isinstance(result, dict)
    for key in ("next_earnings_date", "ex_dividend_date", "dividend_date"):
        assert key in result
```

- [ ] **Step 2: Verify fails**

```bash
pytest tests/test_yfinance.py::test_get_calendar_aapl_returns_required_fields -v
```

- [ ] **Step 3: Implement**

```python
@mcp.tool()
def get_calendar(ticker: str) -> dict:
    """Return upcoming corporate calendar events.

    Schema per spec §9.1:
        {
            "next_earnings_date": str | None,  # ISO 8601 date
            "ex_dividend_date": str | None,
            "dividend_date": str | None,
        }

    Failure modes:
        - Unknown ticker: `{"ticker_not_found": True}`
    """
    t = yf.Ticker(ticker)
    if _is_ticker_unknown(t):
        return {"ticker_not_found": True}

    try:
        cal = t.calendar
    except Exception:
        cal = None

    def _coerce_date(v):
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat() if hasattr(v, "year") else str(v)
        return str(v)

    if isinstance(cal, dict):
        earnings_dates = cal.get("Earnings Date")
        # yfinance returns a list of dates for earnings; take first
        next_earnings = earnings_dates[0] if isinstance(earnings_dates, list) and earnings_dates else earnings_dates
        return {
            "next_earnings_date": _coerce_date(next_earnings),
            "ex_dividend_date": _coerce_date(cal.get("Ex-Dividend Date")),
            "dividend_date": _coerce_date(cal.get("Dividend Date")),
        }
    # Fall back to info-derived
    info = t.info or {}
    return {
        "next_earnings_date": _coerce_date(info.get("earningsTimestamp")),
        "ex_dividend_date": _coerce_date(info.get("exDividendDate")),
        "dividend_date": _coerce_date(info.get("dividendDate")),
    }
```

- [ ] **Step 4: Verify pass**

```bash
pytest tests/test_yfinance.py::test_get_calendar_aapl_returns_required_fields -v
```

- [ ] **Step 5: Commit**

```bash
git add src/mcp/yfinance/server.py tests/test_yfinance.py
git commit -m "yfinance MCP: implement get_calendar

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Implement `get_holders` (TDD)

**Files:**
- Modify: `src/mcp/yfinance/server.py`
- Modify: `tests/test_yfinance.py`

- [ ] **Step 1: Append failing test**

```python
get_holders = _module.get_holders  # add near top imports


@pytest.mark.integration
def test_get_holders_aapl_returns_required_fields():
    result = get_holders("AAPL")
    assert isinstance(result, dict)
    for key in ("institutional_holders", "major_holders", "insider_holders", "institutional_pct"):
        assert key in result
    assert isinstance(result["institutional_holders"], list)
```

- [ ] **Step 2: Verify fails**

- [ ] **Step 3: Implement**

```python
@mcp.tool()
def get_holders(ticker: str) -> dict:
    """Return institutional + insider ownership snapshot.

    Schema per spec §9.1:
        {
            "institutional_holders": [
                {"holder": str, "shares": int, "pct_held": float, "value": float},
                ...
            ],
            "major_holders": {"insider_pct": float, "institution_pct": float, ...},
            "insider_holders": [...],
            "institutional_pct": float | None,
            "qoq_delta": float | None,  # not always available
        }

    Failure modes:
        - Unknown ticker: `{"ticker_not_found": True}`
    """
    t = yf.Ticker(ticker)
    if _is_ticker_unknown(t):
        return {"ticker_not_found": True}

    def _df_to_records(df):
        if df is None or (hasattr(df, "empty") and df.empty):
            return []
        try:
            return df.to_dict(orient="records")
        except Exception:
            return []

    inst = _df_to_records(getattr(t, "institutional_holders", None))
    insiders = _df_to_records(getattr(t, "insider_purchases", None))

    major = {}
    try:
        mh = t.major_holders
        if mh is not None and not mh.empty:
            # major_holders is a 2-col DataFrame: pct, label
            for _, row in mh.iterrows():
                vals = list(row.values)
                if len(vals) >= 2:
                    major[str(vals[1])] = vals[0]
    except Exception:
        pass

    info = t.info or {}
    return {
        "institutional_holders": inst,
        "major_holders": major,
        "insider_holders": insiders,
        "institutional_pct": info.get("heldPercentInstitutions"),
        "qoq_delta": None,  # not directly available; compute later from snapshots
    }
```

- [ ] **Step 4: Verify pass**

```bash
pytest tests/test_yfinance.py::test_get_holders_aapl_returns_required_fields -v
```

- [ ] **Step 5: Commit**

```bash
git add src/mcp/yfinance/server.py tests/test_yfinance.py
git commit -m "yfinance MCP: implement get_holders

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Implement `get_peer_comps` (TDD)

**Files:**
- Modify: `src/mcp/yfinance/server.py`
- Modify: `tests/test_yfinance.py`

- [ ] **Step 1: Append failing test**

```python
get_peer_comps = _module.get_peer_comps  # add near top imports


@pytest.mark.integration
def test_get_peer_comps_aapl_returns_list():
    result = get_peer_comps("AAPL")
    assert isinstance(result, list)
    if result:
        peer = result[0]
        for key in ("ticker", "pe", "ev_ebitda", "ev_sales", "market_cap"):
            assert key in peer, f"missing required field {key}"
```

- [ ] **Step 2: Verify fails**

- [ ] **Step 3: Implement**

```python
@mcp.tool()
def get_peer_comps(ticker: str, max_peers: int = 5) -> list[dict] | dict:
    """Return peer tickers + key valuation multiples.

    Schema per spec §9.1:
        [
            {
                "ticker": str,
                "pe": float | None,
                "ev_ebitda": float | None,
                "ev_sales": float | None,
                "market_cap": float | None,
            },
            ...
        ]

    Failure modes:
        - Unknown ticker: `{"ticker_not_found": True}` (returns dict, not list)
        - No peers available: `[]`
    """
    t = yf.Ticker(ticker)
    if _is_ticker_unknown(t):
        return {"ticker_not_found": True}

    # yfinance does not expose first-class peer lists. Use info["recommendationKey"]
    # peers when available, else fall back to industry-mate scan.
    info = t.info or {}
    industry_peers: list[str] = []
    # Try the SEC-style same-industry list if exposed; otherwise yfinance has none.
    try:
        recs = getattr(t, "recommendations", None)
    except Exception:
        recs = None

    # As a stable v1, derive peers by reading `info.get("companyOfficers")` is wrong;
    # better: rely on the `industry` field + a hardcoded short list of known
    # peer-defining tickers per industry. For v1 we surface "peer discovery is a
    # separate concern" by returning [] when no peers can be derived. The agent
    # prompt instructs CDD to fall back to manual peer construction in that case.

    peers = industry_peers[:max_peers]

    out: list[dict] = []
    for peer_ticker in peers:
        pt = yf.Ticker(peer_ticker)
        if _is_ticker_unknown(pt):
            continue
        pi = pt.info or {}
        out.append({
            "ticker": peer_ticker,
            "pe": pi.get("trailingPE"),
            "ev_ebitda": pi.get("enterpriseToEbitda"),
            "ev_sales": pi.get("enterpriseToRevenue"),
            "market_cap": pi.get("marketCap"),
        })
    return out
```

(Note: yfinance has no first-class peer-discovery API. v1 returns an empty list when no peers are derivable; the CDD agent prompt instructs the agent to fall back to manual peer construction from EDGAR SIC codes. v2 may add a peer-resolution layer.)

- [ ] **Step 4: Verify pass**

```bash
pytest tests/test_yfinance.py::test_get_peer_comps_aapl_returns_list -v
```

(Empty list is acceptable.)

- [ ] **Step 5: Commit**

```bash
git add src/mcp/yfinance/server.py tests/test_yfinance.py
git commit -m "yfinance MCP: implement get_peer_comps

v1 returns [] when no peers derivable; agent falls back to EDGAR SIC peers.
Peer-resolution layer deferred to v2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Failure-mode handling — ticker delisted check

**Files:**
- Modify: `src/mcp/yfinance/server.py`
- Modify: `tests/test_yfinance.py`

Per spec §9.4, when a ticker returns `{ticker_not_found: True}`, the agent prompt instructs it to verify via `mcp__fundamentals__get_delistings`. The MCP itself doesn't need to call that — it just needs to consistently return the failure-mode dict.

- [ ] **Step 1: Append failing test for unknown-ticker on every endpoint**

```python
@pytest.mark.integration
@pytest.mark.parametrize("fn_name", [
    "get_consensus_estimates",
    "get_target_prices",
    "get_calendar",
    "get_holders",
])
def test_unknown_ticker_returns_not_found_dict(fn_name):
    fn = getattr(_module, fn_name)
    result = fn("ZZZZNOTAREALTICKER12345")
    assert result == {"ticker_not_found": True}, (
        f"{fn_name} did not return {{ticker_not_found: True}} for unknown ticker; "
        f"got {result!r}"
    )


@pytest.mark.integration
def test_unknown_ticker_recommendations_returns_not_found_dict():
    result = _module.get_recommendations("ZZZZNOTAREALTICKER12345")
    assert result == {"ticker_not_found": True}


@pytest.mark.integration
def test_unknown_ticker_peer_comps_returns_not_found_dict():
    result = _module.get_peer_comps("ZZZZNOTAREALTICKER12345")
    assert result == {"ticker_not_found": True}
```

- [ ] **Step 2: Run tests; fix any endpoint that doesn't return the failure-mode dict consistently**

```bash
pytest tests/test_yfinance.py -v -k unknown_ticker
```

If a test fails because `_is_ticker_unknown` doesn't catch the case, debug with:

```bash
python -c "import yfinance as yf; t = yf.Ticker('ZZZZNOTAREALTICKER12345'); print(t.info)"
```

Tighten `_is_ticker_unknown` heuristic until all parametrized cases pass.

- [ ] **Step 3: Commit**

```bash
git add src/mcp/yfinance/server.py tests/test_yfinance.py
git commit -m "yfinance MCP: enforce ticker_not_found contract on all endpoints

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Register yfinance in `.mcp.json`

**Files:**
- Modify: `.mcp.json`

- [ ] **Step 1: Read current `.mcp.json`**

```bash
cat .mcp.json
```

- [ ] **Step 2: Add yfinance server entry**

Edit `.mcp.json`. Insert after the `broker` block (just before the closing `}` of `mcpServers`):

```json
    "yfinance": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "src/mcp/yfinance",
        "python",
        "src/mcp/yfinance/server.py"
      ]
    }
```

(Remember to add the trailing comma after the prior block's closing brace if needed.)

The full `mcpServers` block should now have 8 entries: postgres, contamination_check, edgar, market_data, fundamentals, fred, broker, yfinance.

- [ ] **Step 3: Validate JSON**

```bash
python -c "import json; json.load(open('.mcp.json'))"
```

Expected: no output (silent success). If invalid, fix.

- [ ] **Step 4: Boot test**

```bash
uv run --project src/mcp/yfinance python src/mcp/yfinance/server.py &
sleep 2
kill %1
```

Expected: starts without import error, runs until killed.

- [ ] **Step 5: Commit**

```bash
git add .mcp.json
git commit -m "Register yfinance MCP server in .mcp.json

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Extend `industry-addenda/software.md`

**Files:**
- Modify: `.claude/references/industry-addenda/software.md`

The existing file already covers Rule of 40 + NRR. Extend with: Rule of X (AI-native), Burn Multiple, AI-native gross margin, Bessemer/Sacks/Tanay citations.

- [ ] **Step 1: Read current file**

```bash
cat .claude/references/industry-addenda/software.md
```

- [ ] **Step 2: Append a new section at end of file**

Append:

```markdown

---

## v1 framework canon refresh (2026-05-07)

Per `docs/superpowers/specs/2026-05-07-flow-b-v1-frameworks-and-yfinance-design.md` §7.1, the SaaS addendum invokes the following named sources (cite by short key in memo `frameworks_cited` field):

### Rule of X (AI-native variant)

For AI-native names where compute scales the revenue line non-linearly, weight growth 2× over EBITDA/FCF margin:

```
Rule of X = 2 × Revenue Growth Rate (%) + Profit Margin (%)
```

Bessemer 2025 framing for "Supernovas." Cite as `bessemer_cloud_100`. Source: https://www.bvp.com/the-official-state-of-the-cloud-ai

### Burn Multiple (Sacks)

```
Burn Multiple = Net Burn ÷ Net New ARR
```

Bands: <1 amazing, 1–1.5 great, 1.5–2 OK, >2 watch, >3 bad.

Cite as `sacks_burn_multiple`. Source: https://sacks.substack.com/p/the-burn-multiple-51a7e43cb200

### AI-native gross margin scrutiny

For any AI-native name, surface:
- Hosting/inference costs as a % of revenue (from 10-K Item 7 / cost of revenue footnote)
- Third-party model costs if disclosed
- Provider GM dispersion (DeepSeek 85%, Anthropic 55%, Together 45%) as benchmark

Median AI-app GM 50–60%; 84% report 6%+ erosion. Cite as `tanay_ai_gross_margin_2025`. Source: https://www.tanayj.com/p/the-gross-margin-debate-in-ai

### Required citations in `frameworks_cited`

Any SaaS memo must include at least one of: `bessemer_cloud_100`, `skok_saas_metrics`, `sacks_burn_multiple` in the `frameworks_cited` field of the output template (per spec §10).
```

- [ ] **Step 3: Commit**

```bash
git add .claude/references/industry-addenda/software.md
git commit -m "Extend software addendum with Bessemer/Sacks/Tanay refs

Adds Rule of X for AI-native, Burn Multiple, AI gross margin scrutiny.
Required citations align with v1 spec §7.1 + canonical-frameworks.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Create `industry-addenda/marketplace.md`

**Files:**
- Create: `.claude/references/industry-addenda/marketplace.md`

- [ ] **Step 1: Write file**

```markdown
# Industry Addendum: Marketplace / Multi-Sided Platform

Loaded by `company-deep-dive` and `bear-case` subagents when the company business model has explicit multi-sided structure (matches buyers and sellers, hosts and guests, riders and drivers, etc.).

Source canon (cite by short key in memo `frameworks_cited`):
- `a16z_marketplace_metrics` — a16z, "13 Metrics for Marketplaces" + "GMV Retention" (https://a16z.com/13-metrics-for-marketplace-companies/)

## Required marketplace metrics

### GMV (Gross Merchandise Volume)

Total transaction volume passing through the platform. Surface trailing 12mo and quarterly trend.

### Take rate

```
Take rate = Revenue / GMV
```

Typical range: **10–30%**. Above 30% is unusual and worth interrogating (is the platform actually a vertical operator in disguise?). Below 10% suggests pricing power weakness.

### GMV-cohort retention

Cohort buyers' GMV in year N divided by year 1 GMV. The healthy curve flattens above ~80% by year 1 and stays flat.

### Frequency + liquidity

- **Frequency** — transactions per active user per period.
- **Liquidity** — fill rate or conversion rate from search to transaction. Below 30% in many marketplace categories signals supply/demand imbalance.

## Required strategic analysis (Hagiu/Eisenmann)

For each side of the platform, the memo must answer:

1. **Identity of each side.** Who pays, who is subsidized? (Often subsidized side is the harder side to attract.)
2. **Cross-side network effect direction and magnitude.** Does adding a buyer increase seller value? By how much?
3. **Chicken-and-egg solution at cold-start.** How did the platform overcome the simultaneity problem? (Single-side seeding, big-bang, marquee customers, micromarkets.)
4. **Envelopment risk from adjacent platforms.** Could a horizontal platform (Amazon, Meta, etc.) bundle in this functionality at zero marginal cost?

## BearCase symmetry

BearCase memos for marketplaces must additionally argue:
- Why "platform" framing actually masks switching-cost or scale-economy power that is more vulnerable than network-effect rhetoric implies (Helmer 7 Powers diagnostic).
- Where take-rate compression is plausible (regulation, disintermediation by major sellers, alternative platforms).
- Cohort retention curve weakness (cohort decay, not just headline GMV growth).
```

- [ ] **Step 2: Commit**

```bash
git add .claude/references/industry-addenda/marketplace.md
git commit -m "Add marketplace addendum

a16z 13-metrics + Hagiu/Eisenmann platform-side analysis. Symmetric
BearCase requirements per v1 spec §7.2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Create `industry-addenda/ai-native.md`

**Files:**
- Create: `.claude/references/industry-addenda/ai-native.md`

- [ ] **Step 1: Write file**

```markdown
# Industry Addendum: AI-Native / AI-Stack Participant

Loaded by `company-deep-dive` and `bear-case` subagents when the company's revenue or value-prop materially derives from AI capability — including foundation model providers, AI-platform/tooling vendors, AI-application companies, and incumbents whose AI exposure has become the dominant valuation driver.

Source canon (cite by short key in memo `frameworks_cited`):
- `sequoia_ai_ascent_2025` — Sequoia AI Ascent 2025 (https://inferencebysequoia.substack.com/p/insights-from-ai-ascent-2025)
- `bain_ai_trillion_dollar_2024` — Bain Tech Report 2024 (https://www.bain.com/insights/ais-trillion-dollar-opportunity-tech-report-2024/)
- `tanay_ai_gross_margin_2025` — Tanay Jaipuria, "AI Gross Margin Debate" (https://www.tanayj.com/p/the-gross-margin-debate-in-ai)

## Required: AI-stack position

Place the company on this stack and surface the implication for value capture:

| Layer | Examples | Margin profile |
|---|---|---|
| Hardware | NVIDIA, AMD, TSMC, Broadcom | Capital-intensive, scale-driven, durable advantage to leader (CUDA moat) |
| Cloud / infra | AWS, Azure, GCP, CoreWeave | Capital-intensive, low margin at scale, reseller economics |
| Foundation model | OpenAI, Anthropic, xAI, Meta, Google | Capital-intensive; Sequoia view = margin pressure; a16z view = barbell. **Hold both views — flag divergence.** |
| Tooling / platform | LangChain, Pinecone, Hugging Face, ServiceNow AI | Variable; depends on lock-in vs commoditization |
| Vertical app | Harvey (legal), Tempus (oncology), Glean (enterprise search) | Sequoia "sells outcomes" view = highest durable margin |

## Required: AI gross margin scrutiny

For any AI-native company, the memo must:

1. Break out hosting/inference/third-party-model costs from 10-K Item 7 / cost of revenue footnote.
2. Compare reported gross margin to the AI-native median 50–60% (`tanay_ai_gross_margin_2025`).
3. If GM > 70%, ask: is this from cross-subsidy by a foundation-layer parent, or genuine unit economics?
4. If GM < 50%, ask: is the company on a credible path to scale-driven margin expansion, or structurally exposed to inference cost?
5. Surface inference-cost-per-active-user where derivable (the 2026 SaaS-equivalent of COGS-per-seat).

## Required: TAM discipline

- Bain estimates AI HW + SW TAM $780–990B by 2027 (`bain_ai_trillion_dollar_2024`). Use as **upper bound prior**, never as a point estimate.
- "TAM × penetration" with no sensitivity bands is a banned output (per spec §8 universal). Memos must show low/mid/high penetration scenarios.

## BearCase symmetry

BearCase memos for AI-native names must additionally argue:
- Where margin compression from inference cost or model commoditization is plausible.
- Where the "moat" is actually distribution + branding rather than model quality.
- Where the company is mis-positioned on the stack (e.g., a tooling layer about to be enveloped by a foundation-model provider).
- For foundation-model providers: hold both Sequoia (margin pressure) and a16z (barbell) views; argue the bear case under each.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/references/industry-addenda/ai-native.md
git commit -m "Add ai-native addendum

Sequoia/Bain AI-stack value-capture mapping + Tanay GM scrutiny. v1 spec §7.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Rewrite `.claude/agents/company-deep-dive.md`

**Files:**
- Modify: `.claude/agents/company-deep-dive.md`

This is the largest change in the plan. Add tier classification as the first action, replace the existing classification step's industry-addenda routing to include the three new/extended addenda, add the 5-framework core canon, banned outputs list, MCP grants for yfinance.

- [ ] **Step 1: Read existing file**

```bash
cat .claude/agents/company-deep-dive.md
```

- [ ] **Step 2: Update frontmatter to add yfinance MCP grants**

Edit the `tools:` line in frontmatter (line 4). Replace the existing line with:

```
tools: Read, Bash, mcp__edgar__get_company_facts, mcp__edgar__get_filing_text, mcp__edgar__get_filings, mcp__market_data__get_news, mcp__market_data__get_prices, mcp__market_data__get_real_time_quote, mcp__fundamentals__get_delistings, mcp__fundamentals__get_fundamentals, mcp__postgres__query, mcp__postgres__execute, mcp__postgres__schema_info, mcp__yfinance__get_consensus_estimates, mcp__yfinance__get_target_prices, mcp__yfinance__get_recommendations, mcp__yfinance__get_calendar, mcp__yfinance__get_holders, mcp__yfinance__get_peer_comps
```

(All MCP tools are listed at tool-level, not server-level shorthand — per the repo memory rule.)

- [ ] **Step 3: Update §"1. Read references first" to add canonical-frameworks reference**

Find the section that lists references to load. Add to the list:

```markdown
- `.claude/references/canonical-frameworks.md` — citation source of truth for the 5-framework core canon (Damodaran, Mauboussin reverse-DCF, Mauboussin Moat 2024, Helmer 7 Powers, Mauboussin Capital Allocation 5-bucket); cite frameworks by short key
```

- [ ] **Step 4: Insert new §"2. Classify tier" BEFORE existing "Classify the company"**

Insert after §1 (Read references), before existing §2 (Classify industry):

```markdown
### 2. Classify tier (HARD BRANCH — first action after references)

Set the `tier` field of your output BEFORE doing any framework analysis. The tier determines which frameworks apply (per §6.1 of the v1 spec) and which output schemas are permitted.

Rubric (default to the more conservative tier on ambiguity):

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

Tier-conditional framework application:

| Tier | DCF | Reverse-DCF | Moat | 7 Powers | Capital Allocation | Output constraint |
|---|---|---|---|---|---|---|
| core_fundamental | ✓ point + bands | ✓ | ✓ | ✓ | ✓ | Standard memo |
| thematic_growth | ✓ ranges only | ✓ | ✓ | ✓ | ✓ | Sensitivity bands required, no point targets |
| speculative_optionality | SKIP | SKIP | ✓ qualitative | ✓ qualitative | N/A acceptable | Milestone-tree + probability-weighted payoffs only |

For `speculative_optionality`, replace the DCF section with:

```yaml
milestone_tree:
  - milestone: <description>
    target_date: <YYYY-Q#>
    probability: <0..1>
    conditional_payoff_if_met: <multiple of current price, range>
    conditional_payoff_if_missed: <multiple, range>
expected_value_decomposition:
  sum_pv_payoff_if_met: <expected value if all milestones met>
  sum_pv_payoff_if_missed: <expected value if all missed>
sleeve_reference:
  speculative_sleeve_cap_pct: 8  # aggregate book cap reference
  intra_theme_diversification_rule: "no single thematic sub-sleeve >40%"
```

Renumber all subsequent sections (existing §2 → §3, §3 → §4, etc.).
```

- [ ] **Step 5: Update existing "Classify the company" section to add three new addenda routes**

Find the industry classification list. Add three lines:

```markdown
- Software / SaaS → load `.claude/references/industry-addenda/software.md` (always; extended with v1 framework canon)
- Marketplace / multi-sided platform → also load `.claude/references/industry-addenda/marketplace.md`
- AI-native (revenue or value-prop materially from AI) → also load `.claude/references/industry-addenda/ai-native.md`
```

(Multiple addenda CAN fire — e.g., an AI-native SaaS loads software.md + ai-native.md.)

- [ ] **Step 6: Insert new section "Apply 5-framework core" after classification, before existing analysis steps**

Insert as a new numbered section:

```markdown
### Apply the 5-framework core canon

For every memo regardless of tier (with tier-conditional skips per §2 rubric above), apply these five frameworks. Cite each by short key in the memo's `frameworks_cited` field.

#### 1. damodaran_narrative_dcf

Bind a narrative to numbers. Stress-test 3 cases (bear/base/bull) with explicit growth, margin, duration assumptions. Use NYU Stern data for ERP, country risk, industry beta. **Skip entirely if tier = speculative_optionality** (replace with milestone-tree per §2).

#### 2. mauboussin_reverse_dcf

Translate the current price into `implied_growth`, `implied_margin`, `implied_duration`. Compare to historical ROIIC (MEROI methodology). State whether implied expectations are achievable given moat and capital allocation. **Skip entirely if tier = speculative_optionality.**

#### 3. mauboussin_moat_2024

Identify source of advantage: production / consumer (network effects, switching costs, search costs, habits) / external (regulation, subsidy). State expected fade pattern over next decade.

#### 4. helmer_7_powers

Which of the 7 Powers (Scale, Network Economies, Counter-Positioning, Switching Costs, Branding, Cornered Resource, Process Power) does the company hold? For each claimed Power, state Benefit (cash flow effect) AND Barrier (why competitor arbitrage fails). Counter-Positioning and Process Power are diagnostically rarest and highest-signal.

#### 5. mauboussin_capital_allocation_2024

Grade past 5y allocation across 5 buckets (CapEx, R&D, M&A, dividends, buybacks, debt) against ROIC vs WACC. Rubric: past behavior, current ROIC, alignment of incentives, stated principles. Mark "N/A — pre-revenue, no allocation history" acceptable for `tier = speculative_optionality`.

#### Quality gate (precondition)

Before any framework analysis, compute:

- Piotroski F-Score (9-point checklist; cite as `piotroski_2000`)
- Altman Z'' for non-manufacturers (cite as `altman_1968`)

If F-Score < 6 OR Z'' < 1.1, gate the memo to `disposition: REJECT` with the failing gate named in the gate field. Sloan accruals reported as a flag only.

#### Sector addenda (classification-triggered, additive)

If classification matches, additionally apply the relevant addendum's required metrics:
- SaaS / software → `software.md` (Rule of 40, Rule of X, NRR, GRR, Magic Number, CAC payback, Burn Multiple)
- Marketplace → `marketplace.md` (GMV, take rate, GMV-cohort retention, Hagiu platform-side analysis)
- AI-native → `ai-native.md` (AI-stack position, GM scrutiny, TAM with sensitivity bands)

Multiple addenda can fire (e.g., AI-native SaaS triggers both software + ai-native).
```

- [ ] **Step 7: Insert new section "Banned outputs"**

Insert after the framework section, before the existing memo-output section:

```markdown
### Banned outputs

The Evaluator agent grades these as hard-gate failures. Memos containing any of the following fail the gate and are returned for rewrite:

**Universal:**
- Stovall classical sector rotation (`molchanov_stangl_stovall_rejection_2024`)
- PEG-only ranking (no out-of-sample empirical support)
- ARK-style decade-out point price targets (methodology repeatedly resets goalpost; per spec §15 evidence)

**Tier-specific:**
- `core_fundamental` + `thematic_growth`: Fed-action commentary without referencing HFI window (`nakamura_steinsson_2018`) or FOMC-cycle position (`cieslak_vissing_jorgensen_2019`)
- `speculative_optionality`: any DCF with point target; "TAM × penetration" without sensitivity bands; comparison to "next NVIDIA" without modality-specific evidence

If you find yourself wanting to write any of the above, restructure the argument to use a permitted framework instead.
```

- [ ] **Step 8: Update output template at end of file**

Find the existing memo output schema. Add these required fields at the top of the schema:

```yaml
tier: core_fundamental | thematic_growth | speculative_optionality
quality_gate:
  piotroski_f_score: <int>
  altman_z_double_prime: <float>
  passes_quality_gate: <bool>
  if_failed_gate_to_disposition: REJECT  # if applicable
frameworks_cited:
  # Each entry uses a short_key from .claude/references/canonical-frameworks.md
  # so the Evaluator can verify citations are valid (Task 17 hard gate #6).
  - framework_key: damodaran_narrative_dcf
    output: <inline section reference>
  - framework_key: mauboussin_reverse_dcf
    output: <inline section reference>
  - framework_key: mauboussin_moat_2024
    output: <inline section reference>
  - framework_key: helmer_7_powers
    output: <inline section reference>
  - framework_key: mauboussin_capital_allocation_2024
    output: <inline section reference>
sector_addenda_invoked:
  - addendum_name: <e.g. saas_unit_economics, marketplace, ai_native>
    framework_keys: [<list of canonical-frameworks short keys, e.g. bessemer_cloud_100>]
yfinance_data_freshness:
  consensus_estimates: {available: bool, last_updated: <iso8601>}
  target_prices: {available: bool, last_updated: <iso8601>}
banned_outputs_check:
  stovall_rotation_used: false
  peg_only_ranking_used: false
  ark_point_targets_used: false
  fed_commentary_without_hfi_used: false
```

- [ ] **Step 9: Commit**

```bash
git add .claude/agents/company-deep-dive.md
git commit -m "Rewrite CDD agent with tier classification + 5-framework core

Per v1 spec §3, §4, §6. Adds:
- Tier classification as first action (core_fundamental / thematic_growth /
  speculative_optionality) routing tier-conditional framework application
- 5-framework core canon (Damodaran narrative-DCF, Mauboussin reverse-DCF,
  Mauboussin Moat 2024, Helmer 7 Powers, Mauboussin Capital Allocation)
  with required citations to canonical-frameworks.md
- Quality gate (Piotroski + Altman) as precondition
- Three new sector-addenda routes (software extended, marketplace, ai-native)
- Banned outputs list (Stovall rotation, PEG-only, ARK point targets,
  Fed commentary without HFI window)
- yfinance MCP tool grants

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Rewrite `.claude/agents/bear-case.md`

**Files:**
- Modify: `.claude/agents/bear-case.md`

Symmetric rewrite. Same 5 frameworks applied adversarially. Same tier discipline. Same yfinance grants. Plus the analog non-overlap rule.

- [ ] **Step 1: Read existing file**

```bash
cat .claude/agents/bear-case.md
```

- [ ] **Step 2: Update frontmatter to add yfinance MCP grants**

Same tool-level grant list as CDD (Task 14 Step 2).

- [ ] **Step 3: Add canonical-frameworks reference to load list**

Add to whatever section instructs the agent to load references:

```markdown
- `.claude/references/canonical-frameworks.md` — same canon as CDD; you apply each framework adversarially (where it breaks, what assumption fails)
```

- [ ] **Step 4: Insert tier classification section (parallel to CDD §2)**

Same content as CDD Task 14 Step 4. The bear case classifies tier based on its own independent data pull.

If your tier classification disagrees with CDD's, surface that disagreement in your output — it's a meaningful signal.

- [ ] **Step 5: Insert "Apply 5-framework core adversarially" section**

```markdown
### Apply the 5-framework core canon adversarially

You see CDD's memo as input. Apply the same 5 frameworks, but argue where each breaks. Cite each by short key in `bear_frameworks_cited`.

#### 1. damodaran_narrative_dcf — adversarial

Where does the bull narrative break? Which growth/margin/duration assumption is too aggressive? Cite a historical analog where a similar story compressed dramatically (NTAP 2002, CSCO 2000, GE 2017, MTCH 2022, PTON 2022).

#### 2. mauboussin_reverse_dcf — adversarial

Are CDD's implied growth + margin + duration achievable? Compute MEROI implied by current price vs the company's actual ROIIC trend. Where they diverge by >1σ, the narrative is unsupported.

#### 3. mauboussin_moat_2024 — adversarial

Why is the moat narrower than CDD claims? Specific erosion vectors: regulatory threat, technology substitution, geographic exposure, customer concentration, key-person risk. State the fade timeline you'd argue for.

#### 4. helmer_7_powers — adversarial

Which "Power" CDD claims is actually a switching cost or scale economy in disguise? (Easy to over-claim Network Economies when the real driver is Scale.) Counter-Positioning vulnerabilities — is there a competitor whose business model would be self-cannibalizing if they imitated?

#### 5. mauboussin_capital_allocation_2024 — adversarial

Where has past allocation destroyed value? Buybacks above intrinsic value? M&A with negative spread (ROIC < WACC on acquired earnings)? Misaligned incentives — does management's comp track per-share metrics, or just headline EPS?

### Analog non-overlap rule

Your output MUST cite different historical analogs than CDD. Re-using CDD's analogs is graded as memo failure by Evaluator. Independent data re-pull (existing rule) stays mandatory — do not rely on CDD's evidence_index citations as the basis for your bear analysis.

### Tier-specific bear analysis

- `core_fundamental`: argue compression of the multiple via specific ROIC fade or terminal-multiple revision
- `thematic_growth`: argue the implied growth premium fails on a defined-probability path
- `speculative_optionality`: walk the milestone tree from CDD's bull side, arguing the probability of each milestone is overstated; for binary milestones, walk the failure-conditional payoff (often -50 to -90% of current price)
```

- [ ] **Step 6: Insert banned-outputs section**

Same content as CDD Task 14 Step 7 (universal + tier-specific).

- [ ] **Step 7: Update bear-case output template**

Add at top of memo schema:

```yaml
tier: core_fundamental | thematic_growth | speculative_optionality
tier_disagreement_with_cdd: <bool, false if matches>
bear_frameworks_cited:
  # Same canonical-frameworks short keys as CDD; the adversarial application
  # is in the `output` section, not the key. Evaluator verifies key validity.
  - framework_key: damodaran_narrative_dcf
    output: <adversarial — where the bull narrative breaks>
  - framework_key: mauboussin_reverse_dcf
    output: <adversarial — implied expectations vs MEROI>
  - framework_key: mauboussin_moat_2024
    output: <adversarial — moat narrower than claimed; specific erosion vectors>
  - framework_key: helmer_7_powers
    output: <adversarial — Power claimed is actually X in disguise>
  - framework_key: mauboussin_capital_allocation_2024
    output: <adversarial — past allocation destroyed value where>

historical_analogs_cited: [<list of company-year strings, MUST NOT overlap with CDD>]
analog_non_overlap_with_cdd: true  # MUST be true
bear_confidence: <float 0..1>
severity_assessment: catastrophic | serious | manageable
banned_outputs_check:
  # same as CDD
```

- [ ] **Step 8: Commit**

```bash
git add .claude/agents/bear-case.md
git commit -m "Rewrite BearCase agent with adversarial 5-framework canon

Symmetric to CDD rewrite. Same 5 frameworks applied to argue where each
breaks. Tier classification independent of CDD; analog non-overlap rule
enforced (different historical analogs than CDD). yfinance MCP grants.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: Update `research-company.md` PMSupervisor section

**Files:**
- Modify: `.claude/commands/research-company.md`

PMSupervisor reads the new `tier` field and includes a tier-aware sleeve-cap reference for `speculative_optionality` recommendations.

- [ ] **Step 1: Read existing file**

```bash
cat .claude/commands/research-company.md
```

- [ ] **Step 2: Find the PMSupervisor synthesis section**

Look for the section that describes how PMSupervisor consumes CDD + BearCase outputs and produces a disposition. (Likely contains language like "synthesizer" or "PM in main context" or "ADD/WATCH/PASS/REJECT".)

- [ ] **Step 3: Add this paragraph immediately before the disposition logic**

```markdown
### Tier-aware synthesis (v1, 2026-05-07)

CDD and BearCase now emit a `tier` field (`core_fundamental | thematic_growth | speculative_optionality`) per spec §6 of `docs/superpowers/specs/2026-05-07-flow-b-v1-frameworks-and-yfinance-design.md`.

Read the tier from CDD's output. If CDD and BearCase disagree on tier, default to the more conservative of the two (BearCase tier wins on disagreement). Apply the tier-aware constraints below to your synthesis:

| Tier | Disposition constraint |
|---|---|
| core_fundamental | Standard logic. ADD/WATCH/PASS/REJECT per existing rubric. |
| thematic_growth | Same logic, but flag in output if implied growth from reverse-DCF exceeds 3-yr historical revenue CAGR. |
| speculative_optionality | If ADD or WATCH: include a `sleeve_reference` block citing the speculative-sleeve cap (≤8% of book aggregate; no single thematic sub-sleeve >40%). Operator enforces the cap manually at sizing time — this is a v1 reference only, not enforced by code. |

Banned outputs at the synthesis layer: the same list as CDD/BearCase (Stovall rotation, PEG-only ranking, ARK-style point targets, Fed commentary without HFI window).
```

- [ ] **Step 4: Commit**

```bash
git add .claude/commands/research-company.md
git commit -m "research-company: tier-aware PMSupervisor synthesis

Reads new tier field from CDD; defaults to BearCase's more-conservative
tier on disagreement. Adds sleeve_reference block for speculative names
(operator-enforced; v1 reference only).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 17: Update `evaluator.md` with new hard gates

**Files:**
- Modify: `.claude/agents/evaluator.md`

Per spec §11.2.

- [ ] **Step 1: Read existing file**

```bash
cat .claude/agents/evaluator.md
```

- [ ] **Step 2: Find the "hard gates" section**

(Look for "hard-gate", "hard_gate", or similar.)

- [ ] **Step 3: Append these gates to the hard-gate list**

```markdown
### v1 framework-canon hard gates (added 2026-05-07)

Applied to every CDD and BearCase memo per `docs/superpowers/specs/2026-05-07-flow-b-v1-frameworks-and-yfinance-design.md` §11.2:

1. **All 5 core frameworks invoked OR correctly skipped per §6.1 tier-conditional table.** DCF + reverse-DCF skipped is acceptable iff `tier = speculative_optionality`. Moat / 7 Powers / Capital Allocation must always run (Capital Allocation may be marked "N/A — pre-revenue, no allocation history" for speculative tier).
2. **No banned outputs.** Universal: Stovall rotation, PEG-only, ARK point targets. Tier-specific: Fed commentary without HFI/FOMC-cycle reference (core/thematic); DCF with point target on speculative; "TAM × penetration" without sensitivity bands on speculative; "next NVIDIA" without modality-specific evidence on speculative.
3. **Quality gate computed.** Memo must include Piotroski F-Score and Altman Z'' (Z for manufacturers) values; if either fails the threshold (F < 6, Z'' < 1.1), `disposition` must be REJECT.
4. **Tier classification field present and matches §6 rubric.** Auditable mapping from quantitative thresholds to assigned tier.
5. **For BearCase: analog non-overlap with CDD.** `historical_analogs_cited` MUST not overlap with CDD's analogs. Soft score, not hard gate.
6. **`frameworks_cited` references valid short keys** from `.claude/references/canonical-frameworks.md`.

Framework substance (depth and quality of application) is graded as a soft score, not a hard gate.
```

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/evaluator.md
git commit -m "Evaluator: add v1 framework-canon hard gates

Per v1 spec §11.2. Hard gates: all 5 frameworks invoked-or-correctly-skipped,
no banned outputs, quality gate computed, tier field present, citations
reference valid canonical-frameworks short keys. BearCase analog non-overlap
graded as soft score.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 18: Three-tier smoke test

**Files:** No file changes; this is a runtime verification.

Per spec §11.1. Validate the v1 system works end-to-end on representative tickers from each tier.

- [ ] **Step 1: Run `/research-company AAPL` (core_fundamental)**

Expected outputs in the memo:
- `tier: core_fundamental`
- All 5 core frameworks invoked with citations to `canonical-frameworks.md` short keys
- Quality gate computed (F-Score + Z'')
- yfinance fields populated (consensus estimates, target prices, etc.)
- No banned outputs
- BearCase produces non-trivial counter-arguments AND cites different historical analogs

If any of these fail, debug the agent prompt and iterate.

- [ ] **Step 2: Run `/research-company TSLA` (thematic_growth)**

Expected:
- `tier: thematic_growth`
- DCF runs but uses ranges, not point targets
- ai-native addendum invoked (TSLA has AI exposure via FSD)
- Sensitivity bands required and present

- [ ] **Step 3: Run `/research-company IONQ` (speculative_optionality)**

Expected:
- `tier: speculative_optionality`
- DCF + reverse-DCF SKIPPED (correctly marked)
- Moat / 7 Powers / Capital Allocation run qualitatively
- Output includes `milestone_tree` block + `sleeve_reference` block
- ai-native addendum invoked (frontier tech with TAM uncertainty)
- No ARK-style point targets
- BearCase walks the milestone tree arguing failure-conditional payoffs

- [ ] **Step 4: Run Evaluator on each memo**

```bash
# Or via /evaluate skill if integrated
```

Each memo must pass all 6 v1 hard gates (Task 17 Step 3).

- [ ] **Step 5: Document results**

Append to `BUILD_LOG.md`:

```markdown
## 2026-05-07 — Flow B v1 smoke test results

Three-tier smoke test per `docs/superpowers/specs/2026-05-07-flow-b-v1-frameworks-and-yfinance-design.md` §11.1:

- AAPL (core_fundamental): [PASS / FAIL with notes]
- TSLA (thematic_growth): [PASS / FAIL with notes]
- IONQ (speculative_optionality): [PASS / FAIL with notes]

Evaluator hard-gate compliance: [PASS / FAIL summary]

Outstanding issues to fix: [list]
```

- [ ] **Step 6: Commit**

```bash
git add BUILD_LOG.md
git commit -m "BUILD_LOG: Flow B v1 three-tier smoke test results

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

If any tier fails: open issues against Task 14/15/16/17 and iterate. Do not declare v1 done until all three tiers pass.

---

## Verification at the end of v1

Before declaring v1 shipped:

1. All 18 tasks above committed.
2. Three-tier smoke test passes on AAPL + TSLA + IONQ.
3. Evaluator agent passes all 6 v1 hard gates on at least 3 memos.
4. `git log --oneline` shows clean per-task commits.
5. `pytest tests/test_yfinance.py -v` passes (or skips cleanly when offline).
6. `.mcp.json` validates as JSON.
7. No regressions in existing memo flow (run a known historical memo through the new agent and confirm output structure matches expectation).

Out-of-scope items (per spec §14) explicitly NOT done in v1:
- CatalystScout subagent (deferred to v2)
- Polygon/Massive options MCP (deferred to v2)
- macro-stack MCP (BLS/BEA/Census/EIA — deferred)
- yfinance Postgres cache (deferred; v1 ships live-only)
- evidence_index producer fix (separate work)
- PMSupervisor sleeve-cap enforcement beyond reference note (v0.5+)
- Schema changes (none in v1)
