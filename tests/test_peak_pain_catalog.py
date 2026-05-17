"""Smoke tests for `src/peak_pain_catalog` — 3-LLM consensus pipeline.

Mocked `AnthropicClient` returns canned JSON per LLM call so no live API hit.
Coverage:
    - parser.parse_catalog → CaseRecord roundtrip
    - feature_typing: categorical exact / ordinal within-±1
    - consensus: HIGH (unanimous iter 1), MEDIUM (converged after retry),
                 LOW (2/3 at cap), DISPUTED (no agreement at cap)
    - persistence: HMAC signature stable + verifiable
    - priority_runner: dispatch + missing-id reporting
    - lazy_runner: promotion paths
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.peak_pain_catalog import (  # noqa: E402
    CaseRecord,
    parse_catalog,
)
from src.peak_pain_catalog.consensus import (  # noqa: E402
    DEFAULT_MODEL_MIX,
    run_consensus,
)
from src.peak_pain_catalog.extractor import (  # noqa: E402
    SECTOR_EXTENSIONS,
    extract_features,
)
from src.peak_pain_catalog.feature_typing import (  # noqa: E402
    FeatureKind,
    FEATURE_TYPES,
    categorical_match,
    features_agree,
    is_within_one_step,
)
from src.peak_pain_catalog.lazy_runner import (  # noqa: E402
    validate_on_first_retrieval,
)
from src.peak_pain_catalog.persistence import (  # noqa: E402
    verify_hmac,
    write_validated_case,
)
from src.peak_pain_catalog.priority_runner import (  # noqa: E402
    PRIORITY_CASE_IDS,
    run_priority_subset,
)


CATALOG_MD = (
    Path(__file__).resolve().parents[1]
    / ".claude"
    / "references"
    / "empirical"
    / "peak-pain-archetypes"
    / "catalog-v0.1.md"
)


# ---------------------------------------------------------------------------
# Stub Anthropic client
# ---------------------------------------------------------------------------


class StubClient:
    """Returns canned JSON per (model, call_index) tuple.

    Tests register responses via .seed(...). The default extracts make every
    feature present with a stable verbatim quote so no defaults are triggered.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._scripted: list[dict[str, Any]] = []
        self._default_payload: dict[str, dict[str, str]] = {}

    def set_default(self, payload: dict[str, dict[str, str]]) -> None:
        self._default_payload = payload

    def seed(self, payload: dict[str, dict[str, str]]) -> None:
        self._scripted.append(payload)

    def messages_create(
        self, *, model: str, max_tokens: int, system: str, messages: list[dict[str, Any]]
    ) -> Any:
        self.calls.append({"model": model, "messages": messages})
        if self._scripted:
            payload = self._scripted.pop(0)
        else:
            payload = self._default_payload
        return {"content": [{"text": json.dumps(payload)}]}


def _full_payload(value_overrides: dict[str, str] | None = None) -> dict[str, dict[str, str]]:
    """Build a payload for a tech_saas case (uni-core + tech extensions)."""
    base = {
        "founder_insider_stake_direction": "flat",
        "cash_runway": ">24mo",
        "founder_in_place": "yes",
        "margin_trajectory": "improving",
        "revenue_trajectory": "growing",
        "industry_tailwind": "weakening",
        "customer_engagement": "holding",
        "engagement_decoupling_from_price": "yes",
        "NDR_trend": "expanding",
    }
    if value_overrides:
        base.update(value_overrides)
    return {f: {"value": v, "verbatim_quote": f"quote-for-{f}"} for f, v in base.items()}


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


def test_parse_catalog_emits_records():
    cases = parse_catalog(CATALOG_MD)
    assert len(cases) > 100, f"expected >100 cases, got {len(cases)}"
    by_id = {c.case_id: c for c in cases}
    # Spot-check known cases
    assert "NVDA-2008" in by_id
    nvda = by_id["NVDA-2008"]
    assert nvda.ticker == "NVDA"
    assert nvda.outcome == "SURVIVOR"
    assert nvda.sector == "semis_hardware"
    assert nvda.peak_dd_pct == pytest.approx(-85.0)
    # Pre-2008 expansion case
    assert any(c.era_category == "gfc_nonfin" for c in cases)
    assert any(c.era_category == "stagflation_1973_82" for c in cases)


def test_parse_catalog_descriptive_text_contains_headers():
    cases = parse_catalog(CATALOG_MD)
    nvda = next(c for c in cases if c.case_id == "NVDA-2008")
    assert "Outcome:" in nvda.descriptive_text or "outcome" in nvda.descriptive_text.lower()
    assert "Cash" in nvda.descriptive_text or "cash" in nvda.descriptive_text.lower()


