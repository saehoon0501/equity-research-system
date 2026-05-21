#!/usr/bin/env python3
"""Append an ESCALATE resolution row to logs/validation_attempts.jsonl.

Per docs/phase_gates.md §2: stub writer for the first ESCALATE event so
verbal-only resolution doesn't lose the highest-information datapoint.
"""
import argparse
import json
import os
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--agent-type", required=True)
    parser.add_argument("--attempt-n", type=int, required=True)
    parser.add_argument(
        "--outcome",
        required=True,
        choices=[
            "operator_override_accept",
            "operator_override_reject",
            "retry_succeeded_offline",
            "run_abandoned",
        ],
    )
    parser.add_argument("--notes", default="")
    parser.add_argument("--by", default=os.environ.get("USER", "unknown"))
    parser.add_argument(
        "--log-path",
        default="logs/validation_attempts.jsonl",
        help="Override JSONL path (default: logs/validation_attempts.jsonl).",
    )
    args = parser.parse_args()

    row = {
        "run_id": args.run_id,
        "agent_type": args.agent_type,
        "attempt_n": args.attempt_n,
        "resolution_event": True,
        "resolution_outcome": args.outcome,
        "resolution_notes": args.notes[:500],
        "resolution_timestamp_unix": int(time.time()),
        "resolution_by": args.by,
    }
    with open(args.log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()
        os.fsync(f.fileno())
    print(f"appended resolution row for run_id={args.run_id} to {args.log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
