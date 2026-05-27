"""Advisory LLM judge for the WS-6 hybrid gate.

The judge is **advisory only**. It runs on sonnet (cheaper, different from the
opus *producer* — cuts self-preference bias), at temperature 0, with a
**position swap** to control answer-order bias, and is **cached** so CI replays
deterministically with no network.

Hard contract (the linchpin):

  * The judge can emit only two verdicts: ``PASS`` (no objection) or
    ``ESCALATE`` (objection / abstain-to-escalate). It can NEVER emit ``FAIL``
    — hard-FAIL is the deterministic spine's sole privilege.
  * A judge **error** (exception, malformed/blank response, position-swap
    disagreement that can't be resolved, cache miss in replay) degrades to
    ``ESCALATE`` — NEVER to ``PASS``, NEVER silently to ``FAIL``.

Master-key trap
---------------
Adversarial / degenerate inputs that are known LLM-as-judge "master keys"
(a bare ``":"``, a leaked chain-of-thought header like ``"Thought process:"``,
empty/whitespace) must score 0 — i.e. they are NOT allowed to coax a ``PASS``.
They deterministically resolve to ``ESCALATE`` *before* any model call, so no
prompt-injection string can reach the judge model and flip the verdict.

Determinism / no-network
-------------------------
The real model round-trip is injected as ``compute_fn`` and routed through the
P0-5 cache. Tests pass a stub ``compute_fn`` (or set the cache to replay) so no
network is touched. ``resolve_judge_model`` reads ``judge_model: sonnet`` from
``.claude/agents/evaluator.md`` via the P0-6 reader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from src.llm_cache.agent_model import JUDGE, effective_model
from src.llm_cache.cache import LLMCache
from src.llm_cache.wrappers import cached_call_messages

# The only verdicts the judge may produce.
JUDGE_PASS = "PASS"
JUDGE_ESCALATE = "ESCALATE"
JUDGE_VERDICTS = (JUDGE_PASS, JUDGE_ESCALATE)

# Temperature is pinned to 0 for the judge (locked decision).
JUDGE_TEMPERATURE = 0.0
JUDGE_MAX_TOKENS = 256

# Master-key trap patterns. Inputs whose *entire* meaningful content matches
# one of these are degenerate / adversarial and score 0 (=> ESCALATE) without
# ever reaching the model.
_MASTER_KEY_EXACT = {
    ":",
    "thought process:",
    "thought process",
    "reasoning:",
    "final answer:",
    "verdict: pass",
    "pass",
    "score: 10",
}
# Leaked-CoT / role-leak prefixes — if the input *starts* with one of these
# it is a master-key probe regardless of trailing text.
_MASTER_KEY_PREFIXES = (
    "thought process:",
    "thought process :",
    "<thinking>",
    "assistant:",
    "system:",
    "ignore previous",
    "ignore all previous",
)


@dataclass(frozen=True)
class JudgeVerdict:
    """One advisory judgement."""

    verdict: str  # JUDGE_PASS | JUDGE_ESCALATE
    rationale: str
    degraded: bool = False  # True when forced to ESCALATE by error/trap
    master_key_trapped: bool = False
    position_swap_consistent: bool = True

    def __post_init__(self) -> None:
        if self.verdict not in JUDGE_VERDICTS:
            raise ValueError(
                f"judge verdict {self.verdict!r} not in {JUDGE_VERDICTS}"
            )


def is_master_key(text: object) -> bool:
    """Return True if ``text`` is a degenerate / adversarial master-key probe.

    Pure, deterministic, no model call. Empty / whitespace / a bare colon /
    leaked-CoT headers all count.
    """
    if not isinstance(text, str):
        return True  # non-string judge input is itself degenerate -> trap
    s = text.strip()
    if not s:
        return True
    low = s.lower()
    if low in _MASTER_KEY_EXACT:
        return True
    if any(low.startswith(p) for p in _MASTER_KEY_PREFIXES):
        return True
    # A string with no alphanumeric content (e.g. ":", "::", "---") carries no
    # judgeable signal.
    if not re.search(r"[a-z0-9]", low):
        return True
    return False


def resolve_judge_model(agent_name: str = "evaluator") -> str:
    """Resolve the judge model id from the agent header (P0-6).

    Reads ``judge_model: sonnet`` from ``.claude/agents/<agent>.md`` and pins
    it to a versioned id. Falls back to the literal ``"sonnet"`` only if the
    header is unreadable (so the judge never silently runs on the producer
    model without a recorded reason).
    """
    try:
        resolved = effective_model(agent_name, role=JUDGE)
    except (FileNotFoundError, ValueError):
        resolved = None
    return resolved or "sonnet"


def _serialize_envelope(envelope: dict) -> str:
    import json

    return json.dumps(envelope, sort_keys=True, default=str)


def _build_prompts(
    artifact_type: str, envelope_text: str, *, swapped: bool
) -> tuple[str, str]:
    """Build (system, user) prompts. Position-swap reorders the two response
    options so a model with answer-order bias is detected by disagreement
    between the two orderings."""
    system = (
        "You are an ADVISORY judge for an equity-research artifact. You judge "
        "ONLY whether the artifact is sound enough to release. You can NEVER "
        "fail it (that is a separate deterministic gate); you may only AGREE "
        "(no objection) or OBJECT (escalate to a human). Reply with exactly "
        "one token from the option list, nothing else."
    )
    if swapped:
        options = "Options: [ESCALATE, PASS]"
    else:
        options = "Options: [PASS, ESCALATE]"
    user = (
        f"artifact_type: {artifact_type}\n"
        f"{options}\n"
        f"PASS = no objection to release. ESCALATE = object / send to human.\n"
        f"Artifact JSON:\n{envelope_text}\n"
        f"Your one-token verdict:"
    )
    return system, user


def _parse_verdict(raw: object) -> Optional[str]:
    """Map a raw model response to a verdict, or None if unparseable."""
    if not isinstance(raw, str):
        return None
    low = raw.strip().lower()
    if not low:
        return None
    # ESCALATE is the safe interpretation when both appear; check it first.
    if "escalate" in low or "object" in low:
        return JUDGE_ESCALATE
    if "pass" in low or "agree" in low:
        return JUDGE_PASS
    return None


# A compute_fn performs the real model round-trip: (model, system, user,
# temperature, max_tokens, sample_index) -> assistant text.
ComputeFn = Callable[..., str]


def run_judge(
    artifact_type: str,
    envelope: dict,
    *,
    compute_fn: ComputeFn,
    cache: Optional[LLMCache] = None,
    model: Optional[str] = None,
    judge_input_text: Optional[str] = None,
) -> JudgeVerdict:
    """Run the advisory judge with position-swap + caching + trap.

    Args:
        artifact_type: artifact type label (forwarded into the prompt).
        envelope: the parsed artifact envelope dict to judge.
        compute_fn: zero-context model round-trip; called as
            ``compute_fn(model=..., system=..., user=..., temperature=...,
            max_tokens=..., sample_index=...)`` -> assistant text. Injected so
            tests can stub it and CI replays from cache.
        cache: optional P0-5 LLM cache. When set, calls route through it.
        model: override the resolved judge model (tests/CI).
        judge_input_text: optional raw string fed to the master-key trap. When
            None, the serialized envelope is used. Lets the trap see degenerate
            string inputs like ``":"`` directly.

    Returns:
        JudgeVerdict. On ANY error, on the master-key trap firing, or on an
        unresolved position-swap disagreement -> ``ESCALATE`` (degraded=True).
        NEVER ``PASS`` on error; NEVER ``FAIL`` ever.
    """
    # 1. Master-key trap — fires BEFORE any model call.
    trap_input = judge_input_text if judge_input_text is not None else _serialize_envelope(envelope)
    if is_master_key(trap_input):
        return JudgeVerdict(
            verdict=JUDGE_ESCALATE,
            rationale="master-key trap: degenerate/adversarial input scored 0",
            degraded=True,
            master_key_trapped=True,
        )

    resolved_model = model or resolve_judge_model()
    envelope_text = _serialize_envelope(envelope)

    def _one(swapped: bool, sample_index: int) -> Optional[str]:
        system, user = _build_prompts(artifact_type, envelope_text, swapped=swapped)
        try:
            raw = cached_call_messages(
                cache=cache,
                model=resolved_model,
                system=system,
                user=user,
                temperature=JUDGE_TEMPERATURE,
                max_tokens=JUDGE_MAX_TOKENS,
                sample_index=sample_index,
                compute=lambda: compute_fn(
                    model=resolved_model,
                    system=system,
                    user=user,
                    temperature=JUDGE_TEMPERATURE,
                    max_tokens=JUDGE_MAX_TOKENS,
                    sample_index=sample_index,
                ),
            )
        except Exception:  # noqa: BLE001 — any judge error degrades to ESCALATE
            return None
        return _parse_verdict(raw)

    # 2. Position-swap: run both orderings.
    v_normal = _one(swapped=False, sample_index=0)
    v_swapped = _one(swapped=True, sample_index=1)

    # Any error / unparseable -> ESCALATE (never PASS).
    if v_normal is None or v_swapped is None:
        return JudgeVerdict(
            verdict=JUDGE_ESCALATE,
            rationale="judge error or unparseable response -> ESCALATE (fail-safe)",
            degraded=True,
            position_swap_consistent=False,
        )

    # 3. Position-swap disagreement -> order bias detected -> ESCALATE.
    if v_normal != v_swapped:
        return JudgeVerdict(
            verdict=JUDGE_ESCALATE,
            rationale=(
                f"position-swap disagreement (normal={v_normal}, "
                f"swapped={v_swapped}) -> ESCALATE"
            ),
            degraded=True,
            position_swap_consistent=False,
        )

    # 4. Consistent verdict.
    return JudgeVerdict(
        verdict=v_normal,
        rationale="position-swap-consistent advisory verdict",
        degraded=False,
        position_swap_consistent=True,
    )


__all__ = [
    "JUDGE_PASS",
    "JUDGE_ESCALATE",
    "JUDGE_VERDICTS",
    "JUDGE_TEMPERATURE",
    "JudgeVerdict",
    "ComputeFn",
    "is_master_key",
    "resolve_judge_model",
    "run_judge",
]
