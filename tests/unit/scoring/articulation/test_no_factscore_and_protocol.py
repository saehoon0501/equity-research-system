"""Criterion 3 (no FActScore) + ScoreProvider protocol conformance.

- No ``FActScore`` import: grep the owned source + test trees and assert
  no case-insensitive ``factscore`` token appears (VERISCORE replaces it).
- ArticulationScorer structurally satisfies ``ScoreProvider`` (runtime
  checkable Protocol from the Phase-0 contracts) and returns a ScoreResult
  with the required keys.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.scoring.articulation.scorer import ArticulationScorer
from src.scoring.contracts import ScoreProvider

_REPO_ROOT = Path(__file__).resolve().parents[4]
_OWNED = [
    _REPO_ROOT / "src" / "scoring" / "articulation",
    _REPO_ROOT / "tests" / "unit" / "scoring" / "articulation",
]
_FACTSCORE = re.compile(r"factscore", re.IGNORECASE)


def test_no_factscore_token_in_owned_trees():
    offenders = []
    for root in _OWNED:
        for py in root.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            # This very test file references the token only inside the regex
            # literal / docstring; exclude self to avoid a false positive.
            if py.resolve() == Path(__file__).resolve():
                continue
            if _FACTSCORE.search(text):
                offenders.append(str(py))
    assert offenders == [], f"FActScore token found in: {offenders}"


def test_articulation_scorer_satisfies_scoreprovider_protocol():
    scorer = ArticulationScorer()
    assert isinstance(scorer, ScoreProvider)


def test_score_returns_scoreresult_keys():
    scorer = ArticulationScorer()
    result = scorer.score(
        {"thesis": "x", "frameworks_cited": []},
        grounding="",
        supported_frameworks=set(),
    )
    assert set(result.keys()) == {"block_name", "scores", "mode"}
    assert result["block_name"] == "axis_a"
    assert result["mode"] == "advisory"


def test_axis_a_payload_has_all_canonical_flat_keys():
    """All 8 canonical FLAT keys appear (value may be null on degrade)."""
    scorer = ArticulationScorer()
    result = scorer.score(
        {"thesis": "x", "frameworks_cited": []},
        grounding="",
        supported_frameworks=set(),
    )
    scores = result["scores"]
    for k in (
        "faithfulness",
        "answer_relevancy",
        "citation_precision",
        "citation_recall",
        "veriscore",
        "coherence",
        "clarity",
        "mode",
    ):
        assert k in scores, f"missing canonical key {k}"
