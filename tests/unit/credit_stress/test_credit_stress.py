"""Tests for the credit_stress block (WS-7.3) — pure/offline, NO network."""

from __future__ import annotations

import math

import pytest

from src.credit_stress.contracts import DebtMaturity, Financials, RateCurve
from src.credit_stress.credit_stress import (
    COVERAGE_HIGH_STRESS_X,
    RUNWAY_HIGH_QUARTERS,
    compute_cash_runway,
    compute_credit_stress,
    compute_interest_coverage,
    compute_maturity_wall,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _healthy_financials() -> Financials:
    """High coverage, distant maturities, long runway, low coupons."""
    return Financials(
        ebit=10_000.0,
        interest_expense=500.0,  # 20x coverage
        cash=40_000.0,
        quarterly_burn=-2_000.0,  # cash-GENERATIVE -> runway not_applicable
        debt_maturities=(
            DebtMaturity(years_to_maturity=8.0, amount=5_000.0, coupon_rate_pct=3.0),
            DebtMaturity(years_to_maturity=12.0, amount=5_000.0, coupon_rate_pct=3.2),
        ),
    )


def _healthy_curve() -> RateCurve:
    # Curve roughly in line with the company's long-dated coupons.
    return RateCurve(points={1.0: 3.1, 5.0: 3.3, 10.0: 3.5})


def _distressed_financials() -> Financials:
    """Coverage < 1.5x, near-term wall, < 2 quarters runway, low coupons."""
    return Financials(
        ebit=120.0,
        interest_expense=100.0,  # 1.2x base coverage; stressed even lower
        cash=300.0,
        quarterly_burn=200.0,  # 1.5 quarters runway
        debt_maturities=(
            # 80% of debt due in <=1y at a 2% coupon -> must roll much higher.
            DebtMaturity(years_to_maturity=0.8, amount=8_000.0, coupon_rate_pct=2.0),
            DebtMaturity(years_to_maturity=9.0, amount=2_000.0, coupon_rate_pct=2.5),
        ),
    )


def _distressed_curve() -> RateCurve:
    # Sharply higher than the maturing tranche's 2% coupon (>150bps gap).
    return RateCurve(points={1.0: 7.0, 5.0: 6.5, 10.0: 6.0})


# ---------------------------------------------------------------------------
# Acceptance: end-to-end flag
# ---------------------------------------------------------------------------


def test_healthy_fixture_is_low_credit_stress():
    block = compute_credit_stress(_healthy_financials(), _healthy_curve(), ticker="HLTH")
    assert block["overall_flag"] == "low"
    assert block["ticker"] == "HLTH"
    # sanity: no hard trips recorded
    assert block["interest_coverage"]["status"] == "ok"
    assert block["maturity_wall"]["risk"] == "low"
    assert block["cash_runway"]["status"] == "not_applicable"


def test_distressed_fixture_is_high_credit_stress():
    block = compute_credit_stress(
        _distressed_financials(), _distressed_curve(), ticker="DSTR"
    )
    assert block["overall_flag"] == "high"
    # all three legs should be contributing trips
    reasons = " ".join(block["flag_reasons"]).lower()
    assert "coverage" in reasons
    assert "maturity" in reasons
    assert "runway" in reasons


# ---------------------------------------------------------------------------
# Sub-metric correctness
# ---------------------------------------------------------------------------


def test_interest_coverage_equals_ebit_over_interest():
    fin = Financials(ebit=900.0, interest_expense=300.0)
    cov = compute_interest_coverage(fin, RateCurve())
    assert cov["status"] == "ok"
    assert cov["base_coverage_x"] == pytest.approx(3.0)
    # No near-term coupon/curve data -> stressed multiplier floored at 1.0.
    assert cov["stress_interest_multiplier"] == pytest.approx(1.0)
    assert cov["stressed_coverage_x"] == pytest.approx(3.0)


def test_stressed_coverage_repriced_to_higher_curve():
    fin = Financials(
        ebit=300.0,
        interest_expense=100.0,  # base 3.0x
        debt_maturities=(
            DebtMaturity(years_to_maturity=1.0, amount=1_000.0, coupon_rate_pct=2.0),
        ),
    )
    curve = RateCurve(points={1.0: 6.0})  # 3x the 2% coupon
    cov = compute_interest_coverage(fin, curve)
    # multiplier = 6/2 = 3.0 -> stressed interest 300 -> stressed coverage 1.0x
    assert cov["stress_interest_multiplier"] == pytest.approx(3.0)
    assert cov["stressed_coverage_x"] == pytest.approx(1.0)
    assert cov["stressed_coverage_x"] < COVERAGE_HIGH_STRESS_X


def test_cash_runway_equals_cash_over_burn():
    fin = Financials(cash=1_000.0, quarterly_burn=250.0)
    rw = compute_cash_runway(fin)
    assert rw["status"] == "ok"
    assert rw["runway_quarters"] == pytest.approx(4.0)


def test_cash_runway_not_applicable_when_generative():
    fin = Financials(cash=1_000.0, quarterly_burn=-50.0)
    rw = compute_cash_runway(fin)
    assert rw["status"] == "not_applicable"
    assert rw["value"] is None


# ---------------------------------------------------------------------------
# Maturity-wall: isolated discrimination (curve drives the risk, per advisor)
# ---------------------------------------------------------------------------


def test_maturity_wall_risk_rises_when_near_term_meets_higher_curve():
    fin = Financials(
        debt_maturities=(
            DebtMaturity(years_to_maturity=1.0, amount=8_000.0, coupon_rate_pct=2.0),
            DebtMaturity(years_to_maturity=9.0, amount=2_000.0, coupon_rate_pct=2.5),
        )
    )
    # Same fixture, two curves. Only the curve differs.
    low_curve = RateCurve(points={1.0: 2.1, 10.0: 2.6})  # tiny gap
    high_curve = RateCurve(points={1.0: 7.0, 10.0: 6.0})  # >150bps gap

    low = compute_maturity_wall(fin, low_curve)
    high = compute_maturity_wall(fin, high_curve)

    # Same near-term concentration, but the higher curve escalates the risk.
    assert low["near_term_share"] == pytest.approx(high["near_term_share"])
    assert high["risk"] == "high"
    assert low["risk"] != "high"
    assert high["rate_gap_bps"] > low["rate_gap_bps"]


def test_maturity_wall_distant_maturities_are_low_risk():
    fin = Financials(
        debt_maturities=(
            DebtMaturity(years_to_maturity=8.0, amount=10_000.0, coupon_rate_pct=3.0),
        )
    )
    mw = compute_maturity_wall(fin, RateCurve(points={1.0: 7.0, 10.0: 6.0}))
    assert mw["risk"] == "low"
    assert mw["near_term_share"] == pytest.approx(0.0)


def test_maturity_wall_not_applicable_without_debt():
    mw = compute_maturity_wall(Financials(), RateCurve(points={1.0: 5.0}))
    assert mw["status"] == "not_applicable"
    assert mw["risk"] == "not_applicable"


# ---------------------------------------------------------------------------
# Graceful degradation — missing/None inputs mark unavailable, never raise
# ---------------------------------------------------------------------------


def test_missing_coverage_inputs_unavailable():
    cov = compute_interest_coverage(Financials(ebit=None, interest_expense=100.0), RateCurve())
    assert cov["status"] == "unavailable"
    assert cov["value"] is None


def test_missing_runway_inputs_unavailable():
    rw = compute_cash_runway(Financials(cash=None, quarterly_burn=100.0))
    assert rw["status"] == "unavailable"
    assert rw["value"] is None


def test_zero_interest_expense_not_applicable():
    cov = compute_interest_coverage(Financials(ebit=500.0, interest_expense=0.0), RateCurve())
    assert cov["status"] == "not_applicable"
    assert cov["value"] is None


def test_all_inputs_missing_overall_unavailable():
    block = compute_credit_stress(Financials(), RateCurve(), ticker="EMPTY")
    assert block["overall_flag"] == "unavailable"
    assert block["interest_coverage"]["status"] == "unavailable"
    assert block["cash_runway"]["status"] == "unavailable"
    # No debt -> maturity wall is not_applicable (not unavailable).
    assert block["maturity_wall"]["status"] == "not_applicable"


def test_no_inputs_at_all_does_not_raise():
    # Defaults: financials=None, curve=None, no fetchers -> empty dataclasses.
    block = compute_credit_stress()
    assert block["overall_flag"] == "unavailable"


def test_maturity_wall_near_term_but_no_curve_uses_concentration_only():
    fin = Financials(
        debt_maturities=(
            DebtMaturity(years_to_maturity=1.0, amount=8_000.0, coupon_rate_pct=2.0),
            DebtMaturity(years_to_maturity=9.0, amount=2_000.0, coupon_rate_pct=2.0),
        )
    )
    mw = compute_maturity_wall(fin, RateCurve())  # empty curve
    assert mw["status"] == "ok"
    assert mw["rate_gap_bps"] is None
    # high concentration but cannot price refi -> elevated, never "high"
    assert mw["risk"] == "elevated"


# ---------------------------------------------------------------------------
# Injectable fetcher seam (live EDGAR/FRED boundary) — exercised with stubs
# ---------------------------------------------------------------------------


def test_fetcher_seams_invoked_when_direct_inputs_none():
    calls = {"fin": 0, "curve": 0}

    def fin_fetcher(ticker):
        calls["fin"] += 1
        assert ticker == "XYZ"
        return _healthy_financials()

    def curve_fetcher():
        calls["curve"] += 1
        return _healthy_curve()

    block = compute_credit_stress(
        ticker="XYZ",
        financials_fetcher=fin_fetcher,
        curve_fetcher=curve_fetcher,
    )
    assert calls == {"fin": 1, "curve": 1}
    assert block["overall_flag"] == "low"


def test_direct_inputs_take_precedence_over_fetchers():
    def boom(*_a, **_k):  # pragma: no cover - must NOT be called
        raise AssertionError("fetcher should not run when direct input given")

    block = compute_credit_stress(
        _healthy_financials(),
        _healthy_curve(),
        ticker="XYZ",
        financials_fetcher=boom,
        curve_fetcher=boom,
    )
    assert block["overall_flag"] == "low"


def test_default_no_fetchers_makes_no_network_call():
    # Smoke: with no fetchers and no inputs, the function is fully offline.
    block = compute_credit_stress(ticker="OFFLINE")
    assert block["ticker"] == "OFFLINE"
    assert "methodology" in block


# ---------------------------------------------------------------------------
# Block shape
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Flag-logic regression: NaN coverage must not fail open; not_applicable vs
# unavailable must be distinguished (WS-7.3 confirmed bugs).
# ---------------------------------------------------------------------------


def test_nan_coverage_does_not_escape_high_when_other_leg_hard_trips():
    """Bug 1: NaN EBIT/interest -> NaN stressed coverage must be treated as the
    coverage leg being *unavailable*, NOT as silently passing the 1.5x trip.

    With a real hard trip on another leg (runway < 2q here), the overall flag
    must still resolve "high" — the garbage coverage leg must not clear it.
    """
    fin = Financials(
        ebit=float("nan"),  # garbage -> NaN coverage
        interest_expense=100.0,
        cash=200.0,
        quarterly_burn=200.0,  # 1.0 quarter runway -> hard "high" trip
        debt_maturities=(
            DebtMaturity(years_to_maturity=0.8, amount=8_000.0, coupon_rate_pct=2.0),
            DebtMaturity(years_to_maturity=9.0, amount=2_000.0, coupon_rate_pct=2.5),
        ),
    )
    block = compute_credit_stress(fin, _distressed_curve(), ticker="NANC")
    # The coverage leg computed a NaN value but carries status "ok".
    assert block["interest_coverage"]["status"] == "ok"
    assert math.isnan(block["interest_coverage"]["stressed_coverage_x"])
    # Overall must NOT fail open to elevated/low — a real hard trip stands.
    assert block["overall_flag"] == "high"
    reasons = " ".join(block["flag_reasons"]).lower()
    # The "high" must come from a real leg (runway and/or maturity), never from
    # the NaN coverage leg "passing" the threshold.
    assert "runway" in reasons or "maturity" in reasons
    assert "stressed coverage" not in reasons


def test_nan_coverage_treated_unavailable_does_not_block_low():
    """Bug 1 corollary: a NaN coverage leg behaves like a genuinely-unavailable
    leg — it neither hard-trips nor counts as a healthy signal. When the other
    legs are healthy, classification proceeds and resolves "low" (the NaN leg
    is neutral, it does not silently clear a high trip nor force elevated)."""
    fin = Financials(
        ebit=float("nan"),  # garbage coverage
        interest_expense=100.0,
        cash=80_000.0,
        quarterly_burn=1_000.0,  # 80q runway -> healthy
        debt_maturities=(
            DebtMaturity(years_to_maturity=8.0, amount=10_000.0, coupon_rate_pct=3.0),
        ),
    )
    block = compute_credit_stress(fin, _healthy_curve(), ticker="NANL")
    assert block["interest_coverage"]["status"] == "ok"
    assert math.isnan(block["interest_coverage"]["stressed_coverage_x"])
    # runway healthy + maturity low -> low; NaN coverage neutral.
    assert block["overall_flag"] == "low"


def test_debt_free_cash_generative_healthy_is_low_not_unavailable():
    """Bug 2: a debt-free, cash-generative HEALTHY firm has NO "ok" leg
    (coverage unavailable, maturity not_applicable, runway not_applicable) yet
    must classify "low" — the not_applicable legs are HEALTHY structural
    signals, NOT "no data"."""
    fin = Financials(
        ebit=None,
        interest_expense=None,  # coverage unavailable (no data)
        cash=50_000.0,
        quarterly_burn=-2_000.0,  # cash-generative -> runway not_applicable
        debt_maturities=(),  # no debt -> maturity not_applicable
    )
    block = compute_credit_stress(fin, RateCurve(), ticker="DBTFREE")
    assert block["interest_coverage"]["status"] == "unavailable"
    assert block["maturity_wall"]["status"] == "not_applicable"
    assert block["cash_runway"]["status"] == "not_applicable"
    # The discriminating not_applicable (runway, from burn<=0) makes this "low".
    assert block["overall_flag"] == "low"


def test_truly_no_data_firm_is_unavailable():
    """Bug 2 boundary: when EVERY leg is genuinely unavailable (all inputs
    absent — and the only not_applicable is the ambiguous empty-debt maturity
    leg), the overall flag is "unavailable"."""
    block = compute_credit_stress(Financials(), RateCurve(), ticker="NODATA")
    assert block["interest_coverage"]["status"] == "unavailable"
    assert block["cash_runway"]["status"] == "unavailable"
    # Empty debt_maturities -> maturity not_applicable, but that is the
    # dataclass default (ambiguous with "no data") so it must NOT rescue.
    assert block["maturity_wall"]["status"] == "not_applicable"
    assert block["overall_flag"] == "unavailable"


def test_block_shape_carries_all_subblocks_and_thresholds():
    block = compute_credit_stress(_healthy_financials(), _healthy_curve(), ticker="SHAPE")
    for key in (
        "overall_flag",
        "flag_reasons",
        "interest_coverage",
        "maturity_wall",
        "cash_runway",
        "thresholds",
        "methodology",
    ):
        assert key in block
    assert block["thresholds"]["runway_high_quarters"] == RUNWAY_HIGH_QUARTERS
