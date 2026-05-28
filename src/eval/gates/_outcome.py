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
