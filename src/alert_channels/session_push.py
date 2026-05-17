"""Claude Code session-start push: surface unacknowledged alerts at session boot.

Per v3 spec Section 5.3 (Push alerts table — "Claude Code session push:
catch-up at session start; Unread M-3/M-2 since last session") and Section
5.4 (slash commands — ``/alerts`` and ``/ack``).

Public API:
    surface_unread_at_session_start(conn, operator_id) -> str

The returned markdown is what the harness pastes into the operator's
session at boot. We DO NOT auto-acknowledge — the operator must invoke
``/ack <alert_id>`` or ``/ack all`` explicitly so acknowledgement is a
deliberate act.

Side effect: every row returned is stamped with
``claude_session_pushed_at = NOW()`` so we can later observe
``email_sent_at IS NULL AND claude_session_pushed_at IS NOT NULL`` (i.e.,
"queued for session push" — Phase 4 Q9 final-failure path) without losing
that signal at first surfacing.

Reference:
  Section 5.3 (Push alerts table — Claude Code session push channel)
  Section 5.4 (/alerts, /ack <alert_id>, /ack all)
  Section 7 PB#4 (multi-channel architecture)
  db/migrations/009_v3_daily_monitor.sql (unread_alerts state columns:
    acknowledged_at, claude_session_pushed_at — only these mutate)
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from . import SEVERITY_M2, SEVERITY_M3

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class UnreadAlertSummary:
    """One row's surface form for session push + /alerts rendering."""

    alert_id: UUID
    severity: int
    alert_type: str
    ticker: Optional[str]
    summary: str
    drill_link_recommendation_id: Optional[UUID]
    created_at: _dt.datetime


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def surface_unread_at_session_start(
    conn: Any,
    operator_id: str = "operator",
    *,
    now: Optional[_dt.datetime] = None,
    mark_pushed: bool = True,
) -> str:
    """Render unacknowledged alerts as markdown for Claude Code to display.

    Args:
        conn: PEP-249 Postgres connection.
        operator_id: Audit-trail label; not used for filtering at v0.1
            (single-operator system per Section 5.5).
        now: Clock override for tests.
        mark_pushed: Set ``claude_session_pushed_at = NOW()`` on each row
            in this batch. Disable for dry-run / preview from /alerts.

    Returns:
        Markdown string. Empty (returns banner "No unread alerts") when
        nothing is unacknowledged.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    rows = list_unread_alerts(conn)

    if not rows:
        return "_No unread alerts._"

    if mark_pushed:
        _stamp_session_pushed(conn, [r.alert_id for r in rows], now=now)

    return _render_session_push_markdown(rows, now=now)


def list_unread_alerts(
    conn: Any,
    *,
    severity: Optional[int] = None,
    ticker: Optional[str] = None,
    alert_type: Optional[str] = None,
    since: Optional[_dt.datetime] = None,
) -> list[UnreadAlertSummary]:
    """Read unacknowledged alerts with optional filters.

    Default ordering: severity DESC, created_at DESC (newest M-3 first).
    Backs both the session-push surface and the ``/alerts`` slash command.
    """
    sql = (
        "SELECT alert_id, severity, alert_type, ticker, summary, "
        "       drill_link_recommendation_id, created_at "
        "FROM unread_alerts "
        "WHERE acknowledged_at IS NULL "
    )
    params: list[Any] = []
    if severity is not None:
        sql += "AND severity = %s "
        params.append(severity)
    if ticker is not None:
        sql += "AND ticker = %s "
        params.append(ticker)
    if alert_type is not None:
        sql += "AND alert_type = %s "
        params.append(alert_type)
    if since is not None:
        sql += "AND created_at >= %s "
        params.append(since)
    sql += "ORDER BY severity DESC, created_at DESC"

    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

    out: list[UnreadAlertSummary] = []
    for r in rows:
        created_at_raw = r[6]
        if isinstance(created_at_raw, _dt.datetime):
            created_at = created_at_raw
        else:
            created_at = _dt.datetime.fromisoformat(str(created_at_raw))
        # Defensive: coerce naive datetimes to aware UTC so any downstream
        # comparison against an aware `now` does not raise TypeError.
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=_dt.timezone.utc)
        out.append(
            UnreadAlertSummary(
                alert_id=_to_uuid(r[0]),
                severity=int(r[1]),
                alert_type=r[2],
                ticker=r[3],
                summary=r[4],
                drill_link_recommendation_id=_to_uuid(r[5]) if r[5] else None,
                created_at=created_at,
            )
        )
    return out


def acknowledge(
    conn: Any,
    alert_id: UUID,
    *,
    operator_id: str = "operator",
    now: Optional[_dt.datetime] = None,
) -> bool:
    """Mark a single alert acknowledged.

    Returns True when a row was updated; False when alert_id is unknown OR
    already acknowledged (idempotent — double-ack is a no-op).
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE unread_alerts "
            "SET acknowledged_at = %s, acknowledged_by = %s "
            "WHERE alert_id = %s AND acknowledged_at IS NULL",
            (now, operator_id, str(alert_id)),
        )
        rowcount = cur.rowcount
    if hasattr(conn, "commit"):
        conn.commit()
    return rowcount > 0


