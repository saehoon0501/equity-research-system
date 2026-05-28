"""RAGAS faithfulness + answer-relevancy (WS-1, Axis A) — LLM, cached, N=5.

RAGAS-style decomposition:

  faithfulness   = fraction of the answer's atomic claims that are
                   ENTAILED by the retrieved grounding context. The
                   complementary set (claims NOT entailed) is the
                   "unsupported-claim" set. We surface
                   ``unsupported_detection_rate`` = (# of the N self-
                   consistency samples that flagged >=1 unsupported claim)
                   / N. This is a sample-agreement detection rate, NOT a
                   ground-truth recall (no labelled "truly unsupported"
                   set exists on the LLM path). Acceptance criterion 1
                   requires this rate > 0 on a seeded unsupported-claim
                   fixture (i.e. the unsupported claim is detected).

  answer_relevancy = how on-topic the answer is to the question/thesis
                   (RAGAS answer-relevancy). LLM-scored in [0, 1].

Both are LLM-based, routed through ``src/llm_cache`` (default OFF) with
self-consistency N=5 @ temp 0.7 median (LOCKED), first-pass only.

DEGRADE: any failure (no SDK, no API key, parse error, cache replay miss)
raises ``ArticulationMetricError``; the orchestrating scorer catches it,
writes ``axis_a.faithfulness = None`` and keeps ``mode=advisory``. This
module never returns a fabricated PASS and never silently skips to FAIL.

The ``anthropic`` import is FUNCTION-LOCAL (mirrors stage2_llm_rubric's
``_get_anthropic_client``) so this module imports cleanly with the SDK
absent — important so the deterministic citation test never drags a
network dependency into collection.
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

FAITHFULNESS_METHOD = "ragas-faithfulness-relevancy-v1"


class ArticulationMetricError(RuntimeError):
    """Raised by any LLM sub-metric on failure → caller degrades to null."""


# An LLM caller has the same shape as stage2's ``llm_caller`` test seam:
# ``(system, user, model, temperature, sample_index) -> dict``.
LLMCaller = Callable[[str, str, str, float, int], dict]


@dataclass
class FaithfulnessScore:
    faithfulness: float                 # median of per-sample faithfulness
    answer_relevancy: float             # median of per-sample relevancy
    n_claims: int                       # atomic claims considered
    n_unsupported_flagged: int          # claims flagged NOT entailed
    unsupported_detection_rate: float   # share of N samples flagging >=1 unsupported
    samples_faithfulness: list[float] = field(default_factory=list)
    samples_relevancy: list[float] = field(default_factory=list)
    method: str = FAITHFULNESS_METHOD
    mode: str = "advisory"

    def to_block(self) -> dict[str, Any]:
        return {
            "faithfulness": self.faithfulness,
            "answer_relevancy": self.answer_relevancy,
            "n_claims": self.n_claims,
            "n_unsupported_flagged": self.n_unsupported_flagged,
            "unsupported_detection_rate": self.unsupported_detection_rate,
            "n_self_consistency": len(self.samples_faithfulness),
            "temperature": SELF_CONSISTENCY_TEMPERATURE,
            "method": self.method,
            "mode": self.mode,
        }


def _build_prompt(answer: str, grounding: str) -> tuple[str, str]:
    """RAGAS faithfulness+relevancy prompt. Grounding = evidence_documents text."""
    system = (
        "You are a RAGAS-style grounding judge. Given an ANSWER and the "
        "retrieved GROUNDING context, decompose the answer into atomic "
        "claims and judge each as entailed by the grounding or not.\n"
        "Output ONLY a JSON object:\n"
        '  {"claims": [{"claim": str, "supported": bool}], '
        '"answer_relevancy": number in [0,1]}\n'
        "A claim is 'supported': true ONLY if the grounding entails it. "
        "Claims with no grounding support MUST be supported: false."
    )
    user = (
        f"GROUNDING CONTEXT:\n{grounding}\n\n"
        f"ANSWER:\n{answer}\n\n"
        "Return JSON only."
    )
    return system, user


def _parse_sample(raw: dict) -> tuple[float, int, int, float]:
    """One sample -> (faithfulness, n_claims, n_unsupported, relevancy)."""
    if not isinstance(raw, dict):
        raise ArticulationMetricError("faithfulness sample is not a dict")
    claims = raw.get("claims")
    if not isinstance(claims, list) or not claims:
        # No decomposable claims => faithfulness undefined; treat as 0 support.
        relevancy = _coerce_unit(raw.get("answer_relevancy"))
        return 0.0, 0, 0, relevancy
    n_claims = len(claims)
    n_supported = sum(
        1 for c in claims if isinstance(c, dict) and bool(c.get("supported"))
    )
    n_unsupported = n_claims - n_supported
    faithfulness = n_supported / n_claims if n_claims else 0.0
    relevancy = _coerce_unit(raw.get("answer_relevancy"))
    return faithfulness, n_claims, n_unsupported, relevancy


def _coerce_unit(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, v))


def _default_llm_caller(
    system: str,
    user: str,
    model: str,
    temperature: float,
    sample_index: int,
) -> dict:
    """Real LLM round-trip routed through the opt-in cache (default OFF).

    Mirrors stage2_llm_rubric._call_llm_once: lazy anthropic import, cache
    via src.llm_cache keyed on (model, prompt_sha, temp, max_tokens,
    sample_index). Raises ArticulationMetricError on any failure.
    """
    import os

    def _raw() -> dict:
        try:
            import anthropic  # noqa: WPS433 - function-local by design
        except ImportError as e:  # pragma: no cover - exercised via mock seam
            raise ArticulationMetricError(f"anthropic SDK unavailable: {e}") from e
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ArticulationMetricError("ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            b.text for b in msg.content if getattr(b, "type", None) == "text"
        ).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
        return json.loads(text)

    try:
        from src.llm_cache import cache_from_env, cached_call_once  # noqa: WPS433

        cache = cache_from_env()
    except Exception:  # pragma: no cover - cache import must never break runtime
        cache = None

    try:
        if cache is not None:
            return cached_call_once(
                cache=cache,
                model=model,
                system=system,
                user=user,
                temperature=temperature,
                max_tokens=1024,
                sample_index=sample_index,
                compute=_raw,
                dumps=json.dumps,
                loads=json.loads,
            )
        return _raw()
    except ArticulationMetricError:
        raise
    except Exception as e:  # parse / API errors → degrade
        raise ArticulationMetricError(f"faithfulness LLM call failed: {e}") from e


def score_faithfulness(
    answer: str,
    grounding: str,
    *,
    model: str = "claude-sonnet-4-5",
    n: int = SELF_CONSISTENCY_N,
    temperature: float = SELF_CONSISTENCY_TEMPERATURE,
    llm_caller: Optional[LLMCaller] = None,
) -> FaithfulnessScore:
    """RAGAS faithfulness + answer-relevancy with N=5 self-consistency.

    Args:
        answer:    the agent's articulated text (thesis / rationale).
        grounding: retrieved grounding context (evidence_documents.raw_text).
        llm_caller: test seam — ``(system,user,model,temp,sample_index)->dict``.
                    When None, the cached real Anthropic caller is used.

    Returns:
        FaithfulnessScore. Raises ArticulationMetricError on failure so the
        caller can degrade ``axis_a.faithfulness`` to null (advisory).
    """
    caller = llm_caller or _default_llm_caller
    system, user = _build_prompt(answer, grounding)

    per_sample: list[tuple[float, int, int, float]] = []

    def _faith_sampler(i: int) -> float:
        raw = caller(system, user, model, temperature, i)
        parsed = _parse_sample(raw)
        per_sample.append(parsed)
        return parsed[0]  # faithfulness component drives the median sampler

    median_faith, samples_faith = median_self_consistency(_faith_sampler, n=n)

    if not per_sample:  # pragma: no cover - n>=1 always populates
        raise ArticulationMetricError("no faithfulness samples produced")

    samples_relevancy = [p[3] for p in per_sample]
    import statistics

    median_relevancy = statistics.median(samples_relevancy)

    # Claim accounting from the median-representative sample: pick the sample
    # whose faithfulness equals the median (first match) for the claim counts.
    rep = next(
        (p for p in per_sample if abs(p[0] - median_faith) < 1e-9),
        per_sample[0],
    )
    n_claims = rep[1]
    # Unsupported detection rate: across all N samples, the share that
    # flagged >=1 unsupported claim. On a seeded unsupported-claim fixture
    # this is > 0 (criterion 1 — the unsupported claim is detected).
    n_samples_flagging = sum(1 for p in per_sample if p[2] > 0)
    unsupported_detection_rate = n_samples_flagging / len(per_sample)
    n_unsupported_flagged = rep[2]

    return FaithfulnessScore(
        faithfulness=median_faith,
        answer_relevancy=median_relevancy,
        n_claims=n_claims,
        n_unsupported_flagged=n_unsupported_flagged,
        unsupported_detection_rate=unsupported_detection_rate,
        samples_faithfulness=samples_faith,
        samples_relevancy=samples_relevancy,
    )
