"""NVDA-2023 launch walkthrough reproducer (Section 7.3a #2).

Validates the Phase 4 Q2 conviction-rollup HIGH-gate against the canonical
NVDA-2023 clean-BUY scenario:
  * Mode B' rule_clean=True
  * Debate consensus 5/5 ADD
  * Counterfactual top-3 SURVIVOR-dominant (NVDA-2008 + 2 cross-sector
    SURVIVORs from the realistic 17-case catalog)
  * Anchor-drift 0 channels triggered
  * Catalog HMAC verified at load
  * No cold-start cap (post day-90)

Asserts the rollup returns ``HIGH``. This is the inverse-asymmetry foil to
PLTR-2022: a SURVIVOR-dominant retrieval must CONFIRM HIGH BUY, not block.

Reproduces ``docs/superpowers/launch-walkthroughs/nvda-2023.md``.
"""

from __future__ import annotations

import pytest

from src.counterfactual_veto.feature_extractor import CandidateFeatures
from src.counterfactual_veto.retrieval import retrieve_top_3, archetype_distribution
from src.p7_recommendation_emitter.conviction_rollup import (
    CONVICTION_HIGH,
    ConvictionInputs,
    roll_up_conviction,
)
from tests.fixtures.realistic_catalog import build_realistic_catalog


@pytest.fixture
def nvda_2023_candidate() -> CandidateFeatures:
    """NVDA at 2023-05-24 post-Q1 earnings — clean BUY-side SURVIVOR shape."""
    return CandidateFeatures(
        ticker="NVDA",
        sector="semis_hardware",
        extraction_date="2023-05-24",
        universal_core={
            "founder_insider_stake_direction": "increasing",
            "cash_runway": ">24mo",
            "founder_in_place": "yes",
            "margin_trajectory": "improving",
            "revenue_trajectory": "growing",
            "industry_tailwind": "intact",
        },
        sector_extensions={
            "moat_state": "intact",
            "cycle_state": "cyclical-trough",
            "customer_concentration": "moderate",
        },
        consensus={f: "HIGH" for f in [
            "founder_insider_stake_direction",
            "cash_runway",
            "founder_in_place",
            "margin_trajectory",
            "revenue_trajectory",
            "industry_tailwind",
            "moat_state",
            "cycle_state",
            "customer_concentration",
        ]},
    )


