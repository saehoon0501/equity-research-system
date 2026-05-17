"""Stage 2 — Company-quality refinement (Section 7 PB#3).

Per spec Section 2.2 line 111-113::

    HIGH-quality flag if
        (founder >=10yr tenure if B-bin, >=5yr if B'-bin) AND
        (ROIIC > 15% sustained 5yr if B-bin) AND
        profitability-path-clear
    STANDARD flag otherwise

The flag is a *conviction multiplier* (Section 2.2 line 124), not a
mode-bin determinant. It is produced once we know which bin Stage 1
landed on (B, B', or C), since the founder-tenure threshold is
bin-conditional.

C-bin handling: the spec explicitly lists thresholds only for B and
B' bins, so for C-bin names the HIGH flag requires
``profitability-path-clear == True`` AND ``founder_tenure_years >= 5``
(treating C the same as B'); this is the conservative reading per
Phase 4 Q1 ("for C, profitability-path-clear is the gating question").

The function is *pure*: it takes the bin and a :class:`QualityFacts`
snapshot and returns a :class:`Stage2Result`. Missing data biases to
``STANDARD`` (the conservative default; HIGH-quality should require
*positive* evidence).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import MODE_B, MODE_B_PRIME, MODE_C, QUALITY_HIGH, QUALITY_STANDARD
from .adapters import QualityFacts


# Spec-fixed thresholds — Section 7 PB#3 / Section 2.2 line 112.
FOUNDER_TENURE_B_MIN_YEARS: float = 10.0
FOUNDER_TENURE_BPRIME_MIN_YEARS: float = 5.0
ROIIC_5YR_B_THRESHOLD: float = 0.15  # > 15% sustained 5yr


@dataclass(frozen=True)
class Stage2Result:
    """Output of the quality refinement stage.

    Attributes:
        flag: ``HIGH`` or ``STANDARD`` per Phase 4 Q1.
        bin_evaluated: The Stage 1 bin we refined within (B / B_prime / C).
        founder_tenure_passed: Did the founder-tenure threshold pass?
        roiic_passed: Did the ROIIC threshold pass? (B-bin only;
            non-applicable for B'/C, in which case this is True.)
        profitability_path_clear: Pass-through from input.
        rationale: Human-readable one-liner explaining the flag.
        facts_snapshot: The :class:`QualityFacts` we evaluated.
    """

    flag: str
    bin_evaluated: str
    founder_tenure_passed: bool
    roiic_passed: bool
    profitability_path_clear: bool
    rationale: str
    facts_snapshot: QualityFacts

    def to_audit_payload(self) -> dict:
        """Serialize for inclusion under ``mode_classifications.rule_outcomes``."""
        return {
            "flag": self.flag,
            "bin_evaluated": self.bin_evaluated,
            "founder_tenure_passed": self.founder_tenure_passed,
            "roiic_passed": self.roiic_passed,
            "profitability_path_clear": self.profitability_path_clear,
            "rationale": self.rationale,
            "facts": asdict(self.facts_snapshot),
            "thresholds": {
                "founder_tenure_b": FOUNDER_TENURE_B_MIN_YEARS,
                "founder_tenure_b_prime": FOUNDER_TENURE_BPRIME_MIN_YEARS,
                "roiic_5yr_b": ROIIC_5YR_B_THRESHOLD,
            },
        }


def _founder_threshold(bin_label: str) -> float:
    if bin_label == MODE_B:
        return FOUNDER_TENURE_B_MIN_YEARS
    # B' and C share the 5-year floor (conservative reading for C).
    return FOUNDER_TENURE_BPRIME_MIN_YEARS


def _eval_founder(bin_label: str, tenure: float | None) -> bool:
    if tenure is None:
        return False
    return tenure >= _founder_threshold(bin_label)


def _eval_roiic(bin_label: str, roiic: float | None) -> bool:
    """ROIIC clause is only required for B-bin per spec line 112.

    For B' and C the spec does not require the 15% ROIIC bar, so this
    returns True (clause non-applicable). Missing data on a B-bin name
    returns False (cannot prove sustained ROIIC).
    """
    if bin_label != MODE_B:
        return True
    if roiic is None:
        return False
    return roiic > ROIIC_5YR_B_THRESHOLD


def classify(bin_label: str, facts: QualityFacts) -> Stage2Result:
    """Run the Stage 2 quality refinement.

    Args:
        bin_label: Stage 1 winning bin (``B``, ``B_prime``, ``C``).
        facts: :class:`QualityFacts` snapshot.

    Returns:
        :class:`Stage2Result` with ``flag`` set to HIGH or STANDARD.
    """
    if bin_label not in (MODE_B, MODE_B_PRIME, MODE_C):
        raise ValueError(f"unknown bin: {bin_label!r}")

    founder_ok = _eval_founder(bin_label, facts.founder_tenure_years)
    roiic_ok = _eval_roiic(bin_label, facts.roiic_5yr_avg)
    path_ok = bool(facts.profitability_path_clear)

    is_high = founder_ok and roiic_ok and path_ok
    flag = QUALITY_HIGH if is_high else QUALITY_STANDARD

    if is_high:
        rationale = (
            f"HIGH: founder_tenure={facts.founder_tenure_years}y "
            f">= {_founder_threshold(bin_label)}y, ROIIC clause OK, "
            f"profitability-path-clear=True"
        )
    else:
        why = []
        if not founder_ok:
            why.append(
                f"founder_tenure={facts.founder_tenure_years} < "
                f"{_founder_threshold(bin_label)}y"
            )
        if not roiic_ok and bin_label == MODE_B:
            why.append(f"ROIIC_5yr={facts.roiic_5yr_avg} not > 15%")
        if not path_ok:
            why.append("profitability-path NOT clear")
        rationale = "STANDARD: " + "; ".join(why) if why else "STANDARD"

    return Stage2Result(
        flag=flag,
        bin_evaluated=bin_label,
        founder_tenure_passed=founder_ok,
        roiic_passed=roiic_ok,
        profitability_path_clear=path_ok,
        rationale=rationale,
        facts_snapshot=facts,
    )
