"""Materiality router — Section 4.5 Q2 hybrid floor + LLM judge.

Per v3 spec Section 4.5 Q2 (lines 489-504): the materiality verdict
determines the routing action.

| Tier | Action                                            | LLM-judge role |
|------|---------------------------------------------------|----------------|
| M-1  | No-op, log only                                   | None           |
| M-2  | P4 partial re-underwrite; LLM picks 2-4 of 5      | Bounded sel.   |
| M-3  | P4 full 5-agent re-underwrite + operator alert    | Cannot downgr. |

Hybrid floor: when the LLM judge's confidence < 0.6, the router falls
back to a deterministic event_type → agents lookup table (the
``EVENT_TYPE_AGENT_LOOKUP`` dict in ``__init__.py``).

For M-3, all 5 agents always fire (no LLM agent-selection call).

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 4.5 Q2 — materiality routing (hybrid floor + LLM judge)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from . import (
    ALL_AGENTS,
    DEFAULT_MODEL,
    EVENT_TYPE_AGENT_LOOKUP,
    JUDGE_CONFIDENCE_FLOOR,
    MATERIALITY_M1,
    MATERIALITY_M3,
)
from .event_ingestor import Event
from .materiality_classifier import LLMUnavailableError, MaterialityVerdict

_LOG = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    """Routing output for one (event, verdict) pair.

    Attributes:
        action: One of:
            'no_op'                 — M-1.
            'partial_reunderwrite'  — M-2 (subset of agents).
            'full_reunderwrite'     — M-3 (all 5 agents + alert).
        agents: Agent names to dispatch (subset of ``ALL_AGENTS``).
        operator_alert: True iff M-3 (Section 7 PB#4: alerts only on M-2/M-3,
            but routing uses operator_alert specifically for M-3 escalations
            that demand interrupt-level attention).
        rationale: Why this routing was chosen.
        used_fallback_table: True if the deterministic lookup was used.
        agent_selection_model: Model used for agent picking (None when
            fallback table fired).
    """

    action: str
    agents: list[str]
    operator_alert: bool
    rationale: str
    used_fallback_table: bool
    agent_selection_model: Optional[str] = None
    flags: list[str] = field(default_factory=list)
    raw_response: Optional[str] = None


# --------------------------------------------------------------------------- #
# LLM agent picker                                                            #
# --------------------------------------------------------------------------- #


_AGENT_PICKER_SYSTEM_PROMPT = (
    "You are the agent router for an equity-research system's M-2 partial "
    "re-underwrite. Your single task is to pick 2-4 of 5 debate agents to "
    "dispatch:\n"
    "  Quality          - moat, governance, accounting, balance sheet\n"
    "  Growth           - TAM, unit economics, secular drivers\n"
    "  Value            - multiples, FCF yield, capital allocation\n"
    "  Macro-Regime     - rates, FX, credit, regime\n"
    "  Quant-Technical  - flows, technicals, smart money\n\n"
    "RULES:\n"
    "1. Output ONLY a single JSON object. No markdown.\n"
    "2. Schema: {\"agents\": [...], \"rationale\": \"<= 2 sentences\"}\n"
    "3. agents MUST be 2-4 names from the list above (case-sensitive).\n"
    "4. Single-attribute task: pick agents only.\n"
)


def _build_picker_prompt(
    ticker: str, event: Event, verdict: MaterialityVerdict
) -> str:
    return (
        f"TICKER: {ticker}\n\n"
        f"EVENT TYPE: {event.type}\n"
        f"EVENT SOURCE: {event.source_id}\n\n"
        f"MATERIALITY VERDICT: {verdict.label} "
        f"(confidence {verdict.confidence:.2f})\n"
        f"VERBATIM_QUOTE: {verdict.verbatim_quote!r}\n"
        f"RATIONALE: {verdict.rationale}\n\n"
        "Pick 2-4 of {Quality, Growth, Value, Macro-Regime, Quant-Technical} "
        "and return your JSON now."
    )


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


def _validate_picker(payload: Any) -> Optional[list[str]]:
    """Return the validated agent list or None on failure."""
    if not isinstance(payload, dict):
        return None
    agents = payload.get("agents")
    if not isinstance(agents, list) or not (2 <= len(agents) <= 4):
        return None
    cleaned: list[str] = []
    for a in agents:
        if not isinstance(a, str) or a not in ALL_AGENTS:
            return None
        if a not in cleaned:
            cleaned.append(a)
    if not (2 <= len(cleaned) <= 4):
        return None
    return cleaned


def _call_picker(
    ticker: str,
    event: Event,
    verdict: MaterialityVerdict,
    client: Any,
) -> tuple[Optional[list[str]], str, str]:
    """Return (agents_or_none, rationale, raw_text)."""
    sys_prompt = _AGENT_PICKER_SYSTEM_PROMPT
    user_prompt = _build_picker_prompt(ticker, event, verdict)
    resp = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=512,
        temperature=0.0,
        system=sys_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    parts: list[str] = []
    for block in getattr(resp, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
        elif isinstance(block, dict) and block.get("text"):
            parts.append(str(block["text"]))
    raw = "\n".join(parts).strip()
    parsed = _extract_json(raw)
    if parsed is None:
        return None, "agent picker: malformed JSON", raw
    agents = _validate_picker(parsed)
    rationale = str(parsed.get("rationale", "")) if isinstance(parsed, dict) else ""
    return agents, rationale, raw


def _build_default_client() -> Any:
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError as exc:
        raise LLMUnavailableError(
            "anthropic SDK not installed; pip install anthropic OR pass a "
            "test double via the `client=` argument."
        ) from exc
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMUnavailableError("ANTHROPIC_API_KEY not set in environment.")
    return anthropic.Anthropic()


# --------------------------------------------------------------------------- #
# Public entry                                                                #
# --------------------------------------------------------------------------- #


def fallback_agents_for_event(event_type: str) -> list[str]:
    """Section 4.5 Q2 deterministic fallback table.

    Returns 2 agents per the table; defaults to ('Quality', 'Value') for
    unknown event types (defensive — guarantees ≥2 agents fire).
    """
    return list(EVENT_TYPE_AGENT_LOOKUP.get(event_type, ("Quality", "Value")))


def route_materiality(
    ticker: str,
    event: Event,
    verdict: MaterialityVerdict,
    client: Any = None,
) -> RoutingDecision:
    """Route a materiality verdict to action + agents.

    Per Section 4.5 Q2:
      - M-1 → no-op.
      - M-2 → LLM picks 2-4 agents; fallback to lookup table if
              judge confidence < 0.6.
      - M-3 → all 5 agents + operator alert (no LLM picker call).

    Args:
        ticker: Equity ticker.
        event: The :class:`Event` being routed.
        verdict: :class:`MaterialityVerdict` from the classifier.
        client: Optional Anthropic client; injectable for tests.

    Returns:
        :class:`RoutingDecision`.
    """
    if verdict.classification == MATERIALITY_M1:
        return RoutingDecision(
            action="no_op",
            agents=[],
            operator_alert=False,
            rationale="M-1 noise; log only.",
            used_fallback_table=False,
        )

    if verdict.classification == MATERIALITY_M3:
        return RoutingDecision(
            action="full_reunderwrite",
            agents=list(ALL_AGENTS),
            operator_alert=True,
            rationale="M-3 act: full 5-agent re-underwrite + operator alert.",
            used_fallback_table=False,
            agent_selection_model=None,
        )

    # --- M-2: LLM picker with floor fallback ------------------------------ #
    flags: list[str] = []
    raw: Optional[str] = None

    # Floor fallback when judge confidence is low (Section 4.5 Q2).
    if verdict.confidence < JUDGE_CONFIDENCE_FLOOR:
        flags.append(
            f"used_fallback:judge_conf_{verdict.confidence:.2f}_below_{JUDGE_CONFIDENCE_FLOOR}"
        )
        agents = fallback_agents_for_event(event.type)
        return RoutingDecision(
            action="partial_reunderwrite",
            agents=agents,
            operator_alert=False,
            rationale=(
                f"M-2 partial; judge confidence {verdict.confidence:.2f} below "
                f"{JUDGE_CONFIDENCE_FLOOR} floor — used event-type lookup."
            ),
            used_fallback_table=True,
            agent_selection_model=None,
            flags=flags,
        )

    if client is None:
        try:
            client = _build_default_client()
        except LLMUnavailableError:
            flags.append("used_fallback:llm_unavailable")
            agents = fallback_agents_for_event(event.type)
            return RoutingDecision(
                action="partial_reunderwrite",
                agents=agents,
                operator_alert=False,
                rationale=(
                    "M-2 partial; LLM picker unavailable — fell back to "
                    "event-type lookup table."
                ),
                used_fallback_table=True,
                agent_selection_model=None,
                flags=flags,
            )

    agents, rationale, raw = _call_picker(ticker, event, verdict, client)
    if agents is None:
        flags.append("used_fallback:picker_invalid_output")
        agents = fallback_agents_for_event(event.type)
        return RoutingDecision(
            action="partial_reunderwrite",
            agents=agents,
            operator_alert=False,
            rationale=(
                "M-2 partial; LLM picker output invalid — fell back to "
                "event-type lookup table."
            ),
            used_fallback_table=True,
            agent_selection_model=DEFAULT_MODEL,
            flags=flags,
            raw_response=raw,
        )

    return RoutingDecision(
        action="partial_reunderwrite",
        agents=agents,
        operator_alert=False,
        rationale=rationale or "M-2 partial; LLM picker selected agents.",
        used_fallback_table=False,
        agent_selection_model=DEFAULT_MODEL,
        flags=flags,
        raw_response=raw,
    )
