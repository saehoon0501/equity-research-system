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

import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Walk: server.py → yfinance/ → mcp/ → src/ → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


mcp = FastMCP("yfinance")

import yfinance as yf

import psycopg
from psycopg.types.json import Jsonb

# ---------------------------------------------------------------------------
# Postgres write-through cache (Migration 029)
# ---------------------------------------------------------------------------
# Per spec §9.3: each yfinance endpoint checks yfinance_cache before calling
# Yahoo. Fresh rows (now - fetched_at < ttl_seconds) are returned with a
# `_cache_hit:True` flag added to the returned dict only (not persisted).
# ticker_not_found sentinels are never cached.
TTL_SECONDS = {
    "consensus_estimates": 21600,   # 6h
    "target_prices": 21600,         # 6h
    "recommendations": 21600,       # 6h
    "calendar": 86400,              # 24h
    "holders": 604800,              # 7d
    "peer_comps": 604800,           # 7d
}


def _dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@localhost:{os.environ.get('POSTGRES_PORT','5432')}/{os.environ['POSTGRES_DB']}"
    )


@contextmanager
def _conn():
    with psycopg.connect(_dsn(), autocommit=True) as conn:
        yield conn


def _cache_read(endpoint: str, ticker: str):
    """Return cached payload if fresh, else None. Never raises."""
    ttl = TTL_SECONDS[endpoint]
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT payload, EXTRACT(EPOCH FROM (NOW() - fetched_at)) AS age "
                "FROM yfinance_cache WHERE endpoint=%s AND ticker=%s",
                (endpoint, ticker.upper()),
            ).fetchone()
            if row and row[1] < ttl:
                return row[0]
    except Exception:
        return None
    return None


