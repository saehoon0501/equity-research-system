"""Candidate assembly — the daemon's market-data → features → direction seam.

Boundary: candidate (Requirement 12; design §"Control — ``candidate``", Rev 2.4).

Each evaluation, ``assemble`` is the daemon's **single** market-data fetch point
and the **sole** point that converts the tactical-overlay relative-strength bin
into a ``Direction`` (§12.3 — the side is *not* from fundamentals or the
slow-layer thesis; the slow-layer veto is the entry-exclusion stage housed
inside ``survival-gate`` §12.6). It:

1. **fetches the fast-clock market data** (Req 12.1) — the ticker's recent daily
   bars, the SPY benchmark series, and the risk-free DGS1 yield — from the
   ``MarketFeed`` (the live fetch is **mocked** in task 3.1; task 3.6 builds the
   concrete 3-leg client behind this same ``MarketFeed`` interface);
2. **computes the ``FeatureSet``** via ``reactive.features.compute_features`` over
   the fetched arrays (Req 12.2 — the daemon never passes raw data to ``decide``);
3. **maps the tactical bin → a candidate ``direction``** (Req 12.3), reading the
   verbatim 4-valued bin from ``FeatureSet.raw["tactical_bin"]`` — **never**
   ``trend_vote`` (NB-1: ``_TACTICAL_VOTE`` omits ``unavailable`` so ``trend_vote``
   folds ``unavailable``→``0.0``==``neutral``'s vote, which would silently collapse
   the two non-directional bins and break the Req 12.5 / 12.4 distinction):

   | tactical bin  | direction        | outcome                              |
   |---------------|------------------|--------------------------------------|
   | ``positive``  | ``Direction.LONG``  | candidate                          |
   | ``negative``  | ``Direction.SHORT`` | candidate                          |
   | ``neutral``   | —                | no candidate → ``None`` (Req 12.5)   |
   | ``unavailable`` | —              | no candidate → ``None`` (Req 12.5)   |

4. on a **directional** bin, **surfaces the reference price**
   ``reference_price = ticker_closes[-1]`` (the last close — ``compute_features``
   computes it then drops it, CN-4) and returns a daemon-owned
   ``Candidate{features, direction, reference_price}``.

A **non-directional** bin (``neutral``/``unavailable``) is the *absence of an
edge*, not a data error → ``None`` (Req 12.5); **missing/insufficient market
data** (a ``FeatureFailure`` from ``compute_features``) → ``None`` (Req 12.4).
Both halt new exposure, but the skip stays **attributable** — ``assemble``
records *which* non-directional case it saw via the optional
``on_non_directional`` callback (``NEUTRAL`` / ``UNAVAILABLE`` for 12.5,
``INSUFFICIENT_DATA`` for 12.4) so the orchestrator's declined trace can name the
12.5-vs-12.4 cause (a degenerate-feature ``FeatureFailure`` maps to
``INSUFFICIENT_DATA`` as well — both are the data-error class, not no-edge).

Pure over the fetched arrays except the one impure ``feed`` edge → **inner-ring
testable with a mocked feed, no ``survival.gate`` (Phase 1)**. Imports the
reactive feature/type leaves + the daemon-owned ``types`` only — no MCP, no DB,
no ``src.survival`` (P1/P14). Dependency direction: ``types → candidate``.
"""

from __future__ import annotations

import enum
from typing import Callable, Optional, Protocol, Sequence, runtime_checkable

from src.reactive.daemon.types import Candidate, PinnedParams
from src.reactive.features import FeatureSet, compute_features
from src.reactive.types import Bar, Direction, FeatureFailure

__all__ = [
    "MarketFeed",
    "NonDirectionalReason",
    "assemble",
]


# --- The fast-clock market feed (consumer-owned interface; concrete in 3.6) --


@runtime_checkable
class MarketFeed(Protocol):
    """The daemon's fast-clock data source — the three legs the feature compute
    needs (Req 12.1).

    The **consumer owns this interface** (``candidate`` is the only caller); the
    concrete 3-leg client (Massive daily bars + SPY adj-close + FRED DGS1) is
    built in task 3.6 *behind* this Protocol, keeping the daemon's "no MCP/FastMCP
    imported into the loop" boundary (§14.10) and letting task 3.1 test against a
    plain stub. The legs are exactly ``compute_features``'s positional inputs:

      * ``ticker_bars(symbol)`` → chronological daily OHLCV ``Bar``s (index
        ``[-1]`` = most recent), feeding ``indicators.atr`` + the overlay cores;
      * ``spy_close()`` → the SPY adjusted-close benchmark series (index ``[-1]``
        = most recent);
      * ``rf_yield_pct()`` → the risk-free DGS1 yield (percent), or ``None`` when
        unresolved (``None`` makes the tactical core abstain → ``unavailable``
        bin, *not* a failure).
    """

    def ticker_bars(self, symbol: str) -> Sequence[Bar]: ...

    def spy_close(self) -> Sequence[float]: ...

    def rf_yield_pct(self) -> Optional[float]: ...


# --- Non-directional attribution (Req 12.5 vs 12.4) ------------------------


