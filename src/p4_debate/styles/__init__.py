"""Style personas for the 5-style debate.

Per v3 spec Section 2.3 lines 152-185 + L8 Section D.1. Each style has:

* a **locked persistent identity** (the system prompt is invariant per
  prompt-version; PMSupervisor cannot rewrite it);
* a **persona description** (Buffett/Klarman/Marks/etc. archetypes);
* what the style **prioritizes** (its concrete decision criteria);
* what the style **rejects** (its explicit non-negotiables).

The "locked persistent identity" is the L8 mitigation for inter-agent
sycophancy (L8 Section B finding 13): persistent identity prevents
"peacemaker collapse" during Phase C.
"""

from __future__ import annotations

from .growth import GROWTH_PERSONA
from .macro_regime import MACRO_REGIME_PERSONA
from .quality_moat import QUALITY_MOAT_PERSONA
from .quant_technical import QUANT_TECHNICAL_PERSONA
from .value import VALUE_PERSONA

# Single source-of-truth registry. The orchestrator iterates this map.
PERSONAS: dict[str, "StylePersona"] = {  # type: ignore[name-defined]
    "value": VALUE_PERSONA,
    "growth": GROWTH_PERSONA,
    "quality_moat": QUALITY_MOAT_PERSONA,
    "macro_regime": MACRO_REGIME_PERSONA,
    "quant_technical": QUANT_TECHNICAL_PERSONA,
}


__all__ = [
    "PERSONAS",
    "VALUE_PERSONA",
    "GROWTH_PERSONA",
    "QUALITY_MOAT_PERSONA",
    "MACRO_REGIME_PERSONA",
    "QUANT_TECHNICAL_PERSONA",
]
