"""Override-outcome resolver — calibration-circularity defense (v3 spec §6.0).

For every row in `operator_overrides`, the operator chose a different
sizing / routing / mode / recommendation / exit timing than the system
proposed. To avoid v0.5+ formulas calibrating *toward* the operator's
behavioral biases, §6.0 mandates per-override outcome capture:

    actual_outcome_t<N>          — what happened under the OPERATOR's choice
    counterfactual_outcome_t<N>  — what WOULD have happened under the SYSTEM's
                                    recommendation (shadow-portfolio replay)

The boolean `operator_was_better` (GENERATED at T+1y) collapses the
comparison; `system_vs_operator_brier` view (migration 025) aggregates
this per (mode, materiality, recommendation_type) cell so the calibration
sign convention can flip when the operator outperforms.

Resolution policy at v0.1:
    * Actual outcome — same arithmetic as recommendation_outcomes:
      adjusted-close return at T+30/90/365. The override is identified by
      ticker+date; we treat the operator's choice as a long position in
      the ticker on that date, regardless of override_type. (For sizing
      overrides this overstates the effect; v0.5+ refinement is to scale by
      the actual sizing delta read from operator_overrides.new_value.)
    * Counterfactual outcome — for `recommendation` and `veto` override
      types, the system's choice was different from the operator's. Per
      operator decision 2026-05-04 the v0.1 counterfactual baseline is
      SPY benchmark return over the same window — i.e., the system's
      "what we would have done" defaults to "stayed in benchmark" for
      overrides that veto a BUY. For overrides where both system and
      operator chose to be long but at different sizes, the counterfactual
      is the same ticker return (size cancels out at the per-row level —
      the divergence shows up in fill_divergence, not here).

Idempotency:
    Per-override UPSERT keyed on `override_id`. Rows with both T+N values
    populated are skipped on subsequent runs.
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from src.outcomes.resolver import (
    PriceProvider,
    _first_close_on_or_after,
    _last_close_on_or_before,
)

_LOG = logging.getLogger(__name__)

_HORIZON_DAYS: dict[str, int] = {"30d": 30, "90d": 90, "1y": 365}
_MAX_ERRORS_RETAINED = 50


@dataclass
class OverrideResolutionStats:
    """Outcome of an override-resolver invocation."""

    candidates_examined: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    horizons_resolved: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def record_horizon(self, horizon: str) -> None:
        self.horizons_resolved[horizon] = self.horizons_resolved.get(horizon, 0) + 1

    def record_error(self, msg: str) -> None:
        if len(self.errors) < _MAX_ERRORS_RETAINED:
            self.errors.append(msg)


@dataclass
class _PendingOverride:
    override_id: str
    ticker: str
    override_date: _dt.date
    override_type: str
    horizon: str
    target_close_date: _dt.date


class OverrideResolver:
    """Resolves T+30/90/365 actual + counterfactual returns for operator
    overrides per spec §6.0."""

    def __init__(
        self,
        conn: Any,
        *,
        price_provider: PriceProvider,
        counterfactual_benchmark: str = "SPY",
    ) -> None:
        self._conn = conn
        self._provider = price_provider
        self._cf_benchmark = counterfactual_benchmark

    def resolve(
        self,
        *,
        as_of: Optional[_dt.date] = None,
        ticker: Optional[str] = None,
        dry_run: bool = False,
    ) -> OverrideResolutionStats:
        as_of = as_of or _dt.datetime.now(_dt.timezone.utc).date()
        stats = OverrideResolutionStats()

        pending = self._select_pending(as_of=as_of, ticker=ticker)
        stats.candidates_examined = len(pending)

        for item in pending:
            try:
                actual = self._compute_return(
                    item.ticker, item.override_date, item.target_close_date
                )
                counterfactual = self._counterfactual(
                    item, target_close=item.target_close_date
                )
            except Exception as exc:  # noqa: BLE001
                stats.record_error(
                    f"{item.override_id}/{item.horizon}: {type(exc).__name__}: {exc}"
                )
                _LOG.warning(
                    "override resolver failure: id=%s horizon=%s err=%s",
                    item.override_id, item.horizon, exc,
                )
                continue

            if actual is None or counterfactual is None:
                continue

            if dry_run:
                stats.record_horizon(item.horizon)
                continue

            inserted = self._upsert(item, actual=actual, counterfactual=counterfactual)
            if inserted:
                stats.rows_inserted += 1
            else:
                stats.rows_updated += 1
            stats.record_horizon(item.horizon)

        if not dry_run:
            self._conn.commit()

        return stats

    # ---------------- internals ----------------

    def _select_pending(
        self, *, as_of: _dt.date, ticker: Optional[str]
    ) -> list[_PendingOverride]:
        params: list[Any] = []
        ticker_clause = ""
        if ticker is not None:
            ticker_clause = "AND oo.ticker = %s"
            params.append(ticker.upper())

        sql = f"""
            SELECT
                oo.override_id::text,
                oo.ticker,
                oo.override_date::date,
                oo.override_type,
                ovo.actual_outcome_t30d,
                ovo.actual_outcome_t90d,
                ovo.actual_outcome_t1y,
                ovo.counterfactual_outcome_t30d,
                ovo.counterfactual_outcome_t90d,
                ovo.counterfactual_outcome_t1y
            FROM operator_overrides oo
            LEFT JOIN override_outcomes ovo
                ON ovo.override_id = oo.override_id
            WHERE oo.override_date::date <= %s
              {ticker_clause}
            ORDER BY oo.override_date ASC
        """
        cur = self._conn.cursor()
        try:
            cur.execute(sql, [as_of] + params)
            rows = cur.fetchall()
        finally:
            cur.close()

        out: list[_PendingOverride] = []
        for r in rows:
            (
                ovid, tk, od, ot,
                a30, a90, a1y,
                c30, c90, c1y,
            ) = r
            actual_present = {"30d": a30, "90d": a90, "1y": a1y}
            cf_present = {"30d": c30, "90d": c90, "1y": c1y}
            for horizon, days in _HORIZON_DAYS.items():
                if actual_present[horizon] is not None and cf_present[horizon] is not None:
                    continue
                close_date = od + _dt.timedelta(days=days)
                if close_date > _dt.datetime.now(_dt.timezone.utc).date():
                    continue
                out.append(
                    _PendingOverride(
                        override_id=ovid,
                        ticker=tk,
                        override_date=od,
                        override_type=ot,
                        horizon=horizon,
                        target_close_date=close_date,
                    )
                )
        return out

    def _compute_return(
        self,
        ticker: str,
        anchor_date: _dt.date,
        target_close: _dt.date,
    ) -> Optional[float]:
        start = (anchor_date - _dt.timedelta(days=5)).isoformat()
        end = (target_close + _dt.timedelta(days=5)).isoformat()
        payload = self._provider.get_prices(ticker, start, end, interval="1d")
        rows = sorted(payload.get("rows") or [], key=lambda r: r.get("date", ""))
        if not rows:
            return None
        first = _first_close_on_or_after(rows, anchor_date)
        last = _last_close_on_or_before(rows, target_close)
        if first is None or last is None or first == 0:
            return None
        return (last / first) - 1.0

    def _counterfactual(
        self, item: _PendingOverride, *, target_close: _dt.date
    ) -> Optional[float]:
        """System's would-have outcome.

        v0.1 baseline:
            * `recommendation` / `veto` override → benchmark (SPY) return,
              i.e., system effectively "stayed in benchmark."
            * other types (sizing / routing / mode / exit_timing) → same
              ticker return; the size/mode delta lives in fill_divergence
              and doesn't change the per-row counterfactual at this grain.
        """
        if item.override_type in {"recommendation", "veto"}:
            return self._compute_return(
                self._cf_benchmark, item.override_date, target_close
            )
        return self._compute_return(item.ticker, item.override_date, target_close)

    def _upsert(
        self,
        item: _PendingOverride,
        *,
        actual: float,
        counterfactual: float,
    ) -> bool:
        actual_col = f"actual_outcome_t{item.horizon}"
        cf_col = f"counterfactual_outcome_t{item.horizon}"

        cur = self._conn.cursor()
        try:
            cur.execute(
                "SELECT 1 FROM override_outcomes WHERE override_id = %s",
                (item.override_id,),
            )
            existed = cur.fetchone() is not None

            if not existed:
                cur.execute(
                    f"""
                    INSERT INTO override_outcomes (
                        override_id, ticker, override_date,
                        {actual_col}, {cf_col}
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        item.override_id,
                        item.ticker,
                        item.override_date,
                        actual,
                        counterfactual,
                    ),
                )
                return True

            cur.execute(
                f"""
                UPDATE override_outcomes
                SET {actual_col} = %s,
                    {cf_col}     = %s,
                    last_updated_at = NOW()
                WHERE override_id = %s
                """,
                (actual, counterfactual, item.override_id),
            )
            return False
        finally:
            cur.close()


def resolve_override_outcomes(
    conn: Any,
    *,
    as_of: Optional[_dt.date] = None,
    ticker: Optional[str] = None,
    dry_run: bool = False,
    price_provider: Optional[PriceProvider] = None,
    counterfactual_benchmark: str = "SPY",
) -> OverrideResolutionStats:
    """One-shot helper. See `OverrideResolver.resolve`."""
    if price_provider is None:
        from src.mcp.market_data import polygon_provider as _polygon
        price_provider = _polygon
    resolver = OverrideResolver(
        conn,
        price_provider=price_provider,
        counterfactual_benchmark=counterfactual_benchmark,
    )
    return resolver.resolve(as_of=as_of, ticker=ticker, dry_run=dry_run)
