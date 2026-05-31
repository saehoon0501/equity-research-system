"""The persistent fast-clock evaluation loop (task 4.4).

Boundary: ``loop`` (Requirements 1, 5, 7, 9). Source of truth:
``.kiro/specs/execution-daemon/design.md`` §"System Flows" (the per-tick
sequence, lines 174-216) + §"Control — ``loop``" (line 367: "single-eval-at-a-
time; **polls intake first**, then ``assess`` within cadence + on margin-material
events; fail-toward-minimum-exposure on dependency error") + the
Requirements-Traceability rows 1.x / 5.x / 7.3 / 9.x.

What this module is
-------------------
The daemon's **single-threaded blocking evaluation loop** — the only persistent
process shape in the repo. It wraps the §13 gate-orchestrator (``orchestrator``),
the command surface (``commands``), and the de-risk action (``lifecycle``) on one
owned psycopg3 connection serialized through the loop. Per tick it runs, *in this
fixed order*:

  1. **Poll the command intake FIRST** (design §System-Flows "Key decisions":
     the command intake is polled first each cycle so a just-issued kill-switch /
     safe-mode is observed before any admit) — op-state freshness extended to the
     out-of-process transport (Req 5.2/7.3).
  2. **Read operational state fresh** (Req 5.2 — never a pinned copy; the just-
     applied command is read on this same tick).
  3. **Run the Survive standing monitor (Phase 1, ``orchestrator.run_assess``)** —
     every tick (Req 1.2). It yields the op-state transition + de-risk directives
     + events **without acting on them**.
  4. **PERSIST the op-state transition + events DURABLY** (``persist_op_state``,
     inside the owned conn's transaction) — **before** any directive is executed
     or any order is admitted (persist-then-act, Req 5.1). This is the seam the
     4.4 reviewer flagged: the standing-monitor transition is committed to durable
     storage (``survival_gate_state`` / ``survival_gate_events``) before the
     per-order admit/submit path runs, so a just-engaged kill switch / safe-mode
     escalation can never be bypassed by an in-flight admit. If the persist itself
     fails, persist-then-act is a **hard gate**: the edge path does NOT run (no
     admit, no open submitted) — fail toward minimum exposure (Req 1.5/5.1).
  5. **Run the edge path (Phase 2, ``orchestrator.run_edge_path``)** — *only after*
     the persist committed: derive permit → ``candidate`` → ``decide`` →
     ``order_builder`` → per-order ``admit``. The op-state the permit + admit read
     is the just-persisted one.
  6. **Execute the assess de-risk directives** (``lifecycle`` flatten/reduce) —
     these ALWAYS flow (a true exit / reduce / flatten is never blocked, Req 7.2).
  7. On any **dependency error** during step 5 (the edge/order/admit path): **fail
     toward minimum exposure** (Req 1.5) — reject any opening order (no submit),
     but STILL execute the de-risk directives and record the failure. The de-risk
     path is computed from the Phase-1 ``assess`` (run + persisted before the
     failing edge path) so a reduce/flatten is never lost to an edge-side blowup.

Single-eval-at-a-time (Req 1.1): the loop is single-threaded and blocking — each
:func:`run_cycle` completes its read-modify-write of op-state before the next
begins; there is no concurrency, no asyncio, no pool (the all-sync deps + the
op-state-freshness guarantee mandate this shape, design §Architecture-Pattern).

Cadence + margin-material trigger (Req 1.2/1.3): :func:`should_run_now` is the
pure scheduler predicate — run when the cadence has elapsed OR a margin-material
event is pending (the latter triggers an out-of-cadence cycle, Req 1.3).

Inner-ring testable (P14): :func:`run_cycle` takes every dep as an **injected
callable** (``poll_commands`` / ``read_op_state`` / ``assemble`` / ``decide`` /
``build_order`` / ``get_positions`` / ``admit`` / ``assess`` / ``persist_op_state``
/ ``submit_order`` / ``execute_de_risk`` / ``record_failure``), so the loop logic
— including the **persist-then-act ordering** (the op-state transition is persisted
before admit/submit) — is exercised with synthetic state + the REAL pure
``survival.admit`` / ``assess`` (no DB, no MCP, no LLM). :func:`build_and_run`
wires the real deps against the owned connection: the **live**
``survival_gate_state`` / ``survival_gate_events`` persist **and** the broker /
market-feed venue handles (``feed.MassiveRestFeed`` + the ``broker_seam``
``submit_decision`` / ``get_positions`` / ``get_account_assets`` readouts), driving
real PAPER ticks end-to-end (PAPER-ONLY by construction — every submit pins the
default ``RuntimeMode()`` so ``live_transmit_allowed()`` is False; see the
``build_and_run`` note).

Pure-leaf control (P1): stdlib + the daemon-owned components only — no MCP, no
LLM dispatch, no decision logic of its own (it orchestrates + emits, Req 10).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import (
    AbstractSet,
    Any,
    Callable,
    MutableMapping,
    Optional,
    Sequence,
)

from src.reactive.daemon.candidate import MarketFeed, NonDirectionalReason
from src.reactive.daemon.orchestrator import (
    OrchestrationOutcome,
    run_assess,
    run_edge_path,
)
from src.reactive.daemon.types import (
    Candidate,
    EpochContext,
    ProposedOrder,
)
from src.reactive.types import ReactiveDecision
from src.survival.params import SurvivalParameters
from src.survival.types import (
    AccountState,
    AdmitDecision,
    AssessDirective,
    ClockState,
    OperationalState,
    OrderEvaluation,
    ProposedOrder as SurvivalProposedOrder,
)

__all__ = [
    "CycleOutcome",
    "should_run_now",
    "run_cycle",
    "run",
    "persist_op_state_transition",
    "read_op_state_fresh",
    "build_and_run",
]


# --------------------------------------------------------------------------- #
# Live persist-then-act writer (Req 5.1/5.4) — the durable op-state persist.    #
# --------------------------------------------------------------------------- #
#
# The op-state transition the Survive standing monitor emits is written to the
# survival package's caller-side tables (migration 049): the events to the
# append-only ``survival_gate_events`` log, and the next op-state to the monotonic
# singleton ``survival_gate_state``. The whole write runs in ONE
# ``conn.transaction()`` so the transition is committed atomically BEFORE the loop
# runs the per-order admit/submit path (persist-then-act, Req 5.1). The gate's own
# ``assess`` guarantees ``next_op_state`` is monotonic-tighten, so the
# ``survival_gate_state`` UPDATE never trips the migration-049 monotonic guard.

# Insert one append-only ``survival_gate_events`` row per emitted SurvivalEvent.
_INSERT_GATE_EVENT_SQL = """
    INSERT INTO survival_gate_events (run_id, ticker, event_type, account_snapshot)
    VALUES (%s, %s, %s, %s::jsonb)
    RETURNING event_id
