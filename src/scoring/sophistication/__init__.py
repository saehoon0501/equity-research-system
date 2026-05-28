"""WS-2 sophistication scorer (Axis B).

Public surface for the Axis-B scorer over an envelope's
``reasoning_trace[].rationale`` sentences. See ``scorer.py`` for the
contract behaviours (abstain / relative / novelty-AND-grounding /
degrade) and ``seams.py`` for the injection points that keep the scorer
runnable offline.
"""
from __future__ import annotations

from .metrics import (
    grounding_credit,
    novelty_anded_with_grounding,
    receval_proxy,
    roscoe_proxy,
)
from .scorer import BLOCK_NAME, MODE, SophisticationScorer, extract_rationales
from .seams import (
    BaselineStore,
    PerplexityModel,
    RationaleLM,
    StaticBaselineStore,
    UnavailablePerplexityModel,
)

__all__ = [
    "SophisticationScorer",
    "extract_rationales",
    "BLOCK_NAME",
    "MODE",
    "PerplexityModel",
    "RationaleLM",
    "BaselineStore",
    "UnavailablePerplexityModel",
    "StaticBaselineStore",
    "roscoe_proxy",
    "receval_proxy",
    "grounding_credit",
    "novelty_anded_with_grounding",
]
