"""Unit tests for src.eval.gates.sentiment_degradation (Bug 14)."""

from __future__ import annotations

from src.eval.gates.sentiment_degradation import (
    DEGRADATION_THRESHOLD,
    EXPECTED_INDICATOR_NAMES,
    compute_sentiment_data_degraded,
)


def _ind(name: str, reading=1.0, reading_date="2026-05-15", **extra) -> dict:
    """Build a generic available indicator block. Pass extra kwargs to
    override or add fields (e.g., reading=None to simulate unavailable)."""
    block = {
        "indicator": name,
        "reading": reading,
        "reading_date": reading_date,
        "historical_percentile": 50,
        "implication": "neutral",
    }
    block.update(extra)
    return block


def test_all_four_available_not_degraded():
    indicators = [
        _ind("BofA FMS cash level"),
        _ind("AAII bull-bear spread"),
        _ind("Investors Intelligence bull%"),
        _ind("NAAIM exposure"),
    ]
    r = compute_sentiment_data_degraded(indicators)
    assert r.degraded is False
    assert r.n_unavailable == 0
    assert set(r.available_names) == set(EXPECTED_INDICATOR_NAMES)
    assert r.indicators_missing_from_emission == []


def test_msft_bug14_three_unavailable_is_degraded():
    """MSFT 2026-05-15 regression: 3 of 4 sentiment indicators
    WebFetch-degraded; only NAAIM available."""
    indicators = [
        _ind("BofA FMS cash level", reading=None, reading_date=None),
        _ind("AAII bull-bear spread", reading=None, reading_date=None),
        _ind("Investors Intelligence bull%", reading=None, reading_date=None),
        _ind("NAAIM exposure", reading=77.34),
    ]
    r = compute_sentiment_data_degraded(indicators)
    assert r.degraded is True
    assert r.n_unavailable == 3
    assert r.available_names == ["NAAIM"]
    assert set(r.unavailable_names) == {
        "BofA FMS",
        "AAII",
        "Investors Intelligence",
    }


def test_one_unavailable_below_threshold():
    """Single unavailable indicator (n=1) stays below the n>=2 threshold."""
    indicators = [
        _ind("BofA FMS cash level"),
        _ind("AAII bull-bear spread"),
        _ind("Investors Intelligence bull%"),
        _ind("NAAIM exposure", reading=None, reading_date=None),
    ]
    r = compute_sentiment_data_degraded(indicators)
    assert r.degraded is False
    assert r.n_unavailable == 1


def test_two_unavailable_at_threshold():
    """Exactly 2 unavailable → degraded=true (>= threshold inclusive)."""
    indicators = [
        _ind("BofA FMS cash level"),
        _ind("AAII bull-bear spread"),
        _ind("Investors Intelligence bull%", reading=None, reading_date=None),
        _ind("NAAIM exposure", reading=None, reading_date=None),
    ]
    r = compute_sentiment_data_degraded(indicators)
    assert r.degraded is True
    assert r.n_unavailable == DEGRADATION_THRESHOLD


def test_indicator_entirely_missing_from_emission_counts_as_unavailable():
    """If an expected indicator never appears in the emission, it counts
    as unavailable. This catches sloppy agent emission patterns."""
    indicators = [
        _ind("BofA FMS cash level"),
        _ind("AAII bull-bear spread"),
        # Investors Intelligence + NAAIM entirely absent from emission
    ]
    r = compute_sentiment_data_degraded(indicators)
    assert r.degraded is True
    assert r.n_unavailable == 2
    assert "Investors Intelligence" in r.indicators_missing_from_emission
    assert "NAAIM" in r.indicators_missing_from_emission


def test_unknown_indicator_name_ignored():
    """Indicators with unrecognized names are ignored (does not count
    toward available/unavailable; the canonical 4 still rule)."""
    indicators = [
        _ind("BofA FMS cash level"),
        _ind("AAII bull-bear spread"),
        _ind("Investors Intelligence bull%"),
        _ind("NAAIM exposure"),
        _ind("Some Other Indicator The Agent Invented"),
    ]
    r = compute_sentiment_data_degraded(indicators)
    assert r.degraded is False
    assert r.n_unavailable == 0


def test_explicit_marker_fields_flag_unavailable():
    """Markers like error_class, data_unavailable=true, fetch_failed=true
    all flag the indicator as unavailable even if reading is populated."""
    indicators = [
        _ind("BofA FMS cash level", error_class="webfetch_timeout"),
        _ind("AAII bull-bear spread", data_unavailable=True),
        _ind("Investors Intelligence bull%", fetch_failed=True),
        _ind("NAAIM exposure"),
    ]
    r = compute_sentiment_data_degraded(indicators)
    assert r.degraded is True
    assert r.n_unavailable == 3


def test_implication_data_unavailable_flags_unavailable():
    """An indicator with implication='data-unavailable' (string sentinel)
    is treated as unavailable even if reading is non-null."""
    indicators = [
        _ind("BofA FMS cash level", implication="data-unavailable"),
        _ind("AAII bull-bear spread", implication="data_unavailable"),
        _ind("Investors Intelligence bull%"),
        _ind("NAAIM exposure"),
    ]
    r = compute_sentiment_data_degraded(indicators)
    assert r.degraded is True
    assert r.n_unavailable == 2


def test_empty_list_is_fully_degraded():
    r = compute_sentiment_data_degraded([])
    assert r.degraded is True
    assert r.n_unavailable == 4
    assert r.indicators_missing_from_emission == list(EXPECTED_INDICATOR_NAMES)


def test_non_list_input_handled_gracefully():
    r = compute_sentiment_data_degraded({"not": "a list"})  # type: ignore[arg-type]
    assert r.degraded is True
    assert r.n_unavailable == 4


def test_case_insensitive_substring_name_match():
    """Tolerates variations: 'bofa fms' lowercase matches 'BofA FMS'."""
    indicators = [
        _ind("bofa fms cash level"),
        _ind("aaii sentiment survey bull-bear spread"),
        _ind("investors intelligence newsletter bull pct"),
        _ind("NAAIM Exposure Index reading"),
    ]
    r = compute_sentiment_data_degraded(indicators)
    assert r.degraded is False
    assert r.n_unavailable == 0


def test_audit_trail_contains_per_name_breakdown():
    indicators = [
        _ind("BofA FMS cash level"),
        _ind("AAII bull-bear spread", reading=None, reading_date=None),
        _ind("Investors Intelligence bull%", reading=None, reading_date=None),
        _ind("NAAIM exposure"),
    ]
    r = compute_sentiment_data_degraded(indicators)
    assert r.degraded is True
    assert sorted(r.available_names) == ["BofA FMS", "NAAIM"]
    assert sorted(r.unavailable_names) == ["AAII", "Investors Intelligence"]
    assert r.threshold == DEGRADATION_THRESHOLD
    assert r.n_total_expected == 4
