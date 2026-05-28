"""Tests for HG-34 catalyst+flow modifier composition determinism gate (v0.2)."""

import pytest

from src.eval.gates.catalyst_modifier_composition_check import (
    CatalystModifierCompositionResult,
    validate_catalyst_modifier_composition,
)
from src.supervisor.catalyst_flow_modifier import (
    compose_catalyst_flow_modifier,
)


def _params_snapshot() -> dict:
    """Standard parameters_active snapshot (integer-percent per migration storage)."""
    return {
        "sizing.catalyst_modifier_magnitude_scaler.low": 5,
        "sizing.catalyst_modifier_magnitude_scaler.medium": 10,
        "sizing.catalyst_modifier_magnitude_scaler.high": 20,
        "sizing.flow_modifier_pp_per_unit": 5,
        "sizing.catalyst_modifier_bound.full_pct": 25,
        "sizing.catalyst_modifier_bound.shrunk_pct": 10,
    }


def _catalyst_env(direction=1, magnitude="medium", tier_insufficient=False, sentiment_data_degraded=False) -> dict:
    return {
        "conviction_modifier": {
            "direction": direction,
            "magnitude": magnitude,
            "reason": "test catalyst reason",
        },
        "positioning": {"tier_insufficient": tier_insufficient},
        "sentiment_data_degraded": sentiment_data_degraded,
    }


def _flow_env(bin_="positive") -> dict:
    return {"flow_signal_bin": bin_}


def _pm_env_with_expected_audit(catalyst_env: dict, flow_env: dict, base_midpoint_pp=4.0) -> dict:
    """Build a pm-supervisor envelope whose catalyst_modifier_applied is the
    deterministically-correct audit string for the given inputs.
    """
    cm = catalyst_env["conviction_modifier"]
    tier_insufficient = catalyst_env["positioning"]["tier_insufficient"]
    sentiment_degraded = catalyst_env["sentiment_data_degraded"]
    bound = 10 if (tier_insufficient or sentiment_degraded) else 25

    expected = compose_catalyst_flow_modifier(
        base_midpoint_pp=base_midpoint_pp,
        catalyst_direction=cm["direction"],
        catalyst_magnitude=cm["magnitude"],
        catalyst_magnitude_scaler={"low": 0.05, "medium": 0.10, "high": 0.20},
        flow_signal_bin=flow_env["flow_signal_bin"],
        flow_per_unit_pct=0.05,
        bound_pct=bound / 100.0,
        catalyst_reason=cm["reason"],
    )
    return {
        "size_band_pre_modifier_midpoint_pp": base_midpoint_pp,
        "catalyst_modifier_applied": expected.audit_string,
    }


# ---------- Happy path ----------


def test_consistent_triple_passes():
    """When pm-supervisor's audit string matches the deterministic re-derivation, valid=True."""
    cat = _catalyst_env(direction=1, magnitude="medium")
    flow = _flow_env(bin_="positive")
    pm = _pm_env_with_expected_audit(cat, flow)
    r = validate_catalyst_modifier_composition(cat, flow, pm, _params_snapshot())
    assert r.valid is True
    assert r.drift_detected is False
    assert r.audit_string_expected == r.audit_string_observed


def test_offline_flow_treated_as_zero_contribution():
    """flow_env=None → flow_signal_bin coerced to 'offline' (zero contribution)."""
    cat = _catalyst_env(direction=1, magnitude="medium")
    pm = _pm_env_with_expected_audit(cat, _flow_env(bin_="offline"), base_midpoint_pp=4.0)
    r = validate_catalyst_modifier_composition(cat, flow_env=None, pm_env=pm, parameters_active_snapshot=_params_snapshot())
    assert r.valid is True


def test_catalyst_scout_offline_requires_canonical_audit():
    """When catalyst-scout offline, modifier MUST be '0 (catalyst-scout offline)'."""
    pm_correct = {
        "size_band_pre_modifier_midpoint_pp": 4.0,
        "catalyst_modifier_applied": "0 (catalyst-scout offline)",
    }
    r = validate_catalyst_modifier_composition(
        catalyst_env=None, flow_env=_flow_env(), pm_env=pm_correct,
        parameters_active_snapshot=_params_snapshot(),
    )
    assert r.valid is True


def test_catalyst_scout_offline_rejects_drift():
    """When catalyst-scout offline, any audit string other than the canonical is drift."""
    pm_wrong = {
        "size_band_pre_modifier_midpoint_pp": 4.0,
        "catalyst_modifier_applied": "+0.05 (some made-up reason)",
    }
    r = validate_catalyst_modifier_composition(
        catalyst_env=None, flow_env=_flow_env(), pm_env=pm_wrong,
        parameters_active_snapshot=_params_snapshot(),
    )
    assert r.valid is False
    assert r.drift_detected is True


