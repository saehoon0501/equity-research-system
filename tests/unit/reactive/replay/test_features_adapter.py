"""Unit tests for the Replay-Harness daily feature adapter (Task 2.1).

NON-BEHAVIORAL drive-not-reimplement tests. The adapter (`features_adapter`)
assembles the daily feature inputs the landed `compute_features` consumes and
DRIVES it — it owns no feature math. These tests therefore assert the *seam*
(compute_features is invoked with the assembled arrays) and the two
point-in-time correctness rules the adapter DOES own, riding the R9.2
`FixtureDataPort` isolation seam (no network/DB/LLM):

  - Requirement 3 AC 3.1 — only data timestamped ≤ the as-of day D feeds the
    features (no bar dated > D reaches `compute_features`).
  - Requirement 4 AC 4.2 (design "Core algorithms #4", the as-of split rule) —
    the DataPort serves `adjusted=false` raw bars; the adapter split-adjusts the
    feature-window prices for splits with ex-date (Polygon `execution_date`) ≤ D
    ONLY. An in-window pre-D split IS applied to the pre-ex-date bars (so
    momentum is continuous); a post-D split is NEVER applied (that would be
    look-ahead). The full OHLC of a pre-ex-date bar is adjusted (not just close)
    so `_atr` over the same bars does not spike across the split.

The seam is asserted via a SPY on `compute_features` patched WHERE IT IS BOUND
(`src.reactive.replay.features_adapter.compute_features`); the spy captures the
assembled `ticker_bars`/`spy_close` and returns a sentinel `FeatureSet`, so the
tests assert on the captured arrays without fighting the landed 252-bar
`insufficient_history` gate.

Source of truth: requirements.md R3 AC 3.1, R4 AC 4.2; design.md "Core
algorithms #4 (as-of split rule)" + the `features_adapter` references
(File Structure Plan / Components table row 170 / Traceability row 155).

Requirements: 3.1, 4.2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.reactive.features import FeatureSet
from src.reactive.replay import features_adapter
from src.reactive.replay.features_adapter import compute_daily_features

from tests.unit.reactive.replay._fixtures import FixtureDataPort


# --- helpers ---------------------------------------------------------------- #


def _epoch_ms(iso_date: str) -> int:
    """The Polygon aggregate ``t`` (epoch MILLIseconds, UTC midnight) for a date."""
    d = datetime.fromisoformat(iso_date).replace(tzinfo=timezone.utc)
    return int(d.timestamp()) * 1_000


def _bar(iso_date: str, *, o: float, h: float, l: float, c: float, v: float = 1.0) -> dict:
    """A raw Massive-wire daily bar (keys ``t/o/h/l/c/v``; ``t`` epoch ms)."""
    return {"t": _epoch_ms(iso_date), "o": o, "h": h, "l": l, "c": c, "v": v}


_SENTINEL = FeatureSet(
    trend_vote=1.0, flow_vote=0.5, meanrev_vote=0.0, trend_strength=0.5, raw={}
)


class _SpyPort(FixtureDataPort):
    """A `FixtureDataPort` whose daily bars / splits are injectable per symbol."""

    def __init__(
        self,
        *,
        ticker_bars: list[dict],
        spy_bars: list[dict],
        splits: list[dict] | None = None,
        rf_yield: float = 4.25,
    ) -> None:
        super().__init__(rf_yield=rf_yield)
        self._ticker_bars = ticker_bars
        self._spy_bars = spy_bars
        self._splits = splits or []

    def fetch_daily_bars(self, symbol: str, start: str, end: str) -> list[dict]:
        bars = self._spy_bars if symbol.upper() == "SPY" else self._ticker_bars
        return [dict(b) for b in bars]

    def fetch_corporate_actions(self, symbol: str, start: str, end: str) -> dict:
        # SPY carries no splits in these fixtures (the ticker leg owns the split).
        splits = [] if symbol.upper() == "SPY" else [dict(s) for s in self._splits]
        return {"splits": splits, "dividends": []}


def _install_spy(monkeypatch: Any) -> dict:
    """Patch `compute_features` WHERE BOUND; capture its call args; return a dict."""
    captured: dict = {}

    def _spy(ticker_bars, spy_close, rf_yield_pct, atr_period=14):
        captured["ticker_bars"] = list(ticker_bars)
        captured["spy_close"] = list(spy_close)
        captured["rf_yield_pct"] = rf_yield_pct
        captured["atr_period"] = atr_period
        captured["call_count"] = captured.get("call_count", 0) + 1
        return _SENTINEL

    monkeypatch.setattr(features_adapter, "compute_features", _spy)
    return captured


def _closes(bars: list[dict]) -> list[float]:
    return [b["close"] for b in bars]


# --- the drive-not-reimplement seam (3.1) ----------------------------------- #


def test_drives_compute_features_and_returns_its_result(monkeypatch) -> None:
    """The adapter invokes the landed `compute_features` and returns its output.

    Drive-not-reimplement (Task 2.1 boundary / design Traceability 3.1): the
    adapter assembles inputs and DELEGATES. The spy proves the call happened and
    the adapter passes the result straight back (the sentinel `FeatureSet`).
    """
    captured = _install_spy(monkeypatch)
    port = _SpyPort(
        ticker_bars=[_bar("2024-01-02", o=100, h=102, l=99, c=101)],
        spy_bars=[_bar("2024-01-02", o=400, h=404, l=398, c=402)],
        rf_yield=4.25,
    )

    out = compute_daily_features("AAPL", "2024-01-02", port)

    assert captured["call_count"] == 1, "compute_features must be DRIVEN, not bypassed"
    assert out is _SENTINEL, "the adapter must return compute_features' result verbatim"


def test_assembles_bars_spy_and_rf_yield(monkeypatch) -> None:
    """The assembled inputs are the wire→Bar ticker bars, SPY closes, and rf-yield.

    The raw wire bars (`t/o/h/l/c/v`) are mapped to the landed `Bar` TypedDict
    shape (`open/high/low/close/volume`) that `compute_features` + `_atr` consume.
    """
    captured = _install_spy(monkeypatch)
    port = _SpyPort(
        ticker_bars=[_bar("2024-01-02", o=100, h=102, l=99, c=101, v=5.0)],
        spy_bars=[_bar("2024-01-02", o=400, h=404, l=398, c=402)],
        rf_yield=3.75,
    )

    compute_daily_features("AAPL", "2024-01-02", port)

    bar = captured["ticker_bars"][0]
    assert set(bar) >= {"open", "high", "low", "close", "volume"}, "wire→Bar mapping"
    assert (bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"]) == (
        100.0, 102.0, 99.0, 101.0, 5.0,
    )
    assert captured["spy_close"] == [402.0], "SPY adj-close array is passed by value"
    assert captured["rf_yield_pct"] == 3.75, "the rf-yield is pulled via the port"


# --- point-in-time: no bar dated > D reaches the features (3.1) ------------- #


def test_no_bar_after_as_of_day_reaches_features(monkeypatch) -> None:
    """Only bars timestamped ≤ D feed the features; a future bar is dropped (3.1).

    The fixture port returns canned bars ignoring start/end, so the ADAPTER must
    enforce the point-in-time bound. A bar dated strictly after D must never
    reach `compute_features` (no look-ahead).
    """
    captured = _install_spy(monkeypatch)
    port = _SpyPort(
        ticker_bars=[
            _bar("2024-01-02", o=100, h=101, l=99, c=100),
            _bar("2024-01-03", o=100, h=101, l=99, c=101),  # == D (kept, inclusive)
            _bar("2024-01-04", o=100, h=101, l=99, c=200),  # > D (look-ahead, dropped)
        ],
        spy_bars=[
            _bar("2024-01-02", o=400, h=404, l=398, c=400),
            _bar("2024-01-03", o=400, h=404, l=398, c=401),
            _bar("2024-01-04", o=400, h=404, l=398, c=500),  # > D (dropped)
        ],
    )

    compute_daily_features("AAPL", "2024-01-03", port)

    ticker_closes = _closes(captured["ticker_bars"])
    assert ticker_closes == [100.0, 101.0], "the > D ticker bar must be dropped"
    assert 200.0 not in ticker_closes, "no look-ahead close reaches the features"
    assert captured["spy_close"] == [400.0, 401.0], "the > D SPY bar must be dropped"


# --- the as-of split rule (4.2 / design Core-algorithms #4) ----------------- #


def test_in_window_pre_D_split_is_applied(monkeypatch) -> None:
    """A split with ex-date ≤ D IS applied to the pre-ex-date bars (4.2).

    A 1→4 forward split (`split_from=1, split_to=4`, factor 4) on 2024-01-04
    with D = 2024-01-10: bars STRICTLY BEFORE the ex-date are divided by 4 so the
    series is continuous across the split (momentum continuity); bars on/after
    the ex-date are already post-split and stay raw. The full OHLC of a
    pre-ex-date bar is adjusted (not just close) so `_atr` does not spike.
    """
    captured = _install_spy(monkeypatch)
    port = _SpyPort(
        ticker_bars=[
            _bar("2024-01-02", o=400, h=412, l=396, c=400),  # pre-split → ÷4
            _bar("2024-01-03", o=404, h=416, l=400, c=404),  # pre-split → ÷4
            _bar("2024-01-04", o=101, h=103, l=99, c=101),   # ex-date → raw
            _bar("2024-01-05", o=102, h=104, l=100, c=102),  # post-split → raw
        ],
        spy_bars=[
            _bar("2024-01-02", o=400, h=404, l=398, c=400),
            _bar("2024-01-03", o=400, h=404, l=398, c=401),
            _bar("2024-01-04", o=400, h=404, l=398, c=402),
            _bar("2024-01-05", o=400, h=404, l=398, c=403),
        ],
        splits=[{"execution_date": "2024-01-04", "split_from": 1, "split_to": 4}],
    )

    compute_daily_features("AAPL", "2024-01-10", port)

    bars = captured["ticker_bars"]
    # pre-ex-date closes divided by 4 → continuous with the ~101 post-split level.
    assert _closes(bars) == [100.0, 101.0, 101.0, 102.0], "pre-D split applied to closes"
    # OHLC (not just close) adjusted on the pre-ex-date bars → no ATR spike.
    assert (bars[0]["high"], bars[0]["low"], bars[0]["open"]) == (103.0, 99.0, 100.0)
    assert (bars[1]["high"], bars[1]["low"], bars[1]["open"]) == (104.0, 100.0, 101.0)
    # the ex-date and post-split bars are untouched (already post-split).
    assert (bars[2]["high"], bars[2]["low"]) == (103.0, 99.0)
    assert (bars[3]["high"], bars[3]["low"]) == (104.0, 100.0)


def test_post_D_split_is_never_applied(monkeypatch) -> None:
    """A split with ex-date > D is NEVER applied (that would be look-ahead, 4.2).

    Same 1→4 split but ex-date 2024-01-20 with D = 2024-01-10. Because the split
    has not yet occurred as-of D, NO bar in the feature window is adjusted — the
    raw `adjusted=false` closes pass through unchanged.
    """
    captured = _install_spy(monkeypatch)
    raw_ticker = [
        _bar("2024-01-02", o=400, h=412, l=396, c=400),
        _bar("2024-01-03", o=404, h=416, l=400, c=404),
    ]
    port = _SpyPort(
        ticker_bars=raw_ticker,
        spy_bars=[
            _bar("2024-01-02", o=400, h=404, l=398, c=400),
            _bar("2024-01-03", o=400, h=404, l=398, c=401),
        ],
        splits=[{"execution_date": "2024-01-20", "split_from": 1, "split_to": 4}],
    )

    compute_daily_features("AAPL", "2024-01-10", port)

    bars = captured["ticker_bars"]
    assert _closes(bars) == [400.0, 404.0], "post-D split must NOT touch the closes"
    assert (bars[0]["high"], bars[0]["low"]) == (412.0, 396.0), "raw OHLC unchanged"
    assert (bars[1]["high"], bars[1]["low"]) == (416.0, 400.0), "raw OHLC unchanged"


def test_in_window_and_post_D_split_partition(monkeypatch) -> None:
    """One in-window (≤ D) + one post-D split: only the in-window one is applied.

    The single-fixture check the task names: an in-window pre-D split (applied)
    coexists with a post-D split (skipped). Only the ≤ D factor adjusts the
    pre-ex-date bars; the post-D split is ignored entirely.
    """
    captured = _install_spy(monkeypatch)
    port = _SpyPort(
        ticker_bars=[
            _bar("2024-01-02", o=200, h=206, l=198, c=200),  # pre-(in-window) → ÷2
            _bar("2024-01-03", o=101, h=103, l=99, c=101),   # in-window ex-date → raw
            _bar("2024-01-04", o=102, h=104, l=100, c=102),  # between splits → raw
        ],
        spy_bars=[
            _bar("2024-01-02", o=400, h=404, l=398, c=400),
            _bar("2024-01-03", o=400, h=404, l=398, c=401),
            _bar("2024-01-04", o=400, h=404, l=398, c=402),
        ],
        splits=[
            {"execution_date": "2024-01-03", "split_from": 1, "split_to": 2},  # ≤ D
            {"execution_date": "2024-01-20", "split_from": 1, "split_to": 4},  # > D
        ],
    )

    compute_daily_features("AAPL", "2024-01-10", port)

    bars = captured["ticker_bars"]
    # Only the 1→2 (factor 2) in-window split touches the single pre-ex-date bar.
    # The post-D 1→4 split is NOT applied (no ÷8, no ÷4).
    assert _closes(bars) == [100.0, 101.0, 102.0], "only the ≤ D split is applied"
    assert (bars[0]["high"], bars[0]["low"]) == (103.0, 99.0), "OHLC ÷2 (in-window only)"
