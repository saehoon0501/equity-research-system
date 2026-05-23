"""Wiring tests for v0.2 quantitative-analyst ERP injection.

This is a STATIC test (no live agent dispatch). It verifies the wiring sites:

1. Migration 040 ships the three flow.erp_add_bps.gamma_<bin> keys with the
   expected placeholder magnitudes.
2. quantitative-analyst.md cites the regime-adjustment formula at line 96
   (the load-bearing spec contract).
3. research-company.md §1.5 Step 6 scopes flow.erp_add_bps.* to
   quantitative-analyst's PARAMETERS_USED block (NOT strategic-analyst's).
4. quantitative-analyst.md has the architectural-invariant comment
   forbidding F-Score and Altman Z'' from reading flow_modifier.

Integration test of actual agent dispatch is out of scope for this static
test (requires live LLM dispatch + cost). The static checks here would catch
the most common wiring failures: a future operator editing one site but
forgetting another.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
MIGRATION_PATH = REPO / "db" / "migrations" / "040_flow_overlay_v02_gamma_erp.sql"
QUANT_AGENT_PATH = REPO / ".claude" / "agents" / "quantitative-analyst.md"
RESEARCH_COMPANY_PATH = REPO / ".claude" / "commands" / "research-company.md"
STRATEGIC_AGENT_PATH = REPO / ".claude" / "agents" / "strategic-analyst.md"


# ---------- Migration 040 ships the expected placeholder rows ----------


def test_migration_040_has_three_erp_bps_rows():
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "flow.erp_add_bps.gamma_positive" in text
    assert "flow.erp_add_bps.gamma_neutral" in text
    assert "flow.erp_add_bps.gamma_negative" in text


def test_migration_040_erp_negative_default_50bps():
    """Default placeholder per plan: positive=0, neutral=0, negative=50."""
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    # The negative row should ship 50 as its JSONB value (50bps stress placeholder).
    # Search for the row block; it should pair the key with value '50'.
    assert "'flow.erp_add_bps.gamma_negative'" in text
    # Specifically check the value-50 token appears near the gamma_negative key.
    # (Loose check; the migration prose around the row will contain '50bp' / '50'.)
    negative_idx = text.find("flow.erp_add_bps.gamma_negative")
    snippet = text[negative_idx : negative_idx + 600]
    assert "'50'::jsonb" in snippet or "'50'\n" in snippet


def test_migration_040_cites_bonelli_caveat():
    """The placeholder magnitudes must explicitly flag Bonelli 2025 ungrounded-conjecture caveat."""
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "Bonelli" in text or "ungrounded" in text


# ---------- quantitative-analyst.md cites the regime-adjustment formula ----------


def test_quant_md_cites_erp_adjustment_formula():
    """quantitative-analyst.md MUST contain the regime-adjustment formula at the ERP read site."""
    text = QUANT_AGENT_PATH.read_text(encoding="utf-8")
    # The formula spec: erp_adjusted = wacc.erp + flow_modifier.erp_add_bps / 100
    assert "flow_modifier.erp_add_bps" in text, (
        "quantitative-analyst.md must reference flow_modifier.erp_add_bps at the ERP read site (v0.2 spec)"
    )


def test_quant_md_has_invariant_comment_for_quality_gates():
    """F-Score and Altman Z'' must NEVER read flow_modifier — invariant comment present."""
    text = QUANT_AGENT_PATH.read_text(encoding="utf-8")
    # Look for the architectural invariant marker
    assert "ARCHITECTURAL INVARIANT" in text or "MUST NOT read flow_modifier" in text, (
        "quantitative-analyst.md must carry an explicit invariant comment that F-Score and Altman Z'' do NOT read flow_modifier"
    )


# ---------- research-company.md scopes flow.erp_add_bps.* to quant only ----------


def test_research_company_scopes_erp_add_bps_to_quant():
    """research-company.md §1.5 Step 6 must mention flow.erp_add_bps.* in the quantitative-analyst consumption list."""
    text = RESEARCH_COMPANY_PATH.read_text(encoding="utf-8")
    assert "flow.erp_add_bps" in text or "flow_modifier.erp_add_bps" in text, (
        "research-company.md §1.5 Step 6 must scope flow.erp_add_bps.* to quantitative-analyst's PARAMETERS_USED block"
    )


def test_research_company_includes_hg34_in_tier1_validation():
    """research-company.md §4.5/§4.6 must list HG-34 in the Tier-1 validation enumeration."""
    text = RESEARCH_COMPANY_PATH.read_text(encoding="utf-8")
    assert "HG-34" in text or "catalyst_modifier_composition_check" in text, (
        "research-company.md must reference HG-34 in the Tier-1 validation list"
    )


# ---------- strategic-analyst.md remains regime-blind (architectural invariant) ----------


def test_strategic_md_contains_no_flow_modifier_references():
    """strategic-analyst MUST NOT reference flow_modifier — regime-blind by design."""
    text = STRATEGIC_AGENT_PATH.read_text(encoding="utf-8")
    # Allow the word "flow" generally (e.g., "cashflow"), but reject flow_modifier or flow_signal_bin reads
    assert "flow_modifier" not in text, (
        "strategic-analyst.md must NOT reference flow_modifier (regime-blind invariant; v0.2 plan)"
    )
    assert "flow_signal_bin" not in text, (
        "strategic-analyst.md must NOT reference flow_signal_bin (regime-blind invariant)"
    )
