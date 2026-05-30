"""Per-artifact gate registry (P0-4).

This module turns the previously-hardcoded gate-run lists — both the
top-level ``if/elif`` artifact dispatcher in :mod:`src.eval.gates` AND
the manual ``outcomes.append(...)`` / ``summary[...] = ...`` bodies inside
each ``_validate_*`` helper — into a single data structure:

    REGISTRY: dict[artifact_type, list[GateRunner]]

A *GateRunner* is a thin callable that wraps exactly one underlying
``validate_*`` helper. Each runner:

  * receives the parsed envelope dict + a :class:`GateContext` carrying the
    passthrough knobs that ``validate_all`` used to forward positionally;
  * decides on its own whether it applies (conditional gates such as
    ``sentiment_degradation`` / ``catalyst_modifier_composition_check`` /
    ``crowding_composition_check`` short-circuit to a ``skipped`` summary);
  * returns ``(GateOutcome | None, summary_key, summary_value)``.

    - ``GateOutcome`` is ``None`` when the gate is *skipped* — the runner
      still reports a summary entry (``"skipped"``) but contributes no
      outcome to the aggregate ``valid`` roll-up. This exactly mirrors the
      old behavior where skipped gates set ``summary[k] = "skipped"`` and
      never appended to ``outcomes``.

Adding a new gate to an artifact is therefore a pure data edit: append a
runner to ``REGISTRY[artifact_type]``. No edit to ``validate_all`` and no
edit to any ``_validate_*`` body is needed (those bodies no longer exist —
``validate_all`` iterates this registry directly).

Behavior is intended to be byte-identical to the pre-refactor dispatcher:
the runners below run the same helpers, in the same order, under the same
conditions, and emit the same summary keys/values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.eval.gates.envelope_shape import validate_envelope_shape
from src.eval.gates.evidence_uuid_check import (
    validate_evidence_refs_syntactic,
    validate_evidence_refs_with_db,
)
from src.eval.gates.outside_view_blend import validate_outside_view_blend
from src.eval.gates.sizing_math import validate_sizing_math
from src.eval.gates.counterfactual_catalog import validate_counterfactual_top3
from src.eval.gates.sentiment_degradation import compute_sentiment_data_degraded
from src.eval.gates.quant_memo_shape import validate_quant_memo_shape
from src.eval.gates.strategic_memo_shape import validate_strategic_memo_shape
from src.eval.gates.catalyst_memo_shape import validate_catalyst_memo_shape
from src.eval.gates.cdd_memo_shape import validate_cdd_memo_shape
from src.eval.gates.tactical_envelope_shape import validate_tactical_envelope_shape
from src.eval.gates.reversion_envelope_shape import (
    validate_reversion_envelope_shape,
)
from src.eval.gates.intangibles_adjustment_shape import (
    validate_intangibles_adjustment,
)
from src.eval.gates.intervention_audit_shape import (
    validate_intervention_audit_shape,
)
from src.eval.gates.catalyst_modifier_composition_check import (
    validate_catalyst_modifier_composition,
)
from src.eval.gates.crowding_composition_check import (
    validate_crowding_composition,
)

from src.eval.gates._fingerprints import (
    fingerprint_catalyst_memo,
    fingerprint_catalyst_modifier_composition,
    fingerprint_cdd_memo,
    fingerprint_counterfactual,
    fingerprint_crowding_composition,
    fingerprint_envelope_shape,
    fingerprint_evidence,
    fingerprint_intangibles,
    fingerprint_intervention_audit,
    fingerprint_outside_view,
    fingerprint_quant_memo,
    fingerprint_reversion_envelope,
    fingerprint_sizing,
    fingerprint_strategic_memo,
    fingerprint_tactical_envelope,
)
from src.eval.gates._outcome import make_outcome, to_dict_safe


@dataclass
class GateContext:
    """Passthrough knobs forwarded from ``validate_all`` to each gate runner.

    Mirrors the keyword arguments the old ``_validate_*`` helpers received.
    A runner reads only the fields it needs.
    """

    resolve_evidence_db: bool = False
    case_ids_for_counterfactual: list[str] | None = None
    db_dsn: str | None = None
    catalyst_indicators: list[dict] | None = None
    strict_envelope_shape: bool = False
    catalyst_env: dict | None = None
    flow_env: dict | None = None
    params_snapshot: dict | None = None


# A runner: (envelope, context) -> (outcome_or_None, summary_key, summary_value).
# outcome=None means the gate was skipped (summary still recorded, no roll-up).
GateRunner = Callable[
    [dict[str, Any], GateContext], "tuple[Any, str, str]"
]


# --------------------------------------------------------------------------- #
# Individual gate runners. Each wraps exactly one validate_* helper and
# reproduces the append/summary line(s) of the old _validate_* body verbatim.
# --------------------------------------------------------------------------- #


def _run_envelope_shape(env: dict[str, Any], ctx: GateContext):
    shape = validate_envelope_shape(env, strict=ctx.strict_envelope_shape)
    outcome = make_outcome(
        "envelope_shape", shape.valid, to_dict_safe(shape), fingerprint_envelope_shape(shape)
    )
    return outcome, "envelope_shape", "pass" if shape.valid else "fail"


def _run_evidence_uuid_check(env: dict[str, Any], ctx: GateContext):
    refs = env.get("evidence_index_refs")
    ev = (
        validate_evidence_refs_with_db(refs, db_dsn=ctx.db_dsn)
        if ctx.resolve_evidence_db
        else validate_evidence_refs_syntactic(refs)
    )
    outcome = make_outcome(
        "evidence_uuid_check", ev.valid, to_dict_safe(ev), fingerprint_evidence(ev)
    )
    return outcome, "evidence_uuid_check", "pass" if ev.valid else "fail"


def _run_outside_view_blend_ast(env: dict[str, Any], ctx: GateContext):
    """pm-envelope variant: reads the nested ``adversarial_stress_test`` block."""
    ast_block = env.get("adversarial_stress_test") or {}
    ov = validate_outside_view_blend(ast_block)
    outcome = make_outcome(
        "outside_view_blend", ov.valid, to_dict_safe(ov), fingerprint_outside_view(ov)
    )
    return outcome, "outside_view_blend", "pass" if ov.valid else "fail"


def _run_outside_view_blend_top(env: dict[str, Any], ctx: GateContext):
    """quant-memo variant: the ``outside_view`` field lives at the top level."""
    ov = validate_outside_view_blend(env.get("outside_view") or {})
    outcome = make_outcome(
        "outside_view_blend", ov.valid, to_dict_safe(ov), fingerprint_outside_view(ov)
    )
    return outcome, "outside_view_blend", "pass" if ov.valid else "fail"


def _run_sizing_math(env: dict[str, Any], ctx: GateContext):
    sm = validate_sizing_math(env)
    outcome = make_outcome(
        "sizing_math", sm.valid, to_dict_safe(sm), fingerprint_sizing(sm)
    )
    return outcome, "sizing_math", "pass" if sm.valid else "fail"


def _run_counterfactual_catalog(env: dict[str, Any], ctx: GateContext):
    cf = validate_counterfactual_top3(
        env, case_ids=ctx.case_ids_for_counterfactual, db_dsn=ctx.db_dsn
    )
    outcome = make_outcome(
        "counterfactual_catalog", cf.valid, to_dict_safe(cf), fingerprint_counterfactual(cf)
    )
    return outcome, "counterfactual_catalog", "pass" if cf.valid else "fail"


def _run_sentiment_degradation(env: dict[str, Any], ctx: GateContext):
    # HG-24: skipped unless catalyst-scout §4 indicators were supplied.
    if ctx.catalyst_indicators is None:
        return None, "sentiment_degradation", "skipped"
    sd = compute_sentiment_data_degraded(ctx.catalyst_indicators)
    emitted = env.get("sentiment_data_degraded")
    matches = emitted is None or bool(emitted) == bool(sd.degraded)
    sd_dict = {
        "recomputed_degraded": sd.degraded,
        "emitted_degraded": emitted,
        "matches": matches,
        "n_unavailable": sd.n_unavailable,
        "threshold": sd.threshold,
        "unavailable_names": sd.unavailable_names,
        "notes": sd.notes,
    }
    outcome = make_outcome(
        "sentiment_degradation", matches, sd_dict, "mismatch" if not matches else "ok"
    )
    return outcome, "sentiment_degradation", "pass" if matches else "fail"


def _run_catalyst_modifier_composition(env: dict[str, Any], ctx: GateContext):
    # HG-34 (v0.2): skipped when no parameters_active snapshot was supplied.
    if ctx.params_snapshot is None:
        return None, "catalyst_modifier_composition_check", "skipped"
    cmc = validate_catalyst_modifier_composition(
        catalyst_env=ctx.catalyst_env,
        flow_env=ctx.flow_env,
        pm_env=env,
        parameters_active_snapshot=ctx.params_snapshot,
    )
    outcome = make_outcome(
        "catalyst_modifier_composition_check",
        cmc.valid,
        {
            "audit_string_expected": cmc.audit_string_expected,
            "audit_string_observed": cmc.audit_string_observed,
            "missing_inputs": cmc.missing_inputs,
            "invalid_inputs": cmc.invalid_inputs,
            "drift_detected": cmc.drift_detected,
            "drift_summary": cmc.drift_summary,
            "notes": cmc.notes,
        },
        fingerprint_catalyst_modifier_composition(cmc),
    )
    return (
        outcome,
        "catalyst_modifier_composition_check",
        "pass" if cmc.valid else "fail",
    )


def _run_crowding_composition(env: dict[str, Any], ctx: GateContext):
    # HG-35 (v0.3): skipped when no parameters_active snapshot was supplied.
    if ctx.params_snapshot is None:
        return None, "crowding_composition_check", "skipped"
    cwc = validate_crowding_composition(
        flow_env=ctx.flow_env,
        parameters_active_snapshot=ctx.params_snapshot,
    )
    outcome = make_outcome(
        "crowding_composition_check",
        cwc.valid,
        {
            "warning_expected": cwc.warning_expected,
            "warning_observed": cwc.warning_observed,
            "missing_inputs": cwc.missing_inputs,
            "invalid_inputs": cwc.invalid_inputs,
            "invariant_violations": cwc.invariant_violations,
            "drift_detected": cwc.drift_detected,
            "drift_summary": cwc.drift_summary,
            "notes": cwc.notes,
        },
        fingerprint_crowding_composition(cwc),
    )
    return outcome, "crowding_composition_check", "pass" if cwc.valid else "fail"


def _run_quant_memo_shape(env: dict[str, Any], ctx: GateContext):
    shape = validate_quant_memo_shape(env)
    outcome = make_outcome(
        "quant_memo_shape", shape.valid, to_dict_safe(shape), fingerprint_quant_memo(shape)
    )
    return outcome, "quant_memo_shape", "pass" if shape.valid else "fail"


def _run_intangibles_adjustment(env: dict[str, Any], ctx: GateContext):
    ia = validate_intangibles_adjustment(env)
    outcome = make_outcome(
        "intangibles_adjustment_shape",
        ia.valid,
        to_dict_safe(ia),
        fingerprint_intangibles(ia),
    )
    return outcome, "intangibles_adjustment_shape", "pass" if ia.valid else "fail"


def _run_strategic_memo_shape(env: dict[str, Any], ctx: GateContext):
    shape = validate_strategic_memo_shape(env)
    outcome = make_outcome(
        "strategic_memo_shape",
        shape.valid,
        to_dict_safe(shape),
        fingerprint_strategic_memo(shape),
    )
    return outcome, "strategic_memo_shape", "pass" if shape.valid else "fail"


def _run_catalyst_memo_shape(env: dict[str, Any], ctx: GateContext):
    shape = validate_catalyst_memo_shape(env)
    outcome = make_outcome(
        "catalyst_memo_shape",
        shape.valid,
        to_dict_safe(shape),
        fingerprint_catalyst_memo(shape),
    )
    return outcome, "catalyst_memo_shape", "pass" if shape.valid else "fail"


def _run_cdd_memo_shape(env: dict[str, Any], ctx: GateContext):
    shape = validate_cdd_memo_shape(env)
    outcome = make_outcome(
        "cdd_memo_shape", shape.valid, to_dict_safe(shape), fingerprint_cdd_memo(shape)
    )
    return outcome, "cdd_memo_shape", "pass" if shape.valid else "fail"


def _run_tactical_envelope_shape(env: dict[str, Any], ctx: GateContext):
    shape = validate_tactical_envelope_shape(env)
    outcome = make_outcome(
        "tactical_envelope_shape",
        shape.valid,
        to_dict_safe(shape),
        fingerprint_tactical_envelope(shape),
    )
    return outcome, "tactical_envelope_shape", "pass" if shape.valid else "fail"


def _run_reversion_envelope_shape(env: dict[str, Any], ctx: GateContext):
    shape = validate_reversion_envelope_shape(env)
    outcome = make_outcome(
        "reversion_envelope_shape",
        shape.valid,
        to_dict_safe(shape),
        fingerprint_reversion_envelope(shape),
    )
    return outcome, "reversion_envelope_shape", "pass" if shape.valid else "fail"


def _run_intervention_audit(env: dict[str, Any], ctx: GateContext):
    """In-session-monitor intervention-audit shape gate (HG-39).

    Mirrors ``_run_envelope_shape`` exactly: runs the presence-only validator
    (P13) over the audit envelope and emits the gate outcome.

    Naming (mirrors reversion/tactical): the gate NAME passed to ``make_outcome``
    and the GATE_IDS key are the ``_shape``-suffixed ``intervention_audit_shape``
    (so ``make_outcome`` resolves ``GATE_IDS["intervention_audit_shape"]`` =
    HG-39); the REGISTRY *artifact_type* it is registered under stays the short
    ``intervention_audit`` (design.md §Gate — intervention_audit_shape).

    This runner is registered AFTER the import-time WS-6 hybrid loop below
    (Resolution A): the audit is presence-only (P13), NOT a WS-6 advisory-judge
    artifact — ``_hybrid_gate._spine_for("intervention_audit")`` returns None,
    so attaching a hybrid runner would fail-safe to FAIL and drag a valid audit
    invalid. Registering post-loop keeps the audit out of the judge family the
    design never sanctioned (design.md:255).
    """
    shape = validate_intervention_audit_shape(env)
    outcome = make_outcome(
        "intervention_audit_shape",
        shape.valid,
        to_dict_safe(shape),
        fingerprint_intervention_audit(shape),
    )
    return outcome, "intervention_audit_shape", "pass" if shape.valid else "fail"


# --------------------------------------------------------------------------- #
# The registry: artifact_type -> ordered list of gate runners.
# Order matches the pre-refactor _validate_* bodies exactly so the resulting
# outcomes list (and thus error ordering) is unchanged.
# --------------------------------------------------------------------------- #

REGISTRY: dict[str, list[GateRunner]] = {
    "pm_envelope": [
        _run_envelope_shape,
        _run_evidence_uuid_check,
        _run_outside_view_blend_ast,
        _run_sizing_math,
        _run_counterfactual_catalog,
        _run_sentiment_degradation,
        _run_catalyst_modifier_composition,
        _run_crowding_composition,
    ],
    "quant_memo": [
        _run_quant_memo_shape,
        _run_evidence_uuid_check,
        _run_outside_view_blend_top,
        _run_intangibles_adjustment,
    ],
    "strategic_memo": [
        _run_strategic_memo_shape,
        _run_evidence_uuid_check,
    ],
    "catalyst_memo": [
        _run_catalyst_memo_shape,
        _run_evidence_uuid_check,
    ],
    "cdd_memo": [
        _run_cdd_memo_shape,
    ],
    "tactical_envelope": [
        _run_tactical_envelope_shape,
    ],
    "reversion_envelope": [
        _run_reversion_envelope_shape,
    ],
}


# --------------------------------------------------------------------------- #
# WS-6 HYBRID GATE registration (APPEND-ONLY).
#
# Per the P0-4 contract a new gate is added purely by APPENDING a runner to the
# artifact's REGISTRY list — no edit to ``validate_all`` and no per-artifact
# ``_validate_*`` body. We do exactly that below: build one hybrid runner per
# artifact type (each closes over its artifact_type so it knows which
# deterministic spine to run) and append it to the existing lists.
#
# Production wiring:
#   * The judge round-trip is served from the P0-5 LLM cache (replay in CI).
#   * When no cache hit and no live model client is available the judge
#     fail-safes to ESCALATE (never auto-PASS, never silent-FAIL) — the
#     deterministic spine remains the only thing that can hard-FAIL.
# --------------------------------------------------------------------------- #
from src.eval.gates._hybrid_gate import make_hybrid_runner_for as _make_hybrid_runner_for
from src.llm_cache.cache import cache_from_env as _cache_from_env

# The judge backend is the P0-5 LLM cache when enabled (replay in CI serves the
# verdict from a checked-in cassette). When the cache is disabled (the default
# outside CI) the registered runner has NO judge backend at all — and the
# hybrid gate then ABSTAINS the advisory judge: a spine-PASS stays PASS. This
# is deliberate. An unconfigured advisory judge must never silently downgrade
# every passing envelope to ESCALATE (that would make the advisory judge a
# release blocker — forbidden). The deterministic spine remains the only thing
# that can hard-FAIL regardless. A live model round-trip is opt-in: callers
# that want it pass their own ``compute_fn`` via a custom runner.
_HYBRID_CACHE = _cache_from_env()

for _artifact_type in list(REGISTRY.keys()):
    REGISTRY[_artifact_type].append(
        _make_hybrid_runner_for(
            _artifact_type,
            cache=_HYBRID_CACHE,  # None when LLM cache disabled -> judge abstains
        )
    )


# --------------------------------------------------------------------------- #
# In-session-monitor intervention-audit artifact (Resolution A — register POST
# hybrid loop). This artifact is presence-only (P13, design.md:255), NOT a WS-6
# advisory-judge artifact: ``_hybrid_gate._spine_for("intervention_audit")``
# returns None. Registering it AFTER the loop above means NO spine-less hybrid
# runner is appended to it — a hybrid runner would fail-safe to HYBRID_FAIL and
# drag a VALID audit invalid through ``validate_all``. The post-loop placement
# is the design-correct seam, not a workaround (see ``_run_intervention_audit``).
# --------------------------------------------------------------------------- #
REGISTRY["intervention_audit"] = [_run_intervention_audit]


__all__ = ["GateContext", "GateRunner", "REGISTRY"]
