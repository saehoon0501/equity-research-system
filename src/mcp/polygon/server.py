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

Implementation note (Flow B v2 task 29 refactor): all 4 endpoints now ride
`list_snapshot_options_chain` — a single paginated call that returns the
entire chain with greeks/IV/volume/OI inline. This replaces the prior
per-contract `get_snapshot_option` + `get_aggs` loops that rate-limited
out on liquid tickers (SPY, QQQ).
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


def _safe_iter(generator, cap: int = 5000) -> list[Any]:
    """Materialize a polygon-api-client paginated iterator with a soft cap.

    Chain snapshots can run to ~3000 contracts for the most-liquid names;
    we cap at 5000 to bound runtime + memory.
    """
    out: list[Any] = []
    try:
        for i, item in enumerate(generator):
            if i >= cap:
                break
            out.append(item)
    except Exception:
        return out
    return out


class _TierInsufficient(Exception):
    """Raised when the operator's Polygon plan does not include the
    snapshot-chain endpoint. Distinct from a transient connectivity error so
    callers can surface an actionable upgrade message instead of a generic
    ticker_not_found.
    """


def _load_chain(client: RESTClient, sym: str) -> list[Any]:
    """Pull the full options-chain snapshot for `sym` in a single paginated
    call.

    Iteration is inlined here (rather than delegating to _safe_iter) because
    the polygon-api-client returns a lazy generator — the HTTP request fires
    on first iteration, so tier-insufficient and transport errors surface
    here, not at the call-site of list_snapshot_options_chain.

    Raises:
        _TierInsufficient: when Polygon returns NOT_AUTHORIZED — the snapshot
            options-chain endpoint requires the paid Options plan.
        RuntimeError: on any other transport-level failure (caller converts
            to {ticker_not_found: True, error_class: ...}).
    """
    cap = 5000
    out: list[Any] = []
    try:
        chain_iter = client.list_snapshot_options_chain(
            underlying_asset=sym,
            params={"limit": 250},  # max page size; pagination is automatic
        )
        for i, item in enumerate(chain_iter):
            if i >= cap:
                break
            out.append(item)
        return out
    except Exception as e:
        msg = str(e).lower()
        if "not_authorized" in msg or "upgrade your plan" in msg or "entitled" in msg:
            raise _TierInsufficient(str(e)[:300]) from e
        raise RuntimeError(str(e)[:300]) from e


def _tier_insufficient_payload(extra: dict | None = None) -> dict:
    payload = {
        "ticker_not_found": True,
        "error_class": "polygon_tier_insufficient",
        "upgrade_url": "https://polygon.io/pricing",
        "note": "Snapshot options chain requires the Options paid tier ($29/mo Starter).",
    }
    if extra:
        payload.update(extra)
    return payload


