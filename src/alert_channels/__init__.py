"""alert_channels — multi-channel push-alert delivery for equity-research v3.

Per v3 spec Section 5.3 (Push alerts) + Section 7 PB#4 (multi-channel
architecture) + Phase 4 Q9 (failure-mode defaults), this package owns three
delivery paths layered over the ``unread_alerts`` table (migration 009 +
017):

  - ``email_sender``    — SMTP delivery for severity=3 (M-3) only
  - ``session_push``    — Claude Code session-start markdown summary
                          (all unacknowledged M-2 + M-3)
  - ``queue_processor`` — daemon-style retry loop; up to 4 attempts using
                          the 1m / 5m / 15m exponential schedule
  - ``system_health``   — ``/system-health`` slash-command body

Channel matrix (Section 5.3 Table):

| Channel             | Triggers                            |
|---------------------|-------------------------------------|
| Email               | M-3 events only                     |
| Claude session push | Unread M-3 / M-2 since last session |
| /alerts             | All current alerts (on-demand)      |

Phase 4 Q9 retry policy:
    Attempt 1 fails -> wait 1 minute   -> Attempt 2
    Attempt 2 fails -> wait 5 minutes  -> Attempt 3
    Attempt 3 fails -> wait 15 minutes -> Attempt 4
    Attempt 4 fails -> queue for next session-push as M-3 unread; log to
                       system_errors with source='alert_channels.email_sender'.

Idempotency: every email-send path checks ``email_sent_at IS NULL`` before
emitting; re-running the queue processor on a fully-drained queue is a no-op.

Reference:
  docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 5.3 (Push alerts — multi-channel)
    Section 5.4 (Slash commands — /alerts, /ack, /system-health)
    Section 7 PB#4 (multi-channel architecture)
    Section 7.1 (launch gate: email channel sends test successfully)
    Phase 4 Q9 (failure-mode defaults — exponential retry + system_errors logging)
  db/migrations/009_v3_daily_monitor.sql (unread_alerts state table)
  db/migrations/014_v3_system_health.sql (system_errors append-mostly table)
  db/migrations/017_v3_alert_type_extension.sql (materiality_m2 + calibration_drift)
"""

from __future__ import annotations

# Severity enum constants — match unread_alerts.severity domain (2 or 3).
SEVERITY_M2: int = 2
SEVERITY_M3: int = 3

# Phase 4 Q9 retry schedule (seconds) — "1m / 5m / 15m" per spec.
# Indexed by attempts-already-completed (0-based):
#   attempts == 0 → send attempt 1 immediately (no wait)
#   attempts == 1 → wait 60s   (1m) before attempt 2
#   attempts == 2 → wait 300s  (5m) before attempt 3
#   attempts == 3 → wait 900s  (15m) before attempt 4
#
# DECISION LOCK (Phase 4 Q9, Section 5.3): MAX_EMAIL_ATTEMPTS = 4 so all
# three backoff slots in RETRY_BACKOFFS_SECONDS are exercised. Attempt 4
# fires at +21min after creation in the worst case — still well under
# typical operator-response window. The previous value (3) left the 15m
# slot dead. Alternative considered + rejected: drop the 15m slot and
# keep MAX=3 — rejected because the spec explicitly mandates the
# "1m / 5m / 15m" schedule.
RETRY_BACKOFFS_SECONDS: tuple[int, int, int] = (60, 300, 900)
MAX_EMAIL_ATTEMPTS: int = 4

# Source string used when logging email failures to system_errors.
EMAIL_ERROR_SOURCE: str = "alert_channels.email_sender"

__all__ = [
    "SEVERITY_M2",
    "SEVERITY_M3",
    "RETRY_BACKOFFS_SECONDS",
    "MAX_EMAIL_ATTEMPTS",
    "EMAIL_ERROR_SOURCE",
]
