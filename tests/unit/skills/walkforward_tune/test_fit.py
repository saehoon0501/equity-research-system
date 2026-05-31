"""Pure-unit tests for the trial-set assembler (task 2.4 — ``fit.py``).

The ``fit`` leaf is the DETERMINISTIC assembler: the *judgment* (which configs
to explore, the falsifiable hypothesis) is the orchestrator's LLM step; this
leaf validates the LLM-proposed ``ParamSnapshot`` / ``SurvivalParameters``
configs against their pinned shapes, applies rolling (edge/return) vs anchored
(tail/risk) in-sample memory, and produces one hashed consumed-``Candidate``
per config with a stamped ``param_version`` (design §"fit (trial-set
assembly)"; tasks 2.4 / R3.1, 3.2, 3.4, 3.5).

These are the load-bearing observables (task 2.4 "Observable"):
  * produces a NON-TRIVIAL trial set (>=2 configs) so the gate's DSR/PBO
    deflation is non-degenerate (R3.4 / R5.2-5.3) — a <2 proposal is rejected;
  * rolling vs anchored windowing is APPLIED and observable (reactive = rolling
    recent-regime memory, survival = anchored all-history memory; R3.2);
  * SHAPE-INVALID configs are rejected (a non-``ParamSnapshot`` reactive config,
    a None/scalar survival config, an empty/trackless proposal);
  * the per-config hash is DETERMINISTIC (same inputs -> same ``param_version``;
    a value change -> a different hash) and is the consumed-``Candidate``'s
    version (R3.4 "hashed, versioned snapshot ... identifiable and reproducible").

The trial set's members are the IMPORTED ``src.reactive.replay.Candidate`` (no
re-declaration) carrying the landed ``src.reactive.params.ParamSnapshot`` — the
real shapes, not fakes (the unit-green/integration-broken trap class).

Pure leaf (P1 / P14 inner ring): stdlib only — no LLM, no MCP, no live DB.

Requirements: 3.1 (a trial SET / config search to deflate against), 3.2
(rolling reactive vs anchored survival memory), 3.4 (hashed versioned snapshot;
>=2 configs), 3.5 (never applies/selects at runtime — the leaf only assembles).
"""

from __future__ import annotations

import dataclasses as d

import pytest

# The consumed contract — IMPORTED, never re-declared (object identity asserted).
from src.reactive.params import DEFAULTS as REACTIVE_DEFAULTS, ParamSnapshot
from src.reactive.replay import Candidate as ReplayCandidate
from src.skills.walkforward_tune import fit as fit_mod
from src.skills.walkforward_tune.fit import assemble_trial_set
from src.skills.walkforward_tune.types import Candidate, TrialSet


# --------------------------------------------------------------------------- #
# Builders — real shapes only (no fakes; mirrors the harness-test convention). #
# --------------------------------------------------------------------------- #


def _param_snapshot(*, threshold: float = 0.60, temperature: float = 1.0) -> ParamSnapshot:
    """A real reactive ``ParamSnapshot`` differing from DEFAULTS by a knob."""
    return d.replace(REACTIVE_DEFAULTS, threshold=threshold, temperature=temperature)


def _survival_params(*, max_drawdown: float = 0.10) -> dict:
    """A structured survival-parameters config.

    ``src.survival`` is DESIGNED-not-landed, so ``Candidate.survival_parameters``
    is typed ``Any``; the assembler validates it STRUCTURALLY (a non-empty
    mapping), not against a not-yet-landed class — matching the spec's "validate
    against the pinned shapes" without over-asserting a shape that does not exist.
    """
    return {"max_drawdown": max_drawdown, "stop_atr_mult": 2.0}


def _memory() -> dict:
    """The rolling (edge/return) + anchored (tail/risk) in-sample memory (R3.2)."""
    return {
        "rolling": {"start": "2024-09-01", "end": "2024-12-31"},   # recent regime
        "anchored": {"start": "2003-09-10", "end": "2024-12-31"},  # all history
    }


def _param_config(threshold: float) -> dict:
    return {"track": "param", "param_snapshot": _param_snapshot(threshold=threshold)}


def _survival_config(max_drawdown: float) -> dict:
    return {"track": "survival", "survival_parameters": _survival_params(max_drawdown=max_drawdown)}


def _base() -> Candidate:
    """The incumbent candidate the proposals are assembled against."""
    return ReplayCandidate(param_snapshot=REACTIVE_DEFAULTS, survival_parameters=None, code_version=None)


def _two_param_configs() -> list[dict]:
    return [_param_config(0.58), _param_config(0.62)]


# --------------------------------------------------------------------------- #
# Non-trivial trial set (>=2 configs) — R3.4 / R5.2-5.3.                       #
# --------------------------------------------------------------------------- #


def test_assembles_nontrivial_trial_set() -> None:
    """Two valid param configs -> a ``TrialSet`` of exactly two ``Candidate``s."""
    ts = assemble_trial_set(_two_param_configs(), base=_base(), memory=_memory())
    assert isinstance(ts, TrialSet)
    assert len(ts.candidates) == 2


