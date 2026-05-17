"""Tests for src.calibration.brier."""

from __future__ import annotations

import pytest

from src.calibration.brier import (
    BRIER_RANDOM_BASELINE,
    BrierScope,
    _aggregate,
    _favorable,
    apply_haircut,
)


# --------------------------------------------------------------------------- #
# _favorable                                                                  #
# --------------------------------------------------------------------------- #


def test_favorable_buy_outperformed():
    assert _favorable("BUY", 0.05) == 1


def test_favorable_buy_underperformed():
    assert _favorable("BUY", -0.02) == 0


def test_favorable_sell_outperformed_means_underperform():
    # SELL favorable = name underperformed benchmark = delta < 0
    assert _favorable("SELL", -0.10) == 1
    assert _favorable("SELL", 0.05) == 0


def test_favorable_hold_within_tolerance_band():
    assert _favorable("HOLD", 0.01) == 1
    assert _favorable("HOLD", -0.005) == 1
    assert _favorable("HOLD", 0.05) == 0


def test_favorable_null_delta_returns_none():
    assert _favorable("BUY", None) is None


def test_favorable_unknown_rec_type_returns_none():
    assert _favorable("UNKNOWN", 0.05) is None


# --------------------------------------------------------------------------- #
# _aggregate                                                                  #
# --------------------------------------------------------------------------- #


def _row(mode, materiality, rec_type, conviction, delta):
    return (mode, materiality, rec_type, conviction, delta)


def test_aggregate_global_brier_sanity():
    """Two HIGH-BUYs that BOTH won → Brier = (0.7-1)^2 = 0.09."""
    rows = [
        _row("B", "cadence", "BUY", "HIGH", 0.05),
        _row("B", "cadence", "BUY", "HIGH", 0.10),
    ]
    cells = _aggregate(rows, scope=BrierScope.GLOBAL, horizon="90d")
    assert len(cells) == 1
    assert cells[0].n == 2
    assert cells[0].brier == pytest.approx(0.09)
    assert cells[0].mean_predicted == pytest.approx(0.7)
    assert cells[0].mean_realized == pytest.approx(1.0)


def test_aggregate_global_brier_baseline_when_random_calls_random():
    """MEDIUM (0.5 prior) calls split 50/50 → Brier = 0.25 (random baseline)."""
    rows = [
        _row("B", "cadence", "BUY", "MEDIUM", 0.05),   # win
        _row("B", "cadence", "BUY", "MEDIUM", -0.05),  # loss
    ]
    cells = _aggregate(rows, scope=BrierScope.GLOBAL, horizon="90d")
    assert cells[0].brier == pytest.approx(BRIER_RANDOM_BASELINE)


def test_aggregate_by_cell_partitions():
    rows = [
        _row("B", "cadence", "BUY", "HIGH", 0.05),
        _row("B_prime", "cadence", "BUY", "HIGH", 0.05),
    ]
    cells = _aggregate(rows, scope=BrierScope.BY_CELL, horizon="90d")
    assert len(cells) == 2
    keys = {c.scope_key for c in cells}
    assert keys == {("B", "cadence", "BUY"), ("B_prime", "cadence", "BUY")}


def test_aggregate_skips_unknown_conviction_or_rec():
    rows = [
        _row("B", "cadence", "BUY", "HIGH", 0.05),
        _row("B", "cadence", "BUY", "BOGUS", 0.05),     # bad conviction → skip
        _row("B", "cadence", "WEIRD", "HIGH", 0.05),    # bad rec_type → skip
        _row("B", "cadence", "BUY", "HIGH", None),      # NULL delta → skip
    ]
    cells = _aggregate(rows, scope=BrierScope.GLOBAL, horizon="90d")
    assert cells[0].n == 1


# --------------------------------------------------------------------------- #
# apply_haircut                                                               #
# --------------------------------------------------------------------------- #


def test_haircut_at_or_below_baseline_no_demote():
    assert apply_haircut("HIGH", 0.20) == "HIGH"
    assert apply_haircut("HIGH", 0.25) == "HIGH"
    assert apply_haircut("MEDIUM", 0.10) == "MEDIUM"


def test_haircut_one_step_demote():
    # excess = 0.05 → 1 step
    assert apply_haircut("HIGH", 0.30) == "MEDIUM"
    assert apply_haircut("MEDIUM", 0.30) == "LOW"


def test_haircut_clamps_at_low():
    assert apply_haircut("LOW", 0.50) == "LOW"
    assert apply_haircut("HIGH", 0.99) == "LOW"


def test_haircut_invalid_conviction_raises():
    with pytest.raises(ValueError):
        apply_haircut("ULTRA", 0.30)
