"""Materiality classifier — LLM judge for L4 / P8 daily monitor.

Per v3 spec Section 4.5 Q1 + Q2 (lines 460-504): every event surfaced
by the ingestor is classified into one of three materiality tiers
(M-1 / M-2 / M-3) by an LLM judge. The judge is **single-attribute**
(classification only — routing is handled separately by router.py)
and **forced-JSON** (validated client-side; non-conforming = re-default
to M-1 with a flag).

Model selection (operator-locked, Section 4.5):
    - Default: claude-sonnet-4-6 (Sonnet, NOT Haiku)
    - Escalation: claude-opus-4-7 for M-3 candidate re-validation

Escalation flow:
    1. First-pass call to Sonnet → returns {classification, confidence,
       rationale, verbatim_quote, cited_kill_criterion_id}.
    2. If first-pass classification == M-3 AND confidence >= 0.6, we
       escalate to Opus for a second-pass re-validation. The Opus
       result wins (cannot be downgraded by Sonnet — Section 4.5 Q2:
       "M-3: Cannot downgrade").
    3. If first-pass returns M-1/M-2, no escalation.

Verbatim-quote enforcement (Section 6 Q1):
    - Every M-2/M-3 verdict MUST cite a verbatim quote present in the
      event's ``raw_text``. Failures are downgraded to M-1 + flag.
    - M-1 verdicts may omit a quote (informational only).

Confidence-distribution monitoring (Phase 4 Q8):
    - Every classification carries a llm_judge_confidence score [0,1].
    - drift_detector.py reads these for P50/P90 quarterly drift watch.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 4.5 Q1, Q2 — daily refresh + materiality routing
    Section 6 Q1     — verbatim-quote audit-trail enforcement
    Phase 4 Q8       — confidence distribution drift watch
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from . import (
    DEFAULT_MODEL,
    ESCALATION_MODEL,
    JUDGE_CONFIDENCE_FLOOR,
    MATERIALITY_LABELS,
    MATERIALITY_M1,
    MATERIALITY_M2,
    MATERIALITY_M3,
    PROMPT_VERSION,
)
from .event_ingestor import Event

_LOG = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """Raised when no Anthropic SDK / API key is available and no client supplied."""


# --------------------------------------------------------------------------- #
# Result dataclass                                                            #
# --------------------------------------------------------------------------- #


@dataclass
class MaterialityVerdict:
    """LLM-judge output for a single event.

    Maps to ``materiality_events`` row + the per-event entry in
    ``daily_refresh_log.events`` JSONB array.

    Phase 4 cleanup #4: ``classification`` is the integer 1/2/3;
    ``label`` is the derived 'M-1'/'M-2'/'M-3' string.
    """

    classification: int            # 1 / 2 / 3
    confidence: float              # [0, 1] — judge self-reported
    rationale: str                 # <= 2 sentences
    verbatim_quote: str            # required for M-2/M-3; empty allowed for M-1
    cited_kill_criterion_id: Optional[str]  # FK to scenarios.kill_criteria_structured
    model: str
    prompt_version: str
    tier_escalated_to_opus: bool   # True only if Sonnet → Opus re-validated
    flags: list[str] = field(default_factory=list)
    raw_responses: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """Derived 'M-1'/'M-2'/'M-3' label per Phase 4 cleanup #4."""
        return MATERIALITY_LABELS[self.classification]

    def to_event_jsonb(self, event: Event) -> dict[str, Any]:
        """Serialize for daily_refresh_log.events JSONB array entry."""
        return {
            "type": event.type,
            "source_id": event.source_id,
            "timestamp": event.timestamp.isoformat(),
            "verbatim_quote": self.verbatim_quote,
            "classification": self.classification,
            "label": self.label,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "cited_kill_criterion_id": self.cited_kill_criterion_id,
            "flags": list(self.flags),
        }


# --------------------------------------------------------------------------- #
# Prompt construction                                                         #
# --------------------------------------------------------------------------- #


