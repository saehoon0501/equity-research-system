"""Unit tests for src.eval.gates.catalyst_memo_shape (HG-31)."""

from __future__ import annotations

import uuid

import pytest

from src.eval.gates.catalyst_memo_shape import (
    VALID_ACTIVE_MANAGER_READS,
    VALID_CATALYST_TYPES,
    VALID_KPI_IMPACTS,
    validate_catalyst_memo_shape,
)


def _u() -> str:
    return str(uuid.uuid4())


def _memo() -> dict:
    """Minimal catalyst-scout memo passing all checks."""
    return {
        "ticker": "MSFT",
        "tier": "core_fundamental",
        "as_of": "2026-05-15T11:50:00Z",
        "catalysts": [
            {
                "date": "2026-07-30",
                "type": "earnings",
                "source": "yfinance calendar",
                "kpi_impact": "EPS",
                "confidence": "high",
            },
        ],
        "positioning": {
            "tier_insufficient": False,
            "iv_spread": -0.85,
            "framework_keys": [
                "cremers_weinbaum_iv_spread_2008",
                "pan_poteshman_pcratio_2006",
            ],
        },
        "institutional_flow": {
            "top10_holders": [
                {"holder": "BlackRock", "shares": 100, "pct_held": 8.1,
                 "classification": "PASSIVE", "rationale": "S&P 500 index fund"},
            ],
            "active_pct_of_float": 4.4,
            "passive_pct_of_float": 23.75,
            "deltas_via_13ga": [],
            "next_13f_deadline": {
                "deadline_date": "2026-08-15",
                "days_to_deadline": 92,
                "active_manager_q_over_q_unavailable_until": "2026-08-15",
            },
            "active_manager_conviction_read": "INCONCLUSIVE",
            "flow_driver_attribution": "passive baseline + retail mix",
        },
        "sentiment_signals": [
            {
                "indicator": "BofA FMS cash level",
                "reading": 4.1,
                "reading_date": "2026-05-13",
                "implication": "neutral",
            },
            {
                "indicator": "AAII bull-bear spread",
                "reading": None,
                "reading_date": None,
                "implication": "data-unavailable",
                "data_unavailable": True,
            },
            {
                "indicator": "Investors Intelligence bull%",
                "reading": None,
                "reading_date": None,
                "implication": "data-unavailable",
                "data_unavailable": True,
            },
            {
                "indicator": "NAAIM exposure",
                "reading": 77.34,
                "reading_date": "2026-05-13",
                "implication": "neutral",
            },
        ],
        "sentiment_data_degraded": True,  # matches re-count (2 of 4 unavailable)
        "sentiment_data_unavailable_names": [
            "AAII bull-bear spread",
            "Investors Intelligence bull%",
        ],
        "conviction_modifier": {
            "direction": 0,
            "magnitude": "low",
            "reason": "neutral routine positioning + sentiment degraded",
        },
        "evidence_index_refs": [_u()],
        "banned_outputs_check": "PASS",
    }


def test_clean_memo_passes() -> None:
    r = validate_catalyst_memo_shape(_memo())
    assert r.valid, r.notes


def test_sentiment_degraded_mismatch_caught() -> None:
    """If emitted flag disagrees with re-count, gate fails."""
    memo = _memo()
    memo["sentiment_data_degraded"] = False  # WRONG — actually 2 unavailable
    r = validate_catalyst_memo_shape(memo)
    assert not r.valid
    assert r.sentiment_degraded_mismatch
    assert r.sentiment_degraded_emitted is False
    assert r.sentiment_degraded_recomputed is True


def test_missing_sentiment_indicator_caught() -> None:
    memo = _memo()
    memo["sentiment_signals"] = memo["sentiment_signals"][:3]  # drop NAAIM
    r = validate_catalyst_memo_shape(memo)
    assert not r.valid
    assert "NAAIM" in r.sentiment_indicators_missing


def test_invalid_conviction_modifier_direction() -> None:
    memo = _memo()
    memo["conviction_modifier"]["direction"] = 2  # not in {-1, 0, +1}
    r = validate_catalyst_memo_shape(memo)
    assert not r.valid
    assert any("direction" in v for v in r.invalid_modifier_values)


def test_invalid_catalyst_type_caught() -> None:
    memo = _memo()
    memo["catalysts"][0]["type"] = "vibes_check"  # not in canonical enum
    r = validate_catalyst_memo_shape(memo)
    assert not r.valid
    assert any(
        any("type=" in e for e in entry.get("invalid_enums", []))
        for entry in r.invalid_catalyst_entries
    )


def test_tier_insufficient_inconsistency_caught() -> None:
    """tier_insufficient=true MUST have null iv_spread."""
    memo = _memo()
    memo["positioning"]["tier_insufficient"] = True
    # Leave iv_spread non-null → inconsistency.
    r = validate_catalyst_memo_shape(memo)
    assert not r.valid
    assert any("iv_spread" in s for s in r.tier_insufficient_inconsistency)


def test_modifier_reason_length_capped() -> None:
    memo = _memo()
    memo["conviction_modifier"]["reason"] = "x" * 600
    r = validate_catalyst_memo_shape(memo)
    assert not r.valid
    assert any("length" in v for v in r.invalid_modifier_values)


def test_invalid_active_manager_read() -> None:
    memo = _memo()
    memo["institutional_flow"]["active_manager_conviction_read"] = "BULLISH"
    r = validate_catalyst_memo_shape(memo)
    assert not r.valid
    assert r.invalid_active_manager_read == "BULLISH"


def test_missing_top_level_caught() -> None:
    memo = _memo()
    del memo["conviction_modifier"]
    r = validate_catalyst_memo_shape(memo)
    assert not r.valid
    assert "conviction_modifier" in r.missing_top_level


def test_constants_match_spec() -> None:
    assert "earnings" in VALID_CATALYST_TYPES
    assert "INCONCLUSIVE" in VALID_ACTIVE_MANAGER_READS
    assert "EPS" in VALID_KPI_IMPACTS
