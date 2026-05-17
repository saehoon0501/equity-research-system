"""Feature typing — declares categorical vs ordinal per Phase 4 Q4.

Per the v3 spec (Section 4.4 universal-core + Phase 4 Q4 feature-typed-v0.1
consensus rule), every catalog feature is one of two kinds, with different
agreement semantics across the 3-LLM consensus pipeline:

    - CATEGORICAL: exact match required across all 3 LLMs
    - ORDINAL:    within-±1 step on a declared ordering counts as agreement

A persistent disagreement after 5 iterations → tag `consensus_status: disputed`
and exclude from active retrieval (PB#7).

This module is the single source of truth for:
    1. Universal-core feature type assignments (6 features)
    2. Sector-extension feature type assignments (per sector)
    3. The explicit ordinal orderings used by the within-±1 rule

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 4.4 (universal-core schema) + Phase 4 Q4 (feature-typed
           consensus rule) + .claude/references/empirical/peak-pain-archetypes/
           catalog-v0.1.md (full sector extension tables).
"""

from __future__ import annotations

from enum import Enum


class FeatureKind(str, Enum):
    """Two kinds of features per Phase 4 Q4.

    CATEGORICAL features have unordered domains — agreement = string equality
    after canonicalization. ORDINAL features have a declared ordering — agreement
    permits within-±1 step (so e.g. cash_runway 12-24mo and cash_runway >24mo
    count as agreement, but cash_runway >24mo and cash_runway distressed don't).
    """

    CATEGORICAL = "categorical"
    ORDINAL = "ordinal"


# ---------------------------------------------------------------------------
# Universal core (Section 4.4 Layer 1) — 6 features, sector-agnostic
# ---------------------------------------------------------------------------

UNIVERSAL_CORE: tuple[str, ...] = (
    "founder_insider_stake_direction",
    "cash_runway",
    "founder_in_place",
    "margin_trajectory",
    "revenue_trajectory",
    "industry_tailwind",
)


# ---------------------------------------------------------------------------
# Feature type assignments
#
# Per Phase 4 Q4:
#   - Categorical: founder_in_place, founder_insider_stake_direction,
#                  sector-specific categorical (moat_state, regulatory_standing,
#                  CEO_change_quality, ...)
#   - Ordinal:     cash_runway, customer_engagement, margin_trajectory,
#                  revenue_trajectory, industry_tailwind, sector-specific
#                  ordinals (capital_ratio, leverage_level, ...)
# ---------------------------------------------------------------------------

FEATURE_TYPES: dict[str, FeatureKind] = {
    # Universal core
    "founder_insider_stake_direction": FeatureKind.CATEGORICAL,
    "founder_in_place": FeatureKind.CATEGORICAL,
    "cash_runway": FeatureKind.ORDINAL,
    "margin_trajectory": FeatureKind.ORDINAL,
    "revenue_trajectory": FeatureKind.ORDINAL,
    "industry_tailwind": FeatureKind.ORDINAL,
    # Tech / SaaS
    "customer_engagement": FeatureKind.ORDINAL,
    "engagement_decoupling_from_price": FeatureKind.CATEGORICAL,
    "NDR_trend": FeatureKind.ORDINAL,
    # Semis / hardware
    "moat_state": FeatureKind.CATEGORICAL,
    "cycle_state": FeatureKind.CATEGORICAL,
    "customer_concentration": FeatureKind.ORDINAL,
    # Consumer-discretionary
    "repeat_purchase_trajectory": FeatureKind.ORDINAL,
    "brand_equity_state": FeatureKind.ORDINAL,
    "distribution_channel_integrity": FeatureKind.ORDINAL,
    # Consumer-brands
    "leverage_level": FeatureKind.ORDINAL,
    "leadership_replacement_quality": FeatureKind.CATEGORICAL,
    # Fintech
    "take_rate_trajectory": FeatureKind.ORDINAL,
    "credit_quality": FeatureKind.ORDINAL,
    "regulatory_standing": FeatureKind.CATEGORICAL,
    # Healthcare / biotech
    "pipeline_depth": FeatureKind.CATEGORICAL,
    "trial_status_at_trough": FeatureKind.CATEGORICAL,
    "TAM_state": FeatureKind.ORDINAL,
    # Industrial
    "backlog_quality": FeatureKind.CATEGORICAL,
    "litigation_state": FeatureKind.CATEGORICAL,
    "CEO_change_quality": FeatureKind.CATEGORICAL,
    # Energy
    "net_debt_at_trough": FeatureKind.ORDINAL,
    "hedge_book": FeatureKind.ORDINAL,
    "reserve_quality": FeatureKind.ORDINAL,
    "cost_curve": FeatureKind.ORDINAL,
    # Comms / media
    "content_IP_moat_state": FeatureKind.ORDINAL,
    "subscriber_DAU_trajectory": FeatureKind.ORDINAL,
    "leverage_multiple": FeatureKind.ORDINAL,
    # International / EM
    "regulatory_overhang_state": FeatureKind.CATEGORICAL,
    "geopolitical_state": FeatureKind.ORDINAL,
    "capital_controls_FX_exposure": FeatureKind.ORDINAL,
    # EV / autos
    "production_trajectory": FeatureKind.ORDINAL,
    "vehicle_margin": FeatureKind.ORDINAL,
    "capital_structure": FeatureKind.CATEGORICAL,
    # REITs
    "property_tier": FeatureKind.CATEGORICAL,
    "debt_maturity_wall": FeatureKind.ORDINAL,
    "asset_class_tailwind": FeatureKind.ORDINAL,
    "tenant_credit_concentration": FeatureKind.ORDINAL,
    # Recent-IPO / SPAC
    "redemption_rate": FeatureKind.ORDINAL,
    "lockup_behavior": FeatureKind.CATEGORICAL,
    "deck_vs_actual_revenue_gap": FeatureKind.ORDINAL,
    # Crypto-adjacent
    "counterparty_exposure": FeatureKind.ORDINAL,
    # Financials / banks
    "capital_ratio": FeatureKind.ORDINAL,
    "uninsured_deposit_pct": FeatureKind.ORDINAL,
    "dilution_at_trough": FeatureKind.ORDINAL,
    "asset_quality": FeatureKind.ORDINAL,
}


