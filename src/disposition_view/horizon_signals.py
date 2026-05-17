"""Per-horizon signal derivation for the multi-horizon disposition view.

Per v3 spec Section 4.6 Q2:

  - Short horizon (≤3mo) — catalyst-driven; near-term price action; tactical.
  - Mid horizon  (3-12mo) — thesis-pillar tracking; earnings cycles;
                            positioning vs near-term path.
  - Long horizon (12+mo) — compounding metrics; secular trend; strategic.

For each watchlist name + horizon we derive:
  - signal:       BUY / HOLD / TRIM / SELL
  - key_signal:   short text describing the dominant driver
  - detail:       expanded payload (only rendered for the primary horizon
                  by default; secondary horizons collapse).

Mode → primary horizon mapping (Section 4.6 Q2):
  - B   → Long primary
  - B'  → Mid primary
  - C   → Short primary
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

# Canonical horizon order (rendering left → right).
HORIZONS: tuple[str, ...] = ("short", "mid", "long")

# Mode-anchored primary horizon per Section 4.6 Q2.
_MODE_PRIMARY: dict[str, str] = {
    "B": "long",
    "B_prime": "mid",
    "C": "short",
}


@dataclass(frozen=True)
class HorizonSignal:
    """One horizon's signal for a single watchlist name.

    Per v3 Section 4.6 Q2 schema:
      { signal, key_signal, detail_collapsed_by_default | detail_expanded_by_default }

    `detail` is a structured payload — rendered as a markdown details/summary
    block. `is_primary` is set to True only for the mode-anchored primary
    horizon (or whatever the operator manually toggled to).
    """

    horizon: str
    signal: str
    key_signal: str
    detail: Mapping[str, Any]
    is_primary: bool


def mode_to_primary_horizon(mode: str) -> str:
    """Return primary horizon for a mode.

    Per Section 4.6 Q2:
      B → long, B' → mid, C → short.

    Raises ValueError on unknown modes.
    """
    try:
        return _MODE_PRIMARY[mode]
    except KeyError as e:
        raise ValueError(
            f"unknown mode {mode!r} — expected one of {tuple(_MODE_PRIMARY)}"
        ) from e


def format_mode_display(mode: str) -> str:
    """Render a mode label for human-facing output.

    Internal storage uses ASCII-safe ``B_prime``, but the spec convention
    is ``B'`` (B-prime with an apostrophe). Use this whenever a mode
    appears in a markdown header, table cell, or push-alert summary.

    Unknown modes are returned unchanged so callers can surface novel
    states without crashing the renderer.
    """
    if mode == "B_prime":
        return "B'"
    return mode


def derive_horizon_signals(
    row: Any,
    *,
    primary_override: Optional[str] = None,
) -> dict[str, HorizonSignal]:
    """Derive Short / Mid / Long signals for one DispositionRow.

    Args:
        row: a DispositionRow (loader.DispositionRow).
        primary_override: if set ('short' / 'mid' / 'long'), overrides the
            mode-anchored default; emitted by the CLI's `--toggle-primary` flag.

    Returns:
        dict[horizon -> HorizonSignal] for all three horizons.

    Per v3 Section 4.6 Q2 + Phase 4 Q2 conviction rollup. The signal mapping
    rules:
      - SELL when latest refresh action contains 'exit' or kills_fired > 0
        with LOW conviction.
      - TRIM when materiality M-3 (act) AND recommendation is TRIM/SELL OR
        action is 'size_down'.
      - BUY when latest recommendation == BUY and conviction in {HIGH, MEDIUM}
        and primary horizon's driver supports it.
      - HOLD otherwise.

    Per-horizon signal differentiation:
      - Short: catalyst events from daily_refresh_log + materiality.
      - Mid:   thesis pillars + execution_context.near_term_catalysts +
               recommendation envelope.
      - Long:  conviction_breakdown + regime_sensitivity + mode certainty.
    """
    primary = primary_override or mode_to_primary_horizon(row.mode)
    if primary not in HORIZONS:
        raise ValueError(
            f"primary_override {primary!r} not in {HORIZONS}"
        )

    short = _derive_short(row, is_primary=(primary == "short"))
    mid = _derive_mid(row, is_primary=(primary == "mid"))
    long_ = _derive_long(row, is_primary=(primary == "long"))
    return {"short": short, "mid": mid, "long": long_}


# -----------------------------------------------------------------------------
# Per-horizon derivation
# -----------------------------------------------------------------------------


def _derive_short(row: Any, *, is_primary: bool) -> HorizonSignal:
    """Short horizon (≤3mo) — catalyst-driven; near-term price action."""
    materiality = row.last_refresh_materiality
    action = (row.last_refresh_action or "").lower()
    events = row.last_refresh_events or []

    # Default
    signal = "HOLD"
    key = "no near-term catalysts; quiet tape"

    # Surface catalysts from execution_context.near_term_catalysts.
    catalysts = (row.execution_context or {}).get("near_term_catalysts") or []
    if isinstance(catalysts, list) and catalysts:
        first = catalysts[0]
        if isinstance(first, dict):
            ev = first.get("event") or first.get("type") or "catalyst"
            when = first.get("date") or first.get("when") or "soon"
            key = f"upcoming {ev} ({when})"

    # Materiality routing
    if materiality == 3 or "exit" in action:
        signal = "SELL"
        key = f"M-3 fired — action: {action or 'exit'}"
    elif materiality == 2 or "size_down" in action or "trim" in action:
        signal = "TRIM"
        key = key + f"; M-2 watch ({action or 'size_down'})"
    elif (row.recommendation or "").upper() == "BUY" and (row.conviction or "").upper() in {
        "HIGH",
        "MEDIUM",
    }:
        signal = "BUY"
        key = key + f"; rec BUY ({row.conviction})"

    detail = {
        "materiality": materiality,
        "last_refresh_action": row.last_refresh_action,
        "last_refresh_date": (
            row.last_refresh_date.isoformat() if row.last_refresh_date else None
        ),
        "near_term_catalysts": catalysts,
        "events": events,
        "current_price": (row.execution_context or {}).get("current_price"),
        "technical_signals": (row.execution_context or {}).get("technical_signals"),
    }
    return HorizonSignal(
        horizon="short",
        signal=signal,
        key_signal=key,
        detail=detail,
        is_primary=is_primary,
    )


def _derive_mid(row: Any, *, is_primary: bool) -> HorizonSignal:
    """Mid horizon (3-12mo) — thesis pillars + earnings cycles."""
    rec = (row.recommendation or "HOLD").upper()
    conv = (row.conviction or "MEDIUM").upper()

    # Default routing tied to the latest recommendation envelope.
    if rec == "SELL":
        signal = "SELL"
    elif rec == "TRIM":
        signal = "TRIM"
    elif rec == "BUY" and conv in {"HIGH", "MEDIUM"}:
        signal = "BUY"
    else:
        signal = "HOLD"

    breakdown = row.conviction_breakdown or {}
    debate = breakdown.get("debate_consensus")
    kills = breakdown.get("kills_fired")
    cf = breakdown.get("counterfactual_top_3")

    pieces: list[str] = []
    if rec:
        pieces.append(f"rec {rec}/{conv}")
    if debate:
        pieces.append(f"debate {debate}")
    if kills:
        pieces.append(f"kills {kills}")
    if cf:
        pieces.append(f"cf {cf}")
    key = "; ".join(pieces) if pieces else "no recommendation envelope yet"

    sizing = row.sizing_suggestion or {}
    fair_value = (row.execution_context or {}).get("fair_value_estimate")

    detail = {
        "recommendation": rec,
        "conviction": conv,
        "conviction_breakdown": breakdown,
        "sizing_suggestion": sizing,
        "fair_value_estimate": fair_value,
        "trigger_metadata": row.trigger_metadata,
        "recommendation_date": (
            row.recommendation_date.isoformat() if row.recommendation_date else None
        ),
    }
    return HorizonSignal(
        horizon="mid",
        signal=signal,
        key_signal=key,
        detail=detail,
        is_primary=is_primary,
    )


def _derive_long(row: Any, *, is_primary: bool) -> HorizonSignal:
    """Long horizon (12+mo) — compounding metrics + secular + regime."""
    breakdown = row.conviction_breakdown or {}
    drift = breakdown.get("drift_channels", "0 of 3 triggered")
    mode_certainty = breakdown.get("mode_certainty", "rule_clean")
    regime_sens = row.regime_sensitivity or "MEDIUM"
    cf = breakdown.get("counterfactual_top_3", "")

    # Long-horizon signal is dominated by anchor drift + counterfactual.
    survivor_match = "SURVIVOR" in str(cf).upper()
    non_survivor = "NON_SURVIVOR" in str(cf).upper() or "NON-SURVIVOR" in str(cf).upper()
    triggered = _drift_triggered_count(drift)

    if non_survivor and triggered >= 2:
        signal = "SELL"
    elif triggered >= 2:
        signal = "TRIM"
    elif survivor_match and (row.conviction or "").upper() == "HIGH":
        signal = "BUY"
    else:
        signal = "HOLD"

    quality = row.company_quality_flag or "STANDARD"
    key = (
        f"quality {quality}; mode-cert {mode_certainty}; "
        f"drift {drift}; regime-sens {regime_sens}"
    )

    detail = {
        "company_quality_flag": quality,
        "mode_certainty": mode_certainty,
        "drift_channels": drift,
        "regime_sensitivity": regime_sens,
        "counterfactual_top_3": cf,
        "conviction_threshold": row.conviction_threshold,
    }
    return HorizonSignal(
        horizon="long",
        signal=signal,
        key_signal=key,
        detail=detail,
        is_primary=is_primary,
    )


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _drift_triggered_count(value: Any) -> int:
    """Parse 'N of 3 triggered' format into an int.

    Per Section 4.6 Q1 conviction_breakdown.drift_channels schema.
    """
    if value is None:
        return 0
    s = str(value).strip().lower()
    # Match leading int.
    head = s.split()
    if not head:
        return 0
    try:
        return int(head[0])
    except ValueError:
        return 0
