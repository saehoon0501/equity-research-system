"""Unit tests for the in-session-monitor intervention-audit shape gate (HG-39).

Mirrors ``test_envelope_shape``-style presence-only validation (P13): the gate
checks KEY PRESENCE of the intervention-audit envelope, not value type-correctness
(type-correctness is the dataclass + richer contract test's job per P14).

Design contract (`.kiro/specs/in-session-monitor/design.md` §Gate —
intervention_audit_shape, §Data Models — InterventionAudit):

  Required keys: a ``keys`` block carrying the 4 correlation keys (run_id /
  code_version / param_version / walk_forward_window) nested, ``trigger_diagnostic``,
  ``verdict``, ``intervention_intent``, ``rationale`` (with a ``falsifiers``
  sub-key), and ``event_ts``.

Two surfaces are pinned:
  * ``validate_intervention_audit_shape`` DIRECTLY (the validator unit); and
  * the registry-dispatch path — the task's actual observable — that a canonical
    audit validates as PASS THROUGH ``validate_all(artifact_type=
    "intervention_audit")`` with NO spurious WS-6 ``hybrid_gate`` runner attached
    (Resolution A: the artifact is registered post-hybrid-loop in _registry,
    presence-only per design.md:255). The gate NAME / summary key is the
    ``_shape``-suffixed ``intervention_audit_shape`` (HG-39); the artifact_type
    is the short ``intervention_audit`` (mirrors reversion_envelope /
    reversion_envelope_shape).
"""

from __future__ import annotations

import copy

import pytest

from src.eval.gates import validate_all
from src.eval.gates._hybrid_gate import HYBRID_GATE_NAME
from src.eval.gates._outcome import GATE_IDS
from src.eval.gates.intervention_audit_shape import (
    InterventionAuditShapeResult,
    REQUIRED_TOP_LEVEL,
    REQUIRED_SUBKEYS,
    validate_intervention_audit_shape,
)


def _canonical_audit() -> dict:
    """A fully-populated, schema-conformant intervention-audit envelope.

    Mirrors the §Data Models — InterventionAudit shape: the 4 correlation keys,
    a derived trigger_diagnostic, the verdict + intent enums, a falsifiable
    rationale block, and an ISO-8601 event_ts. ``applied`` is False with a null
    ``command_ref`` (Phase-1 advisory "NO ACTION TAKEN" signal).
    """
    return {
        # The 4 correlation keys NESTED under ``keys`` (CorrelationKeys: the
        # daemon-epoch keys of the single analyzed (code_version, param_version)),
        # exactly as emit_audit serializes them.
        "keys": {
            "run_id": "8f6e3c2a-0001-4a2b-9c3d-aaaaaaaaaaaa",
            "code_version": "rcfd-2026.05.30+a1b2c3",
            "param_version": "monitor-v0.1",
            "walk_forward_window": "2026Q2-wf03",
        },
        # Derived triggering diagnostic (no asserted probability — P15).
        "trigger_diagnostic": {
            "metric": "reliability",
            "observed": 0.41,
            "threshold": 0.22,
            "window_n": 128,
        },
        "verdict": "DRIFTED",
        "intervention_intent": "TIGHTEN_SAFE_MODE",
        "operator_action_required": None,
        "rationale": {
            "hypothesis": (
                "Softmax reliability has drifted outside the pinned in-sample "
                "baseline by more than the pinned margin over the rolling window."
            ),
            "falsifiers": [
                "next-window reliability CI re-includes the pinned baseline",
                "the drift does not reproduce on the next two cadence ticks",
            ],
        },
        "applied": False,
        "command_ref": None,
        "event_ts": "2026-05-30T15:42:00Z",
    }


def test_canonical_audit_passes():
    """A fully-populated canonical audit envelope validates as PASS."""
    result = validate_intervention_audit_shape(_canonical_audit())

    assert isinstance(result, InterventionAuditShapeResult)
    assert result.valid is True
    assert result.missing_top_level == []
    assert result.missing_subkeys == {}


@pytest.mark.parametrize("missing_key", list(REQUIRED_TOP_LEVEL))
def test_missing_each_required_top_level_key_fails(missing_key):
    """Dropping ANY single required top-level key fails the gate and names it."""
    env = _canonical_audit()
    del env[missing_key]

    result = validate_intervention_audit_shape(env)

    assert result.valid is False
    assert missing_key in result.missing_top_level


def test_missing_correlation_key_fails():
    """Dropping one of the 4 correlation keys (param_version) from the nested
    ``keys`` block fails the gate and names it under missing_subkeys["keys"]."""
    env = _canonical_audit()
    del env["keys"]["param_version"]

    result = validate_intervention_audit_shape(env)

    assert result.valid is False
    assert "param_version" in result.missing_subkeys["keys"]


