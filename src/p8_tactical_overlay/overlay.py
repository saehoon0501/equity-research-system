"""Tactical overlay: cell-size selector + tactical_disposition mapping.

Per Section 2 v3-final Plan C v5 + Section 2.1 v5-final.

Architectural decoupling: this module is pure compute over its inputs (band values
+ conviction + tactical_bin). The agent layer is responsible for reading
sizing.conviction_band.* parameters from postgres parameters_active view.

INV-C1: tactical_disposition.mapping is complete over (conviction × tactical_bin).
INV-2.1-A: tactical_disposition enum is disjoint from summary_code enum.
"""
from __future__ import annotations

from typing import Optional

# Section 2.1 v5-final categorical mapping (12 cells; INV-C1 complete coverage)
_DISPOSITION_MAP: dict[tuple[str, str], str] = {
    # HIGH row: BUY-HIGH on positive concurrent confirmation
    ("HIGH", "negative"): "HOLD",
    ("HIGH", "neutral"): "HOLD",
    ("HIGH", "positive"): "BUY-HIGH",
    ("HIGH", "unavailable"): "HOLD",
    # MEDIUM row: BUY-MED on positive concurrent confirmation (load-bearing case)
    ("MEDIUM", "negative"): "HOLD",
    ("MEDIUM", "neutral"): "HOLD",
    ("MEDIUM", "positive"): "BUY-MED",
    ("MEDIUM", "unavailable"): "HOLD",
    # LOW row: AVOID on affirmative signal; HOLD on unavailable so that
    # data-insufficiency (e.g., recent IPO) defers rather than compounding the
    # LOW-conviction veto into an AVOID without affirmative evidence.
    ("LOW", "negative"): "AVOID",
    ("LOW", "neutral"): "AVOID",
    ("LOW", "positive"): "AVOID",
    ("LOW", "unavailable"): "HOLD",
}


def tactical_cell_size_pct(
    conviction: str,
    tactical_bin: str,
    band_min_pct: Optional[float] = None,
    band_max_pct: Optional[float] = None,
) -> float:
    """Returns cell size_pct as a VIEW of existing sizing.conviction_band.* params.

    Args:
        conviction: 'HIGH' | 'MEDIUM' | 'LOW'.
        tactical_bin: 'positive' | 'neutral' | 'negative' | 'unavailable'.
        band_min_pct: lower bound of conviction band from parameters_active
                      (e.g., sizing.conviction_band.HIGH.min_pct = 3.0). Required
                      for non-LOW conviction; ignored for LOW.
        band_max_pct: upper bound; required for non-LOW conviction.

    Returns:
        size_pct in [0, band_max_pct]. LOW row hard-zeroed.

    Mapping (Section 2 v3-final Plan A v3 selector):
    - positive    → band_max_pct
    - neutral     → midpoint = (band_min_pct + band_max_pct) / 2
    - negative    → band_min_pct
    - unavailable → band_min_pct  (conservative under data-insufficiency; symmetric
                                  with absent-evidence treatment so that recent
                                  IPOs are not silently sized at the midpoint)
    """
    if conviction == "LOW":
        return 0.0  # Plan A LOW row hard-zero discipline
    if band_min_pct is None or band_max_pct is None:
        raise ValueError(
            f"non-LOW conviction {conviction!r} requires band_min_pct + band_max_pct"
        )
    if tactical_bin == "positive":
        return float(band_max_pct)
    if tactical_bin == "neutral":
        return (float(band_min_pct) + float(band_max_pct)) / 2.0
    return float(band_min_pct)


def tactical_disposition(conviction: str, tactical_bin: str) -> str:
    """Returns tactical_disposition per Section 2.1 v5-final categorical mapping.

    Honest framing: tactical_bin is the BUY trigger; conviction = LOW-row veto.
    """
    key = (conviction, tactical_bin)
    if key not in _DISPOSITION_MAP:
        raise ValueError(f"INV-C1 violation: no mapping for {key}")
    return _DISPOSITION_MAP[key]
