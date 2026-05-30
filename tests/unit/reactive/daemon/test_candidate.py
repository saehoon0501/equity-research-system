"""Inner-ring test for candidate assembly (task 3.1).

Boundary: candidate (Requirement 12). Asserts the Observable from tasks.md 3.1:

  * synthetic arrays with a **positive** tactical bin return a **LONG** Candidate
    carrying ``reference_price`` (= the last ticker close, CN-4);
  * a **negative** bin returns a **SHORT** Candidate;
  * a **neutral** bin and an **unavailable** bin each return ``None`` and are
    **distinguishable** in what the assembly records (Req 12.5 — non-directional
    bin = absence of an edge — vs Req 12.4 — insufficient data — attribution);
  * too-short history (a ``FeatureFailure``) returns ``None`` (Req 12.4);
  * the bin is read from ``FeatureSet.raw["tactical_bin"]`` (NB-1) — NOT
    ``trend_vote``, which folds ``unavailable``→``neutral``: a test feeds an
    ``unavailable`` tactical bin (rf ``None``) and asserts it is attributed to
    ``unavailable`` (12.4-leaning), distinct from a ``neutral`` (12.5) bin even
    though ``trend_vote`` would collapse both to ``0.0``.

The live feed is **mocked** (3.6 builds the concrete 3-leg client); the feature
compute + bin→direction map are pure over the fetched arrays, so this is
inner-ring: no LLM, no MCP, no live DB, no ``src.survival`` (P14).
"""

from __future__ import annotations

import math
import sys

import pytest

from src.reactive.daemon.candidate import (
    NonDirectionalReason,
    assemble,
)
from src.reactive.daemon.types import Candidate, PinnedParams
from src.reactive.features import LONGEST_WINDOW
from src.reactive.params import DEFAULTS
from src.reactive.types import Bar


# --- Synthetic feed -------------------------------------------------------


class _StubFeed:
    """A synthetic MarketFeed: returns canned ticker bars + SPY + rf legs.

    Stands in for the concrete 3-leg client task 3.6 un-mocks. The candidate
    only reads the three legs the feature compute needs, so a minimal stub with
    the three accessors is a complete double for the inner ring.
    """

    def __init__(self, ticker_bars, spy_close, rf_yield_pct):
        self._ticker_bars = ticker_bars
        self._spy_close = spy_close
        self._rf_yield_pct = rf_yield_pct
        self.calls: list[str] = []

    def ticker_bars(self, symbol: str):
        self.calls.append(f"ticker_bars:{symbol}")
        return self._ticker_bars

    def spy_close(self):
        self.calls.append("spy_close")
        return self._spy_close

    def rf_yield_pct(self):
        self.calls.append("rf_yield_pct")
        return self._rf_yield_pct


def _bar(close: float) -> Bar:
    """A well-formed daily OHLCV bar with a small, non-degenerate range.

    The range is constant and non-zero so ATR is computable (not degenerate);
    `close` drives both the directional return and the surfaced reference price.
    """
    return {
        "open": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1000.0,
    }


def _ramp_bars(start: float, step: float, n: int) -> list[Bar]:
    """`n` chronological bars whose close ramps by `step` (index [-1] = newest)."""
    return [_bar(start + step * i) for i in range(n)]


# Enough history for the longest reused window (252) plus headroom.
_N = LONGEST_WINDOW + 5


def _pinned() -> PinnedParams:
    """A PinnedParams whose reactive_snapshot is the inner-ring DEFAULTS."""
    return PinnedParams(reactive_snapshot=DEFAULTS, survival_snapshot={})


# --- Directional bins -----------------------------------------------------


def test_positive_bin_returns_long_candidate_with_reference_price():
    """Ticker strongly outperforming SPY + a low rf → positive bin → LONG.

    The candidate carries reference_price = the last ticker close (CN-4 — the
    close compute_features drops), so order_builder needs no re-fetch.
    """
    # Ticker climbs hard; SPY is flat → rel >> 0 and abs >> 0 → positive bin.
    ticker = _ramp_bars(100.0, 1.0, _N)
    spy = [100.0] * _N
    feed = _StubFeed(ticker, spy, rf_yield_pct=1.0)

    cand = assemble("AAPL", feed, _pinned())

    assert isinstance(cand, Candidate)
    assert cand.direction == "LONG"
    # reference_price is the last close of the fetched ticker bars.
    assert cand.reference_price == ticker[-1]["close"]
    assert math.isclose(cand.reference_price, 100.0 + 1.0 * (_N - 1))


