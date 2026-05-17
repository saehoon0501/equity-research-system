"""Dimension fetchers — one module per Tier-1 dimension (v3 §4.1 / §3.3).

Each module exposes a `compute(asof_date, history_days)` function returning a
`DimensionResult` (see `classifier`). All fetchers are pure data-pull +
classification; no DB writes happen here.
"""

from __future__ import annotations
