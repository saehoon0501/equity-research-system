"""Tests for src/p6_disposition/.

Per v3 spec Section 2.1 + Section 4.6 Q2.
"""

from __future__ import annotations

import pytest

from src.p6_disposition.determiner import (
    HORIZON_LONG,
    HORIZON_MID,
    HORIZON_SHORT,
    DispositionInput,
    determine_disposition,
)


# ---------------------------------------------------------------------------
# Mode → primary horizon
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,expected_horizon",
    [
        ("B", HORIZON_LONG),
        ("B_prime", HORIZON_MID),
        ("C", HORIZON_SHORT),
    ],
)
def test_primary_horizon_by_mode(mode: str, expected_horizon: str) -> None:
    inp = DispositionInput(
        ticker="X",
        mode=mode,
        company_quality_flag="STANDARD",
        pm_supervisor_decision="ADD",
    )
    out = determine_disposition(inp)
    assert out.primary_horizon == expected_horizon


def test_invalid_mode_raises() -> None:
    inp = DispositionInput(
        ticker="X",
        mode="A",
        company_quality_flag="STANDARD",
        pm_supervisor_decision="ADD",
    )
    with pytest.raises(ValueError):
        determine_disposition(inp)


# ---------------------------------------------------------------------------
# Signal mapping
# ---------------------------------------------------------------------------


def test_add_not_held_buys() -> None:
    inp = DispositionInput(
        ticker="NVDA",
        mode="B_prime",
        company_quality_flag="HIGH",
        pm_supervisor_decision="ADD",
        currently_held=False,
    )
    out = determine_disposition(inp)
    assert out.primary_recommendation == "BUY"
    # Primary horizon = MID for B_prime; non-primary = HOLD.
    assert out.horizon_signals[HORIZON_MID] == "BUY"
    assert out.horizon_signals[HORIZON_SHORT] == "HOLD"
    assert out.horizon_signals[HORIZON_LONG] == "HOLD"


def test_add_held_holds() -> None:
    inp = DispositionInput(
        ticker="NVDA",
        mode="B_prime",
        company_quality_flag="HIGH",
        pm_supervisor_decision="ADD",
        currently_held=True,
    )
    out = determine_disposition(inp)
    assert out.primary_recommendation == "HOLD"


def test_watch_holds() -> None:
    inp = DispositionInput(
        ticker="X",
        mode="B",
        company_quality_flag="STANDARD",
        pm_supervisor_decision="WATCH",
    )
    out = determine_disposition(inp)
    assert out.primary_recommendation == "HOLD"


def test_pass_held_sells() -> None:
    inp = DispositionInput(
        ticker="X",
        mode="C",
        company_quality_flag="STANDARD",
        pm_supervisor_decision="PASS",
        currently_held=True,
    )
    out = determine_disposition(inp)
    assert out.primary_recommendation == "SELL"


def test_pass_not_held_holds() -> None:
    inp = DispositionInput(
        ticker="X",
        mode="C",
        company_quality_flag="STANDARD",
        pm_supervisor_decision="PASS",
        currently_held=False,
    )
    out = determine_disposition(inp)
    assert out.primary_recommendation == "HOLD"


def test_invalid_decision_raises() -> None:
    inp = DispositionInput(
        ticker="X",
        mode="B",
        company_quality_flag="STANDARD",
        pm_supervisor_decision="UNKNOWN",
    )
    with pytest.raises(ValueError):
        determine_disposition(inp)


# ---------------------------------------------------------------------------
# Pacing
# ---------------------------------------------------------------------------


def test_pacing_b_b_prime_dca() -> None:
    for mode in ("B", "B_prime"):
        inp = DispositionInput(
            ticker="X",
            mode=mode,
            company_quality_flag="STANDARD",
            pm_supervisor_decision="ADD",
        )
        assert "DCA" in determine_disposition(inp).suggested_pacing


def test_pacing_c_wait_for_arrival() -> None:
    inp = DispositionInput(
        ticker="X",
        mode="C",
        company_quality_flag="STANDARD",
        pm_supervisor_decision="ADD",
    )
    assert "wait-for-arrival" in determine_disposition(inp).suggested_pacing


# ---------------------------------------------------------------------------
# Rationale + payload
# ---------------------------------------------------------------------------


def test_rationale_includes_section_refs() -> None:
    inp = DispositionInput(
        ticker="X",
        mode="B",
        company_quality_flag="HIGH",
        pm_supervisor_decision="ADD",
    )
    out = determine_disposition(inp)
    assert any("Section 4.6 Q2" in s for s in out.rationale_strings)


def test_payload_round_trip() -> None:
    inp = DispositionInput(
        ticker="NVDA",
        mode="B_prime",
        company_quality_flag="HIGH",
        pm_supervisor_decision="ADD",
        conviction_bucket="HIGH",
        prior_recommendation="HOLD",
    )
    out = determine_disposition(inp)
    payload = out.to_payload()
    assert payload["ticker"] == "NVDA"
    assert payload["primary_horizon"] == "mid"
    assert payload["horizon_signals"]["mid"] == "BUY"
    assert "rationale_strings" in payload
