"""Pure-unit shape/contract tests for the walkforward-tuning-loop owned types.

Task 1.1 — ``src/skills/walkforward_tune/types.py`` is the dependency-root
BARRIER: every cross-leaf shape (`ReadSet`, `TrialSet`, `Partition`,
`OOSSample`, `OOSMatrix`, `GateParams`, `GateVerdict`, `TunerActionAudit`,
`Event`) is pinned here before the parallel leaf fan-out so the leaves cannot
diverge on shape. These are the load-bearing observables an import-only smoke
check cannot prove:

  * the consumed contract types (`OutcomeRecord`/`ReplayResult`/`ReplayWindow`/
    `Candidate` from `src.reactive.replay`, `Label` from
    `src.calibration.scorer`) are IMPORTED (object identity), NOT re-declared
    (the harness↔tuner / P9 seam);
  * `OOSSample` carries EXACTLY the 4 pinned fields
    (survival_net_return + skew + kurtosis + n_obs) — `metric` PRODUCES them and
    `gate` CONSUMES them via `OOSMatrix`, so they must not diverge;
  * `GateVerdict` carries exactly the 9 design-pinned fields (design.md line
    231-232) and never an IS-Sharpe field (R4.5 — IS-Sharpe is never a
    promotion criterion, so it has no place on the verdict);
  * `TunerActionAudit` mirrors the mig-053 columns minus the DB-default
    `created_at` (design.md Data Models, R8.1) for join-by-the-4-keys;
  * every owned dataclass is frozen (determinism) and `get_type_hints`
    resolves on it (no unresolved forward-ref under
    `from __future__ import annotations`).

No LLM, MCP, or live DB — pure leaf type contracts (P1, P14 inner-ring).

Requirements: 4.5 (never IS-Sharpe → no IS-Sharpe field on the verdict),
8.1 (tuner-action audit row), 10.3 (consume Candidate/ParamSnapshot etc. as the
versioned objects it tunes, never re-declaring them).
"""

from __future__ import annotations

import dataclasses as d
import types as _pytypes
import typing
from typing import get_origin, get_type_hints


def _is_optional_str(hint: object) -> bool:
    """True iff ``hint`` is ``str | None`` in either union flavor.

    PEP 604 ``str | None`` has ``get_origin`` == ``types.UnionType``; the
    ``typing.Optional[str]`` / ``typing.Union[str, None]`` form has
    ``typing.Union``. Accept both; assert the args carry ``str`` and
    ``NoneType``.
    """
    if get_origin(hint) not in (typing.Union, _pytypes.UnionType):
        return False
    args = set(typing.get_args(hint))
    return str in args and type(None) in args

# The consumed contract — the seam this barrier must REUSE, never re-declare.
import src.reactive.replay as replay
from src.calibration.scorer import Label as ScorerLabel
from src.reactive.replay import (
    Candidate as ReplayCandidate,
    OutcomeRecord as ReplayOutcomeRecord,
    ReplayResult as ReplayReplayResult,
    ReplayWindow as ReplayReplayWindow,
)

# The system-under-test: the walkforward-owned barrier module.
from src.skills.walkforward_tune import types as wf
from src.skills.walkforward_tune.types import (
    Candidate,
    Event,
    GateParams,
    GateVerdict,
    Label,
    OOSMatrix,
    OOSSample,
    OutcomeRecord,
    Partition,
    ReadSet,
    ReplayResult,
    ReplayWindow,
    TrialSet,
    TunerActionAudit,
)


# --- The nine WALKFORWARD-OWNED dataclasses --------------------------------

OWNED = (
    ReadSet,
    TrialSet,
    Partition,
    OOSSample,
    OOSMatrix,
    GateParams,
    GateVerdict,
    TunerActionAudit,
    Event,
)


def test_all_owned_types_are_dataclasses() -> None:
    for cls in OWNED:
        assert d.is_dataclass(cls), f"{cls.__name__} should be a dataclass"


def test_all_owned_dataclasses_are_frozen() -> None:
    for cls in OWNED:
        params = getattr(cls, "__dataclass_params__")
        assert params.frozen is True, f"{cls.__name__} must be frozen"


def test_get_type_hints_resolves_on_every_owned_dataclass() -> None:
    # Under `from __future__ import annotations` every annotation is a string;
    # get_type_hints resolves them against the module globals. A NameError here
    # means a referenced name (e.g. ReplayWindow, OOSSample, Label) was not
    # imported into types.py — the barrier would be broken for the leaves.
    for cls in OWNED:
        get_type_hints(cls)  # must not raise


# --- Consumed contract types are IMPORTED, not re-declared (R10.3, P9) -----


