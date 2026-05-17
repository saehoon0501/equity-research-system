"""Veto lifecycle management (v3 spec Section 6 Q6 PB#5).

Implements the "single-fire per peak-pain event + M-3-driven refresh" policy:

    - Once a veto fires for a peak-pain event, it stays in `active` state
      until ONE of the terminal transitions resolves it:
        * 'released-by-recovery'        — drawdown recovered above 2× floor
        * 'released-by-feature-shift'   — M-3 refresh changed archetype mix
        * 'overridden-by-operator'      — operator explicit override
    - Incremental drawdown changes (e.g., -25pp → -28pp) do NOT re-fire.
    - M-3 materiality events (founder departure, kill-criteria change,
      ratings downgrade, etc.) DO trigger re-extraction + re-retrieval.

When refreshing on M-3:
    1. Re-run feature_extractor against the updated descriptive text.
    2. Re-run retrieval to get new top-3.
    3. If new archetype mix == prior archetype mix → veto status unchanged
       (single-fire still in effect; we just append to m3_refreshes JSONB).
    4. If new mix has shifted out of SURVIVOR-dominant region → release
       with status 'released-by-feature-shift'.
    5. If new mix flipped INTO SURVIVOR-dominant → re-fire (the spec calls
       this "veto re-evaluates" — same veto_id, status remains 'active'
       but the archetype_distribution snapshot is updated).

Persistence contract (migration 011):
    veto_lifecycle is APPEND-ONLY at v0.1. Status mutations during life are
    captured by APPENDING to the m3_refreshes JSONB array; the row's
    `status` field is the terminal state at resolution time.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 6 Q6 PB#5 (single-fire + M-3 refresh policy),
           db/migrations/011_v3_counterfactual_retrieval.sql (veto_lifecycle).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from .feature_extractor import CandidateFeatures
from .layer3_veto import VetoStatus, evaluate_veto, is_survivor_dominant
from .retrieval import CatalogCase


VetoLifecycleStatus = Literal[
    "active",
    "released-by-recovery",
    "released-by-feature-shift",
    "overridden-by-operator",
]


@dataclass
class VetoLifecycleRecord:
    """In-memory mirror of one veto_lifecycle row (PB#5 state machine).

    The DB row is append-only at v0.1 — this record holds the working state
    that gets written terminally on resolution.
    """

    veto_id: str
    retrieval_id: str
    ticker: str
    initial_fire_date: _dt.date
    status: VetoLifecycleStatus = "active"
    m3_refreshes: list[dict[str, Any]] = field(default_factory=list)
    operator_override_occurred: bool = False
    operator_override_rationale: str | None = None
    last_archetype_distribution: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class M3RefreshOutcome:
    """Outcome of a single M-3-driven refresh on an active veto."""

    refreshed_at: _dt.datetime
    drawdown_vs_benchmark_pp: float
    new_top_3_case_ids: list[str]
    new_archetype_distribution: dict[str, int]
    archetype_mix_changed: bool  # vs. last_archetype_distribution
    new_status: VetoLifecycleStatus
    action_taken: str
    new_veto_status: VetoStatus


def refresh_on_m3(
    *,
    record: VetoLifecycleRecord,
    candidate: CandidateFeatures,
    catalog: list[CatalogCase],
    drawdown_vs_benchmark_pp: float,
    refreshed_at: _dt.datetime | None = None,
) -> M3RefreshOutcome:
    """Re-evaluate an active veto after an M-3 materiality event.

    Per Section 6 Q6 PB#5: re-extract features + re-run retrieval; compare
    new archetype distribution to prior. State transitions:

        * Mix unchanged → veto continues 'active'; append refresh to
          m3_refreshes array; action_taken='unchanged'.
        * Mix changed AND no longer SURVIVOR-dominant AND prior was
          SURVIVOR-dominant → status flips to 'released-by-feature-shift';
          action_taken='released'.
        * Mix changed AND new is SURVIVOR-dominant → veto remains 'active'
          with refreshed snapshot; action_taken='re-fired'.
        * Otherwise (mixed both ways) → veto remains 'active' but flagged
          for operator review; action_taken='re-evaluate'.

    Mutates `record` in place (m3_refreshes append, status flip,
    last_archetype_distribution refresh) so the caller can persist a
    terminal-state row when the veto resolves.

    Args:
        record:                     Working VetoLifecycleRecord.
        candidate:                  Re-extracted features post-M-3.
        catalog:                    Active catalog pool.
        drawdown_vs_benchmark_pp:   Drawdown at refresh time (signed).
        refreshed_at:               Refresh timestamp (UTC now if omitted).

    Returns:
        M3RefreshOutcome with the new VetoStatus + state-transition decision.
    """
    when = refreshed_at or _dt.datetime.now(_dt.timezone.utc)
    new_veto = evaluate_veto(candidate=candidate, catalog=catalog)
    new_dist = dict(new_veto.archetype_distribution)
    new_top_ids = [m.case.case_id for m in new_veto.top_3_matches]

    prior_dist = dict(record.last_archetype_distribution or {})
    mix_changed = prior_dist != new_dist
    prior_was_blocking = is_survivor_dominant(prior_dist)
    new_is_blocking = is_survivor_dominant(new_dist)

    if not mix_changed:
        action = "unchanged"
        new_status: VetoLifecycleStatus = record.status
    elif prior_was_blocking and not new_is_blocking:
        action = "released"
        new_status = "released-by-feature-shift"
    elif new_is_blocking:
        action = "re-fired"
        new_status = "active"
    else:
        action = "re-evaluate"
        new_status = record.status

    # Append refresh event to m3_refreshes (append-only contract: never
    # mutate prior entries).
    record.m3_refreshes.append({
        "refresh_date": when.date().isoformat(),
        "drawdown_vs_benchmark_pp": drawdown_vs_benchmark_pp,
        "top_3_case_ids": new_top_ids,
        "archetype_distribution": new_dist,
        "archetype_mix_changed": mix_changed,
        "action_taken": action,
    })
    record.status = new_status
    record.last_archetype_distribution = new_dist

    return M3RefreshOutcome(
        refreshed_at=when,
        drawdown_vs_benchmark_pp=drawdown_vs_benchmark_pp,
        new_top_3_case_ids=new_top_ids,
        new_archetype_distribution=new_dist,
        archetype_mix_changed=mix_changed,
        new_status=new_status,
        action_taken=action,
        new_veto_status=new_veto,
    )


def release_by_recovery(
    record: VetoLifecycleRecord,
    *,
    recovered_at: _dt.datetime | None = None,
    drawdown_vs_benchmark_pp: float = 0.0,
) -> VetoLifecycleRecord:
    """Release an active veto when drawdown recovers above 2× floor.

    Appends a refresh entry with action_taken='released-by-recovery' and
    transitions status. Mutates and returns the record.
    """
    when = recovered_at or _dt.datetime.now(_dt.timezone.utc)
    record.m3_refreshes.append({
        "refresh_date": when.date().isoformat(),
        "drawdown_vs_benchmark_pp": drawdown_vs_benchmark_pp,
        "top_3_case_ids": [],
        "archetype_distribution": dict(record.last_archetype_distribution),
        "archetype_mix_changed": False,
        "action_taken": "released-by-recovery",
    })
    record.status = "released-by-recovery"
    return record


def operator_override(
    record: VetoLifecycleRecord,
    *,
    rationale: str,
    overridden_at: _dt.datetime | None = None,
) -> VetoLifecycleRecord:
    """Apply an explicit operator override (PB#5 audit lifecycle).

    Per migration 011: operator_override_occurred + rationale must be
    captured. Status flips to 'overridden-by-operator'.
    """
    when = overridden_at or _dt.datetime.now(_dt.timezone.utc)
    record.operator_override_occurred = True
    record.operator_override_rationale = rationale
    record.m3_refreshes.append({
        "refresh_date": when.date().isoformat(),
        "drawdown_vs_benchmark_pp": 0.0,
        "top_3_case_ids": [],
        "archetype_distribution": dict(record.last_archetype_distribution),
        "archetype_mix_changed": False,
        "action_taken": "overridden-by-operator",
        "rationale": rationale,
    })
    record.status = "overridden-by-operator"
    return record


# ---------------------------------------------------------------------------
# Persistence wiring (DI for tests)
# ---------------------------------------------------------------------------


PgExecuteFn = Callable[[str, tuple[Any, ...]], None]
"""Signature: (sql, params) -> None. Production wires to mcp__postgres__execute
or psycopg2 cursor.execute; tests pass a stub recording the calls."""


def write_veto_lifecycle_row(
    record: VetoLifecycleRecord,
    *,
    execute: PgExecuteFn,
) -> None:
    """INSERT a terminal veto_lifecycle row.

    Per migration 011 append-only contract, this is called when the veto
    resolves (either at initial fire if cooling-off path is short, or at
    terminal-state transition). Status mutations during life are captured
    in m3_refreshes JSONB.
    """
    import json
    sql = (
        "INSERT INTO veto_lifecycle "
        "(veto_id, retrieval_id, ticker, initial_fire_date, status, "
        "m3_refreshes, operator_override_occurred, operator_override_rationale) "
        "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)"
    )
    execute(
        sql,
        (
            record.veto_id,
            record.retrieval_id,
            record.ticker,
            record.initial_fire_date.isoformat(),
            record.status,
            json.dumps(record.m3_refreshes),
            record.operator_override_occurred,
            record.operator_override_rationale,
        ),
    )