def test_trial_set_members_are_the_consumed_candidate() -> None:
    """The members are the IMPORTED ``src.reactive.replay.Candidate`` (no
    re-declaration) carrying the landed ``ParamSnapshot`` — object identity, not
    a structural look-alike (the harness↔tuner seam)."""
    ts = assemble_trial_set(_two_param_configs(), base=_base(), memory=_memory())
    assert Candidate is ReplayCandidate  # the barrier re-exports the consumed type
    for c in ts.candidates:
        assert isinstance(c, ReplayCandidate)
        assert isinstance(c.param_snapshot, ParamSnapshot)


def test_single_config_proposal_is_rejected_as_degenerate() -> None:
    """A trial set with <2 configs is rejected (the gate's deflation would be
    degenerate — R5.2/5.3; P7 fail-safe: refuse rather than emit a degenerate
    set)."""
    with pytest.raises(ValueError):
        assemble_trial_set([_param_config(0.60)], base=_base(), memory=_memory())


def test_empty_proposal_is_rejected() -> None:
    with pytest.raises(ValueError):
        assemble_trial_set([], base=_base(), memory=_memory())


# --------------------------------------------------------------------------- #
# Rolling (reactive) vs anchored (survival) windowing — R3.2.                  #
# --------------------------------------------------------------------------- #


def test_rolling_vs_anchored_windowing_applied() -> None:
    """A reactive (param) config is windowed on ROLLING memory; a survival
    config on ANCHORED memory — the split is observable in ``trial_metadata``
    (R3.2 the provisional rolling/anchored split)."""
    configs = [_param_config(0.58), _survival_config(0.12)]
    ts = assemble_trial_set(configs, base=_base(), memory=_memory())
    wins = ts.trial_metadata["windowing"]
    # Each config carries the memory window its track was fit on.
    by_track = {w["track"]: w["memory"] for w in wins}
    assert by_track["param"] == "rolling"
    assert by_track["survival"] == "anchored"


def test_windowing_threads_the_actual_memory_span() -> None:
    """The rolling/anchored span recorded is the one passed in ``memory`` — not a
    hardcoded constant (so a different memory yields different attribution)."""
    mem = _memory()
    ts = assemble_trial_set([_param_config(0.58), _survival_config(0.12)], base=_base(), memory=mem)
    wins = {w["track"]: w["span"] for w in ts.trial_metadata["windowing"]}
    assert wins["param"] == mem["rolling"]
    assert wins["survival"] == mem["anchored"]


def test_survival_only_candidate_carries_no_reactive_snapshot_but_a_version() -> None:
    """A survival-only config produces a ``Candidate`` with ``survival_parameters``
    set and NO reactive ``param_snapshot``; its content-derived version threads
    through ``trial_metadata['windowing']`` (the consumed frozen ``Candidate`` has
    no ``param_version`` field, so the version lives in the metadata for that
    track)."""
    ts = assemble_trial_set([_survival_config(0.10), _survival_config(0.12)], base=_base(), memory=_memory())
    for c in ts.candidates:
        assert c.param_snapshot is None
        assert isinstance(c.survival_parameters, dict)
    versions = {w["param_version"] for w in ts.trial_metadata["windowing"]}
    assert all(v for v in versions)        # non-empty
    assert len(versions) == 2              # distinct survival configs -> distinct versions


def test_both_track_is_not_supported() -> None:
    """v0.1 keeps the split BINARY: a combined 'both' track is rejected (R3.2
    mandates distinct rolling/anchored memories a single config cannot honor)."""
    both = {"track": "both", "param_snapshot": _param_snapshot(), "survival_parameters": _survival_params()}
    with pytest.raises(ValueError):
        assemble_trial_set([both, _param_config(0.62)], base=_base(), memory=_memory())


# --------------------------------------------------------------------------- #
# Shape-invalid configs rejected — "validate against the pinned shapes".       #
# --------------------------------------------------------------------------- #


def test_rejects_non_paramsnapshot_reactive_config() -> None:
    """A reactive config whose ``param_snapshot`` is not a ``ParamSnapshot``
    (here a loose dict) is rejected — the pinned-shape check."""
    bad = {"track": "param", "param_snapshot": {"threshold": 0.6}}
    with pytest.raises((TypeError, ValueError)):
        assemble_trial_set([bad, _param_config(0.62)], base=_base(), memory=_memory())


def test_rejects_scalar_survival_config() -> None:
    """A survival config that is a scalar (not a structured mapping) is rejected
    structurally (``src.survival`` is not landed, so the check is structural)."""
    bad = {"track": "survival", "survival_parameters": 0.10}
    with pytest.raises((TypeError, ValueError)):
        assemble_trial_set([bad, _survival_config(0.11)], base=_base(), memory=_memory())


def test_rejects_none_survival_config() -> None:
    bad = {"track": "survival", "survival_parameters": None}
    with pytest.raises((TypeError, ValueError)):
        assemble_trial_set([bad, _survival_config(0.11)], base=_base(), memory=_memory())


