"""Replay Harness package — the deterministic point-in-time counterfactual
backtest engine for the reactive CFD layer's after-market tuning.

Re-exports the landed contract types from `.types` and `replay_candidate` (the
public harness entry, landed at task 3.1) — the single contract
`walkforward-tuning-loop` calls per candidate config per CPCV partition (design
§File Structure Plan line 100).
"""

from __future__ import annotations

from src.reactive.replay.harness import replay_candidate
from src.reactive.replay.types import (
    Candidate,
    DataPort,
    FidelityResult,
    Fill,
    OutcomeRecord,
    ReplayResult,
    ReplayWindow,
)

__all__ = [
    "Candidate",
    "DataPort",
    "FidelityResult",
    "Fill",
    "OutcomeRecord",
    "ReplayResult",
    "ReplayWindow",
    "replay_candidate",
]
