"""Command-line entry points for the mode classifier.

Usage::

    python -m mode_classifier.cli classify --ticker NVDA
    python -m mode_classifier.cli classify --ticker NVDA --as-of 2024-12-31
    python -m mode_classifier.cli classify --ticker AAPL --high-stakes --no-persist
    python -m mode_classifier.cli recheck --ticker NVDA
    python -m mode_classifier.cli recheck-all

Exit codes:
    0 - success
    1 - DB error / IO error
    2 - usage error
    3 - LLM unavailable for a name that needed Stage 3
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from typing import Sequence

from .orchestrator import classify_ticker
from .recheck import recheck_all, recheck_ticker
from .stage3_overlap_tiebreaker import LLMUnavailableError


_LOG = logging.getLogger("mode_classifier.cli")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mode_classifier.cli",
        description=(
            "Classify equities into B / B' / C bins per v3 spec Section 2.2 "
            "(layered architecture: market-structural rule + quality refinement "
            "+ LLM tie-breaker on overlap)."
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    # classify
    c = sub.add_parser(
        "classify", help="Run the full pipeline for one ticker."
    )
    c.add_argument("--ticker", required=True)
    c.add_argument(
        "--as-of",
        default=None,
        help="ISO date for the snapshot (default today).",
    )
    c.add_argument(
        "--high-stakes",
        action="store_true",
        help="Route Stage 3 to Opus instead of Sonnet.",
    )
    c.add_argument(
        "--no-persist",
        action="store_true",
        help="Skip the DB INSERT (test/dry-run mode).",
    )
    c.set_defaults(func=_cmd_classify)

    # recheck
    r = sub.add_parser(
        "recheck",
        help="Phase 4 Q5 quarterly recheck for one ticker.",
    )
    r.add_argument("--ticker", required=True)
    r.add_argument("--as-of", default=None)
    r.add_argument("--no-persist", action="store_true")
    r.set_defaults(func=_cmd_recheck)

    # recheck-all
    ra = sub.add_parser(
        "recheck-all",
        help="Phase 4 Q5 quarterly recheck for every ticker on file.",
    )
    ra.add_argument("--as-of", default=None)
    ra.add_argument("--no-persist", action="store_true")
    ra.set_defaults(func=_cmd_recheck_all)

    return p


def _cmd_classify(args: argparse.Namespace) -> int:
    try:
        outcome = classify_ticker(
            ticker=args.ticker,
            as_of=args.as_of,
            high_stakes=args.high_stakes,
            persist=not args.no_persist,
        )
    except LLMUnavailableError as exc:
        print(f"LLM unavailable: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"classify failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(_serialize_outcome(outcome), indent=2, default=str))
    return 0


def _cmd_recheck(args: argparse.Namespace) -> int:
    try:
        outcome = recheck_ticker(
            args.ticker, as_of=args.as_of, persist=not args.no_persist
        )
    except Exception as exc:
        print(f"recheck failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(outcome), indent=2, default=str))
    return 0


def _cmd_recheck_all(args: argparse.Namespace) -> int:
    try:
        outcomes = recheck_all(
            as_of=args.as_of, persist=not args.no_persist
        )
    except Exception as exc:
        print(f"recheck-all failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            [asdict(o) for o in outcomes], indent=2, default=str
        )
    )
    return 0


def _serialize_outcome(outcome) -> dict:
    """Serialize a ClassificationOutcome to JSON-ready dict.

    The dataclass holds Stage 1/2/3 result objects which are themselves
    dataclasses and thus serializable, but Stage 3's TiebreakerResult
    contains nested TiebreakerSample list — easiest path is to serialize
    via the .to_payload() / .to_rule_outcomes() methods we already have.
    """
    return {
        "classification_id": str(outcome.classification_id),
        "ticker": outcome.ticker,
        "final_mode": outcome.final_mode,
        "company_quality_flag": outcome.company_quality_flag,
        "classification_method": outcome.classification_method,
        "rule_outcomes": outcome.rule_outcomes,
        "llm_tiebreaker": outcome.llm_tiebreaker,
        "recheck_status": outcome.recheck_status,
        "prior_classification_id": (
            str(outcome.prior_classification_id)
            if outcome.prior_classification_id
            else None
        ),
        "parameters_version": (
            str(outcome.parameters_version) if outcome.parameters_version else None
        ),
        "classified_at": outcome.classified_at.isoformat(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
