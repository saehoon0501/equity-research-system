"""Unit tests for src.eval.gates.envelope_shape (Bug 13 fix)."""

from __future__ import annotations

import pytest

from src.eval.gates.envelope_shape import (
    CRITICAL_KEYS,
    REPORT_ROW_SUBKEYS,
    REQUIRED_SUBKEYS,
    REQUIRED_TOP_LEVEL,
    validate_envelope_shape,
)


def _make_minimal_valid_envelope() -> dict:
    """Build a minimal envelope that passes the non-strict validator.

    Every REQUIRED_TOP_LEVEL key is present and non-empty; the three
    critical blocks have all REQUIRED_SUBKEYS populated with placeholder
    values. Report rows are present but NOT populated with REPORT_ROW_SUBKEYS
    (strict mode would flag these as invalid — that's a separate test).
    """
    env: dict = {
        "ticker": "MSFT",
        "as_of": "2026-05-15",
        "tier": "core_fundamental",
        "mode": "B",
        "summary_code": "HOLD",
        "conviction": "MEDIUM",
        "size_band_if_long": {"min_book_pct": 0.0, "max_book_pct": 0.0, "midpoint": 0.0},
        "sleeve_cap_check": {"status": "PASS"},
        "counterfactual_top3_summary": {"survivor": 3, "diluted_survivor": 0, "non_survivor": 0},
        "adversarial_stress_test": {"claims_inverted_count": 6},
        "catalyst_modifier_applied": "0 (neutral)",
        "veto_reason": None,
        "conviction_rationale": "MEDIUM per rule + override-block; see rule trace.",
        "evidence_index_refs": ["uuid-1"],
        "rule_engine_version": "v0.2-2026-05-12",
        # HG-22 fields.
        "conviction_from_rule": "HIGH",
        "conviction_emitted": "MEDIUM",
        "conviction_override": True,
        "conviction_override_reason": (
            "stress_open on capex outlier Cisco-1999 trigger feeds narrative concern "
            "that integer kills_fired=0 underweights for tier overlay"
        ),
        # The three critical blocks (Bug 13 surface).
        "tl_dr": {
            "decision_headline": "HOLD @ MEDIUM",
            "scenarios_quant": {"bear": "...", "base": "...", "bull": "..."},
            "scenarios_strategic": {"bear": "...", "base": "...", "bull": "..."},
            "operating_ranges": {"technical_entry": "...", "technical_exit": "..."},
            "top_catalysts_90d": [{"date": "2026-07-30", "event": "FY26 Q4 print"}],
            "reevaluation_triggers": {"toward_buy": ["..."], "toward_sell": ["..."]},
        },
        "report": {
            "sentiment": {"reading": "NEUTRAL"},
            "trend": {"reading": "RANGE-BOUND"},
            "structural_theory": {"reading": "Core compounder"},
            "technical_entry": {"reading": "DO NOT ENTER"},
            "technical_exit": {"reading": "N/A"},
            "reasoning": {"reading": "Converging signals"},
        },
        "audit_trail_hint": {
            "instructions_for_operator": "drill down via evidence_refs",
            "cross_run_artifact_ids": {"quant_brief_id": "uuid"},
            "evidence_index_query_template": "SELECT ... FROM evidence_index WHERE ...",
        },
    }
    return env


def test_minimal_valid_envelope_passes():
    env = _make_minimal_valid_envelope()
    result = validate_envelope_shape(env)
    assert result.valid is True
    assert result.critical_missing is False
    assert result.missing_top_level == []
    assert result.missing_subkeys == {}


def test_msft_bug13_surface_pattern_fails():
    """The actual MSFT 2026-05-15 bug: envelope omits tl_dr/report/audit_trail_hint."""
    env = _make_minimal_valid_envelope()
    del env["tl_dr"]
    del env["report"]
    del env["audit_trail_hint"]
    result = validate_envelope_shape(env)
    assert result.valid is False
    assert result.critical_missing is True
    assert set(result.missing_top_level) >= set(CRITICAL_KEYS)