_SYSTEM_PROMPT = (
    "You are the L4 materiality judge for an equity-research system. "
    "Your single task is to classify ONE event into one of three tiers:\n"
    "  M-1 (noise) — informational; no thesis impact.\n"
    "  M-2 (watch) — partial re-underwrite warranted (2-4 of 5 debate agents).\n"
    "  M-3 (act)   — full re-underwrite + operator alert; thesis-defining.\n\n"
    "RULES (non-negotiable):\n"
    "1. Output ONLY a single JSON object. No markdown, no commentary.\n"
    "2. JSON schema:\n"
    "   {\n"
    '     "classification": "M-1" | "M-2" | "M-3",\n'
    '     "confidence":      0.0 - 1.0,\n'
    '     "rationale":       "<= 2 sentences",\n'
    '     "verbatim_quote":  "<must be a substring of the EVENT raw_text>",\n'
    '     "cited_kill_criterion_id": "<scenario.kill_id or null>"\n'
    "   }\n"
    "3. M-2 and M-3 REQUIRE a non-empty verbatim_quote that appears VERBATIM "
    "in the event raw_text. If you cannot find one, classify M-1.\n"
    "4. Single-attribute task: classify materiality only. Do NOT pick agents, "
    "do NOT recommend actions — that's the router's job.\n"
    "5. If the event maps to a previously-articulated kill criterion, cite its "
    "id in cited_kill_criterion_id; otherwise null.\n"
)


def _build_user_prompt(
    ticker: str,
    event: Event,
    regime_context: dict[str, Any],
    scenario_kill_criteria: list[dict[str, Any]],
) -> str:
    """Compose the user prompt: event + thesis context + kill-criteria list."""
    parts = [
        f"TICKER: {ticker}",
        "",
        f"EVENT TYPE: {event.type}",
        f"EVENT SOURCE: {event.source_id}",
        f"EVENT TIMESTAMP: {event.timestamp.isoformat()}",
        "",
        "EVENT raw_text:",
        event.raw_text or "(empty)",
        "",
        "REGIME CONTEXT (snapshot at evaluation time):",
        json.dumps(regime_context, indent=2, default=str),
        "",
        "KILL CRITERIA (cite by id if event triggers one):",
        json.dumps(scenario_kill_criteria, indent=2, default=str),
        "",
        "Return your JSON now.",
    ]
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# JSON parsing + validation                                                   #
# --------------------------------------------------------------------------- #


_LABEL_TO_INT = {"M-1": 1, "M-2": 2, "M-3": 3, "m-1": 1, "m-2": 2, "m-3": 3}


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _validate_payload(
    payload: Any, event_raw_text: str
) -> tuple[bool, Optional[str], Optional[dict]]:
    """Return (is_valid, reason_if_invalid, normalized_dict).

    Normalizes ``classification`` to integer, validates verbatim quote
    against the event's raw_text. Per spec Section 6 Q1: M-2/M-3 require
    a verbatim quote.
    """
    if not isinstance(payload, dict):
        return False, "payload not an object", None
    cls_raw = payload.get("classification")
    if isinstance(cls_raw, str) and cls_raw in _LABEL_TO_INT:
        cls_int = _LABEL_TO_INT[cls_raw]
    elif isinstance(cls_raw, int) and cls_raw in (1, 2, 3):
        cls_int = cls_raw
    else:
        return False, f"invalid classification: {cls_raw!r}", None
    try:
        conf = float(payload.get("confidence", -1))
    except (TypeError, ValueError):
        return False, "confidence not numeric", None
    if not 0.0 <= conf <= 1.0:
        return False, f"confidence out of range: {conf}", None
    rationale = payload.get("rationale")
    if not isinstance(rationale, str):
        return False, "rationale not a string", None
    quote = payload.get("verbatim_quote") or ""
    if not isinstance(quote, str):
        return False, "verbatim_quote not a string", None
    if cls_int in (MATERIALITY_M2, MATERIALITY_M3):
        if not quote.strip():
            return False, "verbatim_quote required for M-2/M-3", None
        if quote not in (event_raw_text or ""):
            return False, "verbatim_quote not a substring of raw_text", None
    kill_id = payload.get("cited_kill_criterion_id")
    if kill_id is not None and not isinstance(kill_id, str):
        return False, "cited_kill_criterion_id must be string or null", None

    normalized = {
        "classification": cls_int,
        "confidence": conf,
        "rationale": rationale,
        "verbatim_quote": quote,
        "cited_kill_criterion_id": kill_id,
    }
    return True, None, normalized


