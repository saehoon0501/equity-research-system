"""Pure-unit tests for the pinned parameter snapshot + tighten-only resolver.

Task 1.2 (reactive-signal-model). Asserts the observable params contract the
parent's import/shape check cannot: `DEFAULTS` instantiates frozen with every
field present and calibration both-None (unestablished at the inner ring,
Req 7.4 / design §params Invariants); the near-equal weights are normalized so
`Σw == 1` (Req 1.5); and `effective_threshold` is *tighten-only* (Req 6.3/6.4) —
a higher runtime override is applied, a lower one is rejected and the snapshot
threshold retained, and `None` returns the snapshot threshold unchanged.

`Weights` / `CalibrationEvidence` are REUSED from `src.reactive.types`
(task 1.1) — never redefined here (types → params dependency direction).

No LLM, MCP, or live DB — pure leaf config contract (P1, R8).
Task 3.1 will EXTEND this file with broader coverage; keep tests here.
"""

from __future__ import annotations

import ast
import dataclasses as d
import sys
from pathlib import Path

import pytest

import src.reactive.params as params_mod
from src.reactive.params import DEFAULTS, ParamSnapshot, effective_threshold
from src.reactive.types import CalibrationEvidence, Weights


# --- DEFAULTS: frozen, all fields present, calibration unestablished -------


def test_defaults_is_param_snapshot_with_all_fields() -> None:
    assert isinstance(DEFAULTS, ParamSnapshot)
    assert {f.name for f in d.fields(ParamSnapshot)} == {
        "weights",
        "temperature",
        "threshold",
        "calibration",
        "code_version",
        "param_version",
    }


def test_defaults_field_types_and_values() -> None:
    assert isinstance(DEFAULTS.weights, Weights)
    assert isinstance(DEFAULTS.calibration, CalibrationEvidence)
    # temperature must be positive (it divides the logit downstream).
    assert DEFAULTS.temperature > 0
    # threshold is compared against a logistic probability ∈ (0, 1).
    assert 0.0 < DEFAULTS.threshold < 1.0
    # version tags present and non-empty (carried into the substrate).
    assert isinstance(DEFAULTS.code_version, str) and DEFAULTS.code_version
    assert isinstance(DEFAULTS.param_version, str) and DEFAULTS.param_version


def test_defaults_frozen() -> None:
    with pytest.raises(d.FrozenInstanceError):
        DEFAULTS.threshold = 0.99  # type: ignore[misc]


def test_defaults_calibration_both_none() -> None:
    # Unestablished at the inner ring — exposed, never computed here (R7.4).
    assert DEFAULTS.calibration.brier is None
    assert DEFAULTS.calibration.reliability is None


def test_defaults_weights_sum_to_one() -> None:
    # Near-equal, normalized so the aggregate score stays in [-1, +1] (R1.5).
    w = DEFAULTS.weights
    assert w.w_trend + w.w_flow + w.w_meanrev == pytest.approx(1.0)


def test_defaults_weights_near_equal() -> None:
    # No single family dominates the combined signal (R1.5): each near 1/3.
    w = DEFAULTS.weights
    for val in (w.w_trend, w.w_flow, w.w_meanrev):
        assert val == pytest.approx(1.0 / 3.0, abs=0.05)


# --- effective_threshold: tighten-only (R6.3/6.4) --------------------------


def test_effective_threshold_none_returns_snapshot() -> None:
    # No runtime override → snapshot threshold unchanged.
    assert effective_threshold(DEFAULTS, None) == DEFAULTS.threshold


def test_effective_threshold_higher_runtime_applied() -> None:
    # Runtime strictly above snapshot → the HIGHER (tighter) value applies.
    higher = DEFAULTS.threshold + 0.1
    assert effective_threshold(DEFAULTS, higher) == higher
    assert effective_threshold(DEFAULTS, higher) > DEFAULTS.threshold


def test_effective_threshold_lower_runtime_rejected() -> None:
    # Runtime strictly below snapshot → REJECTED; snapshot threshold retained.
    lower = DEFAULTS.threshold - 0.1
    assert effective_threshold(DEFAULTS, lower) == DEFAULTS.threshold


def test_effective_threshold_never_below_snapshot() -> None:
    # The tighten-only invariant across a sweep straddling the snapshot value.
    for runtime in (0.0, DEFAULTS.threshold - 0.2, DEFAULTS.threshold + 0.2, 1.0):
        assert effective_threshold(DEFAULTS, runtime) >= DEFAULTS.threshold


# --- ADDED (task 3.1) ------------------------------------------------------
# Determinism (R8.1) + leaf-isolation import-surface check (R8.2/R8.3). These
# are the genuinely-new 3.1 assertions; everything above PRE-EXISTED from the
# task-1.2 TDD pass (DEFAULTS completeness/frozen/calibration-None, Σw==1, and
# the four tighten-only cases).


# --- Determinism (R8.1): identical inputs -> identical outputs -------------


