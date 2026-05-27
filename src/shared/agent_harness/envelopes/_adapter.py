"""Adapter: EnvelopeValidationResult → existing GateOutcome shape.

Step 3 of v4-final: pydantic-style envelope validation is ADDITIVE to
the existing HG-gate pipeline. We project envelope validation as one
synthetic gate (gate_id "HG-ENV", gate_name "envelope_validation") so:

1. The aggregate result builder picks it up unchanged.
2. dispatcher._compute_error_fingerprint at dispatcher.py:189-200
   composes it into the stuck-loop signature without any code change
   there (it already iterates over all gates and concats fingerprints).
3. delta_prompt.build_delta_prompt picks it up via the renderer
   registered in delta_prompt.py.
"""
from __future__ import annotations

from src.shared.agent_harness.envelopes._base import EnvelopeValidationResult
from src.eval.gates import GateOutcome


GATE_ID = "HG-ENV"
GATE_NAME = "envelope_validation"


def to_gate_outcome(result: EnvelopeValidationResult) -> GateOutcome:
    """Wrap an envelope validation result as a GateOutcome.

    The result_dict is intentionally compatible with the renderer
    registered in delta_prompt._render_envelope_validation: it carries
    field_errors as a list of dicts each holding {path, expected,
    observed, schema_fragment}.
    """
    return GateOutcome(
        gate_id=GATE_ID,
        gate_name=GATE_NAME,
        valid=result.valid,
        result_dict=result.to_result_dict(),
        error_fingerprint=result.error_fingerprint(),
    )


__all__ = ["GATE_ID", "GATE_NAME", "to_gate_outcome"]
