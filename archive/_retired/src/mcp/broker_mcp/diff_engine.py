"""Fill-detection diff engine.

Per `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
Section 4.6 (auto-detect fills via diff against last polled snapshot;
price from market_data quote at fill timestamp or broker-provided fill
price) + Section 7 Q5 lock.

Two complementary signals are reconciled into one canonical FillEvent
list:

  1. **Snapshot diff** — current positions vs last-stored positions row.
     Signed `shares_delta` per ticker; positive → BUY, negative → SELL.
     Detects splits as a special-case (positive delta with simultaneous
     cost-basis ratio change matching a clean integer multiplier).

  2. **Transactions feed** — broker-native transaction records since the
     last poll timestamp. Provides authoritative event_date, price, and
     event_type discrimination (BUY vs DIVIDEND vs SPLIT vs TRANSFER_IN).

When both signals agree, the transactions feed wins on price/date and the
diff confirms it. When they disagree (e.g., diff shows -100 shares but no
SELL transaction is listed), we emit the diff-based event with
`detection_method='broker_diff'` and the operator gets a reconciliation
warning at the app layer (out of scope for the MCP tool; surfaced via
/daily-monitor).

This module deliberately does NOT touch the database. The MCP layer is
read-only over broker; the application layer (postgres MCP via
position_history INSERT) writes events. Returning a list of FillEvent is
the boundary.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from adapters.base import FillEvent, PositionRecord


# Matches '1:10', '1 : 10', '2-for-1' (taking the leading digits via the
# digit-pair groups). Examples covered:
#   "STOCK SPLIT 1:10 REVERSE"   -> ("1", "10")
#   "FORWARD STOCK SPLIT 2 : 1"  -> ("2", "1")
#   "AAPL 4 FOR 1 SPLIT"         -> ("4", "1")
_SPLIT_RATIO_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?::|[-_]?for[-_]?|\s+)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# Float-precision floor for share-count deltas. Schwab's smallest tradable
# fractional share is 0.001 for fractional-share-eligible tickers; we use
# a six-orders-of-magnitude smaller floor so any genuine fractional fill is
# preserved while ulp-level catastrophic-cancellation residue from
# `current - previous` (typical magnitude ~1e-13 for share counts in the
# 100-1000 range) is treated as zero. Without this floor, two snapshots
# carrying the same logical share count but rounded differently in the JSON
# transport (e.g., 100.0001 vs 100.00010000000001) would emit a phantom
# fill event the reconciliation pipeline would chase as a real transaction.
SHARES_DELTA_EPSILON: float = 1e-6


def _parse_split_ratio(description: str) -> str | None:
    """Extract 'NUM:DEN' ratio from a broker SPLIT description, or None.

    Returns the ratio as a normalized 'NUM:DEN' string. Caller can split
    on ':' to get numerator/denominator.
    """
    if not description:
        return None
    m = _SPLIT_RATIO_RE.search(description)
    if not m:
        return None
    return f"{m.group(1)}:{m.group(2)}"


def diff_positions(
    *,
    current: list[PositionRecord],
    previous: list[PositionRecord],
) -> dict[str, float]:
    """Return signed share-count delta per ticker.

    Args:
        current: positions snapshot from broker (now).
        previous: positions snapshot from last poll (loaded by caller from
            `positions` table; may be empty on first poll).

    Returns:
        Mapping ticker → signed delta (positive = shares added, negative
        = shares removed). Tickers absent from one side use 0 for that side.
    """
    prev_map = {p["ticker"]: float(p["shares_held"]) for p in previous}
    curr_map = {p["ticker"]: float(p["shares_held"]) for p in current}

    deltas: dict[str, float] = {}
    for ticker in set(prev_map) | set(curr_map):
        delta = curr_map.get(ticker, 0.0) - prev_map.get(ticker, 0.0)
        # Tolerance-based zero check: subtraction of two near-equal floats
        # (catastrophic cancellation) can leave ulp-level residue even when
        # the broker logically reports the same share count both polls.
        # Direct `delta != 0.0` would emit phantom fills in that case;
        # SHARES_DELTA_EPSILON (1e-6) sits well below Schwab's 0.001 smallest
        # fractional share so genuine fractional-share fills are preserved.
        if abs(delta) >= SHARES_DELTA_EPSILON:
            deltas[ticker] = delta
    return deltas


def normalize_transactions(
    raw_txns: list[dict[str, Any]],
) -> list[FillEvent]:
    """Convert Schwab-shape transactions list → canonical FillEvent list.

    Schwab transaction record shape (abbreviated):
        {
          "type": "TRADE" | "DIVIDEND_OR_INTEREST" | "RECEIVE_AND_DELIVER",
          "tradeDate": "2026-04-15T13:30:00+0000",
          "transactionItem": {
            "instrument": {"symbol": "AAPL"},
            "amount": 50,                # shares (always positive)
            "instruction": "BUY" | "SELL",
            "price": 178.42,
          },
          ...
        }

    Args:
        raw_txns: broker-native list (from SchwabAdapter.get_transactions).

    Returns:
        FillEvent list, in transaction-feed order.
    """
    events: list[FillEvent] = []
    for txn in raw_txns:
        event_type = _classify_event_type(txn)
        if event_type is None:
            continue

        item = txn.get("transactionItem") or {}
        instrument = item.get("instrument") or {}
        symbol = instrument.get("symbol")
        if not symbol:
            continue

        amount = float(item.get("amount") or 0.0)
        instruction = (item.get("instruction") or "").upper()
        if event_type == "SELL" or instruction == "SELL":
            shares_delta = -abs(amount)
        else:
            shares_delta = abs(amount)

        trade_date = (txn.get("tradeDate") or txn.get("transactionDate") or "")[:10]

        price_raw = item.get("price")
        price = float(price_raw) if price_raw is not None else None

        event: FillEvent = FillEvent(
            ticker=symbol,
            event_type=event_type,
            event_date=trade_date,
            shares_delta=shares_delta,
            price=price,
            detection_method="broker_diff",
        )
        # SPLIT events: parse the ratio from the broker description so
        # downstream cost-basis adjustment can scale per-lot accurately.
        # Reference: Section 4.6 corporate-action handling; without ratio,
        # share-count change alone is ambiguous (3-for-1 forward looks like
        # +200% just as a 1-for-3 reverse looks like -67%).
        if event_type == "SPLIT":
            ratio = _parse_split_ratio(txn.get("description") or "")
            if ratio is not None:
                event["split_ratio"] = ratio
        events.append(event)
    return events


def reconcile(
    *,
    snapshot_deltas: dict[str, float],
    txn_events: list[FillEvent],
    fallback_event_date: str,
) -> list[FillEvent]:
    """Merge snapshot-diff signal with transactions-feed signal.

    Strategy:
      - Group txn_events by (ticker, sign(shares_delta)).
      - For each ticker with a snapshot delta, if the txn-events sum
        matches the snapshot delta within float-tolerance, emit those
        txn-events as-is.
      - If no txn-events for a ticker but snapshot delta is nonzero, emit
        a synthesized FillEvent with detection_method='broker_diff' and
        no price.
      - Snapshot delta and txn-event sum mismatch (e.g., partial fills,
        late settlement) → emit the txn-events AND a residual diff event;
        app-layer reconciler resolves.

    Args:
        snapshot_deltas: output of `diff_positions`.
        txn_events: output of `normalize_transactions`.
        fallback_event_date: ISO date 'YYYY-MM-DD' used when synthesizing
            a diff-only event (typically the current poll date).

    Returns:
        Merged FillEvent list ready for position_history INSERTs.
    """
    by_ticker: dict[str, list[FillEvent]] = defaultdict(list)
    for ev in txn_events:
        by_ticker[ev["ticker"]].append(ev)

    out: list[FillEvent] = []
    seen_tickers: set[str] = set()

    for ticker, delta in snapshot_deltas.items():
        seen_tickers.add(ticker)
        ticker_events = by_ticker.get(ticker, [])
        txn_sum = sum(ev["shares_delta"] for ev in ticker_events)

        out.extend(ticker_events)

        residual = delta - txn_sum
        if abs(residual) > 1e-6:
            out.append(
                FillEvent(
                    ticker=ticker,
                    event_type="BUY" if residual > 0 else "SELL",
                    event_date=fallback_event_date,
                    shares_delta=residual,
                    price=None,
                    detection_method="broker_diff",
                )
            )

    # Surface DIVIDEND / SPLIT / TRANSFER events that don't show up in
    # snapshot deltas (e.g., dividends never alter share count for cash
    # dividends) — they have shares_delta == 0 and slipped past the
    # by_ticker loop above only when the ticker had no other activity.
    for ticker, ticker_events in by_ticker.items():
        if ticker in seen_tickers:
            continue
        for ev in ticker_events:
            # Only forward events that the snapshot-delta path wouldn't
            # have caught (DIVIDEND, SPLIT, TRANSFER_IN/OUT).
            if ev["event_type"] in ("DIVIDEND", "SPLIT", "TRANSFER_IN", "TRANSFER_OUT"):
                out.append(ev)

    return out


def _classify_event_type(txn: dict[str, Any]) -> str | None:
    """Map a broker-native transaction record to a canonical event_type.

    Returns None if the record is not a position-affecting event we care
    about (e.g., margin interest, journal entry).
    """
    txn_type = (txn.get("type") or "").upper()
    item = txn.get("transactionItem") or {}
    instruction = (item.get("instruction") or "").upper()

    if txn_type == "TRADE":
        if instruction == "BUY":
            return "BUY"
        if instruction == "SELL":
            return "SELL"
        # BUY_TO_OPEN / SELL_TO_CLOSE etc. — treat by sign of amount.
        return "BUY" if instruction.startswith("BUY") else "SELL"
    if txn_type == "DIVIDEND_OR_INTEREST":
        return "DIVIDEND"
    if txn_type == "RECEIVE_AND_DELIVER":
        # Schwab uses this for both transfers and corporate-action stock
        # dividends / splits. Inspect description for split markers.
        desc = (txn.get("description") or "").upper()
        if "SPLIT" in desc:
            return "SPLIT"
        if "TRANSFER" in desc and "OUT" in desc:
            return "TRANSFER_OUT"
        return "TRANSFER_IN"
    return None