def test_missing_falsifiers_subkey_fails():
    """rationale present but without its ``falsifiers`` sub-key fails (P15:
    a rationale must carry observable falsifiers, not just a hypothesis)."""
    env = _canonical_audit()
    env["rationale"] = {"hypothesis": "drift suspected"}  # no falsifiers

    result = validate_intervention_audit_shape(env)

    assert result.valid is False
    assert "rationale" in result.missing_subkeys
    assert "falsifiers" in result.missing_subkeys["rationale"]


def test_presence_only_accepts_any_nonempty_falsifiers_value():
    """P13: presence-only — the gate does not type-check falsifiers; a non-empty
    value (even a string rather than a list) is accepted at the gate layer.
    Type-correctness is the dataclass + richer contract test's job (P14)."""
    env = _canonical_audit()
    env["rationale"] = {"hypothesis": "h", "falsifiers": "next-tick re-includes baseline"}

    result = validate_intervention_audit_shape(env)

    assert result.valid is True


def test_empty_required_value_is_treated_as_missing():
    """An empty string for a required top-level key counts as missing
    (mirrors envelope_shape._is_present_non_empty)."""
    env = _canonical_audit()
    env["verdict"] = ""

    result = validate_intervention_audit_shape(env)

    assert result.valid is False
    assert "verdict" in result.missing_top_level


def test_non_dict_envelope_fails_gracefully():
    """A non-dict input fails without raising."""
    result = validate_intervention_audit_shape(["not", "a", "dict"])  # type: ignore[arg-type]

    assert result.valid is False
    assert result.missing_top_level  # everything is "missing" on a non-dict


def test_run_id_passthrough_does_not_affect_validation():
    """The optional ``run_id`` arg is a passthrough for the caller's context and
    does not change the presence verdict over the envelope itself."""
    env = _canonical_audit()
    with_arg = validate_intervention_audit_shape(env, run_id="some-orchestration-run")
    without_arg = validate_intervention_audit_shape(env)

    assert with_arg.valid is without_arg.valid is True


def test_required_subkeys_contract_covers_rationale_falsifiers():
    """Guard the module-level contract constant the gate is built on: the
    rationale block's required sub-key set includes ``falsifiers`` (P15)."""
    assert "rationale" in REQUIRED_SUBKEYS
    assert "falsifiers" in REQUIRED_SUBKEYS["rationale"]


def test_canonical_copy_not_mutated_by_validation():
    """Validation is read-only — it must not mutate the envelope passed in."""
    env = _canonical_audit()
    snapshot = copy.deepcopy(env)

    validate_intervention_audit_shape(env)

    assert env == snapshot


# =========================================================================== #
# Registry-dispatch observable — the task's actual acceptance criterion: a
# canonical audit validates as PASS THROUGH the gate machinery (validate_all),
# resolving the new ``intervention_audit`` artifact, with NO WS-6 hybrid runner.
# =========================================================================== #
def test_canonical_audit_passes_through_validate_all():
    """A canonical audit validates as PASS through the registry-dispatch path,
    and NO spurious WS-6 ``hybrid_gate`` runner is attached (Resolution A:
    intervention_audit is registered post-hybrid-loop, presence-only/P13)."""
    result = validate_all(_canonical_audit(), artifact_type="intervention_audit")

    assert result.valid is True
    # gate NAME / summary key is the _shape-suffixed form (mirrors reversion).
    assert result.summary["intervention_audit_shape"] == "pass"
    # The presence-only audit must NOT carry a hybrid runner (a spine-less
    # hybrid fail-safes to FAIL and would drag this valid audit invalid).
    assert HYBRID_GATE_NAME not in result.summary
    assert HYBRID_GATE_NAME not in {g.gate_name for g in result.gates}

    # The single emitted gate carries the allocated HG-39 id.
    audit_gate = next(
        g for g in result.gates if g.gate_name == "intervention_audit_shape"
    )
    assert audit_gate.gate_id == GATE_IDS["intervention_audit_shape"]
    assert audit_gate.valid is True


def test_missing_key_audit_fails_through_validate_all():
    """A missing-required-key audit fails the aggregate through validate_all —
    the gate machinery surfaces the failure, not just the direct validator."""
    env = _canonical_audit()
    del env["verdict"]

    result = validate_all(env, artifact_type="intervention_audit")

    assert result.valid is False
    assert result.summary["intervention_audit_shape"] == "fail"
    audit_gate = next(
        g for g in result.gates if g.gate_name == "intervention_audit_shape"
    )
    assert audit_gate.valid is False
    assert "verdict" in audit_gate.result_dict["missing_top_level"]


def test_intervention_audit_gate_id_is_hg39():
    """The intervention-audit shape gate is allocated HG-39 (HG-37 is LOCKED
    for STRESS_GENERIC fresh-pull cache validation; HG-38 intangibles, HG-40
    hybrid — HG-39 is the only free low slot)."""
    assert GATE_IDS["intervention_audit_shape"] == "HG-39"
