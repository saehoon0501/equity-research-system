"""Terminal-rendered markdown for audit drill-down.

Per v3 spec Section 5.2 (Audit-mode UX) — layered drill-down:
  - Top-level summary first: ticker, recommendation, date, decision_path
    with `drill_link` per stage. Cheap, always rendered.
  - Per-stage drill on demand: verbatim quotes, agent outputs, retrieval
    results, kill-criteria evaluation chain. Expensive payload,
    fetched only when operator explicitly drills in.

Tables are rendered as plain Markdown — no third-party library, terminal
shells (and Claude Code session display) render Markdown tables directly.
This keeps the module zero-dep beyond stdlib.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from src.audit_trail.hmac_verify import ChainVerificationResult
from src.audit_trail.loader import AuditSummary, StageRow

# v3 Section 5.2 stage list, in canonical render order.
STAGES: tuple[str, ...] = (
    "stage_1_mechanical",
    "stage_2_debate",
    "stage_3_kill_criteria",
    "stage_4_counterfactual",
    "materiality",
)

_STAGE_TITLES: dict[str, str] = {
    "stage_1_mechanical": "Stage 1 — Mechanical Rule",
    "stage_2_debate": "Stage 2 — Debate Consensus",
    "stage_3_kill_criteria": "Stage 3 — Kill Criteria",
    "stage_4_counterfactual": "Stage 4 — Counterfactual Veto",
    "materiality": "Materiality Classification",
}


# -----------------------------------------------------------------------------
# Top-level summary
# -----------------------------------------------------------------------------


def render_audit_summary(summary: AuditSummary) -> str:
    """Render the top-level audit summary per v3 Section 5.2 schema.

    Output is markdown suitable for terminal / Claude Code session display.
    """
    rec_id = str(summary.recommendation_id)
    lines: list[str] = []
    lines.append(f"# Audit Trail — {summary.ticker} — {summary.date.isoformat()}")
    lines.append("")
    lines.append(f"**Recommendation:** {summary.recommendation}  ")
    lines.append(f"**Conviction:** {summary.conviction}  ")
    lines.append(f"**Recommendation ID:** `{rec_id}`  ")
    lines.append(
        f"**Audit available:** {'yes' if summary.audit_available else 'NO (flagged)'}"
    )
    lines.append("")
    lines.append("## Decision Path")
    lines.append("")
    lines.append("| Stage | Outcome / Summary | Drill |")
    lines.append("|---|---|---|")
    for stage in STAGES:
        node = summary.decision_path.get(stage)
        if node is None:
            lines.append(
                f"| {_STAGE_TITLES[stage]} | _no row recorded_ | — |"
            )
            continue
        outcome = _summary_outcome_cell(stage, node)
        drill_cmd = _drill_command(rec_id, stage)
        lines.append(
            f"| {_STAGE_TITLES[stage]} | {outcome} | `{drill_cmd}` |"
        )
    lines.append("")
    lines.append("## Versions")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    for k, v in summary.versions.items():
        lines.append(f"| {k} | {_md_escape(v)} |")
    lines.append("")
    lines.append(
        "_Per v3 spec Section 5.2: drill into any stage with the command in "
        "the right column. HMAC chain verification: "
        "`/audit-trail {rec_id} --verify`._".replace("{rec_id}", rec_id)
    )
    return "\n".join(lines)


def _summary_outcome_cell(stage: str, node: Mapping[str, Any]) -> str:
    """Compact one-line summary for the decision_path table."""
    if stage == "stage_1_mechanical":
        return f"outcome: {_v(node.get('outcome'))}; score: {_v(node.get('score'))}"
    if stage == "stage_2_debate":
        return (
            f"consensus: {_v(node.get('consensus'))}; "
            f"dissenter: {_v(node.get('dissenter'))}"
        )
    if stage == "stage_3_kill_criteria":
        fired = node.get("fired")
        if isinstance(fired, list):
            return f"fired: {len(fired)} criteria" + (
                f" — {', '.join(str(x) for x in fired)}" if fired else ""
            )
        return f"fired: {_v(fired)}"
    if stage == "stage_4_counterfactual":
        return (
            f"top-3: {_v(node.get('top_3_archetype'))}; "
            f"veto: {_v(node.get('veto_status'))}"
        )
    if stage == "materiality":
        return (
            f"classification: {_v(node.get('classification'))}; "
            f"trigger: {_v(node.get('trigger'))}"
        )
    return ""


def _drill_command(rec_id: str, stage: str) -> str:
    return f"/audit-trail {rec_id} --stage {stage}"


# -----------------------------------------------------------------------------
# Per-stage drill
# -----------------------------------------------------------------------------


def render_stage_drill(stage: str, row: StageRow) -> str:
    """Render the full drill payload for one stage.

    Per v3 Section 5.2: surfaces verbatim quotes, agent outputs, retrieval
    results, kill-criteria evaluation chain. Renderer dispatches on stage
    and falls back to a generic JSON-pretty-printed block for unknown keys.
    """
    title = _STAGE_TITLES.get(stage, stage)
    lines: list[str] = []
    lines.append(f"# {title} — Drill-down")
    lines.append("")
    lines.append(f"**Audit ID:** `{row.audit_id}`  ")
    lines.append(f"**Recommendation ID:** `{row.recommendation_id}`  ")
    lines.append(
        f"**Parent audit:** "
        f"{'`' + str(row.parent_audit_id) + '`' if row.parent_audit_id else '_root_'}  "
    )
    lines.append(f"**Created at:** {row.created_at.isoformat()}")
    lines.append("")

    payload = row.drill_payload or {}
    if stage == "stage_1_mechanical":
        lines += _render_mechanical(payload)
    elif stage == "stage_2_debate":
        lines += _render_debate(payload)
    elif stage == "stage_3_kill_criteria":
        lines += _render_kill_criteria(payload)
    elif stage == "stage_4_counterfactual":
        lines += _render_counterfactual(payload)
    elif stage == "materiality":
        lines += _render_materiality(payload)
    else:
        lines += _render_generic(payload)

    lines.append("")
    lines.append("## Versions (signed)")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    for k, v in (row.versions or {}).items():
        lines.append(f"| {k} | {_md_escape(v)} |")
    lines.append("")
    lines.append(f"**HMAC signature:** `{row.hmac_signature[:16]}…`")
    return "\n".join(lines)


def _render_mechanical(p: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    out.append("## Mechanical rule outcome")
    out.append("")
    out.append("| Field | Value |")
    out.append("|---|---|")
    out.append(f"| outcome | {_v(p.get('outcome'))} |")
    out.append(f"| score | {_v(p.get('score'))} |")
    out.append(f"| rule_engine_version | {_v(p.get('rule_engine_version'))} |")
    rules = p.get("rules_applied") or p.get("rules") or []
    if rules:
        out.append("")
        out.append("### Rules applied")
        out.append("")
        out.append("| Rule | Matched | Note |")
        out.append("|---|---|---|")
        for r in rules:
            if isinstance(r, Mapping):
                out.append(
                    f"| {_md_escape(r.get('id') or r.get('name'))} | "
                    f"{_v(r.get('matched'))} | {_md_escape(r.get('note', ''))} |"
                )
            else:
                out.append(f"| {_md_escape(r)} | — | — |")
    return out


def _render_debate(p: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    out.append("## Debate consensus")
    out.append("")
    out.append("| Field | Value |")
    out.append("|---|---|")
    out.append(f"| consensus | {_v(p.get('consensus'))} |")
    out.append(f"| dissenter | {_v(p.get('dissenter'))} |")
    out.append(f"| iterations | {_v(p.get('iterations'))} |")
    iterations = p.get("iteration_log") or p.get("iterations_log") or []
    if iterations:
        out.append("")
        out.append("### Iteration log")
        out.append("")
        out.append("| # | Agent | Verdict | Confidence |")
        out.append("|---|---|---|---|")
        for i, it in enumerate(iterations, start=1):
            if isinstance(it, Mapping):
                out.append(
                    f"| {i} | {_md_escape(it.get('agent'))} | "
                    f"{_md_escape(it.get('verdict'))} | "
                    f"{_v(it.get('confidence'))} |"
                )
    quotes = p.get("verbatim_quotes") or p.get("quotes") or []
    if quotes:
        out.append("")
        out.append("### Verbatim quotes")
        out.append("")
        for q in quotes:
            out.append(f"> {_md_escape(q)}")
            out.append("")
    return out


def _render_kill_criteria(p: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    out.append("## Kill-criteria evaluation chain")
    out.append("")
    fired = p.get("fired", [])
    if isinstance(fired, list):
        out.append(f"**Fired:** {len(fired)} criteria")
    else:
        out.append(f"**Fired:** {_v(fired)}")
    out.append("")
    chain = p.get("evaluation_chain") or p.get("chain") or []
    if chain:
        out.append("| Criterion | Threshold | Observed | Fired? |")
        out.append("|---|---|---|---|")
        for c in chain:
            if isinstance(c, Mapping):
                out.append(
                    f"| {_md_escape(c.get('criterion'))} | "
                    f"{_v(c.get('threshold'))} | "
                    f"{_v(c.get('observed'))} | "
                    f"{_v(c.get('fired'))} |"
                )
    return out


def _render_counterfactual(p: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    out.append("## Counterfactual retrieval — top 3 archetypes")
    out.append("")
    top3 = p.get("top_3_archetype") or p.get("top_3") or []
    if isinstance(top3, list) and top3:
        out.append("| Rank | Archetype | Distance | Outcome |")
        out.append("|---|---|---|---|")
        for i, t in enumerate(top3, start=1):
            if isinstance(t, Mapping):
                out.append(
                    f"| {i} | {_md_escape(t.get('archetype') or t.get('name'))} | "
                    f"{_v(t.get('distance'))} | "
                    f"{_md_escape(t.get('outcome'))} |"
                )
            else:
                out.append(f"| {i} | {_md_escape(t)} | — | — |")
    out.append("")
    out.append(f"**Veto status:** {_v(p.get('veto_status'))}")
    rationale = p.get("veto_rationale") or p.get("rationale")
    if rationale:
        out.append("")
        out.append("### Veto rationale")
        out.append("")
        out.append(_md_escape(rationale))
    return out


def _render_materiality(p: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    out.append("## Materiality classification")
    out.append("")
    out.append("| Field | Value |")
    out.append("|---|---|")
    out.append(f"| classification | {_v(p.get('classification'))} |")
    out.append(f"| trigger | {_v(p.get('trigger'))} |")
    out.append(f"| event_ref | {_v(p.get('event_ref'))} |")
    quotes = p.get("verbatim_quotes") or p.get("quotes") or []
    if quotes:
        out.append("")
        out.append("### Verbatim quotes (citation evidence)")
        out.append("")
        for q in quotes:
            out.append(f"> {_md_escape(q)}")
            out.append("")
    return out


def _render_generic(p: Mapping[str, Any]) -> list[str]:
    out = ["## Payload", "", "```json", json.dumps(p, indent=2, default=str), "```"]
    return out


# -----------------------------------------------------------------------------
# HMAC chain verification rendering
# -----------------------------------------------------------------------------


def render_chain_verification(result: ChainVerificationResult) -> str:
    """Render HMAC chain verification result.

    Per v3 Section 7 Q4 lock: any signature mismatch is tamper-evidence;
    surfaces a prominent banner. Caller is expected to flag as M-2 system
    event (see hmac_verify module docstring).
    """
    lines: list[str] = []
    lines.append("# Audit Chain Verification")
    lines.append("")
    lines.append(f"**Recommendation ID:** `{result.recommendation_id}`  ")
    lines.append(f"**Mode:** {result.mode}")
    lines.append("")
    if result.error:
        lines.append(f"**ERROR:** {result.error}")
        return "\n".join(lines)

    if result.all_ok:
        lines.append("**Result:** OK — all rows verified, chain intact.")
    elif result.mode == "unkeyed":
        lines.append(
            "**Result:** UNVERIFIED — AUDIT_HMAC_KEY not set; signature "
            "check skipped. Chain-pointer integrity reported below."
        )
    else:
        lines.append(
            "**Result:** TAMPER-EVIDENT — one or more rows failed HMAC "
            "or chain-pointer verification. **Caller MUST flag this as an "
            "M-2 system event per v3 Section 5.3 push-alert pipeline.**"
        )

    lines.append("")
    lines.append("| Stage | Audit ID | Signature | Parent Link |")
    lines.append("|---|---|---|---|")
    for r in result.rows:
        sig = "OK" if r.signature_ok else ("SKIP" if result.mode == "unkeyed" else "FAIL")
        par = "OK" if r.parent_link_ok else "FAIL"
        lines.append(f"| {r.stage} | `{str(r.audit_id)[:8]}…` | {sig} | {par} |")

    if result.tampered_rows and result.mode == "keyed":
        lines.append("")
        lines.append("## Tamper-evident rows")
        lines.append("")
        for r in result.tampered_rows:
            failures = []
            if not r.signature_ok:
                failures.append("signature mismatch")
            if not r.parent_link_ok:
                failures.append("parent_audit_id pointer invalid")
            lines.append(
                f"- `{r.audit_id}` (stage `{r.stage}`): {', '.join(failures)}"
            )
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


def _v(value: Any) -> str:
    """Render a value compactly for table cells."""
    if value is None:
        return "_n/a_"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        s = json.dumps(value, default=str)
        if len(s) > 60:
            s = s[:57] + "..."
        return f"`{s}`"
    return _md_escape(value)


def _md_escape(value: Any) -> str:
    """Escape pipe + newline so values stay inside table cells."""
    if value is None:
        return ""
    s = str(value)
    return s.replace("|", "\\|").replace("\n", " ")
