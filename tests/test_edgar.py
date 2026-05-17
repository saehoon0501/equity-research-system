"""Integration smoke tests for the EDGAR MCP server (`src/mcp/edgar/server.py`).

These tests hit the LIVE SEC EDGAR API (data.sec.gov + sec.gov). They are
network-dependent and marked `@pytest.mark.integration` so they can be skipped
in offline CI later (e.g. `pytest -m 'not integration'`).

We use AAPL (CIK 320193) for every test — stable, public, lots of filings.

A session-scoped `apple_filings` fixture fetches `get_filings("AAPL")` once and
shares the result, so we don't hammer the SEC API across the basic-shape and
filing-text tests. Per-test calls that need different parameters
(form filter, since_date, CIK alias, unknown ticker) hit the API directly,
each with `limit` kept small.

Run from repo root after both subagents finish:
    pytest tests/test_edgar.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Each MCP server module lives at `src/mcp/<name>/server.py` with no package
# `__init__.py`, and they all share the bare module name `server`. A naive
# `from server import X` after `sys.path.insert(...)` collides in
# `sys.modules` when pytest collects multiple MCP test files in one session
# (only the first `server` ever loaded sticks). Load this MCP's `server.py`
# directly by file path under a unique module name to avoid the collision.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVER_PATH = _REPO_ROOT / "src/mcp/edgar/server.py"
_spec = importlib.util.spec_from_file_location("edgar_mcp_server", _SERVER_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["edgar_mcp_server"] = _module
_spec.loader.exec_module(_module)

get_company_facts = _module.get_company_facts
get_filing_text = _module.get_filing_text
get_filings = _module.get_filings

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
APPLE_TICKER = "AAPL"
APPLE_CIK_PADDED = "0000320193"
APPLE_CIK_INT = 320193
APPLE_ARCHIVES_PREFIX = "https://www.sec.gov/Archives/edgar/data/320193/"


# -----------------------------------------------------------------------------
# Shared fixtures (be polite to SEC — fetch once per session where reusable)
# -----------------------------------------------------------------------------
@pytest.fixture(scope="session")
def apple_filings() -> dict:
    """One get_filings("AAPL") call, shared by basic-shape and filing-text tests."""
    return get_filings(APPLE_TICKER)


@pytest.fixture(scope="session")
def apple_10k_url(apple_filings: dict) -> str:
    """Pick one Apple 10-K primary_doc_url for get_filing_text tests.

    We do a small targeted call here (limit=3) rather than scanning the full
    default-size list, since 10-Ks may not appear in the most-recent default
    window (Apple files quarterly 10-Qs and many 8-Ks).
    """
    res = get_filings(APPLE_TICKER, form_type="10-K", limit=3)
    filings = res.get("filings", [])
    assert filings, "expected at least one 10-K for AAPL"
    return filings[0]["primary_doc_url"]


# -----------------------------------------------------------------------------
# get_filings
# -----------------------------------------------------------------------------
@pytest.mark.integration
def test_get_filings_apple_basic(apple_filings: dict) -> None:
    """Basic shape: identifiers, company name, non-empty filings, expected fields."""
    result = apple_filings

    assert result["cik"] == APPLE_CIK_PADDED
    assert result["ticker"] == APPLE_TICKER
    assert "Apple" in result["company_name"]

    filings = result["filings"]
    assert len(filings) > 0

    first = filings[0]
    for field in ("accession_number", "form", "filing_date", "primary_doc_url"):
        assert field in first, f"missing field in filing: {field}"

    assert first["primary_doc_url"].startswith(APPLE_ARCHIVES_PREFIX), (
        f"primary_doc_url should live under {APPLE_ARCHIVES_PREFIX}, "
        f"got {first['primary_doc_url']!r}"
    )


@pytest.mark.integration
def test_get_filings_form_filter() -> None:
    """form_type='10-K' returns only 10-Ks, respects limit, finds at least one."""
    result = get_filings(APPLE_TICKER, form_type="10-K", limit=5)
    filings = result["filings"]

    assert len(filings) <= 5
    assert len(filings) >= 1, "Apple files 10-K annually; expected >= 1"
    for f in filings:
        assert f["form"] == "10-K", f"non-10-K leaked through filter: {f['form']}"


@pytest.mark.integration
def test_get_filings_since_date() -> None:
    """since_date is inclusive: every returned filing_date >= since_date."""
    since = "2020-01-01"
    result = get_filings(APPLE_TICKER, since_date=since, limit=10)
    filings = result["filings"]

    assert len(filings) > 0, "Apple has filed since 2020-01-01; expected results"
    for f in filings:
        assert f["filing_date"] >= since, (
            f"filing_date {f['filing_date']} predates since_date {since}"
        )


@pytest.mark.integration
def test_get_filings_by_cik() -> None:
    """CIK string ('320193') works as alias for ticker — same result shape."""
    result = get_filings("320193", limit=5)

    assert result["cik"] == APPLE_CIK_PADDED
    # ticker may be "AAPL" (resolved) — assert it's present and Apple-shaped.
    assert result["ticker"] == APPLE_TICKER
    assert "Apple" in result["company_name"]
    assert len(result["filings"]) > 0

    first = result["filings"][0]
    for field in ("accession_number", "form", "filing_date", "primary_doc_url"):
        assert field in first
    assert first["primary_doc_url"].startswith(APPLE_ARCHIVES_PREFIX)


@pytest.mark.integration
def test_get_filings_unknown_ticker() -> None:
    """Unknown ticker raises ValueError (not a silent empty result)."""
    with pytest.raises(ValueError):
        get_filings("NOSUCHTICKER12345")


# -----------------------------------------------------------------------------
# get_filing_text
# -----------------------------------------------------------------------------
@pytest.mark.integration
def test_get_filing_text_html(apple_10k_url: str) -> None:
    """Fetch a real Apple 10-K's primary doc; check content_type, size, and Apple mention."""
    result = get_filing_text(apple_10k_url)

    content_type = result["content_type"].lower()
    assert content_type.startswith("text/") or "html" in content_type, (
        f"expected text/* or html content_type, got {result['content_type']!r}"
    )

    assert result["length"] > 1000, (
        f"10-K should be large; got length={result['length']}"
    )

    text = result["text"]
    assert APPLE_TICKER in text or "Apple" in text, (
        "expected 'AAPL' or 'Apple' to appear in 10-K text"
    )


# -----------------------------------------------------------------------------
# get_company_facts
# -----------------------------------------------------------------------------
@pytest.mark.integration
def test_get_company_facts_apple() -> None:
    """Basic shape of XBRL company facts for Apple."""
    result = get_company_facts(APPLE_TICKER)

    assert result["cik"] == APPLE_CIK_INT
    assert "Apple" in result["entityName"]

    facts = result["facts"]
    assert "us-gaap" in facts, "expected us-gaap taxonomy in facts"

    us_gaap = facts["us-gaap"]
    # Apple reports revenue under one of these GAAP concept names depending on
    # year; require at least one to be present.
    revenue_concepts = (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    )
    assert any(c in us_gaap for c in revenue_concepts), (
        f"expected one of {revenue_concepts} in us-gaap facts; "
        f"got keys sample: {list(us_gaap.keys())[:10]}"
    )
