"""CLI for P5 watchlist add.

Two invocations:

    python -m p5_watchlist.cli add --debate-result <path>
        Read a serialized P4 debate result (JSON) from disk.

    python -m p5_watchlist.cli add --from-orchestrator
        Read the JSON-serialized debate result from STDIN — used when the
        master orchestrator pipes P4 → P5 in-process.

Per v3 spec Section 2.1 funnel composition.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from typing import Any

from src.p5_watchlist.adder import (
    WatchlistAddInput,
    add_to_watchlist,
)


_LOG = logging.getLogger(__name__)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="p5_watchlist", description="P5 watchlist add")
    sub = parser.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="add ADD-verdict ticker to watchlist")
    src = add.add_mutually_exclusive_group(required=True)
    src.add_argument("--debate-result", type=str, help="path to P4 debate result JSON")
    src.add_argument(
        "--from-orchestrator",
        action="store_true",
        help="read debate result JSON from STDIN",
    )
    add.add_argument(
        "--dry-run",
        action="store_true",
        help="compute HMACs + outcome but do NOT write to Postgres",
    )
    add.add_argument(
        "--parameters-version",
        type=str,
        default=None,
        help="UUID of parameters config used at lock time",
    )
    return parser.parse_args(argv)


def _load_debate(args: argparse.Namespace) -> dict[str, Any]:
    if args.from_orchestrator:
        return json.loads(sys.stdin.read())
    with open(args.debate_result, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _build_input(payload: dict[str, Any], parameters_version: str | None) -> WatchlistAddInput:
    """Map a P4 debate-result JSON payload onto WatchlistAddInput.

    Expected payload shape (loose contract; tolerant of variations the
    P4 orchestrator may produce)::

        {
          "ticker": "NVDA",
          "mode": "B_prime",
          "company_quality_flag": "HIGH",
          "phase_d": {"decision": "ADD", ...},
          "thesis_pillars_original": [...],
          "scenario_A_base_projections": {...},
          "macro_regime_style_output": ...
        }
    """
    pd = payload.get("phase_d") or {}
    decision = (
        pd.get("decision")
        or payload.get("decision")
        or payload.get("pm_supervisor_decision")
    )
    if not decision:
        raise ValueError("debate-result payload missing PMSupervisor decision")

    macro = (
        payload.get("macro_regime_style_output")
        or payload.get("phase_a", {}).get("macro_regime")
        or payload.get("phase_b", {}).get("macro_regime")
        or {}
    )

    return WatchlistAddInput(
        ticker=payload["ticker"],
        mode=payload["mode"],
        company_quality_flag=payload.get("company_quality_flag", "STANDARD"),
        pm_supervisor_decision=decision,
        thesis_pillars_original=payload["thesis_pillars_original"],
        scenario_A_base_projections=payload["scenario_A_base_projections"],
        macro_regime_style_output=macro,
        parameters_version=(
            uuid.UUID(parameters_version) if parameters_version else None
        ),
    )


def _connect() -> Any:
    """Lazy psycopg connection; defers import so dry-run does not require it."""
    import psycopg  # type: ignore

    dsn = os.environ.get(
        "EQUITY_RESEARCH_DSN",
        "postgresql://postgres@127.0.0.1:5432/equity_research",
    )
    return psycopg.connect(dsn)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    payload = _load_debate(args)
    inp = _build_input(payload, args.parameters_version)
    conn = None if args.dry_run else _connect()
    try:
        outcome = add_to_watchlist(inp, conn=conn)
    finally:
        if conn is not None:
            conn.close()
    print(
        json.dumps(
            {
                "ticker": outcome.ticker,
                "inserted": outcome.inserted,
                "mode": outcome.mode,
                "company_quality_flag": outcome.company_quality_flag,
                "conviction_threshold": outcome.conviction_threshold,
                "regime_sensitivity": outcome.regime_sensitivity,
                "thesis_pillars_original_hmac": outcome.thesis_pillars_original_hmac,
                "scenario_A_base_projections_hmac": (
                    outcome.scenario_A_base_projections_hmac
                ),
                "added_at": outcome.added_at.isoformat(),
                "error": outcome.error,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
