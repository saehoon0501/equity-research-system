"""FRED MCP server for the equity research system.

Per BUILD_LOG.md decision 6, this is a tool consumed by Claude Code (specifically
the MacroCycleAgent), not an orchestrator. Thin HTTP wrapper over
`api.stlouisfed.org` per `.claude/references/mcp-required.md` §"`mcp__fred`".

Two tools:

- get_series(series_id, start, end): fetch a FRED time series with optional
  date bounds. e.g., 'DGS10' (10Y Treasury), 'UNRATE' (unemployment),
  'CPIAUCSL' (CPI), 'GDP', 'T10Y2Y' (10Y-2Y yield curve spread).
- get_series_info(series_id): metadata only (title, frequency, units), no
  observations. Cheap; use to confirm a series exists before fetching observations.

Connection info (specifically the FRED API key) is loaded from the repo root
`.env` file via python-dotenv. The API key is required; the server fails loud
on the first tool call if `FRED_API_KEY` is unset.

Scope notes:
- No FRED-MD/QD heavy series. No nowcasting (e.g., GDPNow). MacroCycleAgent
  composes the few headline series it needs from individual `get_series` calls.
- Missing observations: FRED ships missing values as the literal string ".";
  we map those to Python `None` so consumers don't accidentally choke on it
  or, worse, treat "." as a valid number via str-coercion.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Walk: server.py → fred/ → mcp/ → src/ → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
_SERIES_URL = "https://api.stlouisfed.org/fred/series"

_HTTP_TIMEOUT = 30.0


def _api_key() -> str:
    """Return the FRED API key or fail loud.

    FRED requires a free API key on every request. We refuse to make any HTTP
    call until the operator has registered one and dropped it into `.env`.
    """
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise RuntimeError(
            "FRED_API_KEY must be set in .env. Register a free key at "
            "https://fredaccountmanager.research.stlouisfed.org/apikey"
        )
    return key


def _http_client() -> httpx.Client:
    """Per-call httpx client. No connection pooling at v0.1 scale."""
    return httpx.Client(timeout=_HTTP_TIMEOUT)


def _parse_value(raw: str | None) -> float | None:
    """FRED ships missing observations as '.'; coerce to None, else float."""
    if raw is None or raw == "" or raw == ".":
        return None
    return float(raw)


mcp = FastMCP("fred")


@mcp.tool()
def get_series(
    series_id: str,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """Fetch a FRED time series.

    Args:
        series_id: FRED series ID (e.g., 'DGS10' for 10Y Treasury, 'UNRATE',
                   'CPIAUCSL', 'GDP', 'T10Y2Y' yield curve spread).
        start: optional ISO date 'YYYY-MM-DD' (observations on or after).
        end: optional ISO date 'YYYY-MM-DD' (observations on or before).

    Returns:
        {
            "series_id": "DGS10",
            "title": "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity",
            "frequency": "Daily",
            "units": "Percent",
            "observations": [
                {"date": "2024-01-02", "value": 3.95},
                ...
            ],
            "rowcount": N
        }
    """
    key = _api_key()
    with _http_client() as client:
        # Series metadata (title, frequency, units) lives on /fred/series.
        info_params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": key,
            "file_type": "json",
        }
        info_resp = client.get(_SERIES_URL, params=info_params)
        info_resp.raise_for_status()
        info_data = info_resp.json()
        seriess = info_data.get("seriess") or []  # FRED's typo, not ours
        if not seriess:
            raise ValueError(f"Unknown FRED series: {series_id}")
        meta = seriess[0]
        title = meta.get("title", "")
        frequency = meta.get("frequency", "")
        units = meta.get("units", "")

        # Observations.
        obs_params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": key,
            "file_type": "json",
        }
        if start is not None:
            obs_params["observation_start"] = start
        if end is not None:
            obs_params["observation_end"] = end
        obs_resp = client.get(_OBSERVATIONS_URL, params=obs_params)
        obs_resp.raise_for_status()
        obs_data = obs_resp.json()

        raw_observations = obs_data.get("observations") or []
        observations: list[dict[str, Any]] = [
            {"date": o.get("date", ""), "value": _parse_value(o.get("value"))}
            for o in raw_observations
        ]

        return {
            "series_id": series_id,
            "title": title,
            "frequency": frequency,
            "units": units,
            "observations": observations,
            "rowcount": len(observations),
        }


@mcp.tool()
def get_series_info(series_id: str) -> dict:
    """Series metadata only (no observations). Cheap; useful for confirming
    the series exists before doing a heavier observations fetch.

    Args:
        series_id: FRED series ID.

    Returns:
        {
            "series_id": "UNRATE",
            "title": "Unemployment Rate",
            "frequency": "Monthly",
            "units": "Percent"
        }
    """
    key = _api_key()
    with _http_client() as client:
        params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": key,
            "file_type": "json",
        }
        resp = client.get(_SERIES_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        seriess = data.get("seriess") or []  # FRED's typo, not ours
        if not seriess:
            raise ValueError(f"Unknown FRED series: {series_id}")
        meta = seriess[0]
        return {
            "series_id": series_id,
            "title": meta.get("title", ""),
            "frequency": meta.get("frequency", ""),
            "units": meta.get("units", ""),
        }


if __name__ == "__main__":
    mcp.run()
