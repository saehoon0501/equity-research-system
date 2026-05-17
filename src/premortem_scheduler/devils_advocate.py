"""LLM devil's-advocate assistant — generates 3 plausible failure modes.

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.5 Q4 line 528::

    LLM role: devil's-advocate assistant (Opus for high-stakes
    contestable judgment); generates 3 plausible failure modes the
    operator may have missed; operator accepts/rejects each with
    rationale logged.

Model: Claude Opus (per spec — high-stakes contestable judgment is
explicitly Opus territory in Phase 4 ``the spec requires Opus for
contestable judgment``). Output is forced JSON; transport / parse
failures fall back to an empty list and the operator drives the
session unaided (the recorder still writes the row, with
``llm_assist_metadata.error`` set).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from . import (
    DEVILS_ADVOCATE_FAILURE_MODE_COUNT,
    DEVILS_ADVOCATE_LLM_MODEL,
)

_LOG = logging.getLogger(__name__)


@dataclass
class DevilsAdvocateOutput:
    """Structured output from the devil's-advocate assistant."""

    model: str
    failure_modes: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_metadata(
        self,
        *,
        accepted_count: int = 0,
        rejected_count: int = 0,
    ) -> dict[str, Any]:
        """Return the ``llm_assist_metadata`` JSONB shape per migration 012."""
        return {
            "model": self.model,
            "role": "devil's_advocate",
            "operator_accepted_count": int(accepted_count),
            "operator_rejected_count": int(rejected_count),
            "n_proposed": len(self.failure_modes),
            "error": self.error,
        }


_DEVILS_ADVOCATE_PROMPT = """You are a devil's advocate for an equity-research \
pre-mortem session. The operator owns a thesis on {ticker} (mode {mode}). \
Your job is to surface failure modes the operator may have anchored away from.

Operator's thesis pillars:
{pillars}

Recent context:
{context}

Generate EXACTLY {n} plausible failure modes that the operator likely has NOT \
fully considered. Bias toward mechanism-level critiques (what would have to \
become true in the world for the thesis to fail), not surface restatements. \
Avoid generic "macro recession" boilerplate unless mechanism-specific.

Output ONLY valid JSON, no prose, no markdown fences. Schema:
{{
  "failure_modes": [
    {{
      "mode": "<short label, e.g., 'demand_reversal_h2_2026'>",
      "mechanism": "<2-3 sentence mechanism>",
      "leading_indicator": "<measurable signal that would precede failure>",
      "probability_estimate": <number in [0,1]>,
      "kill_criterion_proposal": "<concrete trigger condition operator could \
adopt as a kill criterion, or null>"
    }}
  ]
}}
"""


def generate_failure_modes(
    *,
    ticker: str,
    mode: str,
    thesis_pillars: Any,
    context: Optional[dict[str, Any]] = None,
    n: int = DEVILS_ADVOCATE_FAILURE_MODE_COUNT,
    client: Any | None = None,
) -> DevilsAdvocateOutput:
    """Call Claude Opus for the devil's-advocate failure-mode candidates.

    Args:
        ticker: equity ticker.
        mode: B / B_prime / C.
        thesis_pillars: current operating thesis pillars.
        context: optional context dict (recent events, regime, drift
            channels, etc.) — wired into the prompt verbatim.
        n: how many failure modes to request (default 3 per spec).
        client: optional Anthropic SDK client (for tests).

    Returns:
        DevilsAdvocateOutput. ``failure_modes`` empty + ``error`` set on
        transport / parse failure (the session continues operator-led).
    """
    context_str = (
        json.dumps(context, ensure_ascii=False, default=str)
        if context else "{}"
    )
    pillars_str = json.dumps(thesis_pillars, ensure_ascii=False, default=str)
    prompt = _DEVILS_ADVOCATE_PROMPT.format(
        ticker=ticker,
        mode=mode,
        pillars=pillars_str,
        context=context_str,
        n=int(n),
    )

    if client is None:
        try:
            import anthropic  # deferred
        except ImportError:
            _LOG.warning("anthropic SDK not installed; skipping devil's-advocate")
            return DevilsAdvocateOutput(
                model=DEVILS_ADVOCATE_LLM_MODEL, error="sdk_missing"
            )
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            _LOG.warning("ANTHROPIC_API_KEY not set; skipping devil's-advocate")
            return DevilsAdvocateOutput(
                model=DEVILS_ADVOCATE_LLM_MODEL, error="no_api_key"
            )
        client = anthropic.Anthropic(api_key=api_key)

    try:
        resp = client.messages.create(
            model=DEVILS_ADVOCATE_LLM_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            getattr(b, "text", "") for b in getattr(resp, "content", [])
        ).strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
        modes = parsed.get("failure_modes", [])
        if not isinstance(modes, list):
            return DevilsAdvocateOutput(
                model=DEVILS_ADVOCATE_LLM_MODEL,
                error="bad_schema",
            )
        return DevilsAdvocateOutput(
            model=DEVILS_ADVOCATE_LLM_MODEL,
            failure_modes=modes[:n],
        )
    except Exception as exc:
        _LOG.exception("devil's-advocate LLM call failed: %s", exc)
        return DevilsAdvocateOutput(
            model=DEVILS_ADVOCATE_LLM_MODEL,
            error=f"llm_error: {type(exc).__name__}",
        )


__all__ = ["DevilsAdvocateOutput", "generate_failure_modes"]
