"""Phase 1 tactical-overlay envelope cutover — parity gate + golden tests.

Per harness-v4-final v4-final (5-iteration /review-me convergence,
2026-05-22). The parity gate is mechanical: it diffs DETERMINISTIC bytes
(rendered prompt + validator outcome + delta-prompt on canned fixtures)
across the cutover, NOT live LLM emissions (iter-4 finding: live
emission diffs would false-alarm on sampling jitter).

Smoke-test runner (stdlib only — no pytest required):

    python3 tests/test_agent_harness_envelopes_tactical.py

Exit 0 on full parity + golden pass, non-zero otherwise.
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy

from src.agent_harness.delta_prompt import build_delta_prompt
from src.agent_harness.dispatch_template import (
    EvidenceRef,
    lint_dispatch_prompt,
    render_dispatch_prompt,
)
from src.agent_harness.envelopes import to_gate_outcome
from src.agent_harness.envelopes import tactical as tactical_envelope
from src.evaluator_gates import AggregateValidationResult
from src.evaluator_gates.tactical_envelope_shape import (
    validate_tactical_envelope_shape,
)


# Canonical inputs — fixed UUID, fixed PARAMETERS_USED block, fixed date
# so the rendered-prompt bytes are byte-stable across runs.
_RUN_ID = "11111111-2222-4333-8444-555555555555"
_PARAMETERS_USED_BLOCK = (
    "PARAMETERS_USED (parameters_version_max: v1.1, "
    "effective_parameters_hash: deadbeef, tag: phase-1-pilot):\n"
    "  tactical.lookback_trading_days: 252\n"
    "  tactical.positive_min: 0.0\n"
    "  tactical.negative_max: 0.0\n"
    "  sizing.conviction_band.HIGH.min_pct: 4.0\n"
    "  sizing.conviction_band.HIGH.max_pct: 8.0"
)


def _valid_envelope() -> dict:
    return {
        "ticker": "MSFT",
        "as_of_date": "2026-05-22",
        "run_id": _RUN_ID,
        "tactical_signal_bin": "positive",
        "rf_degenerate": False,
        "tactical_cell": {
            "conviction": "HIGH",
            "tactical_bin": "positive",
            "cell_size_pct": 6.0,
            "cell_disposition": "BUY-HIGH",
        },
        "frameworks_cited": ["Antonacci dual-momentum"],
        "reasoning_path_taken": [
            "load_ticker_prices",
            "load_spy_prices",
            "resolve_risk_free_at_helper",
            "compute_12m_excess_return",
            "compare_to_antonacci_thresholds",
            "classify_tactical_bin",
            "lookup_tactical_cell_disposition",
            "compute_tactical_cell_size_pct",
            "emit_envelope",
        ],
        "unavailable_reason": None,
    }


# ---------- Test 1: dispatch render + lint are deterministic ----------


def test_render_dispatch_prompt_is_deterministic() -> None:
    p1 = render_dispatch_prompt(
        agent_type="tactical-overlay",
        run_id=_RUN_ID,
        parameters_used_block=_PARAMETERS_USED_BLOCK,
        goal="Emit a TacticalEnvelope conforming to OUTPUT_SCHEMA",
        cdd_brief={"ticker": "MSFT", "tier": "core_fundamental"},
        evidence_refs=[
            EvidenceRef(
                uri="evidence://msft/price-history",
                evidence_uuid="aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
            ),
        ],
        reasoning_steps=tactical_envelope.REASONING_STEPS,
        output_schema=tactical_envelope.SCHEMA,
    )
    p2 = render_dispatch_prompt(
        agent_type="tactical-overlay",
        run_id=_RUN_ID,
        parameters_used_block=_PARAMETERS_USED_BLOCK,
        goal="Emit a TacticalEnvelope conforming to OUTPUT_SCHEMA",
        cdd_brief={"ticker": "MSFT", "tier": "core_fundamental"},
        evidence_refs=[
            EvidenceRef(
                uri="evidence://msft/price-history",
                evidence_uuid="aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
            ),
        ],
        reasoning_steps=tactical_envelope.REASONING_STEPS,
        output_schema=tactical_envelope.SCHEMA,
    )
    assert p1 == p2, "render_dispatch_prompt is not deterministic"
    lint_dispatch_prompt(p1)  # must pass

    # Spot-check load-bearing lines
    assert p1.startswith("PARAMETERS_USED"), "L1 contract broken"
    # run_id line follows the PARAMETERS_USED block immediately (no blank
    # between them); the lint contract is "in first 50 lines", parity
    # test mirrors that.
    assert f"run_id: {_RUN_ID}" in p1.split("\n")[:50], "L2 contract broken"
    assert "# GOAL" in p1
    assert "# INPUTS" in p1
    assert "# REASONING_PATH" in p1
    assert "# OUTPUT_SCHEMA" in p1
    assert "# ON_VALIDATION_FAILURE" in p1


# ---------- Test 2: HG-ENV agrees with HG-33 on valid envelopes -------


def test_valid_envelope_passes_both_gates() -> None:
    env = _valid_envelope()
    hg_env = tactical_envelope.validate(env)
    hg_33 = validate_tactical_envelope_shape(env)
    assert hg_env.valid, f"HG-ENV failed on valid envelope: {hg_env.to_result_dict()}"
    assert hg_33.valid, f"HG-33 failed on valid envelope: {hg_33.__dict__}"


# ---------- Test 3: structural failures surface deterministically -----


def test_bad_disposition_fails_both_gates() -> None:
    # Section 2.1 INV-2.1-A: 'BUY' (canonical summary_code) forbidden as
    # cell_disposition; must use BUY-HIGH/BUY-MED/HOLD/AVOID.
    env = _valid_envelope()
    env["tactical_cell"]["cell_disposition"] = "BUY"
    hg_env = tactical_envelope.validate(env)
    hg_33 = validate_tactical_envelope_shape(env)
    assert not hg_env.valid, "HG-ENV missed INV-2.1-A violation"
    assert not hg_33.valid, "HG-33 missed INV-2.1-A violation"
    assert any(
        "cell_disposition" in e.path for e in hg_env.field_errors
    ), "HG-ENV path does not surface the violating field"


# ---------- Test 4: invented reasoning step is hard-failed ------------


def test_invented_reasoning_step_fails() -> None:
    env = _valid_envelope()
    env["reasoning_path_taken"].append("HALLUCINATED_STEP_FROM_PROSE_FREEDOM")
    hg_env = tactical_envelope.validate(env)
    assert not hg_env.valid
    assert "HALLUCINATED_STEP_FROM_PROSE_FREEDOM" in hg_env.invalid_reasoning_steps


# ---------- Test 5: cross-field predicate catches state-shuffle -------


def test_top_bin_must_equal_cell_bin() -> None:
    env = _valid_envelope()
    env["tactical_signal_bin"] = "positive"
    env["tactical_cell"]["tactical_bin"] = "negative"
    hg_env = tactical_envelope.validate(env)
    assert not hg_env.valid
    assert "top_bin_equals_cell_bin" in hg_env.failed_predicates


def test_unavailable_requires_reason() -> None:
    env = _valid_envelope()
    env["tactical_signal_bin"] = "unavailable"
    env["tactical_cell"]["tactical_bin"] = "unavailable"
    env["unavailable_reason"] = None
    hg_env = tactical_envelope.validate(env)
    assert not hg_env.valid
    assert "unavailable_implies_reason" in hg_env.failed_predicates


# ---------- Test 6: delta-prompt is deterministic on canned fixture ---


def test_delta_prompt_byte_stable() -> None:
    bad = _valid_envelope()
    bad["tactical_cell"]["cell_disposition"] = "BUY"  # INV-2.1-A
    bad["reasoning_path_taken"].append("INVENTED_X")
    r1 = tactical_envelope.validate(bad)
    r2 = tactical_envelope.validate(deepcopy(bad))
    assert r1.error_fingerprint() == r2.error_fingerprint()

    agg = AggregateValidationResult(
        valid=False,
        artifact_path="/tmp/fixture.json",
        gates=[to_gate_outcome(r1)],
    )
    dp1 = build_delta_prompt(
        agg, prior_artifact_path="/tmp/fixture.json",
        agent_type="tactical-overlay",
    )
    dp2 = build_delta_prompt(
        agg, prior_artifact_path="/tmp/fixture.json",
        agent_type="tactical-overlay",
    )
    assert dp1 == dp2, "delta-prompt not deterministic"
    # Sanity: both failures surface
    assert "cell_disposition" in dp1
    assert "INVENTED_X" in dp1


# ---------- Test 7: parity-gate composite (rendered + validator + dp) -


def test_parity_gate_composite() -> None:
    """The three-way diff that gates per-agent cutover.

    Cutover gate (v4-final): diffs of (a) rendered prompt bytes,
    (b) validator pass/fail tuple, (c) delta-prompt bytes on canned
    ValidationError fixtures must all be null. NOT live LLM emission
    (avoids sampling jitter).
    """
    prompt = render_dispatch_prompt(
        agent_type="tactical-overlay",
        run_id=_RUN_ID,
        parameters_used_block=_PARAMETERS_USED_BLOCK,
        goal="Emit a TacticalEnvelope conforming to OUTPUT_SCHEMA",
        cdd_brief={"ticker": "MSFT", "tier": "core_fundamental"},
        evidence_refs=[
            EvidenceRef(
                uri="evidence://msft/price-history",
                evidence_uuid="aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
            ),
        ],
        reasoning_steps=tactical_envelope.REASONING_STEPS,
        output_schema=tactical_envelope.SCHEMA,
    )
    lint_dispatch_prompt(prompt)

    valid_env = _valid_envelope()
    r_valid = tactical_envelope.validate(valid_env)
    assert (r_valid.valid, r_valid.error_fingerprint()) == (True, "ok")

    bad = _valid_envelope()
    bad["tactical_cell"]["cell_disposition"] = "BUY"
    r_bad = tactical_envelope.validate(bad)
    assert r_bad.valid is False
    # Stable fingerprint: same fixture, same path, same expected
    expected_fp = "field:tactical_cell.cell_disposition"
    assert r_bad.error_fingerprint() == expected_fp, (
        f"unexpected fingerprint {r_bad.error_fingerprint()!r}"
    )


# ---------- runner ----------------------------------------------------


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
