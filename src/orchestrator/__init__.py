"""Master orchestrator for the equity-research system.

Per v3 spec Section 5.4: ``/run`` is the single entry point that wraps all
slash commands into one workflow. The orchestrator auto-detects the current
phase (v0.1-launch-readiness / v0.1-active / v0.5-active / v1.0-active) and
routes to appropriate sub-commands.

Render-only: this module produces a briefing the operator acts on. It does
NOT execute trades, auto-run sub-commands, or modify state.

Modules:
  phase_detector       — query Postgres state to determine current phase
  v01_launch_status    — surface launch-gate grid for v0.1-launch-readiness
  v01_active_routing   — produce per-cadence sub-command schedule for v0.1-active
  operator_briefing    — top-level briefing renderer assembled on /run
  cli                  — `python -m src.orchestrator.cli` entry points
"""

from __future__ import annotations

from src.orchestrator.phase_detector import (
    Phase,
    PhaseSnapshot,
    detect_phase,
)
from src.orchestrator.v01_launch_status import (
    GateStatus,
    LaunchGate,
    LaunchGateGrid,
    collect_launch_gates,
    render_launch_gate_grid,
)
from src.orchestrator.v01_active_routing import (
    ScheduledAction,
    collect_scheduled_actions,
    render_scheduled_actions,
)
from src.orchestrator.operator_briefing import (
    OperatorBriefing,
    collect_operator_briefing,
    render_operator_briefing,
)

__all__ = [
    "Phase",
    "PhaseSnapshot",
    "detect_phase",
    "GateStatus",
    "LaunchGate",
    "LaunchGateGrid",
    "collect_launch_gates",
    "render_launch_gate_grid",
    "ScheduledAction",
    "collect_scheduled_actions",
    "render_scheduled_actions",
    "OperatorBriefing",
    "collect_operator_briefing",
    "render_operator_briefing",
]
