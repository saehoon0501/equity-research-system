"""Tactical overlay package — Section 2 v3-final + Section 2.1 v5-final.

Implements the unified tactical overlay agent's Python compute layer:
- contracts: TacticalSignal frozen dataclass (cross-plan handoff per INV-COMPOSE-1)
- bin_classifier: Antonacci dual-momentum + resolve_rf_at helper (INV-B6)
- overlay: cell-size selector + tactical_disposition categorical mapping (INV-C1)

Spec references:
- docs/superpowers/plans/2026-05-21-section2-tactical-overlay-v3-final.md
- docs/superpowers/consensus/2026-05-21-section2.1-label-vocabulary.md
"""
