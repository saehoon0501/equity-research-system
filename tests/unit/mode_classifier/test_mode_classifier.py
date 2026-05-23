"""Smoke tests for the mode_classifier package.

Tests cover each stage with mocks — no DB I/O, no live LLM, no
network. The orchestrator is exercised in ``persist=False`` mode
with injected adapters and a fake LLM client.

Layered to mirror the package structure:

* Stage 1 — pure rule, no I/O. Test boundary cases per Section 2.2.
* Stage 2 — pure rule, no I/O. Test HIGH/STANDARD per bin.
* Stage 3 — LLM tie-breaker. Test schema validation, verbatim evidence,
  self-consistency aggregation, conservative tie-break, malformed JSON.
* Orchestrator — end-to-end with persist=False.
* Recheck — function shape only (DB-touching paths smoke-test only).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Mirror the sys.path trick used by tests/test_edgar.py et al.: the
# package lives at src/mode_classifier/ and tests run from repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from mode_classifier import (
    MODE_B,
    MODE_B_PRIME,
    MODE_C,
    QUALITY_HIGH,
    QUALITY_STANDARD,
    METHOD_LLM,
    METHOD_RULE,
)
from mode_classifier.adapters import (
    QualityFacts,
    StructuralFacts,
)
from mode_classifier.orchestrator import classify_ticker
from mode_classifier.stage1_market_structural import classify as s1_classify
from mode_classifier.stage2_company_quality import classify as s2_classify
from mode_classifier.stage3_overlap_tiebreaker import (
    LLMUnavailableError,
    _aggregate,
    _validate_payload,
    tiebreaker as s3_tiebreaker,
    TiebreakerSample,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _facts(**overrides: Any) -> StructuralFacts:
    base: dict[str, Any] = {
        "market_cap_usd": 100e9,
        "realized_vol_252d": 0.20,
        "profitable_consecutive_years": 10,
        "revenue_growth_yoy": 0.08,
        "narrative_driven": False,
        "as_of_date": "2024-12-31",
    }
    base.update(overrides)
    return StructuralFacts(**base)


def _qfacts(**overrides: Any) -> QualityFacts:
    base: dict[str, Any] = {
        "founder_tenure_years": 12.0,
        "roiic_5yr_avg": 0.20,
        "profitability_path_clear": True,
        "as_of_date": "2024-12-31",
    }
    base.update(overrides)
    return QualityFacts(**base)


# --------------------------------------------------------------------------- #
# Stage 1                                                                     #
# --------------------------------------------------------------------------- #


class TestStage1:
    def test_clean_b_match(self) -> None:
        # KO-shape: $300B, 18% vol, 30y profitable, 5% growth
        r = s1_classify(
            _facts(
                market_cap_usd=300e9,
                realized_vol_252d=0.18,
                profitable_consecutive_years=30,
                revenue_growth_yoy=0.05,
            )
        )
        assert r.b_match
        assert not r.b_prime_match
        assert not r.c_match
        assert not r.overlap_detected
        assert r.provisional_bin == MODE_B

    def test_clean_b_prime_match(self) -> None:
        # NVDA-shape: $2T, 45% vol, profitable 10y, 60% growth
        r = s1_classify(
            _facts(
                market_cap_usd=2_000e9,
                realized_vol_252d=0.45,
                profitable_consecutive_years=10,
                revenue_growth_yoy=0.60,
            )
        )
        assert not r.b_match
        assert r.b_prime_match
        assert not r.c_match
        assert r.provisional_bin == MODE_B_PRIME

    def test_clean_c_match_small_cap(self) -> None:
        r = s1_classify(_facts(market_cap_usd=10e9))
        assert r.c_match
        assert r.provisional_bin == MODE_C

    def test_clean_c_match_unprofitable(self) -> None:
        r = s1_classify(
            _facts(
                market_cap_usd=80e9,
                profitable_consecutive_years=0,
            )
        )
        assert r.c_match
        assert r.provisional_bin == MODE_C

    def test_narrative_driven_forces_c(self) -> None:
        r = s1_classify(_facts(narrative_driven=True))
        assert r.c_match
        # B is not affected by narrative_driven, so this is overlap.
        assert r.b_match
        assert r.overlap_detected

    def test_overlap_no_rule_fires(self) -> None:
        # $60B, 22% vol, profitable 6y, 13% growth -- not <12% (B),
        # not (vol>25% or growth>15%) (B'), not <$50B (C). All three False.
        r = s1_classify(
            _facts(
                market_cap_usd=60e9,
                realized_vol_252d=0.22,
                profitable_consecutive_years=6,
                revenue_growth_yoy=0.13,
            )
        )
        assert not r.b_match
        assert not r.b_prime_match
        assert not r.c_match
        assert r.overlap_detected
        assert r.provisional_bin is None

    def test_missing_data_forces_overlap(self) -> None:
        r = s1_classify(_facts(market_cap_usd=None))
        assert r.overlap_detected

    def test_to_rule_outcomes_shape(self) -> None:
        r = s1_classify(_facts())
        out = r.to_rule_outcomes()
        for k in ("B_match", "B_prime_match", "C_match", "overlap_detected"):
            assert k in out

    # --------------------------------------------------------------------- #
    # Boundary tests — exact-threshold semantics (Section 2.2 lines 106-109)
    #
    # Spec uses STRICT inequalities throughout Stage 1:
    #   B  : market_cap > $50B AND vol < 25% AND profitable > 5y AND growth < 12%
    #   B' : market_cap > $50B AND profitable AND (vol > 25% OR growth > 15%)
    #   C  : market_cap < $50B OR not-yet-profitable OR narrative-driven
    # Boundary semantics chosen:
    #   - At equality (e.g., cap == $50B), the rule does NOT fire — the
    #     name lands in overlap and routes to Stage 3.
    #   - profitable_consecutive_years is integer; the strict ">5" means
    #     5 fails, 6 passes for B.
    # --------------------------------------------------------------------- #

    def test_market_cap_at_threshold_50e9_overlaps(self) -> None:
        # cap == 50e9 fails B (>$50B), fails B' (>$50B), fails C (<$50B).
        # Result: overlap (no rule fires).
        r = s1_classify(
            _facts(
                market_cap_usd=50e9,
                realized_vol_252d=0.20,
                profitable_consecutive_years=10,
                revenue_growth_yoy=0.05,
            )
        )
        assert not r.b_match
        assert not r.b_prime_match
        assert not r.c_match
        assert r.overlap_detected
        assert r.provisional_bin is None

    def test_realized_vol_at_threshold_025_neither_b_nor_bprime(self) -> None:
        # vol == 0.25 fails B (vol<0.25) AND fails B' (vol>0.25). The B'
        # rule may still fire via the growth>15% disjunct; here growth is
        # 0.08 so neither vol nor growth triggers B'.
        r = s1_classify(
            _facts(
                market_cap_usd=200e9,
                realized_vol_252d=0.25,
                profitable_consecutive_years=10,
                revenue_growth_yoy=0.08,
            )
        )
        assert not r.b_match  # vol == 0.25 not < 0.25
        assert not r.b_prime_match  # vol == 0.25 not > 0.25, growth not > 0.15
        assert r.overlap_detected

    def test_growth_at_b_ceiling_012_fails_b(self) -> None:
        # growth == 0.12 fails B (<0.12). B' growth disjunct also fails
        # (growth not >0.15), so B' fires only if vol>0.25.
        r = s1_classify(
            _facts(
                market_cap_usd=200e9,
                realized_vol_252d=0.20,
                profitable_consecutive_years=10,
                revenue_growth_yoy=0.12,
            )
        )
        assert not r.b_match
        assert not r.b_prime_match
        assert not r.c_match
        assert r.overlap_detected

    def test_growth_at_b_prime_floor_015_fails_b_prime(self) -> None:
        # growth == 0.15 fails B' (>0.15). With vol < 0.25 and growth
        # < 0.12 also false, neither B nor B' fires.
        r = s1_classify(
            _facts(
                market_cap_usd=200e9,
                realized_vol_252d=0.20,
                profitable_consecutive_years=10,
                revenue_growth_yoy=0.15,
            )
        )
        assert not r.b_match  # growth not < 0.12
        assert not r.b_prime_match  # growth not > 0.15
        assert not r.c_match
        assert r.overlap_detected

    def test_profitable_at_b_floor_5_fails_b(self) -> None:
        # B requires >5 years (strict). 5 fails; 6 would pass.
        r = s1_classify(
            _facts(
                market_cap_usd=200e9,
                realized_vol_252d=0.18,
                profitable_consecutive_years=5,
                revenue_growth_yoy=0.05,
            )
        )
        assert not r.b_match  # 5 not > 5

    def test_profitable_just_above_floor_6_passes_b(self) -> None:
        # 6 satisfies "> 5y".
        r = s1_classify(
            _facts(
                market_cap_usd=200e9,
                realized_vol_252d=0.18,
                profitable_consecutive_years=6,
                revenue_growth_yoy=0.05,
            )
        )
        assert r.b_match


# --------------------------------------------------------------------------- #
# Stage 2                                                                     #
# --------------------------------------------------------------------------- #


class TestStage2:
    def test_high_b_passes_all_clauses(self) -> None:
        r = s2_classify(MODE_B, _qfacts())
        assert r.flag == QUALITY_HIGH

    def test_b_below_founder_tenure(self) -> None:
        r = s2_classify(MODE_B, _qfacts(founder_tenure_years=8.0))
        assert r.flag == QUALITY_STANDARD
        assert not r.founder_tenure_passed

    def test_b_below_roiic(self) -> None:
        r = s2_classify(MODE_B, _qfacts(roiic_5yr_avg=0.10))
        assert r.flag == QUALITY_STANDARD
        assert not r.roiic_passed

    def test_b_prime_relaxed_tenure(self) -> None:
        r = s2_classify(
            MODE_B_PRIME,
            _qfacts(founder_tenure_years=6.0, roiic_5yr_avg=None),
        )
        # B' has no ROIIC requirement; 5y founder threshold met.
        assert r.flag == QUALITY_HIGH

    def test_c_requires_path_clear(self) -> None:
        r = s2_classify(
            MODE_C,
            _qfacts(profitability_path_clear=False, roiic_5yr_avg=None),
        )
        assert r.flag == QUALITY_STANDARD

    def test_missing_data_biases_standard(self) -> None:
        r = s2_classify(
            MODE_B,
            _qfacts(founder_tenure_years=None, roiic_5yr_avg=None),
        )
        assert r.flag == QUALITY_STANDARD

    def test_unknown_bin_raises(self) -> None:
        with pytest.raises(ValueError):
            s2_classify("X", _qfacts())

    # --------------------------------------------------------------------- #
    # Stage 2 boundary tests — exact-threshold semantics
    #
    # Stage 2 uses INCLUSIVE inequalities (per stage2_company_quality.py):
    #   founder_tenure  : >= 10y for B, >= 5y for B'
    #   roiic_5yr       : > 15% (strict; B only)
    # Boundary semantics chosen:
    #   - founder_tenure == 10.0 PASSES for B (>=)
    #   - founder_tenure == 5.0 PASSES for B' (>=)
    #   - roiic_5yr == 0.15 FAILS for B (strict >); 0.1500001 would pass
    # --------------------------------------------------------------------- #

    def test_founder_tenure_at_b_threshold_10y_passes_high(self) -> None:
        # B requires >= 10y. 10.0 must pass.
        r = s2_classify(
            MODE_B,
            _qfacts(founder_tenure_years=10.0, roiic_5yr_avg=0.20),
        )
        assert r.flag == QUALITY_HIGH
        assert r.founder_tenure_passed

    def test_founder_tenure_just_below_b_threshold_99y_fails(self) -> None:
        r = s2_classify(
            MODE_B,
            _qfacts(founder_tenure_years=9.9, roiic_5yr_avg=0.20),
        )
        assert r.flag == QUALITY_STANDARD
        assert not r.founder_tenure_passed

    def test_founder_tenure_at_b_prime_threshold_5y_passes_high(self) -> None:
        # B' requires >= 5y. 5.0 must pass; ROIIC clause not required for B'.
        r = s2_classify(
            MODE_B_PRIME,
            _qfacts(founder_tenure_years=5.0, roiic_5yr_avg=None),
        )
        assert r.flag == QUALITY_HIGH

    def test_roiic_at_b_threshold_015_fails_strict_inequality(self) -> None:
        # B's "> 15%" is strict; 0.15 fails, 0.151 passes.
        r = s2_classify(
            MODE_B,
            _qfacts(founder_tenure_years=12.0, roiic_5yr_avg=0.15),
        )
        assert r.flag == QUALITY_STANDARD
        assert not r.roiic_passed

    def test_roiic_just_above_b_threshold_passes(self) -> None:
        r = s2_classify(
            MODE_B,
            _qfacts(founder_tenure_years=12.0, roiic_5yr_avg=0.1501),
        )
        assert r.flag == QUALITY_HIGH
        assert r.roiic_passed


# --------------------------------------------------------------------------- #
# Stage 3                                                                     #
# --------------------------------------------------------------------------- #


class _FakeContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [_FakeContent(text)]


class _FakeMessages:
    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)

    def create(self, **_kwargs: Any) -> _FakeMessage:
        if not self._texts:
            return _FakeMessage("")
        return _FakeMessage(self._texts.pop(0))


class _FakeClient:
    def __init__(self, texts: list[str]) -> None:
        self.messages = _FakeMessages(texts)


_EVIDENCE = (
    "ticker_as_of_date: 2024-12-31\n"
    "market_cap_usd: 60000000000.0\n"
    "realized_vol_252d: 0.22\n"
    "profitable_consecutive_years: 6\n"
    "revenue_growth_yoy: 0.13\n"
    "narrative_driven: False"
)


def _ok_payload(bin_: str, quote: str = "market_cap_usd: 60000000000.0") -> str:
    return json.dumps(
        {
            "bin": bin_,
            "confidence": 0.7,
            "rationale": f"Picked {bin_} based on cap+growth boundary.",
            "evidence_quotes": [quote],
        }
    )


class TestStage3Validation:
    def test_validate_ok(self) -> None:
        ok, reason = _validate_payload(
            json.loads(_ok_payload(MODE_B_PRIME)), _EVIDENCE
        )
        assert ok
        assert reason is None

    def test_validate_rejects_non_verbatim(self) -> None:
        bad = {
            "bin": MODE_B,
            "confidence": 0.9,
            "rationale": "x",
            "evidence_quotes": ["fabricated quote not in evidence"],
        }
        ok, reason = _validate_payload(bad, _EVIDENCE)
        assert not ok
        assert "non-verbatim" in (reason or "")

    def test_validate_rejects_empty_quotes(self) -> None:
        bad = {
            "bin": MODE_B,
            "confidence": 0.9,
            "rationale": "x",
            "evidence_quotes": [],
        }
        ok, reason = _validate_payload(bad, _EVIDENCE)
        assert not ok

    def test_validate_rejects_bad_bin(self) -> None:
        bad = {
            "bin": "Z",
            "confidence": 0.9,
            "rationale": "x",
            "evidence_quotes": ["market_cap_usd: 60000000000.0"],
        }
        ok, _ = _validate_payload(bad, _EVIDENCE)
        assert not ok


class TestStage3Aggregation:
    def test_modal_majority(self) -> None:
        samples = [
            TiebreakerSample(MODE_B_PRIME, 0.8, "r1", ["q"], "raw", True),
            TiebreakerSample(MODE_B_PRIME, 0.7, "r2", ["q"], "raw", True),
            TiebreakerSample(MODE_B_PRIME, 0.9, "r3", ["q"], "raw", True),
            TiebreakerSample(MODE_C, 0.5, "rC", ["q"], "raw", True),
            TiebreakerSample(MODE_B, 0.5, "rB", ["q"], "raw", True),
        ]
        bin_, share, _, _ = _aggregate(samples)
        assert bin_ == MODE_B_PRIME
        assert share == pytest.approx(3 / 5)

    def test_conservative_tiebreak(self) -> None:
        # 2-2-1 split B vs B' vs C — conservative tie picks the more
        # conservative of the *tied* bins (B_prime over B).
        samples = [
            TiebreakerSample(MODE_B, 0.8, "rB", ["q"], "raw", True),
            TiebreakerSample(MODE_B, 0.7, "rB", ["q"], "raw", True),
            TiebreakerSample(MODE_B_PRIME, 0.9, "rBp", ["q"], "raw", True),
            TiebreakerSample(MODE_B_PRIME, 0.6, "rBp", ["q"], "raw", True),
            TiebreakerSample(MODE_C, 0.5, "rC", ["q"], "raw", True),
        ]
        bin_, _, _, _ = _aggregate(samples)
        assert bin_ == MODE_B_PRIME

    def test_all_invalid_defaults_to_c(self) -> None:
        samples = [
            TiebreakerSample(MODE_C, 0.0, "x", [], "raw", False, "bad")
            for _ in range(5)
        ]
        bin_, share, _, _ = _aggregate(samples)
        assert bin_ == MODE_C
        assert share == 0.0


class TestStage3FullCall:
    def test_majority_b_prime(self) -> None:
        client = _FakeClient(
            [
                _ok_payload(MODE_B_PRIME),
                _ok_payload(MODE_B_PRIME),
                _ok_payload(MODE_B_PRIME),
                _ok_payload(MODE_C),
                _ok_payload(MODE_B),
            ]
        )
        result = s3_tiebreaker(
            ticker="ZZZ",
            evidence_block=_EVIDENCE,
            rule_outcomes={"B_match": True, "B_prime_match": True, "C_match": False, "overlap_detected": True},
            client=client,
        )
        assert result.bin == MODE_B_PRIME
        assert result.confidence == pytest.approx(0.6)
        payload = result.to_payload()
        assert payload["rating"] == MODE_B_PRIME
        assert payload["self_consistency"]["valid_samples"] == 5
        assert "n_samples" in payload["self_consistency"]

    def test_malformed_json_defaults_to_c(self) -> None:
        client = _FakeClient(["not json", "also not", "{", "{}", "garbage"])
        result = s3_tiebreaker(
            ticker="ZZZ",
            evidence_block=_EVIDENCE,
            rule_outcomes={},
            client=client,
        )
        assert result.bin == MODE_C
        assert result.confidence == 0.0

    def test_non_verbatim_quote_defaults_to_c(self) -> None:
        bad_payload = json.dumps(
            {
                "bin": MODE_B,
                "confidence": 0.99,
                "rationale": "claiming B",
                "evidence_quotes": ["This text is not in the evidence block"],
            }
        )
        client = _FakeClient([bad_payload] * 5)
        result = s3_tiebreaker(
            ticker="ZZZ",
            evidence_block=_EVIDENCE,
            rule_outcomes={},
            client=client,
        )
        # All samples invalid → conservative C, zero confidence.
        assert result.bin == MODE_C

    def test_llm_unavailable_when_no_sdk_and_no_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force LLMUnavailableError by removing API key & no client.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # We don't import anthropic in the test path because client=None
        # triggers _build_default_client which will fail on missing key
        # even if the SDK is installed.
        with pytest.raises(LLMUnavailableError):
            s3_tiebreaker(
                ticker="ZZZ",
                evidence_block=_EVIDENCE,
                rule_outcomes={},
                client=None,
            )


# --------------------------------------------------------------------------- #
# Orchestrator                                                                #
# --------------------------------------------------------------------------- #


class _StubDataAdapter:
    def __init__(self, facts: StructuralFacts) -> None:
        self._facts = facts

    def get_structural_facts(
        self, ticker: str, as_of: str
    ) -> StructuralFacts:
        return self._facts


class _StubQualityAdapter:
    def __init__(self, qfacts: QualityFacts) -> None:
        self._qfacts = qfacts

    def get_quality_facts(self, ticker: str, as_of: str) -> QualityFacts:
        return self._qfacts


class TestOrchestrator:
    def test_clean_rule_b_no_persist(self) -> None:
        outcome = classify_ticker(
            "KO",
            as_of="2024-12-31",
            data_adapter=_StubDataAdapter(
                _facts(
                    market_cap_usd=300e9,
                    realized_vol_252d=0.18,
                    profitable_consecutive_years=30,
                    revenue_growth_yoy=0.05,
                )
            ),
            quality_adapter=_StubQualityAdapter(_qfacts()),
            persist=False,
        )
        assert outcome.final_mode == MODE_B
        assert outcome.classification_method == METHOD_RULE
        assert outcome.company_quality_flag == QUALITY_HIGH
        assert outcome.llm_tiebreaker is None

    def test_overlap_routes_to_stage3(self) -> None:
        client = _FakeClient([_ok_payload(MODE_B_PRIME)] * 5)
        outcome = classify_ticker(
            "ZZZ",
            as_of="2024-12-31",
            data_adapter=_StubDataAdapter(
                _facts(
                    market_cap_usd=60e9,
                    realized_vol_252d=0.22,
                    profitable_consecutive_years=6,
                    revenue_growth_yoy=0.13,
                )
            ),
            quality_adapter=_StubQualityAdapter(
                _qfacts(founder_tenure_years=4.0)
            ),
            persist=False,
            llm_client=client,
        )
        assert outcome.final_mode == MODE_B_PRIME
        assert outcome.classification_method == METHOD_LLM
        assert outcome.llm_tiebreaker is not None
        assert outcome.llm_tiebreaker["rating"] == MODE_B_PRIME

    def test_overlap_with_no_llm_falls_back_pending(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        outcome = classify_ticker(
            "ZZZ",
            as_of="2024-12-31",
            data_adapter=_StubDataAdapter(
                _facts(
                    market_cap_usd=60e9,
                    realized_vol_252d=0.22,
                    profitable_consecutive_years=6,
                    revenue_growth_yoy=0.13,
                )
            ),
            quality_adapter=_StubQualityAdapter(_qfacts()),
            persist=False,
            llm_client=None,
        )
        assert outcome.classification_method == METHOD_RULE
        assert outcome.recheck_status == "pending_review"
        # Conservative C when no provisional bin available.
        assert outcome.final_mode == MODE_C
