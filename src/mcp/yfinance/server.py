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

from datetime import datetime, timedelta, timezone
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


@mcp.tool()
def get_target_prices(ticker: str) -> dict:
    """Return sell-side target price summary for `ticker`.

    Schema per spec §9.1:
        {
            "target_high": float | None,
            "target_low": float | None,
            "target_mean": float | None,
            "target_median": float | None,
            "number_of_analyst_opinions": int | None,
            "recommendation_mean": float | None,
            "recommendation_key": str | None,
        }

    recommendation_mean is on a 1.0–5.0 scale (1=Strong Buy, 5=Strong Sell).
    recommendation_key is the human-readable form ("strong_buy", "buy",
    "hold", "underperform", "sell").

    Failure modes:
        - Unknown ticker: {"ticker_not_found": True}
    """
    t = yf.Ticker(ticker)
    if _is_ticker_unknown(t):
        return {"ticker_not_found": True}
    info = t.info or {}

    # Coerce analyst-count int (yfinance returns float/NaN sometimes; same pattern as Task 5)
    raw_count = info.get("numberOfAnalystOpinions")
    try:
        count = int(raw_count) if raw_count is not None else None
    except (TypeError, ValueError):
        count = None

    return {
        "target_high": info.get("targetHighPrice"),
        "target_low": info.get("targetLowPrice"),
        "target_mean": info.get("targetMeanPrice"),
        "target_median": info.get("targetMedianPrice"),
        "number_of_analyst_opinions": count,
        "recommendation_mean": info.get("recommendationMean"),
        "recommendation_key": info.get("recommendationKey"),
    }


@mcp.tool()
def get_recommendations(ticker: str, days: int = 90) -> list[dict] | dict:
    """Return analyst upgrade/downgrade events within the last `days` days.

    Schema per spec §9.1:
        [
            {
                "firm": str,
                "to_grade": str,
                "from_grade": str,
                "action": str,    # e.g. "up", "down", "init", "main", "reit"
                "date": str,      # ISO 8601
            },
            ...
        ]

    Failure modes:
        - Unknown ticker: {"ticker_not_found": True}  (returns dict, not list)
        - No recent activity within window: []
        - yfinance API drift / different schema: best-effort parse; return [] if unreadable

    Note: yfinance 0.2.66 exposes per-event upgrade/downgrade data via
    `Ticker.upgrades_downgrades` (DatetimeIndex=GradeDate, cols=Firm/ToGrade/
    FromGrade/Action). `Ticker.recommendations` in this version returns a
    period-level summary (strongBuy/buy/hold/sell/strongSell) which is
    incompatible with the per-event schema above.
    """
    t = yf.Ticker(ticker)
    if _is_ticker_unknown(t):
        return {"ticker_not_found": True}

    try:
        rec_df = t.upgrades_downgrades
    except Exception:
        return []
    if rec_df is None or (hasattr(rec_df, "empty") and rec_df.empty):
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items: list[dict] = []
    for idx, row in rec_df.iterrows():
        try:
            # idx is a pandas Timestamp (DatetimeIndex named GradeDate)
            row_date = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
            if hasattr(row_date, "tzinfo") and row_date.tzinfo is None:
                row_date = row_date.replace(tzinfo=timezone.utc)
            if hasattr(row_date, "__lt__") and row_date < cutoff:
                continue
            items.append({
                "firm": str(row.get("Firm", "") or ""),
                "to_grade": str(row.get("ToGrade", row.get("To Grade", "")) or ""),
                "from_grade": str(row.get("FromGrade", row.get("From Grade", "")) or ""),
                "action": str(row.get("Action", "") or ""),
                "date": row_date.isoformat() if hasattr(row_date, "isoformat") else str(row_date),
            })
        except Exception:
            continue
    return items


@mcp.tool()
def get_calendar(ticker: str) -> dict:
    """Return upcoming corporate calendar events for `ticker`.

    Schema per spec §9.1:
        {
            "next_earnings_date": str | None,  # ISO 8601 date
            "ex_dividend_date": str | None,
            "dividend_date": str | None,
        }

    Failure modes:
        - Unknown ticker: {"ticker_not_found": True}
    """
    t = yf.Ticker(ticker)
    if _is_ticker_unknown(t):
        return {"ticker_not_found": True}

    def _coerce_date(v) -> str | None:
        if v is None or (isinstance(v, float) and v != v):  # NaN check
            return None
        if isinstance(v, (int, float)):
            # Unix epoch seconds → ISO date
            try:
                return datetime.fromtimestamp(int(v), tz=timezone.utc).date().isoformat()
            except (ValueError, OSError):
                return None
        if hasattr(v, "isoformat"):
            try:
                return v.isoformat()
            except Exception:
                pass
        return str(v) if v else None

    cal = None
    try:
        cal = t.calendar
    except Exception:
        cal = None

    if isinstance(cal, dict) and cal:
        earnings_dates = cal.get("Earnings Date")
        # yfinance returns list of dates for earnings; take first
        next_earnings = earnings_dates[0] if isinstance(earnings_dates, list) and earnings_dates else earnings_dates
        return {
            "next_earnings_date": _coerce_date(next_earnings),
            "ex_dividend_date": _coerce_date(cal.get("Ex-Dividend Date")),
            "dividend_date": _coerce_date(cal.get("Dividend Date")),
        }

    # Fall back to info-derived
    info = t.info or {}
    return {
        "next_earnings_date": _coerce_date(info.get("earningsTimestamp")),
        "ex_dividend_date": _coerce_date(info.get("exDividendDate")),
        "dividend_date": _coerce_date(info.get("dividendDate")),
    }


if __name__ == "__main__":
    mcp.run()
