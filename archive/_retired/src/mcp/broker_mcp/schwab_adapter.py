"""Schwab adapter for broker MCP.

Per `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
Section 4.6 (broker MCP architecture; first broker = Schwab) + Section 7 Q5
(read-only positions endpoint).

Schwab Trader API (Individual) — https://developer.schwab.com/products/trader-api--individual

Endpoints used (READ-ONLY scope only):
  - GET /trader/v1/accounts/{accountHash}/positions  (alias: positions field
        on /accounts response with `fields=positions`)
  - GET /trader/v1/accounts/{accountHash}/transactions
  - POST https://api.schwabapi.com/v1/oauth/token (token + refresh)

Authorization scope requested: `readonly`. The adapter NEVER calls trade-
execution endpoints; per Section 7 Q5 the system does not execute. If a
future operator wants execution they would explicitly add a different
adapter and the MCP server wiring would still not expose `place_order` —
that is deliberately out of scope for v0.1.

Rate-limit handling per Phase 4 Q9: exponential-backoff on HTTP 429
(0.5s, 1s, 2s, 4s; up to 4 retries). After exhaustion, raises
`BrokerRateLimitError` so the app layer can mark the positions row
degraded.

Account-id-hash mapping: Schwab returns an opaque `hashValue` per account
on `GET /trader/v1/accounts/accountNumbers`. We use that hash directly as
the `account_id_hash` argument; raw account numbers never enter or leave
this module.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from adapters.base import (
    AccountSummary,
    BrokerAdapter,
    BrokerAuthError,
    BrokerConfigError,
    BrokerRateLimitError,
    PositionRecord,
)
from oauth import (
    OAuthTokens,
    load_tokens,
    refresh_access_token,
    save_tokens,
)

_API_BASE = "https://api.schwabapi.com"
_TOKEN_URL = f"{_API_BASE}/v1/oauth/token"
_TRADER_BASE = f"{_API_BASE}/trader/v1"

_HTTP_TIMEOUT = 30.0
_BACKOFF_SCHEDULE_SECONDS = (0.5, 1.0, 2.0, 4.0)

# Cadence-floor caching (Section 7 Q3): B weekly, B' every 3d, C daily.
# We cache positions snapshots at the most permissive cadence (C = daily)
# so multiple watchlist names can share one fetch. Keyed by account_id_hash.
_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h
_positions_cache: dict[str, tuple[float, list[PositionRecord]]] = {}
_summary_cache: dict[str, tuple[float, AccountSummary]] = {}


class SchwabAdapter(BrokerAdapter):
    """Schwab Trader API integration.

    OAuth tokens loaded from `.env` via `oauth.load_tokens('SCHWAB')`.
    """

    def __init__(self) -> None:
        self._client_id = os.environ.get("SCHWAB_CLIENT_ID")
        self._client_secret = os.environ.get("SCHWAB_CLIENT_SECRET")
        if not (self._client_id and self._client_secret):
            raise BrokerConfigError(
                "SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET must be set in .env. "
                "Register an app at https://developer.schwab.com to obtain credentials."
            )
        # Per-instance lock guarding the token refresh path. Concurrent
        # callers can race on `_tokens()` after a token expiry; without a
        # lock both threads would mint new refresh requests and only one
        # would land in `.env`. Double-checked locking inside `_refresh()`
        # collapses concurrent refreshes to a single network call.
        self._refresh_lock = threading.Lock()

    @property
    def broker_name(self) -> str:
        return "schwab"

    # -------------------------------------------------------------------------
    # Token lifecycle
    # -------------------------------------------------------------------------

    def _tokens(self) -> OAuthTokens:
        """Return a non-expired token set, refreshing if necessary.

        Raises:
            BrokerAuthError: if no tokens are stored or refresh fails.
        """
        tokens = load_tokens("SCHWAB")
        if tokens is None:
            raise BrokerAuthError(
                "No Schwab OAuth tokens in .env. Run the authorize flow per "
                "src/mcp/broker_mcp/README.md (one-time setup)."
            )
        if tokens.is_expired():
            tokens = self._refresh(tokens)
        return tokens

    def _refresh(self, tokens: OAuthTokens) -> OAuthTokens:
        """Exchange refresh_token for a new access_token; persist.

        Thread-safe via double-checked locking: concurrent callers serialize
        on `self._refresh_lock`, and once inside the lock we re-load tokens
        from `.env` to detect refreshes already completed by a sibling
        thread (in which case we return those rather than burning a fresh
        refresh-token round-trip).
        """
        with self._refresh_lock:
            # Double-check: another thread may have already refreshed.
            current = load_tokens("SCHWAB")
            if current is not None and not current.is_expired():
                return current

            try:
                payload = refresh_access_token(
                    refresh_url=_TOKEN_URL,
                    client_id=self._client_id or "",
                    client_secret=self._client_secret or "",
                    refresh_token=tokens.refresh_token,
                )
            except httpx.HTTPStatusError as exc:
                raise BrokerAuthError(
                    f"Schwab token refresh failed (HTTP {exc.response.status_code}). "
                    "Refresh token may be expired (Schwab refresh tokens are 7 days). "
                    "Re-run the authorize flow."
                ) from exc

            new_tokens = OAuthTokens(
                access_token=payload["access_token"],
                # Schwab returns a new refresh_token on each refresh; fall back to
                # existing if the response omits it (defensive).
                refresh_token=payload.get("refresh_token", tokens.refresh_token),
                expires_at_epoch=int(time.time()) + int(payload.get("expires_in", 1800)),
            )
            save_tokens("SCHWAB", new_tokens)
            return new_tokens

    # -------------------------------------------------------------------------
    # HTTP plumbing — rate-limit-aware
    # -------------------------------------------------------------------------

    def _http_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a Schwab Trader endpoint with backoff on 429.

        Args:
            path: path under `_TRADER_BASE`, e.g., '/accounts/{hash}/positions'.
            params: optional query-string parameters.

        Raises:
            BrokerRateLimitError: after backoff schedule exhausted on 429.
            BrokerAuthError: on 401/403 after one auto-retry with refresh.
        """
        url = f"{_TRADER_BASE}{path}"
        last_exc: Exception | None = None
        # Track auth-retry state independently of the rate-limit attempt
        # counter. Without this split, a persistent 401/403 used to leak
        # past the auth-retry guard and surface as "rate limited" on
        # attempt >= 1 — the wrong exception class for ops triage.
        auth_retry_consumed = False

        for attempt, backoff in enumerate((0.0,) + _BACKOFF_SCHEDULE_SECONDS):
            if backoff:
                time.sleep(backoff)
            tokens = self._tokens()
            try:
                with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
                    resp = client.get(
                        url,
                        params=params,
                        headers={
                            "Authorization": f"Bearer {tokens.access_token}",
                            "Accept": "application/json",
                        },
                    )
                if resp.status_code == 429:
                    last_exc = BrokerRateLimitError(
                        f"Schwab rate-limited GET {path} (attempt {attempt + 1})"
                    )
                    continue
                if resp.status_code in (401, 403):
                    # One auth-retry budget per request: force-refresh once,
                    # then retry. Persistent auth failure → BrokerAuthError
                    # (NOT BrokerRateLimitError, which would mislead ops).
                    if not auth_retry_consumed:
                        auth_retry_consumed = True
                        self._refresh(tokens)
                        continue
                    raise BrokerAuthError(
                        f"Schwab returned {resp.status_code} on {path} after refresh."
                    )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as exc:
                last_exc = exc
                continue

        if isinstance(last_exc, BrokerRateLimitError):
            raise last_exc
        raise BrokerRateLimitError(
            f"Schwab GET {path} exhausted retries: {last_exc!r}"
        )

    # -------------------------------------------------------------------------
    # BrokerAdapter interface
    # -------------------------------------------------------------------------

    def get_positions(self, account_id_hash: str) -> list[PositionRecord]:
        """Fetch positions snapshot for an account.

        Cached at `_CACHE_TTL_SECONDS`; daily cadence is the most permissive
        floor across modes (Section 7 Q3). Callers that need fresher data
        should clear the cache first (not implemented in v0.1; restart MCP).
        """
        cached = _positions_cache.get(account_id_hash)
        if cached is not None and time.time() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

        raw = self._http_get(
            f"/accounts/{account_id_hash}",
            params={"fields": "positions"},
        )

        positions = _normalize_positions(raw)
        _positions_cache[account_id_hash] = (time.time(), positions)
        return positions

    def get_account_summary(self, account_id_hash: str) -> AccountSummary:
        """Fetch cash + total-value summary."""
        cached = _summary_cache.get(account_id_hash)
        if cached is not None and time.time() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

        raw = self._http_get(f"/accounts/{account_id_hash}")
        summary = _normalize_summary(raw)
        _summary_cache[account_id_hash] = (time.time(), summary)
        return summary

    def get_transactions(
        self, account_id_hash: str, since_timestamp: str
    ) -> list[dict[str, Any]]:
        """Fetch raw transactions since `since_timestamp` (ISO 8601).

        Schwab's transactions endpoint expects ISO-8601 with `Z` suffix.
        Returns the broker-native shape; `diff_engine.normalize_transactions`
        converts to canonical FillEvent.
        """
        # Schwab supports both `startDate` and `endDate` query params.
        params = {
            "startDate": since_timestamp,
            "endDate": _now_iso(),
            "types": "TRADE,DIVIDEND_OR_INTEREST,RECEIVE_AND_DELIVER",
        }
        raw = self._http_get(
            f"/accounts/{account_id_hash}/transactions",
            params=params,
        )
        if isinstance(raw, list):
            return raw
        return raw.get("transactions", []) or []


