"""Trial-set assembly leaf (task 2.4 — ``fit.py``).

The DETERMINISTIC assembler of the walk-forward tuning cycle's **trial set**.
The *judgment* — which configs to explore (the §14.2 grid-search / optimizer
role) and the falsifiable hypothesis — is the orchestrator's LLM step
(`.claude/commands/walkforward-tune.md`); this leaf only validates the
LLM-proposed configs against their pinned shapes, applies the rolling
(edge/return) vs anchored (tail/risk) in-sample memory, and produces one
hashed, versioned consumed-``Candidate`` per config. It NEVER applies or selects
a fitted version at runtime (R3.5 — runtime application + in-session selection
are owned downstream by `execution-daemon` / `in-session-monitor`).

Contract (design §"fit (trial-set assembly)"):
    assemble_trial_set(proposed_configs, base, memory) -> TrialSet

Behavioral contract:
  * the trial set must be NON-TRIVIAL (>=2 configs) so the gate's DSR/PBO/MinBTL
    deflation is non-degenerate (R3.4 / R5.2-5.3); a <2 proposal is rejected
    (P7 fail-safe — refuse rather than emit a degenerate set the gate would
    spuriously pass);
  * reactive configs are validated against the LANDED ``ParamSnapshot`` shape;
    survival configs are validated STRUCTURALLY (a non-empty mapping) because
    ``src.survival`` is DESIGNED-not-landed and ``Candidate.survival_parameters``
    is typed ``Any`` (re-type this validation to the landed ``SurvivalParameters``
    when it lands — a revalidation trigger, R10.4);
  * rolling (reactive / edge-return) vs anchored (survival / tail-risk) in-sample
    memory is applied and recorded per config (R3.2);
  * each config gets a DETERMINISTIC, content-derived ``param_version`` (sha256
    of canonical JSON — mirrors ``src/reactive/daemon/params.py::hash_param_map``
    and ``run_parameters_snapshot.effective_parameters_hash``), so each candidate
    is identifiable and reproducible (R3.4). The version is stamped INTO the
    reactive ``ParamSnapshot.param_version`` (the version-carrying field; the
    consumed frozen ``Candidate`` itself has no ``param_version`` field).

Pure leaf (P1 / design §"File Structure Plan → Dependency direction"): stdlib
only + the dependency-root ``types`` barrier (which re-exports the consumed
``Candidate``) + the landed reactive ``ParamSnapshot``. NO other walkforward
leaf is imported; no DB, no MCP, no httpx, no LLM; no ``counterfactual_ledger``
read.

Requirements: 3.1, 3.2, 3.4, 3.5.
"""

from __future__ import annotations

import dataclasses as d
import hashlib
import json
from collections.abc import Mapping
from typing import Any

# The landed reactive parameter snapshot — the pinned shape a reactive config
# is validated against (design §Allowed Dependencies; R10.3 "consume ... the
# reactive parameter snapshot ... as the versioned objects it tunes").
from src.reactive.params import ParamSnapshot

# The dependency-root barrier (re-exports the consumed ``Candidate`` — object
# identity holds; no re-declaration). The only walkforward import allowed here.
from src.skills.walkforward_tune.types import Candidate, TrialSet

__all__ = ["assemble_trial_set"]


# The track vocabulary the orchestrator proposes configs under (v0.1 — a clean
# BINARY split per R3.2): "param" = the reactive edge/return snapshot, fit on
# ROLLING (recent-regime) memory; "survival" = the tail/risk parameters, fit on
# ANCHORED (all-history) memory. A combined ("both") track is deliberately NOT
# supported here — R3.2 mandates *distinct* memories per family, so a single
# config cannot honor both windows without dual-memory folding; that is deferred
# until ``src.survival`` lands (then re-introduce with both spans in the identity
# hash). Keeping the split binary avoids an untested branch that would window the
# survival portion on the wrong (rolling) memory.
_PARAM_TRACK = "param"
_SURVIVAL_TRACK = "survival"
_KNOWN_TRACKS = (_PARAM_TRACK, _SURVIVAL_TRACK)

