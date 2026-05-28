"""Phase 2 catalyst-scout envelope cutover — parity gate + golden tests.

Per harness-v4-final Phase 2 (2026-05-22). Same shape as the tactical
parity tests (Phase 1) — three-way diff on rendered prompt bytes +
validator pass/fail tuple + delta-prompt bytes on canned fixtures.
"""
from __future__ import annotations

import sys

from src.shared.agent_harness.delta_prompt import build_delta_prompt
from src.shared.agent_harness.dispatch_template import (
    EvidenceRef,
    lint_dispatch_prompt,
    render_dispatch_prompt,
)
from src.shared.agent_harness.envelopes import to_gate_outcome
from src.shared.agent_harness.envelopes import catalyst as catalyst_envelope
from src.eval.gates import AggregateValidationResult
from src.eval.gates.catalyst_memo_shape import validate_catalyst_memo_shape


_RUN_ID = "22222222-3333-4444-8555-666666666666"
_PARAMETERS_USED_BLOCK = (
    "PARAMETERS_USED (parameters_version_max: v1.1, "
    "effective_parameters_hash: deadbeef, tag: phase-2-pilot):\n"
    "  catalyst_scout.lookback_days: 90\n"
    "  catalyst_scout.iv_spread_threshold_pct: 5.0"
)


def _valid_envelope() -> dict:
    return {
        "ticker": "MSFT",
        "tier": "core_fundamental",
        "as_of": "2026-05-22",
        "catalysts": [
            {
                "date": "2026-07-23",
                "type": "earnings",
                "source": "Wall Street Horizon",
                "kpi_impact": "EPS",
                "confidence": "high",
            }
        ],
        "positioning": {
            "tier_insufficient": False,
            "iv_spread": 0.03,
            "p_c_ratio": 0.75,
            "framework_keys": ["IV term structure", "P/C ratio"],
        },
        "institutional_flow": {
            "active_manager_conviction_read": "HOLD_THROUGH_PARABOLIC",
        },
        "sentiment_signals": [
            {
                "indicator": "AAII Bullish %",
                "reading": 45.2,
                "reading_date": "2026-05-21",
                "implication": "neutral",
            },
            {
                "indicator": "BofA FMS cash levels",
                "reading": 4.8,
                "reading_date": "2026-05-15",
                "implication": "neutral",
            },
            {
                "indicator": "Investors Intelligence",
                "reading": 50.0,
                "reading_date": "2026-05-21",
                "implication": "neutral",
            },
            {
                "indicator": "NAAIM exposure",
                "reading": 75.0,
                "reading_date": "2026-05-21",
                "implication": "neutral",
            },
        ],
        "sentiment_data_degraded": False,
        "conviction_modifier": {
            "direction": 0,
            "magnitude": "low",
            "reason": "no material 90-day catalysts",
        },
        "evidence_index_refs": [
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        ],
        "banned_outputs_check": True,
        "reasoning_path_taken": [
            "load_forward_catalyst_calendar",
            "rank_top_catalysts_90d",
            "load_options_positioning",
            "load_institutional_flow",
            "load_sentiment_indicators",
            "compute_sentiment_data_degraded",
            "derive_conviction_modifier",
            "emit_envelope",
        ],
    }


def test_render_lint_roundtrip() -> None:
    prompt = render_dispatch_prompt(
        agent_type="catalyst-scout",
        run_id=_RUN_ID,
        parameters_used_block=_PARAMETERS_USED_BLOCK,
        goal="Emit a CatalystEnvelope conforming to OUTPUT_SCHEMA",
        cdd_brief={"ticker": "MSFT", "tier": "core_fundamental"},
        evidence_refs=[
            EvidenceRef(
                uri="evidence://msft/wsh-calendar",
                evidence_uuid="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            ),
        ],
        reasoning_steps=catalyst_envelope.REASONING_STEPS,
        output_schema=catalyst_envelope.SCHEMA,
    )
    lint_dispatch_prompt(prompt)
    assert prompt.startswith("PARAMETERS_USED")
    assert f"run_id: {_RUN_ID}" in prompt


def test_valid_envelope_passes_both_gates() -> None:
    env = _valid_envelope()
    hg_env = catalyst_envelope.validate(env)
    hg_31 = validate_catalyst_memo_shape(env)
    assert hg_env.valid, f"HG-ENV failed: {hg_env.to_result_dict()}"
    assert hg_31.valid, f"HG-31 failed: {hg_31.__dict__}"


def test_invalid_catalyst_type_fails() -> None:
    env = _valid_envelope()
    env["catalysts"][0]["type"] = "earthquake"  # not in enum
    hg_env = catalyst_envelope.validate(env)
    assert not hg_env.valid
    assert any("catalysts[0].type" in e.path for e in hg_env.field_errors)


def test_invalid_modifier_direction_fails() -> None:
    env = _valid_envelope()
    env["conviction_modifier"]["direction"] = 5
    hg_env = catalyst_envelope.validate(env)
    assert not hg_env.valid


def test_tier_insufficient_consistency_predicate() -> None:
    env = _valid_envelope()
    env["positioning"]["tier_insufficient"] = True
    env["positioning"]["iv_spread"] = 0.03  # forbidden when insufficient
    hg_env = catalyst_envelope.validate(env)
    assert not hg_env.valid
    assert "tier_insufficient_consistency" in hg_env.failed_predicates


def test_invented_reasoning_step_fails() -> None:
    env = _valid_envelope()
    env["reasoning_path_taken"].append("PROSE_FREEDOM_STEP")
    hg_env = catalyst_envelope.validate(env)
    assert not hg_env.valid
    assert "PROSE_FREEDOM_STEP" in hg_env.invalid_reasoning_steps


def test_delta_prompt_renders_envelope_failures() -> None:
    env = _valid_envelope()
    env["catalysts"][0]["type"] = "earthquake"
    env["reasoning_path_taken"].append("INVENTED_STEP")
    r = catalyst_envelope.validate(env)
    agg = AggregateValidationResult(
        valid=False,
        artifact_path="/tmp/fixture.json",
        gates=[to_gate_outcome(r)],
    )
    dp = build_delta_prompt(
        agg, prior_artifact_path="/tmp/fixture.json",
        agent_type="catalyst-scout",
    )
    assert "earthquake" in dp
    assert "INVENTED_STEP" in dp


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
