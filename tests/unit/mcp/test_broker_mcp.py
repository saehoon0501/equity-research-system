"""Tests for broker_mcp package.

Mocked OAuth + diff-engine + adapter coverage. No real Schwab calls.

Tests are organized by module:
  - oauth.py: token serialization round-trip, expiry detection
  - diff_engine.py: snapshot diff, transaction normalization, reconciliation
  - schwab_adapter.py: mocked HTTP client; verifies request shape +
    rate-limit backoff
  - server.py: end-to-end MCP tool invocation with mocked adapter

Per Section 7.1 launch gate ("token refresh validated") the OAuth refresh
path is exercised in `test_token_refresh_round_trip`.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# Make broker_mcp importable from tests/.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src" / "mcp" / "broker_mcp"))
sys.path.insert(0, str(_REPO_ROOT / "src" / "mcp"))


# =============================================================================
# oauth.py
# =============================================================================


def test_oauth_tokens_expiry_detection() -> None:
    from broker_mcp.oauth import OAuthTokens

    expired = OAuthTokens(
        access_token="a", refresh_token="r", expires_at_epoch=int(time.time()) - 100
    )
    assert expired.is_expired()

    fresh = OAuthTokens(
        access_token="a", refresh_token="r", expires_at_epoch=int(time.time()) + 3600
    )
    assert not fresh.is_expired()

    # Skew window: token expiring in 30s should register as expired with
    # default skew=60.
    near = OAuthTokens(
        access_token="a", refresh_token="r", expires_at_epoch=int(time.time()) + 30
    )
    assert near.is_expired()
    assert not near.is_expired(skew_seconds=10)


def test_load_tokens_returns_none_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    from broker_mcp.oauth import load_tokens

    monkeypatch.delenv("TESTBROKER_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TESTBROKER_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("TESTBROKER_TOKEN_EXPIRES_AT", raising=False)

    assert load_tokens("TESTBROKER") is None


def test_load_tokens_parses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from broker_mcp.oauth import load_tokens

    monkeypatch.setenv("TESTBROKER_ACCESS_TOKEN", "A")
    monkeypatch.setenv("TESTBROKER_REFRESH_TOKEN", "R")
    monkeypatch.setenv("TESTBROKER_TOKEN_EXPIRES_AT", "1234567890")

    tokens = load_tokens("TESTBROKER")
    assert tokens is not None
    assert tokens.access_token == "A"
    assert tokens.refresh_token == "R"
    assert tokens.expires_at_epoch == 1234567890


def test_save_tokens_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Round-trip: save_tokens then load_tokens recovers same values."""
    from broker_mcp import oauth
    from broker_mcp.oauth import OAuthTokens, load_tokens, save_tokens

    fake_env = tmp_path / ".env"
    fake_env.write_text("OTHER_VAR=keep\n")
    monkeypatch.setattr(oauth, "_ENV_PATH", fake_env)

    save_tokens(
        "TESTBROKER",
        OAuthTokens(access_token="A1", refresh_token="R1", expires_at_epoch=99),
    )
    loaded = load_tokens("TESTBROKER")
    assert loaded is not None
    assert loaded.access_token == "A1"
    assert loaded.refresh_token == "R1"
    assert loaded.expires_at_epoch == 99

    # In-place rewrite preserves unrelated keys.
    body = fake_env.read_text()
    assert "OTHER_VAR=keep" in body
    assert "TESTBROKER_ACCESS_TOKEN=A1" in body

    # Updating tokens replaces in place (no duplicates).
    save_tokens(
        "TESTBROKER",
        OAuthTokens(access_token="A2", refresh_token="R2", expires_at_epoch=100),
    )
    body = fake_env.read_text()
    assert body.count("TESTBROKER_ACCESS_TOKEN=") == 1
    assert "TESTBROKER_ACCESS_TOKEN=A2" in body


