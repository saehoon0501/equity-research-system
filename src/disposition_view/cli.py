"""CLI entry point for /disposition.

Per v3 spec Section 5.4 — backs the `/disposition` slash command.

Usage:
  python -m src.disposition_view.cli render
  python -m src.disposition_view.cli render --ticker NVDA
  python -m src.disposition_view.cli render --mode B_prime
  python -m src.disposition_view.cli render --toggle-primary NVDA short

Connection wiring (mirrors src/audit_trail/cli.py):
  - DATABASE_URL env var, else POSTGRES_* env vars (USER, PASSWORD, HOST,
    PORT, DB).
  - Tries `psycopg` (v3) first, then `psycopg2`.

Exit codes:
  0 = success
  2 = lookup error (no such ticker)
  4 = bad arguments
  5 = environment / driver missing
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from src.disposition_view.horizon_signals import HORIZONS
from src.disposition_view.loader import get_disposition_rows
from src.disposition_view.renderer import render_disposition, render_single_ticker

# Allowed mode filter values per Section 2.2.
_VALID_MODES = ("B", "B_prime", "C")


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
        print(
            "ERROR: neither psycopg (v3) nor psycopg2 is installed. "
            "Install one to run the disposition_view CLI.",
            file=sys.stderr,
        )
        raise SystemExit(5) from e


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.disposition_view.cli",
        description=(
            "Render multi-horizon disposition view + mode-fit dashboard. "
            "Per v3 spec Section 4.6 Q2 + 5.4 + Phase 4 Q5."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    render = sub.add_parser(
        "render", help="Render the disposition view (default invocation)."
    )
    render.add_argument(
        "--ticker",
        metavar="T",
        help="Render expanded detail for a single ticker.",
    )
    render.add_argument(
        "--mode",
        choices=_VALID_MODES,
        help="Filter to one mode (B / B_prime / C).",
    )
    render.add_argument(
        "--toggle-primary",
        metavar=("TICKER", "HORIZON"),
        nargs=2,
        action="append",
        default=[],
        help=(
            "Override mode-anchored default primary horizon for a name. "
            "Repeatable. HORIZON ∈ {short, mid, long}."
        ),
    )
    return p


def _parse_overrides(items: list[list[str]]) -> dict[str, str]:
    """Parse repeated ``--toggle-primary T H`` pairs into a mapping.

    Per v3 spec Section 4.6 Q2 + Section 5.4: ``--toggle-primary`` is
    SESSION-ONLY. Overrides are not persisted across CLI invocations
    (no write to ``disposition_overrides`` or any other table). To
    re-apply a non-default primary horizon, re-pass the flag.

    Validation:
      * Each pair must have exactly two elements (ticker, horizon).
      * ``horizon`` must be in ``HORIZONS`` (``short`` / ``mid`` / ``long``).
      * The same ticker must not appear twice — duplicate overrides
        almost always indicate operator confusion (which one wins?), so
        we exit with code 4 rather than silently last-write-wins.

    Raises:
        SystemExit(4): malformed pair, unknown horizon, or duplicate
            ticker. The caller (``main``) lets this bubble up.

    v0.5+ deferred work: a persistent ``disposition_overrides`` table
    keyed by ``(operator_id, ticker)`` could replace this session-only
    semantics. Out of scope for v0.1.
    """
    overrides: dict[str, str] = {}
    for pair in items:
        if len(pair) != 2:
            raise SystemExit(4)
        ticker, horizon = pair
        if horizon not in HORIZONS:
            print(
                f"ERROR: --toggle-primary horizon {horizon!r} not in {HORIZONS}",
                file=sys.stderr,
            )
            raise SystemExit(4)
        if ticker in overrides:
            print(
                f"ERROR: --toggle-primary specified twice for ticker "
                f"{ticker!r} (was {overrides[ticker]!r}, now {horizon!r}); "
                "pass each ticker at most once",
                file=sys.stderr,
            )
            raise SystemExit(4)
        overrides[ticker] = horizon
    return overrides


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd != "render":
        print(f"ERROR: unknown command {args.cmd!r}", file=sys.stderr)
        return 4

    overrides = _parse_overrides(args.toggle_primary)

    conn = _open_connection()
    try:
        rows = get_disposition_rows(conn, ticker=args.ticker, mode=args.mode)
        if args.ticker:
            if not rows:
                print(
                    f"ERROR: ticker {args.ticker!r} not in watchlist",
                    file=sys.stderr,
                )
                return 2
            primary_override = overrides.get(args.ticker)
            print(render_single_ticker(rows[0], primary_override=primary_override))
            return 0

        print(render_disposition(rows, primary_overrides=overrides))
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
