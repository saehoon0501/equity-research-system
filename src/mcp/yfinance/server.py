"""yfinance MCP server for the equity research system.

Wraps Yahoo Finance via the `yfinance` Python lib. Six endpoints (per spec §9):
get_consensus_estimates, get_target_prices, get_recommendations, get_calendar,
get_holders, get_peer_comps. Endpoints land in subsequent TDD tasks.

ToS reality: Yahoo prohibits automated access for commercial use. Personal
research only; do NOT productize.

Failure-mode contract per spec §9.4: each endpoint returns one of:
- normal data dict
- {"ticker_not_found": True}
- {"available": False, "reason": "endpoint_dropped"}
- {"rate_limited": True, "retry_after": <seconds>}

No persistent cache in v1 (spec §9.3 calls for Postgres cache; deferred).
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
