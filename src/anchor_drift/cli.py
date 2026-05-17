"""Command-line entry points for anchor-drift detection.

Usage::

    python -m anchor_drift.cli check --ticker NVDA
    python -m anchor_drift.cli check --ticker NVDA --as-of 2026-04-29
    python -m anchor_drift.cli check --bulk
    python -m anchor_drift.cli check --bulk --no-persist

Exit codes:
    0 - success (no channels triggered OR triggered + persisted)
    1 - DB / IO error
    2 - usage error
    3 - LookupError (ticker not on watchlist)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Sequence

from .orchestrator import (
    run_anchor_drift_check,
    run_anchor_drift_check_bulk,
)

_LOG = logging.getLogger("anchor_drift.cli")


def _outcome_to_dict(o: object) -> dict:
    a = o  # type: ignore
    return {
        "ticker": a.ticker,
        "check_date": a.check_date,
        "any_triggered": a.any_triggered,
        "triggered_channels": a.triggered_channels,
        "channel_1": a.channel_1.to_payload(),
        "channel_2": a.channel_2.to_payload(),
        "channel_3": a.channel_3.to_payload(),
        "forced_review": a.forced_review,
        "check_id": str(a.check_id) if a.check_id else None,
    }


def _cmd_check(args: argparse.Namespace) -> int:
    persist = not args.no_persist
    if args.bulk:
        outcomes = run_anchor_drift_check_bulk(
            as_of=args.as_of, persist=persist
        )
        print(json.dumps(
            [_outcome_to_dict(o) for o in outcomes],
            indent=2, default=str,
        ))
        return 0
    if not args.ticker:
        print("--ticker required (or pass --bulk)", file=sys.stderr)
        return 2
    try:
        outcome = run_anchor_drift_check(
            ticker=args.ticker,
            current_pillars=[],
            as_of=args.as_of,
            persist=persist,
        )
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(_outcome_to_dict(outcome), indent=2, default=str))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="anchor_drift.cli",
        description=(
            "Run the 3-channel anchor-drift detector per v3 spec "
            "Section 4.5 Q5 (lines 530-536)."
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="Run anchor-drift check")
    c.add_argument("--ticker", default=None)
    c.add_argument(
        "--bulk", action="store_true", help="Run across full watchlist"
    )
    c.add_argument("--as-of", default=None)
    c.add_argument("--no-persist", action="store_true")
    c.set_defaults(func=_cmd_check)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
