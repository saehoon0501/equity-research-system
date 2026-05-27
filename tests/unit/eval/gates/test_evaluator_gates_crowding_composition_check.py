"""Unit tests for HG-35 crowding_composition_check.

Covers:
- NOT-APPLICABLE path (flow envelope lacks components.crowding) → valid=True
- Bit-identical re-derivation match (AND + OR) → valid=True
- Drift detection (re-derived warning ≠ emitted warning) → valid=False, drift_detected
- INV-CRD-1 violation (numerics don't match emitted warning bool)
- INV-CRD-2 violation (unavailable_reason set but warning=True)
- INV-CRD-3 violation (stale=True but warning=True)
- Missing parameters → valid=False, missing_inputs populated
- Invalid logic_operator in params → invalid_inputs populated
"""
from __future__ import annotations

from datetime import date

import pytest

from src.eval.gates.crowding_composition_check import (
    validate_crowding_composition,
)


_BASE_PARAMS = {
    "flow.crowding_days_to_cover_threshold": 5.0,
    "flow.crowding_short_pct_float_threshold": 0.20,
    "flow.crowding_logic_operator": "AND",
    "flow.crowding_stale_data_max_days": 21,
}

_AS_OF = date(2026, 5, 23)


def _flow_env_with_crowding(crowding: dict) -> dict:
    """Build a minimal flow envelope with a crowding sub-block."""
    return {
        "ticker": "TST",
        "flow_signal_bin": "neutral",
        "components": {"ticker_score": 0, "market_score": 0, "crowding": crowding},
    }


# ---------- NOT-APPLICABLE paths ----------


def test_flow_env_none_is_not_applicable():
    r = validate_crowding_composition(flow_env=None, parameters_active_snapshot=_BASE_PARAMS)
    assert r.valid is True
    assert any("NOT-APPLICABLE" in n for n in r.notes)


def test_flow_env_without_crowding_block_is_not_applicable():
    env = {"ticker": "AAPL", "components": {"ticker_score": 2, "market_score": 1}}
    r = validate_crowding_composition(flow_env=env, parameters_active_snapshot=_BASE_PARAMS)
    assert r.valid is True
    assert any("NOT-APPLICABLE" in n for n in r.notes)


# ---------- Consistent triple PASS ----------


def test_consistent_warning_true_and_logic_passes():
    crowding = {
        "warning": True,
        "days_to_cover": 8.0,
        "short_pct_float": 0.25,
        "settlement_date": "2026-05-15",
        "stale": False,
        "unavailable_reason": None,
    }
    env = _flow_env_with_crowding(crowding)
    r = validate_crowding_composition(env, _BASE_PARAMS, as_of=_AS_OF)
    assert r.valid is True
    assert r.warning_expected is True
    assert r.warning_observed is True
    assert r.drift_detected is False


def test_consistent_warning_false_below_threshold_passes():
    crowding = {
        "warning": False,
        "days_to_cover": 1.3,
        "short_pct_float": 0.05,
        "settlement_date": "2026-05-15",
        "stale": False,
        "unavailable_reason": None,
    }
    env = _flow_env_with_crowding(crowding)
    r = validate_crowding_composition(env, _BASE_PARAMS, as_of=_AS_OF)
    assert r.valid is True
    assert r.warning_expected is False


def test_consistent_or_logic_one_breach_passes():
    params = dict(_BASE_PARAMS, **{"flow.crowding_logic_operator": "OR"})
    crowding = {
        "warning": True,
        "days_to_cover": 8.0,
        "short_pct_float": 0.05,  # below threshold but OR fires on dtc alone
        "settlement_date": "2026-05-15",
        "stale": False,
        "unavailable_reason": None,
    }
    env = _flow_env_with_crowding(crowding)
    r = validate_crowding_composition(env, params, as_of=_AS_OF)
    assert r.valid is True
    assert r.warning_expected is True


# ---------- Drift detection ----------


def test_drift_warning_true_but_thresholds_not_met():
    """Emitter claims True but only one threshold breached under AND logic."""
    crowding = {
        "warning": True,
        "days_to_cover": 8.0,
        "short_pct_float": 0.05,  # under AND, this alone shouldn't fire
        "settlement_date": "2026-05-15",
        "stale": False,
        "unavailable_reason": None,
    }
    env = _flow_env_with_crowding(crowding)
    r = validate_crowding_composition(env, _BASE_PARAMS, as_of=_AS_OF)
    assert r.valid is False
    assert r.drift_detected is True
    assert r.warning_expected is False
    assert r.warning_observed is True


