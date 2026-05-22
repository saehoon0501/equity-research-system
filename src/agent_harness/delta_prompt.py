"""Delta-prompt builder — error list → targeted re-emission prompt.

When Tier-1 validation fails on an agent's artifact, the retry should
NOT re-run the full agent prompt (expensive — agent re-fetches MCP data,
redoes analysis). It should send a TARGETED prompt asking the agent to
patch only the failed fields while reusing the prior artifact verbatim
for everything else.

This module turns an ``AggregateValidationResult`` into that prompt.

Three properties matter:

1. **Targeted**: only the failed fields are mentioned. Agent doesn't burn
   tokens redoing analysis.
2. **Spec-cited**: every error carries its HG-NN identifier and the spec
   file/line where the rule is defined, so the agent can self-correct
   against the source of truth.
3. **Reuse-hint**: the prior artifact path is surfaced with explicit
   "reuse all other fields verbatim; do NOT re-fetch MCP data" language.

DETERMINISM: pure stdlib; the prompt text is fully reproducible from the
inputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

from src.evaluator_gates import AggregateValidationResult, GateOutcome

# Spec-file references used in the delta-prompt body. Kept short and
# stable so the agent can cross-reference quickly.
SPEC_REFS: dict[str, str] = {
    "HG-23": "pm-supervisor.md §8 lines 359-510 (envelope_shape, REQUIRED_TOP_LEVEL + REQUIRED_SUBKEYS + FORBIDDEN_TOP_LEVEL)",
    "HG-24": "pm-supervisor.md §6 line 296 (sentiment_data_degraded ≥2-of-4 indicators rule)",
    "HG-25": "pm-supervisor.md §6 lines 274-294 (conviction bands × mode multipliers; §7 speculative-tier headroom clip)",
    "HG-26": "pm-supervisor.md §8 (evidence_index_refs UUID array; must resolve in evidence_index table)",
    "HG-27": "quantitative-analyst.md Overlay 3+4 (Bayesian blend corrected = intuitive*(1-r) + reference*r)",
    "HG-28": "pm-supervisor.md §8 line 488 (counterfactual_top3_summary canonical buckets; §3.5 retrieval against peak_pain_archetypes)",
    "HG-38": "quantitative-analyst.md §3.10 Overlay 7 (intangibles_adjustment block; Mauboussin Apr 2025 / EPW 2024 industry rates; compute always for non-speculative tiers — regime flag controls only label-calculus promotion, NOT computation)",
}

# Per-gate human-readable diagnostic templates. Each receives a
# ``GateOutcome.result_dict`` and returns a one-line summary plus a
# bullet-list of specific fixes.
GateRenderer = "type alias only — see _renderers below"


def _render_envelope_shape(rd: dict) -> tuple[str, list[str]]:
    summary = "Envelope shape (HG-23) failed — required top-level / sub-keys missing or forbidden field present."
    bullets: list[str] = []
    for k in rd.get("missing_top_level", []) or []:
        bullets.append(f"missing required top-level key: `{k}`")
    for top, subs in (rd.get("missing_subkeys") or {}).items():
        for s in subs:
            bullets.append(f"missing sub-key `{s}` inside `{top}`")
    for f in rd.get("forbidden_fields_present", []) or []:
        bullets.append(
            f"forbidden field present: `{f}` — remove (not in spec enum)"
        )
    if rd.get("invalid_summary_code"):
        bullets.append(
            f"`summary_code` value `{rd['invalid_summary_code']}` not in "
            "canonical enum {BUY, HOLD, TRIM, SELL}"
        )
    rows = rd.get("invalid_report_rows") or {}
    for row_name, missing in rows.items():
        for s in missing:
            bullets.append(
                f"`report.{row_name}` row missing sub-key `{s}` "
                "(reading/detail/evidence_refs/framework_keys/cdd_memo_refs)"
            )
    return summary, bullets


def _render_evidence(rd: dict) -> tuple[str, list[str]]:
    summary = "Evidence UUIDs (HG-26) failed — evidence_index_refs invalid."
    bullets: list[str] = []
    if rd.get("n_refs", 0) == 0:
        bullets.append(
            "`evidence_index_refs` is empty — every claim must cite at "
            "least one evidence_index row; populate this array with the "
            "UUIDs returned from your INSERT INTO evidence_index calls"
        )
    for entry in rd.get("invalid_entries", []) or []:
        bullets.append(f"not a valid UUID: `{entry}`")
    for entry in rd.get("placeholder_entries", []) or []:
        bullets.append(
            f"placeholder string in evidence_index_refs: `{entry}` — "
            "replace with a real UUID from a populated evidence_index row"
        )
    for entry in rd.get("duplicate_entries", []) or []:
        bullets.append(f"duplicate UUID in evidence_index_refs: `{entry}`")
    for entry in rd.get("unresolved_uuids", []) or []:
        bullets.append(
            f"UUID `{entry}` not found in evidence_index table — "
            "INSERT the evidence row before referencing the UUID in the envelope"
        )
    return summary, bullets


def _render_outside_view(rd: dict) -> tuple[str, list[str]]:
    summary = (
        "Outside-view blend (HG-27) failed — Bayesian-blend math "
        "inconsistent with stated r coefficient."
    )
    bullets: list[str] = []
    inputs = rd.get("inputs") or {}
    recomp = rd.get("recomputed") or {}
    deltas = rd.get("deltas") or {}
    if deltas.get("corrected") is not None:
        bullets.append(
            f"`corrected_growth_pct` emitted="
            f"{inputs.get('corrected_growth_pct_emitted')} but blend formula "
            f"intuitive*(1-r) + reference*r = {recomp.get('corrected_growth_pct')} "
            f"(delta {deltas['corrected']:+.4f}pp); recompute and re-emit"
        )
    if deltas.get("raw_divergence") is not None:
        bullets.append(
            f"`outside_view_divergence_pp_raw` emitted="
            f"{inputs.get('outside_view_divergence_pp_raw_emitted')} but "
            f"intuitive - reference = {recomp.get('outside_view_divergence_pp_raw')} "
            f"(delta {deltas['raw_divergence']:+.4f}pp)"
        )
    if deltas.get("corrected_divergence") is not None:
        bullets.append(
            f"`corrected_divergence_pp` emitted="
            f"{inputs.get('corrected_divergence_pp_emitted')} but "
            f"corrected - reference = {recomp.get('corrected_divergence_pp')} "
            f"(delta {deltas['corrected_divergence']:+.4f}pp)"
        )
    for note in rd.get("notes") or []:
        if note.startswith("AMZN-signature"):
            bullets.append(
                "raw_divergence == corrected_divergence with r > 0 — "
                "the blend step appears skipped (corrected copied from raw)"
            )
    return summary, bullets


def _render_sizing(rd: dict) -> tuple[str, list[str]]:
    summary = "Sizing math (HG-25) failed — band/multiplier mismatch."
    bullets: list[str] = []
    inputs = rd.get("inputs") or {}
    if "not in canonical enum" in " ".join(rd.get("notes") or []):
        for n in rd.get("notes") or []:
            bullets.append(n)
        return summary, bullets
    expected = rd.get("expected_band")
    emitted = rd.get("emitted_band")
    if expected and emitted and expected != emitted:
        bullets.append(
            f"`size_band_if_long` emitted={emitted} but expected "
            f"{expected} for conviction={inputs.get('conviction')} × "
            f"mode={inputs.get('mode')}"
            + (
                f" clipped to headroom={rd.get('headroom')} for "
                "speculative_optionality tier"
                if rd.get("tier_clip_required")
                else ""
            )
        )
    if rd.get("tier_clip_required") and rd.get("clipped_max_expected") is not None:
        bullets.append(
            f"speculative_optionality tier requires clipping max_book_pct "
            f"to headroom={rd.get('headroom')}; expected clipped band "
            f"max={rd.get('clipped_max_expected')}"
        )
    for n in rd.get("notes") or []:
        if "non-zero" in n or "sleeve_reference" in n:
            bullets.append(n)
    return summary, bullets


def _render_counterfactual(rd: dict) -> tuple[str, list[str]]:
    summary = "Counterfactual top-3 (HG-28) failed — bucket-schema or catalog membership."
    bullets: list[str] = []
    for b in rd.get("missing_buckets") or []:
        bullets.append(
            f"missing required bucket `{b}` (canonical schema: "
            "survivor / diluted_survivor / non_survivor)"
        )
    for b in rd.get("invented_buckets") or []:
        bullets.append(
            f"invented bucket `{b}` — remove; only "
            "{survivor, diluted_survivor, non_survivor} are valid"
        )
    for f in rd.get("invented_fields") or []:
        bullets.append(
            f"invented sibling field `{f}` — only `lens_disciplined_note` "
            "is permitted alongside the 3 count buckets"
        )
    for cid in rd.get("case_ids_not_in_catalog") or []:
        bullets.append(
            f"case_id `{cid}` is not in peak_pain_archetypes — only "
            "case_ids retrieved via §3.5 may be cited; do NOT fabricate analogs"
        )
    if rd.get("total_count") not in (0, 3, None) and not rd.get("count_matches_top_k"):
        bullets.append(
            f"sum of bucket counts = {rd.get('total_count')}; top-3 "
            "retrieval emits sum=3 (or sum=0 if retrieval failed)"
        )
    return summary, bullets


def _render_sentiment(rd: dict) -> tuple[str, list[str]]:
    summary = "Sentiment degradation (HG-24) failed — emitted flag does not match deterministic re-count."
    bullets: list[str] = [
        f"`sentiment_data_degraded` emitted={rd.get('emitted_degraded')} "
        f"but deterministic re-count from §4 indicators gives "
        f"degraded={rd.get('recomputed_degraded')} "
        f"(unavailable={rd.get('n_unavailable')}, threshold={rd.get('threshold')}, "
        f"unavailable_names={rd.get('unavailable_names')}); re-emit with "
        "the corrected flag and propagate to catalyst_modifier_applied "
        "bound (±25% → ±10% when degraded=true per pm-supervisor.md §6)",
    ]
    return summary, bullets


def _render_intangibles(rd: dict) -> tuple[str, list[str]]:
    summary = (
        "Intangibles adjustment block (HG-38) failed — Overlay 7 schema "
        "fields contain non-numeric sentinels where numeric values are "
        "required, or required sub-blocks are missing."
    )
    bullets: list[str] = []
    if not rd.get("block_present"):
        bullets.append(
            "`intangibles_adjustment` block is missing — per §3.10, tier "
            f"{rd.get('tier')!r} REQUIRES the block. Compute and emit "
            "the 5 numeric fields (capitalized_intangibles_balance_usd, "
            "intangibles_adjusted_earnings_usd, "
            "intangibles_adjusted_invested_capital_usd, "
            "intangibles_adjusted_roic_pct, "
            "reverse_dcf_implied_growth_delta_pp) using EPW 2024 "
            "industry rates + Hall steady-state seed."
        )
    for fname in rd.get("missing_numeric_fields") or []:
        bullets.append(
            f"`intangibles_adjustment.{fname}` is None — compute and "
            "emit a numeric value (do NOT emit any sentinel string)"
        )
    forbidden = rd.get("forbidden_sentinels_in_numeric_fields") or {}
    for fname, sentinel in forbidden.items():
        bullets.append(
            f"`intangibles_adjustment.{fname}` = {sentinel!r} — sentinel "
            "strings are NOT valid for non-speculative tiers. SHADOW MODE "
            "means the value is computed and emitted in shadow alongside "
            "the GAAP baseline; it does NOT mean skip computation. "
            "Compute and emit a numeric value using EPW HiTec rates "
            "(δ_R&D=0.42, δ_organ=0.20, γ_SGA=0.37) for High-tech tickers, "
            "Hall steady-state seed K_0 = I_0/(g+δ) per category, then "
            "geometric roll-forward to current year. See §3.10 for the full "
            "procedure."
        )
    for k in rd.get("missing_epw_rate_keys") or []:
        bullets.append(
            f"`intangibles_adjustment.epw_industry_rates.{k}` missing or "
            "non-numeric — pull from EPW 2024 parameter file at "
            "github.com/michaelewens/Intangible-capital-stocks; for HiTec "
            "use δ_R&D=0.42, δ_organ=0.20, γ_SGA=0.37"
        )
    ff = rd.get("invalid_fama_french_class")
    if ff is not None:
        bullets.append(
            f"`fama_french_industry_class` = {ff!r} not in canonical "
            "5-class enum {HiTec, Hlth, Cnsmr, Manuf, Other}; map ticker's "
            "SIC code to one of these"
        )
    regime = rd.get("invalid_regime")
    if regime is not None:
        bullets.append(
            f"`roic_methodology_regime` = {regime!r} — must be 'gaap' or "
            "'intangibles_adjusted'. Pre-promotion default is 'gaap'"
        )
    if rd.get("skip_flag_inconsistency"):
        bullets.append(rd["skip_flag_inconsistency"])
    for n in rd.get("notes") or []:
        bullets.append(n)
    return summary, bullets


_RENDERERS = {
    "envelope_shape":        _render_envelope_shape,
    "evidence_uuid_check":   _render_evidence,
    "outside_view_blend":    _render_outside_view,
    "sizing_math":           _render_sizing,
    "counterfactual_catalog": _render_counterfactual,
    "sentiment_degradation": _render_sentiment,
    "intangibles_adjustment_shape": _render_intangibles,
}


@dataclass
class DeltaPromptSpec:
    """Structured representation of the delta-prompt before string rendering."""

    failed_gates_summary: list[str]
    fix_bullets: list[str]
    prior_artifact_path: str | None
    reuse_instruction: str


def build_delta_prompt(
    result: AggregateValidationResult,
    *,
    prior_artifact_path: str | None = None,
    agent_type: str | None = None,
    extra_context: str | None = None,
) -> str:
    """Render a targeted re-emission prompt from an aggregate result.

    Args:
        result: failed AggregateValidationResult.
        prior_artifact_path: filesystem path to the prior artifact; the
            prompt instructs the agent to reuse it verbatim and only
            patch the failed fields.
        agent_type: optional name of the agent being re-prompted, used
            only in the prompt header.
        extra_context: optional additional context to inject (e.g.
            "this is attempt 2 of 3").

    Returns:
        A single multi-line string ready to pass back through the agent
        runner.
    """
    spec = build_delta_prompt_spec(
        result, prior_artifact_path=prior_artifact_path
    )

    lines: list[str] = []
    header = f"Re-emission required — Tier-1 validation failed."
    if agent_type:
        header = f"[{agent_type}] {header}"
    lines.append(header)
    lines.append("")
    lines.append(
        "Your prior artifact failed deterministic code-level "
        "validation. Patch ONLY the fields called out below — do NOT "
        "re-fetch MCP data, do NOT redo upstream analysis."
    )
    if extra_context:
        lines.append("")
        lines.append(extra_context)
    lines.append("")
    lines.append("Failed gates:")
    for s in spec.failed_gates_summary:
        lines.append(f"  - {s}")
    lines.append("")
    lines.append("Specific fixes required (one per failing rule):")
    for i, b in enumerate(spec.fix_bullets, start=1):
        lines.append(f"  {i}. {b}")
    lines.append("")
    lines.append(spec.reuse_instruction)
    lines.append("")
    lines.append(
        "Validate locally before returning: "
        "`python3 -m src.evaluator_gates --envelope <path-to-your-envelope>` "
        "must exit 0. Repeated failures on the same field will escalate "
        "to the operator and halt the run."
    )
    return "\n".join(lines)


def build_delta_prompt_spec(
    result: AggregateValidationResult,
    *,
    prior_artifact_path: str | None = None,
) -> DeltaPromptSpec:
    """Structured intermediate form — useful for tests + audit logging."""
    failed_summary: list[str] = []
    fix_bullets: list[str] = []

    for gate in result.gates:
        if gate.valid:
            continue
        renderer = _RENDERERS.get(gate.gate_name)
        if renderer is None:
            failed_summary.append(
                f"{gate.gate_id} {gate.gate_name}: failed (no renderer)"
            )
            continue
        summary, bullets = renderer(gate.result_dict)
        spec_ref = SPEC_REFS.get(gate.gate_id, "(spec ref unknown)")
        failed_summary.append(
            f"{gate.gate_id} {gate.gate_name}: {summary} "
            f"[spec: {spec_ref}]"
        )
        fix_bullets.extend(
            f"[{gate.gate_id}] {b}" for b in bullets
        )

    if prior_artifact_path:
        reuse = (
            f"Your prior artifact is at: {prior_artifact_path}\n"
            "Reuse every field that did NOT fail validation verbatim. "
            "Only emit the patched fields plus enough context for the "
            "envelope to remain well-formed JSON."
        )
    else:
        reuse = (
            "Reuse every field that did NOT fail validation verbatim. "
            "Only emit the patched fields."
        )

    return DeltaPromptSpec(
        failed_gates_summary=failed_summary,
        fix_bullets=fix_bullets,
        prior_artifact_path=prior_artifact_path,
        reuse_instruction=reuse,
    )


def serialize_delta_prompt_spec(spec: DeltaPromptSpec) -> str:
    """Serialize a DeltaPromptSpec to JSON for audit logging."""
    return json.dumps(
        {
            "failed_gates_summary": spec.failed_gates_summary,
            "fix_bullets": spec.fix_bullets,
            "prior_artifact_path": spec.prior_artifact_path,
            "reuse_instruction": spec.reuse_instruction,
        },
        indent=2,
    )


__all__ = [
    "build_delta_prompt",
    "build_delta_prompt_spec",
    "serialize_delta_prompt_spec",
    "DeltaPromptSpec",
    "SPEC_REFS",
]
