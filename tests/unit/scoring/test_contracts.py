"""Unit tests for src/scoring/contracts.py typed contracts.

C2 regression: the ``GateDecision`` TypedDict must match the key set the
producer ``_hybrid_gate.HybridResult.to_gate_decision()`` actually emits
(``{verdict, deterministic, advisory, escalated}``).
"""

from __future__ import annotations

from src.scoring.contracts import GateDecision


def _gate_decision_keys() -> set[str]:
    """The declared key set of the GateDecision TypedDict."""
    return set(GateDecision.__annotations__.keys())


def test_gate_decision_typeddict_has_escalated_key():
    assert _gate_decision_keys() == {
        "verdict",
        "deterministic",
        "advisory",
        "escalated",
    }
    # The module uses ``from __future__ import annotations`` (PEP 563), so the
    # raw annotation is the stringified form; resolve it to confirm it's bool.
    import typing

    resolved = typing.get_type_hints(GateDecision)
    assert resolved["escalated"] is bool


def test_four_key_dict_satisfies_gate_decision():
    """A dict with exactly the 4 declared keys is a structurally valid
    GateDecision (TypedDicts are plain dicts at runtime)."""
    decision: GateDecision = {
        "verdict": "ESCALATE",
        "deterministic": {"shape": "pass"},
        "advisory": {"judge_status": "configured", "judge": "abstain"},
        "escalated": True,
    }
    assert set(decision.keys()) == _gate_decision_keys()


def test_producer_output_keys_match_typeddict():
    """to_gate_decision()'s output key set == the GateDecision TypedDict key
    set, so the contract is not stale against its producer."""
    from src.eval.gates._hybrid_gate import HybridResult

    result = HybridResult(
        spine_valid=True,
        spine_detail={"shape": True},
        judge=None,
        hybrid_verdict="PASS",
        hard_valid=True,
    )
    produced = result.to_gate_decision()
    assert set(produced.keys()) == _gate_decision_keys()
