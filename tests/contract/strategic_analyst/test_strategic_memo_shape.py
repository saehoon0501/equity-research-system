"""Unit tests for src.eval.gates.strategic_memo_shape (HG-30)."""

from __future__ import annotations

import uuid

import pytest

from src.eval.gates.strategic_memo_shape import (
    CANONICAL_HELMER_POWERS,
    CAPITAL_ALLOCATION_BUCKETS,
    HELD_POWER_MIN_CITATIONS,
    VALID_LETTER_GRADES,
    validate_strategic_memo_shape,
)


def _u() -> str:
    return str(uuid.uuid4())


def _memo() -> dict:
    """Minimal strategic memo passing all checks."""
    return {
        "analyst": "strategic",
        "ticker": "MSFT",
        "tier": "core_fundamental",
        "frameworks_cited": [
            {"framework_key": "mauboussin_moat_2024", "output": {}},
            {
                "framework_key": "helmer_7_powers",
                "output": {
                    "helmer_powers_evidence": [
                        {
                            "power_name": "switching_costs",
                            "benefit_cashflow_effect": "20pp ROIC premium",
                            "barrier_to_arbitrage": "M365 file-format lock-in + AD migration cost",
                            "primary_source_citations": [_u(), _u()],
                            "status": "held",
                        },
                        {
                            "power_name": "scale_economies",
                            "benefit_cashflow_effect": "Azure unit-cost scaling",
                            "barrier_to_arbitrage": "$60B/yr capex",
                            "primary_source_citations": [_u(), _u()],
                            "status": "held",
                        },
                    ],
                    "powers_assessed_not_held": [
                        {"power_name": "process_power", "evidence_gap_note": "no proprietary knowhow"},
                    ],
                },
            },
            {
                "framework_key": "mauboussin_capital_allocation_2024",
                "output": {
                    "grades": {
                        "capex": "A-",
                        "rd": "A",
                        "ma": "B+",
                        "dividends": "B+",
                        "buybacks": {
                            "grade": "B",
                            "reasoning": "fwd P/E 21.3x vs trailing-5y median 30x = 29% discount; reverse-DCF implied value $435 vs spot $412",
                        },
                        "debt": "A",
                    },
                    "overall_grade": "A-",
                    "key_examples": {
                        "value_creating": ["LinkedIn 2016 acquisition"],
                        "value_destroying": [],
                    },
                },
            },
        ],
        "evidence_index_refs": [_u(), _u()],
        "banned_outputs_check": {
            "stovall_rotation_used": False,
            "ark_point_targets_used": False,
        },
    }


def test_clean_memo_passes() -> None:
    r = validate_strategic_memo_shape(_memo())
    assert r.valid, r.notes


def test_held_power_with_one_citation_fails() -> None:
    """Overlay 1 hard rule: held Powers need ≥2 primary citations."""
    memo = _memo()
    memo["frameworks_cited"][1]["output"]["helmer_powers_evidence"][0][
        "primary_source_citations"
    ] = [_u()]
    r = validate_strategic_memo_shape(memo)
    assert not r.valid
    assert any(
        p["power_name"] == "switching_costs"
        for p in r.held_powers_with_insufficient_citations
    )


def test_non_canonical_power_name_caught() -> None:
    memo = _memo()
    memo["frameworks_cited"][1]["output"]["helmer_powers_evidence"][0][
        "power_name"
    ] = "Switching Costs"  # Title Case, not canonical
    r = validate_strategic_memo_shape(memo)
    assert not r.valid
    assert "Switching Costs" in r.invalid_power_names


def test_invalid_citation_uuid_caught() -> None:
    memo = _memo()
    memo["frameworks_cited"][1]["output"]["helmer_powers_evidence"][0][
        "primary_source_citations"
    ] = ["not-a-uuid", _u()]
    r = validate_strategic_memo_shape(memo)
    assert not r.valid
    assert "not-a-uuid" in r.invalid_citation_uuids


def test_missing_framework_fails() -> None:
    memo = _memo()
    memo["frameworks_cited"] = [
        fw for fw in memo["frameworks_cited"]
        if fw["framework_key"] != "helmer_7_powers"
    ]
    r = validate_strategic_memo_shape(memo)
    assert not r.valid
    assert "helmer_7_powers" in r.missing_frameworks


def test_missing_capital_allocation_bucket() -> None:
    memo = _memo()
    del memo["frameworks_cited"][2]["output"]["grades"]["debt"]
    r = validate_strategic_memo_shape(memo)
    assert not r.valid
    assert "debt" in r.missing_capital_allocation_buckets


def test_invalid_letter_grade() -> None:
    memo = _memo()
    memo["frameworks_cited"][2]["output"]["grades"]["capex"] = "Excellent"
    r = validate_strategic_memo_shape(memo)
    assert not r.valid
    assert any(g["bucket"] == "capex" for g in r.invalid_letter_grades)


def test_buybacks_without_anchor_caught() -> None:
    """Per strategic-analyst.md, buybacks grade must reference one of the
    dual anchors. Pure narrative without anchor keywords → flagged."""
    memo = _memo()
    memo["frameworks_cited"][2]["output"]["grades"]["buybacks"] = {
        "grade": "B",
        "reasoning": "Management says they buy when stock is low",
    }
    memo["frameworks_cited"][2]["output"]["key_examples"] = {}
    r = validate_strategic_memo_shape(memo)
    assert not r.valid
    assert r.buyback_anchor_missing


def test_constants_match_spec() -> None:
    assert CAPITAL_ALLOCATION_BUCKETS == (
        "capex", "rd", "ma", "dividends", "buybacks", "debt",
    )
    assert HELD_POWER_MIN_CITATIONS == 2
    assert "A" in VALID_LETTER_GRADES
    assert "switching_costs" in CANONICAL_HELMER_POWERS
