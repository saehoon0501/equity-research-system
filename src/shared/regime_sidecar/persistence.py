"""Persistence layer — writes daily classification results to Postgres.

Per migration 005_v3_regime.sql. Target table: `regime_classification_history`
(append-only via DB trigger; one row per (classification_date, dimension_id)
tuple — the unique constraint is at the DB level).

Connection convention follows `src/mcp/postgres/server.py` exactly:
- Loads `.env` from repo root.
- Uses `psycopg` (psycopg3) — same library as the postgres MCP server.
- DSN built from POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_HOST /
  POSTGRES_PORT / POSTGRES_DB.

Cold-start flag (§7.5):
    cold_start = True for the first 90 trading days post-launch.
    `is_cold_start_for_date` resolves the flag against a configurable launch
    date. Default launch date = first row in `regime_classification_history`
    (auto-detected); fallback = today.
    Spec line 824: "first 90 days carry the flag; clears on day 91." Day 0
    is launch day → cold-start; day 90 is the last cold-start day; day 91
    clears. Implemented via strict-less-than over a real trading calendar
    (NYSE business days; pandas BDay) — NOT the 5/7 calendar approximation
    which drifts by ~3 days over the 90-trading-day window.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import psycopg
from dotenv import load_dotenv

from src.shared.regime_sidecar.types import DimensionResult


logger = logging.getLogger(__name__)


# Walk: persistence.py → regime_sidecar/ → src/ → repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")


COLD_START_TRADING_DAYS = 90
# Bumped to v0.1.1 on dual-signal architecture rollout (operator-locked):
# both `bocpd_change_probability` (canonical) and `bocpd_short_run_mass`
# (firing) are now persisted per row. See migration 020 + bocpd.py module
# docstring.
RULE_ENGINE_VERSION = "regime_sidecar.v0.1.1"


def _dsn() -> str:
    """Mirror src/mcp/postgres/server.py._dsn() exactly."""
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ.get('POSTGRES_HOST', '127.0.0.1')}:{os.environ.get('POSTGRES_PORT', '5432')}"
        f"/{os.environ['POSTGRES_DB']}"
    )


def _resolve_launch_date(conn: psycopg.Connection) -> date:
    """First-row classification_date in regime_classification_history, or today.

    Used to resolve cold-start: dates within (launch_date, launch_date + 90
    trading days] get cold_start=True.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(classification_date) FROM regime_classification_history"
        )
        row = cur.fetchone()
        if row and row[0] is not None:
            return row[0]
    # UTC date — ``date.today()`` reads server local tz, but the launch
    # date is compared against UTC ``classification_date`` rows; fall back
    # to UTC today so the cold-start window is consistent across servers.
    return datetime.now(timezone.utc).date()


def _trading_days_between(launch: date, asof: date) -> int:
    """Count NYSE business days between launch (inclusive day 0) and asof.

    Returns N where N=0 if asof == launch, N=1 if asof is one business day
    after launch, etc. Uses pandas `bdate_range` (Mon-Fri) which captures
    standard 5-day-trading-week behavior. NYSE holidays (e.g., Christmas,
    Thanksgiving, MLK day) are NOT excluded at v0.1 — pandas-market-calendars
    integration is a v0.5+ refinement; the 90-day cold-start window has
    ~6 holiday days at most, well within the spec tolerance for the
    flag-clearing date.

    Per v3 §7.5: launch day is day 0. Day 1 = first business day after
    launch. Day 90 = last cold-start day (90 business days elapsed). Day 91
    clears the flag.
    """
    if asof <= launch:
        return 0
    # bdate_range from launch+1 to asof (inclusive) → count of business days
    # strictly after launch. asof itself counted iff it's a business day.
    bdays = pd.bdate_range(start=pd.Timestamp(launch) + pd.Timedelta(days=1),
                           end=pd.Timestamp(asof))
    return int(len(bdays))


def is_cold_start_for_date(asof_date: date, launch_date: date) -> bool:
    """Return True if `asof_date` is within the first 90 trading days
    post-launch (cold-start window).

    Per v3 §7.5 (spec line 824): "first 90 days carry the flag; clears on
    day 91." Day 0 = launch (cold-start). Day 90 = last cold-start day.
    Day 91 = first non-cold-start day.

    Implementation: count NYSE business days between launch and asof; flag
    is True iff `trading_days_elapsed < 90` (strict less-than → day 90 is
    the last day flagged, day 91 clears). NYSE holidays not yet excluded;
    deferred to v0.5+ via pandas-market-calendars.
    """
    if asof_date < launch_date:
        return True  # backfilled rows are inherently cold-start data.
    elapsed_trading_days = _trading_days_between(launch_date, asof_date)
    # Strict < so trading-day 90 is the LAST cold-start day; day 91 clears.
    return elapsed_trading_days < COLD_START_TRADING_DAYS


