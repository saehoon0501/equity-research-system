"""Tests for TacticalSignal frozen dataclass — cross-plan handoff contract."""

from datetime import date

import pytest

from src.p8_tactical_overlay.contracts import (
    Conviction,
    TacticalBin,
    TacticalDisposition,
    TacticalSignal,
)


def test_tactical_signal_constructs_valid():
    sig = TacticalSignal(
        ticker="GOOGL",
        as_of_date=date(2026, 5, 20),
        tactical_bin="positive",
        rf_degenerate=False,
        unavailable_reason=None,
    )
    assert sig.ticker == "GOOGL"
    assert sig.tactical_bin == "positive"


def test_tactical_signal_frozen_dataclass_rejects_mutation():
    sig = TacticalSignal(
        ticker="GOOGL",
        as_of_date=date(2026, 5, 20),
        tactical_bin="positive",
        rf_degenerate=False,
    )
    with pytest.raises(Exception):  # frozen → FrozenInstanceError
        sig.tactical_bin = "negative"  # type: ignore[misc]


def test_tactical_disposition_enum_values():
    """INV-2.1-A: tactical_disposition enum (BUY-HIGH/BUY-MED/HOLD/AVOID)."""
    expected = {"HOLD", "BUY-HIGH", "BUY-MED", "AVOID"}
    assert set(TacticalDisposition.__args__) == expected


def test_tactical_bin_enum_values():
    expected = {"positive", "neutral", "negative", "unavailable"}
    assert set(TacticalBin.__args__) == expected


def test_conviction_enum_values():
    expected = {"HIGH", "MEDIUM", "LOW"}
    assert set(Conviction.__args__) == expected


def test_unavailable_reason_optional():
    sig = TacticalSignal(
        ticker="RDDT",
        as_of_date=date(2026, 5, 20),
        tactical_bin="unavailable",
        rf_degenerate=False,
        unavailable_reason="insufficient_price_history",
    )
    assert sig.unavailable_reason == "insufficient_price_history"


def test_canonical_buy_not_in_tactical_disposition():
    """Section 2.1 v5-final: canonical BUY MUST NOT appear in tactical_disposition."""
    assert "BUY" not in TacticalDisposition.__args__
