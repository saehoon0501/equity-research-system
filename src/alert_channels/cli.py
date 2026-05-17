"""CLI entry points for alert_channels.

Per v3 spec Section 5.4 — backs the ``/alerts``, ``/ack``, and
``/system-health`` slash commands; also drives the email queue processor
(cron-style) and the session-start push.

Subcommands:

  surface-session                 — Render Claude Code session-start markdown
  ack <alert_id>                  — Mark one alert acknowledged
  ack-all                         — Mark every unacknowledged alert acknowledged
  list [--severity N] [--ticker T] [--type T] [--since ISO]
                                  — Render /alerts (filtered listing)
  system-health                   — Render /system-health markdown
  process-email-queue             — One-pass email-queue drain (cron-driven)

Connection wiring:
  Reuses the ``audit_trail.cli`` env-var convention: prefer DATABASE_URL,
  else compose from POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_HOST /
  POSTGRES_PORT / POSTGRES_DB.

Exit codes:
  0  success
  2  lookup error (no such alert_id, etc.)
  4  bad arguments
  5  environment / driver missing
  6  partial failure (e.g., process-email-queue had transient send failures)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any
from uuid import UUID

from .email_sender import SmtpConfig
from .queue_processor import process_email_queue
from .session_push import (
    acknowledge,
    acknowledge_all,
    list_unread_alerts,
    render_alerts_list,
    surface_unread_at_session_start,
)
from .system_health import render_system_health

_LOG = logging.getLogger("alert_channels.cli")


# --------------------------------------------------------------------------- #
# Connection wiring                                                           #
# --------------------------------------------------------------------------- #


def _open_connection() -> Any:
    """Open a Postgres connection from env vars (psycopg or psycopg2)."""
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        user = os.environ.get("POSTGRES_USER", "postgres")
        password = os.environ.get("POSTGRES_PASSWORD", "")
        host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ.get("POSTGRES_DB", "equity_research")
        cred = f"{user}:{password}" if password else user
        dsn = f"postgresql://{cred}@{host}:{port}/{db}"

    try:
        import psycopg  # type: ignore[import-not-found]

        return psycopg.connect(dsn)
    except ImportError:
        pass
    try:
        import psycopg2  # type: ignore[import-not-found]

        return psycopg2.connect(dsn)
    except ImportError as e:
        print(
            "ERROR: neither psycopg (v3) nor psycopg2 is installed. "
            "Install one to run the alert_channels CLI.",
            file=sys.stderr,
        )
        raise SystemExit(5) from e


# --------------------------------------------------------------------------- #
# Argparse                                                                    #
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.alert_channels.cli",
        description=(
            "alert_channels CLI — backs /alerts, /ack, /system-health, "
            "and the email queue processor. Per v3 spec Section 5.3 + 5.4."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "surface-session",
        help="Render unread alerts for Claude Code session-start.",
    )

    p_ack = sub.add_parser("ack", help="Acknowledge one alert by id.")
    p_ack.add_argument("alert_id", help="alert_id (UUID).")

    sub.add_parser("ack-all", help="Acknowledge every unacknowledged alert.")

    p_list = sub.add_parser(
        "list", help="Render /alerts listing (with optional filters)."
    )
    p_list.add_argument("--severity", type=int, choices=(2, 3))
    p_list.add_argument("--ticker", type=str)
    p_list.add_argument("--type", dest="alert_type", type=str)
    p_list.add_argument(
        "--since",
        type=str,
        help="ISO timestamp (UTC). Filters alerts created at-or-after this time.",
    )

    sub.add_parser("system-health", help="Render /system-health markdown.")

    sub.add_parser(
        "process-email-queue",
        help="One-pass email-queue drain (cron-style entry point).",
    )

    return p


# --------------------------------------------------------------------------- #
# Subcommand bodies                                                           #
# --------------------------------------------------------------------------- #


def _cmd_surface_session(conn: Any) -> int:
    print(surface_unread_at_session_start(conn))
    return 0


def _cmd_ack(conn: Any, alert_id_arg: str) -> int:
    try:
        alert_id = UUID(alert_id_arg)
    except ValueError:
        print(f"ERROR: alert_id {alert_id_arg!r} is not a valid UUID", file=sys.stderr)
        return 4
    ok = acknowledge(conn, alert_id)
    if not ok:
        print(f"No unacknowledged alert with id {alert_id}", file=sys.stderr)
        return 2
    print(f"Acknowledged {alert_id}")
    return 0


def _cmd_ack_all(conn: Any) -> int:
    n = acknowledge_all(conn)
    print(f"Acknowledged {n} alert(s)")
    return 0


def _cmd_list(conn: Any, args: argparse.Namespace) -> int:
    import datetime as _dt

    since = None
    if args.since:
        try:
            since = _dt.datetime.fromisoformat(args.since)
        except ValueError:
            print(f"ERROR: --since {args.since!r} is not a valid ISO timestamp", file=sys.stderr)
            return 4
        # Coerce naive `--since` to aware UTC so downstream comparisons
        # against timestamptz columns do not mix tz-aware and tz-naive.
        if since.tzinfo is None:
            since = since.replace(tzinfo=_dt.timezone.utc)
    rows = list_unread_alerts(
        conn,
        severity=args.severity,
        ticker=args.ticker,
        alert_type=args.alert_type,
        since=since,
    )
    print(render_alerts_list(rows))
    return 0


def _cmd_system_health(conn: Any) -> int:
    print(render_system_health(conn))
    return 0


def _cmd_process_email_queue(conn: Any) -> int:
    try:
        smtp_config = SmtpConfig.from_env()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 5
    result = process_email_queue(conn, smtp_config)
    print(
        f"examined={result.rows_examined} "
        f"sent={result.rows_sent} "
        f"failed_transient={result.rows_failed_transient} "
        f"queued_for_session_push={result.rows_queued_for_session_push} "
        f"skipped_backoff={result.rows_skipped_backoff}"
    )
    if result.rows_failed_transient or result.rows_queued_for_session_push:
        return 6
    return 0


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    conn = _open_connection()
    try:
        if args.cmd == "surface-session":
            return _cmd_surface_session(conn)
        if args.cmd == "ack":
            return _cmd_ack(conn, args.alert_id)
        if args.cmd == "ack-all":
            return _cmd_ack_all(conn)
        if args.cmd == "list":
            return _cmd_list(conn, args)
        if args.cmd == "system-health":
            return _cmd_system_health(conn)
        if args.cmd == "process-email-queue":
            return _cmd_process_email_queue(conn)
        # argparse should reject anything else
        print(f"ERROR: unknown subcommand {args.cmd!r}", file=sys.stderr)
        return 4
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
