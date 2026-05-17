"""CLI entrypoint for the outcome resolver.

Usage:
    python -m src.outcomes.cli resolve [--as-of YYYY-MM-DD] [--ticker T] [--dry-run]
    python -m src.outcomes.cli status

Exit codes mirror the orchestrator CLI convention:
    0  success
    4  bad arguments
    5  environment / driver missing
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from typing import Any

from src.outcomes.resolver import resolve_outcomes


def _open_connection() -> Any:
    """Same DSN convention as src/orchestrator/cli.py for consistency."""
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
            "ERROR: neither psycopg (v3) nor psycopg2 is installed.",
            file=sys.stderr,
        )
        raise SystemExit(5) from e


def _cmd_resolve(args: argparse.Namespace) -> int:
    as_of = _dt.date.fromisoformat(args.as_of) if args.as_of else None
    conn = _open_connection()
    try:
        stats = resolve_outcomes(
            conn,
            as_of=as_of,
            ticker=args.ticker,
            dry_run=args.dry_run,
        )
    finally:
        conn.close()

    print(f"candidates examined : {stats.candidates_examined}")
    print(f"rows inserted       : {stats.rows_inserted}")
    print(f"rows updated        : {stats.rows_updated}")
    print(f"horizons resolved   :")
    for horizon in ("30d", "90d", "1y"):
        n = stats.horizons_resolved.get(horizon, 0)
        print(f"  T+{horizon:<3} : {n}")
    if stats.errors:
        print(f"errors ({len(stats.errors)}):")
        for line in stats.errors[:10]:
            print(f"  - {line}")
        if len(stats.errors) > 10:
            print(f"  ... ({len(stats.errors) - 10} more)")
    return 0


def _cmd_status(_: argparse.Namespace) -> int:
    """Surface counts: total recs, resolved-at-T+90 (the v0.5 trigger)."""
    conn = _open_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM execution_recommendations")
        total_recs = cur.fetchone()[0]
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE t_plus_30d_return IS NOT NULL) AS r30,
                COUNT(*) FILTER (WHERE t_plus_90d_return IS NOT NULL) AS r90,
                COUNT(*) FILTER (WHERE t_plus_1y_return  IS NOT NULL) AS r1y,
                COUNT(*) AS total_outcome_rows
            FROM recommendation_outcomes
            """
        )
        r30, r90, r1y, total_out = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    print(f"execution_recommendations     : {total_recs}")
    print(f"recommendation_outcomes (any) : {total_out}")
    print(f"resolved at T+30d             : {r30}")
    print(f"resolved at T+90d             : {r90}  (v0.5 trigger ≥ 50)")
    print(f"resolved at T+1y              : {r1y}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="outcomes")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_resolve = sub.add_parser("resolve", help="Resolve closed-window returns")
    p_resolve.add_argument("--as-of", help="YYYY-MM-DD; default today (UTC)")
    p_resolve.add_argument("--ticker", help="Restrict to one ticker")
    p_resolve.add_argument("--dry-run", action="store_true")
    p_resolve.set_defaults(func=_cmd_resolve)

    p_status = sub.add_parser("status", help="Show resolution counts")
    p_status.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
