"""SEC EDGAR MCP server for the equity research system.

Per BUILD_LOG.md decision 6, this is a tool consumed by Claude Code (specifically
the CompanyDeepDive subagent), not an orchestrator. Thin HTTP wrapper over
`data.sec.gov` and `www.sec.gov` per `.claude/references/mcp-required.md`
§"`mcp__edgar`".

Three tools:

- get_filings(ticker_or_cik, form_type, since_date, limit): recent filings list.
- get_filing_text(primary_doc_url): fetch the text content of a primary document.
- get_company_facts(ticker_or_cik): XBRL company-facts JSON, returned as-is.

Connection info (specifically the SEC fair-access User-Agent header) is loaded
from the repo root `.env` file via python-dotenv. The User-Agent is required;
the server fails loud on the first tool call if `EDGAR_USER_AGENT` is unset.

Scope notes:
- Only `filings.recent` is consulted on the submissions endpoint. SEC may
  expose older filings under `filings.files` (separate JSON files); v0.1 does
  not paginate into those — `filings.recent` covers ~1000 most-recent filings
  which is plenty for CompanyDeepDive purposes.
- No XBRL deserialization; `get_company_facts` returns the raw JSON dict.
"""

from __future__ import annotations

import importlib.util as _importlib_util
import os
import sys as _sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Walk: server.py → edgar/ → mcp/ → src/ → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


def _load_evidence_persistence():
    """Load the shared fail-soft evidence_documents persistence helper.

    Loaded by file path (under a unique module name) so it works whether this
    server is launched as an MCP process or imported by file path in tests —
    ``src/mcp`` is not guaranteed to be on ``sys.path``. Fail-soft: if the
    helper cannot be loaded, persistence becomes a no-op.
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


_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik_padded}.json"
_COMPANY_FACTS_URL = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
)
_ARCHIVES_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_nodash}/{primary_document}"
)

_HTTP_TIMEOUT = 30.0

# Module-level cache for the ticker→CIK map. Lazy on-demand: first ticker
# lookup populates it; subsequent calls hit the cache. Reset only by restart.
_TICKER_TO_CIK: dict[str, dict[str, Any]] | None = None


def _user_agent() -> str:
    """Return the SEC fair-access User-Agent or fail loud.

    SEC may rate-limit or block requests without a proper UA. We refuse to
    make any HTTP call until the operator has set this in `.env`.
    """
    ua = os.environ.get("EDGAR_USER_AGENT")
    if not ua:
        raise RuntimeError(
            "EDGAR_USER_AGENT must be set in .env per SEC fair-access policy. "
            "Format: 'Project Name contact@example.com'"
        )
    return ua


def _http_client() -> httpx.Client:
    """Per-call httpx client with the SEC User-Agent header.

    Connection pooling is not needed at v0.1 scale; one client per tool call
    keeps the surface area minimal.
    """
    return httpx.Client(
        headers={"User-Agent": _user_agent()},
        timeout=_HTTP_TIMEOUT,
    )


def _pad_cik(cik: str | int) -> str:
    """Zero-pad a CIK to the 10-digit form SEC URLs expect."""
    return str(int(str(cik).lstrip("0") or "0")).zfill(10)


def _load_ticker_map(client: httpx.Client) -> dict[str, dict[str, Any]]:
    """Fetch and cache the ticker→CIK map (uppercase-ticker keyed)."""
    global _TICKER_TO_CIK
    if _TICKER_TO_CIK is not None:
        return _TICKER_TO_CIK
    resp = client.get(_TICKER_MAP_URL)
    resp.raise_for_status()
    raw = resp.json()
    # SEC ships this as {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    mapping: dict[str, dict[str, Any]] = {}
    for entry in raw.values():
        ticker = str(entry.get("ticker", "")).upper()
        if not ticker:
            continue
        mapping[ticker] = {
            "cik_int": int(entry["cik_str"]),
            "cik_padded": _pad_cik(entry["cik_str"]),
            "ticker": ticker,
            "company_name": entry.get("title", ""),
        }
    _TICKER_TO_CIK = mapping
    return mapping


def _resolve(
    ticker_or_cik: str, client: httpx.Client
) -> dict[str, Any]:
    """Resolve a ticker or CIK string to {cik_int, cik_padded, ticker, company_name}.

    Discrimination rule: if the input (after stripping leading zeros) is all
    digits, treat it as a CIK and reverse-lookup the ticker map for the
    matching ticker + company_name. Otherwise look it up in the cached
    ticker map by ticker (case-insensitive). Both paths fetch the ticker
    map at most once per process; the cache is shared.
    """
    raw = ticker_or_cik.strip()
    digits_only = raw.lstrip("0")
    if digits_only.isdigit() or (raw == "0" * len(raw) and raw):
        cik_int = int(digits_only or "0")
        mapping = _load_ticker_map(client)
        for record in mapping.values():
            if record["cik_int"] == cik_int:
                return dict(record)
        # CIK not in the public ticker map (private filer, fund, etc.);
        # still functional for filings/facts queries — just no ticker echo.
        return {
            "cik_int": cik_int,
            "cik_padded": _pad_cik(raw),
            "ticker": "",
            "company_name": "",
        }
    mapping = _load_ticker_map(client)
    record = mapping.get(raw.upper())
    if record is None:
        raise ValueError(f"Unknown CIK/ticker: {ticker_or_cik}")
    return dict(record)


def _build_primary_doc_url(
    cik_int: int, accession_number: str, primary_document: str
) -> str:
    """Construct the canonical Archives URL for a filing's primary document."""
    accession_no_nodash = accession_number.replace("-", "")
    return _ARCHIVES_URL.format(
        cik_int=cik_int,
        accession_no_nodash=accession_no_nodash,
        primary_document=primary_document,
    )


