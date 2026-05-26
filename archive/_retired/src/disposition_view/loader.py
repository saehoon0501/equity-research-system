"""Postgres query layer for /disposition.

Per v3 spec Section 4.6 Q2 + Section 5.4 + Phase 4 Q5.

One row per watchlist name. The loader joins five sources and packages
them into `DispositionRow` dataclasses (read-only):
  - watchlist                   (mode, conviction_threshold, regime_sensitivity)
  - positions                   (current shares + cost basis; nullable)
  - execution_recommendations   (latest per ticker; envelope per Section 4.6 Q1)
  - daily_refresh_log           (latest per ticker; recommended_action +
                                  materiality + events)
  - mode_classifications        (latest per ticker; recheck_status drives
                                  pending_reclassification flag)
  - mode_vol_checks             (latest per ticker; vol-band data for
                                  Phase 4 Q5 mode-fit dashboard)

The loader does NOT compute the per-horizon signals; that's `horizon_signals.py`.

Connection contract (matches src/audit_trail/loader.py):
  - We do not couple to any specific Postgres driver. Functions accept a
    `conn` object exposing `.cursor()`; cursor must implement
    `.execute(sql, params)` + `.fetchone()/.fetchall()/.close()`.
  - Tests pass a fake conn; production passes psycopg/psycopg2.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Optional, Protocol
from uuid import UUID


class _Cursor(Protocol):
    def execute(self, sql: str, params: Optional[tuple[Any, ...]] = None) -> Any: ...
    def fetchone(self) -> Optional[tuple[Any, ...]]: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...
    def close(self) -> None: ...


class _Connection(Protocol):
    def cursor(self) -> _Cursor: ...


# -----------------------------------------------------------------------------
# Dataclasses
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ModeFitRow:
    """Phase 4 Q5 mode-fit dashboard row.

    Per v3 Section 2.2 (mode silent-failure detection):
      - mode                — the mode the name was filed under (B/B'/C)
      - realized_vol_252d   — latest 252d realized vol from mode_vol_checks
      - mode_band_low/high  — expected vol band for this mode
      - within_band         — whether realized falls inside the expected band
      - consecutive_outside_count — flips the flag at >= 2 consecutive
      - flagged             — denormalized; true when the dashboard surfaces
      - last_confirmed_date — last classified_at where recheck_status='confirmed'
      - recheck_status      — confirmed / pending_review / reclassification_proposed
    """

    mode: str
    realized_vol_252d: Optional[float]
    mode_band_low: Optional[float]
    mode_band_high: Optional[float]
    within_band: Optional[bool]
    consecutive_outside_count: int
    flagged: bool
    last_confirmed_date: Optional[date]
    recheck_status: str
    last_check_date: Optional[date]


@dataclass(frozen=True)
class DispositionRow:
    """One watchlist name, packaged for the multi-horizon disposition view.

    Per v3 Section 4.6 Q2 disposition_row schema. Carries enough source data
    that `derive_horizon_signals()` can compute Short / Mid / Long signals
    without re-querying Postgres.
    """

    ticker: str

    # Mode (B/B_prime/C) per Section 2.2 — drives primary horizon mapping.
    mode: str
    company_quality_flag: str
    conviction_threshold: float
    regime_sensitivity: str

    # Latest execution_recommendations envelope (may be None for cold names).
    recommendation: Optional[str]
    conviction: Optional[str]
    conviction_breakdown: Mapping[str, Any]
    sizing_suggestion: Mapping[str, Any]
    execution_context: Mapping[str, Any]
    trigger_metadata: Mapping[str, Any]
    recommendation_id: Optional[UUID]
    recommendation_date: Optional[date]

    # Latest daily_refresh_log (may be None if never refreshed).
    last_refresh_date: Optional[date]
    last_refresh_materiality: Optional[int]
    last_refresh_action: Optional[str]
    last_refresh_events: list[Mapping[str, Any]]

    # Position state (nullable when not yet held).
    shares_held: Optional[float]
    cost_basis: Optional[float]
    first_acquired: Optional[date]

    # Phase 4 Q5 mode-fit dashboard data.
    mode_fit: ModeFitRow


# -----------------------------------------------------------------------------
# Public loader
# -----------------------------------------------------------------------------


def get_disposition_rows(
    conn: _Connection,
    *,
    ticker: Optional[str] = None,
    mode: Optional[str] = None,
) -> list[DispositionRow]:
    """Return per-watchlist-name disposition rows.

    Per v3 Section 4.6 Q2: one row per watchlist name; joins watchlist with
    latest-per-ticker projections from execution_recommendations,
    daily_refresh_log, mode_classifications, mode_vol_checks; left-joins
    positions (cold names have no position row).

    Args:
        conn:    PEP-249-style connection.
        ticker:  filter to single ticker (optional).
        mode:    filter to single mode (B / B_prime / C; optional).

    Returns rows in (mode, ticker) order so the rendered table is stable.

    Per Section 5.4 `/disposition`: this is the read entry point.
    """
    cur = conn.cursor()
    try:
        # Watchlist driving table — left join everything else so cold names
        # surface even before they have a recommendation.
        sql = """
            SELECT w.ticker,
                   w.mode,
                   w.company_quality_flag,
                   w.conviction_threshold,
                   w.regime_sensitivity
            FROM watchlist w
            WHERE TRUE
        """
        params: list[Any] = []
        if ticker is not None:
            sql += " AND w.ticker = %s"
            params.append(ticker)
        if mode is not None:
            sql += " AND w.mode = %s"
            params.append(mode)
        sql += " ORDER BY w.mode, w.ticker"
        cur.execute(sql, tuple(params))
        watchlist_rows = cur.fetchall()
    finally:
        cur.close()

    out: list[DispositionRow] = []
    for (
        wticker,
        wmode,
        company_quality_flag,
        conviction_threshold,
        regime_sensitivity,
    ) in watchlist_rows:
        latest_rec = _fetch_latest_recommendation(conn, wticker)
        latest_refresh = _fetch_latest_daily_refresh(conn, wticker)
        position = _fetch_position(conn, wticker)
        mode_fit = _fetch_mode_fit(conn, wticker, wmode)

        out.append(
            DispositionRow(
                ticker=wticker,
                mode=wmode,
                company_quality_flag=company_quality_flag,
                conviction_threshold=float(conviction_threshold)
                if conviction_threshold is not None
                else 0.0,
                regime_sensitivity=regime_sensitivity,
                recommendation=latest_rec.get("recommendation"),
                conviction=latest_rec.get("conviction"),
                conviction_breakdown=latest_rec.get("conviction_breakdown", {}),
                sizing_suggestion=latest_rec.get("sizing_suggestion", {}),
                execution_context=latest_rec.get("execution_context", {}),
                trigger_metadata=latest_rec.get("trigger_metadata", {}),
                recommendation_id=latest_rec.get("recommendation_id"),
                recommendation_date=latest_rec.get("date"),
                last_refresh_date=latest_refresh.get("date"),
                last_refresh_materiality=latest_refresh.get("materiality"),
                last_refresh_action=latest_refresh.get("recommended_action"),
                last_refresh_events=latest_refresh.get("events", []),
                shares_held=position.get("shares_held"),
                cost_basis=position.get("cost_basis"),
                first_acquired=position.get("first_acquired"),
                mode_fit=mode_fit,
            )
        )
    return out


# -----------------------------------------------------------------------------
# Per-source fetch helpers
# -----------------------------------------------------------------------------


def _fetch_latest_recommendation(conn: _Connection, ticker: str) -> dict[str, Any]:
    """Latest execution_recommendations row for a ticker (or empty dict)."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT recommendation_id, ticker, date, recommendation, conviction,
                   conviction_breakdown, sizing_suggestion, execution_context,
                   trigger_metadata
            FROM execution_recommendations
            WHERE ticker = %s
            ORDER BY date DESC, created_at DESC
            LIMIT 1
            """,
            (ticker,),
        )
        row = cur.fetchone()
        if row is None:
            return {}
        return {
            "recommendation_id": _coerce_uuid(row[0]),
            "ticker": row[1],
            "date": row[2],
            "recommendation": row[3],
            "conviction": row[4],
            "conviction_breakdown": _coerce_jsonb(row[5]),
            "sizing_suggestion": _coerce_jsonb(row[6]),
            "execution_context": _coerce_jsonb(row[7]),
            "trigger_metadata": _coerce_jsonb(row[8]),
        }
    finally:
        cur.close()


def _fetch_latest_daily_refresh(conn: _Connection, ticker: str) -> dict[str, Any]:
    """Latest daily_refresh_log row for a ticker (or empty dict)."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT date, materiality, recommended_action, events
            FROM daily_refresh_log
            WHERE ticker = %s
            ORDER BY date DESC, created_at DESC
            LIMIT 1
            """,
            (ticker,),
        )
        row = cur.fetchone()
        if row is None:
            return {}
        events = _coerce_jsonb(row[3])
        return {
            "date": row[0],
            "materiality": int(row[1]) if row[1] is not None else None,
            "recommended_action": row[2],
            "events": events if isinstance(events, list) else [],
        }
    finally:
        cur.close()


def _fetch_position(conn: _Connection, ticker: str) -> dict[str, Any]:
    """Aggregated position row (sum across accounts) for a ticker.

    Returns empty dict if not held. Cost basis is share-weighted average
    when held in multiple accounts.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT SUM(shares_held)                                    AS shares_held,
                   CASE WHEN SUM(shares_held) > 0
                        THEN SUM(shares_held * cost_basis) / SUM(shares_held)
                        ELSE NULL
                   END                                                  AS avg_cost_basis,
                   MIN(first_acquired)                                  AS first_acquired
            FROM positions
            WHERE ticker = %s
            """,
            (ticker,),
        )
        row = cur.fetchone()
        if row is None or row[0] is None:
            return {}
        return {
            "shares_held": float(row[0]) if row[0] is not None else None,
            "cost_basis": float(row[1]) if row[1] is not None else None,
            "first_acquired": row[2],
        }
    finally:
        cur.close()


def _fetch_mode_fit(conn: _Connection, ticker: str, mode: str) -> ModeFitRow:
    """Phase 4 Q5: mode-fit dashboard data for a ticker.

    Joins:
      - latest mode_classifications (for last_confirmed_date / recheck_status)
      - latest mode_vol_checks (for realized_252d_vol + within-band data)
    """
    cur = conn.cursor()
    try:
        # Latest mode_classifications row
        cur.execute(
            """
            SELECT classified_at, recheck_status
            FROM mode_classifications
            WHERE ticker = %s
            ORDER BY classified_at DESC
            LIMIT 1
            """,
            (ticker,),
        )
        cls_row = cur.fetchone()
        recheck_status = cls_row[1] if cls_row else "unknown"

        # Last confirmed classified_at — most recent row with status confirmed.
        cur.execute(
            """
            SELECT classified_at
            FROM mode_classifications
            WHERE ticker = %s AND recheck_status = 'confirmed'
            ORDER BY classified_at DESC
            LIMIT 1
            """,
            (ticker,),
        )
        confirmed_row = cur.fetchone()
        last_confirmed_date: Optional[date] = None
        if confirmed_row is not None:
            ts = confirmed_row[0]
            if isinstance(ts, datetime):
                last_confirmed_date = ts.date()
            elif isinstance(ts, date):
                last_confirmed_date = ts

        # Latest mode_vol_checks row
        cur.execute(
            """
            SELECT check_date, realized_vol_252d, mode_band_low, mode_band_high,
                   within_band, consecutive_outside_count, flagged
            FROM mode_vol_checks
            WHERE ticker = %s
            ORDER BY check_date DESC
            LIMIT 1
            """,
            (ticker,),
        )
        vol_row = cur.fetchone()

        if vol_row is None:
            return ModeFitRow(
                mode=mode,
                realized_vol_252d=None,
                mode_band_low=None,
                mode_band_high=None,
                within_band=None,
                consecutive_outside_count=0,
                flagged=False,
                last_confirmed_date=last_confirmed_date,
                recheck_status=recheck_status,
                last_check_date=None,
            )

        return ModeFitRow(
            mode=mode,
            realized_vol_252d=float(vol_row[1]) if vol_row[1] is not None else None,
            mode_band_low=float(vol_row[2]) if vol_row[2] is not None else None,
            mode_band_high=float(vol_row[3]) if vol_row[3] is not None else None,
            within_band=bool(vol_row[4]) if vol_row[4] is not None else None,
            consecutive_outside_count=int(vol_row[5] or 0),
            flagged=bool(vol_row[6]),
            last_confirmed_date=last_confirmed_date,
            recheck_status=recheck_status,
            last_check_date=vol_row[0],
        )
    finally:
        cur.close()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _coerce_uuid(value: Any) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _coerce_jsonb(value: Any) -> Any:
    """Postgres JSONB: dict/list (psycopg default) or str (raw)."""
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value
