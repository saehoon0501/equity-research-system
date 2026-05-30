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

- **Direction is hard-defaulted LONG (``_DEFAULT_DIRECTION``).** The reactive
  model NEVER selects/flips the side — it confirms the caller-supplied direction
  or HOLDs — so the daily layer must SUPPLY a side, and v0.1 drives a LONG probe.
  Consequence the later tasks MUST account for: the candidate's decision space is
  ``{LONG, HOLD}`` — it can never reconstruct a champion **SHORT**. Any
  champion-SHORT day therefore always reads as divergent, and (more seriously)
  champion-reproduction fidelity (R7, a later task) will FAIL on any SHORT day
  because re-simulating the champion's own config still cannot emit SHORT. Before
  fidelity or any SHORT-capable replay works, direction must be threaded through
  the candidate (or read from the champion's recorded direction-*input*, never
  its output decision). Threading direction is OUT OF SCOPE for 2.3 — this is the
  documented seam for 2.4+.

Pure leaf (P1 / design §Dependency direction
``types → data_client → features_adapter → simulator``): imports the owned
``types``, the sibling ``features_adapter``, and the landed ``signal_model``
core only — no httpx, no MCP, no DB, no consumer-spec import. It does NOT import
``telemetry.reader`` (``query_trace`` is INJECTED — the real reader in prod, a
fake/pre-indexed dict in tests — preserving R9.2 isolation).

Source of truth: requirements.md R2 AC 2.1/2.2, R3 AC 3.1/3.3, R9 AC 9.1;
design.md `simulator` "Core algorithms #1" + the System Flow daily leg + the
Components table (row 171) / Traceability (rows 154-155).

Requirements: 2.1, 2.2, 3.1, 3.3.
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

# The candidate's caller-supplied side for the daily decision. The reactive
# model NEVER selects/flips the side (it confirms the caller direction or
# HOLDs); the daily layer drives a LONG probe per the v0.1 long-bias reactive
# convention. (A later task may thread a per-name direction through the
# candidate config; this is the documented default seam.)
_DEFAULT_DIRECTION: Direction = "LONG"


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
        never the champion's recorded outcome — R2.1/R3.3).
      - `champion_decision`: the champion's indexed decision for `(day, symbol)`,
        or the `_CHAMPION_ABSENT` HOLD sentinel when the champion has no record.
      - `diverged`: candidate decision != champion decision (R2.2 — INCLUDING
        champion-HOLD/absent vs candidate-actionable).
      - `needs_intraday_refetch`: `diverged AND candidate actionable` — the flag
        the (later) intraday layer reads to re-fetch this name's point-in-time
        path. A divergent-but-candidate-HOLD day needs no intraday path, so this
        is False there even though `diverged` is True.
    """

    as_of_day: str
    symbol: str
    decision: ReactiveDecision
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
    direction: Direction = _DEFAULT_DIRECTION,
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
        direction: the caller-supplied side driven into `decide` (default LONG —
            the model confirms it or HOLDs; it never selects/flips the side).

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
            decision = _decide_for_day(
                symbol, day, snapshot, data_port, decide_fn, features_fn, direction
            )
            champion = index.get((day, symbol), _CHAMPION_ABSENT)
            diverged = _diverges(decision.decision, champion)
            actionable = decision.decision != "HOLD"
            results.append(
                DailyDecision(
                    as_of_day=day,
                    symbol=symbol,
                    decision=decision,
                    champion_decision=champion,
                    diverged=diverged,
                    needs_intraday_refetch=diverged and actionable,
                )
            )
    return results


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


def _decide_for_day(
    symbol: str,
    day: str,
    snapshot: ParamSnapshot,
    data_port: DataPort,
    decide_fn: DecideFn,
    features_fn: FeaturesFn,
    direction: Direction,
) -> ReactiveDecision:
    """Build features as-of D and DRIVE `decide` → the candidate's `ReactiveDecision`.

    The candidate reconstructs its OWN decision (R2.1): features are computed
    point-in-time via `features_fn`, then `decide_fn` is driven with the
    candidate's `snapshot` (R3.1). `decide` is DRIVEN, never reimplemented
    (R3.3). A `FeatureFailure` flows through `decide` verbatim (it degrades to a
    HOLD carrying the failure reason — the landed core owns that).
    """
    features = features_fn(symbol, day, data_port)
    return decide_fn(features, direction, snapshot)


__all__ = [
    "DailyDecision",
    "index_champion_decisions",
    "run_daily_layer",
]
