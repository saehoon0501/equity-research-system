"""Scoring-layer interface stubs (P0-10).

Typed contracts only — NO logic. The Phase-1 workstreams implement these:

  - ``ScoreProvider`` — the structural Protocol every axis scorer (WS-1
    articulation, WS-2 sophistication) and any block-level scorer
    satisfies: ``score(envelope) -> ScoreResult`` where the result names
    the block it scored, the per-metric scores, and whether the block
    acts as a hard ``gate`` or as ``advisory`` input.
  - ``GateDecision`` — the hybrid-gate verdict (WS-6): a deterministic
    spine plus advisory judge output and an overall verdict.

These are imported (and type-checked) by all six WS modules; they carry
no runtime behaviour at Phase 0.
"""
from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

# --- ScoreProvider -----------------------------------------------------

ScoreMode = Literal["gate", "advisory"]


class ScoreResult(TypedDict):
    """Return shape of ``ScoreProvider.score``.

    block_name : the score block this provider writes (e.g. "axis_a").
    scores     : per-metric numeric (or null) scores for that block.
    mode       : "gate" (a hard companion check) | "advisory" (informational).
    """

    block_name: str
    scores: dict[str, Any]
    mode: ScoreMode


@runtime_checkable
class ScoreProvider(Protocol):
    """Structural interface for an insight-quality scorer.

    Implementations live in the Phase-1 workstreams (e.g.
    ``src/scoring/articulation/``, ``src/scoring/sophistication/``).
    """

    def score(self, envelope: dict[str, Any]) -> ScoreResult:  # pragma: no cover - stub
        ...


# --- GateDecision ------------------------------------------------------

GateVerdict = Literal["PASS", "FAIL", "ESCALATE"]


class GateDecision(TypedDict):
    """Hybrid-gate verdict (WS-6).

    verdict       : PASS | FAIL | ESCALATE (the rolled-up outcome).
    deterministic : results of the hard deterministic companion checks.
    advisory      : the advisory (LLM-judge) output; never flips to PASS
                    alone (can only downgrade to ESCALATE — see WS-6).
    """

    verdict: GateVerdict
    deterministic: dict[str, Any]
    advisory: dict[str, Any]


__all__ = [
    "GateDecision",
    "GateVerdict",
    "ScoreMode",
    "ScoreProvider",
    "ScoreResult",
]
