"""Acceptance criterion 1 — faithfulness flags a seeded unsupported claim.

Uses a MOCKED llm_caller (no network) that returns, for the seeded
fixture, a decomposition where one claim is NOT entailed by the grounding.
We assert the unsupported-claim recall > 0 and faithfulness < 1.0.
"""

from __future__ import annotations

from src.scoring.articulation.faithfulness import score_faithfulness

GROUNDING = (
    "Apple reported Q4 FY2024 revenue of $94.9 billion. iPhone revenue was "
    "$46.2 billion. The company declared a dividend of $0.25 per share."
)

# The answer asserts one claim that the grounding does NOT support
# (the fabricated $200B services figure).
ANSWER = (
    "Apple's Q4 FY2024 revenue was $94.9 billion. Services revenue reached "
    "$200 billion, an all-time high."
)


def _mock_caller_with_unsupported(system, user, model, temperature, sample_index):
    """Deterministic mock: 2 claims, the services one is unsupported."""
    return {
        "claims": [
            {"claim": "Q4 FY2024 revenue was $94.9B", "supported": True},
            {"claim": "Services revenue reached $200B", "supported": False},
        ],
        "answer_relevancy": 0.9,
    }


def test_seeded_unsupported_claim_flagged():
    res = score_faithfulness(
        ANSWER, GROUNDING, llm_caller=_mock_caller_with_unsupported, n=5
    )
    # Criterion 1: the seeded unsupported claim is detected (rate > 0).
    assert res.unsupported_detection_rate > 0.0
    assert res.n_unsupported_flagged >= 1
    # faithfulness = supported/total = 1/2 = 0.5 (< 1.0 because one unsupported)
    assert res.faithfulness < 1.0
    assert res.faithfulness == 0.5
    assert res.answer_relevancy == 0.9
    assert len(res.samples_faithfulness) == 5  # N=5 self-consistency


def test_all_supported_gives_full_faithfulness_and_zero_unsupported_detection_rate():
    def _all_supported(system, user, model, temperature, sample_index):
        return {
            "claims": [
                {"claim": "x", "supported": True},
                {"claim": "y", "supported": True},
            ],
            "answer_relevancy": 0.8,
        }

    res = score_faithfulness(ANSWER, GROUNDING, llm_caller=_all_supported, n=5)
    assert res.faithfulness == 1.0
    assert res.unsupported_detection_rate == 0.0
    assert res.n_unsupported_flagged == 0


def test_faithfulness_block_shape_and_mode():
    res = score_faithfulness(
        ANSWER, GROUNDING, llm_caller=_mock_caller_with_unsupported, n=5
    )
    block = res.to_block()
    assert block["mode"] == "advisory"
    assert block["n_self_consistency"] == 5
    assert "unsupported_detection_rate" in block
