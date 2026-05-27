"""Tests for the deterministic catalyst + flow modifier composition helper."""

import pytest

from src.supervisor.catalyst_flow_modifier import (
    compose_catalyst_flow_modifier,
)

# Standard scaler used across tests (mirrors the launch-default values pm-supervisor
# §6 will load from sizing.catalyst_modifier_magnitude_scaler.*)
SCALER = {"low": 0.05, "medium": 0.10, "high": 0.20}


def test_catalyst_only_no_flow():
    """Catalyst +1 medium with neutral flow → catalyst_pp only, no clip."""
    r = compose_catalyst_flow_modifier(
        base_midpoint_pp=4.0,
        catalyst_direction=1,
        catalyst_magnitude="medium",
        catalyst_magnitude_scaler=SCALER,
        flow_signal_bin="neutral",
        flow_per_unit_pct=0.05,
        bound_pct=0.25,
    )
    assert r.catalyst_pp_unclipped == pytest.approx(0.40)  # 0.10 × 4.0
    assert r.flow_pp_unclipped == 0.0
    assert r.combined_pp_clipped == pytest.approx(0.40)
    assert r.clip_engaged is False


def test_flow_only_no_catalyst():
    """Catalyst direction = 0, flow = positive → flow contribution only."""
    r = compose_catalyst_flow_modifier(
        base_midpoint_pp=4.0,
        catalyst_direction=0,
        catalyst_magnitude=None,
        catalyst_magnitude_scaler=SCALER,
        flow_signal_bin="positive",
        flow_per_unit_pct=0.05,
        bound_pct=0.25,
    )
    assert r.catalyst_pp_unclipped == 0.0
    assert r.flow_sign == 1
    assert r.flow_pp_unclipped == pytest.approx(0.20)  # 0.05 × 4.0
    assert r.combined_pp_clipped == pytest.approx(0.20)


def test_both_same_direction_sum():
    """Catalyst +1 high + flow positive → both add; INV-CFM-1 sum-before-clip."""
    r = compose_catalyst_flow_modifier(
        base_midpoint_pp=4.0,
        catalyst_direction=1,
        catalyst_magnitude="high",
        catalyst_magnitude_scaler=SCALER,
        flow_signal_bin="positive",
        flow_per_unit_pct=0.05,
        bound_pct=0.25,
    )
    # catalyst = 0.20 × 4 = 0.80; flow = 0.05 × 4 = 0.20; sum = 1.00
    # bound = 0.25 × 4 = 1.00; combined exactly at bound, no clip
    assert r.catalyst_pp_unclipped == pytest.approx(0.80)
    assert r.flow_pp_unclipped == pytest.approx(0.20)
    assert r.combined_pp_unclipped == pytest.approx(1.00)
    assert r.bound_pp == pytest.approx(1.00)
    assert r.combined_pp_clipped == pytest.approx(1.00)
    assert r.clip_engaged is False


def test_clip_engages_when_sum_exceeds_bound():
    """INV-CFM-2: combined_pp_unclipped > bound_pp → clipped to +bound_pp."""
    # catalyst +1 high = 0.80; flow positive = 0.20; sum = 1.00
    # bound = 0.20 × 4 = 0.80 (shrunk); combined > bound → clip
    r = compose_catalyst_flow_modifier(
        base_midpoint_pp=4.0,
        catalyst_direction=1,
        catalyst_magnitude="high",
        catalyst_magnitude_scaler=SCALER,
        flow_signal_bin="positive",
        flow_per_unit_pct=0.05,
        bound_pct=0.20,  # shrunk bound
    )
    assert r.combined_pp_unclipped == pytest.approx(1.00)
    assert r.bound_pp == pytest.approx(0.80)
    assert r.combined_pp_clipped == pytest.approx(0.80)
    assert r.clip_engaged is True


