"""CLI entry point for /micro — the intraday day-trading signal helper.

Per CLAUDE.md P1, the /micro slash command keeps orchestration in markdown and
delegates the deterministic signal math here. The command fetches data via the
``massive`` MCP server, writes a payload to a scratch JSON file, then runs:

    python -m src.micro.cli signal --input <scratch.json>

and renders the JSON printed to stdout.

Input payload schema (all keys optional except ``bars``):
    {
      "ticker": "SPY",
      "bars":  [ {"ts","open","high","low","close","volume","vwap"}, ... ],
      "live":  { ...stream_micro_aggregate output... },
      "prior": { "summary_code": "BUY"|"HOLD"|"TRIM"|"SELL", ... }
    }

Output: the signal dict from ``signal_model.compute_signal`` plus echoed
``ticker`` and ``as_of``, pretty-printed JSON on stdout.

Exit codes:
    0 = success
    2 = no/invalid input
    4 = bad arguments
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from typing import Sequence

from src.micro.signal_model import compute_signal


def _now_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.micro.cli",
        description="Intraday LONG/SHORT/HOLD signal for the /micro command.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sig = sub.add_parser("signal", help="compute a probabilistic intraday signal")
    src = sig.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="path to a JSON payload file")
    src.add_argument("--stdin", action="store_true", help="read JSON payload from stdin")
    return p


def _load_payload(args: argparse.Namespace) -> dict:
    if args.stdin:
        raw = sys.stdin.read()
    else:
        with open(args.input, "r", encoding="utf-8") as fh:
            raw = fh.read()
    return json.loads(raw)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd != "signal":  # argparse already enforces, defensive
        return 4
    try:
        payload = _load_payload(args)
    except FileNotFoundError:
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"ERROR: could not read JSON payload: {exc}", file=sys.stderr)
        return 2

    bars = payload.get("bars") or []
    if not isinstance(bars, list):
        print("ERROR: 'bars' must be a list", file=sys.stderr)
        return 2

    kwargs = {"bars": bars, "live": payload.get("live"), "prior": payload.get("prior")}
    if payload.get("horizon_minutes") is not None:
        kwargs["horizon_minutes"] = float(payload["horizon_minutes"])
    if payload.get("daily_atr") is not None:
        kwargs["daily_atr"] = float(payload["daily_atr"])
    result = compute_signal(**kwargs)
    result["ticker"] = (payload.get("ticker") or "").upper() or None
    result["as_of"] = _now_iso()
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
