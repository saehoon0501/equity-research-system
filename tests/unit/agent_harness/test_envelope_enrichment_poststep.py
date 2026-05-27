"""Tests for the Phase-2 envelope-enrichment post-step in orchestrator_step.

These exercise the best-effort, decision-preserving side-effect wired into
``run_step`` (P2-A):

  1. The hybrid gate's ``result_dict['gate_decision']`` is persisted onto the
     envelope FILE as ``envelope['gate_decision']`` (always on, cheap).
  2. Advisory ``axis_a``/``axis_b`` blocks are spliced ONLY when
     ``INSIGHT_SCORING_ENABLED`` is truthy (default OFF).
  3. The PASS/RETRY/ESCALATE decision is identical whether the post-step
     succeeds or an injected error makes it fail — the post-step never
     changes the decision and never raises out of ``run_step``.

``validate_all`` is fully mocked (a hand-built AggregateValidationResult), so
these run with NO network and NO live DB. The hybrid (HG-40) outcome carries a
canned ``gate_decision`` block matching ``HybridResult.to_gate_decision()``.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

import src.agent_harness.orchestrator_step as ostep
from src.agent_harness.orchestrator_step import (
    EXIT_PASS,
    EXIT_RETRY,
    run_step,
)
from src.evaluator_gates import AggregateValidationResult
from src.evaluator_gates._outcome import GateOutcome


def _u() -> str:
    return str(uuid.uuid4())


def _gate_decision(verdict: str = "PASS", escalated: bool = False) -> dict:
    """Canonical gate_decision block (shape of HybridResult.to_gate_decision)."""
    return {
        "verdict": verdict,
        "deterministic": {"valid": True, "detail": {}},
        "advisory": {"verdict": "agree", "degraded": False},
        "escalated": escalated,
    }


def _hybrid_outcome(*, valid: bool = True, with_gate_decision: bool = True) -> GateOutcome:
    rd: dict = {"hybrid_verdict": "PASS" if valid else "FAIL"}
    if with_gate_decision:
        rd["gate_decision"] = _gate_decision()
    return GateOutcome(
        gate_id="HG-40",
        gate_name="hybrid_gate",
        valid=valid,
        result_dict=rd,
        error_fingerprint="ok" if valid else "spine_fail:x",
    )


def _other_outcome(*, valid: bool = True, gate_id: str = "HG-23") -> GateOutcome:
    return GateOutcome(
        gate_id=gate_id,
        gate_name="envelope_shape",
        valid=valid,
        result_dict={"valid": valid},
        error_fingerprint="ok" if valid else "shape_fail",
    )


def _make_validation(
    *,
    valid: bool,
    include_hybrid: bool = True,
    hybrid_valid: bool = True,
    hybrid_with_gate_decision: bool = True,
) -> AggregateValidationResult:
    gates: list[GateOutcome] = [_other_outcome(valid=valid)]
    if include_hybrid:
        gates.append(
            _hybrid_outcome(valid=hybrid_valid, with_gate_decision=hybrid_with_gate_decision)
        )
    summary = {"envelope_shape": "pass" if valid else "fail"}
    if include_hybrid:
        summary["hybrid_gate"] = "pass" if hybrid_valid else "fail"
    return AggregateValidationResult(
        valid=valid,
        artifact_path=None,
        gates=gates,
        summary=summary,
    )


@pytest.fixture
def envelope_file(tmp_path: Path) -> Path:
    p = tmp_path / "envelope.json"
    p.write_text(json.dumps({"ticker": "TEST", "as_of": "2026-05-16"}), encoding="utf-8")
    return p


def _patch_validate_all(monkeypatch, validation: AggregateValidationResult) -> None:
    monkeypatch.setattr(ostep, "validate_all", lambda *a, **k: validation)


def _run(envelope_file: Path, tmp_path: Path, **overrides):
    kwargs = dict(
        envelope_path=envelope_file,
        run_id=_u(),
        agent_type="test-agent",
        attempt_cost_usd=1.0,
        state_dir=tmp_path / "state",
        audit_path=tmp_path / "audit.jsonl",
    )
    kwargs.update(overrides)
    return run_step(**kwargs)


# --------------------------------------------------------------------------
# 1. gate_decision persisted to the envelope file
# --------------------------------------------------------------------------
def test_gate_decision_persisted_to_envelope_file(monkeypatch, envelope_file, tmp_path):
    _patch_validate_all(monkeypatch, _make_validation(valid=True))
    monkeypatch.delenv("INSIGHT_SCORING_ENABLED", raising=False)

    _run(envelope_file, tmp_path)

    written = json.loads(envelope_file.read_text(encoding="utf-8"))
    assert "gate_decision" in written
    assert set(written["gate_decision"].keys()) == {
        "verdict",
        "deterministic",
        "advisory",
        "escalated",
    }


def test_gate_decision_persisted_even_on_fail_decision(monkeypatch, envelope_file, tmp_path):
    # RETRY decision still gets the side-effect writeback.
    _patch_validate_all(
        monkeypatch, _make_validation(valid=False, hybrid_valid=False)
    )
    monkeypatch.delenv("INSIGHT_SCORING_ENABLED", raising=False)

    decision = _run(envelope_file, tmp_path)

    assert decision.decision == "RETRY"
    written = json.loads(envelope_file.read_text(encoding="utf-8"))
    assert "gate_decision" in written


def test_no_gate_decision_when_hybrid_absent(monkeypatch, envelope_file, tmp_path):
    _patch_validate_all(monkeypatch, _make_validation(valid=True, include_hybrid=False))
    monkeypatch.delenv("INSIGHT_SCORING_ENABLED", raising=False)

    _run(envelope_file, tmp_path)

    written = json.loads(envelope_file.read_text(encoding="utf-8"))
    assert "gate_decision" not in written


def test_no_gate_decision_when_block_missing(monkeypatch, envelope_file, tmp_path):
    # Hybrid gate ran but emitted no gate_decision -> skip silently.
    _patch_validate_all(
        monkeypatch,
        _make_validation(valid=True, hybrid_with_gate_decision=False),
    )
    monkeypatch.delenv("INSIGHT_SCORING_ENABLED", raising=False)

    _run(envelope_file, tmp_path)

    written = json.loads(envelope_file.read_text(encoding="utf-8"))
    assert "gate_decision" not in written


# --------------------------------------------------------------------------
# 2. axis enrichment behind the default-OFF flag
# --------------------------------------------------------------------------
def test_axes_not_added_when_flag_off(monkeypatch, envelope_file, tmp_path):
    _patch_validate_all(monkeypatch, _make_validation(valid=True))
    monkeypatch.delenv("INSIGHT_SCORING_ENABLED", raising=False)

    _run(envelope_file, tmp_path)

    written = json.loads(envelope_file.read_text(encoding="utf-8"))
    assert "axis_a" not in written
    assert "axis_b" not in written


def test_axes_added_when_flag_on(monkeypatch, envelope_file, tmp_path):
    _patch_validate_all(monkeypatch, _make_validation(valid=True))
    monkeypatch.setenv("INSIGHT_SCORING_ENABLED", "1")

    _run(envelope_file, tmp_path)

    written = json.loads(envelope_file.read_text(encoding="utf-8"))
    assert "axis_a" in written
    assert "axis_b" in written
    # Offline, the enrichment adapter degrades to advisory blocks (never None).
    assert isinstance(written["axis_a"], dict)
    assert isinstance(written["axis_b"], dict)


# --------------------------------------------------------------------------
# 3. decision is invariant to post-step success/failure
# --------------------------------------------------------------------------
def test_decision_unchanged_and_no_raise_on_poststep_error(monkeypatch, envelope_file, tmp_path):
    validation = _make_validation(valid=True)
    _patch_validate_all(monkeypatch, validation)
    monkeypatch.delenv("INSIGHT_SCORING_ENABLED", raising=False)

    # Baseline decision with a healthy post-step.
    baseline = _run(envelope_file, tmp_path)
    assert baseline.decision == "PASS"
    assert baseline.exit_code == EXIT_PASS

    # Now inject a failure into the post-step internals and confirm the
    # decision is identical and run_step does not raise.
    def _boom(*a, **k):
        raise RuntimeError("injected gate_decision/scoring error")

    monkeypatch.setattr(ostep, "_extract_gate_decision", _boom)

    envelope_file.write_text(
        json.dumps({"ticker": "TEST", "as_of": "2026-05-16"}), encoding="utf-8"
    )
    after = _run(envelope_file, tmp_path)

    assert after.decision == baseline.decision == "PASS"
    assert after.exit_code == baseline.exit_code == EXIT_PASS
    # Post-step swallowed the error: no gate_decision written.
    written = json.loads(envelope_file.read_text(encoding="utf-8"))
    assert "gate_decision" not in written


def test_retry_decision_unchanged_on_poststep_error(monkeypatch, envelope_file, tmp_path):
    _patch_validate_all(monkeypatch, _make_validation(valid=False, hybrid_valid=False))
    monkeypatch.delenv("INSIGHT_SCORING_ENABLED", raising=False)

    def _boom(*a, **k):
        raise RuntimeError("injected error")

    monkeypatch.setattr(ostep, "_extract_gate_decision", _boom)

    decision = _run(envelope_file, tmp_path)

    assert decision.decision == "RETRY"
    assert decision.exit_code == EXIT_RETRY


# --------------------------------------------------------------------------
# 4. C1 — decoupled writes: an enrichment-branch failure must NOT drop the
#    always-on gate_decision write.
# --------------------------------------------------------------------------
def test_gate_decision_persisted_when_enrichment_branch_raises(
    monkeypatch, envelope_file, tmp_path
):
    # Flag ON so the opt-in axis-enrichment branch runs; make enrich_envelope
    # blow up. The decoupled gate_decision write must still land, the decision
    # must be unchanged, and run_step must not raise.
    validation = _make_validation(valid=True)
    _patch_validate_all(monkeypatch, validation)
    monkeypatch.setenv("INSIGHT_SCORING_ENABLED", "1")

    import src.scoring.enrichment as enrichment_mod

    def _boom(*a, **k):
        raise RuntimeError("injected enrichment error")

    # Patch on the source module: enrich_envelope is lazily imported inside
    # the post-step, so the lookup resolves to this module attribute.
    monkeypatch.setattr(enrichment_mod, "enrich_envelope", _boom)

    decision = _run(envelope_file, tmp_path)

    # Decision unaffected; no raise out of run_step.
    assert decision.decision == "PASS"
    assert decision.exit_code == EXIT_PASS

    written = json.loads(envelope_file.read_text(encoding="utf-8"))
    # Always-on write survived the enrichment-branch failure (the C1 fix).
    assert "gate_decision" in written
    assert set(written["gate_decision"].keys()) == {
        "verdict",
        "deterministic",
        "advisory",
        "escalated",
    }
    # Enrichment failed, so its axes were never spliced.
    assert "axis_a" not in written
    assert "axis_b" not in written


# --------------------------------------------------------------------------
# 5. A4 — the envelope file is rewritten atomically (tmp + os.replace).
# --------------------------------------------------------------------------
def test_envelope_write_leaves_no_tmp_sibling(monkeypatch, envelope_file, tmp_path):
    _patch_validate_all(monkeypatch, _make_validation(valid=True))
    monkeypatch.delenv("INSIGHT_SCORING_ENABLED", raising=False)

    _run(envelope_file, tmp_path)

    written = json.loads(envelope_file.read_text(encoding="utf-8"))
    assert "gate_decision" in written
    # A clean atomic write must not leave a *.tmp sibling behind.
    leftovers = list(envelope_file.parent.glob(envelope_file.name + ".*.tmp"))
    assert leftovers == [], f"unexpected leftover temp files: {leftovers}"


def test_envelope_write_uses_os_replace(monkeypatch, envelope_file, tmp_path):
    _patch_validate_all(monkeypatch, _make_validation(valid=True))
    monkeypatch.delenv("INSIGHT_SCORING_ENABLED", raising=False)

    calls: list[tuple[str, str]] = []
    real_replace = ostep.os.replace

    def _spy_replace(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(ostep.os, "replace", _spy_replace)

    _run(envelope_file, tmp_path)

    # The envelope path must have been written via os.replace (atomic swap),
    # never a direct open(path, "w") truncating write.
    assert any(dst == str(envelope_file) for _, dst in calls), (
        f"os.replace was not used to write the envelope; calls={calls}"
    )