# --------------------------------------------------------------------------- #
# Public entry                                                                #
# --------------------------------------------------------------------------- #


def classify_materiality(
    ticker: str,
    event: Event,
    regime_context: Optional[dict[str, Any]] = None,
    scenario_kill_criteria: Optional[list[dict[str, Any]]] = None,
    client: Any = None,
    escalate_m3: bool = True,
) -> MaterialityVerdict:
    """Classify a single event into M-1 / M-2 / M-3.

    Args:
        ticker: Equity ticker.
        event: :class:`Event` to classify.
        regime_context: S0 regime snapshot at evaluation time. Optional;
            defaults to {} (still classifies, but model loses context).
        scenario_kill_criteria: List of {kill_id, criterion_text, ...}
            from ``scenarios.kill_criteria_structured`` for this ticker.
            Optional; defaults to []. The judge cites by kill_id when an
            event trips a criterion.
        client: Optional pre-built ``anthropic.Anthropic`` client; tests
            inject a fake.
        escalate_m3: If True (default), Sonnet M-3 verdicts trigger an
            Opus second-pass re-validation per Section 4.5.

    Returns:
        :class:`MaterialityVerdict`.

    Raises:
        :class:`LLMUnavailableError` if no SDK/key and no client supplied.
    """
    regime_context = regime_context or {}
    kill_criteria = scenario_kill_criteria or []
    if client is None:
        client = _build_default_client()

    sys_prompt = _SYSTEM_PROMPT
    user_prompt = _build_user_prompt(ticker, event, regime_context, kill_criteria)

    flags: list[str] = []
    raw_responses: list[str] = []

    # --- First pass: Sonnet ------------------------------------------------ #
    raw1 = _call_once(client, DEFAULT_MODEL, sys_prompt, user_prompt)
    raw_responses.append(raw1)
    parsed1 = _extract_json(raw1)
    if parsed1 is None:
        flags.append("malformed_json_default_to_m1")
        return _default_m1_verdict(
            DEFAULT_MODEL, flags, raw_responses,
            rationale="malformed JSON; defaulted to M-1",
        )
    ok1, reason1, norm1 = _validate_payload(parsed1, event.raw_text)
    if not ok1:
        # Section 6 Q1: no quote → defaults to M-1 + flag.
        flags.append(f"validation_failed:{reason1}")
        return _default_m1_verdict(
            DEFAULT_MODEL, flags, raw_responses,
            rationale=str(parsed1.get("rationale", "")) or "validation failed",
        )

    # M-1 / M-2: no escalation needed.
    if norm1["classification"] != MATERIALITY_M3 or not escalate_m3:
        return MaterialityVerdict(
            classification=norm1["classification"],
            confidence=norm1["confidence"],
            rationale=norm1["rationale"],
            verbatim_quote=norm1["verbatim_quote"],
            cited_kill_criterion_id=norm1["cited_kill_criterion_id"],
            model=DEFAULT_MODEL,
            prompt_version=PROMPT_VERSION,
            tier_escalated_to_opus=False,
            flags=flags,
            raw_responses=raw_responses,
        )

    # --- Second pass: Opus re-validation (M-3 candidates) ------------------ #
    if norm1["confidence"] < JUDGE_CONFIDENCE_FLOOR:
        # Low-confidence M-3 → still escalate per spec (M-3 cannot
        # downgrade), but tag the flag.
        flags.append("low_confidence_m3_escalated")
    raw2 = _call_once(client, ESCALATION_MODEL, sys_prompt, user_prompt)
    raw_responses.append(raw2)
    parsed2 = _extract_json(raw2)
    if parsed2 is None:
        # Opus failed to parse — keep Sonnet M-3 verdict but tag.
        flags.append("opus_malformed_json_kept_sonnet_m3")
        return MaterialityVerdict(
            classification=MATERIALITY_M3,
            confidence=norm1["confidence"],
            rationale=norm1["rationale"],
            verbatim_quote=norm1["verbatim_quote"],
            cited_kill_criterion_id=norm1["cited_kill_criterion_id"],
            model=ESCALATION_MODEL,
            prompt_version=PROMPT_VERSION,
            tier_escalated_to_opus=True,
            flags=flags,
            raw_responses=raw_responses,
        )
    ok2, reason2, norm2 = _validate_payload(parsed2, event.raw_text)
    if not ok2:
        flags.append(f"opus_validation_failed_kept_sonnet_m3:{reason2}")
        return MaterialityVerdict(
            classification=MATERIALITY_M3,
            confidence=norm1["confidence"],
            rationale=norm1["rationale"],
            verbatim_quote=norm1["verbatim_quote"],
            cited_kill_criterion_id=norm1["cited_kill_criterion_id"],
            model=ESCALATION_MODEL,
            prompt_version=PROMPT_VERSION,
            tier_escalated_to_opus=True,
            flags=flags,
            raw_responses=raw_responses,
        )

    # Spec line 495: M-3 cannot be downgraded. If Opus says M-1/M-2 we keep
    # the M-3 floor but adopt Opus's rationale + quote (more authoritative).
    final_cls = max(MATERIALITY_M3, norm2["classification"])  # always M-3
    if norm2["classification"] != MATERIALITY_M3:
        flags.append(
            f"opus_proposed_{MATERIALITY_LABELS[norm2['classification']]}_floored_to_M-3"
        )
    return MaterialityVerdict(
        classification=final_cls,
        confidence=norm2["confidence"],
        rationale=norm2["rationale"],
        verbatim_quote=norm2["verbatim_quote"] or norm1["verbatim_quote"],
        cited_kill_criterion_id=norm2["cited_kill_criterion_id"]
            or norm1["cited_kill_criterion_id"],
        model=ESCALATION_MODEL,
        prompt_version=PROMPT_VERSION,
        tier_escalated_to_opus=True,
        flags=flags,
        raw_responses=raw_responses,
    )


