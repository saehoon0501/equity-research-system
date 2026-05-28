"""WS-2 sophistication scorer unit tests (offline, no network).

All external dependencies (perplexity model, faithfulness LM, baseline
store) are injected as in-process fakes, so every test runs with NO
network and NO ML deps.

Covers the three WS-2 acceptance criteria:
  1. label-only / no-rationale input ABSTAINS (no silent number).
  2. intervention flags a post-hoc-rationalization fixture; scores are
     percentile-vs-rolling-baseline (relative).
  3. high-novelty + ungrounded fixture scores LOW (novelty AND grounding);
     scorer error degrades to axis_b=null / advisory (never blocks).
"""
from __future__ import annotations

from typing import Sequence

import pytest

from src.scoring.contracts import ScoreProvider
from src.scoring.sophistication import (
    SophisticationScorer,
    StaticBaselineStore,
    UnavailablePerplexityModel,
)
from src.scoring.sophistication.metrics import novelty_anded_with_grounding


def _full_baseline() -> StaticBaselineStore:
    """Per-metric rolling baselines for surprise/roscoe/receval."""
    return StaticBaselineStore(
        surprise=[1.0, 2.0, 3.0, 4.0],
        roscoe=[0.1, 0.2, 0.3, 0.4],
        receval=[0.1, 0.2, 0.3, 0.4],
    )


# ---------- injected fakes (no network) --------------------------------


class FakePerplexity:
    """Returns a fixed surprise; pinned model_version."""

    def __init__(self, value: float, version: str = "fake-ppl-v1") -> None:
        self._value = value
        self._version = version

    @property
    def model_version(self) -> str:
        return self._version

    def surprise(self, text: str) -> float:  # noqa: ARG002
        return self._value


class RaisingPerplexity:
    """Surprise model that crashes — exercises the degrade path."""

    @property
    def model_version(self) -> str:
        return "raising-ppl"

    def surprise(self, text: str) -> float:  # noqa: ARG002
        raise RuntimeError("perplexity backend exploded")


class PostHocLM:
    """Conclusion is INVARIANT to perturbation => post-hoc rationalization."""

    @property
    def model_version(self) -> str:
        return "fake-lm-posthoc"

    def conclude(self, steps: Sequence[str], *, sample_index: int = 0) -> str:  # noqa: ARG002
        return "Conclusion: BUY-HIGH, high conviction, unchanged."


class FaithfulLM:
    """Conclusion RESPONDS to perturbation => faithful chain."""

    @property
    def model_version(self) -> str:
        return "fake-lm-faithful"

    def conclude(self, steps: Sequence[str], *, sample_index: int = 0) -> str:  # noqa: ARG002
        # If a perturbation marker is present, return a materially different
        # conclusion; otherwise the baseline conclusion.
        joined = " ".join(steps)
        if "NOT TRUE" in joined or "opposite" in joined:
            return "Conclusion: AVOID, thesis broken, sell everything now."
        return "Conclusion: BUY-HIGH, high conviction, accumulate."


# ---------- envelope fixtures ------------------------------------------


def _grounded_envelope() -> dict:
    return {
        "ticker": "NVDA",
        "evidence_index_refs": ["evidence://nvda/dcf", "evidence://nvda/moat"],
        "reasoning_trace": [
            {"op": "load_dcf", "rationale": "Loaded the nvda dcf valuation model inputs."},
            {"op": "assess_moat", "rationale": "Assessed the nvda moat via switching costs."},
            {"op": "synthesize", "rationale": "Therefore nvda dcf and moat support BUY-HIGH."},
        ],
    }


def _high_novelty_ungrounded_envelope() -> dict:
    """Surprising rationale text that references NOTHING in the envelope."""
    return {
        "ticker": "NVDA",
        # No evidence/ref/framework fields at all => zero grounding.
        "reasoning_trace": [
            {"op": "speculate", "rationale": "Quantum tunnelling reshapes semiconductor demand."},
            {"op": "speculate2", "rationale": "Lunar fabrication yields exotic margin expansion."},
            {"op": "leap", "rationale": "Hence interstellar arbitrage justifies BUY-HIGH."},
        ],
    }


def _label_only_envelope() -> dict:
    """Has axis labels / decision but NO reasoning_trace rationale."""
    return {
        "ticker": "NVDA",
        "conviction": "HIGH",
        "summary_code": "BUY",
        "axis_b": {"roscoe": 0.8},  # label present, no rationale
        # reasoning_trace absent entirely
    }


def _blank_rationale_envelope() -> dict:
    return {
        "ticker": "NVDA",
        "reasoning_trace": [
            {"op": "a", "rationale": ""},
            {"op": "b", "rationale": "   "},
        ],
    }


