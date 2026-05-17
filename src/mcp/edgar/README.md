# `mcp__edgar` server

SEC EDGAR MCP server for the equity research system. Per BUILD_LOG.md decision 6, this is a *tool consumed by Claude Code* (specifically the CompanyDeepDive subagent), not an orchestrator. Three tools, exactly matching `.claude/references/mcp-required.md` §"`mcp__edgar`":

| Tool | Purpose | Notes |
|---|---|---|
| `get_filings(ticker_or_cik, form_type, since_date, limit)` | Recent filings list (10-K, 10-Q, 8-K, Form 4, 13F, etc.) | Reads `filings.recent` from `data.sec.gov/submissions`; ticker→CIK lookup cached on first use |
| `get_filing_text(primary_doc_url)` | Fetch the text content of a filing's primary document | Returns raw `text` (HTML or XML preserved); no parsing |
| `get_company_facts(ticker_or_cik)` | XBRL company-facts JSON | Returned as-is from `data.sec.gov/api/xbrl/companyfacts`; no deserialization |

## Bring up

```sh
# From repo root, install deps into the project's venv.
uv sync --project src/mcp/edgar

# Smoke test: requires EDGAR_USER_AGENT in .env. Lists most-recent Apple filings.
uv run --project src/mcp/edgar python -c "
from server import get_filings
result = get_filings('AAPL', form_type='10-K', limit=3)
print(result['cik'], result['company_name'])
for f in result['filings']:
    print(f['form'], f['filing_date'], f['primary_doc_url'])
"
```

The MCP server itself is launched by Claude Code (not by you) via `.mcp.json` at repo root. Restart Claude Code after editing `.mcp.json` for the changes to take effect.

## How connection info is loaded

`server.py` walks up to repo root and loads `.env` via `python-dotenv` — the same single source of truth as `mcp__postgres` and `mcp__contamination_check`.

### Required env

| Var | Required | Purpose |
|---|---|---|
| `EDGAR_USER_AGENT` | yes | Sent on every SEC HTTP request per [SEC fair-access policy](https://www.sec.gov/os/accessing-edgar-data). Format: `'Project Name contact@example.com'`. SEC may rate-limit or block requests without a proper UA — this server fails loud (raises `RuntimeError`) on the first tool call if unset, rather than letting SEC silently degrade or block us. |

## Why our own server (decision 6)

The `edgartools` Python library is a fine reference implementation, but wrapping it in MCP would couple us to its release cadence and surface area. The `data.sec.gov` and `www.sec.gov` HTTP endpoints are the underlying truth: `submissions/CIK{cik}.json`, `api/xbrl/companyfacts/CIK{cik}.json`, and the `Archives/edgar/data/...` static tree. A thin httpx wrapper over those three URLs (~250 lines) is transparent and auditable: every byte going to or from SEC is visible in this file. The Evidence Index cites filing dates from these endpoints; mechanical contamination check resolves against them. Owning the wrapper means we own the resolution semantics.

This server lives in the same Python shape as `src/mcp/postgres/` and `src/mcp/contamination_check/` (FastMCP, `.env` config) and shares the canonical decision-6 pattern: code is a tool consumed by Claude Code, not the orchestrator.

## What this is not

- **Not the `edgartools` library.** No dependency on `edgartools`. We talk to SEC's HTTP endpoints directly.
- **Not an XBRL deserializer.** `get_company_facts` returns the raw `companyfacts` JSON dict as SEC ships it. Concept slicing (e.g., "Revenues over the last 8 quarters") is the consumer's job — usually a downstream subagent or `mcp__fundamentals` (Sharadar, deferred).
- **Not paginating into older filings.** Only `filings.recent` is read on the submissions endpoint. SEC may list older filings under `filings.files` (separate JSON files); v0.1 ignores those. `filings.recent` carries ~1000 most-recent filings, which is plenty for CompanyDeepDive scope.
- **Not authenticated** beyond the `EDGAR_USER_AGENT` SEC asks us to send.
- **Not a connection pool.** New `httpx.Client` per tool call. v0.1 single-operator usage.
- **Not retry-aware.** HTTP errors propagate; mcp surfaces them. SEC 429 (rate limit) means the operator should slow down or check the UA value.