def _cache_write(endpoint: str, ticker: str, payload) -> None:
    """Persist payload. Skips ticker_not_found and any falsy payload. Never raises."""
    if not payload:
        return
    # ticker_not_found guard: only applies when payload is a dict.
    if isinstance(payload, dict) and payload.get("ticker_not_found"):
        return
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO yfinance_cache (endpoint, ticker, payload, ttl_seconds) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (endpoint, ticker) DO UPDATE "
                "SET payload = EXCLUDED.payload, fetched_at = NOW(), ttl_seconds = EXCLUDED.ttl_seconds",
                (endpoint, ticker.upper(), Jsonb(payload), TTL_SECONDS[endpoint]),
            )
    except Exception:
        pass  # cache failure must never break the call


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
    cached = _cache_read("consensus_estimates", ticker)
    if cached is not None:
        cached["_cache_hit"] = True
        return cached

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

    result = {
        "fy_eps_mean": info.get("forwardEps"),
        "fy_eps_std": None,
        "fy_revenue_mean": fy_revenue_mean,
        "fy_revenue_std": None,
        "next_q_eps_mean": info.get("earningsQuarterlyGrowth"),
        "next_q_revenue_mean": info.get("revenueQuarterlyGrowth"),
        "analyst_count": analyst_count,
    }
    _cache_write("consensus_estimates", ticker, result)
    return result


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
    cached = _cache_read("target_prices", ticker)
    if cached is not None:
        cached["_cache_hit"] = True
        return cached

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

    result = {
        "target_high": info.get("targetHighPrice"),
        "target_low": info.get("targetLowPrice"),
        "target_mean": info.get("targetMeanPrice"),
        "target_median": info.get("targetMedianPrice"),
        "number_of_analyst_opinions": count,
        "recommendation_mean": info.get("recommendationMean"),
        "recommendation_key": info.get("recommendationKey"),
    }
    _cache_write("target_prices", ticker, result)
    return result


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

    Note: cache key omits `days` window; the cached payload is the full
    upgrades/downgrades list as last fetched. The window filter is applied
    after the cache lookup so different `days` callers share the cached
    underlying data.
    """
    cached = _cache_read("recommendations", ticker)
    if cached is not None:
        # Cached payload is the full unfiltered list of events. Re-apply window.
        if isinstance(cached, list):
            cutoff_cached = datetime.now(timezone.utc) - timedelta(days=days)
            filtered = []
            for item in cached:
                date_str = item.get("date") if isinstance(item, dict) else None
                if not date_str:
                    filtered.append(item)
                    continue
                try:
                    dt = datetime.fromisoformat(date_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt >= cutoff_cached:
                        filtered.append(item)
                except Exception:
                    filtered.append(item)
            return filtered

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
    all_items: list[dict] = []
    for idx, row in rec_df.iterrows():
        try:
            # idx is a pandas Timestamp (DatetimeIndex named GradeDate)
            row_date = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
            if hasattr(row_date, "tzinfo") and row_date.tzinfo is None:
                row_date = row_date.replace(tzinfo=timezone.utc)
            event = {
                "firm": str(row.get("Firm", "") or ""),
                "to_grade": str(row.get("ToGrade", row.get("To Grade", "")) or ""),
                "from_grade": str(row.get("FromGrade", row.get("From Grade", "")) or ""),
                "action": str(row.get("Action", "") or ""),
                "date": row_date.isoformat() if hasattr(row_date, "isoformat") else str(row_date),
            }
            all_items.append(event)
            if hasattr(row_date, "__lt__") and row_date < cutoff:
                continue
            items.append(event)
        except Exception:
            continue
    # Cache the full pre-window list so callers with different `days` share data.
    _cache_write("recommendations", ticker, all_items)
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
    cached = _cache_read("calendar", ticker)
    if cached is not None:
        cached["_cache_hit"] = True
        return cached

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
        result = {
            "next_earnings_date": _coerce_date(next_earnings),
            "ex_dividend_date": _coerce_date(cal.get("Ex-Dividend Date")),
            "dividend_date": _coerce_date(cal.get("Dividend Date")),
        }
        _cache_write("calendar", ticker, result)
        return result

    # Fall back to info-derived
    info = t.info or {}
    result = {
        "next_earnings_date": _coerce_date(info.get("earningsTimestamp")),
        "ex_dividend_date": _coerce_date(info.get("exDividendDate")),
        "dividend_date": _coerce_date(info.get("dividendDate")),
    }
    _cache_write("calendar", ticker, result)
    return result


@mcp.tool()
def get_holders(ticker: str) -> dict:
    """Return institutional + insider ownership snapshot for `ticker`.

    Schema per spec §9.1:
        {
            "institutional_holders": [
                {"holder": str, "shares": int, "pct_held": float, "value": float},
                ...
            ],
            "major_holders": {<key>: <value>, ...},
            "insider_holders": [...],
            "institutional_pct": float | None,
            "qoq_delta": float | None,
        }

    Failure modes:
        - Unknown ticker: {"ticker_not_found": True}
    """
    cached = _cache_read("holders", ticker)
    if cached is not None:
        cached["_cache_hit"] = True
        return cached

    t = yf.Ticker(ticker)
    if _is_ticker_unknown(t):
        return {"ticker_not_found": True}

    def _df_to_records(df) -> list[dict]:
        if df is None or (hasattr(df, "empty") and df.empty):
            return []
        try:
            return df.to_dict(orient="records")
        except Exception:
            return []

    # institutional_holders columns: Date Reported, Holder, pctHeld, Shares, Value, pctChange
    inst_raw = _df_to_records(getattr(t, "institutional_holders", None))
    inst = [
        {
            "holder": str(r.get("Holder", "") or ""),
            "shares": int(r["Shares"]) if r.get("Shares") is not None else None,
            "pct_held": float(r["pctHeld"]) if r.get("pctHeld") is not None else None,
            "value": float(r["Value"]) if r.get("Value") is not None else None,
        }
        for r in inst_raw
    ]

    # insider_purchases is available; insider_holders is None in yfinance 0.2.66
    insiders = _df_to_records(getattr(t, "insider_purchases", None))

    # major_holders: DataFrame with Breakdown index and Value column
    major: dict = {}
    try:
        mh = t.major_holders
        if mh is not None and hasattr(mh, "empty") and not mh.empty:
            if "Breakdown" in mh.columns and "Value" in mh.columns:
                # Breakdown + Value columns (some yfinance versions)
                for _, row in mh.iterrows():
                    major[str(row["Breakdown"])] = row["Value"]
            elif "Value" in mh.columns:
                # Index is the label, Value column holds the number
                for label, row in mh.iterrows():
                    major[str(label)] = row["Value"]
            else:
                # Two-column fallback: first col = value, second col = label
                for _, row in mh.iterrows():
                    vals = list(row.values)
                    if len(vals) >= 2:
                        major[str(vals[1])] = vals[0]
    except Exception:
        pass

    info = t.info or {}
    result = {
        "institutional_holders": inst,
        "major_holders": major,
        "insider_holders": insiders,
        "institutional_pct": info.get("heldPercentInstitutions"),
        "qoq_delta": None,  # not directly available; would compute from cross-quarter snapshots
    }
    _cache_write("holders", ticker, result)
    return result


@mcp.tool()
def get_peer_comps(ticker: str, max_peers: int = 5) -> list[dict] | dict:
    """Return peer tickers + key valuation multiples for `ticker`.

    yfinance does NOT expose a first-class peer-discovery API in 0.2.x.
    v1 returns an empty list when no peers can be derived from yfinance
    surfaces. The CDD agent prompt instructs the agent to fall back to
    EDGAR SIC peers in that case.

    Schema per spec §9.1:
        [
            {
                "ticker": str,
                "pe": float | None,
                "ev_ebitda": float | None,
                "ev_sales": float | None,
                "market_cap": float | None,
            },
            ...
        ]

    Failure modes:
        - Unknown ticker: {"ticker_not_found": True}  (returns dict, not list)
        - No peers derivable: []
    """
    cached = _cache_read("peer_comps", ticker)
    if cached is not None and isinstance(cached, list):
        # Re-apply max_peers slice since cache may hold a longer list.
        return cached[:max_peers]

    t = yf.Ticker(ticker)
    if _is_ticker_unknown(t):
        return {"ticker_not_found": True}

    # yfinance has no first-class peer surface as of 0.2.66.
    # Probe a few candidate fields; fall back to empty list.
    peers: list[str] = []
    info = t.info or {}
    related = info.get("recommendationsList") or getattr(t, "related_tickers", None)
    if related and isinstance(related, (list, tuple)):
        # Filter out self and keep only string tickers
        peers = [p for p in related if isinstance(p, str) and p != ticker.upper()][:max_peers]

    if not peers:
        # Empty list — falsy; _cache_write guard skips. Return uncached.
        return []

    out: list[dict] = []
    for peer_ticker in peers:
        try:
            pt = yf.Ticker(peer_ticker)
            if _is_ticker_unknown(pt):
                continue
            pi = pt.info or {}
            out.append({
                "ticker": peer_ticker,
                "pe": pi.get("trailingPE"),
                "ev_ebitda": pi.get("enterpriseToEbitda"),
                "ev_sales": pi.get("enterpriseToRevenue"),
                "market_cap": pi.get("marketCap"),
            })
        except Exception:
            continue
    _cache_write("peer_comps", ticker, out)
    return out


if __name__ == "__main__":
    mcp.run()
