"""Fundamentals MCP server for the equity research system.

Per operator decision 2026-05-01 (final): EDGAR XBRL company-facts API
filtered by `filed`-date is the canonical PIT source. Sharadar Core
Fundamentals was evaluated against an active free-tier NDL key on
2026-05-01 — the free tier provides only `MRY` dimension (restated, NOT
PIT-correct), only 2 fiscal years of history, and only a sample subset of
tickers, which is strictly worse than EDGAR XBRL on every dimension we
care about. Sharadar code path removed.

If `NDL_API_KEY` is upgraded to paid SF1 in the future (~$70-100/mo
unlocks ARY/ARQ PIT dimensions + full historical depth + full universe),
re-introduce the Sharadar primary path here. Until then: EDGAR-only.

PIT semantics on EDGAR XBRL:
    Each fact returned by /api/xbrl/companyfacts/CIK{cik}.json carries a
    `filed` field (date the containing 10-K/10-Q/8-K was submitted to SEC).
    To reconstruct what was publicly known about a company on date T:
        1. Fetch all facts.
        2. For each metric, filter to entries where `filed <= T`.
        3. Take the most recent (by `end`-date or `filed`-date) entry.
    The pre-restatement values are preserved as separate entries with their
    original filed-dates, so look-ahead is impossible when the filter is
    applied correctly. Equivalent PIT-correctness to Sharadar's paid SF1
    ARQ/ARY dimensions for the metrics EDGAR covers.

Coverage gap acknowledged:
    - Pre-2009 data (XBRL mandate started 2009).
    - Certain non-XBRL filers (small/foreign).
    For v0.1 (research-driven memos on liquid US equities post-2010), the
    EDGAR PIT path is sufficient.

Two tools:
    - get_fundamentals(ticker, as_of_date): PIT XBRL snapshot via EDGAR.
    - get_delistings(ticker): delisting status via Polygon reference data.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util as _importlib_util
import json
import os
import sys as _sys
import urllib.parse
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


def _load_evidence_persistence():
    """Load the shared fail-soft evidence_documents persistence helper.

    Loaded by file path (unique module name) so it works whether this server is
    launched as an MCP process or imported by file path in tests. Fail-soft: a
    load failure makes persistence a no-op.
    """
    if "_mcp_evidence_persistence" in _sys.modules:
        return _sys.modules["_mcp_evidence_persistence"]
    helper_path = Path(__file__).resolve().parents[1] / "evidence_persistence.py"
    try:
        spec = _importlib_util.spec_from_file_location(
            "_mcp_evidence_persistence", helper_path
        )
        module = _importlib_util.module_from_spec(spec)
        _sys.modules["_mcp_evidence_persistence"] = module
        spec.loader.exec_module(module)
        return module
    except Exception:  # pragma: no cover - persistence is best-effort
        return None


mcp = FastMCP("fundamentals")

# Curated subset of XBRL tags exposed by SEC. The EDGAR companyfacts endpoint
# returns hundreds of tags; this list captures the load-bearing fundamentals
# downstream skills need (memo generation, kill-criteria evaluation, mode
# classifier vol band). Add more on demand — staying narrow keeps the response
# size tractable for LLM consumption.
_PRIMARY_TAGS: tuple[str, ...] = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "NetIncomeLoss",
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue",
    "LongTermDebt",
    "ShortTermBorrowings",
    "OperatingIncomeLoss",
    "GrossProfit",
    "NetCashProvidedByUsedInOperatingActivities",
    "CommonStockSharesOutstanding",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
)


def _ticker_to_cik(ticker: str) -> int:
    """Resolve ticker to SEC CIK via the public ticker→CIK map.

    Cached for the lifetime of the process (the map is ~1MB; SEC asks we be
    polite). Same pattern as src/mcp/edgar/server.py — duplicated here to
    keep this module self-contained.
    """
    if not hasattr(_ticker_to_cik, "_cache"):
        ua = os.environ.get("EDGAR_USER_AGENT")
        if not ua:
            raise RuntimeError(
                "EDGAR_USER_AGENT not set. SEC requires a User-Agent string "
                "with project name and contact email per fair-access policy."
            )
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": ua},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        cache: dict[str, int] = {}
        for row in data.values():
            cache[str(row["ticker"]).upper()] = int(row["cik_str"])
        _ticker_to_cik._cache = cache  # type: ignore[attr-defined]
    cache = _ticker_to_cik._cache  # type: ignore[attr-defined]
    cik = cache.get(ticker.upper())
    if cik is None:
        raise ValueError(f"ticker {ticker!r} not found in SEC ticker→CIK map")
    return cik


def _fetch_company_facts(ticker: str) -> dict[str, Any]:
    """Pull the full XBRL company-facts JSON for a ticker."""
    cik = _ticker_to_cik(ticker)
    ua = os.environ["EDGAR_USER_AGENT"]
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    resp = requests.get(url, headers={"User-Agent": ua}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _pit_value(fact_units: dict[str, Any], as_of: _dt.date) -> dict[str, Any] | None:
    """Pick the most-recent fact entry filed on or before `as_of`.

    `fact_units` is a dict like ``{"USD": [...], "USD/shares": [...]}``. We
    search across all units, prefer USD when ambiguous, and return the entry
    with the latest `end`-date among entries with `filed <= as_of`. This
    gives the AS-FILED snapshot — no look-ahead via restatements.
    """
    candidates: list[dict[str, Any]] = []
    # Prefer USD if present; fall back to other units (USD/shares for EPS).
    unit_priority = ["USD", "USD/shares", "shares"]
    units_iter = sorted(
        fact_units.keys(), key=lambda u: unit_priority.index(u) if u in unit_priority else 99
    )
    for unit_key in units_iter:
        for entry in fact_units[unit_key]:
            try:
                filed = _dt.date.fromisoformat(entry["filed"])
            except (KeyError, ValueError):
                continue
            if filed > as_of:
                continue
            candidates.append({**entry, "_unit": unit_key})
        if candidates:
            break  # use first non-empty unit per priority
    if not candidates:
        return None
    # Sort by `end` (fiscal period end) DESC, then `filed` DESC as tiebreak.
    candidates.sort(
        key=lambda e: (e.get("end", ""), e.get("filed", "")),
        reverse=True,
    )
    return candidates[0]


def _fetch_edgar_pit(ticker: str, as_of: _dt.date) -> dict[str, Any]:
    """Canonical path: EDGAR XBRL company-facts filtered by `filed`-date."""
    company_facts = _fetch_company_facts(ticker)
    cik = company_facts.get("cik")
    entity_name = company_facts.get("entityName", "")
    us_gaap = (company_facts.get("facts") or {}).get("us-gaap", {})

    facts_out: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for tag in _PRIMARY_TAGS:
        tag_block = us_gaap.get(tag)
        if not tag_block or not tag_block.get("units"):
            missing.append(tag)
            continue
        pit = _pit_value(tag_block["units"], as_of)
        if pit is None:
            missing.append(tag)
            continue
        facts_out[tag] = {
            "value": pit.get("val"),
            "unit": pit.get("_unit"),
            "fiscal_period_end": pit.get("end"),
            "filed": pit.get("filed"),
            "fy": pit.get("fy"),
            "fp": pit.get("fp"),
        }
    return {
        "ticker": ticker.upper(),
        "cik": cik,
        "as_of_date": as_of.isoformat(),
        "entity_name": entity_name,
        "facts": facts_out,
        "missing": missing,
        "source": "edgar_xbrl_pit_filtered",
    }


@mcp.tool()
def get_fundamentals(ticker: str, as_of_date: str) -> dict:
    """Point-in-time fundamentals snapshot via EDGAR XBRL.

    Filtered by `filed <= as_of_date` so the snapshot reflects only what
    was publicly known on that date — no look-ahead via restatements.

    Args:
        ticker: stock ticker (e.g., 'AAPL').
        as_of_date: ISO date 'YYYY-MM-DD'.

    Returns:
        {
            "ticker": "AAPL",
            "cik": 320193,
            "as_of_date": "2024-12-31",
            "entity_name": "Apple Inc.",
            "facts": {
                "Revenues": {"value": ..., "unit": "USD",
                             "fiscal_period_end": "...", "filed": "..."},
                ...
            },
            "missing": [...],
            "source": "edgar_xbrl_pit_filtered"
        }
    """
    try:
        as_of = _dt.date.fromisoformat(as_of_date)
    except ValueError:
        raise ValueError(f"as_of_date must be ISO 'YYYY-MM-DD'; got {as_of_date!r}")
    result = _fetch_edgar_pit(ticker, as_of)

    # P0-3: persist the PIT fundamentals payload to evidence_documents, keyed to
    # a synthetic source_uri (same vocabulary as evidence_index). Fail-soft &
    # additive — the return shape below is unchanged.
    _persist = _load_evidence_persistence()
    if _persist is not None:
        _persist.persist_document(
            source_uri=f"fundamentals://edgar-pit/{ticker.upper()}/{as_of.isoformat()}",
            body=result,
            fetched_by="fundamentals",
        )

    return result


@mcp.tool()
def get_delistings(ticker: str) -> dict:
    """Delisting status via Polygon /v3/reference/tickers.

    Args:
        ticker: stock ticker.

    Returns:
        {
            "ticker": "BBBY",
            "active": false,
            "delisted_utc": "2023-04-26T00:00:00Z",  # null if active
            "name": "Bed Bath & Beyond Inc.",
            "primary_exchange": "XNAS",
            "list_date": "2000-06-05",
            "source": "polygon_reference"
        }
    """
    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        return {
            "ticker": ticker.upper(),
            "active": None,
            "delisted_utc": None,
            "error": "POLYGON_API_KEY not set; delisting status unavailable. "
                     "Set Polygon Stocks Starter ($29/mo) key in .env.",
            "source": "polygon_reference",
        }
    url = f"https://api.polygon.io/v3/reference/tickers/{ticker.upper()}"
    try:
        resp = requests.get(
            url,
            params={"apiKey": api_key},
            headers={"User-Agent": "equity-research-system/0.1"},
            timeout=10,
        )
    except requests.RequestException as exc:
        return {
            "ticker": ticker.upper(),
            "active": None,
            "delisted_utc": None,
            "error": f"network error: {type(exc).__name__}: {exc}",
            "source": "polygon_reference",
        }
    if resp.status_code == 404:
        return {
            "ticker": ticker.upper(),
            "active": False,
            "delisted_utc": None,
            "error": "404 from Polygon — ticker not found, possibly delisted "
                     "before Polygon's coverage window or invalid symbol.",
            "source": "polygon_reference",
        }
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results") or {}
    return {
        "ticker": ticker.upper(),
        "active": results.get("active"),
        "delisted_utc": results.get("delisted_utc"),
        "name": results.get("name"),
        "primary_exchange": results.get("primary_exchange"),
        "list_date": results.get("list_date"),
        "source": "polygon_reference",
    }


if __name__ == "__main__":
    mcp.run()
