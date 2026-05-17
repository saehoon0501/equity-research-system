"""Unit tests for src.evaluator_gates.sizing_math (HG-25, Group C)."""

from __future__ import annotations

import pytest

from src.evaluator_gates.sizing_math import (
    CONVICTION_BANDS,
    MODE_MULTIPLIERS,
    validate_sizing_math,
)


def _env(**overrides) -> dict:
    """Build a minimal envelope for sizing-math checks. summary_code=BUY by
    default so size_band_if_long must match the expected band."""
    base = {
        "ticker": "TEST",
        "conviction": "HIGH",
        "mode": "B",
        "tier": "core_fundamental",
        "summary_code": "BUY",
        "size_band_if_long": {
            "min_book_pct": 3.0,
            "max_book_pct": 6.0,
            "midpoint": 4.5,
        },
    }
    base.update(overrides)
    return base


def test_high_b_core_passes() -> None:
    r = validate_sizing_math(_env())
    assert r.valid, r.notes


def test_medium_b_core_passes() -> None:
    r = validate_sizing_math(_env(
        conviction="MEDIUM",
        size_band_if_long={"min_book_pct": 1.5, "max_book_pct": 3.0, "midpoint": 2.25},
    ))
    assert r.valid, r.notes


def test_high_b_prime_half_size() -> None:
    """HIGH × B' (0.5×) = (1.5, 3.0, 2.25)."""
    r = validate_sizing_math(_env(
        mode="B_prime",
        size_band_if_long={"min_book_pct": 1.5, "max_book_pct": 3.0, "midpoint": 2.25},
    ))
    assert r.valid, r.notes


def test_high_c_third_size() -> None:
    """HIGH × C (0.333×) ≈ (1.0, 2.0, 1.5). RKLB bug: emitted Mode C as 0.5×."""
    r = validate_sizing_math(_env(
        mode="C",
        size_band_if_long={
            "min_book_pct": round(3.0 / 3.0, 4),
            "max_book_pct": round(6.0 / 3.0, 4),
            "midpoint": 1.50,
        },
    ))
    assert r.valid, r.notes


def test_rklb_mode_c_wrong_multiplier_fails() -> None:
    """RKLB emitted Mode C with ~0.5× multiplier instead of ~0.333×.

    Correct: MEDIUM × C = (1.5, 3.0, 2.25) × 0.333 ≈ (0.5, 1.0, 0.75).
    Bug:     MEDIUM × C emitted as (1.5, 3.0, 2.25) × 0.5 = (0.75, 1.5, 1.125).
    """
    r = validate_sizing_math(_env(
        conviction="MEDIUM",
        mode="C",
        size_band_if_long={"min_book_pct": 0.75, "max_book_pct": 1.5, "midpoint": 1.125},
    ))
    assert not r.valid
    assert r.min_delta is not None and abs(r.min_delta) > r.epsilon


def test_non_buy_band_must_be_zero() -> None:
    """summary_code != BUY ⇒ size_band_if_long must be all zeros."""
    r = validate_sizing_math(_env(
        summary_code="HOLD",
        size_band_if_long={"min_book_pct": 3.0, "max_book_pct": 6.0, "midpoint": 4.5},
    ))
    assert not r.valid
    assert any("non-zero" in n for n in r.notes)


def test_non_buy_zero_band_passes() -> None:
    r = validate_sizing_math(_env(
        summary_code="HOLD",
        size_band_if_long={"min_book_pct": 0.0, "max_book_pct": 0.0, "midpoint": 0.0},
    ))
    assert r.valid, r.notes


def test_would_be_size_audit_trace_validated() -> None:
    """When summary_code != BUY, the would_be_size_* trace must match."""
    r = validate_sizing_math({
        "ticker": "TEST",
        "conviction": "MEDIUM",
        "mode": "B",
        "tier": "core_fundamental",
        "summary_code": "HOLD",
        "size_band_if_long": {"min_book_pct": 0.0, "max_book_pct": 0.0, "midpoint": 0.0},
        "would_be_size_at_medium_mode_B": {
            "min_book_pct": 1.5,
            "max_book_pct": 3.0,
            "midpoint": 2.25,
        },
    })
    assert r.valid, r.notes


def test_speculative_tier_requires_sleeve_reference() -> None:
    """speculative_optionality MUST have a sleeve_reference block."""
    r = validate_sizing_math(_env(
        tier="speculative_optionality",
        # no sleeve_reference
    ))
    assert not r.valid
    assert any("sleeve_reference" in n for n in r.notes)


def test_speculative_tier_clip_to_headroom() -> None:
    """RGTI: HIGH conviction × B mode = 3-6%, but speculative headroom 4.0%
    forces clip to max=4.0, midpoint=3.5."""
    r = validate_sizing_math({
        "ticker": "RGTI",
        "conviction": "HIGH",
        "mode": "B",
        "tier": "speculative_optionality",
        "summary_code": "BUY",
        "size_band_if_long": {"min_book_pct": 3.0, "max_book_pct": 4.0, "midpoint": 3.5},
        "sleeve_reference": {
            "tier_cap": 8.0,
            "current_aggregate": 4.0,
            "headroom": 4.0,
            "clipped_to_headroom": True,
        },
    })
    assert r.valid, r.notes


def test_speculative_unclipped_when_should_be_clipped_fails() -> None:
    """RGTI bug: emitted full 3-6% band when headroom was only 4%."""
    r = validate_sizing_math({
        "ticker": "RGTI",
        "conviction": "HIGH",
        "mode": "B",
        "tier": "speculative_optionality",
        "summary_code": "BUY",
        "size_band_if_long": {"min_book_pct": 3.0, "max_book_pct": 6.0, "midpoint": 4.5},
        "sleeve_reference": {
            "tier_cap": 8.0,
            "current_aggregate": 4.0,
            "headroom": 4.0,
        },
    })
    assert not r.valid


def test_unknown_conviction_fails() -> None:
    r = validate_sizing_math(_env(conviction="MEGA"))
    assert not r.valid
    assert any("conviction" in n and "MEGA" in n for n in r.notes)


def test_unknown_mode_fails() -> None:
    r = validate_sizing_math(_env(mode="A"))
    assert not r.valid
    assert any("mode" in n and "'A'" in n for n in r.notes)


def test_constants_match_spec() -> None:
    """Pin the spec table values: HIGH (3, 6, 4.5), MEDIUM (1.5, 3, 2.25), LOW zero."""
    assert CONVICTION_BANDS["HIGH"] == (3.0, 6.0, 4.5)
    assert CONVICTION_BANDS["MEDIUM"] == (1.5, 3.0, 2.25)
    assert CONVICTION_BANDS["LOW"] == (0.0, 0.0, 0.0)
    assert MODE_MULTIPLIERS["B"] == 1.0
    assert MODE_MULTIPLIERS["B'"] == 0.5
    assert MODE_MULTIPLIERS["B_prime"] == 0.5
    assert abs(MODE_MULTIPLIERS["C"] - 1.0 / 3.0) < 1e-9
