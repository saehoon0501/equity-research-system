"""Phase C — LLM-as-judge for the Phase C trigger.

Per v3 spec Section 4.8 lines 664-669 + Section 2.3 row "C Conditional
negotiation" (line 168):

    LLM-as-judge detects claim-conflict (Type 1/2/3); bounded to 3 rounds.

    Type 1 (direct contradiction): A asserts X is true; B asserts X is false.
    Type 2 (material magnitude disagreement): A requires variable in
        range R1; B asserts variable in R2 disjoint from R1.
    Type 3 (mutually exclusive prerequisite): A requires regime X;
        B asserts regime opposite of X.

The judge is the gatekeeper for whether Phase C runs at all. If
``phase_c_needed=False`` the orchestrator skips negotiation and proceeds
directly to Phase D — most cases will fall here (the 5 styles can
disagree on verdict without their CLAIMS conflicting; e.g., Value says
PASS because price is high, Growth says ADD because TAM is huge — these
are not direct claim contradictions, just different priorities).

Model: Opus (high-stakes adjudication; matches mode_classifier's
high-stakes routing convention from Section 6 Q1).

Output schema::

    {
      "phase_c_needed": bool,
      "judge_confidence": float ∈ [0,1],
      "conflicts": [
        {
          "conflict_id": str,
          "type": "type_1_..." | "type_2_..." | "type_3_...",
          "style_a": str, "style_a_claim_id": str,
          "style_b": str, "style_b_claim_id": str,
          "rationale": str
        }, ...
      ]
    }

The judge prompt is a `parameters` table entry (versioned, recalibratable)
per Section 4.8 line 669; the version constant lives in
``__init__.py`` (PROMPT_VERSION_PHASE_C_JUDGE).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from . import (
    CONFLICT_TYPE_1,
    CONFLICT_TYPE_2,
    CONFLICT_TYPE_3,
    MODEL_OPUS,
    PROMPT_VERSION_PHASE_C_JUDGE,
)
from ._llm import build_default_client, call_messages, extract_json
from .phase_b_locked import PhaseBLockedSet

_LOG = logging.getLogger(__name__)


@dataclass
class JudgedConflict:
    """One judge-detected conflict between a pair of style claims."""

    conflict_id: str
    conflict_type: str  # one of CONFLICT_TYPE_{1,2,3}
    style_a: str
    style_a_claim_id: str
    style_b: str
    style_b_claim_id: str
    rationale: str

    def to_payload(self) -> dict:
        return {
            "conflict_id": self.conflict_id,
            "type": self.conflict_type,
            "style_a": self.style_a,
            "style_a_claim_id": self.style_a_claim_id,
            "style_b": self.style_b,
            "style_b_claim_id": self.style_b_claim_id,
            "rationale": self.rationale,
        }


@dataclass
class PhaseCJudgeResult:
    """Output of the Phase C trigger judge."""

    phase_c_needed: bool
    judge_confidence: float
    conflicts: list[JudgedConflict] = field(default_factory=list)
    raw_text: str = ""
    valid: bool = True
    invalid_reason: Optional[str] = None
    prompt_version: str = PROMPT_VERSION_PHASE_C_JUDGE
    model: str = MODEL_OPUS

    def to_payload(self) -> dict:
        return {
            "phase_c_needed": self.phase_c_needed,
            "judge_confidence": self.judge_confidence,
            "conflicts": [c.to_payload() for c in self.conflicts],
            "valid": self.valid,
            "invalid_reason": self.invalid_reason,
            "prompt_version": self.prompt_version,
            "model": self.model,
        }


# --------------------------------------------------------------------------- #
# Judge prompts                                                               #
# --------------------------------------------------------------------------- #


_SYSTEM_PROMPT = """\
You are the PHASE C TRIGGER JUDGE for a 5-style equity-research debate.

