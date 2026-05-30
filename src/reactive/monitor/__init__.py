"""In-Session Monitor leaf package (reactive CFD layer).

Owns the supervisory loop's domain types — the calibration-drift diagnostic, the
envelope verdict + anomaly classification, the bounded intervention vocabulary,
the writer-side command payload, the falsifiable intervention audit, and the
P2-pinned `MonitorParams`. This `__init__` re-exports ONLY the stable type
contract defined in `types.py`; later leaf tasks add `diagnostic` / `judge` /
`intervene` / `audit` / `command_writer` modules without modifying this file
(consumers import those from their submodules directly, preserving the strict
`types → diagnostic → judge → intervene → {audit, command_writer}` direction).
Pure leaf (P1): no DB, no MCP, no I/O at import time.
"""

from src.reactive.monitor.types import (
    ActiveState,
    CommandResult,
    CommandResultStatus,
    CommandType,
    DriftDiagnostic,
    EnvelopeState,
    EnvelopeVerdict,
    InterventionAudit,
    InterventionCommand,
    InterventionIntent,
    MetricObservation,
    MonitorParams,
    Severity,
    VersionRef,
)

__all__ = [
    "ActiveState",
    "CommandResult",
    "CommandResultStatus",
    "CommandType",
    "DriftDiagnostic",
    "EnvelopeState",
    "EnvelopeVerdict",
    "InterventionAudit",
    "InterventionCommand",
    "InterventionIntent",
    "MetricObservation",
    "MonitorParams",
    "Severity",
    "VersionRef",
]
