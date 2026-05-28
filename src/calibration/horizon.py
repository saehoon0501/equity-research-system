"""Signal-type -> primary_horizon -> recommendation_outcomes column mapping.

WS-4 (P0-2 / mig-045). ``primary_horizon`` is CHECK-constrained at the DB to
exactly ``{'30d','90d','1y'}`` (see db/migrations/045_calibration_resolver.sql),
each mapping 1:1 to an *existing* ``recommendation_outcomes`` column triple:

    '30d' -> t_plus_30d_return / benchmark_return_30d / delta_vs_benchmark_30d
    '90d' -> t_plus_90d_return / benchmark_return_90d / delta_vs_benchmark_90d
    '1y'  -> t_plus_1y_return  / benchmark_return_1y  / delta_vs_benchmark_1y

'1y' IS the 365-calendar-day window. There is intentionally NO ``t_plus_365``
column anywhere — resolving 365 days uses ``t_plus_1y_return``.

Signal-type -> horizon (WS-4 spec / parallel plan):
    tactical, flow      -> '30d'
    fundamental         -> '90d' (default) or '1y'

``fundamental`` is multi-horizon: the resolver clusters BOTH the 90d and 1y rows
under the same rec_id. ``primary_horizon_for`` returns the *default* primary
window; ``horizons_for`` returns every window the signal type is resolved at.
"""

from __future__ import annotations

# The three legal primary_horizon values, in ascending window length. Mirrors
# the CHECK constraint in mig-045 exactly — keep in sync.
LEGAL_HORIZONS: tuple[str, ...] = ("30d", "90d", "1y")

# horizon -> (return_col, benchmark_col, delta_col) on recommendation_outcomes.
# No '365' key — '1y' IS the 365-day window.
_HORIZON_COLUMNS: dict[str, tuple[str, str, str]] = {
    "30d": ("t_plus_30d_return", "benchmark_return_30d", "delta_vs_benchmark_30d"),
    "90d": ("t_plus_90d_return", "benchmark_return_90d", "delta_vs_benchmark_90d"),
    "1y": ("t_plus_1y_return", "benchmark_return_1y", "delta_vs_benchmark_1y"),
}

# horizon -> calendar days in the realized-return window. '1y' == 365 calendar
# days (mig-013's resolver convention), NOT a trading-day count.
_HORIZON_DAYS: dict[str, int] = {"30d": 30, "90d": 90, "1y": 365}

# signal_type (lowercased) -> default primary_horizon.
_SIGNAL_PRIMARY: dict[str, str] = {
    "tactical": "30d",
    "flow": "30d",
    "fundamental": "90d",
}

# signal_type -> every horizon the resolver resolves it at (multi-horizon
# clustering for fundamental rows).
_SIGNAL_HORIZONS: dict[str, tuple[str, ...]] = {
    "tactical": ("30d",),
    "flow": ("30d",),
    "fundamental": ("90d", "1y"),
}


def primary_horizon_for(signal_type: str) -> str:
    """Default primary_horizon for a signal type. Raises on unknown type."""
    key = (signal_type or "").strip().lower()
    try:
        return _SIGNAL_PRIMARY[key]
    except KeyError as exc:
        raise ValueError(
            f"unknown signal_type {signal_type!r}; "
            f"expected one of {sorted(_SIGNAL_PRIMARY)}"
        ) from exc


def horizons_for(signal_type: str) -> tuple[str, ...]:
    """All horizons resolved for a signal type (multi-horizon for fundamental)."""
    key = (signal_type or "").strip().lower()
    try:
        return _SIGNAL_HORIZONS[key]
    except KeyError as exc:
        raise ValueError(
            f"unknown signal_type {signal_type!r}; "
            f"expected one of {sorted(_SIGNAL_HORIZONS)}"
        ) from exc


def columns_for(horizon: str) -> tuple[str, str, str]:
    """(return_col, benchmark_col, delta_col) for a horizon. Raises on illegal."""
    try:
        return _HORIZON_COLUMNS[horizon]
    except KeyError as exc:
        raise ValueError(
            f"illegal primary_horizon {horizon!r}; "
            f"legal values are {LEGAL_HORIZONS} (no 't_plus_365')"
        ) from exc


def return_column_for(horizon: str) -> str:
    """The t_plus_*_return column a horizon joins to. Raises on illegal."""
    return columns_for(horizon)[0]


def window_days_for(horizon: str) -> int:
    """Calendar days in a horizon's realized-return window ('1y' == 365)."""
    try:
        return _HORIZON_DAYS[horizon]
    except KeyError as exc:
        raise ValueError(
            f"illegal primary_horizon {horizon!r}; legal values are {LEGAL_HORIZONS}"
        ) from exc
