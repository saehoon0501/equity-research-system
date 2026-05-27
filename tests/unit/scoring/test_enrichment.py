"""Unit tests for the Phase-2 envelope enrichment adapter (src/scoring/enrichment.py).

Covers: pure (non-mutating) enrichment, offline degrade (no seams => advisory
blocks, never None, never raise), pass-through of injected scorer output, the
non-dict guard, and the resolve_grounding live seam.
"""

from __future__ import annotations

import pytest

from src.scoring.enrichment import (
    enrich_axes,
    enrich_envelope,
    resolve_grounding,
)


class _FakeScorer:
    """A scorer stub returning a fixed ScoreResult-shaped dict."""

    def __init__(self, block_name, scores):
        self._block = block_name
        self._scores = scores

    def score(self, envelope, **kwargs):
        return {"block_name": self._block, "scores": self._scores, "mode": "advisory"}


class _RaisingScorer:
    def score(self, envelope, **kwargs):
        raise RuntimeError("boom")


def test_enrich_axes_returns_both_blocks_offline_without_raising():
    env = {"thesis": "x", "reasoning_trace": [{"op": "CLAIM", "rationale": "r"}]}
    out = enrich_axes(env)
    assert set(out.keys()) == {"axis_a", "axis_b"}
    # Offline, no seams => both scorers degrade, but to a dict (never None).
    assert isinstance(out["axis_a"], dict)
    assert isinstance(out["axis_b"], dict)
    assert out["axis_a"].get("mode") == "advisory"
    assert out["axis_b"].get("mode") == "advisory"


def test_enrich_axes_does_not_mutate_envelope():
    env = {"thesis": "x"}
    before = dict(env)
    enrich_axes(env)
    assert env == before
    assert "axis_a" not in env and "axis_b" not in env


def test_enrich_axes_passes_through_injected_scorer_output():
    flat_a = {
        "faithfulness": 0.91,
        "answer_relevancy": 0.8,
        "citation_precision": 1.0,
        "citation_recall": 0.75,
        "veriscore": 0.7,
        "coherence": 0.85,
        "clarity": 0.9,
        "mode": "advisory",
    }
    flat_b = {"roscoe": 0.6, "receval": 0.5, "novelty_percentile": 0.4, "mode": "advisory"}
    out = enrich_axes(
        {"thesis": "x"},
        articulation=_FakeScorer("axis_a", flat_a),
        sophistication=_FakeScorer("axis_b", flat_b),
    )
    assert out["axis_a"] == flat_a
    assert out["axis_b"] == flat_b


def test_enrich_axes_degrades_on_raising_scorer():
    out = enrich_axes(
        {"thesis": "x"},
        articulation=_RaisingScorer(),
        sophistication=_RaisingScorer(),
    )
    assert out["axis_a"]["degraded"] is True
    assert out["axis_b"]["degraded"] is True
    assert out["axis_a"]["mode"] == "advisory"


def test_enrich_axes_degrade_block_matches_scorer_degrade_shape():
    """C3: an adapter-degraded block carries the SAME canonical flat-null keys
    the scorers emit when they themselves degrade — so a consumer iterating the
    canonical key-set (not ``.get``) sees one schema either way.
    """
    # Pull the canonical key-sets straight from the scorer modules so the test
    # fails if the adapter ever drifts from the scorers' own degrade shape.
    from src.scoring.articulation.scorer import CANONICAL_NUMERIC_KEYS as A_KEYS
    from src.scoring.sophistication.scorer import _NUMERIC_KEYS as B_KEYS

    out = enrich_axes(
        {"thesis": "x"},
        articulation=_RaisingScorer(),
        sophistication=_RaisingScorer(),
    )

    axis_a = out["axis_a"]
    assert set(A_KEYS) <= set(axis_a)  # all 8 articulation canonical keys present
    assert all(axis_a[k] is None for k in A_KEYS)  # numeric ones None
    assert axis_a["mode"] == "advisory"

    axis_b = out["axis_b"]
    assert set(B_KEYS) <= set(axis_b)  # all sophistication canonical keys present
    assert all(axis_b[k] is None for k in B_KEYS)  # numeric/flag ones None
    assert axis_b["mode"] == "advisory"


def test_enrich_axes_handles_none_scores_payload():
    out = enrich_axes(
        {"thesis": "x"},
        articulation=_FakeScorer("axis_a", None),  # legacy total-degrade None
    )
    assert isinstance(out["axis_a"], dict)
    assert out["axis_a"]["mode"] == "advisory"


@pytest.mark.parametrize("bad", [None, [], "x", 5])
def test_enrich_envelope_non_dict_returned_unchanged(bad):
    assert enrich_envelope(bad) is bad


def test_enrich_envelope_splices_blocks_into_new_dict():
    env = {"thesis": "x", "summary_code": "BUY"}
    enriched = enrich_envelope(
        env,
        articulation=_FakeScorer("axis_a", {"faithfulness": 0.9, "mode": "advisory"}),
        sophistication=_FakeScorer("axis_b", {"roscoe": 0.5, "mode": "advisory"}),
    )
    assert enriched is not env  # new dict
    assert "axis_a" not in env  # original untouched
    assert enriched["axis_a"]["faithfulness"] == 0.9
    assert enriched["axis_b"]["roscoe"] == 0.5
    assert enriched["summary_code"] == "BUY"  # original keys preserved


def test_resolve_grounding_no_fetch_returns_empty():
    text, frameworks = resolve_grounding({"evidence_index_refs": ["e1"]})
    assert text == ""
    assert frameworks == set()


def test_resolve_grounding_uses_fetch():
    def fetch(env):
        return "grounding text", {"dcf", "comps"}

    text, frameworks = resolve_grounding({}, fetch=fetch)
    assert text == "grounding text"
    assert frameworks == {"dcf", "comps"}


def test_resolve_grounding_swallows_fetch_error():
    def fetch(env):
        raise RuntimeError("db down")

    text, frameworks = resolve_grounding({}, fetch=fetch)
    assert text == "" and frameworks == set()
