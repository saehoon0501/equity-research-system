"""Pre-mortem scheduler — runs daily; checks all watchlist names.

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.5 Q4: calendar floor + 4 event triggers ORd; if ANY fires,
the name surfaces as ``pre-mortem due`` to the alerts queue.

Trigger 4 (mode reclassification proposed) is **mandatory before
commit** — the scheduler tags it as ``blocking`` so downstream commit
flows refuse to advance until the pre-mortem is recorded.

This module does NOT deliver pushes (Wave C); it produces a queue of
``ScheduledPremortem`` records and writes the ``pre-mortem due`` to a
local /alerts table read by the operator UI.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from . import (
    TRIGGER_CALENDAR_FLOOR,
    TRIGGER_MODE_RECLASS,
    VALID_TRIGGERS,
)
from .cadence import CadenceStatus, cadence_status
from .event_triggers import (
    TriggerCheck,
    check_auto_tighten,
    check_consecutive_m2,
    check_mode_reclass_proposed,
    check_thesis_confirmation,
)

_LOG = logging.getLogger(__name__)


def _dsn() -> str:
    return os.environ.get(
        "EQUITY_RESEARCH_DSN",
        "postgresql://postgres@127.0.0.1:5432/equity_research",
    )


@dataclass
class ScheduledPremortem:
    """One ticker's scheduled pre-mortem decision."""

    ticker: str
    mode: str
    due: bool
    triggers: list[str] = field(default_factory=list)
    cadence: Optional[CadenceStatus] = None
    event_checks: list[TriggerCheck] = field(default_factory=list)
    blocking: bool = False  # True when Trigger 4 fires
    primary_trigger: Optional[str] = None
    detail: dict[str, Any] = field(default_factory=dict)


def _resolve_primary(triggers: list[str]) -> Optional[str]:
    """Priority for primary_trigger:
    mode_reclass > thesis_confirmation > consecutive_m2 > auto_tighten >
    calendar_floor.
    """
    priority = [
        "mode_reclass",
        "thesis_confirmation",
        "consecutive_m2",
        "auto_tighten",
        TRIGGER_CALENDAR_FLOOR,
    ]
    for t in priority:
        if t in triggers:
            return t
    return None


def schedule_check_one(
    ticker: str,
    mode: str,
    *,
    as_of: Optional[str] = None,
    drawdown_vs_benchmark_pp: Optional[float] = None,
    cadence_override: Optional[CadenceStatus] = None,
    event_overrides: Optional[dict[str, TriggerCheck]] = None,
) -> ScheduledPremortem:
    """Run all checks for one ticker.

    Args:
        ticker: equity ticker.
        mode: B / B_prime / C.
        as_of: ISO date (default today).
        drawdown_vs_benchmark_pp: precomputed drawdown for Trigger 3.
        cadence_override: pre-fetched cadence status (tests).
        event_overrides: dict ``{trigger_code: TriggerCheck}`` (tests).

    Returns:
        ScheduledPremortem. ``due`` = OR of cadence + 4 triggers.
    """
    ticker = ticker.upper().strip()
    overrides = event_overrides or {}

    cad = cadence_override or cadence_status(ticker, mode, as_of=as_of)

    t1 = overrides.get("thesis_confirmation") or check_thesis_confirmation(
        ticker, as_of=as_of
    )
    t2 = overrides.get("consecutive_m2") or check_consecutive_m2(
        ticker, as_of=as_of
    )
    t3 = overrides.get("auto_tighten") or check_auto_tighten(
        ticker, mode, drawdown_vs_benchmark_pp=drawdown_vs_benchmark_pp
    )
    t4 = overrides.get("mode_reclass") or check_mode_reclass_proposed(ticker)

    triggers: list[str] = []
    if cad.due:
        triggers.append(TRIGGER_CALENDAR_FLOOR)
    for chk in (t1, t2, t3, t4):
        if chk.triggered:
            triggers.append(chk.trigger_code)

    blocking = TRIGGER_MODE_RECLASS in triggers
    due = bool(triggers)
    primary = _resolve_primary(triggers)

    return ScheduledPremortem(
        ticker=ticker,
        mode=mode,
        due=due,
        triggers=triggers,
        cadence=cad,
        event_checks=[t1, t2, t3, t4],
        blocking=blocking,
        primary_trigger=primary,
        detail={
            # UTC date — ``date.today()`` reads server local tz.
            "as_of": as_of or _dt.datetime.now(_dt.timezone.utc).date().isoformat(),
        },
    )


def _fetch_watchlist_modes() -> list[tuple[str, str]]:
    """Return ``[(ticker, mode), ...]`` from the watchlist."""
    try:
        import psycopg  # deferred
    except ImportError:
        return []
    try:
        with psycopg.connect(_dsn()) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ticker, mode FROM watchlist ORDER BY ticker"
                )
                return [(r[0], r[1]) for r in cur.fetchall()]
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.exception("watchlist fetch failed: %s", exc)
        return []


def schedule_check_all(
    *,
    as_of: Optional[str] = None,
    drawdowns: Optional[dict[str, float]] = None,
) -> list[ScheduledPremortem]:
    """Bulk schedule-check across the entire watchlist.

    Args:
        as_of: ISO date.
        drawdowns: optional ``ticker -> drawdown_pp`` map (Trigger 3).

    Returns:
        One ScheduledPremortem per watchlist row. The caller is
        responsible for surfacing ``[s for s in results if s.due]`` to
        the alerts queue.
    """
    rows = _fetch_watchlist_modes()
    drawdowns = drawdowns or {}
    out: list[ScheduledPremortem] = []
    for ticker, mode in rows:
        try:
            out.append(
                schedule_check_one(
                    ticker,
                    mode,
                    as_of=as_of,
                    drawdown_vs_benchmark_pp=drawdowns.get(ticker),
                )
            )
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.exception("schedule_check_one failure on %s: %s", ticker, exc)
    return out


__all__ = [
    "ScheduledPremortem",
    "schedule_check_one",
    "schedule_check_all",
]