def test_consumed_replay_types_are_imported_identity_not_redeclared() -> None:
    # Object identity proves types.py re-exports the SAME class object from
    # src.reactive.replay — it did NOT re-declare a parallel shape.
    assert Candidate is ReplayCandidate
    assert OutcomeRecord is ReplayOutcomeRecord
    assert ReplayResult is ReplayReplayResult
    assert ReplayWindow is ReplayReplayWindow
    # Also identical to the package-level re-exports.
    assert Candidate is replay.Candidate
    assert OutcomeRecord is replay.OutcomeRecord
    assert ReplayResult is replay.ReplayResult
    assert ReplayWindow is replay.ReplayWindow


def test_consumed_replay_types_live_in_the_harness_module() -> None:
    # Non-redeclaration is provable by where the class object lives: the
    # harness's types module, not the walkforward types module.
    for cls in (Candidate, OutcomeRecord, ReplayResult, ReplayWindow):
        assert cls.__module__ == "src.reactive.replay.types", (
            f"{cls.__name__} must be the consumed harness type, "
            f"not re-declared in walkforward (got {cls.__module__})"
        )


def test_label_reuses_calibration_scorer_label_not_redeclared() -> None:
    # P9: one canonical 4-bin vocabulary. types.py re-exports the SAME Label
    # enum object from src.calibration.scorer.
    assert Label is ScorerLabel
    assert Label.__module__ == "src.calibration.scorer"
    assert [m.value for m in Label] == ["BUY", "HOLD", "TRIM", "SELL"]


# --- BARRIER PIN: OOSSample — EXACTLY the 4 fields metric↔gate share --------


def test_oossample_has_exactly_the_four_pinned_fields() -> None:
    # The crux: `metric` PRODUCES an OOSSample; `gate` CONSUMES it via
    # OOSMatrix. These four fields are the contract the parallel leaves must
    # NOT diverge on. No 5th field (calibration is folded into the survival-net
    # scalar, not a separate matrix field).
    names = [f.name for f in d.fields(OOSSample)]
    assert names == ["survival_net_return", "skew", "kurtosis", "n_obs"]
    assert len(names) == 4


def test_oossample_field_types() -> None:
    hints = get_type_hints(OOSSample)
    assert hints["survival_net_return"] is float
    assert hints["skew"] is float
    assert hints["kurtosis"] is float
    assert hints["n_obs"] is int


# --- OOSMatrix: the metric→gate container (per-config × per-partition) ------


def test_oosmatrix_carries_per_config_samples_incumbent_and_trial_metadata() -> None:
    names = {f.name for f in d.fields(OOSMatrix)}
    # The gate needs: per-config partition-ordered samples, the incumbent's
    # series, and the trial metadata it deflates effective_n against.
    assert "per_config" in names
    assert "incumbent" in names
    assert "trial_metadata" in names


def test_oosmatrix_per_config_maps_config_to_oossample_series() -> None:
    hints = get_type_hints(OOSMatrix)
    # per_config: {config_id: [OOSSample, ...]} — partition-ordered series.
    assert get_origin(hints["per_config"]) is dict
    key_t, val_t = typing.get_args(hints["per_config"])
    assert key_t is str
    assert get_origin(val_t) is list
    assert typing.get_args(val_t) == (OOSSample,)


def test_oosmatrix_incumbent_is_oossample_series() -> None:
    hints = get_type_hints(OOSMatrix)
    assert get_origin(hints["incumbent"]) is list
    assert typing.get_args(hints["incumbent"]) == (OOSSample,)


# --- GateVerdict: the 9 design-pinned fields; NEVER an IS-Sharpe field ------


def test_gate_verdict_has_exactly_the_nine_design_pinned_fields() -> None:
    # design.md line 231-232.
    names = [f.name for f in d.fields(GateVerdict)]
    assert names == [
        "promote",
        "selected_config",
        "reasons",
        "dsr",
        "psr",
        "min_trl_met",
        "pbo",
        "effective_n",
        "lexicographic_ok",
    ]
    assert len(names) == 9


def test_gate_verdict_field_types() -> None:
    hints = get_type_hints(GateVerdict)
    assert hints["promote"] is bool
    assert _is_optional_str(hints["selected_config"])  # str | None
    assert get_origin(hints["reasons"]) is list
    assert typing.get_args(hints["reasons"]) == (str,)
    assert hints["dsr"] is float
    assert hints["psr"] is float
    assert hints["min_trl_met"] is bool
    assert hints["pbo"] is float
    assert hints["effective_n"] is int
    assert hints["lexicographic_ok"] is bool


def test_gate_verdict_carries_no_in_sample_sharpe_field() -> None:
    # R4.5 / R5.5: IS-Sharpe is NEVER a promotion criterion, so it must not
    # appear on the verdict shape (would invite a downstream consumer to read
    # it). Guard the absence explicitly.
    names = {f.name for f in d.fields(GateVerdict)}
    for forbidden in ("is_sharpe", "in_sample_sharpe", "sharpe", "isr"):
        assert forbidden not in names, f"{forbidden} must not be a GateVerdict field"


# --- GateParams: DSR/PSR/MinTRL/PBO/MinBTL/decision-rule knobs --------------


