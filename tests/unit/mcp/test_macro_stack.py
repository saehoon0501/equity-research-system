"""Integration smoke tests for the macro-stack MCP server.

Hits LIVE BLS, BEA, and Census APIs. Marked `@pytest.mark.integration` so
they're skipped under `pytest -m 'not integration'`.

Each agency has its own API key (BLS_API_KEY / BEA_API_KEY / CENSUS_API_KEY),
loaded from repo `.env` by `tests/conftest.py`. If a key is missing, the
matching live test is *cleanly skipped* with a clear reason rather than
errored. Structural tests (import + tool count = 3) run regardless of keys.

Run from repo root:
    pytest tests/test_macro_stack.py -v
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# Load this MCP's `server.py` directly by file path under a unique module
# name; bare `from server import X` collides across MCP test files because
# every MCP module is named `server` and Python caches by module name.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVER_PATH = _REPO_ROOT / "src/mcp/macro_stack/server.py"
_spec = importlib.util.spec_from_file_location("macro_stack_mcp_server", _SERVER_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["macro_stack_mcp_server"] = _module
_spec.loader.exec_module(_module)

get_bls_series = _module.get_bls_series
get_bea_table = _module.get_bea_table
get_census_series = _module.get_census_series


# -----------------------------------------------------------------------------
# Structural — runs without any API keys.
# -----------------------------------------------------------------------------
def test_module_imports_and_exposes_three_tools() -> None:
    """The server module loads cleanly and exposes exactly three @mcp.tool
    callables. Structural — independent of any API key."""
    mcp = _module.mcp
    # FastMCP exposes registered tools via _tool_manager._tools (an internal,
    # but stable-since-1.0 surface). Fall back to attribute probing if the
    # internal layout shifts.
    tool_names: set[str] = set()
    tm = getattr(mcp, "_tool_manager", None)
    if tm is not None and hasattr(tm, "_tools"):
        tool_names = set(tm._tools.keys())
    else:
        for name in ("get_bls_series", "get_bea_table", "get_census_series"):
            assert hasattr(_module, name), f"missing tool fn {name}"
        return

    assert tool_names == {"get_bls_series", "get_bea_table", "get_census_series"}, (
        f"expected exactly 3 tools; got {tool_names!r}"
    )


# -----------------------------------------------------------------------------
# Live integration tests.
# -----------------------------------------------------------------------------
def _require(env_var: str, signup_url: str) -> None:
    if not os.environ.get(env_var):
        pytest.skip(
            f"{env_var} not set in .env; register a free key at {signup_url}"
        )


@pytest.mark.integration
def test_get_bls_series_cpi_u_2023_2024() -> None:
    """Pull CPI-U headline (CUUR0000SA0) for 2023–2024 (monthly).
    Expect >=12 monthly observations across the 24-month window."""
    _require("BLS_API_KEY", "https://data.bls.gov/registrationEngine/")
    result = get_bls_series("CUUR0000SA0", 2023, 2024)

    assert "series_not_found" not in result, (
        f"unexpected not-found sentinel: {result!r}"
    )
    assert result["series_id"] == "CUUR0000SA0"
    assert result["source"] == "bls"
    assert "retrieved_at" in result
    observations = result["observations"]
    assert isinstance(observations, list)
    assert len(observations) >= 12, (
        f"expected >=12 monthly CPI obs across 2023-2024; got {len(observations)}"
    )
    for o in observations:
        assert "year" in o and "period" in o and "value" in o
        assert o["value"] is None or isinstance(o["value"], float)


@pytest.mark.integration
def test_get_bea_table_nipa_t10101_2024() -> None:
    """Pull NIPA T10101 (real GDP % change), Q, 2024. Expect non-empty data."""
    _require("BEA_API_KEY", "https://apps.bea.gov/API/signup/")
    result = get_bea_table("NIPA", "T10101", "Q", "2024")

    assert "table_not_found" not in result, (
        f"unexpected not-found sentinel: {result!r}"
    )
    assert result["dataset"] == "NIPA"
    assert result["table_name"] == "T10101"
    assert result["source"] == "bea"
    assert "retrieved_at" in result
    data = result["data"]
    assert isinstance(data, list)
    assert len(data) > 0, "BEA NIPA T10101 returned empty data list"
    first = data[0]
    for key in ("TimePeriod", "LineNumber", "LineDescription", "DataValue"):
        assert key in first, f"missing expected BEA column {key}"


@pytest.mark.integration
def test_get_census_series_marts_2024() -> None:
    """Pull retail sales monthly time series 2024 from EITS MARTS.
    Expect non-empty observations."""
    _require("CENSUS_API_KEY", "https://api.census.gov/data/key_signup.html")
    result = get_census_series(
        "timeseries/eits/marts",
        "2024",
        ["cell_value", "data_type_code", "category_code"],
    )

    assert "dataset_not_found" not in result, (
        f"unexpected not-found sentinel: {result!r}"
    )
    assert result["dataset"] == "timeseries/eits/marts"
    assert result["source"] == "census"
    assert "retrieved_at" in result
    observations = result["observations"]
    assert isinstance(observations, list)
    assert len(observations) > 0, "Census MARTS 2024 returned no observations"
    # Each obs is a dict keyed by the variable column names (plus `time`).
    first = observations[0]
    assert isinstance(first, dict)
    assert "cell_value" in first


# -----------------------------------------------------------------------------
# Failure-mode contract — parametrized across all three endpoints.
# -----------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.parametrize(
    "endpoint_label, key_env, signup, call, sentinel_field",
    [
        (
            "bls",
            "BLS_API_KEY",
            "https://data.bls.gov/registrationEngine/",
            lambda: get_bls_series("ZZNOTAREALBLSSERIES12345", 2023, 2024),
            "series_not_found",
        ),
        (
            "bea",
            "BEA_API_KEY",
            "https://apps.bea.gov/API/signup/",
            lambda: get_bea_table("NIPA", "TZZNOTATABLE9999", "Q", "2024"),
            "table_not_found",
        ),
        (
            "census",
            "CENSUS_API_KEY",
            "https://api.census.gov/data/key_signup.html",
            lambda: get_census_series(
                "timeseries/eits/zznotarealdataset", "2024", ["cell_value"]
            ),
            "dataset_not_found",
        ),
    ],
)
def test_failure_mode_sentinel_on_bogus_id(
    endpoint_label, key_env, signup, call, sentinel_field
) -> None:
    """Bogus series_id / table_name / dataset must return the not-found
    sentinel, not raise."""
    _require(key_env, signup)
    result = call()
    assert isinstance(result, dict), f"{endpoint_label}: expected dict, got {type(result)}"
    assert result.get(sentinel_field) is True, (
        f"{endpoint_label}: expected {sentinel_field}=True sentinel; got {result!r}"
    )


# -----------------------------------------------------------------------------
# Missing-key failure-mode — runs even when keys ARE present, by temporarily
# unsetting the env var. Locks in the documented "do not raise on missing
# key" contract.
# -----------------------------------------------------------------------------
def test_missing_bls_key_returns_sentinel(monkeypatch) -> None:
    monkeypatch.delenv("BLS_API_KEY", raising=False)
    result = get_bls_series("CUUR0000SA0", 2023, 2024)
    assert result.get("series_not_found") is True
    assert result.get("error_class") == "missing_api_key"


def test_missing_bea_key_returns_sentinel(monkeypatch) -> None:
    monkeypatch.delenv("BEA_API_KEY", raising=False)
    result = get_bea_table("NIPA", "T10101", "Q", "2024")
    assert result.get("table_not_found") is True
    assert result.get("error_class") == "missing_api_key"


def test_missing_census_key_returns_sentinel(monkeypatch) -> None:
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    result = get_census_series(
        "timeseries/eits/marts", "2024", ["cell_value"]
    )
    assert result.get("dataset_not_found") is True
    assert result.get("error_class") == "missing_api_key"