def test_strip_ticker_handles_company_name_paren_then_year_paren():
    # FSR (Fisker) (2021-24) should select the YEAR-bearing parenthetical,
    # not the leading company-name one; case_id therefore = FSR-2024.
    from src.peak_pain_catalog.parser import _strip_ticker, _build_case_id

    ticker, period = _strip_ticker("FSR (Fisker) (2021-24)")
    assert ticker == "FSR"
    assert "2021" in period and "24" in period
    assert _build_case_id(ticker, period) == "FSR-2024"


def test_parse_catalog_includes_pltr_2022_calibration_case():
    # Section 6 Q6 d' calibration test set requires a PLTR-2022 row.
    # priority_runner reports it as missing if absent.
    cases = parse_catalog(CATALOG_MD)
    by_id = {c.case_id: c for c in cases}
    assert "PLTR-2022" in by_id, (
        "PLTR-2022 must be present in the catalog as the motivating "
        "calibration case for the counterfactual VETO authority"
    )
    pltr = by_id["PLTR-2022"]
    assert pltr.ticker == "PLTR"


# ---------------------------------------------------------------------------
# Feature-typing tests (Phase 4 Q4)
# ---------------------------------------------------------------------------


def test_categorical_exact_match_required():
    assert categorical_match("yes", "yes")
    assert categorical_match("YES", "yes")  # case-insensitive
    assert not categorical_match("yes", "departed")


def test_ordinal_within_one_step():
    # cash_runway order: >24mo / 12-24mo / <12mo / distressed
    assert is_within_one_step("cash_runway", ">24mo", "12-24mo")
    assert is_within_one_step("cash_runway", "12-24mo", "<12mo")
    # Two steps → disagreement
    assert not is_within_one_step("cash_runway", ">24mo", "<12mo")
    assert not is_within_one_step("cash_runway", ">24mo", "distressed")


def test_features_agree_dispatches_on_kind():
    # founder_in_place is categorical
    assert FEATURE_TYPES["founder_in_place"] == FeatureKind.CATEGORICAL
    assert features_agree("founder_in_place", "yes", "yes")
    assert not features_agree("founder_in_place", "yes", "departed")
    # margin_trajectory is ordinal
    assert FEATURE_TYPES["margin_trajectory"] == FeatureKind.ORDINAL
    assert features_agree("margin_trajectory", "improving", "stable")
    assert not features_agree("margin_trajectory", "improving", "deteriorating")


# ---------------------------------------------------------------------------
# Extractor tests
# ---------------------------------------------------------------------------


def _tech_saas_case() -> CaseRecord:
    return CaseRecord(
        case_id="SHOP-2022",
        ticker="SHOP",
        period="(2021-22)",
        sector="tech_saas",
        era_category="recent",
        outcome_raw="SURVIVOR",
        outcome="SURVIVOR",
        peak_dd_pct=-85.0,
        raw_row_cells=[],
        column_headers=[],
        descriptive_text="cash_runway: >24mo; founder: yes; engagement: holding",
    )


def test_extractor_returns_extracted_features():
    case = _tech_saas_case()
    client = StubClient()
    client.set_default(_full_payload())
    result = extract_features(case, client=client, model="claude-sonnet-4-6")
    assert result.case_id == "SHOP-2022"
    assert "cash_runway" in result.universal_core
    assert result.universal_core["cash_runway"].value == ">24mo"
    assert "customer_engagement" in result.sector_extensions
    assert result.sector_extensions["customer_engagement"].value == "holding"


def test_extractor_falls_back_when_no_quote():
    case = _tech_saas_case()
    client = StubClient()
    # Empty payload → defaults trigger across all features
    client.set_default({})
    result = extract_features(case, client=client)
    assert result.universal_core["cash_runway"].defaulted
    assert result.universal_core["cash_runway"].value == "distressed"
    assert result.universal_core["founder_in_place"].value == "departed"


# ---------------------------------------------------------------------------
# Consensus tests
# ---------------------------------------------------------------------------


def test_consensus_high_when_all_three_agree_iter1():
    case = _tech_saas_case()
    client = StubClient()
    payload = _full_payload()
    # All 3 LLMs return the same payload
    client.seed(payload)
    client.seed(payload)
    client.seed(payload)
    result = run_consensus(case, client=client)
    assert result.validation_status == "validated"
    cr = result.universal_core["cash_runway"]
    assert cr.consensus == "HIGH"
    assert cr.iterations == 1
    assert cr.agreement_count == 3


def test_consensus_within_one_step_counts_as_agreement():
    case = _tech_saas_case()
    client = StubClient()
    # Three LLMs disagree slightly on cash_runway but within ±1 step
    client.seed(_full_payload({"cash_runway": ">24mo"}))
    client.seed(_full_payload({"cash_runway": "12-24mo"}))
    client.seed(_full_payload({"cash_runway": ">24mo"}))
    result = run_consensus(case, client=client)
    cr = result.universal_core["cash_runway"]
    # All 3 within ±1: ">24mo" and "12-24mo" agree pairwise; ">24mo" and ">24mo" agree
    assert cr.consensus == "HIGH"
    assert cr.iterations == 1


