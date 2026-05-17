"""Integration smoke tests for the FRED MCP server (`src/mcp/fred/server.py`).

These tests hit the LIVE FRED API (api.stlouisfed.org). They are network-
dependent and marked `@pytest.mark.integration` so they can be skipped in
offline CI later (e.g. `pytest -m 'not integration'`).

`FRED_API_KEY` is a free-but-required key. Until the operator has registered
one at https://fredaccountmanager.research.stlouisfed.org/apikey, every test
in this module is *cleanly skipped* (not errored) by an autouse fixture below.
The moment a key lands in `.env`, all three tests start running on their next
invocation — no test code changes needed.

Run from repo root:
    pytest tests/test_fred.py -v
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

# Load this MCP's `server.py` directly by file path under a unique module
# name; bare `from server import X` collides across MCP test files because
# every MCP module is named `server` and Python caches by module name.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVER_PATH = _REPO_ROOT / "src/mcp/fred/server.py"
_spec = importlib.util.spec_from_file_location("fred_mcp_server", _SERVER_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["fred_mcp_server"] = _module
_spec.loader.exec_module(_module)

get_series = _module.get_series
get_series_info = _module.get_series_info


# -----------------------------------------------------------------------------
# Skip-when-no-key gate
# -----------------------------------------------------------------------------
# Autouse fixture skips every test in this module if FRED_API_KEY is unset.
# This is a clean skip (not an error) so CI/local runs without a key just
# show "skipped" rather than a noisy RuntimeError from the server module.
# `conftest.py` loads .env before this runs, so the env var is populated if
# the operator has registered.
@pytest.fixture(autouse=True)
def _require_fred_api_key() -> None:
    if not os.environ.get("FRED_API_KEY"):
        pytest.skip(
            "FRED_API_KEY not set in .env; register a free key at "
            "https://fredaccountmanager.research.stlouisfed.org/apikey"
        )


# -----------------------------------------------------------------------------
# get_series
# -----------------------------------------------------------------------------
@pytest.mark.integration
def test_get_series_dgs10() -> None:
    """Fetch 10Y Treasury (DGS10) for the last 30 calendar days.

    DGS10 is daily (business days only), so 30 calendar days yields ~20 obs.
    We assert >= 10 to leave slack for holidays/weekends. Every returned date
    must be on or after `start`.
    """
    start = (date.today() - timedelta(days=30)).isoformat()
    result = get_series("DGS10", start=start)

    assert result["series_id"] == "DGS10"
    assert "Treasury" in result["title"], (
        f"expected 'Treasury' in DGS10 title, got {result['title']!r}"
    )
    # DGS10 frequency is 'Daily'; units are 'Percent'. Don't over-constrain.
    assert result["frequency"]
    assert result["units"]

    observations = result["observations"]
    assert result["rowcount"] == len(observations)
    assert len(observations) >= 10, (
        f"expected >=10 daily obs in last 30 calendar days; got {len(observations)}"
    )
    for o in observations:
        assert "date" in o and "value" in o
        assert o["date"] >= start, (
            f"observation date {o['date']} predates start {start}"
        )
        # value is None (missing) or float; never a raw "."
        assert o["value"] is None or isinstance(o["value"], float)


@pytest.mark.integration
def test_get_series_info_unrate() -> None:
    """get_series_info('UNRATE') metadata sanity."""
    result = get_series_info("UNRATE")

    assert result["series_id"] == "UNRATE"
    assert "Unemployment" in result["title"], (
        f"expected 'Unemployment' in UNRATE title, got {result['title']!r}"
    )
    assert "Monthly" in result["frequency"], (
        f"expected 'Monthly' in UNRATE frequency, got {result['frequency']!r}"
    )
    assert result["units"]


@pytest.mark.integration
def test_get_series_unknown_id() -> None:
    """A clearly bogus series ID raises (FRED 400 -> httpx.HTTPStatusError,
    or our own ValueError if FRED ever returns an empty `seriess` list).
    """
    with pytest.raises((httpx.HTTPStatusError, ValueError)):
        get_series("NOSUCHFREDSERIES_ZZZ12345")
