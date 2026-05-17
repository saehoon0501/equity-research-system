"""Cut evaluator — Section 4.5 Q3 mode-tuned cut thresholds.

Per v3 spec Section 4.5 Q3 (lines 506-512): each mode (B / B' / C) has
a distinct cut-criteria checklist. The evaluator returns whether ANY
condition for the ticker's mode is met → recommend cut.

Mode B (steady, hold-through bias):
    (i)  ≥2 kill-criteria fired; OR
    (ii) thesis-defining moat erosion verbatim-confirmed; OR
    (iii) drawdown vs S&P 500 > 10pp sustained ≥3 quarters.

Mode B' (growth, moderate):
    (i)  ≥1 thesis-defining kill-criterion fired; OR
    (ii) growth-rate inflection > -50% YoY for 2 consecutive quarters; OR
    (iii) drawdown vs QQQ > 12pp sustained ≥2 quarters.

Mode C (thematic, cut-fast bias):
    (i)  any kill-criterion fired; OR
    (ii) BOCPD regime-change probability > 0.7 against thesis; OR
    (iii) drawdown vs IWO/ARKK > 15pp sustained ≥1 quarter; OR
    (iv) smart-money exit signal verified.

Per operator-locked dual-signal architecture (v3 §4.1 / migration 020):
the Mode-C BOCPD trigger consumes ``bocpd_short_run_mass`` (cumulative
posterior P(r_t < 10 | x_{1:t})), NOT the canonical Adams-MacKay marginal.
The canonical marginal `bocpd_change_probability` is structurally pinned
near hazard rate in steady state and would not cross the 0.7 floor in
practice. Short-run mass is what actually crosses the firing threshold
on regime shifts. The canonical marginal remains in
`regime_classification_history` for audit traceability only.

The evaluator is **deterministic** — no LLM call. Inputs are the
materiality events emitted today + any rolling state (recent kill
fires, drawdown history, BOCPD prob, smart-money exit verified
flag).

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 4.5 Q3 — mode-tuned cut thresholds
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from . import MODE_B, MODE_B_PRIME, MODE_C
from .materiality_classifier import MaterialityVerdict

_LOG = logging.getLogger(__name__)


# Cut threshold parameters per Section 4.5 Q3.
KILL_FLOOR_B: int = 2
KILL_FLOOR_B_PRIME: int = 1
KILL_FLOOR_C: int = 1

DRAWDOWN_PP_B: float = 10.0       # vs S&P 500
DRAWDOWN_PP_B_PRIME: float = 12.0  # vs QQQ
DRAWDOWN_PP_C: float = 15.0       # vs IWO/ARKK

DRAWDOWN_QUARTERS_B: int = 3
DRAWDOWN_QUARTERS_B_PRIME: int = 2
DRAWDOWN_QUARTERS_C: int = 1

# Mode-C BOCPD threshold per Section 4.5 Q3 (iv).
BOCPD_PROB_FLOOR: float = 0.7

# Mode-B' YoY growth-inflection threshold (Section 4.5 Q3 mode B').
GROWTH_INFLECTION_PP: float = -50.0
GROWTH_INFLECTION_QUARTERS: int = 2


# --------------------------------------------------------------------------- #
# Inputs / outputs                                                            #
# --------------------------------------------------------------------------- #


@dataclass
class CutContext:
    """Rolling state needed to evaluate Section 4.5 Q3 thresholds.

    Attributes:
        kills_fired_today: Number of kill criteria tripped by today's
            materiality events. Computed from
            ``MaterialityVerdict.cited_kill_criterion_id``.
        thesis_defining_kill_fired: True if any tripped kill criterion
            is flagged thesis_defining=true in scenarios.kill_criteria_structured.
            Used by Mode B' and the moat-erosion path of Mode B.
        moat_erosion_verbatim_confirmed: True if any M-3 verdict cites a
            verbatim quote tagged as moat erosion. Mode B path (ii).
        drawdown_pp_vs_benchmark: Trailing drawdown vs the mode's
            benchmark (S&P/QQQ/IWO) in percentage points (positive
            number = drawdown).
        drawdown_quarters_sustained: Quarters this drawdown has held.
        growth_yoy_recent_quarters: List of recent YoY growth %
            (most-recent first); used by Mode B' inflection rule.
        bocpd_against_thesis_prob: BOCPD short-run-mass probability
            against thesis (Mode C path ii). Consume short-run mass per
            dual-signal architecture (operator-locked); canonical marginal
            kept for audit. Sourced from
            ``regime_state.bocpd_short_run_mass`` for the dimension(s)
            tagged against this position's thesis.
        smart_money_exit_verified: True if a 13F/13G/13D event
            today verified an exit signal. Mode C path iv.
    """

    kills_fired_today: int = 0
    thesis_defining_kill_fired: bool = False
    moat_erosion_verbatim_confirmed: bool = False
    drawdown_pp_vs_benchmark: float = 0.0
    drawdown_quarters_sustained: int = 0
    growth_yoy_recent_quarters: list[float] = field(default_factory=list)
    bocpd_against_thesis_prob: float = 0.0
    smart_money_exit_verified: bool = False


@dataclass
class CutDecision:
    """Output of the cut evaluator."""

    mode: str
    cut_recommended: bool
    triggered_conditions: list[str]
    rationale: str

    def to_jsonb(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "cut_recommended": self.cut_recommended,
            "triggered_conditions": list(self.triggered_conditions),
            "rationale": self.rationale,
        }


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def build_cut_context_from_verdicts(
    verdicts: list[MaterialityVerdict],
    *,
    kill_criteria_meta: Optional[dict[str, dict[str, Any]]] = None,
    drawdown_pp_vs_benchmark: float = 0.0,
    drawdown_quarters_sustained: int = 0,
    growth_yoy_recent_quarters: Optional[list[float]] = None,
    bocpd_against_thesis_prob: float = 0.0,
    smart_money_exit_verified: bool = False,
) -> CutContext:
    """Roll up today's verdicts + rolling state into a :class:`CutContext`.

    Args:
        verdicts: Materiality verdicts from today's classifier run.
        kill_criteria_meta: Optional dict {kill_id: {thesis_defining: bool,
            tag: str, ...}} from scenarios.kill_criteria_structured. Lets
            us tell whether a fired kill is thesis-defining (Mode B'
            path) or moat-erosion (Mode B path).
        drawdown_pp_vs_benchmark: Pre-computed by sizing/portfolio module.
        drawdown_quarters_sustained: Pre-computed.
        growth_yoy_recent_quarters: From data layer, most-recent first.
        bocpd_against_thesis_prob: From regime sidecar.
        smart_money_exit_verified: From verdicts that cite 13F/13G/13D
            and the operator's "exit signal verified" tag.

    Returns:
        :class:`CutContext` ready for :func:`evaluate_cut`.
    """
    meta = kill_criteria_meta or {}
    kills_fired = 0
    thesis_defining_fired = False
    moat_erosion_confirmed = False
    sm_exit = smart_money_exit_verified

    for v in verdicts:
        if v.cited_kill_criterion_id:
            kills_fired += 1
            km = meta.get(v.cited_kill_criterion_id, {})
            if km.get("thesis_defining"):
                thesis_defining_fired = True
            if km.get("tag") == "moat_erosion" and v.classification >= 2 and v.verbatim_quote:
                moat_erosion_confirmed = True

    return CutContext(
        kills_fired_today=kills_fired,
        thesis_defining_kill_fired=thesis_defining_fired,
        moat_erosion_verbatim_confirmed=moat_erosion_confirmed,
        drawdown_pp_vs_benchmark=drawdown_pp_vs_benchmark,
        drawdown_quarters_sustained=drawdown_quarters_sustained,
        growth_yoy_recent_quarters=list(growth_yoy_recent_quarters or []),
        bocpd_against_thesis_prob=bocpd_against_thesis_prob,
        smart_money_exit_verified=sm_exit,
    )


# --------------------------------------------------------------------------- #
# Public entry                                                                #
# --------------------------------------------------------------------------- #


def evaluate_cut(mode: str, context: CutContext) -> CutDecision:
    """Evaluate Section 4.5 Q3 cut thresholds for the given mode.

    Returns ``CutDecision.cut_recommended=True`` if ANY condition for
    the mode is met. ``triggered_conditions`` lists every condition
    that fired (multiple may fire simultaneously — the operator sees
    the full list).

    Args:
        mode: One of MODE_B, MODE_B_PRIME, MODE_C.
        context: Rolling state.

    Returns:
        :class:`CutDecision`.
    """
    if mode == MODE_B:
        return _evaluate_mode_b(context)
    if mode == MODE_B_PRIME:
        return _evaluate_mode_b_prime(context)
    if mode == MODE_C:
        return _evaluate_mode_c(context)
    raise ValueError(f"unknown mode: {mode!r}")


def _evaluate_mode_b(ctx: CutContext) -> CutDecision:
    triggered: list[str] = []
    if ctx.kills_fired_today >= KILL_FLOOR_B:
        triggered.append(
            f"kills_fired_today={ctx.kills_fired_today} >= {KILL_FLOOR_B}"
        )
    if ctx.moat_erosion_verbatim_confirmed:
        triggered.append("moat_erosion_verbatim_confirmed")
    if (
        ctx.drawdown_pp_vs_benchmark > DRAWDOWN_PP_B
        and ctx.drawdown_quarters_sustained >= DRAWDOWN_QUARTERS_B
    ):
        triggered.append(
            f"drawdown_vs_sp500_{ctx.drawdown_pp_vs_benchmark:.1f}pp"
            f"_for_{ctx.drawdown_quarters_sustained}q"
            f"_>_{DRAWDOWN_PP_B}pp_for_{DRAWDOWN_QUARTERS_B}q"
        )
    cut = bool(triggered)
    return CutDecision(
        mode=MODE_B,
        cut_recommended=cut,
        triggered_conditions=triggered,
        rationale=(
            "Mode B (steady) cut-evaluation: " +
            ("triggered: " + "; ".join(triggered) if cut else "no conditions met")
        ),
    )


def _evaluate_mode_b_prime(ctx: CutContext) -> CutDecision:
    triggered: list[str] = []
    if ctx.thesis_defining_kill_fired:
        triggered.append("thesis_defining_kill_fired")
    # Note: a prior elif branch guarded by `kills_fired_today >= KILL_FLOOR_B_PRIME
    # AND thesis_defining_kill_fired` was unreachable (the AND with the above
    # if-clause means the elif could never fire). Removed in remediation pass.
    growth = ctx.growth_yoy_recent_quarters
    if (
        len(growth) >= GROWTH_INFLECTION_QUARTERS
        and all(g < GROWTH_INFLECTION_PP for g in growth[:GROWTH_INFLECTION_QUARTERS])
    ):
        triggered.append(
            f"growth_yoy<{GROWTH_INFLECTION_PP}_for_"
            f"{GROWTH_INFLECTION_QUARTERS}_consec_quarters"
        )
    if (
        ctx.drawdown_pp_vs_benchmark > DRAWDOWN_PP_B_PRIME
        and ctx.drawdown_quarters_sustained >= DRAWDOWN_QUARTERS_B_PRIME
    ):
        triggered.append(
            f"drawdown_vs_qqq_{ctx.drawdown_pp_vs_benchmark:.1f}pp"
            f"_for_{ctx.drawdown_quarters_sustained}q"
            f"_>_{DRAWDOWN_PP_B_PRIME}pp_for_{DRAWDOWN_QUARTERS_B_PRIME}q"
        )
    cut = bool(triggered)
    return CutDecision(
        mode=MODE_B_PRIME,
        cut_recommended=cut,
        triggered_conditions=triggered,
        rationale=(
            "Mode B' (growth) cut-evaluation: " +
            ("triggered: " + "; ".join(triggered) if cut else "no conditions met")
        ),
    )


def _evaluate_mode_c(ctx: CutContext) -> CutDecision:
    triggered: list[str] = []
    if ctx.kills_fired_today >= KILL_FLOOR_C:
        triggered.append(
            f"any_kill_fired (count={ctx.kills_fired_today})"
        )
    # Consume short-run mass per dual-signal architecture (operator-locked);
    # canonical marginal kept for audit. See module docstring + migration 020.
    if ctx.bocpd_against_thesis_prob > BOCPD_PROB_FLOOR:
        triggered.append(
            f"bocpd_short_run_mass_against_thesis_{ctx.bocpd_against_thesis_prob:.2f}"
            f"_>_{BOCPD_PROB_FLOOR}"
        )
    if (
        ctx.drawdown_pp_vs_benchmark > DRAWDOWN_PP_C
        and ctx.drawdown_quarters_sustained >= DRAWDOWN_QUARTERS_C
    ):
        triggered.append(
            f"drawdown_vs_iwo_arkk_{ctx.drawdown_pp_vs_benchmark:.1f}pp"
            f"_for_{ctx.drawdown_quarters_sustained}q"
            f"_>_{DRAWDOWN_PP_C}pp_for_{DRAWDOWN_QUARTERS_C}q"
        )
    if ctx.smart_money_exit_verified:
        triggered.append("smart_money_exit_verified")
    cut = bool(triggered)
    return CutDecision(
        mode=MODE_C,
        cut_recommended=cut,
        triggered_conditions=triggered,
        rationale=(
            "Mode C (thematic) cut-evaluation: " +
            ("triggered: " + "; ".join(triggered) if cut else "no conditions met")
        ),
    )
