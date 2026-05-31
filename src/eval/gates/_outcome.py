"""Shared gate-outcome primitives (P0-4 extraction).

Holds the stable gate-id table, the :class:`GateOutcome` dataclass, and the
``make_outcome`` / ``to_dict_safe`` helpers. Lives in its own module so both
:mod:`src.eval.gates` (the public ``validate_all`` entrypoint) and
:mod:`src.eval.gates._registry` (the gate runners) can import them
without a circular dependency.

These are byte-for-byte the same definitions that previously lived inline in
``__init__.py``; only their location changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Stable rule IDs used in audit rows + delta-prompts. The convention
# matches the existing HG-NN identifiers from the evaluator rubric.
GATE_IDS: dict[str, str] = {
    "envelope_shape":        "HG-23",
    "sentiment_degradation": "HG-24",
    "sizing_math":           "HG-25",
    "evidence_uuid_check":   "HG-26",
    "outside_view_blend":    "HG-27",
    "counterfactual_catalog": "HG-28",
    "quant_memo_shape":      "HG-29",
    "strategic_memo_shape":  "HG-30",
    "catalyst_memo_shape":   "HG-31",
    "cdd_memo_shape":        "HG-32",
    "tactical_envelope_shape": "HG-33",
    "catalyst_modifier_composition_check": "HG-34",
    "crowding_composition_check": "HG-35",
    "intangibles_adjustment_shape": "HG-38",
    "reversion_envelope_shape": "HG-36",
    # in-session-monitor intervention-audit shape gate. HG-37 is NOT free —
    # it is LOCKED for STRESS_GENERIC fresh-pull cache validation (see the
    # authoritative enumeration in .claude/agents/eval/evaluator.md:818,
    # 2026-05-20). HG-38 is intangibles, HG-40 is the WS-6 hybrid gate; a
    # repo-wide HG-NN scan shows HG-39 is the only free low slot. Gate NAME /
    # GATE_IDS key is the _shape-suffixed form (mirrors reversion/tactical);
    # the REGISTRY artifact_type stays the short "intervention_audit".
    "intervention_audit_shape": "HG-39",
    # walkforward-tuning-loop tuner-action-audit shape gate. HG-40 is the WS-6
    # hybrid gate (the highest assigned); HG-41 is the next free monotonic slot
    # (HG-1..HG-40 all assigned per the repo-wide HG-NN scan; HG-17 is a legacy
    # gap left undisturbed). Gate NAME / GATE_IDS key is the _shape-suffixed form
    # (mirrors reversion/tactical/intervention); the REGISTRY artifact_type is
    # the spec-pinned "tuner_action_audit_envelope".
    "tuner_action_audit_shape": "HG-41",
}


@dataclass
class GateOutcome:
    """One gate's outcome inside an aggregate result."""

    gate_id: str
    gate_name: str
    valid: bool
    result_dict: dict[str, Any]
    # ``error_fingerprint`` is the (gate_id, sorted-key-tuple-of-failures)
    # used by the agent_harness retry loop for stuck-loop detection.
    error_fingerprint: str | None = None


def make_outcome(
    gate_name: str,
    valid: bool,
    result_dict: dict[str, Any],
    fingerprint: str,
) -> GateOutcome:
    # When the gate failed but the helper didn't populate any specific
    # fingerprint parts (e.g. missing-block + short-circuit return), use
    # a sentinel so stuck-loop detection still works. "ok" must never
    # appear on a failed outcome.
    fp = fingerprint
    if not valid and fp == "ok":
        fp = "generic_fail"
    return GateOutcome(
        gate_id=GATE_IDS[gate_name],
        gate_name=gate_name,
        valid=valid,
        result_dict=result_dict,
        error_fingerprint=fp if not valid else "ok",
    )


def to_dict_safe(obj: Any) -> dict[str, Any]:
    """Convert a dataclass-result to dict for serialization."""
    if hasattr(obj, "__dict__"):
        out: dict[str, Any] = {}
        for k, v in obj.__dict__.items():
            if isinstance(v, (str, int, float, bool, type(None))):
                out[k] = v
            elif isinstance(v, (list, tuple)):
                out[k] = list(v)
            elif isinstance(v, dict):
                out[k] = v
            else:
                out[k] = str(v)
        return out
    return {"result": str(obj)}


__all__ = ["GATE_IDS", "GateOutcome", "make_outcome", "to_dict_safe"]
