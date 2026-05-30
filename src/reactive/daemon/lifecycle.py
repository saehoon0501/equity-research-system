"""Version-pinned lifecycle + flat-before-close action (task 4.3).

Boundary: ``lifecycle`` (Requirements 6, 8). Source of truth:
``.kiro/specs/execution-daemon/design.md`` §"System Flows -> Version-pinned
lifecycle + hot-swap" (line 237) + §"Control -> ``lifecycle``" (line 367,
"flatten-in-window + verify-flat escalation; version-pin at open; manage under
opening version after hot-swap; whole-object atomic swap; global-tightest
survive; adopts the version ``commands`` selected") + the Requirements-Traceability
rows 6.1/6.2/6.3 (line 260) and 8.1/8.2/8.3/8.4 (lines 264-266) and 9.4 (line 269).
The physical version-pin table is ``execution_daemon_position_version``
(``db/migrations/052_execution_daemon_state.sql``).

What this module is — two cooperating concerns
----------------------------------------------
1. **Flat-before-close ACTION + verify-flat handshake** (Req 6). The survival
   gate owns the *rule* — :func:`survival.gate.assess` decides when a closure is
   imminent and emits ``FLATTEN`` / ``REDUCE`` / ``FREEZE_ENTRIES`` directives
   (``AssessDirective.reduce_directives``). The daemon owns the *action*:
   :func:`execute_de_risk_directives` translates each directive into a venue
   action over ``broker.submit_decision``, then **re-checks the flat
   post-condition** against a freshly-read post-flatten account and, when not
   flat, **escalates + records a verify-flat failure** (Req 6.2/6.3). A
   ``FREEZE_ENTRIES`` (account-wide) directive is a control signal, not a venue
   order — it routes no submit. The gate's own ``assess`` events (the
   ``flat_verify_failed`` / ``margin_breach`` / ``safe_mode_entered``
   :class:`SurvivalEvent`s) are persisted via :func:`persist_assess_events`
   (Req 5.4 — append-only).

2. **Version-pinned position lifecycle + atomic hot-swap** (Req 8). The
   :class:`VersionManager` holds the **whole** active versioned param object and
   swaps it as a single atomic unit (pointer-flip, Req 8.1 — never field-by-field).
   Each open position is associated with the (``code_version``, ``param_version``)
   in effect **at open time** (Req 8.2) and stays managed under that **opening
   version** even after a hot-swap (Req 8.3 — never retroactively re-managed). The
   open/close pair is written to ``execution_daemon_position_version`` via an
   injected writer. While positions opened under more than one version coexist,
   :func:`global_tightest` folds the coexisting version param objects to the
   **globally-tightest** survival parameters (Req 8.4 — the smallest per-order
   cap, the highest safe-mode buffer, etc. — reusing the survival package's single
   tighten-direction source so the cross-version fold cannot drift from the
   gate's own ``tighten_only``). The manager **adopts the version ``commands``
   selected** (Req 9.4): a ``select_validated_config`` records a pending
   version_id the next ``hot_swap`` consumes.

Leaf-executor boundary (Req 10): this module **executes and emits**, it never
recomputes a survival value. It obtains the de-risk directives + the events from
``assess`` (the dependency), the venue action from ``broker.submit_decision``,
and the tighten direction from ``survival.params`` — it computes nothing of its
own. The broker submit / event emit / version-pin writer are **injected** so the
module is inner-ring-testable with synthetic state + the REAL pure
``survival.assess`` (P14 — no DB, no MCP, no LLM at this seam). The loop
(task 4.4) wires the real ``broker.submit_decision`` / ``event_queue.emit_event``
/ the position-version writer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Optional, Sequence

from src.reactive.daemon.broker_seam import Direction, Label, Position, RuntimeMode
from src.reactive.daemon.types import PinnedParams
from src.survival.params import SurvivalParameters, _TIGHTENS
from src.survival.types import AccountState, ReduceDirective, SurvivalEvent

__all__ = [
    "DeRiskOutcome",
    "execute_de_risk_directives",
    "persist_assess_events",
    "PositionVersion",
    "VersionManager",
    "global_tightest",
]


# --------------------------------------------------------------------------- #
# Flat-before-close action + verify-flat handshake (Req 6).                    #
# --------------------------------------------------------------------------- #


# The directive kinds that REDUCE/close venue exposure (route a submit) vs the
# account-wide control kind that does not. FLATTEN and REDUCE both net-reduce a
# held position; FREEZE_ENTRIES is a "no new entries" control signal (the open
# block lives in the gate's admit / the orchestrator's permit, not a venue order).
_VENUE_DIRECTIVE_KINDS = frozenset({"FLATTEN", "REDUCE"})

# The net-reducing intent for a flatten/reduce of a held position. A LONG is
# closed by a SELL on its own side (the broker venue convention — the daemon
# targets the position by id, so a SELL net-reduces it). Always net-reducing,
# never a BUY open (Req 7.2 — a de-risk directive only ever reduces exposure).
_REDUCE_INTENT: Label = Label.SELL


@dataclass(frozen=True)
class DeRiskOutcome:
    """The result of executing a tick's de-risk directives (Req 6).

    ``submitted_position_ids`` are the venue positions a FLATTEN/REDUCE directive
    actually routed a submit for (a FREEZE_ENTRIES routes none). ``flat_verified``
    is the re-checked flat post-condition AFTER the flatten executed (Req 6.2) —
    True iff the post-flatten account holds no open positions. ``verify_flat_failed``
    is True when a flatten was executed (an in-window FLATTEN was present) but the
    book is **still not flat** afterward (Req 6.3 — the escalation condition). When
    no FLATTEN directive was present (e.g. a lone FREEZE_ENTRIES), there is nothing
    to verify-flat, so ``verify_flat_failed`` is False.
    """

    submitted_position_ids: tuple[str, ...]
    flat_verified: bool
    verify_flat_failed: bool


def _positions_for_directive(
    directive: ReduceDirective, broker_positions: Sequence[Position]
) -> list[Position]:
    """The held venue positions a FLATTEN/REDUCE directive targets.

    ``directive.symbol is None`` ⇒ **account-wide** → every held position
    (Req: ``symbol=None`` = account-wide). A symbol-scoped directive targets the
    held positions in that symbol. The daemon targets positions by their venue id
    obtained from the broker readout — it never infers position state (Req 11.5).
    """
    if directive.symbol is None:
        return list(broker_positions)
    return [p for p in broker_positions if p.symbol == directive.symbol]


def execute_de_risk_directives(
    *,
    directives: Sequence[ReduceDirective],
    broker_positions: Sequence[Position],
    post_flatten_account: AccountState,
    submit_decision: Callable[..., Any],
    runtime_mode: Optional[RuntimeMode] = None,
) -> DeRiskOutcome:
    """Execute the survival gate's de-risk directives, then re-check the flat
    post-condition (Req 6.1/6.2/6.3).

    For each directive:

      * ``FLATTEN`` / ``REDUCE`` → submit a net-reducing (SELL) order against each
        targeted held position (by ``position_id`` from the broker readout). An
        account-wide directive (``symbol=None``) targets every held position; a
        symbol-scoped one targets that symbol's held positions. Paper-only: a
        paper ``RuntimeMode`` is pinned so no live path is reachable (Req 3.1).
      * ``FREEZE_ENTRIES`` → a control signal, not a venue action → **no submit**
        (the new-exposure block is enforced at the orchestrator permit / the gate
        admit, not by a venue order).

    After executing the directives, **re-check the flat post-condition** against
    the freshly-read ``post_flatten_account`` (Req 6.2 — never trust that a flatten
    was issued). When an in-window FLATTEN was executed but the book is still not
    flat, the verify-flat **fails** (Req 6.3 — the daemon escalates per the gate
    and records a verify-flat failure; the gate has already emitted the
    ``flat_verify_failed`` :class:`SurvivalEvent` for :func:`persist_assess_events`
    to persist, and the next assess tick will re-escalate the grade against the
    still-open state).

    Args:
        directives: ``AssessDirective.reduce_directives`` for this tick.
        broker_positions: the freshly-read broker ``Position`` list (the targets).
        post_flatten_account: the survival ``AccountState`` read AFTER executing
            the flatten (the re-check input — in paper the position is not removed,
            so the re-check sees the still-open book and verify-flat fails, which
            the loop realizes "until flat" across ticks).
        submit_decision: the broker leaf ``submit_decision`` (injected — the loop
            wires the real one through the broker seam; tests pass a recording fake).
        runtime_mode: an explicit paper ``RuntimeMode``; ``None`` ⇒ the safe
            paper default (``paper_enabled=True`` ⇒ no live path).

    Returns:
        A :class:`DeRiskOutcome` (submitted ids + the re-checked flat post-condition
        + the verify-flat-failure escalation flag).
    """
    rm = runtime_mode if runtime_mode is not None else RuntimeMode()
    # Defense-in-depth (P6): never route a de-risk action on a live path.
    if not rm.paper_enabled:
        rm = RuntimeMode(paper_enabled=True)

    submitted: list[str] = []
    had_flatten = False

    for directive in directives:
        if directive.kind == "FLATTEN":
            had_flatten = True
        if directive.kind not in _VENUE_DIRECTIVE_KINDS:
            # FREEZE_ENTRIES (or any non-venue control kind) routes no submit.
            continue
        for pos in _positions_for_directive(directive, broker_positions):
            # Net-reducing close of the held position, targeted by its venue id
            # (Req 11.4). Direction is the HELD side — a SELL on the held side
            # closes it; the daemon never opens fresh exposure on a de-risk path.
            submit_decision(
                _REDUCE_INTENT,
                pos.symbol,
                pos.direction,
                volume=pos.volume,
                position_id=pos.position_id,
                stop_loss=None,
                runtime_mode=rm,
                prior_queue_task_id=None,
            )
            submitted.append(pos.position_id)

    # ----- verify-flat handshake (Req 6.2): re-check against fresh state. ------
    flat_verified = len(post_flatten_account.positions) == 0
    # Escalation condition (Req 6.3): an in-window FLATTEN was executed but the
    # book is still not flat. A lone FREEZE_ENTRIES (no FLATTEN) has nothing to
    # verify, so it never reads as a verify-flat failure.
    verify_flat_failed = had_flatten and not flat_verified

    return DeRiskOutcome(
        submitted_position_ids=tuple(submitted),
        flat_verified=flat_verified,
        verify_flat_failed=verify_flat_failed,
    )


# The event_queue kind a survival anomaly event travels under. ``flat_verify_failed``
# / ``margin_breach`` / ``safe_mode_entered`` are all safety-state anomalies → the
# ``safe_mode`` queue kind (the survival event_type is preserved in the payload so
# the drainer keeps the full granularity). Every other survival event travels under
# the ``lifecycle`` kind (a generic lifecycle transition).
_SAFE_MODE_EVENT_TYPES = frozenset(
    {"flat_verify_failed", "margin_breach", "safe_mode_entered"}
)


def persist_assess_events(
    *,
    run_id: str,
    events: Sequence[SurvivalEvent],
    emit_event: Callable[..., Any],
) -> int:
    """Persist each ``AssessDirective.events`` :class:`SurvivalEvent` to the
    append-only event queue (Req 5.4).

    The gate performs no I/O — it emits the events for the daemon to persist. Each
    survival event is emitted as ONE ``execution_daemon_event_queue`` row under the
    queue ``event_type`` it maps to (a safety anomaly → ``safe_mode``; otherwise
    ``lifecycle``), carrying the survival event's full body (``event_type`` /
    ``ticker`` / ``detail`` / ``account_snapshot``) in the JSONB payload so the
    drainer keeps every field. ``run_id`` is the epoch correlation key (P3).

    Args:
        run_id: the emitting epoch's run_id (P3 — the same key on the trace).
        events: the ``AssessDirective.events`` for this tick.
        emit_event: the ``event_queue.emit_event``-shaped seam (injected — the loop
            wires the real one bound to the daemon connection; tests pass a fake).
            Called keyword-only as ``emit_event(run_id=, event_type=, payload=)``.

    Returns:
        The count of events persisted (one row per survival event).
    """
    count = 0
    for event in events:
        queue_kind = (
            "safe_mode" if event.event_type in _SAFE_MODE_EVENT_TYPES else "lifecycle"
        )
        emit_event(
            run_id=run_id,
            event_type=queue_kind,
            payload={
                "event_type": event.event_type,
                "ticker": event.ticker,
                "detail": event.detail,
                "account_snapshot": event.account_snapshot,
            },
        )
        count += 1
    return count


# --------------------------------------------------------------------------- #
# Version-pinned position lifecycle + atomic hot-swap (Req 8).                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PositionVersion:
    """The (code_version, param_version) a position was opened under (Req 8.2).

    Frozen — a position's opening version is immutable; it is the version the
    position stays managed under for its whole lifetime, even across a hot-swap
    (Req 8.3). ``run_id`` is the epoch whose version this is (the epoch_id pinned
    at open time) so the close row correlates to the opening epoch (P3).
    """

    run_id: str
    code_version: str
    param_version: str


def global_tightest(versions: Sequence[SurvivalParameters]) -> SurvivalParameters:
    """The globally-tightest survival parameters across coexisting versions (Req 8.4).

    While positions opened under more than one version are open simultaneously, the
    daemon applies survival constraints at the **globally-tightest** level across
    all of them — never the loosest, never an average (P7 — fail toward more
    protection). This folds the version param objects field-by-field, keeping the
    **tighter** value per field as defined by the survival package's single
    tighten-direction source (``survival.params._TIGHTENS``) — so the cross-version
    fold cannot drift from the gate's own per-field tighten direction
    (``tighten_only``). Non-tightenable fields (``code_version`` / ``param_version``)
    are carried from the first version (identity metadata, not a constraint).

    Args:
        versions: the distinct ``SurvivalParameters`` of the currently-open
            positions' versions (one entry per coexisting version). Must be
            non-empty.

    Returns:
        A ``SurvivalParameters`` whose every tightenable field is the tightest
        across ``versions``. With a single version, that version's params are
        returned unchanged.
    """
    if not versions:
        raise ValueError(
            "global_tightest requires at least one version's SurvivalParameters "
            "(there is no tightest constraint over an empty set)"
        )
    tightest = versions[0]
    for candidate in versions[1:]:
        overrides: dict[str, Any] = {}
        for field_name, is_tighter in _TIGHTENS.items():
            current = getattr(tightest, field_name)
            other = getattr(candidate, field_name)
            # Keep ``other`` only where it is strictly tighter than the running
            # tightest (the same predicate the gate uses to apply a tighten).
            if is_tighter(current, other):
                overrides[field_name] = other
        if overrides:
            tightest = replace(tightest, **overrides)
    return tightest


class VersionManager:
    """The version-pinned position lifecycle + atomic hot-swap manager (Req 8/9.4).

    Holds the **whole** active versioned param object and swaps it as a single
    atomic unit (:meth:`hot_swap` — pointer-flip, Req 8.1). Each opened position
    is associated with the active (``code_version``, ``param_version``) at open
    time (:meth:`record_open`, Req 8.2) and **stays** on that opening version even
    after a swap (:meth:`version_for_position`, Req 8.3). The open/close pair is
    written to ``execution_daemon_position_version`` via the injected writer. A
    ``select_validated_config`` recorded by ``commands`` (:meth:`select_version`)
    is **adopted at the next hot_swap** (Req 9.4).

    Single-threaded by construction (the loop serializes evaluations, Req 1.1), so
    no lock is needed — plain dicts keyed on the venue position id.
    """

    def __init__(
        self,
        *,
        initial_run_id: str,
        initial_code_version: str,
        initial_param_version: str,
        initial_params: PinnedParams,
        write_version_pin: Optional[Callable[..., Any]] = None,
    ) -> None:
        """Open the manager on the initial (startup) epoch's version.

        Args:
            initial_run_id / initial_code_version / initial_param_version: the
                startup epoch's identity (the version positions opened now pin).
            initial_params: the startup epoch's whole ``PinnedParams`` (the object
                a later hot_swap replaces atomically).
            write_version_pin: the ``execution_daemon_position_version`` writer
                seam (injected — the loop wires the real one; ``None`` ⇒ the
                version pins are tracked in-memory only, for inner-ring tests that
                do not assert the DB write).
        """
        self._active_run_id = initial_run_id
        self._active_code_version = initial_code_version
        self._active_param_version = initial_param_version
        self._active_params = initial_params
        self._write_version_pin = write_version_pin
        # venue_position_id -> the PositionVersion it was OPENED under (its
        # opening version, retained across hot-swaps — Req 8.3).
        self._open_versions: dict[str, PositionVersion] = {}
        # A select_validated_config recorded by commands, pending the next swap.
        self._pending_selected_version: Optional[str] = None

    # -- active version (whole-object) --------------------------------------- #

    @property
    def active_params(self) -> PinnedParams:
        """The WHOLE active versioned param object (Req 8.1 — pointer-flip target)."""
        return self._active_params

    @property
    def active_run_id(self) -> str:
        return self._active_run_id

    @property
    def active_code_version(self) -> str:
        return self._active_code_version

    @property
    def active_param_version(self) -> str:
        return self._active_param_version

    @property
    def pending_selected_version(self) -> Optional[str]:
        """The version_id ``commands`` selected for the next hot-swap, or ``None``."""
        return self._pending_selected_version

    # -- command-selected version adoption (Req 9.4) ------------------------- #

    def select_version(self, version_id: str) -> None:
        """Record the version ``commands`` selected (a ``select_validated_config``).

        Adopted at the next :meth:`hot_swap` (Req 9.4). The toward-safer guard
        (registry-member, not looser) is enforced by ``commands`` before this is
        called — the manager only holds the pending selection.
        """
        self._pending_selected_version = version_id

    # -- atomic hot-swap (Req 8.1) ------------------------------------------- #

    def hot_swap(
        self,
        *,
        run_id: str,
        code_version: str,
        param_version: str,
        params: PinnedParams,
    ) -> None:
        """Flip the WHOLE versioned param object atomically (Req 8.1).

        Replaces the active (run_id, code_version, param_version, params) as a
        single unit — a pointer-flip, never field-by-field. Already-open positions
        are **not** touched: they keep the opening version recorded in
        :attr:`_open_versions` (Req 8.3). Adopting a hot-swap **clears** the pending
        ``commands``-selected version (Req 9.4 — the selection has been consumed).
        """
        self._active_run_id = run_id
        self._active_code_version = code_version
        self._active_param_version = param_version
        # Whole-object pointer-flip — the new frozen PinnedParams replaces the old.
        self._active_params = params
        # The pending selection (if any) is now adopted/consumed.
        self._pending_selected_version = None

    # -- version-pinned open/close (Req 8.2 / 8.3) --------------------------- #

    def record_open(self, venue_position_id: str) -> PositionVersion:
        """Associate a newly-opened position with the ACTIVE version (Req 8.2).

        Records the (code_version, param_version) in effect at open time as the
        position's opening version (retained for its lifetime) and writes an
        ``opened`` version-pin row via the injected writer. Returns the pinned
        :class:`PositionVersion`.
        """
        version = PositionVersion(
            run_id=self._active_run_id,
            code_version=self._active_code_version,
            param_version=self._active_param_version,
        )
        self._open_versions[venue_position_id] = version
        self._emit_version_pin(venue_position_id, version, event="opened")
        return version

    def record_close(self, venue_position_id: str) -> PositionVersion:
        """Close a position, pinning its OPENING version (Req 8.3).

        Writes a ``closed`` version-pin row carrying the position's **opening**
        version (not the active version — a position closed after a hot-swap still
        pins the version it was opened under) and forgets the open record. Raises
        ``KeyError`` if the position was never opened through this manager (the
        manager never invents a version — that would corrupt the version-pinned
        lifetime).
        """
        version = self._open_versions.pop(venue_position_id)
        self._emit_version_pin(venue_position_id, version, event="closed")
        return version

    def version_for_position(self, venue_position_id: str) -> PositionVersion:
        """The OPENING version a still-open position is managed under (Req 8.3).

        Raises ``KeyError`` for a position never opened through this manager — the
        manager never fabricates a version (managing a position under an invented
        version would corrupt its lifecycle).
        """
        return self._open_versions[venue_position_id]

    def open_position_versions(self) -> tuple[PositionVersion, ...]:
        """The opening versions of every currently-open position.

        The input to :func:`global_tightest` when more than one version coexists
        (Req 8.4) — the caller resolves each ``PositionVersion`` to its pinned
        ``SurvivalParameters`` and folds them to the globally-tightest.
        """
        return tuple(self._open_versions.values())

    # -- internal --------------------------------------------------------------

    def _emit_version_pin(
        self, venue_position_id: str, version: PositionVersion, *, event: str
    ) -> None:
        """Write one ``execution_daemon_position_version`` row via the injected
        writer (no-op when no writer was wired — in-memory inner-ring tracking)."""
        if self._write_version_pin is None:
            return
        self._write_version_pin(
            run_id=version.run_id,
            venue_position_id=venue_position_id,
            code_version=version.code_version,
            param_version=version.param_version,
            event=event,
        )
