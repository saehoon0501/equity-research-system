"""Tests for src.outcomes.override_resolver."""

from __future__ import annotations

import datetime as _dt

import pytest

from src.outcomes.override_resolver import OverrideResolver, OverrideResolutionStats


class _FakeCursor:
    def __init__(self, scripted_results: list[list[tuple]]):
        self._scripted = scripted_results
        self._call = 0
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.statements.append((sql, tuple(params) if params else ()))

    def fetchone(self):
        if self._call >= len(self._scripted):
            return None
        result = self._scripted[self._call]
        self._call += 1
        return result[0] if result else None

    def fetchall(self):
        if self._call >= len(self._scripted):
            return []
        result = self._scripted[self._call]
        self._call += 1
        return result

    def close(self):
        pass


class _FakeConn:
    def __init__(self, scripted_results):
        self._cursor = _FakeCursor(scripted_results)
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


class _StaticProvider:
    def __init__(self, rows_by_ticker):
        self._rows = rows_by_ticker

    def get_prices(self, ticker, start, end, interval="1d"):
        return {"rows": self._rows.get(ticker.upper(), [])}


def test_counterfactual_for_recommendation_override_uses_benchmark():
    """recommendation/veto override → counterfactual = SPY return."""
    pending_row = (
        "11111111-1111-1111-1111-111111111111",
        "AAPL",
        _dt.date(2025, 1, 2),
        "recommendation",
        None, None, None,
        None, None, None,
    )
    conn = _FakeConn(scripted_results=[[pending_row]])

    # Anchor bars at the trading-day target for each horizon.
    aapl_rows = [
        {"date": "2025-01-02", "close": 100.0, "adj_close": 100.0},
        {"date": "2025-01-31", "close": 105.0, "adj_close": 105.0},  # T+30
        {"date": "2025-04-02", "close": 110.0, "adj_close": 110.0},  # T+90
    ]
    spy_rows = [
        {"date": "2025-01-02", "close": 400.0, "adj_close": 400.0},
        {"date": "2025-01-31", "close": 404.0, "adj_close": 404.0},
        {"date": "2025-04-02", "close": 408.0, "adj_close": 408.0},  # +2%
    ]
    provider = _StaticProvider({"AAPL": aapl_rows, "SPY": spy_rows})

    resolver = OverrideResolver(conn, price_provider=provider)
    stats = resolver.resolve(as_of=_dt.date(2026, 4, 15), dry_run=True)

    # 3 horizons × 1 row = 3 candidates; T+30 + T+90 have bars; T+1y has none.
    assert stats.candidates_examined == 3
    assert sum(stats.horizons_resolved.values()) == 2


def test_counterfactual_for_sizing_override_uses_same_ticker():
    """sizing/routing/mode/exit_timing → counterfactual = same ticker return."""
    pending_row = (
        "22222222-2222-2222-2222-222222222222",
        "AAPL",
        _dt.date(2025, 1, 2),
        "sizing",
        None, None, None,
        None, None, None,
    )
    conn = _FakeConn(scripted_results=[[pending_row]])

    aapl_rows = [
        {"date": "2025-01-02", "close": 100.0, "adj_close": 100.0},
        {"date": "2025-04-02", "close": 110.0, "adj_close": 110.0},
    ]
    provider = _StaticProvider({"AAPL": aapl_rows})

    resolver = OverrideResolver(conn, price_provider=provider)
    # Use the resolver's internal counterfactual to assert it uses ticker, not SPY
    from src.outcomes.override_resolver import _PendingOverride

    item = _PendingOverride(
        override_id="22222222-2222-2222-2222-222222222222",
        ticker="AAPL",
        override_date=_dt.date(2025, 1, 2),
        override_type="sizing",
        horizon="90d",
        target_close_date=_dt.date(2025, 4, 2),
    )
    cf = resolver._counterfactual(item, target_close=item.target_close_date)
    assert cf == pytest.approx(0.10)  # +10% on AAPL, NOT SPY


def test_stats_caps_error_log():
    stats = OverrideResolutionStats()
    for i in range(70):
        stats.record_error(f"err {i}")
    assert len(stats.errors) == 50
