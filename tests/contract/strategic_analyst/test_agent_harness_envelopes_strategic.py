"""Phase 3 strategic-analyst envelope cutover — parity gate + golden tests."""
from __future__ import annotations

import sys

from src.shared.agent_harness.delta_prompt import build_delta_prompt
from src.shared.agent_harness.dispatch_template import (
    EvidenceRef,
    lint_dispatch_prompt,
    render_dispatch_prompt,
)
from src.shared.agent_harness.envelopes import to_gate_outcome
from src.shared.agent_harness.envelopes import strategic as strategic_envelope
from src.eval.gates import AggregateValidationResult
from src.eval.gates.strategic_memo_shape import validate_strategic_memo_shape


_RUN_ID = "33333333-4444-4555-8666-777777777777"
_PARAMETERS_USED_BLOCK = (
    "PARAMETERS_USED (parameters_version_max: v1.1, "
    "effective_parameters_hash: deadbeef, tag: phase-3-pilot):\n"
    "  evaluator.gate.helmer_powers_min_held: 1\n"
    "  evaluator.gate.helmer_held_min_citations: 2"
)

_VALID_UUID_1 = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
_VALID_UUID_2 = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"


def _valid_envelope() -> dict:
    return {
        "analyst": "strategic-analyst",
        "ticker": "MSFT",
        "tier": "core_fundamental",
        "frameworks_cited": {
            "mauboussin_moat_2024": {
                "key": "mauboussin_moat_2024",
                "output": {"verdict": "wide_moat"},
            },
            "helmer_7_powers": {
                "key": "helmer_7_powers",
                "output": {
                    "helmer_powers_evidence": [
                        {
                            "power_name": "switching_costs",
                            "status": "held",
                            "primary_source_citations": [
                                _VALID_UUID_1,
                                _VALID_UUID_2,
                            ],
                            "benefit_cashflow_effect": "high renewal rates",
                            "barrier_to_arbitrage": "data lock-in",
                        },
                    ],
                },
            },
            "mauboussin_capital_allocation_2024": {
                "key": "mauboussin_capital_allocation_2024",
                "output": {
                    "grades": {
                        "capex": "A",
                        "rd": "A",
                        "ma": "B",
                        "dividends": "A",
                        "buybacks": {
                            "grade": "A-",
                            "reasoning": (
                                "Buyback program executes at implied_value "
                                "from reverse_dcf vs trailing 5y median multiple."
                            ),
                        },
                        "debt": "A",
                    },
                    "overall_grade": "A-",
                },
            },
        },
        "evidence_index_refs": [_VALID_UUID_1, _VALID_UUID_2],
        "banned_outputs_check": True,
        "reasoning_path_taken": [
            "load_company_facts",
            "load_peer_comps",
            "apply_mauboussin_moat_2024",
            "evaluate_helmer_power_switching_costs",
            "grade_capital_allocation_capex",
            "grade_capital_allocation_rd",
            "grade_capital_allocation_ma",
            "grade_capital_allocation_dividends",
            "grade_capital_allocation_buybacks",
            "grade_capital_allocation_debt",
            "compute_overall_capital_allocation_grade",
            "emit_envelope",
        ],
    }


def test_render_lint_roundtrip() -> None:
    prompt = render_dispatch_prompt(
        agent_type="strategic-analyst",
        run_id=_RUN_ID,
        parameters_used_block=_PARAMETERS_USED_BLOCK,
        goal="Emit a StrategicEnvelope conforming to OUTPUT_SCHEMA",
        cdd_brief={"ticker": "MSFT", "tier": "core_fundamental"},
        evidence_refs=[
            EvidenceRef(uri="evidence://msft/10k", evidence_uuid=_VALID_UUID_1),
        ],
        reasoning_steps=strategic_envelope.REASONING_STEPS,
        output_schema=strategic_envelope.SCHEMA,
    )
    lint_dispatch_prompt(prompt)


def test_valid_envelope_passes_both_gates() -> None:
    env = _valid_envelope()
    hg_env = strategic_envelope.validate(env)
    hg_30 = validate_strategic_memo_shape(env)
    assert hg_env.valid, f"HG-ENV failed: {hg_env.to_result_dict()}"
    assert hg_30.valid, f"HG-30 failed: {hg_30.__dict__}"


def test_invalid_power_name_fails() -> None:
    env = _valid_envelope()
    env["frameworks_cited"]["helmer_7_powers"]["output"][
        "helmer_powers_evidence"
    ][0]["power_name"] = "synergies"  # invented
    hg_env = strategic_envelope.validate(env)
    # power_name is inside frameworks_cited (additionalProperties=True at top),
    # so HG-ENV catches via the held-Power citation predicate failing for an
    # unknown power_name + status=held? No — invalid power_name still pings
    # because the predicate code returns False for unknown names? Let me check.
    # Actually: invalid power_name doesn't trip predicate; HG-30 catches it.
    # HG-ENV is structural; predicates are cross-field. Not all HG-30 surface
    # is mirrored by HG-ENV — that's per-design.
    hg_30 = validate_strategic_memo_shape(env)
    assert not hg_30.valid


def test_held_power_below_citation_floor() -> None:
    env = _valid_envelope()
    env["frameworks_cited"]["helmer_7_powers"]["output"][
        "helmer_powers_evidence"
    ][0]["primary_source_citations"] = [_VALID_UUID_1]  # only 1, need 2
    hg_env = strategic_envelope.validate(env)
    assert not hg_env.valid
    assert "held_powers_have_min_citations" in hg_env.failed_predicates


def test_missing_capital_allocation_bucket() -> None:
    env = _valid_envelope()
    del env["frameworks_cited"]["mauboussin_capital_allocation_2024"][
        "output"
    ]["grades"]["debt"]
    hg_env = strategic_envelope.validate(env)
    assert not hg_env.valid
    assert "capital_allocation_grades_complete" in hg_env.failed_predicates


def test_buybacks_missing_anchor_fails() -> None:
    env = _valid_envelope()
    env["frameworks_cited"]["mauboussin_capital_allocation_2024"]["output"][
        "grades"
    ]["buybacks"]["reasoning"] = "Looks fine."  # no anchor keyword
    hg_env = strategic_envelope.validate(env)
    assert not hg_env.valid
    assert "buybacks_grade_has_anchor" in hg_env.failed_predicates


def test_missing_required_framework() -> None:
    env = _valid_envelope()
    del env["frameworks_cited"]["mauboussin_moat_2024"]
    hg_env = strategic_envelope.validate(env)
    assert not hg_env.valid
    assert "all_required_frameworks_cited" in hg_env.failed_predicates


def test_invented_reasoning_step_fails() -> None:
    env = _valid_envelope()
    env["reasoning_path_taken"].append("INVENTED_PROSE_STEP")
    hg_env = strategic_envelope.validate(env)
    assert not hg_env.valid
    assert "INVENTED_PROSE_STEP" in hg_env.invalid_reasoning_steps


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