def acknowledge_all(
    conn: Any,
    *,
    operator_id: str = "operator",
    now: Optional[_dt.datetime] = None,
) -> int:
    """Mark all unacknowledged alerts acknowledged. Returns count updated."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE unread_alerts "
            "SET acknowledged_at = %s, acknowledged_by = %s "
            "WHERE acknowledged_at IS NULL",
            (now, operator_id),
        )
        rowcount = cur.rowcount
    if hasattr(conn, "commit"):
        conn.commit()
    return rowcount


def render_alerts_list(rows: list[UnreadAlertSummary]) -> str:
    """Render the ``/alerts`` slash-command output.

    Same look-and-feel as the session-push markdown but framed as a
    request-response (no "since last session" header).
    """
    if not rows:
        return "_No unacknowledged alerts._"
    n_m3 = sum(1 for r in rows if r.severity == SEVERITY_M3)
    n_m2 = sum(1 for r in rows if r.severity == SEVERITY_M2)
    lines = [
        f"# /alerts — {len(rows)} unacknowledged ({n_m3} M-3, {n_m2} M-2)",
        "",
    ]
    lines.extend(_render_alert_one_liners(rows))
    lines.append("")
    lines.append("_Acknowledge: `/ack <alert_id>` or `/ack all`._")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _render_session_push_markdown(
    rows: list[UnreadAlertSummary],
    *,
    now: _dt.datetime,
) -> str:
    """Markdown surfaced at Claude Code session start."""
    n_m3 = sum(1 for r in rows if r.severity == SEVERITY_M3)
    n_m2 = sum(1 for r in rows if r.severity == SEVERITY_M2)
    oldest = min(r.created_at for r in rows)
    # "since HH:MM" — local time renders in the harness; we surface UTC.
    since_str = oldest.strftime("%Y-%m-%d %H:%M")

    header = (
        f"# Unread alerts — {len(rows)} since {since_str} UTC "
        f"({n_m3} M-3 / {n_m2} M-2)"
    )
    lines = [header, ""]
    lines.extend(_render_alert_one_liners(rows))
    lines.append("")
    lines.append("_Acknowledge: `/ack <alert_id>` or `/ack all`._")
    return "\n".join(lines)


def _render_alert_one_liners(rows: list[UnreadAlertSummary]) -> list[str]:
    out: list[str] = []
    for r in rows:
        sev_tag = "M-3" if r.severity == SEVERITY_M3 else "M-2"
        ticker = r.ticker or "PORTFOLIO"
        drill = ""
        if r.drill_link_recommendation_id is not None:
            drill = f" — drill: `/audit-trail {r.drill_link_recommendation_id}`"
        out.append(
            f"- **[{sev_tag}]** `{r.alert_id}` {ticker} "
            f"({r.alert_type}): {r.summary}{drill}"
        )
    return out


def _stamp_session_pushed(
    conn: Any,
    alert_ids: list[UUID],
    *,
    now: _dt.datetime,
) -> None:
    """Set claude_session_pushed_at on a batch — preserves first-stamp.

    Use COALESCE to keep the original push timestamp on subsequent
    reopens; only the FIRST surface time is recorded so analytics on
    "time-to-acknowledge" stay accurate.
    """
    if not alert_ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE unread_alerts "
            "SET claude_session_pushed_at = COALESCE(claude_session_pushed_at, %s) "
            "WHERE alert_id = ANY(%s::uuid[])",
            (now, [str(a) for a in alert_ids]),
        )
    if hasattr(conn, "commit"):
        conn.commit()


def _to_uuid(v: Any) -> UUID:
    if isinstance(v, UUID):
        return v
    return UUID(str(v))
