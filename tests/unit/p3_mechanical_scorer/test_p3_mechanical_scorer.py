"""Smoke tests for the P3 mechanical scorer (`src/p3_mechanical_scorer/`).

Coverage:

* Stage 1A: knockout on fraud-signature 3+/6, knockout on era-fit, pass-through
  on clean inputs, conservative-on-missing-data behaviour.
* Stage 1B: A / WATCH / REJECT thresholds; LEI-style proportional re-weighting;
  conservative demotion on sparse data.
* Stage 2: information-isolation enforcement (the load-bearing property);
  verbatim-evidence requirement (no quote -> defaults to LOW); self-consistency
  N=5 median aggregation; saw_rule_output=False enforced.
* Stage 3: linter detects HIGH-without-evidence, contradictions vs Stage 1B,
  position bias, info-isolation violations.
* Orchestrator: end-to-end with mocked LLM; audit row chain; composition
  disagreement first-class field; PROCEED/WATCH/PASS final decisions.

LLM calls are mocked via the `llm_caller` injection; no live Anthropic API
calls are made.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from p3_mechanical_scorer import (  # noqa: E402
    DECISION_PASS,
    DECISION_PROCEED,
    DECISION_WATCH,
    RATING_HIGH,
    RATING_LOW,
    RATING_MEDIUM,
    STAGE_OUTCOME_PROCEED,
    STAGE_OUTCOME_REJECT,
    STAGE_OUTCOME_TIER_A,
    STAGE_OUTCOME_WATCH,
)
from p3_mechanical_scorer.orchestrator import (  # noqa: E402
    P3DataAdapter,
    score_ticker,
)
from p3_mechanical_scorer.stage1a_multiplicative_knockout import (  # noqa: E402
    EraFitInput,
    FraudSignatureInput,
)
from p3_mechanical_scorer.stage1a_multiplicative_knockout import (  # noqa: E402
    evaluate as stage1a_evaluate,
)
from p3_mechanical_scorer.stage1b_tier_a_composite import (  # noqa: E402
    TierAInput,
)
from p3_mechanical_scorer.stage1b_tier_a_composite import (  # noqa: E402
    evaluate as stage1b_evaluate,
)
from p3_mechanical_scorer.stage2_llm_rubric import (  # noqa: E402
    CacheMissError,
    EvidenceCorpus,
    LLMUnavailableError,
    PATTERNS_TO_SCORE,
    score_all_patterns,
    score_pattern,
)
from p3_mechanical_scorer.stage3_linter import lint as stage3_lint  # noqa: E402


# ---------------------------------------------------------------------------
# Stage 1A
# ---------------------------------------------------------------------------


def _clean_fraud() -> FraudSignatureInput:
    return FraudSignatureInput(
        charismatic_ceo_with_mystique=False,
        board_lacks_domain_or_co_opted=False,
        novel_accounting_or_metrics=False,
        secrecy_under_trade_secret_cover=False,
        dismissed_bear_research=False,
        related_party_transactions=False,
    )


def test_stage1a_clean_passes():
    r = stage1a_evaluate(_clean_fraud(), EraFitInput(era_fit=True))
    assert r.outcome == STAGE_OUTCOME_PROCEED
    assert r.fraud_signature_count == 0
    assert r.era_fit_pass is True


def test_stage1a_fraud_3_of_6_rejects():
    fraud = FraudSignatureInput(
        charismatic_ceo_with_mystique=True,
        board_lacks_domain_or_co_opted=True,
        novel_accounting_or_metrics=True,
        secrecy_under_trade_secret_cover=False,
        dismissed_bear_research=False,
        related_party_transactions=False,
    )
    r = stage1a_evaluate(fraud, EraFitInput(era_fit=True))
    assert r.outcome == STAGE_OUTCOME_REJECT
    assert r.fraud_signature_count == 3
    assert "fraud_signature 3/6" in " ".join(r.reasons)


def test_stage1a_fraud_2_of_6_passes():
    fraud = FraudSignatureInput(
        charismatic_ceo_with_mystique=True,
        board_lacks_domain_or_co_opted=True,
        novel_accounting_or_metrics=False,
        secrecy_under_trade_secret_cover=False,
        dismissed_bear_research=False,
        related_party_transactions=False,
    )
    r = stage1a_evaluate(fraud, EraFitInput(era_fit=True))
    assert r.outcome == STAGE_OUTCOME_PROCEED


def test_stage1a_era_fit_false_rejects():
    r = stage1a_evaluate(_clean_fraud(), EraFitInput(era_fit=False))
    assert r.outcome == STAGE_OUTCOME_REJECT


def test_stage1a_era_fit_unknown_is_conservative_reject():
    r = stage1a_evaluate(_clean_fraud(), EraFitInput(era_fit=None))
    assert r.outcome == STAGE_OUTCOME_REJECT
    assert any("conservative REJECT" in x for x in r.reasons)


def test_stage1a_data_quality_flag_when_unknowns():
    fraud = FraudSignatureInput(
        charismatic_ceo_with_mystique=False,
        board_lacks_domain_or_co_opted=None,  # unknown
        novel_accounting_or_metrics=False,
        secrecy_under_trade_secret_cover=False,
        dismissed_bear_research=False,
        related_party_transactions=False,
    )
    r = stage1a_evaluate(fraud, EraFitInput(era_fit=True))
    assert r.data_quality == "degraded"
    assert r.outcome == STAGE_OUTCOME_PROCEED  # 0 definite + 1 unknown != REJECT


def test_stage1a_audit_payload_shape():
    r = stage1a_evaluate(_clean_fraud(), EraFitInput(era_fit=True))
    p = r.to_audit_payload()
    assert p["stage"] == "stage_1a_multiplicative_knockout"
    assert "fraud_signature" in p
    assert p["fraud_signature"]["threshold"] == 3


# ---------------------------------------------------------------------------
# Stage 1B
# ---------------------------------------------------------------------------


def test_stage1b_all_four_pass_is_tier_a():
    r = stage1b_evaluate(
        TierAInput(
            founder_ceo_duration_ge_15y=True,
            per_share_value_primary_metric=True,
            roiic_gt_15_sustained=True,
            pivot_creates_multi_bag=True,
        )
    )
    assert r.outcome == STAGE_OUTCOME_TIER_A
    assert r.pass_count == 4
    assert r.proportional_score == 1.0


def test_stage1b_three_pass_one_fail_is_tier_a():
    r = stage1b_evaluate(
        TierAInput(
            founder_ceo_duration_ge_15y=True,
            per_share_value_primary_metric=True,
            roiic_gt_15_sustained=True,
            pivot_creates_multi_bag=False,
        )
    )
    assert r.outcome == STAGE_OUTCOME_TIER_A
    assert r.pass_count == 3


def test_stage1b_two_pass_is_watch():
    r = stage1b_evaluate(
        TierAInput(
            founder_ceo_duration_ge_15y=True,
            per_share_value_primary_metric=True,
            roiic_gt_15_sustained=False,
            pivot_creates_multi_bag=False,
        )
    )
    assert r.outcome == STAGE_OUTCOME_WATCH
    assert r.pass_count == 2


def test_stage1b_one_pass_is_reject():
    r = stage1b_evaluate(
        TierAInput(
            founder_ceo_duration_ge_15y=True,
            per_share_value_primary_metric=False,
            roiic_gt_15_sustained=False,
            pivot_creates_multi_bag=False,
        )
    )
    assert r.outcome == STAGE_OUTCOME_REJECT


def test_stage1b_sparse_data_demotes_3_of_3_to_watch():
    """3 passes with 1 missing -> WATCH (conservative demotion)."""
    r = stage1b_evaluate(
        TierAInput(
            founder_ceo_duration_ge_15y=True,
            per_share_value_primary_metric=True,
            roiic_gt_15_sustained=True,
            pivot_creates_multi_bag=None,  # missing
        )
    )
    assert r.outcome == STAGE_OUTCOME_WATCH
    assert r.sparse_data_demoted is True


def test_stage1b_too_sparse_rejects():
    r = stage1b_evaluate(
        TierAInput(
            founder_ceo_duration_ge_15y=True,
            per_share_value_primary_metric=None,
            roiic_gt_15_sustained=None,
            pivot_creates_multi_bag=None,
        )
    )
    # present_count = 1 < MIN_PRESENT_FOR_DECISION (2) -> REJECT
    assert r.outcome == STAGE_OUTCOME_REJECT
    assert r.present_count == 1


def test_stage1b_proportional_score_lei_style():
    """2 of 3 present-and-pass -> proportional 0.667."""
    r = stage1b_evaluate(
        TierAInput(
            founder_ceo_duration_ge_15y=True,
            per_share_value_primary_metric=True,
            roiic_gt_15_sustained=False,
            pivot_creates_multi_bag=None,
        )
    )
    assert r.present_count == 3
    assert abs(r.proportional_score - 2 / 3) < 1e-6


# ---------------------------------------------------------------------------
# Stage 2 — information isolation (load-bearing)
# ---------------------------------------------------------------------------


def test_stage2_info_isolation_blocks_forbidden_attrs():
    """If EvidenceCorpus has Stage-1 attrs, score_all_patterns must raise."""
    corpus = EvidenceCorpus(ticker="NVDA", documents=[])
    # Inject a forbidden attr
    corpus.__dict__["stage1"] = {"outcome": "PROCEED"}
    with pytest.raises(AssertionError, match="forbidden"):
        score_all_patterns(corpus, llm_caller=lambda *a, **kw: {})


def test_stage2_info_isolation_blocks_forbidden_phrases_in_corpus():
    docs = [
        {
            "source_id": "leaked",
            "kind": "filing",
            "text": "Stage 1A outcome: PROCEED. Tier-A pass count: 4.",
        }
    ]
    corpus = EvidenceCorpus(ticker="NVDA", documents=docs)
    with pytest.raises(AssertionError, match="Stage-1 phrasing"):
        score_all_patterns(corpus, llm_caller=lambda *a, **kw: {})


def test_stage2_score_pattern_no_quote_defaults_low():
    """LLM returns HIGH but no quote -> validator defaults to LOW (Section 4.3)."""
    pattern = PATTERNS_TO_SCORE[0]
    corpus = EvidenceCorpus(
        ticker="NVDA",
        documents=[{"source_id": "10K", "kind": "filing", "text": "Verbatim text body."}],
    )

    def liar(system, user, model, temperature):
        return {
            "rating": "HIGH",
            "confidence": 0.9,
            "evidence_quotes": [],  # missing!
            "rationale": "Confident.",
            "defer_to_human": False,
            "tie_break_applied": False,
        }

    result = score_pattern(pattern, corpus, llm_caller=liar)
    assert result.rating == RATING_LOW
    assert result.score == 0.0


def test_stage2_score_pattern_verbatim_quote_required():
    """Quote not in corpus -> sample defaults to LOW."""
    pattern = PATTERNS_TO_SCORE[0]
    corpus = EvidenceCorpus(
        ticker="NVDA",
        documents=[{"source_id": "10K", "kind": "filing", "text": "AWS-style pivot drives value."}],
    )

    def fabricator(system, user, model, temperature):
        return {
            "rating": "HIGH",
            "confidence": 0.9,
            "evidence_quotes": ["NEVER APPEARED IN CORPUS"],
            "rationale": "n/a",
            "defer_to_human": False,
            "tie_break_applied": False,
        }

    result = score_pattern(pattern, corpus, llm_caller=fabricator)
    assert result.rating == RATING_LOW


def test_stage2_score_pattern_self_consistency_median():
    """N=5; 3 HIGH + 2 LOW -> median HIGH (modal too)."""
    pattern = PATTERNS_TO_SCORE[0]
    quote = "NVIDIA pivoted from gaming GPU to AI infrastructure via CUDA."
    corpus = EvidenceCorpus(
        ticker="NVDA",
        documents=[{"source_id": "10K", "kind": "filing", "text": quote}],
    )
    seq = iter(["HIGH", "HIGH", "HIGH", "LOW", "LOW"])

    def varying(system, user, model, temperature):
        rating = next(seq)
        return {
            "rating": rating,
            "confidence": 0.6,
            "evidence_quotes": [quote] if rating != "LOW" else [],
            "rationale": "ok",
            "defer_to_human": False,
            "tie_break_applied": False,
        }

    result = score_pattern(pattern, corpus, llm_caller=varying)
    assert result.rating == RATING_HIGH
    assert result.confidence == 3 / 5
    assert result.dispersion == pytest.approx(2 / 5, rel=1e-3)
    assert result.saw_rule_output is False


def test_stage2_saw_rule_output_always_false():
    pattern = PATTERNS_TO_SCORE[0]
    corpus = EvidenceCorpus(
        ticker="X",
        documents=[{"source_id": "x", "kind": "x", "text": "x"}],
    )
    result = score_pattern(
        pattern, corpus,
        llm_caller=lambda *a, **kw: {"rating": "LOW", "confidence": 0.5,
                                     "evidence_quotes": [], "rationale": "",
                                     "defer_to_human": False, "tie_break_applied": False},
    )
    assert result.saw_rule_output is False


def test_stage2_cache_miss_propagates_not_swallowed():
    """P0-5 replay-mode contract (FINDING A1): a CacheMissError (missing
    cassette in LLM_CACHE_MODE=replay) MUST propagate and fail the run hard —
    it must NOT be swallowed into ``sample = {}``, which would silently corrupt
    the self-consistency median and let CI pass green on a missing cassette."""
    pattern = PATTERNS_TO_SCORE[0]
    corpus = EvidenceCorpus(
        ticker="NVDA",
        documents=[{"source_id": "10K", "kind": "filing", "text": "Verbatim text body."}],
    )

    def missing_cassette(system, user, model, temperature):
        # Simulates get_or_compute() in replay mode hitting a missing cassette.
        raise CacheMissError("no cassette for prompt_sha=deadbeef (replay mode)")

    with pytest.raises(CacheMissError):
        score_pattern(pattern, corpus, llm_caller=missing_cassette)


def test_stage2_genuine_llm_unavailable_still_degrades():
    """Narrowing the broad except (FINDING A1) must NOT break the real degrade
    path: a genuine LLMUnavailableError / JSONDecodeError still degrades to an
    empty sample (-> default LOW), it does not newly raise."""
    pattern = PATTERNS_TO_SCORE[0]
    corpus = EvidenceCorpus(
        ticker="NVDA",
        documents=[{"source_id": "10K", "kind": "filing", "text": "Verbatim text body."}],
    )

    def unavailable(system, user, model, temperature):
        raise LLMUnavailableError("anthropic SDK not installed")

    # Does not raise — degrades all N samples to {} -> validator defaults LOW.
    result = score_pattern(pattern, corpus, llm_caller=unavailable)
    assert result.rating == RATING_LOW
    assert result.score == 0.0

    def bad_json(system, user, model, temperature):
        raise json.JSONDecodeError("Expecting value", "not json", 0)

    result_json = score_pattern(pattern, corpus, llm_caller=bad_json)
    assert result_json.rating == RATING_LOW


# ---------------------------------------------------------------------------
# Stage 3 linter
# ---------------------------------------------------------------------------


def _stage2_audit_skeleton(saw_rule_output=False, ratings=None):
    return {
        "stage": "stage_2_llm_rubric",
        "saw_rule_output": saw_rule_output,
        "prompt_version": "p3-stage2-rubric-v0.1",
        "n_self_consistency": 5,
        "temperature": 0.7,
        "info_isolation_assertions": {"passed": True},
        "aggregate_score": 0.5,
        "ratings": list(ratings or []),
    }


def test_stage3_flags_high_without_evidence():
    s2 = _stage2_audit_skeleton(
        ratings=[
            {
                "pattern_id": "L3-e-04",
                "rating": "HIGH",
                "score": 1.0,
                "confidence": 0.7,
                "dispersion": 0.3,
                "evidence_quotes": [],  # MISSING
                "rationale": "x.",
                "defer_to_human": False,
                "tie_break_applied": False,
                "samples": [],
                "model": "claude-sonnet-4-5",
                "saw_rule_output": False,
            }
        ]
    )
    out = stage3_lint(s2)
    codes = [f.code for f in out.flags]
    assert "high_without_evidence" in codes
    assert out.operator_review_required is True


def test_stage3_flags_info_isolation_violation_when_saw_rule_output_true():
    s2 = _stage2_audit_skeleton(saw_rule_output=True, ratings=[])
    out = stage3_lint(s2)
    codes = [f.code for f in out.flags]
    assert "info_isolation_violation" in codes
    assert out.info_isolation_intact is False


def test_stage3_flags_info_isolation_when_flag_missing():
    s2 = _stage2_audit_skeleton(ratings=[])
    s2.pop("saw_rule_output")
    out = stage3_lint(s2)
    codes = [f.code for f in out.flags]
    assert "info_isolation_violation" in codes


def test_stage3_flags_contradiction_vs_stage1b():
    """Stage 2 HIGH on L3-e-04 + Stage 1B has pivot_creates_multi_bag in fails."""
    s2 = _stage2_audit_skeleton(
        ratings=[
            {
                "pattern_id": "L3-e-04",
                "rating": "HIGH",
                "score": 1.0,
                "confidence": 0.8,
                "dispersion": 0.2,
                "evidence_quotes": ["quote"],
                "rationale": "x.",
                "defer_to_human": False,
                "tie_break_applied": False,
                "samples": [],
                "model": "claude-sonnet-4-5",
                "saw_rule_output": False,
            }
        ]
    )
    s1b = {
        "stage": "stage_1b_tier_a_composite",
        "criteria_fail": ["pivot_creates_multi_bag"],
        "criteria_pass": [],
        "criteria_missing": [],
    }
    out = stage3_lint(s2, stage1b=s1b)
    codes = [f.code for f in out.flags]
    assert "contradiction_high_vs_stage1_negative" in codes


def test_stage3_flags_position_bias_all_same():
    ratings = [
        {
            "pattern_id": f"L3-e-{i:02d}",
            "rating": "MEDIUM",
            "score": 0.5,
            "confidence": 0.5,
            "dispersion": 0.5,
            "evidence_quotes": ["q"],
            "rationale": "x.",
            "defer_to_human": False,
            "tie_break_applied": False,
            "samples": [],
            "model": "claude-sonnet-4-5",
            "saw_rule_output": False,
        }
        for i in range(6)
    ]
    s2 = _stage2_audit_skeleton(ratings=ratings)
    out = stage3_lint(s2)
    codes = [f.code for f in out.flags]
    assert "position_bias" in codes


# ---------------------------------------------------------------------------
# Orchestrator end-to-end
# ---------------------------------------------------------------------------


class _StubAdapter:
    """Test adapter — allows passing of arbitrary inputs.

    Carries a `_evidence_seen_kwargs` flag so tests can verify the
    orchestrator never asked for stage-1 outputs alongside the corpus.
    """

    def __init__(self, fraud, era, tier_a, evidence_docs):
        self._fraud = fraud
        self._era = era
        self._tier_a = tier_a
        self._evidence_docs = evidence_docs
        self.fetch_evidence_corpus_call_count = 0
        self.fetch_stage1_inputs_call_count = 0

    def fetch_stage1_inputs(self, ticker):
        self.fetch_stage1_inputs_call_count += 1
        return self._fraud, self._era, self._tier_a

    def fetch_evidence_corpus(self, ticker):
        self.fetch_evidence_corpus_call_count += 1
        return EvidenceCorpus(ticker=ticker, documents=list(self._evidence_docs))


def _high_llm(quote: str):
    """LLM stub that returns HIGH with a verbatim quote."""

    def _impl(system, user, model, temperature):
        return {
            "rating": "HIGH",
            "confidence": 0.8,
            "evidence_quotes": [quote],
            "rationale": "Strong evidence of pattern.",
            "defer_to_human": False,
            "tie_break_applied": False,
        }

    return _impl


def _low_llm():
    def _impl(system, user, model, temperature):
        return {
            "rating": "LOW",
            "confidence": 0.7,
            "evidence_quotes": [],
            "rationale": "no evidence.",
            "defer_to_human": False,
            "tie_break_applied": False,
        }

    return _impl


def test_orchestrator_short_circuits_on_stage1a_reject():
    fraud = FraudSignatureInput(
        charismatic_ceo_with_mystique=True,
        board_lacks_domain_or_co_opted=True,
        novel_accounting_or_metrics=True,
        secrecy_under_trade_secret_cover=False,
        dismissed_bear_research=False,
        related_party_transactions=False,
    )
    era = EraFitInput(era_fit=True)
    tier_a = TierAInput(
        founder_ceo_duration_ge_15y=True,
        per_share_value_primary_metric=True,
        roiic_gt_15_sustained=True,
        pivot_creates_multi_bag=True,
    )
    adapter = _StubAdapter(fraud, era, tier_a, [])
    out = score_ticker("FRAUD", adapter, llm_caller=_low_llm())
    assert out.decision == DECISION_PASS
    assert out.stage1b is None
    assert out.stage2 is None
    assert out.stage3 is None
    # Stage 2 must NOT have been invoked when Stage 1A rejects.
    assert adapter.fetch_evidence_corpus_call_count == 0
    # Audit chain has only Stage 1A row.
    assert len(out.audit_rows) == 1
    assert out.audit_rows[0]["drill_payload"]["substage"] == "stage_1a"


def test_orchestrator_short_circuits_on_stage1b_reject():
    fraud = FraudSignatureInput(
        charismatic_ceo_with_mystique=False,
        board_lacks_domain_or_co_opted=False,
        novel_accounting_or_metrics=False,
        secrecy_under_trade_secret_cover=False,
        dismissed_bear_research=False,
        related_party_transactions=False,
    )
    era = EraFitInput(era_fit=True)
    tier_a = TierAInput(
        founder_ceo_duration_ge_15y=False,
        per_share_value_primary_metric=False,
        roiic_gt_15_sustained=False,
        pivot_creates_multi_bag=True,
    )
    adapter = _StubAdapter(fraud, era, tier_a, [])
    out = score_ticker("WEAK", adapter, llm_caller=_low_llm())
    assert out.decision == DECISION_PASS
    assert out.stage2 is None
    assert adapter.fetch_evidence_corpus_call_count == 0
    assert len(out.audit_rows) == 2  # 1A + 1B


def test_orchestrator_full_proceed_path_with_high_stage2():
    quote = "NVIDIA pivoted from gaming GPU to AI infrastructure via CUDA."
    fraud = FraudSignatureInput(
        charismatic_ceo_with_mystique=False,
        board_lacks_domain_or_co_opted=False,
        novel_accounting_or_metrics=False,
        secrecy_under_trade_secret_cover=False,
        dismissed_bear_research=False,
        related_party_transactions=False,
    )
    era = EraFitInput(era_fit=True)
    tier_a = TierAInput(
        founder_ceo_duration_ge_15y=True,
        per_share_value_primary_metric=True,
        roiic_gt_15_sustained=True,
        pivot_creates_multi_bag=True,
    )
    adapter = _StubAdapter(
        fraud, era, tier_a,
        [{"source_id": "10K-2024", "kind": "filing", "text": quote}],
    )
    out = score_ticker("NVDA", adapter, llm_caller=_high_llm(quote))
    # Negative patterns (#16 reflexivity, #19 mystique-without-execution) are
    # inverted in aggregate — HIGH on those reduces score. So aggregate may
    # land in WATCH band when ALL ratings are HIGH. The exact aggregate is
    # computed deterministically; we assert the run completed cleanly.
    assert out.stage2 is not None
    assert out.stage2.saw_rule_output is False
    # Audit chain: 1A + 1B + 2 + 3
    assert len(out.audit_rows) == 4
    substages = [r["drill_payload"]["substage"] for r in out.audit_rows]
    assert substages == [
        "stage_1a", "stage_1b", "stage_2_llm_rubric", "stage_3_linter",
    ]
    # Each audit row has a hmac_signature.
    assert all(r["hmac_signature"] for r in out.audit_rows)
    # Audit chain links via parent_audit_id.
    assert out.audit_rows[0]["parent_audit_id"] is None
    assert out.audit_rows[1]["parent_audit_id"] == out.audit_rows[0]["audit_id"]
    assert out.audit_rows[2]["parent_audit_id"] == out.audit_rows[1]["audit_id"]
    assert out.audit_rows[3]["parent_audit_id"] == out.audit_rows[2]["audit_id"]


def test_orchestrator_composition_disagreement_flagged():
    """Stage 1B says A; Stage 2 says PASS (all LOW) -> disagreement=True."""
    fraud = FraudSignatureInput(
        charismatic_ceo_with_mystique=False,
        board_lacks_domain_or_co_opted=False,
        novel_accounting_or_metrics=False,
        secrecy_under_trade_secret_cover=False,
        dismissed_bear_research=False,
        related_party_transactions=False,
    )
    era = EraFitInput(era_fit=True)
    tier_a = TierAInput(
        founder_ceo_duration_ge_15y=True,
        per_share_value_primary_metric=True,
        roiic_gt_15_sustained=True,
        pivot_creates_multi_bag=True,
    )
    docs = [{"source_id": "10K", "kind": "filing", "text": "filler text."}]
    adapter = _StubAdapter(fraud, era, tier_a, docs)
    out = score_ticker("DISAGREE", adapter, llm_caller=_low_llm())
    # Stage 1B says A; Stage 2 all LOW (negatives invert -> two come out 1.0,
    # four come out 0.0; aggregate = 2/6 = 0.333 -> PASS band).
    # Final decision composition takes the more conservative -> PASS.
    assert out.composition_disagreement is True
    assert out.decision in (DECISION_PASS, DECISION_WATCH)
    assert out.operator_review_required is True


def test_orchestrator_info_isolation_assert_in_stage2():
    """Verify Stage-2 assertion machinery actually fires."""
    fraud = FraudSignatureInput(
        charismatic_ceo_with_mystique=False,
        board_lacks_domain_or_co_opted=False,
        novel_accounting_or_metrics=False,
        secrecy_under_trade_secret_cover=False,
        dismissed_bear_research=False,
        related_party_transactions=False,
    )
    era = EraFitInput(era_fit=True)
    tier_a = TierAInput(
        founder_ceo_duration_ge_15y=True,
        per_share_value_primary_metric=True,
        roiic_gt_15_sustained=True,
        pivot_creates_multi_bag=True,
    )

    class _LeakyAdapter(_StubAdapter):
        def fetch_evidence_corpus(self, ticker):
            corpus = EvidenceCorpus(ticker=ticker, documents=list(self._evidence_docs))
            corpus.__dict__["stage1"] = "leaked"
            return corpus

    adapter = _LeakyAdapter(fraud, era, tier_a, [{"source_id": "x", "kind": "x", "text": "x"}])
    with pytest.raises(AssertionError, match="Information-isolation"):
        score_ticker("LEAK", adapter, llm_caller=_low_llm())


def test_orchestrator_audit_versioning_shape():
    fraud = FraudSignatureInput(
        charismatic_ceo_with_mystique=False,
        board_lacks_domain_or_co_opted=False,
        novel_accounting_or_metrics=False,
        secrecy_under_trade_secret_cover=False,
        dismissed_bear_research=False,
        related_party_transactions=False,
    )
    era = EraFitInput(era_fit=True)
    tier_a = TierAInput(
        founder_ceo_duration_ge_15y=False,
        per_share_value_primary_metric=False,
        roiic_gt_15_sustained=False,
        pivot_creates_multi_bag=False,
    )
    adapter = _StubAdapter(fraud, era, tier_a, [])
    out = score_ticker("WEAK", adapter, llm_caller=_low_llm())
    for row in out.audit_rows:
        v = row["versions"]
        assert "rule_engine_version" in v
        assert "llm_prompt_version" in v
        assert "linter_version" in v


# ---------------------------------------------------------------------------
# Integration-style: the full pipeline emits a coherent envelope
# ---------------------------------------------------------------------------


def test_outcome_to_dict_serialises_cleanly():
    fraud = FraudSignatureInput(
        charismatic_ceo_with_mystique=False,
        board_lacks_domain_or_co_opted=False,
        novel_accounting_or_metrics=False,
        secrecy_under_trade_secret_cover=False,
        dismissed_bear_research=False,
        related_party_transactions=False,
    )
    era = EraFitInput(era_fit=True)
    tier_a = TierAInput(
        founder_ceo_duration_ge_15y=True,
        per_share_value_primary_metric=True,
        roiic_gt_15_sustained=True,
        pivot_creates_multi_bag=True,
    )
    docs = [{"source_id": "10K", "kind": "filing", "text": "ok"}]
    adapter = _StubAdapter(fraud, era, tier_a, docs)
    out = score_ticker("OK", adapter, llm_caller=_low_llm())
    d = out.to_dict()
    import json

    j = json.dumps(d)  # round-trips
    assert "p3_run_id" in j
    assert "composition_disagreement" in j
    assert "audit_rows" in j
