"""Tests for flow overlay (cell-size selector + disposition mapping)."""

import pytest

from src.overlays.flow.overlay import (
    disposition_map,
    flow_cell_size_pct,
    flow_disposition,
)


# ---------- flow_cell_size_pct -----------------------------------------


def test_high_positive_uses_band_max():
    assert flow_cell_size_pct("HIGH", "positive", 3.0, 6.0) == 6.0


def test_medium_positive_uses_band_max():
    assert flow_cell_size_pct("MEDIUM", "positive", 1.5, 3.0) == 3.0


def test_high_neutral_uses_midpoint():
    assert flow_cell_size_pct("HIGH", "neutral", 3.0, 6.0) == 4.5


def test_high_negative_uses_band_min():
    assert flow_cell_size_pct("HIGH", "negative", 3.0, 6.0) == 3.0


def test_high_unavailable_uses_band_min():
    """unavailable defers to band.min (conservative; symmetric with absent-evidence)."""
    assert flow_cell_size_pct("HIGH", "unavailable", 3.0, 6.0) == 3.0


def test_low_conviction_hard_zero():
    """LOW row hard-zero regardless of flow_bin."""
    for flow_bin in ("positive", "neutral", "negative", "unavailable"):
        assert flow_cell_size_pct("LOW", flow_bin) == 0.0


def test_non_low_requires_band_params():
    with pytest.raises(ValueError):
        flow_cell_size_pct("HIGH", "positive")
    with pytest.raises(ValueError):
        flow_cell_size_pct("MEDIUM", "positive", band_min_pct=1.5)  # max missing


# ---------- flow_disposition --------------------------------------------


def test_high_positive_buy_high():
    assert flow_disposition("HIGH", "positive") == "BUY-HIGH"


def test_medium_positive_buy_med():
    assert flow_disposition("MEDIUM", "positive") == "BUY-MED"


def test_high_unavailable_hold():
    assert flow_disposition("HIGH", "unavailable") == "HOLD"


def test_low_positive_avoid():
    """LOW × positive → AVOID (LOW-row veto)."""
    assert flow_disposition("LOW", "positive") == "AVOID"


def test_low_unavailable_hold():
    """LOW × unavailable → HOLD (data-insufficiency defers; no double-penalty)."""
    assert flow_disposition("LOW", "unavailable") == "HOLD"


def test_invalid_combination_raises():
    with pytest.raises(ValueError):
        flow_disposition("BOGUS", "positive")
    with pytest.raises(ValueError):
        flow_disposition("HIGH", "BOGUS")


def test_disposition_map_returns_copy():
    """disposition_map() must return a copy — not a reference to the private dict."""
    m1 = disposition_map()
    m2 = disposition_map()
    assert m1 == m2
    m1[("HIGH", "positive")] = "MUTATED"
    assert disposition_map()[("HIGH", "positive")] == "BUY-HIGH"


def test_disposition_map_complete_12_cells():
    """INV-FLOW-C1: every (conviction × flow_bin) cell is mapped."""
    m = disposition_map()
    assert len(m) == 12
    for conv in ("HIGH", "MEDIUM", "LOW"):
        for fb in ("positive", "neutral", "negative", "unavailable"):
            assert (conv, fb) in m


def test_inv_flow_2_1_a_all_dispositions_in_disjoint_enum():
    """INV-FLOW-2.1-A: every mapped disposition is in {HOLD, BUY-HIGH, BUY-MED, AVOID}."""
    valid = {"HOLD", "BUY-HIGH", "BUY-MED", "AVOID"}
    for disp in disposition_map().values():
        assert disp in valid, f"disposition {disp} violates INV-FLOW-2.1-A"
