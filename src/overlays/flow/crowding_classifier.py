"""Crowding classifier — pure compute layer for the v0.3 flow-overlay sub-signal.

Per the v0.3 plan, this module classifies a ticker as crowded (True) or not
(False) based on two thresholds combined by a configurable logic operator:

  1. days_to_cover threshold breach
  2. short_pct_float threshold breach (computed = short_interest / shares_outstanding)

Asymmetric design: True ONLY when extreme (per logic_operator); fail-safe to
False on any missing/stale input. Downstream pm-supervisor §7.6 contributes -1
to tech_axis_score when True; 0 otherwise (never +1).

Empirical grounding (literature establishes informativeness; no published threshold):
  - Diether, Lee, Werner (2009) "Short-Sale Strategies and Return Predictability"
  - Boehmer, Jones, Zhang (2008) "Which Shorts Are Informed?"
  - Engelberg, Reed, Ringgenberg (2018) "Short-Selling Risk"
  - Cohen, Diether, Malloy (2007) "Supply and Demand Shifts in the Shorting Market"

Architectural decoupling: pure compute on already-fetched data.
Agent layer (.claude/agents/overlays/flow-overlay.md) handles MCP I/O.

Open items for /review-me (placeholders in migration 041 with honest disclosure):
- days_to_cover_threshold (Wikipedia folk-wisdom; no academic anchor)
- short_pct_float_threshold (practitioner rule-of-thumb)
- logic_operator (AND vs OR; conservative AND default)
- stale_data_max_days (~1.5 FINRA bi-weekly cycles)
"""
from __future__ import annotations

from datetime import date


VALID_LOGIC_OPERATORS = ("AND", "OR")

FRAMEWORK_KEYS = (
    "diether_lee_werner_2009",
    "boehmer_jones_zhang_2008",
    "engelberg_reed_ringgenberg_2018",
    "cohen_diether_malloy_2007",
)


def compute_short_pct_float(short_interest: int, shares_outstanding: int) -> float | None:
    """Return short interest as fraction of float, or None when inputs invalid.

    Returns None (not 0) on division-by-zero / negative inputs — caller should
    treat None as 'unavailable', fail-safe to warning=False.
    """
    if shares_outstanding is None or shares_outstanding <= 0:
        return None
    if short_interest is None or short_interest < 0:
        return None
    return short_interest / shares_outstanding


def is_stale(settlement_date: date, as_of: date, max_age_days: int) -> bool:
    """Return True if settlement_date is older than max_age_days from as_of."""
    if settlement_date is None or as_of is None or max_age_days is None:
        return True
    if max_age_days < 0:
        return True
    age = (as_of - settlement_date).days
    return age > max_age_days


def _parse_settlement_date(raw: str | date | None) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def classify_crowding(
    short_interest_data: dict | None,
    shares_outstanding: int | None,
    as_of: date,
    days_to_cover_threshold: float,
    short_pct_float_threshold: float,
    logic_operator: str = "AND",
    stale_data_max_days: int = 21,
) -> dict:
    """Classify whether the ticker is in a crowded-short regime.

    Args:
        short_interest_data: Polygon get_short_interest response dict. May be
            None or a failure payload ({"ticker_not_found": True, ...}); both
            collapse to warning=False with unavailable_reason set.
        shares_outstanding: from fundamentals MCP (CommonStockSharesOutstanding).
            None or 0 collapses to warning=False / shares_outstanding_unavailable.
        as_of: date the classification is anchored to (typically the
            prior-trading-day close anchor used by the flow-overlay agent).
        days_to_cover_threshold: launch_default 5.0 (Wikipedia folk-wisdom).
        short_pct_float_threshold: launch_default 0.20 (fractional, 20%).
        logic_operator: "AND" (both breached) | "OR" (either). Default AND.
        stale_data_max_days: launch_default 21 (~1.5 FINRA cycles).

    Returns:
        {
            "warning": bool,
            "days_to_cover": float | None,
            "short_pct_float": float | None,
            "settlement_date": str | None,
            "logic_operator": "AND" | "OR",
            "thresholds_applied": {"days_to_cover": float, "short_pct_float": float},
            "stale": bool,
            "unavailable_reason": str | None,
            "framework_keys": tuple[str, ...],
        }
    """
    if logic_operator not in VALID_LOGIC_OPERATORS:
        raise ValueError(
            f"logic_operator must be one of {VALID_LOGIC_OPERATORS}; got {logic_operator!r}"
        )

    result_base: dict = {
        "warning": False,
        "days_to_cover": None,
        "short_pct_float": None,
        "settlement_date": None,
        "logic_operator": logic_operator,
        "thresholds_applied": {
            "days_to_cover": days_to_cover_threshold,
            "short_pct_float": short_pct_float_threshold,
        },
        "stale": False,
        "unavailable_reason": None,
        "framework_keys": FRAMEWORK_KEYS,
    }

    # Fail-safe paths: any missing/failure input -> warning=False with explicit reason.
    if short_interest_data is None or short_interest_data.get("ticker_not_found"):
        result_base["unavailable_reason"] = "short_interest_unavailable"
        return result_base

    if shares_outstanding is None or shares_outstanding <= 0:
        result_base["unavailable_reason"] = "shares_outstanding_unavailable"
        return result_base

    settlement_str = short_interest_data.get("settlement_date")
    settlement = _parse_settlement_date(settlement_str)
    if settlement is None:
        result_base["unavailable_reason"] = "short_interest_unavailable"
        return result_base
    result_base["settlement_date"] = str(settlement_str)

    if is_stale(settlement, as_of, stale_data_max_days):
        result_base["stale"] = True
        result_base["unavailable_reason"] = "short_interest_stale"
        return result_base

    days_to_cover = short_interest_data.get("days_to_cover")
    short_interest = short_interest_data.get("short_interest")
    if days_to_cover is None or short_interest is None:
        result_base["unavailable_reason"] = "short_interest_unavailable"
        return result_base

    short_pct_float = compute_short_pct_float(int(short_interest), int(shares_outstanding))
    if short_pct_float is None:
        result_base["unavailable_reason"] = "shares_outstanding_unavailable"
        return result_base

    result_base["days_to_cover"] = float(days_to_cover)
    result_base["short_pct_float"] = float(short_pct_float)

    dtc_breach = result_base["days_to_cover"] >= days_to_cover_threshold
    spf_breach = result_base["short_pct_float"] >= short_pct_float_threshold

    if logic_operator == "AND":
        result_base["warning"] = dtc_breach and spf_breach
    else:
        result_base["warning"] = dtc_breach or spf_breach

    return result_base
