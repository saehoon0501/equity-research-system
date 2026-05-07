"""Integration smoke tests for the yfinance MCP server.

Hits LIVE Yahoo Finance via the `yfinance` Python lib. Network-dependent;
mark @pytest.mark.integration when we wire up offline CI later.

Run from repo root:
    pytest tests/test_yfinance.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load the MCP server module by path; bare `from server import X` collides
# across MCP test files because every MCP module is named `server`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVER_PATH = _REPO_ROOT / "src/mcp/yfinance/server.py"
_spec = importlib.util.spec_from_file_location("yfinance_mcp_server", _SERVER_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["yfinance_mcp_server"] = _module
_spec.loader.exec_module(_module)

get_consensus_estimates = _module.get_consensus_estimates
get_target_prices = _module.get_target_prices
get_recommendations = _module.get_recommendations
get_calendar = _module.get_calendar
get_holders = _module.get_holders
get_peer_comps = _module.get_peer_comps


@pytest.mark.integration
def test_get_consensus_estimates_aapl_returns_required_fields():
    result = get_consensus_estimates("AAPL")
    assert isinstance(result, dict)
    for key in (
        "fy_eps_mean",
        "fy_revenue_mean",
        "next_q_eps_mean",
        "next_q_revenue_mean",
        "analyst_count",
    ):
        assert key in result, f"missing required field {key}"
    # analyst_count is int or None
    assert result["analyst_count"] is None or isinstance(result["analyst_count"], int)


@pytest.mark.integration
def test_get_consensus_estimates_unknown_ticker_returns_not_found():
    result = get_consensus_estimates("ZZZZNOTAREALTICKER")
    assert result == {"ticker_not_found": True}


@pytest.mark.integration
def test_get_target_prices_aapl_returns_required_fields():
    result = get_target_prices("AAPL")
    assert isinstance(result, dict)
    for key in (
        "target_high",
        "target_low",
        "target_mean",
        "target_median",
        "number_of_analyst_opinions",
        "recommendation_mean",
        "recommendation_key",
    ):
        assert key in result, f"missing required field {key}"


@pytest.mark.integration
def test_get_target_prices_unknown_ticker_returns_not_found():
    result = get_target_prices("ZZZZNOTAREALTICKER")
    assert result == {"ticker_not_found": True}


@pytest.mark.integration
def test_get_recommendations_aapl_returns_list():
    result = get_recommendations("AAPL", days=90)
    assert isinstance(result, list)
    if result:
        item = result[0]
        for key in ("firm", "to_grade", "from_grade", "action", "date"):
            assert key in item, f"missing required field {key}"


@pytest.mark.integration
def test_get_recommendations_unknown_ticker_returns_not_found():
    result = get_recommendations("ZZZZNOTAREALTICKER")
    assert result == {"ticker_not_found": True}


@pytest.mark.integration
def test_get_calendar_aapl_returns_required_fields():
    result = get_calendar("AAPL")
    assert isinstance(result, dict)
    for key in ("next_earnings_date", "ex_dividend_date", "dividend_date"):
        assert key in result


@pytest.mark.integration
def test_get_calendar_unknown_ticker_returns_not_found():
    result = get_calendar("ZZZZNOTAREALTICKER")
    assert result == {"ticker_not_found": True}


@pytest.mark.integration
def test_get_holders_aapl_returns_required_fields():
    result = get_holders("AAPL")
    assert isinstance(result, dict)
    for key in ("institutional_holders", "major_holders", "insider_holders", "institutional_pct"):
        assert key in result
    assert isinstance(result["institutional_holders"], list)


@pytest.mark.integration
def test_get_holders_unknown_ticker_returns_not_found():
    result = get_holders("ZZZZNOTAREALTICKER")
    assert result == {"ticker_not_found": True}


@pytest.mark.integration
def test_get_peer_comps_aapl_returns_list():
    result = get_peer_comps("AAPL")
    assert isinstance(result, list)
    if result:
        peer = result[0]
        for key in ("ticker", "pe", "ev_ebitda", "ev_sales", "market_cap"):
            assert key in peer, f"missing required field {key}"
        assert peer["ticker"] != "AAPL"  # peer should not be self


@pytest.mark.integration
def test_get_peer_comps_unknown_ticker_returns_not_found():
    result = get_peer_comps("ZZZZNOTAREALTICKER")
    assert result == {"ticker_not_found": True}