# -----------------------------------------------------------------------------
# Normalization helpers (broker-shape → canonical TypedDict shape)
# -----------------------------------------------------------------------------


def _normalize_positions(raw: dict[str, Any]) -> list[PositionRecord]:
    """Convert Schwab account+positions response → list[PositionRecord].

    Schwab response shape (abbreviated):
        {
          "securitiesAccount": {
            "positions": [
              {
                "instrument": {"symbol": "AAPL", ...},
                "longQuantity": 100,
                "averagePrice": 175.42,
                ...
              },
              ...
            ]
          }
        }
    """
    sec_acct = raw.get("securitiesAccount") or raw.get("aggregatedBalance") or {}
    positions_raw = sec_acct.get("positions", []) or []
    out: list[PositionRecord] = []
    for p in positions_raw:
        instrument = p.get("instrument") or {}
        symbol = instrument.get("symbol")
        if not symbol:
            continue
        long_qty = float(p.get("longQuantity") or 0.0)
        short_qty = float(p.get("shortQuantity") or 0.0)
        # Net signed shares; v0.1 supports long-only watchlist but record
        # actual broker state honestly.
        shares = long_qty - short_qty
        # Tolerance-based zero check: subtraction of long_qty - short_qty
        # can leave ulp-level residue when the position is logically zero
        # but JSON-encoded with tiny rounding differences (catastrophic
        # cancellation). Direct `== 0.0` would let those ghost positions
        # leak into the watchlist downstream. 1e-6 sits well below the
        # smallest tradable fractional share (Schwab: 0.001).
        if abs(shares) < 1e-6:
            continue
        out.append(
            PositionRecord(
                ticker=symbol,
                shares_held=shares,
                cost_basis=float(p.get("averagePrice") or 0.0),
                # Schwab does not expose tax-lot method on the positions
                # endpoint; default to FIFO per Section 8.1 deferral
                # (operator may override per-position via UI).
                cost_basis_method="FIFO",
                # Schwab does not return per-lot acquisition date on positions
                # endpoint; pass None so the application layer can detect
                # "unknown" and defer to position_history replay. Migration
                # 019 dropped NOT NULL on positions.first_acquired so this
                # is now writable.
                first_acquired=None,
                last_updated=_now_iso(),
            )
        )
    return out


def _normalize_summary(raw: dict[str, Any]) -> AccountSummary:
    sec_acct = raw.get("securitiesAccount") or {}
    initial = sec_acct.get("initialBalances") or {}
    current = sec_acct.get("currentBalances") or {}
    cash = float(
        current.get("cashAvailableForTrading")
        or current.get("cashBalance")
        or initial.get("cashBalance")
        or 0.0
    )
    total = float(
        current.get("liquidationValue")
        or current.get("equity")
        or initial.get("equity")
        or 0.0
    )
    return AccountSummary(
        cash_available=cash,
        total_value=total,
        last_synced_at=_now_iso(),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