"""

# Upsert the monotonic ``survival_gate_state`` singleton (scope='default') to the
# next op-state. INSERT … ON CONFLICT DO UPDATE so the first-ever transition seeds
# the row and subsequent ones tighten it (the migration-049 monotonic guard fires
# on the UPDATE path; ``assess`` guarantees a tighten so it passes).
_UPSERT_GATE_STATE_SQL = """
    INSERT INTO survival_gate_state (scope, safe_mode_grade, kill_switch_engaged)
    VALUES ('default', %s, %s)
    ON CONFLICT (scope) DO UPDATE
        SET safe_mode_grade = EXCLUDED.safe_mode_grade,
            kill_switch_engaged = EXCLUDED.kill_switch_engaged,
            entered_at = now()
"""

# The survival event_type vocabulary the migration-049 CHECK permits.
_SURVIVAL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "margin_breach",
        "forced_liquidation",
        "safe_mode_entered",
        "kill_switch_engaged",
        "flatten_directive",
        "flat_verify_failed",
    }
)


def persist_op_state_transition(
    conn: Any, *, run_id: str, directive: AssessDirective
) -> None:
    """Durably persist a Survive-standing-monitor transition (Req 5.1/5.4).

    Writes, in ONE ``conn.transaction()`` (so the whole transition commits
    atomically before any directive/admit acts — persist-then-act, Req 5.1):

      1. **Each ``directive.events`` :class:`SurvivalEvent`** as one append-only
         ``survival_gate_events`` row (Req 5.4 — every survival event + transition
         to an append-only record). ``account_snapshot`` is JSON-serialized.
      2. **The ``directive.next_op_state``** into the monotonic
         ``survival_gate_state`` singleton (``scope='default'``) via
         ``INSERT … ON CONFLICT DO UPDATE`` — the safe-mode grade + kill-switch
         flag. ``assess`` guarantees a monotonic-tighten, so the migration-049
         guard never rejects it.

    This is the **live wiring** of the loop's ``persist_op_state`` seam: it is the
    callable :func:`build_and_run` passes into :func:`run_cycle`, partially applied
    with the owned ``conn`` + the epoch ``run_id``. A failure here propagates to
    the loop, which treats it as the persist-then-act **hard gate** (the edge path
    is skipped — a transition that could not be durably recorded must never be
    bypassed by an in-flight admit).

    Args:
        conn: the daemon's single owned psycopg connection (``db.DaemonConnection``).
        run_id: the epoch's ``run_id`` (``execution_daemon_epoch.epoch_id``, P3) —
            the ``survival_gate_events.run_id`` correlation key.
        directive: the Phase-1 :class:`AssessDirective` (its ``next_op_state`` +
            ``events`` are persisted; the ``reduce_directives`` are the *action*
            the loop executes after, not persisted here).
    """
    import json

    next_op_state = directive.next_op_state
    with conn.transaction():
        with conn.cursor() as cur:
            for event in directive.events:
                if event.event_type not in _SURVIVAL_EVENT_TYPES:
                    # Defense in depth (P6): an unexpected event_type would trip
                    # the migration-049 CHECK; surface it as a clear error rather
                    # than a raw constraint violation. A contract violation, not a
                    # routine path.
                    raise ValueError(
                        f"persist_op_state_transition: unknown survival event_type "
                        f"{event.event_type!r}; expected one of "
                        f"{sorted(_SURVIVAL_EVENT_TYPES)}"
                    )
                cur.execute(
                    _INSERT_GATE_EVENT_SQL,
                    (
                        run_id,
                        event.ticker,
                        event.event_type,
                        json.dumps(event.account_snapshot),
                    ),
                )
                cur.fetchone()  # consume RETURNING to confirm the write
            cur.execute(
                _UPSERT_GATE_STATE_SQL,
                (
                    next_op_state.safe_mode_grade,
                    next_op_state.kill_switch_engaged,
                ),
            )


# --------------------------------------------------------------------------- #
# The structured per-cycle outcome.                                            #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CycleOutcome:
    """The result of one loop cycle — what the persistent loop / tests inspect.

    ``assess_directive`` is the Survive standing-monitor result (the op-state
    transition + de-risk directives + events). ``admitted_order`` is the daemon
    ``ProposedOrder`` that cleared ``admit`` and was submitted (``None`` when
    nothing was admitted — blocked open / HOLD / no candidate / persistent reject
    / a dependency failure). ``declined`` is True on a HOLD / no-candidate
    evaluation. ``de_risk_executed`` is True when the assess de-risk directives
    were run this cycle (they ALWAYS run when present, even on a failure — Req
    7.2/1.5). ``failed`` is True when a dependency error forced the fail-toward-
    minimum-exposure path (the open was rejected; the failure was recorded —
    Req 1.5). ``failure_reason`` carries the recorded reason on a failure.
    ``non_directional_reason`` attributes a no-candidate skip to 12.5 vs 12.4.
    """

    assess_directive: Optional[AssessDirective]
    admitted_order: Optional[ProposedOrder]
    declined: bool
    de_risk_executed: bool
    failed: bool
    failure_reason: Optional[str]
    non_directional_reason: Optional[NonDirectionalReason]


# --------------------------------------------------------------------------- #
# The scheduler predicate (pure — Req 1.2 cadence + Req 1.3 margin-material).   #
# --------------------------------------------------------------------------- #


def should_run_now(
    *,
    elapsed_seconds: float,
    cadence_seconds: float,
    margin_material_event: bool,
) -> bool:
    """Whether the next evaluation cycle should run now (Req 1.2/1.3).

    Pure scheduler predicate: a cycle runs when **either** the cadence interval
    has elapsed (the standing-monitor max-latency bound, Req 1.2 — the assess
    cadence is honored even with no order contemplated) **or** a margin-material
    event is pending (Req 1.3 — a margin-material event triggers an out-of-cadence
    cycle without waiting for the next interval). Keeping it pure (no clock read)
    makes the cadence/trigger logic inner-ring testable.
    """
    if margin_material_event:
        return True
    return elapsed_seconds >= cadence_seconds


# --------------------------------------------------------------------------- #
# One evaluation cycle — the single-eval-at-a-time unit (Req 1.1/1.5/5.2).      #
# --------------------------------------------------------------------------- #


def run_cycle(
    *,
    symbol: str,
    epoch: EpochContext,
    survival_params: SurvivalParameters,
    clock: ClockState,
    account: AccountState,
    feed: MarketFeed,
    universe: AbstractSet[str],
    leverage: Optional[float],
    is_excluded: Optional[bool],
    stop_loss_atr_mult: float,
    op_state_holder: MutableMapping[str, OperationalState],
    poll_commands: Callable[[MutableMapping[str, OperationalState]], Any],
    read_op_state: Callable[[], OperationalState],
    assemble: Callable[..., Optional[Candidate]],
    decide: Callable[..., ReactiveDecision],
    build_order: Callable[..., Optional[ProposedOrder]],
    get_positions: Callable[[], Sequence[Any]],
    admit: Callable[
        [
            SurvivalProposedOrder,
            AccountState,
            OperationalState,
            SurvivalParameters,
            ClockState,
            OrderEvaluation,
        ],
        AdmitDecision,
    ],
    assess: Callable[
        [AccountState, OperationalState, SurvivalParameters, ClockState],
        AssessDirective,
    ],
    persist_op_state: Callable[[AssessDirective], Any],
    submit_order: Callable[[ProposedOrder], Any],
    execute_de_risk: Callable[[Sequence[Any], AccountState], Any],
    record_failure: Callable[[str], Any],
) -> CycleOutcome:
    """Run exactly one evaluation cycle (single-eval-at-a-time, Req 1.1).

    The fixed per-tick order (design §System-Flows):

      1. **Poll the command intake FIRST** — a just-issued kill-switch/safe-mode
         is applied to ``op_state_holder`` before anything reads op-state
         (Req 5.2/7.3 — intake polled first).
      2. **Read op-state fresh** from the holder (never a pinned copy, Req 5.2) —
         so the just-applied command is observed on THIS tick.
      3. **Run the Survive standing monitor (Phase 1, ``run_assess``)** every tick
         (Req 1.2). It yields the op-state transition + de-risk directives + events
         without acting on them.
      4. **PERSIST the op-state transition + events DURABLY** (``persist_op_state``)
         **before** any directive is executed or any order is admitted
         (persist-then-act, Req 5.1). A persist failure is a **hard gate**: the
         edge path does not run (no admit, no open submitted) — fail toward
         minimum exposure. The de-risk directives still flow (Req 1.5/7.2).
      5. **Run the edge path (Phase 2, ``run_edge_path``)** *only after* the persist
         committed — candidate → decide → build → admit; permitted-or-true-exit
         gates the build.
      6. **Execute the assess de-risk directives** (flatten/reduce) — these
         ALWAYS flow (Req 7.2 — a true exit / reduce / flatten is never blocked).
      7. **Submit the admitted order** (the paper-lifecycle driver is wired as
         ``submit_order``). On a dependency error in the edge path, fail toward
         minimum exposure (Req 1.5): reject the open (no submit), still run the
         de-risk directives, record the failure.

    The deps are injected so this is inner-ring-testable with synthetic state +
    the REAL pure ``admit`` / ``assess`` (P14) and a recording ``persist_op_state``
    that proves the persist write happens BEFORE admit. The op-state
    read-modify-write is contiguous and completes before the caller begins the next
    cycle (the single-threaded loop never overlaps two evaluations, Req 1.1).

    Args:
        persist_op_state: the **persist-then-act** seam (Req 5.1) — durably persists
            the Phase-1 ``AssessDirective``'s ``next_op_state`` transition + its
            ``events`` (to ``survival_gate_state`` / ``survival_gate_events`` via
            the owned conn, inside a transaction) **before** the edge path's admit
            runs. The loop wires the live writer; tests pass a recording callable
            that asserts the write precedes ``admit``. A raise from here is a hard
            gate — the edge path is skipped (fail toward minimum exposure).

    Returns:
        A :class:`CycleOutcome` (the assess directive + the admitted order /
        declined / de-risk-executed / failed flags).
    """
    # ----- Step 1: poll command intake FIRST (Req 5.2/7.3). -------------------
    # The out-of-process commander's just-issued kill-switch/safe-mode is applied
    # to op_state_holder here, BEFORE op-state is read — so it is observed on this
    # same tick's admit (op-state freshness extended to the intake transport).
    poll_commands(op_state_holder)

    # ----- Step 2: read op-state FRESH (Req 5.2 — never a pinned copy). -------
    op_state = read_op_state()

    assess_directive: Optional[AssessDirective] = None
    admitted_order: Optional[ProposedOrder] = None
    declined = False
    failed = False
    failure_reason: Optional[str] = None
    non_directional_reason: Optional[NonDirectionalReason] = None

    # ----- Step 3 (Phase 1): the Survive standing monitor (assess) — Req 1.2. -
    # Run FIRST and capture the op-state transition WITHOUT acting on it. The
    # de-risk path needs this directive REGARDLESS of whether the edge path
    # (candidate/decide/build/admit) succeeds, so it is obtained before — and
    # persisted before — the act (Req 1.5: never block a true exit / reduce /
    # flatten).
    try:
        assess_directive = run_assess(
            op_state=op_state,
            account=account,
            survival_params=survival_params,
            clock=clock,
            assess=assess,
        )
    except Exception as assess_exc:  # noqa: BLE001 — defense in depth (P6/Req 1.5)
        # Even the standing monitor failed — there is no transition to persist and
        # no de-risk directive to execute. Fail toward minimum exposure: record the
        # failure and skip the persist + edge + de-risk steps (no open submitted).
        failed = True
        failure_reason = (
            f"assess failed: {type(assess_exc).__name__}: {assess_exc}"
        )
        record_failure(failure_reason)
        return CycleOutcome(
            assess_directive=None,
            admitted_order=None,
            declined=False,
            de_risk_executed=False,
            failed=True,
            failure_reason=failure_reason,
            non_directional_reason=None,
        )

    # ----- Step 4: PERSIST-THEN-ACT — durably persist the transition FIRST. ---
    # Req 5.1: persist the operational-state transition (and its events) BEFORE
    # executing any directive or admitting any order. The persist runs here,
    # strictly between the standing monitor (Phase 1) and the per-order admit
    # (Phase 2 / Step 5). A persist failure is a HARD GATE: do NOT run the edge
    # path (no admit, no open submitted) — a just-engaged kill switch that could
    # not be durably recorded must never be bypassed by an in-flight admit
    # (Req 5.1). The de-risk directives still flow below (Req 1.5/7.2 — a reduce/
    # flatten is never blocked).
    persist_failed = False
    try:
        persist_op_state(assess_directive)
    except Exception as persist_exc:  # noqa: BLE001 — persist-then-act hard gate
        persist_failed = True
        failed = True
        failure_reason = (
            f"op-state persist failed (persist-then-act hard gate; edge path "
            f"skipped): {type(persist_exc).__name__}: {persist_exc}"
        )
        record_failure(failure_reason)

    # ----- Step 5 (Phase 2): the edge path — ONLY after the persist committed. -
    # Skipped entirely on a persist failure (the hard gate above). On a dependency
    # error inside the edge path, fail toward minimum exposure: reject the open
    # (admitted_order stays None), still run the de-risk directives below.
    if not persist_failed:
        try:
            outcome: OrchestrationOutcome = run_edge_path(
                symbol=symbol,
                epoch=epoch,
                op_state=op_state,
                account=account,
                survival_params=survival_params,
                clock=clock,
                feed=feed,
                universe=universe,
                leverage=leverage,
                is_excluded=is_excluded,
                stop_loss_atr_mult=stop_loss_atr_mult,
                assess_directive=assess_directive,
                assemble=assemble,
                decide=decide,
                build_order=build_order,
                get_positions=get_positions,
                admit=admit,
            )
            admitted_order = outcome.admitted_order
            declined = outcome.declined
            non_directional_reason = outcome.non_directional_reason
        except Exception as exc:  # noqa: BLE001 — fail toward minimum exposure (Req 1.5)
            # A dependency error mid-edge-path. Fail toward minimum exposure:
            # reject any opening order (admitted_order stays None — nothing is
            # submitted), but STILL run the de-risk directives below so a true exit
            # / reduce / flatten is never blocked by the failure (Req 1.5/7.2). The
            # assess directive (already persisted) drives that de-risk path.
            failed = True
            failure_reason = f"{type(exc).__name__}: {exc}"
            record_failure(failure_reason)

    # ----- Step 6 (always): execute the assess de-risk directives. -----------
    # FLATTEN / REDUCE / FREEZE_ENTRIES from assess are de-risk actions that must
    # ALWAYS flow — they net-reduce exposure (Req 7.2), so they run on a healthy
    # cycle AND on a failed one (a dependency error never blocks a reduce/flatten,
    # Req 1.5). A None assess_directive (assess itself failed) skips this.
    de_risk_executed = False
    if assess_directive is not None and assess_directive.reduce_directives:
        execute_de_risk(assess_directive.reduce_directives, account)
        de_risk_executed = True

    # ----- Step 7: submit the admitted order (paper lifecycle). --------------
    # Only an order that cleared admit on a healthy edge path reaches here; a
    # failed cycle (or a persist-then-act hard gate) has admitted_order=None, so
    # no open is submitted (Req 1.5/5.1).
    if admitted_order is not None:
        submit_order(admitted_order)

    return CycleOutcome(
        assess_directive=assess_directive,
        admitted_order=admitted_order,
        declined=declined,
        de_risk_executed=de_risk_executed,
        failed=failed,
        failure_reason=failure_reason,
        non_directional_reason=non_directional_reason,
    )


# --------------------------------------------------------------------------- #
# The persistent loop driver (cadence + single-eval serialization).            #
# --------------------------------------------------------------------------- #


def run(
    *,
    run_one_cycle: Callable[[], CycleOutcome],
    cadence_seconds: float,
    margin_material_pending: Callable[[], bool],
    should_continue: Callable[[], bool],
    sleep: Callable[[float], Any] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Drive the persistent single-threaded loop (Req 1.1/1.2/1.3).

    Blocking + single-threaded: it runs **one** ``run_one_cycle`` at a time, never
    overlapping two evaluations (Req 1.1 — op-state read-modify-write completes
    before the next begins, guaranteed by the serial call). Between cycles it
    waits up to the cadence interval, but runs immediately on a margin-material
    event (:func:`should_run_now`, Req 1.2/1.3).

    The cycle body, the continue predicate, the margin-material check, and the
    clock/sleep are all **injected** so the driver itself is inner-ring testable
    (a bounded ``should_continue`` + a fake clock drives a deterministic finite
    run with no real sleep). The real wiring lives in :func:`build_and_run`.

    Args:
        run_one_cycle: runs exactly one evaluation cycle (the wired
            :func:`run_cycle`). Called serially — never concurrently.
        cadence_seconds: the standing-monitor max-latency interval (Req 1.2).
        margin_material_pending: True when a margin-material event is pending
            (forces an out-of-cadence cycle, Req 1.3).
        should_continue: the loop liveness predicate — False halts the loop
            (a real daemon returns True until a shutdown signal; tests bound it).
        sleep: the inter-cycle wait (injected; defaults to ``time.sleep``).
        monotonic: the monotonic clock (injected; defaults to ``time.monotonic``).
    """
    last_run = monotonic()
    # Run the first cycle immediately on entry (the standing monitor must start).
    first = True
    while should_continue():
        now = monotonic()
        elapsed = now - last_run
        if first or should_run_now(
            elapsed_seconds=elapsed,
            cadence_seconds=cadence_seconds,
            margin_material_event=margin_material_pending(),
        ):
            run_one_cycle()
            last_run = monotonic()
            first = False
        else:
            # Wait the remaining cadence before re-checking (bounded so a
            # margin-material event is observed within the cadence).
            remaining = max(0.0, cadence_seconds - elapsed)
            sleep(remaining if remaining > 0 else cadence_seconds)


