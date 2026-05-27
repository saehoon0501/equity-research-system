"""Credit-stress / balance-sheet computation — pure compute layer (WS-7.3).

Per the plan at
``docs/superpowers/plans/2026-05-27-insight-quality-enhancement-parallel-plan.md``
Phase 3 (OPTIONAL): produce a ``credit_stress`` block (a plain dict) for the
quantitative-analyst envelope.

Three sub-metrics + an overall qualitative flag:

  1. interest_coverage   — EBIT / interest expense, plus a STRESSED variant
                           that re-prices interest to the current curve point
                           at the near-term maturity tenor (ties the stress to
                           the same FRED input the maturity-wall leg uses).
  2. maturity_wall       — near-term maturities vs the current rate curve;
                           refinancing risk RISES when a large share of total
                           debt comes due soon AND must roll at a materially
                           higher rate than its existing coupon.
  3. cash_runway         — cash / quarterly burn (quarters of runway), for
                           cash-burning names; not_applicable when generative.

A sub-metric leg is "usable" when its status is "ok" AND its driving value is
finite. A leg with status "ok" but a NON-FINITE value (NaN/inf — e.g. NaN EBIT
or interest_expense yielding a NaN stressed coverage) is treated as effectively
UNAVAILABLE for classification: it neither hard-trips "high" nor counts as a
healthy signal (garbage data must NOT let a name escape a "high" trip on the
other legs). ``not_applicable`` (no debt / cash-generative) is a HEALTHY
structural signal, distinct from ``unavailable`` (no data).

OVERALL FLAG truth table (documented thresholds, see constants below):
  - "high"        if ANY hard trip fires among USABLE legs:
                      stressed coverage < COVERAGE_HIGH_STRESS_X (1.5x), OR
                      maturity_wall risk == "high", OR
                      runway < RUNWAY_HIGH_QUARTERS (2 quarters)
  - "low"         if NO trip fires AND every USABLE leg is healthy
                      (coverage >= COVERAGE_LOW_X, maturity risk == low,
                      runway >= RUNWAY_LOW_QUARTERS) AND at least one leg
                      yielded a real signal (usable "ok" OR not_applicable —
                      a not_applicable leg counts as a healthy structural fact)
  - "elevated"    otherwise (something is marginal but nothing hard-trips)
  - "unavailable" ONLY when EVERY leg is genuinely unavailable: no usable "ok"
                      leg, and no not_applicable DERIVED FROM REAL INPUT
                      (coverage NA <= interest<=0, runway NA <= burn<=0). A
                      maturity not_applicable means an EMPTY debt_maturities
                      tuple, which is also the dataclass default — so it is
                      ambiguous with "no data" and cannot, by itself, lift a
                      name out of "unavailable". A debt-free, cash-generative
                      firm (runway not_applicable from burn<=0) is "low", never
                      "unavailable"; a truly empty Financials() is "unavailable".

Architectural decoupling: PURE compute on already-fetched financials + curve.
The agent layer (.claude/agents/quantitative-analyst.md) owns the live
EDGAR + FRED I/O and injects ``Financials`` + ``RateCurve``. NO network here.

Each sub-metric is a dict ``{value, status, inputs_used, reasoning, ...}``
where ``status`` is one of ``ok`` / ``unavailable`` / ``not_applicable``.
Missing/None inputs => ``status="unavailable"``, ``value=None`` (never raises).
"""

from __future__ import annotations

import math
from typing import Any, Optional

from src.credit_stress.contracts import (
    DebtMaturity,
    Financials,
    RateCurve,
)

# ---------------------------------------------------------------------------
# Documented thresholds (module-level constants — single source of truth)
# ---------------------------------------------------------------------------

# Interest coverage (EBIT / interest). Below the HIGH bound is a hard trip;
# at/above the LOW bound is "healthy". Between = marginal.
COVERAGE_HIGH_STRESS_X = 1.5  # stressed coverage < this => hard "high" trip
COVERAGE_LOW_X = 3.0  # base coverage >= this => healthy leg

