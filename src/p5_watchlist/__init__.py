"""p5_watchlist — P5 phase: research-approved name → watchlist row.

Per v3 spec Section 2.1 funnel composition:

    P4 deep dive (5-style debate, ADD/WATCH/PASS verdict)
        ↓
    P5 watchlist add (research artifact — NO portfolio cap)
        ↓
    P6 disposition determination
        ↓
    P7 entry execution recommendation

P5 takes a P4 PMSupervisor verdict of ``ADD`` and writes one immutable
watchlist row (mode + quality + thesis pillars + scenario A baselines +
regime sensitivity + conviction threshold). The two anchor JSONB fields
(``thesis_pillars_original`` + ``scenario_A_base_projections``) are
HMAC-signed at insert time so anchor-drift detection (Section 6.2) can
flag tampering.

Public surface:
  * ``add_to_watchlist`` — orchestrates the P5 row build + HMAC sign + INSERT.
  * ``WatchlistAddInput`` — typed input bundle.
  * ``WatchlistAddOutcome`` — typed output (row written + signatures).

Reference:
  docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 2.1 (funnel composition; watchlist vs portfolio)
    Section 2.2 (mode-specific conviction thresholds: B≥0.7, B'≥0.6, C≥0.5)
    Section 4.6 (downstream consumption — P5 row anchors recommendation
                 emitter scenario + pillar references)
    Section 4.8 (Macro-Regime sensitivity tagging at P5)
    Section 6 Q5 (anchor-drift HMAC contract)
  db/migrations/007_v3_watchlist_positions.sql
"""

from __future__ import annotations

from src.p5_watchlist.adder import (
    WatchlistAddInput,
    WatchlistAddOutcome,
    add_to_watchlist,
    derive_conviction_threshold,
    derive_regime_sensitivity,
)

__all__ = [
    "WatchlistAddInput",
    "WatchlistAddOutcome",
    "add_to_watchlist",
    "derive_conviction_threshold",
    "derive_regime_sensitivity",
]
