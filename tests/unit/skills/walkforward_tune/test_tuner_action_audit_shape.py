"""Unit tests for the tuner-action-audit HG validator (task 3.3).

Pure-unit, no LLM/MCP/DB (P14 inner ring). The validator under test is
``src.eval.gates.tuner_action_audit_shape.validate_tuner_action_audit`` — the
HG validator (registered ``artifact_type="tuner_action_audit_envelope"``) that
enforces, on the audit envelope assembled by the ``audit`` leaf (task 3.2):

  * the four correlation keys (``run_id``, ``code_version``, ``param_version``,
    ``walk_forward_window``) at the TOP LEVEL — flattened, NOT nested (the audit
    leaf serializes ``asdict(TunerActionAudit)``), with ``walk_forward_window``
    NULLABLE (null on decline / "until promoted");
  * the P15 falsifiability/derived-metrics check: ``gate_metrics`` present with
    its six DERIVED keys + ``hypothesis`` present with a falsifiable
    ``statement`` and a non-empty ``falsifiers`` list.

The HAPPY-PATH envelopes are built from the REAL ``TunerActionAudit`` frozen
dataclass via ``dataclasses.asdict`` (imported HERE in the test only — the
validator itself stays dict-only, importing no skill module) so any drift
between what audit.py assembles and what the gate validates is caught (the
unit-green/integration-broken trap, design Testing Strategy).

Requirements: 8.4 (own HG-validator surface), 6.1 (the evaluator obligation
realized as this validator's falsifiability gate).
"""

from __future__ import annotations

import copy
from dataclasses import asdict

import pytest

from src.skills.walkforward_tune.types import TunerActionAudit
from src.eval.gates.tuner_action_audit_shape import (
    CORRELATION_KEYS,
    GATE_METRIC_KEYS,
    TunerActionAuditResult,
    validate_tuner_action_audit,
)


# --------------------------------------------------------------------------- #
# Envelope builders — anchored to the REAL TunerActionAudit dataclass so the
# test catches drift between audit.py's assembly and the validator's contract.
# --------------------------------------------------------------------------- #


def _gate_metrics() -> dict:
    """The six DERIVED gate figures audit.py pins (P15)."""
    return {
        "dsr": 0.42,
        "psr": 0.61,
        "min_trl_met": True,
        "pbo": 0.18,
        "effective_n": 4,
        "lexicographic_ok": True,
    }


def _hypothesis() -> dict:
    """A falsifiable promotion hypothesis: a statement + observable falsifiers."""
    return {
        "statement": (
            "Config C2 raises the survival-net OOS Sharpe over the incumbent "
            "across the CPCV partitions without breaching the §13 lexicographic "
            "guard."
        ),
        "falsifiers": [
            "next-cycle OOS realized survival-net return falls below incumbent",
            "a survival breach (stop-out) fires under C2 the incumbent avoided",
        ],
    }


def _promote_audit() -> TunerActionAudit:
    """A PROMOTE audit — walk_forward_window is a stamped (non-null) label."""
    return TunerActionAudit(
        audit_id="00000000-0000-5000-8000-000000000001",
        run_id="11111111-1111-4111-8111-111111111111",
        code_version="code-v7",
        param_version="param-v12",
        walk_forward_window="wfw-2026-05-31",
        promoted=True,
        track="param",
        gate_metrics=_gate_metrics(),
        hypothesis=_hypothesis(),
    )


def _decline_audit() -> TunerActionAudit:
    """A DECLINE audit — walk_forward_window is NULL ("null until promoted")."""
    return TunerActionAudit(
        audit_id="00000000-0000-5000-8000-000000000002",
        run_id="22222222-2222-4222-8222-222222222222",
        code_version="code-v7",
        param_version="param-v12",
        walk_forward_window=None,
        promoted=False,
        track="param",
        gate_metrics=_gate_metrics(),
        hypothesis=_hypothesis(),
    )


def _promote_env() -> dict:
    return asdict(_promote_audit())


def _decline_env() -> dict:
    return asdict(_decline_audit())


# --------------------------------------------------------------------------- #
# Happy paths — both promote AND decline must validate (R8.1: emitted on both).
# --------------------------------------------------------------------------- #


def test_promote_envelope_is_valid():
    res = validate_tuner_action_audit(_promote_env())
    assert isinstance(res, TunerActionAuditResult)
    assert res.valid is True
    assert res.missing_top_level == []
    assert res.missing_subkeys == {}


def test_decline_envelope_with_null_walk_forward_window_is_valid():
    """The conservative decline path (P7) must validate — walk_forward_window is
    null until promoted; rejecting it would fail every decline audit."""
    res = validate_tuner_action_audit(_decline_env())
    assert res.valid is True, res.missing_top_level
    assert "walk_forward_window" not in res.missing_top_level


# --------------------------------------------------------------------------- #
# The four correlation keys — flattened at top level, NOT nested under "keys".
# --------------------------------------------------------------------------- #


def test_keys_are_flattened_at_top_level_not_nested():
    env = _promote_env()
    for key in ("run_id", "code_version", "param_version", "walk_forward_window"):
        assert key in env  # flattened, not nested under a "keys" block
    assert "keys" not in env


@pytest.mark.parametrize(
    "missing_key", ["run_id", "code_version", "param_version", "walk_forward_window"]
)
def test_rejects_envelope_missing_each_correlation_key(missing_key):
    env = _promote_env()
    del env[missing_key]
    res = validate_tuner_action_audit(env)
    assert res.valid is False
    assert missing_key in res.missing_top_level


def test_walk_forward_window_must_be_present_even_when_null():
    """Null is an accepted VALUE (nullable), but the KEY must be present."""
    env = _decline_env()
    del env["walk_forward_window"]
    res = validate_tuner_action_audit(env)
    assert res.valid is False
    assert "walk_forward_window" in res.missing_top_level