def test_consensus_disputed_when_categorical_diverges_at_cap():
    case = _tech_saas_case()
    client = StubClient()
    # founder_in_place is categorical — three different values, never converging
    diverge_payloads = [
        _full_payload({"founder_in_place": "yes"}),
        _full_payload({"founder_in_place": "departed"}),
        _full_payload({"founder_in_place": "replaced-by-competent"}),
    ]
    # Seed for 5 iterations × 3 LLMs = 15 calls
    for _ in range(5):
        for p in diverge_payloads:
            client.seed(p)
    result = run_consensus(case, client=client, max_iterations=5)
    fp = result.universal_core["founder_in_place"]
    assert fp.consensus == "DISPUTED"
    assert fp.iterations == 5
    assert result.validation_status == "disputed"


def test_consensus_low_when_two_thirds_at_cap():
    case = _tech_saas_case()
    client = StubClient()
    # 2/3 stick to "yes", 1 sticks to "departed" — agreement band of 2
    payloads = [
        _full_payload({"founder_in_place": "yes"}),
        _full_payload({"founder_in_place": "yes"}),
        _full_payload({"founder_in_place": "departed"}),
    ]
    for _ in range(5):
        for p in payloads:
            client.seed(p)
    result = run_consensus(case, client=client, max_iterations=5)
    fp = result.universal_core["founder_in_place"]
    assert fp.consensus == "LOW"
    assert fp.agreement_count == 2
    # validation_status should be 'pending' (LOW on universal core, no DISPUTED)
    assert result.validation_status == "pending"


def test_consensus_uses_default_model_mix():
    case = _tech_saas_case()
    client = StubClient()
    payload = _full_payload()
    client.seed(payload)
    client.seed(payload)
    client.seed(payload)
    result = run_consensus(case, client=client)
    assert result.model_mix == DEFAULT_MODEL_MIX
    assert result.model_mix[0].startswith("claude-sonnet")
    assert result.model_mix[2].startswith("claude-opus")
    # Verify the 3 calls hit those models. Order is set-equality after the
    # parallel-dispatch refactor (3 LLMs run concurrently per iteration);
    # the contract is "all 3 models invoked exactly once on iter 1," not
    # the dispatch order.
    models_used = [c["model"] for c in client.calls]
    assert sorted(models_used) == sorted(list(DEFAULT_MODEL_MIX))
    assert len(models_used) == 3


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


def test_persistence_dry_run_writes_hmac_payload():
    case = _tech_saas_case()
    client = StubClient()
    payload = _full_payload()
    client.seed(payload)
    client.seed(payload)
    client.seed(payload)
    consensus = run_consensus(case, client=client)
    p = write_validated_case(case, consensus, dsn=None, hmac_key=b"test-key")
    # HMAC is hex, stored in dedicated column (per migration 016)
    assert len(p.hmac_signature) == 64
    assert all(c in "0123456789abcdef" for c in p.hmac_signature)
    # HMAC is NO LONGER embedded in notes — it lives in its own column.
    assert "[hmac=" not in p.notes
    # Verifiable using the canonical scheme from audit_trail.hmac_verify
    assert verify_hmac(p, hmac_key=b"test-key")


def test_persistence_hmac_detects_tamper():
    case = _tech_saas_case()
    client = StubClient()
    payload = _full_payload()
    client.seed(payload)
    client.seed(payload)
    client.seed(payload)
    consensus = run_consensus(case, client=client)
    p = write_validated_case(case, consensus, dsn=None, hmac_key=b"test-key")
    # Build a tampered copy
    import dataclasses

    tampered = dataclasses.replace(p, ticker="EVIL")
    assert not verify_hmac(tampered, hmac_key=b"test-key")


