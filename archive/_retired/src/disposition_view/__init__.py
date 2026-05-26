"""disposition_view — multi-horizon disposition + mode-fit dashboard.

Per v3 spec sections:
  - Section 4.6 Q2 — Multi-horizon disposition view (Short / Mid / Long with
    mode-anchored primary horizon expanded by default).
  - Section 5.4 — `/disposition` slash command.
  - Phase 4 Q5 — Mode-fit dashboard (per-name mode + realized 252d vol +
    last_confirmed_date + flag_status).

This package is the LOADER + RENDERER for the disposition view. It does NOT
write rows to any underlying table; reads only.

Public surface:
  - DispositionRow                        — dataclass for one watchlist name
  - HorizonSignal                         — per-horizon (short/mid/long) signal
  - ModeFitRow                            — Phase 4 Q5 dashboard row
  - get_disposition_rows(conn, ...)       — Postgres loader
  - derive_horizon_signals(row)           — derive short/mid/long signals
  - mode_to_primary_horizon(mode)         — mode → primary-horizon mapping
  - render_disposition(rows, ...)         — terminal-rendered markdown
  - render_mode_fit_dashboard(rows)       — Phase 4 Q5 dashboard markdown

Reference:
  docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 2.2 (mode silent-failure detection — Phase 4 Q5)
    Section 4.6 Q2 (multi-horizon disposition view)
    Section 5.4 (/disposition slash command)
  db/migrations/007_v3_watchlist_positions.sql
  db/migrations/008_v3_recommendations.sql
  db/migrations/009_v3_daily_monitor.sql
  db/migrations/010_v3_drift_detection.sql
"""

from __future__ import annotations

from src.disposition_view.horizon_signals import (
    HORIZONS,
    HorizonSignal,
    derive_horizon_signals,
    mode_to_primary_horizon,
)
from src.disposition_view.loader import (
    DispositionRow,
    ModeFitRow,
    get_disposition_rows,
)
from src.disposition_view.mode_fit_dashboard import (
    FLAG_STATUSES,
    derive_flag_status,
)
from src.disposition_view.renderer import (
    render_disposition,
    render_mode_fit_dashboard,
    render_single_ticker,
)

__all__ = [
    "DispositionRow",
    "FLAG_STATUSES",
    "HORIZONS",
    "HorizonSignal",
    "ModeFitRow",
    "derive_flag_status",
    "derive_horizon_signals",
    "get_disposition_rows",
    "mode_to_primary_horizon",
    "render_disposition",
    "render_mode_fit_dashboard",
    "render_single_ticker",
]
