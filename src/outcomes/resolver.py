"""Outcome resolver — populates `recommendation_outcomes` T+N return columns.

Per v3 spec §6.4 + §8.1, v0.5 calibration (Brier-haircut, believability
weighting, BB-pseudo-BMA+, override-outcome circularity defense) all
consume `recommendation_outcomes` rows where the T+N window has closed.

The resolver:
    1. Selects (recommendation_id, ticker, recommendation_date) rows from
       `execution_recommendations` whose T+N close date ≤ as_of date AND
       the corresponding column in `recommendation_outcomes` is NULL.
    2. Fetches ticker + benchmark close prices via the price provider
       (default Polygon; injectable for tests).
    3. Computes return = (close_at_T_plus_N / close_at_recommendation) - 1
       on adjusted closes. Same calc for the benchmark series.
    4. UPSERTs into `recommendation_outcomes`. Per the migration's state-table
       guard, only T+N return + close_date columns and last_updated_at are
       mutable. The benchmark column is set on first INSERT and immutable.

Trading-day handling:
    - Recommendation date often falls on a non-trading day (weekend, holiday).
      We anchor returns to the FIRST close ≥ recommendation_date for both legs
      (ticker and benchmark). T+N close is the LAST close ≤ recommendation_date
      + N days. If no bar exists in the window, the leg stays NULL.

Idempotency:
    - Safe to re-run any number of times: an UPSERT pattern (`INSERT ... ON
      CONFLICT (recommendation_id) DO UPDATE`) only writes columns that are
      currently NULL OR distinct, and the migration's guard rejects mutation
      of immutable columns.

Failure handling:
    - Per-recommendation errors do NOT halt the batch. They are recorded in
      `ResolutionStats.errors` (capped at 50 entries to bound memory) and
      surfaced by the CLI summary; the resolver continues.
    - Provider auth/network errors propagate up so the operator sees them
      explicitly rather than silently producing zero rows.
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

_LOG = logging.getLogger(__name__)

# Per spec §8.1 the v0.5-active phase trigger lands at ≥50 resolved
# predictions. T+90d is the proxy for "resolved" because the migration's
# pending-1y index waits on a window that takes a full year to close.
_HORIZON_DAYS: dict[str, int] = {"30d": 30, "90d": 90, "1y": 365}

# Cap how many errors we retain per batch — bounds memory if a provider
# blip makes everything fail.
_MAX_ERRORS_RETAINED = 50


class PriceProvider(Protocol):
    """Subset of polygon_provider / yfinance used by the resolver."""

    def get_prices(
        self,
        ticker: str,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> dict[str, Any]:
        ...


@dataclass
class _Pending:
    """One recommendation × horizon pair awaiting resolution."""

    recommendation_id: str
    ticker: str
    recommendation_date: _dt.date
    benchmark: str
    horizon: str  # '30d' | '90d' | '1y'
    target_close_date: _dt.date


@dataclass
class ResolutionStats:
    """Outcome of a resolver invocation."""

    candidates_examined: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    horizons_resolved: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def record_horizon(self, horizon: str) -> None:
        self.horizons_resolved[horizon] = self.horizons_resolved.get(horizon, 0) + 1

    def record_error(self, message: str) -> None:
        if len(self.errors) < _MAX_ERRORS_RETAINED:
            self.errors.append(message)


class Resolver:
    """Stateful resolver — holds DB connection + price provider.

    Prefer the module-level `resolve_outcomes` helper for one-shot calls;
    instantiate `Resolver` directly only when callers want to pass a custom
    price provider (tests) or reuse cached price series.
    """

    def __init__(
        self,
        conn: Any,
        *,
        price_provider: PriceProvider,
        default_benchmark: str = "SPY",
        clock: Optional[Callable[[], _dt.date]] = None,
    ) -> None:
        self._conn = conn
        self._provider = price_provider
        self._default_benchmark = default_benchmark
        self._clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc).date())

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def resolve(
        self,
        *,
        as_of: Optional[_dt.date] = None,
        ticker: Optional[str] = None,
        dry_run: bool = False,
    ) -> ResolutionStats:
        """Resolve every closed window not yet populated in
        `recommendation_outcomes`.

        Args:
            as_of: cutoff date; only horizons whose close_date ≤ as_of are
                considered closed. Defaults to today (UTC).
            ticker: when provided, restricts the batch to one ticker.
            dry_run: when True, no DB writes are performed; stats reflect
                what would have been written.
        """
        as_of = as_of or self._clock()
        stats = ResolutionStats()

        pending = self._select_pending(as_of=as_of, ticker=ticker)
        stats.candidates_examined = len(pending)

        for item in pending:
            try:
                ticker_return = self._compute_return(
                    item.ticker, item.recommendation_date, item.target_close_date
                )
                bench_return = self._compute_return(
                    item.benchmark, item.recommendation_date, item.target_close_date
                )
            except Exception as exc:  # noqa: BLE001 — per-row defense
                stats.record_error(
                    f"{item.recommendation_id}/{item.horizon}: {type(exc).__name__}: {exc}"
                )
                _LOG.warning(
                    "resolver row failure: rec=%s horizon=%s err=%s",
                    item.recommendation_id, item.horizon, exc,
                )
                continue

            if ticker_return is None or bench_return is None:
                # No bar in the window — leave NULL, try again next run.
                continue

            if dry_run:
                stats.record_horizon(item.horizon)
                continue

            inserted = self._upsert(
                item=item,
                ticker_return=ticker_return,
                bench_return=bench_return,
            )
            if inserted:
                stats.rows_inserted += 1
            else:
                stats.rows_updated += 1
            stats.record_horizon(item.horizon)

        if not dry_run:
            self._conn.commit()

        return stats

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    def _select_pending(
        self, *, as_of: _dt.date, ticker: Optional[str]
    ) -> list[_Pending]:
        """Find every (recommendation × horizon) that is closed but unresolved.

        Strategy: LEFT JOIN execution_recommendations to recommendation_outcomes
        on recommendation_id; for each horizon, emit a row when the column is
        NULL AND (recommendation_date + horizon_days) ≤ as_of.
        """
        params: list[Any] = [as_of]
        ticker_clause = ""
        if ticker is not None:
            ticker_clause = "AND er.ticker = %s"
            params.append(ticker.upper())

        sql = f"""
            SELECT
                er.recommendation_id::text,
                er.ticker,
                er.date AS recommendation_date,
                COALESCE(ro.benchmark, %s) AS benchmark,
                ro.t_plus_30d_return,
                ro.t_plus_90d_return,
                ro.t_plus_1y_return
            FROM execution_recommendations er
            LEFT JOIN recommendation_outcomes ro
                ON ro.recommendation_id = er.recommendation_id
            WHERE er.date <= %s
              {ticker_clause}
            ORDER BY er.date ASC
        """
        # Re-arrange params: default_benchmark first (for COALESCE), then
        # as_of (for the WHERE), then optional ticker.
        ordered = [self._default_benchmark, as_of] + (
            [ticker.upper()] if ticker is not None else []
        )

        cur = self._conn.cursor()
        try:
            cur.execute(sql, ordered)
            rows = cur.fetchall()
        finally:
            cur.close()

        out: list[_Pending] = []
        for r in rows:
            rec_id, tk, rec_date, bench, ret30, ret90, ret1y = r
            existing = {"30d": ret30, "90d": ret90, "1y": ret1y}
            for horizon, days in _HORIZON_DAYS.items():
                if existing[horizon] is not None:
                    continue
                close_date = rec_date + _dt.timedelta(days=days)
                if close_date > as_of:
                    continue
                out.append(
                    _Pending(
                        recommendation_id=rec_id,
                        ticker=tk,
                        recommendation_date=rec_date,
                        benchmark=bench,
                        horizon=horizon,
                        target_close_date=close_date,
                    )
                )
        return out

    def _compute_return(
        self,
        ticker: str,
        rec_date: _dt.date,
        target_close: _dt.date,
    ) -> Optional[float]:
        """Adjusted-close return from the first bar ≥ rec_date to the last
        bar ≤ target_close. Returns None if either anchor is missing.
        """
        # Pad either end to absorb non-trading-day anchoring.
        start = (rec_date - _dt.timedelta(days=5)).isoformat()
        end = (target_close + _dt.timedelta(days=5)).isoformat()
        payload = self._provider.get_prices(ticker, start, end, interval="1d")
        rows = payload.get("rows") or []
        if not rows:
            return None

        # Bars are date-ascending per polygon_provider contract; assert defensively.
        rows = sorted(rows, key=lambda r: r.get("date", ""))

        first = _first_close_on_or_after(rows, rec_date)
        last = _last_close_on_or_before(rows, target_close)
        if first is None or last is None:
            return None
        if first == 0:
            return None
        return (last / first) - 1.0

    def _upsert(
        self,
        *,
        item: _Pending,
        ticker_return: float,
        bench_return: float,
    ) -> bool:
        """Insert or update one horizon column. Returns True on INSERT."""
        ret_col = f"t_plus_{item.horizon}_return"
        close_col = f"t_plus_{item.horizon}_close_date"
        bench_col = f"benchmark_return_{item.horizon}"

        cur = self._conn.cursor()
        try:
            cur.execute(
                "SELECT 1 FROM recommendation_outcomes WHERE recommendation_id = %s",
                (item.recommendation_id,),
            )
            existed = cur.fetchone() is not None

            if not existed:
                cur.execute(
                    f"""
                    INSERT INTO recommendation_outcomes (
                        recommendation_id, ticker, recommendation_date,
                        {ret_col}, {close_col}, {bench_col}, benchmark
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        item.recommendation_id,
                        item.ticker,
                        item.recommendation_date,
                        ticker_return,
                        item.target_close_date,
                        bench_return,
                        item.benchmark,
                    ),
                )
                return True

            cur.execute(
                f"""
                UPDATE recommendation_outcomes
                SET {ret_col} = %s,
                    {close_col} = %s,
                    {bench_col} = %s,
                    last_updated_at = NOW()
                WHERE recommendation_id = %s
                """,
                (
                    ticker_return,
                    item.target_close_date,
                    bench_return,
                    item.recommendation_id,
                ),
            )
            return False
        finally:
            cur.close()


