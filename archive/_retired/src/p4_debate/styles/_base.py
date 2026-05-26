"""Shared dataclass for style personas.

Per v3 spec Section 2.3. Each style locks its identity at module-import
time; the locked identity is what gets passed as ``system`` to the
Anthropic SDK. Phase C negotiation rounds re-use the SAME locked identity
(L8 finding 13 — persistent identity prevents sycophancy).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StylePersona:
    """Immutable persona definition for one of the 5 debate styles.

    Frozen: any modification is an explicit module-replacement, which
    surfaces in version control review (per Section 2.4 #2 — "Phase C
    cannot modify Phase B locks" extends to: nothing modifies the persona
    once committed).
    """

    style_id: str
    """Stable id; one of ``ALL_STYLES`` from ``p4_debate``."""

    display_name: str
    """Human-facing name, e.g. ``Value`` / ``Quality / Moat``."""

    archetypes: tuple[str, ...]
    """Practitioner archetypes the persona embodies (Buffett, Marks, ...)."""

    core_question: str
    """The single question this style is built to answer."""

    prioritizes: tuple[str, ...]
    """What the style weights heavily."""

    rejects: tuple[str, ...]
    """What the style refuses to be persuaded by — the non-negotiable
    'won't budge' list. This is what makes the agent persistent under
    Phase C cross-pressure (L8 finding 13)."""

    system_prompt: str
    """Full locked system prompt sent to the LLM. Includes identity +
    prioritization + rejection list + output discipline."""