def _extract_contract_row(snap: Any) -> dict | None:
    """Extract canonical contract row from an OptionContractSnapshot.

    Returns None if `details` is missing (snapshot too sparse to use).
    """
    details = getattr(snap, "details", None)
    if details is None:
        return None
    strike = getattr(details, "strike_price", None)
    expiry = getattr(details, "expiration_date", None)
    ctype = getattr(details, "contract_type", None)
    if strike is None or expiry is None or ctype is None:
        return None

    day = getattr(snap, "day", None)
    greeks = getattr(snap, "greeks", None)
    iv = getattr(snap, "implied_volatility", None)
    oi = getattr(snap, "open_interest", None)

    vol_raw = getattr(day, "volume", None) if day is not None else None

    return {
        "ticker": getattr(details, "ticker", None),
        "strike": float(strike),
        "expiry": str(expiry),
        "type": str(ctype).lower(),
        "open_interest": int(oi) if oi is not None else None,
        "volume": int(vol_raw) if vol_raw is not None else None,
        "iv": float(iv) if iv is not None else None,
        "delta": float(getattr(greeks, "delta", 0.0)) if greeks and getattr(greeks, "delta", None) is not None else None,
        "gamma": float(getattr(greeks, "gamma", 0.0)) if greeks and getattr(greeks, "gamma", None) is not None else None,
        "theta": float(getattr(greeks, "theta", 0.0)) if greeks and getattr(greeks, "theta", None) is not None else None,
        "vega": float(getattr(greeks, "vega", 0.0)) if greeks and getattr(greeks, "vega", None) is not None else None,
    }


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

    If `expiry` is None, returns the nearest 4 forward expirations.
    """
    try:
        client = _client()
    except Exception as e:
        return {"ticker_not_found": True, "error_class": type(e).__name__}

    if _is_ticker_unknown(ticker, client):
        return {"ticker_not_found": True}

    sym = ticker.upper()
    try:
        snapshots = _load_chain(client, sym)
    except _TierInsufficient:
        return _tier_insufficient_payload()
    except RuntimeError as e:
        return {"ticker_not_found": True, "error_class": "snapshot_chain_error", "detail": str(e)}
    if not snapshots:
        return {"ticker_not_found": True}

    rows: list[dict] = []
    for snap in snapshots:
        row = _extract_contract_row(snap)
        if row is None:
            continue
        rows.append(row)

    if not rows:
        return {"ticker_not_found": True}

    # Filter to target expirations.
    today = datetime.now(timezone.utc).date()
    forward_expiries = sorted(
        {r["expiry"] for r in rows if r["expiry"] >= str(today)}
    )
    if expiry is not None:
        target_expiries = {expiry} if expiry in forward_expiries else set()
    else:
        target_expiries = set(forward_expiries[:4])

    out_contracts = [
        {k: v for k, v in r.items() if k != "ticker"}
        for r in rows
        if r["expiry"] in target_expiries
    ]

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

    try:
        snapshots = _load_chain(client, sym)
    except _TierInsufficient:
        return _tier_insufficient_payload()
    except RuntimeError as e:
        return {"ticker_not_found": True, "error_class": "snapshot_chain_error", "detail": str(e)}
    if not snapshots:
        return {"ticker_not_found": True}

    # Calls only — ATM IV from calls is cheaper + monotone in moneyness.
    by_expiry: dict[str, list[dict]] = defaultdict(list)
    for snap in snapshots:
        row = _extract_contract_row(snap)
        if row is None or row["type"] != "call":
            continue
        by_expiry[row["expiry"]].append(row)

    today = datetime.now(timezone.utc).date()
    term: list[dict] = []
    front_iv: float | None = None
    back_iv: float | None = None

    for exp_str in sorted(by_expiry.keys()):
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (exp_date - today).days
        if dte < 0:
            continue

        calls = by_expiry[exp_str]
        strikes = [c["strike"] for c in calls if c["strike"] is not None]
        atm_strike = _atm_strike(strikes, spot)
        if atm_strike is None:
            continue
        atm_call = next((c for c in calls if c["strike"] == atm_strike), None)
        atm_iv = atm_call["iv"] if atm_call else None

        term.append({"days_to_expiry": dte, "atm_iv": atm_iv})

        if front_iv is None and atm_iv is not None:
            front_iv = atm_iv
        if back_iv is None and atm_iv is not None and 75 <= dte <= 120:
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
    """Return aggregated put vs call volume.

    Schema:
        {
            "ticker": str,
            "lookback_days": int,
            "total_put_vol": int,
            "total_call_vol": int,
            "p_c_ratio": float | None,
            "retrieved_at": str,
        }

    v1 implementation: returns today's chain-snapshot put/call volume sum.
    `lookback_days` is retained for API forward-compatibility; multi-day
    historical P/C will be added when polygon-api-client exposes a
    chain-aggregate-history endpoint (currently requires per-contract aggs,
    which rate-limits out on liquid tickers — see task 25 commit message).
    Single-day snapshot P/C is the standard indicator anyway (Pan-Poteshman 2006
    use daily-resolution data).
    """
    try:
        client = _client()
    except Exception as e:
        return {"ticker_not_found": True, "error_class": type(e).__name__}

    if _is_ticker_unknown(ticker, client):
        return {"ticker_not_found": True}

    sym = ticker.upper()
    try:
        snapshots = _load_chain(client, sym)
    except _TierInsufficient:
        return _tier_insufficient_payload({"lookback_days": lookback_days})
    except RuntimeError as e:
        return {"ticker_not_found": True, "error_class": "snapshot_chain_error", "detail": str(e)}
    if not snapshots:
        return {"ticker_not_found": True}

    total_put = 0
    total_call = 0
    for snap in snapshots:
        row = _extract_contract_row(snap)
        if row is None or row["volume"] is None:
            continue
        if row["type"] == "put":
            total_put += row["volume"]
        elif row["type"] == "call":
            total_call += row["volume"]

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

    Tier-1 filter (cheap, from chain snapshot):
      - volume / open_interest > 1.0

    Tier-2 enrichment (capped, per-contract aggs for the top 20 vol/oi hits):
      - today's volume vs `lookback_days`-day rolling average; flagged when > 3x.

    The Tier-2 cap keeps total API calls bounded for liquid tickers; if you
    need full coverage, increase the per-pull cap and budget for rate-limit
    waits.
    """
    try:
        client = _client()
    except Exception as e:
        return {"ticker_not_found": True, "error_class": type(e).__name__}

    if _is_ticker_unknown(ticker, client):
        return {"ticker_not_found": True}

    sym = ticker.upper()
    try:
        snapshots = _load_chain(client, sym)
    except _TierInsufficient:
        return _tier_insufficient_payload()
    except RuntimeError as e:
        return {"ticker_not_found": True, "error_class": "snapshot_chain_error", "detail": str(e)}
    if not snapshots:
        return {"ticker_not_found": True}

    # Tier-1: vol/oi from snapshot.
    candidates: list[dict] = []
    for snap in snapshots:
        row = _extract_contract_row(snap)
        if row is None:
            continue
        vol = row["volume"]
        oi = row["open_interest"]
        if vol is None or vol <= 0:
            continue
        vol_oi_ratio = (vol / oi) if (oi and oi > 0) else None
        if vol_oi_ratio is not None and vol_oi_ratio > 1.0:
            candidates.append({
                "ticker": row["ticker"],
                "strike": row["strike"],
                "expiry": row["expiry"],
                "type": row["type"],
                "vol": vol,
                "oi": oi if oi is not None else 0,
                "vol_oi_ratio": vol_oi_ratio,
            })

    # Sort by vol_oi_ratio desc; cap Tier-2 enrichment at 20 (rate-limit guard).
    candidates.sort(key=lambda c: c["vol_oi_ratio"] or 0.0, reverse=True)
    enriched = candidates[:20]

    # Tier-2: 90-day avg volume for the top-20 unusual hits.
    today = datetime.now(timezone.utc).date()
    ninety_start = today - timedelta(days=max(lookback_days, 90))
    for row in enriched:
        opt_ticker = row.pop("ticker", None)
        avg_vol: float | None = None
        if opt_ticker:
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

        row["vol_vs_avg_x"] = (
            (row["vol"] / avg_vol) if (avg_vol is not None and avg_vol > 0) else None
        )

    # Strip the helper "ticker" field from remaining (non-enriched-but-passed) rows;
    # also flatten the final shape per spec.
    for row in candidates[20:]:
        row.pop("ticker", None)
        row["vol_vs_avg_x"] = None

    unusual = enriched + candidates[20:]

    return {
        "ticker": sym,
        "unusual_contracts": unusual,
        "retrieved_at": _now_iso(),
    }


