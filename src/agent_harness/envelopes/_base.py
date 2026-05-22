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

    if schema.get("type") == "object" and isinstance(obj, dict):
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

    if schema.get("type") == "array" and isinstance(obj, list):
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
    "EnvelopeFieldError",
    "EnvelopeValidationResult",
    "Predicate",
    "validate_envelope",
]