def test_rejects_trackless_config() -> None:
    """A proposal with no recognized track (neither param nor survival) is
    rejected — the assembler cannot window or hash a trackless config."""
    bad = {"track": "param"}  # 'param' track but no param_snapshot payload
    with pytest.raises((TypeError, ValueError, KeyError)):
        assemble_trial_set([bad, _param_config(0.62)], base=_base(), memory=_memory())


def test_rejects_unknown_track() -> None:
    bad = {"track": "voodoo", "param_snapshot": _param_snapshot()}
    with pytest.raises(ValueError):
        assemble_trial_set([bad, _param_config(0.62)], base=_base(), memory=_memory())


# --------------------------------------------------------------------------- #
# Deterministic per-config hash / param_version — R3.4.                        #
# --------------------------------------------------------------------------- #


def test_per_config_hash_is_stamped_as_param_version() -> None:
    """Each reactive ``Candidate`` carries a stamped, content-derived
    ``param_version`` (the "hashed, versioned snapshot" — R3.4); it is NOT the
    base default version."""
    ts = assemble_trial_set(_two_param_configs(), base=_base(), memory=_memory())
    for c in ts.candidates:
        assert c.param_snapshot.param_version != ""
        assert c.param_snapshot.param_version != REACTIVE_DEFAULTS.param_version


def test_hash_is_deterministic_across_calls() -> None:
    """Identical inputs -> identical per-config ``param_version`` (the
    determinism contract; a reproducible snapshot, R3.4)."""
    ts1 = assemble_trial_set(_two_param_configs(), base=_base(), memory=_memory())
    ts2 = assemble_trial_set(_two_param_configs(), base=_base(), memory=_memory())
    v1 = [c.param_snapshot.param_version for c in ts1.candidates]
    v2 = [c.param_snapshot.param_version for c in ts2.candidates]
    assert v1 == v2


def test_distinct_configs_hash_distinctly() -> None:
    """Two configs that differ by a knob value get different ``param_version``s
    (so each candidate is individually identifiable, R3.4)."""
    ts = assemble_trial_set([_param_config(0.58), _param_config(0.62)], base=_base(), memory=_memory())
    versions = {c.param_snapshot.param_version for c in ts.candidates}
    assert len(versions) == 2


def test_a_value_change_changes_the_hash() -> None:
    """Changing a knob changes the content hash (no collision / no stale reuse)."""
    ts_a = assemble_trial_set([_param_config(0.58), _param_config(0.62)], base=_base(), memory=_memory())
    ts_b = assemble_trial_set([_param_config(0.59), _param_config(0.62)], base=_base(), memory=_memory())
    # The first config differs by threshold; its version must change.
    va = ts_a.candidates[0].param_snapshot.param_version
    vb = ts_b.candidates[0].param_snapshot.param_version
    assert va != vb


def test_hash_depends_on_windowing_memory() -> None:
    """The per-config version is content-derived including the memory span it was
    fit on — a different rolling memory yields a different version (so the
    windowing is part of the candidate's reproducible identity, R3.2 + R3.4)."""
    mem_a = _memory()
    mem_b = {**_memory(), "rolling": {"start": "2024-06-01", "end": "2024-12-31"}}
    va = assemble_trial_set([_param_config(0.58), _param_config(0.62)], base=_base(), memory=mem_a).candidates[0].param_snapshot.param_version
    vb = assemble_trial_set([_param_config(0.58), _param_config(0.62)], base=_base(), memory=mem_b).candidates[0].param_snapshot.param_version
    assert va != vb


# --------------------------------------------------------------------------- #
# Trial metadata for effective_N — R5.2/5.3 (what the gate deflates against).  #
# --------------------------------------------------------------------------- #


def test_trial_metadata_carries_trial_count() -> None:
    """``trial_metadata`` records the trial count the gate deflates ``effective_n``
    against (R5.2/5.3 — the search breadth)."""
    ts = assemble_trial_set(_two_param_configs(), base=_base(), memory=_memory())
    assert ts.trial_metadata["n_trials"] == 2


# --------------------------------------------------------------------------- #
# Purity — no I/O, no LLM, no DB at module level.                              #
# --------------------------------------------------------------------------- #


def test_module_is_pure_stdlib() -> None:
    """The leaf imports no DB / MCP / httpx (pure leaf, P1). It may import the
    consumed contract + the barrier ``types`` — but no other walkforward leaf."""
    import inspect

    src = inspect.getsource(fit_mod)
    # Forbid actual I/O imports / a ledger READ — not a docstring MENTION of the
    # boundary (the leaf documents that it does NOT read the ledger).
    forbidden = ("import psycopg", "import httpx", "mcp__", "FROM counterfactual_ledger")
    for token in forbidden:
        assert token not in src, f"fit.py must not reference {token!r}"
    # No other walkforward leaf is imported (strict left->right dependency).
    for leaf in ("read", "cpcv", "metric", "gate", "publish", "audit"):
        assert f"walkforward_tune.{leaf}" not in src, f"fit.py must not import the {leaf} leaf"
