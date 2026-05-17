"""Channel 3 — Periodic forced re-read (calendar floor).

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.5 Q5 line 534::

    3. Periodic forced re-read: cadence matches Q4 (B 180d, B' 120d,
       C 60d); operator must explicitly acknowledge or revise

This channel is purely time-based — no LLM, no quantitative computation.
The ``last_reread`` baseline is taken from the most recent
``anchor_drift_checks`` row where Channel 3 fired and the operator
acknowledged the review. If absent, ``watchlist.added_at`` is the
fallback baseline.

Operator UX: when this channel triggers, the orchestrator must display
``thesis_pillars_original`` verbatim alongside the current operating
thesis (handled in the audit-trail viewer; this module surfaces the
trigger + payload).
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass
from typing import Any, Optional

from . import CADENCE_DAYS_BY_MODE

_LOG = logging.getLogger(__name__)


@dataclass
class PeriodicRereadResult:
    """One name's Channel 3 result.

    ``payload`` matches the JSONB shape documented in
    ``010_v3_drift_detection.sql`` for ``channel_3_periodic_reread``.
    """

    triggered: bool
    last_reread: str  # ISO date
    days_elapsed: int
    cadence_threshold_days: int
    mode: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "last_reread": self.last_reread,
            "days_elapsed": int(self.days_elapsed),
            "cadence_threshold_days": int(self.cadence_threshold_days),
            "mode": self.mode,
            "triggered": bool(self.triggered),
        }


def _coerce_date(value: Any) -> _dt.date:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        return _dt.date.fromisoformat(value[:10])
    raise TypeError(f"unparseable date: {value!r}")


def detect_periodic_reread(
    *,
    ticker: str,
    mode: str,
    last_reread_date: Any,
    as_of: Optional[str] = None,
) -> PeriodicRereadResult:
    """Run Channel 3 periodic-reread detection for one ticker.

    Args:
        ticker: equity ticker (for logging).
        mode: one of ``B`` / ``B_prime`` / ``C``.
        last_reread_date: date of most recent operator-acknowledged
            re-read (fallback: watchlist.added_at).
        as_of: ISO date for the check (default today).

    Returns:
        PeriodicRereadResult with ``triggered`` true when
        ``days_elapsed >= cadence_threshold_days``.
    """
    ticker = ticker.upper().strip()
    # UTC date — ``date.today()`` reads server local tz.
    today = (
        _dt.date.fromisoformat(as_of)
        if as_of
        else _dt.datetime.now(_dt.timezone.utc).date()
    )
    last = _coerce_date(last_reread_date)
    days_elapsed = (today - last).days
    threshold = CADENCE_DAYS_BY_MODE.get(mode)
    if threshold is None:
        # Unknown mode -> default to most aggressive (most-frequent) cadence.
        _LOG.warning(
            "Unknown mode %r for %s; defaulting Channel 3 cadence to 60d",
            mode, ticker,
        )
        threshold = CADENCE_DAYS_BY_MODE["C"]
    triggered = days_elapsed >= threshold
    return PeriodicRereadResult(
        triggered=triggered,
        last_reread=last.isoformat(),
        days_elapsed=days_elapsed,
        cadence_threshold_days=threshold,
        mode=mode,
    )


__all__ = ["PeriodicRereadResult", "detect_periodic_reread"]
