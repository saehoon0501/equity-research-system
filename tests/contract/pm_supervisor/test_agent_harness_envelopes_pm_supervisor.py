"""Phase 5 pm-supervisor envelope cutover — parity gate + golden tests.

Highest-risk phase per harness-v4-final: §2.6 stress enum surgery. The
test below pins the 5 canonical STRESS_* tokens; drift here re-opens
Bug 3 (byte-identical-input divergence from freeform stress).
"""
from __future__ import annotations

import sys

from src.shared.agent_harness.dispatch_template import (
    EvidenceRef,
    lint_dispatch_prompt,
    render_dispatch_prompt,
)
from src.shared.agent_harness.envelopes import pm_supervisor as pm_envelope


_RUN_ID = "55555555-6666-4777-8888-999999999999"
_PARAMETERS_USED_BLOCK = (
    "PARAMETERS_USED (parameters_version_max: v1.1, "
    "effective_parameters_hash: deadbeef, tag: phase-5-pilot):\n"
    "  sizing.conviction_band.HIGH.min_pct: 4.0\n"
    "  mode.thematic_alpha: 0.5"
)


def _valid_envelope() -> dict:
    """Minimal valid pm-supervisor envelope per §8 schema."""
    return {
        "ticker": "MSFT",
        "as_of": "2026-05-22",
        "tier": "core_fundamental",
        "mode": "core_compounder",
        "tl_dr": {
            "decision_headline": "BUY HIGH",
            "scenarios_quant": "bull/base/bear DCFs",
            "scenarios_strategic": "wide moat held",
            "operating_ranges": "11% growth, 35% margin",
            "top_catalysts_90d": "Q4 print",
            "reevaluation_triggers": "margin compression",
        },
        "report": {
            "sentiment": {
                "reading": "neutral",
                "detail": "AAII 45%",
                "evidence_refs": [],
                "framework_keys": ["sentiment"],
                "cdd_memo_refs": [],
            },
            "trend": {
                "reading": "positive",
                "detail": "12m excess +18%",
                "evidence_refs": [],
                "framework_keys": ["antonacci"],
                "cdd_memo_refs": [],
            },
            "structural_theory": {
                "reading": "wide_moat",
                "detail": "switching_costs held",
                "evidence_refs": [],
                "framework_keys": ["helmer"],
                "cdd_memo_refs": [],
            },
            "technical_entry": {
                "reading": "ready",
                "detail": "above 50dma",
                "evidence_refs": [],
                "framework_keys": [],
                "cdd_memo_refs": [],
            },
            "technical_exit": {
                "reading": "trail",
                "detail": "below 200dma",
                "evidence_refs": [],
                "framework_keys": [],
                "cdd_memo_refs": [],
            },
            "reasoning": {
                "reading": "BUY-HIGH",
                "detail": "conviction high; valuation within IV band",
                "evidence_refs": [],
                "framework_keys": [],
                "cdd_memo_refs": [],
            },
        },
        "audit_trail_hint": {
            "instructions_for_operator": "review at next 13F print",
            "cross_run_artifact_ids": [],
            "evidence_index_query_template": "SELECT * FROM evidence_index WHERE run_id=:run_id",
        },
        "summary_code": "BUY",
        "conviction": "HIGH",
        "size_band_if_long": {"min_pct": 4.0, "max_pct": 8.0},
        "sleeve_cap_check": {"violated": False},
        "counterfactual_top3_summary": [],
        "adversarial_stress_test": {
            "kills_fired": 0,
            "kills_fired_evidence": [],
        },
        "catalyst_modifier_applied": {"direction": 0, "magnitude": "low"},
        "veto_reason": None,
        "conviction_rationale": "narrative DCF supports HIGH",
        "evidence_index_refs": [],
        "rule_engine_version": "v1.1",
        "conviction_from_rule": "HIGH",
        "conviction_emitted": "HIGH",
        "conviction_override": False,
        "reasoning_path_taken": [
            "load_cdd_integrated_memo",
            "load_tactical_envelope",
            "load_catalyst_envelope",
            "classify_mode",
            "compose_tl_dr",
            "compose_report_sentiment_row",
            "compose_report_trend_row",
            "compose_report_structural_theory_row",
            "compose_report_technical_entry_row",
            "compose_report_technical_exit_row",
            "compose_report_reasoning_row",
            "compose_adversarial_stress_test",
            "evaluate_counterfactual_veto",
            "compute_sleeve_cap_check",
            "compute_conviction_from_rule",
            "compute_conviction_emitted",
            "derive_summary_code",
            "derive_size_band_if_long",
            "compose_counterfactual_top3_summary",
            "compose_audit_trail_hint",
            "emit_envelope",
        ],
    }


