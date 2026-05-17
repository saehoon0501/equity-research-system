"""Stage 3 — Overlap detection + LLM tie-breaker.

Per spec Section 2.2 lines 115-121 and Section 7 PB#3::

    IF candidate hits >1 bin OR fails all 3 -> LLM tie-breaker
    Single-attribute LLM call (Sonnet/Opus per Section 6 Q1)
    Forced JSON: {bin, confidence, rationale, evidence_quotes}
    Verbatim evidence required (no quote -> defaults to most-conservative C)
    Self-consistency N=5 samples at temp=0.7

This module isolates the LLM contract:

* **Single-attribute call.** The prompt asks for the *bin only* — not
  bin + sizing + horizon together. Per Section 6 Q1 (verifier-aware
  generation): single-attribute calls have lower hallucination than
  multi-attribute joint outputs.
* **Forced JSON schema validation.** The model must return exactly the
  four fields :func:`_validate_payload` checks; non-compliant payloads
  are dropped from the self-consistency vote.
* **Verbatim evidence requirement.** ``evidence_quotes`` must be a
  non-empty list AND each quote must appear verbatim in the input
  context. If the validator can't verify any quote, the sample is
  *re-binned to C* (the most-conservative default per spec line 119).
* **Self-consistency N=5 at temp=0.7.** We run 5 independent samples
  and take the median (modal) bin. Confidence reported is the share
  of samples that voted with the modal bin (range [0, 1]; 0 if no
  samples produced valid output).

Model selection per Section 6 Q1:

* Default: ``claude-sonnet-4-5`` (current Sonnet at the v3 spec date).
* High-stakes escalation: ``claude-opus-4-5`` when ``high_stakes=True``
  is passed by the caller (e.g., position-already-taken on the name,
  large notional, or reclassification flagged by Phase 4 Q5 recheck).

Path-A note: BUILD_LOG.md decision 1 says Claude Code is the runtime
and there is no separate Anthropic API key in v0.1. This module still
imports the ``anthropic`` SDK (the task spec requires it) and degrades
gracefully when no key is present — :func:`tiebreaker` will raise
:class:`LLMUnavailableError` rather than silently default to C, so the
caller can decide whether to fall back to "rule_clean=False, mode=C
with low confidence" or to fail loud.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional

from . import MODE_B, MODE_B_PRIME, MODE_C

_LOG = logging.getLogger(__name__)

# Per Section 6 Q1 — model identifiers reviewable in one place.
DEFAULT_MODEL: str = "claude-sonnet-4-5"
HIGH_STAKES_MODEL: str = "claude-opus-4-5"

# Spec-fixed knobs — DO NOT change without spec amendment.
SELF_CONSISTENCY_N: int = 5
SAMPLING_TEMPERATURE: float = 0.7
PROMPT_VERSION: str = "stage3.v1.2026-04-29"


class LLMUnavailableError(RuntimeError):
    """Raised when the SDK is missing or no credentials are available."""


@dataclass
class TiebreakerSample:
    """One Self-consistency sample's parsed output."""

    bin: str
    confidence: float
    rationale: str
    evidence_quotes: list[str]
    raw_text: str
    valid: bool
    invalid_reason: Optional[str] = None


@dataclass
class TiebreakerResult:
    """Aggregated tie-breaker output for the orchestrator.

    Maps to ``mode_classifications.llm_tiebreaker`` JSONB column per
    migration 008. Schema mirrors the documented payload comment.
    """

    bin: str
    confidence: float
    rationale: str
    evidence_quotes: list[str]
    model: str
    prompt_version: str
    self_consistency: dict[str, Any]
    samples: list[TiebreakerSample] = field(default_factory=list)

    def to_payload(self) -> dict:
        """Serialize for ``mode_classifications.llm_tiebreaker`` JSONB."""
        return {
            "model": self.model,
            "prompt_version": self.prompt_version,
            "rating": self.bin,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "evidence_quotes": self.evidence_quotes,
            "self_consistency": self.self_consistency,
        }


# --------------------------------------------------------------------------- #
# Prompt construction — single-attribute, forced JSON.                        #
# --------------------------------------------------------------------------- #


_SYSTEM_PROMPT = (
    "You are the Stage 3 tie-breaker for an equity-research system's mode "
    "classifier. Your single task is to assign a ticker to one of three bins:\n"
    "  B       - steady compounder, market_cap > $50B, vol < 25%, profitable >5y, growth < 12%\n"
    "  B_prime - growth compounder, market_cap > $50B, profitable, (vol > 25% OR growth > 15%)\n"
    "  C       - thematic / pre-profit / narrative-driven / market_cap < $50B\n\n"
    "RULES (non-negotiable):\n"
    "1. Output ONLY a single JSON object. No markdown, no commentary.\n"
    "2. JSON schema: {\"bin\":\"B|B_prime|C\",\"confidence\":0.0-1.0,"
    "\"rationale\":\"<= 2 sentences\",\"evidence_quotes\":[\"verbatim ...\", ...]}\n"
    "3. evidence_quotes MUST be verbatim substrings of the EVIDENCE block. "
    "If you cannot find verbatim evidence, return bin = \"C\" (the conservative default).\n"
    "4. Single-attribute task: classify the BIN only. Do not opine on sizing, "
    "horizon, or quality flag.\n"
)


