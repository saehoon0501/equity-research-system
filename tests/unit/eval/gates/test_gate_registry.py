"""Unit tests for the P0-4 per-artifact gate registry.

The contract these tests pin down:

  * ``validate_all`` is driven entirely by ``REGISTRY`` (artifact_type ->
    ordered list of gate-runner callables). A *new gate can be added to an
    artifact purely by appending a runner to its registry entry* — with NO
    edit to ``validate_all`` and NO per-artifact ``_validate_*`` body to
    touch (there are none anymore).

  * The dummy runner below is defined in this test module (production code is
    untouched), registered in a fixture, and exercised through the public
    ``validate_all`` entrypoint. Its appearance in the result proves the
    registry is the single source of truth for which gates run.

  * Skipped gates (runner returns ``outcome=None``) record a summary entry
    but contribute no GateOutcome and never flip ``valid``.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.eval.gates import (
    GATE_IDS,
    GateContext,
    REGISTRY,
    VALID_ARTIFACT_TYPES,
    validate_all,
)
from src.eval.gates._outcome import GateOutcome, make_outcome


# A stable id registered for the dummy gate so make_outcome can resolve it.
_DUMMY_GATE_NAME = "dummy_registry_probe"
_DUMMY_GATE_ID = "HG-DUMMY-TEST"


def _dummy_runner(env: dict[str, Any], ctx: GateContext):
    """A trivial gate runner. Reports the dummy gate name; passes iff the
    envelope carries a truthy ``_dummy_ok`` flag (so we can prove the gate's
    outcome actually flows into the aggregate result + its valid roll-up)."""
    ok = bool(env.get("_dummy_ok"))
    outcome = make_outcome(
        _DUMMY_GATE_NAME,
        ok,
        {"observed_flag": env.get("_dummy_ok")},
        "ok" if ok else "dummy_flag_falsey",
    )
    return outcome, _DUMMY_GATE_NAME, "pass" if ok else "fail"


def _dummy_skip_runner(env: dict[str, Any], ctx: GateContext):
    """A conditional dummy runner that always skips (outcome=None), proving
    the skip path records a summary entry without an outcome."""
    return None, _DUMMY_GATE_NAME, "skipped"


@pytest.fixture()
def register_dummy_gate():
    """Append the dummy runner to pm_envelope's registry, register its id,
    then remove both in teardown so global state stays clean for other tests.

    Crucially: this fixture mutates ONLY the registry data structure — it does
    NOT touch validate_all or any _validate_* body (there is none)."""
    GATE_IDS[_DUMMY_GATE_NAME] = _DUMMY_GATE_ID
    REGISTRY["pm_envelope"].append(_dummy_runner)
    try:
        yield
    finally:
        REGISTRY["pm_envelope"].remove(_dummy_runner)
        GATE_IDS.pop(_DUMMY_GATE_NAME, None)


@pytest.fixture()
def register_dummy_skip_gate():
    GATE_IDS[_DUMMY_GATE_NAME] = _DUMMY_GATE_ID
    REGISTRY["pm_envelope"].append(_dummy_skip_runner)
    try:
        yield
    finally:
        REGISTRY["pm_envelope"].remove(_dummy_skip_runner)
        GATE_IDS.pop(_DUMMY_GATE_NAME, None)


def test_dummy_gate_runs_via_registry(register_dummy_gate):
    """Registering a dummy gate (append to REGISTRY) makes validate_all run
    it — proving validate_all dispatches purely off the registry."""
    result = validate_all({"_dummy_ok": True}, artifact_type="pm_envelope")

    gate_names = {g.gate_name for g in result.gates}
    assert _DUMMY_GATE_NAME in gate_names, (
        "dummy gate did not run; validate_all is not driven by REGISTRY"
    )
    assert result.summary[_DUMMY_GATE_NAME] == "pass"

    dummy = next(g for g in result.gates if g.gate_name == _DUMMY_GATE_NAME)
    assert isinstance(dummy, GateOutcome)
    assert dummy.gate_id == _DUMMY_GATE_ID
    assert dummy.valid is True
    assert dummy.result_dict == {"observed_flag": True}


def test_dummy_gate_failure_flips_aggregate_valid(register_dummy_gate):
    """A failing dummy gate must drag the aggregate result invalid — proving
    its outcome participates in the overall ``valid`` roll-up like any gate."""
    result = validate_all({"_dummy_ok": False}, artifact_type="pm_envelope")

    dummy = next(g for g in result.gates if g.gate_name == _DUMMY_GATE_NAME)
    assert dummy.valid is False
    assert dummy.error_fingerprint == "dummy_flag_falsey"
    assert result.valid is False
    assert result.summary[_DUMMY_GATE_NAME] == "fail"


def test_dummy_skip_gate_records_summary_without_outcome(register_dummy_skip_gate):
    """A runner returning outcome=None records a 'skipped' summary entry and
    contributes no GateOutcome (mirrors sentiment_degradation et al.)."""
    result = validate_all({}, artifact_type="pm_envelope")

    assert result.summary[_DUMMY_GATE_NAME] == "skipped"
    assert _DUMMY_GATE_NAME not in {g.gate_name for g in result.gates}


def test_registry_unmutated_after_fixture_teardown():
    """Sanity: outside the fixtures the dummy gate is absent — fixtures clean
    up so they don't pollute the shared REGISTRY for other tests."""
    assert _dummy_runner not in REGISTRY["pm_envelope"]
    assert _DUMMY_GATE_NAME not in GATE_IDS
    result = validate_all({}, artifact_type="pm_envelope")
    assert _DUMMY_GATE_NAME not in {g.gate_name for g in result.gates}


def test_registry_keys_match_valid_artifact_types():
    """The registry is the source of truth for artifact dispatch; its keys
    must stay in lock-step with the public VALID_ARTIFACT_TYPES tuple."""
    assert set(REGISTRY) == set(VALID_ARTIFACT_TYPES)


def test_every_artifact_type_has_at_least_one_runner():
    for artifact_type, runners in REGISTRY.items():
        assert runners, f"{artifact_type} has an empty runner list"
        assert all(callable(r) for r in runners)
