"""Unit tests for src.outcomes.resolver.

Covers the trading-day anchoring logic and the resolver state machine
without touching live Postgres or Polygon. Resolver._select_pending and
Resolver._upsert are exercised against a hand-rolled fake DB connection
that records statements and supplies canned rows.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from src.outcomes.resolver import (
    Resolver,
    _first_close_on_or_after,
    _last_close_on_or_before,
)


# --------------------------------------------------------------------------- #
# Anchoring helpers                                                           #
# --------------------------------------------------------------------------- #


def test_first_close_on_or_after_skips_weekend():
    rows = [
        {"date": "2026-01-02", "close": 100.0, "adj_close": 100.0},  # Fri
        {"date": "2026-01-05", "close": 101.0, "adj_close": 101.0},  # Mon
        {"date": "2026-01-06", "close": 102.0, "adj_close": 102.0},
    ]
    # Sat → first bar ≥ Sat is Mon
    got = _first_close_on_or_after(rows, _dt.date(2026, 1, 3))
    assert got == 101.0


def test_last_close_on_or_before_includes_target():
    rows = [
        {"date": "2026-01-02", "close": 100.0, "adj_close": 100.0},
        {"date": "2026-01-05", "close": 101.0, "adj_close": 101.0},
        {"date": "2026-01-06", "close": 102.0, "adj_close": 102.0},
    ]
    got = _last_close_on_or_before(rows, _dt.date(2026, 1, 5))
    assert got == 101.0


def test_last_close_on_or_before_walks_back_for_weekend_target():
    rows = [
        {"date": "2026-01-02", "close": 100.0, "adj_close": 100.0},  # Fri
        {"date": "2026-01-05", "close": 101.0, "adj_close": 101.0},  # Mon
    ]
    # Sun target → last bar ≤ Sun is Fri close
    got = _last_close_on_or_before(rows, _dt.date(2026, 1, 4))
    assert got == 100.0


def test_anchors_return_none_when_window_has_no_bars():
    assert _first_close_on_or_after([], _dt.date(2026, 1, 1)) is None
    assert _last_close_on_or_before([], _dt.date(2026, 1, 1)) is None


# --------------------------------------------------------------------------- #
# Fake DB + provider                                                          #
# --------------------------------------------------------------------------- #


class _FakeCursor:
    def __init__(self, scripted_results: list[list[tuple]]):
        self._scripted = scripted_results
        self._call = 0
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params=()):
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
    def __init__(self, scripted_results: list[list[tuple]]):
        self._cursor = _FakeCursor(scripted_results)
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


class _StaticProvider:
    """Provider stub returning a fixed price series for any ticker."""

    def __init__(self, rows_by_ticker: dict[str, list[dict]]):
        self._rows = rows_by_ticker

    def get_prices(self, ticker, start, end, interval="1d"):
        return {"rows": self._rows.get(ticker.upper(), [])}


# --------------------------------------------------------------------------- #
# Pending-selection                                                           #
# --------------------------------------------------------------------------- #


def test_select_pending_emits_only_closed_unresolved_horizons():
    # One recommendation, recommended on 2025-01-01.
    # As-of = 2026-04-15: T+30d closed, T+90d closed, T+1y closed.
    # But ro row already populated T+30d → only 90d + 1y should emit.
    rec_row = (
        "11111111-1111-1111-1111-111111111111",  # recommendation_id
        "AAPL",
        _dt.date(2025, 1, 1),  # recommendation_date
        "SPY",
        0.05,  # t_plus_30d_return populated
        None,  # t_plus_90d_return NULL
        None,  # t_plus_1y_return NULL
    )
    conn = _FakeConn(scripted_results=[[rec_row]])
    resolver = Resolver(
        conn,
        price_provider=_StaticProvider({}),
        clock=lambda: _dt.date(2026, 4, 15),
    )

    pending = resolver._select_pending(
        as_of=_dt.date(2026, 4, 15), ticker=None
    )

    horizons = sorted(p.horizon for p in pending)
    assert horizons == ["1y", "90d"]


def test_select_pending_skips_unclosed_windows():
    rec_row = (
        "22222222-2222-2222-2222-222222222222",
        "MSFT",
        _dt.date(2026, 4, 1),
        "SPY",
        None,
        None,
        None,
    )
    conn = _FakeConn(scripted_results=[[rec_row]])
    resolver = Resolver(
        conn,
        price_provider=_StaticProvider({}),
        clock=lambda: _dt.date(2026, 4, 15),
    )

    # As-of = 2026-04-15. Recommendation on 2026-04-01 → only T+30 not closed
    # yet (closes 2026-05-01). All horizons should be skipped.
    pending = resolver._select_pending(
        as_of=_dt.date(2026, 4, 15), ticker=None
    )
    assert pending == []


# --------------------------------------------------------------------------- #
# End-to-end resolve()                                                        #
# --------------------------------------------------------------------------- #


def test_resolve_dry_run_does_not_write_or_commit():
    rec_row = (
        "33333333-3333-3333-3333-333333333333",
        "AAPL",
        _dt.date(2025, 1, 2),
        "SPY",
        None,
        None,
        None,
    )
    # Cursor will be hit once (SELECT pending). No upsert executed in dry-run.
    conn = _FakeConn(scripted_results=[[rec_row]])
    # Anchor bars sit ON the trading-day target for each horizon.
    # T+30 = 2025-02-01 (Sat) → walk back to Fri 2025-01-31.
    # T+90 = 2025-04-02 (Wed, trading day).
    # T+1y = 2026-01-02 (Fri, trading day).
    aapl_rows = [
        {"date": "2025-01-02", "close": 100.0, "adj_close": 100.0},
        {"date": "2025-01-31", "close": 110.0, "adj_close": 110.0},  # T+30
        {"date": "2025-04-02", "close": 120.0, "adj_close": 120.0},  # T+90
        {"date": "2026-01-02", "close": 130.0, "adj_close": 130.0},  # T+1y
    ]
    spy_rows = [
        {"date": "2025-01-02", "close": 400.0, "adj_close": 400.0},
        {"date": "2025-01-31", "close": 408.0, "adj_close": 408.0},
        {"date": "2025-04-02", "close": 412.0, "adj_close": 412.0},
        {"date": "2026-01-02", "close": 440.0, "adj_close": 440.0},
    ]
    provider = _StaticProvider({"AAPL": aapl_rows, "SPY": spy_rows})

    resolver = Resolver(
        conn,
        price_provider=provider,
        clock=lambda: _dt.date(2026, 4, 15),
    )

    stats = resolver.resolve(dry_run=True)

    assert stats.candidates_examined == 3  # 30d + 90d + 1y
    assert stats.rows_inserted == 0
    assert stats.rows_updated == 0
    assert sum(stats.horizons_resolved.values()) == 3
    assert conn.committed is False


def test_resolve_records_per_row_errors_without_halting():
    # Two recommendations; provider raises on the first ticker.
    rec_row_a = (
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "BAD",
        _dt.date(2025, 1, 2),
        "SPY",
        None,
        None,
        None,
    )
    rec_row_b = (
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "AAPL",
        _dt.date(2025, 1, 2),
        "SPY",
        None,
        None,
        None,
    )
    # Cursor invoked once for SELECT, then never (dry_run).
    conn = _FakeConn(scripted_results=[[rec_row_a, rec_row_b]])

    class _ExplodingProvider:
        def get_prices(self, ticker, start, end, interval="1d"):
            if ticker == "BAD":
                raise RuntimeError("synthetic failure")
            return {
                "rows": [
                    {"date": "2025-01-02", "close": 100.0, "adj_close": 100.0},
                    {"date": "2025-01-31", "close": 110.0, "adj_close": 110.0},
                    {"date": "2025-04-02", "close": 120.0, "adj_close": 120.0},
                    {"date": "2026-01-02", "close": 130.0, "adj_close": 130.0},
                ]
            }

    resolver = Resolver(
        conn,
        price_provider=_ExplodingProvider(),
        clock=lambda: _dt.date(2026, 4, 15),
    )
    stats = resolver.resolve(dry_run=True)

    # 3 horizons × 2 recs = 6 candidates; BAD's 3 fail, AAPL's 3 resolve.
    assert stats.candidates_examined == 6
    assert sum(stats.horizons_resolved.values()) == 3
    assert len(stats.errors) == 3
    for line in stats.errors:
        assert "BAD" in line or "synthetic failure" in line


def test_compute_return_handles_missing_window():
    """If the price provider returns nothing in the window, return is None."""
    resolver = Resolver(
        _FakeConn(scripted_results=[]),
        price_provider=_StaticProvider({"FOO": []}),
    )
    got = resolver._compute_return(
        "FOO", _dt.date(2025, 1, 2), _dt.date(2025, 4, 2)
    )
    assert got is None


def test_compute_return_correct_arithmetic():
    rows = [
        {"date": "2025-01-02", "close": 100.0, "adj_close": 100.0},
        {"date": "2025-04-02", "close": 125.0, "adj_close": 125.0},
    ]
    resolver = Resolver(
        _FakeConn(scripted_results=[]),
        price_provider=_StaticProvider({"AAPL": rows}),
    )
    got = resolver._compute_return(
        "AAPL", _dt.date(2025, 1, 2), _dt.date(2025, 4, 2)
    )
    assert got == pytest.approx(0.25)


# --------------------------------------------------------------------------- #
# Stats                                                                       #
# --------------------------------------------------------------------------- #


def test_stats_caps_error_log_to_avoid_unbounded_memory():
    from src.outcomes.resolver import ResolutionStats, _MAX_ERRORS_RETAINED

    stats = ResolutionStats()
    for i in range(_MAX_ERRORS_RETAINED + 25):
        stats.record_error(f"err {i}")
    assert len(stats.errors) == _MAX_ERRORS_RETAINED