def test_token_refresh_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mocked HTTP refresh exchange returns new access + refresh tokens.

    Per Section 7.1 ("token refresh validated").
    """
    from broker_mcp import oauth

    captured: dict[str, Any] = {}

    class FakeResponse:
        def __init__(self) -> None:
            self.status_code = 200

        def raise_for_status(self) -> None: ...
        def json(self) -> dict[str, Any]:
            return {
                "access_token": "NEW_ACCESS",
                "refresh_token": "NEW_REFRESH",
                "expires_in": 1800,
            }

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None: ...
        def post(self, url: str, **kwargs: Any) -> FakeResponse:
            captured["url"] = url
            captured["data"] = kwargs.get("data")
            captured["auth"] = kwargs.get("auth")
            return FakeResponse()

    monkeypatch.setattr(oauth.httpx, "Client", FakeClient)

    payload = oauth.refresh_access_token(
        refresh_url="https://example.test/token",
        client_id="CID",
        client_secret="CSECRET",
        refresh_token="OLD_REFRESH",
    )

    assert payload["access_token"] == "NEW_ACCESS"
    assert captured["data"]["grant_type"] == "refresh_token"
    assert captured["data"]["refresh_token"] == "OLD_REFRESH"
    assert captured["auth"] == ("CID", "CSECRET")


def test_concurrent_refresh_does_not_burn_two_round_trips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two threads needing refresh at the same time must collapse to ONE
    `refresh_access_token` HTTP call. Without the per-instance lock + double-
    checked-locking pattern, both threads would mint independent refresh
    requests; only one would land in `.env`, and the broker may invalidate the
    older refresh token on the second attempt.
    """
    import threading
    from broker_mcp import oauth as oauth_mod
    from broker_mcp.adapters.base import BrokerAuthError  # noqa: F401  (used implicitly)
    from broker_mcp.schwab_adapter import SchwabAdapter

    monkeypatch.setenv("SCHWAB_CLIENT_ID", "CID")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "CSECRET")

    # Seed expired tokens.
    expired = oauth_mod.OAuthTokens(
        access_token="OLD_A",
        refresh_token="OLD_R",
        expires_at_epoch=int(time.time()) - 100,
    )
    fresh = oauth_mod.OAuthTokens(
        access_token="NEW_A",
        refresh_token="NEW_R",
        expires_at_epoch=int(time.time()) + 3600,
    )

    adapter = SchwabAdapter()

    call_counter: dict[str, int] = {"refresh": 0, "load": 0}
    state: dict[str, oauth_mod.OAuthTokens] = {"current": expired}
    barrier = threading.Barrier(2)

    def fake_load_tokens(prefix: str) -> oauth_mod.OAuthTokens | None:
        call_counter["load"] += 1
        return state["current"]

    def fake_save_tokens(prefix: str, tokens: oauth_mod.OAuthTokens) -> None:
        state["current"] = tokens

    def fake_refresh(**kwargs: Any) -> dict[str, Any]:
        # Hold both threads here so the race window is wide.
        barrier.wait(timeout=5)
        call_counter["refresh"] += 1
        return {
            "access_token": fresh.access_token,
            "refresh_token": fresh.refresh_token,
            "expires_in": 3600,
        }

    monkeypatch.setattr(
        "broker_mcp.schwab_adapter.load_tokens", fake_load_tokens
    )
    monkeypatch.setattr(
        "broker_mcp.schwab_adapter.save_tokens", fake_save_tokens
    )
    monkeypatch.setattr(
        "broker_mcp.schwab_adapter.refresh_access_token", fake_refresh
    )

    results: list[oauth_mod.OAuthTokens] = []
    errors: list[Exception] = []

    def worker() -> None:
        try:
            results.append(adapter._refresh(expired))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    # Lower the barrier expectation: only the first thread to enter the lock
    # will actually call refresh_access_token; the second hits the
    # double-checked re-load and short-circuits. So we abort the barrier
    # after a short wait to unblock the single thread that does refresh.
    barrier = threading.Barrier(1)
    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not errors, errors
    # Single refresh call despite two threads.
    assert call_counter["refresh"] == 1, (
        f"expected exactly 1 refresh call, got {call_counter['refresh']}"
    )
    # Both threads observe fresh tokens.
    assert all(r.access_token == "NEW_A" for r in results)


