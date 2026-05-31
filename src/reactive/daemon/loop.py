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
wires the real deps against the owned connection, including the **live**
``survival_gate_state`` / ``survival_gate_events`` persist (the broker / market
feed venue handles stay deferred — see the module's ``build_and_run`` note).

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


def build_and_run(
    *,
    code_version: str = "execution-daemon-v0.1",
    param_version: str = "bootstrap",
) -> int:
    """Build the owned connection + config, pin the epoch, wire the **live DB**
    persist-then-act path, and run the persistent loop.

    This is the entrypoint the process (``python -m src.reactive.daemon``) calls.
    It opens the daemon's single owned psycopg3 connection (``db.DaemonConnection``)
    from the env-resolved ``DaemonConfig`` (``config._dsn()``), mints the startup
    epoch (``params.resolve_epoch`` against the **live** ``parameters_active``,
    writing the ``execution_daemon_epoch`` row), and builds the **live**
    ``persist_op_state`` writer (``persist_op_state_transition`` partially applied
    with the owned conn + the epoch ``run_id``) — so the persist-then-act op-state
    write (Req 5.1) is wired against the real ``survival_gate_state`` /
    ``survival_gate_events`` and exercised by the integration smoke.

    Restart-safe: the connection lifecycle is a context manager (opened here,
    closed on exit), the epoch is re-minted on each process start, and all durable
    state is in the append-only DB tables — a crash + restart re-pins a fresh epoch
    and resumes from the persisted op-state (no in-memory state survives a restart,
    by design — the daemon is a leaf executor, Req 10).

    **Deferred — narrowed to ONLY the broker/feed venue handles.** The DB persist
    path above is **live** (it opens the owned conn, writes the epoch row, and the
    persist-then-act writer is constructed against the real survival tables). What
    remains deferred is the **live broker session + market-feed venue connection**
    (the ``broker.submit_decision`` / ``broker.get_positions`` venue handles + the
    fast-clock ``MarketFeed``), which need Gate / massive credentials and an
    ``integration_live`` venue bring-up. The loop LOGIC (single-eval, intake-first,
    cadence, persist-then-act ordering, fail-toward-minimum) is unit-tested via
    :func:`run_cycle` / :func:`should_run_now` / :func:`run` against synthetic deps
    + the live persist via the integration suite; this function is the production
    wiring of those tested pieces, with the venue handles the last live seam.

    Args:
        code_version / param_version: the epoch identity stamped onto the pinned
            params + the trace correlation keys (P3). v0.1 bootstrap defaults until
            the tuner publishes a promoted version.

    Returns:
        A process exit code (0 on a clean shutdown).
    """
    # Imported here (not at module top) so importing ``loop`` for the inner-ring
    # unit tests pulls in no DB / broker / feed machinery — the wiring deps are
    # only needed when the real process actually starts (P14: the loop logic is
    # testable without them). The config build is a pure env read (opens no
    # connection — db.py owns the connection lifecycle).
    from functools import partial

    from src.reactive.daemon import params as params_mod
    from src.reactive.daemon.config import DaemonConfig
    from src.reactive.daemon.db import DaemonConnection

    config = DaemonConfig.from_env()

    # ----- LIVE DB path: open the owned conn, pin the epoch, wire persist. ----
    # The connection lifecycle is a context manager (opened here, closed on exit).
    # The epoch mint is a real ``parameters_active`` REPEATABLE-READ read + an
    # ``execution_daemon_epoch`` INSERT (a live DB write), so the DB persist path
    # is genuinely exercised here, not faked.
    with DaemonConnection(config) as conn:
        epoch = params_mod.resolve_epoch(
            conn,
            code_version=code_version,
            param_version=param_version,
        )

        # The live persist-then-act writer (Req 5.1): the callable the loop runs
        # to durably persist the op-state transition BEFORE the per-order admit.
        # Bound to the owned conn + the epoch run_id; passed into ``run_cycle`` as
        # its ``persist_op_state`` seam when the loop drives. This is the live DB
        # wiring the task closes — the persist path is real and exercised.
        persist_op_state = partial(  # noqa: F841 — wired into run_cycle at the venue seam
            _persist_op_state_for_epoch, conn, epoch.run_id
        )

        # ----- DEFERRED: ONLY the broker/feed venue handles. ------------------
        # The DB persist path (epoch pin + persist-then-act writer) is LIVE above.
        # What remains is the live broker session + market-feed venue connection —
        # the ``broker.submit_decision`` / ``broker.get_positions`` venue handles
        # and the fast-clock ``MarketFeed`` — which need Gate / massive credentials
        # and an integration_live venue bring-up. Narrowed NotImplementedError so
        # the deferred seam is ONLY the venue handles, not the DB path.
        raise NotImplementedError(
            "loop.build_and_run: the live DB persist-then-act path is wired and "
            f"exercised (epoch={epoch.run_id} pinned against parameters_active; "
            "persist_op_state writes survival_gate_state/_events). DEFERRED to the "
            "integration_live venue bring-up: ONLY the live broker session + "
            "market-feed venue handles (broker.submit_decision / get_positions + "
            "the massive MarketFeed; need Gate / massive creds). Wire the real "
            "candidate.assemble (feed) / signal_model.decide / order_builder / "
            "broker readouts / paper-lifecycle / lifecycle.execute_de_risk and "
            "drive run() here once the venue handles are available "
            f"(paper={config.paper})."
        )


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
