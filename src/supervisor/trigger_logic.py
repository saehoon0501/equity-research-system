"""P7 trigger logic — Section 4.6 Q3.

Per v3 spec lines 644-652::

    | Mode | Forced cadence floor | Materiality interrupts |
    |---|---|---|
    | B  | Weekly Monday open  | M-2 or M-3 → immediate |
    | B' | Every 3 days        | M-2 or M-3 → immediate |
    | C  | Daily               | M-2 or M-3 → immediate |

    New-candidate trigger: initial BUY recommendation fires upon completion
    of full P3 → P4 funnel approval, regardless of cadence rules.

This module COMPUTES the trigger metadata; it does not run the cadence
scheduler itself. The scheduler (cron-driven separately) calls
``compute_trigger_metadata`` to generate the JSONB envelope embedded in
``execution_recommendations.trigger_metadata``.

Returns ``TriggerMetadata`` matching Section 4.6 Q1::

    trigger_metadata:
      triggered_by: mode_cadence_floor / m2_event / m3_event / new_candidate
      cadence_floor_due_at: ...
      materiality_event_ref: null | event_uuid
      prior_recommendation_date: 2026-04-30
      prior_recommendation: BUY
      changed_from_prior: false
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo


# America/New_York handles DST automatically; `09:30` ET is 13:30 UTC during
# EDT (≈mid-March → early-November) and 14:30 UTC during EST (the rest of
# the year). The previous implementation hard-coded 13:30 UTC, which was
# off by 1 hour for ~5 months/year. See Section 4.6 Q3 mode rules.
_NY_TZ = ZoneInfo("America/New_York")
_NYSE_OPEN_HOUR = 9
_NYSE_OPEN_MINUTE = 30


def _next_session_open_ny(target_date: _dt.date) -> _dt.datetime:
    """Return 09:30 America/New_York on ``target_date`` as an aware UTC dt.

    Avoids DST off-by-1-hour by using ``zoneinfo`` rather than a hard-coded
    UTC offset. The returned datetime is in UTC (so callers can compare /
    serialize without further conversion).
    """
    aware_ny = _dt.datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        _NYSE_OPEN_HOUR,
        _NYSE_OPEN_MINUTE,
        tzinfo=_NY_TZ,
    )
    return aware_ny.astimezone(_dt.timezone.utc)


TRIGGER_NEW_CANDIDATE = "new_candidate"
TRIGGER_MODE_CADENCE_FLOOR = "mode_cadence_floor"
TRIGGER_M2 = "m2_event"
TRIGGER_M3 = "m3_event"

_VALID_TRIGGERS: tuple[str, ...] = (
    TRIGGER_NEW_CANDIDATE,
    TRIGGER_MODE_CADENCE_FLOOR,
    TRIGGER_M2,
    TRIGGER_M3,
)


@dataclass
class TriggerInputs:
    """Cycle inputs: what fired this evaluation, prior emission state."""

    mode: str  # 'B' / 'B_prime' / 'C'
    triggered_by: str  # one of _VALID_TRIGGERS
    now: Optional[_dt.datetime] = None
    materiality_event_ref: Optional[UUID] = None
    prior_recommendation: Optional[str] = None  # BUY / HOLD / TRIM / SELL
    prior_recommendation_date: Optional[_dt.date] = None
    new_recommendation: Optional[str] = None  # for changed_from_prior calc

    def effective_now(self) -> _dt.datetime:
        return self.now or _dt.datetime.now(_dt.timezone.utc)


@dataclass
class TriggerMetadata:
    """JSONB envelope for execution_recommendations.trigger_metadata."""

    triggered_by: str
    cadence_floor_due_at: Optional[_dt.datetime]
    materiality_event_ref: Optional[UUID]
    prior_recommendation: Optional[str]
    prior_recommendation_date: Optional[_dt.date]
    changed_from_prior: bool

    def to_payload(self) -> dict:
        return {
            "triggered_by": self.triggered_by,
            "cadence_floor_due_at": (
                self.cadence_floor_due_at.isoformat()
                if self.cadence_floor_due_at
                else None
            ),
            "materiality_event_ref": (
                str(self.materiality_event_ref)
                if self.materiality_event_ref
                else None
            ),
            "prior_recommendation": self.prior_recommendation,
            "prior_recommendation_date": (
                self.prior_recommendation_date.isoformat()
                if self.prior_recommendation_date
                else None
            ),
            "changed_from_prior": self.changed_from_prior,
        }


# ---------------------------------------------------------------------------
# Cadence-floor helpers
# ---------------------------------------------------------------------------


def _next_monday_open(now: _dt.datetime) -> _dt.datetime:
    """Mode B: weekly Monday open (09:30 America/New_York → UTC).

    DST-correct: uses ``zoneinfo`` so the UTC value is 13:30 in EDT and
    14:30 in EST automatically. The "already past today's open" check
    uses the NY-local timestamp so the comparison stays in market-time.
    """
    now_ny = now.astimezone(_NY_TZ)
    days_ahead = (0 - now_ny.weekday()) % 7  # 0 = Monday
    if days_ahead == 0:
        today_open = _next_session_open_ny(now_ny.date())
        if now >= today_open:
            days_ahead = 7
    target_date = (now_ny + _dt.timedelta(days=days_ahead)).date()
    return _next_session_open_ny(target_date)


def _next_3day(now: _dt.datetime) -> _dt.datetime:
    """Mode B': every 3 days from now (calendar days), at 09:30 ET."""
    target_date = (now.astimezone(_NY_TZ) + _dt.timedelta(days=3)).date()
    return _next_session_open_ny(target_date)


