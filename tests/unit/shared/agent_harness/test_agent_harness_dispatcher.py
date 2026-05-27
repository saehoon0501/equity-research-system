"""Integration tests for the agent_harness dispatcher retry loop."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from src.shared.agent_harness import (
    AgentRunOutput,
    DispatchEscalation,
    InMemoryAuditSink,
    build_delta_prompt,
    dispatch_with_validation,
)
from src.eval.gates import validate_all


# ---------- helpers ---------------------------------------------------------


def _u() -> str:
    return str(uuid.uuid4())


def _valid_envelope() -> dict[str, Any]:
    """Build a minimal envelope that passes every Tier-1 gate."""
    return {
        "ticker": "TEST",
        "as_of": "2026-05-16",
        "tier": "core_fundamental",
        "mode": "B",
        "tl_dr": {
            "decision_headline": "hold",
            "scenarios_quant": {"bear": "x", "base": "y", "bull": "z"},
            "scenarios_strategic": {"bear": "x", "base": "y", "bull": "z"},
            "operating_ranges": "x",
            "top_catalysts_90d": ["a"],
            "reevaluation_triggers": ["a"],
        },
        "report": {
            "sentiment": {
                "reading": "neutral",
                "detail": "...",
                "evidence_refs": [_u()],
                "framework_keys": ["pan_poteshman_pcratio_2006"],
                "cdd_memo_refs": ["a.md"],
            },
            "trend": {
                "reading": "range",
                "detail": "...",
                "evidence_refs": [_u()],
                "framework_keys": ["cremers_weinbaum_iv_spread_2008"],
                "cdd_memo_refs": ["a.md"],
            },
            "structural_theory": {
                "reading": "intact",
                "detail": "...",
                "evidence_refs": [_u()],
                "framework_keys": ["helmer_7_powers"],
                "cdd_memo_refs": ["a.md"],
            },
            "technical_entry": {
                "reading": "wait",
                "detail": "...",
                "evidence_refs": [_u()],
                "framework_keys": ["damodaran_narrative_dcf"],
                "cdd_memo_refs": ["a.md"],
            },
            "technical_exit": {
                "reading": "n/a",
                "detail": "...",
                "evidence_refs": [_u()],
                "framework_keys": ["damodaran_narrative_dcf"],
                "cdd_memo_refs": ["a.md"],
            },
            "reasoning": {
                "reading": "converging",
                "detail": "...",
                "evidence_refs": [_u()],
                "framework_keys": ["mauboussin_reverse_dcf"],
                "cdd_memo_refs": ["a.md"],
            },
        },
        "audit_trail_hint": {
            "instructions_for_operator": "see evidence_index",
            "cross_run_artifact_ids": {"quant_brief_id": _u()},
            "evidence_index_query_template": "SELECT ...",
        },
        "summary_code": "HOLD",
        "conviction": "MEDIUM",
        "size_band_if_long": {
            "min_book_pct": 0.0,
            "max_book_pct": 0.0,
            "midpoint": 0.0,
        },
        "sleeve_cap_check": {"status": "PASS"},
        "counterfactual_top3_summary": {
            "survivor": 3,
            "diluted_survivor": 0,
            "non_survivor": 0,
            "lens_disciplined_note": "3 SURVIVOR analogs",
        },
        "adversarial_stress_test": {
            "claims_inverted_count": 6,
            "stress_passed": 4,
            "stress_open": 2,
            "stress_failed": 0,
            "catastrophic_failures": 0,
            "bear_confidence_proxy": 0.4,
            "outside_view_alert": True,
            "outside_view_divergence_pp_raw": 4.95,
            "corrected_divergence_pp": 3.96,
            "r_coefficient_used": 0.20,
            "reference_source": "base_rates_cohort_refined.test",
            "cohort_values_placeholder": True,
            "outside_view_emission_missing": False,
            "helmer_gate_fired": True,
            "helmer_gate_verdict": "stress_passed",
            "reinvestment_moat_quality_label": "A",
            "intuitive_growth_pct": 15.95,
            "reference_class_growth_mean_pct": 11.0,
            "corrected_growth_pct": 14.96,
        },
        "catalyst_modifier_applied": "0 (neutral)",
        "veto_reason": None,
        "sleeve_reference": None,
        "conviction_rationale": "MEDIUM by §5",
        "evidence_index_refs": [_u(), _u()],
        "rule_engine_version": "v0.2-2026-05-12",
        "conviction_from_rule": "MEDIUM",
        "conviction_emitted": "MEDIUM",
        "conviction_override": False,
    }


# ---------- tests -----------------------------------------------------------


def test_pass_on_first_attempt() -> None:
    """Valid envelope → 1 attempt, no retry, no escalation."""
    audit = InMemoryAuditSink()
    valid_env = _valid_envelope()

    def runner(prompt: str, *, attempt_n: int) -> AgentRunOutput:
        return AgentRunOutput(
            artifact=valid_env,
            artifact_path="/tmp/test.json",
            cost_estimate_usd=5.0,
            duration_ms=100,
        )

    result = dispatch_with_validation(
        agent_type="test-agent",
        run_id="r1",
        initial_prompt="emit it",
        agent_runner=runner,
        audit_sink=audit,
    )
    assert result.passed
    assert result.attempt_count == 1
    assert result.cumulative_cost_usd == 5.0
    assert not result.escalated
    assert audit.rows[-1]["validation_passed"] is True


def test_recovers_on_second_attempt() -> None:
    """First attempt invalid → delta-prompt → valid on attempt 2."""
    audit = InMemoryAuditSink()
    valid_env = _valid_envelope()

    calls = {"n": 0}

    def runner(prompt: str, *, attempt_n: int) -> AgentRunOutput:
        calls["n"] += 1
        if attempt_n == 1:
            # Drop a required field on first attempt.
            bad = dict(valid_env)
            del bad["evidence_index_refs"]
            return AgentRunOutput(
                artifact=bad,
                artifact_path="/tmp/test.json",
                cost_estimate_usd=5.0,
                duration_ms=100,
            )
        # Verify the delta-prompt mentions the missing field.
        assert "evidence_index_refs" in prompt
        return AgentRunOutput(
            artifact=valid_env,
            artifact_path="/tmp/test.json",
            cost_estimate_usd=2.0,
            duration_ms=80,
        )

    result = dispatch_with_validation(
        agent_type="test-agent",
        run_id="r2",
        initial_prompt="emit it",
        agent_runner=runner,
        audit_sink=audit,
    )
    assert result.passed
    assert result.attempt_count == 2
    assert calls["n"] == 2
    assert result.cumulative_cost_usd == 7.0
    # Verify attempt 1 was logged as fail, attempt 2 as pass.
    fails = [r for r in audit.rows if r.get("validation_passed") is False]
    passes = [r for r in audit.rows if r.get("validation_passed") is True]
    assert len(fails) == 1
    assert len(passes) == 1


def test_stuck_loop_escalates_early() -> None:
    """Same fingerprint twice in a row → escalate before attempt 3."""
    audit = InMemoryAuditSink()
    valid_env = _valid_envelope()
    bad = dict(valid_env)
    del bad["summary_code"]  # same failure each attempt

    def runner(prompt: str, *, attempt_n: int) -> AgentRunOutput:
        return AgentRunOutput(
            artifact=dict(bad),
            cost_estimate_usd=3.0,
            duration_ms=50,
        )

    with pytest.raises(DispatchEscalation) as excinfo:
        dispatch_with_validation(
            agent_type="test-agent",
            run_id="r3",
            initial_prompt="emit it",
            agent_runner=runner,
            audit_sink=audit,
            max_attempts=3,
        )
    assert excinfo.value.reason == "stuck_loop"
    # Should have escalated after exactly 2 attempts (same fingerprint).
    assert excinfo.value.result.attempt_count == 2


def test_max_attempts_escalates() -> None:
    """3 distinct failures still escalate at attempt 3."""
    audit = InMemoryAuditSink()
    valid_env = _valid_envelope()

    def runner(prompt: str, *, attempt_n: int) -> AgentRunOutput:
        # Different failure each attempt → different fingerprints, so no
        # stuck-loop short-circuit; but still 3 failures total.
        bad = dict(valid_env)
        if attempt_n == 1:
            del bad["summary_code"]
        elif attempt_n == 2:
            del bad["conviction"]
        else:
            del bad["mode"]
        return AgentRunOutput(
            artifact=bad,
            cost_estimate_usd=3.0,
            duration_ms=50,
        )

    with pytest.raises(DispatchEscalation) as excinfo:
        dispatch_with_validation(
            agent_type="test-agent",
            run_id="r4",
            initial_prompt="emit it",
            agent_runner=runner,
            audit_sink=audit,
            max_attempts=3,
        )
    assert excinfo.value.reason == "max_attempts_exhausted"
    assert excinfo.value.result.attempt_count == 3


def test_cost_ceiling_escalates() -> None:
    """Cumulative cost ≥ ceiling on the NEXT attempt boundary → escalate."""
    audit = InMemoryAuditSink()
    valid_env = _valid_envelope()
    bad = dict(valid_env)
    del bad["summary_code"]
    bad2 = dict(valid_env)
    del bad2["conviction"]

    calls = {"n": 0}

    def runner(prompt: str, *, attempt_n: int) -> AgentRunOutput:
        calls["n"] += 1
        # First call: $20. Second call: would be requested, but cumulative
        # already at $20 ≥ ceiling $10 ⇒ escalate without running.
        return AgentRunOutput(
            artifact=bad if attempt_n == 1 else bad2,
            cost_estimate_usd=20.0,
            duration_ms=50,
        )

    with pytest.raises(DispatchEscalation) as excinfo:
        dispatch_with_validation(
            agent_type="test-agent",
            run_id="r5",
            initial_prompt="emit it",
            agent_runner=runner,
            audit_sink=audit,
            max_attempts=3,
            cost_ceiling_usd=10.0,
        )
    assert excinfo.value.reason == "cost_ceiling"
    # Should have called the runner exactly once before cost-ceiling fired.
    assert calls["n"] == 1


def test_agent_runner_exception_escalates() -> None:
    """An exception from the agent runner is captured + escalated cleanly."""
    audit = InMemoryAuditSink()

    def runner(prompt: str, *, attempt_n: int) -> AgentRunOutput:
        raise RuntimeError("agent crashed")

    with pytest.raises(DispatchEscalation) as excinfo:
        dispatch_with_validation(
            agent_type="test-agent",
            run_id="r6",
            initial_prompt="emit it",
            agent_runner=runner,
            audit_sink=audit,
        )
    assert excinfo.value.reason == "agent_error"
    assert any(
        r.get("error_fingerprint", "").startswith("agent_error:RuntimeError")
        for r in audit.rows
    )


def test_audit_rows_per_attempt() -> None:
    """One audit row per attempt, with cumulative_cost tracked across rows."""
    audit = InMemoryAuditSink()
    valid_env = _valid_envelope()

    def runner(prompt: str, *, attempt_n: int) -> AgentRunOutput:
        if attempt_n == 1:
            bad = dict(valid_env)
            del bad["conviction"]
            return AgentRunOutput(artifact=bad, cost_estimate_usd=5.0)
        return AgentRunOutput(artifact=valid_env, cost_estimate_usd=3.0)

    result = dispatch_with_validation(
        agent_type="test-agent",
        run_id="r7",
        initial_prompt="emit it",
        agent_runner=runner,
        audit_sink=audit,
    )
    # Two attempt rows + zero escalation rows (passed).
    assert len(audit.rows) == 2
    assert audit.rows[0]["cumulative_cost_usd"] == 5.0
    assert audit.rows[1]["cumulative_cost_usd"] == 8.0
    assert audit.rows[1]["prompt_kind"] == "delta"
    assert audit.rows[1]["delta_prompt_hash"] is not None


def test_build_delta_prompt_cites_failed_gates() -> None:
    """The delta-prompt body must name the failed gates + the prior artifact path."""
    bad = _valid_envelope()
    del bad["evidence_index_refs"]
    result = validate_all(bad)
    assert not result.valid

    prompt = build_delta_prompt(
        result,
        prior_artifact_path="/tmp/prior.json",
        agent_type="pm-supervisor",
    )
    assert "pm-supervisor" in prompt
    assert "evidence_index_refs" in prompt
    assert "/tmp/prior.json" in prompt
    assert "HG-23" in prompt or "HG-26" in prompt
