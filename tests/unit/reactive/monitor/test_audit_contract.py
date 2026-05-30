"""Golden-shape CONTRACT test for the In-Session Monitor intervention-audit envelope.

Task 6.1 (in-session-monitor). The inner-ring (P14) richer-than-presence companion
to the HG-39 ``intervention_audit_shape`` validator (which is presence-only by
design, P13). It asserts the FULL ``InterventionAudit`` envelope shape from a
CANONICAL ``emit_audit`` emit — value/enum/structure assertions the presence-only
gate deliberately does NOT make — so a silent audit-shape regression (a dropped
correlation key, a flipped Phase-1 advisory flag, an empty falsifiers list, an
enum drift) is caught here in <1s with no LLM / no MCP / no live DB.

Requirements: 7.1 (the audit is emitted with the advisory ``applied`` signal),
7.4 (the audit owns the falsifiable *why*, separate from the model trace), 9.5
(inner-ring contract coverage richer than HG presence-only, the refactor tripwire).

Key load-bearing observation this test pins (P12 / P13): ``emit_audit`` serializes
via ``dataclasses.asdict``, so the four correlation keys land NESTED under
``envelope["keys"]`` (``envelope["keys"]["run_id"]`` ...), NOT at the top level —
exactly as the ``InterventionAudit`` data model specifies (``keys: CorrelationKeys``).
The HG-39 ``validate_intervention_audit_shape`` validator reads them there (the
``keys`` block is a required top-level block; the four keys are its required
sub-keys), so the real emitter envelope validates DIRECTLY — no flattening.
(This P14 contract test originally surfaced a nested-vs-flat divergence where HG-39
checked the keys at the top level; that was fixed by aligning the validator to the
nested data-model shape.)

Pure leaf (P1): stdlib + own-layer ``types`` / ``audit`` + the HG validator only.
``conn=None`` is the DRY-RUN that returns the serialized would-be envelope and
writes NOTHING to disk — so this test needs no tmp dir and touches no filesystem.
"""

from __future__ import annotations

import copy

import pytest

from src.eval.gates.intervention_audit_shape import (
    CORRELATION_KEYS,
    validate_intervention_audit_shape,
)
from src.reactive.monitor import InterventionAudit
from src.reactive.monitor.audit import emit_audit
from src.reactive.monitor.types import EnvelopeState, InterventionIntent
from src.reactive.telemetry import CorrelationKeys


# --- Canonical emit (mirrors tests/unit/reactive/monitor/test_audit.py) -----


def _keys() -> CorrelationKeys:
    """The four daemon-epoch correlation keys of the single analyzed version
    (R7.3) — read off the analyzed trace by the diagnostic, carried typed."""
    return CorrelationKeys(
        run_id="run-abc-123",
        code_version="c7",
        param_version="p3",
        walk_forward_window="2026Q1",
    )


def _audit(
    keys: CorrelationKeys | None = None,
    verdict: str = "DRIFTED",
    intervention_intent: str = "HALT_NEW_ENTRIES",
    applied: bool = False,
    command_ref: str | None = None,
    operator_action_required: str | None = None,
) -> InterventionAudit:
    """A falsifiable `InterventionAudit` (P15): rationale is a structured
    `{hypothesis, falsifiers: list[str]}`, the trigger is a derived diagnostic
    (metric / observed / threshold / window_n — never an asserted probability)."""
    return InterventionAudit(
        keys=keys if keys is not None else _keys(),
        trigger_diagnostic={
            "metric": "brier",
            "observed": 0.31,
            "threshold": 0.18,
            "window_n": 64,
        },
        verdict=verdict,
        intervention_intent=intervention_intent,
        operator_action_required=operator_action_required,
        rationale={
            "hypothesis": "softmax calibration has broken down inside survival limits",
            "falsifiers": [
                "next-window Brier returns within the pinned baseline CI",
                "reliability slope recovers toward 1.0 over W closed decisions",
            ],
        },
        applied=applied,
        command_ref=command_ref,
        event_ts="2026-05-30T14:05:00Z",
    )


def _canonical_envelope(**kwargs) -> dict:
    """The serialized would-be envelope from a CANONICAL `emit_audit` DRY-RUN.

    `conn=None` ⟹ DRY-RUN: returns the serialized envelope dict, writes NOTHING.
    This is the real on-disk shape (`asdict`), so every assertion below is pinned
    against the emitter's actual output, not a hand-built dict.
    """
    return emit_audit(_audit(**kwargs), conn=None)


