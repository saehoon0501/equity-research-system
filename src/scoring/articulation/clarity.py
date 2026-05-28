"""G-Eval clarity (WS-1, Axis A) — ADVISORY ONLY.

G-Eval (LLM-as-judge with chain-of-thought form-filling) rates the
clarity / readability of the articulated output on a [0,1] scale. Per
spec this metric is ADVISORY ONLY — it is informational and never a gate
input even within axis_a. The sub-block always carries ``mode:
"advisory"`` and ``advisory_only: true``.

LLM-based, cached via src/llm_cache, N=5 @ temp 0.7 median (LOCKED).
Lazy anthropic import. DEGRADE: failure raises ArticulationMetricError;
caller nulls the sub-metric (and, being advisory-only, this never affects
any downstream gate regardless).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ._selfconsistency import (
    SELF_CONSISTENCY_N,
    SELF_CONSISTENCY_TEMPERATURE,
    median_self_consistency,
)
from .faithfulness import ArticulationMetricError, LLMCaller, _coerce_unit

CLARITY_METHOD = "g-eval-clarity-v1"


@dataclass
class ClarityScore:
    clarity: float
    samples: list[float] = field(default_factory=list)
    method: str = CLARITY_METHOD
    mode: str = "advisory"
    advisory_only: bool = True

    def to_block(self) -> dict[str, Any]:
        return {
            "clarity": self.clarity,
            "n_self_consistency": len(self.samples),
            "temperature": SELF_CONSISTENCY_TEMPERATURE,
            "method": self.method,
            "mode": self.mode,
            "advisory_only": self.advisory_only,
        }


def _build_prompt(text: str) -> tuple[str, str]:
    system = (
        "You are a G-Eval clarity judge. Rate the clarity and readability "
        "of the TEXT for a professional equity-research audience. Think "
        "step by step, then output ONLY JSON:\n"
        '  {"clarity": number in [0,1]}'
    )
    user = f"TEXT:\n{text}\n\nReturn JSON only."
    return system, user


def _default_llm_caller(
    system: str, user: str, model: str, temperature: float, sample_index: int
) -> dict:
    from .faithfulness import _default_llm_caller as faith_caller

    return faith_caller(system, user, model, temperature, sample_index)


def score_clarity(
    text: str,
    *,
    model: str = "claude-sonnet-4-5",
    n: int = SELF_CONSISTENCY_N,
    temperature: float = SELF_CONSISTENCY_TEMPERATURE,
    llm_caller: Optional[LLMCaller] = None,
) -> ClarityScore:
    """G-Eval clarity (advisory only) with N=5 self-consistency."""
    caller = llm_caller or _default_llm_caller
    system, user = _build_prompt(text)

    def _sampler(i: int) -> float:
        raw = caller(system, user, model, temperature, i)
        if not isinstance(raw, dict):
            raise ArticulationMetricError("clarity sample is not a dict")
        return _coerce_unit(raw.get("clarity"))

    median_clarity, samples = median_self_consistency(_sampler, n=n)
    return ClarityScore(clarity=median_clarity, samples=samples)
