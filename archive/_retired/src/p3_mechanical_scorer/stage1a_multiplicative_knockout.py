"""Stage 1A — Multiplicative knockout (any fail -> REJECT).

Per spec Section 4.3 (lines 369-372)::

    - Fraud signature 3+/6 check
        (charismatic CEO + board lacks domain + novel accounting +
         secrecy + dismissed bear research + related-party transactions)
    - Era-fit binary check (right-thing-right-decade)
    - Missing data = flag raised conservatively

Source patterns:

* L3-e Pattern #8 (HIGH confidence) and Pattern #21 (FTX reinforcement) —
  fraud signature is sector-invariant across 25-year span (Theranos,
  Enron, Valeant, WeWork, FTX). Any 3+ of the 6 components = REJECT.
* L3-e Pattern #20 (HIGH for principle, MEDIUM for forward application)
  + Pattern #24 refinement (Coinbase test) — era-fit applies to
  companies that *structurally capture* the secular shift, not to
  companies that merely *trade exposure to* it.

Conservative-on-missing-data policy
-----------------------------------
The spec ("Missing data = flag raised conservatively") is interpreted as:

* Fraud-signature components: missing data on a component is treated as
  a soft positive (component flagged but with ``data_missing=True``);
  these soft-positives do NOT count toward the 3+/6 threshold on their
  own, but their presence raises ``data_quality='degraded'`` and is
  surfaced to Stage 3 / operator. Rationale: fraud detection should not
  fail-open on absence of evidence; but it also should not auto-reject
  on absence (which would block legitimate names with sparse coverage).
* Era-fit: missing data => ``era_fit=None`` => treated as REJECT for
  Stage 1A purposes (per "raised conservatively"); operator can override
  via the audit-trail re-run.

The fail-loud bias is intentional: knockout stages are meant to filter
hard. False-rejects are recoverable (operator override / re-run); false-
accepts here would propagate to Stage 1B/2/3 and contaminate downstream
debate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import STAGE_OUTCOME_PROCEED, STAGE_OUTCOME_REJECT


# The six fraud-signature components per L3-e #8 / #21.
FRAUD_COMPONENTS = (
    "charismatic_ceo_with_mystique",
    "board_lacks_domain_or_co_opted",
    "novel_accounting_or_metrics",
    "secrecy_under_trade_secret_cover",
    "dismissed_bear_research",
    "related_party_transactions",
)

FRAUD_THRESHOLD = 3  # 3+/6 = REJECT per Section 4.3


@dataclass
class FraudSignatureInput:
    """Per-component booleans + optional evidence quotes.

    Each field is Optional[bool]: True=present, False=absent, None=unknown.
    Unknown is treated as conservative-flagged (see module docstring).
    """

    charismatic_ceo_with_mystique: Optional[bool] = None
    board_lacks_domain_or_co_opted: Optional[bool] = None
    novel_accounting_or_metrics: Optional[bool] = None
    secrecy_under_trade_secret_cover: Optional[bool] = None
    dismissed_bear_research: Optional[bool] = None
    related_party_transactions: Optional[bool] = None
    evidence: dict = field(default_factory=dict)  # component -> quote(s)


@dataclass
class EraFitInput:
    """Era-fit binary input.

    Per L3-e Pattern #20/#24:

    * ``era_fit=True``  — company structurally captures secular shift
                          (e.g., NVDA-CUDA-AI, AMZN-AWS-cloud).
    * ``era_fit=False`` — wrong-decade-for-thesis (Pets.com analogue) OR
                          trades exposure to the shift without capturing
                          it structurally (COIN-as-Bitcoin-proxy).
    * ``era_fit=None``  — insufficient evidence; treated as REJECT.
    """

    era_fit: Optional[bool] = None
    rationale: Optional[str] = None
    evidence_quote: Optional[str] = None


@dataclass
class Stage1AResult:
    """Stage 1A outcome with full audit payload."""

    outcome: str  # STAGE_OUTCOME_REJECT | STAGE_OUTCOME_PROCEED
    fraud_signature_count: int
    fraud_threshold: int
    fraud_components_flagged: list
    fraud_components_unknown: list
    era_fit_pass: Optional[bool]
    reasons: list
    data_quality: str  # "complete" | "degraded"

    def to_audit_payload(self) -> dict:
        """JSON-serialisable dict for audit_provenance.drill_payload."""
        return {
            "stage": "stage_1a_multiplicative_knockout",
            "outcome": self.outcome,
            "fraud_signature": {
                "count": self.fraud_signature_count,
                "threshold": self.fraud_threshold,
                "components_flagged": list(self.fraud_components_flagged),
                "components_unknown": list(self.fraud_components_unknown),
            },
            "era_fit_pass": self.era_fit_pass,
            "reasons": list(self.reasons),
            "data_quality": self.data_quality,
        }


def _count_fraud_signature(payload: FraudSignatureInput) -> tuple[int, list, list]:
    """Return (definite_count, flagged_components, unknown_components)."""
    flagged: list = []
    unknown: list = []
    for c in FRAUD_COMPONENTS:
        v = getattr(payload, c)
        if v is True:
            flagged.append(c)
        elif v is None:
            unknown.append(c)
    return len(flagged), flagged, unknown


def evaluate(
    fraud: FraudSignatureInput,
    era_fit: EraFitInput,
) -> Stage1AResult:
    """Run Stage 1A multiplicative knockout.

    Per Section 4.3: any single fail -> REJECT.
    """
    reasons: list = []
    count, flagged, unknown = _count_fraud_signature(fraud)
    data_quality = "complete" if not unknown else "degraded"

    fraud_fail = count >= FRAUD_THRESHOLD
    if fraud_fail:
        reasons.append(
            f"fraud_signature {count}/{len(FRAUD_COMPONENTS)} >= "
            f"threshold {FRAUD_THRESHOLD} (components={flagged})"
        )

    era_fail = era_fit.era_fit is not True  # None or False both fail
    if era_fail:
        if era_fit.era_fit is None:
            reasons.append("era_fit unknown (data missing) -> conservative REJECT")
        else:
            reasons.append("era_fit=False (wrong-decade or non-structural capture)")

    outcome = STAGE_OUTCOME_REJECT if (fraud_fail or era_fail) else STAGE_OUTCOME_PROCEED

    return Stage1AResult(
        outcome=outcome,
        fraud_signature_count=count,
        fraud_threshold=FRAUD_THRESHOLD,
        fraud_components_flagged=flagged,
        fraud_components_unknown=unknown,
        era_fit_pass=era_fit.era_fit,
        reasons=reasons,
        data_quality=data_quality,
    )
