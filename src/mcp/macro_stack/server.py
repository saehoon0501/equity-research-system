"""macro-stack MCP server for the equity research system.

Unified MCP wrapper over three U.S. government macro-data APIs:

- BLS  — https://api.bls.gov/publicAPI/v2/timeseries/data/
- BEA  — https://apps.bea.gov/api/data
- Census — https://api.census.gov/data/{dataset}

Per BUILD_LOG.md decision 6, this is a Claude-Code-consumed tool, not an
orchestrator. Sibling of `fred`: where FRED republishes select indicators,
this MCP reaches the primary sources directly for tables FRED does not carry
(BEA NIPA detail, Census EITS time series, granular BLS series).

Failure-mode contract (mirrors `yfinance`/`fred` patterns):
- get_bls_series:    on auth/404/empty → {series_not_found: True, series_id, ...}
- get_bea_table:     on auth/404/bad table → {table_not_found: True, table_name, ...}
- get_census_series: on auth/404/empty → {dataset_not_found: True, dataset, ...}
- Any networking/JSON exception → same sentinel + `error_class` describing it.
  We never raise out of a tool; MacroCycleAgent degrades gracefully on miss.

API keys load from repo-root `.env` via python-dotenv. Missing keys do NOT
fail-loud here (unlike `fred`); we return the not-found sentinel with
`error_class: "missing_api_key"` so a partial-key environment can still
exercise the other two endpoints.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Walk: server.py → macro_stack/ → mcp/ → src/ → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


_BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
_BEA_URL = "https://apps.bea.gov/api/data"
_CENSUS_URL_TMPL = "https://api.census.gov/data/{dataset}"

_HTTP_TIMEOUT = 30.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


mcp = FastMCP("macro_stack")


# ---------------------------------------------------------------------------
# get_bls_series
# ---------------------------------------------------------------------------
@mcp.tool()
def get_bls_series(series_id: str, start_year: int, end_year: int) -> dict:
    """Fetch a BLS public time series via the v2 POST API.

    Args:
        series_id: BLS series ID (e.g. 'CUUR0000SA0' CPI-U, 'LNS14000000'
                   unemployment rate, 'CES0000000001' nonfarm payrolls).
        start_year: inclusive (e.g. 2023).
        end_year:   inclusive (e.g. 2024).

    Returns on success:
        {
            "series_id": str,
            "start_year": int,
            "end_year": int,
            "observations": [{year, period, value, footnotes}, ...],
            "source": "bls",
            "retrieved_at": ISO8601,
        }

    Failure-mode sentinel:
        {"series_not_found": True, "series_id": str, "error_class": str?}
    """
    key = os.environ.get("BLS_API_KEY")
    if not key:
        return {
            "series_not_found": True,
            "series_id": series_id,
            "error_class": "missing_api_key",
        }

    payload: dict[str, Any] = {
        "seriesid": [series_id],
        "startyear": str(start_year),
        "endyear": str(end_year),
        "registrationkey": key,
    }

    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.post(_BLS_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else None
        return {
            "series_not_found": True,
            "series_id": series_id,
            "error_class": f"http_{status}" if status else "http_error",
        }
    except httpx.HTTPError:
        return {
            "series_not_found": True,
            "series_id": series_id,
            "error_class": "connectivity",
        }
    except (ValueError, KeyError):
        return {
            "series_not_found": True,
            "series_id": series_id,
            "error_class": "bad_response",
        }

    # BLS v2: top-level status is "REQUEST_SUCCEEDED" or "REQUEST_NOT_PROCESSED".
    if data.get("status") != "REQUEST_SUCCEEDED":
        return {
            "series_not_found": True,
            "series_id": series_id,
            "error_class": "request_not_processed",
        }

    series_list = (data.get("Results") or {}).get("series") or []
    if not series_list:
        return {
            "series_not_found": True,
            "series_id": series_id,
            "error_class": "empty_results",
        }

    raw_obs = series_list[0].get("data") or []
    if not raw_obs:
        # Valid series ID but no observations in this window.
        return {
            "series_not_found": True,
            "series_id": series_id,
            "error_class": "no_observations",
        }

    observations: list[dict[str, Any]] = []
    for o in raw_obs:
        raw_val = o.get("value")
        try:
            val: float | None = float(raw_val) if raw_val not in (None, "", "-") else None
        except (TypeError, ValueError):
            val = None
        observations.append({
            "year": o.get("year", ""),
            "period": o.get("period", ""),
            "value": val,
            "footnotes": o.get("footnotes", []),
        })

    return {
        "series_id": series_id,
        "start_year": start_year,
        "end_year": end_year,
        "observations": observations,
        "source": "bls",
        "retrieved_at": _now_iso(),
    }


# ---------------------------------------------------------------------------
# get_bea_table
# ---------------------------------------------------------------------------
@mcp.tool()
def get_bea_table(dataset: str, table_name: str, frequency: str, year: str) -> dict:
    """Fetch a BEA Data API table.

    Args:
        dataset:    e.g. 'NIPA', 'FixedAssets', 'Regional'.
        table_name: e.g. 'T10101' (real GDP % change), 'T20305' (PCE by type).
        frequency:  'A' annual, 'Q' quarterly, 'M' monthly (table-dependent).
        year:       four-digit year string, comma-separated list, or 'ALL'.

    Returns on success:
        {
            "dataset": str,
            "table_name": str,
            "frequency": str,
            "year": str,
            "data": [{TimePeriod, LineNumber, LineDescription, DataValue,
                      METRIC_NAME, CL_UNIT}, ...],
            "source": "bea",
            "retrieved_at": ISO8601,
        }

    Failure-mode sentinel:
        {"table_not_found": True, "table_name": str, "error_class": str?}
    """
    key = os.environ.get("BEA_API_KEY")
    if not key:
        return {
            "table_not_found": True,
            "table_name": table_name,
            "error_class": "missing_api_key",
        }

    params: dict[str, Any] = {
        "UserID": key,
        "method": "GetData",
        "datasetname": dataset,
        "TableName": table_name,
        "Frequency": frequency,
        "Year": year,
        "ResultFormat": "JSON",
    }

    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.get(_BEA_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else None
        return {
            "table_not_found": True,
            "table_name": table_name,
            "error_class": f"http_{status}" if status else "http_error",
        }
    except httpx.HTTPError:
        return {
            "table_not_found": True,
            "table_name": table_name,
            "error_class": "connectivity",
        }
    except (ValueError, KeyError):
        return {
            "table_not_found": True,
            "table_name": table_name,
            "error_class": "bad_response",
        }

    # BEA returns either:
    #   {"BEAAPI": {"Results": {"Data": [...], ...}}}                — success
    #   {"BEAAPI": {"Results": {"Error": {...}}}}                    — table-level error
    #   {"BEAAPI": {"Error": {...}}}                                 — request-level error
    bea_api = data.get("BEAAPI") or {}
    if "Error" in bea_api:
        return {
            "table_not_found": True,
            "table_name": table_name,
            "error_class": "bea_error",
        }

    results = bea_api.get("Results") or {}
    # When dataset is bad, BEA can wrap an error inside Results.
    if isinstance(results, dict) and "Error" in results:
        return {
            "table_not_found": True,
            "table_name": table_name,
            "error_class": "bea_table_error",
        }

    # Some endpoints return Results as a list (e.g. multi-table requests); flatten.
    if isinstance(results, list):
        results = results[0] if results else {}

    rows = results.get("Data") or []
    if not rows:
        return {
            "table_not_found": True,
            "table_name": table_name,
            "error_class": "empty_data",
        }

    keep_keys = ("TimePeriod", "LineNumber", "LineDescription", "DataValue",
                 "METRIC_NAME", "CL_UNIT")
    cleaned: list[dict[str, Any]] = [
        {k: r.get(k) for k in keep_keys} for r in rows
    ]

    return {
        "dataset": dataset,
        "table_name": table_name,
        "frequency": frequency,
        "year": year,
        "data": cleaned,
        "source": "bea",
        "retrieved_at": _now_iso(),
    }


# ---------------------------------------------------------------------------
# get_census_series
# ---------------------------------------------------------------------------
@mcp.tool()
def get_census_series(dataset: str, time_period: str, variables: list[str]) -> dict:
    """Fetch a Census Bureau time-series API endpoint.

    Args:
        dataset: e.g. 'timeseries/eits/marts' (Monthly Retail Trade Survey),
                 'timeseries/eits/resconst' (housing starts).
        time_period: e.g. '2024', 'from+2023+to+2024', or a specific month.
                     Passed straight through as the `time=` query param.
        variables:   list of column codes to request, e.g.
                     ['cell_value', 'data_type_code', 'category_code'].

    Returns on success:
        {
            "dataset": str,
            "time_period": str,
            "variables": [str],
            "observations": [ {col: val, ...}, ... ],   # column-name → cell
            "source": "census",
            "retrieved_at": ISO8601,
        }

    Failure-mode sentinel:
        {"dataset_not_found": True, "dataset": str, "error_class": str?}

    Census returns CSV-style JSON: first row is the column header, subsequent
    rows are values. We reshape into a list of dicts keyed by column name.
    """
    key = os.environ.get("CENSUS_API_KEY")
    if not key:
        return {
            "dataset_not_found": True,
            "dataset": dataset,
            "error_class": "missing_api_key",
        }

    if not variables:
        return {
            "dataset_not_found": True,
            "dataset": dataset,
            "error_class": "no_variables",
        }

    url = _CENSUS_URL_TMPL.format(dataset=dataset)
    params: dict[str, Any] = {
        "get": ",".join(variables),
        "time": time_period,
        "key": key,
    }

    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            raw = resp.json()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else None
        return {
            "dataset_not_found": True,
            "dataset": dataset,
            "error_class": f"http_{status}" if status else "http_error",
        }
    except httpx.HTTPError:
        return {
            "dataset_not_found": True,
            "dataset": dataset,
            "error_class": "connectivity",
        }
    except (ValueError, KeyError):
        return {
            "dataset_not_found": True,
            "dataset": dataset,
            "error_class": "bad_response",
        }

    # Census returns a list-of-lists; first row = header, rest = data.
    if not isinstance(raw, list) or len(raw) < 1:
        return {
            "dataset_not_found": True,
            "dataset": dataset,
            "error_class": "empty_response",
        }

    header = raw[0]
    rows = raw[1:]
    if not rows:
        return {
            "dataset_not_found": True,
            "dataset": dataset,
            "error_class": "no_observations",
        }

    observations: list[dict[str, Any]] = [
        {col: row[i] if i < len(row) else None for i, col in enumerate(header)}
        for row in rows
    ]

    return {
        "dataset": dataset,
        "time_period": time_period,
        "variables": variables,
        "observations": observations,
        "source": "census",
        "retrieved_at": _now_iso(),
    }


if __name__ == "__main__":
    mcp.run()