def _build_user_prompt(
    ticker: str,
    facts_block: str,
    rule_outcomes: dict,
) -> str:
    return (
        f"TICKER: {ticker}\n\n"
        f"RULE OUTCOMES:\n{json.dumps(rule_outcomes, indent=2, default=str)}\n\n"
        f"EVIDENCE:\n{facts_block.strip()}\n\n"
        "Return your JSON now."
    )


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #


def _validate_payload(
    payload: Any, evidence_block: str
) -> tuple[bool, Optional[str]]:
    """Return (is_valid, reason_if_invalid).

    Verbatim-evidence rule: every entry in ``evidence_quotes`` must
    appear as a substring of ``evidence_block``. Empty list also fails.
    """
    if not isinstance(payload, dict):
        return False, "payload not an object"
    for k in ("bin", "confidence", "rationale", "evidence_quotes"):
        if k not in payload:
            return False, f"missing key: {k}"
    if payload["bin"] not in (MODE_B, MODE_B_PRIME, MODE_C):
        return False, f"invalid bin: {payload['bin']!r}"
    try:
        conf = float(payload["confidence"])
    except (TypeError, ValueError):
        return False, "confidence not numeric"
    if not 0.0 <= conf <= 1.0:
        return False, f"confidence out of range: {conf}"
    if not isinstance(payload["rationale"], str):
        return False, "rationale not a string"
    quotes = payload["evidence_quotes"]
    if not isinstance(quotes, list) or not quotes:
        return False, "evidence_quotes must be a non-empty list"
    for q in quotes:
        if not isinstance(q, str):
            return False, "evidence_quote not a string"
        if not q.strip():
            return False, "evidence_quote is empty or whitespace-only"
        if q not in evidence_block:
            return False, f"non-verbatim quote: {q[:80]!r}"
    return True, None


def _extract_json(text: str) -> Optional[dict]:
    """Best-effort JSON extraction from a model response.

    Models occasionally emit code fences or leading prose despite the
    system prompt; we strip the first/last brace span before parse.
    """
    text = text.strip()
    # Direct parse first.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip code fences.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    # Find first '{' and last '}'.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------- #
# Self-consistency aggregation                                                #
# --------------------------------------------------------------------------- #


def _aggregate(samples: list[TiebreakerSample]) -> tuple[str, float, str, list[str]]:
    """Return (modal_bin, share_confidence, best_rationale, merged_quotes).

    Spec line 120: "median bin". With 3 categorical bins and 5 samples
    we use the *modal* bin (mode == median for unimodal categoricals).
    Tie-break on equal counts: prefer the most conservative bin per
    spec line 119 (C > B_prime > B for safety).
    """
    valid = [s for s in samples if s.valid]
    if not valid:
        # All samples invalid → conservative C with zero confidence.
        return MODE_C, 0.0, "all samples invalid; defaulted to C", []
    counts = Counter(s.bin for s in valid)
    top = counts.most_common()
    top_n = top[0][1]
    tied = [b for b, n in top if n == top_n]
    if len(tied) == 1:
        modal = tied[0]
    else:
        # Conservative tie-break: C > B_prime > B
        for cand in (MODE_C, MODE_B_PRIME, MODE_B):
            if cand in tied:
                modal = cand
                break
    share = top_n / len(valid)
    # Pick the modal sample with highest internal confidence as the
    # canonical rationale; merge unique quotes from all modal samples.
    modal_samples = [s for s in valid if s.bin == modal]
    canonical = max(modal_samples, key=lambda s: s.confidence)
    quotes_seen: list[str] = []
    for s in modal_samples:
        for q in s.evidence_quotes:
            if q not in quotes_seen:
                quotes_seen.append(q)
    return modal, share, canonical.rationale, quotes_seen


# --------------------------------------------------------------------------- #
# Public entry                                                                #
# --------------------------------------------------------------------------- #


