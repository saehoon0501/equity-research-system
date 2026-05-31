"""Pure-unit shape/contract tests for the Replay Harness contract types.

Task 1.1 (reactive-replay-harness). These are the harness↔tuner seam's
load-bearing observables that an import-only smoke check cannot prove:
the pinned 9-field ``OutcomeRecord`` shape (design "Data Models → Owned
(in-memory contracts only)" block), the reuse of the canonical decision
vocabulary (``Decision`` from ``src.reactive.types``) and the calibration
label (``Label`` from ``src.calibration.scorer``) rather than re-declaration,
the frozen-dataclass determinism contract, and ``DataPort`` being a structural
``typing.Protocol`` exposing the five named point-in-time fetch methods.

No LLM, MCP, or live DB — these are pure leaf type contracts (P1, P14
inner-ring; R1.3 single-config candidate shape, R8.1 outcome-record contract).

Requirements: 1.3 (candidate = param snapshot and/or survival params and/or
code version), 8.1 (per-period record: decisions, fills, total-return P&L,
survival events, predicted probabilities, realized labels).
"""

from __future__ import annotations

import dataclasses as d
import typing
from typing import Protocol, get_origin, get_type_hints

# Canonical vocabularies the contract MUST reuse (P9), not re-declare.
from src.calibration.scorer import Label
from src.reactive.types import Decision

from src.reactive.replay.types import (
    Candidate,
    DataPort,
    Fill,
    FidelityResult,
    OutcomeRecord,
    ReplayResult,
    ReplayWindow,
)


# --- All contract types import (R1.3, R8.1) ------------------------------


def test_all_contract_types_importable() -> None:
    for cls in (
        Candidate,
        ReplayWindow,
        Fill,
        OutcomeRecord,
        ReplayResult,
        FidelityResult,
    ):
        assert d.is_dataclass(cls), f"{cls.__name__} should be a dataclass"


# --- Frozen-dataclass determinism contract (R9.1) ------------------------


def test_contract_dataclasses_are_frozen() -> None:
    for cls in (
        Candidate,
        ReplayWindow,
        Fill,
        OutcomeRecord,
        ReplayResult,
        FidelityResult,
    ):
        params = getattr(cls, "__dataclass_params__")
        assert params.frozen is True, f"{cls.__name__} must be frozen"


# --- OutcomeRecord: EXACTLY the 9 pinned fields (R8.1) -------------------


def test_outcome_record_has_exactly_nine_pinned_fields() -> None:
    names = [f.name for f in d.fields(OutcomeRecord)]
    assert names == [
        "period",
        "symbol",
        "decision",
        "predicted_probability",
        "fills",
        "total_return_pnl",
        "survival_events",
        "realized_outcome",
        "realized_label",
    ]
    assert len(names) == 9


def test_outcome_record_realized_label_reuses_calibration_label() -> None:
    hints = get_type_hints(OutcomeRecord)
    # Enum class identity proves reuse of src.calibration.scorer.Label.
    assert hints["realized_label"] is Label


def test_outcome_record_decision_reuses_reactive_decision() -> None:
    hints = get_type_hints(OutcomeRecord)
    # Literal equality (typing caches Literal so `is` is unreliable);
    # equality proves the field is the reactive Decision vocab, not a re-decl.
    assert hints["decision"] == Decision


def test_outcome_record_fills_is_list_of_fill() -> None:
    hints = get_type_hints(OutcomeRecord)
    assert get_origin(hints["fills"]) is list
    assert typing.get_args(hints["fills"]) == (Fill,)


# --- ReplayResult: records (list) + fidelity (FidelityResult) -----------


def test_replay_result_records_is_list_and_fidelity_is_fidelityresult() -> None:
    hints = get_type_hints(ReplayResult)
    assert get_origin(hints["records"]) is list
    assert typing.get_args(hints["records"]) == (OutcomeRecord,)
    assert hints["fidelity"] is FidelityResult


# --- DataPort: a structural Protocol with the five named methods --------


def test_dataport_is_a_protocol() -> None:
    # typing.Protocol leaves this sentinel truthy on the class object.
    assert getattr(DataPort, "_is_protocol", False) is True
    assert issubclass(DataPort, Protocol)


def test_dataport_exposes_the_five_pinned_fetch_methods() -> None:
    for name in (
        "fetch_daily_bars",
        "fetch_intraday",
        "fetch_quotes",
        "fetch_corporate_actions",
        "fetch_rf_yield",
    ):
        assert callable(getattr(DataPort, name)), f"DataPort.{name} missing"


def test_dataport_is_structurally_satisfiable() -> None:
    # A fixture provider with the five methods is a structural DataPort —
    # the R9.2 isolation seam (real data_client in prod, fixture in tests).
    class _Fixture:
        def fetch_daily_bars(self, symbol, start, end):  # noqa: ANN001
            return []

        def fetch_intraday(self, symbol, day):  # noqa: ANN001
            return []

        def fetch_quotes(self, symbol, ts):  # noqa: ANN001
            return {}

        def fetch_corporate_actions(self, symbol, start, end):  # noqa: ANN001
            return []

        def fetch_rf_yield(self, day):  # noqa: ANN001
            return 0.0

    port: DataPort = _Fixture()
    assert port.fetch_rf_yield("2026-05-30") == 0.0


# --- FidelityResult: status vocabulary (R7.1/7.2/7.3) -------------------


def test_fidelity_result_status_literal_exact() -> None:
    hints = get_type_hints(FidelityResult)
    assert set(typing.get_args(hints["status"])) == {
        "pass",
        "fail",
        "not_evaluable",
    }


# --- Candidate: all three knobs optional (R1.3) -------------------------


def test_candidate_fields_are_param_survival_code() -> None:
    names = [f.name for f in d.fields(Candidate)]
    assert names == ["param_snapshot", "survival_parameters", "code_version"]
