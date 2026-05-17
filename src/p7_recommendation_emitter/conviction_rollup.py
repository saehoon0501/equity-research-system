"""P7 conviction rollup — Section 4.6 Phase 4 Q2 revision of Section 7 PB#5.

Per v3 spec lines 622-629::

    HIGH = ≥4/5 debate AND 0 kills fired
           AND ≤1 of {1 anchor-drift channel triggered}
    MEDIUM = ANY ONE of {3/5 debate, 1 kill fired,
            ≥2 anchor-drift channels triggered}
    LOW = ANY ONE of {<3/5 debate, ≥2 kills fired}

    `mode_certainty: rule_clean | llm_tiebreaker` is a separate annotation
    field, NOT a conviction-bucket determinant.

This module is DETERMINISTIC — no LLM calls. The conviction bucket is a
mechanical rollup over the inputs from upstream phases.

Returns ``ConvictionRollup`` matching the JSONB schema embedded in
``execution_recommendations.conviction`` + ``conviction_breakdown``
(Section 4.6 Q1).

DECISION LOCKS (Section 4.6 Phase 4 Q2):
  * LOW takes precedence over HIGH/MEDIUM when both could fire (LOW
    triggers are stronger negative-evidence than MEDIUM mixed-evidence).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence


CONVICTION_HIGH = "HIGH"
CONVICTION_MEDIUM = "MEDIUM"
CONVICTION_LOW = "LOW"
_VALID_BUCKETS: tuple[str, ...] = (CONVICTION_HIGH, CONVICTION_MEDIUM, CONVICTION_LOW)


@dataclass
class ConvictionInputs:
    """Inputs the rollup consumes.

    debate_add_count: number of styles voting ADD (out of 5).
    debate_total: total styles (default 5).
    kills_fired: count of kill-criterion firings.
    anchor_drift_channels_triggered: 0..3.
    """

    debate_add_count: int
    kills_fired: int
    anchor_drift_channels_triggered: int
    debate_total: int = 5


@dataclass
class ConvictionRollup:
    """Final bucket + breakdown."""

    bucket: str  # HIGH / MEDIUM / LOW
    breakdown: dict
    triggered_rules: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_high(inp: ConvictionInputs) -> tuple[bool, list[str]]:
    """HIGH gate per Section 4.6 (Phase 4 Q2).

    HIGH = debate_add_count >= 4 AND kills_fired == 0 AND
           anchor_drift_channels_triggered <= 1.
    """
    debate_ok = inp.debate_add_count >= 4
    kills_ok = inp.kills_fired == 0
    drift_ok = inp.anchor_drift_channels_triggered <= 1
    if debate_ok and kills_ok and drift_ok:
        return True, [
            f"debate_add_count={inp.debate_add_count} >= 4",
            "kills_fired == 0",
            f"anchor_drift_channels_triggered={inp.anchor_drift_channels_triggered} <= 1",
        ]
    return False, []


def _is_low(inp: ConvictionInputs) -> tuple[bool, list[str]]:
    """LOW: ANY ONE of {<3/5 debate, ≥2 kills}."""
    triggered: list[str] = []
    if inp.debate_add_count < 3:
        triggered.append(f"debate_add_count={inp.debate_add_count} < 3")
    if inp.kills_fired >= 2:
        triggered.append(f"kills_fired={inp.kills_fired} >= 2")
    return (bool(triggered), triggered)


def _is_medium(inp: ConvictionInputs) -> tuple[bool, list[str]]:
    """MEDIUM: ANY ONE of {3/5 debate, 1 kill fired,
    >=2 anchor-drift channels}.
    """
    triggered: list[str] = []
    if inp.debate_add_count == 3:
        triggered.append("debate_add_count == 3")
    if inp.kills_fired == 1:
        triggered.append("kills_fired == 1")
    if inp.anchor_drift_channels_triggered >= 2:
        triggered.append(
            f"anchor_drift_channels_triggered="
            f"{inp.anchor_drift_channels_triggered} >= 2"
        )
    return (bool(triggered), triggered)


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def roll_up_conviction(inp: ConvictionInputs) -> ConvictionRollup:
    """Deterministic conviction rollup per Section 4.6 (Phase 4 Q2).

    Precedence (matches spec wording — "ANY ONE of" → first-rule-wins):
      1. LOW conditions take precedence (any LOW trigger → LOW).
      2. Else if HIGH gate fully satisfied → HIGH.
      3. Else if any MEDIUM trigger → MEDIUM.
      4. Else fallback MEDIUM (no specific trigger; conservative default
         when bins overlap or inputs underspecified).

    Spec ambiguity resolution: when LOW + MEDIUM triggers BOTH fire, LOW
    wins because LOW conditions are stronger negative-evidence (>=2 kills,
    <3 debate, ≥2 NON-SURVIVOR) than MEDIUM's mixed-evidence triggers.
    HIGH only fires when ALL gates pass (it's an AND-gate, not OR).
    """
    # Validate
    if inp.debate_total <= 0:
        raise ValueError("debate_total must be > 0")
    if not 0 <= inp.debate_add_count <= inp.debate_total:
        raise ValueError(
            f"debate_add_count must be in [0, {inp.debate_total}]"
        )
    if inp.kills_fired < 0:
        raise ValueError("kills_fired must be >= 0")
    if not 0 <= inp.anchor_drift_channels_triggered <= 3:
        raise ValueError(
            "anchor_drift_channels_triggered must be in [0, 3]"
        )

    breakdown_base = {
        "debate_consensus": (
            f"{inp.debate_add_count}/{inp.debate_total} ADD"
        ),
        "kills_fired": f"{inp.kills_fired}",
        "drift_channels": (
            f"{inp.anchor_drift_channels_triggered} of 3 triggered"
        ),
    }

    low_hit, low_rules = _is_low(inp)
    if low_hit:
        return ConvictionRollup(
            bucket=CONVICTION_LOW,
            breakdown={**breakdown_base, "rolled_up_via": "LOW rule"},
            triggered_rules=low_rules,
        )

    high_hit, high_rules = _is_high(inp)
    if high_hit:
        return ConvictionRollup(
            bucket=CONVICTION_HIGH,
            breakdown={**breakdown_base, "rolled_up_via": "HIGH gate (all 3 conditions)"},
            triggered_rules=high_rules,
        )

    med_hit, med_rules = _is_medium(inp)
    if med_hit:
        return ConvictionRollup(
            bucket=CONVICTION_MEDIUM,
            breakdown={**breakdown_base, "rolled_up_via": "MEDIUM rule"},
            triggered_rules=med_rules,
        )

    # Fallback: no specific rule fired (e.g., 4/5 debate but only 1 SURVIVOR).
    # This is the "between HIGH and LOW with no MEDIUM trigger" case —
    # conservative MEDIUM default.
    return ConvictionRollup(
        bucket=CONVICTION_MEDIUM,
        breakdown={**breakdown_base, "rolled_up_via": "MEDIUM (fallback default)"},
        triggered_rules=[
            "no LOW/HIGH/MEDIUM rule explicitly fired — conservative MEDIUM "
            "default per ambiguity resolution"
        ],
    )


# ---------------------------------------------------------------------------
# Phase 2 Step 5 — code-pinned summary_code + sleeve_cap + override admissibility
# (drift-fix 2026-05-17)
# ---------------------------------------------------------------------------


# Sleeve caps per pm-supervisor.md §3 (canonical source: v3 spec).
_SLEEVE_CAPS: dict[str, float] = {
    "core_fundamental": 80.0,
    "thematic_growth": 25.0,
    "speculative_optionality": 8.0,
}


# Summary-code enum (v3 spec 4-bin lock 2026-05-16).
SUMMARY_BUY = "BUY"
SUMMARY_HOLD = "HOLD"
SUMMARY_TRIM = "TRIM"
SUMMARY_SELL = "SELL"
_VALID_SUMMARY_CODES: tuple[str, ...] = (
    SUMMARY_BUY, SUMMARY_HOLD, SUMMARY_TRIM, SUMMARY_SELL,
)


# Canonical override reasons admissible per HG-22 v2 (drift-fix 2026-05-17).
# Each reason maps to a predicate that mechanically validates the structured
# override fields against the upstream signals that should have fired.
_ADMISSIBLE_OVERRIDE_REASONS: frozenset[str] = frozenset({
    "price_discipline_overlay",
    "sleeve_cap_violation",
    "brief_quality_floor_breach",
    "stress_test_catastrophic",
})


# Schema version for summary_code derivation. Increments on rule changes so
# evaluator HG-29 can grandfather pre-cutover rows under the prior schema.
SUMMARY_CODE_SCHEMA_VERSION = "v1-2026-05-17"


def check_sleeve_cap(
    tier: str,
    current_aggregate_pct: float,
    projected_aggregate_pct: float,
) -> dict:
    """Mechanical sleeve-cap check per pm-supervisor.md §3.

    Replaces the LLM-prose check that lived in pm-supervisor §3 prior to
    2026-05-17. Returns the canonical dict that pm-supervisor must
    transcribe verbatim into the envelope's ``sleeve_cap_check`` block.

    Args:
        tier: one of ``core_fundamental`` / ``thematic_growth`` /
              ``speculative_optionality``.
        current_aggregate_pct: book_pct sum of HELD + PROPOSED_ADD names in
                               this tier prior to the candidate add.
        projected_aggregate_pct: current + midpoint of the candidate's
                                 proposed size band (size_band_if_long.midpoint).

    Returns:
        dict with keys:
          - ``tier_cap``: float cap for this tier
          - ``current_aggregate``: float, echoed input
          - ``projected_aggregate``: float, echoed input
          - ``headroom``: tier_cap - current_aggregate (>= 0 means addable)
          - ``status``: ``PASS`` / ``VIOLATION`` / ``PASS_SOFT_WARNING``
            PASS_SOFT_WARNING fires when current is approximated from a
            partial-aggregation fallback (caller signals this via passing
            ``current_aggregate_pct`` of exactly 0.0 with positions table
            empty — pm-supervisor.md §2 footnote).

    Raises:
        ValueError on unknown tier.
    """
    if tier not in _SLEEVE_CAPS:
        raise ValueError(
            f"unknown tier '{tier}'; must be one of {list(_SLEEVE_CAPS)}"
        )
    cap = _SLEEVE_CAPS[tier]
    headroom = cap - current_aggregate_pct
    if projected_aggregate_pct > cap:
        status = "VIOLATION"
    elif current_aggregate_pct == 0.0:
        # Soft-warning fallback per pm-supervisor.md §2 — current_aggregate
        # is approximated from the partial-positions fallback rather than
        # the materialised view.
        status = "PASS_SOFT_WARNING"
    else:
        status = "PASS"
    return {
        "tier_cap": cap,
        "current_aggregate": current_aggregate_pct,
        "projected_aggregate": projected_aggregate_pct,
        "headroom": headroom,
        "status": status,
    }


def derive_summary_code(
    conviction: str,
    structural_theory_bullish: bool,
    sleeve_cap_status: str,
    held_position: bool,
) -> tuple[str, str]:
    """Mechanical summary_code derivation per pm-supervisor.md §8.

    Replaces the LLM-prose derivation table that lived in §8 prior to
    2026-05-17. The mapping is monotonic over the inputs; pm-supervisor
    must transcribe the returned code + rule verbatim.

    Args:
        conviction: ``HIGH`` / ``MEDIUM`` / ``LOW`` from roll_up_conviction.
        structural_theory_bullish: whether the §Structural Theory row reads
            bullish (base-case fair > spot AND Helmer gate cleared AND
            reinvestment_moat label ∈ {A, B} AND quality gate PASS).
        sleeve_cap_status: ``PASS`` / ``PASS_SOFT_WARNING`` / ``VIOLATION``.
        held_position: True if ticker is currently HELD per watchlist.

    Returns:
        (summary_code, rule_fired) — the code from the enum + a one-line
        string describing the §8 derivation row that fired (for the
        envelope's audit trail).

    Raises:
        ValueError on invalid conviction or sleeve_cap_status enum values.
    """
    if conviction not in _VALID_BUCKETS:
        raise ValueError(f"invalid conviction '{conviction}'; must be in {_VALID_BUCKETS}")
    if sleeve_cap_status not in ("PASS", "PASS_SOFT_WARNING", "VIOLATION"):
        raise ValueError(
            f"invalid sleeve_cap_status '{sleeve_cap_status}'; "
            "must be PASS / PASS_SOFT_WARNING / VIOLATION"
        )

    # Sleeve cap violation blocks BUY (§3 hard gate).
    if sleeve_cap_status == "VIOLATION":
        return SUMMARY_HOLD, "sleeve_cap VIOLATION → forced HOLD (would-be BUY cap-blocked)"

    cap_pass = sleeve_cap_status in ("PASS", "PASS_SOFT_WARNING")

    # HIGH bullish + cap PASS → BUY
    if conviction == CONVICTION_HIGH and structural_theory_bullish and cap_pass:
        return SUMMARY_BUY, "§5 HIGH conviction AND Structural Theory bullish AND sleeve_cap_check.status = PASS → BUY"

    # MEDIUM bullish + cap PASS → BUY (per pm-supervisor.md line 554)
    if conviction == CONVICTION_MEDIUM and structural_theory_bullish and cap_pass:
        return SUMMARY_BUY, "§5 MEDIUM conviction AND Structural Theory bullish AND sleeve_cap_check.status = PASS → BUY"

    # LOW conviction → HOLD (defer to operator)
    if conviction == CONVICTION_LOW:
        return SUMMARY_HOLD, "§5 LOW conviction → HOLD pending operator review"

    # Bearish structural theory at HIGH/MEDIUM → TRIM if held, else HOLD
    if not structural_theory_bullish:
        if held_position:
            return SUMMARY_TRIM, "Structural Theory NOT bullish AND held position → TRIM"
        return SUMMARY_HOLD, "Structural Theory NOT bullish AND not held → HOLD"

    return SUMMARY_HOLD, "fallback default (conservative HOLD; no derivation row matched)"


def validate_override(
    reason: str,
    fields: dict,
    upstream_channels_fired: frozenset[str],
) -> tuple[bool, str]:
    """3-part admissibility check for conviction overrides per HG-22 v2.

    Replaces the presence-only check in HG-22 (Bug 11 fix 2026-05-16) with
    a structured-validation check that mechanically verifies the claimed
    override reason is justified by upstream signals AND that the
    structured fields support the claim.

    Part (i): ``reason`` must be in the canonical admissible set.
    Part (ii): per-reason field predicate must validate.
    Part (iii): at least one upstream channel matching the reason must
                have actually fired in this run.

    Args:
        reason: the ``conviction_override.reason`` string emitted by
                pm-supervisor.
        fields: the structured override fields dict (overlay_value,
                threshold, observed, etc.).
        upstream_channels_fired: set of channel names that actually
                                 fired upstream in this run.

    Returns:
        (admissible, audit_line) — admissible=True if all three parts pass;
        audit_line carries the specific failure reason or success line.
    """
    if reason not in _ADMISSIBLE_OVERRIDE_REASONS:
        return False, (
            f"override reason '{reason}' not in canonical admissible set "
            f"{sorted(_ADMISSIBLE_OVERRIDE_REASONS)}; "
            "free-text overrides are forbidden post-2026-05-17"
        )

    ok_ii, audit_ii = _validate_override_predicate(reason, fields)
    if not ok_ii:
        return False, audit_ii

    ok_iii, audit_iii = _check_upstream_channel(reason, upstream_channels_fired)
    if not ok_iii:
        return False, audit_iii

    return True, f"override admissible: reason={reason}, predicate validated, channel fired"


def _validate_override_predicate(reason: str, fields: dict) -> tuple[bool, str]:
    """Per-reason structured-field validators."""
    if reason == "price_discipline_overlay":
        try:
            observed = float(fields.get("observed"))
            threshold = float(fields.get("threshold"))
            overlay_value = float(fields.get("overlay_value"))
        except (TypeError, ValueError):
            return False, "price_discipline_overlay predicate: observed/threshold/overlay_value must all be numeric"
        if observed <= threshold:
            return False, (
                f"price_discipline_overlay predicate: observed ({observed}) "
                f"must exceed threshold ({threshold}) for overlay to apply"
            )
        if abs(overlay_value - (observed - threshold)) > 0.01:
            return False, (
                f"price_discipline_overlay predicate: overlay_value ({overlay_value}) "
                f"must equal observed-threshold ({observed - threshold:.4f})"
            )
        return True, "price_discipline_overlay predicate ok"

    if reason == "sleeve_cap_violation":
        try:
            observed_weight = float(fields.get("observed_weight"))
            sleeve_cap = float(fields.get("sleeve_cap"))
        except (TypeError, ValueError):
            return False, "sleeve_cap_violation predicate: observed_weight/sleeve_cap must be numeric"
        if observed_weight <= sleeve_cap:
            return False, (
                f"sleeve_cap_violation predicate: observed_weight ({observed_weight}) "
                f"must exceed sleeve_cap ({sleeve_cap})"
            )
        tier = fields.get("tier")
        if tier in _SLEEVE_CAPS and abs(sleeve_cap - _SLEEVE_CAPS[tier]) > 0.001:
            return False, (
                f"sleeve_cap_violation predicate: emitted cap {sleeve_cap} "
                f"!= canonical cap {_SLEEVE_CAPS[tier]} for tier {tier}"
            )
        return True, "sleeve_cap_violation predicate ok"

    if reason == "brief_quality_floor_breach":
        try:
            observed_score = float(fields.get("observed_score"))
            quality_floor = float(fields.get("quality_floor"))
        except (TypeError, ValueError):
            return False, "brief_quality_floor_breach predicate: observed_score/quality_floor must be numeric"
        if observed_score >= quality_floor:
            return False, (
                f"brief_quality_floor_breach predicate: observed_score ({observed_score}) "
                f"must be below quality_floor ({quality_floor})"
            )
        return True, "brief_quality_floor_breach predicate ok"

    if reason == "stress_test_catastrophic":
        catastrophic = fields.get("catastrophic_failures")
        if not isinstance(catastrophic, int) or catastrophic < 1:
            return False, (
                f"stress_test_catastrophic predicate: catastrophic_failures "
                f"({catastrophic}) must be int >= 1"
            )
        return True, "stress_test_catastrophic predicate ok"

    return False, f"no validator registered for reason '{reason}' (unreachable)"


def _check_upstream_channel(
    reason: str, fired: frozenset[str]
) -> tuple[bool, str]:
    """Verify the claimed override reason has a corresponding upstream
    channel that mechanically fired this run.

    Without this gate, an LLM could emit a structurally-valid override
    block (Part ii predicate passes) for a reason that no signal actually
    triggered — the MSFT 2026-05-15 "honest synthesizer judgment is MEDIUM"
    failure mode lives here.
    """
    expected: dict[str, set[str]] = {
        "price_discipline_overlay": {
            "mos_below_threshold", "reverse_dcf_implied_above_cohort_double",
            "even_bull_case_dcf_below_spot",
        },
        "sleeve_cap_violation": {"sleeve_cap_violation_at_§3"},
        "brief_quality_floor_breach": {
            "brief_below_quality_floor_at_§2_7", "essentials_unverified",
        },
        "stress_test_catastrophic": {"stress_failed_catastrophic_at_§2_6"},
    }
    candidates = expected.get(reason, set())
    if not (candidates & fired):
        return False, (
            f"override reason '{reason}' claimed but no matching upstream "
            f"channel fired in this run. Expected one of {sorted(candidates)}; "
            f"channels that fired: {sorted(fired)}"
        )
    matched = candidates & fired
    return True, f"upstream channel fired: {sorted(matched)}"


__all__ = [
    "CONVICTION_HIGH",
    "CONVICTION_MEDIUM",
    "CONVICTION_LOW",
    "SUMMARY_BUY",
    "SUMMARY_HOLD",
    "SUMMARY_TRIM",
    "SUMMARY_SELL",
    "SUMMARY_CODE_SCHEMA_VERSION",
    "ConvictionInputs",
    "ConvictionRollup",
    "roll_up_conviction",
    "check_sleeve_cap",
    "derive_summary_code",
    "validate_override",
]


def _cli(argv: list[str] | None = None) -> int:
    """Thin CLI wrapper so pm-supervisor (and other agents) can shell out
    to the deterministic rollup instead of re-implementing the rule in
    prose. Prints rollup as JSON to stdout; exit 0 on success.

    Example:
      python -m src.p7_recommendation_emitter.conviction_rollup \\
        --debate-add-count 4 \\
        --kills-fired 0 \\
        --anchor-drift 0
    """
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        prog="conviction_rollup",
        description="Deterministic conviction rollup (HIGH/MEDIUM/LOW).",
    )
    parser.add_argument("--debate-add-count", type=int, required=True)
    parser.add_argument("--kills-fired", type=int, required=True)
    parser.add_argument("--anchor-drift", type=int, required=True)
    parser.add_argument("--debate-total", type=int, default=5)
    args = parser.parse_args(argv)

    inp = ConvictionInputs(
        debate_add_count=args.debate_add_count,
        kills_fired=args.kills_fired,
        anchor_drift_channels_triggered=args.anchor_drift,
        debate_total=args.debate_total,
    )
    try:
        rollup = roll_up_conviction(inp)
    except ValueError as exc:
        sys.stderr.write(f"ValueError: {exc}\n")
        return 2

    sys.stdout.write(
        json.dumps(
            {
                "bucket": rollup.bucket,
                "breakdown": rollup.breakdown,
                "triggered_rules": rollup.triggered_rules,
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
