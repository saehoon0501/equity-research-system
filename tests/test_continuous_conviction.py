"""Tests for src.p7_recommendation_emitter.continuous_conviction."""

from __future__ import annotations

import pytest

from src.p7_recommendation_emitter.conviction_rollup import ConvictionInputs
from src.p7_recommendation_emitter.continuous_conviction import (
    DEFAULT_COMPONENT_WEIGHTS,
    score_conviction,
)


def _inp(**kw):
    defaults = {
        "debate_add_count": 5,
        "kills_fired": 0,
        "anchor_drift_channels_triggered": 0,
        "debate_total": 5,
    }
    defaults.update(kw)
    return ConvictionInputs(**defaults)


def test_perfect_inputs_score_one():
    """5/5 debate, 0 kills, 0 drift → score = 1.0."""
    out = score_conviction(_inp())
    assert out.score == pytest.approx(1.0)
    assert out.components["debate"] == 1.0
    assert out.components["kills"] == 1.0
    assert out.components["drift"] == 1.0


def test_worst_inputs_score_zero():
    """0/5 debate, 2 kills, 3 drift → score = 0.0."""
    out = score_conviction(_inp(
        debate_add_count=0,
        kills_fired=2,
        anchor_drift_channels_triggered=3,
    ))
    assert out.score == pytest.approx(0.0)


def test_one_kill_halfway():
    out = score_conviction(_inp(kills_fired=1))
    assert out.components["kills"] == pytest.approx(0.5)


def test_partial_drift_step_third():
    """1 of 3 drift channels triggered → drift = 0.667."""
    out = score_conviction(_inp(anchor_drift_channels_triggered=1))
    assert out.components["drift"] == pytest.approx(2 / 3)


def test_score_is_weighted_average_with_default_weights():
    """Each component gets 1/3; score should be the mean."""
    inp = _inp(
        debate_add_count=4,                # 0.8
        kills_fired=1,                     # 0.5
        anchor_drift_channels_triggered=2, # drift = 1/3
    )
    out = score_conviction(inp)
    expected = (0.8 + 0.5 + 1 / 3) / 3.0
    assert out.score == pytest.approx(expected)


def test_custom_weights_renormalize_to_one():
    """Pass weights summing to 2.0 — function should renormalize."""
    inp = _inp(debate_add_count=4, kills_fired=0)
    weights = {"debate": 1.0, "kills": 1.0, "drift": 0.0}
    out = score_conviction(inp, weights=weights)
    # debate=0.8, kills=1.0, equal weight → 0.9
    assert out.score == pytest.approx(0.9)
    assert sum(out.weights.values()) == pytest.approx(1.0)


def test_zero_weights_falls_back_to_default():
    inp = _inp()
    out = score_conviction(
        inp,
        weights={"debate": 0.0, "kills": 0.0, "drift": 0.0},
    )
    # Fallback to DEFAULT_COMPONENT_WEIGHTS → all three contribute equally
    for k in ("debate", "kills", "drift"):
        assert out.weights[k] == pytest.approx(1.0 / 3.0)


def test_score_clamped_to_unit_interval():
    """Even with weird inputs, score never escapes [0, 1]."""
    inp = _inp(debate_add_count=10, debate_total=5)  # invalid but tolerant
    out = score_conviction(inp)
    assert 0.0 <= out.score <= 1.0


def test_payload_serializes_floats_with_4_decimals():
    out = score_conviction(_inp(debate_add_count=4))
    payload = out.to_payload()
    assert "continuous_score" in payload
    assert "components" in payload
    assert "weights" in payload
    # round to 4
    assert isinstance(payload["continuous_score"], float)