def tiebreaker(
    ticker: str,
    evidence_block: str,
    rule_outcomes: dict,
    high_stakes: bool = False,
    n_samples: int = SELF_CONSISTENCY_N,
    temperature: float = SAMPLING_TEMPERATURE,
    client: Any = None,  # injectable for tests
) -> TiebreakerResult:
    """Run the LLM tie-breaker.

    Args:
        ticker: The ticker under classification (for logging only).
        evidence_block: Plain-text evidence (cap, vol, growth, profit
            history, narrative flag, etc.) — model may only quote from
            this block. The verbatim-evidence rule rejects out-of-block
            "quotes".
        rule_outcomes: The Stage 1 :class:`Stage1Result.to_rule_outcomes`
            dict; included in the prompt so the model knows which rule
            collisions triggered the tie-break.
        high_stakes: If True, route to :data:`HIGH_STAKES_MODEL`
            (Opus); otherwise :data:`DEFAULT_MODEL` (Sonnet).
        n_samples: Self-consistency N (default 5 per spec).
        temperature: Sampling temperature (default 0.7 per spec).
        client: Optional pre-built ``anthropic.Anthropic`` client; if
            ``None`` we construct one from the environment. Tests pass
            a fake client implementing the same ``messages.create`` API.

    Returns:
        :class:`TiebreakerResult`.

    Raises:
        :class:`LLMUnavailableError` when the SDK or API key is missing
        and no client was supplied.
    """
    model = HIGH_STAKES_MODEL if high_stakes else DEFAULT_MODEL
    if client is None:
        client = _build_default_client()

    sys_prompt = _SYSTEM_PROMPT
    user_prompt = _build_user_prompt(ticker, evidence_block, rule_outcomes)

    samples: list[TiebreakerSample] = []
    for i in range(n_samples):
        raw = _call_once(client, model, sys_prompt, user_prompt, temperature)
        parsed = _extract_json(raw)
        if parsed is None:
            samples.append(
                TiebreakerSample(
                    bin=MODE_C,
                    confidence=0.0,
                    rationale="malformed JSON",
                    evidence_quotes=[],
                    raw_text=raw,
                    valid=False,
                    invalid_reason="json parse failure",
                )
            )
            continue
        ok, reason = _validate_payload(parsed, evidence_block)
        if not ok:
            # Spec line 119: no quote -> defaults to most-conservative C.
            samples.append(
                TiebreakerSample(
                    bin=MODE_C,
                    confidence=0.0,
                    rationale=str(parsed.get("rationale", "")),
                    evidence_quotes=[],
                    raw_text=raw,
                    valid=False,
                    invalid_reason=reason,
                )
            )
            continue
        samples.append(
            TiebreakerSample(
                bin=parsed["bin"],
                confidence=float(parsed["confidence"]),
                rationale=str(parsed["rationale"]),
                evidence_quotes=list(parsed["evidence_quotes"]),
                raw_text=raw,
                valid=True,
            )
        )

    modal, share, rationale, quotes = _aggregate(samples)
    valid_count = sum(1 for s in samples if s.valid)
    bin_distribution = dict(Counter(s.bin for s in samples if s.valid))

    self_consistency = {
        "n_samples": n_samples,
        "valid_samples": valid_count,
        "temperature": temperature,
        "modal_share": share,
        "bin_distribution": bin_distribution,
        "median_confidence": (
            statistics.median([s.confidence for s in samples if s.valid])
            if valid_count
            else 0.0
        ),
        "invalid_reasons": [
            s.invalid_reason for s in samples if not s.valid and s.invalid_reason
        ],
    }

    return TiebreakerResult(
        bin=modal,
        confidence=share,
        rationale=rationale,
        evidence_quotes=quotes,
        model=model,
        prompt_version=PROMPT_VERSION,
        self_consistency=self_consistency,
        samples=samples,
    )


# --------------------------------------------------------------------------- #
# SDK glue                                                                    #
# --------------------------------------------------------------------------- #


def _build_default_client() -> Any:
    """Build an Anthropic client from the environment, or raise."""
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError as exc:
        raise LLMUnavailableError(
            "anthropic SDK not installed; pip install anthropic OR pass a "
            "test double via the `client=` argument."
        ) from exc
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMUnavailableError(
            "ANTHROPIC_API_KEY not set in environment. Per BUILD_LOG.md "
            "decision 1 (Path A) the v0.1 runtime is Claude Code; the LLM "
            "tie-breaker is therefore expected to be exercised under "
            "Claude Code's MCP tool surface, not direct SDK calls. To run "
            "the classifier outside Claude Code you must set ANTHROPIC_API_KEY."
        )
    return anthropic.Anthropic()


def _call_once(
    client: Any,
    model: str,
    system: str,
    user: str,
    temperature: float,
) -> str:
    """One messages.create round-trip; returns the assistant text."""
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # anthropic.types.Message.content is a list of content blocks;
    # the first text block is what we want.
    blocks = getattr(resp, "content", None) or []
    for b in blocks:
        text = getattr(b, "text", None)
        if text:
            return text
    # Dict-shape fallback (test doubles often return plain dicts).
    if isinstance(resp, dict):
        for b in resp.get("content", []) or []:
            if isinstance(b, dict) and b.get("type") == "text":
                return b.get("text", "")
    _LOG.warning("LLM response had no text content; returning empty string")
    return ""
