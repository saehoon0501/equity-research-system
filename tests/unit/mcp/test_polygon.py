"""Integration smoke tests for the polygon options MCP server.

Hits LIVE Polygon.io via `polygon-api-client`. Network-dependent;
mark @pytest.mark.integration when we wire up offline CI later.

If POLYGON_API_KEY is missing from the environment, tests skip gracefully
(structural-only verification) rather than failing loudly — the operator's
key may not be provisioned yet.

Run from repo root:
    pytest tests/test_polygon.py -v
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
# Load .env so POLYGON_API_KEY is available when pytest is invoked outside the
# `set -a && source .env && set +a` shell-wrapper convention.
load_dotenv(_REPO_ROOT / ".env")

# Load the MCP server module by path; bare `from server import X` collides
# across MCP test files because every MCP module is named `server`.
_SERVER_PATH = _REPO_ROOT / "src/mcp/polygon/server.py"
_spec = importlib.util.spec_from_file_location("polygon_mcp_server", _SERVER_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["polygon_mcp_server"] = _module
_spec.loader.exec_module(_module)

get_options_chain = _module.get_options_chain
get_iv_term_structure = _module.get_iv_term_structure
get_put_call_ratio = _module.get_put_call_ratio
get_unusual_activity = _module.get_unusual_activity


_HAVE_KEY = bool((os.environ.get("POLYGON_API_KEY") or "").strip())

requires_polygon_key = pytest.mark.skipif(
    not _HAVE_KEY,
    reason="POLYGON_API_KEY not set; skipping live-API test (structural verification only)",
)


def _skip_if_tier_insufficient(result: dict) -> None:
    """Tests that hit live Polygon should skip — not fail — when the operator's
    plan does not include the snapshot options-chain endpoint. The agent layer
    propagates the tier_insufficient signal upstream so callers can route to a
    fallback (e.g., yfinance get_recommendations for sentiment), but for unit
    tests the contract is that we surface the upgrade message cleanly.
    """
    if isinstance(result, dict) and result.get("error_class") == "polygon_tier_insufficient":
        pytest.skip(
            "Polygon plan does not include snapshot options chain — "
            "upgrade required: " + str(result.get("upgrade_url", ""))
        )


def test_structural_module_loads_and_registers_four_tools():
    """Structural verification: module imports + FastMCP has 4 tools registered.

    This test runs even without POLYGON_API_KEY so we always validate the
    package shape on every CI run.
    """
    assert hasattr(_module, "mcp"), "FastMCP instance not exposed as `mcp`"
    # Each @mcp.tool() decorated callable remains accessible at module scope.
    for name in (
        "get_options_chain",
        "get_iv_term_structure",
        "get_put_call_ratio",
        "get_unusual_activity",
    ):
        assert callable(getattr(_module, name)), f"missing endpoint {name}"


@pytest.mark.integration
@requires_polygon_key
def test_get_options_chain_spy_returns_required_fields():
    result = get_options_chain("SPY")
    assert isinstance(result, dict)
    _skip_if_tier_insufficient(result)
    assert result.get("ticker_not_found") is not True, f"unexpected ticker_not_found for SPY: {result}"
    assert result["ticker"] == "SPY"
    assert result["source"] == "polygon"
    assert "retrieved_at" in result
    assert isinstance(result["contracts"], list)
    if result["contracts"]:
        c = result["contracts"][0]
        for key in ("strike", "expiry", "type", "open_interest", "volume", "iv",
                    "delta", "gamma", "theta", "vega"):
            assert key in c, f"missing required field {key} in contract row"


@pytest.mark.integration
@requires_polygon_key
def test_get_iv_term_structure_spy_returns_required_fields():
    result = get_iv_term_structure("SPY")
    assert isinstance(result, dict)
    _skip_if_tier_insufficient(result)
    assert result.get("ticker_not_found") is not True
    assert result["ticker"] == "SPY"
    assert "term_structure" in result
    assert "front_back_spread" in result
    assert "retrieved_at" in result
    assert isinstance(result["term_structure"], list)
    if result["term_structure"]:
        row = result["term_structure"][0]
        assert "days_to_expiry" in row
        assert "atm_iv" in row


@pytest.mark.integration
@requires_polygon_key
def test_get_put_call_ratio_spy_returns_required_fields():
    result = get_put_call_ratio("SPY", lookback_days=5)  # small window to keep test fast
    assert isinstance(result, dict)
    _skip_if_tier_insufficient(result)
    assert result.get("ticker_not_found") is not True
    assert result["ticker"] == "SPY"
    assert result["lookback_days"] == 5
    for key in ("total_put_vol", "total_call_vol", "p_c_ratio", "retrieved_at"):
        assert key in result, f"missing required field {key}"


@pytest.mark.integration
@requires_polygon_key
def test_get_unusual_activity_spy_returns_required_fields():
    result = get_unusual_activity("SPY", lookback_days=5)
    assert isinstance(result, dict)
    _skip_if_tier_insufficient(result)
    assert result.get("ticker_not_found") is not True
    assert result["ticker"] == "SPY"
    assert "unusual_contracts" in result
    assert "retrieved_at" in result
    assert isinstance(result["unusual_contracts"], list)
    if result["unusual_contracts"]:
        u = result["unusual_contracts"][0]
        for key in ("strike", "expiry", "type", "vol", "oi", "vol_oi_ratio", "vol_vs_avg_x"):
            assert key in u, f"missing required field {key}"


@pytest.mark.integration
@requires_polygon_key
def test_tier_insufficient_payload_shape_when_chain_unauthorized():
    """When the operator's Polygon plan does NOT include snapshot options-chain
    (free tier), the four endpoints must return a tier_insufficient payload
    with: error_class, upgrade_url, note, plus the ticker_not_found flag.

    This test is the contract for the upstream agent layer (CatalystScout)
    so it can route gracefully — e.g., fall back to yfinance sentiment or
    flag the operator to upgrade.

    The test calls get_options_chain('SPY'); on a free-tier key this hits
    the tier_insufficient branch. On a paid-tier key we skip — the live
    happy-path tests above already cover that side.
    """
    result = get_options_chain("SPY")
    if result.get("error_class") != "polygon_tier_insufficient":
        pytest.skip("operator's Polygon key has paid tier — covered by live tests")
    # Verify the payload contract.
    assert result.get("ticker_not_found") is True
    assert result["error_class"] == "polygon_tier_insufficient"
    assert "upgrade_url" in result
    assert result["upgrade_url"].startswith("https://")
    assert "note" in result


@pytest.mark.integration
@requires_polygon_key
@pytest.mark.parametrize("fn_name", [
    "get_options_chain",
    "get_iv_term_structure",
    "get_put_call_ratio",
    "get_unusual_activity",
])
def test_unknown_ticker_returns_not_found_dict(fn_name):
    """All four endpoints must return {ticker_not_found: True} consistently for unknown tickers."""
    fn = getattr(_module, fn_name)
    result = fn("ZZZZNOTAREALTICKER12345")
    assert isinstance(result, dict), f"{fn_name} did not return a dict; got {type(result)}"
    assert result.get("ticker_not_found") is True, (
        f"{fn_name} did not return ticker_not_found=True for unknown ticker; "
        f"got {result!r}"
    )