# Maturity wall.
NEAR_TERM_YEARS = 2.0  # tranches maturing within this horizon are "near-term"
WALL_SHARE_HIGH = 0.30  # near-term share of total debt at/above => wall present
WALL_SHARE_ELEVATED = 0.15  # smaller-but-notable near-term concentration
RATE_GAP_BPS_HIGH = 150.0  # curve - weighted near-term coupon >= => costly refi
RATE_GAP_BPS_ELEVATED = 50.0

# Cash runway (quarters = cash / quarterly burn).
RUNWAY_HIGH_QUARTERS = 2.0  # runway < this => hard "high" trip
RUNWAY_LOW_QUARTERS = 8.0  # runway >= this => healthy leg (>= ~2 years)

# Stressed-coverage construction: re-price interest expense to the current
# curve at the near-term tenor. Floor the multiplier at 1.0 so the "stress"
# never makes coverage LOOK better than the base case (a falling curve does
# not relieve refinancing risk for the purposes of this conservative block).
STRESS_INTEREST_MULTIPLIER_FLOOR = 1.0


# ---------------------------------------------------------------------------
# Sub-metric helpers (each returns a self-describing dict; never raises)
# ---------------------------------------------------------------------------


def _unavailable(reason: str, inputs_used: dict[str, Any]) -> dict[str, Any]:
    return {
        "value": None,
        "status": "unavailable",
        "inputs_used": inputs_used,
        "reasoning": reason,
    }


def compute_interest_coverage(
    fin: Financials, curve: RateCurve
) -> dict[str, Any]:
    """EBIT / interest expense, plus a stressed variant.

    Stressed variant re-prices interest to the current curve at the nearest
    near-term maturity tenor: if the curve rate exceeds the existing weighted
    near-term coupon, interest is scaled up by (curve_rate / coupon), floored
    at 1.0. When no near-term coupon or curve is available, the stressed
    variant degrades to the base coverage (multiplier 1.0).
    """
    ebit = fin.ebit
    interest = fin.interest_expense
    inputs = {"ebit": ebit, "interest_expense": interest}

    if ebit is None or interest is None:
        return _unavailable(
            "EBIT or interest_expense missing; cannot compute coverage.", inputs
        )
    if interest <= 0:
        # No interest burden => coverage is effectively infinite / N/A as a
        # STRESS signal. Treat as not_applicable (does not trip "high").
        return {
            "value": None,
            "base_coverage_x": None,
            "stressed_coverage_x": None,
            "status": "not_applicable",
            "inputs_used": inputs,
            "reasoning": (
                "interest_expense <= 0: no interest burden, coverage is not a "
                "meaningful stress signal (not_applicable)."
            ),
        }

    base_cov = ebit / interest

    # Stressed: re-price interest to current curve at near-term tenor.
    stress_mult, stress_note = _stress_interest_multiplier(fin, curve)
    stressed_interest = interest * stress_mult
    stressed_cov = ebit / stressed_interest

    return {
        "value": base_cov,  # convenience: "value" == base coverage
        "base_coverage_x": base_cov,
        "stressed_coverage_x": stressed_cov,
        "stress_interest_multiplier": stress_mult,
        "status": "ok",
        "inputs_used": {**inputs, "stress_note": stress_note},
        "reasoning": (
            f"base coverage = EBIT/interest = {base_cov:.2f}x; stressed "
            f"coverage = {stressed_cov:.2f}x after applying interest "
            f"multiplier {stress_mult:.2f} ({stress_note})."
        ),
    }