def test_gate_params_carries_the_threshold_and_decision_rule_knobs() -> None:
    names = {f.name for f in d.fields(GateParams)}
    # The threshold + multiple-testing + decision-rule knob families the gate
    # reads (R5.1-5.5). Names are pinned so gate.py and the orchestrator agree.
    for knob in (
        "dsr_threshold",
        "psr_threshold",
        "min_trl",
        "pbo_threshold",
        "min_btl",
        "oos_margin",
        "consecutive_required",
        "hysteresis",
    ):
        assert knob in names, f"GateParams missing knob {knob}"


# --- TunerActionAudit: mirrors mig-053 columns minus DB-default created_at --


def test_tuner_action_audit_has_the_nine_audit_fields() -> None:
    # design.md Data Models (mig 053): audit_id, run_id, code_version,
    # param_version, walk_forward_window, promoted, track, gate_metrics,
    # hypothesis — created_at is a DB default, not an in-memory field.
    names = [f.name for f in d.fields(TunerActionAudit)]
    assert names == [
        "audit_id",
        "run_id",
        "code_version",
        "param_version",
        "walk_forward_window",
        "promoted",
        "track",
        "gate_metrics",
        "hypothesis",
    ]
    assert len(names) == 9


def test_tuner_action_audit_field_types() -> None:
    hints = get_type_hints(TunerActionAudit)
    assert hints["audit_id"] is str
    assert hints["run_id"] is str
    assert hints["code_version"] is str
    assert hints["param_version"] is str
    # walk_forward_window is null until promoted (design Data Models).
    assert _is_optional_str(hints["walk_forward_window"])
    assert hints["promoted"] is bool
    assert hints["track"] is str
    # gate_metrics / hypothesis are JSONB-backed dicts.
    assert get_origin(hints["gate_metrics"]) is dict
    assert get_origin(hints["hypothesis"]) is dict


def test_tuner_action_audit_carries_the_four_correlation_keys() -> None:
    # R8.3: the 4 keys make every audit row joinable to the trace + ledger.
    names = {f.name for f in d.fields(TunerActionAudit)}
    for key in ("run_id", "code_version", "param_version", "walk_forward_window"):
        assert key in names, f"correlation key {key} missing from audit"


# --- Partition: a CPCV split carrying / deriving a ReplayWindow OOS span ----


def test_partition_carries_or_derives_a_replay_window() -> None:
    # design seam note (line 205): the two specs share ONE window type — this
    # loop's Partition carries/derives the consumed harness ReplayWindow for
    # its OOS span. Prove a ReplayWindow-typed (or -returning) member exists.
    field_names = {f.name for f in d.fields(Partition)}
    hints = get_type_hints(Partition)
    has_window_field = any(hints.get(n) is ReplayWindow for n in field_names)
    has_window_method = any(
        get_type_hints(getattr(Partition, m)).get("return") is ReplayWindow
        for m in dir(Partition)
        if callable(getattr(Partition, m, None)) and not m.startswith("__")
    )
    assert has_window_field or has_window_method, (
        "Partition must carry or derive a ReplayWindow OOS span "
        "(the shared harness window type, design line 205)"
    )


# --- TrialSet: >=2 Candidates + trial metadata for effective_N -------------


def test_trial_set_holds_candidates_and_trial_metadata() -> None:
    hints = get_type_hints(TrialSet)
    names = {f.name for f in d.fields(TrialSet)}
    # A list of the consumed Candidate (>=2 enforced by fit.py, not the type),
    # plus trial metadata the gate deflates effective_N against.
    cand_field = next(
        n for n in names if get_origin(hints.get(n)) is list
        and typing.get_args(hints[n]) == (Candidate,)
    )
    assert cand_field, "TrialSet must hold a list[Candidate]"
    assert any("metadata" in n or "trial" in n for n in names), (
        "TrialSet must carry trial metadata (for effective_N)"
    )


# --- ReadSet: firewalled trace slice + drained events ----------------------


def test_read_set_carries_a_trace_slice_and_drained_events() -> None:
    hints = get_type_hints(ReadSet)
    names = {f.name for f in d.fields(ReadSet)}
    # The drained events are a list[Event] (the owned drained-event shape).
    event_field = next(
        (n for n in names
         if get_origin(hints.get(n)) is list
         and typing.get_args(hints[n]) == (Event,)),
        None,
    )
    assert event_field is not None, "ReadSet must carry a list[Event] of drained events"


# --- Module hygiene: pure stdlib/typing + consumed-contract re-exports ------


def test_types_module_reexports_the_consumed_contract() -> None:
    # The barrier is the single import point for the parallel leaves.
    for name in (
        "Candidate",
        "OutcomeRecord",
        "ReplayResult",
        "ReplayWindow",
        "Label",
    ):
        assert hasattr(wf, name), f"types.py must re-export {name}"
        assert name in wf.__all__, f"{name} must be in types.__all__"
