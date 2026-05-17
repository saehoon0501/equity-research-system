"""Anchor-drift detection package (v3 Section 6 Q5).

Implements the **3 independent anchor-drift channels** from the v3 spec
``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.5 Q5 (lines 530-536):

  Channel 1  Pillar drift          (LLM-diff of HMAC-signed original
                                    thesis pillars vs current operating
                                    thesis; trigger if drift score > 0.25)
  Channel 2  Outcome divergence    (quarterly earnings actuals vs
                                    HMAC-signed scenario_A_base_projections;
                                    trigger if any of {revenue, gross
                                    margin, FCF} deviates > 25%)
  Channel 3  Periodic forced       (calendar floor: B 180d, B' 120d,
             re-read                C 60d; operator must explicitly
                                    acknowledge or revise)

When ANY channel triggers, the operator MUST choose one of:
  - Reaffirm
  - Revise-with-rationale (verbatim citation required)
  - Cut

The no-op default is BLOCKED. The orchestrator writes one row per
(ticker, check_date) into ``anchor_drift_checks`` (010_v3_drift_detection.sql).

LLM model selection (Section 6 Q5 + Phase 4):
  - Channel 1 diff: Sonnet (structured comparison, not contestable).
  - Channels 2 + 3: pure deterministic / quantitative — no LLM.

Public API:

    from anchor_drift.orchestrator import run_anchor_drift_check
    from anchor_drift.hmac_verify import verify_pillars_hmac
"""

from __future__ import annotations

# Trigger thresholds (Section 4.5 Q5).
PILLAR_DRIFT_THRESHOLD: float = 0.25
OUTCOME_DEVIATION_THRESHOLD: float = 0.25  # 25%

# Calendar floor (days) — matches Section 4.5 Q4 pre-mortem cadence.
CADENCE_DAYS_BY_MODE: dict[str, int] = {
    "B": 180,
    "B_prime": 120,
    "C": 60,
}

# Operator decision values (mirror DB CHECK constraint in
# 010_v3_drift_detection.sql).
DECISION_REAFFIRM: str = "reaffirm"
DECISION_REVISE: str = "revise_with_rationale"
DECISION_CUT: str = "cut"
DECISION_PENDING: str = "pending"

# LLM model used for Channel 1 (structured diff — Sonnet per Section 6 Q5).
CHANNEL_1_LLM_MODEL: str = "claude-sonnet-4-5"

__all__ = [
    "PILLAR_DRIFT_THRESHOLD",
    "OUTCOME_DEVIATION_THRESHOLD",
    "CADENCE_DAYS_BY_MODE",
    "DECISION_REAFFIRM",
    "DECISION_REVISE",
    "DECISION_CUT",
    "DECISION_PENDING",
    "CHANNEL_1_LLM_MODEL",
]
