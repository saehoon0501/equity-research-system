# `mcp__fundamentals` — STUB

**Status: STUB.** Both tools (`get_fundamentals`, `get_delistings`) raise
`NotImplementedError` with an operator-action message. They reserve the tool
surface that slash commands expect; they do not return data.

## Why stubbed

Sharadar Core Fundamentals subscription is deliberately deferred per
`BUILD_LOG.md` decision 2. v0.1 is paper-only and does not require
point-in-time fundamentals or survivorship-bias-free delisting data to ship a
sample memo. Full deferral rationale and unblocking criteria were in
`docs/tier4-deferred-work.md` (removed in the 2026-05-27 archive cleanup —
recoverable via git history).

## Operator unblocking

To replace this stub with a real implementation:

1. Subscribe to **Sharadar Core Fundamentals** on
   [Nasdaq Data Link](https://data.nasdaq.com/databases/SF1).
2. Add credentials to the repo-root `.env` as `NDL_API_KEY=...`.
3. Replace `server.py` with a real implementation that:
   - In `get_fundamentals`: queries the SF1 (`SHARADAR/SF1`) table filtered to
     the most recent record with `datekey <= as_of_date` for that ticker
     (point-in-time discipline — never read forward-restated values).
   - In `get_delistings`: queries the SF1 / TICKERS metadata for delisting
     events keyed on ticker, returning event date and reason.
4. Remove the `NotImplementedError` raises and update this README to drop the
   STUB banner.

## What this is NOT

This is **not** silent degradation. Slash commands or subagents that reach
`get_fundamentals` and receive `NotImplementedError` are expected to **halt
and report** per `.claude/references/mcp-required.md` §"How skills handle
missing MCPs". They must not catch the error and substitute a degraded
source without explicit operator opt-in.

## V0.1 fallback path

For sample memo generation only (paper-only, **never** for backtests), agents
may use `mcp__edgar.get_company_facts` to source fundamentals data from EDGAR
XBRL. This is a **non-PIT** source — XBRL data is filed-as-of, not
restated-as-of, so backtests using it would suffer look-ahead bias from
subsequent restatements. The fallback is acceptable for sample memos
**only with the explicit non-PIT caveat surfaced in the memo**, per
`mcp-required.md` §3 "Why soft".

## Tests

No tests are included. The stub raises a constant string from a constant
input — there is no behavior to verify beyond "the import works and the
tools are registered with FastMCP", which `mcp.run()` smoke-tests on
startup. Tests will be added when the stub is replaced with the real
Sharadar implementation.

## Dependencies

Minimal — `mcp>=1.0.0` and `python-dotenv>=1.0.0`. No paid SDKs (e.g.,
`nasdaq-data-link`) are pulled in until the operator unblocks the
subscription. This keeps `uv sync` fast and avoids dragging in credentials
that are not yet provisioned.
