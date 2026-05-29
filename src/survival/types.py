"""Input / output data contracts and fixed vocabularies for the Survival Gate.

This is the base module of the ``survival`` package (dependency direction
``types → params → gate``): it imports nothing from ``params`` or ``gate`` and
depends only on the standard library. All contracts are immutable
(``@dataclass(frozen=True)``) so a decision object cannot be mutated after the
pure core emits it. Fixed vocabularies are ``typing.Literal`` aliases.

Design source: ``.kiro/specs/survival-gate/design.md`` §"Types — `types`" and
§"Data Models". R7 (operator decision 2026-05-29) removes real-time
per-instrument trading-halt detection from scope, so there is:

  * no ``trading_status`` / halt field on :class:`Position`
    (it mirrors broker ``get_positions`` 1:1),
  * no ``halt_freeze`` value in :data:`BindingConstraint`, and
  * no ``FLATTEN_AT_REOPEN`` value in :class:`ReduceDirective` ``kind``.

Per the §Types field list, only five things are ``Literal``-typed
(``SafeModeGrade``, ``BindingConstraint``, ``ProposedOrder.intent``,
``AdmitDecision.decision``, ``ReduceDirective.kind``). All other string-valued
fields (``direction``, ``event_type``, ``triggered_by``) are plain ``str`` and
are intentionally left un-pinned here so the later gate logic owns their
semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


# --------------------------------------------------------------------------- #
# Fixed vocabularies.                                                          #
# --------------------------------------------------------------------------- #

# Graded safe-mode response (monotonic-tighten by severity band):
# NONE → TIGHTEN → HALT_NEW → FLATTEN. Never auto-loosens.
SafeModeGrade = Literal["NONE", "TIGHTEN", "HALT_NEW", "FLATTEN"]

# The constraint that bound an admit/assess decision (the lexicographic walk
# emits the first one that fires for audit). No ``halt_freeze`` — real-time
# per-instrument halt detection is out of boundary (R7).
BindingConstraint = Literal[
    "kill_switch",
    "safe_mode",
    "not_activated",
    "universe",
    "entry_exclusion",
    "margin_distance",
    "funding_cap",
    "size_limit",
    "missing_sl",
]


# --------------------------------------------------------------------------- #
# Inputs.                                                                      #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Position:
    """A single open position, mirroring broker ``get_positions`` 1:1.

    Seam reconciled 2026-05-29 vs broker design ``72020a0``+``c79738f``:
    ``avg_open_price`` (renamed from ``open_price`` to match the broker field).
    No ``trading_status`` / halt-adjacent field: real-time halt detection is out
    of boundary (R7). The broker's only halt-adjacent signal is the post-hoc
    ``close_reason: forced_liquidation`` via ``get_history``, recorded to the
    event log — never a live input to ``admit``/``assess``.
    """

    position_id: str
    symbol: str
    direction: str
    volume: float
    avg_open_price: float
    used_margin: float
    unrealized_pnl: float


@dataclass(frozen=True)
class AccountState:
    """Account-level view composed by the Phase-2 adapter from broker
    ``get_account_assets`` + ``get_positions``.

    ``activated`` ← broker mt5-account ``status``. Cross-margin: ``margin_level``
    is account equity / aggregate used margin (R1.1). Total-book equity is *not*
    a per-call field — the funding cap is a capitalization-time precondition that
    takes an operator/config-supplied total-book figure (see
    ``gate.check_capitalization``).
    """

    activated: bool
    equity: float
    used_margin: float
    free_margin: float
    margin_level: float
    balance: float
    stop_out_level: float
    positions: list[Position] = field(default_factory=list)


@dataclass(frozen=True)
class ClockState:
    """Closure-imminence + session as *inputs* — the pure core cannot read the
    wall clock (R6, R11.2).

    ``seconds_to_next_closure`` is ``None`` when no closure is scheduled / known.
    """

    session_open: bool
    seconds_to_next_closure: Optional[float]


@dataclass(frozen=True)
class ProposedOrder:
    """An order proposed for admission. ``intent`` carries the upstream
    disposition label, but exit/open classification is by *effect on the held
    position*, not by this label (P7 — never trust the upstream label).

    ``stop_loss`` is ``None`` when the proposed order carries no protective stop;
    a missing SL on an open is a ``missing_sl`` rejection (R4.2/R4.3).
    """

    symbol: str
    intent: Literal["BUY", "TRIM", "SELL"]
    direction: str
    volume: float
    stop_loss: Optional[float]


@dataclass(frozen=True)
class OperationalState:
    """The gate's current operational state — read *fresh* per ``admit``/``assess``
    call (never folded into the pinned parameter snapshot — the op-state
    freshness guarantee).

    ``triggered_by`` is ``None`` when no event drove the current state.
    """

    kill_switch_engaged: bool
    safe_mode_grade: SafeModeGrade
    entered_at: Optional[datetime]
    triggered_by: Optional[str]


# --------------------------------------------------------------------------- #
# Outputs.                                                                     #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class AdmitDecision:
    """The per-order veto result.

    On ``REJECT`` the ``binding_constraint`` names the first constraint that
    fired (inspectable for audit, R2/R11.3); ``advisory_max_volume`` is a
    non-binding suggestion on a size breach (the daemon resizes + re-submits —
    the gate never returns a mutated order). ``binding_constraint`` /
    ``advisory_max_volume`` / ``reason`` are ``None`` on ``ALLOW``.
    """

    decision: Literal["ALLOW", "REJECT"]
    binding_constraint: Optional[BindingConstraint]
    advisory_max_volume: Optional[float]
    reason: Optional[str]


@dataclass(frozen=True)
class ReduceDirective:
    """A de-risking directive emitted by the standing monitor for the daemon to
    execute.

    No ``FLATTEN_AT_REOPEN`` kind — the halt path is removed (R7). ``symbol`` is
    ``None`` for an account-wide directive (e.g. ``FREEZE_ENTRIES``);
    ``target_volume`` is ``None`` when not applicable.
    """

    kind: Literal["FLATTEN", "REDUCE", "FREEZE_ENTRIES"]
    symbol: Optional[str]
    target_volume: Optional[float]
    reason: str


@dataclass(frozen=True)
class SurvivalEvent:
    """An anomaly / audit event emitted to the after-market queue.

    ``ticker`` is ``None`` for account-wide events. ``account_snapshot`` is a
    plain dict captured at emission time (the caller persists it as JSONB).
    """

    event_type: str
    ticker: Optional[str]
    detail: str
    account_snapshot: dict


@dataclass(frozen=True)
class AssessDirective:
    """The standing-monitor result.

    ``next_op_state.safe_mode_grade`` is monotonic-tighten (≥ the input grade);
    ``reduce_directives`` and ``events`` are emitted for the daemon to execute /
    persist (the gate performs no I/O).
    """

    next_op_state: OperationalState
    reduce_directives: list[ReduceDirective] = field(default_factory=list)
    events: list[SurvivalEvent] = field(default_factory=list)


__all__ = [
    "SafeModeGrade",
    "BindingConstraint",
    "Position",
    "AccountState",
    "ClockState",
    "ProposedOrder",
    "OperationalState",
    "AdmitDecision",
    "ReduceDirective",
    "SurvivalEvent",
    "AssessDirective",
]
