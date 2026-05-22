"""Per-agent envelope contracts — single source of truth.

Each ``envelopes/<agent>.py`` declares SCHEMA + REASONING_STEPS +
PREDICATES + ``validate(data: dict) -> EnvelopeValidationResult`` for one
subagent's emit envelope. The same module is consumed:

  - by ``dispatch_template.render_dispatch_prompt`` to render the
    #OUTPUT_SCHEMA + #REASONING_PATH sections of the dispatch prompt
    (the LLM sees the schema verbatim — no prose to mis-translate);
  - by the PostToolUse hook to validate the emitted envelope post-hoc
    via the ``HG-ENV`` synthetic gate (envelopes/_adapter.py).

Per harness-v4-final v4 (5-iteration /review-me convergence, 2026-05-22).
The pydantic v2 model in the original plan is implemented as a stdlib
@dataclass + JSON-Schema-dict pair to match the repo's existing typed
contract pattern (src/p8_tactical_overlay/contracts.py).

"block wins" invariant: numerics that appear in BOTH the PARAMETERS_USED
header block AND the agent's prose body — block wins. dispatch_template
preserves the PARAMETERS_USED prefix verbatim (§1.5 contract); only the
instructional body below it is replaced with the 5-section template.
"""
from src.agent_harness.envelopes._base import (
    EnvelopeFieldError,
    EnvelopeValidationResult,
    Predicate,
    validate_envelope,
)
from src.agent_harness.envelopes._adapter import (
    GATE_ID as ENVELOPE_GATE_ID,
    GATE_NAME as ENVELOPE_GATE_NAME,
    to_gate_outcome,
)

__all__ = [
    "ENVELOPE_GATE_ID",
    "ENVELOPE_GATE_NAME",
    "EnvelopeFieldError",
    "EnvelopeValidationResult",
    "Predicate",
    "to_gate_outcome",
    "validate_envelope",
]
