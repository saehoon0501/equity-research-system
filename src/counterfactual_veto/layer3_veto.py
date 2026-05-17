"""Layer 3 — Counterfactual VETO authority (v3 spec Section 4.5 Q6).

Top-3 archetype-distribution rules:

    ≥2 SURVIVOR     → cut requires explicit operator override (BLOCKED auto-cut)
    ≥2 NON-SURVIVOR → cut proceeds per mode polarity (NOT_TRIGGERED)
    Mixed (e.g. 1S/1NS/1DS, or any spread) → operator review required

Veto operates ON TOP of mode polarity. Even Mode-C "cut-fast" names get
blocked when their structural features match historical SURVIVOR cases —
this is the PLTR-2022 problem (Section 7.3a Walkthrough #1).

DILUTED-SURVIVOR is treated as its own bucket — it is neither a clean
SURVIVOR vote (the bagholder dilutions are how survivors lose alpha) nor a
NON-SURVIVOR (the equity didn't go to zero). For the VETO rule it counts
as SURVIVOR-leaning (the company survived; only the equity got diluted).
This matches Section 4.4 catalog status: SURVIVOR + DILUTED-SURVIVOR are
both pulled into the active retrieval pool, only NON-SURVIVOR is the
"cut was right" signal.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 4.5 Q6 Layer 3,
           Section 4.4 (catalog status + retrieval scoring),
           Section 7.3a Walkthrough #1 (PLTR-2022).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .feature_extractor import CandidateFeatures
from .retrieval import (
    CatalogCase,
    RetrievalMatch,
    archetype_distribution,
    retrieve_top_3,
)


VetoStatusLabel = Literal[
    "not_triggered",
    "blocked",
    "operator_override_required",
    "mixed_review_required",
]


@dataclass(frozen=True)
class VetoStatus:
    """Outcome of the Layer 3 VETO evaluation.

    Attributes:
        veto_invoked:           True for any non-'not_triggered' status.
        status:                 One of VetoStatusLabel values.
        archetype_distribution: ``{outcome: count}`` over top-3 matches.
        top_3_matches:          List of RetrievalMatch (case + similarity).
        rationale:              Human-readable summary for audit chain.
    """

    veto_invoked: bool
    status: VetoStatusLabel
    archetype_distribution: dict[str, int]
    top_3_matches: list[RetrievalMatch] = field(default_factory=list)
    rationale: str = ""


def _classify_distribution(dist: dict[str, int]) -> tuple[VetoStatusLabel, str]:
    """Apply the Section 4.5 Q6 Layer 3 archetype-count rule.

    Survivor-leaning count = SURVIVOR + DILUTED-SURVIVOR. The veto fires when
    survivor-leaning ≥2 (cut blocked, operator override required) or when
    NON-SURVIVOR ≥2 (cut proceeds; veto does not interfere). Anything else
    is mixed — operator review required.
    """
    survivor_lean = dist.get("SURVIVOR", 0) + dist.get("DILUTED-SURVIVOR", 0)
    non_survivor = dist.get("NON-SURVIVOR", 0)

    if survivor_lean >= 2:
        return (
            "operator_override_required",
            f"≥2 SURVIVOR-leaning matches in top-3 "
            f"(SURVIVOR+DILUTED-SURVIVOR={survivor_lean}); "
            f"cut blocked pending explicit operator override",
        )
    if non_survivor >= 2:
        return (
            "not_triggered",
            f"≥2 NON-SURVIVOR matches in top-3 (n={non_survivor}); "
            f"cut proceeds per mode polarity",
        )
    return (
        "mixed_review_required",
        f"mixed archetype distribution {dict(dist)}; operator review required",
    )


def evaluate_veto(
    *,
    candidate: CandidateFeatures,
    catalog: list[CatalogCase],
) -> VetoStatus:
    """Run Layer 3 VETO authority for a candidate at peak-pain trigger.

    Args:
        candidate: Materialized features from feature_extractor.
        catalog:   Pre-loaded peak-pain archetype catalog (active pool).

    Returns:
        VetoStatus carrying the veto label, archetype distribution, and the
        top-3 retrieval result. Fewer than 3 active matches degrades
        gracefully — veto status reports the actual top-K and applies the
        same rule.

    Raises:
        ValueError: If ``catalog`` is empty. A degenerate empty catalog
            cannot produce a meaningful veto signal; callers must surface
            this as a system event rather than silently passing.
    """
    if not catalog:
        raise ValueError(
            "evaluate_veto requires a non-empty catalog; received zero "
            "active archetype cases. Surface as system_errors / M-2 event."
        )
    top_3 = retrieve_top_3(
        candidate_sector=candidate.sector,
        candidate_universal_core=candidate.universal_core,
        candidate_sector_extensions=candidate.sector_extensions,
        catalog=catalog,
        k=3,
    )
    dist = archetype_distribution(top_3)
    status, rationale = _classify_distribution(dist)
    veto_invoked = status != "not_triggered"
    return VetoStatus(
        veto_invoked=veto_invoked,
        status=status,
        archetype_distribution=dist,
        top_3_matches=top_3,
        rationale=rationale,
    )


def is_survivor_dominant(dist: dict[str, int]) -> bool:
    """Convenience: True iff distribution is SURVIVOR-leaning ≥2 (veto-blocking).

    Used by orchestrator.py to decide whether to fire the M-3 unread_alerts
    row per task brief.
    """
    return (dist.get("SURVIVOR", 0) + dist.get("DILUTED-SURVIVOR", 0)) >= 2