def test_effective_threshold_deterministic_interleaved() -> None:
    # R8.1: identical (snapshot, runtime) -> identical result, with NO hidden
    # state. Interleave two distinct inputs and re-issue the first: a stateful
    # resolver could drift between the two A-calls; a pure one cannot.
    a = DEFAULTS.threshold + 0.10
    b = DEFAULTS.threshold - 0.10  # rejected (tighten-only) -> snapshot value
    first_a = effective_threshold(DEFAULTS, a)
    mid_b = effective_threshold(DEFAULTS, b)
    third_a = effective_threshold(DEFAULTS, a)
    assert first_a == third_a == a
    assert mid_b == DEFAULTS.threshold


def test_effective_threshold_deterministic_repeated_none() -> None:
    # R8.1: the None (no-override) path is equally stable across repeats.
    results = {effective_threshold(DEFAULTS, None) for _ in range(50)}
    assert results == {DEFAULTS.threshold}


def test_effective_threshold_does_not_mutate_snapshot() -> None:
    # R8.1: resolution reads the snapshot by value and never mutates it. Frozen
    # already forbids mutation; this asserts the determinism contract directly.
    before = d.astuple(DEFAULTS)
    effective_threshold(DEFAULTS, DEFAULTS.threshold + 0.2)
    effective_threshold(DEFAULTS, DEFAULTS.threshold - 0.2)
    effective_threshold(DEFAULTS, None)
    assert d.astuple(DEFAULTS) == before


def test_defaults_is_stable_module_constant() -> None:
    # R8.1: DEFAULTS is a single fixed module constant, not rebuilt per access
    # — repeated attribute reads return the SAME object (no per-call / no
    # randomized construction), and `from ... import DEFAULTS` binds that same
    # identity. A function-call-backed or freshly-constructed value would fail
    # the identity assertion.
    assert params_mod.DEFAULTS is params_mod.DEFAULTS
    assert DEFAULTS is params_mod.DEFAULTS


# --- Isolation (R8.2 / R8.3): pure leaf, no LLM/MCP/network/DB imports ------

# Third-party / IO families that would break the "pure leaf, no LLM/MCP/live-DB"
# contract if imported by the params module (R8.2). The stdlib allowlist below
# is the load-bearing general check; this list makes the intent legible to a
# reviewer and guards the named offenders explicitly.
_FORBIDDEN_IMPORT_SUBSTRINGS = (
    "psycopg",
    "sqlalchemy",
    "httpx",
    "requests",
    "urllib3",
    "aiohttp",
    "mcp",
    "llm",
    "anthropic",
    "openai",
    "boto3",
    "numpy",
    "scipy",
    "pandas",
)


def _top_level_imports(source: str) -> set[str]:
    """Top-level module name of every import statement in `source`.

    AST over the *source file* — not `sys.modules` — because the test harness
    itself loads numpy/scipy/httpx/pandas (see the validation command), so a
    `sys.modules` probe would be polluted and meaningless. This inspects what
    params.py actually imports.
    """
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Skip relative imports (no module / level>0); none expected here.
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_params_module_imports_only_stdlib_and_reactive_types() -> None:
    # R8.2/R8.3: the params module is a pure leaf. Its direct import surface
    # must be confined to the stdlib + `src.reactive.types` — no third-party
    # I/O (network/DB) and no LLM/MCP client. `sys.stdlib_module_names` (3.10+)
    # is the robust general allowlist: it catches ANY third-party import, not
    # only the enumerated offenders.
    source = Path(params_mod.__file__).read_text()
    tree = ast.parse(source)

    allowed_roots = set(sys.stdlib_module_names) | {"__future__", "src"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root in allowed_roots, (
                    f"params imports non-stdlib/non-src module {alias.name!r} "
                    "— breaks the pure-leaf isolation contract (R8.2/R8.3)"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or node.module is None:
                pytest.fail(
                    "params uses a relative import; expected only stdlib + "
                    "the absolute `src.reactive.types`"
                )
            root = node.module.split(".")[0]
            assert root in allowed_roots, (
                f"params imports from non-stdlib/non-src module "
                f"{node.module!r} — breaks isolation (R8.2/R8.3)"
            )
            # Any `src.`-prefixed import must be EXACTLY `src.reactive.types`
            # (dependency direction types -> params; design §Allowed Deps).
            # Stops a future `src.…db` slipping past the stdlib allowlist.
            if root == "src":
                assert node.module == "src.reactive.types", (
                    f"params imports {node.module!r} from src; the only "
                    "permitted intra-src dependency is `src.reactive.types`"
                )


def test_params_module_has_no_forbidden_io_imports() -> None:
    # R8.2: explicit, reviewer-legible guard against the named LLM/MCP/network/
    # DB families. Redundant with the stdlib allowlist above by design — it
    # documents that R8.2's specific offenders are absent.
    roots = _top_level_imports(Path(params_mod.__file__).read_text())
    for root in roots:
        for forbidden in _FORBIDDEN_IMPORT_SUBSTRINGS:
            assert forbidden not in root, (
                f"params imports forbidden I/O/LLM family {root!r} "
                f"(matched {forbidden!r}) — violates R8.2 (no LLM/MCP/live-DB)"
            )
