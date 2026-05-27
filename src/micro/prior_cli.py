"""CLI for /micro's prior resolution (PM Recommendation → PM report fallback).

The command fetches candidates via ``mcp__postgres`` (and optionally a PM-report
text file), then runs:

    python -m src.micro.prior_cli --recommendation HOLD
    python -m src.micro.prior_cli --summary-code SELL
    python -m src.micro.prior_cli --report-file memos/envelopes/pm-supervisor__<run>.json

and reads the printed JSON `{"summary_code", "source"}`. See ``src/micro/prior.py``.

Exit codes: 0 always (a null summary_code with source="none" is a valid
"prior-free" result, not an error).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from src.micro.prior import resolve


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.micro.prior_cli")
    p.add_argument("--recommendation", default=None,
                   help="execution_recommendations.recommendation (Tier-1 PM Recommendation)")
    p.add_argument("--summary-code", default=None,
                   help="counterfactual_ledger.summary_code (Tier-1 logged twin)")
    p.add_argument("--report-file", default=None,
                   help="path to a PM report / envelope text (Tier-2 fallback)")
    args = p.parse_args(argv)

    report_text = None
    if args.report_file:
        try:
            with open(args.report_file, "r", encoding="utf-8") as fh:
                report_text = fh.read()
        except OSError as exc:
            print(f"WARN: could not read report file: {exc}", file=sys.stderr)

    out = resolve(
        recommendation=args.recommendation,
        summary_code=args.summary_code,
        report_text=report_text,
    )
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
