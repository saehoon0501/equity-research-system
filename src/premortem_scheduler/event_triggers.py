"""4 event triggers (force pre-mortem regardless of calendar floor).

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.5 Q4 (lines 522-526):

  1. Thesis-confirmation event (paradoxically dangerous moment)
     -> auto-schedule fresh pre-mortem within 7 days.
  2. Consecutive M-2 events on same name within 30 days.
  3. First auto-tighten threshold crossed (B/S&P 5pp, B'/QQQ 7pp,
     C/IWO 10pp).
  4. Mode reclassification proposed -> mandatory before commit.

Each evaluator returns a TriggerCheck with ``triggered`` + structured
context. Scheduler ORs the four (and the calendar floor) to decide
``due``.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from . import (
    AUTO_TIGHTEN_THRESHOLDS_PP,
    CONSECUTIVE_M2_WINDOW_DAYS,
    THESIS_CONFIRMATION_DEADLINE_DAYS,
    TRIGGER_AUTO_TIGHTEN,
    TRIGGER_CONSECUTIVE_M2,
    TRIGGER_MODE_RECLASS,
    TRIGGER_THESIS_CONFIRMATION,
)

_LOG = logging.getLogger(__name__)


def _dsn() -> str:
    return os.environ.get(
        "EQUITY_RESEARCH_DSN",
        "postgresql://postgres@127.0.0.1:5432/equity_research",
    )


@dataclass
class TriggerCheck:
    """Result of one event-trigger evaluator."""

    triggered: bool
    trigger_code: str
    detail: dict[str, Any] = field(default_factory=dict)
    deadline_date: Optional[str] = None


# --------------------------------------------------------------------------- #
# Trigger 1 — thesis-confirmation event                                       #
# --------------------------------------------------------------------------- #


def check_thesis_confirmation(
    ticker: str,
    *,
    as_of: Optional[str] = None,
    events: Optional[list[dict[str, Any]]] = None,
) -> TriggerCheck:
    """Trigger 1: thesis-confirmation event in last 30 days.

    Per Section 4.5 Q4: thesis-confirming wins are paradoxically the
    moment kill-discipline goes lax — force a pre-mortem within
    ``THESIS_CONFIRMATION_DEADLINE_DAYS`` (7 days).

    Args:
        ticker: equity ticker.
        as_of: ISO date for the check (default today).
        events: optional pre-fetched events list (for tests). Each
            event dict has at minimum ``{event_type, event_date}``.

    Returns:
        TriggerCheck. ``deadline_date`` set when triggered.
    """
    today = (
        _dt.date.fromisoformat(as_of)
        if as_of
        else _dt.datetime.now(_dt.timezone.utc).date()
    )
    if events is None:
        events = _fetch_events(ticker, days=30)
    triggered = any(
        (e.get("event_type") or "").lower() == "thesis_confirmation"
        for e in events
    )
    deadline = (today + _dt.timedelta(days=THESIS_CONFIRMATION_DEADLINE_DAYS))
    return TriggerCheck(
        triggered=triggered,
        trigger_code=TRIGGER_THESIS_CONFIRMATION,
        detail={
            "ticker": ticker,
            "events_scanned": len(events),
        },
        deadline_date=deadline.isoformat() if triggered else None,
    )


# --------------------------------------------------------------------------- #
# Trigger 2 — consecutive M-2 events within 30 days                            #
# --------------------------------------------------------------------------- #


def check_consecutive_m2(
    ticker: str,
    *,
    as_of: Optional[str] = None,
    m2_events: Optional[list[dict[str, Any]]] = None,
) -> TriggerCheck:
    """Trigger 2: >= 2 M-2 events on same name within 30 days.

    Args:
        ticker: equity ticker.
        as_of: ISO date.
        m2_events: optional pre-fetched events; each dict needs
            ``{event_date}`` (date or ISO string) and tier == 'M-2'.

    Returns:
        TriggerCheck.
    """
    today = (
        _dt.date.fromisoformat(as_of)
        if as_of
        else _dt.datetime.now(_dt.timezone.utc).date()
    )
    cutoff = today - _dt.timedelta(days=CONSECUTIVE_M2_WINDOW_DAYS)

    if m2_events is None:
        m2_events = _fetch_m2_events(ticker, since=cutoff)

    in_window = []
    for e in m2_events:
        d = e.get("event_date")
        if isinstance(d, str):
            try:
                d = _dt.date.fromisoformat(d[:10])
            except ValueError:
                continue
        if isinstance(d, _dt.datetime):
            d = d.date()
        if isinstance(d, _dt.date) and d >= cutoff:
            in_window.append(d)

    triggered = len(in_window) >= 2
    return TriggerCheck(
        triggered=triggered,
        trigger_code=TRIGGER_CONSECUTIVE_M2,
        detail={
            "ticker": ticker,
            "m2_count_in_window": len(in_window),
            "window_days": CONSECUTIVE_M2_WINDOW_DAYS,
        },
    )


# --------------------------------------------------------------------------- #
# Trigger 3 — auto-tighten threshold crossed                                  #
# --------------------------------------------------------------------------- #


def check_auto_tighten(
    ticker: str,
    mode: str,
    *,
    drawdown_vs_benchmark_pp: Optional[float] = None,
    benchmark_used: Optional[str] = None,
) -> TriggerCheck:
    """Trigger 3: first time the auto-tighten threshold is crossed.

    Mode-paired thresholds (Section 4.5 Q4 line 525):
      B  /SPY  5 pp
      B' /QQQ  7 pp
      C  /IWO  10 pp

    Args:
        ticker: equity ticker.
        mode: B / B_prime / C.
        drawdown_vs_benchmark_pp: signed drawdown in pp (positive =
            ticker is underperforming benchmark).
        benchmark_used: optional override for the mode-default benchmark.

    Returns:
        TriggerCheck.
    """
    if mode not in AUTO_TIGHTEN_THRESHOLDS_PP:
        return TriggerCheck(
            triggered=False,
            trigger_code=TRIGGER_AUTO_TIGHTEN,
            detail={"ticker": ticker, "error": f"unknown mode {mode!r}"},
        )
    bm, threshold = AUTO_TIGHTEN_THRESHOLDS_PP[mode]
    triggered = (
        drawdown_vs_benchmark_pp is not None
        and drawdown_vs_benchmark_pp >= threshold
    )
    return TriggerCheck(
        triggered=triggered,
        trigger_code=TRIGGER_AUTO_TIGHTEN,
        detail={
            "ticker": ticker,
            "mode": mode,
            "benchmark": benchmark_used or bm,
            "drawdown_pp": drawdown_vs_benchmark_pp,
            "threshold_pp": threshold,
        },
    )


# --------------------------------------------------------------------------- #
# Trigger 4 — mode reclassification proposed -> mandatory before commit       #
# --------------------------------------------------------------------------- #


def check_mode_reclass_proposed(
    ticker: str,
    *,
    pending_proposal: Optional[dict[str, Any]] = None,
) -> TriggerCheck:
    """Trigger 4: a mode-reclassification is proposed.

    Per Section 4.5 Q4 line 526 + Phase 4 Q5: when
    ``mode_classifier.recheck`` writes a ``pending_review`` row, a
    pre-mortem is MANDATORY before any commit to the new mode. This
    trigger is the gate.

    Args:
        ticker: equity ticker.
        pending_proposal: optional pre-fetched
            mode_classifications row in ``pending_review`` state.

    Returns:
        TriggerCheck.
    """
    if pending_proposal is None:
        pending_proposal = _fetch_pending_reclass(ticker)
    triggered = bool(pending_proposal)
    return TriggerCheck(
        triggered=triggered,
        trigger_code=TRIGGER_MODE_RECLASS,
        detail={
            "ticker": ticker,
            "pending_proposal": pending_proposal,
        },
    )


# --------------------------------------------------------------------------- #
# DB fetchers (deferred psycopg import)                                       #
# --------------------------------------------------------------------------- #


def _fetch_events(ticker: str, *, days: int) -> list[dict[str, Any]]:
    """Pull recent events from the calibration / decision-event log.

    Returns ``[{event_type, event_date}, ...]``. Empty on DB error.
    """
    try:
        import psycopg  # deferred
    except ImportError:
        return []
    # UTC date — ``date.today()`` reads server local tz; the resulting
    # ``cutoff`` is sent to a Postgres ``WHERE event_date >= %s`` query.
    cutoff = _dt.datetime.now(_dt.timezone.utc).date() - _dt.timedelta(days=days)
    try:
        with psycopg.connect(_dsn()) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT event_type, event_date
                    FROM calibration_events
                    WHERE ticker = %s AND event_date >= %s
                    ORDER BY event_date DESC
                    """,
                    (ticker, cutoff),
                )
                return [
                    {"event_type": r[0], "event_date": r[1]}
                    for r in cur.fetchall()
                ]
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.debug("calibration_events fetch failed: %s", exc)
        return []


