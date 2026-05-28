"""Insight-quality scoring layer (P0-10 interface stubs).

This package holds the typed interface contracts that the Phase-1
workstreams (WS-1 articulation, WS-2 sophistication, WS-6 hybrid gate)
implement. Per P0-10 the only thing that exists at Phase 0 is the
contract surface — see ``src.scoring.contracts``.
"""
from src.scoring.contracts import GateDecision, ScoreProvider, ScoreResult

__all__ = ["GateDecision", "ScoreProvider", "ScoreResult"]
