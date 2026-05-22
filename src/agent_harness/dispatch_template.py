"""Templated dispatch + pre-flight lint.

Per harness-v4-final Step 2 (5-iteration /review-me convergence,
2026-05-22). Renders the dispatch prompt from typed inputs — no prose
composition — and lints the rendered output before the orchestrator
hands it to ``Agent()``.

PROMPT LAYOUT (preserves §1.5 + PostToolUse-hook contracts):

    <line 1>   PARAMETERS_USED header block VERBATIM
    <line 2>   run_id: <uuid>
    <blank>
    # GOAL
    <one sentence>

    # INPUTS
    <JSON object: cdd_brief + evidence_refs>

    # REASONING_PATH
    Allowed steps (cite by name in envelope.reasoning_path_taken):
    - <step_1>
    - <step_2>
    ...

    # OUTPUT_SCHEMA
    <JSON Schema of the emit envelope, indent=2>

    # ON_VALIDATION_FAILURE
    Re-read OUTPUT_SCHEMA. Emit corrected JSON only. Do not narrate.

Lines 1–2 (PARAMETERS_USED + run_id) are preserved BYTE-VERBATIM because
the PostToolUse hook parses ``run_id:`` from the prompt body and the
HG-25 DB roundtrip joins on the resolved UUID. Restructuring those two
lines would break ``scripts/post_agent_validate.sh`` line 100 and the
``run_parameters_snapshot`` JOIN at the same step.

NO DB HITS in pre-flight lint: EvidenceRef UUIDs are format-checked
only; DB resolution stays in HG-25 post-emit (iter-3 finding).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EvidenceRef:
    uri: str
    evidence_uuid: str


class DispatchLintError(ValueError):
    """Pre-flight lint rejected the rendered prompt — do not dispatch."""


def render_dispatch_prompt(
    *,
    agent_type: str,
    run_id: str,
    parameters_used_block: str,
    goal: str,
    cdd_brief: dict[str, Any],
    evidence_refs: list[EvidenceRef],
    reasoning_steps: tuple[str, ...],
    output_schema: dict[str, Any],
) -> str:
    """Render a dispatch prompt deterministically from typed inputs.

    Args:
        agent_type: subagent name (audit only; not in prompt text).
        run_id: UUIDv4 stamped into line 2.
        parameters_used_block: pre-composed PARAMETERS_USED block (§1.5
            contract) — INSERTED BYTE-VERBATIM as line 1+. The caller is
            responsible for upstream composition; this module does not
            re-derive it from parameter snapshots.
        goal: one-sentence goal for #GOAL.
        cdd_brief: CDD brief as a JSON-serializable dict (NEVER inline
            long text — pass evidence refs and let the agent look it up).
        evidence_refs: typed {uri, evidence_uuid} list. Long-text inputs
            (10-K excerpts, transcripts) are NEVER inlined here — they
            live behind UUIDs in the evidence_index store.
        reasoning_steps: allowed Literal values for
            envelope.reasoning_path_taken. Invented steps → HG-ENV fail.
        output_schema: JSON Schema of the emit envelope.

    Returns:
        The rendered prompt string. Caller MUST pass it through
        ``lint_dispatch_prompt`` before dispatching to ``Agent()``.
    """
    if not goal.strip().endswith((".", "?", "!")):
        goal = goal.rstrip() + "."

    inputs_blob = {
        "cdd_brief": cdd_brief,
        "evidence_refs": [
            {"uri": r.uri, "evidence_uuid": r.evidence_uuid}
            for r in evidence_refs
        ],
    }

    parts: list[str] = []
    parts.append(parameters_used_block.rstrip("\n"))
    parts.append(f"run_id: {run_id}")
    parts.append("")
    parts.append("# GOAL")
    parts.append(goal.strip())
    parts.append("")
    parts.append("# INPUTS")
    parts.append(json.dumps(inputs_blob, indent=2, sort_keys=True))
    parts.append("")
    parts.append("# REASONING_PATH")
    parts.append(
        "Allowed steps (cite by name in envelope.reasoning_path_taken; "
        "any other name = HG-ENV hard fail):"
    )
    for s in reasoning_steps:
        parts.append(f"  - {s}")
    parts.append("")
    parts.append("# OUTPUT_SCHEMA")
    parts.append(
        "Your emit envelope MUST conform to this JSON Schema "
        "(extra fields forbidden, required fields enforced):"
    )
    parts.append(json.dumps(output_schema, indent=2, sort_keys=True))
    parts.append("")
    parts.append("# ON_VALIDATION_FAILURE")
    parts.append(
        "Re-read OUTPUT_SCHEMA and the delta-prompt's field-error list. "
        "Emit corrected JSON only. Do not narrate. Do not re-fetch MCP data."
    )
    return "\n".join(parts) + "\n"


def lint_dispatch_prompt(prompt: str) -> None:
    """Pre-dispatch lint. Raises DispatchLintError on failure.

    Checks (NO DB hits — HG-25 owns evidence_uuid DB resolution post-emit):

      L1. PARAMETERS_USED block present at line 1 (§1.5 contract).
      L2. ``run_id: <uuid>`` line with UUIDv4 syntax (PostToolUse hook).
      L3. # GOAL section present (1 sentence).
      L4. # INPUTS section parses as JSON.
      L5. # REASONING_PATH section present.
      L6. # OUTPUT_SCHEMA section parses as JSON.
      L7. # ON_VALIDATION_FAILURE section present.
      L8. EvidenceRef entries in #INPUTS have UUIDv4-syntax evidence_uuid.
    """
    lines = prompt.split("\n")
    if not lines or not lines[0].startswith("PARAMETERS_USED"):
        raise DispatchLintError(
            "L1: line 1 must start with 'PARAMETERS_USED' (§1.5 contract)"
        )

    rid_match = None
    for ln in lines[:50]:
        if ln.startswith("run_id:"):
            rid_match = ln
            break
    if rid_match is None:
        raise DispatchLintError("L2: no 'run_id:' line found in first 50 lines")
    rid = rid_match[len("run_id:"):].strip()
    if not UUID_V4_RE.match(rid):
        raise DispatchLintError(
            f"L2: run_id {rid!r} is not a valid UUIDv4"
        )

    sections = _extract_sections(prompt)
    for required in (
        "# GOAL",
        "# INPUTS",
        "# REASONING_PATH",
        "# OUTPUT_SCHEMA",
        "# ON_VALIDATION_FAILURE",
    ):
        if required not in sections:
            raise DispatchLintError(
                f"L3-7: missing section {required!r}"
            )

    inputs_text = sections["# INPUTS"].strip()
    try:
        inputs = json.loads(inputs_text)
    except json.JSONDecodeError as exc:
        raise DispatchLintError(
            f"L4: #INPUTS does not parse as JSON: {exc}"
        ) from exc

    schema_text = sections["# OUTPUT_SCHEMA"].strip()
    # OUTPUT_SCHEMA section has a leading sentence before the JSON block;
    # extract the first balanced JSON object.
    jstart = schema_text.find("{")
    if jstart < 0:
        raise DispatchLintError("L6: #OUTPUT_SCHEMA contains no JSON object")
    try:
        json.loads(schema_text[jstart:])
    except json.JSONDecodeError as exc:
        raise DispatchLintError(
            f"L6: #OUTPUT_SCHEMA JSON object does not parse: {exc}"
        ) from exc

    refs = inputs.get("evidence_refs", []) if isinstance(inputs, dict) else []
    for i, r in enumerate(refs):
        if not isinstance(r, dict):
            raise DispatchLintError(
                f"L8: evidence_refs[{i}] is not a dict"
            )
        ev_uuid = r.get("evidence_uuid", "")
        if not UUID_V4_RE.match(str(ev_uuid)):
            raise DispatchLintError(
                f"L8: evidence_refs[{i}].evidence_uuid {ev_uuid!r} "
                "is not a valid UUIDv4 (DB resolution deferred to HG-25)"
            )


def _extract_sections(prompt: str) -> dict[str, str]:
    """Slice the prompt by '# SECTION' headers, returning header → body."""
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in prompt.split("\n"):
        if line.startswith("# ") and not line.startswith("# -"):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = line.strip()
            buf = []
        else:
            if current is not None:
                buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


__all__ = [
    "DispatchLintError",
    "EvidenceRef",
    "lint_dispatch_prompt",
    "render_dispatch_prompt",
]
