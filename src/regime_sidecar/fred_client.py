"""Thin direct-HTTP FRED client for the regime sidecar.

The repo already has an `mcp__fred` server (src/mcp/fred/server.py). MCP tools
are scoped to subagents/Claude-Code calls, but the sidecar runs as a plain
Python module under cron / CLI — so we duplicate the minimal FRED HTTP logic
here rather than introducing an MCP-client dependency. Same env var
(`FRED_API_KEY`); same observation parsing (`.` → None) per the existing
server.

Per v3 spec §3.3 — all 6 dimensions buildable on free data; FRED is the
backbone for dims 2, 4, 5, and the realized-variance computation in dim 3.

Reference: `src/mcp/fred/server.py` (canonical observation parsing).
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")

_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
_HTTP_TIMEOUT = 30.0


def _api_key() -> str:
    """Return the FRED API key or fail loud (mirrors mcp__fred server)."""
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise RuntimeError(
            "FRED_API_KEY must be set in .env. Register a free key at "
            "https://fredaccountmanager.research.stlouisfed.org/apikey"
        )
    return key


def _parse_value(raw: str | None) -> float | None:
    """FRED ships missing observations as '.'; coerce to None, else float."""
    if raw is None or raw == "" or raw == ".":
        return None
    return float(raw)


def get_series(
    series_id: str,
    start: date | str | None = None,
    end: date | str | None = None,
) -> list[dict[str, Any]]:
    """Fetch a FRED time series; returns list of {date, value} observations.

    Args:
        series_id: e.g. 'DGS10', 'WALCL', 'DTWEXBGS', 'M2SL'.
        start, end: optional ISO date or `datetime.date`; inclusive bounds.

    Returns:
        [{"date": "YYYY-MM-DD", "value": float|None}, ...]
        Missing observations are parsed to None (never the literal '.').
    """
    key = _api_key()
    params: dict[str, Any] = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
    }
    if start is not None:
        params["observation_start"] = str(start)
    if end is not None:
        params["observation_end"] = str(end)

    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.get(_OBSERVATIONS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    raw = data.get("observations") or []
    return [
        {"date": o.get("date", ""), "value": _parse_value(o.get("value"))}
        for o in raw
    ]


def latest_value(series_id: str, asof: date | str | None = None) -> tuple[str, float | None]:
    """Return the most recent (date, value) pair on or before `asof`.

    Skips missing observations (None values from FRED's '.'). Returns
    ('', None) if no usable observation exists.
    """
    obs = get_series(series_id, end=asof)
    for o in reversed(obs):
        if o["value"] is not None:
            return o["date"], o["value"]
    return "", None
