"""Daemon-owned data contracts — the Phase-1 record types (task 1.3).

Boundary: types (Requirements 2, 11, 12).

These are the daemon's **own** value objects, deliberately distinct from the
dependency leaf types (P11 — each spec owns its envelope/shapes; LLM/consumer
code reads heterogeneous shapes natively, cross-spec state goes through DB rows,
never a shared base type). The module is **Phase-1 buildable with no
``src.survival`` dependency** (BL-3, design Rev 2.4): ``ProposedOrder`` and
``Candidate`` are pinned here so ``order_builder`` and ``candidate`` construct
daemon-owned shapes and stay inner-ring-testable before survival-gate lands —
the ``ProposedOrder`` → ``survival.admit`` field adaptation is the **Phase-2**
cross-spec seam (task 4.1), not an import here.

Direction import sources are pinned explicitly (gap-analysis G4 — two
string-equal but type-distinct ``Direction`` types coexist):

  * ``Candidate.direction`` is the **reactive** ``Direction``
    (``Literal["LONG","SHORT"]``, ``src/reactive/types.py:58``) — the
    ``Candidate`` feeds ``reactive.decide`` (BL-1: ``neutral``/``unavailable``
    bins never reach here; a non-directional bin is no ``Candidate`` at all).
  * ``ProposedOrder.direction`` is the **broker** ``Direction`` enum
    (``src/mcp/broker/models.py:65``) and ``ProposedOrder.intent`` is the
    broker ``Label`` BUY/TRIM/SELL vocabulary (P9) — these fields feed the
    venue mapping (SHORT-open = ``BUY`` + ``Direction.SHORT``, ``mappers.py``).

Pinning both sources keeps a static-check-passing but venue-failing
type-form divergence (T2 class) out of the order path.

``PinnedParams`` exposes ``.reactive_snapshot`` — the reactive ``ParamSnapshot``
(``src/reactive/params.py:30``) that ``decide`` consumes as its **3rd positional
arg** (``src/reactive/signal_model.py:212``, BL-2) — by value, alongside the
pinned survival namespace. The orchestrator passes ``params.reactive_snapshot``
straight into ``decide`` so the snapshot is sourced from the epoch pin, never
re-resolved mid-cycle (P2).

Pure types, no logic, no I/O (mirrors ``src/reactive/types.py``): stdlib +
the reactive/broker shape imports only — no numpy, no MCP, no DB, no survival.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

# Broker domain vocabulary (P9) the daemon-owned ProposedOrder pins. Imported
# from the broker package directly — `models.py` self-bootstraps the repo root
# onto sys.path for its transitive `from src.calibration.scorer import Label`,
# so this resolves under the daemon's interpreter. The robust submit/readout
# *function*-import seam is task 1.4; these are pure value-object/enum imports.
from src.mcp.broker.models import Direction as BrokerDirection, Label

# Reactive shapes the candidate carries by value (the inputs to `decide`).
from src.reactive.features import FeatureSet
from src.reactive.params import ParamSnapshot
from src.reactive.types import Direction as ReactiveDirection

__all__ = [
    "EvalTick",
    "PinnedParams",
    "EpochContext",
    "Candidate",
    "ProposedOrder",
    "CommandRow",
]


# --- Loop scheduling descriptor -------------------------------------------


@dataclass(frozen=True)
class EvalTick:
    """One evaluation tick the single-threaded loop processes (Req 1.1).

    ``tick_seq`` is the monotonically-increasing per-run evaluation counter and
    ``monotonic_ts`` the cadence clock reading (``time.monotonic()``) at the
    tick — together they let the loop bound the ``assess`` cadence (Req 1.2)
    and order the single-eval-at-a-time stream without a wall clock. Frozen so a
    dispatched tick cannot be mutated mid-evaluation.
    """

    symbol: str
    tick_seq: int
    monotonic_ts: float


# --- Pinned parameters (by value; P2) -------------------------------------


@dataclass(frozen=True)
class PinnedParams:
    """The epoch-pinned parameter object, exposed **by value** (P2, Req 1.4/8.1).

    ``reactive_snapshot`` is the reactive ``ParamSnapshot`` (``params.py:30``)
    that ``decide`` consumes as its 3rd positional arg (BL-2) — the orchestrator
    passes it straight through, never re-resolving from live state mid-cycle.
    ``survival_snapshot`` carries the pinned survival namespace (the resolved
    survival ``parameters_active`` map) — kept as a plain mapping here so the
    daemon does not import an unbuilt ``src.survival`` type (BL-3); survival's
    concrete shape is adapted at the Phase-2 admit boundary (task 4.1).

    The whole object is swapped atomically (whole-object pointer-flip, Req 8.1)
    — never field-by-field; frozen so a hot-swap replaces the object rather than
    mutating an open position's pinned copy.
    """

    reactive_snapshot: ParamSnapshot
    survival_snapshot: dict[str, Any]


# --- Per-epoch context (run_id + versions + window + pinned params) --------


@dataclass(frozen=True)
class EpochContext:
    """The pinned-param epoch the trace correlates against (Req 4.1/4.2, P3).

    One per pinned-param epoch (daemon start + each atomic hot-swap). ``run_id``
    is the ``execution_daemon_epoch.epoch_id`` carried on every decision/fill
    trace and event in the epoch (P3); ``code_version`` / ``param_version`` are
    the two correlation keys the signal model emits, echoed here so the trace
    assembler injects the full four-key set; ``walk_forward_window`` is the key
    the model does *not* provide — re-sourced from the P2 registry at hot-swap
    (v0.1 bootstrap label until the tuner first publishes, Req 4.2).
    ``pinned_params`` is the by-value snapshot bundle for this epoch.
    """

    run_id: str
    code_version: str
    param_version: str
    walk_forward_window: str
    pinned_params: PinnedParams


# --- Candidate (candidate.assemble output; BL-1/CN-4) ---------------------


@dataclass(frozen=True)
class Candidate:
    """The model's assembled inputs: features + directional side + reference price.

    Returned by ``candidate.assemble`` only on a **directional** tactical bin
    (``positive``→``LONG`` / ``negative``→``SHORT``); a ``neutral``/``unavailable``
    bin or insufficient data yields ``None`` (no candidate, Req 12.4/12.5), so a
    constructed ``Candidate`` always carries a real ``direction``.

    ``features`` is the ``FeatureSet`` ``decide`` consumes (Req 12.2 — never raw
    market data); ``direction`` is the **reactive** ``Direction`` (the side
    ``decide`` echoes, Req 12.3); ``reference_price`` is the last close the
    ``order_builder`` anchors the protective stop-loss on — surfaced here
    because ``compute_features`` computes ``close = ticker_closes[-1]`` then
    drops it (``features.py:170``), so the candidate carries it explicitly
    rather than forcing a stale re-fetch (CN-4). Frozen — an assembled candidate
    is immutable evidence threaded by value to ``decide`` and ``order_builder``.
    """

    features: FeatureSet
    direction: ReactiveDirection
    reference_price: float


# --- ProposedOrder (order_builder.build_order output; BL-3) ----------------


@dataclass(frozen=True)
class ProposedOrder:
    """The daemon-owned pre-admit order ``order_builder`` constructs (Req 11.x).

    Daemon-owned (BL-3): ``survival.admit`` *reads* these fields but does not
    own the type — the field adaptation to survival's landed ``admit`` shape is
    the Phase-2 cross-spec seam (task 4.1). Built daemon-side so ``order_builder``
    is genuinely Phase-1 inner-ring-testable with no survival import.

    ``intent`` is the P9 ``Label`` BUY/TRIM/SELL vocabulary and ``direction``
    the broker ``Direction`` enum: together they express open/reduce on the
    decided side — **SHORT-open = ``BUY`` + ``Direction.SHORT``** (the broker
    venue mapping, ``mappers.py``), *not* a ``SELL`` (Req 11.1). ``volume`` is
    set from the advisory ``sizing_hint`` capped by survival and clamped ≤ held
    on a reduce (Req 11.2/11.6). ``stop_loss`` is a **price level**
    = ``reference_price ∓ atr×stop_loss_atr_mult`` (Req 11.3 — the daemon owns
    the SL as an order parameter, survival + reactive both disclaim it), so the
    order satisfies survival's mandatory-stop check by construction.
    ``position_id`` targets the specific position on a reduce/close (Req 11.4) —
    ``None`` on an open. Frozen — a proposed order is rebuilt (not mutated) on a
    resize-on-advisory rejection (Req 3.5).
    """

    symbol: str
    intent: Label
    direction: BrokerDirection
    volume: float
    stop_loss: float
    position_id: Optional[str] = None


# --- CommandRow (command_intake row mirror; gated supervisory transport) ---


# The gated command vocabulary — the only seams a supervisory command may target
# (Req 9.2). A row naming anything else is rejected at intake (Req 9.3); the
# daemon never applies a direct-mutation command.
CommandType = Literal[
    "engage_kill_switch",
    "set_safe_mode_grade",
    "select_validated_config",
]

# Intake lifecycle status (state-guard whitelist on the table; the daemon is the
# sole applier — it moves a row pending → applied | rejected, never the reverse).
CommandStatus = Literal["pending", "applied", "rejected"]


@dataclass(frozen=True)
class CommandRow:
    """An ``execution_daemon_command_intake`` row the daemon polls + applies.

    The out-of-process commander (in-session-monitor / operator) INSERTs a gated
    row; the daemon is the sole reader/applier (Req 9.2/9.3). ``command_id`` is
    commander-minted; ``issued_by`` is validated against the configured allowlist
    at apply-time (write-auth, Issue 3); ``command_type`` must be a gated seam;
    ``target`` is the JSONB payload (e.g. the safe-mode grade or the version_id);
    ``status`` / ``applied_at`` / ``reject_reason`` carry the set-once apply
    outcome (Req 9.3 — toward-safer guard rejects a direct-mutation or loosening
    command with a reason, never applies it). A plain frozen record mirroring the
    table; the validate/apply logic lives in ``commands.py`` (task 3.5).
    """

    command_id: str
    issued_by: str
    command_type: CommandType
    target: dict[str, Any] = field(default_factory=dict)
    status: CommandStatus = "pending"
    applied_at: Optional[str] = None
    reject_reason: Optional[str] = None
