"""Regression tests for the EDGAR-XBRL-backed fundamentals MCP.

Pins the PIT-correctness invariant: when filtered by `filed`-date, the
fundamentals snapshot reflects only what was publicly known on the as-of
date — no look-ahead via restatements. This is the core property that
lets us drop the Sharadar dependency.

Tests use synthetic XBRL fact dicts (no live API call) so they run in CI.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_fundamentals():
    """Load the fundamentals MCP module by file path (avoids name collision
    with other server.py modules in the test process)."""
    spec = importlib.util.spec_from_file_location(
        "fundamentals_mcp_under_test",
        _REPO_ROOT / "src/mcp/fundamentals/server.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fundamentals_mcp_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_pit_filter_picks_latest_fact_filed_before_as_of():
    mod = _load_fundamentals()
    # Three facts: original Q3 filing, original Q4 filing, restated Q3 (filed 2y later).
    units = {
        "USD": [
            {"end": "2020-09-30", "val": 100, "filed": "2020-10-30", "fy": 2020, "fp": "Q3"},
            {"end": "2020-12-31", "val": 110, "filed": "2021-01-30", "fy": 2020, "fp": "Q4"},
            # RESTATEMENT of Q3 — filed two years later, value adjusted
            {"end": "2020-09-30", "val": 95, "filed": "2022-01-30", "fy": 2020, "fp": "Q3/R"},
        ]
    }
    # As of 2020-12-15: only the original Q3 filing is visible.
    pit = mod._pit_value(units, _dt.date(2020, 12, 15))
    assert pit["val"] == 100, "must return AS-FILED Q3 value, not restated"
    assert pit["filed"] == "2020-10-30"

    # As of 2021-06-30: Q3 + Q4 filings visible; pick most recent end-date (Q4).
    pit = mod._pit_value(units, _dt.date(2021, 6, 30))
    assert pit["val"] == 110, "must return Q4 (latest end-date among filings <= as_of)"

    # As of 2024-01-01: restatement is now public; pick the LATEST end-date
    # among all filings — but Q4 (110) has end 2020-12-31, restatement has
    # end 2020-09-30. So Q4 still wins on end-date sort.
    pit = mod._pit_value(units, _dt.date(2024, 1, 1))
    assert pit["val"] == 110


def test_pit_filter_returns_none_when_no_facts_filed_yet():
    mod = _load_fundamentals()
    units = {"USD": [{"end": "2020-12-31", "val": 100, "filed": "2021-01-30"}]}
    # As-of date is BEFORE any filing.
    pit = mod._pit_value(units, _dt.date(2020, 6, 30))
    assert pit is None


def test_pit_filter_handles_unit_priority_usd_first():
    mod = _load_fundamentals()
    # USD/shares appears alongside USD; we should prefer USD.
    units = {
        "USD/shares": [{"end": "2023-09-30", "val": 5.5, "filed": "2023-11-03"}],
        "USD": [{"end": "2023-09-30", "val": 96e9, "filed": "2023-11-03"}],
    }
    pit = mod._pit_value(units, _dt.date(2024, 1, 1))
    assert pit["_unit"] == "USD"
    assert pit["val"] == 96e9


def test_pit_filter_falls_back_to_secondary_unit_when_usd_empty():
    mod = _load_fundamentals()
    units = {
        "USD/shares": [{"end": "2023-09-30", "val": 5.5, "filed": "2023-11-03"}],
    }
    pit = mod._pit_value(units, _dt.date(2024, 1, 1))
    assert pit["_unit"] == "USD/shares"
    assert pit["val"] == 5.5


def test_pit_filter_skips_entries_with_malformed_filed_dates():
    mod = _load_fundamentals()
    units = {
        "USD": [
            {"end": "2020-09-30", "val": 100, "filed": "not-a-date"},
            {"end": "2021-09-30", "val": 200, "filed": "2021-11-03"},
        ]
    }
    pit = mod._pit_value(units, _dt.date(2024, 1, 1))
    assert pit["val"] == 200, "malformed date must be skipped, not crash"


def test_get_fundamentals_invalid_as_of_date_raises():
    mod = _load_fundamentals()
    with pytest.raises(ValueError, match="ISO"):
        mod.get_fundamentals("AAPL", "not-a-date")


def test_get_delistings_returns_error_when_polygon_key_missing(monkeypatch):
    mod = _load_fundamentals()
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    result = mod.get_delistings("AAPL")
    assert result["active"] is None
    assert "POLYGON_API_KEY" in result["error"]
    assert result["source"] == "polygon_reference"


def test_primary_tags_contain_load_bearing_metrics():
    """Pin the curated tag list to what skills depend on. If a skill
    starts depending on a new XBRL tag, add it explicitly here."""
    mod = _load_fundamentals()
    # Subset that memo generation + kill-criteria + mode classifier consume.
    must_have = {
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "NetIncomeLoss",
        "EarningsPerShareDiluted",
        "Assets",
        "Liabilities",
        "StockholdersEquity",
        "CashAndCashEquivalentsAtCarryingValue",
        "CommonStockSharesOutstanding",
    }
    actual = set(mod._PRIMARY_TAGS)
    missing = must_have - actual
    assert not missing, f"_PRIMARY_TAGS missing load-bearing metrics: {missing}"
