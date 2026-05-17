"""Abstract base class for broker adapters.

Per `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
Section 4.6 (broker MCP architecture) + Section 7 Q5 (read-only scope).

The MCP server (`../server.py`) talks to one `BrokerAdapter` instance picked
at startup based on `BROKER_PROVIDER` env var. v0.1 only registers
`SchwabAdapter`; v0.5+ may register IBKR / Fidelity adapters here without
changing the server-side tool schema.

Schema-discipline goal: the three return-types (PositionRecord,
AccountSummary, FillEvent) are the ONLY shapes the MCP server emits to
Claude Code. Adapters MUST normalize broker-specific JSON into these dicts;
no broker-specific fields leak through.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypedDict


class PositionRecord(TypedDict):
    """One row returned by `mcp__broker__get_positions`.

    Mirrors the `positions` table contract in
    `db/migrations/007_v3_watchlist_positions.sql` (with migration 019
    making `first_acquired` nullable).
    """

    ticker: str
    shares_held: float
    cost_basis: float
    cost_basis_method: str  # 'FIFO' | 'LIFO' | 'SPECIFIC_LOT' | 'AVERAGE'
    # NULL when the broker positions endpoint does not expose per-lot
    # acquisition date (e.g., Schwab). Backfilled by replaying
    # position_history once a fill is observed. Migration 019 dropped
    # NOT NULL on the column to permit this. Long-term-capital-gains
    # math (1y holding) defers until the column is backfilled — callers
    # SHOULD treat None as "unknown holding period" and conservatively
    # assume short-term tax treatment.
    first_acquired: str | None  # ISO date 'YYYY-MM-DD' or None
    last_updated: str  # ISO 8601 timestamp


class AccountSummary(TypedDict):
    """Returned by `mcp__broker__get_account_summary`."""

    cash_available: float
    total_value: float
    last_synced_at: str  # ISO 8601 timestamp


class FillEvent(TypedDict, total=False):
    """One detected fill / corp-action event.

    Mirrors the `position_history` table contract per Section 4.6 +
    `db/migrations/007_v3_watchlist_positions.sql`.

    Required keys: ticker, event_type, event_date, shares_delta, price,
    detection_method.

    Optional keys (present only on certain event_types):
        split_ratio: tuple-encoded as 'NUM:DEN' string (e.g., '1:10' for a
            1-for-10 reverse split, '2:1' for a 2-for-1 forward split).
            Populated only when event_type == 'SPLIT' AND the broker
            description contains a parsable ratio.
    """

    ticker: str
    event_type: str  # 'BUY' | 'SELL' | 'DIVIDEND' | 'SPLIT' | 'TRANSFER_IN' | 'TRANSFER_OUT'
    event_date: str  # ISO date 'YYYY-MM-DD'
    shares_delta: float
    price: float | None
    detection_method: str  # 'broker_diff' | 'manual' | 'corp_action_feed'
    # Optional — only populated for SPLIT events when ratio can be parsed
    # from the broker description (e.g., '1:10' reverse, '2:1' forward).
    split_ratio: str | None


class BrokerAdapter(ABC):
    """Abstract base for broker integrations.

    Concrete implementations (e.g., `SchwabAdapter`) handle:
      - OAuth 2.0 token flow (read-only scope)
      - Token refresh
      - Rate-limit backoff (per Phase 4 Q9 default; degraded-broker flag on 429)
      - JSON normalization to the TypedDicts above

    Per Section 7 Q5: READ-ONLY. No `place_order` or other write methods on
    this interface — execution is deliberately not in scope.
    """

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Short broker identifier; lands in `positions.broker` column."""

    @abstractmethod
    def get_positions(self, account_id_hash: str) -> list[PositionRecord]:
        """Return current portfolio snapshot for the given account.

        Args:
            account_id_hash: hashed brokerage account ID; the adapter is
                responsible for resolving this to the underlying account
                (broker-specific account-encrypted-id mapping). The plain
                account number is NEVER passed in or out of the MCP.

        Returns:
            List of `PositionRecord`. Empty list if account has no positions.

        Raises:
            BrokerRateLimitError: if the broker rate-limited (caller sets
                degraded-broker flag in app layer).
            BrokerAuthError: if the OAuth token is invalid or refresh fails.
        """

    @abstractmethod
    def get_account_summary(self, account_id_hash: str) -> AccountSummary:
        """Return cash + total-value snapshot for the account."""

    @abstractmethod
    def get_transactions(
        self, account_id_hash: str, since_timestamp: str
    ) -> list[dict[str, Any]]:
        """Return broker-native transactions since `since_timestamp`.

        Used by `diff_engine.py` as a corroborating signal alongside the
        positions-snapshot diff. Adapter returns the broker's native
        transaction-record shape (NOT yet normalized to `FillEvent`); the
        diff engine reconciles snapshot-diff vs transaction-feed and emits
        the canonical `FillEvent` list.

        Args:
            since_timestamp: ISO 8601; lower bound (inclusive).
        """


class BrokerError(Exception):
    """Base class for broker-adapter errors."""


class BrokerAuthError(BrokerError):
    """OAuth token invalid or refresh failed; operator must re-auth."""


class BrokerRateLimitError(BrokerError):
    """Broker rate-limited the request; caller marks position degraded.

    Per Phase 4 Q9 default: when this fires, the app layer SHOULD write a
    `degraded_broker=true` indicator alongside the positions row so /sizing
    and /entry-check can apply staleness penalties.
    """


class BrokerConfigError(BrokerError):
    """Required config (env var, OAuth client id/secret) is missing."""
