"""Cross-plan handoff contracts for tactical overlay.

INV-COMPOSE-1: Plan B (bin_classifier) emits exactly TacticalSignal shape;
               Plan C (overlay) consumes exactly this shape.
INV-2.1-A:     tactical_disposition enum is disjoint from summary_code enum.

Per Section 2 v3-final + Section 2.1 v5-final.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

# Enum types (Literal for static type checking; .__args__ exposes values at runtime)
TacticalBin = Literal["positive", "neutral", "negative", "unavailable"]
TacticalDisposition = Literal["HOLD", "BUY-HIGH", "BUY-MED", "AVOID"]
Conviction = Literal["HIGH", "MEDIUM", "LOW"]
UnavailableReason = Literal["insufficient_price_history", "rf_resolver_staleness"]


@dataclass(frozen=True)
class TacticalSignal:
    """Plan B → Plan C handoff. Frozen; runtime-validated at consumption."""

    ticker: str
    as_of_date: date
    tactical_bin: TacticalBin
    rf_degenerate: bool
    unavailable_reason: Optional[UnavailableReason] = None