def _fetch_m2_events(
    ticker: str, *, since: _dt.date
) -> list[dict[str, Any]]:
    """Pull M-2 materiality events since cutoff."""
    try:
        import psycopg  # deferred
    except ImportError:
        return []
    try:
        with psycopg.connect(_dsn()) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT event_date
                    FROM materiality_events
                    WHERE ticker = %s
                      AND tier = 'M-2'
                      AND event_date >= %s
                    ORDER BY event_date DESC
                    """,
                    (ticker, since),
                )
                return [{"event_date": r[0]} for r in cur.fetchall()]
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.debug("materiality_events fetch failed: %s", exc)
        return []


def _fetch_pending_reclass(ticker: str) -> Optional[dict[str, Any]]:
    """Find any pending_review row in mode_classifications for ticker."""
    try:
        import psycopg  # deferred
    except ImportError:
        return None
    try:
        with psycopg.connect(_dsn()) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT classification_id, final_mode,
                           rule_outcomes, classified_at
                    FROM mode_classifications
                    WHERE ticker = %s
                      AND recheck_status = 'pending_review'
                    ORDER BY classified_at DESC
                    LIMIT 1
                    """,
                    (ticker,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "classification_id": str(row[0]),
                    "stored_mode": row[1],
                    "rule_outcomes": row[2],
                    "classified_at": (
                        row[3].isoformat() if row[3] else None
                    ),
                }
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.debug("mode_classifications fetch failed: %s", exc)
        return None


__all__ = [
    "TriggerCheck",
    "check_thesis_confirmation",
    "check_consecutive_m2",
    "check_auto_tighten",
    "check_mode_reclass_proposed",
]
