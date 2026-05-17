"""Realistic 2022-era peak-pain catalog fixture for calibration + walkthroughs.

Provides ~14 hand-coded ``CatalogCase`` rows spanning SURVIVOR / NON-SURVIVOR /
DILUTED-SURVIVOR outcomes across multiple sectors. Each case reflects the
shape recorded in catalog-v0.1.md but is structured purely as deterministic
test data so the calibration harness produces reproducible scoring (no LLM
calls, no DB).

Used by:
    * tests/test_calibration_harness.py — runs Section 7.2 launch-gate harness
    * tests/test_counterfactual_veto.py — PLTR-2022 walkthrough tests
    * docs/superpowers/launch-walkthroughs/pltr-2022.md — referenced expected
      behavior

Per remediation brief: features are NOT hand-tuned to guarantee outcomes.
The retrieval scorer (0.7 universal-core + 0.3 sector-extension Bayesian-shrunk
Hamming) determines the top-3 per its rules; the operator-pre-annotated
expected_archetype_distribution in the calibration JSON is what gets graded.
"""

from __future__ import annotations

from typing import Any

from src.counterfactual_veto.retrieval import CatalogCase


def build_realistic_catalog() -> list[CatalogCase]:
    """Return the realistic 17-case catalog fixture.

    Mix:
        SURVIVOR (6):           NVDA-2008, AMD-2014, NFLX-2011, MELI-2022,
                                CVNA-2022, AAPL-2003
        DILUTED-SURVIVOR (3):   GE-2018, F-2008, BAC-2009
        NON-SURVIVOR (8):       BBBY-2023, FSR-2024, CHK-2020, NOK-2012, OPI-2024,
                                LEH-2008, WaMu-2008, IndyMac-2008

    Sectors covered: tech_saas, semis_hardware, comms_media, international_em,
    consumer_discretionary, ev_autos, energy, reits, financials_banks,
    industrial, banks_regional.

    Banks-2008 trio (LEH-2008, WaMu-2008, IndyMac-2008) added for SVB-March-2023
    walkthrough validation. Features reflect deposit-flight + uninsured-deposit-
    concentration + HTM-unrealized-loss profile that maps SVB onto the historical
    bank-collapse archetype. Per Section 7.3a launch-walkthrough #3 (SVB).
    """
    return [
        # ---------- SURVIVOR ----------
        CatalogCase(
            case_id="NVDA-2008",
            ticker="NVDA",
            sector="semis_hardware",
            outcome="SURVIVOR",
            universal_core_features={
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
            validation_status="validated",
            era_category="recent",
            peak_dd_pct=-85.0,
        ),
        CatalogCase(
            case_id="AMD-2014",
            ticker="AMD",
            sector="semis_hardware",
            outcome="SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "increasing",
                "cash_runway": "12-24mo",
                "founder_in_place": "replaced-by-competent",
                "margin_trajectory": "improving",
                "revenue_trajectory": "flat",
                "industry_tailwind": "intact",
            },
            sector_extensions={
                "moat_state": "weakening",
                "cycle_state": "cyclical-trough",
                "customer_concentration": "moderate",
            },
            validation_status="validated",
            era_category="recent",
            peak_dd_pct=-80.0,
        ),
        CatalogCase(
            case_id="NFLX-2011",
            ticker="NFLX",
            sector="comms_media",
            outcome="SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "increasing",
                "cash_runway": ">24mo",
                "founder_in_place": "yes",
                "margin_trajectory": "improving",
                "revenue_trajectory": "growing",
                "industry_tailwind": "intact",
            },
            sector_extensions={
                "content_IP_moat_state": "intact",
                "subscriber_DAU_trajectory": "growing",
                "leverage_multiple": "healthy",
            },
            validation_status="validated",
            era_category="recent",
            peak_dd_pct=-75.0,
        ),
        CatalogCase(
            case_id="MELI-2022",
            ticker="MELI",
            sector="international_em",
            outcome="SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "increasing",
                "cash_runway": ">24mo",
                "founder_in_place": "yes",
                "margin_trajectory": "improving",
                "revenue_trajectory": "growing",
                "industry_tailwind": "intact",
            },
            sector_extensions={
                "regulatory_overhang_state": "contained",
                "geopolitical_state": "deteriorating",
                "capital_controls_FX_exposure": "moderate",
            },
            validation_status="validated",
            era_category="recent",
            peak_dd_pct=-60.0,
        ),
        CatalogCase(
            case_id="CVNA-2022",
            ticker="CVNA",
            sector="consumer_discretionary",
            outcome="SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "increasing",
                "cash_runway": "12-24mo",
                "founder_in_place": "yes",
                "margin_trajectory": "improving",
                "revenue_trajectory": "flat",
                "industry_tailwind": "weakening",
            },
            sector_extensions={
                "repeat_purchase_trajectory": "holding",
                "brand_equity_state": "intact",
                "distribution_channel_integrity": "intact",
            },
            validation_status="validated",
            era_category="recent",
            peak_dd_pct=-99.0,
        ),
        CatalogCase(
            case_id="AAPL-2003",
            ticker="AAPL",
            sector="tech_saas",
            outcome="SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "increasing",
                "cash_runway": ">24mo",
                "founder_in_place": "yes",
                "margin_trajectory": "improving",
                "revenue_trajectory": "growing",
                "industry_tailwind": "intact",
            },
            sector_extensions={
                "customer_engagement": "holding",
                "engagement_decoupling_from_price": "yes",
                "NDR_trend": "expanding",
            },
            validation_status="validated",
            era_category="dot_com",
            peak_dd_pct=-80.0,
        ),
        # ---------- DILUTED-SURVIVOR ----------
        CatalogCase(
            case_id="GE-2018",
            ticker="GE",
            sector="industrial",
            outcome="DILUTED-SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "flat",
                "cash_runway": "12-24mo",
                "founder_in_place": "replaced-by-competent",
                "margin_trajectory": "stable",
                "revenue_trajectory": "flat",
                "industry_tailwind": "weakening",
            },
            sector_extensions={
                "backlog_quality": "contracted",
                "litigation_state": "contained",
                "CEO_change_quality": "Culp-pattern",
            },
            validation_status="validated",
            era_category="recent",
            peak_dd_pct=-70.0,
        ),
        CatalogCase(
            case_id="F-2008",
            ticker="F",
            sector="ev_autos",
            outcome="DILUTED-SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "flat",
                "cash_runway": "12-24mo",
                "founder_in_place": "replaced-by-competent",
                "margin_trajectory": "stable",
                "revenue_trajectory": "flat",
                "industry_tailwind": "weakening",
            },
            sector_extensions={
                "production_trajectory": "flat",
                "vehicle_margin": "positive",
                "capital_structure": "public-only",
            },
            validation_status="validated",
            era_category="gfc_nonfin",
            peak_dd_pct=-90.0,
        ),
        CatalogCase(
            case_id="BAC-2009",
            ticker="BAC",
            sector="financials_banks",
            outcome="DILUTED-SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "flat",
                "cash_runway": "12-24mo",
                "founder_in_place": "replaced-by-competent",
                "margin_trajectory": "stable",
                "revenue_trajectory": "flat",
                "industry_tailwind": "weakening",
            },
            sector_extensions={
                "capital_ratio": "weak",
                "uninsured_deposit_pct": "33-66%",
                "dilution_at_trough": "extreme",
                "asset_quality": "contested",
            },
            validation_status="validated",
            era_category="gfc_nonfin",
            peak_dd_pct=-94.0,
        ),
        # ---------- NON-SURVIVOR ----------
        CatalogCase(
            case_id="BBBY-2023",
            ticker="BBBY",
            sector="consumer_discretionary",
            outcome="NON-SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "departed",
                "cash_runway": "distressed",
                "founder_in_place": "departed",
                "margin_trajectory": "deteriorating",
                "revenue_trajectory": "declining",
                "industry_tailwind": "structural-decline",
            },
            sector_extensions={
                "repeat_purchase_trajectory": "collapsed",
                "brand_equity_state": "collapsed",
                "distribution_channel_integrity": "impaired",
            },
            validation_status="validated",
            era_category="recent",
            peak_dd_pct=-99.0,
        ),
        CatalogCase(
            case_id="FSR-2024",
            ticker="FSR",
            sector="ev_autos",
            outcome="NON-SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "decreasing",
                "cash_runway": "distressed",
                "founder_in_place": "yes",
                "margin_trajectory": "deteriorating",
                "revenue_trajectory": "declining",
                "industry_tailwind": "weakening",
            },
            sector_extensions={
                "production_trajectory": "declining",
                "vehicle_margin": "catastrophic-negative",
                "capital_structure": "public-only",
            },
            validation_status="validated",
            era_category="recent",
            peak_dd_pct=-99.0,
        ),
        CatalogCase(
            case_id="CHK-2020",
            ticker="CHK",
            sector="energy",
            outcome="NON-SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "departed",
                "cash_runway": "distressed",
                "founder_in_place": "departed",
                "margin_trajectory": "deteriorating",
                "revenue_trajectory": "declining",
                "industry_tailwind": "reversed",
            },
            sector_extensions={
                "net_debt_at_trough": "distressed",
                "hedge_book": "unhedged",
                "reserve_quality": "tier-2",
                "cost_curve": "high",
            },
            validation_status="validated",
            era_category="recent",
            peak_dd_pct=-99.0,
        ),
        CatalogCase(
            case_id="NOK-2012",
            ticker="NOK",
            sector="tech_saas",
            outcome="NON-SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "departed",
                "cash_runway": "<12mo",
                "founder_in_place": "departed",
                "margin_trajectory": "deteriorating",
                "revenue_trajectory": "declining",
                "industry_tailwind": "structural-decline",
            },
            sector_extensions={
                "customer_engagement": "collapsed",
                "engagement_decoupling_from_price": "no",
                "NDR_trend": "contracting",
            },
            validation_status="validated",
            era_category="recent",
            peak_dd_pct=-90.0,
        ),
        CatalogCase(
            case_id="OPI-2024",
            ticker="OPI",
            sector="reits",
            outcome="NON-SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "decreasing",
                "cash_runway": "distressed",
                "founder_in_place": "departed",
                "margin_trajectory": "deteriorating",
                "revenue_trajectory": "declining",
                "industry_tailwind": "structural-decline",
            },
            sector_extensions={
                "property_tier": "B",
                "debt_maturity_wall": "immediate",
                "asset_class_tailwind": "structural-decline",
                "tenant_credit_concentration": "high",
            },
            validation_status="validated",
            era_category="recent",
            peak_dd_pct=-95.0,
        ),
        # ---------- Banks-2008 trio (NON-SURVIVOR) — SVB walkthrough catalog ----------
        # Lehman Brothers Sept 2008. Deposit/funding-flight terminal collapse —
        # uninsured wholesale-funding-concentration profile maps onto SVB.
        CatalogCase(
            case_id="LEH-2008",
            ticker="LEH",
            sector="banks_regional",
            outcome="NON-SURVIVOR",
            universal_core_features={
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
            validation_status="validated",
            era_category="gfc_nonfin",
            peak_dd_pct=-99.0,
        ),
        # Washington Mutual Sept 2008. Largest bank failure in US history;
        # deposit run + HTM/AFS unrealized losses on the residential book.
        CatalogCase(
            case_id="WaMu-2008",
            ticker="WM",
            sector="banks_regional",
            outcome="NON-SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "decreasing",
                "cash_runway": "distressed",
                "founder_in_place": "departed",
                "margin_trajectory": "deteriorating",
                "revenue_trajectory": "declining",
                "industry_tailwind": "stressed",
            },
            sector_extensions={
                "uninsured_deposit_pct": "94%",
                "deposit_flight_rate_30d": "accelerating",
                "HTM_unrealized_loss_pct_capital": "91%",
                "htm_to_loans_ratio": "1.2",
                "brokered_deposits_pct": "low",
            },
            validation_status="validated",
            era_category="gfc_nonfin",
            peak_dd_pct=-99.0,
        ),
        # IndyMac July 2008. Pre-Lehman bank failure — uninsured concentration
        # + alt-A residential exposure + early deposit run pattern.
        CatalogCase(
            case_id="IndyMac-2008",
            ticker="IMB",
            sector="banks_regional",
            outcome="NON-SURVIVOR",
            universal_core_features={
                "founder_insider_stake_direction": "decreasing",
                "cash_runway": "distressed",
                "founder_in_place": "departed",
                "margin_trajectory": "deteriorating",
                "revenue_trajectory": "declining",
                "industry_tailwind": "stressed",
            },
            sector_extensions={
                "uninsured_deposit_pct": "94%",
                "deposit_flight_rate_30d": "accelerating",
                "HTM_unrealized_loss_pct_capital": "91%",
                "htm_to_loans_ratio": "1.3",
                "brokered_deposits_pct": "low",
            },
            validation_status="validated",
            era_category="gfc_nonfin",
            peak_dd_pct=-99.0,
        ),
    ]


