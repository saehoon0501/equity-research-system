"""peak_pain_catalog CLI.

    python -m peak_pain_catalog.cli priority-run [--dry-run] [--catalog PATH]
    python -m peak_pain_catalog.cli validate-case --case-id NVDA-2008 [--dry-run]
    python -m peak_pain_catalog.cli list-priority

Per Section 7.4 cold-start parallel track, `priority-run` is the entry point
that operator runs offline before v0.1 launch to validate the ~45 priority
cases (15 calibration + 30 canonical archetypes).

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 7.4 (parallel tracks; priority subset offline pre-launch).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from src.peak_pain_catalog.lazy_runner import validate_on_first_retrieval
from src.peak_pain_catalog.priority_runner import (
    PRIORITY_CASE_IDS,
    run_priority_subset,
    summary_to_dict,
)


DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "references"
    / "empirical"
    / "peak-pain-archetypes"
    / "catalog-v0.1.md"
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="peak_pain_catalog",
        description="3-LLM consensus extraction pipeline for the peak-pain catalog.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser(
        "priority-run",
        help="Validate the ~45 priority cases (15 calibration + 30 canonical).",
    )
    pr.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG_PATH,
        help="Path to catalog-v0.1.md.",
    )
    pr.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Postgres writes; HMAC-sign payloads but emit to stdout.",
    )
    pr.add_argument(
        "--dsn",
        default=os.environ.get("PEAK_PAIN_DSN"),
        help="Postgres DSN (overrides PEAK_PAIN_DSN env). Ignored if --dry-run.",
    )

    vc = sub.add_parser(
        "validate-case",
        help="Validate a single case (used by lazy-retrieval path).",
    )
    vc.add_argument("--case-id", required=True, help="Catalog case_id, e.g. NVDA-2008.")
    vc.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    vc.add_argument("--dry-run", action="store_true")
    vc.add_argument("--dsn", default=os.environ.get("PEAK_PAIN_DSN"))

    sub.add_parser(
        "list-priority",
        help="Print the priority subset case_id list.",
    )

    return p


def _cmd_priority_run(args: argparse.Namespace) -> int:
    dsn = None if args.dry_run else args.dsn
    summary = run_priority_subset(
        catalog_md_path=args.catalog,
        dsn=dsn,
    )
    print(json.dumps(summary_to_dict(summary), indent=2))
    if summary.missing_case_ids:
        print(
            f"WARN: {len(summary.missing_case_ids)} case_ids not matched in catalog",
            file=sys.stderr,
        )
    if summary.disputed > 0:
        print(
            f"WARN: {summary.disputed} cases tagged disputed — excluded from active retrieval",
            file=sys.stderr,
        )
        return 2
    return 0


def _cmd_validate_case(args: argparse.Namespace) -> int:
    dsn = None if args.dry_run else args.dsn
    result = validate_on_first_retrieval(
        args.case_id, catalog_md_path=args.catalog, dsn=dsn
    )
    print(
        json.dumps(
            {
                "case_id": result.case_id,
                "outcome": result.outcome,
                "validation_status": result.consensus.validation_status,
                "retrieval_safe": result.retrieval_safe,
                "model_mix": list(result.consensus.model_mix),
                "hmac_signature": result.payload.hmac_signature,
            },
            indent=2,
        )
    )
    return 0 if result.retrieval_safe else 2


def _cmd_list_priority(_args: argparse.Namespace) -> int:
    print(json.dumps(list(PRIORITY_CASE_IDS), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "priority-run":
        return _cmd_priority_run(args)
    if args.command == "validate-case":
        return _cmd_validate_case(args)
    if args.command == "list-priority":
        return _cmd_list_priority(args)
    parser.error("unknown command")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
