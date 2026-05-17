# `mcp__postgres` server

Postgres MCP server for the equity research system. Per BUILD_LOG.md decision 6, this is a *tool consumed by Claude Code*, not an orchestrator. Three tools, exactly matching `.claude/references/mcp-required.md` spec:

| Tool | Purpose | Notes |
|---|---|---|
| `query(sql)` | Read-only SELECT / EXPLAIN / SHOW | Runs in a `READ ONLY` transaction; writes fail at Postgres level |
| `execute(sql, params)` | INSERT / UPDATE / DELETE / DDL | Permissive at MCP layer; append-only is enforced by DB-level triggers (Tier 2) |
| `schema_info(table_name)` | Introspection | No arg → list of public tables; with arg → columns for that table |

## Bring up

The DB needs to be running first (see `db/README.md` at repo root).

```sh
# From repo root, install deps into the project's venv.
uv sync --project src/mcp/postgres

# Smoke test: connects to the DB and prints version.
uv run --project src/mcp/postgres python -c "
from server import query
print(query('SELECT version()'))
"
```

The MCP server itself is launched by Claude Code (not by you) via `.mcp.json` at repo root. Restart Claude Code after editing `.mcp.json` for the changes to take effect.

## How connection info is loaded

`server.py` walks up to repo root and loads `.env` via `python-dotenv`. This means:

- The single source of truth for the DB password is `.env` (gitignored).
- `.mcp.json` does not embed credentials — it just tells Claude Code how to launch the server.
- Local tools (psql, ad-hoc scripts) and this MCP server all read from the same `.env`.

If you change the password in `.env`, the next MCP-server launch picks it up. No restart of the DB needed.

## Why our own server (not a community one)

The official `@modelcontextprotocol/server-postgres` is read-only — only `SELECT`. We need writes for Evidence Index inserts, so we'd need a community implementation or our own.

Our own is the canonical demonstration of decision 6: ~150 lines of Python, exactly the tools `mcp-required.md` specifies, append-only handled by Postgres triggers (Tier 2), no surface area we don't control.

## What this is not

- Not a connection pool. New connection per tool call. For v0.1 single-operator usage this is fine; if Tier 4 reveals contention, swap in a pooler (`pgbouncer` sidecar or `psycopg_pool`).
- Not authenticated beyond the DB user. The MCP server runs as a subprocess of Claude Code on your machine; access control is "if you can read `.env`, you can hit the DB."
- Not retry-aware. If Postgres is down, tools raise. The slash command surfaces the error to the operator, who restarts `docker compose`.
