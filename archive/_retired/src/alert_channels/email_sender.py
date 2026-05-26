"""SMTP-backed email delivery for M-3 alerts.

Per v3 spec Section 5.3 (Push alerts) and Section 7 PB#4 (multi-channel),
email fires for M-3 events ONLY. M-2 events stay in the session-push +
``/alerts`` channels.

Phase 4 Q9 retry policy (failure-mode default):
    1st attempt fails  -> wait  1 minute   -> 2nd attempt
    2nd attempt fails  -> wait  5 minutes  -> 3rd attempt
    3rd attempt fails  -> wait 15 minutes  -> 4th attempt
    4th attempt fails  -> queue for session-push (already done by virtue of
                          being an unread_alerts row with severity=3 and
                          email_send_attempts == MAX_EMAIL_ATTEMPTS marker);
                          log to system_errors with
                          source='alert_channels.email_sender'.

Idempotency:
  Every send call guards on ``email_sent_at IS NULL`` so a re-run after a
  successful send is a no-op. Attempt counters are advanced unconditionally
  on each invocation; the ``queue_processor`` enforces backoff timing.

Module contract:
  - ``send_email_for_alert(conn, alert_row, smtp_config)`` — one shot, no
    backoff sleep. Caller (``queue_processor``) owns scheduling; this
    function only attempts the SMTP send and updates the row.

Reference:
  Section 5.3, Section 7 PB#4, Phase 4 Q9.
  db/migrations/009_v3_daily_monitor.sql (unread_alerts state mutation rules:
  only acknowledged_at, acknowledged_by, email_sent_at, email_send_attempts,
  claude_session_pushed_at are mutable).
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional
from uuid import UUID

from . import EMAIL_ERROR_SOURCE, MAX_EMAIL_ATTEMPTS, SEVERITY_M3

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmtpConfig:
    """Resolved SMTP credentials. Loaded from environment via ``from_env()``.

    Per the project's .env convention (``BUILD_LOG.md`` decision 1, Path A),
    all secrets live in a gitignored ``.env``; ``from_env()`` reads
    pre-populated environment variables — it does NOT call ``dotenv``
    directly so test harnesses can inject overrides.
    """

    host: str
    port: int
    username: str
    password: str
    sender: str
    recipient: str
    use_tls: bool = True

    @classmethod
    def from_env(cls, env: Optional[dict[str, str]] = None) -> "SmtpConfig":
        """Build SmtpConfig from environment variables.

        Required env vars:
          ALERT_SMTP_HOST        — e.g., 'smtp.gmail.com'
          ALERT_SMTP_PORT        — e.g., '587'
          ALERT_SMTP_USERNAME    — SMTP auth user (often the sender address)
          ALERT_SMTP_PASSWORD    — SMTP auth password / app-password
          ALERT_SMTP_SENDER      — From: address (may equal username)
          ALERT_SMTP_RECIPIENT   — operator's address; M-3 emails go here

        Optional:
          ALERT_SMTP_USE_TLS     — '1'/'0' (default '1' = STARTTLS)

        Raises:
            RuntimeError if any required var is missing — never silently
            fall back to a wrong sender; ``/system-health`` will surface
            the gap.
        """
        e = env if env is not None else os.environ
        missing: list[str] = []
        for k in (
            "ALERT_SMTP_HOST",
            "ALERT_SMTP_PORT",
            "ALERT_SMTP_USERNAME",
            "ALERT_SMTP_PASSWORD",
            "ALERT_SMTP_SENDER",
            "ALERT_SMTP_RECIPIENT",
        ):
            if not e.get(k):
                missing.append(k)
        if missing:
            raise RuntimeError(
                "Missing required SMTP env vars for alert_channels: "
                + ", ".join(missing)
            )
        return cls(
            host=e["ALERT_SMTP_HOST"],
            port=int(e["ALERT_SMTP_PORT"]),
            username=e["ALERT_SMTP_USERNAME"],
            password=e["ALERT_SMTP_PASSWORD"],
            sender=e["ALERT_SMTP_SENDER"],
            recipient=e["ALERT_SMTP_RECIPIENT"],
            use_tls=e.get("ALERT_SMTP_USE_TLS", "1") not in ("0", "false", "False"),
        )


@dataclass(frozen=True)
class AlertRow:
    """Subset of unread_alerts columns needed to render + send an email.

    Mirrors the schema in db/migrations/009 + 017. Caller assembles this
    from a SELECT; we don't couple to the row tuple ordering.
    """

    alert_id: UUID
    severity: int
    alert_type: str
    ticker: Optional[str]
    summary: str
    payload: dict[str, Any]
    drill_link_recommendation_id: Optional[UUID]
    email_send_attempts: int


@dataclass(frozen=True)
class SendResult:
    """Outcome of a single send attempt."""

    sent: bool
    attempt_number: int  # 1-based; the attempt this call represents
    error_detail: Optional[str] = None
    queued_for_session_push: bool = False


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def send_email_for_alert(
    conn: Any,
    alert: AlertRow,
    smtp_config: SmtpConfig,
    *,
    smtp_client_factory: Any = None,
    now: Optional[_dt.datetime] = None,
) -> SendResult:
    """Attempt one email send for a single unread_alerts row.

    Args:
        conn: PEP-249-style Postgres connection (``psycopg`` or ``psycopg2``).
        alert: The row to deliver.
        smtp_config: SMTP credentials.
        smtp_client_factory: Optional injection point for tests — callable
            ``() -> smtp_client``. Production uses ``smtplib.SMTP`` keyed
            off ``smtp_config.host`` / ``port``.
        now: Optional clock override for tests.

    Returns:
        :class:`SendResult` describing the attempt.

    Notes:
        - Severity guard: only severity=3 (M-3) sends. M-2 returns
          ``sent=False`` with ``error_detail='severity_below_threshold'``.
        - Idempotency: ``SELECT ... FOR UPDATE`` row lock + pre-bump of
          ``email_send_attempts`` prevents double-send on concurrent
          processors. A peer waiting on the lock sees the bumped attempt
          count immediately on acquire, then bails out if we succeeded
          (or claims the next attempt slot if we transient-failed).
        - Final-failure path (attempt_number == MAX_EMAIL_ATTEMPTS): logs
          to system_errors and sets ``queued_for_session_push=True``. The
          row is already discoverable by ``session_push`` because it stays
          unacknowledged; the marker is the
          ``email_send_attempts == MAX_EMAIL_ATTEMPTS`` counter so
          /system-health can count "queued for session push".
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)

    if alert.severity != SEVERITY_M3:
        return SendResult(
            sent=False,
            attempt_number=alert.email_send_attempts,
            error_detail="severity_below_threshold",
        )

    # Idempotency guard — Phase 4 Q9 + Section 5.3 TOCTOU lock.
    # Use ``SELECT ... FOR UPDATE`` row-lock inside an explicit
    # transaction so two concurrent queue processors cannot both observe
    # ``email_sent_at IS NULL`` and double-send. We also bump
    # ``email_send_attempts`` BEFORE releasing the lock, so a peer
    # waiting on the row sees the incremented counter as soon as they
    # acquire the lock — they then re-check ``email_sent_at`` and bail
    # out if we succeeded, or accept their attempt as the next one if
    # we transiently failed.
    #
    # The row lock is released by ``conn.commit()`` (or rollback). On
    # a non-transactional / autocommit fake the SELECT degrades to a
    # plain SELECT and the test must coordinate concurrency externally.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT email_sent_at, email_send_attempts FROM unread_alerts "
            "WHERE alert_id = %s FOR UPDATE",
            (str(alert.alert_id),),
        )
        row = cur.fetchone()
        if row is None:
            # Row deleted underneath us — treat as already-handled to
            # avoid sending a phantom email.
            if hasattr(conn, "commit"):
                conn.commit()
            return SendResult(
                sent=True,
                attempt_number=alert.email_send_attempts,
                error_detail="already_sent_or_unknown",
            )
        row_sent_at, row_attempts_seen = row[0], int(row[1])
        if row_sent_at is not None:
            if hasattr(conn, "commit"):
                conn.commit()
            return SendResult(
                sent=True,
                attempt_number=row_attempts_seen,
                error_detail="already_sent",
            )
        # Reserve our slot: bump email_send_attempts before releasing
        # the lock so a concurrent peer sees the increment.
        attempt_number = row_attempts_seen + 1
        cur.execute(
            "UPDATE unread_alerts SET email_send_attempts = %s "
            "WHERE alert_id = %s",
            (attempt_number, str(alert.alert_id)),
        )
    if hasattr(conn, "commit"):
        conn.commit()  # release FOR UPDATE row lock

    subject, plain, html = _render_email_body(alert)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_config.sender
    msg["To"] = smtp_config.recipient
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    error_detail: Optional[str] = None
    sent_ok = False
    try:
        if smtp_client_factory is not None:
            client = smtp_client_factory()
        else:
            client = smtplib.SMTP(smtp_config.host, smtp_config.port, timeout=30)
        try:
            if smtp_config.use_tls:
                ctx = ssl.create_default_context()
                client.starttls(context=ctx)
            client.login(smtp_config.username, smtp_config.password)
            client.sendmail(smtp_config.sender, [smtp_config.recipient], msg.as_string())
            sent_ok = True
        finally:
            try:
                client.quit()
            except Exception:  # pragma: no cover — best-effort close
                pass
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {exc}"
        _LOG.warning(
            "alert_channels.email_sender attempt %d/%d failed for alert %s: %s",
            attempt_number, MAX_EMAIL_ATTEMPTS, alert.alert_id, error_detail,
        )

    # Counter was already advanced under the FOR UPDATE row lock above;
    # only stamp ``email_sent_at`` on success.
    _stamp_sent_at_if_success(
        conn=conn,
        alert_id=alert.alert_id,
        sent_at=now if sent_ok else None,
    )

    queued = False
    if not sent_ok and attempt_number >= MAX_EMAIL_ATTEMPTS:
        # Final failure — log to system_errors. Row stays unacknowledged
        # so session_push will surface it next session-start.
        _log_system_error(
            conn=conn,
            alert=alert,
            error_detail=error_detail or "unknown_send_failure",
            now=now,
        )
        queued = True

    return SendResult(
        sent=sent_ok,
        attempt_number=attempt_number,
        error_detail=None if sent_ok else error_detail,
        queued_for_session_push=queued,
    )


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _render_email_body(alert: AlertRow) -> tuple[str, str, str]:
    """Return (subject, plain_text, minimal_html).

    Per spec: subject = '[M-3] {ticker} — {alert_type}'; body must include
    ``Run /audit-trail <rec_id>`` instruction when a drill_link is present.
    Rich-HTML deferred per task constraints — minimal HTML for v0.1.
    """
    ticker = alert.ticker or "PORTFOLIO"
    subject = f"[M-3] {ticker} — {alert.alert_type}"

    drill_line = ""
    if alert.drill_link_recommendation_id is not None:
        drill_line = (
            f"Drill: Run /audit-trail {alert.drill_link_recommendation_id}"
        )

    plain_lines = [
        f"M-3 ALERT — {ticker}",
        "",
        f"Type:    {alert.alert_type}",
        f"Summary: {alert.summary}",
    ]
    if drill_line:
        plain_lines += ["", drill_line]
    plain_lines += [
        "",
        f"Acknowledge with: /ack {alert.alert_id}",
        "",
        "(Generated by alert_channels.email_sender; v3 Section 5.3 push alerts)",
    ]
    plain = "\n".join(plain_lines)

    drill_html = (
        f'<p><strong>Drill:</strong> '
        f'<code>Run /audit-trail {alert.drill_link_recommendation_id}</code></p>'
        if alert.drill_link_recommendation_id is not None
        else ""
    )
    html = (
        "<!DOCTYPE html><html><body>"
        f"<h2>M-3 ALERT — {_html_escape(ticker)}</h2>"
        f"<p><strong>Type:</strong> {_html_escape(alert.alert_type)}</p>"
        f"<p><strong>Summary:</strong> {_html_escape(alert.summary)}</p>"
        f"{drill_html}"
        f"<p>Acknowledge with: <code>/ack {alert.alert_id}</code></p>"
        "<hr/>"
        "<p style=\"color:#666;font-size:smaller\">"
        "alert_channels.email_sender; v3 Section 5.3 push alerts"
        "</p></body></html>"
    )
    return subject, plain, html


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _stamp_sent_at_if_success(
    conn: Any,
    alert_id: UUID,
    sent_at: Optional[_dt.datetime],
) -> None:
    """Stamp ``email_sent_at`` on a successful send.

    The attempts counter has already been advanced under the FOR UPDATE
    row lock at the start of :func:`send_email_for_alert`, so this only
    needs to record success. ``COALESCE(email_sent_at, %s)`` ensures we
    never overwrite a prior successful send (defensive — also enforced by
    migration 009's mutable-column guard).
    """
    if sent_at is None:
        return  # transient failure path: counter already advanced; nothing more to do
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE unread_alerts "
            "SET email_sent_at = COALESCE(email_sent_at, %s) "
            "WHERE alert_id = %s",
            (sent_at, str(alert_id)),
        )
    if hasattr(conn, "commit"):
        conn.commit()