@mcp.tool()
def get_short_interest(ticker: str, limit: int = 1) -> dict:
    """Return most-recent short-interest record for `ticker`.

    Wraps Polygon /stocks/v1/short-interest. FINRA reports settle bi-weekly;
    the endpoint returns one record per settlement_date.

    Schema (success):
        {
            "ticker": str,
            "short_interest": int,
            "days_to_cover": float,
            "settlement_date": str,        # YYYY-MM-DD
            "avg_daily_volume": int,
            "retrieved_at": str,            # ISO 8601 UTC
            "source": "polygon_short_interest_v1",
        }

    Failure modes (same contract as sibling polygon tools):
        - Unknown ticker / no SI record  -> {"ticker_not_found": True}
        - Tier insufficient              -> _tier_insufficient_payload()
        - Auth / transport error         -> {"ticker_not_found": True, "error_class": "<cls>"}

    Per v0.3 flow-overlay plan: crowding-warning fail-safe is to treat
    any non-success response as "no warning" (asymmetric signal must not
    false-fire on missing data).
    """
    try:
        client = _client()
    except Exception as e:
        return {"ticker_not_found": True, "error_class": type(e).__name__}

    if _is_ticker_unknown(ticker, client):
        return {"ticker_not_found": True}

    sym = ticker.upper()
    list_method = getattr(client, "list_short_interest", None)
    if list_method is None:
        return {
            "ticker_not_found": True,
            "error_class": "polygon_sdk_missing_short_interest",
            "note": "polygon-api-client SDK does not expose list_short_interest; upgrade to a version that includes /stocks/v1/short-interest support.",
        }

    try:
        records_iter = list_method(ticker=sym, limit=max(1, int(limit)))
        records = _safe_iter(records_iter, cap=max(1, int(limit)))
    except Exception as e:
        msg = str(e).lower()
        if "not_authorized" in msg or "upgrade your plan" in msg or "entitled" in msg:
            return _tier_insufficient_payload({"note": "Short-interest endpoint requires a Polygon Stocks plan tier that includes /stocks/v1/short-interest."})
        return {"ticker_not_found": True, "error_class": "short_interest_transport_error", "detail": str(e)[:300]}

    if not records:
        return {"ticker_not_found": True}

    most_recent = records[0]
    short_interest = getattr(most_recent, "short_interest", None)
    days_to_cover = getattr(most_recent, "days_to_cover", None)
    settlement_date = getattr(most_recent, "settlement_date", None)
    avg_daily_volume = getattr(most_recent, "avg_daily_volume", None)

    if short_interest is None or days_to_cover is None or settlement_date is None:
        return {"ticker_not_found": True, "error_class": "short_interest_malformed_record"}

    return {
        "ticker": sym,
        "short_interest": int(short_interest),
        "days_to_cover": float(days_to_cover),
        "settlement_date": str(settlement_date),
        "avg_daily_volume": int(avg_daily_volume) if avg_daily_volume is not None else None,
        "retrieved_at": _now_iso(),
        "source": "polygon_short_interest_v1",
    }


if __name__ == "__main__":
    mcp.run()
