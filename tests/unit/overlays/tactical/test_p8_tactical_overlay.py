"""Tests for tactical overlay: cell selector + tactical_disposition mapping."""

import pytest

from src.overlays.tactical.overlay import (
    _DISPOSITION_MAP,
    tactical_cell_size_pct,
    tactical_disposition,
)

HIGH_MIN, HIGH_MAX = 3.0, 6.0
MED_MIN, MED_MAX = 1.5, 3.0


def test_cell_size_high_positive_equals_band_max():
    assert tactical_cell_size_pct("HIGH", "positive", HIGH_MIN, HIGH_MAX) == 6.0


def test_cell_size_high_neutral_equals_midpoint():
    assert tactical_cell_size_pct("HIGH", "neutral", HIGH_MIN, HIGH_MAX) == 4.5


def test_cell_size_high_negative_equals_band_min():
    assert tactical_cell_size_pct("HIGH", "negative", HIGH_MIN, HIGH_MAX) == 3.0


def test_cell_size_high_unavailable_equals_band_min():
    """v3 fix: unavailable → band.min (closes IPO alpha leak vs midpoint)."""
    assert tactical_cell_size_pct("HIGH", "unavailable", HIGH_MIN, HIGH_MAX) == 3.0


def test_cell_size_medium_positive_equals_band_max():
    assert tactical_cell_size_pct("MEDIUM", "positive", MED_MIN, MED_MAX) == 3.0


def test_cell_size_medium_neutral_equals_midpoint():
    assert tactical_cell_size_pct("MEDIUM", "neutral", MED_MIN, MED_MAX) == 2.25


def test_cell_size_low_hardzero_regardless():
    """LOW row hard-zeroed; band params not required."""
    for tactical_bin in ("positive", "neutral", "negative", "unavailable"):
        assert tactical_cell_size_pct("LOW", tactical_bin) == 0.0


def test_cell_size_non_low_requires_bands():
    with pytest.raises(ValueError, match="requires band"):
        tactical_cell_size_pct("HIGH", "positive")


def test_tactical_disposition_high_positive_is_buy_high():
    assert tactical_disposition("HIGH", "positive") == "BUY-HIGH"


def test_tactical_disposition_medium_positive_is_buy_med():
    """Load-bearing consensus-fit case per empirical 83% MEDIUM base rate."""
    assert tactical_disposition("MEDIUM", "positive") == "BUY-MED"


def test_tactical_disposition_low_unavailable_is_hold():
    """Section 2.1 v4 fix: LOW × Unavailable = HOLD (not AVOID; data-insufficiency defers)."""
    assert tactical_disposition("LOW", "unavailable") == "HOLD"


def test_tactical_disposition_low_with_signal_is_avoid():
    for tactical_bin in ("positive", "neutral", "negative"):
        assert tactical_disposition("LOW", tactical_bin) == "AVOID"


def test_tactical_disposition_high_neutral_is_hold():
    assert tactical_disposition("HIGH", "neutral") == "HOLD"


def test_tactical_disposition_high_negative_is_hold():
    """Section 2 v3 case: no TRIM/SELL outputs from overlay (pm-supervisor domain)."""
    assert tactical_disposition("HIGH", "negative") == "HOLD"


def test_inv_c1_mapping_completeness():
    """INV-C1: tactical_disposition.mapping is complete over (3 conviction × 4 tactical_bin)."""
    valid_values = {"HOLD", "BUY-HIGH", "BUY-MED", "AVOID"}
    convictions = ("HIGH", "MEDIUM", "LOW")
    bins = ("positive", "neutral", "negative", "unavailable")
    assert len(_DISPOSITION_MAP) == 12, "INV-C1: expected exactly 12 cells"
    for conv in convictions:
        for tactical_bin in bins:
            result = tactical_disposition(conv, tactical_bin)
            assert result in valid_values, f"({conv},{tactical_bin}) → {result}"


def test_unknown_cell_raises():
    with pytest.raises(ValueError, match="INV-C1 violation"):
        tactical_disposition("BOGUS", "positive")


def test_no_trim_sell_in_overlay_mapping():
    """Section 2 v3: tactical_disposition does NOT emit TRIM/SELL (pm-supervisor domain)."""
    forbidden = {"TRIM", "SELL"}
    mapping_values = set(_DISPOSITION_MAP.values())
    assert mapping_values & forbidden == set()


def test_no_canonical_buy_in_overlay_mapping():
    """INV-2.1-A: canonical BUY MUST NOT appear; only BUY-HIGH and BUY-MED."""
    mapping_values = set(_DISPOSITION_MAP.values())
    assert "BUY" not in mapping_values
    assert "BUY-HIGH" in mapping_values
    assert "BUY-MED" in mapping_values