def _next_daily(now: _dt.datetime) -> _dt.datetime:
    """Mode C: daily; next day at 09:30 ET (DST-correct via zoneinfo)."""
    next_day = (now.astimezone(_NY_TZ) + _dt.timedelta(days=1)).date()
    return _next_session_open_ny(next_day)


def cadence_floor_due_at(mode: str, now: _dt.datetime) -> _dt.datetime:
    """Compute next cadence-floor due time per Section 4.6 Q3 mode rules."""
    if mode == "B":
        return _next_monday_open(now)
    if mode == "B_prime":
        return _next_3day(now)
    if mode == "C":
        return _next_daily(now)
    raise ValueError(
        f"mode {mode!r} not in {{'B', 'B_prime', 'C'}} — see Section 2.2"
    )


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def compute_trigger_metadata(inp: TriggerInputs) -> TriggerMetadata:
    """Build TriggerMetadata for the current emission.

    Logic:
      * triggered_by='new_candidate' → no prior; cadence_floor still computed
        so the next cycle is scheduled.
      * triggered_by='m2_event' / 'm3_event' → materiality_event_ref must be
        present; cadence_floor computed; recommendation revised vs prior
        determines changed_from_prior.
      * triggered_by='mode_cadence_floor' → routine cycle; computes next
        cadence_floor relative to now.
    """
    if inp.triggered_by not in _VALID_TRIGGERS:
        raise ValueError(
            f"triggered_by {inp.triggered_by!r} not in {_VALID_TRIGGERS}"
        )
    if inp.triggered_by in (TRIGGER_M2, TRIGGER_M3) and not inp.materiality_event_ref:
        raise ValueError(
            f"triggered_by={inp.triggered_by} requires materiality_event_ref "
            "(M-2/M-3 events MUST link the source event per Section 5.3)"
        )

    now = inp.effective_now()
    next_floor = cadence_floor_due_at(inp.mode, now)

    changed = False
    if inp.prior_recommendation and inp.new_recommendation:
        changed = inp.prior_recommendation != inp.new_recommendation
    elif inp.triggered_by == TRIGGER_NEW_CANDIDATE:
        changed = False  # no prior to change from

    return TriggerMetadata(
        triggered_by=inp.triggered_by,
        cadence_floor_due_at=next_floor,
        materiality_event_ref=inp.materiality_event_ref,
        prior_recommendation=inp.prior_recommendation,
        prior_recommendation_date=inp.prior_recommendation_date,
        changed_from_prior=changed,
    )


__all__ = [
    "TRIGGER_M2",
    "TRIGGER_M3",
    "TRIGGER_MODE_CADENCE_FLOOR",
    "TRIGGER_NEW_CANDIDATE",
    "TriggerInputs",
    "TriggerMetadata",
    "cadence_floor_due_at",
    "compute_trigger_metadata",
]
