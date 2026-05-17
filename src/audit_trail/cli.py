"""CLI entry point: `python -m src.audit_trail.cli <rec_id> [--stage <s>] [--latest <ticker>] [--verify]`.

Per v3 spec Section 5.4 — backs the `/audit-trail` slash command.

Connection wiring:
  - Reads DATABASE_URL or POSTGRES_* env vars for connection.
  - Tries psycopg (v3) first, then psycopg2; both are common in Python data
    stacks. If neither is installed, falls back to a clear error.

Exit codes:
  0 = success
  2 = lookup error (no such rec_id / ticker / stage)
  3 = HMAC chain verification surfaced tamper-evidence (M-2 event signal)
  4 = bad arguments
  5 = environment / driver missing
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any
from uuid import UUID

from src.audit_trail.hmac_verify import verify_chain
from src.audit_trail.loader import (
    VALID_STAGES,
    get_audit_summary,
    get_chain_for_recommendation,
    get_latest_for_ticker,
    get_stage_drill,
)
from src.audit_trail.renderer import (
    render_audit_summary,
    render_chain_verification,
    render_stage_drill,
)


def _open_connection() -> Any:
    """Open a Postgres connection from env vars.

    Tries psycopg (v3) first, then psycopg2. The connection object exposes
    a `.cursor()` method matching the loader's _Connection protocol.
    """
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
            "Install one to run the audit_trail CLI.",
            file=sys.stderr,
        )
        raise SystemExit(5) from e


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.audit_trail.cli",
        description=(
            "Render audit drill-down for an execution recommendation. "
            "Per v3 spec Section 5.2 + 5.4."
        ),
    )
    p.add_argument(
        "rec_id",
        nargs="?",
        help="recommendation_id (UUID). Omit when using --latest <ticker>.",
    )
    p.add_argument(
        "--stage",
        choices=VALID_STAGES,
        help="Drill into one stage. Omit for top-level summary.",
    )
    p.add_argument(
        "--latest",
        metavar="TICKER",
        help="Resolve latest recommendation_id for ticker, then render.",
    )
    p.add_argument(
        "--verify",
        action="store_true",
        help="Render HMAC chain verification result for the recommendation.",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help=(
            "When --verify and AUDIT_HMAC_KEY missing, fail rather than "
            "report unkeyed mode. Per v3 Section 7 Q4 launch gate."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not args.rec_id and not args.latest:
        print("ERROR: must provide rec_id or --latest <ticker>", file=sys.stderr)
        return 4

    conn = _open_connection()
    try:
        # Resolve rec_id from --latest if needed.
        if args.latest:
            try:
                rec_id: UUID = get_latest_for_ticker(conn, args.latest)
            except LookupError as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 2
        else:
            try:
                rec_id = UUID(args.rec_id)
            except ValueError:
                print(
                    f"ERROR: rec_id {args.rec_id!r} is not a valid UUID",
                    file=sys.stderr,
                )
                return 4

        if args.verify:
            rows = get_chain_for_recommendation(conn, rec_id)
            try:
                result = verify_chain(rows, strict=args.strict)
            except RuntimeError as e:
                # `--strict` requested but AUDIT_HMAC_KEY missing — surface
                # cleanly with the env/driver-missing exit code instead of
                # crashing with an uncaught traceback.
                print(f"ERROR: {e}", file=sys.stderr)
                return 5
            print(render_chain_verification(result))

            # Hard error (e.g., empty chain) — same surface as before.
            if result.error:
                return 3

            # Parent-link tampering must surface as exit 3 even in unkeyed
            # mode (parent_audit_id chain semantics are independent of the
            # HMAC key). Previously, unkeyed mode short-circuited to 0,
            # masking forged parent pointers — the CLI would render the
            # report but exit success. Now: keyed mode reports
            # signature-AND-parent; unkeyed reports parent only.
            parent_ok = all(r.parent_link_ok for r in result.rows)
            if result.mode == "keyed":
                return 0 if result.all_ok else 3
            return 0 if parent_ok else 3

        if args.stage:
            try:
                row = get_stage_drill(conn, rec_id, args.stage)
            except LookupError as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 2
            print(render_stage_drill(args.stage, row))
            return 0

        try:
            summary = get_audit_summary(conn, rec_id)
        except LookupError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        print(render_audit_summary(summary))
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
