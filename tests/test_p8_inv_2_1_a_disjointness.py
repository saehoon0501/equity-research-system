"""INV-2.1-A: summary_code enum ⊥ tactical_disposition enum.

Per Section 2.1 v5-final consensus doc at
docs/superpowers/consensus/2026-05-21-section2.1-label-vocabulary.md.

The canonical summary_code enum (BUY/HOLD/TRIM/SELL — pm-supervisor's domain) and
the tactical_disposition enum (BUY-HIGH/BUY-MED/HOLD/AVOID — overlay's domain) are
deliberately DISJOINT. Section 2.1 v5 locked this invariant after the v2 reviewer
caught that "BUY" semantic overload between the two fields creates calibration
drift (operator pattern-matches "BUY = MEDIUM conviction" given empirical 83%
MEDIUM base rate).
"""

from src.p8_tactical_overlay.contracts import TacticalDisposition

CANONICAL_SUMMARY_CODE = {"BUY", "HOLD", "TRIM", "SELL"}


def test_inv_2_1_a_disjointness():
    """summary_code ∩ tactical_disposition = ∅."""
    tactical_disp = set(TacticalDisposition.__args__)
    intersection = CANONICAL_SUMMARY_CODE & tactical_disp
    # HOLD is the ONE shared label by design — semantic is identical across both
    # fields and operator interpretation does not drift. BUY/TRIM/SELL must NOT
    # appear in tactical_disposition (those are pm-supervisor's domain).
    assert intersection == {"HOLD"}, (
        f"INV-2.1-A violation: unexpected enum overlap {intersection - {'HOLD'}}"
    )


def test_canonical_buy_not_in_tactical_disposition():
    """Section 2.1 v5: BUY-HIGH and BUY-MED are tactical-only; canonical BUY is summary_code-only."""
    tactical_disp = set(TacticalDisposition.__args__)
    assert "BUY" not in tactical_disp
    assert "TRIM" not in tactical_disp
    assert "SELL" not in tactical_disp


def test_tactical_buy_variants_present():
    """v5-final: hyphenated BUY-HIGH and BUY-MED are the tactical-disposition BUY variants."""
    tactical_disp = set(TacticalDisposition.__args__)
    assert "BUY-HIGH" in tactical_disp
    assert "BUY-MED" in tactical_disp


def test_avoid_only_in_tactical_disposition():
    """AVOID is tactical-only (LOW-conviction discipline guard); not a summary_code."""
    tactical_disp = set(TacticalDisposition.__args__)
    assert "AVOID" in tactical_disp
    assert "AVOID" not in CANONICAL_SUMMARY_CODE
