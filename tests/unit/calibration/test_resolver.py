"""Resolver — PIT, idempotency, delisted total-return, multi-horizon clustering.

NO live DB/API: a FakePriceClient serves frozen price series and applies the
same as_of PIT guard the real market_data server does; a FakeOutcomeStore is an
in-memory dict.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.calibration import resolver as R
from src.calibration.resolver import PendingOutcome


# --------------------------------------------------------------------------- #
# Fakes                                                                        #
# --------------------------------------------------------------------------- #
class FakePriceClient:
    """Serves frozen {ticker: [(date_iso, total_return_close)]} series.

    Mirrors the real server: applies the as_of PIT guard (drops bars > as_of),
    and surfaces total_return_close when mode='total_return'. Records every
    (ticker, as_of) call so tests can assert PIT was honoured.
    """

    def __init__(self, series: dict[str, list[tuple[str, float]]]):
        self._series = series
        self.calls: list[dict] = []

    def get_prices(self, ticker, start, end, interval="1d", mode="split_only", as_of=None):
        self.calls.append({"ticker": ticker, "as_of": as_of, "mode": mode, "end": end})
        rows = []
        for d, px in self._series.get(ticker, []):
            if d < start or d > end:
                continue
            rows.append(
                {
                    "date": d,
                    "close": px,
                    "total_return_close": px if mode == "total_return" else None,
                }
            )
        # PIT guard — exactly like server.py.
        if as_of is not None:
            rows = [r for r in rows if r["date"] <= as_of]
        return {"ticker": ticker, "rows": rows, "rowcount": len(rows), "mode": mode, "as_of": as_of}


class FakeOutcomeStore:
    """In-memory recommendation_outcomes — ONE row per rec_id (UNIQUE rec_id).

    ``upsert_outcome`` overwrites the single row keyed by rec_id, mirroring the
    production ``INSERT ... ON CONFLICT (recommendation_id) DO UPDATE``.

    IMMUTABILITY ENFORCEMENT (mig-045): the resolver must NEVER write
    benchmark_return_* / delta_vs_benchmark_* on an UPDATE — they are immutable
    and the real DB's STATE-guard would RAISE. This fake mirrors that contract by
    capturing any UNEXPECTED kwarg in ``**forbidden`` and raising, so a regression
    that re-adds ``benchmark_returns=...`` (or any other immutable column) to the
    resolver's upsert call is caught OFFLINE — no live DB needed.
    """

    def __init__(self, pending):
        self._pending = list(pending)
        # rec_id -> single written row dict (one row per rec, like the DB)
        self.written: dict[str, dict] = {}
        self.upsert_calls = 0

    def fetch_pending(self):
        return list(self._pending)

    def upsert_outcome(
        self,
        *,
        rec_id,
        ticker,
        primary_horizon,
        label_binary,
        excess_return,
        label_method_version,
        ticker_returns,
        ticker_close_dates,
        **forbidden,
    ):
        if forbidden:
            # Mirrors the mig-045 STATE-guard: writing an immutable column on
            # UPDATE raises. benchmark_return_* / delta_vs_benchmark_* land here.
            raise AssertionError(
                "resolver attempted to write immutable column(s): "
                f"{sorted(forbidden)}"
            )
        self.upsert_calls += 1
        self.written[rec_id] = {  # ON CONFLICT DO UPDATE: overwrite the one row
            "ticker": ticker,
            "primary_horizon": primary_horizon,
            "label_binary": label_binary,
            "excess_return": excess_return,
            "label_method_version": label_method_version,
            "ticker_returns": dict(ticker_returns),
            "ticker_close_dates": dict(ticker_close_dates),
        }


def _daily_series(start_iso: str, n: int, start_px: float, step: float):
    d0 = date.fromisoformat(start_iso)
    return [((d0 + timedelta(days=i)).isoformat(), start_px + i * step) for i in range(n)]


# --------------------------------------------------------------------------- #
# Criterion 1 — PIT + idempotency                                              #
# --------------------------------------------------------------------------- #
class TestPointInTime:
    def test_all_reads_are_pit_le_resolve_at(self):
        # 30d window: rec 2024-01-01 -> resolve 2024-01-31. Provide bars THROUGH
        # 2024-03-01 (look-ahead temptation); resolver must never read past 01-31.
        ticker_series = _daily_series("2023-12-25", 70, 100.0, 1.0)
        spy_series = _daily_series("2023-12-25", 70, 200.0, 0.5)
        client = FakePriceClient({"FOO": ticker_series, "SPY": spy_series})
        store = FakeOutcomeStore(
            [PendingOutcome("rec-1", "FOO", date(2024, 1, 1), "tactical")]
        )
        result = R.run_resolver(store, client, today=date(2024, 6, 1))
        assert result.n_resolved == 1
        resolve_at = "2024-01-31"
        for call in client.calls:
            assert call["as_of"] == resolve_at
            assert call["end"] <= resolve_at  # never fetch past resolve_at
            assert call["mode"] == "total_return"  # P0-7 total return basis

    def test_idempotent_rerun_on_same_store_writes_identical_values(self):
        # True idempotency: re-run against the SAME store. The single rec row is
        # overwritten with bit-identical values; upsert fires again (ON CONFLICT
        # DO UPDATE) but the row content is unchanged.
        client = FakePriceClient(
            {
                "FOO": _daily_series("2023-12-25", 70, 100.0, 1.0),
                "SPY": _daily_series("2023-12-25", 70, 200.0, 0.5),
            }
        )
        pending = [PendingOutcome("rec-1", "FOO", date(2024, 1, 1), "tactical")]
        store = FakeOutcomeStore(pending)
        R.run_resolver(store, client, today=date(2024, 6, 1))
        first = dict(store.written["rec-1"])
        R.run_resolver(store, client, today=date(2024, 6, 1))  # re-run, same store
        assert store.written["rec-1"] == first  # identical values
        assert len(store.written) == 1  # still exactly one row per rec_id
        assert store.upsert_calls == 2  # UPSERT fired twice, content unchanged

    def test_label_is_beat_benchmark(self):
        # FOO rises faster than SPY -> beats benchmark -> label True, excess > 0.
        client = FakePriceClient(
            {
                "FOO": _daily_series("2023-12-25", 70, 100.0, 2.0),
                "SPY": _daily_series("2023-12-25", 70, 200.0, 0.2),
            }
        )
        store = FakeOutcomeStore(
            [PendingOutcome("rec-1", "FOO", date(2024, 1, 1), "tactical")]
        )
        r = R.run_resolver(store, client, today=date(2024, 6, 1))
        lab = r.resolved[0]
        assert lab.label_binary is True
        assert lab.excess_return > 0
        assert lab.label_method_version == R.LABEL_METHOD_VERSION

    def test_window_not_closed_is_deferred_not_skipped(self):
        # today before resolve_at -> deferred (NOT silently dropped, NOT written).
        client = FakePriceClient(
            {"FOO": _daily_series("2023-12-25", 70, 100.0, 1.0), "SPY": _daily_series("2023-12-25", 70, 200.0, 0.5)}
        )
        store = FakeOutcomeStore(
            [PendingOutcome("rec-1", "FOO", date(2024, 1, 1), "tactical")]
        )
        r = R.run_resolver(store, client, today=date(2024, 1, 10))
        assert r.n_resolved == 0
        assert r.n_deferred == 1
        assert r.deferred[0].reason == "window_not_yet_closed"
        assert store.upsert_calls == 0


# --------------------------------------------------------------------------- #
# Criterion 2 — delisted FSR via total-return + multi-horizon clustering       #
# --------------------------------------------------------------------------- #
class TestDelistedAndMultiHorizon:
    def test_delisted_fsr_resolves_via_total_return(self):
        # FSR delists mid-window: its series stops before resolve_at, but the
        # last available total-return bar is used (not dropped). >=2 bars exist.
        fsr = _daily_series("2023-12-28", 20, 50.0, -1.0)  # declining then delisted
        spy = _daily_series("2023-12-25", 70, 200.0, 0.5)
        client = FakePriceClient({"FSR": fsr, "SPY": spy})
        store = FakeOutcomeStore(
            [PendingOutcome("rec-fsr", "FSR", date(2024, 1, 1), "tactical")]
        )
        r = R.run_resolver(store, client, today=date(2024, 6, 1))
        assert r.n_resolved == 1, r.deferred
        lab = r.resolved[0]
        assert lab.ticker == "FSR"
        # FSR fell while SPY rose -> did NOT beat benchmark.
        assert lab.label_binary is False
        # Confirm total-return mode was requested for the delisted name.
        assert all(c["mode"] == "total_return" for c in client.calls if c["ticker"] == "FSR")

    def test_fundamental_multi_horizon_clustered_in_one_row_per_rec_id(self):
        # fundamental -> resolve 90d AND 1y, consolidated into ONE row per rec_id
        # (recommendation_outcomes has UNIQUE recommendation_id). Both t_plus_*
        # returns are backfilled on that single row; the row LABEL is the primary
        # (90d) horizon.
        client = FakePriceClient(
            {
                "BAR": _daily_series("2023-12-25", 400, 100.0, 0.5),
                "SPY": _daily_series("2023-12-25", 400, 200.0, 0.4),
            }
        )
        store = FakeOutcomeStore(
            [PendingOutcome("rec-bar", "BAR", date(2024, 1, 1), "fundamental")]
        )
        r = R.run_resolver(store, client, today=date(2025, 6, 1))
        # Exactly one resolved row, clustered under the one rec_id.
        clustered = r.by_rec_id()
        assert set(clustered.keys()) == {"rec-bar"}
        assert len(clustered["rec-bar"]) == 1  # one consolidated row, not two
        row = clustered["rec-bar"][0]
        assert row.primary_horizon == "90d"  # fundamental primary
        # Both horizon legs resolved (drives t_plus_90d_return + t_plus_1y_return).
        assert {leg.horizon for leg in row.legs} == {"90d", "1y"}
        # Store: ONE row per rec_id, carrying BOTH t_plus_* returns.
        assert len(store.written) == 1
        written = store.written["rec-bar"]
        assert set(written["ticker_returns"].keys()) == {"90d", "1y"}
        # benchmark_return_* is IMMUTABLE (mig-045) — the resolver never writes it,
        # so the row carries no benchmark_returns key.
        assert "benchmark_returns" not in written
        # t_plus_*_close_date columns are backfilled per horizon (PIT resolve_at).
        assert set(written["ticker_close_dates"].keys()) == {"90d", "1y"}
        assert written["ticker_close_dates"]["90d"] == "2024-03-31"  # 2024-01-01 + 90d
        assert written["primary_horizon"] == "90d"
        assert store.upsert_calls == 1  # single UPSERT for the rec

    def test_insufficient_history_deferred_not_skipped(self):
        # Only one bar -> cannot compute a return -> deferred, never written.
        client = FakePriceClient(
            {"FOO": [("2024-01-01", 100.0)], "SPY": _daily_series("2023-12-25", 70, 200.0, 0.5)}
        )
        store = FakeOutcomeStore(
            [PendingOutcome("rec-1", "FOO", date(2024, 1, 1), "tactical")]
        )
        r = R.run_resolver(store, client, today=date(2024, 6, 1))
        assert r.n_resolved == 0
        assert r.n_deferred == 1
        assert "insufficient_pit_history" in r.deferred[0].reason
        assert store.upsert_calls == 0


class TestPITAssertGuard:
    def test_internal_pit_assert_catches_lookahead(self):
        # A misbehaving client that ignores as_of must trip the resolver's own
        # PIT assertion rather than producing a label from look-ahead data.
        class LeakyClient:
            def get_prices(self, ticker, start, end, interval="1d", mode="split_only", as_of=None):
                # ignores as_of -> returns a bar dated AFTER as_of.
                return {
                    "rows": [
                        {"date": "2024-01-15", "close": 100.0, "total_return_close": 100.0},
                        {"date": "2099-01-01", "close": 999.0, "total_return_close": 999.0},
                    ]
                }

        store = FakeOutcomeStore(
            [PendingOutcome("rec-1", "FOO", date(2024, 1, 1), "tactical")]
        )
        with pytest.raises(AssertionError, match="PIT violation"):
            R.run_resolver(store, LeakyClient(), today=date(2024, 6, 1))


# --------------------------------------------------------------------------- #
# Regression — confirmed idempotency / PIT bugs (BUG 1/2/3)                     #
# --------------------------------------------------------------------------- #
class TestImmutabilityRegression:
    """BUG 1: the resolver must not write the immutable benchmark_return_* columns.

    The FakeOutcomeStore raises on any unexpected kwarg, mirroring the mig-045
    STATE-guard. So if the resolver re-adds ``benchmark_returns=...`` the second
    (or first) resolve raises here, OFFLINE.
    """

    def test_resolve_never_writes_benchmark_returns_and_is_idempotent(self):
        client = FakePriceClient(
            {
                "FOO": _daily_series("2023-12-25", 70, 100.0, 1.0),
                "SPY": _daily_series("2023-12-25", 70, 200.0, 0.5),
            }
        )
        store = FakeOutcomeStore(
            [PendingOutcome("rec-1", "FOO", date(2024, 1, 1), "tactical")]
        )
        # First resolve: must not attempt to write any immutable column.
        R.run_resolver(store, client, today=date(2024, 6, 1))
        first = dict(store.written["rec-1"])
        assert "benchmark_returns" not in first
        # excess_return is still computed (benchmark folded in transiently).
        assert "excess_return" in first
        # Re-resolve on the SAME store: identical values, still no immutable write
        # (the fake would raise on an UPDATE touching benchmark_return_*).
        R.run_resolver(store, client, today=date(2024, 6, 1))
        assert store.written["rec-1"] == first
        assert "benchmark_returns" not in store.written["rec-1"]
        assert store.upsert_calls == 2  # UPSERT fired twice, content identical


class TestWindowClosedGuard:
    """BUG 2: ``today`` defaults to date.today() so an unclosed window DEFERS."""

    def test_unclosed_window_defers_nothing_written(self):
        # 30d window: rec 2024-01-01 -> resolve_at 2024-01-31; today is BEFORE it.
        client = FakePriceClient(
            {
                "FOO": _daily_series("2023-12-25", 70, 100.0, 1.0),
                "SPY": _daily_series("2023-12-25", 70, 200.0, 0.5),
            }
        )
        store = FakeOutcomeStore(
            [PendingOutcome("rec-1", "FOO", date(2024, 1, 1), "tactical")]
        )
        r = R.run_resolver(store, client, today=date(2024, 1, 15))
        assert r.n_resolved == 0
        assert r.n_deferred == 1
        assert r.deferred[0].reason == "window_not_yet_closed"
        assert store.upsert_calls == 0
        assert store.written == {}

    def test_closed_window_resolves(self):
        client = FakePriceClient(
            {
                "FOO": _daily_series("2023-12-25", 70, 100.0, 1.0),
                "SPY": _daily_series("2023-12-25", 70, 200.0, 0.5),
            }
        )
        store = FakeOutcomeStore(
            [PendingOutcome("rec-1", "FOO", date(2024, 1, 1), "tactical")]
        )
        r = R.run_resolver(store, client, today=date(2024, 2, 1))  # past resolve_at
        assert r.n_resolved == 1
        assert r.n_deferred == 0
        assert store.upsert_calls == 1

    def test_default_today_is_used_when_omitted(self):
        # With today omitted, an unclosed FUTURE window must still defer — proving
        # the guard is active (BUG 2 regression: a None default disabled it).
        future_rec = date.today() + timedelta(days=5)
        client = FakePriceClient(
            {
                "FOO": _daily_series(future_rec.isoformat(), 70, 100.0, 1.0),
                "SPY": _daily_series(future_rec.isoformat(), 70, 200.0, 0.5),
            }
        )
        store = FakeOutcomeStore(
            [PendingOutcome("rec-1", "FOO", future_rec, "tactical")]
        )
        r = R.run_resolver(store, client)  # today defaults to date.today()
        assert r.n_resolved == 0
        assert r.n_deferred == 1
        assert r.deferred[0].reason == "window_not_yet_closed"
        assert store.upsert_calls == 0


class TestDuplicateDateDedup:
    """BUG 3: same-date bars are deduped deterministically before entry pick."""

    def test_duplicate_same_date_bars_order_independent(self):
        spy = _daily_series("2023-12-25", 70, 200.0, 0.5)
        base = _daily_series("2023-12-25", 70, 100.0, 1.0)
        # Inject a duplicate for the entry date (2024-01-01) with a different price.
        dup_a = ("2024-01-01", 111.0)
        dup_b = ("2024-01-01", 222.0)

        def build(order):
            series = list(base) + list(order)
            return FakePriceClient({"FOO": series, "SPY": spy})

        results = []
        for order in ([dup_a, dup_b], [dup_b, dup_a]):
            store = FakeOutcomeStore(
                [PendingOutcome("rec-1", "FOO", date(2024, 1, 1), "tactical")]
            )
            R.run_resolver(store, build(order), today=date(2024, 6, 1))
            results.append(dict(store.written["rec-1"]))

        # Identical excess_return / label regardless of duplicate arrival order.
        assert results[0]["excess_return"] == results[1]["excess_return"]
        assert results[0]["label_binary"] == results[1]["label_binary"]
        assert results[0]["ticker_returns"] == results[1]["ticker_returns"]
