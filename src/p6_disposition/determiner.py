"""P6 disposition determiner — derives mode-anchored horizon + per-horizon signal.

Per v3 spec Section 2.1 funnel composition:

    P5 watchlist add (research artifact)
        ↓
    P6 disposition determination ← THIS MODULE
        ↓
    P7 entry execution → recommendation output

Per Section 4.6 Q2 (Multi-horizon disposition view):

    Single screen lists all watchlist names; three horizon columns
    (Short ≤3mo / Mid 3-12mo / Long 12+mo). Mode-anchored primary
    horizon highlighted/expanded by default:
      - B: Long primary
      - B': Mid primary
      - C: Short primary

Per Section 4.6 (sizing v0.1 + suggested_pacing):
  - Mode B/B' default pacing = "DCA over 21 days"
  - Mode C default pacing = "wait-for-arrival" (Section 2.5 13G framework)

Pure derivation — no LLM calls, no DB writes. Output is a
``DispositionDecision`` dataclass that P7 consumes when composing the
``execution_recommendations`` row.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Mapping, Optional


# Horizon constants
HORIZON_SHORT = "short"  # ≤3mo
HORIZON_MID = "mid"  # 3-12mo
HORIZON_LONG = "long"  # 12+mo

# Per Section 4.6 Q2 mode → primary horizon mapping.
MODE_PRIMARY_HORIZON: dict[str, str] = {
    "B": HORIZON_LONG,
    "B_prime": HORIZON_MID,
    "C": HORIZON_SHORT,
}

# Per-horizon signal vocabulary.
SIGNAL_BUY = "BUY"
SIGNAL_HOLD = "HOLD"
SIGNAL_TRIM = "TRIM"
SIGNAL_SELL = "SELL"
_VALID_SIGNALS: frozenset[str] = frozenset(
    {SIGNAL_BUY, SIGNAL_HOLD, SIGNAL_TRIM, SIGNAL_SELL}
)

# Per Section 4.6 — default pacing strings.
PACING_DCA_21D = "DCA over 21 days"
PACING_WAIT_ARRIVAL = "wait-for-arrival (Section 2.5 13G framework)"


# ---------------------------------------------------------------------------
# Inputs / Outputs
# ---------------------------------------------------------------------------


@dataclass
class DispositionInput:
    """Bundle of inputs the P6 determiner consumes.

    All inputs are pre-computed by upstream phases:
      * ticker: from watchlist row
      * mode + company_quality_flag: from mode_classifier
      * pm_supervisor_decision: from P4 phase D (ADD/WATCH/PASS)
      * currently_held: from broker MCP positions (Section 7 Q5)
      * conviction_bucket: from P7 conviction rollup (None at the
        first new-candidate emission — P7 derives + back-fills)
    """

    ticker: str
    mode: str  # 'B' | 'B_prime' | 'C'
    company_quality_flag: str  # 'HIGH' | 'STANDARD'
    pm_supervisor_decision: str  # 'ADD' | 'WATCH' | 'PASS'
    currently_held: bool = False
    conviction_bucket: Optional[str] = None  # 'HIGH' | 'MEDIUM' | 'LOW'
    # Optional: prior recommendation for revised-emission paths.
    prior_recommendation: Optional[str] = None


@dataclass
class DispositionDecision:
    """Per-name disposition decision; P7 consumes this for emission.

    Schema matches Section 4.6 Q2 multi-horizon disposition view::

        {ticker, mode, primary_horizon, horizon_signals: {short, mid, long},
         suggested_pacing, rationale_strings: [...]}

    Each ``horizon_signals[h]`` is one of BUY/HOLD/TRIM/SELL.

    The ``primary_recommendation`` field projects the primary-horizon
    signal as the top-line BUY/HOLD/TRIM/SELL P7 writes to
    ``execution_recommendations.recommendation``.
    """

    ticker: str
    mode: str
    primary_horizon: str  # short / mid / long
    horizon_signals: Mapping[str, str]  # {short, mid, long} → signal
    primary_recommendation: str  # signal at the primary horizon
    suggested_pacing: str
    rationale_strings: list[str] = field(default_factory=list)
    derived_at: _dt.datetime = field(
        default_factory=lambda: _dt.datetime.now(_dt.timezone.utc)
    )

    def to_payload(self) -> dict:
        """Serialize for P7 + audit_provenance drill_payload."""
        return {
            "ticker": self.ticker,
            "mode": self.mode,
            "primary_horizon": self.primary_horizon,
            "horizon_signals": dict(self.horizon_signals),
            "primary_recommendation": self.primary_recommendation,
            "suggested_pacing": self.suggested_pacing,
            "rationale_strings": list(self.rationale_strings),
            "derived_at": self.derived_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _primary_horizon_for_mode(mode: str) -> str:
    """Section 4.6 Q2 mode → primary horizon mapping.

    Raises ValueError on unknown mode.
    """
    if mode not in MODE_PRIMARY_HORIZON:
        raise ValueError(
            f"mode {mode!r} not in {tuple(MODE_PRIMARY_HORIZON.keys())} — "
            "see Section 2.2 mode definitions"
        )
    return MODE_PRIMARY_HORIZON[mode]


def _default_pacing_for_mode(mode: str) -> str:
    """Section 4.6 default pacing per mode.

    Mode B/B' → DCA over 21 days (ride-along default).
    Mode C → wait-for-arrival (Section 2.5 13G framework — let smart-money
        accumulate before chasing a thematic name).
    """
    if mode == "C":
        return PACING_WAIT_ARRIVAL
    return PACING_DCA_21D


def _signal_for_new_candidate(
    decision: str, currently_held: bool
) -> str:
    """Map P4 verdict → primary-horizon signal for a fresh emission.

    ADD + not held → BUY.
    ADD + already held → HOLD (already at target — only revise on M-2/M-3).
    WATCH → HOLD (not yet trade-eligible per Section 2.2 conviction threshold).
    PASS + held → SELL (P9 exit path).
    PASS + not held → HOLD (no-op).
    """
    if decision == "ADD":
        return SIGNAL_BUY if not currently_held else SIGNAL_HOLD
    if decision == "WATCH":
        return SIGNAL_HOLD
    if decision == "PASS":
        return SIGNAL_SELL if currently_held else SIGNAL_HOLD
    raise ValueError(
        f"pm_supervisor_decision {decision!r} not in {{ADD, WATCH, PASS}}"
    )


def _per_horizon_signals(
    primary_horizon: str, primary_signal: str
) -> dict[str, str]:
    """Project the primary signal across all 3 horizons.

    v0.1 simple rule per Section 4.6: primary horizon carries the strong
    signal; non-primary horizons default to HOLD. Operator can manually
    toggle primary horizon (Section 4.6 Q2). v0.5+ adds composable
    horizon-conditional signals once outcome data accumulates.
    """
    return {
        HORIZON_SHORT: (
            primary_signal if primary_horizon == HORIZON_SHORT else SIGNAL_HOLD
        ),
        HORIZON_MID: (
            primary_signal if primary_horizon == HORIZON_MID else SIGNAL_HOLD
        ),
        HORIZON_LONG: (
            primary_signal if primary_horizon == HORIZON_LONG else SIGNAL_HOLD
        ),
    }


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def determine_disposition(inp: DispositionInput) -> DispositionDecision:
    """Derive per-name disposition. Pure function — no I/O.

    Per v3 spec Section 2.1 (P6) + Section 4.6 Q2 (multi-horizon view).

    Returns a DispositionDecision with:
      * primary_horizon = mode-anchored (B=Long / B'=Mid / C=Short)
      * horizon_signals = {short, mid, long} → BUY/HOLD/TRIM/SELL
      * primary_recommendation = horizon_signals[primary_horizon]
      * suggested_pacing = mode default (DCA 21d for B/B', wait-for-arrival for C)
      * rationale_strings = audit trail fragments
    """
    primary_horizon = _primary_horizon_for_mode(inp.mode)
    primary_signal = _signal_for_new_candidate(
        inp.pm_supervisor_decision, inp.currently_held
    )
    horizon_signals = _per_horizon_signals(primary_horizon, primary_signal)
    pacing = _default_pacing_for_mode(inp.mode)

    rationale: list[str] = [
        f"Mode {inp.mode} → primary horizon {primary_horizon} per Section 4.6 Q2",
        f"PMSupervisor {inp.pm_supervisor_decision} + currently_held="
        f"{inp.currently_held} → primary signal {primary_signal}",
        f"Default pacing for mode {inp.mode}: {pacing}",
    ]
    if inp.conviction_bucket:
        rationale.append(
            f"Conviction bucket: {inp.conviction_bucket} (rolled up by P7)"
        )
    if inp.prior_recommendation and inp.prior_recommendation != primary_signal:
        rationale.append(
            f"Revised: prior {inp.prior_recommendation} → {primary_signal}"
        )

    return DispositionDecision(
        ticker=inp.ticker,
        mode=inp.mode,
        primary_horizon=primary_horizon,
        horizon_signals=horizon_signals,
        primary_recommendation=primary_signal,
        suggested_pacing=pacing,
        rationale_strings=rationale,
    )


__all__ = [
    "DispositionDecision",
    "DispositionInput",
    "HORIZON_LONG",
    "HORIZON_MID",
    "HORIZON_SHORT",
    "MODE_PRIMARY_HORIZON",
    "PACING_DCA_21D",
    "PACING_WAIT_ARRIVAL",
    "SIGNAL_BUY",
    "SIGNAL_HOLD",
    "SIGNAL_SELL",
    "SIGNAL_TRIM",
    "determine_disposition",
]