Your single task: read the Phase B locked claims from all 5 styles
(Value, Growth, Quality/Moat, Macro/Regime, Quant/Technical) and decide
whether their CLAIMS conflict in a way that warrants negotiation.

You are NOT deciding the verdict. You are NOT weighting the styles.
You are DETECTING claim-level conflicts under a strict 3-Type rubric:

  TYPE 1 — DIRECT CONTRADICTION:
    Style A asserts X is true; Style B asserts X is false.
    Example: A: "ROIC > 15% is sustainable"; B: "ROIC compression in
    last 8 quarters is structural" — these directly contradict.

  TYPE 2 — MATERIAL MAGNITUDE DISAGREEMENT:
    Style A requires variable V in range R1; Style B asserts V in
    range R2 with R1 ∩ R2 = ∅.
    Example: A: "Growth must be ≥25% for 3y"; B: "Growth will compress
    to 8-12% over 3y" — disjoint ranges on the same variable.

  TYPE 3 — MUTUALLY EXCLUSIVE PREREQUISITE:
    Style A requires regime X; Style B asserts the opposite regime.
    Example: A: "Thesis requires Fed accommodation through 2026";
    B: "Hawkish Fed regime is the load-bearing assumption" — mutually
    exclusive.

EXCLUSIONS — these are NOT conflicts:
  - Different priorities at the same fact (Value cares about price,
    Growth cares about TAM — both can be right simultaneously).
  - Different verdicts without conflicting claims (Value PASS because
    price is high, Growth ADD because TAM is huge — no claim conflict).
  - Style preference disagreements that don't reduce to falsifiable
    propositions.

OUTPUT DISCIPLINE:
  - Return JSON only. No markdown, no commentary.
  - phase_c_needed = TRUE iff there is at least one Type 1/2/3 conflict.
  - judge_confidence ∈ [0, 1] — your calibrated confidence in the
    binary trigger decision.
  - conflicts list — empty when phase_c_needed is FALSE.
  - Each conflict references SPECIFIC claim ids from Phase B; do not
    invent claims.
"""


_USER_TEMPLATE = """\
TICKER: {ticker}

PHASE B LOCKED CLAIMS (5 styles):

{phase_b_block}

TASK: Apply the 3-Type rubric to these locked claims. Output ONLY this
JSON object:

{{
  "phase_c_needed": true | false,
  "judge_confidence": 0.0-1.0,
  "conflicts": [
    {{
      "conflict_id": "<short id>",
      "type": "type_1_direct_contradiction" |
              "type_2_magnitude_disagreement" |
              "type_3_mutually_exclusive_prerequisite",
      "style_a": "<style_id>",
      "style_a_claim_id": "<id from Phase B>",
      "style_b": "<style_id>",
      "style_b_claim_id": "<id from Phase B>",
      "rationale": "<= 2 sentences explaining the conflict"
    }},
    ...
  ]
}}
"""


def _format_phase_b(locked: PhaseBLockedSet) -> str:
    """Render the locked set into a stable, judge-readable block."""
    parts: list[str] = []
    for sid, lk in locked.locks.items():
        parts.append(f"--- STYLE: {sid} ({lk.verdict}) ---")
        parts.append("LOAD_BEARING_CLAIMS:")
        for c in lk.load_bearing_claims:
            parts.append(
                f"  [{c.claim_id}] (-> {c.supports_recommendation}) {c.text}"
            )
        parts.append("NON_NEGOTIABLES:")
        for n in lk.non_negotiables:
            parts.append(f"  [{n.constraint_id}] {n.text}")
        parts.append("")
    return "\n".join(parts)


_VALID_CONFLICT_TYPES = {
    CONFLICT_TYPE_1,
    CONFLICT_TYPE_2,
    CONFLICT_TYPE_3,
}


def _parse_judge_payload(parsed: dict) -> PhaseCJudgeResult:
    """Validate + coerce the judge's JSON payload."""
    if not isinstance(parsed, dict):
        return PhaseCJudgeResult(
            phase_c_needed=False,
            judge_confidence=0.0,
            valid=False,
            invalid_reason="payload not an object",
        )
    needed = parsed.get("phase_c_needed", False)
    if not isinstance(needed, bool):
        return PhaseCJudgeResult(
            phase_c_needed=False,
            judge_confidence=0.0,
            valid=False,
            invalid_reason=f"phase_c_needed not boolean: {needed!r}",
        )
    try:
        conf = float(parsed.get("judge_confidence", 0.0))
    except (TypeError, ValueError):
        return PhaseCJudgeResult(
            phase_c_needed=needed,
            judge_confidence=0.0,
            valid=False,
            invalid_reason="judge_confidence not numeric",
        )
    if not 0.0 <= conf <= 1.0:
        return PhaseCJudgeResult(
            phase_c_needed=needed,
            judge_confidence=0.0,
            valid=False,
            invalid_reason=f"judge_confidence out of range: {conf}",
        )
    raw_conflicts = parsed.get("conflicts", [])
    if not isinstance(raw_conflicts, list):
        return PhaseCJudgeResult(
            phase_c_needed=needed,
            judge_confidence=conf,
            valid=False,
            invalid_reason="conflicts not a list",
        )
    conflicts: list[JudgedConflict] = []
    for i, raw in enumerate(raw_conflicts):
        if not isinstance(raw, dict):
            continue
        ctype = str(raw.get("type", ""))
        if ctype not in _VALID_CONFLICT_TYPES:
            continue
        sa = str(raw.get("style_a", "")).strip()
        sb = str(raw.get("style_b", "")).strip()
        ca = str(raw.get("style_a_claim_id", "")).strip()
        cb = str(raw.get("style_b_claim_id", "")).strip()
        if not (sa and sb and ca and cb) or sa == sb:
            continue
        conflicts.append(
            JudgedConflict(
                conflict_id=str(raw.get("conflict_id") or f"c_{i+1}"),
                conflict_type=ctype,
                style_a=sa,
                style_a_claim_id=ca,
                style_b=sb,
                style_b_claim_id=cb,
                rationale=str(raw.get("rationale", "")),
            )
        )
    return PhaseCJudgeResult(
        phase_c_needed=needed and len(conflicts) > 0,
        judge_confidence=conf,
        conflicts=conflicts,
        valid=True,
    )


def run_phase_c_judge(
    *,
    locked: PhaseBLockedSet,
    client: Any = None,
    model: str = MODEL_OPUS,
    temperature: float = 0.0,
) -> PhaseCJudgeResult:
    """Adjudicate whether Phase C negotiation is needed.

    Args:
        locked: The Phase B locked set; this is the only input.
        client: Optional pre-built Anthropic client.
        model: Default Opus (high-stakes adjudication, Section 6 Q1).
        temperature: 0.0 — we want maximum determinism on a binary
            trigger decision.

    Returns:
        :class:`PhaseCJudgeResult` with ``phase_c_needed`` true/false +
        the conflict list. The orchestrator uses ``phase_c_needed`` to
        decide whether to invoke ``run_phase_c_negotiation``.
    """
    if client is None:
        client = build_default_client()

    user_prompt = _USER_TEMPLATE.format(
        ticker=locked.ticker,
        phase_b_block=_format_phase_b(locked),
    )
    raw = call_messages(
        client,
        model,
        _SYSTEM_PROMPT,
        user_prompt,
        max_tokens=2048,
        temperature=temperature,
    )
    parsed = extract_json(raw)
    if parsed is None:
        return PhaseCJudgeResult(
            phase_c_needed=False,
            judge_confidence=0.0,
            raw_text=raw,
            valid=False,
            invalid_reason="json parse failure",
        )
    result = _parse_judge_payload(parsed)
    result.raw_text = raw
    return result


__all__ = [
    "JudgedConflict",
    "PhaseCJudgeResult",
    "run_phase_c_judge",
]
