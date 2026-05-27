"""P0-8 — golden score-block fixture tests.

Asserts the Phase-0 deliverable P0-8 fixtures are real, schema-valid
envelopes with FULLY POPULATED ``axis_a`` / ``axis_b`` / ``gate_decision``
blocks — the blocks WS-6 will test gating-on-scores against, and the
WS-5 ``bon_panel/`` quality-lift baseline panel (exactly 10 envelopes).

All fixtures are validated through the SAME entrypoint the contract test
uses: ``<module>.validate(envelope)`` from
``src.agent_harness.envelopes.*``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent_harness.envelopes import flow as flow_env
from src.agent_harness.envelopes import pm_supervisor as pm_env
from src.agent_harness.envelopes import reversion as reversion_env
from src.agent_harness.envelopes import tactical as tactical_env

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_GOLDEN_DIR = _FIXTURES / "golden_score_blocks"
_BON_PANEL_DIR = _FIXTURES / "bon_panel"

# filename stem -> the validation entrypoint for that envelope type.
_GOLDEN_VALIDATORS = {
    "pm_supervisor": pm_env.validate,
    "flow": flow_env.validate,
    "tactical": tactical_env.validate,
    "reversion": reversion_env.validate,
}

# The three populated score blocks P0-8 requires (non-null, non-empty dicts).
_SCORE_BLOCKS = ("axis_a", "axis_b", "gate_decision")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _golden_paths() -> list[Path]:
    return sorted(_GOLDEN_DIR.glob("*.json"))


def _bon_paths() -> list[Path]:
    return sorted(_BON_PANEL_DIR.glob("*.json"))


# ---------- (a) every golden fixture validates against the schema -------


def test_golden_dir_covers_required_envelope_types():
    stems = {p.stem for p in _golden_paths()}
    for required in ("pm_supervisor", "flow", "tactical", "reversion"):
        assert required in stems, f"missing golden fixture for {required}"


@pytest.mark.parametrize("path", _golden_paths(), ids=lambda p: p.stem)
def test_golden_fixture_validates(path: Path):
    env = _load(path)
    validate = _GOLDEN_VALIDATORS.get(path.stem)
    assert validate is not None, f"no validator mapped for fixture {path.name}"
    result = validate(env)
    assert result.valid is True, result.to_result_dict()


# ---------- (b) bon_panel has exactly 10 schema-valid envelopes ---------


def test_bon_panel_has_exactly_ten():
    paths = _bon_paths()
    assert len(paths) == 10, f"bon_panel must hold exactly 10 envelopes, found {len(paths)}"


@pytest.mark.parametrize("path", _bon_paths(), ids=lambda p: p.stem)
def test_bon_panel_envelope_validates_as_pm_supervisor(path: Path):
    env = _load(path)
    result = pm_env.validate(env)
    assert result.valid is True, result.to_result_dict()


def test_bon_panel_is_diversified():
    envs = [_load(p) for p in _bon_paths()]
    # A baseline panel of carbon copies defeats the quality-lift comparison.
    assert len({e["ticker"] for e in envs}) >= 8
    assert {e["tier"] for e in envs} == {
        "core_fundamental",
        "thematic_growth",
        "speculative_optionality",
    }
    assert len({e["summary_code"] for e in envs}) >= 3


# ---------- (c) populated axis_a / axis_b / gate_decision present -------


def _all_fixture_paths() -> list[Path]:
    return _golden_paths() + _bon_paths()


@pytest.mark.parametrize(
    "path",
    _all_fixture_paths(),
    ids=lambda p: f"{p.parent.name}/{p.stem}",
)
def test_score_blocks_present_and_populated(path: Path):
    env = _load(path)
    for block in _SCORE_BLOCKS:
        assert block in env, f"{path.name}: missing {block}"
        value = env[block]
        assert value is not None, f"{path.name}: {block} is null"
        assert isinstance(value, dict) and value, (
            f"{path.name}: {block} must be a non-empty object"
        )
    # axis blocks must carry a real score number (not just a mode flag).
    assert isinstance(env["axis_a"].get("faithfulness"), (int, float))
    assert isinstance(env["axis_b"].get("roscoe"), (int, float))
    assert env["gate_decision"].get("verdict") in ("PASS", "ESCALATE", "FAIL")
