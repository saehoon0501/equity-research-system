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

import yfinance as yf


def _is_ticker_unknown(ticker_obj) -> bool:
    """yfinance returns empty/sparse info dict for nonexistent tickers."""
    try:
        info = ticker_obj.info
    except Exception:
        return True
    if not info or len(info) <= 1:
        return True
    # Yahoo sometimes returns a stub with only `trailingPegRatio` for unknown tickers.
    if info.get("regularMarketPrice") is None and info.get("symbol") is None:
        return True
    return False


@mcp.tool()
def get_consensus_estimates(ticker: str) -> dict:
    """Return forward EPS + revenue consensus estimates for `ticker`.

    Schema (per spec §9.1):
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
        - Unknown ticker: {"ticker_not_found": True}
    """
    t = yf.Ticker(ticker)
    if _is_ticker_unknown(t):
        return {"ticker_not_found": True}

    info = t.info or {}

    # yfinance does not surface std deviations on the consensus; leave None.
    revenue_estimate = info.get("revenueEstimate")
    fy_revenue_mean = (
        revenue_estimate.get("avg")
        if isinstance(revenue_estimate, dict)
        else revenue_estimate if isinstance(revenue_estimate, (int, float)) else None
    )

    # Coerce analyst_count to int if it comes back as float (e.g. NaN -> None)
    raw_analyst_count = info.get("numberOfAnalystOpinions")
    try:
        analyst_count = int(raw_analyst_count) if raw_analyst_count is not None else None
    except (ValueError, TypeError):
        analyst_count = None

    return {
        "fy_eps_mean": info.get("forwardEps"),
        "fy_eps_std": None,
        "fy_revenue_mean": fy_revenue_mean,
        "fy_revenue_std": None,
        "next_q_eps_mean": info.get("earningsQuarterlyGrowth"),
        "next_q_revenue_mean": info.get("revenueQuarterlyGrowth"),
        "analyst_count": analyst_count,
    }


if __name__ == "__main__":
    mcp.run()