# --- Presence half: reuse the HG-39 validator (P14: complement, don't replace) --


def test_presence_half_canonical_envelope_passes_hg_validator() -> None:
    """The canonical emitter envelope passes the presence-only HG-39 gate
    DIRECTLY (no flattening): HG-39 reads the four correlation keys nested under
    the ``keys`` block, matching emit_audit's data-model shape. Reuses
    `validate_intervention_audit_shape` for the presence half (P14: complement,
    don't replace)."""
    env = _canonical_envelope()
    result = validate_intervention_audit_shape(env)
    assert result.valid is True
    assert result.missing_top_level == []
    assert result.missing_subkeys == {}


def test_raw_emitter_envelope_nests_keys_under_keys_block() -> None:
    """Pin the canonical nested-keys structure (P12 / data model).

    The four correlation keys are NOT at the top level of the emitter envelope;
    they ride nested under `["keys"]` (``keys: CorrelationKeys``). HG-39 reads them
    there. Pinned so a future flatten of `emit_audit` (which would desync the
    emitter from the validator + the data model) trips this test."""
    env = _canonical_envelope()
    for key in CORRELATION_KEYS:
        assert key not in env, f"{key} unexpectedly hoisted to envelope top level"
        assert key in env["keys"]


# --- Richer half #1: all four correlation keys present + correct (R7.3) ------


def test_all_four_correlation_keys_present_under_keys_block() -> None:
    """All FOUR correlation keys present (and carrying the analyzed version's
    values) under `keys` — the join surface to the model trace + ledger."""
    env = _canonical_envelope()
    keys_block = env["keys"]
    assert set(CORRELATION_KEYS) <= set(keys_block), (
        "envelope keys block missing one of the four correlation keys"
    )
    assert keys_block["run_id"] == "run-abc-123"
    assert keys_block["code_version"] == "c7"
    assert keys_block["param_version"] == "p3"
    assert keys_block["walk_forward_window"] == "2026Q1"


# --- Richer half #2: Phase-1 advisory applied-flag semantics (R7.1) ----------


def test_phase1_advisory_applied_flag_semantics() -> None:
    """Phase-1 advisory: `applied is False` AND `command_ref is None` together.

    These two are the unmistakable "NO ACTION TAKEN" advisory signal (Issue 2);
    a richer-than-presence assertion the HG gate (which only checks the KEY is
    present) does not make. Identity (`is`) is deliberate — a truthy non-bool or
    a non-null command_ref must fail."""
    env = _canonical_envelope(applied=False, command_ref=None)
    assert env["applied"] is False
    assert env["command_ref"] is None


# --- Richer half #3: falsifiable rationale block (P15 / R7.2 / R7.4) ----------


def test_rationale_carries_hypothesis_and_nonempty_falsifiers() -> None:
    """The rationale is a falsifiable block: a non-empty `hypothesis` plus a
    NON-EMPTY list of string `falsifiers` (P15 — a hypothesis alone is not
    falsifiable). HG-39 only checks `falsifiers` is present-non-empty; this also
    pins it is a list of non-empty strings and the hypothesis is present."""
    env = _canonical_envelope()
    rationale = env["rationale"]
    assert isinstance(rationale, dict)

    assert isinstance(rationale.get("hypothesis"), str)
    assert rationale["hypothesis"].strip(), "hypothesis must be non-empty"

    falsifiers = rationale.get("falsifiers")
    assert isinstance(falsifiers, list)
    assert len(falsifiers) >= 1, "falsifiers must be a non-empty list (P15)"
    assert all(isinstance(f, str) and f.strip() for f in falsifiers), (
        "every falsifier must be a non-empty string"
    )


# --- Richer half #4: verdict / intent ENUM membership (P9) -------------------


def test_verdict_is_envelope_state_enum_member() -> None:
    """`verdict` is a member of the `EnvelopeState` vocabulary (derived from the
    real enum, never a hardcoded string set — catches enum drift, P9)."""
    env = _canonical_envelope()
    assert env["verdict"] in {s.value for s in EnvelopeState}
    assert {s.value for s in EnvelopeState} == {
        "IN_ENVELOPE",
        "DRIFTED",
        "INSUFFICIENT",
    }


def test_intervention_intent_is_intervention_intent_enum_member() -> None:
    """`intervention_intent` is a member of `InterventionIntent` — and the
    vocabulary is EXACTLY the four members (a fifth would mint authority the
    operator never granted; types.py docstring contract)."""
    env = _canonical_envelope()
    assert env["intervention_intent"] in {i.value for i in InterventionIntent}
    assert len(InterventionIntent) == 4
    assert {i.value for i in InterventionIntent} == {
        "NONE",
        "HALT_NEW_ENTRIES",
        "TIGHTEN_SAFE_MODE",
        "SELECT_SAFER_CONFIG",
    }