def test_drift_warning_false_but_thresholds_met():
    """Emitter claims False but BOTH thresholds breached under AND."""
    crowding = {
        "warning": False,
        "days_to_cover": 8.0,
        "short_pct_float": 0.25,
        "settlement_date": "2026-05-15",
        "stale": False,
        "unavailable_reason": None,
    }
    env = _flow_env_with_crowding(crowding)
    r = validate_crowding_composition(env, _BASE_PARAMS, as_of=_AS_OF)
    assert r.valid is False
    assert r.drift_detected is True
    assert r.warning_expected is True


# ---------- INV-CRD-2 fail-safe violations ----------


def test_inv_crd_2_violation_unavailable_reason_with_true_warning():
    """unavailable_reason set + warning=True breaches fail-safe contract."""
    crowding = {
        "warning": True,
        "days_to_cover": None,
        "short_pct_float": None,
        "settlement_date": None,
        "stale": False,
        "unavailable_reason": "short_interest_unavailable",
    }
    env = _flow_env_with_crowding(crowding)
    r = validate_crowding_composition(env, _BASE_PARAMS, as_of=_AS_OF)
    assert r.valid is False
    assert any("INV-CRD-2" in v for v in r.invariant_violations)


def test_unavailable_reason_with_false_warning_passes():
    """Fail-safe satisfied: unavailable_reason set AND warning=False."""
    crowding = {
        "warning": False,
        "days_to_cover": None,
        "short_pct_float": None,
        "settlement_date": None,
        "stale": False,
        "unavailable_reason": "short_interest_unavailable",
    }
    env = _flow_env_with_crowding(crowding)
    r = validate_crowding_composition(env, _BASE_PARAMS, as_of=_AS_OF)
    assert r.valid is True
    assert r.warning_expected is False


# ---------- INV-CRD-3 fail-safe violations ----------


def test_inv_crd_3_violation_stale_with_true_warning():
    """stale=True + warning=True breaches fail-safe contract."""
    crowding = {
        "warning": True,
        "days_to_cover": 8.0,
        "short_pct_float": 0.25,
        "settlement_date": "2026-04-01",
        "stale": True,
        "unavailable_reason": "short_interest_stale",
    }
    env = _flow_env_with_crowding(crowding)
    r = validate_crowding_composition(env, _BASE_PARAMS, as_of=_AS_OF)
    assert r.valid is False
    # Both INV-CRD-2 (unavailable_reason set) and INV-CRD-3 (stale) should fire
    assert any("INV-CRD-3" in v for v in r.invariant_violations)


def test_stale_with_false_warning_passes():
    crowding = {
        "warning": False,
        "days_to_cover": 8.0,
        "short_pct_float": 0.25,
        "settlement_date": "2026-04-01",
        "stale": True,
        "unavailable_reason": "short_interest_stale",
    }
    env = _flow_env_with_crowding(crowding)
    r = validate_crowding_composition(env, _BASE_PARAMS, as_of=_AS_OF)
    assert r.valid is True


# ---------- Missing / invalid inputs ----------


def test_missing_warning_field():
    env = _flow_env_with_crowding({"days_to_cover": 8.0, "short_pct_float": 0.25})
    r = validate_crowding_composition(env, _BASE_PARAMS, as_of=_AS_OF)
    assert r.valid is False
    assert "flow_env.components.crowding.warning" in r.missing_inputs


def test_missing_parameter_key():
    params = dict(_BASE_PARAMS)
    del params["flow.crowding_days_to_cover_threshold"]
    crowding = {
        "warning": False,
        "days_to_cover": 8.0,
        "short_pct_float": 0.05,
        "stale": False,
        "unavailable_reason": None,
    }
    env = _flow_env_with_crowding(crowding)
    r = validate_crowding_composition(env, params, as_of=_AS_OF)
    assert r.valid is False
    assert len(r.missing_inputs) > 0


def test_invalid_logic_operator():
    params = dict(_BASE_PARAMS, **{"flow.crowding_logic_operator": "XOR"})
    crowding = {
        "warning": False,
        "days_to_cover": 8.0,
        "short_pct_float": 0.05,
        "stale": False,
        "unavailable_reason": None,
    }
    env = _flow_env_with_crowding(crowding)
    r = validate_crowding_composition(env, params, as_of=_AS_OF)
    assert r.valid is False
    assert any("logic_operator" in i for i in r.invalid_inputs)


def test_unavailable_with_stale_consistent_passes():
    """unavailable + stale + warning=False is the canonical fail-safe response."""
    crowding = {
        "warning": False,
        "days_to_cover": None,
        "short_pct_float": None,
        "settlement_date": None,
        "stale": True,
        "unavailable_reason": "short_interest_stale",
    }
    env = _flow_env_with_crowding(crowding)
    r = validate_crowding_composition(env, _BASE_PARAMS, as_of=_AS_OF)
    assert r.valid is True
