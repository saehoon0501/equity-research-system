"""Tests for src.regime_sidecar.bma."""

from __future__ import annotations

import math

import pytest

from src.regime_sidecar.bma import (
    bb_stabilize,
    compute_pseudo_bma_plus,
    diebold_pauly_shrunk,
    shrunk_bb_pseudo_bma_plus,
)


# --------------------------------------------------------------------------- #
# pseudo-BMA+                                                                 #
# --------------------------------------------------------------------------- #


def test_pseudo_bma_uniform_input_equal_weights():
    """If every dim has identical lpd, weights should be uniform."""
    K, N = 6, 50
    lpd = [[-0.5] * N for _ in range(K)]
    res = compute_pseudo_bma_plus(lpd)
    for w in res.weights:
        assert w == pytest.approx(1.0 / K)
    assert sum(res.weights) == pytest.approx(1.0)


def test_pseudo_bma_dominant_dim_takes_most_weight():
    """A clearly-better-calibrated dim should grab >50% weight."""
    K, N = 3, 50
    lpd = [
        [-0.1] * N,   # very accurate
        [-1.0] * N,   # mediocre
        [-1.0] * N,
    ]
    res = compute_pseudo_bma_plus(lpd)
    assert res.weights[0] > 0.5
    assert res.weights[1] < 0.3
    assert sum(res.weights) == pytest.approx(1.0)


def test_pseudo_bma_validates_input():
    with pytest.raises(ValueError):
        compute_pseudo_bma_plus([])
    with pytest.raises(ValueError):
        compute_pseudo_bma_plus([[]])
    with pytest.raises(ValueError):
        compute_pseudo_bma_plus([[1.0, 2.0], [1.0]])  # ragged


def test_pseudo_bma_clamps_extreme_lpd():
    """A single near-impossible prediction shouldn't drive a dim to zero."""
    K, N = 3, 5
    lpd = [
        [-0.5] * N,
        [-0.5] * N,
        [-0.5] * (N - 1) + [-1e9],   # one catastrophic pointwise lpd
    ]
    res = compute_pseudo_bma_plus(lpd)
    # Without clamping, dim 2 would have weight ≈ 0.
    # With clamping, it's reduced but non-trivial.
    assert res.weights[2] > 1e-4


# --------------------------------------------------------------------------- #
# BB stabilization                                                            #
# --------------------------------------------------------------------------- #


def test_bb_stabilize_uniform_input_yields_uniform_weights():
    K, N = 6, 30
    lpd = [[-0.5] * N for _ in range(K)]
    res = bb_stabilize(lpd, n_bootstrap=50, seed=42)
    for w in res.weights:
        assert w == pytest.approx(1.0 / K, abs=0.05)
    assert sum(res.weights) == pytest.approx(1.0)


def test_bb_stabilize_deterministic_with_seed():
    K, N = 4, 20
    lpd = [[-0.1 * (d + 1)] * N for d in range(K)]
    a = bb_stabilize(lpd, n_bootstrap=30, seed=7)
    b = bb_stabilize(lpd, n_bootstrap=30, seed=7)
    assert a.weights == b.weights


def test_bb_stabilize_signal_propagates():
    """Better dim still wins under BB stabilization."""
    K, N = 3, 30
    lpd = [
        [-0.05] * N,
        [-2.0] * N,
        [-2.0] * N,
    ]
    res = bb_stabilize(lpd, n_bootstrap=100, seed=1)
    assert res.weights[0] > res.weights[1]
    assert res.weights[0] > res.weights[2]


# --------------------------------------------------------------------------- #
# Diebold-Pauly shrinkage                                                     #
# --------------------------------------------------------------------------- #


def test_shrinkage_at_n_zero_recovers_equal_weight():
    """N=0 → all-equal-weight."""
    bma = [0.7, 0.2, 0.1]
    out = diebold_pauly_shrunk(bma, n=0)
    for w in out:
        assert w == pytest.approx(1 / 3)


def test_shrinkage_pulls_toward_equal_weight_at_small_n():
    """N=10 → shrinkage strong; output weight closer to 1/K than to bma."""
    K = 3
    bma = [0.7, 0.2, 0.1]
    out = diebold_pauly_shrunk(bma, n=10)
    # blend coef on bma = 10/48 ≈ 0.208; on equal = 38/48 ≈ 0.792
    expected_first = 0.792 * (1 / K) + 0.208 * 0.7
    assert out[0] == pytest.approx(expected_first, abs=1e-3)
    # Weight should be much closer to 1/K than to 0.7
    assert abs(out[0] - 1 / K) < abs(out[0] - 0.7)


def test_shrinkage_at_large_n_approaches_bma():
    """N=1000 → shrinkage minimal; output ≈ bma."""
    bma = [0.7, 0.2, 0.1]
    out = diebold_pauly_shrunk(bma, n=1000)
    for o, b in zip(out, bma):
        assert abs(o - b) < 0.04   # within 4% absolute


def test_shrunk_output_normalizes():
    bma = [0.7, 0.2, 0.1]
    out = diebold_pauly_shrunk(bma, n=42)
    assert sum(out) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# All-in-one                                                                  #
# --------------------------------------------------------------------------- #


def test_shrunk_bb_at_v05_entry_holds_meaningful_equal_weight_anchor():
    """At N=30 (v0.5 shadow trigger), shrinkage weight on equal-weight =
    38/(38+30) = 0.559. The equal-weight anchor still contributes >=50%
    of the final blend even when the data screams for one dim.
    """
    K, N = 6, 30
    lpd = [
        [-0.05] * N,                                  # dim 0 nearly perfect
        [-2.0] * N, [-2.0] * N, [-2.0] * N, [-2.0] * N, [-2.0] * N,
    ]
    res = shrunk_bb_pseudo_bma_plus(lpd, n_bootstrap=50, seed=1)
    # The 5 'losing' dims should each carry weight ≥ 0.559/6 ≈ 0.093 from
    # the equal-weight anchor floor, even when data assigns them ~0 BMA mass.
    for w in res.weights[1:]:
        assert w >= 0.55 / K * 0.9  # 10% slack for FP / BB noise
    # And dim 0 takes substantial weight from the BMA component.
    assert res.weights[0] >= 0.30
    assert sum(res.weights) == pytest.approx(1.0)


def test_shrunk_bb_at_v05_entry_with_uniform_data_yields_equal_weight():
    """If all dims have identical lpd, shrinkage + equal-weight anchor → 1/K."""
    K, N = 6, 30
    lpd = [[-0.5] * N for _ in range(K)]
    res = shrunk_bb_pseudo_bma_plus(lpd, n_bootstrap=50, seed=1)
    for w in res.weights:
        assert w == pytest.approx(1 / K, abs=0.05)
