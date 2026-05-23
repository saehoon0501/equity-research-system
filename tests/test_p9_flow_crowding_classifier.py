"""Unit tests for src.p9_flow_overlay.crowding_classifier.

Covers:
- AND logic (both thresholds breached → warning=True)
- OR logic (either breach → warning=True)
- Below-threshold paths → warning=False
- Stale data → warning=False with unavailable_reason=short_interest_stale
- Missing inputs → warning=False with appropriate unavailable_reason
- compute_short_pct_float edge cases
- Fail-safe contract: warning=False whenever ANY input missing/stale
"""
from __future__ import annotations

from datetime import date

import pytest

from src.p9_flow_overlay.crowding_classifier import (
    classify_crowding,
    compute_short_pct_float,
    is_stale,
)


# Common fixtures

_DTC_THRESH = 5.0
_SPF_THRESH = 0.20
_STALE_MAX = 21
_AS_OF = date(2026, 5, 23)
_FRESH_SETTLE = "2026-05-15"  # 8d old; within stale_max=21
_STALE_SETTLE = "2026-04-01"  # 52d old; beyond stale_max=21


def _si(short_interest: int, days_to_cover: float, settlement_date: str = _FRESH_SETTLE) -> dict:
    return {
        "ticker": "TST",
        "short_interest": short_interest,
        "days_to_cover": days_to_cover,
        "settlement_date": settlement_date,
        "avg_daily_volume": 1_000_000,
    }


# ---------- compute_short_pct_float ----------


def test_compute_short_pct_float_basic():
    assert compute_short_pct_float(2_000_000, 10_000_000) == pytest.approx(0.20)


def test_compute_short_pct_float_zero_shares_returns_none():
    assert compute_short_pct_float(1_000_000, 0) is None


def test_compute_short_pct_float_negative_shares_returns_none():
    assert compute_short_pct_float(1_000_000, -100) is None


def test_compute_short_pct_float_negative_short_returns_none():
    assert compute_short_pct_float(-100, 10_000_000) is None


def test_compute_short_pct_float_none_inputs_returns_none():
    assert compute_short_pct_float(None, 10_000_000) is None
    assert compute_short_pct_float(1_000_000, None) is None


# ---------- is_stale ----------


def test_is_stale_within_window():
    assert is_stale(date(2026, 5, 15), date(2026, 5, 23), 21) is False


def test_is_stale_at_boundary():
    # 21d boundary inclusive: age==21 still NOT stale
    assert is_stale(date(2026, 5, 2), date(2026, 5, 23), 21) is False


def test_is_stale_past_boundary():
    assert is_stale(date(2026, 5, 1), date(2026, 5, 23), 21) is True


def test_is_stale_none_dates_returns_stale():
    assert is_stale(None, _AS_OF, 21) is True
    assert is_stale(date(2026, 5, 15), None, 21) is True


# ---------- classify_crowding — AND logic ----------


def test_and_both_breached_warning_true():
    # dtc=8.0 >= 5.0, spf=0.25 >= 0.20 → both breached under AND → True
    si = _si(short_interest=2_500_000, days_to_cover=8.0)
    out = classify_crowding(
        short_interest_data=si,
        shares_outstanding=10_000_000,  # spf = 2.5M / 10M = 0.25
        as_of=_AS_OF,
        days_to_cover_threshold=_DTC_THRESH,
        short_pct_float_threshold=_SPF_THRESH,
        logic_operator="AND",
        stale_data_max_days=_STALE_MAX,
    )
    assert out["warning"] is True
    assert out["days_to_cover"] == pytest.approx(8.0)
    assert out["short_pct_float"] == pytest.approx(0.25)
    assert out["unavailable_reason"] is None


def test_and_only_dtc_breached_warning_false():
    # dtc=8.0 >= 5.0 but spf=0.05 < 0.20 → AND fails → False
    si = _si(short_interest=500_000, days_to_cover=8.0)
    out = classify_crowding(si, 10_000_000, _AS_OF, _DTC_THRESH, _SPF_THRESH, "AND", _STALE_MAX)
    assert out["warning"] is False


def test_and_only_spf_breached_warning_false():
    # spf=0.25 >= 0.20 but dtc=2.0 < 5.0 → AND fails → False
    si = _si(short_interest=2_500_000, days_to_cover=2.0)
    out = classify_crowding(si, 10_000_000, _AS_OF, _DTC_THRESH, _SPF_THRESH, "AND", _STALE_MAX)
    assert out["warning"] is False


# ---------- classify_crowding — OR logic ----------


def test_or_only_dtc_breached_warning_true():
    # OR: dtc=8.0 breached, spf=0.05 not → True
    si = _si(short_interest=500_000, days_to_cover=8.0)
    out = classify_crowding(si, 10_000_000, _AS_OF, _DTC_THRESH, _SPF_THRESH, "OR", _STALE_MAX)
    assert out["warning"] is True


