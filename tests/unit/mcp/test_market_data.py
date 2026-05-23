"""Integration smoke tests for the market_data MCP server (`src/mcp/market_data/server.py`).

These tests hit the LIVE yfinance API (which proxies Yahoo Finance). They are
network-dependent and marked `@pytest.mark.integration` so they can be skipped
in offline CI later (e.g. `pytest -m 'not integration'`).

We use AAPL for every test — stable, public, never delisted, plenty of news.

Run from repo root:
    pytest tests/test_market_data.py -v
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip(
    "yfinance",
    reason="market_data MCP requires yfinance; install via the MCP's uv project or `pip install yfinance`",
)

# Load this MCP's `server.py` directly by file path under a unique module
# name; bare `from server import X` collides across MCP test files because
# every MCP module is named `server` and Python caches by module name.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SERVER_PATH = _REPO_ROOT / "src/mcp/market_data/server.py"
_spec = importlib.util.spec_from_file_location("market_data_mcp_server", _SERVER_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["market_data_mcp_server"] = _module
_spec.loader.exec_module(_module)

get_news = _module.get_news
get_prices = _module.get_prices
get_real_time_quote = _module.get_real_time_quote

APPLE_TICKER = "AAPL"


@pytest.mark.integration
def test_get_prices_basic() -> None:
    """One month of daily AAPL: >=15 rows, expected fields, dates within window."""
    start = "2024-11-01"
    end = "2024-11-30"
    result = get_prices(APPLE_TICKER, start, end, interval="1d")

    assert result["ticker"] == APPLE_TICKER
    assert result["start"] == start
    assert result["end"] == end
    assert result["interval"] == "1d"

    rows = result["rows"]
    # ~21 trading days in Nov; allow some slack for holidays / partial weeks.
    assert len(rows) >= 15, f"expected >=15 daily rows in Nov 2024, got {len(rows)}"
    assert result["rowcount"] == len(rows)

    for row in rows:
        for field in ("date", "open", "close", "volume"):
            assert field in row, f"missing field {field} in row: {row}"
        # Dates within the inclusive window.
        assert start <= row["date"] <= end, (
            f"row date {row['date']} outside [{start}, {end}]"
        )
        assert isinstance(row["close"], (int, float)) and row["close"] > 0
        assert isinstance(row["volume"], (int, float)) and row["volume"] > 0


@pytest.mark.integration
def test_get_prices_interval_weekly() -> None:
    """3-month window at weekly interval: ~12 rows (allow 10–14)."""
    start = "2024-09-01"
    end = "2024-11-30"
    result = get_prices(APPLE_TICKER, start, end, interval="1wk")

    assert result["interval"] == "1wk"
    rows = result["rows"]
    assert 10 <= len(rows) <= 14, (
        f"expected ~12 weekly rows in 3-month window, got {len(rows)}"
    )
    for row in rows:
        assert row["close"] > 0


@pytest.mark.integration
def test_get_news_basic() -> None:
    """AAPL news: >=1 item, items have title and publish_time."""
    result = get_news(APPLE_TICKER)

    assert result["ticker"] == APPLE_TICKER
    items = result["items"]
    assert len(items) >= 1, "expected at least one AAPL news item"
    assert result["rowcount"] == len(items)

    for item in items:
        assert "title" in item and item["title"], f"empty title in: {item}"
        assert "publish_time" in item, f"missing publish_time in: {item}"


@pytest.mark.integration
def test_get_real_time_quote() -> None:
    """AAPL quote: last_price > 0 and as_of is a recent ISO timestamp."""
    result = get_real_time_quote(APPLE_TICKER)

    assert result["ticker"] == APPLE_TICKER
    last_price = result["last_price"]
    assert isinstance(last_price, (int, float)) and last_price > 0, (
        f"expected positive last_price, got {last_price!r}"
    )

    # as_of should be ISO-parseable and within the last hour (we just stamped it).
    as_of_str = result["as_of"]
    # Strip trailing 'Z' to use fromisoformat.
    parsed = _dt.datetime.fromisoformat(as_of_str.replace("Z", "+00:00"))
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    delta = abs((now - parsed).total_seconds())
    assert delta < 3600, (
        f"as_of timestamp {as_of_str} is not recent (delta={delta}s)"
    )

    assert result["currency"], "expected non-empty currency"
