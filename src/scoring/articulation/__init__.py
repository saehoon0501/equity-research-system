"""Axis-A articulation scorer (WS-1, Phase 1 insight-quality enhancement).

Implements the ``src.scoring.contracts.ScoreProvider`` protocol for the
``axis_a`` block. Sub-metrics:

  - RAGAS faithfulness + answer-relevancy (LLM, cached, N=5 @ temp 0.7)
  - ALCE citation precision/recall       (DETERMINISTIC set-overlap)
  - VERISCORE long-form factuality        (LLM; replaces the old scorer)
  - UNION coherence                       (pinned local model)
  - G-Eval clarity                        (advisory only)

All LLM sub-metrics degrade to ``None`` (advisory) on failure; the
deterministic citation path has no LLM/network dependency. This package
imports the Phase-0 contracts (does NOT redefine them) and reuses the
self-consistency / cache / model-pin primitives by import.
"""

from __future__ import annotations

from .citation import CitationScore, compute_citation_pr, score_citation
from .clarity import ClarityScore, score_clarity
from .coherence import CoherenceScore, score_coherence
from .faithfulness import (
    ArticulationMetricError,
    FaithfulnessScore,
    score_faithfulness,
)
from .scorer import BLOCK_NAME, SCORER_VERSION, ArticulationScorer
from .veriscore import VeriScore, score_veriscore

__all__ = [
    "ArticulationScorer",
    "BLOCK_NAME",
    "SCORER_VERSION",
    "ArticulationMetricError",
    "CitationScore",
    "compute_citation_pr",
    "score_citation",
    "FaithfulnessScore",
    "score_faithfulness",
    "VeriScore",
    "score_veriscore",
    "CoherenceScore",
    "score_coherence",
    "ClarityScore",
    "score_clarity",
]
