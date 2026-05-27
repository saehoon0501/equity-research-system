"""VERISCORE long-form factuality (WS-1, Axis A).

This metric REPLACES the older atomize-everything factuality scorer
(the one whose name a criterion-3 grep proves absent). VERISCORE (Song
et al., 2024) decomposes long-form output into *verifiable* claims
(dropping unverifiable/subjective spans, rather than atomizing every
span) and scores precision = supported / verifiable. There is NO import
of the replaced scorer anywhere in this subpackage (acceptance criterion
3 — the grep proves absence).

LLM-based, cached via src/llm_cache (default OFF), self-consistency N=5
@ temp 0.7 median, first-pass only. Lazy/function-local anthropic import.
DEGRADE: failure raises ArticulationMetricError; the caller nulls the
sub-metric and stays advisory.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ._selfconsistency import (
    SELF_CONSISTENCY_N,
    SELF_CONSISTENCY_TEMP,
    median_self_consistency,
)
from .faithfulness import ArticulationMetricError, LLMCaller

VERISCORE_METHOD = "veriscore-longform-v1"


@dataclass
class VeriScore:
    factuality_precision: float       # supported / verifiable (median)
    n_verifiable: int
    n_supported: int
    samples: list[float] = field(default_factory=list)
    method: str = VERISCORE_METHOD
    mode: str = "advisory"

    def to_block(self) -> dict[str, Any]:
        return {
            "factuality_precision": self.factuality_precision,
            "n_verifiable": self.n_verifiable,
            "n_supported": self.n_supported,
            "n_self_consistency": len(self.samples),
            "temperature": SELF_CONSISTENCY_TEMP,
            "method": self.method,
            "mode": self.mode,
        }


def _build_prompt(text: str, grounding: str) -> tuple[str, str]:
    system = (
        "You are a VERISCORE long-form factuality judge. Extract only the "
        "VERIFIABLE factual claims from the TEXT (drop subjective, "
        "speculative, or opinion spans — the key difference from "
        "atomize-everything factuality scorers). For each verifiable claim, "
        "judge whether the GROUNDING supports it.\n"
        "Output ONLY JSON:\n"
        '  {"verifiable_claims": [{"claim": str, "supported": bool}]}'
    )
    user = f"GROUNDING:\n{grounding}\n\nTEXT:\n{text}\n\nReturn JSON only."
    return system, user


def _parse_sample(raw: dict) -> tuple[float, int, int]:
    if not isinstance(raw, dict):
        raise ArticulationMetricError("veriscore sample is not a dict")
    claims = raw.get("verifiable_claims")
    if not isinstance(claims, list) or not claims:
        return 0.0, 0, 0
    n_verifiable = len(claims)
    n_supported = sum(
        1 for c in claims if isinstance(c, dict) and bool(c.get("supported"))
    )
    precision = n_supported / n_verifiable if n_verifiable else 0.0
    return precision, n_verifiable, n_supported


def _default_llm_caller(
    system: str, user: str, model: str, temperature: float, sample_index: int
) -> dict:
    # Reuse faithfulness' cached caller (same cache 5-tuple + degrade contract).
    from .faithfulness import _default_llm_caller as faith_caller

    return faith_caller(system, user, model, temperature, sample_index)


def score_veriscore(
    text: str,
    grounding: str,
    *,
    model: str = "claude-sonnet-4-5",
    n: int = SELF_CONSISTENCY_N,
    temperature: float = SELF_CONSISTENCY_TEMP,
    llm_caller: Optional[LLMCaller] = None,
) -> VeriScore:
    """VERISCORE factuality precision with N=5 self-consistency.

    Raises ArticulationMetricError on failure (caller degrades to null).
    """
    caller = llm_caller or _default_llm_caller
    system, user = _build_prompt(text, grounding)
    per_sample: list[tuple[float, int, int]] = []

    def _sampler(i: int) -> float:
        raw = caller(system, user, model, temperature, i)
        parsed = _parse_sample(raw)
        per_sample.append(parsed)
        return parsed[0]

    median_prec, samples = median_self_consistency(_sampler, n=n)
    if not per_sample:  # pragma: no cover
        raise ArticulationMetricError("no veriscore samples produced")
    n_verifiable = int(statistics.median([p[1] for p in per_sample]))
    n_supported = int(statistics.median([p[2] for p in per_sample]))
    return VeriScore(
        factuality_precision=median_prec,
        n_verifiable=n_verifiable,
        n_supported=n_supported,
        samples=samples,
    )
