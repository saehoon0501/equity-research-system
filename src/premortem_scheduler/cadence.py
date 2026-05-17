"""Mode-tuned calendar floor for pre-mortem cadence.

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.5 Q4 (lines 514-520)::

    Mode B    180 days
    Mode B'   120 days
    Mode C     60 days

This module reads ``premortem.last_premortem_date`` for the ticker via
``MAX(premortem_date)`` over the append-only ledger and computes
``days_since``. ``due_for_calendar_floor`` returns True when
``days_since >= mode_threshold`` (or no prior pre-mortem on file).
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
from dataclasses import dataclass
from typing import Optional

from . import CADENCE_DAYS_BY_MODE

_LOG = logging.getLogger(__name__)


def _dsn() -> str:
    return os.environ.get(
        "EQUITY_RESEARCH_DSN",
        "postgresql://postgres@127.0.0.1:5432/equity_research",
    )


@dataclass
class CadenceStatus:
    """Result of the calendar-floor check for one ticker."""

    ticker: str
    mode: str
    last_premortem_date: Optional[str]  # ISO date or None
    days_since: Optional[int]
    threshold_days: int
    due: bool


def _fetch_last_premortem(ticker: str) -> Optional[_dt.date]:
    """Return the most-recent premortem.premortem_date for ticker."""
    import psycopg  # deferred

    with psycopg.connect(_dsn()) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(premortem_date) FROM premortem WHERE ticker = %s",
                (ticker,),
            )
            row = cur.fetchone()
            return row[0] if row and row[0] else None


def cadence_status(
    ticker: str,
    mode: str,
    *,
    as_of: Optional[str] = None,
    last_premortem_date: Optional[_dt.date] = None,
) -> CadenceStatus:
    """Compute calendar-floor status for one ticker.

    Args:
        ticker: equity ticker.
        mode: one of ``B`` / ``B_prime`` / ``C``.
        as_of: ISO date for the check (default today).
        last_premortem_date: optional pre-fetched value (for tests).

    Returns:
        CadenceStatus.due is True when ``days_since >= threshold`` or
        when no prior pre-mortem exists for the ticker.
    """
    ticker = ticker.upper().strip()
    # UTC date — ``date.today()`` reads server local tz; ``today`` is used
    # to compute ``days_since`` against a stored UTC date.
    today = (
        _dt.date.fromisoformat(as_of)
        if as_of
        else _dt.datetime.now(_dt.timezone.utc).date()
    )
    threshold = CADENCE_DAYS_BY_MODE.get(mode, CADENCE_DAYS_BY_MODE["C"])

    last = last_premortem_date
    if last is None:
        try:
            last = _fetch_last_premortem(ticker)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.exception("DB fetch failed for %s: %s", ticker, exc)
            last = None

    if last is None:
        return CadenceStatus(
            ticker=ticker,
            mode=mode,
            last_premortem_date=None,
            days_since=None,
            threshold_days=threshold,
            due=True,
        )

    days_since = (today - last).days
    return CadenceStatus(
        ticker=ticker,
        mode=mode,
        last_premortem_date=last.isoformat(),
        days_since=days_since,
        threshold_days=threshold,
        due=days_since >= threshold,
    )


__all__ = ["CadenceStatus", "cadence_status"]