# ---------- protocol conformance ---------------------------------------


def test_implements_scoreprovider_protocol():
    scorer = SophisticationScorer()
    assert isinstance(scorer, ScoreProvider)


# ---------- CRITERION 1: abstain on label-only / no rationale ----------


def test_label_only_abstains_no_silent_number():
    scorer = SophisticationScorer(perplexity_model=FakePerplexity(5.0))
    result = scorer.score(_label_only_envelope())
    assert result["block_name"] == "axis_b"
    assert result["mode"] == "advisory"
    assert result["scores"]["abstained"] is True
    assert result["scores"]["reason"] == "no_rationale"
    # No silent numbers — every numeric metric is None.
    for k in ("roscoe", "receval", "cot_faithfulness_flag", "novelty_percentile", "surprise"):
        assert result["scores"][k] is None


def test_absent_reasoning_trace_abstains():
    scorer = SophisticationScorer(perplexity_model=FakePerplexity(5.0))
    result = scorer.score({"ticker": "X"})
    assert result["scores"]["abstained"] is True


def test_blank_rationales_abstain():
    scorer = SophisticationScorer(perplexity_model=FakePerplexity(5.0))
    result = scorer.score(_blank_rationale_envelope())
    assert result["scores"]["abstained"] is True
    assert result["scores"]["reason"] == "no_rationale"


def test_null_reasoning_trace_abstains():
    scorer = SophisticationScorer(perplexity_model=FakePerplexity(5.0))
    result = scorer.score({"ticker": "X", "reasoning_trace": None})
    assert result["scores"]["abstained"] is True


# ---------- CRITERION 2: intervention flags post-hoc; relative scores --


def test_intervention_flags_post_hoc_rationalization():
    scorer = SophisticationScorer(
        perplexity_model=FakePerplexity(5.0),
        rationale_lm=PostHocLM(),
        baseline_store=_full_baseline(),
    )
    result = scorer.score(_grounded_envelope())
    # Post-hoc LM never moves the conclusion => flag True (unfaithful).
    assert result["scores"]["cot_faithfulness_flag"] is True


def test_intervention_passes_faithful_chain():
    scorer = SophisticationScorer(
        perplexity_model=FakePerplexity(5.0),
        rationale_lm=FaithfulLM(),
        baseline_store=_full_baseline(),
    )
    result = scorer.score(_grounded_envelope())
    # Faithful LM moves the conclusion => not flagged.
    assert result["scores"]["cot_faithfulness_flag"] is False


def test_novelty_is_percentile_vs_rolling_baseline():
    # surprise=2.5 vs baseline [1,2,3,4] => 2 of 4 are <= 2.5 => 0.5 percentile.
    scorer = SophisticationScorer(
        perplexity_model=FakePerplexity(2.5),
        baseline_store=_full_baseline(),
    )
    result = scorer.score(_grounded_envelope())
    s = result["scores"]
    assert s["surprise"] == 2.5
    # grounded fixture -> grounding > 0, so novelty == 0.5 * grounding.
    assert s["novelty_percentile"] is not None
    assert 0.0 < s["novelty_percentile"] <= 0.5


def test_roscoe_receval_stored_as_percentile_not_absolute():
    # The proxy raw values are uncalibrated; what's stored must be the
    # percentile-vs-baseline (criterion 2), with raw kept only as diagnostic.
    # roscoe baseline [0.1,0.2,0.3,0.4]; a high raw proxy ranks at 1.0.
    scorer = SophisticationScorer(
        perplexity_model=FakePerplexity(2.5),
        baseline_store=StaticBaselineStore(
            surprise=[1.0, 2.0, 3.0, 4.0],
            roscoe=[0.1, 0.2, 0.3, 0.4],
            receval=[0.1, 0.2, 0.3, 0.4],
        ),
    )
    result = scorer.score(_grounded_envelope())
    s = result["scores"]
    # Stored roscoe/receval are percentiles in [0,1] AND differ from the raw.
    assert s["roscoe"] is not None and 0.0 <= s["roscoe"] <= 1.0
    assert s["receval"] is not None and 0.0 <= s["receval"] <= 1.0
    assert "roscoe_raw" in s and "receval_raw" in s
    # Raw proxy is recorded separately as a diagnostic.
    assert s["roscoe"] != s["roscoe_raw"] or s["roscoe_raw"] in (0.0, 1.0)


