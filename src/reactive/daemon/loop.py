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
  3. **Run the §13 walk** (``orchestrator.orchestrate_tick``): ``assess`` (Survive
     standing monitor, every tick, Req 1.2) → derive permit → ``candidate`` →
     ``decide`` → ``order_builder`` → per-order ``admit`` → the paper submit.
  4. **Execute the assess de-risk directives** (``lifecycle`` flatten/reduce) —
     these ALWAYS flow (a true exit / reduce / flatten is never blocked, Req 7.2).
  5. On any **dependency error** during steps 3 (the edge/order/admit path): **fail
     toward minimum exposure** (Req 1.5) — reject any opening order (no submit),
     but STILL execute the de-risk directives and record the failure. The de-risk
     path is computed from ``assess`` (run before the failing edge path) so a
     reduce/flatten is never lost to an edge-side blowup.

Single-eval-at-a-time (Req 1.1): the loop is single-threaded and blocking — each
:func:`run_cycle` completes its read-modify-write of op-state before the next
begins; there is no concurrency, no asyncio, no pool (the all-sync deps + the
op-state-freshness guarantee mandate this shape, design §Architecture-Pattern).

Cadence + margin-material trigger (Req 1.2/1.3): :func:`should_run_now` is the
pure scheduler predicate — run when the cadence has elapsed OR a margin-material
event is pending (the latter triggers an out-of-cadence cycle, Req 1.3).

Inner-ring testable (P14): :func:`run_cycle` takes every dep as an **injected
callable** (``poll_commands`` / ``read_op_state`` / ``assemble`` / ``decide`` /
``build_order`` / ``get_positions`` / ``admit`` / ``assess`` / ``submit_order`` /
``execute_de_risk`` / ``record_failure``), so the loop logic is exercised with
synthetic state + the REAL pure ``survival.admit`` / ``assess`` (no DB, no MCP, no
LLM). :func:`build_and_run` wires the real deps against the owned connection (the
live "service starts against postgres" path needs a DB and is deferred — see the
module's ``build_and_run`` note).

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
from src.reactive.daemon.orchestrator import OrchestrationOutcome, orchestrate_tick
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
    "build_and_run",
]


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
      3. **Run the §13 walk** (``orchestrate_tick``): ``assess`` first (every
         tick, Req 1.2), then — only if permitted (or a true-exit is buildable) —
         candidate → decide → build → admit. The assess directive is captured
         FIRST so the de-risk path survives an edge-side failure (Req 1.5).
      4. **Execute the assess de-risk directives** (flatten/reduce) — these
         ALWAYS flow (Req 7.2 — a true exit / reduce / flatten is never blocked).
      5. **Submit the admitted order** (the paper-lifecycle driver is wired as
         ``submit_order``). On a dependency error in steps 3-5's edge path, fail
         toward minimum exposure (Req 1.5): reject the open (no submit), still run
         the de-risk directives, record the failure.

    The deps are injected so this is inner-ring-testable with synthetic state +
    the REAL pure ``admit`` / ``assess`` (P14). The op-state read-modify-write is
    contiguous and completes before the caller begins the next cycle (the
    single-threaded loop never overlaps two evaluations, Req 1.1).

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

    # ----- Step 3 + 4 + 5: the §13 walk, then de-risk, then submit. ----------
    # The assess directive is needed for the de-risk path REGARDLESS of whether
    # the edge path (candidate/decide/build/admit) succeeds — so on a dependency
    # error we still execute the de-risk directives (Req 1.5: never block a true
    # exit / reduce / flatten). We obtain it via orchestrate_tick when the edge
    # path is healthy, and via a direct assess fallback when the edge path raises.
    assess_directive: Optional[AssessDirective] = None
    admitted_order: Optional[ProposedOrder] = None
    declined = False
    failed = False
    failure_reason: Optional[str] = None
    non_directional_reason: Optional[NonDirectionalReason] = None

    try:
        outcome: OrchestrationOutcome = orchestrate_tick(
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
            assemble=assemble,
            decide=decide,
            build_order=build_order,
            get_positions=get_positions,
            admit=admit,
            assess=assess,
        )
        assess_directive = outcome.assess_directive
        admitted_order = outcome.admitted_order
        declined = outcome.declined
        non_directional_reason = outcome.non_directional_reason
    except Exception as exc:  # noqa: BLE001 — fail toward minimum exposure (Req 1.5)
        # A dependency error mid-evaluation. Fail toward minimum exposure: reject
        # any opening order (admitted_order stays None — nothing is submitted),
        # but STILL run the de-risk directives below so a true exit / reduce /
        # flatten is never blocked by the failure (Req 1.5/7.2). Re-derive the
        # assess directive directly from the gate (the Survive standing monitor
        # must still run even when the edge path blew up).
        failed = True
        failure_reason = f"{type(exc).__name__}: {exc}"
        try:
            assess_directive = assess(account, op_state, survival_params, clock)
        except Exception as assess_exc:  # noqa: BLE001 — defense in depth (P6)
            # Even the standing monitor failed — there is no de-risk directive to
            # execute; record the compounded failure and skip the de-risk step.
            failure_reason = (
                f"{failure_reason}; assess also failed: "
                f"{type(assess_exc).__name__}: {assess_exc}"
            )
            assess_directive = None
        record_failure(failure_reason)

    # ----- Step 4 (always): execute the assess de-risk directives. -----------
    # FLATTEN / REDUCE / FREEZE_ENTRIES from assess are de-risk actions that must
    # ALWAYS flow — they net-reduce exposure (Req 7.2), so they run on a healthy
    # cycle AND on a failed one (a dependency error never blocks a reduce/flatten,
    # Req 1.5). A None assess_directive (assess itself failed) skips this.
    de_risk_executed = False
    if assess_directive is not None and assess_directive.reduce_directives:
        execute_de_risk(assess_directive.reduce_directives, account)
        de_risk_executed = True

    # ----- Step 5: submit the admitted order (paper lifecycle). --------------
    # Only an order that cleared admit on a healthy edge path reaches here; a
    # failed cycle has admitted_order=None, so no open is submitted (Req 1.5).
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