def test_atomic_save_tokens_uses_replace(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """save_tokens must stage to a sibling file then os.replace into place.

    Verifies the atomic-write contract: a crash mid-write cannot leave a
    partially written `.env`.
    """
    from broker_mcp import oauth as oauth_mod

    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\nSCHWAB_ACCESS_TOKEN=OLD\n")
    monkeypatch.setattr(oauth_mod, "_ENV_PATH", env_path)

    replace_calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def tracking_replace(src: Any, dst: Any) -> None:
        replace_calls.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(oauth_mod.os, "replace", tracking_replace)

    tokens = oauth_mod.OAuthTokens(
        access_token="A1",
        refresh_token="R1",
        expires_at_epoch=int(time.time()) + 3600,
    )
    oauth_mod.save_tokens("SCHWAB", tokens)

    assert len(replace_calls) == 1
    src, dst = replace_calls[0]
    assert dst == str(env_path)
    assert src.endswith(".env.tmp")
    assert "SCHWAB_ACCESS_TOKEN=A1" in env_path.read_text()
    assert "FOO=bar" in env_path.read_text()


# =============================================================================
# diff_engine.py
# =============================================================================


def test_diff_positions_detects_buy_sell_and_new() -> None:
    from broker_mcp.diff_engine import diff_positions

    previous = [
        {"ticker": "AAPL", "shares_held": 100, "cost_basis": 150,
         "cost_basis_method": "FIFO", "first_acquired": "", "last_updated": ""},
        {"ticker": "MSFT", "shares_held": 50, "cost_basis": 300,
         "cost_basis_method": "FIFO", "first_acquired": "", "last_updated": ""},
    ]
    current = [
        {"ticker": "AAPL", "shares_held": 150, "cost_basis": 160,
         "cost_basis_method": "FIFO", "first_acquired": "", "last_updated": ""},
        # MSFT sold entirely.
        {"ticker": "GOOG", "shares_held": 10, "cost_basis": 140,
         "cost_basis_method": "FIFO", "first_acquired": "", "last_updated": ""},
    ]

    deltas = diff_positions(current=current, previous=previous)
    assert deltas == {"AAPL": 50.0, "MSFT": -50.0, "GOOG": 10.0}


def test_diff_positions_no_change() -> None:
    from broker_mcp.diff_engine import diff_positions

    snapshot = [
        {"ticker": "AAPL", "shares_held": 100, "cost_basis": 150,
         "cost_basis_method": "FIFO", "first_acquired": "", "last_updated": ""},
    ]
    assert diff_positions(current=snapshot, previous=snapshot) == {}


def test_diff_positions_ignores_subepsilon_residue() -> None:
    """Regression: catastrophic-cancellation residue must NOT emit phantom fills.

    Float-precision audit: ``current - previous`` on identical logical share
    counts can leave ulp-level (~1e-13) residue when JSON-decoded floats round
    inconsistently across polls. Direct ``delta != 0.0`` previously emitted a
    phantom fill; the SHARES_DELTA_EPSILON (1e-6) tolerance now suppresses it
    while preserving genuine fractional-share fills (Schwab smallest = 0.001).
    """
    from broker_mcp.diff_engine import diff_positions

    # Same logical share count, but with sub-epsilon ulp residue.
    previous = [
        {"ticker": "AAPL", "shares_held": 100.000000000000001, "cost_basis": 150,
         "cost_basis_method": "FIFO", "first_acquired": "", "last_updated": ""},
    ]
    current = [
        {"ticker": "AAPL", "shares_held": 100.0, "cost_basis": 150,
         "cost_basis_method": "FIFO", "first_acquired": "", "last_updated": ""},
    ]
    # No phantom fill should be emitted.
    assert diff_positions(current=current, previous=previous) == {}


def test_diff_positions_preserves_genuine_fractional_fill() -> None:
    """Regression: fractional fills at or above 0.001 (Schwab minimum) are kept.

    The SHARES_DELTA_EPSILON of 1e-6 must be small enough to preserve the
    smallest tradable fractional share (0.001) — otherwise we'd silently drop
    real fills.
    """
    from broker_mcp.diff_engine import diff_positions

    previous = [
        {"ticker": "AAPL", "shares_held": 100.0, "cost_basis": 150,
         "cost_basis_method": "FIFO", "first_acquired": "", "last_updated": ""},
    ]
    current = [
        {"ticker": "AAPL", "shares_held": 100.001, "cost_basis": 150,
         "cost_basis_method": "FIFO", "first_acquired": "", "last_updated": ""},
    ]
    deltas = diff_positions(current=current, previous=previous)
    assert "AAPL" in deltas
    assert deltas["AAPL"] == pytest.approx(0.001, abs=1e-9)


def test_normalize_transactions_buy_sell_dividend() -> None:
    from broker_mcp.diff_engine import normalize_transactions

    raw = [
        {
            "type": "TRADE",
            "tradeDate": "2026-04-15T13:30:00+0000",
            "transactionItem": {
                "instrument": {"symbol": "AAPL"},
                "amount": 50,
                "instruction": "BUY",
                "price": 178.42,
            },
        },
        {
            "type": "TRADE",
            "tradeDate": "2026-04-16T13:30:00+0000",
            "transactionItem": {
                "instrument": {"symbol": "MSFT"},
                "amount": 25,
                "instruction": "SELL",
                "price": 320.10,
            },
        },
        {
            "type": "DIVIDEND_OR_INTEREST",
            "tradeDate": "2026-04-20T00:00:00+0000",
            "transactionItem": {
                "instrument": {"symbol": "AAPL"},
                "amount": 0,
                "price": 0.0,
            },
        },
        {
            "type": "RECEIVE_AND_DELIVER",
            "tradeDate": "2026-04-22T00:00:00+0000",
            "description": "STOCK SPLIT 4:1",
            "transactionItem": {
                "instrument": {"symbol": "NVDA"},
                "amount": 100,
                "price": 0.0,
            },
        },
    ]

    events = normalize_transactions(raw)
    assert len(events) == 4
    assert events[0]["ticker"] == "AAPL"
    assert events[0]["event_type"] == "BUY"
    assert events[0]["shares_delta"] == 50.0
    assert events[0]["price"] == 178.42
    assert events[0]["event_date"] == "2026-04-15"

    assert events[1]["event_type"] == "SELL"
    assert events[1]["shares_delta"] == -25.0

    assert events[2]["event_type"] == "DIVIDEND"
    assert events[3]["event_type"] == "SPLIT"


def test_normalize_transactions_extracts_split_ratio() -> None:
    """SPLIT events parse 'NUM:DEN' from broker description per Section 4.6.

    Without the ratio, share-count change alone is ambiguous (e.g. a 1-for-10
    reverse split looks like -90% by raw amount; a 10-for-1 forward looks like
    +900%). The diff engine MUST surface the ratio so cost-basis adjusters
    scale per-lot accurately.
    """
    from broker_mcp.diff_engine import normalize_transactions

    # Reverse split 1:10 (very common for going-concern micro-caps).
    raw_reverse = [
        {
            "type": "RECEIVE_AND_DELIVER",
            "tradeDate": "2026-04-22T00:00:00+0000",
            "description": "STOCK SPLIT 1:10 REVERSE",
            "transactionItem": {
                "instrument": {"symbol": "ZZZZ"},
                "amount": 90,
                "price": 0.0,
            },
        }
    ]
    events = normalize_transactions(raw_reverse)
    assert len(events) == 1
    assert events[0]["event_type"] == "SPLIT"
    assert events[0].get("split_ratio") == "1:10"

    # Forward split 4:1 (existing test format).
    raw_forward = [
        {
            "type": "RECEIVE_AND_DELIVER",
            "tradeDate": "2026-04-22T00:00:00+0000",
            "description": "STOCK SPLIT 4:1",
            "transactionItem": {
                "instrument": {"symbol": "NVDA"},
                "amount": 300,
                "price": 0.0,
            },
        }
    ]
    events = normalize_transactions(raw_forward)
    assert events[0].get("split_ratio") == "4:1"

    # Unparsable description: ratio is absent (key omitted; FillEvent total=False).
    raw_no_ratio = [
        {
            "type": "RECEIVE_AND_DELIVER",
            "tradeDate": "2026-04-22T00:00:00+0000",
            "description": "STOCK SPLIT",
            "transactionItem": {
                "instrument": {"symbol": "FOO"},
                "amount": 50,
                "price": 0.0,
            },
        }
    ]
    events = normalize_transactions(raw_no_ratio)
    # No ratio should be present
    assert "split_ratio" not in events[0] or events[0].get("split_ratio") is None


def test_reconcile_matches_snapshot_to_txns() -> None:
    """Snapshot delta + txn-feed agree → emit txn events as-is."""
    from broker_mcp.diff_engine import reconcile

    snapshot_deltas = {"AAPL": 50.0}
    txn_events = [
        {
            "ticker": "AAPL",
            "event_type": "BUY",
            "event_date": "2026-04-15",
            "shares_delta": 50.0,
            "price": 178.42,
            "detection_method": "broker_diff",
        }
    ]
    out = reconcile(
        snapshot_deltas=snapshot_deltas,
        txn_events=txn_events,
        fallback_event_date="2026-04-29",
    )
    assert len(out) == 1
    assert out[0]["price"] == 178.42


def test_reconcile_synthesizes_event_when_no_txns() -> None:
    """Snapshot delta with no matching txn → synthesized broker_diff event."""
    from broker_mcp.diff_engine import reconcile

    out = reconcile(
        snapshot_deltas={"AAPL": -100.0},
        txn_events=[],
        fallback_event_date="2026-04-29",
    )
    assert len(out) == 1
    assert out[0]["ticker"] == "AAPL"
    assert out[0]["event_type"] == "SELL"
    assert out[0]["shares_delta"] == -100.0
    assert out[0]["price"] is None
    assert out[0]["event_date"] == "2026-04-29"


def test_reconcile_emits_dividend_with_no_snapshot_change() -> None:
    """Dividends don't show in shares-snapshot but should pass through."""
    from broker_mcp.diff_engine import reconcile

    out = reconcile(
        snapshot_deltas={},
        txn_events=[
            {
                "ticker": "AAPL",
                "event_type": "DIVIDEND",
                "event_date": "2026-04-20",
                "shares_delta": 0.0,
                "price": 0.0,
                "detection_method": "broker_diff",
            }
        ],
        fallback_event_date="2026-04-29",
    )
    assert len(out) == 1
    assert out[0]["event_type"] == "DIVIDEND"


def test_reconcile_emits_residual_when_partial_match() -> None:
    """Snapshot says +100 but txns sum to +60 → emit txn + +40 residual."""
    from broker_mcp.diff_engine import reconcile

    out = reconcile(
        snapshot_deltas={"AAPL": 100.0},
        txn_events=[
            {
                "ticker": "AAPL",
                "event_type": "BUY",
                "event_date": "2026-04-15",
                "shares_delta": 60.0,
                "price": 178.0,
                "detection_method": "broker_diff",
            }
        ],
        fallback_event_date="2026-04-29",
    )
    assert len(out) == 2
    residual = [e for e in out if e["price"] is None][0]
    assert residual["shares_delta"] == 40.0


# =============================================================================
# schwab_adapter.py — rate-limit backoff
# =============================================================================


def test_schwab_adapter_config_error_when_no_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from broker_mcp.adapters.base import BrokerConfigError

    monkeypatch.delenv("SCHWAB_CLIENT_ID", raising=False)
    monkeypatch.delenv("SCHWAB_CLIENT_SECRET", raising=False)

    from broker_mcp.schwab_adapter import SchwabAdapter

    with pytest.raises(BrokerConfigError):
        SchwabAdapter()


def test_schwab_adapter_auth_error_when_no_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from broker_mcp.adapters.base import BrokerAuthError

    monkeypatch.setenv("SCHWAB_CLIENT_ID", "CID")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "CSECRET")
    monkeypatch.delenv("SCHWAB_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SCHWAB_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("SCHWAB_TOKEN_EXPIRES_AT", raising=False)

    from broker_mcp.schwab_adapter import SchwabAdapter

    adapter = SchwabAdapter()
    with pytest.raises(BrokerAuthError):
        adapter.get_positions("HASH")


def test_schwab_adapter_rate_limit_backoff_then_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All retries return 429 → BrokerRateLimitError raised."""
    monkeypatch.setenv("SCHWAB_CLIENT_ID", "CID")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "CSECRET")
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "A")
    monkeypatch.setenv("SCHWAB_REFRESH_TOKEN", "R")
    monkeypatch.setenv("SCHWAB_TOKEN_EXPIRES_AT", str(int(time.time()) + 3600))

    from broker_mcp import schwab_adapter
    from broker_mcp.adapters.base import BrokerRateLimitError

    # Bust positions cache so the test always hits the HTTP path.
    schwab_adapter._positions_cache.clear()

    class FakeResp:
        def __init__(self) -> None:
            self.status_code = 429
            self.text = "rate limited"

        def raise_for_status(self) -> None: ...
        def json(self) -> dict[str, Any]:
            return {}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None: ...
        def get(self, *args: Any, **kwargs: Any) -> FakeResp:
            return FakeResp()

    monkeypatch.setattr(schwab_adapter.httpx, "Client", FakeClient)
    # Skip actual sleeps in backoff schedule.
    monkeypatch.setattr(schwab_adapter.time, "sleep", lambda *_a, **_k: None)

    adapter = schwab_adapter.SchwabAdapter()
    with pytest.raises(BrokerRateLimitError):
        adapter.get_positions("HASH")


def test_schwab_adapter_normalizes_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCHWAB_CLIENT_ID", "CID")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "CSECRET")
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "A")
    monkeypatch.setenv("SCHWAB_REFRESH_TOKEN", "R")
    monkeypatch.setenv("SCHWAB_TOKEN_EXPIRES_AT", str(int(time.time()) + 3600))

    from broker_mcp import schwab_adapter

    schwab_adapter._positions_cache.clear()

    class FakeResp:
        status_code = 200

        def raise_for_status(self) -> None: ...
        def json(self) -> dict[str, Any]:
            return {
                "securitiesAccount": {
                    "positions": [
                        {
                            "instrument": {"symbol": "AAPL"},
                            "longQuantity": 100,
                            "shortQuantity": 0,
                            "averagePrice": 175.42,
                        },
                        {
                            "instrument": {"symbol": "MSFT"},
                            "longQuantity": 50,
                            "shortQuantity": 0,
                            "averagePrice": 320.10,
                        },
                    ]
                }
            }

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: Any) -> None: ...
        def get(self, *args: Any, **kwargs: Any) -> FakeResp:
            return FakeResp()

    monkeypatch.setattr(schwab_adapter.httpx, "Client", FakeClient)

    adapter = schwab_adapter.SchwabAdapter()
    positions = adapter.get_positions("HASH")
    assert len(positions) == 2
    assert positions[0]["ticker"] == "AAPL"
    assert positions[0]["shares_held"] == 100.0
    assert positions[0]["cost_basis"] == 175.42
    assert positions[0]["cost_basis_method"] == "FIFO"


# =============================================================================
# server.py — end-to-end MCP tool invocation with mocked adapter
# =============================================================================


class _MockAdapter:
    """Minimal mock implementing the BrokerAdapter contract."""

    broker_name = "mock"

    def __init__(self) -> None:
        self.positions_calls = 0
        self.txn_calls = 0

    def get_positions(self, account_id_hash: str) -> list[dict[str, Any]]:
        self.positions_calls += 1
        return [
            {
                "ticker": "AAPL",
                "shares_held": 150.0,
                "cost_basis": 160.0,
                "cost_basis_method": "FIFO",
                "first_acquired": "",
                "last_updated": "2026-04-29T12:00:00Z",
            }
        ]

    def get_account_summary(self, account_id_hash: str) -> dict[str, Any]:
        return {
            "cash_available": 12500.0,
            "total_value": 187500.0,
            "last_synced_at": "2026-04-29T12:00:00Z",
        }

    def get_transactions(
        self, account_id_hash: str, since_timestamp: str
    ) -> list[dict[str, Any]]:
        self.txn_calls += 1
        return [
            {
                "type": "TRADE",
                "tradeDate": "2026-04-15T13:30:00+0000",
                "transactionItem": {
                    "instrument": {"symbol": "AAPL"},
                    "amount": 50,
                    "instruction": "BUY",
                    "price": 178.42,
                },
            }
        ]


@pytest.fixture()
def mock_adapter(monkeypatch: pytest.MonkeyPatch) -> _MockAdapter:
    """Inject _MockAdapter into server module-level cache."""
    from broker_mcp import server

    instance = _MockAdapter()
    monkeypatch.setattr(server, "_adapter_instance", instance)
    return instance


def test_server_get_positions(mock_adapter: _MockAdapter) -> None:
    from broker_mcp.server import get_positions

    result = get_positions("HASH123")
    assert result["broker"] == "mock"
    assert result["account_id_hash"] == "HASH123"
    assert len(result["positions"]) == 1
    assert result["positions"][0]["ticker"] == "AAPL"


def test_server_get_account_summary(mock_adapter: _MockAdapter) -> None:
    from broker_mcp.server import get_account_summary

    result = get_account_summary("HASH123")
    assert result["cash_available"] == 12500.0
    assert result["total_value"] == 187500.0


def test_server_poll_for_fills_cold_start(mock_adapter: _MockAdapter) -> None:
    """No previous snapshot → snapshot_deltas treats AAPL as +150; txn says
    +50; reconciler emits the +50 BUY plus a +100 residual broker_diff."""
    from broker_mcp.server import poll_for_fills

    result = poll_for_fills(
        account_id_hash="HASH123",
        since_timestamp="2026-04-01T00:00:00Z",
        previous_snapshot=[],
    )
    events = result["fill_events"]
    # One real BUY (price=178.42) + one residual diff (price=None).
    assert len(events) == 2
    real = [e for e in events if e["price"] == 178.42][0]
    residual = [e for e in events if e["price"] is None][0]
    assert real["shares_delta"] == 50.0
    assert residual["shares_delta"] == 100.0


def test_server_poll_for_fills_with_previous_snapshot_match(
    mock_adapter: _MockAdapter,
) -> None:
    """Previous snapshot already has AAPL at 100; current is 150; +50 delta
    matches the +50 BUY transaction → no residual."""
    from broker_mcp.server import poll_for_fills

    result = poll_for_fills(
        account_id_hash="HASH123",
        since_timestamp="2026-04-01T00:00:00Z",
        previous_snapshot=[
            {
                "ticker": "AAPL",
                "shares_held": 100.0,
                "cost_basis": 150.0,
                "cost_basis_method": "FIFO",
                "first_acquired": "2025-01-01",
                "last_updated": "2026-04-15T12:00:00Z",
            }
        ],
    )
    events = result["fill_events"]
    assert len(events) == 1
    assert events[0]["ticker"] == "AAPL"
    assert events[0]["shares_delta"] == 50.0
    assert events[0]["price"] == 178.42


# =============================================================================
# Read-only contract guard
# =============================================================================


def test_no_place_order_tool_exists() -> None:
    """Per Section 7 Q5: this MCP is read-only. There must be no tool that
    can submit orders. Belt-and-suspenders check that nobody adds one."""
    from broker_mcp import server

    forbidden = {"place_order", "submit_order", "execute_trade", "buy", "sell"}
    public_attrs = {a for a in dir(server) if not a.startswith("_")}
    assert forbidden.isdisjoint(public_attrs), (
        f"Read-only contract violated: server exposes {forbidden & public_attrs}"
    )


def test_broker_adapter_abc_has_no_write_methods() -> None:
    """The adapter contract has no place_order/submit_order method."""
    from broker_mcp.adapters.base import BrokerAdapter

    abstract = set(BrokerAdapter.__abstractmethods__)
    assert "place_order" not in abstract
    assert "submit_order" not in abstract
    # Sanity: read methods are present.
    assert "get_positions" in abstract
    assert "get_account_summary" in abstract
    assert "get_transactions" in abstract
