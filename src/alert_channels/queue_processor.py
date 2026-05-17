"""Daemon-style email queue processor for unread_alerts.

Per v3 spec Section 5.3 + Phase 4 Q9 retry policy:

  Polls ``unread_alerts`` for severity=3 rows where ``email_sent_at IS NULL``
  AND ``email_send_attempts < MAX_EMAIL_ATTEMPTS``. For each row whose backoff
  window has elapsed since ``created_at`` (or last attempt), invokes
  :func:`alert_channels.email_sender.send_email_for_alert`.

Backoff schedule (Phase 4 Q9 default; "1m / 5m / 15m"):
    attempt 1 sends immediately on poll (no wait beyond row visibility)
    attempt 2 waits  60s after attempt 1
    attempt 3 waits 300s after attempt 2
    attempt 4 waits 900s after attempt 3 (cap at MAX_EMAIL_ATTEMPTS=4)

NOTE on backoff timing source: ``unread_alerts`` does NOT carry a
``last_attempt_at`` column (migration 009's mutable set is just
``acknowledged_at, acknowledged_by, email_sent_at, email_send_attempts,
claude_session_pushed_at``). We approximate "time since last attempt" using
``created_at + sum(backoff_so_far)``: Attempt N becomes eligible at
``created_at + sum(RETRY_BACKOFFS_SECONDS[:N-1])``. This is conservative
(processor catches up after restart) and avoids a schema change.

Caller pattern (cron / systemd / k8s job):
    python -m src.alert_channels.cli process-email-queue

Each invocation is one PASS over the queue — drain-and-exit. Long-running
daemonization is the orchestration layer's job, not this module's.

Reference:
  Section 5.3 / Section 7 PB#4 / Phase 4 Q9.
  alert_channels.email_sender (delegates one-shot send + system_errors logging)
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from . import (
    MAX_EMAIL_ATTEMPTS,
    RETRY_BACKOFFS_SECONDS,
    SEVERITY_M3,
)
from .email_sender import (
    AlertRow,
    SendResult,
    SmtpConfig,
    send_email_for_alert,
)

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueueProcessResult:
    """Aggregate stats from a single drain pass."""

    rows_examined: int
    rows_sent: int
    rows_failed_transient: int  # attempt advanced; not yet final
    rows_queued_for_session_push: int  # final-failure path
    rows_skipped_backoff: int  # not yet eligible


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def process_email_queue(
    conn: Any,
    smtp_config: SmtpConfig,
    *,
    smtp_client_factory: Any = None,
    now: Optional[_dt.datetime] = None,
) -> QueueProcessResult:
    """Drain the M-3 email queue once.

    Selection predicate: ``severity = 3 AND email_sent_at IS NULL AND
    email_send_attempts < MAX_EMAIL_ATTEMPTS``. Backoff filtering happens
    in Python (the schema doesn't carry a last_attempt_at column).

    Args:
        conn: Postgres connection.
        smtp_config: Resolved SMTP credentials.
        smtp_client_factory: Test injection point.
        now: Clock override.

    Returns:
        :class:`QueueProcessResult` summary.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)

    pending = _select_pending_email_rows(conn)
    rows_examined = len(pending)
    sent = 0
    failed_transient = 0
    queued = 0
    skipped = 0

    for alert, created_at in pending:
        if not _is_eligible_now(
            attempts=alert.email_send_attempts,
            created_at=created_at,
            now=now,
        ):
            skipped += 1
            continue

        result: SendResult = send_email_for_alert(
            conn=conn,
            alert=alert,
            smtp_config=smtp_config,
            smtp_client_factory=smtp_client_factory,
            now=now,
        )
        if result.sent:
            sent += 1
        elif result.queued_for_session_push:
            queued += 1
        else:
            failed_transient += 1

    return QueueProcessResult(
        rows_examined=rows_examined,
        rows_sent=sent,
        rows_failed_transient=failed_transient,
        rows_queued_for_session_push=queued,
        rows_skipped_backoff=skipped,
    )


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _select_pending_email_rows(
    conn: Any,
) -> list[tuple[AlertRow, _dt.datetime]]:
    """SELECT rows that need an email attempt.

    Returns list of ``(AlertRow, created_at)``. Caller filters on backoff.
    """
    sql = (
        "SELECT alert_id, severity, alert_type, ticker, summary, payload, "
        "       drill_link_recommendation_id, email_send_attempts, created_at "
        "FROM unread_alerts "
        "WHERE severity = %s "
        "  AND email_sent_at IS NULL "
        "  AND email_send_attempts < %s "
        "ORDER BY created_at ASC"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (SEVERITY_M3, MAX_EMAIL_ATTEMPTS))
        rows = cur.fetchall()

    out: list[tuple[AlertRow, _dt.datetime]] = []

    for r in rows:
        payload = r[5]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, ValueError) as exc:
                # Corrupted payload — log + degrade to {} so the row still
                # gets a send attempt; the operator can drill via alert_id.
                _LOG.warning(
                    "alert_channels.queue_processor: failed to parse "
                    "payload for alert %s: %s",
                    r[0],
                    exc,
                )
                payload = {}
        elif payload is None:
            payload = {}
        alert = AlertRow(
            alert_id=UUID(str(r[0])),
            severity=int(r[1]),
            alert_type=r[2],
            ticker=r[3],
            summary=r[4],
            payload=payload,
            drill_link_recommendation_id=UUID(str(r[6])) if r[6] else None,
            email_send_attempts=int(r[7]),
        )
        created_at = r[8]
        if not isinstance(created_at, _dt.datetime):
            created_at = _dt.datetime.fromisoformat(str(created_at))
        # Defensive: if upstream produced a naive datetime (psycopg session
        # without tz, or fromisoformat over a tz-less string), coerce to
        # UTC. Without this, _is_eligible_now (which compares against an
        # aware UTC `now`) raises TypeError on mixed-aware/naive subtract.
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=_dt.timezone.utc)
        out.append((alert, created_at))
    return out


def _is_eligible_now(
    attempts: int,
    created_at: _dt.datetime,
    now: _dt.datetime,
) -> bool:
    """Return True if this row's next attempt is due.

    Eligibility window per Phase 4 Q9 (1m / 5m / 15m):
      - attempts == 0: immediately on visibility
      - attempts == 1: created_at +   60s          (after 1m wait)
      - attempts == 2: created_at +  360s          (after 1m+5m  cumulative)
      - attempts == 3: created_at + 1260s          (after 1m+5m+15m cumulative)
      - attempts >= MAX_EMAIL_ATTEMPTS: ineligible (caller filters on
        attempts < MAX)

    Using a creation-time-anchored schedule avoids a last_attempt_at
    column. The tradeoff: if attempt 1 fires late (queue lag), the
    inter-attempt waits can shrink. Acceptable for v0.1; revisit in
    v0.5 if a tighter SLA is required.
    """
    if attempts >= MAX_EMAIL_ATTEMPTS:
        return False
    cumulative = sum(RETRY_BACKOFFS_SECONDS[:attempts])
    eligible_at = created_at + _dt.timedelta(seconds=cumulative)
    return now >= eligible_at
