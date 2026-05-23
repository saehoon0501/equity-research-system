"""Cross-plan handoff contracts for mean-reversion overlay (v0.4.0 standalone).

Mirrors src/p9_flow_overlay/contracts.py at structural level — same Literal
vocabulary discipline, same frozen-dataclass handoff. Per the v0.4.0 plan,
mean-reversion-overlay is STANDALONE (no pm-supervisor cell completion in v0.4.0).

v0.4.2 will add ReversionDisposition + cell types when wiring to pm-supervisor.
v0.4.0 omits those entirely.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

# Enum types (Literal for static type checking; .__args__ exposes values at runtime)
ReversionBin = Literal["MR_OVERSOLD", "MR_NEUTRAL", "MR_OVERBOUGHT", "MR_UNAVAILABLE"]
AuditMode = Literal["standalone", "snapshot"]
UnavailableReason = Literal[
    "insufficient_price_history",
    "corrupt_price_data",
]


@dataclass(frozen=True)
class ReversionSignal:
    """classify_reversion handoff. Frozen; runtime-validated at consumption."""

    ticker: str
    as_of_date: date
    reversion_bin: ReversionBin
    unavailable_reason: Optional[UnavailableReason] = None
