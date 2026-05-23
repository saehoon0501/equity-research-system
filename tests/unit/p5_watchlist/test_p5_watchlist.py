"""Tests for src/p5_watchlist/.

Smoke + HMAC round-trip + input-validation coverage.

Per v3 spec Section 2.1 + Section 4.8 + Section 6 Q5.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.anchor_drift.hmac_verify import (
    verify_pillars_hmac,
    verify_scenario_hmac,
)
from src.p5_watchlist.adder import (
    WatchlistAddInput,
    add_to_watchlist,
    derive_conviction_threshold,
    derive_regime_sensitivity,
)
from src.watchlist.hmac_producer import WATCHLIST_HMAC_ENV


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_secret(monkeypatch: pytest.MonkeyPatch, secret: str = "test-watchlist-secret") -> None:
    monkeypatch.setenv(WATCHLIST_HMAC_ENV, secret)


def _make_input(**overrides: Any) -> WatchlistAddInput:
    base = dict(
        ticker="NVDA",
        mode="B_prime",
        company_quality_flag="HIGH",
        pm_supervisor_decision="ADD",
        thesis_pillars_original=[
            {"pillar": "moat", "evidence": "dominant H100 share"},
            {"pillar": "growth", "evidence": "datacenter capex tailwind"},
        ],
        scenario_A_base_projections={
            "revenue_5y_cagr": 0.30,
            "fcf_margin_terminal": 0.45,
            "wacc": 0.09,
        },
        macro_regime_style_output={"regime_sensitivity": "MEDIUM"},
    )
    base.update(overrides)
    return WatchlistAddInput(**base)


# ---------------------------------------------------------------------------
# Threshold derivation
# ---------------------------------------------------------------------------


def test_threshold_defaults() -> None:
    assert derive_conviction_threshold("B") == pytest.approx(0.70)
    assert derive_conviction_threshold("B_prime") == pytest.approx(0.60)
    assert derive_conviction_threshold("C") == pytest.approx(0.50)


def test_threshold_override_allowed() -> None:
    assert derive_conviction_threshold("C", override=0.65) == pytest.approx(0.65)


def test_threshold_invalid_override() -> None:
    with pytest.raises(ValueError):
        derive_conviction_threshold("B", override=1.5)


def test_threshold_invalid_mode() -> None:
    with pytest.raises(ValueError):
        derive_conviction_threshold("X")


# ---------------------------------------------------------------------------
# Regime sensitivity derivation
# ---------------------------------------------------------------------------


def test_regime_sensitivity_string() -> None:
    assert derive_regime_sensitivity("HIGH") == "HIGH"
    assert derive_regime_sensitivity("medium") == "MEDIUM"


def test_regime_sensitivity_dict_top_level() -> None:
    assert derive_regime_sensitivity({"regime_sensitivity": "LOW"}) == "LOW"


def test_regime_sensitivity_dict_nested() -> None:
    assert (
        derive_regime_sensitivity(
            {"rationale_payload": {"regime_sensitivity": "HIGH"}}
        )
        == "HIGH"
    )


def test_regime_sensitivity_default_medium() -> None:
    """Per Section 4.8: MEDIUM = quarterly review (prudent default)."""
    assert derive_regime_sensitivity({}) == "MEDIUM"
    assert derive_regime_sensitivity(None) == "MEDIUM"


# ---------------------------------------------------------------------------
# Add — dry-run path (no DB)
# ---------------------------------------------------------------------------


def test_add_dry_run_produces_hmac(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_secret(monkeypatch)
    inp = _make_input()
    out = add_to_watchlist(inp, conn=None)
    assert out.inserted is False
    assert len(out.thesis_pillars_original_hmac) == 64
    assert len(out.scenario_A_base_projections_hmac) == 64
    assert out.regime_sensitivity == "MEDIUM"
    assert out.conviction_threshold == pytest.approx(0.60)


def test_add_dry_run_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """HMAC produced at P5 must verify under anchor_drift verifier."""
    _set_secret(monkeypatch)
    inp = _make_input()
    out = add_to_watchlist(inp, conn=None)
    assert verify_pillars_hmac(
        list(inp.thesis_pillars_original), out.thesis_pillars_original_hmac
    )
    assert verify_scenario_hmac(
        dict(inp.scenario_A_base_projections),
        out.scenario_A_base_projections_hmac,
    )


def test_add_dry_run_tampered_pillar_fails_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_secret(monkeypatch)
    inp = _make_input()
    out = add_to_watchlist(inp, conn=None)
    tampered = list(inp.thesis_pillars_original) + [{"pillar": "INJECTED"}]
    assert not verify_pillars_hmac(tampered, out.thesis_pillars_original_hmac)


def test_add_rejects_non_add_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_secret(monkeypatch)
    inp = _make_input(pm_supervisor_decision="WATCH")
    with pytest.raises(ValueError, match="ADD"):
        add_to_watchlist(inp, conn=None)


def test_add_rejects_invalid_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_secret(monkeypatch)
    inp = _make_input(mode="A")
    with pytest.raises(ValueError):
        add_to_watchlist(inp, conn=None)


def test_add_rejects_invalid_quality(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_secret(monkeypatch)
    inp = _make_input(company_quality_flag="LOW")
    with pytest.raises(ValueError):
        add_to_watchlist(inp, conn=None)


# ---------------------------------------------------------------------------
# Add — fake-conn write path (no Postgres)
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(self) -> None:
        self.cur = _FakeCursor()
        self.committed = False

    def cursor(self) -> _FakeCursor:
        return self.cur

    def commit(self) -> None:
        self.committed = True


def test_add_writes_via_fake_conn(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_secret(monkeypatch)
    inp = _make_input()
    conn = _FakeConn()
    out = add_to_watchlist(inp, conn=conn)
    assert out.inserted is True
    assert len(conn.cur.executed) == 1
    sql, params = conn.cur.executed[0]
    assert "INSERT INTO watchlist" in sql
    # ticker first, mode second
    assert params[0] == "NVDA"
    assert params[1] == "B_prime"
    # HMAC fields included (positions 5 + 7 in the SQL).
    assert params[5] == out.thesis_pillars_original_hmac
    assert params[7] == out.scenario_A_base_projections_hmac
    assert conn.committed is True
