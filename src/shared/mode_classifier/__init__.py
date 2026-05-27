"""Mode classifier package for the v3 equity-research system.

Critical-path component #2 in v0.1. Implements the **layered B / B' / C
mode-classification architecture** described in
`docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
Section 2.2 (lines 95-130) — three stages reconciling the original
Section 1 Item 1 market-structural rule with the Section 7 PB#3
quality refinement and Phase 4 Q1 layered architecture:

  Stage 1  Market-structural filter  (mechanical rule on cap/vol/profit/growth)
  Stage 2  Company-quality refinement (HIGH / STANDARD flag on founder/ROIIC)
  Stage 3  Overlap detection + LLM tie-breaker (only when Stage 1 ambiguous)

Outputs are persisted to the `mode_classifications` table per
`db/migrations/008_v3_recommendations.sql`. The package is name-by-name —
cold-start handling lives in the S0 sidecar (out of scope here), and the
pre-mortem trigger on reclassification is dispatched separately.

Public API:

    from mode_classifier.orchestrator import classify_ticker
    from mode_classifier.recheck import recheck_ticker, recheck_all

Module map:

    stage1_market_structural  - Section 1 Item 1 rule
    stage2_company_quality    - Section 7 PB#3 quality refinement
    stage3_overlap_tiebreaker - LLM tie-breaker with N=5 self-consistency
    orchestrator              - end-to-end pipeline; persistence
    recheck                   - quarterly per-name re-classification (Phase 4 Q5)
    cli                       - command-line entry points
    adapters                  - data-source Protocols + default MCP adapter

References:
    docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
        Section 2.2  - layered architecture; mode definitions
        Section 7    - PB#3 (quality refinement) + Q1-Q4 (layered classifier)
        Phase 4 Q1   - layered architecture reconciliation
        Phase 4 Q5   - quarterly per-name re-classification
"""

from __future__ import annotations

__all__ = [
    "MODE_B",
    "MODE_B_PRIME",
    "MODE_C",
    "QUALITY_HIGH",
    "QUALITY_STANDARD",
    "METHOD_RULE",
    "METHOD_LLM",
    "RECHECK_CONFIRMED",
    "RECHECK_PENDING",
    "RECHECK_PROPOSED",
]

# Mode bins (mirror DB CHECK constraint in 008_v3_recommendations.sql).
MODE_B: str = "B"
MODE_B_PRIME: str = "B_prime"
MODE_C: str = "C"

# Company-quality flag per Phase 4 Q1.
QUALITY_HIGH: str = "HIGH"
QUALITY_STANDARD: str = "STANDARD"

# Classification method (rule-clean vs LLM tie-breaker).
METHOD_RULE: str = "rule"
METHOD_LLM: str = "llm_tiebreaker"

# Recheck workflow states (Phase 4 Q5).
RECHECK_CONFIRMED: str = "confirmed"
RECHECK_PENDING: str = "pending_review"
RECHECK_PROPOSED: str = "reclassification_proposed"