def test_roscoe_receval_abstain_without_per_metric_baseline():
    # No roscoe/receval baseline windows -> percentile is meaningless ->
    # stored as None (explicit abstain, no silent absolute number); raw kept.
    scorer = SophisticationScorer(
        perplexity_model=FakePerplexity(2.5),
        baseline_store=StaticBaselineStore(surprise=[1.0, 2.0, 3.0, 4.0]),
    )
    result = scorer.score(_grounded_envelope())
    s = result["scores"]
    assert s["roscoe"] is None
    assert s["receval"] is None
    # Raw diagnostics still present (so the baseline can be backfilled).
    assert s["roscoe_raw"] is not None
    assert s["receval_raw"] is not None


def test_no_baseline_abstains_novelty_only():
    # Empty baseline -> percentile meaningless -> novelty None, rest valid.
    scorer = SophisticationScorer(
        perplexity_model=FakePerplexity(2.5),
        baseline_store=StaticBaselineStore([]),
    )
    result = scorer.score(_grounded_envelope())
    s = result["scores"]
    assert s["novelty_percentile"] is None
    assert s["surprise"] == 2.5  # raw surprise still recorded
    assert s["roscoe_raw"] is not None  # rest of block computed (raw proxy)


# ---------- CRITERION 3: novelty AND grounding; degrade ----------------


def test_high_novelty_ungrounded_scores_low():
    # Max surprise (percentile ~ 1.0) but zero grounding => novelty ~ 0.
    scorer = SophisticationScorer(
        perplexity_model=FakePerplexity(999.0),
        baseline_store=_full_baseline(),
    )
    result = scorer.score(_high_novelty_ungrounded_envelope())
    s = result["scores"]
    assert s["surprise"] == 999.0  # raw surprise is high
    assert s["grounding_credit"] == 0.0  # nothing to ground against
    # ANDed novelty collapses to 0 — surprising-but-unsupported scores LOW.
    assert s["novelty_percentile"] == 0.0


def test_grounded_high_novelty_scores_higher_than_ungrounded():
    base = _full_baseline()
    grounded = SophisticationScorer(
        perplexity_model=FakePerplexity(999.0), baseline_store=base
    ).score(_grounded_envelope())["scores"]["novelty_percentile"]
    ungrounded = SophisticationScorer(
        perplexity_model=FakePerplexity(999.0), baseline_store=base
    ).score(_high_novelty_ungrounded_envelope())["scores"]["novelty_percentile"]
    assert grounded > ungrounded
    assert ungrounded == 0.0


def test_novelty_and_grounding_unit():
    # Direct AND check: high novelty, zero grounding => 0.
    assert novelty_anded_with_grounding(1.0, 0.0) == 0.0
    # high novelty, full grounding => preserved.
    assert novelty_anded_with_grounding(0.9, 1.0) == pytest.approx(0.9)
    # clamps.
    assert novelty_anded_with_grounding(2.0, 2.0) == 1.0


def test_scorer_error_degrades_to_null_advisory():
    scorer = SophisticationScorer(
        perplexity_model=RaisingPerplexity(),
        baseline_store=StaticBaselineStore([1.0, 2.0, 3.0]),
    )
    result = scorer.score(_grounded_envelope())
    assert result["block_name"] == "axis_b"
    assert result["mode"] == "advisory"  # never flips to gate
    assert result["scores"]["degraded"] is True
    assert result["scores"]["reason"].startswith("scorer_error:")
    # axis_b numeric content is null — never an auto-PASS, never blocks.
    for k in ("roscoe", "receval", "cot_faithfulness_flag", "novelty_percentile", "surprise"):
        assert result["scores"][k] is None


@pytest.mark.parametrize("bad_envelope", [None, [], "x"])
def test_non_dict_envelope_degrades_without_raising(bad_envelope):
    # Degrade-contract: score() must NEVER raise on a non-dict envelope —
    # it returns the null/advisory axis_b block instead.
    scorer = SophisticationScorer(perplexity_model=FakePerplexity(5.0))
    result = scorer.score(bad_envelope)  # must not raise
    assert result["block_name"] == "axis_b"
    assert result["mode"] == "advisory"
    # Every numeric metric is None — never a silent number, never an auto-PASS.
    for k in ("roscoe", "receval", "cot_faithfulness_flag", "novelty_percentile", "surprise"):
        assert result["scores"][k] is None


def test_default_perplexity_is_unavailable_and_degrades():
    # No model injected -> UnavailablePerplexityModel raises -> degrade.
    scorer = SophisticationScorer(baseline_store=StaticBaselineStore([1.0, 2.0]))
    assert isinstance(scorer.perplexity_model, UnavailablePerplexityModel)
    result = scorer.score(_grounded_envelope())
    assert result["scores"]["degraded"] is True
    assert result["scores"]["surprise"] is None