# ---------- Drift detection ----------


def test_drift_in_audit_string_detected():
    """pm-supervisor emits an audit string that doesn't match the deterministic helper → fail."""
    cat = _catalyst_env(direction=1, magnitude="medium")
    flow = _flow_env(bin_="positive")
    pm = _pm_env_with_expected_audit(cat, flow)
    # Corrupt the audit string
    pm["catalyst_modifier_applied"] = pm["catalyst_modifier_applied"] + " EXTRA DRIFT"
    r = validate_catalyst_modifier_composition(cat, flow, pm, _params_snapshot())
    assert r.valid is False
    assert r.drift_detected is True
    assert r.audit_string_observed != r.audit_string_expected


def test_drift_whitespace_difference_caught():
    """Bit-identical comparison — extra whitespace counts as drift."""
    cat = _catalyst_env(direction=1, magnitude="medium")
    flow = _flow_env(bin_="positive")
    pm = _pm_env_with_expected_audit(cat, flow)
    pm["catalyst_modifier_applied"] = pm["catalyst_modifier_applied"] + " "  # trailing space
    r = validate_catalyst_modifier_composition(cat, flow, pm, _params_snapshot())
    assert r.valid is False
    assert r.drift_detected is True


# ---------- Missing inputs ----------


def test_missing_pm_audit_string_fails():
    cat = _catalyst_env()
    flow = _flow_env()
    pm = {"size_band_pre_modifier_midpoint_pp": 4.0}  # no catalyst_modifier_applied
    r = validate_catalyst_modifier_composition(cat, flow, pm, _params_snapshot())
    assert r.valid is False
    assert any("catalyst_modifier_applied" in m for m in r.missing_inputs)


def test_missing_base_midpoint_fails():
    cat = _catalyst_env()
    flow = _flow_env()
    pm = {"catalyst_modifier_applied": "+0.40pp | ..."}  # no base midpoint
    r = validate_catalyst_modifier_composition(cat, flow, pm, _params_snapshot())
    assert r.valid is False
    assert any("size_band_pre_modifier_midpoint_pp" in m for m in r.missing_inputs)


def test_missing_params_snapshot_keys_fails():
    cat = _catalyst_env()
    flow = _flow_env()
    pm = _pm_env_with_expected_audit(cat, flow)
    # Drop a required key
    incomplete_params = {k: v for k, v in _params_snapshot().items() if k != "sizing.catalyst_modifier_bound.full_pct"}
    r = validate_catalyst_modifier_composition(cat, flow, pm, incomplete_params)
    assert r.valid is False
    assert r.invalid_inputs  # at least one populated


# ---------- Invalid input shape ----------


def test_invalid_catalyst_direction_non_int_fails():
    cat = _catalyst_env()
    cat["conviction_modifier"]["direction"] = "not-an-int"
    flow = _flow_env()
    pm = {"size_band_pre_modifier_midpoint_pp": 4.0, "catalyst_modifier_applied": "x"}
    r = validate_catalyst_modifier_composition(cat, flow, pm, _params_snapshot())
    assert r.valid is False
    assert r.invalid_inputs


def test_string_direction_coerced_to_int():
    """Some agents emit '+1' as string — should be coerced via int()."""
    cat = _catalyst_env()
    cat["conviction_modifier"]["direction"] = "1"  # string but int-parseable
    flow = _flow_env()
    pm = _pm_env_with_expected_audit(_catalyst_env(direction=1), flow)
    r = validate_catalyst_modifier_composition(cat, flow, pm, _params_snapshot())
    assert r.valid is True  # coerced; audit matches


# ---------- Bound shrinkage logic ----------


def test_tier_insufficient_shrinks_bound():
    """tier_insufficient=True must trigger the ±10% shrunk bound."""
    cat = _catalyst_env(tier_insufficient=True)
    flow = _flow_env()
    pm = _pm_env_with_expected_audit(cat, flow)
    r = validate_catalyst_modifier_composition(cat, flow, pm, _params_snapshot())
    assert r.valid is True
    # The audit string should reference bound=±0.40pp (10% × 4.0 base midpoint = 0.40pp)
    assert "0.40pp" in r.audit_string_expected


def test_sentiment_degraded_shrinks_bound():
    """sentiment_data_degraded=True must trigger the ±10% shrunk bound."""
    cat = _catalyst_env(sentiment_data_degraded=True)
    flow = _flow_env()
    pm = _pm_env_with_expected_audit(cat, flow)
    r = validate_catalyst_modifier_composition(cat, flow, pm, _params_snapshot())
    assert r.valid is True
    assert "0.40pp" in r.audit_string_expected
