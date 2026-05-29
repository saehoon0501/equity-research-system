"""Decision-Trace Telemetry leaf package (reactive CFD layer).

Owns the correlation-key contract and the two append-only row types. This
`__init__` re-exports ONLY the stable type contract defined in `schema.py`;
later leaf tasks add `trace_writer` / `reader` modules without modifying this
file (consumers import those from their submodules directly). Pure leaf (P1):
no DB, no MCP, no I/O at import time.
"""

from src.reactive.telemetry.schema import (
    CorrelationKeys,
    DecisionTraceRow,
    FillOutcomeRow,
)

__all__ = [
    "CorrelationKeys",
    "DecisionTraceRow",
    "FillOutcomeRow",
]