class NonDirectionalReason(enum.Enum):
    """Why an evaluation produced **no candidate** — kept attributable downstream.

    ``NEUTRAL`` / ``UNAVAILABLE`` are the two non-directional **tactical bins**
    (Req 12.5 — the absence of an edge); ``INSUFFICIENT_DATA`` is a
    ``compute_features`` ``FeatureFailure`` (Req 12.4 — a data error). All three
    halt new exposure, but they are **distinct** so the orchestrator's declined
    trace can name the cause (NB-1 — ``NEUTRAL`` and ``UNAVAILABLE`` must never
    collapse together, the failure ``trend_vote`` would have introduced).
    """

    NEUTRAL = "neutral"
    UNAVAILABLE = "unavailable"
    INSUFFICIENT_DATA = "insufficient_data"


# --- Bin → direction map (the sole tactical-bin → Direction conversion) -----

# Only the two **directional** bins map to a side. ``neutral``/``unavailable``
# are deliberately ABSENT — a `.get(bin)` miss is a non-directional bin (Req
# 12.5), never silently defaulted to a side.
_BIN_DIRECTION: dict[str, Direction] = {
    "positive": "LONG",
    "negative": "SHORT",
}

# The two non-directional bins, mapped to their attribution reason (Req 12.5).
# Read from the verbatim ``raw["tactical_bin"]`` string, so ``unavailable`` stays
# distinct from ``neutral`` (NB-1).
_NON_DIRECTIONAL_REASON: dict[str, NonDirectionalReason] = {
    "neutral": NonDirectionalReason.NEUTRAL,
    "unavailable": NonDirectionalReason.UNAVAILABLE,
}


def assemble(
    symbol: str,
    feed: MarketFeed,
    params: PinnedParams,
    on_non_directional: Optional[Callable[[NonDirectionalReason], None]] = None,
) -> Optional[Candidate]:
    """Assemble the model's inputs, or ``None`` when there is no candidate.

    Args:
        symbol: the ticker under evaluation.
        feed: the fast-clock ``MarketFeed`` (live fetch mocked in 3.1).
        params: the epoch-pinned parameters. (The reactive snapshot is consumed
            by ``decide`` downstream; the candidate fetches + computes features +
            selects the side, so it does not itself read the snapshot — it is
            threaded for interface symmetry with ``decide``'s call site and so the
            feed/feature config can be sourced from the pin in 3.6 without a
            signature change.)
        on_non_directional: optional sink the assembly calls with the
            ``NonDirectionalReason`` when it returns ``None`` — lets the
            orchestrator attribute the skip to 12.5 (no edge) vs 12.4 (bad data).

    Returns:
        A ``Candidate{features, direction, reference_price}`` on a **directional**
        tactical bin (``positive``→``LONG`` / ``negative``→``SHORT``); ``None`` on
        a non-directional bin (Req 12.5) or insufficient/degenerate data
        (Req 12.4 — a ``compute_features`` ``FeatureFailure``).
    """
    # --- Leg 1-3: fetch the fast-clock market data (Req 12.1) ---------------
    ticker_bars = feed.ticker_bars(symbol)
    spy_close = feed.spy_close()
    rf_yield_pct = feed.rf_yield_pct()

    # --- Compute the FeatureSet (Req 12.2 — never raw data to decide) -------
    features = compute_features(ticker_bars, spy_close, rf_yield_pct)

    # --- Req 12.4: insufficient/degenerate data → no candidate --------------
    # `compute_features` never raises — it returns a typed FeatureFailure for a
    # too-short history (`insufficient_history`) or an uncomputable ATR
    # (`degenerate_features`). Both are the data-error class (12.4), distinct
    # from a non-directional bin (12.5).
    if isinstance(features, FeatureFailure):
        _emit(on_non_directional, NonDirectionalReason.INSUFFICIENT_DATA)
        return None

    # --- Req 12.3 / 12.5: read the VERBATIM tactical bin (NB-1) -------------
    # Read from raw["tactical_bin"], NOT trend_vote: trend_vote folds
    # `unavailable`→0.0==`neutral`, which would collapse the two non-directional
    # bins and break the 12.5/12.4 attribution.
    tactical_bin = features.raw["tactical_bin"]
    direction = _BIN_DIRECTION.get(tactical_bin)

    if direction is None:
        # A non-directional bin (`neutral`/`unavailable`) is the absence of an
        # edge, not a data error (Req 12.5) — distinguishable in the reason.
        reason = _NON_DIRECTIONAL_REASON.get(
            tactical_bin, NonDirectionalReason.UNAVAILABLE
        )
        _emit(on_non_directional, reason)
        return None

    # --- Directional bin → surface reference_price + the Candidate (CN-4) ---
    # reference_price = the last ticker close. `compute_features` computes
    # `close = ticker_closes[-1]` then drops it, so surface it here from the
    # fetched bars rather than forcing a stale re-fetch.
    reference_price = float(ticker_bars[-1]["close"])

    return Candidate(
        features=features,
        direction=direction,
        reference_price=reference_price,
    )


def _emit(
    sink: Optional[Callable[[NonDirectionalReason], None]],
    reason: NonDirectionalReason,
) -> None:
    """Report a no-candidate attribution to the optional sink (no-op if absent)."""
    if sink is not None:
        sink(reason)
