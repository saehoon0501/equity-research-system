"""Unit tests for src.evaluator_gates.outside_view_blend (Group F AMZN math)."""

from __future__ import annotations

import pytest

from src.evaluator_gates.outside_view_blend import (
    DEFAULT_EPSILON_PP,
    validate_outside_view_blend,
)


def test_correct_blend_passes() -> None:
    """intuitive=15.95, reference=11.0, r=0.20 → corrected=14.96, raw_div=4.95, corrected_div=3.96"""
    block = {
        "intuitive_growth_pct": 15.95,
        "reference_class_growth_mean_pct": 11.0,
        "r_coefficient_used": 0.20,
        "corrected_growth_pct": 14.96,
        "outside_view_divergence_pp_raw": 4.95,
        "corrected_divergence_pp": 3.96,
    }
    r = validate_outside_view_blend(block)
    assert r.valid, r.notes


def test_amzn_signature_caught() -> None:
    """AMZN 2026-05-14: raw == corrected == -0.80 with r=0.20 is the
    classic 'skipped the blend' signature."""
    block = {
        "intuitive_growth_pct": 8.20,
        "reference_class_growth_mean_pct": 9.00,
        "r_coefficient_used": 0.20,
        "corrected_growth_pct": 8.20,            # WRONG — should be 8.36
        "outside_view_divergence_pp_raw": -0.80,
        "corrected_divergence_pp": -0.80,        # WRONG — should be -0.64
    }
    r = validate_outside_view_blend(block)
    assert not r.valid
    assert any("AMZN-signature" in n for n in r.notes)


def test_zero_r_makes_raw_equal_corrected_legitimately() -> None:
    """When r=0 the blend collapses to intuitive; raw==corrected is OK."""
    block = {
        "intuitive_growth_pct": 12.0,
        "reference_class_growth_mean_pct": 9.0,
        "r_coefficient_used": 0.0,
        "corrected_growth_pct": 12.0,
        "outside_view_divergence_pp_raw": 3.0,
        "corrected_divergence_pp": 3.0,
    }
    r = validate_outside_view_blend(block)
    assert r.valid, r.notes


def test_missing_inputs_skips_check() -> None:
    """Speculative tier may emit sentinel strings; check should skip not fail."""
    block = {
        "intuitive_growth_pct": "N/A speculative skip",
        "reference_class_growth_mean_pct": None,
        "r_coefficient_used": 0.20,
    }
    r = validate_outside_view_blend(block)
    assert r.valid
    assert any("speculative" in n.lower() or "non-numeric" in n for n in r.notes)


def test_corrected_off_by_epsilon_fails() -> None:
    block = {
        "intuitive_growth_pct": 15.95,
        "reference_class_growth_mean_pct": 11.0,
        "r_coefficient_used": 0.20,
        "corrected_growth_pct": 14.50,  # off by ~0.46pp
        "outside_view_divergence_pp_raw": 4.95,
        "corrected_divergence_pp": 3.96,
    }
    r = validate_outside_view_blend(block)
    assert not r.valid
    assert any("does not match" in n for n in r.notes)


def test_r_out_of_range_invalid() -> None:
    block = {
        "intuitive_growth_pct": 15.0,
        "reference_class_growth_mean_pct": 11.0,
        "r_coefficient_used": 1.5,  # outside [0, 1]
        "corrected_growth_pct": 12.0,
    }
    r = validate_outside_view_blend(block)
    assert not r.valid
    assert any("outside [0, 1]" in n for n in r.notes)


def test_non_dict_fails() -> None:
    r = validate_outside_view_blend("not a dict")
    assert not r.valid


def test_epsilon_default_constant() -> None:
    assert DEFAULT_EPSILON_PP == 0.05