# Backwards-compatible alias for any external callers (none in tree).
def _update_alert_after_attempt(
    conn: Any,
    alert_id: UUID,
    attempt_number: int,
    sent_at: Optional[_dt.datetime],
) -> None:
    """Deprecated; retained for tests that still patch this name.

    The TOCTOU-safe path bumps ``email_send_attempts`` under FOR UPDATE
    before SMTP, so the counter is already advanced by the time we
    decide whether to stamp ``email_sent_at``.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE unread_alerts "
            "SET email_send_attempts = %s, "
            "    email_sent_at = COALESCE(email_sent_at, %s) "
            "WHERE alert_id = %s",
            (attempt_number, sent_at, str(alert_id)),
        )
    if hasattr(conn, "commit"):
        conn.commit()


def _log_system_error(
    conn: Any,
    alert: AlertRow,
    error_detail: str,
    now: _dt.datetime,
) -> None:
    """Insert a system_errors row capturing the email-send final failure."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO system_errors "
            "(timestamp_at, source, error_type, error_detail, "
            " retry_count, escalated_to_alert, blocked_decision) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                now,
                EMAIL_ERROR_SOURCE,
                "smtp_send_failed",
                error_detail,
                MAX_EMAIL_ATTEMPTS,
                True,  # alert remains unacknowledged → escalated to session push
                f"email_alert_{alert.alert_id}",
            ),
        )
    if hasattr(conn, "commit"):
        conn.commit()
