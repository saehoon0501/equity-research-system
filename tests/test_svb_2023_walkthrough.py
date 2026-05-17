"""SVB-March-2023 launch walkthrough reproducer (Section 7.3a #3).

Validates the Banks-B mode + sector-extension matching pathway against the
SVB collapse scenario. The cut pipeline must produce a NON-SURVIVOR-dominant
top-3 against the realistic catalog (with the 2008 banks trio added) — the
counterfactual veto does NOT block, and the cut proceeds.

Asserts:
  * Top-3 retrieval against the realistic catalog (with LEH/WaMu/IndyMac)
    surfaces same-sector banks NON-SURVIVOR cases above cross-sector cases.
  * Layer 3 veto returns ``not_triggered`` (NON-SURVIVOR-dominant) → cut
    pipeline proceeds rather than block.
  * Section 7.2 sector-extension matching is load-bearing: the 0.3 sector-
    extension term carries banks cases over cross-sector NON-SURVIVOR cases.

Reproduces ``docs/superpowers/launch-walkthroughs/svb-march-2023.md``.
"""

from __future__ import annotations

import pytest

from src.counterfactual_veto.feature_extractor import CandidateFeatures
from src.counterfactual_veto.layer3_veto import evaluate_veto
from src.counterfactual_veto.retrieval import retrieve_top_3
from tests.fixtures.realistic_catalog import build_realistic_catalog


@pytest.fixture
def svb_2023_candidate() -> CandidateFeatures:
    """SVB at 2023-03-08 capital-raise 8-K — banks-collapse archetype shape.

    Universal-core is sector-naive (banks have N/A on cash_runway); the
    sector-extension features (uninsured deposit %, deposit flight rate,
    HTM unrealized loss) are load-bearing.
    """
    return CandidateFeatures(
        ticker="SIVB",
        sector="banks_regional",
        extraction_date="2023-03-08",
        universal_core={
            "founder_insider_stake_direction": "decreasing",
            "cash_runway": "distressed",
            "founder_in_place": "yes",
            "margin_trajectory": "deteriorating",
            "revenue_trajectory": "declining",
            "industry_tailwind": "stressed",
        },
        sector_extensions={
            "uninsured_deposit_pct": "94%",
            "deposit_flight_rate_30d": "accelerating",
            "HTM_unrealized_loss_pct_capital": "91%",
            "htm_to_loans_ratio": "1.4",
            "brokered_deposits_pct": "low",
        },
        consensus={f: "HIGH" for f in [
            "founder_insider_stake_direction",
            "cash_runway",
            "founder_in_place",
            "margin_trajectory",
            "revenue_trajectory",
            "industry_tailwind",
            "uninsured_deposit_pct",
            "deposit_flight_rate_30d",
            "HTM_unrealized_loss_pct_capital",
            "htm_to_loans_ratio",
            "brokered_deposits_pct",
        ]},
    )


class TestSvbBanksBCut:
    """Section 7.3a #3 — the banks-sector cut pathway."""

    def test_top_3_retrieval_dominated_by_banks_2008_cases(
        self, svb_2023_candidate: CandidateFeatures
    ) -> None:
        """Same-sector banks NON-SURVIVOR cases lead the top-3.

        Sector-extension matching is load-bearing: cross-sector NON-SURVIVOR
        cases (OPI, CHK, BBBY, FSR, NOK) lose the 0.3 extension term and rank
        below LEH/WaMu/IndyMac despite similar universal-core feature shape.
        """
        catalog = build_realistic_catalog()
        top = retrieve_top_3(
            candidate_sector=svb_2023_candidate.sector,
            candidate_universal_core=svb_2023_candidate.universal_core,
            candidate_sector_extensions=svb_2023_candidate.sector_extensions,
            catalog=catalog,
            k=3,
        )
        case_ids = [m.case.case_id for m in top]
        # All three top cases must be banks_regional NON-SURVIVOR.
        sectors = [m.case.sector for m in top]
        outcomes = [m.case.outcome for m in top]
        assert all(s == "banks_regional" for s in sectors), (
            f"expected all banks_regional in top-3, got {list(zip(case_ids, sectors))}"
        )
        assert all(o == "NON-SURVIVOR" for o in outcomes), (
            f"expected all NON-SURVIVOR in top-3, got {list(zip(case_ids, outcomes))}"
        )
        # The 2008 banks trio must all be present.
        assert set(case_ids) == {"LEH-2008", "WaMu-2008", "IndyMac-2008"}, (
            f"expected the 2008 banks trio in top-3, got {case_ids}"
        )

    def test_same_sector_banks_match_carries_extension_term(
        self, svb_2023_candidate: CandidateFeatures
    ) -> None:
        """LEH-2008 (same-sector banks) gets the +0.3 extension contribution."""
        catalog = build_realistic_catalog()
        top = retrieve_top_3(
            candidate_sector=svb_2023_candidate.sector,
            candidate_universal_core=svb_2023_candidate.universal_core,
            candidate_sector_extensions=svb_2023_candidate.sector_extensions,
            catalog=catalog,
            k=5,  # inspect top-5 to compare same-sector vs cross-sector
        )
        same_sector = [m for m in top if m.case.sector == "banks_regional"]
        cross_sector = [m for m in top if m.case.sector != "banks_regional"]
        # All same-sector banks must score HIGHER than any cross-sector match.
        if cross_sector:
            min_same = min(m.similarity for m in same_sector)
            max_cross = max(m.similarity for m in cross_sector)
            assert min_same > max_cross, (
                f"same-sector banks ({min_same}) must outscore cross-sector "
                f"({max_cross}); sector-extension term is load-bearing"
            )
        # Same-sector matches should carry a non-None sector_extension_similarity.
        assert all(m.sector_extension_similarity is not None for m in same_sector)
        # Cross-sector matches must have None sector_extension_similarity.
        assert all(m.sector_extension_similarity is None for m in cross_sector)

    def test_non_survivor_dominant_does_not_block_cut(
        self, svb_2023_candidate: CandidateFeatures
    ) -> None:
        """NON-SURVIVOR-dominant top-3 → veto.status='not_triggered' → cut proceeds.

        This is the inverse of PLTR-2022: where SURVIVOR-dominant blocks for
        operator-override, NON-SURVIVOR-dominant confirms the cut.
        """
        catalog = build_realistic_catalog()
        result = evaluate_veto(candidate=svb_2023_candidate, catalog=catalog)
        assert not result.veto_invoked
        assert result.status == "not_triggered"
        assert result.archetype_distribution["NON-SURVIVOR"] == 3
        assert result.archetype_distribution["SURVIVOR"] == 0
        assert result.archetype_distribution["DILUTED-SURVIVOR"] == 0

    def test_canonical_payload_top_3_case_ids_match_walkthrough(
        self, svb_2023_candidate: CandidateFeatures
    ) -> None:
        """The walkthrough HMAC payload cites LEH/WaMu/IndyMac — verify those IDs come back."""
        catalog = build_realistic_catalog()
        top = retrieve_top_3(
            candidate_sector=svb_2023_candidate.sector,
            candidate_universal_core=svb_2023_candidate.universal_core,
            candidate_sector_extensions=svb_2023_candidate.sector_extensions,
            catalog=catalog,
            k=3,
        )
        case_ids = sorted(m.case.case_id for m in top)
        # The walkthrough HMAC payload says top_3_case_ids =
        # ["IndyMac-2008", "LEH-2008", "WaMu-2008"] (sorted lexicographically).
        assert case_ids == ["IndyMac-2008", "LEH-2008", "WaMu-2008"]