def test_critical_missing_flag_partial():
    """Only one critical block missing still flips critical_missing."""
    env = _make_minimal_valid_envelope()
    del env["tl_dr"]
    result = validate_envelope_shape(env)
    assert result.critical_missing is True
    assert "tl_dr" in result.missing_top_level


def test_empty_critical_block_is_missing():
    """An empty dict for a critical block counts as missing."""
    env = _make_minimal_valid_envelope()
    env["report"] = {}
    result = validate_envelope_shape(env)
    assert result.valid is False
    assert "report" in result.missing_top_level


def test_subkey_validation_for_tl_dr():
    """If tl_dr lacks a required subkey, it surfaces in missing_subkeys."""
    env = _make_minimal_valid_envelope()
    del env["tl_dr"]["top_catalysts_90d"]
    result = validate_envelope_shape(env)
    assert result.valid is False
    assert "tl_dr" in result.missing_subkeys
    assert "top_catalysts_90d" in result.missing_subkeys["tl_dr"]


def test_subkey_validation_for_report():
    env = _make_minimal_valid_envelope()
    del env["report"]["structural_theory"]
    result = validate_envelope_shape(env)
    assert result.valid is False
    assert "report" in result.missing_subkeys
    assert "structural_theory" in result.missing_subkeys["report"]


def test_subkey_validation_for_audit_trail_hint():
    env = _make_minimal_valid_envelope()
    del env["audit_trail_hint"]["evidence_index_query_template"]
    result = validate_envelope_shape(env)
    assert result.valid is False
    assert "audit_trail_hint" in result.missing_subkeys


def test_strict_mode_flags_incomplete_report_rows():
    """Strict mode catches report rows missing reading/detail/evidence_refs/etc."""
    env = _make_minimal_valid_envelope()
    # Default minimal envelope has report rows with only `reading`. In strict
    # mode this should fail on missing detail/evidence_refs/framework_keys/cdd_memo_refs.
    result = validate_envelope_shape(env, strict=True)
    assert result.valid is False
    assert result.invalid_report_rows  # at least one row flagged
    # Spot-check one row.
    for row_name, missing in result.invalid_report_rows.items():
        assert "detail" in missing or "evidence_refs" in missing


def test_strict_mode_passes_with_complete_report_rows():
    env = _make_minimal_valid_envelope()
    for row in REQUIRED_SUBKEYS["report"]:
        env["report"][row] = {sk: f"placeholder_{sk}" for sk in REPORT_ROW_SUBKEYS}
        env["report"][row]["evidence_refs"] = [{"evidence_id": "uuid"}]
        env["report"][row]["framework_keys"] = ["damodaran_narrative_dcf"]
        env["report"][row]["cdd_memo_refs"] = ["path/to/memo.md"]
    result = validate_envelope_shape(env, strict=True)
    assert result.valid is True
    assert result.invalid_report_rows == {}


def test_non_dict_envelope_fails():
    """A non-dict input (e.g., raw string from a JSON-decode error) fails cleanly."""
    result = validate_envelope_shape("not a dict")  # type: ignore[arg-type]
    assert result.valid is False
    assert result.critical_missing is True


def test_hg22_override_reason_required_when_override_true():
    """HG-22 conditional: if conviction_override=True, override_reason is mandatory."""
    env = _make_minimal_valid_envelope()
    del env["conviction_override_reason"]
    result = validate_envelope_shape(env)
    assert result.valid is False
    assert "conviction_override_reason" in result.missing_top_level


def test_hg22_override_reason_optional_when_override_false():
    """No override → override_reason can be absent without failing."""
    env = _make_minimal_valid_envelope()
    env["conviction_override"] = False
    env["conviction_emitted"] = env["conviction_from_rule"]  # must agree
    del env["conviction_override_reason"]
    result = validate_envelope_shape(env)
    assert result.valid is True


