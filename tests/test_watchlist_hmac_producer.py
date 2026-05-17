"""Tests for src/watchlist/hmac_producer.py.

Round-trip tests: producer signs, anchor_drift verifier validates.

Per v3 spec Section 6 Q5 + Section 6.2 anchor-drift HMAC contract.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.anchor_drift.hmac_verify import (
    HmacVerificationError,
    verify_pillars_hmac,
    verify_scenario_hmac,
)
from src.watchlist.hmac_producer import (
    WATCHLIST_HMAC_ENV,
    WatchlistHmacError,
    sign_watchlist_row,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_secret(monkeypatch: pytest.MonkeyPatch, secret: str = "test-secret-key") -> None:
    monkeypatch.setenv(WATCHLIST_HMAC_ENV, secret)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sign_watchlist_row_returns_both_hmacs(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_secret(monkeypatch)
    pillars = [
        {"pillar": "moat", "evidence": "10K-2024 disclosure"},
        {"pillar": "founder", "evidence": "AAPL CEO since 1976"},
    ]
    scenario = {
        "revenue_5y_cagr": "0.12",
        "fcf_margin_terminal": "0.27",
        "wacc": "0.085",
    }
    sigs = sign_watchlist_row(pillars, scenario)
    assert "thesis_pillars_original_hmac" in sigs
    assert "scenario_A_base_projections_hmac" in sigs
    # Hex digest
    assert len(sigs["thesis_pillars_original_hmac"]) == 64
    assert len(sigs["scenario_A_base_projections_hmac"]) == 64
    # Signatures differ (different payloads).
    assert (
        sigs["thesis_pillars_original_hmac"]
        != sigs["scenario_A_base_projections_hmac"]
    )


def test_round_trip_pillars(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_secret(monkeypatch)
    pillars = [
        {"pillar": "moat", "still_holds": True, "score": 0.9},
        {"pillar": "founder", "still_holds": True, "score": 0.85},
    ]
    scenario = {"revenue_5y_cagr": 0.12, "wacc": 0.085}
    sigs = sign_watchlist_row(pillars, scenario)
    assert verify_pillars_hmac(pillars, sigs["thesis_pillars_original_hmac"])
    assert verify_scenario_hmac(
        scenario, sigs["scenario_A_base_projections_hmac"]
    )


def test_tampering_invalidates_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_secret(monkeypatch)
    pillars = [{"pillar": "moat", "still_holds": True}]
    sigs = sign_watchlist_row(pillars, {"x": 1})
    tampered = [{"pillar": "moat", "still_holds": False}]
    assert not verify_pillars_hmac(tampered, sigs["thesis_pillars_original_hmac"])


def test_unicode_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Greek letter + em-dash MUST round-trip — catches ensure_ascii=True bugs."""
    _set_secret(monkeypatch)
    pillars = [
        {"pillar": "alpha is α — measured per-share", "verbatim": "δ-Δ-em—dash"},
    ]
    scenario = {"note": "—"}
    sigs = sign_watchlist_row(pillars, scenario)
    assert verify_pillars_hmac(pillars, sigs["thesis_pillars_original_hmac"])
    assert verify_scenario_hmac(scenario, sigs["scenario_A_base_projections_hmac"])


def test_decimal_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decimal columns (Postgres NUMERIC arrives as Decimal in psycopg)."""
    _set_secret(monkeypatch)
    scenario = {
        "revenue_5y_cagr": Decimal("0.123456789"),
        "wacc": Decimal("0.0850"),
    }
    pillars = [{"pillar": "x"}]
    sigs = sign_watchlist_row(pillars, scenario)
    assert verify_scenario_hmac(scenario, sigs["scenario_A_base_projections_hmac"])


def test_missing_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WATCHLIST_HMAC_ENV, raising=False)
    with pytest.raises(WatchlistHmacError):
        sign_watchlist_row([{"pillar": "x"}], {"y": 1})


def test_explicit_key_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WATCHLIST_HMAC_ENV, raising=False)
    pillars = [{"pillar": "moat"}]
    scenario = {"x": 1}
    # Sign with explicit key, then expect verify to fail without secret in env.
    sigs = sign_watchlist_row(pillars, scenario, hmac_key=b"explicit")
    # Without env, verifier raises:
    with pytest.raises(HmacVerificationError):
        verify_pillars_hmac(pillars, sigs["thesis_pillars_original_hmac"])
