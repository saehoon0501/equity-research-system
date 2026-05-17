"""Postgres MCP server for the equity research system.

Per BUILD_LOG.md decision 6, this is a tool consumed by Claude Code, not an
orchestrator. Exposes three tools per `.claude/references/mcp-required.md`:

- query(sql): read-only SELECT (forced via READ ONLY transaction)
- execute(sql, params): writes — INSERT/UPDATE/DELETE/DDL
                        (append-only is enforced at the DB level via Tier 2 triggers,
                        not here; this tool is permissive by design)
- schema_info(table_name): introspect tables / columns

Connection info is loaded from the repo root `.env` file via python-dotenv.
"""

from __future__ import annotations

import datetime
import decimal
import os
import uuid
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Walk: server.py → postgres/ → mcp/ → src/ → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


def _dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ.get('POSTGRES_HOST', '127.0.0.1')}:{os.environ.get('POSTGRES_PORT', '5432')}"
        f"/{os.environ['POSTGRES_DB']}"
    )


def _jsonify(value: Any) -> Any:
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return value


mcp = FastMCP("postgres")


@mcp.tool()
def query(sql: str) -> dict[str, Any]:
    """Run a read-only SQL query against the equity_research database.

    Statement runs inside a READ ONLY transaction; any attempt to modify
    data fails at the Postgres level. Use `execute` for writes.

    Returns:
        {"columns": [...], "rows": [...], "rowcount": N}
    """
    with psycopg.connect(_dsn()) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql)
            columns = [d.name for d in cur.description] if cur.description else []
            rows: list[tuple] = cur.fetchall() if cur.description else []
            return {
                "columns": columns,
                "rows": [[_jsonify(c) for c in row] for row in rows],
                "rowcount": cur.rowcount,
            }


@mcp.tool()
def execute(sql: str, params: list | None = None) -> dict[str, Any]:
    """Execute a write statement (INSERT, UPDATE, DELETE, DDL).

    Append-only constraints on evidence_index, predictions, and
    counterfactual_ledger are enforced at the DB level via triggers
    installed in Tier 2. UPDATE/DELETE on those tables will be rejected
    by Postgres regardless of what is sent here.

    Args:
        sql: parameterized SQL with %s placeholders
        params: positional parameters

    Returns:
        {"rowcount": N, "status": "OK"}
    """
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return {"rowcount": cur.rowcount, "status": "OK"}


@mcp.tool()
def schema_info(table_name: str | None = None) -> dict[str, Any]:
    """Introspect the public schema.

    With no argument: returns the list of tables.
    With table_name: returns column info for that table.
    """
    with psycopg.connect(_dsn()) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            if table_name is None:
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                    """
                )
                return {"tables": [r[0] for r in cur.fetchall()]}
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table_name,),
            )
            return {
                "table": table_name,
                "columns": [
                    {
                        "name": r[0],
                        "type": r[1],
                        "nullable": r[2] == "YES",
                        "default": r[3],
                    }
                    for r in cur.fetchall()
                ],
            }


if __name__ == "__main__":
    mcp.run()
