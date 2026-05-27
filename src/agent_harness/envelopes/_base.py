"""Envelope base — stdlib stand-in for pydantic v2's BaseModel.

Per harness-v4-final review (5 iterations, 2026-05-22). The plan called
for pydantic v2 envelopes; the repo runs stdlib-only at the top level and
existing typed contracts use ``@dataclass(frozen=True)``
(src/p8_tactical_overlay/contracts.py is the precedent). This module
provides the same SHAPE — JSON Schema export + validate() roundtrip +
cross-field predicates — without the dep.

Each per-agent envelope module declares:
  - SCHEMA: dict — JSON Schema for the emit envelope (rendered into the
    dispatch prompt's #OUTPUT_SCHEMA section so the LLM sees it).
  - REASONING_STEPS: tuple[str, ...] — Literal-equivalent enum the agent
    cites in envelope.reasoning_path_taken.
  - PREDICATES: dict[str, Callable[[dict], bool]] — CROSS-FIELD /
    arithmetic invariants only. Anything reducible to a JSON-Schema
    constraint stays in SCHEMA, not here (iter-3 contract).
  - validate_envelope(data: dict) -> EnvelopeValidationResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# A predicate takes the envelope dict (already shape-validated) and
# returns True iff its invariant holds.
Predicate = Callable[[dict[str, Any]], bool]


# ---------- P0-1 insight-quality schema extension (additive) ----------
#
# Five OPTIONAL top-level fields added to every per-agent envelope module
# for the insight-quality enhancement (plan 2026-05-27, P0-1). They are
# ADDITIVE and BACKWARD-COMPATIBLE: none appears in any module's
# ``required`` list, every one is nullable, and existing envelopes that
# omit them all continue to validate.
#
#   - reasoning_trace: list[{op, rationale}] — paired 1:1 with the
#     existing ``reasoning_path_taken`` (each entry annotates the
#     corresponding opcode with the agent's rationale). The 1:1
#     invariant is contract-documented but NOT enforced by a predicate
#     yet (a length-equality predicate would reject any pre-existing
#     envelope that has ``reasoning_path_taken`` but no
#     ``reasoning_trace``). Enforcement is deferred to WS-2.
#   - axis_a / axis_b — articulation / sophistication score blocks
#     written back by the WS-1 / WS-2 scorers (permissive objects for
#     now; concrete sub-keys land with those workstreams).
#   - gate_decision — the hybrid-gate verdict block (WS-6).
#   - calibration_emission — write-once emission snapshot carrying the
#     fields Brier/log-loss labelling reproduces from (P0-2 resolver).
#
# Schemas keep these blocks permissive (additionalProperties: True) so
# partially-populated envelopes validate during the parallel build.

REASONING_TRACE_SCHEMA: dict[str, Any] = {
    "type": ["array", "null"],
    "items": {
        "type": "object",
        "required": ["op", "rationale"],
        "additionalProperties": True,
        "properties": {
            "op": {"type": "string"},
            "rationale": {"type": "string"},
        },
    },
}

AXIS_SCHEMA: dict[str, Any] = {
    # Articulation / sophistication score block. Permissive object;
    # sub-keys (faithfulness/citation_pr/mode/...) land with WS-1/WS-2.
    "type": ["object", "null"],
    "additionalProperties": True,
}

GATE_DECISION_SCHEMA: dict[str, Any] = {
    # Hybrid-gate verdict block. Permissive object; concrete shape
    # ({verdict, deterministic, advisory}) lands with WS-6.
    "type": ["object", "null"],
    "additionalProperties": True,
}

CALIBRATION_EMISSION_SCHEMA: dict[str, Any] = {
    # Write-once emission snapshot (P0-2). Permissive object; the
    # canonical keys are listed in ``properties`` for documentation but
    # none is required so partially-populated snapshots still validate.
    "type": ["object", "null"],
    "additionalProperties": True,
    "properties": {
        "rec_id": {"type": ["string", "null"]},
        "as_of_ts": {"type": ["string", "null"]},
        "primary_horizon": {"type": ["string", "null"]},
        "benchmark_id": {"type": ["string", "null"]},
        "p_beat_benchmark": {"type": ["number", "null"]},
        "label_method_version": {"type": ["string", "null"]},
        "continuous_score": {"type": ["number", "null"]},
        "model_version": {"type": ["string", "null"]},
    },
}


def insight_quality_properties() -> dict[str, dict[str, Any]]:
    """Return the five additive P0-1 schema properties as a fresh dict.

    Returns NEW copies of the shared fragments so a per-module SCHEMA can
    splice them into its ``properties`` without aliasing shared state.
    All five are OPTIONAL (never added to ``required``).
    """
    import copy

    return {
        "reasoning_trace": copy.deepcopy(REASONING_TRACE_SCHEMA),
        "axis_a": copy.deepcopy(AXIS_SCHEMA),
        "axis_b": copy.deepcopy(AXIS_SCHEMA),
        "gate_decision": copy.deepcopy(GATE_DECISION_SCHEMA),
        "calibration_emission": copy.deepcopy(CALIBRATION_EMISSION_SCHEMA),
    }


@dataclass
class EnvelopeFieldError:
    """One field-level error from JSON-Schema validation.

    Mirrors pydantic v2's ``ValidationError.errors()`` entry shape so
    consumers (delta-prompt renderer) can format uniformly.
    """

    path: str           # e.g. "tactical_cell.cell_disposition"
    expected: str       # e.g. "one of ['HOLD','BUY-HIGH','BUY-MED','AVOID']"
    observed: str       # e.g. "'BUY'" (repr of the offending value)
    schema_fragment: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnvelopeValidationResult:
    """Aggregate envelope validation result.

    Mirrors the existing evaluator_gates result shape (valid + result_dict
    serializable) so the adapter in ``_adapter.py`` can produce a
    GateOutcome that drops into the existing delta_prompt / dispatcher
    fingerprint pipeline without changes to either.
    """

    valid: bool
    field_errors: list[EnvelopeFieldError] = field(default_factory=list)
    failed_predicates: list[str] = field(default_factory=list)
    invalid_reasoning_steps: list[str] = field(default_factory=list)

    def error_fingerprint(self) -> str:
        # Stuck-loop detection: same field-error set across attempts =
        # delta-prompt didn't land. Ordering is sorted for determinism.
        parts = sorted(f"field:{e.path}" for e in self.field_errors)
        parts += sorted(f"pred:{p}" for p in self.failed_predicates)
        parts += sorted(f"step:{s}" for s in self.invalid_reasoning_steps)
        return "|".join(parts) if parts else "ok"

    def to_result_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "field_errors": [e.__dict__ for e in self.field_errors],
            "failed_predicates": list(self.failed_predicates),
            "invalid_reasoning_steps": list(self.invalid_reasoning_steps),
        }


def validate_envelope(
    data: Any,
    *,
    schema: dict[str, Any],
    reasoning_steps: tuple[str, ...],
    predicates: dict[str, Predicate],
) -> EnvelopeValidationResult:
    """Validate ``data`` against the agent envelope contract.

    1. Shape check via JSON Schema (Draft-7 subset; stdlib-only impl).
    2. ``reasoning_path_taken`` values must be in REASONING_STEPS.
    3. PREDICATES are run only if shape + reasoning pass (avoid noisy
       cascade errors when shape is already broken).
    """
    result = EnvelopeValidationResult(valid=True)
    if not isinstance(data, dict):
        result.valid = False
        result.field_errors.append(
            EnvelopeFieldError(
                path="$",
                expected="object",
                observed=type(data).__name__,
                schema_fragment={"type": "object"},
            )
        )
        return result

    _validate_object(data, schema, path="$", out=result)

    rpt = data.get("reasoning_path_taken")
    if isinstance(rpt, list):
        for i, step in enumerate(rpt):
            if step not in reasoning_steps:
                result.valid = False
                result.invalid_reasoning_steps.append(str(step))

    if result.valid:
        for name, pred in predicates.items():
            try:
                ok = bool(pred(data))
            except Exception:
                ok = False
            if not ok:
                result.valid = False
                result.failed_predicates.append(name)

    return result


# ---------- JSON Schema validation (stdlib subset; no external dep) ----


def _validate_object(
    obj: Any,
    schema: dict[str, Any],
    *,
    path: str,
    out: EnvelopeValidationResult,
) -> None:
    if "type" in schema and not _type_matches(obj, schema["type"]):
        out.valid = False
        out.field_errors.append(
            EnvelopeFieldError(
                path=path,
                expected=f"type={schema['type']}",
                observed=f"{type(obj).__name__}={obj!r}",
                schema_fragment=schema,
            )
        )
        return

    # Normalize the declared type to a set so the LIST form
    # (e.g. ["object", "null"], ["array", "null"]) recurses into nested
    # shape validation exactly like the scalar form. The isinstance guard
    # preserves null-permissiveness: a null value (allowed when "null" is
    # in the type) is not a dict/list, so its nested branch is skipped.
    declared_type = schema.get("type")
    type_members = set(declared_type) if isinstance(declared_type, list) else {declared_type}

    if "object" in type_members and isinstance(obj, dict):
        required = schema.get("required", [])
        for r in required:
            if r not in obj:
                out.valid = False
                out.field_errors.append(
                    EnvelopeFieldError(
                        path=f"{path}.{r}" if path != "$" else r,
                        expected="required",
                        observed="missing",
                        schema_fragment=schema.get("properties", {}).get(r, {}),
                    )
                )
        props = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        if additional is False:
            for k in obj:
                if k not in props:
                    out.valid = False
                    out.field_errors.append(
                        EnvelopeFieldError(
                            path=f"{path}.{k}" if path != "$" else k,
                            expected=f"one of {sorted(props.keys())}",
                            observed=f"unknown field {k!r}",
                            schema_fragment={"additionalProperties": False},
                        )
                    )
        for k, sub in props.items():
            if k in obj:
                sub_path = f"{path}.{k}" if path != "$" else k
                _validate_object(obj[k], sub, path=sub_path, out=out)
        return

    if "array" in type_members and isinstance(obj, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, v in enumerate(obj):
                _validate_object(v, items, path=f"{path}[{i}]", out=out)
        return

    if "enum" in schema:
        if obj not in schema["enum"]:
            out.valid = False
            out.field_errors.append(
                EnvelopeFieldError(
                    path=path,
                    expected=f"one of {schema['enum']}",
                    observed=repr(obj),
                    schema_fragment=schema,
                )
            )
            return

    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if "minimum" in schema and obj < schema["minimum"]:
            out.valid = False
            out.field_errors.append(
                EnvelopeFieldError(
                    path=path,
                    expected=f">= {schema['minimum']}",
                    observed=repr(obj),
                    schema_fragment=schema,
                )
            )
        if "maximum" in schema and obj > schema["maximum"]:
            out.valid = False
            out.field_errors.append(
                EnvelopeFieldError(
                    path=path,
                    expected=f"<= {schema['maximum']}",
                    observed=repr(obj),
                    schema_fragment=schema,
                )
            )


def _type_matches(obj: Any, t: Any) -> bool:
    types = t if isinstance(t, list) else [t]
    py_map = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    for tn in types:
        py = py_map.get(tn)
        if py is None:
            continue
        if tn == "integer":
            if isinstance(obj, int) and not isinstance(obj, bool):
                return True
        elif tn == "number":
            if isinstance(obj, (int, float)) and not isinstance(obj, bool):
                return True
        elif tn == "boolean":
            if isinstance(obj, bool):
                return True
        else:
            if isinstance(obj, py):
                return True
    return False


__all__ = [
    "AXIS_SCHEMA",
    "CALIBRATION_EMISSION_SCHEMA",
    "EnvelopeFieldError",
    "EnvelopeValidationResult",
    "GATE_DECISION_SCHEMA",
    "Predicate",
    "REASONING_TRACE_SCHEMA",
    "insight_quality_properties",
    "validate_envelope",
]
