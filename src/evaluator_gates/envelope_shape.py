"""Pm-supervisor JSON envelope shape validator (Bug 13 fix — 2026-05-16).

The §8 schema in pm-supervisor.md (lines 342-510) requires top-level
blocks ``tl_dr``, ``report``, and ``audit_trail_hint`` in the serialized
JSON envelope. MSFT 2026-05-15 was surfaced by the audit as omitting all
three from the JSON while rendering the equivalent content in markdown
body — downstream consumers (audit-trail drill, push-alert generation,
operator dashboards) read the envelope, not the markdown, and therefore
silently lost the structured 6-dim report.

This module is the deterministic shape checker. It validates the
envelope dict against the §8 schema and returns a structured result.
Evaluator HG-23 calls this; it can also be invoked directly via CLI.

DETERMINISM: pure Python; no I/O beyond CLI stdin/stdout. No HTTP.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

# Top-level keys per §8 schema. The three CRITICAL_KEYS were the Bug 13
# surface — they MUST be present and non-empty in the JSON envelope, not
# rendered only as markdown body.
CRITICAL_KEYS: tuple[str, ...] = ("tl_dr", "report", "audit_trail_hint")

REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "ticker",
    "as_of",
    "tier",
    "mode",
    "decision_cell_matrix",  # §7.6 v2 (2026-05-23): mandatory top-of-report cell synthesis
    "tl_dr",
    "report",
    "audit_trail_hint",
    "summary_code",
    "conviction",
    "size_band_if_long",
    "sleeve_cap_check",
    "counterfactual_top3_summary",
    "adversarial_stress_test",
    "catalyst_modifier_applied",
    "veto_reason",
    "conviction_rationale",
    "evidence_index_refs",
    "rule_engine_version",
    # HG-22 (Bug 11): conviction-rollup determinism fields.
    "conviction_from_rule",
    "conviction_emitted",
    "conviction_override",
)

# Fields where ``null`` is a legitimate value per §8 schema. For these
# fields the validator requires the KEY to be present, but accepts
# ``None`` / ``null`` as a valid value (no veto fired, no sleeve
# reference for non-speculative tiers, etc.).
NULLABLE_TOP_LEVEL: frozenset[str] = frozenset({
    "veto_reason",       # null when no counterfactual veto fired
    "sleeve_reference",  # null for non-speculative tiers (also optional top-level)
})

# Per-block sub-key nullable map. Same semantics as NULLABLE_TOP_LEVEL but
# scoped to a parent block's sub-keys. Used by the sub-key validation loop
# so that nullable sub-keys count as "present" when the KEY exists and the
# value is None, instead of requiring non-empty. §7.6 v2 (2026-05-23) added
# the decision_cell_matrix.{fundamental_track, technical_track, null_reason}
# trio where any of the three may legitimately be None (a SELL cell has
# fundamental_track=None; an AVOID cell has both tracks None; a populated
# BUY-HIGH cell has null_reason=None). The cross-field rule "null_reason
# REQUIRED iff either track is null" is enforced separately in the
# conditional block below.
NULLABLE_SUBKEYS: dict[str, frozenset[str]] = {
    "decision_cell_matrix": frozenset({
        "fundamental_track",
        "technical_track",
        "null_reason",
    }),
}

# Forbidden fields per the HIGH-4 consensus (docs/high-4-enum-drift-consensus.md,
# 2026-05-16). The MSFT 2026-05-15 run invented ``summary_code_operator_semantic``
# to bridge a 4-bin/5-bin gap that the consensus dissolved entirely. Any
# envelope containing this field is structurally non-conforming and is
# REJECTed by HG-23.
FORBIDDEN_TOP_LEVEL: frozenset[str] = frozenset({
    "summary_code_operator_semantic",
})

# The canonical 4-bin enum for ``summary_code`` per pm-supervisor.md §8
# line 417 and Consensus Item #1. Any value outside this set is invalid.
VALID_SUMMARY_CODES: frozenset[str] = frozenset({"BUY", "HOLD", "TRIM", "SELL"})

# Required sub-keys per top-level block. Only the three critical blocks
# get sub-key validation here; the rest are presence-only at top level.
REQUIRED_SUBKEYS: dict[str, tuple[str, ...]] = {
    "tl_dr": (
        "decision_headline",
        "scenarios_quant",
        "scenarios_strategic",
        "operating_ranges",
        "top_catalysts_90d",
        "reevaluation_triggers",
    ),
    "report": (
        "sentiment",
        "trend",
        "structural_theory",
        "technical_entry",
        "technical_exit",
        "reasoning",
    ),
    "audit_trail_hint": (
        "instructions_for_operator",
        "cross_run_artifact_ids",
        "evidence_index_query_template",
    ),
    # §7.6 v2 (2026-05-23): Decision Cell Matrix sub-keys. The 8 non-nullable
    # sub-keys carry the deterministic axis derivation + cell mapping +
    # consistency check + migration triggers. The 2 nullable sub-keys
    # (fundamental_track, technical_track) carry the USD-anchored entry/exit
    # tracks per the operator-locked v2 emission shape; null_reason is
    # conditionally required iff either track is null (enforced below).
    "decision_cell_matrix": (
        "fund_axis_verdict",
        "fund_axis_signals",
        "tech_axis_verdict",
        "tech_axis_signals",
        "matrix_cell",
        "matrix_cell_narrative",
        "consistency_check",
        "migration_triggers",
        "fundamental_track",  # nullable — see NULLABLE_SUBKEYS
        "technical_track",    # nullable — see NULLABLE_SUBKEYS
    ),
}

# Each row of report.* must have these four fields per §8 spec lines
# 383-432. Used only when strict=True.
REPORT_ROW_SUBKEYS: tuple[str, ...] = (
    "reading",
    "detail",
    "evidence_refs",
    "framework_keys",
    "cdd_memo_refs",
)


@dataclass
class EnvelopeShapeResult:
    """Result envelope for shape validation."""

    valid: bool
    critical_missing: bool  # True iff any of tl_dr/report/audit_trail_hint missing/empty
    missing_top_level: list[str] = field(default_factory=list)
    missing_subkeys: dict[str, list[str]] = field(default_factory=dict)
    invalid_report_rows: dict[str, list[str]] = field(default_factory=dict)
    # invalid_report_rows[row_name] = [list of missing subkeys in that row]
    forbidden_fields_present: list[str] = field(default_factory=list)
    # Fields per FORBIDDEN_TOP_LEVEL that appear in the envelope. Bug 13.1
    # (HIGH-4 consensus 2026-05-16) — silent invention of bridging fields
    # is structurally non-conforming and forces HG-23 REJECT.
    invalid_summary_code: str | None = None
    # Set when summary_code is present but not in VALID_SUMMARY_CODES.
    notes: list[str] = field(default_factory=list)


def _is_present_non_empty(value: object) -> bool:
    """Top-level / sub-key presence check.

    A value counts as present iff it is not None, not a missing key, and
    not an empty container. A literal empty string also fails — an empty
    ``decision_headline`` is not a populated envelope field.
    """
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple)) and len(value) == 0:
        return False
    return True


def validate_envelope_shape(
    envelope: dict, strict: bool = False
) -> EnvelopeShapeResult:
    """Validate ``envelope`` against the pm-supervisor §8 schema.

    Args:
        envelope: parsed JSON envelope dict (typically the pm-supervisor output).
        strict: when True, also validates that each ``report.*`` row has
            the four required sub-keys (reading/detail/evidence_refs/
            framework_keys/cdd_memo_refs). When False (default), only
            top-level + level-1 sub-key presence is checked.

    Returns:
        EnvelopeShapeResult with valid=True iff (a) all REQUIRED_TOP_LEVEL
        keys are present and non-empty, AND (b) the three critical
        blocks each have all their REQUIRED_SUBKEYS, AND (c) when strict,
        each report row has its REPORT_ROW_SUBKEYS.
    """
    if not isinstance(envelope, dict):
        return EnvelopeShapeResult(
            valid=False,
            critical_missing=True,
            notes=[
                f"envelope must be a JSON object (dict); "
                f"got {type(envelope).__name__}"
            ],
        )

    result = EnvelopeShapeResult(valid=True, critical_missing=False)

    # Top-level key presence. For nullable fields, only the KEY needs to
    # exist; null/None is an acceptable value.
    for key in REQUIRED_TOP_LEVEL:
        if key in NULLABLE_TOP_LEVEL:
            if key not in envelope:
                result.missing_top_level.append(key)
        else:
            if not _is_present_non_empty(envelope.get(key)):
                result.missing_top_level.append(key)
                if key in CRITICAL_KEYS:
                    result.critical_missing = True

    # HG-22 conditional: conviction_override_reason required iff
    # conviction_override == True.
    conv_override = envelope.get("conviction_override")
    if conv_override is True:
        if not _is_present_non_empty(envelope.get("conviction_override_reason")):
            result.missing_top_level.append("conviction_override_reason")
            result.notes.append(
                "conviction_override=true requires populated "
                "conviction_override_reason (HG-22 Check 3)"
            )

    # Sub-key presence for the validated blocks. Nullable sub-keys
    # (NULLABLE_SUBKEYS) require only KEY presence; non-nullable sub-keys
    # require both KEY presence AND a non-empty value.
    for top_key, subkeys in REQUIRED_SUBKEYS.items():
        block = envelope.get(top_key)
        if not isinstance(block, dict):
            # If the top-level block itself is missing, that's already
            # in missing_top_level — don't double-report sub-keys for
            # a block that doesn't exist.
            continue
        nullable_for_block = NULLABLE_SUBKEYS.get(top_key, frozenset())
        missing_here = []
        for sk in subkeys:
            if sk in nullable_for_block:
                if sk not in block:
                    missing_here.append(sk)
            else:
                if not _is_present_non_empty(block.get(sk)):
                    missing_here.append(sk)
        if missing_here:
            result.missing_subkeys[top_key] = missing_here

    # §7.6 v2 conditional: decision_cell_matrix.null_reason required iff
    # either fundamental_track or technical_track is null. Mirror of the
    # HG-22 conviction_override_reason conditional above.
    dcm = envelope.get("decision_cell_matrix")
    if isinstance(dcm, dict):
        fund_t = dcm.get("fundamental_track")
        tech_t = dcm.get("technical_track")
        null_r = dcm.get("null_reason")
        if (fund_t is None or tech_t is None) and not _is_present_non_empty(null_r):
            result.missing_subkeys.setdefault(
                "decision_cell_matrix", []
            ).append("null_reason")
            result.notes.append(
                "decision_cell_matrix.null_reason required when either "
                "fundamental_track or technical_track is null (§7.6 v2)"
            )

    # Strict mode: each report.* row must have the row-level subkeys.
    if strict:
        report = envelope.get("report")
        if isinstance(report, dict):
            for row_name in REQUIRED_SUBKEYS["report"]:
                row = report.get(row_name)
                if not isinstance(row, dict):
                    continue  # already counted as a missing subkey above
                missing_row = [
                    sk
                    for sk in REPORT_ROW_SUBKEYS
                    if not _is_present_non_empty(row.get(sk))
                ]
                if missing_row:
                    result.invalid_report_rows[row_name] = missing_row

    # Forbidden-field check (HIGH-4 consensus 2026-05-16 — Bug 13.1).
    for forbidden in FORBIDDEN_TOP_LEVEL:
        if forbidden in envelope:
            result.forbidden_fields_present.append(forbidden)

    # summary_code enum validation per Consensus Item #1.
    sc = envelope.get("summary_code")
    if sc is not None and sc not in VALID_SUMMARY_CODES:
        result.invalid_summary_code = str(sc)

    # Roll up validity.
    if (
        result.missing_top_level
        or result.missing_subkeys
        or result.invalid_report_rows
        or result.forbidden_fields_present
        or result.invalid_summary_code is not None
    ):
        result.valid = False

    return result


def _result_to_dict(r: EnvelopeShapeResult) -> dict:
    return {
        "valid": r.valid,
        "critical_missing": r.critical_missing,
        "missing_top_level": r.missing_top_level,
        "missing_subkeys": r.missing_subkeys,
        "invalid_report_rows": r.invalid_report_rows,
        "forbidden_fields_present": r.forbidden_fields_present,
        "invalid_summary_code": r.invalid_summary_code,
        "notes": r.notes,
    }


def _cli(argv: list[str] | None = None) -> int:
    """CLI wrapper. Reads envelope JSON from ``--envelope <path>`` or
    stdin (``--envelope -``) and prints the validation result as JSON.

    Exit codes:
      0  envelope valid
      1  envelope invalid (one or more checks failed)
      2  envelope unparseable or arguments invalid
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="envelope_shape",
        description=(
            "Validate a pm-supervisor JSON envelope against the §8 "
            "schema. Exit 0 valid, 1 invalid, 2 unparseable."
        ),
    )
    parser.add_argument(
        "--envelope",
        required=True,
        help='path to envelope JSON file, or "-" to read from stdin',
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "additionally validate each report.* row has its required "
            "sub-keys (reading/detail/evidence_refs/framework_keys/cdd_memo_refs)"
        ),
    )
    args = parser.parse_args(argv)

    try:
        if args.envelope == "-":
            raw = sys.stdin.read()
        else:
            with open(args.envelope, "r", encoding="utf-8") as f:
                raw = f.read()
        envelope = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"unable to read/parse envelope: {exc}\n")
        return 2

    result = validate_envelope_shape(envelope, strict=args.strict)
    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "EnvelopeShapeResult",
    "validate_envelope_shape",
    "REQUIRED_TOP_LEVEL",
    "REQUIRED_SUBKEYS",
    "REPORT_ROW_SUBKEYS",
    "CRITICAL_KEYS",
    "FORBIDDEN_TOP_LEVEL",
    "VALID_SUMMARY_CODES",
    "NULLABLE_TOP_LEVEL",
    "NULLABLE_SUBKEYS",
]
