"""Tests for src.shared.agent_harness.orchestrator_step + scripts/validate_envelope.sh.

Covers the stateful per-attempt CLI used by the orchestrator's bash hook:

- PASS path (exit 0).
- RETRY path (exit 10) with delta_prompt in stdout.
- Stuck-loop escalation (exit 11) after 2 identical fingerprints.
- Max-attempts escalation (exit 11) at attempt 3.
- Cost-ceiling escalation (exit 11) when cumulative ≥ ceiling.
- State + audit persistence across invocations.
- End-to-end through scripts/validate_envelope.sh.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from src.shared.agent_harness.orchestrator_step import (
    EXIT_ESCALATE,
    EXIT_PASS,
    EXIT_RETRY,
    StepState,
    run_step,
)


def _u() -> str:
    return str(uuid.uuid4())


def _valid_envelope() -> dict:
    """Minimal envelope that passes all 6 gates."""
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
            row: {
                "reading": "x",
                "detail": "x",
                "evidence_refs": [_u()],
                "framework_keys": ["k"],
                "cdd_memo_refs": ["m.md"],
            }
            for row in (
                "sentiment",
                "trend",
                "structural_theory",
                "technical_entry",
                "technical_exit",
                "reasoning",
            )
        },
        "audit_trail_hint": {
            "instructions_for_operator": "x",
            "cross_run_artifact_ids": {"q": _u()},
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
            "lens_disciplined_note": "x",
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
            "reference_source": "x",
            "cohort_values_placeholder": False,
            "outside_view_emission_missing": False,
            "helmer_gate_fired": True,
            "helmer_gate_verdict": "stress_passed",
            "reinvestment_moat_quality_label": "A",
            "intuitive_growth_pct": 15.95,
            "reference_class_growth_mean_pct": 11.0,
            "corrected_growth_pct": 14.96,
        },
        "catalyst_modifier_applied": "0",
        "veto_reason": None,
        "conviction_rationale": "MEDIUM",
        "evidence_index_refs": [_u(), _u()],
        "rule_engine_version": "v0.2",
        "conviction_from_rule": "MEDIUM",
        "conviction_emitted": "MEDIUM",
        "conviction_override": False,
    }


def _write_envelope(path: Path, env: dict) -> Path:
    path.write_text(json.dumps(env), encoding="utf-8")
    return path


# ---------- run_step direct (Python boundary) ------------------------------


def test_pass_on_first_attempt(tmp_path: Path) -> None:
    env_path = _write_envelope(tmp_path / "env.json", _valid_envelope())
    state_dir = tmp_path / "state"
    audit_path = tmp_path / "audit.jsonl"

    decision = run_step(
        envelope_path=env_path,
        run_id="r1",
        agent_type="pm-supervisor",
        attempt_cost_usd=5.0,
        state_dir=state_dir,
        audit_path=audit_path,
    )
    assert decision.decision == "PASS"
    assert decision.exit_code == EXIT_PASS
    assert decision.attempt_n == 1
    assert decision.cumulative_cost_usd == 5.0
    assert decision.delta_prompt is None

    # State file written.
    state = StepState.load(state_dir / "r1__pm-supervisor.json")
    assert state.status == "passed"
    assert state.attempt_count == 1

    # Audit row written.
    rows = [json.loads(l) for l in audit_path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["decision"] == "PASS"


def test_retry_with_delta_prompt(tmp_path: Path) -> None:
    bad = _valid_envelope()
    del bad["summary_code"]
    env_path = _write_envelope(tmp_path / "env.json", bad)
    state_dir = tmp_path / "state"
    audit_path = tmp_path / "audit.jsonl"

    decision = run_step(
        envelope_path=env_path,
        run_id="r2",
        agent_type="pm-supervisor",
        attempt_cost_usd=4.0,
        state_dir=state_dir,
        audit_path=audit_path,
    )
    assert decision.decision == "RETRY"
    assert decision.exit_code == EXIT_RETRY
    assert decision.delta_prompt is not None
    assert "summary_code" in decision.delta_prompt
    assert "attempt 2 of 3" in decision.delta_prompt
    assert "HG-23" in decision.delta_prompt


def test_recovers_on_second_call(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    audit_path = tmp_path / "audit.jsonl"
    bad = _valid_envelope()
    del bad["summary_code"]
    env_bad = _write_envelope(tmp_path / "bad.json", bad)
    env_good = _write_envelope(tmp_path / "good.json", _valid_envelope())

    # Call 1: fail.
    d1 = run_step(
        envelope_path=env_bad,
        run_id="r3",
        agent_type="pm-supervisor",
        attempt_cost_usd=4.0,
        state_dir=state_dir,
        audit_path=audit_path,
    )
    assert d1.decision == "RETRY"
    assert d1.attempt_n == 1

    # Call 2: succeed.
    d2 = run_step(
        envelope_path=env_good,
        run_id="r3",
        agent_type="pm-supervisor",
        attempt_cost_usd=2.0,
        state_dir=state_dir,
        audit_path=audit_path,
    )
    assert d2.decision == "PASS"
    assert d2.attempt_n == 2
    assert d2.cumulative_cost_usd == 6.0

    state = StepState.load(state_dir / "r3__pm-supervisor.json")
    assert state.status == "passed"
    assert state.attempt_count == 2
    assert len(state.fingerprints) == 2


def test_stuck_loop_escalates(tmp_path: Path) -> None:
    """Same fingerprint twice in a row → ESCALATE on call 2."""
    state_dir = tmp_path / "state"
    audit_path = tmp_path / "audit.jsonl"
    bad = _valid_envelope()
    del bad["summary_code"]  # same failure both attempts
    env_path = _write_envelope(tmp_path / "bad.json", bad)

    d1 = run_step(
        envelope_path=env_path,
        run_id="r4",
        agent_type="pm-supervisor",
        attempt_cost_usd=3.0,
        state_dir=state_dir,
        audit_path=audit_path,
    )
    assert d1.decision == "RETRY"

    d2 = run_step(
        envelope_path=env_path,
        run_id="r4",
        agent_type="pm-supervisor",
        attempt_cost_usd=3.0,
        state_dir=state_dir,
        audit_path=audit_path,
    )
    assert d2.decision == "ESCALATE"
    assert d2.escalation_reason == "stuck_loop"
    assert d2.exit_code == EXIT_ESCALATE


def test_max_attempts_escalates(tmp_path: Path) -> None:
    """3 distinct failures → ESCALATE at attempt 3 (max_attempts_exhausted)."""
    state_dir = tmp_path / "state"
    audit_path = tmp_path / "audit.jsonl"
    v = _valid_envelope()

    # 3 different failure modes so fingerprints don't match.
    e1 = dict(v); del e1["summary_code"]
    e2 = dict(v); del e2["conviction"]
    e3 = dict(v); del e3["mode"]

    for n, env in enumerate((e1, e2, e3), start=1):
        path = _write_envelope(tmp_path / f"e{n}.json", env)
        decision = run_step(
            envelope_path=path,
            run_id="r5",
            agent_type="pm-supervisor",
            attempt_cost_usd=2.0,
            state_dir=state_dir,
            audit_path=audit_path,
        )
        if n < 3:
            assert decision.decision == "RETRY", f"call {n}"
        else:
            assert decision.decision == "ESCALATE"
            assert decision.escalation_reason == "max_attempts_exhausted"


def test_cost_ceiling_escalates(tmp_path: Path) -> None:
    """When cumulative cost crosses the ceiling on a failed attempt → ESCALATE."""
    state_dir = tmp_path / "state"
    audit_path = tmp_path / "audit.jsonl"
    bad = _valid_envelope()
    del bad["summary_code"]
    env_path = _write_envelope(tmp_path / "bad.json", bad)

    decision = run_step(
        envelope_path=env_path,
        run_id="r6",
        agent_type="pm-supervisor",
        attempt_cost_usd=15.0,  # > ceiling 10
        state_dir=state_dir,
        audit_path=audit_path,
        cost_ceiling_usd=10.0,
    )
    assert decision.decision == "ESCALATE"
    assert decision.escalation_reason == "cost_ceiling"


def test_audit_jsonl_append_only(tmp_path: Path) -> None:
    """Every call writes one audit row; nothing rewritten."""
    state_dir = tmp_path / "state"
    audit_path = tmp_path / "audit.jsonl"
    bad = _valid_envelope()
    del bad["summary_code"]
    env_bad = _write_envelope(tmp_path / "bad.json", bad)
    env_good = _write_envelope(tmp_path / "good.json", _valid_envelope())

    run_step(
        envelope_path=env_bad, run_id="r7", agent_type="pm-supervisor",
        attempt_cost_usd=1.0, state_dir=state_dir, audit_path=audit_path,
    )
    run_step(
        envelope_path=env_good, run_id="r7", agent_type="pm-supervisor",
        attempt_cost_usd=1.0, state_dir=state_dir, audit_path=audit_path,
    )
    rows = [json.loads(l) for l in audit_path.read_text().splitlines()]
    assert len(rows) == 2
    assert [r["decision"] for r in rows] == ["RETRY", "PASS"]
    assert [r["attempt_n"] for r in rows] == [1, 2]
    assert [r["cumulative_cost_usd"] for r in rows] == [1.0, 2.0]


def test_state_isolated_per_run_id_and_agent(tmp_path: Path) -> None:
    """Different (run_id, agent_type) ⇒ different state files."""
    state_dir = tmp_path / "state"
    audit_path = tmp_path / "audit.jsonl"
    env_good = _write_envelope(tmp_path / "good.json", _valid_envelope())

    run_step(
        envelope_path=env_good, run_id="rA", agent_type="pm-supervisor",
        attempt_cost_usd=1.0, state_dir=state_dir, audit_path=audit_path,
    )
    run_step(
        envelope_path=env_good, run_id="rB", agent_type="pm-supervisor",
        attempt_cost_usd=1.0, state_dir=state_dir, audit_path=audit_path,
    )
    run_step(
        envelope_path=env_good, run_id="rA", agent_type="catalyst-scout",
        attempt_cost_usd=1.0, state_dir=state_dir, audit_path=audit_path,
    )
    files = sorted(p.name for p in state_dir.iterdir())
    assert files == [
        "rA__catalyst-scout.json",
        "rA__pm-supervisor.json",
        "rB__pm-supervisor.json",
    ]


# ---------- bash wrapper boundary ------------------------------------------


def _run_bash(env_path: Path, **kwargs) -> tuple[int, str, str]:
    """Run scripts/validate_envelope.sh with the given args; return
    (exit_code, stdout, stderr)."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
    script = repo_root / "scripts" / "validate_envelope.sh"
    args = [
        str(script),
        "--envelope", str(env_path),
        "--run-id", kwargs.pop("run_id", "bash-test"),
        "--agent-type", kwargs.pop("agent_type", "pm-supervisor"),
        "--attempt-cost-usd", str(kwargs.pop("attempt_cost_usd", 1.0)),
        "--state-dir", kwargs.pop("state_dir"),
        "--audit-path", kwargs.pop("audit_path"),
    ]
    for k, v in kwargs.items():
        args.append(f"--{k.replace('_', '-')}")
        if not isinstance(v, bool):
            args.append(str(v))
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        env={"PYTHON": sys.executable, "PATH": str(repo_root)} | __import__("os").environ,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_bash_wrapper_pass(tmp_path: Path) -> None:
    env_path = _write_envelope(tmp_path / "env.json", _valid_envelope())
    rc, out, err = _run_bash(
        env_path,
        run_id="b1",
        state_dir=str(tmp_path / "state"),
        audit_path=str(tmp_path / "audit.jsonl"),
    )
    assert rc == 0
    payload = json.loads(out)
    assert payload["decision"] == "PASS"
    assert "[validate_envelope]" in err
    assert "decision=PASS" in err