mcp = FastMCP("edgar")


@mcp.tool()
def get_filings(
    ticker_or_cik: str,
    form_type: str | None = None,
    since_date: str | None = None,
    limit: int = 20,
) -> dict:
    """Return recent filings for a company.

    Args:
        ticker_or_cik: ticker (e.g., 'AAPL') or CIK string (e.g., '320193' or '0000320193')
        form_type: optional filter, e.g., '10-K', '10-Q', '8-K'. Exact match against the form column.
        since_date: optional ISO date 'YYYY-MM-DD'; only filings on or after this date.
        limit: max filings to return (default 20).

    Returns:
        {
            "cik": "0000320193",  # zero-padded 10 digits
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "filings": [
                {
                    "accession_number": "0000320193-24-000123",
                    "form": "10-K",
                    "filing_date": "2024-11-01",
                    "report_date": "2024-09-28",
                    "primary_document": "aapl-20240928.htm",
                    "primary_doc_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                },
                ...
            ]
        }

    Note:
        Only `filings.recent` is consulted; older filings under `filings.files`
        are not paginated into at v0.1. `filings.recent` carries ~1000 most-recent
        filings which is sufficient for CompanyDeepDive scope.
    """
    with _http_client() as client:
        resolved = _resolve(ticker_or_cik, client)
        cik_padded = resolved["cik_padded"]
        cik_int = resolved["cik_int"]

        url = _SUBMISSIONS_URL.format(cik_padded=cik_padded)
        resp = client.get(url)
        if resp.status_code == 404:
            raise ValueError(f"Unknown CIK/ticker: {ticker_or_cik}")
        resp.raise_for_status()
        data = resp.json()

        company_name = (
            resolved.get("company_name") or data.get("name", "") or ""
        )

        recent = data.get("filings", {}).get("recent", {}) or {}
        accession_numbers = recent.get("accessionNumber", []) or []
        forms = recent.get("form", []) or []
        filing_dates = recent.get("filingDate", []) or []
        report_dates = recent.get("reportDate", []) or []
        primary_documents = recent.get("primaryDocument", []) or []

        filings: list[dict[str, Any]] = []
        for i in range(len(accession_numbers)):
            form = forms[i] if i < len(forms) else ""
            filing_date = filing_dates[i] if i < len(filing_dates) else ""
            report_date = report_dates[i] if i < len(report_dates) else ""
            primary_document = (
                primary_documents[i] if i < len(primary_documents) else ""
            )
            accession_number = accession_numbers[i]

            # Form filter: exact match against the SEC form column.
            if form_type is not None and form != form_type:
                continue
            # Date filter: ISO-comparable 'YYYY-MM-DD' string compare is correct.
            if since_date is not None and filing_date < since_date:
                continue

            filings.append(
                {
                    "accession_number": accession_number,
                    "form": form,
                    "filing_date": filing_date,
                    "report_date": report_date,
                    "primary_document": primary_document,
                    "primary_doc_url": _build_primary_doc_url(
                        cik_int, accession_number, primary_document
                    ),
                }
            )
            if len(filings) >= limit:
                break

        return {
            "cik": cik_padded,
            "ticker": resolved.get("ticker", ""),
            "company_name": company_name,
            "filings": filings,
        }


@mcp.tool()
def get_filing_text(primary_doc_url: str) -> dict:
    """Fetch the text content of a filing's primary document, given the URL
    returned by `get_filings`.

    Args:
        primary_doc_url: full URL from get_filings result.

    Returns:
        {
            "url": str,
            "content_type": str,           # e.g., 'text/html', 'application/xml'
            "length": int,                  # bytes
            "text": str,                    # decoded text content (HTML or XML preserved)
        }
    """
    with _http_client() as client:
        resp = client.get(primary_doc_url)
        resp.raise_for_status()
        content_bytes = resp.content
        content_type = resp.headers.get("content-type", "").split(";")[0].strip()
        text = resp.text

        # P0-3: persist the fetched filing body to evidence_documents, keyed to
        # the document URL (== source_uri vocabulary). Fail-soft & additive —
        # the return shape below is unchanged.
        _persist = _load_evidence_persistence()
        if _persist is not None:
            _persist.persist_document(
                source_uri=primary_doc_url, body=text, fetched_by="edgar"
            )

        return {
            "url": primary_doc_url,
            "content_type": content_type,
            "length": len(content_bytes),
            "text": text,
        }


@mcp.tool()
def get_company_facts(ticker_or_cik: str) -> dict:
    """Fetch XBRL company facts (structured financial data).

    Args:
        ticker_or_cik: ticker or CIK.

    Returns the data.sec.gov XBRL company facts response as a dict, with at minimum:
        {
            "cik": int,
            "entityName": str,
            "facts": {"us-gaap": {...}, "dei": {...}}
        }
    """
    with _http_client() as client:
        resolved = _resolve(ticker_or_cik, client)
        url = _COMPANY_FACTS_URL.format(cik_padded=resolved["cik_padded"])
        resp = client.get(url)
        if resp.status_code == 404:
            raise ValueError(f"Unknown CIK/ticker: {ticker_or_cik}")
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    mcp.run()