def test_non_nullable_correlation_key_empty_string_rejected():
    """run_id is required non-empty: an empty string is not a present value."""
    env = _promote_env()
    env["run_id"] = ""
    res = validate_tuner_action_audit(env)
    assert res.valid is False
    assert "run_id" in res.missing_top_level


def test_correlation_keys_constant_is_the_four_keys():
    assert set(CORRELATION_KEYS) == {
        "run_id",
        "code_version",
        "param_version",
        "walk_forward_window",
    }


# --------------------------------------------------------------------------- #
# P15 — derived gate metrics (the six pinned keys).
# --------------------------------------------------------------------------- #


def test_rejects_envelope_missing_gate_metrics_block():
    env = _promote_env()
    del env["gate_metrics"]
    res = validate_tuner_action_audit(env)
    assert res.valid is False
    assert "gate_metrics" in res.missing_top_level


@pytest.mark.parametrize(
    "metric_key",
    ["dsr", "psr", "min_trl_met", "pbo", "effective_n", "lexicographic_ok"],
)
def test_rejects_envelope_missing_each_derived_gate_metric(metric_key):
    env = _promote_env()
    del env["gate_metrics"][metric_key]
    res = validate_tuner_action_audit(env)
    assert res.valid is False
    assert "gate_metrics" in res.missing_subkeys
    assert metric_key in res.missing_subkeys["gate_metrics"]


def test_falsey_derived_metrics_count_as_present():
    """A derived metric of False / 0 / 0.0 is a real value — present, not missing
    (the P15-derived figures include booleans and counts)."""
    env = _promote_env()
    env["gate_metrics"]["min_trl_met"] = False
    env["gate_metrics"]["pbo"] = 0.0
    env["gate_metrics"]["effective_n"] = 0
    env["gate_metrics"]["lexicographic_ok"] = False
    res = validate_tuner_action_audit(env)
    assert res.valid is True, res.missing_subkeys


def test_gate_metric_keys_constant_is_the_six_derived_figures():
    assert set(GATE_METRIC_KEYS) == {
        "dsr",
        "psr",
        "min_trl_met",
        "pbo",
        "effective_n",
        "lexicographic_ok",
    }


# --------------------------------------------------------------------------- #
# P15 — falsifiable hypothesis (statement + non-empty falsifiers).
# --------------------------------------------------------------------------- #


def test_rejects_envelope_missing_hypothesis_block():
    env = _promote_env()
    del env["hypothesis"]
    res = validate_tuner_action_audit(env)
    assert res.valid is False
    assert "hypothesis" in res.missing_top_level


def test_rejects_hypothesis_missing_statement():
    env = _promote_env()
    del env["hypothesis"]["statement"]
    res = validate_tuner_action_audit(env)
    assert res.valid is False
    assert "hypothesis" in res.missing_subkeys
    assert "statement" in res.missing_subkeys["hypothesis"]


def test_rejects_hypothesis_missing_falsifiers():
    env = _promote_env()
    del env["hypothesis"]["falsifiers"]
    res = validate_tuner_action_audit(env)
    assert res.valid is False
    assert "hypothesis" in res.missing_subkeys
    assert "falsifiers" in res.missing_subkeys["hypothesis"]


def test_rejects_hypothesis_with_empty_falsifiers_list():
    """A hypothesis with NO observable falsifiers is not falsifiable (P15)."""
    env = _promote_env()
    env["hypothesis"]["falsifiers"] = []
    res = validate_tuner_action_audit(env)
    assert res.valid is False
    assert "hypothesis" in res.missing_subkeys
    assert "falsifiers" in res.missing_subkeys["hypothesis"]


# --------------------------------------------------------------------------- #
# Non-dict / degenerate inputs.
# --------------------------------------------------------------------------- #


def test_non_dict_envelope_is_invalid():
    res = validate_tuner_action_audit(["not", "a", "dict"])
    assert res.valid is False
    assert res.missing_top_level  # all required keys reported missing


def test_empty_dict_is_invalid():
    res = validate_tuner_action_audit({})
    assert res.valid is False
    assert "run_id" in res.missing_top_level
    assert "gate_metrics" in res.missing_top_level
    assert "hypothesis" in res.missing_top_level


def test_validator_does_not_mutate_input():
    env = _promote_env()
    before = copy.deepcopy(env)
    validate_tuner_action_audit(env)
    assert env == before


# --------------------------------------------------------------------------- #
# Registry wiring — registered + discoverable by artifact_type (data-only edit).
# --------------------------------------------------------------------------- #


def test_registered_in_registry_under_exact_artifact_type():
    from src.eval.gates._registry import REGISTRY

    assert "tuner_action_audit_envelope" in REGISTRY
    assert len(REGISTRY["tuner_action_audit_envelope"]) >= 1


def test_validate_all_dispatches_to_the_gate():
    """The artifact_type is discoverable through the public validate_all entry
    and a valid envelope passes the dispatched gate."""
    from src.eval.gates import validate_all, VALID_ARTIFACT_TYPES

    assert "tuner_action_audit_envelope" in VALID_ARTIFACT_TYPES
    agg = validate_all(_promote_env(), artifact_type="tuner_action_audit_envelope")
    assert agg.valid is True
    assert agg.summary.get("tuner_action_audit_shape") == "pass"


def test_validate_all_fails_an_unfalsifiable_envelope():
    env = _promote_env()
    env["hypothesis"]["falsifiers"] = []
    from src.eval.gates import validate_all

    agg = validate_all(env, artifact_type="tuner_action_audit_envelope")
    assert agg.valid is False
    assert agg.summary.get("tuner_action_audit_shape") == "fail"