# The minimum non-trivial trial-set size (R3.4 / R5.2-5.3): below this the
# gate's multiple-testing deflation (DSR/PBO over the trial set) is degenerate.
_MIN_TRIAL_SET = 2

# Which in-sample memory each track is fit on (R3.2, the provisional split):
# reactive edge/return -> ROLLING (recent-regime); survival tail/risk ->
# ANCHORED (all-history).
_TRACK_MEMORY = {
    _PARAM_TRACK: "rolling",
    _SURVIVAL_TRACK: "anchored",
}


def _canonical_hash(payload: dict[str, Any]) -> str:
    """sha256 of the canonical JSON of ``payload`` (sorted keys, tight separators).

    Mirrors ``src/reactive/daemon/params.py::hash_param_map`` and
    ``run_parameters_snapshot.effective_parameters_hash`` so the version is
    order-independent and any value change changes the hash. Deterministic:
    identical inputs -> identical digest.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _param_snapshot_payload(snapshot: ParamSnapshot) -> dict[str, Any]:
    """The content of a reactive ``ParamSnapshot`` that defines its identity.

    Excludes the existing ``param_version`` (we are MINTING a new one — including
    the old version would make the hash depend on the incumbent's label rather
    than the proposed VALUES) but includes the substantive knobs + ``weights`` +
    ``code_version`` so two configs differing by any knob hash distinctly (R3.4).
    """
    w = snapshot.weights
    return {
        "weights": {"w_trend": w.w_trend, "w_flow": w.w_flow, "w_meanrev": w.w_meanrev},
        "temperature": snapshot.temperature,
        "threshold": snapshot.threshold,
        "calibration": {
            "brier": snapshot.calibration.brier,
            "reliability": snapshot.calibration.reliability,
        },
        "code_version": snapshot.code_version,
    }


def _validate_track(config: Mapping[str, Any]) -> str:
    """Return the recognized track or raise ``ValueError`` on an unknown one."""
    track = config.get("track")
    if track not in _KNOWN_TRACKS:
        raise ValueError(
            f"unknown trial-config track {track!r}; expected one of {_KNOWN_TRACKS}"
        )
    return track


def _validate_reactive(config: Mapping[str, Any]) -> ParamSnapshot:
    """Validate the reactive payload against the PINNED ``ParamSnapshot`` shape.

    A reactive config must carry a real ``src.reactive.params.ParamSnapshot``
    instance (the landed, pinned shape) — a loose dict / missing payload is
    rejected (the "validate against the pinned shapes" obligation).
    """
    snapshot = config.get("param_snapshot")
    if snapshot is None:
        raise ValueError("reactive trial config is missing its 'param_snapshot' payload")
    if not isinstance(snapshot, ParamSnapshot):
        raise TypeError(
            "reactive trial config 'param_snapshot' must be a "
            f"src.reactive.params.ParamSnapshot, got {type(snapshot).__name__}"
        )
    return snapshot


def _validate_survival(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate the survival payload STRUCTURALLY (a non-empty mapping).

    ``src.survival`` is DESIGNED-not-landed, so ``Candidate.survival_parameters``
    is typed ``Any``; we cannot validate against a class that does not exist.
    The defensible pinned-shape check available is structural: a survival config
    must be a non-empty mapping (a None / scalar is rejected). Re-type this to
    the landed ``SurvivalParameters`` when survival lands (R10.4 revalidation).
    """
    survival = config.get("survival_parameters")
    if survival is None:
        raise ValueError("survival trial config is missing its 'survival_parameters' payload")
    if not isinstance(survival, Mapping) or len(survival) == 0:
        raise TypeError(
            "survival trial config 'survival_parameters' must be a non-empty "
            f"mapping (src.survival not yet landed), got {type(survival).__name__}"
        )
    return survival


def _memory_span(memory: Mapping[str, Any], window: str) -> Any:
    """The in-sample memory span for the named window ('rolling' | 'anchored')."""
    if window not in memory:
        raise ValueError(
            f"memory is missing the {window!r} in-sample window required by the "
            "rolling-vs-anchored split (R3.2)"
        )
    return memory[window]