def test_clip_engages_symmetrically_on_negative():
    """INV-CFM-2: clipping is symmetric on negative side."""
    r = compose_catalyst_flow_modifier(
        base_midpoint_pp=4.0,
        catalyst_direction=-1,
        catalyst_magnitude="high",
        catalyst_magnitude_scaler=SCALER,
        flow_signal_bin="negative",
        flow_per_unit_pct=0.05,
        bound_pct=0.20,
    )
    assert r.combined_pp_unclipped == pytest.approx(-1.00)
    assert r.bound_pp == pytest.approx(0.80)
    assert r.combined_pp_clipped == pytest.approx(-0.80)
    assert r.clip_engaged is True


def test_opposing_signals_partial_cancellation():
    """Catalyst +1 high + flow negative → contributions oppose."""
    r = compose_catalyst_flow_modifier(
        base_midpoint_pp=4.0,
        catalyst_direction=1,
        catalyst_magnitude="high",
        catalyst_magnitude_scaler=SCALER,
        flow_signal_bin="negative",
        flow_per_unit_pct=0.05,
        bound_pct=0.25,
    )
    # catalyst = +0.80, flow = -0.20, sum = +0.60, within bound
    assert r.combined_pp_unclipped == pytest.approx(0.60)
    assert r.combined_pp_clipped == pytest.approx(0.60)


def test_offline_flow_treated_as_zero():
    """flow_signal_bin = 'offline' (sentinel for .degraded) → zero contribution."""
    r = compose_catalyst_flow_modifier(
        base_midpoint_pp=4.0,
        catalyst_direction=1,
        catalyst_magnitude="medium",
        catalyst_magnitude_scaler=SCALER,
        flow_signal_bin="offline",
        flow_per_unit_pct=0.05,
        bound_pct=0.25,
    )
    assert r.flow_sign == 0
    assert r.flow_pp_unclipped == 0.0
    assert r.combined_pp_unclipped == pytest.approx(0.40)


def test_unavailable_flow_treated_as_zero():
    r = compose_catalyst_flow_modifier(
        base_midpoint_pp=4.0,
        catalyst_direction=0,
        catalyst_magnitude=None,
        catalyst_magnitude_scaler=SCALER,
        flow_signal_bin="unavailable",
        flow_per_unit_pct=0.05,
        bound_pct=0.25,
    )
    assert r.flow_sign == 0
    assert r.combined_pp_clipped == 0.0


def test_invalid_flow_bin_raises():
    with pytest.raises(ValueError):
        compose_catalyst_flow_modifier(
            base_midpoint_pp=4.0,
            catalyst_direction=0,
            catalyst_magnitude=None,
            catalyst_magnitude_scaler=SCALER,
            flow_signal_bin="UNKNOWN",
            flow_per_unit_pct=0.05,
            bound_pct=0.25,
        )


def test_invalid_catalyst_direction_raises():
    with pytest.raises(ValueError):
        compose_catalyst_flow_modifier(
            base_midpoint_pp=4.0,
            catalyst_direction=2,  # not in {-1, 0, +1}
            catalyst_magnitude="high",
            catalyst_magnitude_scaler=SCALER,
            flow_signal_bin="neutral",
            flow_per_unit_pct=0.05,
            bound_pct=0.25,
        )


def test_missing_magnitude_scaler_key_raises():
    """If catalyst_direction != 0, magnitude must be in scaler keys."""
    with pytest.raises(ValueError):
        compose_catalyst_flow_modifier(
            base_midpoint_pp=4.0,
            catalyst_direction=1,
            catalyst_magnitude="extreme",  # not in SCALER
            catalyst_magnitude_scaler=SCALER,
            flow_signal_bin="positive",
            flow_per_unit_pct=0.05,
            bound_pct=0.25,
        )


def test_zero_bound_raises():
    with pytest.raises(ValueError):
        compose_catalyst_flow_modifier(
            base_midpoint_pp=4.0,
            catalyst_direction=0,
            catalyst_magnitude=None,
            catalyst_magnitude_scaler=SCALER,
            flow_signal_bin="positive",
            flow_per_unit_pct=0.05,
            bound_pct=0.0,
        )


