"""CLI for the override-outcome resolver (companion to /resolve-outcomes).

Usage:
    python -m src.outcomes.override_cli resolve [--as-of YYYY-MM-DD]
                                                 [--ticker T] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from typing import Any

from src.outcomes.override_resolver import resolve_override_outcomes


def _open_connection() -> Any:
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
        print("ERROR: neither psycopg nor psycopg2 installed.", file=sys.stderr)
        raise SystemExit(5) from e


def _cmd_resolve(args: argparse.Namespace) -> int:
    as_of = _dt.date.fromisoformat(args.as_of) if args.as_of else None
    conn = _open_connection()
    try:
        stats = resolve_override_outcomes(
            conn, as_of=as_of, ticker=args.ticker, dry_run=args.dry_run
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
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="override-outcomes")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("--as-of")
    p_resolve.add_argument("--ticker")
    p_resolve.add_argument("--dry-run", action="store_true")
    p_resolve.set_defaults(func=_cmd_resolve)
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
