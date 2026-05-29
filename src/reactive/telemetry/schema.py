"""Decision-Trace Telemetry: correlation-key contract + row types.

The single source of the correlation-key contract and the two append-only row
kinds (decision, fill) for the reactive CFD layer's process trace. Per the
design's "Components and Interfaces -> Telemetry leaf -> schema": pure types,
no I/O — this module satisfies requirements 1.4, 3.1, 8.2.

Pure leaf (P1): stdlib only — no psycopg, no MCP, no DB, no repo imports.
The Python *type* is the kind discriminator: `DecisionTraceRow` is
`kind == 'decision'`, `FillOutcomeRow` is `kind == 'fill'`. A `fill` row
carries `parent_trace_id`; a `decision` row does not. All rows are frozen.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CorrelationKeys:
    """The canonical key set every trace/fill/ledger/LLM-audit row joins on.

    Per requirement 3.1: the run identifier, code version, parameter version,
    and walk-forward window under which the decision was made. For a `fill`
    row, `walk_forward_window` carries the DECISION's window (attribution
    follows the decision), not the fill's landing window.
    """

    run_id: str  # uuid
    code_version: str
    param_version: str
    walk_forward_window: str | None


@dataclass(frozen=True)
class DecisionTraceRow:
    """A single daemon decision (kind == 'decision').

    `trace_id` is CLIENT-minted (the caller supplies it; it enables the fill
    link + ON CONFLICT idempotency downstream). `event_ts` is pinned at
    decision time — not wall-clock at write. `trace` is the flexible JSONB
    payload (requirement 8.2): gate_link, signal_values, probability,
    decision, liq_proximity, stop_out, declined.
    """

    trace_id: str  # CLIENT-minted UUID
    keys: CorrelationKeys
    event_ts: str  # ISO8601 / unix; time of THIS event (decision time)
    trace: dict  # JSONB payload; correlation keys stay typed on `keys`


@dataclass(frozen=True)
class FillOutcomeRow:
    """The async fill resolving a decision (kind == 'fill').

    Per requirement 1.4 / the design's R1.4-as-surface resolution: the
    expected-vs-actual fill is a SEPARATE linked row, never a mutation of the
    decision row. `parent_trace_id` references the decision's client-minted
    `trace_id`. `event_ts` is the fill's own (later) landing time — it may
    fall in a LATER walk-forward window than the decision, while
    `keys.walk_forward_window` still carries the decision's window for
    attribution. `trace` holds the fill payload: expected_price,
    actual_fill_price, slippage, fill_volume, counterparty_price.
    """

    trace_id: str  # CLIENT-minted UUID for the fill row
    parent_trace_id: str  # the decision row this fill resolves
    keys: CorrelationKeys  # walk_forward_window = the DECISION's window
    event_ts: str  # when the fill actually landed (may be a later window)
    trace: dict  # JSONB fill payload
