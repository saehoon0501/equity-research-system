"""Command-line entry points for the pre-mortem scheduler.

Usage::

    python -m premortem_scheduler.cli schedule-check
    python -m premortem_scheduler.cli schedule-check --ticker NVDA --mode B_prime
    python -m premortem_scheduler.cli record --ticker NVDA --trigger calendar_floor \\
        --mode B_prime --input session.json
    python -m premortem_scheduler.cli record --ticker NVDA --trigger mode_reclass \\
        --mode B_prime --input session.json --no-persist

``session.json`` shape (one session)::

    {
      "operator_imagined_failure_modes": [...],
      "thesis_pillars_revisited":        [...],
      "net_thesis_strength":             0.62,
      "operator_accepted_count":         2,
      "operator_rejected_count":         1,
      "days_since_last_premortem":       128,
      "llm_assist": {                  // optional — record from devil's-advocate
        "model": "claude-opus-4-7",
        "failure_modes": [...]
      }
    }

Exit codes:
    0 - success
    1 - DB / IO error
    2 - usage error
    3 - validation error (trigger not in enum)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from typing import Any, Sequence

from .devils_advocate import DevilsAdvocateOutput
from .recorder import PremortemRecord, record_premortem
from .scheduler import schedule_check_all, schedule_check_one

_LOG = logging.getLogger("premortem_scheduler.cli")


def _scheduled_to_dict(s: Any) -> dict[str, Any]:
    return {
        "ticker": s.ticker,
        "mode": s.mode,
        "due": s.due,
        "blocking": s.blocking,
        "primary_trigger": s.primary_trigger,
        "triggers": s.triggers,
        "cadence": asdict(s.cadence) if s.cadence else None,
        "event_checks": [asdict(c) for c in s.event_checks],
        "detail": s.detail,
    }


def _cmd_schedule_check(args: argparse.Namespace) -> int:
    if args.ticker:
        if not args.mode:
            print("--mode required when --ticker is provided", file=sys.stderr)
            return 2
        scheduled = schedule_check_one(
            args.ticker, args.mode, as_of=args.as_of
        )
        print(json.dumps(
            _scheduled_to_dict(scheduled), indent=2, default=str
        ))
        return 0
    rows = schedule_check_all(as_of=args.as_of)
    if args.due_only:
        rows = [s for s in rows if s.due]
    print(json.dumps(
        [_scheduled_to_dict(s) for s in rows], indent=2, default=str
    ))
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"failed to read --input: {exc}", file=sys.stderr)
        return 1
    llm = None
    if isinstance(payload.get("llm_assist"), dict):
        la = payload["llm_assist"]
        llm = DevilsAdvocateOutput(
            model=la.get("model") or "claude-opus-4-7",
            failure_modes=la.get("failure_modes", []) or [],
            error=la.get("error"),
        )
    record = PremortemRecord(
        ticker=args.ticker,
        premortem_date=args.date,
        trigger=args.trigger,
        mode=args.mode,
        operator_imagined_failure_modes=payload.get(
            "operator_imagined_failure_modes", []
        ),
        thesis_pillars_revisited=payload.get(
            "thesis_pillars_revisited", []
        ),
        net_thesis_strength=payload.get("net_thesis_strength"),
        llm_assist=llm,
        operator_accepted_count=int(
            payload.get("operator_accepted_count", 0)
        ),
        operator_rejected_count=int(
            payload.get("operator_rejected_count", 0)
        ),
        days_since_last_premortem=payload.get("days_since_last_premortem"),
    )
    try:
        pid = record_premortem(record, persist=not args.no_persist)
    except ValueError as exc:
        print(f"validation error: {exc}", file=sys.stderr)
        return 3
    print(json.dumps({"premortem_id": str(pid)}, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="premortem_scheduler.cli",
        description=(
            "Pre-mortem scheduler / recorder per v3 spec Section 4.5 Q4 "
            "(lines 514-528): mode-tuned cadence + 4 event triggers."
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser(
        "schedule-check",
        help="Run cadence + event-trigger checks (one ticker or all).",
    )
    s.add_argument("--ticker", default=None)
    s.add_argument("--mode", default=None, choices=["B", "B_prime", "C"])
    s.add_argument("--as-of", default=None)
    s.add_argument("--due-only", action="store_true")
    s.set_defaults(func=_cmd_schedule_check)

    r = sub.add_parser(
        "record",
        help="Record a completed pre-mortem session (writes to premortem).",
    )
    r.add_argument("--ticker", required=True)
    r.add_argument("--trigger", required=True)
    r.add_argument("--mode", default=None, choices=["B", "B_prime", "C"])
    r.add_argument(
        "--date",
        default=None,
        help="ISO date for premortem_date (default today).",
    )
    r.add_argument(
        "--input",
        required=True,
        help="Path to JSON session file (see module docstring).",
    )
    r.add_argument("--no-persist", action="store_true")
    r.set_defaults(func=_cmd_record)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.command == "record" and not args.date:
        import datetime as _dt
        # UTC date — ``date.today()`` reads server local tz.
        args.date = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