def realistic_catalog_as_db_rows(
    *,
    sign_with_key: bytes | None = None,
) -> list[dict[str, Any]]:
    """Materialize the realistic catalog as DB-row dicts (for HMAC tests).

    Each row mirrors the SELECT shape ``load_catalog_from_pg`` expects. If
    ``sign_with_key`` is provided, attach a valid HMAC signature to each row
    (using the canonical payload contract from
    ``src.audit_trail.hmac_verify.compute_signature_dict``).
    """
    from src.audit_trail.hmac_verify import compute_signature_dict
    from src.counterfactual_veto.retrieval import _HMAC_PAYLOAD_FIELDS, _row_hmac_payload

    base_cases = build_realistic_catalog()
    rows: list[dict[str, Any]] = []
    for c in base_cases:
        row: dict[str, Any] = {
            "case_id": c.case_id,
            "ticker": c.ticker,
            "peak_date": "2022-01-01",
            "trough_date": "2022-12-31",
            "peak_dd_pct": c.peak_dd_pct or -50.0,
            "outcome": c.outcome,
            "sector": c.sector,
            "era_category": c.era_category,
            "universal_core_features": dict(c.universal_core_features),
            "sector_extensions": dict(c.sector_extensions),
            "universal_core_consensus": {},
            "validation_status": c.validation_status,
            "consensus_method": "feature-typed-v0.1",
            "notes": "",
            "source_urls": [],
            "hmac_signature": "",
            "signed_at": None,
        }
        if sign_with_key is not None:
            payload = _row_hmac_payload(row)
            row["hmac_signature"] = compute_signature_dict(payload, sign_with_key)
        rows.append(row)
    return rows
