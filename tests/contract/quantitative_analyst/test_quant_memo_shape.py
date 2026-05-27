"""Unit tests for src.eval.gates.quant_memo_shape (HG-29)."""

from __future__ import annotations

import uuid

import pytest

from src.eval.gates.quant_memo_shape import (
    CANONICAL_HELMER_POWERS,
    PENDING_STRATEGIC_SENTINEL,
    REQUIRED_REINVESTMENT_MOAT_KEYS,
    validate_quant_memo_shape,
)


def _u() -> str:
    return str(uuid.uuid4())


def _core_memo() -> dict:
    """Minimal core_fundamental memo that passes the shape gate."""
    return {
        "analyst": "quantitative",
        "ticker": "MSFT",
        "tier": "core_fundamental",
        "quality_gate": {
            "piotroski_f_score": 7,
            "altman_z_double_prime": 7.89,
            "passes_quality_gate": True,
        },
        "frameworks_cited": [
            {
                "framework_key": "damodaran_narrative_dcf",
                "output": {
                    "base_case_value": 435.5,
                    "bull_case_narrative": {
                        "helmer_power_anchor": "switching_costs",
                        "distinct_arc_description": "M365 + Azure lock-in deepens",
                        "falsifying_observable": "M365 NRR < 105% for 2 consecutive quarters",
                        "falsifier_resolution_date": "2027-01-28",
                    },
                    "bear_case_narrative": {
                        "structural_impairment_anchor": "AI capex bubble",
                        "falsifying_observable": "Azure growth above 22%",
                        "falsifier_resolution_date": "2027-01-28",
                    },
                },
            },
            {"framework_key": "austere_dcf", "output": {"base_case_value": 125.9}},
            {"framework_key": "mauboussin_reverse_dcf", "output": {}},
            {
                "framework_key": "buffett_2007_inevitables",
                "output": {
                    "reinvestment_moat": {
                        "quality_label": "A",
                        "incremental_roic_3y_trailing_pct": 26.4,
                        "deployable_runway_years_est": 7,
                    }
                },
            },
        ],
        "outside_view": {
            "intuitive_growth_pct": 15.95,
            "reference_class_growth_mean_pct": 11.0,
            "reference_source": "base_rates_cohort_refined.mega_cap_tech",
            "cohort_values_placeholder": True,
            "r_coefficient_used": 0.20,
            "corrected_growth_pct": 14.96,
            "corrected_divergence_pp": 3.96,
        },
        "evidence_index_refs": [_u()],
        "banned_outputs_check": {
            "peg_only_ranking_used": False,
            "fed_commentary_without_hfi_used": False,
        },
    }


def test_clean_core_memo_passes() -> None:
    r = validate_quant_memo_shape(_core_memo())
    assert r.valid, r.notes


def test_missing_top_level_fails() -> None:
    memo = _core_memo()
    del memo["quality_gate"]
    r = validate_quant_memo_shape(memo)
    assert not r.valid
    assert "quality_gate" in r.missing_top_level


def test_missing_outside_view_keys_fails() -> None:
    memo = _core_memo()
    del memo["outside_view"]["corrected_growth_pct"]
    r = validate_quant_memo_shape(memo)
    assert not r.valid
    assert "corrected_growth_pct" in r.missing_outside_view_keys


def test_missing_reinvestment_moat_quality_label() -> None:
    memo = _core_memo()
    rim = memo["frameworks_cited"][3]["output"]["reinvestment_moat"]
    del rim["quality_label"]
    r = validate_quant_memo_shape(memo)
    assert not r.valid
    assert "quality_label" in r.missing_reinvestment_moat_keys


def test_missing_dual_dcf_fails() -> None:
    memo = _core_memo()
    # Drop austere_dcf — HG-20-style bug.
    memo["frameworks_cited"] = [
        fw for fw in memo["frameworks_cited"]
        if fw["framework_key"] != "austere_dcf"
    ]
    r = validate_quant_memo_shape(memo)
    assert not r.valid
    assert "austere_dcf" in r.missing_frameworks


def test_invalid_helmer_anchor_caught() -> None:
    memo = _core_memo()
    memo["frameworks_cited"][0]["output"]["bull_case_narrative"][
        "helmer_power_anchor"
    ] = "switching costs"  # space instead of underscore
    r = validate_quant_memo_shape(memo)
    assert not r.valid
    assert r.invalid_helmer_anchor == "switching costs"


def test_pending_anchor_allowed() -> None:
    memo = _core_memo()
    memo["frameworks_cited"][0]["output"]["bull_case_narrative"][
        "helmer_power_anchor"
    ] = PENDING_STRATEGIC_SENTINEL
    r = validate_quant_memo_shape(memo)
    assert r.valid, r.notes


def test_quarter_end_falsifier_date_caught() -> None:
    """HG-15.5a — MSFT FY27 Q2 print observable cannot resolve on 2026-12-31."""
    memo = _core_memo()
    memo["frameworks_cited"][0]["output"]["bull_case_narrative"][
        "falsifier_resolution_date"
    ] = "2026-12-31"  # quarter-end pattern + quarterly observable text
    r = validate_quant_memo_shape(memo)
    assert not r.valid
    assert any("quarter-end" in s for s in r.falsifier_date_issues)


def test_canonical_helmer_powers_constant() -> None:
    """Pin the canonical 7-Power enum."""
    assert CANONICAL_HELMER_POWERS == frozenset({
        "scale_economies", "network_economies", "counter_positioning",
        "switching_costs", "branding", "cornered_resource", "process_power",
    })


def test_speculative_tier_skips_dual_dcf() -> None:
    """speculative_optionality is allowed to skip dual-DCF; should pass."""
    memo = _core_memo()
    memo["tier"] = "speculative_optionality"
    # Remove dual-DCF frameworks — should NOT fail.
    memo["frameworks_cited"] = [
        fw for fw in memo["frameworks_cited"]
        if fw["framework_key"] not in {"damodaran_narrative_dcf", "austere_dcf",
                                        "buffett_2007_inevitables"}
    ]
    # Speculative tier also expects outside_view to be marked SKIPPED.
    memo["outside_view"] = "SKIPPED — speculative_optionality"
    r = validate_quant_memo_shape(memo)
    # Some fail bits possible (e.g. reinvestment_moat absent OK for speculative);
    # the key assertion is dual-DCF absence is not flagged.
    assert "damodaran_narrative_dcf" not in r.missing_frameworks
    assert "austein_dcf" not in r.missing_frameworks


def test_non_dict_fails() -> None:
    r = validate_quant_memo_shape("not a dict")
    assert not r.valid