def test_or_only_spf_breached_warning_true():
    si = _si(short_interest=2_500_000, days_to_cover=2.0)
    out = classify_crowding(si, 10_000_000, _AS_OF, _DTC_THRESH, _SPF_THRESH, "OR", _STALE_MAX)
    assert out["warning"] is True


def test_or_neither_breached_warning_false():
    si = _si(short_interest=500_000, days_to_cover=2.0)
    out = classify_crowding(si, 10_000_000, _AS_OF, _DTC_THRESH, _SPF_THRESH, "OR", _STALE_MAX)
    assert out["warning"] is False


# ---------- Boundary cases ----------


def test_dtc_exact_boundary_breaches():
    # dtc == threshold → breach (>=)
    si = _si(short_interest=2_500_000, days_to_cover=5.0)
    out = classify_crowding(si, 10_000_000, _AS_OF, _DTC_THRESH, _SPF_THRESH, "AND", _STALE_MAX)
    assert out["warning"] is True


def test_spf_exact_boundary_breaches():
    si = _si(short_interest=2_000_000, days_to_cover=8.0)
    out = classify_crowding(si, 10_000_000, _AS_OF, _DTC_THRESH, _SPF_THRESH, "AND", _STALE_MAX)
    # spf = 2M / 10M = 0.20 == threshold → breach
    assert out["short_pct_float"] == pytest.approx(0.20)
    assert out["warning"] is True


# ---------- Fail-safe paths ----------


def test_stale_data_forces_warning_false():
    si = _si(short_interest=2_500_000, days_to_cover=8.0, settlement_date=_STALE_SETTLE)
    out = classify_crowding(si, 10_000_000, _AS_OF, _DTC_THRESH, _SPF_THRESH, "AND", _STALE_MAX)
    assert out["warning"] is False
    assert out["stale"] is True
    assert out["unavailable_reason"] == "short_interest_stale"


def test_short_interest_unavailable_warning_false():
    out = classify_crowding(None, 10_000_000, _AS_OF, _DTC_THRESH, _SPF_THRESH, "AND", _STALE_MAX)
    assert out["warning"] is False
    assert out["unavailable_reason"] == "short_interest_unavailable"


def test_ticker_not_found_in_data_warning_false():
    out = classify_crowding(
        {"ticker_not_found": True},
        10_000_000,
        _AS_OF,
        _DTC_THRESH,
        _SPF_THRESH,
        "AND",
        _STALE_MAX,
    )
    assert out["warning"] is False
    assert out["unavailable_reason"] == "short_interest_unavailable"


def test_shares_outstanding_missing_warning_false():
    si = _si(short_interest=2_500_000, days_to_cover=8.0)
    out = classify_crowding(si, None, _AS_OF, _DTC_THRESH, _SPF_THRESH, "AND", _STALE_MAX)
    assert out["warning"] is False
    assert out["unavailable_reason"] == "shares_outstanding_unavailable"


def test_shares_outstanding_zero_warning_false():
    si = _si(short_interest=2_500_000, days_to_cover=8.0)
    out = classify_crowding(si, 0, _AS_OF, _DTC_THRESH, _SPF_THRESH, "AND", _STALE_MAX)
    assert out["warning"] is False
    assert out["unavailable_reason"] == "shares_outstanding_unavailable"


def test_settlement_date_missing_warning_false():
    si = {"short_interest": 2_500_000, "days_to_cover": 8.0}  # no settlement_date
    out = classify_crowding(si, 10_000_000, _AS_OF, _DTC_THRESH, _SPF_THRESH, "AND", _STALE_MAX)
    assert out["warning"] is False
    assert out["unavailable_reason"] == "short_interest_unavailable"


def test_invalid_logic_operator_raises():
    si = _si(2_500_000, 8.0)
    with pytest.raises(ValueError, match="logic_operator"):
        classify_crowding(si, 10_000_000, _AS_OF, _DTC_THRESH, _SPF_THRESH, "XOR", _STALE_MAX)


# ---------- Output shape ----------


def test_output_carries_all_documented_fields():
    si = _si(2_500_000, 8.0)
    out = classify_crowding(si, 10_000_000, _AS_OF, _DTC_THRESH, _SPF_THRESH, "AND", _STALE_MAX)
    expected_keys = {
        "warning",
        "days_to_cover",
        "short_pct_float",
        "settlement_date",
        "logic_operator",
        "thresholds_applied",
        "stale",
        "unavailable_reason",
        "framework_keys",
    }
    assert set(out.keys()) == expected_keys
    assert out["thresholds_applied"] == {
        "days_to_cover": _DTC_THRESH,
        "short_pct_float": _SPF_THRESH,
    }
    assert "diether_lee_werner_2009" in out["framework_keys"]
