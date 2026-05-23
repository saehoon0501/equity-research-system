"""Flow overlay: cell-size selector + flow_disposition mapping.

Mirrors src/p8_tactical_overlay/overlay.py 1:1 in signature. Same selector
semantics — band_max on positive, midpoint on neutral, band_min on negative
or unavailable. Same LOW-row hard-zero discipline.

Architectural decoupling: pure compute over inputs (band values + conviction +
flow_bin). Agent layer reads sizing.conviction_band.* from postgres
parameters_active view.

INV-FLOW-C1: flow_disposition.mapping is complete over (conviction × flow_bin).
INV-FLOW-2.1-A: flow_disposition enum is disjoint from canonical summary_code enum.

The 12-cell mapping below is the v0.1 default (same shape as tactical's
disposition map; /review-me may diverge specific cells once flow signal
behavior is observed).
"""
from __future__ import annotations

from typing import Optional

# v0.1 default 12-cell mapping (mirrors tactical's _DISPOSITION_MAP).
# Open item for /review-me: whether MEDIUM × positive should be BUY-MED here
# (matching tactical's load-bearing case) or downweighted given that flow
# signal is more transient than the Antonacci dual-momentum signal.
_DISPOSITION_MAP: dict[tuple[str, str], str] = {
    ("HIGH", "negative"): "HOLD",
    ("HIGH", "neutral"): "HOLD",
    ("HIGH", "positive"): "BUY-HIGH",
    ("HIGH", "unavailable"): "HOLD",
    ("MEDIUM", "negative"): "HOLD",
    ("MEDIUM", "neutral"): "HOLD",
    ("MEDIUM", "positive"): "BUY-MED",
    ("MEDIUM", "unavailable"): "HOLD",
    ("LOW", "negative"): "AVOID",
    ("LOW", "neutral"): "AVOID",
    ("LOW", "positive"): "AVOID",
    ("LOW", "unavailable"): "HOLD",
}


def flow_cell_size_pct(
    conviction: str,
    flow_bin: str,
    band_min_pct: Optional[float] = None,
    band_max_pct: Optional[float] = None,
) -> float:
    """Returns cell size_pct as a VIEW of existing sizing.conviction_band.* params.

    Signature matches src/p8_tactical_overlay/overlay.py::tactical_cell_size_pct
    so pm-supervisor's Stage 3 cell-completion logic can call both with the
    same argument shape.

    Args:
        conviction: 'HIGH' | 'MEDIUM' | 'LOW'.
        flow_bin: 'positive' | 'neutral' | 'negative' | 'unavailable'.
        band_min_pct: lower bound of conviction band; required for non-LOW.
        band_max_pct: upper bound; required for non-LOW.

    Returns:
        size_pct in [0, band_max_pct]. LOW row hard-zeroed.
    """
    if conviction == "LOW":
        return 0.0
    if band_min_pct is None or band_max_pct is None:
        raise ValueError(
            f"non-LOW conviction {conviction!r} requires band_min_pct + band_max_pct"
        )
    if flow_bin == "positive":
        return float(band_max_pct)
    if flow_bin == "neutral":
        return (float(band_min_pct) + float(band_max_pct)) / 2.0
    return float(band_min_pct)


def flow_disposition(conviction: str, flow_bin: str) -> str:
    """Returns flow_disposition per the 12-cell categorical mapping.

    Honest framing: flow_bin is the BUY trigger; conviction = LOW-row veto.
    Same composition discipline as tactical_disposition.
    """
    key = (conviction, flow_bin)
    if key not in _DISPOSITION_MAP:
        raise ValueError(f"INV-FLOW-C1 violation: no mapping for {key}")
    return _DISPOSITION_MAP[key]


def disposition_map() -> dict[tuple[str, str], str]:
    """Public accessor for the 12-cell matrix; returns a shallow copy."""
    return dict(_DISPOSITION_MAP)
