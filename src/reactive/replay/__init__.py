"""Replay Harness package — the deterministic point-in-time counterfactual
backtest engine for the reactive CFD layer's after-market tuning.

At task 1.1 only the contract types (`types.py`) exist; the design's end-state
`__init__` exports `replay_candidate` (the harness entry), but `harness.py` is
a later task — importing it now would break the package import. This `__init__`
therefore re-exports only the landed contract types from `.types`; the
`replay_candidate` export is added when `harness.py` lands.
"""

from __future__ import annotations

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
]
