"""L4 / P8 — View-refresh discipline (daily monitor).

Critical-path component for v0.1 per
``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.5 (lines 458-512). The daily monitor is the **slow-loop**
heartbeat: once per trading day per ticker we sweep the world for
events, ask the LLM judge to classify materiality (M-1 / M-2 / M-3),
route the materiality verdict to the appropriate downstream agents,
and evaluate Section 4.5 Q3 mode-tuned cut thresholds.

Pipeline (per spec Section 4.5):

    event_ingestor          (1) pull events for (ticker, date)
        -> materiality_classifier (2) Sonnet/Opus LLM judge -> M-{1,2,3}
            -> router               (3) hybrid floor + LLM agent picker
                -> cut_evaluator    (4) mode-tuned cut threshold check
                    -> refresh_emitter  (5) write daily_refresh_log row +
                                            materiality_events rows + alerts

Persistence:
- daily_refresh_log     (one row per ticker per day; append-only)
- materiality_events    (one row per LLM-classified event; append-only)
- unread_alerts         (M-2/M-3 fires only; STATE table)
- materiality_classifier_drift  (Phase 4 Q8 quarterly drift watch)

Model constraint (operator-locked, Section 4.5):
- M-1 / M-2: claude-sonnet-4-6 default
- M-3 escalation: claude-opus-4-7
- NO Haiku anywhere in v3.

Materiality field convention (Phase 4 cleanup #4):
- Stored as integer 1 / 2 / 3 (SMALLINT in Postgres).
- ``materiality_label`` is a derived 'M-1' / 'M-2' / 'M-3' string.

Public API:

    from l4_daily_monitor.event_ingestor import ingest_events
    from l4_daily_monitor.materiality_classifier import classify_materiality
    from l4_daily_monitor.router import route_materiality
    from l4_daily_monitor.cut_evaluator import evaluate_cut
    from l4_daily_monitor.refresh_emitter import run_daily_refresh
    from l4_daily_monitor.drift_detector import run_quarterly_drift_check

Reference: ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
    Section 4.5 (Q1-Q3) — daily monitor + materiality routing + cut thresholds
    Section 6 Q1 — verbatim-quote audit-trail enforcement
    Section 7 PB#4 — unread-alert queue
    Phase 4 Q8 — materiality classifier drift watch
"""

from __future__ import annotations

__all__ = [
    "MATERIALITY_M1",
    "MATERIALITY_M2",
    "MATERIALITY_M3",
    "MATERIALITY_LABELS",
    "MODE_B",
    "MODE_B_PRIME",
    "MODE_C",
    "DEFAULT_MODEL",
    "ESCALATION_MODEL",
    "PROMPT_VERSION",
    "EVENT_TYPE_AGENT_LOOKUP",
    "ALL_AGENTS",
    "JUDGE_CONFIDENCE_FLOOR",
    "MIN_DRIFT_SAMPLE_SIZE",
    "DRIFT_KAPPA_FLOOR",
]

# Materiality (Phase 4 cleanup #4: int storage; label derived).
MATERIALITY_M1: int = 1
MATERIALITY_M2: int = 2
MATERIALITY_M3: int = 3

MATERIALITY_LABELS: dict[int, str] = {
    MATERIALITY_M1: "M-1",
    MATERIALITY_M2: "M-2",
    MATERIALITY_M3: "M-3",
}

# Mode bins (mirror mode_classifier package + DB CHECK constraint).
MODE_B: str = "B"
MODE_B_PRIME: str = "B_prime"
MODE_C: str = "C"

# Model identifiers per Section 4.5 (operator-locked: Sonnet/Opus only).
# Spec v3 (2026-04-29) pins these versions; bump together when re-locked.
DEFAULT_MODEL: str = "claude-sonnet-4-6"
ESCALATION_MODEL: str = "claude-opus-4-7"
PROMPT_VERSION: str = "L4-daily-refresh-v0.1"

# Five debate agents per Section 4.5 Q2 / Section 4.4 P4 re-underwrite.
ALL_AGENTS: tuple[str, ...] = (
    "Quality",
    "Growth",
    "Value",
    "Macro-Regime",
    "Quant-Technical",
)

# Section 4.5 Q2 fallback table — used when judge confidence < FLOOR.
EVENT_TYPE_AGENT_LOOKUP: dict[str, tuple[str, ...]] = {
    "earnings_call_remark":   ("Quality", "Growth"),
    "eps_surprise":           ("Quality", "Growth"),
    "earnings_miss":          ("Quality", "Growth"),
    "guidance_cut":           ("Quality", "Growth"),
    "macro_print":            ("Macro-Regime", "Value"),
    "fed_decision":           ("Macro-Regime", "Value"),
    "cpi_print":              ("Macro-Regime", "Value"),
    "nfp_print":              ("Macro-Regime", "Value"),
    "smart_money_signal":     ("Quality", "Quant-Technical"),
    "13f_filing":             ("Quality", "Quant-Technical"),
    "13d_filing":             ("Quality", "Quant-Technical"),
    "13g_filing":             ("Quality", "Quant-Technical"),
    "sector_rotation":        ("Macro-Regime", "Quant-Technical"),
    "peer_move":              ("Macro-Regime", "Quant-Technical"),
    "regulatory":             ("Quality", "Value"),
    "litigation":             ("Quality", "Value"),
    "product_announcement":   ("Growth", "Value"),
    "capex_announcement":     ("Growth", "Value"),
    "ma_announcement":        ("Growth", "Value"),
    "credit_event":           ("Macro-Regime", "Value"),
    "spread_blowout":         ("Macro-Regime", "Value"),
    "filing_8k":              ("Quality", "Value"),
    "filing_10q":             ("Quality", "Growth"),
    "filing_10k":             ("Quality", "Growth"),
}

# Section 4.5 Q2: judge confidence floor below which we fall back to lookup.
JUDGE_CONFIDENCE_FLOOR: float = 0.6

# Phase 4 Q8: hard floor on quarterly drift sample size.
MIN_DRIFT_SAMPLE_SIZE: int = 30

# Phase 4 Q8 + Section 7.2 launch gate: kappa < 0.61 sustained = M-2 fire.
DRIFT_KAPPA_FLOOR: float = 0.61