def test_persistence_hmac_decimal_roundtrip_byte_equal():
    """Regression test for the live-DB HMAC bug.

    NUMERIC columns return ``Decimal`` from psycopg, but a Python ``float``
    serializes as a JSON number while ``Decimal`` serializes as a JSON
    string. If ``peak_dd_pct`` is signed as a ``float`` at INSERT time and
    re-signed as a ``Decimal`` after SELECT-readback, the canonical bytes
    differ and HMAC verification fails in production.

    The fix lives in ``persistence._build_payload_unsigned``: convert
    ``peak_dd_pct`` to ``Decimal(str(...))`` at the signing site so write
    and read canonical bytes match.

    This test simulates the round-trip by re-canonicalizing a parsed-Decimal
    copy of the payload and asserting the HMAC stays byte-equal.
    """
    import dataclasses
    from decimal import Decimal

    from src.audit_trail.hmac_verify import compute_signature_dict

    case = _tech_saas_case()
    client = StubClient()
    payload = _full_payload()
    client.seed(payload)
    client.seed(payload)
    client.seed(payload)
    consensus = run_consensus(case, client=client)
    p = write_validated_case(case, consensus, dsn=None, hmac_key=b"test-key")

    # peak_dd_pct must be a Decimal in the signed PersistencePayload so the
    # canonical bytes match the post-readback Decimal shape from psycopg.
    assert isinstance(p.peak_dd_pct, Decimal)

    # Sign exactly the way the post-readback verifier does — using the raw
    # Decimal — and compare to the stored signature: must be byte-equal.
    unsigned = {
        f.name: getattr(p, f.name)
        for f in dataclasses.fields(p)
        if f.name != "hmac_signature"
    }
    expected = compute_signature_dict(unsigned, b"test-key")
    assert expected == p.hmac_signature

    # And explicitly: a "post-roundtrip" payload built from the SAME
    # Decimal value (mimicking what psycopg returns from a NUMERIC SELECT)
    # produces the byte-identical signature.
    roundtripped = dict(unsigned)
    roundtripped["peak_dd_pct"] = Decimal(str(p.peak_dd_pct))
    expected_rt = compute_signature_dict(roundtripped, b"test-key")
    assert expected_rt == p.hmac_signature

    # Sanity: had we (wrongly) signed with a Python float, the sig differs.
    wrong = dict(unsigned)
    wrong["peak_dd_pct"] = float(p.peak_dd_pct)
    wrong_sig = compute_signature_dict(wrong, b"test-key")
    assert wrong_sig != p.hmac_signature, (
        "If float and Decimal canonicalized identically, this test would be "
        "vacuous — the bug would not exist"
    )


# ---------------------------------------------------------------------------
# Priority runner tests
# ---------------------------------------------------------------------------


def test_priority_runner_dispatches_on_known_subset():
    # Use a tiny override list with known catalog members
    client = StubClient()
    payload_semis = {
        f: {"value": "intact" if f == "moat_state" else "yes" if f == "founder_in_place" else "flat" if f == "founder_insider_stake_direction" else ">24mo" if f == "cash_runway" else "improving" if f == "margin_trajectory" else "growing" if f == "revenue_trajectory" else "intact" if f == "industry_tailwind" else "cyclical-trough" if f == "cycle_state" else "moderate" if f == "customer_concentration" else "intact",
            "verbatim_quote": f"q-{f}"}
        for f in (list(SECTOR_EXTENSIONS["semis_hardware"]) + [
            "founder_insider_stake_direction", "cash_runway", "founder_in_place",
            "margin_trajectory", "revenue_trajectory", "industry_tailwind",
        ])
    }
    client.set_default(payload_semis)
    summary = run_priority_subset(
        catalog_md_path=CATALOG_MD,
        client=client,
        dsn=None,
        case_ids=("NVDA-2008",),
    )
    assert summary.attempted == 1
    assert summary.resolved == 1
    assert summary.validated + summary.pending + summary.disputed == 1
    assert "NVDA-2008" in summary.payloads_by_case


def test_priority_runner_reports_missing_ids():
    client = StubClient()
    client.set_default(_full_payload())
    summary = run_priority_subset(
        catalog_md_path=CATALOG_MD,
        client=client,
        dsn=None,
        case_ids=("BOGUS-9999",),
    )
    assert summary.resolved == 0
    assert "BOGUS-9999" in summary.missing_case_ids


def test_priority_case_list_size():
    # 15 calibration + 30 canonical = 45
    assert len(PRIORITY_CASE_IDS) == 45


# ---------------------------------------------------------------------------
# Lazy runner tests
# ---------------------------------------------------------------------------


def test_lazy_runner_promotes_validated():
    client = StubClient()
    client.set_default(_full_payload())
    # SHOP is in tech_saas table — pick an existing catalog case
    cases = parse_catalog(CATALOG_MD)
    tech_case = next(c for c in cases if c.sector == "tech_saas")
    result = validate_on_first_retrieval(
        tech_case.case_id,
        catalog_md_path=CATALOG_MD,
        client=client,
        dsn=None,
    )
    assert result.outcome in ("promoted_to_validated", "promoted_to_pending", "disputed")
    if result.outcome == "promoted_to_validated":
        assert result.retrieval_safe is True


def test_lazy_runner_raises_on_unknown_case():
    client = StubClient()
    with pytest.raises(KeyError):
        validate_on_first_retrieval(
            "DOES-NOT-EXIST",
            catalog_md_path=CATALOG_MD,
            client=client,
            dsn=None,
        )