# ---------------------------------------------------------------------------
# Ordinal orderings — explicit per Phase 4 Q4 (within-±1 rule needs a fixed
# index for every feature). Each list is ordered from "best" to "worst" so the
# index difference is the absolute step distance.
# ---------------------------------------------------------------------------

ORDINAL_ORDERS: dict[str, list[str]] = {
    # Universal core ordinals
    "cash_runway": [">24mo", "12-24mo", "<12mo", "distressed"],
    "margin_trajectory": ["improving", "stable", "deteriorating"],
    "revenue_trajectory": ["growing", "flat", "declining", "pre-revenue"],
    "industry_tailwind": ["intact", "weakening", "reversed", "structural-decline"],
    # Tech / SaaS
    "customer_engagement": ["holding", "eroding", "collapsed"],
    "NDR_trend": ["expanding", "flat", "contracting"],
    # Semis / hardware
    "customer_concentration": ["low", "moderate", "high"],
    # Consumer-discretionary
    "repeat_purchase_trajectory": ["holding", "eroding", "collapsed"],
    "brand_equity_state": ["intact", "eroding", "impaired", "collapsed"],
    "distribution_channel_integrity": ["intact", "weakening", "impaired"],
    # Consumer-brands
    "leverage_level": ["healthy", "stretched", "distressed"],
    # Fintech
    "take_rate_trajectory": ["expanding", "holding", "eroding"],
    "credit_quality": ["improving", "stable", "deteriorating", "severely-impaired"],
    # Healthcare
    "TAM_state": ["intact", "weakening", "closed"],
    # Energy ordinals
    "net_debt_at_trough": ["healthy", "stretched", "distressed"],
    "hedge_book": ["strong", "moderate", "unhedged"],
    "reserve_quality": ["tier-1", "tier-2", "marginal"],
    "cost_curve": ["low", "median", "high"],
    # Comms / media
    "content_IP_moat_state": ["intact", "weakening", "commoditized"],
    "subscriber_DAU_trajectory": ["growing", "flat", "declining"],
    "leverage_multiple": ["healthy", "stretched", "distressed"],
    # International / EM
    "geopolitical_state": ["stable", "deteriorating", "hostile"],
    "capital_controls_FX_exposure": ["low", "moderate", "high"],
    # EV / autos
    "production_trajectory": ["growing", "flat", "declining"],
    "vehicle_margin": ["positive", "negative", "catastrophic-negative"],
    # REITs
    "debt_maturity_wall": ["distant", "near", "immediate"],
    "asset_class_tailwind": ["intact", "weakening", "structural-decline"],
    "tenant_credit_concentration": ["low", "moderate", "high"],
    # Recent-IPO / SPAC
    "redemption_rate": ["low", "moderate", "high", "extreme"],
    "deck_vs_actual_revenue_gap": ["close", "moderate", "wide"],
    # Crypto
    "counterparty_exposure": ["none", "contained", "large"],
    # Financials / banks
    "capital_ratio": ["strong", "adequate", "weak", "inadequate"],
    "uninsured_deposit_pct": ["<33%", "33-66%", ">66%"],
    "dilution_at_trough": ["none", "moderate", "extreme"],
    "asset_quality": ["clean", "contested", "impaired"],
}


