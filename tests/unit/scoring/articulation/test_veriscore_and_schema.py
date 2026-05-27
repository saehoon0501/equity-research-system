"""VERISCORE happy-path (mocked) + axis_a validates against AXIS_SCHEMA.

- VERISCORE: mocked llm_caller, N=5 median factuality precision.
- Schema: the scorer's axis_a payload must validate against the Phase-0
  ``AXIS_SCHEMA`` (permissive object|null) and, when written into a real
  envelope, pass that envelope module's ``validate_envelope``.
"""

from __future__ import annotations

from src.agent_harness.envelopes._base import AXIS_SCHEMA, validate_envelope
from src.scoring.articulation.scorer import ArticulationScorer
from src.scoring.articulation.veriscore import score_veriscore


def _mock_veri(system, user, model, temperature, sample_index):
    return {
        "verifiable_claims": [
            {"claim": "rev $94.9B", "supported": True},
            {"claim": "iPhone $46.2B", "supported": True},
            {"claim": "services $200B", "supported": False},
        ]
    }


def test_veriscore_factuality_precision_median():
    res = score_veriscore("text", "grounding", llm_caller=_mock_veri, n=5)
    # 2 of 3 verifiable claims supported => precision 0.6667
    assert abs(res.factuality_precision - 2 / 3) < 1e-9
    assert res.n_verifiable == 3
    assert res.n_supported == 2
    assert len(res.samples) == 5
    assert res.to_block()["mode"] == "advisory"


def test_axis_a_payload_validates_against_axis_schema():
    scorer = ArticulationScorer(
        faithfulness_llm=lambda s, u, m, t, i: {
            "claims": [{"claim": "c", "supported": True}],
            "answer_relevancy": 0.9,
        },
        veriscore_llm=_mock_veri,
        clarity_llm=lambda s, u, m, t, i: {"clarity": 0.7},
        coherence_runner=lambda text: 0.8,
    )
    result = scorer.score(
        {"thesis": "x", "frameworks_cited": [{"framework_key": "k", "output": {}}]},
        grounding="c",
        supported_frameworks={"k"},
    )
    axis_a = result["scores"]
    # Validate the block against the Phase-0 AXIS_SCHEMA (object|null, permissive).
    res = validate_envelope(
        {"axis_a": axis_a},
        schema={
            "type": "object",
            "properties": {"axis_a": AXIS_SCHEMA},
            "additionalProperties": True,
        },
        reasoning_steps=(),
        predicates={},
    )
    assert res.valid, res.to_result_dict()


def test_axis_a_null_is_valid_per_schema():
    """A degraded null axis_a must also validate (AXIS_SCHEMA allows null)."""
    res = validate_envelope(
        {"axis_a": None},
        schema={
            "type": "object",
            "properties": {"axis_a": AXIS_SCHEMA},
            "additionalProperties": True,
        },
        reasoning_steps=(),
        predicates={},
    )
    assert res.valid, res.to_result_dict()
