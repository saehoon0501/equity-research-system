"""Replay Harness: the public entry — `replay_candidate` (Task 3.1, INTEGRATION).

The single contract `walkforward-tuning-loop` calls per candidate config per
CPCV partition (design §Components "harness"; requirements R1.1/R1.2). This is
the explicit cross-leaf WIRING task: it orchestrates the landed replay leaves
into one entry point and adds the champion-reproduction fidelity precondition.

What `replay_candidate` does (design `harness` block lines 215-216 + the System
Flow):

  1. **Construct the production `DataPort`** (`MassiveDataClient`) when none is
     injected (tests inject a `FixtureDataPort` — the R9.2 isolation seam).
  2. **Prefetch the champion decisions ONCE** (`query_trace(kind='decision')`) →
     two indexes from one read: the `(day, symbol) → decision` divergence index
     the simulator's daily layer consumes, and the `trace_id → (symbol,
     direction)` map the fidelity fill-join needs.
  3. **Candidate pass** — drive the per-day simulator loop on the CANDIDATE
     config over the window, threading the per-day position/account state
     SEQUENTIALLY, collecting one `OutcomeRecord` per (day, ticker) (R1.1/R2.1/
     R2.3). On an admit-REJECT day the harness threads `admit_rejected=True` into
     `outcomes.assemble_outcome` so `survival_events` carries the tag (the 2.8
     seam — `apply_admit_gating`'s bare `None` cannot carry it).
  4. **Champion re-sim (R7.1)** — read the champion's PINNED config (`ParamSnapshot`
     + `SurvivalParameters`) from P2 `run_parameters_snapshot` by `param_version`,
     re-run the SAME per-day loop on the champion config, synthesize the
     harness-joined `recorded_fills` dicts (parent_trace_id → decision join for
     symbol+direction; the leg side derived from event-ts ordering within each
     §16.1 (day, symbol) group — the 2.2 contract), and call `fidelity.compare`
     → attach the `FidelityResult`.
  5. Return `ReplayResult{records, fidelity}`.

CONSUMPTION BOUNDARY (R10.1/R10.2): the harness is a READ-ONLY consumer — all DB
access routes through SELECT-only readers (`query_trace`, the P2 champion-config
reader); it writes NOTHING to the trace/ledger and alters no schema. It performs
NO CPCV partitioning, NO survival-net metric, NO calibration, NO gate, NO fit, NO
publish, and NO live trading — those are the consumer `walkforward-tuning-loop`'s.

Dependency direction (design line 121): the harness sits at the RIGHT end of the
strict left→right chain `types → data_client → features_adapter → simulator →
outcomes → harness`; `fidelity` is a pure comparator the harness orchestrates
(it NEVER imports `simulator`). The harness may import all the landed replay
leaves + `telemetry.reader` + the P2 read + survival read-only; it modifies none
of them (this is the explicit integration task, so cross-leaf wiring lives here).

Injection seams (R9.2 inner-ring isolation — mirrors `run_daily_layer`): the
DB-facing reads (`query_trace_fn`, `champion_config_reader`) and the driven cores
(`decide_fn`, `features_fn`, `admit_fn`) are keyword-only injectables defaulting
to the real landed functions; tests inject fakes/stubs so the full loop runs with
no live feed, no LLM, and no live DB.

Source of truth: requirements.md Requirement 1 AC 1.1/1.2, Requirement 7 AC 7.1,
Requirement 10 AC 10.1/10.2; design.md the `harness` component block + the
dependency-direction note + the System Flow + Core-algorithms #5 (fill-pairing).

Requirements: 1.1, 1.2, 7.1, 10.1, 10.2.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Mapping
from typing import Any

from src.reactive.params import ParamSnapshot
from src.reactive.replay import fidelity, outcomes
from src.reactive.replay.data_client import MassiveDataClient
from src.reactive.replay.features_adapter import compute_daily_features
from src.reactive.replay.simulator import (
    DEFAULT_STOP_LOSS_ATR_MULT,
    DailyDecision,
    apply_admit_gating,
    build_order,
    day_round_trip_pnl,
    flatten_before_close,
    index_champion_decisions,
    run_daily_layer,
    simulate_fill,
)
from src.reactive.replay.types import (
    Candidate,
    DataPort,
    FidelityResult,
    OutcomeRecord,
    ReplayResult,
    ReplayWindow,
)
from src.reactive.signal_model import decide as _landed_decide
from src.survival.params import DEFAULTS as _SURVIVAL_DEFAULTS
from src.survival.params import SurvivalParameters
from src.survival.params import resolve as _survival_resolve
from src.survival.types import (
    AccountState,
    ClockState,
    OperationalState,
    OrderEvaluation,
    Position,
)

# The freeform decision-row trace-payload keys the champion symbol + direction
# are read from (daemon-undetermined, the telemetry payload is schema-free; see
# simulator.py `_CHAMPION_SYMBOL_KEY`). Retargeting these is the revalidation
# trigger when the daemon lands (R10.3).
_CHAMPION_SYMBOL_KEY = "symbol"
_CHAMPION_DECISION_KEY = "decision"

# The §16.1 entry-leg venue side per position direction (fidelity `_is_entry`:
# LONG opens on BUY, SHORT opens on SELL). The exit/flatten leg is the opposite.
_OPEN_SIDE: dict[str, str] = {"LONG": "BUY", "SHORT": "SELL"}
_CLOSE_SIDE: dict[str, str] = {"LONG": "SELL", "SHORT": "BUY"}

# The default champion-reproduction tolerance (R7.1 — an ABSOLUTE aggregate
# tolerance; the plain reading of "within a configured tolerance"). The consumer
# may override per partition. Set non-trivially wide of float noise by default;
# the tuner tightens it. (tasks.md 2.2: the price-only recorded vs total-return
# simulated dividend-basis asymmetry can false-fail a dividend day — the consumer
# either widens this or strips dividends; documented as a CONCERN.)
_DEFAULT_TOLERANCE = 0.01

# A reader that resolves the champion's pinned config from P2
# `run_parameters_snapshot` by `param_version` → a `Candidate`.
ChampionConfigReader = Callable[..., Candidate]
QueryTraceFn = Callable[..., list[dict]]
DecideFn = Callable[..., Any]
FeaturesFn = Callable[..., Any]
AdmitFn = Callable[..., Any] | None


# ============================================================================ #
# Public entry — replay_candidate (the contract walkforward calls)
# ============================================================================ #


def replay_candidate(
    candidate: Candidate,
    window: ReplayWindow,
    *,
    data_port: DataPort | None = None,
    conn: Any = None,
    tolerance: float = _DEFAULT_TOLERANCE,
    champion_keys: Mapping[str, Any] | None = None,
    until: str | None = None,
    query_trace_fn: QueryTraceFn | None = None,
    champion_config_reader: ChampionConfigReader | None = None,
    decide_fn: DecideFn | None = None,
    features_fn: FeaturesFn | None = None,
    admit_fn: AdmitFn = None,
) -> ReplayResult:
    """Backtest ONE candidate config over ONE window → `ReplayResult` (R1.1/R1.2).

    Args:
        candidate: the candidate config (`param_snapshot` / `survival_parameters`
            / `code_version`; R1.3). Drives the candidate decision-and-account path.
        window: the historical window to replay — the caller supplies one per CPCV
            partition; the harness imposes NO cross-validation scheme (R1.2).
        data_port: the point-in-time `DataPort`. `None` ⇒ construct the production
            `MassiveDataClient` (tests inject a `FixtureDataPort` — R9.2 seam).
        conn: a read-only psycopg connection threaded to the DB readers (the
            `_dsn()` dry-run convention); `None` ⇒ the readers open their own.
        tolerance: the champion-reproduction ABSOLUTE tolerance (R7.1).
        champion_keys: the champion's correlation keys (`code_version`,
            `param_version`, `walk_forward_window`) — the P3 four-key set the
            champion ran under. Used for the decision/fill reads + the P2 config
            read. `None` defaults to the window-bounded read with no extra filter
            (a CONCERN: the champion-identity convention is unpinned — see module).
        until: the temporal-firewall boundary (`event_ts <= until`) for the
            champion baseline read; `None` ⇒ the window end (the champion baseline
            may legitimately span the full window — R4.1 note).
        query_trace_fn: the injected decision-trace reader (`telemetry.reader.
            query_trace` in prod; a fake in tests). Read-only (R10.1).
        champion_config_reader: the injected P2 champion-config reader
            (`param_version → Candidate`); defaults to the landed P2 read.
        decide_fn / features_fn / admit_fn: the driven cores (defaulting to the
            landed reactive `decide` / `compute_daily_features` / survival
            `admit`); tests inject stubs (R9.2). NEVER reimplemented (R3.3).

    Returns:
        `ReplayResult{records, fidelity}` — the per-period outcome records (R1.1/
        R8.1) + the champion-reproduction fidelity precondition (R7).
    """
    port = data_port if data_port is not None else MassiveDataClient()
    keys = _as_key_filters(champion_keys)
    boundary = until if until is not None else window.end
    # The landed reader imports `psycopg` at module top (a DB driver absent from
    # the inner-ring venv); import it LAZILY only on the prod path so the harness
    # module — and the R9.2 fixture-injected tests — import with no DB driver.
    q_trace = query_trace_fn if query_trace_fn is not None else _landed_query_trace()
    config_reader = (
        champion_config_reader
        if champion_config_reader is not None
        else _read_champion_config_p2
    )
    decide = decide_fn if decide_fn is not None else _landed_decide
    features = features_fn if features_fn is not None else compute_daily_features

    # --- 1. Prefetch the champion decisions ONCE (R10.1 read-only) ----------
    # One read yields both the divergence index (daily layer) and the fill-join
    # map (symbol+direction by decision trace_id) — no per-day round-trip.
    champion_decision_rows = q_trace(_decision_filters(keys, boundary))
    champion_index = index_champion_decisions(
        lambda _filters: champion_decision_rows, keys, until=boundary
    )
    decision_join = _index_decision_join(champion_decision_rows)

    # --- 2. Candidate pass — the candidate's OWN per-day path (R1.1/R2.1) ---
    records = _simulate_config(
        candidate,
        window,
        port,
        champion_index=champion_index,
        decide=decide,
        features=features,
        admit_fn=admit_fn,
    )

    # --- 3. Champion re-sim → the fidelity precondition (R7.1) --------------
    champion_param_version = keys.get("param_version")
    fidelity_result = _champion_fidelity(
        champion_param_version,
        window,
        port,
        champion_index=champion_index,
        decision_join=decision_join,
        q_trace=q_trace,
        keys=keys,
        boundary=boundary,
        config_reader=config_reader,
        decide=decide,
        features=features,
        admit_fn=admit_fn,
        tolerance=tolerance,
        conn=conn,
    )

    return ReplayResult(records=records, fidelity=fidelity_result)


# ============================================================================ #
# The per-day loop — driven once per config (candidate, then champion)
# ============================================================================ #


def _simulate_config(
    config: Candidate,
    window: ReplayWindow,
    port: DataPort,
    *,
    champion_index: Mapping[tuple[str, str], str],
    decide: DecideFn,
    features: FeaturesFn,
    admit_fn: AdmitFn,
) -> list[OutcomeRecord]:
    """Drive the simulator over the window for ONE config → per-day OutcomeRecords.

    Threads the daily layer (`run_daily_layer` → per-day `DailyDecision` via the
    tactical-bin direction rule) into the intraday account path (`build_order` →
    `apply_admit_gating` → `simulate_fill` → `flatten_before_close` →
    `day_round_trip_pnl` → `outcomes.assemble_outcome`), per day, SEQUENTIALLY.

    §16.1 forces flat-before-close EVERY day, so no position carries overnight:
    each day opens flat (`position=None`) and the "sequential" account path is
    cumulative equity day-over-day (no margin simulator built here — out of
    boundary; flagged as a CONCERN). The admit-REJECT tag is threaded via the
    `build_order != None AND apply_admit_gating == None` disambiguation (the 2.8
    seam — `apply_admit_gating`'s bare `None` cannot carry it).
    """
    survival_params = _survival_params(config)

    daily_decisions = run_daily_layer(
        config,
        window,
        port,
        champion_decisions=champion_index,
        decide_fn=decide,
        features_fn=features,
    )

    records: list[OutcomeRecord] = []
    account = _seed_account()
    equity = account.equity
    for daily in daily_decisions:
        record, equity = _simulate_day(
            daily,
            port,
            survival_params=survival_params,
            features=features,
            account=account,
            equity=equity,
            admit_fn=admit_fn,
        )
        records.append(record)
    return records


def _simulate_day(
    daily: DailyDecision,
    port: DataPort,
    *,
    survival_params: SurvivalParameters,
    features: FeaturesFn,
    account: AccountState,
    equity: float,
    admit_fn: AdmitFn,
) -> tuple[OutcomeRecord, float]:
    """Run ONE trading day's intraday account path → its `OutcomeRecord`.

    A flat day (HOLD / non-directional bin / no order built) short-circuits to a
    no-trade record (no intraday fetches — the cost bound). An actionable day
    builds the order, gates it through `admit` (threading `admit_rejected`), fills
    the entry, force-flattens before close, computes total-return P&L, and
    assembles the record. Returns the record + the day-end equity (cumulative).
    """
    decision = daily.decision
    symbol = daily.symbol
    day = daily.as_of_day

    # A flat/no-trade day (non-directional bin) — no decision, no order, no fetch.
    if decision is None or decision.decision == "HOLD":
        round_trip = flatten_before_close(
            None, entry_fill=None, port=port, symbol=symbol, day=day
        )
        record = outcomes.assemble_outcome(daily, round_trip, 0.0, admit_rejected=False)
        return record, equity

    # An actionable day: source the reference price (last as-of close) + ATR.
    reference_price = _last_close(port, symbol, day)
    atr = _atr_from_features(features, symbol, day, port)

    # Each day opens FLAT (§16.1 flattens every prior day's position) — position=None.
    position: Position | None = None

    # Build → admit-gate. Disambiguate the admit-REJECT flat (the 2.8 seam):
    # build_order returns None ONLY for the non-admit flat cases (HOLD / absent
    # ATR); a built order that the gate then drops to None is an admit REJECT.
    built = build_order(
        decision,
        position=position,
        params=survival_params,
        reference_price=reference_price,
        atr=atr,
        symbol=symbol,
        stop_loss_atr_mult=DEFAULT_STOP_LOSS_ATR_MULT,
    )
    admitted = apply_admit_gating(
        decision,
        position=position,
        params=survival_params,
        reference_price=reference_price,
        atr=atr,
        account=account,
        op_state=_clear_op_state(),
        evaluation=_clearing_evaluation(),
        clock=_clock(),
        symbol=symbol,
        stop_loss_atr_mult=DEFAULT_STOP_LOSS_ATR_MULT,
        admit_fn=admit_fn,
    )
    admit_rejected = built is not None and admitted is None

    if admitted is None:
        # A flat day (HOLD already handled above; here either absent-ATR no-build
        # or an admit REJECT — `admit_rejected` distinguishes them for the tag).
        round_trip = flatten_before_close(
            None, entry_fill=None, port=port, symbol=symbol, day=day
        )
        record = outcomes.assemble_outcome(
            daily, round_trip, 0.0, admit_rejected=admit_rejected
        )
        return record, equity

    # Fill the entry at the counterparty (bid/ask) price (R6.1), then force-flatten
    # before close (§16.1) and compute total-return P&L (R5.1).
    entry_fill = simulate_fill(admitted, port=port, symbol=symbol, ts=day)
    round_trip = flatten_before_close(
        admitted, entry_fill=entry_fill, port=port, symbol=symbol, day=day
    )
    pnl = day_round_trip_pnl(round_trip, port=port, day=day)

    record = outcomes.assemble_outcome(daily, round_trip, pnl, admit_rejected=False)
    return record, equity + pnl


# ============================================================================ #
# Champion re-sim + fidelity precondition (R7.1)
# ============================================================================ #


def _champion_fidelity(
    param_version: str | None,
    window: ReplayWindow,
    port: DataPort,
    *,
    champion_index: Mapping[tuple[str, str], str],
    decision_join: Mapping[str, tuple[str, str]],
    q_trace: QueryTraceFn,
    keys: Mapping[str, Any],
    boundary: str,
    config_reader: ChampionConfigReader,
    decide: DecideFn,
    features: FeaturesFn,
    admit_fn: AdmitFn,
    tolerance: float,
    conn: Any,
) -> FidelityResult:
    """Re-simulate the champion's OWN config + compare to its recorded fills (R7.1).

    Reads the champion's pinned config (P2 by `param_version`), re-runs the SAME
    per-day loop on it, synthesizes the harness-joined `recorded_fills` dicts from
    the champion's `kind=fill` rows (the parent_trace_id → decision join), and
    calls `fidelity.compare`. `fidelity` NEVER imports `simulator` — the harness
    orchestrates both sides (design line 211).
    """
    # Synthesize the recorded-fill baseline FIRST (the parent_trace_id → decision
    # join + the §16.1 per-group side derivation — the 2.2 contract).
    recorded_fills = _synthesize_recorded_fills(
        q_trace(_fill_filters(keys, boundary)), decision_join
    )

    # Short-circuit on an absent/sparse baseline (R7.3 — not_evaluable): with no
    # champion round trip to reproduce there is nothing to re-simulate, so SKIP
    # the P2 config read + the champion re-sim entirely and let the comparator
    # return not_evaluable. (This also keeps the candidate-only path off the DB
    # when the consumer supplies no champion fills.)
    if not _has_round_trip(recorded_fills):
        return fidelity.compare([], recorded_fills, tolerance)

    # A populated baseline exists ⇒ read the champion's pinned config (P2 by
    # param_version) — required to reproduce its admit/flatten behavior (R7.1).
    if param_version is None:
        raise ValueError(
            "a champion recorded-fill baseline is present but no param_version was "
            "supplied — cannot read the champion's pinned config to reproduce it "
            "(R7.1)."
        )
    champion_config = config_reader(param_version, conn=conn)

    simulated_champion_records = _simulate_config(
        champion_config,
        window,
        port,
        champion_index=champion_index,
        decide=decide,
        features=features,
        admit_fn=admit_fn,
    )
    return fidelity.compare(simulated_champion_records, recorded_fills, tolerance)


def _has_round_trip(recorded_fills: list[dict]) -> bool:
    """True iff at least one `(day, symbol)` group has both an entry + an exit leg.

    Mirrors `fidelity._has_any_round_trip` (the 7.3 gate) so the harness can SKIP
    the champion config read + re-sim when the baseline is empty/sparse, rather
    than paying for them only to have the comparator return not_evaluable."""
    sides: dict[tuple[str, str], set[str]] = {}
    for leg in recorded_fills:
        key = (leg["day"], leg["symbol"])
        sides.setdefault(key, set()).add(leg["side"])
    return any(len(s) >= 2 for s in sides.values())


def _synthesize_recorded_fills(
    fill_rows: list[dict],
    decision_join: Mapping[str, tuple[str, str]],
) -> list[dict]:
    """Build the harness-joined `recorded_fills` dicts (the 2.2 contract).

    Each `kind=fill` row carries NEITHER symbol NOR a buy/sell side in its trace
    payload (telemetry schema pin) — they are decision-linked. So per fill row:
      - join `parent_trace_id` → its decision row → `(symbol, direction)`;
      - derive `day` from the fill `event_ts`;
      - derive the leg `side` from event-ts ordering WITHIN each (day, symbol)
        group: under the §16.1 one-position invariant a group is one round trip,
        so the EARLIEST leg is the OPEN (`_OPEN_SIDE[direction]`) and the rest are
        the flatten/exit (`_CLOSE_SIDE[direction]`).
      - pass through `actual_fill_price` + `fill_volume` from the trace payload.

    Produces the `{day, symbol, direction, side, actual_fill_price, fill_volume}`
    dicts `fidelity.compare` FIFO-pairs. A fill whose parent decision is missing
    from the join is dropped (it cannot be attributed to a symbol/direction).
    """
    # First pass: attribute each fill to (day, symbol, direction) + its event_ts.
    enriched: list[dict[str, Any]] = []
    for row in fill_rows:
        parent = row.get("parent_trace_id")
        joined = decision_join.get(parent) if parent is not None else None
        if joined is None:
            continue  # un-joinable fill (no parent decision) — drop.
        symbol, direction = joined
        trace = row.get("trace") or {}
        day = _iso_day(row["event_ts"])
        enriched.append(
            {
                "day": day,
                "symbol": symbol,
                "direction": direction,
                "event_ts": row["event_ts"],
                "actual_fill_price": float(trace["actual_fill_price"]),
                "fill_volume": float(trace["fill_volume"]),
            }
        )

    # Second pass: per (day, symbol) group, derive the entry/exit side from the
    # event-ts ordering (earliest = open; the rest = flatten/exit).
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for leg in enriched:
        groups[(leg["day"], leg["symbol"])].append(leg)

    recorded_fills: list[dict] = []
    for legs in groups.values():
        ordered = sorted(legs, key=lambda leg: leg["event_ts"])
        for i, leg in enumerate(ordered):
            direction = leg["direction"]
            side = _OPEN_SIDE[direction] if i == 0 else _CLOSE_SIDE[direction]
            recorded_fills.append(
                {
                    "day": leg["day"],
                    "symbol": leg["symbol"],
                    "direction": direction,
                    "side": side,
                    "actual_fill_price": leg["actual_fill_price"],
                    "fill_volume": leg["fill_volume"],
                }
            )
    return recorded_fills


def _index_decision_join(decision_rows: list[dict]) -> dict[str, tuple[str, str]]:
    """Index champion DECISION rows by `trace_id → (symbol, direction)`.

    The fill-join map: a `kind=fill` row's `parent_trace_id` references its
    decision's `trace_id`; the decision's freeform trace payload carries the
    symbol + the direction (the `decision` verdict LONG/SHORT). Rows whose
    decision is HOLD carry no tradeable direction → skipped (a HOLD has no fills).
    """
    join: dict[str, tuple[str, str]] = {}
    for row in decision_rows:
        trace = row.get("trace") or {}
        symbol = trace.get(_CHAMPION_SYMBOL_KEY)
        direction = trace.get(_CHAMPION_DECISION_KEY)
        trace_id = row.get("trace_id")
        if symbol is None or trace_id is None:
            continue
        if direction not in ("LONG", "SHORT"):
            continue  # HOLD / non-directional — no tradeable fills.
        join[trace_id] = (symbol, direction)
    return join


# ============================================================================ #
# P2 champion-config read (prod path; injected/faked in tests)
# ============================================================================ #


def _read_champion_config_p2(param_version: str, *, conn: Any = None) -> Candidate:
    """Read the champion's pinned config from P2 `run_parameters_snapshot` (R7.1).

    The champion's config is the `effective_parameters_jsonb` key→value map keyed
    by `param_version` (the column does not exist directly; `param_version` lives
    INSIDE the JSONB). The resolved map is fed to the landed `survival.params.
    resolve` (the by-value pinned-key→field resolver, P2) → a `SurvivalParameters`;
    the reactive `ParamSnapshot` is reconstructed from its persisted fields. This
    is PROD-PATH ONLY — tests inject a fake reader so the JSONB mapping needs no DB.

    Read-only (R10.1): a SELECT on `run_parameters_snapshot`, no write.
    """
    import psycopg

    from src.reactive.telemetry.reader import _dsn  # the landed read-only DSN

    sql = (
        "SELECT effective_parameters_jsonb "
        "FROM run_parameters_snapshot "
        "WHERE effective_parameters_jsonb->>'param_version' = %s "
        "ORDER BY run_started_at DESC LIMIT 1"
    )
    own_conn = conn is None
    if own_conn:
        conn = psycopg.connect(_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (param_version,))
            row = cur.fetchone()
    finally:
        if own_conn:
            conn.close()

    if row is None:
        raise ValueError(
            f"no run_parameters_snapshot row for param_version={param_version!r} "
            "— the champion config is required to reproduce its path (R7.1)."
        )

    effective = row[0]
    if isinstance(effective, str):
        effective = json.loads(effective)

    survival_params = _survival_resolve(effective)
    param_snapshot = _param_snapshot_from_jsonb(effective, param_version)
    return Candidate(
        param_snapshot=param_snapshot,
        survival_parameters=survival_params,
        code_version=effective.get("code_version"),
    )


def _param_snapshot_from_jsonb(effective: Mapping[str, Any], param_version: str) -> ParamSnapshot:
    """Reconstruct the reactive `ParamSnapshot` from the P2 JSONB map (prod path).

    The reactive parameter keys live alongside the survival keys in the same
    `effective_parameters_jsonb`. This maps the persisted fields onto
    `ParamSnapshot`; a missing key falls back to the landed `DEFAULTS` field — a
    revalidation seam if the persisted reactive-key schema drifts (R10.3).
    """
    from dataclasses import fields, replace

    from src.reactive.params import DEFAULTS as _REACTIVE_DEFAULTS

    overrides: dict[str, Any] = {}
    for f in fields(_REACTIVE_DEFAULTS):
        if f.name in effective:
            overrides[f.name] = effective[f.name]
    overrides["param_version"] = param_version
    return replace(_REACTIVE_DEFAULTS, **overrides)


# ============================================================================ #
# Per-day input/state helpers
# ============================================================================ #


def _survival_params(config: Candidate) -> SurvivalParameters:
    """The candidate's `SurvivalParameters`, or the inner-ring DEFAULTS when the
    candidate varies only the reactive snapshot (R1.3 — knobs are independent)."""
    sp = config.survival_parameters
    return sp if isinstance(sp, SurvivalParameters) else _SURVIVAL_DEFAULTS


def _last_close(port: DataPort, symbol: str, day: str) -> float:
    """The last as-of close for `(symbol, day)` — the reference the stop anchors on.

    Point-in-time bounded: the bars up to and INCLUDING `day` (R4.1); the close of
    the day's own bar is the reference (the daily decision is made on the close).
    Falls back to the latest available close if the exact day's bar is absent.
    """
    bars = port.fetch_daily_bars(symbol, day, day)
    if not bars:
        bars = port.fetch_daily_bars(symbol, "", day)
    closes = [b.get("c") for b in bars if b.get("c") is not None]
    if not closes:
        raise ValueError(
            f"no as-of close for {symbol!r} on {day!r} — cannot anchor the "
            "reference price (R4.1)."
        )
    return float(closes[-1])


def _atr_from_features(features: FeaturesFn, symbol: str, day: str, port: DataPort) -> float | None:
    """The day's ATR from the point-in-time features (`features.raw["atr"]`).

    Re-derives the features for the day (deterministic, leak-free) and reads the
    ATR the build-order stop distance scales by. A degraded feature object (no
    `raw`) or an absent ATR ⇒ `None` (build_order then no-orders defensively).
    """
    fs = features(symbol, day, port)
    raw = getattr(fs, "raw", None)
    if not isinstance(raw, Mapping):
        return None
    atr = raw.get("atr")
    return float(atr) if atr is not None else None


def _seed_account() -> AccountState:
    """A healthy seed `AccountState` (clears admit's margin gate by construction).

    §16.1 forces flat-before-close every day, so no position persists; the harness
    does NOT simulate margin evolution (out of boundary — the survival-net metric
    is the consumer's, R8.2). A high margin level so the candidate's OWN path is
    not spuriously margin-rejected. CONCERN: this is a synthesized account, not a
    reconstructed one (flagged in the status report)."""
    return AccountState(
        activated=True,
        equity=100_000.0,
        used_margin=1_000.0,
        free_margin=99_000.0,
        margin_level=10_000.0,
        balance=100_000.0,
        stop_out_level=50.0,
        positions=[],
    )


def _clear_op_state() -> OperationalState:
    """Op-state with no kill switch + grade NONE (admit's gates 1/2 pass)."""
    return OperationalState(
        kill_switch_engaged=False,
        safe_mode_grade="NONE",
        entered_at=None,
        triggered_by=None,
    )


def _clearing_evaluation() -> OrderEvaluation:
    """An `OrderEvaluation` clearing admit's screen gates (in-universe, not
    excluded, a finite small margin delta).

    The `OrderEvaluation` fields (margin delta / universe membership / exclusion)
    are daemon Phase-2 broker/screen knowledge OUT of this spec's boundary
    (survival §"The projection input"). The harness drives the candidate's OWN
    decision path; it supplies a clearing context so the candidate is not
    spuriously screen-rejected. CONCERN: the in-universe/exclusion/margin
    reconstruction is a cross-spec seam not modeled here (flagged)."""
    return OrderEvaluation(
        additional_used_margin=10.0,
        in_universe=True,
        is_excluded=False,
    )


def _clock() -> ClockState:
    """A session-open clock (the §16.1 flatten countdown is the daemon's, not
    modeled in replay — the harness flattens unconditionally at the day close)."""
    return ClockState(session_open=True, seconds_to_next_closure=None)


# ============================================================================ #
# Small pure helpers
# ============================================================================ #


def _as_key_filters(champion_keys: Any) -> dict[str, Any]:
    """Normalize the champion correlation keys to a `query_trace` filter dict.

    Accepts either a `Mapping` or a `CorrelationKeys`-style dataclass (the fixture
    + the landed telemetry contract). Only the `query_trace` whitelist keys that
    are present + non-None are kept; `run_id` is DROPPED — a champion baseline
    spans the window's runs, so filtering by the single run identity would
    over-narrow the recorded-fill baseline (the `(code_version, param_version,
    walk_forward_window)` triple is the champion-identity filter the reader
    PROVIDES; design line 137)."""
    if champion_keys is None:
        return {}
    if isinstance(champion_keys, Mapping):
        raw = dict(champion_keys)
    else:
        from dataclasses import asdict, is_dataclass

        raw = asdict(champion_keys) if is_dataclass(champion_keys) else {}
    allowed = ("code_version", "param_version", "walk_forward_window")
    return {k: raw[k] for k in allowed if raw.get(k) is not None}


def _landed_query_trace() -> QueryTraceFn:
    """Lazily resolve the landed `telemetry.reader.query_trace` (the prod reader).

    Imported INSIDE the call (not at module top) because the landed reader pulls
    in `psycopg` at its own module top — a DB driver the inner-ring venv omits.
    Deferring the import keeps the harness module importable for R9.2 fixture
    tests, which inject `query_trace_fn` and never reach this path."""
    from src.reactive.telemetry.reader import query_trace

    return query_trace


def _iso_day(ts: str) -> str:
    """The bare `YYYY-MM-DD` day of an ISO timestamp/date (mirrors simulator)."""
    return ts[:10]


def _decision_filters(keys: Mapping[str, Any], boundary: str) -> dict[str, Any]:
    """The `query_trace` filter for the champion DECISION read (kind='decision')."""
    return {**dict(keys), "kind": "decision", "until": boundary}


def _fill_filters(keys: Mapping[str, Any], boundary: str) -> dict[str, Any]:
    """The `query_trace` filter for the champion FILL read (kind='fill')."""
    return {**dict(keys), "kind": "fill", "until": boundary}


__all__ = ["replay_candidate"]