def assemble_trial_set(
    proposed_configs: list[Mapping[str, Any]],
    base: Candidate,
    memory: Mapping[str, Any],
) -> TrialSet:
    """Assemble the validated, hashed, windowed trial set from LLM proposals.

    Parameters
    ----------
    proposed_configs:
        The orchestrator-proposed configs (the LLM judgment, already structured).
        Each is a mapping ``{"track": "param"|"survival"|"both", "param_snapshot":
        ParamSnapshot|None, "survival_parameters": Mapping|None}``.
    base:
        The incumbent ``Candidate`` the proposals are assembled against (the
        rolling/anchored memory + base versions the trial set departs from).
    memory:
        ``{"rolling": <span>, "anchored": <span>}`` — the rolling (edge/return)
        and anchored (tail/risk) in-sample memory spans (R3.2). The span objects
        are opaque to this leaf (the orchestrator defines them) but are folded
        into each config's content hash so windowing is part of the reproducible
        identity.

    Returns
    -------
    TrialSet
        ``candidates`` (>=2 consumed ``Candidate``s, each with a stamped
        content-derived ``param_version``) + ``trial_metadata`` (the windowing
        attribution + the trial count the gate deflates ``effective_n`` against).

    Raises
    ------
    ValueError / TypeError
        On a degenerate (<2) or empty proposal, an unknown/missing track, a
        shape-invalid reactive (non-``ParamSnapshot``) or survival (None/scalar)
        config, or a memory span missing the required window — fail-safe: refuse
        to assemble rather than emit a set the gate would spuriously deflate (P7).
    """
    if len(proposed_configs) < _MIN_TRIAL_SET:
        raise ValueError(
            f"trial set must be non-trivial (>={_MIN_TRIAL_SET} configs) so the "
            "gate's deflation is non-degenerate (R3.4/R5.2-5.3); got "
            f"{len(proposed_configs)}"
        )

    candidates: list[Candidate] = []
    windowing: list[dict[str, Any]] = []

    for config in proposed_configs:
        if not isinstance(config, Mapping):
            raise TypeError(
                f"each proposed config must be a mapping, got {type(config).__name__}"
            )
        track = _validate_track(config)
        window = _TRACK_MEMORY[track]
        span = _memory_span(memory, window)

        snapshot: ParamSnapshot | None = None
        survival: Mapping[str, Any] | None = None
        identity: dict[str, Any] = {"track": track, "memory": window, "span": span}

        if track == _PARAM_TRACK:
            snapshot = _validate_reactive(config)
            identity["param_snapshot"] = _param_snapshot_payload(snapshot)
        elif track == _SURVIVAL_TRACK:
            survival = _validate_survival(config)
            identity["survival_parameters"] = dict(survival)

        # Deterministic, content-derived version (R3.4): same inputs -> same
        # hash; any knob (or the windowing memory span) change -> a new hash.
        param_version = _canonical_hash(identity)

        # Stamp the minted version into the reactive snapshot's version-carrying
        # field. For a survival-only config the candidate carries no reactive
        # snapshot; the version threads through the windowing metadata instead
        # (the consumed frozen ``Candidate`` has no ``param_version`` field).
        stamped_snapshot = (
            d.replace(snapshot, param_version=param_version) if snapshot is not None else None
        )

        candidates.append(
            Candidate(
                param_snapshot=stamped_snapshot,
                survival_parameters=dict(survival) if survival is not None else None,
                code_version=None,
            )
        )
        windowing.append(
            {"track": track, "memory": window, "span": span, "param_version": param_version}
        )

    trial_metadata: dict[str, Any] = {
        "n_trials": len(candidates),
        "windowing": windowing,
        "base_param_version": (
            base.param_snapshot.param_version if base.param_snapshot is not None else None
        ),
    }
    return TrialSet(candidates=candidates, trial_metadata=trial_metadata)
