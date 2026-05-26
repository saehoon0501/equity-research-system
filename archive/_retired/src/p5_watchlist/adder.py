"""P5 watchlist adder — append-on-ADD-verdict path.

Per v3 spec Section 2.1 funnel + ``db/migrations/007_v3_watchlist_positions.sql``::

    P4 PMSupervisor.decision == 'ADD'
        ↓
    derive regime_sensitivity from Macro-Regime style output (Section 4.8)
    derive conviction_threshold from mode (Section 2.2 mode-specific
        discipline: B≥0.7, B'≥0.6, C≥0.5; per-name override allowed)
    HMAC-sign thesis_pillars_original + scenario_A_base_projections
        via watchlist HMAC producer (Section 6.2)
    INSERT into watchlist (ticker PK; UPDATE allowed downstream)

The two HMAC-signed JSONB columns are required by Section 6 Q5 + Channel 1
(pillar drift) and Channel 2 (outcome divergence) of the anchor-drift
verifier — they're the canonical "what was the original thesis?" anchor
the verifier compares against drift-of-narrative attempts later.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

from src.watchlist.hmac_producer import sign_watchlist_row

_LOG = logging.getLogger(__name__)


# Mode-specific conviction thresholds per Section 2.2 mode-specific discipline.
_CONVICTION_THRESHOLDS: dict[str, float] = {
    "B": 0.70,
    "B_prime": 0.60,
    "C": 0.50,
}

_VALID_MODES: frozenset[str] = frozenset(_CONVICTION_THRESHOLDS.keys())
_VALID_QUALITY: frozenset[str] = frozenset({"HIGH", "STANDARD"})
_VALID_SENSITIVITY: frozenset[str] = frozenset({"HIGH", "MEDIUM", "LOW"})


# ---------------------------------------------------------------------------
# Inputs / Outputs
# ---------------------------------------------------------------------------


@dataclass
class WatchlistAddInput:
    """Typed bundle of inputs the P5 adder needs.

    Per Section 4.8 sensitivity-tagging: regime_sensitivity is sourced from
    the Macro-Regime style's Phase A/B output. We accept either the verbatim
    string ('HIGH'/'MEDIUM'/'LOW') OR the raw style payload from which the
    derivation function extracts it.
    """

    ticker: str
    mode: str  # 'B' | 'B_prime' | 'C'
    company_quality_flag: str  # 'HIGH' | 'STANDARD'

    # P4 outputs:
    pm_supervisor_decision: str  # must be 'ADD' to proceed
    thesis_pillars_original: Sequence[Mapping[str, Any]]  # P3+P4 pillar set
    scenario_A_base_projections: Mapping[str, Any]  # P2 scenario A baseline

    # Macro-Regime style output (verbatim string OR full payload).
    macro_regime_style_output: Any

    # Per-name override of the mode-default conviction threshold (Section 2.2).
    conviction_threshold_override: Optional[float] = None

    # Versioning (Section 5 Q1 audit-trail bundle).
    parameters_version: Optional[UUID] = None

    # Optional explicit timestamp; defaults to NOW().
    added_at: Optional[_dt.datetime] = None


@dataclass
class WatchlistAddOutcome:
    """Result of the P5 INSERT path."""

    ticker: str
    inserted: bool
    mode: str
    company_quality_flag: str
    conviction_threshold: float
    regime_sensitivity: str
    thesis_pillars_original_hmac: str
    scenario_A_base_projections_hmac: str
    added_at: _dt.datetime
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Derivation helpers
# ---------------------------------------------------------------------------


def derive_conviction_threshold(
    mode: str, *, override: Optional[float] = None
) -> float:
    """Per Section 2.2 mode-specific discipline (B≥0.7, B'≥0.6, C≥0.5).

    Per-name override allowed (e.g., a particularly defensible Mode-C name
    may earn a 0.6 threshold). Override must be in [0, 1].
    """
    if mode not in _VALID_MODES:
        raise ValueError(
            f"mode {mode!r} not in {_VALID_MODES} — see Section 2.2"
        )
    if override is not None:
        if not 0.0 <= override <= 1.0:
            raise ValueError(
                f"conviction_threshold_override {override!r} not in [0, 1]"
            )
        return float(override)
    return _CONVICTION_THRESHOLDS[mode]


def derive_regime_sensitivity(macro_regime_style_output: Any) -> str:
    """Extract regime_sensitivity tag from Macro-Regime style output.

    Per Section 4.8 sensitivity-tagging:
        At P5 watchlist-add, each name tagged regime-sensitivity HIGH/
        MEDIUM/LOW by Macro-Regime style agent during Phase A. When S0
        fires regime-shift, only HIGH auto-re-underwrite.

    Accepted shapes (in order of preference):
      * verbatim string 'HIGH'/'MEDIUM'/'LOW'
      * dict with key ``regime_sensitivity`` → string
      * dict with key ``rationale_payload.regime_sensitivity``
      * dict-of-dicts where any value contains ``regime_sensitivity``

    Defensive fallback: returns 'MEDIUM' (quarterly review per Section 4.8)
    when no tag is found rather than failing — Section 4.8 notes that
    medium = "quarterly review" is the prudent default.
    """
    if isinstance(macro_regime_style_output, str):
        s = macro_regime_style_output.upper().strip()
        if s in _VALID_SENSITIVITY:
            return s

    if isinstance(macro_regime_style_output, Mapping):
        # Top-level direct.
        rs = macro_regime_style_output.get("regime_sensitivity")
        if isinstance(rs, str) and rs.upper() in _VALID_SENSITIVITY:
            return rs.upper()
        # Nested under rationale_payload.
        rp = macro_regime_style_output.get("rationale_payload")
        if isinstance(rp, Mapping):
            rs = rp.get("regime_sensitivity")
            if isinstance(rs, str) and rs.upper() in _VALID_SENSITIVITY:
                return rs.upper()
        # Search one level deeper (e.g., {macro_regime: {regime_sensitivity: ...}}).
        for v in macro_regime_style_output.values():
            if isinstance(v, Mapping):
                rs = v.get("regime_sensitivity")
                if isinstance(rs, str) and rs.upper() in _VALID_SENSITIVITY:
                    return rs.upper()

    _LOG.warning(
        "derive_regime_sensitivity: no tag found in macro_regime_style_output; "
        "defaulting to MEDIUM per Section 4.8 quarterly-review fallback"
    )
    return "MEDIUM"


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def _validate(inp: WatchlistAddInput) -> None:
    if inp.pm_supervisor_decision != "ADD":
        raise ValueError(
            f"P5 only accepts PMSupervisor decision='ADD'; got "
            f"{inp.pm_supervisor_decision!r} for {inp.ticker} — "
            f"WATCH/PASS routes diverge per Section 2.1 funnel."
        )
    if inp.mode not in _VALID_MODES:
        raise ValueError(f"mode {inp.mode!r} not in {_VALID_MODES}")
    if inp.company_quality_flag not in _VALID_QUALITY:
        raise ValueError(
            f"company_quality_flag {inp.company_quality_flag!r} "
            f"not in {_VALID_QUALITY}"
        )
    if not inp.thesis_pillars_original:
        raise ValueError("thesis_pillars_original is required and non-empty")
    if not inp.scenario_A_base_projections:
        raise ValueError("scenario_A_base_projections is required")


def _to_jsonb(value: Any) -> str:
    """Serialize JSONB value for psycopg parameter binding."""
    return json.dumps(value, ensure_ascii=False, default=str)


def add_to_watchlist(
    inp: WatchlistAddInput,
    *,
    conn: Any = None,
    hmac_key: Optional[bytes] = None,
) -> WatchlistAddOutcome:
    """Add one ticker to the watchlist after a P4 ADD verdict.

    Args:
        inp: typed input bundle (P4 + Stage 2 mode classifier outputs).
        conn: psycopg-style connection. If None, the function dry-runs and
            returns the outcome with ``inserted=False`` so callers can use
            this for HMAC dry-runs / unit tests without a DB.
        hmac_key: explicit override; falls back to ``WATCHLIST_HMAC_SECRET``
            env var (per ``src/watchlist/hmac_producer.py``).

    Returns:
        ``WatchlistAddOutcome`` with HMAC signatures + DB-write status.

    Per v3 spec Section 2.1 + 4.8 + 6.2.
    """
    _validate(inp)

    threshold = derive_conviction_threshold(
        inp.mode, override=inp.conviction_threshold_override
    )
    regime_sensitivity = derive_regime_sensitivity(inp.macro_regime_style_output)

    # Sign anchors via watchlist HMAC producer.
    sigs = sign_watchlist_row(
        list(inp.thesis_pillars_original),
        dict(inp.scenario_A_base_projections),
        hmac_key=hmac_key,
    )

    added_at = inp.added_at or _dt.datetime.now(_dt.timezone.utc)

    if conn is None:
        # Dry-run path; HMAC computed but no DB write.
        return WatchlistAddOutcome(
            ticker=inp.ticker,
            inserted=False,
            mode=inp.mode,
            company_quality_flag=inp.company_quality_flag,
            conviction_threshold=threshold,
            regime_sensitivity=regime_sensitivity,
            thesis_pillars_original_hmac=sigs["thesis_pillars_original_hmac"],
            scenario_A_base_projections_hmac=sigs[
                "scenario_A_base_projections_hmac"
            ],
            added_at=added_at,
        )

    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO watchlist (
                ticker, mode, company_quality_flag, conviction_threshold,
                thesis_pillars_original, thesis_pillars_original_hmac,
                scenario_A_base_projections, scenario_A_base_projections_hmac,
                regime_sensitivity, added_at, last_reunderwritten_at,
                parameters_version
            ) VALUES (
                %s, %s, %s, %s,
                %s::jsonb, %s,
                %s::jsonb, %s,
                %s, %s, %s, %s
            )
            ON CONFLICT (ticker) DO UPDATE SET
                mode = EXCLUDED.mode,
                company_quality_flag = EXCLUDED.company_quality_flag,
                conviction_threshold = EXCLUDED.conviction_threshold,
                thesis_pillars_original = EXCLUDED.thesis_pillars_original,
                thesis_pillars_original_hmac = EXCLUDED.thesis_pillars_original_hmac,
                scenario_A_base_projections = EXCLUDED.scenario_A_base_projections,
                scenario_A_base_projections_hmac =
                    EXCLUDED.scenario_A_base_projections_hmac,
                regime_sensitivity = EXCLUDED.regime_sensitivity,
                last_reunderwritten_at = EXCLUDED.last_reunderwritten_at,
                parameters_version = EXCLUDED.parameters_version
            """,
            (
                inp.ticker,
                inp.mode,
                inp.company_quality_flag,
                threshold,
                _to_jsonb(list(inp.thesis_pillars_original)),
                sigs["thesis_pillars_original_hmac"],
                _to_jsonb(dict(inp.scenario_A_base_projections)),
                sigs["scenario_A_base_projections_hmac"],
                regime_sensitivity,
                added_at,
                added_at,
                str(inp.parameters_version) if inp.parameters_version else None,
            ),
        )
    finally:
        cur.close()
    if hasattr(conn, "commit"):
        try:
            conn.commit()
        except Exception:  # pragma: no cover - test conn may not need commit
            pass

    return WatchlistAddOutcome(
        ticker=inp.ticker,
        inserted=True,
        mode=inp.mode,
        company_quality_flag=inp.company_quality_flag,
        conviction_threshold=threshold,
        regime_sensitivity=regime_sensitivity,
        thesis_pillars_original_hmac=sigs["thesis_pillars_original_hmac"],
        scenario_A_base_projections_hmac=sigs["scenario_A_base_projections_hmac"],
        added_at=added_at,
    )


__all__ = [
    "WatchlistAddInput",
    "WatchlistAddOutcome",
    "add_to_watchlist",
    "derive_conviction_threshold",
    "derive_regime_sensitivity",
]
