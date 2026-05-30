"""Replay Harness: the simulator — DAILY decision layer + divergence detection.

Task 2.3 (the FIRST piece of the `simulator` module). This lands the **daily
layer** only — the per-trading-day candidate decision and the champion
divergence detection (design `simulator` "Core algorithms #1"). The
**intraday** account path (decision→order, fills, §16.1 flatten, total-return
P&L) is tasks 2.4-2.7 and is deliberately NOT here; `run_daily_layer` returns a
clean per-day record (`DailyDecision`) the 2.4 decision→order step consumes.

What the daily layer does (design `simulator` "Core algorithms #1 —
champion-decision prefetch + divergence detection" + the System-Flow daily leg):

1. **Champion-decision prefetch (ONCE).** At window start, call the injected
   ``query_trace({...champion keys..., kind:"decision", until:<boundary>})``
   EXACTLY ONCE and index the champion decisions by ``(day, symbol)`` — no
   per-day DB round-trip (removes the ordering hazard, design line 201). In
   production the harness (a later task) injects the landed
   ``telemetry.reader.query_trace``; in tests a fake / pre-indexed dict is
   injected (R9.2 isolation — no live DB).

2. **Per-day candidate decision (R2.1 / R3.1 / R3.3).** For each trading day D
   in the window, drive ``features_adapter.compute_daily_features`` (point-in-
   time) then the LANDED ``signal_model.decide`` with the candidate
   ``ParamSnapshot`` (+ direction) → a ``ReactiveDecision``. The candidate
   reconstructs its OWN decision; it NEVER reimplements ``decide`` (R3.3) and
   NEVER reads the champion's recorded outcome as the candidate's decision
   (R2.1). ``decide``/``compute_daily_features`` are injected (defaulting to the
   landed cores) so unit tests drive the stubs.

3. **Divergence detection (R2.2).** A ``(day, symbol)`` DIVERGES iff the
   candidate decision differs from the champion's indexed decision for that
   ``(day, symbol)`` — INCLUDING the champion-HOLD / no-record vs
   candidate-actionable case (an absent champion row is treated as ``"HOLD"``,
   so a candidate-actionable day diverges). A divergent + actionable day is
   flagged (``needs_intraday_refetch``) so the (later) intraday layer re-fetches
   that name's point-in-time path; a non-divergent day may reuse the champion's
   recorded inputs.

Determinism (R9.1): identical (candidate, window, ``data_port`` responses,
champion index) ⇒ identical per-day records — ordering is the window's ticker
order × sorted trading days.

--------------------------------------------------------------------------------
Two seams this task could not pin from the worktree (CONCERNS / revalidation):
--------------------------------------------------------------------------------
- **Champion-decision symbol key (``_CHAMPION_SYMBOL_KEY``).** The
  ``decision_process_trace`` ``trace`` JSONB payload is "deliberately
  schema-free" (telemetry ``trace_writer`` docstring); the daemon that mints
  decision rows — and therefore decides where the SYMBOL lands in the payload —
  is NOT landed in this worktree. The telemetry schema/spec pin ``decision`` in
  the payload but NOT the symbol. We extract the symbol from
  ``row["trace"][_CHAMPION_SYMBOL_KEY]`` with ``_CHAMPION_SYMBOL_KEY = "symbol"``
  and **fail loud** if a PRESENT row lacks it (a wrong-key DEFECT, NOT a
  no-record — see ``index_champion_decisions``). Retargeting the key when the
  daemon lands is a one-line change here — the **revalidation trigger** (R10.3).

- **Trading-day source.** The ``DataPort`` protocol pins no calendar method, so
  trading days are enumerated from ``fetch_daily_bars`` bounded to
  ``[window.start, window.end]``. Champion rows cannot be the day source: the
  champion-absent divergence case requires evaluating days the champion never
  decided.

- **Direction is selected from the tactical-overlay bin (RESOLVED — amend 2.3).**
  The reactive model NEVER selects/flips the side — it confirms the caller-
  supplied direction or HOLDs — so the daily layer must SUPPLY a side. The
  authoritative rule (execution-daemon design Rev 2.3/2.4, the ``candidate``
  component + Req 12.5, grounded §12.3): **direction = the tactical relative-
  strength bin**, via the explicit map ``positive → LONG``, ``negative → SHORT``,
  ``neutral`` / ``unavailable`` → ``None`` (no new exposure). ``select_direction``
  reads the verbatim 4-valued bin from ``FeatureSet.raw["tactical_bin"]`` — NOT
  ``trend_vote`` (which folds ``unavailable``→``0.0``==``neutral``; the daemon's
  NB-1) — and degrades to ``None`` on any feature object that carries no ``raw``
  (a ``FeatureFailure``: fail-toward-no-exposure, Req 12.4). A ``None`` direction
  is a flat/no-trade day: ``decide`` is NOT called, the ``DailyDecision`` carries
  no ``ReactiveDecision`` (``decision is None``), and the day NEVER counts as
  divergent+actionable (a flat day needs no intraday re-fetch). For a directional
  bin the SELECTED side (LONG **or SHORT**) is driven into ``decide`` — so SHORT
  is now reconstructable.

  This deterministic rule ALSO reconstructs the **champion's** direction: the
  champion ran the same tactical overlay, so identical point-in-time features →
  identical bin → identical direction. That is what fixes champion-reproduction
  fidelity (R7) for SHORT days — re-simulating the champion's own config now
  re-derives its SHORT side rather than forcing a LONG probe. (The earlier 2.3
  hard-default-LONG could never emit SHORT, so any champion-SHORT day spuriously
  diverged AND R7 fidelity failed on it.)

Pure leaf (P1 / design §Dependency direction
``types → data_client → features_adapter → simulator``): imports the owned
``types``, the sibling ``features_adapter``, the landed ``signal_model`` core,
and — added at task 2.4 — the landed ``src.survival`` (``gate.admit`` + its
contract types + ``params``), a SANCTIONED read-only boundary import (the
decision→order + admit-gating step DRIVES the real survival core, R3.1/R3.3).
``src.survival`` is itself a pure stdlib leaf (no MCP / DB / I/O), so the
no-httpx / no-MCP / no-DB / no-consumer-spec purity claim still holds. It does
NOT import ``telemetry.reader`` (``query_trace`` is INJECTED — the real reader
in prod, a fake/pre-indexed dict in tests — preserving R9.2 isolation).

Source of truth: requirements.md R2 AC 2.1/2.2/**2.3**, R3 AC 3.1/**3.2**/3.3,
R9 AC 9.1; design.md `simulator` "Core algorithms #1" (daily layer) + "Core
algorithms #2 (decision→order construction)" (task 2.4) + the execution-daemon
`order_builder` component (the authoritative decision→order rule MIRRORED here,
NOT imported — boundary-forbidden).

Task 2.4 (decision→order + admit gating) addresses R2.3 only PARTIALLY: the
order-dependent decision→order step + the per-day survival admit response land
here; the cross-day sequential account-evolution driver, fills, the §16.1
flatten, and total-return P&L are the 2.5-2.7 seam (see the 2.4 section below).

Requirements: 2.1, 2.2, 2.3 (partial), 3.1, 3.2, 3.3.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from src.reactive.params import ParamSnapshot
from src.reactive.replay.features_adapter import compute_daily_features
from src.reactive.replay.types import Candidate, DataPort, ReplayWindow
from src.reactive.signal_model import decide as _landed_decide
from src.reactive.types import Decision, Direction, ReactiveDecision
from src.survival.gate import admit as _landed_admit
from src.survival.params import SurvivalParameters
from src.survival.types import (
    AccountState,
    AdmitDecision,
    ClockState,
    OperationalState,
    OrderEvaluation,
    Position,
    ProposedOrder,
)

# The freeform decision-row trace-payload key the champion symbol is read from.
# Daemon-undetermined (the emitter is not landed; the telemetry payload is
# schema-free) — retargeting this single constant is the revalidation trigger
# when the daemon lands. See the module docstring CONCERNS.
_CHAMPION_SYMBOL_KEY = "symbol"

# The decision verdict key inside the trace payload (PINNED by the telemetry
# schema + the champion fixture — lower risk than the symbol key).
_CHAMPION_DECISION_KEY = "decision"

# Polygon/Massive aggregate `t` is epoch MILLIseconds (mirrors features_adapter
# / data_client). A bar's UTC calendar date is derived from it locally.
_MS_PER_S = 1_000

# An absent champion record is treated as a HOLD for divergence (design line 201
# "champion-HOLD/no-record vs candidate-actionable"): a candidate-actionable day
# then diverges. This is the canonical reactive HOLD vocabulary (P9).
_CHAMPION_ABSENT: Decision = "HOLD"

# The verbatim 4-valued tactical bin lives in `FeatureSet.raw[_TACTICAL_BIN_KEY]`
# (src/reactive/features.py:190). Read THIS, never `trend_vote` — the vote folds
# `unavailable`→0.0==`neutral` (the `_TACTICAL_VOTE` map omits `unavailable`,
# features.py:83), which would silently merge the two non-directional bins (NB-1).
_TACTICAL_BIN_KEY = "tactical_bin"

# The authoritative tactical-bin → candidate-direction map (execution-daemon
# design Rev 2.3/2.4, the `candidate` component + Req 12.5, grounded §12.3): the
# directional side IS the tactical relative-strength bin. `positive → LONG`,
# `negative → SHORT`; the two non-directional bins (`neutral` = no edge / 12.5,
# `unavailable` = insufficient data / 12.4) map to None = NO new exposure (a flat
# day). A bin absent from this map is non-directional by default (→ None).
_BIN_DIRECTION: dict[str, Direction] = {"positive": "LONG", "negative": "SHORT"}


# --- Per-day record (the 2.4 decision→order seam) -----------------------------
# Lives in simulator.py (NOT types.py — the harness↔tuner contract types are
# off-limits to this task; this is an INTERNAL simulator record).


@dataclass(frozen=True)
class DailyDecision:
    """One trading-day candidate decision + its champion-divergence verdict.

    The per-day record `run_daily_layer` emits and the (later) 2.4 decision→order
    step consumes. Frozen so the determinism contract (R9.1) holds and nothing
    mutates a returned record.

    Fields:
      - `as_of_day`: the trading day D (ISO date) the decision was made as-of.
      - `symbol`: the traded name.
      - `decision`: the candidate's OWN `ReactiveDecision` (driven via `decide`,
        never the champion's recorded outcome — R2.1/R3.3), OR **`None` on a
        non-directional flat day** — when the tactical bin is `neutral`/
        `unavailable` (or the features degraded), `select_direction` returns
        `None`, `decide` is NOT called, and there is no candidate decision (a
        flat/no-trade day, analogous to Req 12.5). `None` is distinguishable from
        a HOLD the model RETURNED (`decision is not None and
        decision.decision == "HOLD"`).
      - `tactical_bin`: the verbatim `raw["tactical_bin"]` the direction was
        selected from (or `None` if the features carried none). Recorded so a
        flat day stays attributable — `neutral` (no edge, 12.5) vs `unavailable`
        (bad data, 12.4) — even though both halt new exposure.
      - `champion_decision`: the champion's indexed decision for `(day, symbol)`,
        or the `_CHAMPION_ABSENT` HOLD sentinel when the champion has no record.
      - `diverged`: candidate decision != champion decision (R2.2 — INCLUDING
        champion-HOLD/absent vs candidate-actionable). A flat day's effective
        decision is HOLD, so it diverges iff the champion traded.
      - `needs_intraday_refetch`: `diverged AND candidate actionable` — the flag
        the (later) intraday layer reads to re-fetch this name's point-in-time
        path. A divergent-but-candidate-HOLD day (and any flat/no-trade day)
        needs no intraday path, so this is False there even though `diverged`
        may be True.
    """

    as_of_day: str
    symbol: str
    decision: ReactiveDecision | None
    tactical_bin: str | None
    champion_decision: Decision
    diverged: bool
    needs_intraday_refetch: bool


# Injected-core type aliases (defaulting to the landed cores; tests inject stubs).
DecideFn = Callable[..., ReactiveDecision]
FeaturesFn = Callable[..., Any]
QueryTraceFn = Callable[..., list[dict]]


# --- Champion-decision prefetch + indexing (algo #1, prefetch ONCE) -----------


def index_champion_decisions(
    query_trace: QueryTraceFn,
    champion_keys: Mapping[str, Any],
    *,
    until: str,
) -> dict[tuple[str, str], Decision]:
    """Prefetch the champion's decisions ONCE and index them by `(day, symbol)`.

    Calls the injected `query_trace` EXACTLY ONCE with the champion's correlation
    keys + `kind="decision"` + the consumer-supplied `until` boundary (the
    temporal firewall the telemetry reader PROVIDES, never enforces). Each
    returned raw row dict is indexed by `(event_ts-date, trace[symbol])` → its
    `trace["decision"]`. No per-day round-trip (design line 201 — "removing the
    ordering hazard").

    **Fail-loud on a malformed PRESENT row (the key-defect tripwire).** A row
    that is present but carries no recognized symbol (or no decision) is a
    DEFECT — almost certainly the daemon wrote the symbol under a different
    payload key than `_CHAMPION_SYMBOL_KEY` — NOT a no-record. Tolerating it
    (returning None / skipping) would collapse the defect into the
    champion-absent path: every champion lookup would miss, every actionable day
    would spuriously diverge, and the intraday re-fetch would fire everywhere,
    silently. So this raises `KeyError`. Genuine row-ABSENCE (a `(day, symbol)`
    the champion never decided) is NOT a row here at all — it is handled
    downstream by the divergence `.get(..., _CHAMPION_ABSENT)`.

    Args:
        query_trace: the injected decision-trace reader (real
            `telemetry.reader.query_trace` in prod, a fake / pre-built in tests).
        champion_keys: the champion's correlation keys (`code_version`,
            `param_version`, `walk_forward_window`) — passed through to the
            filter verbatim.
        until: the boundary `event_ts <= until` predicate (the consumer's
            temporal firewall; the champion baseline read may legitimately span
            the full window — R4.1 note).

    Returns:
        `{(day_iso, symbol): champion_decision}` — the champion-decision index.

    Raises:
        KeyError: a present champion row carries no `_CHAMPION_SYMBOL_KEY` symbol
            (or no `_CHAMPION_DECISION_KEY` decision) — a wrong-key DEFECT, not a
            no-record (the loud tripwire; revalidation trigger when the daemon
            lands).
    """
    filters: dict[str, Any] = {**dict(champion_keys), "kind": "decision", "until": until}
    rows = query_trace(filters)

    index: dict[tuple[str, str], Decision] = {}
    for row in rows:
        trace = row.get("trace") or {}
        if _CHAMPION_SYMBOL_KEY not in trace:
            raise KeyError(
                f"champion decision row {row.get('trace_id')!r} carries no "
                f"{_CHAMPION_SYMBOL_KEY!r} in its trace payload — a wrong-key "
                f"DEFECT (the daemon symbol key is undetermined in this worktree; "
                f"retarget _CHAMPION_SYMBOL_KEY), NOT a champion no-record."
            )
        if _CHAMPION_DECISION_KEY not in trace:
            raise KeyError(
                f"champion decision row {row.get('trace_id')!r} carries no "
                f"{_CHAMPION_DECISION_KEY!r} in its trace payload."
            )
        symbol = trace[_CHAMPION_SYMBOL_KEY]
        decision: Decision = trace[_CHAMPION_DECISION_KEY]
        day = _iso_day(row["event_ts"])
        index[(day, symbol)] = decision
    return index


# --- Trading-day enumeration (DataPort has no calendar method) ----------------


def _iso_day(ts: str) -> str:
    """Normalize an ISO timestamp/date to its bare `YYYY-MM-DD` day.

    Champion `event_ts` is `"2024-01-31T14:30:00Z"`; a candidate as-of day is a
    bare ISO date. Slicing both to the first 10 chars before keying is what makes
    the `(day, symbol)` join match (else it silently never matches).
    """
    return ts[:10]


def _bar_day(row: dict) -> str | None:
    """The UTC calendar day (ISO) of a raw wire bar from its epoch-ms `t`."""
    t = row.get("t")
    if t is None:
        return None
    return datetime.fromtimestamp(t / _MS_PER_S, tz=timezone.utc).date().isoformat()


def _trading_days(
    symbol: str, window: ReplayWindow, data_port: DataPort
) -> list[str]:
    """The trading days for `symbol` within `[window.start, window.end]`.

    The `DataPort` pins no calendar method, so days are derived from the
    `fetch_daily_bars` rows bounded to the window. Sorted + de-duplicated for a
    deterministic per-ticker day order (R9.1).
    """
    start = date.fromisoformat(window.start[:10])
    end = date.fromisoformat(window.end[:10])
    days: set[str] = set()
    for row in data_port.fetch_daily_bars(symbol, window.start, window.end):
        d = _bar_day(row)
        if d is None:
            continue
        if start <= date.fromisoformat(d) <= end:
            days.add(d)
    return sorted(days)


# --- Direction selection from the tactical bin (Req 12.5, §12.3) --------------


def select_direction(features: Any) -> Direction | None:
    """Map the candidate's tactical relative-strength bin to a trade `Direction`.

    The authoritative rule (execution-daemon design Rev 2.3/2.4, the `candidate`
    component + Req 12.5, grounded §12.3): the directional side IS the tactical-
    overlay relative-strength bin, via the explicit `_BIN_DIRECTION` map —
    ``positive → LONG``, ``negative → SHORT``, and the two non-directional bins
    (``neutral`` = no edge / 12.5, ``unavailable`` = insufficient data / 12.4) →
    ``None`` (no new exposure / a flat day).

    The bin is read VERBATIM from ``features.raw[_TACTICAL_BIN_KEY]`` — NEVER
    ``trend_vote``, which folds ``unavailable``→``0.0``==``neutral`` and would
    silently merge the two non-directional bins (NB-1). A feature object that
    carries no ``raw`` (a ``FeatureFailure``) or no bin yields ``None`` —
    fail-toward-no-exposure (Req 12.4). This same deterministic map re-derives
    the CHAMPION's direction from identical point-in-time features (the R7 SHORT-
    fidelity fix), and never selects/flips a side the model didn't compute.

    Args:
        features: the per-day `FeatureSet` (or a `FeatureFailure`-like object).

    Returns:
        `"LONG"` / `"SHORT"` for a directional bin; `None` for a non-directional
        bin, an absent bin, or a degraded feature object (no `raw`).
    """
    raw = getattr(features, "raw", None)
    if not isinstance(raw, Mapping):
        return None
    tactical_bin = raw.get(_TACTICAL_BIN_KEY)
    return _BIN_DIRECTION.get(tactical_bin) if tactical_bin is not None else None


# --- Pure divergence predicate ------------------------------------------------


def _diverges(candidate_decision: Decision, champion_decision: Decision) -> bool:
    """A `(day, symbol)` diverges iff the candidate decision differs from the
    champion's (R2.2). Comparing the `decision` string (LONG/SHORT/HOLD) captures
    direction too, so no separate direction comparison is needed. The
    champion-absent → `_CHAMPION_ABSENT` HOLD substitution is the caller's.
    """
    return candidate_decision != champion_decision


# --- The daily layer ----------------------------------------------------------


def run_daily_layer(
    candidate: Candidate,
    window: ReplayWindow,
    data_port: DataPort,
    *,
    champion_decisions: Mapping[tuple[str, str], Decision] | None = None,
    query_trace: QueryTraceFn | None = None,
    champion_keys: Mapping[str, Any] | None = None,
    is_boundary: str | None = None,
    decide_fn: DecideFn = _landed_decide,
    features_fn: FeaturesFn = compute_daily_features,
) -> list[DailyDecision]:
    """Run the per-day candidate-decision + divergence-detection layer.

    For each (trading day D, ticker) in `window`, drive `features_fn`
    (point-in-time) then `decide_fn` with the candidate's `ParamSnapshot` to
    reconstruct the candidate's OWN `ReactiveDecision` (R2.1/R3.1/R3.3), and flag
    divergence against the champion's indexed decision (R2.2). One `DailyDecision`
    per (day, ticker), in the window's ticker order × sorted-days order (R9.1).

    The champion index is supplied one of two ways (the second is the prefetch
    path the harness uses in prod):
      - `champion_decisions`: a PRE-INDEXED `{(day, symbol): Decision}` mapping
        (tests pass this directly — no DB).
      - `query_trace` + `champion_keys` + `is_boundary`: the daily layer prefetches
        the index ONCE via `index_champion_decisions` (production path).

    Args:
        candidate: the candidate config — its `param_snapshot` drives `decide`
            (R1.3/R3.1). A snapshot is required (the reactive decision needs one);
            a candidate with no snapshot is a contract error.
        window: the historical window (caller-supplied; no CV scheme — R1.2).
        data_port: the injected point-in-time `DataPort` (R9.2 isolation seam).
        champion_decisions: a pre-indexed champion-decision mapping (mutually
            exclusive with the prefetch args).
        query_trace: the injected decision-trace reader (prefetch path).
        champion_keys: the champion's correlation keys (prefetch path).
        is_boundary: the `until` temporal-firewall boundary (prefetch path).
        decide_fn: the reactive decision core (default the landed `decide`; tests
            inject `stub_decide`). NEVER reimplemented here (R3.3).
        features_fn: the daily feature adapter (default the landed
            `compute_daily_features`; tests inject a stub).

    Direction is NOT a caller argument: it is SELECTED per day from the tactical
    bin via `select_direction` (Req 12.5, §12.3). A non-directional bin
    (`neutral`/`unavailable`/degraded features) yields no candidate decision — a
    flat day (no `decide` call). A directional bin drives `decide` with the
    selected LONG/SHORT side, so SHORT is reconstructable.

    Returns:
        `list[DailyDecision]` — one per (trading day, ticker), the 2.4 seam.
    """
    snapshot = candidate.param_snapshot
    if snapshot is None:
        raise ValueError(
            "run_daily_layer: candidate.param_snapshot is required to drive the "
            "reactive decision core (R3.1)."
        )

    index = _resolve_champion_index(
        champion_decisions=champion_decisions,
        query_trace=query_trace,
        champion_keys=champion_keys,
        is_boundary=is_boundary,
    )

    results: list[DailyDecision] = []
    for symbol in window.tickers:
        for day in _trading_days(symbol, window, data_port):
            results.append(
                _daily_decision_for(
                    symbol, day, snapshot, data_port, decide_fn, features_fn, index
                )
            )
    return results


def _daily_decision_for(
    symbol: str,
    day: str,
    snapshot: ParamSnapshot,
    data_port: DataPort,
    decide_fn: DecideFn,
    features_fn: FeaturesFn,
    index: Mapping[tuple[str, str], Decision],
) -> DailyDecision:
    """Build the one `DailyDecision` for `(day, symbol)`: select direction from
    the tactical bin, then either DRIVE `decide` (directional bin) or emit a
    flat/no-trade record (non-directional bin — no `decide` call).

    The champion lookup (`.get(..., _CHAMPION_ABSENT)`) is the only place the
    champion-absent → HOLD substitution happens. A flat day's effective decision
    is HOLD (not actionable), so it diverges iff the champion traded but NEVER
    needs an intraday re-fetch.
    """
    champion = index.get((day, symbol), _CHAMPION_ABSENT)

    features = features_fn(symbol, day, data_port)
    tactical_bin = _read_tactical_bin(features)
    direction = select_direction(features)

    if direction is None:
        # Non-directional bin (neutral/unavailable) or degraded features → a
        # flat/no-trade day: no `decide` call, no candidate decision (Req 12.5).
        # Effective decision is HOLD for divergence; never needs an intraday path.
        return DailyDecision(
            as_of_day=day,
            symbol=symbol,
            decision=None,
            tactical_bin=tactical_bin,
            champion_decision=champion,
            diverged=_diverges("HOLD", champion),
            needs_intraday_refetch=False,
        )

    decision = decide_fn(features, direction, snapshot)
    actionable = decision.decision != "HOLD"
    diverged = _diverges(decision.decision, champion)
    return DailyDecision(
        as_of_day=day,
        symbol=symbol,
        decision=decision,
        tactical_bin=tactical_bin,
        champion_decision=champion,
        diverged=diverged,
        needs_intraday_refetch=diverged and actionable,
    )


def _read_tactical_bin(features: Any) -> str | None:
    """The verbatim `raw["tactical_bin"]` for the attributable-skip record, or
    `None` if the feature object carries no `raw` (a `FeatureFailure`)."""
    raw = getattr(features, "raw", None)
    if not isinstance(raw, Mapping):
        return None
    return raw.get(_TACTICAL_BIN_KEY)


def _resolve_champion_index(
    *,
    champion_decisions: Mapping[tuple[str, str], Decision] | None,
    query_trace: QueryTraceFn | None,
    champion_keys: Mapping[str, Any] | None,
    is_boundary: str | None,
) -> Mapping[tuple[str, str], Decision]:
    """Resolve the champion index: a pre-indexed mapping, or ONE prefetch.

    Pre-indexed wins if supplied (the tests' direct path). Otherwise prefetch via
    `index_champion_decisions` (the production path) — which calls `query_trace`
    EXACTLY ONCE. If neither is supplied, treat the champion as fully absent
    (an empty index → every actionable day diverges; the no-champion baseline).
    """
    if champion_decisions is not None:
        return champion_decisions
    if query_trace is not None:
        if is_boundary is None:
            raise ValueError(
                "run_daily_layer: a prefetch (query_trace) requires `is_boundary` "
                "(the `until` temporal-firewall boundary)."
            )
        return index_champion_decisions(
            query_trace, champion_keys or {}, until=is_boundary
        )
    return {}


# ============================================================================ #
# Task 2.4 — decision→order construction + survival admit gating.
#
# The NEXT simulator layer above the daily layer: turn a directional candidate
# `ReactiveDecision` (from `run_daily_layer`) into a survival-legal
# `ProposedOrder`, then drive the LANDED `src.survival.gate.admit` veto with the
# candidate's `SurvivalParameters`. NON-BEHAVIORAL: this MIRRORS the
# execution-daemon `order_builder` rule (its design line 144/355 — Req 11.1-11.6)
# and DRIVES the real landed `admit`; it never imports the daemon (boundary-
# forbidden) and never reimplements the survival logic (R3.3).
#
# Source of truth: requirements.md R2 AC 2.3, R3 AC 3.2/3.3; design.md
# `simulator` "Core algorithms #2 (decision→order construction)" + the
# execution-daemon `order_builder` component (the authoritative rule).
# ============================================================================ #

# The protective-stop distance multiplier (stop = reference ∓ atr × mult). The
# AUTHORITATIVE home of this knob is the daemon's `DaemonConfig.stop_loss_atr_mult`
# (execution-daemon design line 135) — which is boundary-forbidden to import here,
# and `SurvivalParameters` carries NO stop-loss mult field. So the replay layer
# defines its OWN module default; tests pass an explicit mult to assert the exact
# `reference ∓ atr × mult` formula. Re-sourcing this from a shared config when the
# daemon config lands is a revalidation trigger (the 2.5 seam / R10.3).
DEFAULT_STOP_LOSS_ATR_MULT: float = 3.0

# The recognized directional sides (mirrors the survival gate's
# `_RECOGNIZED_DIRECTIONS`; the broker `Direction` enum values). A SHORT-open is
# expressed as `intent="BUY"` + `direction="SHORT"` (NOT a SELL) — Req 11.1.
_OPEN_INTENT: str = "BUY"


def build_order(
    decision: ReactiveDecision | None,
    *,
    position: Position | None,
    params: SurvivalParameters,
    reference_price: float,
    atr: float | None,
    symbol: str = "",
    stop_loss_atr_mult: float = DEFAULT_STOP_LOSS_ATR_MULT,
) -> ProposedOrder | None:
    """Pure decision→order translator — MIRRORS the daemon `order_builder` rule.

    Turns a directional candidate `ReactiveDecision` + the current held position
    (if any) + the candidate `SurvivalParameters` + the reference price (last
    close) + ATR into a single survival-legal `ProposedOrder`. Pure / no I/O /
    deterministic — inner-ring testable with no `admit`, no DataPort (P14).

    The rule (execution-daemon design line 144/355, Req 11.1-11.6):

      - **Intent + direction (Req 11.1).** An OPEN on the decided side is
        `intent="BUY"` carrying the decided `direction` — *including a short
        open*: opening short exposure is **`BUY` + `Direction.SHORT`**, never a
        `SELL` (the venue side-inversion is the broker mapper's concern, not this
        layer's). A decision opposite to a held position is a **reduce** (`TRIM`
        partial / `SELL` full close).
      - **Volume (Req 11.2).** From `decision.sizing_hint` (the advisory above-
        threshold scalar), capped by `params.per_order_size_max`. A missing
        sizing_hint degrades to the cap (the size limit is the binding bound).
      - **Protective stop-loss (Req 11.3).** A PRICE LEVEL =
        `reference ∓ (atr × stop_loss_atr_mult)` — **minus** for a LONG (stop
        below), **plus** for a SHORT (stop above). This satisfies survival's
        mandatory-stop check by construction. A degenerate/absent `atr` is a
        reactive-contract violation (an actionable decision should always carry
        one) → defense-in-depth no-order (returns None) rather than a stop-less
        order that admit would reject for `missing_sl`.
      - **Reduce clamp (Req 11.4/11.6).** A reduce is **clamped ≤ the held
        volume** — NO flatten-then-flip in a single order in v0.1 (a reversal
        waits for a later post-flat tick). The reduce order is **opposite-side to
        the held position** (the decided side), so survival's `admit` true-exit
        short-circuit classifies it as a net-reducing exit (gate.py:457: a
        same-side order reads as an *add*). The daemon's `position_id` targeting
        has **no home on survival's `ProposedOrder`** (which carries only
        `{symbol, intent, direction, volume, stop_loss}`) — that mapping is the
        named daemon→survival adaptation seam (daemon design line 137/168); under
        the one-position-per-symbol invariant the reduce targets by SYMBOL here.

    HOLD or a `None` decision (a flat/no-trade day) ⇒ **no order** (returns None).

    Args:
        decision: the candidate's `ReactiveDecision`, or `None` for a flat day.
        position: the currently held `Position` in this symbol (None if flat).
        params: the candidate `SurvivalParameters` (its `per_order_size_max`
            caps volume).
        reference_price: the last close (the candidate's surfaced reference;
            daemon design CN-4) the stop level is anchored on.
        atr: the ATR feature (`features.raw["atr"]`) the stop distance scales by.
        symbol: the traded name (the daily layer supplies it — the
            `ReactiveDecision` substrate carries no symbol). Falls back to the
            held position's symbol on a reduce.
        stop_loss_atr_mult: the stop-distance multiplier (module default; the
            daemon's authoritative home is `DaemonConfig`).

    Returns:
        a survival-legal `ProposedOrder`, or `None` on HOLD / a flat day / an
        absent ATR (defense-in-depth).
    """
    if decision is None or decision.decision == "HOLD":
        return None  # a flat/no-trade day — no order.
    if atr is None:
        # Defense-in-depth (daemon CN-3): an actionable decision should always
        # carry an ATR; an absent one is a reactive-contract violation → no order
        # (a stop-less order would be rejected `missing_sl` by admit anyway).
        return None

    side: str = decision.decision  # "LONG" / "SHORT" (the decided side, Req 11.1)
    volume = _capped_volume(decision.sizing_hint, params.per_order_size_max)
    order_symbol = symbol or (position.symbol if position is not None else "")

    # Reduce vs open classification by EFFECT on the held position (P7-aligned):
    # an opposite-side decision against the held position (same symbol — the
    # caller passes the day's held position in this symbol) is a reduce/close.
    if position is not None and position.direction != side:
        return _reduce_order(
            order_symbol, side, position, volume, reference_price, atr, stop_loss_atr_mult
        )

    # Open / add on the decided side: BUY + the decided direction (SHORT-open =
    # BUY + Direction.SHORT — Req 11.1).
    stop = _stop_loss(side, reference_price, atr, stop_loss_atr_mult)
    return ProposedOrder(
        symbol=order_symbol,
        intent=_OPEN_INTENT,
        direction=side,
        volume=volume,
        stop_loss=stop,
    )


def _capped_volume(sizing_hint: float | None, per_order_size_max: float) -> float:
    """Volume from the advisory `sizing_hint`, capped by `per_order_size_max`
    (Req 11.2). A missing sizing_hint degrades to the cap (the size limit binds).
    """
    if sizing_hint is None:
        return per_order_size_max
    return min(sizing_hint, per_order_size_max)


def _stop_loss(side: str, reference_price: float, atr: float, mult: float) -> float:
    """The protective stop-loss PRICE LEVEL (Req 11.3): `reference − atr×mult` for
    a LONG (stop below), `reference + atr×mult` for a SHORT (stop above)."""
    distance = atr * mult
    return reference_price - distance if side == "LONG" else reference_price + distance


def _reduce_order(
    symbol: str,
    side: str,
    position: Position,
    volume: float,
    reference_price: float,
    atr: float,
    mult: float,
) -> ProposedOrder:
    """A reduce/close of the held `position` (an opposite-side decision).

    Volume is **clamped ≤ the held volume** — no flatten-then-flip in v0.1 (Req
    11.6); a full-clamp (`== held`) is a SELL (full close), a partial is a TRIM
    (Req 11.1). The order's `direction` is the **decided side** (`side`), which is
    OPPOSITE the held position — so survival's `admit` classifies it as a true
    net-reducing exit (gate.py:457 treats a same-side order as an *add*). The
    stop level anchors on that decided side. Survival's `ProposedOrder` carries
    no `position_id`; under the one-position-per-symbol invariant the reduce
    targets by SYMBOL (the daemon's id targeting is the daemon→survival
    adaptation seam — design line 137/168)."""
    clamped = min(volume, position.volume)
    full = clamped >= position.volume
    intent = "SELL" if full else "TRIM"
    stop = _stop_loss(side, reference_price, atr, mult)
    return ProposedOrder(
        symbol=symbol or position.symbol,
        intent=intent,
        direction=side,
        volume=clamped,
        stop_loss=stop,
    )


# Admit-core injection alias (default the landed `admit`; tests inject a stub).
AdmitFn = Callable[..., AdmitDecision]


def apply_admit_gating(
    decision: ReactiveDecision | None,
    *,
    position: Position | None,
    params: SurvivalParameters,
    reference_price: float,
    atr: float | None,
    account: AccountState,
    op_state: OperationalState,
    evaluation: OrderEvaluation,
    clock: ClockState,
    symbol: str = "",
    stop_loss_atr_mult: float = DEFAULT_STOP_LOSS_ATR_MULT,
    admit_fn: AdmitFn | None = None,
) -> ProposedOrder | None:
    """Build the order, then drive the LANDED survival `admit` veto (R3.2/R3.3).

    The 2.4 step proper: `build_order` → `admit`. `admit_fn` defaults to the
    REAL landed `src.survival.gate.admit` (None ⇒ real) so the integration is
    exercised; a test may inject the 1.4-style stub for isolation. The candidate's
    `SurvivalParameters` drive the veto (R3.1).

    Gating outcomes (design `simulator` "Core algorithms #2"):
      - the builder returns no order (HOLD / flat day / absent ATR) ⇒ flat (None).
      - `admit=REJECT` ⇒ **no order** (a flat day — R3.2).
      - `admit=ALLOW` ⇒ the order as built.
      - an `advisory_max_volume` (a size-limit REJECT) ⇒ **resize to it** and
        re-build + re-admit ONCE. The ATR stop-loss is volume-independent, so the
        re-build reaches a fixpoint in one pass (daemon design line 216).

    Returns the admitted `ProposedOrder`, or `None` (a flat day) on a non-advisory
    REJECT / no buildable order.

    SEAM (2.5): a bare `None` currently collapses FOUR distinct flat outcomes —
    HOLD, a non-directional flat day, an absent-ATR contract violation, and an
    admit REJECT. `OutcomeRecord.survival_events` wants the `"admit_reject"` tag
    (types.py:128), so the `outcomes` layer (task 2.5) must distinguish the
    admit-REJECT case from a no-decision flat (e.g. this step surfacing the
    `AdmitDecision`/binding-constraint alongside the order) rather than reading a
    bare `None`. Not built here (the simulator emits no `OutcomeRecord`).
    """
    admit = admit_fn if admit_fn is not None else _landed_admit

    order = build_order(
        decision,
        position=position,
        params=params,
        reference_price=reference_price,
        atr=atr,
        stop_loss_atr_mult=stop_loss_atr_mult,
    )
    if order is None:
        return None  # HOLD / flat day / absent ATR — no order to admit.
    if symbol and not order.symbol:
        order = _with_symbol(order, symbol)

    verdict = admit(order, account, op_state, params, clock, evaluation)
    if verdict.decision == "ALLOW":
        return order

    # A size-limit REJECT carries an advisory cap → resize + re-admit ONCE.
    if verdict.advisory_max_volume is not None:
        resized = _resize(order, verdict.advisory_max_volume)
        re_verdict = admit(resized, account, op_state, params, clock, evaluation)
        return resized if re_verdict.decision == "ALLOW" else None

    return None  # a non-advisory REJECT ⇒ a flat day (R3.2).


def _with_symbol(order: ProposedOrder, symbol: str) -> ProposedOrder:
    """Thread the day's symbol onto an order the builder left blank (the decision
    substrate carries no symbol; the daily layer supplies it)."""
    from dataclasses import replace

    return replace(order, symbol=symbol)


def _resize(order: ProposedOrder, advisory_max_volume: float) -> ProposedOrder:
    """Resize an order to the admit advisory cap (re-build is a pure volume swap —
    the ATR stop-loss is volume-independent, so one pass reaches a fixpoint)."""
    from dataclasses import replace

    return replace(order, volume=advisory_max_volume)


# --- Code-track candidate (DEFERRABLE for v0.1 — a guarded branch) ------------


def run_code_track_candidate(*args, **kwargs):  # noqa: ANN002, ANN003, ANN201
    """The code-track candidate path — DEFERRED for v0.1 (a guarded branch, not
    built).

    `walkforward-tuning-loop` may vary a `code_version` candidate (R3.2 "where the
    code track is exercised"); v0.1 does NOT build it (per the spec the code track
    is deferrable). This is the named seam — a guard, not an implementation — so
    the deferral is explicit and a later task has an anchor.
    """
    raise NotImplementedError(
        "code-track candidate replay is deferred for v0.1 (a guarded branch, not "
        "built) — see requirements R3.2 (code track exercise is deferrable)."
    )


__all__ = [
    "DEFAULT_STOP_LOSS_ATR_MULT",
    "DailyDecision",
    "apply_admit_gating",
    "build_order",
    "index_champion_decisions",
    "run_code_track_candidate",
    "run_daily_layer",
    "select_direction",
]
