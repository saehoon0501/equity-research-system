"""Cross-plan handoff contracts for flow overlay.

INV-COMPOSE-FLOW-1: classify_flow (bin_classifier) emits exactly FlowSignal shape;
                    flow_cell_size_pct / flow_disposition (overlay) consume exactly
                    this shape.
INV-FLOW-2.1-A:     flow_disposition enum is disjoint from canonical summary_code
                    enum (parallel to tactical's INV-2.1-A).

Mirrors src/p8_tactical_overlay/contracts.py at structural level — same Literal
vocabulary discipline, same frozen-dataclass handoff. Per the v0.1 plan,
flow-overlay is a Stage 1 parallel soft-modulator that pm-supervisor consumes
alongside tactical-overlay (neither overrides; both visible).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

# Enum types (Literal for static type checking; .__args__ exposes values at runtime)
FlowBin = Literal["positive", "neutral", "negative", "unavailable"]
FlowDisposition = Literal["HOLD", "BUY-HIGH", "BUY-MED", "AVOID"]
Conviction = Literal["HIGH", "MEDIUM", "LOW"]
# v0.1 unavailable reasons (CTA-proximity only).
# v0.2 will add "gex_data_stale" / "options_chain_unavailable" for gamma sub-signal.
# v0.3 will add "si_data_stale" / "thirteenf_unavailable" for crowding sub-signal.
UnavailableReason = Literal[
    "insufficient_price_history",
    "spy_price_history_unavailable",
]


@dataclass(frozen=True)
class FlowSignal:
    """classify_flow → overlay handoff. Frozen; runtime-validated at consumption."""

    ticker: str
    as_of_date: date
    flow_bin: FlowBin
    unavailable_reason: Optional[UnavailableReason] = None
