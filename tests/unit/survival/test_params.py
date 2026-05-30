"""Task 1.2 — observable proof for ``src.survival.params``.

Proves the task-1.2 observable:

  * :data:`DEFAULTS` instantiates with every field present, ``safe_mode_buffer_pct``
    strictly above ``stop_out_level_pct`` (R1.3), ``speculative_sleeve_cap_pct == 8.0``
    (R3.1), and ``stop_out_level_pct <= 50`` (R1.2).
  * :func:`resolve` builds a :class:`SurvivalParameters` from a pinned ``survival.*``
    snapshot **by value** (R10.1/R10.2) and **fails closed** on malformed input
    (missing key, wrong type, NaN, bool-for-float) — no silent defaulting.
  * :func:`tighten_only` rejects a loosening override (retains the pinned value)
    and applies a tightening override, for **each** of the 7 survival fields, in
    **both** directions (R10.4 / R2.5). A flipped tighten direction must fail the
    suite.

Pure unit test — no LLM / MCP / DB (P14, R11.2). This is a minimal observable
proof; the dedicated, exhaustive param tests are task 5.1.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import math
import pathlib
import sys

import pytest


# --------------------------------------------------------------------------- #
# Helpers.                                                                     #
# --------------------------------------------------------------------------- #

def _params_module():
    return importlib.import_module("src.survival.params")


def _valid_snapshot():
    """A well-formed pinned snapshot covering all 9 fields."""
    return {
        "survival.stop_out_level_pct": 50.0,
        "survival.safe_mode_buffer_pct": 100.0,
        "survival.per_order_size_max": 5.0,
        "survival.speculative_sleeve_cap_pct": 8.0,
        "survival.flatten_lead_seconds": 300.0,
        "survival.assess_max_latency_seconds": 5.0,
        "survival.exclusion_enabled": True,
        "code_version": "abc123",
        "param_version": "v1",
    }


# --------------------------------------------------------------------------- #
# DEFAULTS — every field present + invariants.                                 #
# --------------------------------------------------------------------------- #

def test_defaults_is_frozen_survival_parameters():
    m = _params_module()
    assert isinstance(m.DEFAULTS, m.SurvivalParameters)
    assert dataclasses.is_dataclass(m.DEFAULTS)
    params = dataclasses.fields(m.SurvivalParameters)
    # frozen dataclass: cannot mutate.
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.DEFAULTS.stop_out_level_pct = 1.0  # type: ignore[misc]
    assert {f.name for f in params} == {
        "stop_out_level_pct",
        "safe_mode_buffer_pct",
        "per_order_size_max",
        "speculative_sleeve_cap_pct",
        "flatten_lead_seconds",
        "assess_max_latency_seconds",
        "exclusion_enabled",
        "code_version",
        "param_version",
    }


def test_defaults_every_field_present_and_typed():
    m = _params_module()
    d = m.DEFAULTS
    assert isinstance(d.stop_out_level_pct, float)
    assert isinstance(d.safe_mode_buffer_pct, float)
    assert isinstance(d.per_order_size_max, float)
    assert isinstance(d.speculative_sleeve_cap_pct, float)
    assert isinstance(d.flatten_lead_seconds, float)
    assert isinstance(d.assess_max_latency_seconds, float)
    assert isinstance(d.exclusion_enabled, bool)
    assert isinstance(d.code_version, str) and d.code_version
    assert isinstance(d.param_version, str) and d.param_version


def test_defaults_invariants():
    m = _params_module()
    d = m.DEFAULTS
    # R1.3: safe-mode buffer strictly above the stop-out (higher margin = safer).
    assert d.safe_mode_buffer_pct > d.stop_out_level_pct
    # R3.1: funding cap = 8.0.
    assert d.speculative_sleeve_cap_pct == 8.0
    # R1.2: stop-out level <= 50.
    assert d.stop_out_level_pct <= 50.0


# --------------------------------------------------------------------------- #
# resolve — by value + fail closed.                                           #
# --------------------------------------------------------------------------- #

def test_resolve_maps_snapshot_by_value():
    m = _params_module()
    snap = _valid_snapshot()
    p = m.resolve(snap)
    assert isinstance(p, m.SurvivalParameters)
    assert p.stop_out_level_pct == 50.0
    assert p.safe_mode_buffer_pct == 100.0
    assert p.per_order_size_max == 5.0
    assert p.speculative_sleeve_cap_pct == 8.0
    assert p.flatten_lead_seconds == 300.0
    assert p.assess_max_latency_seconds == 5.0
    assert p.exclusion_enabled is True
    assert p.code_version == "abc123"
    assert p.param_version == "v1"


def test_resolve_is_by_value_not_a_reference():
    # Mutating the source dict after resolve must not change the resolved object.
    m = _params_module()
    snap = _valid_snapshot()
    p = m.resolve(snap)
    snap["survival.stop_out_level_pct"] = 1.0
    assert p.stop_out_level_pct == 50.0


def test_resolve_fails_closed_on_missing_key():
    m = _params_module()
    snap = _valid_snapshot()
    del snap["survival.assess_max_latency_seconds"]
    with pytest.raises((KeyError, ValueError)):
        m.resolve(snap)


def test_resolve_fails_closed_on_wrong_type():
    m = _params_module()
    snap = _valid_snapshot()
    snap["survival.stop_out_level_pct"] = "50"
    with pytest.raises((TypeError, ValueError)):
        m.resolve(snap)


def test_resolve_fails_closed_on_nan():
    m = _params_module()
    snap = _valid_snapshot()
    snap["survival.stop_out_level_pct"] = math.nan
    with pytest.raises(ValueError):
        m.resolve(snap)


def test_resolve_fails_closed_on_bool_for_float():
    # bool is an int subclass; True must not slip into a float field.
    m = _params_module()
    snap = _valid_snapshot()
    snap["survival.per_order_size_max"] = True
    with pytest.raises((TypeError, ValueError)):
        m.resolve(snap)


def test_resolve_fails_closed_on_non_bool_for_exclusion():
    m = _params_module()
    snap = _valid_snapshot()
    snap["survival.exclusion_enabled"] = 1
    with pytest.raises((TypeError, ValueError)):
        m.resolve(snap)


# --------------------------------------------------------------------------- #
# tighten_only — per-field, both directions.                                   #
# --------------------------------------------------------------------------- #
# For each field the table is (field, loosen_value, tighten_value) relative to
# the pinned baseline. TIGHTEN = more survival-conservative.

_PINNED_BASE = {
    "stop_out_level_pct": 40.0,
    "safe_mode_buffer_pct": 80.0,
    "per_order_size_max": 5.0,
    "speculative_sleeve_cap_pct": 8.0,
    "flatten_lead_seconds": 300.0,
    "assess_max_latency_seconds": 5.0,
    "exclusion_enabled": False,
    "code_version": "base-code",
    "param_version": "base-param",
}

# (field, loosen_override_value, tighten_override_value)
_DIRECTION_CASES = [
    # stop_out_level_pct: TIGHTEN = higher (liquidate-threshold rises → safer).
    ("stop_out_level_pct", 30.0, 45.0),
    # safe_mode_buffer_pct: TIGHTEN = higher (enter safe-mode sooner).
    ("safe_mode_buffer_pct", 70.0, 90.0),
    # per_order_size_max: TIGHTEN = lower (smaller max order).
    ("per_order_size_max", 9.0, 2.0),
    # speculative_sleeve_cap_pct: TIGHTEN = lower (smaller funding cap).
    ("speculative_sleeve_cap_pct", 12.0, 4.0),
    # flatten_lead_seconds: TIGHTEN = higher (flatten earlier before close).
    ("flatten_lead_seconds", 120.0, 600.0),
    # assess_max_latency_seconds: TIGHTEN = lower (check more frequently).
    ("assess_max_latency_seconds", 10.0, 2.0),
    # exclusion_enabled: TIGHTEN = enable (False → True).
    ("exclusion_enabled", False, True),
]


def _pinned():
    m = _params_module()
    return m.SurvivalParameters(**_PINNED_BASE)


@pytest.mark.parametrize("fieldname,loosen,tighten", _DIRECTION_CASES)
def test_tighten_only_loosening_override_is_rejected(fieldname, loosen, tighten):
    m = _params_module()
    pinned = _pinned()
    result = m.tighten_only(pinned, {fieldname: loosen})
    # Loosening rejected → pinned value retained unchanged.
    assert getattr(result, fieldname) == _PINNED_BASE[fieldname], (
        f"{fieldname}: a loosening override ({loosen}) must retain the pinned "
        f"value ({_PINNED_BASE[fieldname]})"
    )


@pytest.mark.parametrize("fieldname,loosen,tighten", _DIRECTION_CASES)
def test_tighten_only_tightening_override_is_applied(fieldname, loosen, tighten):
    m = _params_module()
    pinned = _pinned()
    result = m.tighten_only(pinned, {fieldname: tighten})
    # Tightening applied → tighter value returned.
    assert getattr(result, fieldname) == tighten, (
        f"{fieldname}: a tightening override ({tighten}) must be applied"
    )


def test_tighten_only_disabling_exclusion_is_rejected():
    # The parametrized exclusion_enabled loosen case is False→False (a no-op).
    # The GENUINE boolean loosen is True→False (disabling the ex-ante exclusion
    # stage); it must be rejected and the pinned True retained (R10.4 / R2.5).
    # This is the only loosen branch the (False, True) parametrize cannot reach.
    m = _params_module()
    pinned = m.SurvivalParameters(**{**_PINNED_BASE, "exclusion_enabled": True})
    result = m.tighten_only(pinned, {"exclusion_enabled": False})
    assert result.exclusion_enabled is True


def test_tighten_only_returns_new_frozen_instance_leaving_pinned_unchanged():
    m = _params_module()
    pinned = _pinned()
    result = m.tighten_only(pinned, {"per_order_size_max": 2.0})
    assert result is not pinned
    assert pinned.per_order_size_max == 5.0  # pinned untouched
    assert result.per_order_size_max == 2.0


def test_tighten_only_empty_override_is_identity():
    m = _params_module()
    pinned = _pinned()
    result = m.tighten_only(pinned, {})
    assert result == pinned


def test_tighten_only_version_fields_carry_pinned_through():
    # code_version / param_version are identity metadata, not numerically
    # tightenable; an override touching them is ignored, pinned carried through.
    m = _params_module()
    pinned = _pinned()
    result = m.tighten_only(
        pinned, {"code_version": "evil", "param_version": "evil"}
    )
    assert result.code_version == "base-code"
    assert result.param_version == "base-param"


# --------------------------------------------------------------------------- #
# tighten_only — malformed override must NEVER loosen (R2.5 / R10.4).          #
# --------------------------------------------------------------------------- #
# `tighten_only` (unlike `resolve`) does not type/finiteness-validate its
# override values. The binding survival invariant is R2.5: a runtime adjustment
# is applied ONLY when it tightens; it must NEVER loosen a survival constraint.
# These tests assert the requirement-level property — the resolved value is never
# *looser* than the pinned value — for malformed input. They deliberately do NOT
# assert that a non-finite override is applied verbatim (that would enshrine
# arguably-buggy behavior; see the module concern on the resolve/tighten_only
# validation asymmetry). The direction is encoded LOCALLY below so the test is
# not circular with the module's own `_TIGHTENS` table.

# field -> "higher" if a higher value is the tighter (more conservative) one,
# else "lower". Derived independently from the design table, NOT from _TIGHTENS.
_TIGHTER_DIRECTION = {
    "stop_out_level_pct": "higher",
    "safe_mode_buffer_pct": "higher",
    "per_order_size_max": "lower",
    "speculative_sleeve_cap_pct": "lower",
    "flatten_lead_seconds": "higher",
    "assess_max_latency_seconds": "lower",
}


def _is_not_looser(fieldname, pinned_value, result_value):
    """True iff ``result_value`` is equal-or-tighter than ``pinned_value``.

    "Not looser" is the R2.5 invariant: equal (override ignored / retained) or
    strictly tighter is acceptable; strictly looser is a survival violation.
    """
    if _TIGHTER_DIRECTION[fieldname] == "higher":
        # higher = tighter; looser would be a STRICTLY lower result.
        return result_value >= pinned_value
    # lower = tighter; looser would be a STRICTLY higher result.
    return result_value <= pinned_value


@pytest.mark.parametrize("fieldname", list(_TIGHTER_DIRECTION))
def test_tighten_only_nan_override_never_loosens(fieldname):
    # NaN compares False to everything, so the comparator rejects it and the
    # pinned value is retained — for every numeric field, in both directions.
    m = _params_module()
    pinned = _pinned()
    result = m.tighten_only(pinned, {fieldname: math.nan})
    assert getattr(result, fieldname) == _PINNED_BASE[fieldname], (
        f"{fieldname}: a NaN override must retain the pinned value (never loosen)"
    )


@pytest.mark.parametrize("fieldname", list(_TIGHTER_DIRECTION))
def test_tighten_only_inf_override_never_loosens(fieldname):
    # +inf is malformed; whether it is rejected (future hardened build) or
    # applied (current build, only on higher-is-tighter fields), the result must
    # never be LOOSER than the pinned value. We assert the requirement, not the
    # current applied/rejected outcome.
    m = _params_module()
    pinned = _pinned()
    pinned_value = getattr(pinned, fieldname)
    for bad in (math.inf, -math.inf):
        result = m.tighten_only(pinned, {fieldname: bad})
        assert _is_not_looser(fieldname, pinned_value, getattr(result, fieldname)), (
            f"{fieldname}: a {bad} override must never loosen the survival "
            f"constraint (pinned={pinned_value}, got={getattr(result, fieldname)})"
        )


@pytest.mark.parametrize("bad", ["2.0", None, [1.0], {"x": 1}])
@pytest.mark.parametrize("fieldname", list(_TIGHTER_DIRECTION))
def test_tighten_only_wrong_type_override_fails_closed_never_loosens(fieldname, bad):
    # A wrong-type override to a numeric field currently raises from the
    # comparator (`'<'/'>' not supported`) — i.e. it fails closed rather than
    # silently loosening. If 1.2 later adds explicit validation it will still
    # raise; either way it must never silently apply a looser value. We accept
    # (TypeError, ValueError) so the assertion survives a future explicit-
    # validation change.
    m = _params_module()
    pinned = _pinned()
    pinned_value = getattr(pinned, fieldname)
    try:
        result = m.tighten_only(pinned, {fieldname: bad})
    except (TypeError, ValueError):
        return  # fail-closed: acceptable (never loosened, raised instead).
    # If it did NOT raise, the result must at minimum never be looser.
    assert _is_not_looser(fieldname, pinned_value, getattr(result, fieldname)), (
        f"{fieldname}: a wrong-type override ({bad!r}) that does not raise must "
        f"never loosen the survival constraint"
    )


def test_tighten_only_unknown_key_override_is_ignored():
    # An override key the gate does not know cannot loosen a constraint: it is
    # ignored and the full pinned set is carried through unchanged.
    m = _params_module()
    pinned = _pinned()
    result = m.tighten_only(pinned, {"not_a_survival_field": 0.0, "another": -1})
    assert result == pinned


def test_tighten_only_malformed_exclusion_override_cannot_disable():
    # Boolean loosen-guard (R5.4 / R10.4): with exclusion pinned True, NO
    # malformed/falsy/truthy override may flip it to False. Disabling the ex-ante
    # exclusion stage at runtime is the boolean LOOSEN and must be impossible via
    # any override value.
    m = _params_module()
    pinned = m.SurvivalParameters(**{**_PINNED_BASE, "exclusion_enabled": True})
    for bad in (False, 0, "", None, math.nan, "false"):
        result = m.tighten_only(pinned, {"exclusion_enabled": bad})
        assert result.exclusion_enabled is True, (
            f"exclusion override {bad!r} must not disable the pinned-True "
            f"ex-ante exclusion stage (boolean loosen)"
        )


# --------------------------------------------------------------------------- #
# resolve — remaining fail-closed branches (inf, empty version string).        #
# --------------------------------------------------------------------------- #

def test_resolve_fails_closed_on_inf():
    # _coerce_float rejects non-finite (inf), like NaN — closing the second
    # branch of the finiteness guard.
    m = _params_module()
    snap = _valid_snapshot()
    snap["survival.flatten_lead_seconds"] = math.inf
    with pytest.raises(ValueError):
        m.resolve(snap)


def test_resolve_fails_closed_on_empty_version_string():
    # An empty version string is malformed run-identity metadata; resolve must
    # fail closed rather than admit an empty four-key identity (P3).
    m = _params_module()
    snap = _valid_snapshot()
    snap["code_version"] = ""
    with pytest.raises(ValueError):
        m.resolve(snap)


# --------------------------------------------------------------------------- #
# R11.2 — inner-ring isolation: no LLM / MCP / live-DB import in the path.     #
# --------------------------------------------------------------------------- #

def test_params_module_imports_are_stdlib_or_survival_only():
    """Structural proof of R11.2 / P14: ``params.py`` pulls in only the standard
    library and the ``src.survival`` package — no LLM client, MCP, or DB driver
    can sit on the decision path. AST-scan of the direct imports (not a
    transitive graph walk — proportionate to the inner-ring isolation claim).

    Crucially this resolves ``src.*`` imports to their FULL dotted path and
    requires ``src.survival.*`` specifically: ``from src.mcp import ...`` or
    ``import src.shared.db`` must fail, not slip through on the shared ``src``
    top-level token.
    """
    m = _params_module()
    source = pathlib.Path(m.__file__).read_text()
    tree = ast.parse(source)

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue  # relative intra-package import (`from . import x`) — safe.
            if node.module:
                modules.add(node.module)

    stdlib = set(sys.stdlib_module_names)
    for mod in modules:
        top = mod.split(".")[0]
        if top == "src":
            assert mod.split(".")[:2] == ["src", "survival"], (
                f"params.py imports {mod!r} — only src.survival.* is allowed on "
                f"the inner-ring path (R11.2 isolation); a non-survival src.* "
                f"import (e.g. src.mcp / src.shared.db) would break it"
            )
        else:
            assert top in stdlib, (
                f"params.py imports {mod!r}, which is neither stdlib nor under "
                f"src.survival — R11.2 inner-ring isolation would be broken"
            )