class TestNvda2023ConvictionRollup:
    """Section 7.3a #2 — the BUY-side conviction-rollup HIGH-gate."""

    def test_top_3_is_survivor_dominant_against_realistic_catalog(
        self, nvda_2023_candidate: CandidateFeatures
    ) -> None:
        """Earned SURVIVOR top-3, not hand-picked. Same-sector NVDA-2008 leads."""
        catalog = build_realistic_catalog()
        top = retrieve_top_3(
            candidate_sector=nvda_2023_candidate.sector,
            candidate_universal_core=nvda_2023_candidate.universal_core,
            candidate_sector_extensions=nvda_2023_candidate.sector_extensions,
            catalog=catalog,
            k=3,
        )
        case_ids = [m.case.case_id for m in top]
        # Top-3 is SURVIVOR-leaning (≥2 of 3).
        survivor_lean = sum(
            1 for m in top if m.case.outcome in ("SURVIVOR", "DILUTED-SURVIVOR")
        )
        assert survivor_lean >= 2, f"expected ≥2 SURVIVOR-leaning, got {case_ids}"
        # Same-sector match (NVDA-2008) must be present and rank highest.
        sims = {m.case.case_id: m.similarity for m in top}
        assert "NVDA-2008" in sims, f"NVDA-2008 (same-sector match) missing from {case_ids}"
        assert sims["NVDA-2008"] == max(sims.values())

    def test_clean_buy_produces_HIGH_conviction(
        self, nvda_2023_candidate: CandidateFeatures
    ) -> None:
        """All 5 HIGH-gate conditions satisfied → bucket=HIGH."""
        catalog = build_realistic_catalog()
        top = retrieve_top_3(
            candidate_sector=nvda_2023_candidate.sector,
            candidate_universal_core=nvda_2023_candidate.universal_core,
            candidate_sector_extensions=nvda_2023_candidate.sector_extensions,
            catalog=catalog,
            k=3,
        )
        dist = archetype_distribution(top)
        # Translate retrieval archetypes ('SURVIVOR' / 'DILUTED-SURVIVOR' /
        # 'NON-SURVIVOR') into the rollup's flat 'SURVIVOR' / 'NON_SURVIVOR'
        # vocabulary. DILUTED-SURVIVOR counts as SURVIVOR-leaning.
        rollup_top_3: list[str] = []
        for m in top:
            if m.case.outcome in ("SURVIVOR", "DILUTED-SURVIVOR"):
                rollup_top_3.append("SURVIVOR")
            else:
                rollup_top_3.append("NON_SURVIVOR")

        result = roll_up_conviction(
            ConvictionInputs(
                debate_add_count=5,  # 5/5 ADD per walkthrough
                kills_fired=0,  # no kill criteria fired (BUY-side)
                counterfactual_top_3=rollup_top_3,
                anchor_drift_channels_triggered=0,
                debate_total=5,
            )
        )
        assert result.bucket == CONVICTION_HIGH, (
            f"expected HIGH, got {result.bucket}; "
            f"top_3={rollup_top_3}, dist={dist}"
        )
        assert "HIGH gate" in result.breakdown["rolled_up_via"]

    def test_4_of_5_ADD_still_qualifies_HIGH(
        self, nvda_2023_candidate: CandidateFeatures
    ) -> None:
        """4/5 ADD is the spec lower bound for HIGH (≥4); 4 must pass."""
        catalog = build_realistic_catalog()
        top = retrieve_top_3(
            candidate_sector=nvda_2023_candidate.sector,
            candidate_universal_core=nvda_2023_candidate.universal_core,
            candidate_sector_extensions=nvda_2023_candidate.sector_extensions,
            catalog=catalog,
            k=3,
        )
        rollup_top_3 = [
            "SURVIVOR" if m.case.outcome in ("SURVIVOR", "DILUTED-SURVIVOR")
            else "NON_SURVIVOR"
            for m in top
        ]
        result = roll_up_conviction(
            ConvictionInputs(
                debate_add_count=4,
                kills_fired=0,
                counterfactual_top_3=rollup_top_3,
                anchor_drift_channels_triggered=0,
            )
        )
        assert result.bucket == CONVICTION_HIGH

    def test_3_of_5_ADD_demotes_to_MEDIUM(
        self, nvda_2023_candidate: CandidateFeatures
    ) -> None:
        """3/5 ADD trips MEDIUM rule even with SURVIVOR-dominant top-3."""
        catalog = build_realistic_catalog()
        top = retrieve_top_3(
            candidate_sector=nvda_2023_candidate.sector,
            candidate_universal_core=nvda_2023_candidate.universal_core,
            candidate_sector_extensions=nvda_2023_candidate.sector_extensions,
            catalog=catalog,
            k=3,
        )
        rollup_top_3 = [
            "SURVIVOR" if m.case.outcome in ("SURVIVOR", "DILUTED-SURVIVOR")
            else "NON_SURVIVOR"
            for m in top
        ]
        result = roll_up_conviction(
            ConvictionInputs(
                debate_add_count=3,
                kills_fired=0,
                counterfactual_top_3=rollup_top_3,
                anchor_drift_channels_triggered=0,
            )
        )
        assert result.bucket == "MEDIUM"

    def test_anchor_drift_2_channels_demotes_to_MEDIUM(
        self, nvda_2023_candidate: CandidateFeatures
    ) -> None:
        """≥2 drift channels triggered → MEDIUM rule fires."""
        catalog = build_realistic_catalog()
        top = retrieve_top_3(
            candidate_sector=nvda_2023_candidate.sector,
            candidate_universal_core=nvda_2023_candidate.universal_core,
            candidate_sector_extensions=nvda_2023_candidate.sector_extensions,
            catalog=catalog,
            k=3,
        )
        rollup_top_3 = [
            "SURVIVOR" if m.case.outcome in ("SURVIVOR", "DILUTED-SURVIVOR")
            else "NON_SURVIVOR"
            for m in top
        ]
        result = roll_up_conviction(
            ConvictionInputs(
                debate_add_count=5,
                kills_fired=0,
                counterfactual_top_3=rollup_top_3,
                anchor_drift_channels_triggered=2,  # drift active
            )
        )
        assert result.bucket == "MEDIUM"
