"""Pre-mortem scheduler package (v3 Section 4.5 Q4).

Implements the **mode-tuned cadence + 4 event triggers** for the
operator's structured pre-mortem ("imagine this position fails: why?")
exercise.

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.5 Q4 (lines 514-528):

  Mode B   180-day calendar floor
  Mode B'  120-day calendar floor
  Mode C    60-day calendar floor

  Event triggers (force pre-mortem regardless of calendar):
    1. Thesis-confirmation event (paradoxically dangerous moment)
    2. Consecutive M-2 events on same name within 30 days
    3. First auto-tighten threshold crossed (B/S&P 5pp, B'/QQQ 7pp,
       C/IWO 10pp)
    4. Mode reclassification proposed -> mandatory before commit

  LLM role: devil's-advocate assistant (Opus for high-stakes
  contestable judgment); generates 3 plausible failure modes;
  operator accepts/rejects each with rationale logged.

The scheduler runs daily, checks all watchlist names, and surfaces
``pre-mortem due`` to the alerts queue. The recorder writes one
``premortem`` row (012_v3_premortem.sql) per completed session.

Trigger taxonomy (mirrors DB CHECK constraint):
"""

from __future__ import annotations

# Calendar floor (days) per mode — Section 4.5 Q4.
CADENCE_DAYS_BY_MODE: dict[str, int] = {
    "B": 180,
    "B_prime": 120,
    "C": 60,
}

# Mode-paired auto-tighten thresholds (drawdown vs benchmark, in pp).
AUTO_TIGHTEN_THRESHOLDS_PP: dict[str, tuple[str, float]] = {
    "B": ("SPY", 5.0),
    "B_prime": ("QQQ", 7.0),
    "C": ("IWO", 10.0),
}

# Trigger codes — mirror DB CHECK constraint in 012_v3_premortem.sql.
TRIGGER_CALENDAR_FLOOR: str = "calendar_floor"
TRIGGER_THESIS_CONFIRMATION: str = "thesis_confirmation"
TRIGGER_CONSECUTIVE_M2: str = "consecutive_m2"
TRIGGER_AUTO_TIGHTEN: str = "auto_tighten"
TRIGGER_MODE_RECLASS: str = "mode_reclass"

VALID_TRIGGERS: set[str] = {
    TRIGGER_CALENDAR_FLOOR,
    TRIGGER_THESIS_CONFIRMATION,
    TRIGGER_CONSECUTIVE_M2,
    TRIGGER_AUTO_TIGHTEN,
    TRIGGER_MODE_RECLASS,
}

# LLM model for the devil's-advocate — Opus per Phase 4 (high-stakes
# contestable judgment).
DEVILS_ADVOCATE_LLM_MODEL: str = "claude-opus-4-7"

# Devil's-advocate must produce N candidate failure modes.
DEVILS_ADVOCATE_FAILURE_MODE_COUNT: int = 3

# Thesis-confirmation event must be answered with a fresh pre-mortem
# scheduled within this many days.
THESIS_CONFIRMATION_DEADLINE_DAYS: int = 7

# Consecutive M-2 events within this window count for trigger 2.
CONSECUTIVE_M2_WINDOW_DAYS: int = 30

__all__ = [
    "CADENCE_DAYS_BY_MODE",
    "AUTO_TIGHTEN_THRESHOLDS_PP",
    "TRIGGER_CALENDAR_FLOOR",
    "TRIGGER_THESIS_CONFIRMATION",
    "TRIGGER_CONSECUTIVE_M2",
    "TRIGGER_AUTO_TIGHTEN",
    "TRIGGER_MODE_RECLASS",
    "VALID_TRIGGERS",
    "DEVILS_ADVOCATE_LLM_MODEL",
    "DEVILS_ADVOCATE_FAILURE_MODE_COUNT",
    "THESIS_CONFIRMATION_DEADLINE_DAYS",
    "CONSECUTIVE_M2_WINDOW_DAYS",
]
