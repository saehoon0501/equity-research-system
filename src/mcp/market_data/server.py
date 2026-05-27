"""Market data MCP server for the equity research system.

Per BUILD_LOG.md decision 6, this is a tool consumed by Claude Code (memo
generation, daily monitor, entry/exit checks), not an orchestrator.

Three tools (provider-agnostic surface):

- get_prices(ticker, start, end, interval): historical OHLCV (default daily).
- get_news(ticker, since): recent news headlines.
- get_real_time_quote(ticker): last price + timestamp.

Provider dispatch (per operator decision 2026-04-30, lifting Polygon from
v0.5+ to v0.1 to satisfy the "high quality live market data" requirement):

    MARKET_DATA_PROVIDER=polygon  + POLYGON_API_KEY=...   -> Polygon SIP feeds
    MARKET_DATA_PROVIDER=yfinance (or unset)              -> yfinance fallback

The yfinance path is preserved as the offline / no-key fallback (mirrors the
"backtests and sample memo generation" use case from the original v0.1
commit). Switching providers is a one-env-var change with no MCP-tool-shape
diff.

`.env` is loaded via python-dotenv (mirroring postgres/edgar/contamination_check).
"""

from __future__ import annotations

import datetime as _dt
import importlib.util as _importlib_util
import logging
import math
import os
import sys as _sys
from pathlib import Path
from typing import Any

import yfinance as yf
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Walk: server.py → market_data/ → mcp/ → src/ → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")

_LOG = logging.getLogger(__name__)


def _load_evidence_persistence():
    """Load the shared fail-soft evidence_documents persistence helper.

    Loaded by file path (unique module name) so it works whether this server is
    launched as an MCP process or imported by file path in tests. Fail-soft: a
    load failure makes persistence a no-op.
    """
    if "_mcp_evidence_persistence" in _sys.modules:
        return _sys.modules["_mcp_evidence_persistence"]
    helper_path = Path(__file__).resolve().parents[1] / "evidence_persistence.py"
    try:
        spec = _importlib_util.spec_from_file_location(
            "_mcp_evidence_persistence", helper_path
        )
        module = _importlib_util.module_from_spec(spec)
        _sys.modules["_mcp_evidence_persistence"] = module
        spec.loader.exec_module(module)
        return module
    except Exception:  # pragma: no cover - persistence is best-effort
        return None

# Provider dispatch resolved at module import. Polygon requires both
# MARKET_DATA_PROVIDER=polygon AND POLYGON_API_KEY set; if the env var
# names polygon but the key is missing, we fall back to yfinance and
# log a warning so /system-health surfaces the misconfiguration.
_PROVIDER = (os.environ.get("MARKET_DATA_PROVIDER") or "yfinance").lower().strip()
_POLYGON_KEY = (os.environ.get("POLYGON_API_KEY") or "").strip()
_USE_POLYGON = _PROVIDER == "polygon" and bool(_POLYGON_KEY)

if _PROVIDER == "polygon" and not _POLYGON_KEY:
    _LOG.warning(
        "MARKET_DATA_PROVIDER=polygon but POLYGON_API_KEY is empty; "
        "falling back to yfinance. Set POLYGON_API_KEY in .env to activate."
    )

if _USE_POLYGON:
    import polygon_provider as _polygon


def _jsonify(value: Any) -> Any:
    """Coerce yfinance/pandas/numpy scalars into JSON-serializable Python.

    json.dumps does not allow NaN; pandas Timestamp and numpy.float64 are not
    JSON-native. We normalize:
      - NaN / pd.NaT  -> None
      - pd.Timestamp / datetime / date -> ISO string
      - numpy scalars (have .item()) -> Python native
      - everything else passes through.
    Mirrors the postgres MCP's _jsonify pattern.
    """
    # NaN check (works for float, numpy.float64).
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is None:
        return None
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    # pandas.Timestamp duck-types as datetime via isinstance above; pd.NaT
    # is a special case that compares != itself.
    try:
        if value != value:  # NaN/NaT trick
            return None
    except (TypeError, ValueError):
        pass
    # numpy scalars expose .item(); use it to drop the numpy wrapper.
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    return value


def _add_one_day(iso_date: str) -> str:
    """Add one calendar day to an ISO 'YYYY-MM-DD' string.

    yfinance's `history(end=...)` is exclusive on the end date; we add one day
    so the operator-facing semantics match: `end` is inclusive.
    """
    d = _dt.date.fromisoformat(iso_date)
    return (d + _dt.timedelta(days=1)).isoformat()


mcp = FastMCP("market_data")