def _stress_interest_multiplier(
    fin: Financials, curve: RateCurve
) -> tuple[float, str]:
    """Multiplier to scale interest expense to the current curve.

    Uses the amount-weighted coupon of NEAR-TERM maturities and the curve rate
    at the (amount-weighted) near-term tenor. Returns (multiplier, note).
    Floored at STRESS_INTEREST_MULTIPLIER_FLOOR (1.0).
    """
    near = [
        m
        for m in fin.debt_maturities
        if m.years_to_maturity <= NEAR_TERM_YEARS and m.amount > 0
    ]
    coupons = [(m.amount, m.coupon_rate_pct) for m in near if m.coupon_rate_pct is not None]
    if not coupons:
        return STRESS_INTEREST_MULTIPLIER_FLOOR, "no near-term coupon data; no step-up"

    total_amt = sum(a for a, _ in coupons)
    w_coupon = sum(a * c for a, c in coupons) / total_amt

    # Weighted near-term tenor for the curve lookup.
    w_tenor = sum(m.amount * m.years_to_maturity for m in near) / sum(
        m.amount for m in near
    )
    curve_rate = curve.rate_at(w_tenor)
    if curve_rate is None or w_coupon <= 0:
        return STRESS_INTEREST_MULTIPLIER_FLOOR, "no curve point; no step-up"

    mult = max(curve_rate / w_coupon, STRESS_INTEREST_MULTIPLIER_FLOOR)
    return mult, (
        f"near-term wtd coupon {w_coupon:.2f}% vs curve {curve_rate:.2f}% "
        f"at {w_tenor:.1f}y tenor"
    )


def compute_maturity_wall(fin: Financials, curve: RateCurve) -> dict[str, Any]:
    """Near-term maturities vs the current curve => refinancing risk level.

    Risk rises with BOTH (a) the share of total debt maturing near-term and
    (b) the rate gap (current curve - existing weighted near-term coupon).

      high     : near-term share >= WALL_SHARE_HIGH AND gap >= RATE_GAP_BPS_HIGH
      elevated : a notable near-term concentration OR a notable gap
      low      : small near-term load and/or refi at comparable rates
      not_applicable : no scheduled debt at all
      unavailable    : debt exists but the curve is empty (can't price refi)
    """
    maturities: tuple[DebtMaturity, ...] = fin.debt_maturities
    inputs: dict[str, Any] = {
        "num_tranches": len(maturities),
        "near_term_years": NEAR_TERM_YEARS,
    }

    total_debt = sum(m.amount for m in maturities if m.amount > 0)
    if total_debt <= 0:
        return {
            "value": None,
            "risk": "not_applicable",
            "status": "not_applicable",
            "inputs_used": inputs,
            "reasoning": "no scheduled debt maturities; maturity wall N/A.",
        }

    near = [
        m
        for m in maturities
        if m.years_to_maturity <= NEAR_TERM_YEARS and m.amount > 0
    ]
    near_amt = sum(m.amount for m in near)
    near_share = near_amt / total_debt
    inputs["near_term_share"] = near_share
    inputs["total_debt"] = total_debt
    inputs["near_term_amount"] = near_amt

    if near_amt <= 0:
        # All debt is long-dated => no near-term wall regardless of curve.
        return {
            "value": near_share,
            "risk": "low",
            "rate_gap_bps": 0.0,
            "near_term_share": near_share,
            "status": "ok",
            "inputs_used": inputs,
            "reasoning": (
                f"no maturities within {NEAR_TERM_YEARS:.0f}y "
                f"(near-term share {near_share:.0%}); no refinancing wall."
            ),
        }

    # Rate gap requires the curve.
    coupons = [(m.amount, m.coupon_rate_pct) for m in near if m.coupon_rate_pct is not None]
    if not coupons or not curve.points:
        # Debt comes due near-term but we cannot price the refi gap.
        # Concentration alone still informs an elevated/low signal.
        risk = "elevated" if near_share >= WALL_SHARE_ELEVATED else "low"
        return {
            "value": near_share,
            "risk": risk,
            "rate_gap_bps": None,
            "near_term_share": near_share,
            "status": "ok",
            "inputs_used": inputs,
            "reasoning": (
                f"near-term share {near_share:.0%} within {NEAR_TERM_YEARS:.0f}y "
                "but coupon/curve data unavailable to price the refi gap; "
                f"risk={risk} on concentration alone."
            ),
        }

    total_amt = sum(a for a, _ in coupons)
    w_coupon = sum(a * c for a, c in coupons) / total_amt
    w_tenor = near_amt and sum(m.amount * m.years_to_maturity for m in near) / near_amt
    curve_rate = curve.rate_at(w_tenor)
    rate_gap_bps = (curve_rate - w_coupon) * 100.0  # pct points -> bps
    inputs["weighted_coupon_pct"] = w_coupon
    inputs["curve_rate_pct"] = curve_rate
    inputs["weighted_tenor_years"] = w_tenor

    if near_share >= WALL_SHARE_HIGH and rate_gap_bps >= RATE_GAP_BPS_HIGH:
        risk = "high"
    elif near_share >= WALL_SHARE_ELEVATED or rate_gap_bps >= RATE_GAP_BPS_ELEVATED:
        risk = "elevated"
    else:
        risk = "low"

    return {
        "value": near_share,
        "risk": risk,
        "rate_gap_bps": rate_gap_bps,
        "near_term_share": near_share,
        "weighted_coupon_pct": w_coupon,
        "curve_rate_pct": curve_rate,
        "status": "ok",
        "inputs_used": inputs,
        "reasoning": (
            f"{near_share:.0%} of debt matures within {NEAR_TERM_YEARS:.0f}y; "
            f"refi gap = curve {curve_rate:.2f}% - coupon {w_coupon:.2f}% = "
            f"{rate_gap_bps:.0f}bps => risk={risk}."
        ),
    }