# --------------------------------------------------------------------------- #
# The wired entrypoint helper (build conn + config; run). Restart-safe.        #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Live op-state read (Req 5.2) — fresh ``survival_gate_state`` read each tick.   #
# --------------------------------------------------------------------------- #
#
# The standing-monitor op-state is read FRESH every tick from the monotonic
# ``survival_gate_state`` singleton (scope='default', migration 049) — never a
# pinned copy (Req 5.2). On a fresh DB the singleton row does not yet exist (the
# first persist-then-act write seeds it); the read then returns the safe-default
# permissive op-state (kill_switch off, grade NONE), which the very-first persist
# seeds durably. This is the same op-state the deterministic kill-switch reflex
# keys off (``orchestrator.new_exposure_permitted`` reads it fresh each tick).

_SELECT_GATE_STATE_SQL = """
    SELECT safe_mode_grade, kill_switch_engaged, entered_at, triggered_by_event_id
    FROM survival_gate_state
    WHERE scope = 'default'
"""


def read_op_state_fresh(conn: Any) -> OperationalState:
    """Read the current operational state FRESH from ``survival_gate_state`` (Req 5.2).

    A single SELECT of the monotonic singleton (``scope='default'``) inside a
    short transaction, mapped to a survival ``OperationalState``. When the row does
    not yet exist (a fresh DB before the first persist-then-act write seeds it),
    returns the **safe-default permissive** op-state (kill-switch off, grade NONE):
    the first standing-monitor transition then seeds the durable row. This is the
    op-state the loop reads each tick *after* the intake poll, so a just-issued
    kill-switch is observed on the same tick (the out-of-process command channel is
    a no-op in v0.1, but a directly-written ``survival_gate_state`` tighten — e.g.
    from a prior tick's persist — is still picked up fresh).
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(_SELECT_GATE_STATE_SQL)
            row = cur.fetchone()

    if row is None:
        # Fresh DB: no singleton yet. Safe-default permissive op-state — the first
        # persist-then-act write seeds the durable row.
        return OperationalState(
            kill_switch_engaged=False,
            safe_mode_grade="NONE",
            entered_at=None,
            triggered_by=None,
        )

    safe_mode_grade, kill_switch_engaged, entered_at, triggered_by_event_id = row
    return OperationalState(
        kill_switch_engaged=bool(kill_switch_engaged),
        safe_mode_grade=safe_mode_grade,
        entered_at=entered_at,
        triggered_by=(
            str(triggered_by_event_id) if triggered_by_event_id is not None else None
        ),
    )


def _noop_poll_commands(op_state_holder: Any) -> None:
    """The v0.1 NO-OP command-intake poll (locked decision).

    v0.1 wires **no** out-of-process SQL ``IntakeTransport``: the command channel
    is a no-op. This is NOT the kill-switch reflex — the deterministic op-state
    kill-switch reflex still works unchanged (the loop reads ``survival_gate_state``
    fresh each tick via :func:`read_op_state_fresh` and derives
    ``new_exposure_permitted`` from it). Only the out-of-process command transport
    is the no-op; a real ``IntakeTransport`` is a tracked follow-on.
    """
    return None


def build_and_run(
    *,
    code_version: str = "execution-daemon-v0.1",
    param_version: str = "bootstrap",
    config: Any = None,
    conn: Any = None,
    feed: Any = None,
    submit_decision: Any = None,
    get_positions: Any = None,
    get_account_assets: Any = None,
    account_activated: Any = None,
    should_continue: Optional[Callable[[], bool]] = None,
    margin_material_pending: Optional[Callable[[], bool]] = None,
) -> int:
    """Build the owned connection + config, pin the epoch, wire the **live DB
    persist-then-act path + the broker/feed venue handles**, and run the
    persistent loop.

    This is the entrypoint the process (``python -m src.reactive.daemon``) calls.
    It opens the daemon's single owned psycopg3 connection (``db.DaemonConnection``)
    from the env-resolved ``DaemonConfig`` (``config._dsn()``), mints the startup
    epoch (``params.resolve_epoch`` against the **live** ``parameters_active``,
    writing the ``execution_daemon_epoch`` row), wires the **live**
    ``persist_op_state`` writer (``persist_op_state_transition`` bound to the owned
    conn + epoch ``run_id``), then binds the **venue handles** and drives the loop:

      * **market feed** — ``feed.MassiveRestFeed(config)`` (the concrete 3-leg
        fast-clock ``MarketFeed``; §14.10, accessed directly, not via MCP).
      * **broker** — ``broker.submit_decision`` / ``broker.get_positions`` /
        ``broker.get_account_assets`` via the daemon's single ``broker_seam``.
      * **survival params** — ``survival.params.resolve`` of the **pinned**
        ``epoch.pinned_params.survival_snapshot`` (a by-value resolve of the pin,
        NOT a live re-read — P2-safe).
      * **op-state** — read FRESH each tick from ``survival_gate_state`` (Req 5.2).
      * **AccountState + ClockState** — assembled FRESH each tick from the broker
        readouts via ``account_state`` (Req 5.2 freshness; Req 10.2 input assembly,
        not a survival recompute).

    **PAPER-ONLY, hard-pinned (locked decision).** Every ``submit_decision`` (the
    open lifecycle + the de-risk de-risk path) is driven under the **default**
    ``RuntimeMode()`` — ``paper_enabled=True`` + all four live clearances ``False``
    — so the broker routes to the paper simulator and ``live_transmit_allowed()``
    is False **by construction**. This function constructs no ``RuntimeMode`` with
    any live clearance; v0.1 has no reachable live transmit path.

    **SINGLE-SYMBOL (v0.1).** One ``config.symbol`` target, no watchlist rotation.

    **COMMAND-INTAKE = NO-OP (v0.1).** ``poll_commands`` is a no-op
    (:func:`_noop_poll_commands`) — no out-of-process SQL ``IntakeTransport`` is
    wired. The deterministic op-state kill-switch reflex is unchanged (op-state read
    fresh each tick + ``new_exposure_permitted``); only the command channel is a
    no-op.

    Restart-safe: the connection lifecycle is a context manager (opened here,
    closed on exit), the epoch is re-minted on each process start, and all durable
    state is in the append-only DB tables — a crash + restart re-pins a fresh epoch
    and resumes from the persisted op-state (no in-memory state survives a restart,
    by design — the daemon is a leaf executor, Req 10).

    Args:
        code_version / param_version: the epoch identity stamped onto the pinned
            params + the trace correlation keys (P3). v0.1 bootstrap defaults until
            the tuner publishes a promoted version.
        config / conn / feed / submit_decision / get_positions /
        get_account_assets / account_activated / should_continue /
        margin_material_pending: **injection seams** (P14) — all ``None`` in
            production (the real config / owned conn / ``MassiveRestFeed`` / broker
            seam / a forever-True ``should_continue`` are constructed here). The
            ``integration_live`` bounded-drive test injects a mock-transport feed +
            broker + a 1-2-tick-bounded ``should_continue`` so the production wiring
            is exercised end-to-end with no live venue. When a live ``conn`` is
            injected the caller owns its lifecycle (this function does not close an
            injected conn); a ``None`` conn opens (and closes) the owned one.

    Returns:
        A process exit code (0 on a clean shutdown).
    """
    # Imported here (not at module top) so importing ``loop`` for the inner-ring
    # unit tests pulls in no DB / broker / feed machinery — the wiring deps are
    # only needed when the real process actually starts (P14: the loop logic is
    # testable without them). The config build is a pure env read (opens no
    # connection — db.py owns the connection lifecycle).
    from functools import partial

    from src.reactive.daemon import account_state as account_state_mod
    from src.reactive.daemon import broker_seam
    from src.reactive.daemon import candidate as candidate_mod
    from src.reactive.daemon import lifecycle as lifecycle_mod
    from src.reactive.daemon import order_builder as order_builder_mod
    from src.reactive.daemon import params as params_mod
    from src.reactive.daemon.config import DaemonConfig
    from src.reactive.daemon.db import DaemonConnection
    from src.reactive.daemon.feed import MassiveRestFeed
    from src.reactive.daemon.orchestrator import (
        PaperSendGuard,
        drive_paper_lifecycle,
    )
    from src.reactive import signal_model
    from src.survival import gate as survival_gate
    from src.survival import params as survival_params_mod

    config = config if config is not None else DaemonConfig.from_env()

    # The venue handles — injectable for the integration_live bounded drive, else
    # the production seam objects. PAPER-ONLY: the paper RuntimeMode() is pinned at
    # every submit below (never constructed with a live clearance).
    feed = feed if feed is not None else MassiveRestFeed(config)
    submit_decision = (
        submit_decision if submit_decision is not None else broker_seam.submit_decision
    )
    get_positions = (
        get_positions if get_positions is not None else broker_seam.get_positions
    )
    get_account_assets = (
        get_account_assets
        if get_account_assets is not None
        else broker_seam.get_account_assets
    )
    account_activated = (
        account_activated
        if account_activated is not None
        else broker_seam.account_activated
    )

    def _run_with_conn(conn: Any) -> int:
        return _drive(
            conn=conn,
            config=config,
            code_version=code_version,
            param_version=param_version,
            feed=feed,
            submit_decision=submit_decision,
            get_positions=get_positions,
            get_account_assets=get_account_assets,
            account_activated=account_activated,
            should_continue=should_continue,
            margin_material_pending=margin_material_pending,
            params_mod=params_mod,
            account_state_mod=account_state_mod,
            candidate_mod=candidate_mod,
            lifecycle_mod=lifecycle_mod,
            order_builder_mod=order_builder_mod,
            signal_model=signal_model,
            survival_gate=survival_gate,
            survival_params_mod=survival_params_mod,
            drive_paper_lifecycle=drive_paper_lifecycle,
            PaperSendGuard=PaperSendGuard,
            partial=partial,
        )

    # When a live ``conn`` is injected the caller owns its lifecycle; otherwise the
    # owned connection is opened + closed here (restart-safe context manager).
    if conn is not None:
        return _run_with_conn(conn)
    with DaemonConnection(config) as owned_conn:
        return _run_with_conn(owned_conn)


def _drive(
    *,
    conn: Any,
    config: Any,
    code_version: str,
    param_version: str,
    feed: Any,
    submit_decision: Any,
    get_positions: Any,
    get_account_assets: Any,
    account_activated: Any,
    should_continue: Optional[Callable[[], bool]],
    margin_material_pending: Optional[Callable[[], bool]],
    params_mod: Any,
    account_state_mod: Any,
    candidate_mod: Any,
    lifecycle_mod: Any,
    order_builder_mod: Any,
    signal_model: Any,
    survival_gate: Any,
    survival_params_mod: Any,
    drive_paper_lifecycle: Any,
    PaperSendGuard: Any,
    partial: Any,
) -> int:
    """Pin the epoch, wire every real dep against ``conn``, and run the loop.

    The single place the venue handles + the live DB persist + the survival pure
    core are wired into the loop's injected-callable seam (so the wiring is exactly
    what the inner-ring ``run_cycle`` test exercises, only with the REAL deps). The
    epoch mint is a live ``parameters_active`` REPEATABLE-READ read + an
    ``execution_daemon_epoch`` INSERT.
    """
    # The paper RuntimeMode source (Req 3.1 paper-only — default ``RuntimeMode()``
    # is paper-on + all live clearances safe-off, ``live_transmit_allowed()`` False
    # by construction). Imported here so ``_drive`` pins it at every submit.
    from src.reactive.daemon import broker_seam

    # ----- pin the epoch (live parameters_active read + epoch-row write). -----
    epoch = params_mod.resolve_epoch(
        conn, code_version=code_version, param_version=param_version
    )

    # ----- the live persist-then-act writer (Req 5.1). ------------------------
    persist_op_state = partial(_persist_op_state_for_epoch, conn, epoch.run_id)

    # ----- survival params: by-value resolve of the PINNED snapshot (P2). -----
    # NOT a live re-read of parameters_active — the pinned ``survival_snapshot``
    # carried on the epoch (resolved once under REPEATABLE READ at the pin) is
    # resolved by value into ``SurvivalParameters`` here, so the survival walk runs
    # against the pinned ground truth, never mid-run live state.
    survival_params = survival_params_mod.resolve(epoch.pinned_params.survival_snapshot)

    # ----- the paper double-send guard (one across all ticks, Req 3.4). -------
    paper_guard = PaperSendGuard()

    def _submit_order(order: Any) -> Any:
        """Drive an admitted daemon order through the PAPER lifecycle (Req 3).

        PAPER-ONLY: the default ``RuntimeMode()`` is pinned (``paper_enabled=True``
        ⇒ ``live_transmit_allowed()`` False by construction) so the broker routes
        to the paper simulator — there is no reachable live POST.
        """
        return drive_paper_lifecycle(
            order,
            submit_decision=submit_decision,
            guard=paper_guard,
            runtime_mode=broker_seam.RuntimeMode(),
        )

    def _execute_de_risk(directives: Any, account: Any) -> Any:
        """Execute the assess de-risk directives (FLATTEN/REDUCE) — PAPER-ONLY.

        The post-flatten re-check reads the FRESH broker book; the de-risk submit
        is pinned to the paper ``RuntimeMode()`` (no live path).
        """
        post_account = _assemble_account()
        return lifecycle_mod.execute_de_risk_directives(
            directives=directives,
            broker_positions=list(get_positions()),
            post_flatten_account=post_account,
            submit_decision=submit_decision,
            runtime_mode=broker_seam.RuntimeMode(),
        )

    def _record_failure(reason: str) -> None:
        """Record a fail-toward-minimum-exposure event (Req 1.5) to the event queue."""
        from src.reactive.daemon.event_queue import emit_event

        emit_event(
            run_id=epoch.run_id,
            event_type="lifecycle",
            payload={"event_type": "cycle_failure", "detail": reason},
            conn=conn,
        )

    def _assemble_account() -> Any:
        """Assemble a FRESH survival ``AccountState`` from the broker readouts.

        Req 5.2 freshness: a fresh ``get_account_assets`` + ``get_positions`` +
        activation readout each call, projected via ``account_state`` (Req 10.2
        input assembly, not a survival recompute). A broker readout failure raises
        here → ``run_cycle``'s edge-path try/except fails toward minimum exposure.
        """
        assets = get_account_assets()
        broker_positions = list(get_positions())
        activated = account_activated()
        return account_state_mod.build_account_state(
            assets, broker_positions, activated=activated
        )

    def run_one_cycle() -> CycleOutcome:
        """One full evaluation cycle with the REAL deps (Req 5.2 freshness).

        FRESH each tick: the survival ``AccountState`` (broker readouts) +
        ``ClockState`` are assembled here (never pinned), then ``run_cycle`` drives
        the persist-then-act ordering + fail-toward-minimum exactly as the
        inner-ring test exercises — only with the live deps.
        """
        account = _assemble_account()
        clock = account_state_mod.build_clock_state()
        return run_cycle(
            symbol=config.symbol,
            epoch=epoch,
            survival_params=survival_params,
            clock=clock,
            account=account,
            feed=feed,
            universe=config.universe,
            leverage=config.instrument_leverage,
            is_excluded=config.is_excluded,
            stop_loss_atr_mult=config.stop_loss_atr_mult,
            op_state_holder={},  # v0.1 no-op intake: nothing mutates this holder
            poll_commands=_noop_poll_commands,
            read_op_state=lambda: read_op_state_fresh(conn),
            assemble=candidate_mod.assemble,
            decide=signal_model.decide,
            build_order=order_builder_mod.build_order,
            get_positions=lambda: list(get_positions()),
            admit=survival_gate.admit,
            assess=survival_gate.assess,
            persist_op_state=persist_op_state,
            submit_order=_submit_order,
            execute_de_risk=_execute_de_risk,
            record_failure=_record_failure,
        )

    # ----- drive the persistent loop. ----------------------------------------
    # Production: a forever-True ``should_continue`` (a real daemon runs until a
    # shutdown signal); the integration_live test injects a 1-2-tick bound. The
    # margin-material trigger defaults False (the v0.1 no-op intake never sets it).
    run(
        run_one_cycle=run_one_cycle,
        cadence_seconds=config.eval_cadence_seconds,
        margin_material_pending=(
            margin_material_pending
            if margin_material_pending is not None
            else (lambda: False)
        ),
        should_continue=(
            should_continue if should_continue is not None else (lambda: True)
        ),
    )
    return 0


def _persist_op_state_for_epoch(
    conn: Any, run_id: str, directive: AssessDirective
) -> None:
    """Adapt :func:`persist_op_state_transition` to the loop's
    ``persist_op_state(directive)`` seam by binding the owned ``conn`` + the epoch
    ``run_id`` (the two leading args ``functools.partial`` supplies).

    A module-level function (not a lambda) so it is picklable / inspectable and the
    ``partial`` in :func:`build_and_run` reads cleanly.
    """
    persist_op_state_transition(conn, run_id=run_id, directive=directive)