def test_bash_wrapper_retry_emits_delta_prompt(tmp_path: Path) -> None:
    bad = _valid_envelope()
    del bad["summary_code"]
    env_path = _write_envelope(tmp_path / "bad.json", bad)
    rc, out, err = _run_bash(
        env_path,
        run_id="b2",
        state_dir=str(tmp_path / "state"),
        audit_path=str(tmp_path / "audit.jsonl"),
    )
    assert rc == EXIT_RETRY
    payload = json.loads(out)
    assert payload["decision"] == "RETRY"
    assert "summary_code" in payload["delta_prompt"]
    assert "HG-23" in payload["delta_prompt"]
    assert "decision=RETRY" in err


def test_bash_wrapper_escalate(tmp_path: Path) -> None:
    bad = _valid_envelope()
    del bad["summary_code"]
    env_path = _write_envelope(tmp_path / "bad.json", bad)

    rc1, _, _ = _run_bash(
        env_path, run_id="b3",
        state_dir=str(tmp_path / "state"),
        audit_path=str(tmp_path / "audit.jsonl"),
    )
    assert rc1 == EXIT_RETRY
    rc2, out2, _ = _run_bash(
        env_path, run_id="b3",
        state_dir=str(tmp_path / "state"),
        audit_path=str(tmp_path / "audit.jsonl"),
    )
    assert rc2 == EXIT_ESCALATE
    payload = json.loads(out2)
    assert payload["decision"] == "ESCALATE"
    assert payload["escalation_reason"] == "stuck_loop"
