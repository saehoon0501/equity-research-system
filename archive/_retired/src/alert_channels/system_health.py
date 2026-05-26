"""/system-health slash-command body.

Per v3 spec Section 5.4 (Slash commands) + Phase 4 Q9 (failure-mode
defaults), ``/system-health`` is the unified observability surface for:

  - Currently-degraded MCPs (system_errors WHERE resolved_at IS NULL)
  - Queued recoveries (Postgres fallback queue, broker MCP retry, email
    queue depth)
  - Disputed catalog entries excluded from retrieval (Section 6.2 hygiene)
  - System errors in last 7 days (count by source)
  - Active push-alert backlog (severity histogram + queued-for-session-push)

The implementation is read-only: every value is queried from Postgres, no
side effects. Output is markdown ready for Claude Code to render.

Reference:
  Section 5.4 (slash command catalog)
  Section 7.5 (cold-start + error handling — never silent fail)
  Phase 4 Q9 (failure-mode defaults — system_errors logging policy)
  db/migrations/014_v3_system_health.sql (system_errors table)
  db/migrations/009_v3_daily_monitor.sql (unread_alerts table)
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass
from typing import Any, Optional

from . import MAX_EMAIL_ATTEMPTS, SEVERITY_M2, SEVERITY_M3

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SystemHealthSnapshot:
    """Structured /system-health view (rendered into markdown)."""

    generated_at: _dt.datetime
    degraded_mcps: list[tuple[str, _dt.datetime]]  # (source, last_success_at)
    email_queue_depth: int
    email_queued_for_session_push: int
    unread_m3: int
    unread_m2: int
    disputed_catalog_count: int
    disputed_catalog_tickers: list[str]
    system_errors_last_7d_by_source: list[tuple[str, int]]


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def render_system_health(
    conn: Any,
    *,
    now: Optional[_dt.datetime] = None,
) -> str:
    """Build + render the /system-health markdown block.

    Args:
        conn: PEP-249 Postgres connection.
        now: Clock override for tests.

    Returns:
        Markdown string suitable for direct display.
    """
    snapshot = collect_system_health(conn, now=now)
    return _render_markdown(snapshot)


def collect_system_health(
    conn: Any,
    *,
    now: Optional[_dt.datetime] = None,
) -> SystemHealthSnapshot:
    """Gather all components of the /system-health view in one pass."""
    now = now or _dt.datetime.now(_dt.timezone.utc)

    return SystemHealthSnapshot(
        generated_at=now,
        degraded_mcps=_query_degraded_mcps(conn),
        email_queue_depth=_query_email_queue_depth(conn),
        email_queued_for_session_push=_query_email_queued_for_session_push(conn),
        unread_m3=_query_unread_count(conn, severity=SEVERITY_M3),
        unread_m2=_query_unread_count(conn, severity=SEVERITY_M2),
        disputed_catalog_count=_query_disputed_catalog_count(conn),
        disputed_catalog_tickers=_query_disputed_catalog_tickers(conn),
        system_errors_last_7d_by_source=_query_system_errors_last_7d(conn, now=now),
    )


# --------------------------------------------------------------------------- #
# Queries                                                                     #
# --------------------------------------------------------------------------- #


def _query_degraded_mcps(conn: Any) -> list[tuple[str, _dt.datetime]]:
    """Return (source, last_success_at) for sources with unresolved errors.

    "last_success_at" is approximated as "most-recent timestamp_at where
    resolved_at IS NOT NULL"; a source with NO resolved row returns the
    epoch sentinel (rendered as 'never'). Sources with NO unresolved row
    are healthy and omitted.
    """
    sql = (
        "SELECT e.source, "
        "       MAX(CASE WHEN e.resolved_at IS NOT NULL "
        "                THEN e.timestamp_at END) AS last_success_at "
        "FROM system_errors e "
        "WHERE EXISTS ("
        "    SELECT 1 FROM system_errors e2 "
        "    WHERE e2.source = e.source AND e2.resolved_at IS NULL"
        ") "
        "GROUP BY e.source "
        "ORDER BY e.source"
    )
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    out: list[tuple[str, _dt.datetime]] = []
    for r in rows:
        ts = r[1] if r[1] is not None else _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)
        if not isinstance(ts, _dt.datetime):
            ts = _dt.datetime.fromisoformat(str(ts))
        # Defensive: ensure aware UTC for the cutoff window comparison
        # (`now - timedelta(days=7)` math must not mix aware vs naive).
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_dt.timezone.utc)
        out.append((r[0], ts))
    return out


def _query_email_queue_depth(conn: Any) -> int:
    """Count of M-3 alerts pending email send (haven't hit MAX attempts)."""
    sql = (
        "SELECT COUNT(*) FROM unread_alerts "
        "WHERE severity = %s "
        "  AND email_sent_at IS NULL "
        "  AND email_send_attempts < %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (SEVERITY_M3, MAX_EMAIL_ATTEMPTS))
        return int(cur.fetchone()[0])


def _query_email_queued_for_session_push(conn: Any) -> int:
    """Count of M-3 alerts that hit email retry-cap and now ride session push."""
    sql = (
        "SELECT COUNT(*) FROM unread_alerts "
        "WHERE severity = %s "
        "  AND email_sent_at IS NULL "
        "  AND email_send_attempts >= %s "
        "  AND acknowledged_at IS NULL"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (SEVERITY_M3, MAX_EMAIL_ATTEMPTS))
        return int(cur.fetchone()[0])


def _query_unread_count(conn: Any, severity: int) -> int:
    sql = (
        "SELECT COUNT(*) FROM unread_alerts "
        "WHERE severity = %s AND acknowledged_at IS NULL"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (severity,))
        return int(cur.fetchone()[0])


def _query_disputed_catalog_count(conn: Any) -> int:
    """Count disputed catalog entries — gracefully degrades if table absent.

    The peak-pain-catalog "disputed" field is added in a migration that may
    not yet be applied in every environment. We probe for the table and
    return 0 when it's missing rather than crashing /system-health.
    """
    return _count_disputed_catalog_safe(conn)


def _query_disputed_catalog_tickers(conn: Any) -> list[str]:
    """Tickers excluded from retrieval due to dispute status — best effort."""
    return _list_disputed_catalog_safe(conn)


def _count_disputed_catalog_safe(conn: Any) -> int:
    sql_probe = (
        "SELECT to_regclass('public.peak_pain_catalog')"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql_probe)
            row = cur.fetchone()
            if not row or row[0] is None:
                return 0
            cur.execute(
                "SELECT COUNT(*) FROM peak_pain_catalog "
                "WHERE COALESCE(disputed, FALSE) = TRUE"
            )
            return int(cur.fetchone()[0])
    except Exception as exc:
        # Column missing or schema variant — log + return 0.
        _LOG.debug("disputed catalog probe failed: %s", exc)
        return 0


def _list_disputed_catalog_safe(conn: Any) -> list[str]:
    sql_probe = (
        "SELECT to_regclass('public.peak_pain_catalog')"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql_probe)
            row = cur.fetchone()
            if not row or row[0] is None:
                return []
            cur.execute(
                "SELECT DISTINCT ticker FROM peak_pain_catalog "
                "WHERE COALESCE(disputed, FALSE) = TRUE "
                "ORDER BY ticker"
            )
            return [r[0] for r in cur.fetchall() if r[0]]
    except Exception as exc:
        _LOG.debug("disputed catalog list probe failed: %s", exc)
        return []


def _query_system_errors_last_7d(
    conn: Any,
    now: _dt.datetime,
) -> list[tuple[str, int]]:
    sql = (
        "SELECT source, COUNT(*) FROM system_errors "
        "WHERE timestamp_at >= %s "
        "GROUP BY source "
        "ORDER BY COUNT(*) DESC, source ASC"
    )
    cutoff = now - _dt.timedelta(days=7)
    with conn.cursor() as cur:
        cur.execute(sql, (cutoff,))
        return [(r[0], int(r[1])) for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #


def _render_markdown(s: SystemHealthSnapshot) -> str:
    lines: list[str] = []
    lines.append(f"# /system-health — {s.generated_at.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # Degraded MCPs
    lines.append("## Degraded MCPs (unresolved errors)")
    if not s.degraded_mcps:
        lines.append("- _None — all MCPs healthy._")
    else:
        for src, last_ok in s.degraded_mcps:
            label = (
                "never"
                if last_ok.year < 2000
                else last_ok.strftime("%Y-%m-%d %H:%M UTC")
            )
            lines.append(f"- `{src}` — last success: {label}")
    lines.append("")

    # Queued recoveries
    lines.append("## Queued recoveries")
    lines.append(f"- Email queue depth (pending M-3 sends): **{s.email_queue_depth}**")
    lines.append(
        f"- Email queued-for-session-push (final-failure backlog): "
        f"**{s.email_queued_for_session_push}**"
    )
    lines.append("")

    # Push-alert backlog
    lines.append("## Active push-alert backlog")
    lines.append(f"- Unread M-3: **{s.unread_m3}**")
    lines.append(f"- Unread M-2: **{s.unread_m2}**")
    lines.append("")

    # Disputed catalog
    lines.append("## Disputed catalog entries (excluded from retrieval)")
    lines.append(f"- Count: **{s.disputed_catalog_count}**")
    if s.disputed_catalog_tickers:
        lines.append("- Tickers: " + ", ".join(f"`{t}`" for t in s.disputed_catalog_tickers))
    lines.append("")

    # System errors last 7d
    lines.append("## system_errors — last 7 days, by source")
    if not s.system_errors_last_7d_by_source:
        lines.append("- _No errors in the last 7 days._")
    else:
        for src, n in s.system_errors_last_7d_by_source:
            lines.append(f"- `{src}` — {n}")
    lines.append("")

    return "\n".join(lines)