def test_top_level_constant_includes_critical_keys():
    """Sanity: CRITICAL_KEYS is a strict subset of REQUIRED_TOP_LEVEL."""
    for k in CRITICAL_KEYS:
        assert k in REQUIRED_TOP_LEVEL


# --------------------------------------------------------------------------
# HIGH-4 consensus (2026-05-16) — Bug 13.1: forbidden-field check
# --------------------------------------------------------------------------


def test_summary_code_operator_semantic_field_is_forbidden():
    """HIGH-4 Consensus Item #1: this invented field must be REJECTed."""
    env = _make_minimal_valid_envelope()
    env["summary_code_operator_semantic"] = "WATCH"
    result = validate_envelope_shape(env)
    assert result.valid is False
    assert "summary_code_operator_semantic" in result.forbidden_fields_present


def test_msft_bug13_1_full_surface():
    """The actual MSFT 2026-05-15 envelope had BOTH the missing critical
    blocks (Bug 13) AND the invented forbidden field (Bug 13.1)."""
    env = _make_minimal_valid_envelope()
    del env["tl_dr"]
    del env["report"]
    del env["audit_trail_hint"]
    env["summary_code_operator_semantic"] = "WATCH"
    result = validate_envelope_shape(env)
    assert result.valid is False
    assert result.critical_missing is True
    assert "summary_code_operator_semantic" in result.forbidden_fields_present


def test_summary_code_must_be_in_4bin_enum():
    """Consensus Item #1: only BUY/HOLD/TRIM/SELL are valid summary_code values."""
    env = _make_minimal_valid_envelope()
    env["summary_code"] = "WATCH"
    result = validate_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_summary_code == "WATCH"


def test_summary_code_pass_is_invalid():
    """Per HIGH-4 consensus, PASS is no longer a valid summary_code value."""
    env = _make_minimal_valid_envelope()
    env["summary_code"] = "PASS"
    result = validate_envelope_shape(env)
    assert result.valid is False
    assert result.invalid_summary_code == "PASS"


def test_all_four_canonical_summary_codes_pass():
    for code in ("BUY", "HOLD", "TRIM", "SELL"):
        env = _make_minimal_valid_envelope()
        env["summary_code"] = code
        result = validate_envelope_shape(env)
        assert result.valid is True, f"summary_code={code} unexpectedly failed"
        assert result.invalid_summary_code is None


def test_inv_2_1_a_tactical_disposition_uses_disjoint_enum():
    """INV-2.1-A: tactical_disposition enum is disjoint from summary_code enum (modulo HOLD).

    Per Section 2.1 v5-final consensus doc at
    docs/superpowers/consensus/2026-05-21-section2.1-label-vocabulary.md.

    BUY/TRIM/SELL must NOT appear in tactical_disposition (those are pm-supervisor's
    summary_code domain). The tactical overlay uses BUY-HIGH/BUY-MED/AVOID instead;
    HOLD is the sole intentional overlap (semantic identity preserved).
    """
    from src.overlays.tactical.contracts import TacticalDisposition

    tactical_values = set(TacticalDisposition.__args__)
    canonical_summary = {"BUY", "TRIM", "SELL"}  # HOLD excluded (intentional overlap)
    forbidden_overlap = tactical_values & canonical_summary
    assert forbidden_overlap == set(), (
        f"INV-2.1-A violation: tactical_disposition contains canonical summary_code "
        f"values {forbidden_overlap} (must use BUY-HIGH/BUY-MED instead of BUY)"
    )


def test_no_forbidden_fields_no_invalid_summary_code_on_clean_envelope():
    env = _make_minimal_valid_envelope()
    result = validate_envelope_shape(env)
    assert result.forbidden_fields_present == []
    assert result.invalid_summary_code is None
    assert result.valid is True
