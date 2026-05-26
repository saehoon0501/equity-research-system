"""Stage 1B — Additive equal-weight 4-criterion Tier-A composite.

Per spec Section 4.3 (lines 373-379)::

    Stage 1B (among Stage-1A survivors):
      - Founder/CEO duration >= 15 years           (L3-e Pattern #1, HIGH)
      - Per-share-value primary management metric  (L3-e Pattern #2, HIGH)
      - ROIIC > 15% sustained                       (L3-e Pattern #3, HIGH)
      - Pivot-creates-multi-bag (not original)      (L3-e Pattern #4, HIGH)
      Threshold: >=3 = A / 2 = WATCH / <=1 = REJECT
      LEI-style proportional re-weighting on missing data.

Equal-weight (0.25 each) is deliberate: per L3-e candidate-evaluation
checklist, all four are Tier-A signals and HIGH confidence; no empirical
basis (yet) for differential weighting at v0.1. v0.5+ may upgrade to
Brier-haircut weighting (Section 6.4).

LEI-style proportional re-weighting on missing data
---------------------------------------------------
The LEI / Conference Board Leading Economic Index treats missing
component values by *normalising remaining components to sum to the full
weight*: i.e., score = sum(present_values) / sum(present_weights). This
gives a proportional re-weight rather than imputing a default. We apply
this directly:

* score = sum(criterion_value for present criteria) / count(present)
* present_count must be >= 2 to compute a score; <2 -> REJECT (data too
  sparse for any meaningful Tier-A signal).
* The unweighted-equivalent threshold remains the *count* of HIGH
  criteria (>=3, =2, <=1), but is computed against present criteria
  only with a guard: if only 2-3 present and all pass, decision is
  WATCH (not A) to avoid false-promotion on sparse data. (This is
  the conservative interpretation of "raised conservatively" in
  Section 4.3.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import STAGE_OUTCOME_REJECT, STAGE_OUTCOME_TIER_A, STAGE_OUTCOME_WATCH


# Tier-A criteria per L3-e Section D + candidate-evaluation checklist.
TIER_A_CRITERIA = (
    "founder_ceo_duration_ge_15y",
    "per_share_value_primary_metric",
    "roiic_gt_15_sustained",
    "pivot_creates_multi_bag",
)

# Decision thresholds on count of HIGH criteria (Section 4.3)
TIER_A_THRESHOLD = 3
WATCH_THRESHOLD = 2

# Minimum present-criteria count for a non-REJECT decision on sparse data.
MIN_PRESENT_FOR_DECISION = 2


@dataclass
class TierAInput:
    """Per-criterion booleans (True=pass, False=fail, None=missing)."""

    founder_ceo_duration_ge_15y: Optional[bool] = None
    per_share_value_primary_metric: Optional[bool] = None
    roiic_gt_15_sustained: Optional[bool] = None
    pivot_creates_multi_bag: Optional[bool] = None
    evidence: dict = field(default_factory=dict)  # criterion -> quote/source


@dataclass
class Stage1BResult:
    """Stage 1B outcome + audit payload."""

    outcome: str  # STAGE_OUTCOME_TIER_A | STAGE_OUTCOME_WATCH | STAGE_OUTCOME_REJECT
    pass_count: int
    fail_count: int
    missing_count: int
    present_count: int
    proportional_score: float  # LEI-style: passes / present (0..1)
    criteria_pass: list
    criteria_fail: list
    criteria_missing: list
    sparse_data_demoted: bool
    reasons: list

    def to_audit_payload(self) -> dict:
        return {
            "stage": "stage_1b_tier_a_composite",
            "outcome": self.outcome,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "missing_count": self.missing_count,
            "present_count": self.present_count,
            "proportional_score": round(self.proportional_score, 4),
            "criteria_pass": list(self.criteria_pass),
            "criteria_fail": list(self.criteria_fail),
            "criteria_missing": list(self.criteria_missing),
            "sparse_data_demoted": self.sparse_data_demoted,
            "reasons": list(self.reasons),
        }


def evaluate(payload: TierAInput) -> Stage1BResult:
    """Run Stage 1B Tier-A 4-criterion composite.

    Section 4.3 thresholds with LEI-style proportional re-weighting on
    missing data and conservative demotion for sparse data.
    """
    passes: list = []
    fails: list = []
    missing: list = []

    for c in TIER_A_CRITERIA:
        v = getattr(payload, c)
        if v is True:
            passes.append(c)
        elif v is False:
            fails.append(c)
        else:
            missing.append(c)

    pass_count = len(passes)
    fail_count = len(fails)
    missing_count = len(missing)
    present_count = pass_count + fail_count

    reasons: list = []
    sparse_data_demoted = False

    proportional_score = 0.0 if present_count == 0 else pass_count / present_count

    if present_count < MIN_PRESENT_FOR_DECISION:
        reasons.append(
            f"present_criteria={present_count} < {MIN_PRESENT_FOR_DECISION} "
            f"(data too sparse) -> REJECT"
        )
        outcome = STAGE_OUTCOME_REJECT
    elif pass_count >= TIER_A_THRESHOLD:
        outcome = STAGE_OUTCOME_TIER_A
        reasons.append(
            f"pass_count={pass_count} >= {TIER_A_THRESHOLD} -> Tier-A"
        )
    elif pass_count == WATCH_THRESHOLD:
        outcome = STAGE_OUTCOME_WATCH
        reasons.append(f"pass_count={pass_count} == {WATCH_THRESHOLD} -> WATCH")
    else:
        outcome = STAGE_OUTCOME_REJECT
        reasons.append(f"pass_count={pass_count} <= 1 -> REJECT")

    # Conservative demotion: even at 3+ passes, if any criteria missing AND
    # present_count < 4, demote one tier (A -> WATCH; WATCH stays WATCH).
    if (
        outcome == STAGE_OUTCOME_TIER_A
        and missing_count > 0
        and present_count < len(TIER_A_CRITERIA)
    ):
        # Only A -> WATCH when sparse data has *not* been all-passes (which
        # would be a clean LEI re-weight). The trigger is: pass_count == 3
        # with one missing — too thin for Tier-A.
        if pass_count == TIER_A_THRESHOLD and present_count == TIER_A_THRESHOLD:
            outcome = STAGE_OUTCOME_WATCH
            sparse_data_demoted = True
            reasons.append(
                "conservative demotion: 3 passes but 1 criterion missing -> WATCH"
            )

    return Stage1BResult(
        outcome=outcome,
        pass_count=pass_count,
        fail_count=fail_count,
        missing_count=missing_count,
        present_count=present_count,
        proportional_score=proportional_score,
        criteria_pass=passes,
        criteria_fail=fails,
        criteria_missing=missing,
        sparse_data_demoted=sparse_data_demoted,
        reasons=reasons,
    )
