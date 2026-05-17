"""Integration tests for validate_all artifact_type dispatching."""

from __future__ import annotations

import uuid

import pytest

from src.evaluator_gates import VALID_ARTIFACT_TYPES, validate_all


def _u() -> str:
    return str(uuid.uuid4())


def test_invalid_artifact_type_raises() -> None:
    with pytest.raises(ValueError):
        validate_all({}, artifact_type="not_a_type")


def test_valid_artifact_types_constant() -> None:
    assert set(VALID_ARTIFACT_TYPES) == {
        "pm_envelope", "quant_memo", "strategic_memo",
        "catalyst_memo", "cdd_memo",
    }


def test_pm_envelope_default_artifact_type() -> None:
    """Backward compat: omitting artifact_type defaults to pm_envelope."""
    r = validate_all({})
    assert not r.valid
    # pm_envelope runs 5 gates (sentiment skipped without indicators).
    gate_names = {g.gate_name for g in r.gates}
    assert "envelope_shape" in gate_names
    assert "evidence_uuid_check" in gate_names
    assert "sizing_math" in gate_names
    assert "counterfactual_catalog" in gate_names
    assert "outside_view_blend" in gate_names


def test_quant_memo_runs_quant_gates() -> None:
    r = validate_all({}, artifact_type="quant_memo")
    gate_names = {g.gate_name for g in r.gates}
    assert "quant_memo_shape" in gate_names
    assert "evidence_uuid_check" in gate_names
    assert "outside_view_blend" in gate_names
    # Should NOT include pm-envelope-only gates.
    assert "envelope_shape" not in gate_names
    assert "sizing_math" not in gate_names
    assert "counterfactual_catalog" not in gate_names


def test_strategic_memo_runs_strategic_gates() -> None:
    r = validate_all({}, artifact_type="strategic_memo")
    gate_names = {g.gate_name for g in r.gates}
    assert "strategic_memo_shape" in gate_names
    assert "evidence_uuid_check" in gate_names
    assert "envelope_shape" not in gate_names


def test_catalyst_memo_runs_catalyst_gates() -> None:
    r = validate_all({}, artifact_type="catalyst_memo")
    gate_names = {g.gate_name for g in r.gates}
    assert "catalyst_memo_shape" in gate_names
    assert "evidence_uuid_check" in gate_names


def test_cdd_memo_runs_cdd_gates() -> None:
    r = validate_all({}, artifact_type="cdd_memo")
    gate_names = {g.gate_name for g in r.gates}
    assert "cdd_memo_shape" in gate_names
    # CDD memo doesn't carry top-level evidence_index_refs (it carries
    # an integer count instead) — no UUID gate.
    assert "evidence_uuid_check" not in gate_names


def test_artifact_type_via_cli_quant_memo(tmp_path) -> None:
    """End-to-end: CLI with --artifact-type quant_memo."""
    import json
    import subprocess
    import sys
    from pathlib import Path

    memo_path = tmp_path / "quant.json"
    memo_path.write_text("{}", encoding="utf-8")

    repo_root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [
            sys.executable, "-m", "src.evaluator_gates",
            "--envelope", str(memo_path),
            "--artifact-type", "quant_memo",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert proc.returncode == 1  # invalid (empty memo fails shape gate)
    payload = json.loads(proc.stdout)
    gate_names = {g["gate_name"] for g in payload["gates"]}
    assert "quant_memo_shape" in gate_names
    assert "envelope_shape" not in gate_names


def test_artifact_type_via_orchestrator_step_cli(tmp_path) -> None:
    """End-to-end: orchestrator_step CLI also routes by --artifact-type."""
    import json
    import subprocess
    import sys
    from pathlib import Path

    memo_path = tmp_path / "strategic.json"
    memo_path.write_text("{}", encoding="utf-8")

    repo_root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [
            sys.executable, "-m", "src.agent_harness.orchestrator_step",
            "--envelope", str(memo_path),
            "--run-id", "art-type-test",
            "--agent-type", "strategic-analyst",
            "--artifact-type", "strategic_memo",
            "--attempt-cost-usd", "10.0",
            "--state-dir", str(tmp_path / "state"),
            "--audit-path", str(tmp_path / "audit.jsonl"),
        ],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    # Exit 10 = RETRY.
    assert proc.returncode == 10
    payload = json.loads(proc.stdout)
    assert payload["decision"] == "RETRY"
    assert "HG-30" in payload["failed_gate_ids"]