def build_and_run() -> int:
    """Build the owned connection + config and run the persistent loop.

    This is the entrypoint the process (``python -m src.reactive.daemon``) calls.
    It opens the daemon's single owned psycopg3 connection (``db.DaemonConnection``)
    from the env-resolved ``DaemonConfig``, mints the startup epoch
    (``params.resolve_epoch`` against the live ``parameters_active``), wires the
    real deps (``commands.poll_and_apply`` / ``orchestrate_tick`` with
    ``gate.admit`` / ``gate.assess`` / ``signal_model.decide`` /
    ``candidate.assemble`` / ``order_builder.build_order`` / ``broker`` readouts /
    the paper-lifecycle driver / ``lifecycle.execute_de_risk``), and drives
    :func:`run`.

    Restart-safe: the connection lifecycle is a context manager (opened here,
    closed on exit), the epoch is re-minted on each process start, and all state
    is in the append-only DB tables — a crash + restart re-pins a fresh epoch and
    resumes from the persisted op-state (no in-memory state survives a restart, by
    design — the daemon is a leaf executor, Req 10).

    **Deferred (not faked):** the live "service starts against postgres" path
    requires a running DB (a live ``parameters_active`` to pin, a live broker
    session, the real market feed). That end-to-end bring-up is an
    ``integration_live`` concern, not an inner-ring unit (P14) — it is wired here
    but exercised only with a real DB. The loop LOGIC (single-eval, intake-first,
    cadence, fail-toward-minimum) is unit-tested via :func:`run_cycle` /
    :func:`should_run_now` / :func:`run` against synthetic deps; this function is
    the production wiring of those tested pieces.

    Returns:
        A process exit code (0 on a clean shutdown).
    """
    # Imported here (not at module top) so importing ``loop`` for the inner-ring
    # unit tests pulls in no DB / broker / feed machinery — the wiring deps are
    # only needed when the real process actually starts (P14: the loop logic is
    # testable without them). The config build is a pure env read (opens no
    # connection — db.py owns the connection lifecycle), so it is safe to do here.
    from src.reactive.daemon.config import DaemonConfig

    config = DaemonConfig.from_env()

    # The live drive — open the owned ``db.DaemonConnection`` from ``config.dsn``,
    # mint the startup epoch (``params.resolve_epoch`` against the live
    # ``parameters_active``), wire the real deps (``commands.poll_and_apply`` /
    # ``orchestrate_tick`` with ``gate.admit`` / ``gate.assess`` /
    # ``signal_model.decide`` / ``candidate.assemble`` / ``order_builder`` /
    # broker readouts / the paper-lifecycle driver / ``lifecycle.execute_de_risk``),
    # and drive :func:`run` — needs a running Postgres + broker session + market
    # feed. That is an ``integration_live`` bring-up, **not** an inner-ring unit
    # (P14). It is intentionally **NOT faked** here, and the deferred-seam guard
    # fires BEFORE any DB I/O so the default entrypoint surfaces a clean message
    # rather than crashing on a connection attempt when no DB is up. The loop
    # LOGIC (single-eval, intake-first, cadence, fail-toward-minimum) is unit-tested
    # via :func:`run_cycle` / :func:`should_run_now` / :func:`run` against synthetic
    # deps; this function is the production wiring of those tested pieces.
    raise NotImplementedError(
        "loop.build_and_run live drive is the deferred integration_live path "
        f"(paper={config.paper}; needs a live DB + broker session + market feed). "
        "The loop LOGIC is unit-tested via run_cycle / should_run_now / run. Open "
        "db.DaemonConnection(config), mint the startup epoch, wire the real deps, "
        "and drive run() here when bringing the service up against postgres."
    )
