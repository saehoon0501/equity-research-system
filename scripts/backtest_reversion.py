#!/usr/bin/env python3
"""Standalone CLI backtest for mean-reversion-overlay (v0.4.0).

Usage:
  python scripts/backtest_reversion.py --ticker CRWD --start 2025-05-01 --end 2026-05-23
  python scripts/backtest_reversion.py --fixture tests/fixtures/crwd_prices_2025-03_2026-05.json

Output: a bin-transition table to stdout. Columns:
  anchor_date | bin | drawdown_pct | rsi_14 | bollinger_pos | ma_dist_pct | transition

`transition` is non-empty when the bin differs from the prior anchor (e.g. "MR_NEUTRAL→MR_OVERSOLD").

Bypasses the Agent() dispatch and the PostToolUse hook entirely — pure in-process
compute via `classify_reversion`. No DB writes, no envelope persistence.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from src.p10_reversion_overlay.bin_classifier import (
    classify_reversion,
    first_trading_day_of_month,
)


def _load_fixture_prices(fixture_path: str) -> list[dict]:
    """Load price-history JSON array from fixture file."""
    with open(fixture_path) as f:
        return json.load(f)


def _monthly_anchors(prices: list[dict], start: date, end: date) -> list[date]:
    """Return list of monthly anchor dates (first trading day of each month between start and end)."""
    anchors: list[date] = []
    months_seen: set[tuple[int, int]] = set()
    for p in prices:
        d = datetime.strptime(p["date"], "%Y-%m-%d").date()
        if d < start or d > end:
            continue
        key = (d.year, d.month)
        if key not in months_seen:
            months_seen.add(key)
            anchors.append(d)
    return anchors


def _replay(prices: list[dict], anchor: date) -> dict:
    """Classify reversion at one anchor using prices up to that point."""
    # Use prices STRICTLY BEFORE anchor (prior-month close convention).
    closes_before = [
        p["adj_close"]
        for p in prices
        if datetime.strptime(p["date"], "%Y-%m-%d").date() < anchor
    ]
    if len(closes_before) < 252:
        return {"bin": "MR_UNAVAILABLE", "components": None, "sub_signal_fires": None}
    return classify_reversion(closes_before)


def main() -> int:
    parser = argparse.ArgumentParser(prog="backtest_reversion")
    parser.add_argument("--ticker", type=str, help="Ticker (e.g., CRWD). With --fetch.")
    parser.add_argument("--start", type=str, help="Start date YYYY-MM-DD (inclusive).")
    parser.add_argument("--end", type=str, help="End date YYYY-MM-DD (inclusive).")
    parser.add_argument(
        "--fixture",
        type=str,
        help="Path to fixture JSON file (overrides --ticker/--start/--end fetch).",
    )
    args = parser.parse_args()

    if args.fixture:
        prices = _load_fixture_prices(args.fixture)
        if not prices:
            print("[backtest_reversion] empty fixture", file=sys.stderr)
            return 2
        start = datetime.strptime(prices[0]["date"], "%Y-%m-%d").date()
        end = datetime.strptime(prices[-1]["date"], "%Y-%m-%d").date()
    else:
        # v0.4.0: no MCP integration — operator must use --fixture for now.
        # v0.4.1 can add live mcp__market_data__get_prices integration.
        print(
            "[backtest_reversion] v0.4.0 requires --fixture path; "
            "live MCP fetch deferred to v0.4.1",
            file=sys.stderr,
        )
        return 2

    # Override start/end if user provided
    if args.start:
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
    if args.end:
        end = datetime.strptime(args.end, "%Y-%m-%d").date()

    anchors = _monthly_anchors(prices, start, end)

    print(
        f"# Backtest: {args.ticker or 'fixture'} | "
        f"anchors: {len(anchors)} ({start} → {end})"
    )
    print(
        "anchor_date | bin            | drawdown_pct | rsi_14  | bollinger_pos | ma_dist_pct | transition"
    )
    print("-" * 120)

    prior_bin: str | None = None
    for anchor in anchors:
        result = _replay(prices, anchor)
        bin_ = result["bin"]
        components = result.get("components") or {}
        transition = ""
        if prior_bin is not None and prior_bin != bin_:
            transition = f"{prior_bin}→{bin_}"
        dd = components.get("drawdown_from_252d_high_pct")
        rsi = components.get("rsi_14")
        bb = components.get("bollinger_band_position")
        mad = components.get("ma_distance_200d_pct")
        dd_s = f"{dd:>11.2f}" if dd is not None else "         n/a"
        rsi_s = f"{rsi:>7.2f}" if rsi is not None else "    n/a"
        bb_s = f"{bb:>13.3f}" if bb is not None else "          n/a"
        mad_s = f"{mad:>11.2f}" if mad is not None else "         n/a"
        print(
            f"{anchor.isoformat()} | {bin_:14s} | {dd_s} | {rsi_s} | {bb_s} | {mad_s} | {transition}"
        )
        prior_bin = bin_

    return 0


if __name__ == "__main__":
    sys.exit(main())