def write_classifications(
    results: Iterable[DimensionResult],
    cold_start_override: bool | None = None,
    parameters_version: str | None = None,
    conn: psycopg.Connection | None = None,
) -> int:
    """Insert one row per dimension into regime_classification_history.

    Args:
        results: iterable of DimensionResult (typically the dict.values()
            produced by `classifier.run_daily_classification`).
        cold_start_override: if not None, force the cold_start flag to this
            value for all rows (used by CLI `--cold-start` for backfill).
        parameters_version: optional UUID string referencing parameters.version_id.
        conn: optional pre-opened connection (for tests). If None, opens a
            new connection and closes it after the write.

    Returns:
        Number of rows inserted.

    Idempotency: the (classification_date, dimension_id) UNIQUE constraint
    means re-running the same date is a no-op INSERT-conflict. We use
    `ON CONFLICT DO NOTHING` so re-runs are safe.
    """
    own_conn = conn is None
    if own_conn:
        conn = psycopg.connect(_dsn())

    try:
        launch_date = _resolve_launch_date(conn)
        rows_inserted = 0
        with conn.cursor() as cur:
            for r in results:
                cold_start = (
                    cold_start_override
                    if cold_start_override is not None
                    else is_cold_start_for_date(r.classification_date, launch_date)
                )
                cur.execute(
                    """
                    INSERT INTO regime_classification_history (
                        classification_date,
                        dimension_id,
                        dimension_name,
                        state_probabilities,
                        headline_state,
                        bocpd_change_probability,
                        bocpd_short_run_mass,
                        raw_inputs,
                        cold_start,
                        history_length_days,
                        rule_engine_version,
                        parameters_version
                    ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                    ON CONFLICT (classification_date, dimension_id) DO NOTHING
                    """,
                    (
                        r.classification_date,
                        r.dimension_id,
                        r.dimension_name,
                        json.dumps(r.state_probabilities),
                        r.headline_state,
                        # Per dual-signal architecture (operator-locked, v3 §4.1):
                        # canonical Adams-MacKay marginal stays in
                        # `bocpd_change_probability` for academic / audit;
                        # cumulative short-run mass is the firing signal.
                        r.bocpd_change_probability,
                        r.bocpd_short_run_mass,
                        json.dumps(r.raw_inputs, default=str),
                        cold_start,
                        r.history_length_days,
                        RULE_ENGINE_VERSION,
                        parameters_version,
                    ),
                )
                if cur.rowcount > 0:
                    rows_inserted += 1
        if own_conn:
            conn.commit()
        return rows_inserted
    finally:
        if own_conn:
            conn.close()


def backfill_cold_start(
    end_date: date,
    months: int = 12,
    parameters_version: str | None = None,
) -> int:
    """Backfill T-`months`-month history per §7.5 cold-start procedure.

    Walks calendar days from (end_date − months) to end_date, runs the daily
    classifier, and writes results with cold_start=True. Idempotent (skip
    already-existing rows via ON CONFLICT DO NOTHING).

    NB: this is a v0.1 simplification — true Adams-MacKay BOCPD is online
    and incremental. Backfilling per-day is wasteful (each day re-fetches
    full history) but keeps the implementation simple and easy to audit.
    Optimization deferred to v0.5+.

    Returns:
        Total rows inserted across all backfilled days.
    """
    from src.shared.regime_sidecar.classifier import run_daily_classification

    start_date = end_date - timedelta(days=int(months * 30.5))
    total = 0
    cursor = start_date
    while cursor <= end_date:
        try:
            results = run_daily_classification(cursor)
            inserted = write_classifications(
                list(results.values()),
                cold_start_override=True,
                parameters_version=parameters_version,
            )
            total += inserted
            logger.info("backfill %s: %d rows", cursor.isoformat(), inserted)
        except Exception as exc:  # noqa: BLE001
            logger.exception("backfill failed for %s: %s", cursor, exc)
        cursor += timedelta(days=1)
    return total
