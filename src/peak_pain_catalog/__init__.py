"""peak_pain_catalog — 3-LLM iterative-consensus extraction pipeline.

Validates the ~160-case peak-pain archetype catalog at
`.claude/references/empirical/peak-pain-archetypes/catalog-v0.1.md` per the
v3 spec (Section 4.4 + Phase 4 Q4 + Section 5 Q3 + Section 6 Q6 PB#7).

Pipeline shape:
    catalog-v0.1.md
        → parser.parse_catalog()           # markdown → list[CaseRecord]
        → extractor.extract_features()     # single LLM call → ExtractionResult
        → consensus.run_consensus()        # 3 LLMs × ≤5 iterations → ConsensusResult
        → persistence.write_validated_case()  # → peak_pain_archetypes row + HMAC

Operator entry points (see cli.py):
    python -m peak_pain_catalog.cli priority-run
    python -m peak_pain_catalog.cli validate-case --case-id NVDA-2008

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
"""

from __future__ import annotations

from src.peak_pain_catalog.consensus import (
    ConsensusResult,
    FeatureConsensus,
    run_consensus,
)
from src.peak_pain_catalog.extractor import (
    ExtractedFeature,
    ExtractionResult,
    extract_features,
)
from src.peak_pain_catalog.feature_typing import (
    FEATURE_TYPES,
    ORDINAL_ORDERS,
    UNIVERSAL_CORE,
    FeatureKind,
    is_within_one_step,
)
from src.peak_pain_catalog.parser import CaseRecord, parse_catalog
from src.peak_pain_catalog.persistence import write_validated_case

__all__ = [
    "CaseRecord",
    "ConsensusResult",
    "ExtractedFeature",
    "ExtractionResult",
    "FEATURE_TYPES",
    "FeatureConsensus",
    "FeatureKind",
    "ORDINAL_ORDERS",
    "UNIVERSAL_CORE",
    "extract_features",
    "is_within_one_step",
    "parse_catalog",
    "run_consensus",
    "write_validated_case",
]