@pytest.mark.parametrize(
    "verdict,intent",
    [
        ("IN_ENVELOPE", "NONE"),
        ("DRIFTED", "TIGHTEN_SAFE_MODE"),
        ("DRIFTED", "SELECT_SAFER_CONFIG"),
        ("INSUFFICIENT", "NONE"),
    ],
)
def test_enum_membership_holds_across_canonical_combos(verdict: str, intent: str) -> None:
    """Enum membership holds for the canonical verdict/intent combinations the
    judge → intervene chain produces — not just the single default fixture."""
    env = _canonical_envelope(verdict=verdict, intervention_intent=intent)
    assert env["verdict"] in {s.value for s in EnvelopeState}
    assert env["intervention_intent"] in {i.value for i in InterventionIntent}


# --- The tripwire: drop a required block/key ⟹ the contract REJECTS it -------


@pytest.mark.parametrize("dropped_key", list(CORRELATION_KEYS))
def test_dropping_a_correlation_key_fails_presence_check(dropped_key: str) -> None:
    """TRIPWIRE: drop ANY one correlation key from the nested ``keys`` block and
    HG-39 must REJECT it, naming the missing key under missing_subkeys["keys"].

    This is the refactor-regression guard: if a future `emit_audit` change drops
    a correlation key, this fails — the contract is not satisfiable by an envelope
    missing a join key."""
    env = _canonical_envelope()
    del env["keys"][dropped_key]
    result = validate_intervention_audit_shape(env)
    assert result.valid is False
    assert dropped_key in result.missing_subkeys["keys"]


@pytest.mark.parametrize("dropped_key", ["trigger_diagnostic", "verdict", "rationale", "event_ts"])
def test_dropping_a_required_top_level_block_fails_presence_check(dropped_key: str) -> None:
    """TRIPWIRE: drop a required top-level block (trigger / verdict / rationale /
    event_ts) and the presence check rejects it, naming the missing block."""
    env = _canonical_envelope()
    del env[dropped_key]
    result = validate_intervention_audit_shape(env)
    assert result.valid is False
    assert dropped_key in result.missing_top_level


def test_dropping_falsifiers_subkey_fails_presence_check() -> None:
    """TRIPWIRE: drop the `rationale.falsifiers` sub-key and the presence check
    rejects it (a rationale without falsifiers is not falsifiable, P15)."""
    env = _canonical_envelope()
    del env["rationale"]["falsifiers"]
    result = validate_intervention_audit_shape(env)
    assert result.valid is False
    assert "rationale" in result.missing_subkeys
    assert "falsifiers" in result.missing_subkeys["rationale"]


def test_emptying_falsifiers_list_fails_richer_check() -> None:
    """TRIPWIRE (richer than presence): an EMPTY falsifiers list must fail —
    HG-39's presence check already rejects empties, and the richer non-empty
    assertion above depends on it. Pinned via the validator's empty-rejection."""
    env = _canonical_envelope()
    env["rationale"]["falsifiers"] = []
    result = validate_intervention_audit_shape(env)
    assert result.valid is False
    assert result.missing_subkeys.get("rationale") == ["falsifiers"]


def test_non_member_verdict_fails_enum_check() -> None:
    """TRIPWIRE (richer than presence): a verdict OUTSIDE the EnvelopeState
    vocabulary is present-non-empty (HG-39 passes it) but must FAIL the enum
    membership check this contract adds — the value-correctness gap P13 names."""
    env = _canonical_envelope()
    env["verdict"] = "WOBBLY"  # present + non-empty, but not an EnvelopeState
    # HG-39 (presence-only) still passes the envelope ...
    assert validate_intervention_audit_shape(env).valid is True
    # ... but the richer enum assertion this contract makes rejects it.
    assert env["verdict"] not in {s.value for s in EnvelopeState}


def test_canonical_fixture_is_not_mutated_by_tripwires() -> None:
    """Sanity: each tripwire mutates its OWN envelope copy — a freshly emitted
    canonical envelope is still fully valid (no shared-state leakage)."""
    env = _canonical_envelope()
    untouched = copy.deepcopy(env)
    assert validate_intervention_audit_shape(untouched).valid is True
    assert env == untouched