def test_negative_bin_returns_short_candidate():
    """Ticker strongly underperforming SPY + below rf → negative bin → SHORT."""
    # Ticker falls; SPY rises → rel << 0 and abs << 0 → negative bin.
    ticker = _ramp_bars(400.0, -1.0, _N)
    spy = _ramp_bars(100.0, 1.0, _N)
    spy_close = [b["close"] for b in spy]
    feed = _StubFeed(ticker, spy_close, rf_yield_pct=4.0)

    cand = assemble("AAPL", feed, _pinned())

    assert isinstance(cand, Candidate)
    assert cand.direction == "SHORT"
    assert cand.reference_price == ticker[-1]["close"]


# --- Non-directional bins (Req 12.5) — distinguishable from each other -----


def test_neutral_bin_returns_none_attributed_no_edge():
    """A neutral (mixed-momentum) bin → no candidate (Req 12.5), attributed
    NEUTRAL — an absence of edge, NOT a data error."""
    # Ticker beats SPY (rel > 0) but trails the risk-free (abs < 0) → mixed →
    # neutral bin. start->end return ~ +5/100 = +5%; rf 8% → abs < 0.
    ticker = _ramp_bars(100.0, 5.0 / _N, _N)
    spy = [100.0] * _N
    feed = _StubFeed(ticker, spy, rf_yield_pct=8.0)

    reason: list[NonDirectionalReason] = []
    cand = assemble("AAPL", feed, _pinned(), on_non_directional=reason.append)

    assert cand is None
    assert reason == [NonDirectionalReason.NEUTRAL]


def test_unavailable_bin_returns_none_attributed_unavailable():
    """An unavailable tactical bin (rf None → rf_resolver_staleness) → no
    candidate, attributed UNAVAILABLE — NOT neutral.

    This is the NB-1 guard: the bin is read from raw['tactical_bin'] (verbatim
    'unavailable'), NOT trend_vote (which maps unavailable -> 0.0 == neutral's
    vote and would fold the two together).
    """
    ticker = _ramp_bars(100.0, 1.0, _N)
    spy = [100.0] * _N
    feed = _StubFeed(ticker, spy, rf_yield_pct=None)  # rf None → tactical unavailable

    reason: list[NonDirectionalReason] = []
    cand = assemble("AAPL", feed, _pinned(), on_non_directional=reason.append)

    assert cand is None
    assert reason == [NonDirectionalReason.UNAVAILABLE]


def test_neutral_and_unavailable_are_distinguishable():
    """The two non-directional bins map to DISTINCT reasons (12.5 vs the
    unavailable sub-case) — they must never collapse together (NB-1)."""
    assert NonDirectionalReason.NEUTRAL != NonDirectionalReason.UNAVAILABLE


# --- Insufficient data (Req 12.4) -----------------------------------------


def test_insufficient_history_returns_none_attributed_insufficient_data():
    """Too-short history → compute_features FeatureFailure → no candidate,
    attributed to insufficient data (Req 12.4), distinct from a bin skip."""
    short = _ramp_bars(100.0, 1.0, 10)  # < LONGEST_WINDOW
    spy = [100.0] * 10
    feed = _StubFeed(short, spy, rf_yield_pct=2.0)

    reason: list[NonDirectionalReason] = []
    cand = assemble("AAPL", feed, _pinned(), on_non_directional=reason.append)

    assert cand is None
    assert reason == [NonDirectionalReason.INSUFFICIENT_DATA]


def test_insufficient_data_distinct_from_non_directional_bin():
    """Insufficient data (12.4) is a SEPARATE reason from a non-directional
    bin (12.5) — both return None but stay attributable downstream."""
    assert NonDirectionalReason.INSUFFICIENT_DATA != NonDirectionalReason.NEUTRAL
    assert NonDirectionalReason.INSUFFICIENT_DATA != NonDirectionalReason.UNAVAILABLE


# --- Boundary hygiene -----------------------------------------------------


def test_assemble_does_not_pull_in_survival():
    """The candidate is Phase-1: assembling never imports src.survival."""
    ticker = _ramp_bars(100.0, 1.0, _N)
    feed = _StubFeed(ticker, [100.0] * _N, rf_yield_pct=1.0)
    assemble("AAPL", feed, _pinned())
    assert "src.survival" not in sys.modules
    assert "src.survival.gate" not in sys.modules


def test_assemble_fetches_all_three_feed_legs():
    """Each evaluation fetches all three fast-clock legs (Req 12.1): the
    ticker bars, the SPY benchmark series, and the risk-free yield."""
    ticker = _ramp_bars(100.0, 1.0, _N)
    feed = _StubFeed(ticker, [100.0] * _N, rf_yield_pct=1.0)
    assemble("AAPL", feed, _pinned())
    assert any(c.startswith("ticker_bars:") for c in feed.calls)
    assert "spy_close" in feed.calls
    assert "rf_yield_pct" in feed.calls
