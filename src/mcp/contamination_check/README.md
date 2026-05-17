# `mcp__contamination_check` server

Mechanical contamination check MCP server for the equity research system. Per BUILD_LOG.md decision 6, this is a *tool consumed by Claude Code* (specifically the Evaluator subagent), not an orchestrator. Three tools, exactly matching `src/mcp/contamination_check/DESIGN.md`:

| Tool | Purpose | Notes |
|---|---|---|
| `verify(agent_run_id, evidence_index_refs, claims)` | Hard-gate verification of an agent output against the Evidence Index | Single connection per call, READ ONLY transaction; any failure mode → `verdict=FAIL` |
| `verify_memo(memo_path)` | Convenience wrapper that reads a memo JSON file and calls `verify()` | For ad-hoc audit at `/evaluate`; production path is `verify()` from the Evaluator |
| `diagnostic(agent_run_id)` | Read-only — returns Evidence Index rows for an `agent_run_id` plus a re-run of `verify()` | Used by Checkpoint 3 audit and `/evaluate` re-examination |

The check is mechanical: any failure mode (MISSING_REF, FABRICATED_UUID, POSTDATED_SOURCE, INCOHERENT_PREDICTION, EMPTY_REFS, MALFORMED_CLAIM) in any claim produces `verdict=FAIL`. No partial credit, no severity weighting, no semantic override.

## Bring up

The DB needs to be running first (see `db/README.md` at repo root) and `mcp__postgres` deps must be resolvable on the same `.env`.

```sh
# From repo root, install deps into the project's venv.
uv sync --project src/mcp/contamination_check

# Smoke test: connects to the DB and runs an empty-claims verify (PASS).
uv run --project src/mcp/contamination_check python -c "
from server import verify
print(verify('00000000-0000-0000-0000-000000000000', [], []))
"
```

The MCP server itself is launched by Claude Code (not by you) via `.mcp.json` at repo root. Restart Claude Code after editing `.mcp.json` for the changes to take effect.

## How connection info is loaded

`server.py` walks up to repo root and loads `.env` via `python-dotenv` — the same single source of truth as `mcp__postgres`. There are no separate credentials for this server.

## Why our own server (decision 6)

The contamination check is load-bearing under Path A (decision 1) once model-family diversity is gone. Per DESIGN.md §1, a skill helper invoked as a subprocess would force the brain to reason about a `subprocess.run` return code; promoting it to MCP makes it a typed, discoverable capability invokable by name from any subagent — `mcp__contamination_check.verify(...)` — exactly mirroring how `mcp__postgres` is consumed.

This server lives in the same Python shape as `src/mcp/postgres/` (~250 lines, FastMCP, `.env` config) and shares the canonical decision-6 pattern: code is a tool consumed by Claude Code, not the orchestrator.

## What this is not

- **Not a claim parser.** No NLP, no LLM, no AI in this server. The Evaluator subagent (or the structured output of the producing subagent) supplies a `claims` list. `verify_memo` accepts a memo only when its structured output already contains `claims` or `reviewable_predictions`; it never re-tokenizes prose. Heuristic prose extraction is fail-closed by design.
- **Not a writer.** The check is a *consumer* of the Evidence Index. Writes are the agent's job per `evidence-index-schema.md` §"Write procedure". This server only reads.
- **Not a connection pool.** New connection per tool call, like `mcp__postgres`. v0.1 single-operator usage; revisit if Tier 4 reveals contention.
- **Not retry-aware.** If Postgres is down, tools raise. The Evaluator's "REJECT all outputs by default" rule fires upstream and the slash command surfaces the error to the operator.
- **Not authenticated** beyond the DB user — same posture as `mcp__postgres`.
