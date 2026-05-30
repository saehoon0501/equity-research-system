"""Pinned survival-parameter set + the tighten-only runtime-override resolver.

This is the ``params`` module of the ``survival`` package (dependency direction
``types → params → gate``): it imports only from the standard library and
nothing upward (no ``gate`` import). ``SurvivalParameters`` is defined locally
here (co-located with ``DEFAULTS``/``resolve``/``tighten_only`` per task 1.2),
not imported from ``types``. It owns the *pinned survival-parameter set* as a unit —
the :class:`SurvivalParameters` frozen dataclass, the module-constant
:data:`DEFAULTS`, the by-value :func:`resolve`, and the tighten-only
:func:`tighten_only` runtime-override resolver.

Design source: ``.kiro/specs/survival-gate/design.md`` §"Components and
Interfaces → Parameters — `params`" and §"Data Models → survival.* parameters".
Requirements: **R10** (consume pinned params by value; no fit; tighten-only
override) and **R2.5** (no runtime loosening of any survival constraint).

Where ``SurvivalParameters`` lives
----------------------------------
The dataclass is defined *here* (co-located with ``DEFAULTS`` / ``resolve`` /
``tighten_only``) rather than in ``types.py``. Task 1.2 owns "the pinned
survival-parameter set" as a single unit, and design §Parameters presents the
dataclass together with its defaults + resolvers. The §File-Structure ``types.py``
comment that also lists ``SurvivalParameters`` is a non-binding doc artifact;
defining it here is design-consistent and was deferred to this task by 1.1. The
``params → types`` import is one-directional (nothing in ``params`` is imported
back by ``types``), so the strict dependency direction is preserved.

Tighten direction (R10.4 — the crux)
-------------------------------------
"Tighten" means *more survival-conservative*; the numeric direction differs per
field. A loosening override is **rejected (the pinned value is retained)** and a
tightening override is **applied**. Both ``stop_out_level_pct`` and
``safe_mode_buffer_pct`` are margin-level percentages where a **higher** margin
level is safer (more liquidation distance), so a higher value is the tighter
one (consistent with the §Types ``AccountState`` "uses the **tighter** of the
two" stop-out note, P7).

  ====================================  =====================  =======================
  field                                 TIGHTEN means          LOOSEN (reject/retain)
  ====================================  =====================  =======================
  stop_out_level_pct                    higher                 lower
  safe_mode_buffer_pct                  higher                 lower
  per_order_size_max                    lower                  higher
  speculative_sleeve_cap_pct            lower                  higher
  flatten_lead_seconds                  higher                 lower
  assess_max_latency_seconds            lower                  higher
  exclusion_enabled                     enable (False→True)    disable (True→False)
  ====================================  =====================  =======================

``code_version`` / ``param_version`` are run identity metadata, **not**
numerically tightenable: :func:`tighten_only` ignores any override of them and
carries the pinned values through (an override touching only the version fields
is a no-op).

Pure stdlib only — no LLM / MCP / DB imports (R11.2, P14). Deterministic;
frozen / immutable.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Any, Callable, Mapping


# --------------------------------------------------------------------------- #
# The pinned survival-parameter set.                                          #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SurvivalParameters:
    """The set of survival parameters pinned by value at run start (P2, R10).

    Frozen / immutable: a pinned snapshot cannot be mutated mid-run, and the core
    never re-resolves from live state (R10.2). The version fields are run-level
    identity metadata threaded into the trace four-key contract (P3); they are
    not survival-domain thresholds and are not tightenable.
    """

    stop_out_level_pct: float          # venue stop-out (<=50); liquidation threshold (R1.2)
    safe_mode_buffer_pct: float        # margin-level buffer STRICTLY ABOVE stop-out (R1.3)
    per_order_size_max: float          # per-order volume / exposure cap (R4.1)
    speculative_sleeve_cap_pct: float  # funding cap = 8.0 (R3.1)
    flatten_lead_seconds: float        # closure lead time for flat-before-close (R6)
    assess_max_latency_seconds: float  # max gap between assess invocations (daemon cadence bound)
    exclusion_enabled: bool            # toggleable ex-ante exclusion stage (R5.4)
    code_version: str                  # run identity (P3 four-key); not tightenable
    param_version: str                 # run identity (P3 four-key); not tightenable


# --------------------------------------------------------------------------- #
# Module-constant inner-ring defaults.                                        #
# --------------------------------------------------------------------------- #
# Inner-ring values (P14): chosen to be conservative and to satisfy the design
# invariants — buffer STRICTLY above stop-out (R1.3), sleeve cap == 8.0 (R3.1),
# stop-out <= 50 (R1.2). Margin-level percentages are account equity / used
# margin * 100, where a HIGHER level is safer.
#
#   * stop_out_level_pct       = 50.0  — the venue stop-out ceiling (<=50, R1.2).
#   * safe_mode_buffer_pct     = 100.0 — enter safe-mode at 2x the stop-out level,
#                                        i.e. well before liquidation (> stop-out, R1.3).
#   * per_order_size_max       = 1.0   — a conservative single-order volume cap.
#   * speculative_sleeve_cap_pct = 8.0 — the funding cap (R3.1, fixed).
#   * flatten_lead_seconds     = 300.0 — begin flat-before-close 5 min ahead (R6).
#   * assess_max_latency_seconds = 5.0 — the standing monitor's worst-case cadence.
#   * exclusion_enabled        = True  — ex-ante exclusion on by default (safer).
#   * code_version / param_version     — placeholder identity for the inner ring;
#                                        real values are pinned per run.
DEFAULTS: SurvivalParameters = SurvivalParameters(
    stop_out_level_pct=50.0,
    safe_mode_buffer_pct=100.0,
    per_order_size_max=1.0,
    speculative_sleeve_cap_pct=8.0,
    flatten_lead_seconds=300.0,
    assess_max_latency_seconds=5.0,
    exclusion_enabled=True,
    code_version="inner-ring-defaults",
    param_version="inner-ring-defaults",
)


# --------------------------------------------------------------------------- #
# Snapshot key mapping (by-value resolve).                                    #
# --------------------------------------------------------------------------- #
# The 7 survival-domain fields are keyed under the ``survival.*`` namespace (the
# pinned seed namespace — design §Data Models). ``code_version`` / ``param_version``
# are run-level identity, not survival-domain, so they are read as snapshot-level
# keys (no ``survival.`` prefix). Every field is required by value and fails
# closed if absent / malformed — no silent defaulting.
_FLOAT_KEYS: dict[str, str] = {
    "survival.stop_out_level_pct": "stop_out_level_pct",
    "survival.safe_mode_buffer_pct": "safe_mode_buffer_pct",
    "survival.per_order_size_max": "per_order_size_max",
    "survival.speculative_sleeve_cap_pct": "speculative_sleeve_cap_pct",
    "survival.flatten_lead_seconds": "flatten_lead_seconds",
    "survival.assess_max_latency_seconds": "assess_max_latency_seconds",
}
_BOOL_KEYS: dict[str, str] = {
    "survival.exclusion_enabled": "exclusion_enabled",
}
_STR_KEYS: dict[str, str] = {
    "code_version": "code_version",
    "param_version": "param_version",
}


def _require(snapshot: Mapping[str, Any], key: str) -> Any:
    if key not in snapshot:
        raise KeyError(f"pinned survival snapshot missing required key: {key!r}")
    return snapshot[key]


def _coerce_float(key: str, value: Any) -> float:
    # bool is an int subclass — reject it explicitly so True/False cannot slip
    # into a numeric field.
    if isinstance(value, bool):
        raise TypeError(f"{key!r}: expected float, got bool {value!r}")
    if not isinstance(value, (int, float)):
        raise TypeError(
            f"{key!r}: expected float, got {type(value).__name__} {value!r}"
        )
    out = float(value)
    if math.isnan(out) or math.isinf(out):
        raise ValueError(f"{key!r}: non-finite float {value!r}")
    return out


def _coerce_bool(key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise TypeError(
            f"{key!r}: expected bool, got {type(value).__name__} {value!r}"
        )
    return value


def _coerce_str(key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(
            f"{key!r}: expected str, got {type(value).__name__} {value!r}"
        )
    if not value:
        raise ValueError(f"{key!r}: expected a non-empty str")
    return value


def resolve(snapshot: Mapping[str, Any]) -> SurvivalParameters:
    """Build :class:`SurvivalParameters` from a pinned ``survival.*`` snapshot,
    **by value** (R10.1 / R10.2 — no live / DB re-resolution).

    Fails **closed** on malformed input — a missing key, a wrong type
    (including a ``bool`` supplied for a numeric field), a non-finite float
    (``NaN`` / ``inf``), or an empty version string raises. There is no silent
    defaulting; every field must be present and well-formed.

    The returned object is built by value: it does not alias the source mapping,
    so a later mutation of ``snapshot`` cannot change the resolved parameters.
    """
    if not isinstance(snapshot, Mapping):
        raise TypeError(
            f"resolve expects a mapping snapshot, got {type(snapshot).__name__}"
        )

    fields: dict[str, Any] = {}
    for key, attr in _FLOAT_KEYS.items():
        fields[attr] = _coerce_float(key, _require(snapshot, key))
    for key, attr in _BOOL_KEYS.items():
        fields[attr] = _coerce_bool(key, _require(snapshot, key))
    for key, attr in _STR_KEYS.items():
        fields[attr] = _coerce_str(key, _require(snapshot, key))

    return SurvivalParameters(**fields)


# --------------------------------------------------------------------------- #
# Tighten-only runtime-override resolver (R10.4 / R2.5).                       #
# --------------------------------------------------------------------------- #
# Per-field comparator: given (pinned_value, override_value) return True iff the
# override is STRICTLY TIGHTER than the pinned value (i.e. should be applied). A
# value that is equal or looser returns False → the pinned value is retained.
#
# Encoded explicitly per field so a flipped direction is a one-line, test-caught
# change.
_TIGHTENS: dict[str, Callable[[Any, Any], bool]] = {
    # higher = tighter (more liquidation distance / enter safe-mode sooner)
    "stop_out_level_pct": lambda pinned, ov: ov > pinned,
    "safe_mode_buffer_pct": lambda pinned, ov: ov > pinned,
    # lower = tighter (smaller max order / smaller funding cap)
    "per_order_size_max": lambda pinned, ov: ov < pinned,
    "speculative_sleeve_cap_pct": lambda pinned, ov: ov < pinned,
    # higher = tighter (flatten earlier before close)
    "flatten_lead_seconds": lambda pinned, ov: ov > pinned,
    # lower = tighter (check more frequently)
    "assess_max_latency_seconds": lambda pinned, ov: ov < pinned,
    # enable = tighter (False → True). Disabling (True → False) is a loosen.
    "exclusion_enabled": lambda pinned, ov: bool(ov) and not bool(pinned),
}


def tighten_only(
    pinned: SurvivalParameters, override: Mapping[str, Any]
) -> SurvivalParameters:
    """Apply a runtime override **only where it tightens** a survival parameter.

    For each survival field, an override that is strictly tighter than the pinned
    value (per :data:`_TIGHTENS`) is applied; an override that is equal or
    *looser* is **rejected** and the pinned value retained (R10.4 / R2.5 — no
    runtime loosening). The version fields (``code_version`` / ``param_version``)
    are run identity, not tightenable: any override of them is ignored and the
    pinned values carry through.

    Returns a new frozen :class:`SurvivalParameters`; ``pinned`` is never
    mutated. An empty / version-only override is therefore an effective no-op.
    Unknown keys in ``override`` are ignored (a key the gate does not know cannot
    loosen a constraint).
    """
    applied: dict[str, Any] = {}
    for key, value in override.items():
        comparator = _TIGHTENS.get(key)
        if comparator is None:
            # Unknown key or a version field — never tightenable; ignore it so
            # the pinned value is retained.
            continue
        pinned_value = getattr(pinned, key)
        if comparator(pinned_value, value):
            applied[key] = value
    if not applied:
        return pinned
    return dataclasses.replace(pinned, **applied)


__all__ = [
    "SurvivalParameters",
    "DEFAULTS",
    "resolve",
    "tighten_only",
]