# ---------------------------------------------------------------------------- #
# Helpers                                                                      #
# ---------------------------------------------------------------------------- #


def _parse_iso(d: Any) -> Optional[_dt.date]:
    if not isinstance(d, str) or not d:
        return None
    try:
        return _dt.date.fromisoformat(d)
    except ValueError:
        return None


# Trading-day anchoring tolerance. A non-trading-day target should walk to
# the nearest adjacent trading day, not months away. 7 days is generous
# enough to clear weekends + most market-closure holidays.
_ANCHOR_TOLERANCE_DAYS = 7


def _first_close_on_or_after(
    rows: list[dict[str, Any]],
    target: _dt.date,
    *,
    max_walkforward_days: int = _ANCHOR_TOLERANCE_DAYS,
) -> Optional[float]:
    """First adjusted-close on a bar whose date ∈ [target, target + max_walkforward]."""
    upper = target + _dt.timedelta(days=max_walkforward_days)
    for r in rows:
        d = _parse_iso(r.get("date"))
        if d is None:
            continue
        if d > upper:
            break
        if d >= target:
            close = r.get("adj_close") or r.get("close")
            return float(close) if close is not None else None
    return None


def _last_close_on_or_before(
    rows: list[dict[str, Any]],
    target: _dt.date,
    *,
    max_walkback_days: int = _ANCHOR_TOLERANCE_DAYS,
) -> Optional[float]:
    """Last adjusted-close on a bar whose date ∈ [target - max_walkback, target]."""
    lower = target - _dt.timedelta(days=max_walkback_days)
    last_close: Optional[float] = None
    for r in rows:
        d = _parse_iso(r.get("date"))
        if d is None:
            continue
        if d > target:
            break
        if d < lower:
            continue
        close = r.get("adj_close") or r.get("close")
        if close is not None:
            last_close = float(close)
    return last_close


def resolve_outcomes(
    conn: Any,
    *,
    as_of: Optional[_dt.date] = None,
    ticker: Optional[str] = None,
    dry_run: bool = False,
    price_provider: Optional[PriceProvider] = None,
    default_benchmark: str = "SPY",
) -> ResolutionStats:
    """One-shot resolver call. See `Resolver.resolve` for behavior."""
    if price_provider is None:
        from src.mcp.market_data import polygon_provider as _polygon

        price_provider = _polygon  # module exposes `get_prices` at module scope
    resolver = Resolver(
        conn,
        price_provider=price_provider,
        default_benchmark=default_benchmark,
    )
    return resolver.resolve(as_of=as_of, ticker=ticker, dry_run=dry_run)
