"""Phase 4 quantitative-analyst envelope cutover — parity gate + golden tests."""
from __future__ import annotations

import sys

from src.agent_harness.dispatch_template import (
    EvidenceRef,
    lint_dispatch_prompt,
    render_dispatch_prompt,
)
from src.agent_harness.envelopes import quantitative as quant_envelope


_RUN_ID = "44444444-5555-4666-8777-888888888888"
_PARAMETERS_USED_BLOCK = (
    "PARAMETERS_USED (parameters_version_max: v1.1, "
    "effective_parameters_hash: deadbeef, tag: phase-4-pilot):\n"
    "  quality_gate.piotroski_min: 6\n"
    "  dcf.austere_fade_years: 7"
)


def _valid_core_envelope() -> dict:
    return {
        "analyst": "quantitative-analyst",
        "ticker": "MSFT",
        "tier": "core_fundamental",
        "quality_gate": {
            "piotroski_f_score": 8,
            "altman_z_double_prime": 6.4,
            "passes_quality_gate": True,
        },
        "frameworks_cited": {
            "damodaran_narrative_dcf": {
                "key": "damodaran_narrative_dcf",
                "output": {
                    "outside_view": {
                        "intuitive_growth_pct": 12.0,
                        "reference_class_growth_mean_pct": 8.0,
                        "reference_source": "Damodaran 2024 dataset",
                        "cohort_values_placeholder": ["AAPL", "GOOG", "META"],
                        "r_coefficient_used": 0.5,
                        "corrected_growth_pct": 10.0,
                        "corrected_divergence_pp": 2.0,
                    },
                    "bull_case_narrative": {
                        "helmer_power_anchor": "switching_costs",
                    },
                    "bear_case_narrative": {
                        "helmer_power_anchor": "scale_economies",
                    },
                },
            },
            "austere_dcf": {"key": "austere_dcf", "output": {}},
            "mauboussin_reverse_dcf": {
                "key": "mauboussin_reverse_dcf",
                "output": {},
            },
            "buffett_2007_inevitables": {
                "key": "buffett_2007_inevitables",
                "output": {
                    "reinvestment_moat": {
                        "quality_label": "A",
                        "incremental_roic_3y_trailing_pct": 32.0,
                        "deployable_runway_years_est": 8,
                    },
                },
            },
        },
        "evidence_index_refs": ["aaaaaaaa-cccc-4ddd-8eee-ffffffffffff"],
        "banned_outputs_check": True,
        "reasoning_path_taken": [
            "load_company_facts",
            "compute_piotroski_f_score",
            "compute_altman_z_double_prime",
            "evaluate_quality_gate",
            "load_outside_view_reference_class",
            "compute_outside_view_prior",
            "blend_intuitive_with_reference",
            "compute_dcf_inherited_case",
            "compute_dcf_austere_case",
            "compute_dcf_bull_case",
            "compute_dcf_bear_case",
            "run_mauboussin_reverse_dcf",
            "evaluate_buffett_inevitables",
            "classify_reinvestment_moat",
            "anchor_helmer_power_to_strategic",
            "compose_bull_case_narrative",
            "compose_bear_case_narrative",
            "emit_envelope",
        ],
    }


def test_render_lint_roundtrip() -> None:
    prompt = render_dispatch_prompt(
        agent_type="quantitative-analyst",
        run_id=_RUN_ID,
        parameters_used_block=_PARAMETERS_USED_BLOCK,
        goal="Emit a QuantEnvelope conforming to OUTPUT_SCHEMA",
        cdd_brief={"ticker": "MSFT", "tier": "core_fundamental"},
        evidence_refs=[
            EvidenceRef(
                uri="evidence://msft/10k",
                evidence_uuid="aaaaaaaa-cccc-4ddd-8eee-ffffffffffff",
            ),
        ],
        reasoning_steps=quant_envelope.REASONING_STEPS,
        output_schema=quant_envelope.SCHEMA,
    )
    lint_dispatch_prompt(prompt)


def test_valid_core_envelope_passes() -> None:
    env = _valid_core_envelope()
    hg_env = quant_envelope.validate(env)
    assert hg_env.valid, f"HG-ENV failed: {hg_env.to_result_dict()}"


def test_piotroski_out_of_range_fails() -> None:
    env = _valid_core_envelope()
    env["quality_gate"]["piotroski_f_score"] = 15
    hg_env = quant_envelope.validate(env)
    assert not hg_env.valid


def test_missing_required_framework_fails() -> None:
    env = _valid_core_envelope()
    del env["frameworks_cited"]["austere_dcf"]
    hg_env = quant_envelope.validate(env)
    assert not hg_env.valid
    assert "required_frameworks_cited_when_non_speculative" in hg_env.failed_predicates


def test_outside_view_incomplete_fails() -> None:
    env = _valid_core_envelope()
    del env["frameworks_cited"]["damodaran_narrative_dcf"]["output"][
        "outside_view"
    ]["corrected_growth_pct"]
    hg_env = quant_envelope.validate(env)
    assert not hg_env.valid
    assert "outside_view_complete_when_non_speculative" in hg_env.failed_predicates


def test_helmer_anchor_non_canonical_fails() -> None:
    env = _valid_core_envelope()
    env["frameworks_cited"]["damodaran_narrative_dcf"]["output"][
        "bull_case_narrative"
    ]["helmer_power_anchor"] = "synergies"  # invented
    hg_env = quant_envelope.validate(env)
    assert not hg_env.valid
    assert "helmer_anchor_canonical_or_pending" in hg_env.failed_predicates


def test_pending_helmer_anchor_accepted() -> None:
    env = _valid_core_envelope()
    env["frameworks_cited"]["damodaran_narrative_dcf"]["output"][
        "bull_case_narrative"
    ]["helmer_power_anchor"] = "PENDING_STRATEGIC_RESOLUTION"
    hg_env = quant_envelope.validate(env)
    assert hg_env.valid, f"PENDING sentinel rejected: {hg_env.to_result_dict()}"


def test_speculative_skips_frameworks() -> None:
    env = _valid_core_envelope()
    env["tier"] = "speculative_optionality"
    env["frameworks_cited"] = {}  # entirely absent for speculative
    hg_env = quant_envelope.validate(env)
    assert hg_env.valid, f"speculative skip not honored: {hg_env.to_result_dict()}"


def test_reinvestment_moat_incomplete_fails() -> None:
    env = _valid_core_envelope()
    del env["frameworks_cited"]["buffett_2007_inevitables"]["output"][
        "reinvestment_moat"
    ]["quality_label"]
    hg_env = quant_envelope.validate(env)
    assert not hg_env.valid
    assert "reinvestment_moat_complete_when_non_speculative" in hg_env.failed_predicates


def test_invented_reasoning_step_fails() -> None:
    env = _valid_core_envelope()
    env["reasoning_path_taken"].append("INVENTED_STEP")
    hg_env = quant_envelope.validate(env)
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
