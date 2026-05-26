"""P3 mechanical scorer package — name-discovery hybrid scorer.

Critical-path component #3 in v0.1. Implements the **3-stage hybrid scorer**
described in
``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.3 (L3 / P3 — successful-company patterns + counterfactuals).

Architecture (Section 4.3, Section 5 Q1 lock)::

    Stage 1A  Multiplicative knockout       (any fail -> REJECT)
              - L3-e Pattern #8/#21 fraud signature 3+/6
              - L3-e Pattern #20 era-fit binary
              - Missing data flagged conservatively

    Stage 1B  Additive equal-weight 4-criterion Tier-A composite
              - L3-e Pattern #1  founder/CEO duration >= 15y
              - L3-e Pattern #2  per-share-value primary metric
              - L3-e Pattern #3  ROIIC > 15% sustained
              - L3-e Pattern #4  pivot-creates-multi-bag (not original product)
              - >=3 = A / 2 = WATCH / <=1 = REJECT
              - Missing data: LEI-style proportional re-weighting

    Stage 2   LLM rubric — INFORMATION-ISOLATED from Stage 1
              - Per-pattern single-attribute call (anchoring-bias mitigation)
              - 3-level ordinal {LOW, MEDIUM, HIGH} -> {0.0, 0.5, 1.0}
              - Forced JSON; verbatim evidence required (no quote -> LOW)
              - Self-consistency N=5 at temp=0.7; median rating
              - saw_rule_output=False enforced in audit

    Stage 3   Deterministic linter (cross-checks LLM vs Stage-1-known facts)
              - Contradictions, HIGH without evidence, round-number defaulting,
                position bias, verbosity
              - Routes to operator review; logs to S2 ledger

Outputs are persisted to the ``audit_provenance`` table (one row per stage,
``stage='stage_1_mechanical'`` for both 1A+1B; debate stage is downstream)
and a final synthesised score returned by the orchestrator. Stage 2 LLM
calls explicitly suppress all knowledge of Stage 1 outputs to mitigate
anchoring (Section 5 Q1 lock + L8 finding).

Public API::

    from p3_mechanical_scorer.orchestrator import score_ticker, P3Outcome

Module map::

    stage1a_multiplicative_knockout - Fraud-signature + era-fit knockouts
    stage1b_tier_a_composite        - Tier-A 4-criterion additive
    stage2_llm_rubric               - Per-pattern LLM rubric (info-isolated)
    stage3_linter                   - Deterministic LLM-output linter
    orchestrator                    - End-to-end pipeline + audit persistence
    cli                             - python -m p3_mechanical_scorer.cli score
"""

from __future__ import annotations

# Stage outcomes (mechanical)
STAGE_OUTCOME_REJECT = "REJECT"
STAGE_OUTCOME_WATCH = "WATCH"
STAGE_OUTCOME_PROCEED = "PROCEED"
STAGE_OUTCOME_TIER_A = "A"

# Final P3 decisions (orchestrator)
DECISION_PROCEED = "PROCEED"
DECISION_WATCH = "WATCH"
DECISION_PASS = "PASS"

# LLM rating ordinal map (Section 4.3)
RATING_LOW = "LOW"
RATING_MEDIUM = "MEDIUM"
RATING_HIGH = "HIGH"
RATING_TO_SCORE = {RATING_LOW: 0.0, RATING_MEDIUM: 0.5, RATING_HIGH: 1.0}

# Versioning — bumped when prompts / rules / parameters change
RULE_ENGINE_VERSION = "p3-mechanical-v0.1"
LLM_PROMPT_VERSION = "p3-stage2-rubric-v0.1"
LINTER_VERSION = "p3-stage3-linter-v0.1"

# Default models (Section 4.5 model constraint: Sonnet or Opus only — NO Haiku)
DEFAULT_MODEL = "claude-sonnet-4-5"
HIGH_STAKES_MODEL = "claude-opus-4-5"

# Self-consistency settings per Section 4.3
SELF_CONSISTENCY_N = 5
SELF_CONSISTENCY_TEMP = 0.7

__all__ = [
    "STAGE_OUTCOME_REJECT",
    "STAGE_OUTCOME_WATCH",
    "STAGE_OUTCOME_PROCEED",
    "STAGE_OUTCOME_TIER_A",
    "DECISION_PROCEED",
    "DECISION_WATCH",
    "DECISION_PASS",
    "RATING_LOW",
    "RATING_MEDIUM",
    "RATING_HIGH",
    "RATING_TO_SCORE",
    "RULE_ENGINE_VERSION",
    "LLM_PROMPT_VERSION",
    "LINTER_VERSION",
    "DEFAULT_MODEL",
    "HIGH_STAKES_MODEL",
    "SELF_CONSISTENCY_N",
    "SELF_CONSISTENCY_TEMP",
]
