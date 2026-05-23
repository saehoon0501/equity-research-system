"""Integration smoke tests for the yfinance MCP server.

Hits LIVE Yahoo Finance via the `yfinance` Python lib. Network-dependent;
mark @pytest.mark.integration when we wire up offline CI later.

Run from repo root:
    pytest tests/test_yfinance.py -v
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# Load .env so POSTGRES_* are available when this test file is invoked
# from repo root (where the env vars aren't shell-exported).
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env")

# Load the MCP server module by path; bare `from server import X` collides
# across MCP test files because every MCP module is named `server`.
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

import psycopg
from psycopg.types.json import Jsonb


def _pg_dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@localhost:{os.environ.get('POSTGRES_PORT','5432')}/{os.environ['POSTGRES_DB']}"
    )


@pytest.fixture
def clean_cache():
    """Yields a function clean_cache(endpoint, ticker) that DELETEs a single row.

    Returned function can be called multiple times in a test. Tests that need
    to clear before and inspect after both share this helper.
    """
    cleared: list[tuple[str, str]] = []

    def _clear(endpoint: str, ticker: str) -> None:
        with psycopg.connect(_pg_dsn(), autocommit=True) as conn:
            conn.execute(
                "DELETE FROM yfinance_cache WHERE endpoint=%s AND ticker=%s",
                (endpoint, ticker.upper()),
            )
        cleared.append((endpoint, ticker.upper()))

    yield _clear

    # Teardown: also clear any rows the test wrote, so re-runs are clean.
    if cleared:
        with psycopg.connect(_pg_dsn(), autocommit=True) as conn:
            for endpoint, ticker in cleared:
                conn.execute(
                    "DELETE FROM yfinance_cache WHERE endpoint=%s AND ticker=%s",
                    (endpoint, ticker),
                )


def _row_exists(endpoint: str, ticker: str) -> bool:
    with psycopg.connect(_pg_dsn(), autocommit=True) as conn:
        row = conn.execute(
            "SELECT 1 FROM yfinance_cache WHERE endpoint=%s AND ticker=%s",
            (endpoint, ticker.upper()),
        ).fetchone()
    return row is not None


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


@pytest.mark.integration
@pytest.mark.parametrize("fn_name", [
    "get_consensus_estimates",
    "get_target_prices",
    "get_calendar",
    "get_holders",
])
def test_unknown_ticker_returns_not_found_dict(fn_name):
    """All scalar-returning endpoints must return {ticker_not_found: True} consistently for unknown tickers."""
    fn = getattr(_module, fn_name)
    result = fn("ZZZZNOTAREALTICKER12345")
    assert result == {"ticker_not_found": True}, (
        f"{fn_name} did not return {{ticker_not_found: True}} for unknown ticker; "
        f"got {result!r}"
    )


@pytest.mark.integration
def test_unknown_ticker_recommendations_returns_not_found_dict():
    """get_recommendations returns list normally; for unknown ticker it returns the failure-mode dict (not a list)."""
    result = _module.get_recommendations("ZZZZNOTAREALTICKER12345")
    assert result == {"ticker_not_found": True}


@pytest.mark.integration
def test_unknown_ticker_peer_comps_returns_not_found_dict():
    """get_peer_comps returns list normally; for unknown ticker it returns the failure-mode dict (not a list)."""
    result = _module.get_peer_comps("ZZZZNOTAREALTICKER12345")
    assert result == {"ticker_not_found": True}


# ---------------------------------------------------------------------------
# Task 23: Postgres write-through cache (Migration 029)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cache_hit_returns_cached_payload(clean_cache):
    """Write a known payload directly to yfinance_cache, call endpoint, assert _cache_hit:True."""
    ticker = "AAPL"
    clean_cache("consensus_estimates", ticker)

    sentinel_payload = {
        "fy_eps_mean": 99.99,
        "fy_eps_std": None,
        "fy_revenue_mean": 1234.0,
        "fy_revenue_std": None,
        "next_q_eps_mean": 0.5,
        "next_q_revenue_mean": 0.1,
        "analyst_count": 42,
    }
    with psycopg.connect(_pg_dsn(), autocommit=True) as conn:
        conn.execute(
            "INSERT INTO yfinance_cache (endpoint, ticker, payload, ttl_seconds) "
            "VALUES (%s, %s, %s, %s)",
            ("consensus_estimates", ticker, Jsonb(sentinel_payload), 21600),
        )

    result = get_consensus_estimates(ticker)
    assert result.get("_cache_hit") is True
    # Sentinel value proves we got the cached row, not a live fetch.
    assert result.get("fy_eps_mean") == 99.99
    assert result.get("analyst_count") == 42


@pytest.mark.integration
def test_cache_miss_then_hit_roundtrip(clean_cache):
    """Clear cache, call endpoint (live), then call again, assert second has _cache_hit:True."""
    ticker = "AAPL"
    clean_cache("target_prices", ticker)

    first = get_target_prices(ticker)
    # First call is a live fetch — no cache_hit marker.
    assert "_cache_hit" not in first or first.get("_cache_hit") is not True

    # Row must now exist
    assert _row_exists("target_prices", ticker)

    second = get_target_prices(ticker)
    assert second.get("_cache_hit") is True
    # Cached payload should mirror the live fetch's required fields.
    for key in (
        "target_high",
        "target_low",
        "target_mean",
        "target_median",
        "number_of_analyst_opinions",
        "recommendation_mean",
        "recommendation_key",
    ):
        assert key in second


@pytest.mark.integration
def test_cache_skips_ticker_not_found(clean_cache):
    """Bogus ticker must not produce a yfinance_cache row."""
    ticker = "ZZZZZ"
    clean_cache("consensus_estimates", ticker)

    result = get_consensus_estimates(ticker)
    assert result == {"ticker_not_found": True}
    # No row written for the unknown ticker.
    assert not _row_exists("consensus_estimates", ticker)


@pytest.mark.integration
def test_cache_respects_ttl_expiry(clean_cache):
    """Write a stale row (fetched_at = NOW() - 1 day) with ttl=21600 (6h); endpoint should miss."""
    ticker = "AAPL"
    clean_cache("consensus_estimates", ticker)

    stale_sentinel = {
        "fy_eps_mean": -1.0,       # sentinel that would never come from real fetch
        "fy_eps_std": None,
        "fy_revenue_mean": -1.0,
        "fy_revenue_std": None,
        "next_q_eps_mean": -1.0,
        "next_q_revenue_mean": -1.0,
        "analyst_count": -1,
    }
    with psycopg.connect(_pg_dsn(), autocommit=True) as conn:
        conn.execute(
            "INSERT INTO yfinance_cache (endpoint, ticker, payload, fetched_at, ttl_seconds) "
            "VALUES (%s, %s, %s, NOW() - INTERVAL '1 day', %s)",
            ("consensus_estimates", ticker, Jsonb(stale_sentinel), 21600),
        )

    result = get_consensus_estimates(ticker)
    # Result must NOT be the stale sentinel — proves miss.
    assert result.get("_cache_hit") is not True
    assert result.get("fy_eps_mean") != -1.0
    # The required schema fields should be present (from a live fetch).
    for key in (
        "fy_eps_mean",
        "fy_revenue_mean",
        "next_q_eps_mean",
        "next_q_revenue_mean",
        "analyst_count",
    ):
        assert key in result
