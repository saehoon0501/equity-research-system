"""Flow overlay package — v0.1 CTA-proximity sub-signal.

Implements the unified flow overlay agent's Python compute layer:
- contracts: FlowSignal frozen dataclass (cross-plan handoff per INV-COMPOSE-FLOW-1)
- bin_classifier: CTA-proximity composite classifier (MA distance + TSMOM + Donchian)
- overlay: cell-size selector + flow_disposition categorical mapping (INV-FLOW-C1)

Scope: v0.1 CTA-proximity only. v0.2 adds gamma-regime sub-signal (DTE-bucketed GEX
from polygon options chain). v0.3 adds crowding sub-signal (SI/DTC/13F).

Spec references:
- plans/first-let-s-plan-the-serialized-hanrahan.md (this v0.1 plan)
- docs/superpowers/research/2026-05-23-cta-and-gamma-mechanics.md (research source)
"""
