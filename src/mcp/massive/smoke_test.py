"""Live smoke test for the Massive MCP server.

Cannot be exercised end-to-end without a real ``MASSIVE_API_KEY`` (the unit
tests cover the deterministic signal math; this covers the network seam). Run
it once you have a key in the repo-root ``.env``:

    uv run --project src/mcp/massive python src/mcp/massive/smoke_test.py SPY

It calls both tools against a liquid name and prints the results. During market
hours you should see ``status=ok`` with a populated ``last_trade_price`` and a
non-empty ``bars`` list. Outside market hours expect ``status=no_ticks`` from
the websocket (markets closed) but bars from the most recent session via REST.

Exit codes: 0 if both tools returned without a config/auth/connection error,
1 otherwise.
"""

from __future__ import annotations

import asyncio
import json
import sys

# Import the server module directly (it lives alongside this file).
import server  # type: ignore[import-not-found]


def main(ticker: str) -> int:
    print(f"=== stream_micro_aggregate({ticker}, 8s) ===")
    live = asyncio.run(server._collect_window(ticker, 8, ["T", "Q", "A"]))
    print(json.dumps(live, indent=2, default=str))

    print(f"\n=== get_intraday_bars({ticker}, 1, minute, 60) ===")
    bars = server.get_intraday_bars(ticker, 1, "minute", 60)
    summary = {k: v for k, v in bars.items() if k != "bars"}
    summary["sample_bar"] = (bars.get("bars") or [None])[-1]
    print(json.dumps(summary, indent=2, default=str))

    bad = {"config_error", "auth_failed", "connection_error", "http_error", "not_entitled"}
    ok = live.get("status") not in bad and bars.get("status") not in bad
    print(f"\nSMOKE {'PASS' if ok else 'FAIL'}: "
          f"ws={live.get('status')} rest={bars.get('status')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sym = sys.argv[1].upper() if len(sys.argv) > 1 else "SPY"
    raise SystemExit(main(sym))