def test_render_lint_roundtrip() -> None:
    prompt = render_dispatch_prompt(
        agent_type="pm-supervisor",
        run_id=_RUN_ID,
        parameters_used_block=_PARAMETERS_USED_BLOCK,
        goal="Emit a PMSupervisorEnvelope conforming to OUTPUT_SCHEMA",
        cdd_brief={"ticker": "MSFT", "tier": "core_fundamental"},
        evidence_refs=[
            EvidenceRef(
                uri="evidence://msft/cdd",
                evidence_uuid="aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
            ),
        ],
        reasoning_steps=pm_envelope.REASONING_STEPS,
        output_schema=pm_envelope.SCHEMA,
    )
    lint_dispatch_prompt(prompt)


def test_valid_envelope_passes() -> None:
    env = _valid_envelope()
    hg_env = pm_envelope.validate(env)
    assert hg_env.valid, f"HG-ENV failed: {hg_env.to_result_dict()}"


def test_forbidden_top_level_field_rejected() -> None:
    """summary_code_operator_semantic — HIGH-4-consensus-banned."""
    env = _valid_envelope()
    env["summary_code_operator_semantic"] = "BUY-OPS"
    hg_env = pm_envelope.validate(env)
    assert not hg_env.valid
    assert "no_forbidden_top_level_fields" in hg_env.failed_predicates


def test_invalid_summary_code_rejected() -> None:
    """5-bin variants like 'BUY-HIGH' are forbidden at top-level
    summary_code — tactical_disposition uses BUY-HIGH but pm-supervisor
    summary_code is canonical 4-bin."""
    env = _valid_envelope()
    env["summary_code"] = "BUY-HIGH"
    hg_env = pm_envelope.validate(env)
    assert not hg_env.valid


def test_stress_enum_drift_rejected() -> None:
    """The load-bearing §2.6 invariant: invented STRESS_* names must
    fail. Phase 5 cutover guard against re-opening Bug 3."""
    env = _valid_envelope()
    env["adversarial_stress_test"] = {
        "kills_fired": 1,
        "kills_fired_evidence": [
            {
                "sub_test_name": "STRESS_SPOT_IV_DIVERGENCE",  # not in §2.6!
                "severity": "non_catastrophic",
            }
        ],
    }
    hg_env = pm_envelope.validate(env)
    assert not hg_env.valid
    assert "stress_kills_fired_enum_only" in hg_env.failed_predicates


def test_canonical_stress_enum_accepted() -> None:
    """All 5 canonical §2.6 STRESS_* tokens must validate."""
    for sub_test in pm_envelope.STRESS_SUB_TESTS:
        env = _valid_envelope()
        env["adversarial_stress_test"] = {
            "kills_fired": 1,
            "kills_fired_evidence": [
                {"sub_test_name": sub_test, "severity": "non_catastrophic"}
            ],
        }
        hg_env = pm_envelope.validate(env)
        assert hg_env.valid, (
            f"canonical token {sub_test!r} rejected: {hg_env.to_result_dict()}"
        )


def test_canonical_stress_enum_pinned() -> None:
    """Pin the exact 5 tokens — drift = regression to Bug 3."""
    expected = {
        "STRESS_HELMER_POWER_ABSENT",
        "STRESS_HELMER_POWER_UNDER_EVIDENCED",
        "STRESS_REINVESTMENT_QUALITY_D_CONTRADICTION",
        "STRESS_CAPITAL_LIGHT_CHAIN_BROKEN",
        "STRESS_GENERIC_CLAIM_INVERSION_FAILED",
    }
    assert set(pm_envelope.STRESS_SUB_TESTS) == expected, (
        "§2.6 stress enum drifted from pm-supervisor.md lines 53-61. "
        "Drift here re-opens the freeform-stress loophole that produced "
        "Bug 3 (byte-identical-input divergence)."
    )


def test_missing_critical_top_level_fails() -> None:
    env = _valid_envelope()
    del env["tl_dr"]
    hg_env = pm_envelope.validate(env)
    assert not hg_env.valid


def test_empty_veto_reason_rejected() -> None:
    env = _valid_envelope()
    env["veto_reason"] = ""  # not null, not a real reason
    hg_env = pm_envelope.validate(env)
    assert not hg_env.valid
    assert "veto_reason_string_or_null" in hg_env.failed_predicates


def test_invented_reasoning_step_fails() -> None:
    env = _valid_envelope()
    env["reasoning_path_taken"].append("FREEFORM_PROSE_STEP")
    hg_env = pm_envelope.validate(env)
    assert not hg_env.valid


def _all_tests() -> list:
    return [v for k, v in globals().items() if k.startswith("test_") and callable(v)]


def main() -> int:
    failed = 0
    for t in _all_tests():
        try:
            t()
            sys.stdout.write(f"PASS {t.__name__}\n")
        except AssertionError as e:
            failed += 1
            sys.stdout.write(f"FAIL {t.__name__}: {e}\n")
        except Exception as e:
            failed += 1
            sys.stdout.write(f"ERROR {t.__name__}: {type(e).__name__}: {e}\n")
    sys.stdout.write(f"\n{len(_all_tests()) - failed}/{len(_all_tests())} passed\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
