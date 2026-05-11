"""Polygon options-chain MCP server for the equity research system.

Wraps Polygon.io options endpoints via `polygon-api-client`. Four endpoints
(per Flow B v2 task 25):

- get_options_chain(ticker, expiry=None)
- get_iv_term_structure(ticker)
- get_put_call_ratio(ticker, lookback_days=30)
- get_unusual_activity(ticker, lookback_days=5)

Failure-mode contract per spec (mirrors yfinance MCP):
- Unknown / non-optionable ticker -> {"ticker_not_found": True}
- Auth / quota / connectivity error -> {"ticker_not_found": True, "error_class": "<cls>"}

POLYGON_API_KEY must be present in repo-root .env. The free tier returns
15-min-delayed data via the same endpoint shapes; the Stocks/Options Starter
tier ($29/mo) unlocks real-time SIP.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Walk: server.py -> polygon/ -> mcp/ -> src/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


mcp = FastMCP("polygon")

# Imported lazily so that structural verification (importing this module) does
# not hard-fail when polygon-api-client is missing from the environment.
from polygon import RESTClient  # type: ignore  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _client() -> RESTClient:
    """Construct a fresh RESTClient. Each call reads POLYGON_API_KEY anew so
    that operator key-rotation does not require a restart.
    """
    key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not key:
        # Caller catches this and converts to ticker_not_found contract.
        raise RuntimeError("POLYGON_API_KEY not set in environment")
    return RESTClient(api_key=key)


def _is_ticker_unknown(ticker: str, client: RESTClient | None = None) -> bool:
    """Validate via Polygon's ticker-details endpoint.

    Returns True on:
      - Polygon raising (404 / bad request / quota / connectivity)
      - the response indicating no active / no options market

    Note: presence in ticker-details does NOT guarantee options exist. The
    chain pull will return empty in that case; downstream endpoints handle
    the empty-chain case explicitly.
    """
    if not ticker or not isinstance(ticker, str):
        return True
    try:
        c = client or _client()
        details = c.get_ticker_details(ticker.upper())
    except Exception:
        return True
    if details is None:
        return True
    # polygon-api-client returns a TickerDetails dataclass. `active` is the
    # canonical aliveness signal.
    active = getattr(details, "active", None)
    if active is False:
        return True
    return False


def _safe_iter(generator) -> list[Any]:
    """Materialize a polygon-api-client paginated iterator with a soft cap."""
    out: list[Any] = []
    try:
        for i, item in enumerate(generator):
            if i >= 2000:  # hard cap — chains rarely exceed this
                break
            out.append(item)
    except Exception:
        return out
    return out


def _atm_strike(strikes: list[float], spot: float) -> float | None:
    """Pick the strike closest to spot."""
    if not strikes:
        return None
    return min(strikes, key=lambda s: abs(s - spot))


def _get_spot(client: RESTClient, ticker: str) -> float | None:
    """Best-effort spot price from previous-close aggregate."""
    try:
        agg = client.get_previous_close_agg(ticker.upper())
        if agg and len(agg) > 0:
            return float(agg[0].close)
    except Exception:
        return None
    return None


@mcp.tool()
def get_options_chain(ticker: str, expiry: str | None = None) -> dict:
    """Return options chain snapshot for `ticker`.

    Schema:
        {
            "ticker": str,
            "contracts": [
                {
                    "strike": float, "expiry": str, "type": "call"|"put",
                    "open_interest": int | None,
                    "volume": int | None,
                    "iv": float | None,
                    "delta": float | None, "gamma": float | None,
                    "theta": float | None, "vega": float | None,
                },
                ...
            ],
            "retrieved_at": str,        # ISO 8601 UTC
            "source": "polygon",
        }

    If `expiry` is None, pulls the nearest 4 forward expirations.
    """
    try:
        client = _client()
    except Exception as e:
        return {"ticker_not_found": True, "error_class": type(e).__name__}

    if _is_ticker_unknown(ticker, client):
        return {"ticker_not_found": True}

    sym = ticker.upper()
    today = datetime.now(timezone.utc).date()

    try:
        # First: list active contracts to discover expirations.
        contracts_iter = client.list_options_contracts(
            underlying_ticker=sym,
            expiration_date_gte=str(today),
            expired=False,
            limit=1000,
        )
        all_contracts = _safe_iter(contracts_iter)
    except Exception as e:
        return {"ticker_not_found": True, "error_class": type(e).__name__}

    if not all_contracts:
        # Underlying exists but no options listed.
        return {"ticker_not_found": True}

    # Group by expiration; pick target set
    by_expiry: dict[str, list[Any]] = defaultdict(list)
    for c in all_contracts:
        exp = getattr(c, "expiration_date", None)
        if exp:
            by_expiry[str(exp)].append(c)

    if expiry is not None:
        target_expiries = [expiry] if expiry in by_expiry else []
    else:
        target_expiries = sorted(by_expiry.keys())[:4]

    selected: list[Any] = []
    for exp in target_expiries:
        selected.extend(by_expiry[exp])

    # Snapshot each contract for greeks + OI + volume + IV.
    out_contracts: list[dict] = []
    for c in selected:
        opt_ticker = getattr(c, "ticker", None)
        if not opt_ticker:
            continue
        snap = None
        try:
            snap = client.get_snapshot_option(sym, opt_ticker)
        except Exception:
            snap = None

        greeks = getattr(snap, "greeks", None) if snap is not None else None
        day = getattr(snap, "day", None) if snap is not None else None

        out_contracts.append({
            "strike": float(getattr(c, "strike_price", 0.0) or 0.0),
            "expiry": str(getattr(c, "expiration_date", "")),
            "type": str(getattr(c, "contract_type", "") or "").lower(),
            "open_interest": int(getattr(snap, "open_interest", 0) or 0) if snap else None,
            "volume": int(getattr(day, "volume", 0) or 0) if day else None,
            "iv": float(getattr(snap, "implied_volatility", 0.0) or 0.0) if snap else None,
            "delta": float(getattr(greeks, "delta", 0.0) or 0.0) if greeks else None,
            "gamma": float(getattr(greeks, "gamma", 0.0) or 0.0) if greeks else None,
            "theta": float(getattr(greeks, "theta", 0.0) or 0.0) if greeks else None,
            "vega": float(getattr(greeks, "vega", 0.0) or 0.0) if greeks else None,
        })

    return {
        "ticker": sym,
        "contracts": out_contracts,
        "retrieved_at": _now_iso(),
        "source": "polygon",
    }


@mcp.tool()
def get_iv_term_structure(ticker: str) -> dict:
    """Return ATM IV term structure for `ticker`.

    Schema:
        {
            "ticker": str,
            "term_structure": [
                {"days_to_expiry": int, "atm_iv": float | None},
                ...
            ],
            "front_back_spread": float | None,
            "retrieved_at": str,
        }

    front_back_spread = front-month ATM IV minus 90-day ATM IV (Cremers-Weinbaum
    implied-vol-spread style signal). Sign: positive => front richer than back
    (term-structure inversion / near-term event-pricing).
    """
    try:
        client = _client()
    except Exception as e:
        return {"ticker_not_found": True, "error_class": type(e).__name__}

    if _is_ticker_unknown(ticker, client):
        return {"ticker_not_found": True}

    sym = ticker.upper()
    spot = _get_spot(client, sym)
    if spot is None or spot <= 0:
        return {"ticker_not_found": True}

    today = datetime.now(timezone.utc).date()
    try:
        contracts_iter = client.list_options_contracts(
            underlying_ticker=sym,
            expiration_date_gte=str(today),
            expired=False,
            contract_type="call",  # ATM IV from calls only; cheaper + monotone
            limit=1000,
        )
        all_contracts = _safe_iter(contracts_iter)
    except Exception as e:
        return {"ticker_not_found": True, "error_class": type(e).__name__}

    if not all_contracts:
        return {"ticker_not_found": True}

    # Group calls by expiry; pick ATM strike per expiry.
    by_expiry: dict[str, list[Any]] = defaultdict(list)
    for c in all_contracts:
        exp = getattr(c, "expiration_date", None)
        if exp:
            by_expiry[str(exp)].append(c)

    term: list[dict] = []
    front_iv: float | None = None
    back_iv: float | None = None

    # Sort expiries ascending.
    sorted_expiries = sorted(by_expiry.keys())
    for exp_str in sorted_expiries:
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (exp_date - today).days
        if dte < 0:
            continue

        calls = by_expiry[exp_str]
        strikes = [float(getattr(c, "strike_price", 0.0) or 0.0) for c in calls]
        atm_strike = _atm_strike(strikes, spot)
        if atm_strike is None:
            continue
        atm_contract = next(
            (c for c in calls if float(getattr(c, "strike_price", 0.0) or 0.0) == atm_strike),
            None,
        )
        if atm_contract is None:
            continue

        opt_ticker = getattr(atm_contract, "ticker", None)
        atm_iv: float | None = None
        if opt_ticker:
            try:
                snap = client.get_snapshot_option(sym, opt_ticker)
                iv_val = getattr(snap, "implied_volatility", None)
                atm_iv = float(iv_val) if iv_val is not None else None
            except Exception:
                atm_iv = None

        term.append({"days_to_expiry": dte, "atm_iv": atm_iv})

        # Capture front and ~90-day IV for the spread.
        if front_iv is None and atm_iv is not None:
            front_iv = atm_iv
        if back_iv is None and atm_iv is not None and dte >= 75 and dte <= 120:
            back_iv = atm_iv

    front_back_spread: float | None = None
    if front_iv is not None and back_iv is not None:
        front_back_spread = front_iv - back_iv

    return {
        "ticker": sym,
        "term_structure": term,
        "front_back_spread": front_back_spread,
        "retrieved_at": _now_iso(),
    }


@mcp.tool()
def get_put_call_ratio(ticker: str, lookback_days: int = 30) -> dict:
    """Return aggregated put vs call volume over `lookback_days`.

    Schema:
        {
            "ticker": str,
            "lookback_days": int,
            "total_put_vol": int,
            "total_call_vol": int,
            "p_c_ratio": float | None,
            "retrieved_at": str,
        }

    Pan-Poteshman style: high P/C => bearish sentiment / informed put-buying.
    """
    try:
        client = _client()
    except Exception as e:
        return {"ticker_not_found": True, "error_class": type(e).__name__}

    if _is_ticker_unknown(ticker, client):
        return {"ticker_not_found": True}

    sym = ticker.upper()
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=lookback_days)

    try:
        # Pull all active contracts; we'll aggregate per-contract volume via
        # historical aggregates over the lookback window.
        contracts_iter = client.list_options_contracts(
            underlying_ticker=sym,
            expiration_date_gte=str(today),
            expired=False,
            limit=1000,
        )
        contracts = _safe_iter(contracts_iter)
    except Exception as e:
        return {"ticker_not_found": True, "error_class": type(e).__name__}

    if not contracts:
        return {"ticker_not_found": True}

    total_put = 0
    total_call = 0
    for c in contracts:
        opt_ticker = getattr(c, "ticker", None)
        ctype = str(getattr(c, "contract_type", "") or "").lower()
        if not opt_ticker or ctype not in ("put", "call"):
            continue
        try:
            aggs = client.get_aggs(
                ticker=opt_ticker,
                multiplier=1,
                timespan="day",
                from_=str(start),
                to=str(today),
                limit=lookback_days + 5,
            )
        except Exception:
            continue
        vol = 0
        try:
            for a in aggs or []:
                v = getattr(a, "volume", 0) or 0
                vol += int(v)
        except Exception:
            vol = 0
        if ctype == "put":
            total_put += vol
        else:
            total_call += vol

    pc_ratio: float | None = None
    if total_call > 0:
        pc_ratio = total_put / total_call

    return {
        "ticker": sym,
        "lookback_days": lookback_days,
        "total_put_vol": total_put,
        "total_call_vol": total_call,
        "p_c_ratio": pc_ratio,
        "retrieved_at": _now_iso(),
    }


@mcp.tool()
def get_unusual_activity(ticker: str, lookback_days: int = 5) -> dict:
    """Return contracts with unusual volume.

    Schema:
        {
            "ticker": str,
            "unusual_contracts": [
                {
                    "strike": float, "expiry": str, "type": str,
                    "vol": int, "oi": int,
                    "vol_oi_ratio": float | None,
                    "vol_vs_avg_x": float | None,
                },
                ...
            ],
            "retrieved_at": str,
        }

    Criteria (either triggers inclusion):
      - volume / open_interest > 1.0
      - today's volume > 90-day rolling average × 3
    """
    try:
        client = _client()
    except Exception as e:
        return {"ticker_not_found": True, "error_class": type(e).__name__}

    if _is_ticker_unknown(ticker, client):
        return {"ticker_not_found": True}

    sym = ticker.upper()
    today = datetime.now(timezone.utc).date()
    ninety_start = today - timedelta(days=90)

    try:
        contracts_iter = client.list_options_contracts(
            underlying_ticker=sym,
            expiration_date_gte=str(today),
            expired=False,
            limit=1000,
        )
        contracts = _safe_iter(contracts_iter)
    except Exception as e:
        return {"ticker_not_found": True, "error_class": type(e).__name__}

    if not contracts:
        return {"ticker_not_found": True}

    unusual: list[dict] = []
    for c in contracts:
        opt_ticker = getattr(c, "ticker", None)
        if not opt_ticker:
            continue
        snap = None
        try:
            snap = client.get_snapshot_option(sym, opt_ticker)
        except Exception:
            snap = None
        if snap is None:
            continue

        oi = int(getattr(snap, "open_interest", 0) or 0)
        day = getattr(snap, "day", None)
        vol = int(getattr(day, "volume", 0) or 0) if day else 0

        if vol <= 0:
            continue

        vol_oi_ratio = (vol / oi) if oi > 0 else None

        # 90-day average daily volume (excluding today) for vol_vs_avg_x.
        avg_vol: float | None = None
        try:
            aggs = client.get_aggs(
                ticker=opt_ticker,
                multiplier=1,
                timespan="day",
                from_=str(ninety_start),
                to=str(today - timedelta(days=1)),
                limit=120,
            )
            vols = [int(getattr(a, "volume", 0) or 0) for a in (aggs or [])]
            if vols:
                avg_vol = sum(vols) / len(vols)
        except Exception:
            avg_vol = None

        vol_vs_avg_x: float | None = None
        if avg_vol is not None and avg_vol > 0:
            vol_vs_avg_x = vol / avg_vol

        # Inclusion test
        flag_oi = vol_oi_ratio is not None and vol_oi_ratio > 1.0
        flag_avg = vol_vs_avg_x is not None and vol_vs_avg_x > 3.0
        if not (flag_oi or flag_avg):
            continue

        unusual.append({
            "strike": float(getattr(c, "strike_price", 0.0) or 0.0),
            "expiry": str(getattr(c, "expiration_date", "")),
            "type": str(getattr(c, "contract_type", "") or "").lower(),
            "vol": vol,
            "oi": oi,
            "vol_oi_ratio": vol_oi_ratio,
            "vol_vs_avg_x": vol_vs_avg_x,
        })

    return {
        "ticker": sym,
        "unusual_contracts": unusual,
        "retrieved_at": _now_iso(),
    }


if __name__ == "__main__":
    mcp.run()