def _prices_source_uri(
    ticker: str, start: str, end: str, interval: str, mode: str
) -> str:
    """Synthetic source_uri for a price pull — same vocabulary as evidence_index.

    Mode is part of the URI so a split-only and a total-return pull of the same
    window are distinguishable / separately auditable.
    """
    return (
        f"marketdata://prices/{ticker.upper()}/{start}/{end}/{interval}/{mode}"
    )


@mcp.tool()
def get_prices(
    ticker: str,
    start: str,
    end: str,
    interval: str = "1d",
    mode: str = "split_only",
    as_of: str | None = None,
) -> dict:
    """Return historical OHLCV prices for a ticker.

    Args:
        ticker: stock ticker (e.g., 'AAPL').
        start: ISO start date 'YYYY-MM-DD' (inclusive).
        end: ISO end date 'YYYY-MM-DD' (inclusive — yfinance treats as exclusive,
             so we add 1 day internally to make it inclusive for the user).
        interval: '1d', '1wk', '1mo' (yfinance values). Default '1d'.
        mode: pricing basis. Default ``"split_only"`` preserves the legacy shape
              (raw OHLC + ``adj_close`` only when the provider supplies a true
              total-return-adjusted series). ``"total_return"`` populates
              ``total_return_close`` (dividend + split inclusive) for each row so
              callers computing realized return capture reinvested dividends.
        as_of: optional ISO 'YYYY-MM-DD' point-in-time guard. When set, bars
               dated AFTER ``as_of`` are dropped — used by the calibration
               resolver to guarantee no look-ahead (reads ≤ resolve_at). When
               None, behaviour is unchanged.

    Returns:
        {
            "ticker": "AAPL",
            "start": "2024-01-01",
            "end": "2024-12-31",
            "interval": "1d",
            "mode": "split_only",
            "as_of": null,
            "rows": [
                {"date": "2024-01-02", "open": 187.15, "high": 188.44,
                 "low": 183.89, "close": 185.64, "adj_close": 184.95,
                 "total_return_close": 184.95, "volume": 82488700},
                ...
            ],
            "rowcount": N
        }

    Notes on ``mode`` semantics:
        - Polygon ``adjusted=true`` is **split-only**, NOT total-return — it
          does not reinvest dividends. The polygon provider therefore
          reconstructs total return from the dividends endpoint when
          ``mode="total_return"`` (see polygon_provider.get_prices). In
          split_only mode the provider returns ``total_return_close: null``.
        - yfinance ``auto_adjust=False`` exposes ``Adj Close`` which Yahoo
          adjusts for BOTH splits AND dividends — i.e. it is already a
          total-return series. So the yfinance total_return mode simply surfaces
          ``Adj Close`` as ``total_return_close``.
    """
    if mode not in ("split_only", "total_return"):
        raise ValueError(
            f"mode={mode!r} unsupported; use 'split_only' or 'total_return'"
        )

    if _USE_POLYGON:
        result = _polygon.get_prices(ticker, start, end, interval, mode=mode)
    else:
        yf_end = _add_one_day(end)
        df = yf.Ticker(ticker).history(
            start=start, end=yf_end, interval=interval, auto_adjust=False
        )

        rows: list[dict[str, Any]] = []
        # yfinance column names: Open, High, Low, Close, Adj Close, Volume.
        # When auto_adjust=False, both Close and Adj Close are present; Adj
        # Close is split+dividend adjusted (a total-return series).
        for ts, row in df.iterrows():
            # ts is a pandas Timestamp; index by name, fall back to date-only ISO.
            date_iso = ts.date().isoformat() if hasattr(ts, "date") else str(ts)
            adj_close = _jsonify(row.get("Adj Close"))
            rows.append(
                {
                    "date": date_iso,
                    "open": _jsonify(row.get("Open")),
                    "high": _jsonify(row.get("High")),
                    "low": _jsonify(row.get("Low")),
                    "close": _jsonify(row.get("Close")),
                    "adj_close": adj_close,
                    # yfinance Adj Close IS total-return adjusted; surface it as
                    # total_return_close only when the caller asked for it.
                    "total_return_close": adj_close if mode == "total_return" else None,
                    "volume": _jsonify(row.get("Volume")),
                }
            )

        result = {
            "ticker": ticker.upper(),
            "start": start,
            "end": end,
            "interval": interval,
            "rows": rows,
            "rowcount": len(rows),
        }

    # P0-7 point-in-time guard: drop any bar dated after as_of so callers
    # (e.g. the calibration resolver) cannot read look-ahead data.
    if as_of is not None:
        kept = [r for r in result.get("rows", []) if r.get("date") and r["date"] <= as_of]
        result["rows"] = kept
        result["rowcount"] = len(kept)
    result["mode"] = mode
    result["as_of"] = as_of

    # P0-3: persist the fetched price payload to evidence_documents, keyed to a
    # synthetic source_uri. Fail-soft & additive.
    _persist = _load_evidence_persistence()
    if _persist is not None:
        _persist.persist_document(
            source_uri=_prices_source_uri(ticker, start, end, interval, mode),
            body=result,
            fetched_by="market_data",
        )

    return result


