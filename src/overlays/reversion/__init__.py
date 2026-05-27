"""v0.4.0 mean-reversion overlay — standalone subagent backing.

Per the plan at ~/.claude/plans/no-pm-supervisor-integration-yet-smooth-cascade.md,
v0.4.0 is twice-narrowed:
- No pm-supervisor integration (no cell completion, no sizing voice)
- No /research-company orchestrator integration

The subagent is dispatched standalone by the operator via `Agent(mean-reversion-overlay, ...)`.
This Python package backs the agent's algorithm + the CLI backtest replay path.
"""
from src.overlays.reversion.bin_classifier import classify_reversion
from src.overlays.reversion.contracts import (
    ReversionBin,
    ReversionSignal,
    UnavailableReason,
)

__all__ = [
    "classify_reversion",
    "ReversionBin",
    "ReversionSignal",
    "UnavailableReason",
]