def test_determinism_identical_inputs():
    """INV-CFM-3: identical inputs produce identical output (no I/O, no clock)."""
    args = dict(
        base_midpoint_pp=4.5,
        catalyst_direction=1,
        catalyst_magnitude="medium",
        catalyst_magnitude_scaler=SCALER,
        flow_signal_bin="positive",
        flow_per_unit_pct=0.05,
        bound_pct=0.25,
    )
    r1 = compose_catalyst_flow_modifier(**args)
    r2 = compose_catalyst_flow_modifier(**args)
    assert r1.audit_string == r2.audit_string
    assert r1.combined_pp_clipped == r2.combined_pp_clipped


def test_integer_percent_bound_pct_raises():
    """INV-CFM-UNIT: bound_pct > 1.0 catches integer-percent unit confusion."""
    with pytest.raises(ValueError, match="FRACTIONAL"):
        compose_catalyst_flow_modifier(
            base_midpoint_pp=4.0,
            catalyst_direction=1,
            catalyst_magnitude="medium",
            catalyst_magnitude_scaler=SCALER,
            flow_signal_bin="positive",
            flow_per_unit_pct=0.05,
            bound_pct=25,  # raw parameters_active value — forgot /100
        )


def test_integer_percent_flow_per_unit_raises():
    """INV-CFM-UNIT: flow_per_unit_pct > 1.0 catches the unit error."""
    with pytest.raises(ValueError, match="FRACTIONAL|/100"):
        compose_catalyst_flow_modifier(
            base_midpoint_pp=4.0,
            catalyst_direction=0,
            catalyst_magnitude=None,
            catalyst_magnitude_scaler=SCALER,
            flow_signal_bin="positive",
            flow_per_unit_pct=5,  # raw integer-percent — forgot /100
            bound_pct=0.25,
        )


def test_integer_percent_magnitude_scaler_raises():
    """INV-CFM-UNIT: scaler values > 1.0 catches the unit error."""
    raw_scaler = {"low": 5, "medium": 10, "high": 20}  # raw integer-percent
    with pytest.raises(ValueError, match="FRACTIONAL|/100"):
        compose_catalyst_flow_modifier(
            base_midpoint_pp=4.0,
            catalyst_direction=1,
            catalyst_magnitude="medium",
            catalyst_magnitude_scaler=raw_scaler,
            flow_signal_bin="positive",
            flow_per_unit_pct=0.05,
            bound_pct=0.25,
        )


def test_none_flow_signal_bin_treated_as_offline():
    """None envelope on disk → coerced to 'offline' (zero contribution) per pm-supervisor §6 contract."""
    r = compose_catalyst_flow_modifier(
        base_midpoint_pp=4.0,
        catalyst_direction=1,
        catalyst_magnitude="medium",
        catalyst_magnitude_scaler=SCALER,
        flow_signal_bin=None,
        flow_per_unit_pct=0.05,
        bound_pct=0.25,
    )
    assert r.flow_signal_bin == "offline"
    assert r.flow_sign == 0
    assert r.flow_pp_unclipped == 0.0
    assert r.combined_pp_clipped == pytest.approx(0.40)


def test_audit_string_shape():
    """Audit string reconstructs the math from named segments."""
    r = compose_catalyst_flow_modifier(
        base_midpoint_pp=4.0,
        catalyst_direction=1,
        catalyst_magnitude="medium",
        catalyst_magnitude_scaler=SCALER,
        flow_signal_bin="positive",
        flow_per_unit_pct=0.05,
        bound_pct=0.25,
        catalyst_reason="2 high-confidence catalysts",
        flow_reason="positive ticker + SPY trend",
    )
    assert "catalyst" in r.audit_string
    assert "flow" in r.audit_string
    assert "bound" in r.audit_string
    assert "+0.60pp" in r.audit_string or "0.60pp" in r.audit_string