@mcp.tool()
def get_news(ticker: str, since: str | None = None) -> dict:
    """Return recent news for a ticker via yfinance's news endpoint.

    Args:
        ticker: stock ticker.
        since: optional ISO date 'YYYY-MM-DD'; only news on or after this date.

    Returns:
        {
            "ticker": "AAPL",
            "items": [
                {"title": "...", "publisher": "...", "link": "...",
                 "publish_time": "2024-12-15T14:30:00Z", "type": "STORY"},
                ...
            ],
            "rowcount": N
        }
    """
    if _USE_POLYGON:
        return _polygon.get_news(ticker, since)
    raw_news = yf.Ticker(ticker).news or []
    since_dt: _dt.date | None = (
        _dt.date.fromisoformat(since) if since else None
    )

    items: list[dict[str, Any]] = []
    for entry in raw_news:
        # yfinance has shipped two shapes for `.news` over time:
        # legacy flat dict {title, publisher, link, providerPublishTime, type}
        # and a newer wrapper {id, content: {title, ...}}. Handle both.
        content = entry.get("content") if isinstance(entry, dict) else None
        if isinstance(content, dict):
            title = content.get("title", "")
            publisher_obj = content.get("provider") or {}
            publisher = (
                publisher_obj.get("displayName", "")
                if isinstance(publisher_obj, dict)
                else str(publisher_obj)
            )
            click_url = content.get("clickThroughUrl") or {}
            link = (
                click_url.get("url", "")
                if isinstance(click_url, dict)
                else ""
            )
            if not link:
                canonical = content.get("canonicalUrl") or {}
                link = (
                    canonical.get("url", "")
                    if isinstance(canonical, dict)
                    else ""
                )
            pub_time_raw = content.get("pubDate") or content.get(
                "displayTime"
            )
            type_str = content.get("contentType", "STORY")

            # pubDate is ISO already in the new shape.
            publish_iso = pub_time_raw or ""
        else:
            title = entry.get("title", "")
            publisher = entry.get("publisher", "")
            link = entry.get("link", "")
            ts = entry.get("providerPublishTime")
            publish_iso = (
                _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
                if isinstance(ts, (int, float))
                else ""
            )
            type_str = entry.get("type", "STORY")

        # Date filter on the YYYY-MM-DD prefix of publish_iso.
        if since_dt is not None and publish_iso:
            try:
                pub_date = _dt.date.fromisoformat(publish_iso[:10])
            except ValueError:
                pub_date = None
            if pub_date is not None and pub_date < since_dt:
                continue

        items.append(
            {
                "title": title,
                "publisher": publisher,
                "link": link,
                "publish_time": publish_iso,
                "type": type_str,
            }
        )

    return {
        "ticker": ticker.upper(),
        "items": items,
        "rowcount": len(items),
    }


@mcp.tool()
def get_real_time_quote(ticker: str) -> dict:
    """V0.5+ scaffold. Returns last price + timestamp from yfinance fast_info.

    Fine for v0.1 sample memo generation; production v0.5+ would use Polygon
    or Finnhub for true real-time tick fidelity.

    Returns:
        {"ticker": "AAPL", "last_price": 245.12,
         "as_of": "2024-12-31T15:59:59Z", "currency": "USD"}
    """
    if _USE_POLYGON:
        return _polygon.get_real_time_quote(ticker)
    fast_info = yf.Ticker(ticker).fast_info
    # yfinance FastInfo exposes attributes in snake_case (last_price, currency)
    # but dict keys are camelCase (lastPrice). Prefer attribute access — it
    # works regardless of whichever casing convention the version honors.
    last_price = getattr(fast_info, "last_price", None)
    if last_price is None and hasattr(fast_info, "get"):
        last_price = fast_info.get("lastPrice")
    currency = getattr(fast_info, "currency", None)
    if currency is None and hasattr(fast_info, "get"):
        currency = fast_info.get("currency")

    as_of = (
        _dt.datetime.now(tz=_dt.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

    return {
        "ticker": ticker.upper(),
        "last_price": _jsonify(last_price),
        "as_of": as_of,
        "currency": currency or "USD",
    }


if __name__ == "__main__":
    mcp.run()
