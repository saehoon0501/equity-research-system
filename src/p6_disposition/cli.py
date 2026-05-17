"""CLI for P6 disposition determination.

    python -m src.p6_disposition.cli determine \\
        --ticker NVDA --mode B_prime --quality HIGH --decision ADD

Outputs JSON to stdout suitable for piping into ``p7_recommendation_emitter``.

Per v3 spec Section 2.1 (funnel composition) + Section 4.6 Q2.
"""

from __future__ import annotations

import argparse
import json
import sys

from src.p6_disposition.determiner import (
    DispositionInput,
    determine_disposition,
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="p6_disposition")
    sub = parser.add_subparsers(dest="cmd", required=True)
    det = sub.add_parser("determine", help="derive disposition for one ticker")
    det.add_argument("--ticker", required=True)
    det.add_argument(
        "--mode", required=True, choices=("B", "B_prime", "C")
    )
    det.add_argument(
        "--quality", required=True, choices=("HIGH", "STANDARD")
    )
    det.add_argument(
        "--decision", required=True, choices=("ADD", "WATCH", "PASS")
    )
    det.add_argument("--currently-held", action="store_true")
    det.add_argument(
        "--conviction-bucket",
        choices=("HIGH", "MEDIUM", "LOW"),
        default=None,
    )
    det.add_argument(
        "--prior-recommendation",
        choices=("BUY", "HOLD", "TRIM", "SELL"),
        default=None,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    inp = DispositionInput(
        ticker=args.ticker,
        mode=args.mode,
        company_quality_flag=args.quality,
        pm_supervisor_decision=args.decision,
        currently_held=args.currently_held,
        conviction_bucket=args.conviction_bucket,
        prior_recommendation=args.prior_recommendation,
    )
    decision = determine_disposition(inp)
    print(json.dumps(decision.to_payload(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
