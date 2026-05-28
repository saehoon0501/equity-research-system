"""Calibration resolver — backfill realized outcomes for recommendation_outcomes.

WS-4. For each pending recommendation_outcomes row the resolver:

  1. Determines the resolve horizon(s) from the signal type
     (tactical/flow -> 30d; fundamental -> 90d AND 1y — multi-horizon, clustered
     under the same rec_id) via ``src.calibration.horizon``.
  2. Polls ``market_data.get_prices`` POINT-IN-TIME (``as_of=resolve_at``) for the
     ticker AND the SPY benchmark. The ``as_of`` guard (P0-7) drops any bar dated
     after ``resolve_at`` so the resolver can never read look-ahead data.
  3. Uses ``mode="total_return"`` so dividends/splits/DELISTINGS resolve via the
     reconstructed total-return series (P0-7 ``total_return_close``) rather than
     being dropped (e.g. delisted ``FSR``).
  4. Computes the realized return over the horizon window for ticker and SPY,
     ``excess_return = ret_ticker - ret_spy``, and
     ``label_binary = excess_return > 0`` (beat the benchmark).
  5. UPSERTs only the MUTABLE resolver-written columns idempotently — a re-run
     with the same PIT inputs writes identical values. The benchmark return is a
     TRANSIENT Python value used to compute excess_return; it is NEVER persisted
     by the resolver. mig-045 makes benchmark_return_{30d,90d,1y} (and
     delta_vs_benchmark_*) IMMUTABLE — an UPDATE that touches them trips the
     STATE-guard (`IS DISTINCT FROM` -> RAISE EXCEPTION). The resolver therefore
     writes only: t_plus_*_return / t_plus_*_close_date / label_binary /
     excess_return / label_method_version / primary_horizon (+ last_updated_at).

DEGRADE (LOCKED): resolver failure => idempotent resume (UPSERT); NEVER silent
skip. A row that cannot be resolved (insufficient PIT price history) is left
pending and surfaced in the run result's ``deferred`` list — not silently dropped.

I/O is dependency-injected: a ``PriceClient`` (duck-typed ``get_prices``) and an
``OutcomeStore`` (read pending rows / write labels). Both have in-memory fakes in
the tests, so the PIT-assert / idempotency tests run with NO live DB or API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional, Protocol, Sequence

from src.calibration.horizon import (
    columns_for,
    horizons_for,
    primary_horizon_for,
    window_days_for,
)

logger = logging.getLogger(__name__)

# Versions the labeling rule so a later rule change is auditable + re-derivable
# (written into recommendation_outcomes.label_method_version).
LABEL_METHOD_VERSION = "calibration.resolver.v1"

# Benchmark used for excess-return / beat-benchmark labeling. SPY per WS-4.
BENCHMARK_TICKER = "SPY"


# --------------------------------------------------------------------------- #
# Dependency-injection protocols (production = MCP/psycopg wrappers; tests =   #
# in-memory fakes). The framework's MarketDataClient precedent is mirrored.    #
# --------------------------------------------------------------------------- #
class PriceClient(Protocol):
    """Subset of mcp__market_data.get_prices the resolver relies on."""

    def get_prices(
        self,
        ticker: str,
        start: str,
        end: str,
        interval: str = "1d",
        mode: str = "split_only",
        as_of: str | None = None,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class PendingOutcome:
    """A recommendation_outcomes row awaiting label backfill."""

    rec_id: str  # recommendation_id (clusters multi-horizon rows)
    ticker: str
    recommendation_date: date
    signal_type: str
    outcome_id: Optional[str] = None  # PK if the store keys writes by it


class OutcomeStore(Protocol):
    """Read pending rows / write resolver outcomes. Production wraps psycopg.

    ``recommendation_outcomes`` has ``UNIQUE (recommendation_id)`` (mig-013) — there
    is exactly ONE row per rec_id. The resolver therefore writes ONE consolidated
    row per rec_id: the per-horizon ``t_plus_*_return`` columns for every horizon
    it resolved (mig-045 widened the STATE-guard to keep ``t_plus_*`` mutable),
    PLUS the row's ``label_binary`` / ``excess_return`` / ``primary_horizon`` /
    ``label_method_version`` computed at the row's PRIMARY horizon.

    Production implements ``upsert_outcome`` as a single
    ``INSERT ... ON CONFLICT (recommendation_id) DO UPDATE`` (idempotent).
    """

    def fetch_pending(self) -> Sequence[PendingOutcome]:
        ...

    def upsert_outcome(
        self,
        *,
        rec_id: str,
        ticker: str,
        primary_horizon: str,
        label_binary: bool,
        excess_return: float,
        label_method_version: str,
        # horizon -> realized t_plus_*_return for the ticker (e.g. {"90d":..,"1y":..})
        ticker_returns: dict[str, float],
        # horizon -> ISO close date (resolve_at) for the t_plus_*_close_date columns.
        # mig-013 keeps t_plus_*_close_date mutable alongside t_plus_*_return.
        ticker_close_dates: dict[str, str],
    ) -> None:
        """Write ONLY the mutable resolver columns for the rec's single row.

        The benchmark return is NOT a parameter: mig-045 makes
        benchmark_return_{30d,90d,1y} (and delta_vs_benchmark_*) IMMUTABLE, so the
        resolver must never write them. The benchmark return is consumed in Python
        to derive ``excess_return`` and discarded. Implementations MUST NOT include
        benchmark_return_* / delta_vs_benchmark_* in the INSERT ... ON CONFLICT
        DO UPDATE SET clause, or the STATE-guard trigger raises on re-resolve.
        """
        ...


@dataclass
class HorizonReturn:
    """One resolved (horizon) leg of a rec — feeds a t_plus_*_return column."""

    horizon: str
    ret_ticker: float
    ret_benchmark: float
    excess_return: float
    label_binary: bool
    resolve_at: str  # the PIT as_of used (ISO date)


@dataclass
class ResolvedLabel:
    """The consolidated single-row outcome written for one rec_id.

    ``primary_horizon`` / ``label_binary`` / ``excess_return`` are the row-level
    label (computed at the signal type's primary horizon). ``legs`` carries every
    resolved horizon (multi-horizon for fundamental: 90d + 1y) so the per-horizon
    ``t_plus_*_return`` backfill is auditable and clustered under the one rec_id.
    """

    rec_id: str
    ticker: str
    primary_horizon: str
    excess_return: float
    label_binary: bool
    label_method_version: str = LABEL_METHOD_VERSION
    legs: list[HorizonReturn] = field(default_factory=list)

    @property
    def ret_ticker(self) -> float:
        """Ticker return at the primary horizon (compat accessor)."""
        for leg in self.legs:
            if leg.horizon == self.primary_horizon:
                return leg.ret_ticker
        raise KeyError(self.primary_horizon)

    @property
    def ret_benchmark(self) -> float:
        for leg in self.legs:
            if leg.horizon == self.primary_horizon:
                return leg.ret_benchmark
        raise KeyError(self.primary_horizon)


@dataclass
class DeferredOutcome:
    rec_id: str
    ticker: str
    primary_horizon: str
    reason: str


@dataclass
class ResolverRunResult:
    resolved: list[ResolvedLabel] = field(default_factory=list)
    deferred: list[DeferredOutcome] = field(default_factory=list)

    @property
    def n_resolved(self) -> int:
        return len(self.resolved)

    @property
    def n_deferred(self) -> int:
        return len(self.deferred)

    def by_rec_id(self) -> dict[str, list[ResolvedLabel]]:
        """Resolved labels clustered by rec_id (multi-horizon rows grouped)."""
        out: dict[str, list[ResolvedLabel]] = {}
        for r in self.resolved:
            out.setdefault(r.rec_id, []).append(r)
        return out


# --------------------------------------------------------------------------- #
# PIT price extraction + return computation                                    #
# --------------------------------------------------------------------------- #
def _iso(d: date) -> str:
    return d.isoformat()


def _resolve_close_series(response: dict[str, Any]) -> list[tuple[str, float]]:
    """Extract sorted [(date, total_return_close)] from a get_prices payload.

    Prefers ``total_return_close`` (mode=total_return, P0-7) so delisted/dividend
    names resolve on the reconstructed TR series; falls back to ``close`` only if
    TR is absent for every row (split_only payload). Rows without a usable price
    are skipped.
    """
    rows = response.get("rows") or []
    has_tr = any(
        isinstance(r, dict) and r.get("total_return_close") is not None for r in rows
    )
    series: list[tuple[str, float]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = r.get("date")
        if not d:
            continue
        raw = r.get("total_return_close") if has_tr else r.get("close")
        if raw is None:
            continue
        try:
            series.append((str(d), float(raw)))
        except (TypeError, ValueError):
            continue
    # Dedupe same-date bars ORDER-INDEPENDENTLY so entry_price never depends on
    # feed arrival order. Sorting by (date, price) then last-write-wins per date
    # is deterministic regardless of input order (keeps the MAX price per date);
    # do NOT "simplify" to a plain sort-by-date + dict, which is arrival-order
    # dependent for duplicate dates.
    series.sort(key=lambda t: (t[0], t[1]))
    deduped: dict[str, float] = {}
    for d, px in series:
        deduped[d] = px
    return sorted(deduped.items(), key=lambda t: t[0])


def _assert_pit(response: dict[str, Any], resolve_at: str, *, who: str) -> None:
    """Hard guarantee that every returned bar is dated <= resolve_at.

    The get_prices ``as_of`` guard should already enforce this; we re-assert here
    so a mocked/misconfigured client cannot smuggle look-ahead data into a label.
    """
    for r in response.get("rows") or []:
        if not isinstance(r, dict):
            continue
        d = r.get("date")
        if d is not None and str(d) > resolve_at:
            raise AssertionError(
                f"PIT violation ({who}): bar dated {d} > resolve_at {resolve_at}"
            )


def _window_return(
    client: PriceClient,
    ticker: str,
    start_date: date,
    resolve_at: date,
    *,
    who: str,
) -> Optional[float]:
    """Realized total return from the bar nearest start_date to the last bar
    at/<= resolve_at, computed PIT.

    Returns None if there are fewer than two usable bars (insufficient history —
    the row is deferred, not silently zero'd).
    """
    resolve_iso = _iso(resolve_at)
    # Fetch a little before recommendation_date so the entry bar exists even if
    # the rec date is a non-trading day; end fetch at resolve_at (PIT).
    fetch_start = _iso(start_date - timedelta(days=10))
    resp = client.get_prices(
        ticker,
        fetch_start,
        resolve_iso,
        interval="1d",
        mode="total_return",
        as_of=resolve_iso,
    )
    _assert_pit(resp, resolve_iso, who=who)
    series = _resolve_close_series(resp)
    if len(series) < 2:
        return None
    start_iso = _iso(start_date)
    # Entry = first bar on/after recommendation_date (or the last bar before it
    # if the rec date precedes the series — clamp to first available).
    entry_price: Optional[float] = None
    for d, px in series:
        if d >= start_iso:
            entry_price = px
            break
    if entry_price is None:
        entry_price = series[0][1]
    exit_price = series[-1][1]  # last bar at/<= resolve_at
    if entry_price == 0:
        return None
    return (exit_price - entry_price) / entry_price


# --------------------------------------------------------------------------- #
# Resolver                                                                     #
# --------------------------------------------------------------------------- #
def resolve_one(
    pending: PendingOutcome,
    horizon: str,
    client: PriceClient,
    *,
    today: Optional[date] = None,
) -> HorizonReturn | DeferredOutcome:
    """Resolve a single (rec, horizon) LEG, PIT.

    resolve_at = recommendation_date + window_days(horizon). If that date is in
    the future relative to ``today``, the window is not yet closed -> deferred.
    Returns a ``HorizonReturn`` (one t_plus_*_return leg), NOT a full row — the
    consolidated single row per rec_id is assembled by ``run_resolver``.
    """
    columns_for(horizon)  # validates horizon, raises on illegal (no t_plus_365)
    # Default to TODAY so the window-closed guard is ALWAYS active. A None default
    # would silently disable the guard and let an unclosed horizon resolve against
    # the latest available (partial) bar — non-idempotent / quasi-look-ahead.
    if today is None:
        today = date.today()
    resolve_at = pending.recommendation_date + timedelta(days=window_days_for(horizon))
    if resolve_at > today:
        return DeferredOutcome(
            pending.rec_id, pending.ticker, horizon, reason="window_not_yet_closed"
        )

    ret_ticker = _window_return(
        client, pending.ticker, pending.recommendation_date, resolve_at, who=pending.ticker
    )
    ret_bench = _window_return(
        client, BENCHMARK_TICKER, pending.recommendation_date, resolve_at, who=BENCHMARK_TICKER
    )
    if ret_ticker is None or ret_bench is None:
        missing = pending.ticker if ret_ticker is None else BENCHMARK_TICKER
        return DeferredOutcome(
            pending.rec_id,
            pending.ticker,
            horizon,
            reason=f"insufficient_pit_history:{missing}",
        )

    excess = ret_ticker - ret_bench
    return HorizonReturn(
        horizon=horizon,
        ret_ticker=ret_ticker,
        ret_benchmark=ret_bench,
        excess_return=excess,
        label_binary=excess > 0.0,
        resolve_at=_iso(resolve_at),
    )


def run_resolver(
    store: OutcomeStore,
    client: PriceClient,
    *,
    today: Optional[date] = None,
) -> ResolverRunResult:
    """Backfill outcomes for every pending row, idempotently.

    For each pending row, resolve EVERY horizon for its signal type (fundamental
    -> 90d AND 1y). Because ``recommendation_outcomes`` has ONE row per rec_id
    (UNIQUE recommendation_id), the resolved horizons are consolidated into a
    SINGLE ``upsert_outcome`` per rec_id: the per-horizon ``t_plus_*_return``
    columns plus the row-level label computed at the signal type's PRIMARY
    horizon. The UPSERT is idempotent (re-run with identical PIT inputs writes
    identical values). Deferred legs are surfaced, never silently skipped; a rec
    is only written if its PRIMARY horizon resolved.

    ``today`` defaults to ``date.today()`` so the window-closed guard is always on:
    an unclosed window (resolve_at > today) DEFERS rather than resolving against
    partial data, keeping resolution idempotent across calendar days.
    """
    if today is None:
        today = date.today()
    result = ResolverRunResult()
    for pending in store.fetch_pending():
        try:
            horizons = horizons_for(pending.signal_type)
            primary = primary_horizon_for(pending.signal_type)
        except ValueError as exc:
            result.deferred.append(
                DeferredOutcome(
                    pending.rec_id, pending.ticker, "?", reason=f"bad_signal_type:{exc}"
                )
            )
            continue

        legs: list[HorizonReturn] = []
        for horizon in horizons:
            leg = resolve_one(pending, horizon, client, today=today)
            if isinstance(leg, DeferredOutcome):
                result.deferred.append(leg)
                continue
            legs.append(leg)

        # The row's label is the PRIMARY-horizon leg. If the primary horizon did
        # not resolve, the whole row stays pending (already surfaced as deferred).
        primary_leg = next((l for l in legs if l.horizon == primary), None)
        if primary_leg is None:
            continue

        ticker_returns = {l.horizon: l.ret_ticker for l in legs}
        ticker_close_dates = {l.horizon: l.resolve_at for l in legs}
        # NOTE: benchmark returns (l.ret_benchmark) are TRANSIENT — already folded
        # into excess_return above. They are NOT passed to the store: mig-045 makes
        # benchmark_return_* immutable, so writing them would trip the STATE-guard
        # on any re-resolve UPDATE.

        # Idempotent single-row UPSERT (ON CONFLICT (recommendation_id) DO UPDATE),
        # touching only the mutable columns.
        store.upsert_outcome(
            rec_id=pending.rec_id,
            ticker=pending.ticker,
            primary_horizon=primary,
            label_binary=primary_leg.label_binary,
            excess_return=primary_leg.excess_return,
            label_method_version=LABEL_METHOD_VERSION,
            ticker_returns=ticker_returns,
            ticker_close_dates=ticker_close_dates,
        )
        result.resolved.append(
            ResolvedLabel(
                rec_id=pending.rec_id,
                ticker=pending.ticker,
                primary_horizon=primary,
                excess_return=primary_leg.excess_return,
                label_binary=primary_leg.label_binary,
                legs=legs,
            )
        )
    return result
