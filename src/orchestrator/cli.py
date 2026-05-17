"""CLI entry point: ``python -m src.orchestrator.cli [subcommand]``.

Per v3 spec Section 5.4 — backs the ``/run`` master orchestrator.

Subcommands:
  (default)        — full operator briefing
  status           — phase status only
  launch-gates     — gate status grid (Section 7)
  today            — today's recommended actions (v0.1-active+)

Connection wiring mirrors src/audit_trail/cli.py:
  - DATABASE_URL env var, else POSTGRES_* env vars (USER, PASSWORD, HOST,
    PORT, DB).
  - Tries `psycopg` (v3) first, then `psycopg2`.

Exit codes:
  0 = success
  4 = bad arguments
  5 = environment / driver missing
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from src.orchestrator.operator_briefing import (
    collect_operator_briefing,
    render_operator_briefing,
)
from src.orchestrator.phase_detector import Phase, detect_phase
from src.orchestrator.v01_active_routing import (
    collect_scheduled_actions,
    render_scheduled_actions,
)
from src.orchestrator.v01_launch_status import (
    collect_launch_gates,
    render_launch_gate_grid,
)


def _open_connection() -> Any:
    """Open a Postgres connection from env vars (mirrors audit_trail CLI)."""
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
            "Install one to run the orchestrator CLI.",
            file=sys.stderr,
        )
        raise SystemExit(5) from e


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.orchestrator.cli",
        description=(
            "Master orchestrator for /run. Auto-detects phase and renders "
            "the operator briefing. Per v3 spec Section 5.4."
        ),
    )
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser(
        "briefing",
        help="Full operator briefing (default if no subcommand given).",
    )
    sub.add_parser(
        "status",
        help="Phase status only — no gate / action / alert detail.",
    )
    sub.add_parser(
        "launch-gates",
        help="Section 7 launch-gate grid (any phase).",
    )
    sub.add_parser(
        "today",
        help="Today's recommended cadence actions (v0.1-active+).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    cmd = args.cmd or "briefing"

    conn = _open_connection()
    try:
        if cmd == "briefing":
            briefing = collect_operator_briefing(conn)
            print(render_operator_briefing(briefing))
            return 0

        if cmd == "status":
            snap = detect_phase(conn)
            lines = [
                f"phase: {snap.phase.value}",
                f"reason: {snap.reason}",
                f"launch_signed_off: {snap.launch_signed_off}",
                f"resolved_predictions: {snap.resolved_predictions}",
                f"real_money_active: {snap.real_money_active}",
                f"days_since_launch: {snap.days_since_launch}",
            ]
            print("\n".join(lines))
            return 0

        if cmd == "launch-gates":
            grid = collect_launch_gates(conn)
            print(render_launch_gate_grid(grid))
            return 0

        if cmd == "today":
            snap = detect_phase(conn)
            if snap.phase == Phase.V01_LAUNCH_READINESS:
                print(
                    "_Phase is v0.1-launch-readiness — no cadence actions yet. "
                    "See `python -m src.orchestrator.cli launch-gates`._"
                )
                return 0
            actions = collect_scheduled_actions(conn)
            print(render_scheduled_actions(actions))
            return 0

        print(f"ERROR: unknown subcommand {cmd!r}", file=sys.stderr)
        return 4
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