# ---------------------------------------------------------------------------
# Categorical domains — used by extractor JSON schema validation. Optional;
# extractor will accept any string but persistence flags off-domain values.
# ---------------------------------------------------------------------------

CATEGORICAL_DOMAINS: dict[str, list[str]] = {
    "founder_insider_stake_direction": ["increasing", "flat", "decreasing", "departed"],
    "founder_in_place": ["yes", "departed", "replaced-by-competent"],
    "engagement_decoupling_from_price": ["yes", "no"],
    "moat_state": ["intact", "weakening", "leapfrogged"],
    "cycle_state": ["cyclical-trough", "secular-decline", "structural-decline"],
    "leadership_replacement_quality": [
        "Culp-pattern",
        "caretaker",
        "founder-entrenched",
        "departed",
        "replaced-by-competent",
    ],
    "regulatory_standing": ["clean", "contested", "hostile"],
    "pipeline_depth": ["diversified", "concentrated"],
    "trial_status_at_trough": ["positive", "mixed", "negative"],
    "backlog_quality": ["contracted", "aspirational"],
    "litigation_state": ["resolved", "contained", "open-ended"],
    "CEO_change_quality": ["Culp-pattern", "caretaker", "founder-entrenched"],
    "regulatory_overhang_state": ["contained", "open-ended", "resolving"],
    "capital_structure": ["public-only", "sovereign-backed", "PE-controlled"],
    "property_tier": ["A", "B", "C"],
    "lockup_behavior": ["clean", "pressure", "selling-aggressive"],
}


# ---------------------------------------------------------------------------
# Within-±1 helper — the core Phase 4 Q4 rule
# ---------------------------------------------------------------------------


def is_within_one_step(feature_name: str, value_a: str, value_b: str) -> bool:
    """Return True if two ordinal values are within ±1 step on the declared order.

    Per Phase 4 Q4 feature-typed-v0.1 consensus rule. Falls back to exact
    equality for features without a declared ordering (defensive — should not
    happen for any feature in FEATURE_TYPES with kind=ORDINAL).

    Args:
        feature_name: Catalog feature key (e.g. "cash_runway").
        value_a:      First value to compare.
        value_b:      Second value to compare.

    Returns:
        True iff |index(a) - index(b)| <= 1 on the declared ORDINAL_ORDERS
        list. If either value is outside the declared domain, returns False
        (treats off-domain as disagreement — surfaces extraction noise).
    """
    if value_a == value_b:
        return True
    order = ORDINAL_ORDERS.get(feature_name)
    if order is None:
        return False
    try:
        i = order.index(_canonicalize(value_a, order))
        j = order.index(_canonicalize(value_b, order))
    except ValueError:
        return False
    return abs(i - j) <= 1


def _canonicalize(value: str, order: list[str]) -> str:
    """Strip whitespace and lowercase for forgiving comparison.

    LLM extractor outputs are normalized but operators may type slight variants
    (e.g. "Distressed" vs "distressed"). Order list is the canonical form.
    """
    if not isinstance(value, str):
        raise ValueError(f"non-string ordinal value: {value!r}")
    norm = value.strip()
    for canon in order:
        if norm.lower() == canon.lower():
            return canon
    return norm  # raises ValueError downstream if not in order


def categorical_match(value_a: str, value_b: str) -> bool:
    """Return True if two categorical values match exactly per Phase 4 Q4.

    Lowercased + whitespace-stripped — defensive against LLM casing drift.
    """
    if not (isinstance(value_a, str) and isinstance(value_b, str)):
        return False
    return value_a.strip().lower() == value_b.strip().lower()


def features_agree(feature_name: str, value_a: str, value_b: str) -> bool:
    """Apply the Phase 4 Q4 feature-typed consensus rule for one pair.

    Dispatches on FEATURE_TYPES; categorical → exact match,
    ordinal → within-±1 step.
    """
    kind = FEATURE_TYPES.get(feature_name)
    if kind == FeatureKind.CATEGORICAL:
        return categorical_match(value_a, value_b)
    if kind == FeatureKind.ORDINAL:
        return is_within_one_step(feature_name, value_a, value_b)
    # Unknown feature → conservative: require exact match.
    return categorical_match(value_a, value_b)
