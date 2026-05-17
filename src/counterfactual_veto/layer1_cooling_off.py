"""Layer 1 — Cooling-off floor (v3 spec Section 4.5 Q6).

Universal cooling-off period that blocks any cut decision until the mode-
tuned floor has elapsed since the peak-pain trigger fired:

    Mode B   → 72h
    Mode B'  → 48h
    Mode C   → 24h

This layer's purpose is to suppress reflex-cut behavior on the day of a
drawdown spike. It fires regardless of any other signal (Layer 1 is the
universal floor; Layers 2 and 3 are gating logic on top).

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 4.5 Q6 Layer 1.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from . import MODE_COOLING_OFF_HOURS


@dataclass(frozen=True)
class CoolingOffStatus:
    """Outcome of the Layer 1 cooling-off check.

    Attributes:
        mode:        Mode label used to pick the floor ('B' / 'B_prime' / 'C').
        duration_h:  Configured floor in hours (24/48/72).
        started_at:  Timestamp of the peak-pain trigger event.
        expires_at:  ``started_at + duration_h``. Cooling-off ends here.
        evaluated_at: Timestamp at which we evaluated the status.
        blocking:    True iff ``evaluated_at < expires_at`` (cut blocked
                     until expiration).
    """

    mode: str
    duration_h: int
    started_at: _dt.datetime
    expires_at: _dt.datetime
    evaluated_at: _dt.datetime
    blocking: bool

    @property
    def remaining_seconds(self) -> int:
        """Seconds remaining until cooling-off ends (zero if expired)."""
        delta = (self.expires_at - self.evaluated_at).total_seconds()
        return max(0, int(delta))


def evaluate_cooling_off(
    *,
    mode: str,
    trigger_event_at: _dt.datetime,
    now: _dt.datetime | None = None,
) -> CoolingOffStatus:
    """Evaluate the Layer 1 cooling-off floor for a given trigger.

    Args:
        mode:               One of 'B' / 'B_prime' / 'C'.
        trigger_event_at:   When the peak-pain (2× cut threshold) trigger fired.
        now:                Evaluation timestamp (defaults to UTC now). Tests
                            pass a fixed clock for determinism.

    Returns:
        CoolingOffStatus dataclass; check ``.blocking`` for whether to halt.

    Raises:
        ValueError: If ``mode`` is not in {'B', 'B_prime', 'C'}.
    """
    if mode not in MODE_COOLING_OFF_HOURS:
        raise ValueError(
            f"unknown mode {mode!r}; expected one of {sorted(MODE_COOLING_OFF_HOURS)}"
        )
    duration_h = MODE_COOLING_OFF_HOURS[mode]
    expires_at = trigger_event_at + _dt.timedelta(hours=duration_h)
    evaluated_at = now or _dt.datetime.now(_dt.timezone.utc)
    blocking = evaluated_at < expires_at
    return CoolingOffStatus(
        mode=mode,
        duration_h=duration_h,
        started_at=trigger_event_at,
        expires_at=expires_at,
        evaluated_at=evaluated_at,
        blocking=blocking,
    )
