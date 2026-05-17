"""Broker MCP server.

Per `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
Section 4.6 (L5/L6 — execution output + multi-horizon disposition) and
Section 7 Q5 (broker MCP read-only positions endpoint).

Three tools exposed to Claude Code:

  - `mcp__broker__get_positions(account_id_hash)`
        Returns the current portfolio snapshot.
  - `mcp__broker__get_account_summary(account_id_hash)`
        Returns cash + total-value snapshot.
  - `mcp__broker__poll_for_fills(account_id_hash, since_timestamp,
                                 previous_snapshot)`
        Returns detected fill events (diff against caller-provided
        previous snapshot + reconciled with broker transactions feed).

Read-only by design (Section 7 Q5). There is no `place_order` tool and
will not be at v0.1.

Adapter selection: `BROKER_PROVIDER` env var (default `schwab`). v0.1 only
registers `SchwabAdapter`; v0.5+ may add IBKR / Fidelity by extending the
`_ADAPTERS` registry below.

Connection info loaded from repo-root `.env` per the same convention as
`mcp__edgar` and `mcp__postgres`.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Walk: server.py → broker_mcp/ → mcp/ → src/ → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")

from adapters.base import BrokerAdapter  # noqa: E402
from diff_engine import (  # noqa: E402
    diff_positions,
    normalize_transactions,
    reconcile,
)
from schwab_adapter import SchwabAdapter  # noqa: E402

# Adapter registry. v0.5+ adds IBKR / Fidelity here.
_ADAPTERS: dict[str, type[BrokerAdapter]] = {
    "schwab": SchwabAdapter,
}

_adapter_instance: BrokerAdapter | None = None


def _adapter() -> BrokerAdapter:
    """Lazy adapter instantiation; cached for process lifetime."""
    global _adapter_instance
    if _adapter_instance is not None:
        return _adapter_instance
    provider = (os.environ.get("BROKER_PROVIDER") or "schwab").lower()
    cls = _ADAPTERS.get(provider)
    if cls is None:
        raise RuntimeError(
            f"Unknown BROKER_PROVIDER={provider!r}. "
            f"Registered: {sorted(_ADAPTERS)}"
        )
    _adapter_instance = cls()
    return _adapter_instance


mcp = FastMCP("broker")


@mcp.tool()
def get_positions(account_id_hash: str) -> dict:
    """Return current portfolio snapshot for the given account (read-only).

    Per Section 7 Q5: position state source is broker MCP, read-only.

    Args:
        account_id_hash: hashed brokerage account ID; the broker-specific
            adapter resolves this to the underlying account. Raw account
            numbers must NEVER be passed in.

    Returns:
        {
            "broker": "schwab",
            "account_id_hash": str,
            "as_of": ISO 8601 timestamp,
            "positions": [
                {
                    "ticker": str,
                    "shares_held": float,
                    "cost_basis": float,
                    "cost_basis_method": "FIFO",  # default per Section 8.1
                    "first_acquired": "YYYY-MM-DD" | "",  # empty if unknown
                    "last_updated": ISO 8601 timestamp,
                },
                ...
            ]
        }
    """
    adapter = _adapter()
    positions = adapter.get_positions(account_id_hash)
    return {
        "broker": adapter.broker_name,
        "account_id_hash": account_id_hash,
        "as_of": _now_iso(),
        "positions": list(positions),
    }


@mcp.tool()
def get_account_summary(account_id_hash: str) -> dict:
    """Return cash + total-value snapshot.

    Args:
        account_id_hash: hashed brokerage account ID.

    Returns:
        {
            "broker": "schwab",
            "account_id_hash": str,
            "cash_available": float,
            "total_value": float,
            "last_synced_at": ISO 8601 timestamp,
        }
    """
    adapter = _adapter()
    summary = adapter.get_account_summary(account_id_hash)
    return {
        "broker": adapter.broker_name,
        "account_id_hash": account_id_hash,
        "cash_available": summary["cash_available"],
        "total_value": summary["total_value"],
        "last_synced_at": summary["last_synced_at"],
    }


@mcp.tool()
def poll_for_fills(
    account_id_hash: str,
    since_timestamp: str,
    previous_snapshot: list[dict[str, Any]] | None = None,
) -> dict:
    """Detect fill events since `since_timestamp`.

    Per Section 4.6: auto-detect fills by diffing current positions
    against the last-stored snapshot, corroborated by the broker's
    transactions feed. Returns canonical FillEvent records ready for
    position_history INSERTs.

    Args:
        account_id_hash: hashed brokerage account ID.
        since_timestamp: ISO 8601 lower bound for transactions feed.
        previous_snapshot: previous positions snapshot (caller-supplied,
            typically loaded from `positions` table). If None, treats as
            empty (cold start — every current position becomes a synthetic
            BUY at first poll).

    Returns:
        {
            "broker": "schwab",
            "account_id_hash": str,
            "polled_at": ISO 8601 timestamp,
            "since_timestamp": str,
            "fill_events": [
                {
                    "ticker": str,
                    "event_type": "BUY" | "SELL" | "DIVIDEND" | "SPLIT" |
                                  "TRANSFER_IN" | "TRANSFER_OUT",
                    "event_date": "YYYY-MM-DD",
                    "shares_delta": float,
                    "price": float | null,
                    "detection_method": "broker_diff",
                },
                ...
            ]
        }
    """
    adapter = _adapter()
    current = adapter.get_positions(account_id_hash)
    previous = previous_snapshot or []

    snapshot_deltas = diff_positions(
        current=current,
        previous=[_coerce_position_record(p) for p in previous],
    )

    raw_txns = adapter.get_transactions(account_id_hash, since_timestamp)
    txn_events = normalize_transactions(raw_txns)

    fallback_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fill_events = reconcile(
        snapshot_deltas=snapshot_deltas,
        txn_events=txn_events,
        fallback_event_date=fallback_date,
    )

    return {
        "broker": adapter.broker_name,
        "account_id_hash": account_id_hash,
        "polled_at": _now_iso(),
        "since_timestamp": since_timestamp,
        "fill_events": list(fill_events),
    }


def _coerce_position_record(p: dict[str, Any]) -> dict[str, Any]:
    """Defensively coerce a caller-supplied previous_snapshot row.

    The MCP wire format is plain dicts; we only require ticker +
    shares_held for the diff. Missing fields default to safe values.
    """
    return {
        "ticker": p.get("ticker") or "",
        "shares_held": float(p.get("shares_held") or 0.0),
        "cost_basis": float(p.get("cost_basis") or 0.0),
        "cost_basis_method": p.get("cost_basis_method") or "FIFO",
        "first_acquired": p.get("first_acquired") or "",
        "last_updated": p.get("last_updated") or "",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    mcp.run()
