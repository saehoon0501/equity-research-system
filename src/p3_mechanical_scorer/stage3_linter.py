"""Stage 3 — deterministic linter.

Per spec Section 4.3 (lines 389-393)::

    Stage 3 (deterministic linter):
      - Cross-check LLM output against Stage-1-known-true facts
      - Flag: contradictions, HIGH without evidence, round-number
              defaulting, position bias, verbosity
      - Routes to operator review; logged to S2 ledger

The linter is *deterministic* (no LLM): it inspects Stage 2 outputs +
Stage 1 outputs (which Stage 2 did NOT see) and surfaces flags. The
linter explicitly verifies that Stage 2's ``saw_rule_output`` flag is
``false`` before performing any cross-check — this prevents accidental
information leakage in audit (if the flag is True, the integrity of
the entire scoring run is in doubt and all results are quarantined).

Flag taxonomy
-------------

* ``contradiction_high_vs_stage1_negative`` — Stage 2 rated a pattern
  HIGH (positive) while Stage 1 rule-evidence indicates the qualitative
  premise is false (e.g., Stage 2 rates founder-equity HIGH but Stage 1B
  marked founder/CEO duration as None/False).
* ``high_without_evidence`` — Stage 2 rating is HIGH but evidence_quotes
  list is empty (should have been auto-defaulted to LOW in Stage 2; if
  present here, indicates a validation pipeline bug).
* ``round_number_defaulting`` — confidence values that look like
  unrefined defaults (0.5, 1.0, 0.0) on >=80% of patterns; empirical
  signal of LLM-laziness.
* ``position_bias`` — same rating across all patterns regardless of
  evidence; or rating monotonically increases/decreases by pattern
  order (LLM anchored on its previous answer).
* ``verbosity`` — rationale strings exceed 2-sentence cap (Section 4.3).
* ``low_confidence_dispersion`` — high dispersion (>=0.6) flagged for
  operator review.
* ``defer_to_human_majority`` — >=50% of patterns flagged
  ``defer_to_human=true``; the run as a whole should escalate.
* ``info_isolation_violation`` — saw_rule_output is True or missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import LINTER_VERSION, RATING_HIGH, RATING_LOW, RATING_MEDIUM


@dataclass
class LinterFlag:
    code: str
    severity: str  # "info" | "warn" | "error"
    detail: str
    pattern_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "detail": self.detail,
            "pattern_id": self.pattern_id,
        }


@dataclass
class Stage3Result:
    flags: list  # list[LinterFlag]
    operator_review_required: bool
    info_isolation_intact: bool
    linter_version: str = LINTER_VERSION
    notes: list = field(default_factory=list)

    def to_audit_payload(self) -> dict:
        return {
            "stage": "stage_3_linter",
            "linter_version": self.linter_version,
            "operator_review_required": self.operator_review_required,
            "info_isolation_intact": self.info_isolation_intact,
            "flags": [f.to_dict() for f in self.flags],
            "notes": list(self.notes),
        }


# Severity that triggers operator review.
OPERATOR_REVIEW_SEVERITIES = frozenset({"warn", "error"})


def _check_info_isolation(stage2: dict) -> tuple[bool, list]:
    """Verify Stage 2 ran under information isolation. Returns (ok, flags)."""
    flags: list = []
    saw = stage2.get("saw_rule_output")
    if saw is None:
        flags.append(
            LinterFlag(
                code="info_isolation_violation",
                severity="error",
                detail="Stage 2 audit missing saw_rule_output flag",
            )
        )
        return False, flags
    if saw is True:
        flags.append(
            LinterFlag(
                code="info_isolation_violation",
                severity="error",
                detail=(
                    "Stage 2 ran with saw_rule_output=true — anchoring-bias "
                    "mitigation broken (Section 4.3)"
                ),
            )
        )
        return False, flags
    return True, flags


def _check_high_without_evidence(stage2: dict) -> list:
    flags: list = []
    for r in stage2.get("ratings", []):
        if r["rating"] == RATING_HIGH and not r.get("evidence_quotes"):
            flags.append(
                LinterFlag(
                    code="high_without_evidence",
                    severity="error",
                    detail=(
                        f"pattern {r['pattern_id']} rated HIGH with no "
                        "evidence_quotes — should have been auto-defaulted to "
                        "LOW in Stage 2 validator"
                    ),
                    pattern_id=r["pattern_id"],
                )
            )
    return flags


def _check_round_number_defaulting(stage2: dict) -> list:
    """Flag if >=80% of confidences are exact round numbers (0.0/0.5/1.0)."""
    flags: list = []
    ratings = stage2.get("ratings", [])
    if not ratings:
        return flags
    rounds = sum(
        1 for r in ratings if r.get("confidence") in (0.0, 0.5, 1.0)
    )
    if rounds / len(ratings) >= 0.8:
        flags.append(
            LinterFlag(
                code="round_number_defaulting",
                severity="warn",
                detail=(
                    f"{rounds}/{len(ratings)} confidences are exact round "
                    "numbers (0.0/0.5/1.0) — likely defaulting"
                ),
            )
        )
    return flags


def _check_position_bias(stage2: dict) -> list:
    flags: list = []
    ratings = stage2.get("ratings", [])
    if len(ratings) < 3:
        return flags
    rs = [r["rating"] for r in ratings]
    # All-same
    if len(set(rs)) == 1:
        flags.append(
            LinterFlag(
                code="position_bias",
                severity="warn",
                detail=(
                    f"All {len(rs)} patterns received the same rating "
                    f"({rs[0]}) — possible position/anchor bias"
                ),
            )
        )
        return flags
    # Monotonic (strictly increasing/decreasing on ordinal scale)
    ord_map = {RATING_LOW: 0, RATING_MEDIUM: 1, RATING_HIGH: 2}
    ords = [ord_map[r] for r in rs]
    if all(b > a for a, b in zip(ords, ords[1:])) or all(
        b < a for a, b in zip(ords, ords[1:])
    ):
        flags.append(
            LinterFlag(
                code="position_bias",
                severity="warn",
                detail="Ratings strictly monotonic by pattern order — likely anchor",
            )
        )
    return flags


def _check_verbosity(stage2: dict) -> list:
    flags: list = []
    for r in stage2.get("ratings", []):
        rationale = r.get("rationale", "") or ""
        # Rough sentence count: split on '. ' / '! ' / '? '
        sent_count = sum(rationale.count(s) for s in (". ", "! ", "? ", ".\n"))
        if rationale.endswith((".", "!", "?")):
            sent_count = max(1, sent_count + 1)
        if sent_count > 2 or len(rationale) > 400:
            flags.append(
                LinterFlag(
                    code="verbosity",
                    severity="info",
                    detail=(
                        f"pattern {r['pattern_id']} rationale exceeds 2-sentence "
                        f"cap (sentences~{sent_count}, len={len(rationale)})"
                    ),
                    pattern_id=r["pattern_id"],
                )
            )
    return flags


def _check_dispersion(stage2: dict) -> list:
    flags: list = []
    for r in stage2.get("ratings", []):
        d = r.get("dispersion")
        if isinstance(d, (int, float)) and d >= 0.6:
            flags.append(
                LinterFlag(
                    code="low_confidence_dispersion",
                    severity="warn",
                    detail=(
                        f"pattern {r['pattern_id']} dispersion={d:.2f} — "
                        "self-consistency disagreement is high"
                    ),
                    pattern_id=r["pattern_id"],
                )
            )
    return flags


def _check_defer_majority(stage2: dict) -> list:
    flags: list = []
    ratings = stage2.get("ratings", [])
    if not ratings:
        return flags
    defers = sum(1 for r in ratings if r.get("defer_to_human"))
    if defers / len(ratings) >= 0.5:
        flags.append(
            LinterFlag(
                code="defer_to_human_majority",
                severity="warn",
                detail=(
                    f"{defers}/{len(ratings)} patterns flagged "
                    "defer_to_human=true — escalate to operator"
                ),
            )
        )
    return flags


def _check_contradictions(stage2: dict, stage1b: dict) -> list:
    """Flag where Stage 2 HIGH rating contradicts a Stage 1B FAIL.

    Concrete checks (Stage 1B has booleans for the same underlying
    proposition that some Stage 2 patterns also rate qualitatively):

    * L3-e-04 pivot-creates-multi-bag (qualitative): if Stage 2 HIGH but
      Stage 1B's ``pivot_creates_multi_bag`` is False -> contradiction.
    * L3-e-05 founder equity stake (qualitative): if Stage 2 HIGH but
      Stage 1B's ``founder_ceo_duration_ge_15y`` is False -> contradiction
      (founder gone for >15y can't have HIGH equity-discipline rating).
    """
    flags: list = []
    if not stage1b:
        return flags
    fails = set(stage1b.get("criteria_fail", []))

    contradiction_map = {
        "L3-e-04": "pivot_creates_multi_bag",
        "L3-e-05": "founder_ceo_duration_ge_15y",
    }
    for r in stage2.get("ratings", []):
        pid = r["pattern_id"]
        crit = contradiction_map.get(pid)
        if crit and crit in fails and r["rating"] == RATING_HIGH:
            flags.append(
                LinterFlag(
                    code="contradiction_high_vs_stage1_negative",
                    severity="error",
                    detail=(
                        f"Stage 2 rated {pid}=HIGH but Stage 1B has {crit}=False "
                        "— qualitative HIGH cannot coexist with mechanical FAIL"
                    ),
                    pattern_id=pid,
                )
            )
    return flags


def lint(stage2: dict, stage1b: Optional[dict] = None) -> Stage3Result:
    """Run all linter checks. ``stage2`` and ``stage1b`` are audit-payload dicts.

    Note: stage1b is optional only because Stage 1A may have rejected
    before Stage 1B ran. If both are None (only Stage 1A), this lints
    Stage 2 alone.
    """
    flags: list = []
    iso_ok, iso_flags = _check_info_isolation(stage2)
    flags.extend(iso_flags)
    if iso_ok:
        flags.extend(_check_high_without_evidence(stage2))
        flags.extend(_check_round_number_defaulting(stage2))
        flags.extend(_check_position_bias(stage2))
        flags.extend(_check_verbosity(stage2))
        flags.extend(_check_dispersion(stage2))
        flags.extend(_check_defer_majority(stage2))
        if stage1b:
            flags.extend(_check_contradictions(stage2, stage1b))

    operator_review = any(f.severity in OPERATOR_REVIEW_SEVERITIES for f in flags)

    return Stage3Result(
        flags=flags,
        operator_review_required=operator_review,
        info_isolation_intact=iso_ok,
    )
