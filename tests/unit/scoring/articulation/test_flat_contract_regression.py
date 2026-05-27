"""Regression tests for the FLAT axis_a contract (BUG 1) + grounding degrade (BUG 2).

These are the tests that were MISSING — which is why the contract break slipped:
nothing asserted the scorer's ``axis_a`` payload shape matched the canonical
golden fixture shape, and nothing asserted that absent grounding degrades
faithfulness to null rather than fabricating ~0.0.

BUG 1 — the scorer must emit a FLAT axis_a with the same 8 canonical top-level
scalar keys the golden fixtures carry (tests/fixtures/golden_score_blocks/*.json)
and the consumer src/p4_debate/_bon_mav.py ``composite_quality`` reads directly.

BUG 2 — empty/absent grounding => RAGAS judges every claim unsupported and
would return a WRONG real 0.0; the scorer must instead degrade faithfulness
(and answer_relevancy) to None.

All mocks are in-process — NO network.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.scoring.articulation.scorer import ArticulationScorer

# The 8 canonical FLAT keys the golden fixtures + consumers require.
_CANONICAL_KEYS = {
    "faithfulness",
    "answer_relevancy",
    "citation_precision",
    "citation_recall",
    "veriscore",
    "coherence",
    "clarity",
    "mode",
}

_GOLDEN = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "golden_score_blocks"
    / "pm_supervisor.json"
)


def _fully_mocked_scorer() -> ArticulationScorer:
    """A scorer with every LLM/local seam injected so axis_a is fully populated."""
    return ArticulationScorer(
        faithfulness_llm=lambda s, u, m, t, i: {
            "claims": [
                {"claim": "rev $94.9B", "supported": True},
                {"claim": "iphone $46.2B", "supported": True},
            ],
            "answer_relevancy": 0.91,
        },
        veriscore_llm=lambda s, u, m, t, i: {
            "verifiable_claims": [
                {"claim": "rev $94.9B", "supported": True},
                {"claim": "iphone $46.2B", "supported": True},
            ]
        },
        clarity_llm=lambda s, u, m, t, i: {"clarity": 0.9},
        coherence_runner=lambda text: 0.87,
    )


def _populated_result():
    scorer = _fully_mocked_scorer()
    return scorer.score(
        {"thesis": "Apple Q4 revenue was strong.", "frameworks_cited": ["dcf"]},
        grounding="Apple reported Q4 revenue of $94.9B; iPhone $46.2B.",
        supported_frameworks={"dcf"},
    )


def test_fully_populated_axis_a_matches_canonical_flat_shape():
    """BUG 1 regression: the scorer output shape matches the golden fixture shape.

    Asserts the 8 canonical keys are present at the FLAT top level, and the
    representative numerics are bare floats (not nested dicts).
    """
    axis_a = _populated_result()["scores"]

    # The 8 canonical keys are present at the top level (extra keys allowed).
    assert set(axis_a.keys()) >= _CANONICAL_KEYS, (
        f"missing canonical keys: {_CANONICAL_KEYS - set(axis_a.keys())}"
    )

    # The scalars are bare floats — NOT nested to_block() dicts (the bug).
    assert isinstance(axis_a["faithfulness"], float)
    assert isinstance(axis_a["answer_relevancy"], float)
    assert isinstance(axis_a["citation_precision"], float)
    assert isinstance(axis_a["citation_recall"], float)
    assert isinstance(axis_a["veriscore"], float)
    assert isinstance(axis_a["coherence"], float)
    assert isinstance(axis_a["clarity"], float)
    assert axis_a["mode"] == "advisory"


def test_scorer_keys_superset_of_golden_fixture_keys():
    """The live scorer block carries at least the golden fixture's axis_a keys."""
    golden_keys = set(json.loads(_GOLDEN.read_text())["axis_a"].keys())
    assert golden_keys == _CANONICAL_KEYS  # guards the fixture itself
    axis_a = _populated_result()["scores"]
    assert set(axis_a.keys()) >= golden_keys


def test_empty_grounding_degrades_faithfulness_to_null_not_zero():
    """BUG 2 regression: absent grounding => faithfulness/answer_relevancy null.

    Without grounding RAGAS would judge every claim unsupported and return a
    fabricated ~0.0. That is a WRONG real score; the scorer must instead
    return None (advisory degrade).
    """
    # Even with a working faithfulness LLM seam, empty grounding must short-
    # circuit BEFORE calling it (so no fabricated 0.0 can be produced).
    called = {"faith": False}

    def _faith(s, u, m, t, i):
        called["faith"] = True
        return {"claims": [{"claim": "x", "supported": False}], "answer_relevancy": 0.0}

    scorer = ArticulationScorer(faithfulness_llm=_faith, coherence_runner=lambda t: 0.5)
    result = scorer.score(
        {"thesis": "some thesis text", "frameworks_cited": []},
        grounding="",  # absent grounding
        supported_frameworks=set(),
    )
    scores = result["scores"]
    assert scores["faithfulness"] is None, "must degrade to null, not fabricate 0.0"
    assert scores["faithfulness"] != 0.0
    assert scores["answer_relevancy"] is None
    assert called["faith"] is False, "faithfulness LLM must not run without grounding"
    # The degrade reason is recorded for the caller.
    assert "faithfulness" in scores["errors"]


def test_whitespace_only_grounding_also_degrades():
    """Whitespace-only grounding is treated as absent (BUG 2)."""
    scorer = ArticulationScorer(
        faithfulness_llm=lambda s, u, m, t, i: {
            "claims": [{"claim": "x", "supported": True}],
            "answer_relevancy": 0.9,
        }
    )
    result = scorer.score(
        {"thesis": "t", "frameworks_cited": []},
        grounding="   \n  ",
        supported_frameworks=set(),
    )
    assert result["scores"]["faithfulness"] is None
    assert result["scores"]["answer_relevancy"] is None
