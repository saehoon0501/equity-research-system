"""P7 execution_context — populates Section 4.6 Q1 execution_context envelope.

Per v3 spec lines 590-596::

    execution_context:
      current_price: 158.32
      fair_value_estimate: { point: 175, range_low: 155, range_high: 195 }
      near_term_catalysts: [{ event, date, importance }]
      suggested_pacing: "DCA over 21 days (Mode B' ride-along default)"
      technical_signals: { ma_50d, ma_200d, rsi_14, atr_20 }
      risk_flags: [...]

Sources:
  * current_price       — mcp__market_data__get_real_time_quote
  * fair_value_estimate — P3/P4 thesis valuation outputs in audit chain
  * near_term_catalysts — mcp__market_data__get_news + earnings calendar
  * suggested_pacing    — P6 disposition output (mode-anchored default)
  * technical_signals   — market_data {ma_50d, ma_200d, rsi_14, atr_20}
  * risk_flags          — aggregated S0 + S2 counterfactual + S4 smart-money

This module is INPUT-ASSEMBLY ONLY. It does not call MCPs directly —
callers (the emitter) inject pre-fetched payloads. This keeps the unit
under test deterministic; integration tests exercise the MCP wiring in
``emitter.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence


@dataclass
class FairValueEstimate:
    """Section 4.6 Q1 fair_value_estimate sub-schema."""

    point: Optional[float]
    range_low: Optional[float]
    range_high: Optional[float]

    def to_payload(self) -> dict:
        return {
            "point": self.point,
            "range_low": self.range_low,
            "range_high": self.range_high,
        }


@dataclass
class NearTermCatalyst:
    """One entry in execution_context.near_term_catalysts."""

    event: str
    date: Optional[str]  # ISO8601
    importance: str  # 'high' / 'medium' / 'low'

    def to_payload(self) -> dict:
        return {
            "event": self.event,
            "date": self.date,
            "importance": self.importance,
        }


@dataclass
class TechnicalSignals:
    """Section 4.6 Q1 technical_signals sub-schema."""

    ma_50d: Optional[float]
    ma_200d: Optional[float]
    rsi_14: Optional[float]
    atr_20: Optional[float]

    def to_payload(self) -> dict:
        return {
            "ma_50d": self.ma_50d,
            "ma_200d": self.ma_200d,
            "rsi_14": self.rsi_14,
            "atr_20": self.atr_20,
        }


@dataclass
class ExecutionContext:
    """Full execution_context payload per Section 4.6 Q1."""

    current_price: Optional[float]
    fair_value_estimate: FairValueEstimate
    near_term_catalysts: list[NearTermCatalyst]
    suggested_pacing: str
    technical_signals: TechnicalSignals
    risk_flags: list[str] = field(default_factory=list)

    def to_payload(self) -> dict:
        return {
            "current_price": self.current_price,
            "fair_value_estimate": self.fair_value_estimate.to_payload(),
            "near_term_catalysts": [c.to_payload() for c in self.near_term_catalysts],
            "suggested_pacing": self.suggested_pacing,
            "technical_signals": self.technical_signals.to_payload(),
            "risk_flags": list(self.risk_flags),
        }


# ---------------------------------------------------------------------------
# Risk-flag aggregation
# ---------------------------------------------------------------------------


def aggregate_risk_flags(
    *,
    s0_regime_state: Optional[Mapping[str, Any]] = None,
    s4_smart_money: Optional[Mapping[str, Any]] = None,
    extra: Optional[Sequence[str]] = None,
) -> list[str]:
    """Aggregate risk_flags from S0 + S4 sidecars + caller-provided extras.

    Per v3 spec sidecars (Section 2.6 + 4.7):
      S0 — regime classification + BOCPD short_run_mass
      S4 — smart-money signals (catastrophic / fraud-signature → flag)

    Returns a deduplicated list of human-readable risk-flag strings.
    """
    flags: list[str] = []

    # S0 — regime / vol elevated
    if s0_regime_state:
        for d in s0_regime_state.get("dimensions", []) or []:
            try:
                short_run = float(d.get("bocpd_short_run_mass", 0.0))
            except (TypeError, ValueError):
                short_run = 0.0
            if short_run > 0.7:
                flags.append(
                    f"S0 dimension {d.get('dimension_name', '?')} "
                    f"BOCPD short_run_mass={short_run:.2f} > 0.7 (regime shift)"
                )
        if s0_regime_state.get("vol_elevated"):
            flags.append("S0 vol dimension elevated (>+1σ)")

    # S4 — smart-money flags (catastrophic / fraud / drawdown-divergence)
    if s4_smart_money:
        category = s4_smart_money.get("category")
        if category == "catastrophic":
            flags.append("S4 catastrophic smart-money signal")
        if s4_smart_money.get("fraud_signature"):
            flags.append("S4 fraud-signature pattern matched")
        if s4_smart_money.get("insider_selling_cluster"):
            flags.append("S4 insider-selling cluster")

    if extra:
        flags.extend(str(s) for s in extra)

    # Dedup, preserve order.
    seen: set[str] = set()
    out: list[str] = []
    for f in flags:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_execution_context(
    *,
    current_price: Optional[float],
    fair_value_payload: Optional[Mapping[str, Any]],
    near_term_catalysts_raw: Optional[Sequence[Mapping[str, Any]]],
    suggested_pacing: str,
    technical_signals_raw: Optional[Mapping[str, Any]],
    risk_flags: Sequence[str],
) -> ExecutionContext:
    """Compose a typed ExecutionContext from raw upstream payloads.

    All upstream inputs are accepted as plain mappings — callers may have
    populated them from MCP responses, P3/P4 audit chain dicts, etc.
    """
    fv = fair_value_payload or {}
    fve = FairValueEstimate(
        point=_to_float(fv.get("point")),
        range_low=_to_float(fv.get("range_low")),
        range_high=_to_float(fv.get("range_high")),
    )

    catalysts: list[NearTermCatalyst] = []
    for c in near_term_catalysts_raw or []:
        catalysts.append(
            NearTermCatalyst(
                event=str(c.get("event", "")),
                date=str(c.get("date")) if c.get("date") is not None else None,
                importance=str(c.get("importance", "medium")),
            )
        )

    ts = technical_signals_raw or {}
    tech = TechnicalSignals(
        ma_50d=_to_float(ts.get("ma_50d")),
        ma_200d=_to_float(ts.get("ma_200d")),
        rsi_14=_to_float(ts.get("rsi_14")),
        atr_20=_to_float(ts.get("atr_20")),
    )

    return ExecutionContext(
        current_price=_to_float(current_price),
        fair_value_estimate=fve,
        near_term_catalysts=catalysts,
        suggested_pacing=suggested_pacing,
        technical_signals=tech,
        risk_flags=list(risk_flags),
    )


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ExecutionContext",
    "FairValueEstimate",
    "NearTermCatalyst",
    "TechnicalSignals",
    "aggregate_risk_flags",
    "build_execution_context",
]