def compute_cash_runway(fin: Financials) -> dict[str, Any]:
    """Cash / quarterly burn => quarters of runway (for cash-burning names).

    burn <= 0 (cash-generative) => not_applicable (does not trip "high").
    cash or burn missing        => unavailable.
    """
    cash = fin.cash
    burn = fin.quarterly_burn
    inputs = {"cash": cash, "quarterly_burn": burn}

    if cash is None or burn is None:
        return _unavailable(
            "cash or quarterly_burn missing; cannot compute runway.", inputs
        )
    if burn <= 0:
        return {
            "value": None,
            "status": "not_applicable",
            "inputs_used": inputs,
            "reasoning": (
                f"quarterly_burn={burn} <= 0: company is cash-generative; "
                "runway is not_applicable as a stress signal."
            ),
        }

    quarters = cash / burn
    return {
        "value": quarters,
        "runway_quarters": quarters,
        "status": "ok",
        "inputs_used": inputs,
        "reasoning": (
            f"runway = cash/burn = {cash}/{burn} = {quarters:.1f} quarters."
        ),
    }


# ---------------------------------------------------------------------------
# Overall flag + block assembly
# ---------------------------------------------------------------------------


def _finite(x: Any) -> bool:
    """True only for a real, finite numeric value (rejects None / NaN / inf)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _classify_overall(
    coverage: dict[str, Any],
    maturity: dict[str, Any],
    runway: dict[str, Any],
) -> tuple[str, list[str]]:
    """Apply the documented truth table. Returns (flag, reasons).

    Two correctness guards beyond the naive status check:

    1. Non-finite sub-metric VALUES (NaN/inf, e.g. NaN EBIT or interest_expense
       producing a NaN stressed coverage) are treated as that leg being
       *effectively unavailable* — they neither hard-trip "high" NOR count as a
       healthy structural signal. A garbage-data coverage leg must not let a
       name silently escape a "high" trip on the OTHER legs (fail closed, not
       open).
    2. ``not_applicable`` (no debt, cash-generative — a HEALTHY structural
       signal) is distinguished from ``unavailable`` (no data). Overall is
       "unavailable" ONLY when every leg is genuinely unavailable; a debt-free
       cash-generative firm whose legs are all ``not_applicable`` classifies
       "low" (or "elevated" if something is marginal), never "unavailable".
    """
    # --- Per-leg effective availability ------------------------------------
    # A value-bearing leg ("ok") whose driving value is non-finite is downgraded
    # to "effectively unavailable" for classification: garbage data is NOT a
    # signal, and must not clear the high-stress trip by default.
    cov_value = coverage.get("stressed_coverage_x")
    cov_ok = coverage["status"] == "ok" and _finite(cov_value)
    # maturity is qualitative ("risk"), so "ok" is usable as-is.
    mat_ok = maturity["status"] == "ok"
    rq_value = runway.get("runway_quarters")
    rw_ok = runway["status"] == "ok" and _finite(rq_value)

    # A leg yields a discriminating "real signal" if it is usably ok OR a
    # not_applicable DERIVED FROM ACTUAL INPUT data.
    #   - coverage not_applicable  <= interest_expense <= 0 (real datum)
    #   - runway   not_applicable  <= quarterly_burn   <= 0 (real datum)
    #   - maturity not_applicable  <= empty debt_maturities, which is ALSO the
    #     dataclass default: indistinguishable from "no data". So maturity
    #     not_applicable contributes a healthy reason but CANNOT, on its own,
    #     rescue a name from the "all genuinely unavailable" verdict.
    cov_signal = cov_ok or coverage["status"] == "not_applicable"
    rw_signal = rw_ok or runway["status"] == "not_applicable"
    mat_usable = mat_ok  # ok maturity is a real signal; not_applicable is not

    # "unavailable" overall ONLY when no leg produced ANY discriminating real
    # signal (every leg is genuinely unavailable — including "ok" legs degraded
    # by NaN/non-finite data, and an ambiguous maturity not_applicable).
    if not (cov_signal or rw_signal or mat_usable):
        return "unavailable", ["no sub-metric produced a usable signal"]

    trips: list[str] = []

    # --- hard "high" trips (only among usable, finite legs) ----------------
    if cov_ok and cov_value < COVERAGE_HIGH_STRESS_X:
        trips.append(
            f"stressed coverage {cov_value:.2f}x < {COVERAGE_HIGH_STRESS_X}x"
        )
    if mat_ok and maturity.get("risk") == "high":
        trips.append("maturity-wall risk = high")
    if rw_ok and rq_value < RUNWAY_HIGH_QUARTERS:
        trips.append(f"runway {rq_value:.1f}q < {RUNWAY_HIGH_QUARTERS}q")

    if trips:
        return "high", trips

    # --- "low": every usable leg healthy AND >=1 real signal ---------------
    healthy_reasons: list[str] = []
    all_healthy = True

    if cov_ok:
        bcov = coverage.get("base_coverage_x")
        if _finite(bcov) and bcov >= COVERAGE_LOW_X:
            healthy_reasons.append(f"coverage {bcov:.2f}x >= {COVERAGE_LOW_X}x")
        else:
            all_healthy = False
    elif coverage["status"] == "not_applicable":
        healthy_reasons.append("coverage not_applicable (no interest burden)")
    # genuinely-unavailable / NaN coverage => neutral (doesn't block "low")

    if mat_ok:
        if maturity.get("risk") == "low":
            healthy_reasons.append("maturity-wall risk low")
        else:
            all_healthy = False
    elif maturity["status"] == "not_applicable":
        healthy_reasons.append("maturity-wall not_applicable (no scheduled debt)")

    if rw_ok:
        if _finite(rq_value) and rq_value >= RUNWAY_LOW_QUARTERS:
            healthy_reasons.append(f"runway {rq_value:.1f}q >= {RUNWAY_LOW_QUARTERS}q")
        else:
            all_healthy = False
    elif runway["status"] == "not_applicable":
        healthy_reasons.append("runway not_applicable (cash-generative)")

    if all_healthy and healthy_reasons:
        return "low", healthy_reasons

    # --- otherwise: marginal -> elevated -----------------------------------
    return "elevated", ["one or more sub-metrics marginal but none hard-trips"]


def compute_credit_stress(
    financials: Optional[Financials] = None,
    rate_curve: Optional[RateCurve] = None,
    *,
    ticker: Optional[str] = None,
    financials_fetcher: Optional[Any] = None,
    curve_fetcher: Optional[Any] = None,
) -> dict[str, Any]:
    """Produce the ``credit_stress`` block (a dict) for the quant envelope.

    Injectable seams (fully offline-testable):
      - ``financials`` / ``rate_curve`` : injected dataclasses (preferred for
        tests). Take precedence over fetchers.
      - ``financials_fetcher`` / ``curve_fetcher`` : OPTIONAL callables for the
        LIVE path (EDGAR / FRED). DEFAULT None — this module makes NO live call
        itself. When provided and the corresponding direct input is None, the
        fetcher is invoked: ``financials_fetcher(ticker) -> Financials`` and
        ``curve_fetcher() -> RateCurve``. The live wiring of these fetchers is
        the integration boundary owned by the quantitative-analyst agent.

    Never raises on missing data: each sub-metric degrades to
    ``status="unavailable"`` and the overall flag falls back accordingly.
    """
    if financials is None and financials_fetcher is not None:
        financials = financials_fetcher(ticker)
    if rate_curve is None and curve_fetcher is not None:
        rate_curve = curve_fetcher()

    fin = financials if financials is not None else Financials()
    curve = rate_curve if rate_curve is not None else RateCurve()

    coverage = compute_interest_coverage(fin, curve)
    maturity = compute_maturity_wall(fin, curve)
    runway = compute_cash_runway(fin)

    flag, flag_reasons = _classify_overall(coverage, maturity, runway)

    return {
        "ticker": ticker,
        "overall_flag": flag,
        "flag_reasons": flag_reasons,
        "interest_coverage": coverage,
        "maturity_wall": maturity,
        "cash_runway": runway,
        "thresholds": {
            "coverage_high_stress_x": COVERAGE_HIGH_STRESS_X,
            "coverage_low_x": COVERAGE_LOW_X,
            "near_term_years": NEAR_TERM_YEARS,
            "wall_share_high": WALL_SHARE_HIGH,
            "wall_share_elevated": WALL_SHARE_ELEVATED,
            "rate_gap_bps_high": RATE_GAP_BPS_HIGH,
            "rate_gap_bps_elevated": RATE_GAP_BPS_ELEVATED,
            "runway_high_quarters": RUNWAY_HIGH_QUARTERS,
            "runway_low_quarters": RUNWAY_LOW_QUARTERS,
        },
        "methodology": (
            "credit_stress (WS-7.3): interest coverage = EBIT/interest (+ "
            "curve-repriced stressed variant); maturity wall = near-term "
            "(<=2y) debt share vs current-curve refi gap; cash runway = "
            "cash/quarterly_burn. Overall flag: 'high' on any hard trip among "
            "usable legs (stressed coverage <1.5x | maturity risk high | "
            "runway <2q; a NaN/non-finite leg is treated as unavailable, never "
            "as a passed threshold), 'low' when all usable legs healthy and "
            "at least one leg yields a real signal (ok or not_applicable), "
            "else 'elevated'; 'unavailable' only when every leg is genuinely "
            "unavailable (no data on any)."
        ),
    }


__all__ = [
    "compute_credit_stress",
    "compute_interest_coverage",
    "compute_maturity_wall",
    "compute_cash_runway",
    # thresholds re-exported for test pinning
    "COVERAGE_HIGH_STRESS_X",
    "COVERAGE_LOW_X",
    "NEAR_TERM_YEARS",
    "WALL_SHARE_HIGH",
    "WALL_SHARE_ELEVATED",
    "RATE_GAP_BPS_HIGH",
    "RATE_GAP_BPS_ELEVATED",
    "RUNWAY_HIGH_QUARTERS",
    "RUNWAY_LOW_QUARTERS",
]