def _default_m1_verdict(
    model: str,
    flags: list[str],
    raw_responses: list[str],
    rationale: str = "",
) -> MaterialityVerdict:
    """Conservative default: M-1 with zero confidence + flag."""
    return MaterialityVerdict(
        classification=MATERIALITY_M1,
        confidence=0.0,
        rationale=rationale,
        verbatim_quote="",
        cited_kill_criterion_id=None,
        model=model,
        prompt_version=PROMPT_VERSION,
        tier_escalated_to_opus=False,
        flags=flags,
        raw_responses=raw_responses,
    )


# --------------------------------------------------------------------------- #
# SDK glue                                                                    #
# --------------------------------------------------------------------------- #


def _build_default_client() -> Any:
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
            "decision 1 (Path A) the v0.1 runtime is Claude Code; this "
            "module is normally invoked from a subagent context. To run "
            "outside Claude Code, set ANTHROPIC_API_KEY."
        )
    return anthropic.Anthropic()


def _call_once(
    client: Any,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 1024,
) -> str:
    """One messages.create round-trip; returns assistant text."""
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        # Temperature 0 for the materiality judge — single-attribute,
        # forced-JSON, no self-consistency averaging here (Sonnet→Opus
        # escalation is the redundancy).
        temperature=0.0,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # The SDK returns ``Message.content`` as a list of content blocks.
    parts: list[str] = []
    for block in getattr(resp, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
        elif isinstance(block, dict) and block.get("text"):
            parts.append(str(block["text"]))
    return "\n".join(parts).strip()
