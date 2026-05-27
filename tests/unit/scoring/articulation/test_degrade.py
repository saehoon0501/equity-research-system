"""Acceptance criterion 4 — degrade: scorer error => axis_a null, advisory.

A sub-metric that raises must NOT propagate out of ArticulationScorer.score.
Instead the offending sub-metric becomes ``None`` in the axis_a payload, the
error is recorded under ``axis_a.errors``, and the block mode stays
"advisory" (never blocks the gate alone; never auto-PASS; never skip-to-FAIL).

All mocks here are in-process — NO network.
"""

from __future__ import annotations

import pytest

from src.scoring.articulation.scorer import (
    BLOCK_NAME,
    SCORER_MODE,
    ArticulationScorer,
)

ENVELOPE = {
    "thesis": "NVDA structurally captures the AI infra era via CUDA lock-in.",
    "frameworks_cited": [{"framework_key": "mauboussin_reverse_dcf", "output": {}}],
    "reasoning_trace": [{"op": "EVAL", "rationale": "moat is durable"}],
}


def _raising_caller(system, user, model, temperature, sample_index):
    raise RuntimeError("simulated LLM provider 500")


def test_faithfulness_error_degrades_to_null_not_raise():
    scorer = ArticulationScorer(faithfulness_llm=_raising_caller)
    # Must not raise.
    result = scorer.score(ENVELOPE, grounding="some grounding", supported_frameworks=set())
    assert result["block_name"] == BLOCK_NAME
    assert result["mode"] == "advisory"
    scores = result["scores"]
    # Faithfulness degraded to null; error captured.
    assert scores["faithfulness"] is None
    assert "faithfulness" in scores["errors"]
    assert "simulated LLM provider 500" in scores["errors"]["faithfulness"]


def test_deterministic_citation_still_populated_when_llm_metrics_fail():
    """LLM metrics degrade independently; deterministic citation survives."""
    scorer = ArticulationScorer(
        faithfulness_llm=_raising_caller,
        veriscore_llm=_raising_caller,
        clarity_llm=_raising_caller,
        # coherence_runner None => coherence degrades (offline default)
    )
    result = scorer.score(
        ENVELOPE,
        grounding="g",
        supported_frameworks={"mauboussin_reverse_dcf"},
    )
    scores = result["scores"]
    # FLAT canonical scalars: failed LLM metrics are null, never fabricated.
    assert scores["faithfulness"] is None
    assert scores["answer_relevancy"] is None
    assert scores["veriscore"] is None
    assert scores["clarity"] is None
    assert scores["coherence"] is None  # no local model offline
    # Citation is deterministic and present: 1 cited, 1 supported, overlap 1.
    assert scores["citation_precision"] == 1.0
    assert scores["citation_recall"] == 1.0
    assert result["mode"] == "advisory"


def test_coherence_offline_degrades_to_null():
    """UNION coherence has no local model offline => null, advisory."""
    scorer = ArticulationScorer()
    result = scorer.score(ENVELOPE, grounding="g", supported_frameworks=set())
    assert result["scores"]["coherence"] is None
    assert "coherence" in result["scores"]["errors"]


def test_coherence_populated_with_injected_runner():
    """Injecting a local-model stub populates coherence (version-pinned)."""
    scorer = ArticulationScorer(coherence_runner=lambda text: 0.83)
    result = scorer.score(ENVELOPE, grounding="g", supported_frameworks=set())
    scores = result["scores"]
    # FLAT canonical scalar.
    assert scores["coherence"] == 0.83
    # Rich diagnostics retained under the single non-canonical key.
    coh_diag = scores["_diagnostics"]["coherence"]
    assert coh_diag["model_version"]  # pinned resolved id stamped
    assert coh_diag["mode"] == "advisory"


def test_non_dict_envelope_yields_null_flat_block():
    """Total degrade: a non-dict envelope => all-null FLAT block (not None).

    Mirrors the WS-2 sibling: scores is a dict with every canonical scalar
    null, mode=advisory, degraded=True.
    """
    scorer = ArticulationScorer()
    result = scorer.score("not-an-envelope")  # type: ignore[arg-type]
    assert result["block_name"] == BLOCK_NAME
    assert result["mode"] == "advisory"
    scores = result["scores"]
    assert isinstance(scores, dict)
    assert scores["degraded"] is True
    for key in (
        "faithfulness",
        "answer_relevancy",
        "citation_precision",
        "citation_recall",
        "veriscore",
        "coherence",
        "clarity",
    ):
        assert scores[key] is None, key
    assert scores["mode"] == "advisory"


def test_clarity_is_advisory_only_flag():
    scorer = ArticulationScorer(
        clarity_llm=lambda s, u, m, t, i: {"clarity": 0.7},
    )
    result = scorer.score(ENVELOPE, grounding="g", supported_frameworks=set())
    scores = result["scores"]
    # FLAT canonical scalar.
    assert scores["clarity"] == 0.7
    # advisory_only flag preserved in diagnostics.
    clar_diag = scores["_diagnostics"]["clarity"]
    assert clar_diag["advisory_only"] is True
    assert clar_diag["mode"] == "advisory"
