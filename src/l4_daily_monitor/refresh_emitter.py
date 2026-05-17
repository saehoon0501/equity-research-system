"""Refresh emitter — orchestrates the daily monitor pipeline + persistence.

Per v3 spec Section 4.5 Q1 (lines 462-483) the refresh emitter writes:

  1. ``daily_refresh_log`` — one row per (ticker, date) with the rolled-up
      mode / materiality / events / regime_context / recommended_action
      / llm_call_metadata payload.
  2. ``materiality_events`` — one row per LLM-classified event.
  3. ``unread_alerts`` — M-2 fires fire ``materiality_m3`` alert_type
     only when severity=3; M-2 with severity=2 also fire per Section 7
     PB#4 ("M-1 informational; M-2/M-3 fire alerts").

Pipeline (per Section 4.5):

    ingest_events()            -> list[Event]
    classify_materiality(e)    -> MaterialityVerdict per event
    route_materiality(e, v)    -> RoutingDecision
    build_cut_context()        -> CutContext
    evaluate_cut(mode, ctx)    -> CutDecision
    persist_refresh()          -> 3-table write inside one transaction

The "day-level rollup" materiality is the max() across event classifications
per Section 6 Q1 schema note ("the daily_refresh_log row carries the
day-level rollup which may be max() across events").

Recommended-action mapping:
    M-1 only            → 'no_action'
    M-2 with no cut     → 'reunderwrite'
    M-2 + cut triggered → 'exit'
    M-3 with no cut     → 'reunderwrite'  (full 5-agent)
    M-3 + cut triggered → 'exit'

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 4.5 Q1 — daily refresh log schema
    Section 6 Q1   — verbatim-quote audit-trail enforcement
    Section 7 PB#4 — unread-alert queue
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from . import (
    DEFAULT_MODEL,
    ESCALATION_MODEL,
    MATERIALITY_LABELS,
    MATERIALITY_M2,
    MATERIALITY_M3,
    PROMPT_VERSION,
)
from .cut_evaluator import (
    CutDecision,
    build_cut_context_from_verdicts,
    evaluate_cut,
)
from .event_ingestor import Event, EventAdapter, ingest_events
from .materiality_classifier import (
    MaterialityVerdict,
    classify_materiality,
)
from .router import RoutingDecision, route_materiality

_LOG = logging.getLogger(__name__)

# Rule engine version stamped on every persisted row (Section 5 Q1
# audit-trail lock). Bump on logic changes.
RULE_ENGINE_VERSION: str = "l4_daily_monitor.v0.1"


@dataclass
class DailyRefreshOutcome:
    """End-to-end refresh result for one (ticker, date)."""

    log_id: uuid.UUID
    ticker: str
    date: _dt.date
    mode: str
    materiality_rollup: int           # max() across events; 1 if no events
    materiality_label: str
    events: list[Event]
    verdicts: list[MaterialityVerdict]
    routings: list[RoutingDecision]
    cut_decision: CutDecision
    recommended_action: str
    regime_context_at_eval: dict[str, Any]
    llm_call_metadata: dict[str, Any]
    triggered_alerts: list[uuid.UUID] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Persistence layer (decoupled via Protocol-ish callable)                     #
# --------------------------------------------------------------------------- #


class _TransactionalDbWriter:
    """Default Postgres writer that holds ONE connection across all SQL calls.

    Atomicity contract (Section 4.5 Q1 + Section 7 PB#4):
        ``run_daily_refresh`` writes 1 daily_refresh_log row + N
        materiality_events rows + 0/1 unread_alerts row. If those rows
        do not commit together, an audit-trail reader can see (e.g.)
        a daily_refresh_log row claiming materiality=3 with NO matching
        materiality_events rows and NO unread_alerts row → operator
        misses a real M-3 escalation.

        The original ``_default_db_writer`` opened a fresh psycopg2
        connection per call, so each row was its own transaction; a
        mid-loop CHECK violation (e.g., one event has an invalid
        verbatim_quote) would persist the daily_refresh_log header row
        + earlier events but lose later events + the alert.

        This writer opens ONE connection on first use and commits on
        ``__exit__``; on exception it rolls back the entire batch.

    Used as a context manager from ``run_daily_refresh``::

        with _TransactionalDbWriter() as writer:
            writer(sql, params)
            ...
    """

    def __init__(self, dsn: Optional[str] = None) -> None:
        self._dsn = dsn or os.environ.get("DATABASE_URL")
        self._conn = None  # type: Any

    def __enter__(self):
        try:
            import psycopg2  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "psycopg2 not installed; pass a stub db_writer for tests."
            ) from exc
        if not self._dsn:
            raise RuntimeError(
                "DATABASE_URL not set; pass a stub db_writer for tests."
            )
        self._conn = psycopg2.connect(self._dsn)  # pragma: no cover
        # Explicit autocommit=False so all calls share one transaction.
        self._conn.autocommit = False
        return self

    def __exit__(self, exc_type, exc, tb):  # pragma: no cover - prod path
        if self._conn is None:
            return False
        try:
            if exc_type is not None:
                # Exception in the body — roll back the whole multi-row write.
                # Don't mask the original; log if rollback itself fails so the
                # operator sees the data-integrity signal in system logs.
                try:
                    self._conn.rollback()
                except Exception as rb_exc:  # noqa: BLE001
                    _LOG.error(
                        "_TransactionalDbWriter rollback FAILED — "
                        "transaction may be in inconsistent state. "
                        "original_exc=%s: %s; rollback_exc=%s: %s",
                        exc_type.__name__ if exc_type else "?",
                        exc,
                        type(rb_exc).__name__,
                        rb_exc,
                    )
            else:
                self._conn.commit()
        finally:
            try:
                self._conn.close()
            except Exception as close_exc:  # noqa: BLE001
                _LOG.warning(
                    "_TransactionalDbWriter close failed: %s: %s",
                    type(close_exc).__name__, close_exc,
                )
        return False

    def __call__(self, sql: str, params: tuple) -> Optional[uuid.UUID]:
        if self._conn is None:
            raise RuntimeError(
                "_TransactionalDbWriter must be entered as a context manager"
            )
        with self._conn.cursor() as cur:  # pragma: no cover
            cur.execute(sql, params)
            row = cur.fetchone() if cur.description else None
            return row[0] if row else None


def _default_db_writer(sql: str, params: tuple) -> Optional[uuid.UUID]:
    """Backward-compatible single-shot writer.

    DEPRECATED for multi-row use cases. ``run_daily_refresh`` now uses
    the transactional writer when the caller passes ``db_writer=None``;
    this function is retained for callers that explicitly want single-
    shot behaviour or are mocking it directly in tests.
    """
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "psycopg2 not installed; pass a stub db_writer for tests."
        ) from exc
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL not set; pass a stub db_writer for tests."
        )
    with psycopg2.connect(dsn) as conn:  # pragma: no cover
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone() if cur.description else None
            return row[0] if row else None


# --------------------------------------------------------------------------- #
# Public entry                                                                #
# --------------------------------------------------------------------------- #


def run_daily_refresh(
    ticker: str,
    date: _dt.date,
    mode: str,
    *,
    regime_context: Optional[dict[str, Any]] = None,
    scenario_kill_criteria: Optional[list[dict[str, Any]]] = None,
    kill_criteria_meta: Optional[dict[str, dict[str, Any]]] = None,
    drawdown_pp_vs_benchmark: float = 0.0,
    drawdown_quarters_sustained: int = 0,
    growth_yoy_recent_quarters: Optional[list[float]] = None,
    bocpd_against_thesis_prob: float = 0.0,
    smart_money_exit_verified: bool = False,
    event_adapter: Optional[EventAdapter] = None,
    llm_client: Any = None,
    db_writer: Any = None,
    parameters_version: Optional[uuid.UUID] = None,
    dry_run: bool = False,
) -> DailyRefreshOutcome:
    """Run the full L4 / P8 daily refresh for one (ticker, date).

    Steps (Section 4.5):
      1. Ingest events.
      2. Classify each event (Sonnet default; Opus escalation for M-3).
      3. Route each verdict (M-2 LLM picker w/ floor; M-3 fixed all-5).
      4. Roll materiality up to day-level (max across events).
      5. Build cut context + evaluate Section 4.5 Q3 thresholds.
      6. Persist daily_refresh_log + materiality_events + unread_alerts.

    Args:
        ticker, date, mode: Identifiers.
        regime_context: S0 regime snapshot at evaluation time. Stored in
            daily_refresh_log.regime_context_at_eval.
        scenario_kill_criteria: List of kill criteria payloads from
            scenarios.kill_criteria_structured for this ticker/scenario.
        kill_criteria_meta: dict {kill_id: {thesis_defining: bool, tag: str}}
            consumed by cut_evaluator to detect thesis-defining /
            moat-erosion fires.
        drawdown_pp_vs_benchmark, drawdown_quarters_sustained,
        growth_yoy_recent_quarters, bocpd_against_thesis_prob,
        smart_money_exit_verified: cut-evaluator inputs.
            Per operator-locked dual-signal architecture (v3 §4.1 +
            migration 020): ``bocpd_against_thesis_prob`` MUST be sourced
            from ``regime_state.bocpd_short_run_mass`` (the firing
            signal), NOT from ``bocpd_change_probability`` (the canonical
            marginal — kept for audit traceability, structurally pinned
            near hazard rate in steady state).
        event_adapter: Optional EventAdapter (injectable for tests).
        llm_client: Optional Anthropic client (injectable for tests).
        db_writer: Optional callable (sql, params) -> UUID-or-None for
            tests; defaults to psycopg2.
        parameters_version: FK into parameters table.
        dry_run: If True, skip all DB writes and return the outcome.

    Returns:
        :class:`DailyRefreshOutcome`.
    """
    regime_context = regime_context or {}
    scenario_kill_criteria = scenario_kill_criteria or []

    log_id = uuid.uuid4()

    # --- 1. Ingest events --------------------------------------------------
    events = ingest_events(ticker, date, adapter=event_adapter)

    # --- 2. Classify each event -------------------------------------------
    verdicts: list[MaterialityVerdict] = []
    for ev in events:
        v = classify_materiality(
            ticker=ticker,
            event=ev,
            regime_context=regime_context,
            scenario_kill_criteria=scenario_kill_criteria,
            client=llm_client,
        )
        verdicts.append(v)

    # --- 3. Route each verdict --------------------------------------------
    routings: list[RoutingDecision] = []
    for ev, v in zip(events, verdicts):
        routings.append(
            route_materiality(ticker=ticker, event=ev, verdict=v, client=llm_client)
        )

    # --- 4. Day-level rollup (max materiality) ----------------------------
    if verdicts:
        materiality_rollup = max(v.classification for v in verdicts)
    else:
        materiality_rollup = 1  # M-1: nothing happened

    # --- 5. Cut evaluation ------------------------------------------------
    cut_ctx = build_cut_context_from_verdicts(
        verdicts,
        kill_criteria_meta=kill_criteria_meta,
        drawdown_pp_vs_benchmark=drawdown_pp_vs_benchmark,
        drawdown_quarters_sustained=drawdown_quarters_sustained,
        growth_yoy_recent_quarters=growth_yoy_recent_quarters,
        bocpd_against_thesis_prob=bocpd_against_thesis_prob,
        smart_money_exit_verified=smart_money_exit_verified,
    )
    cut_decision = evaluate_cut(mode, cut_ctx)

    # --- 6. Recommended action mapping ------------------------------------
    recommended_action = _map_recommended_action(materiality_rollup, cut_decision)

    # --- 7. LLM call metadata ---------------------------------------------
    any_escalated = any(v.tier_escalated_to_opus for v in verdicts)
    llm_call_metadata: dict[str, Any] = {
        "model": ESCALATION_MODEL if any_escalated else DEFAULT_MODEL,
        "prompt_version": PROMPT_VERSION,
        "tier_escalated_to_opus": any_escalated,
        "events_classified": len(verdicts),
        "events_m1": sum(1 for v in verdicts if v.classification == 1),
        "events_m2": sum(1 for v in verdicts if v.classification == 2),
        "events_m3": sum(1 for v in verdicts if v.classification == 3),
        "median_judge_confidence": _median([v.confidence for v in verdicts]) or 0.0,
        "router_used_fallback_count": sum(1 for r in routings if r.used_fallback_table),
    }

    outcome = DailyRefreshOutcome(
        log_id=log_id,
        ticker=ticker,
        date=date,
        mode=mode,
        materiality_rollup=materiality_rollup,
        materiality_label=MATERIALITY_LABELS[materiality_rollup],
        events=events,
        verdicts=verdicts,
        routings=routings,
        cut_decision=cut_decision,
        recommended_action=recommended_action,
        regime_context_at_eval=regime_context,
        llm_call_metadata=llm_call_metadata,
    )

    if dry_run:
        _LOG.info(
            "dry_run: would persist %s on %s as %s/%s; cut=%s",
            ticker, date, mode, outcome.materiality_label,
            cut_decision.cut_recommended,
        )
        return outcome

    # --- 8. Persist (atomic across all 3 tables) --------------------------
    # Per Section 4.5 Q1 atomicity: the daily_refresh_log header, all
    # per-event materiality_events rows, and the optional unread_alerts
    # row must commit together or not at all. A mid-batch failure that
    # left only the header row would surface to operator as "M-3 logged
    # but no alert in /alerts queue" — exactly the audit gap this fix
    # closes.
    if db_writer is None:
        with _TransactionalDbWriter() as writer:
            _persist_all_rows(
                writer,
                outcome=outcome,
                parameters_version=parameters_version,
                materiality_rollup=materiality_rollup,
            )
    else:
        # Caller-supplied writer: contract is "caller owns transaction
        # boundary" (typical test stub records writes; production callers
        # passing a custom writer must wrap in their own transaction).
        _persist_all_rows(
            db_writer,
            outcome=outcome,
            parameters_version=parameters_version,
            materiality_rollup=materiality_rollup,
        )

    return outcome


def _persist_all_rows(
    db_writer: Any,
    *,
    outcome: DailyRefreshOutcome,
    parameters_version: Optional[uuid.UUID],
    materiality_rollup: int,
) -> None:
    """Run the 3-table write batch using the supplied writer.

    Idempotency: the daily_refresh_log INSERT uses ON CONFLICT (ticker, date)
    DO NOTHING. When the header is a no-op (returns NULL log_id), we MUST
    skip the per-event materiality_events INSERTs and the unread_alerts
    INSERT — otherwise a retry would duplicate event rows + duplicate
    operator alerts despite the header being idempotent.
    """
    inserted_log_id = _persist_daily_refresh_log(
        outcome=outcome,
        parameters_version=parameters_version,
        db_writer=db_writer,
    )
    if inserted_log_id is None:
        # Header was a conflict no-op (prior run for this (ticker, date)
        # already committed). Skip per-event + alert writes to keep the
        # full multi-row batch idempotent. The prior run's events and any
        # M-2/M-3 alert already committed at first-write time.
        return
    for ev, v in zip(outcome.events, outcome.verdicts):
        _persist_materiality_event(
            ticker=outcome.ticker,
            event=ev,
            verdict=v,
            parameters_version=parameters_version,
            db_writer=db_writer,
        )
    # Alert fires for M-2 / M-3 only (Section 7 PB#4).
    if materiality_rollup in (MATERIALITY_M2, MATERIALITY_M3):
        alert_id = _persist_unread_alert(outcome=outcome, db_writer=db_writer)
        if alert_id is not None:
            outcome.triggered_alerts.append(alert_id)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _map_recommended_action(rollup: int, cut: CutDecision) -> str:
    """Section 4.5 Q1 + Q3 mapping. Free-text per migration 009."""
    if rollup == 1:
        return "no_action"
    if cut.cut_recommended:
        return "exit"
    return "reunderwrite"


def _median(xs: list[float]) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _persist_daily_refresh_log(
    outcome: DailyRefreshOutcome,
    parameters_version: Optional[uuid.UUID],
    db_writer: Any,
) -> Optional[uuid.UUID]:
    # Idempotency: daily_refresh_log has UNIQUE (ticker, date) per migration
    # 009. Without ON CONFLICT, a cron retry on the same (ticker, date) would
    # raise UniqueViolation — and because this INSERT is the first statement
    # inside the _TransactionalDbWriter batch, the failure rolls back the
    # entire 3-table write (header + materiality_events + unread_alert) for
    # the second invocation. Re-runs MUST be safe per migration's
    # idempotency promise (lines 112-115: "Re-running the daily monitor for
    # a ticker on the same date is a no-op (idempotent at app level via
    # UPSERT-skip)"). DO NOTHING is correct here: the first commit wins;
    # a retry observes the prior row and skips silently.
    sql = (
        "INSERT INTO daily_refresh_log "
        "(log_id, date, ticker, mode, materiality, events, "
        " regime_context_at_eval, recommended_action, llm_call_metadata, "
        " rule_engine_version, parameters_version) "
        "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, "
        " %s, %s) "
        "ON CONFLICT (ticker, date) DO NOTHING "
        "RETURNING log_id"
    )
    events_jsonb = [
        v.to_event_jsonb(ev) for ev, v in zip(outcome.events, outcome.verdicts)
    ]
    params = (
        str(outcome.log_id),
        outcome.date.isoformat(),
        outcome.ticker,
        outcome.mode,
        outcome.materiality_rollup,
        json.dumps(events_jsonb, default=str),
        json.dumps(outcome.regime_context_at_eval, default=str),
        outcome.recommended_action,
        json.dumps(outcome.llm_call_metadata, default=str),
        RULE_ENGINE_VERSION,
        str(parameters_version) if parameters_version else None,
    )
    # ON CONFLICT DO NOTHING with RETURNING returns None on conflict; the
    # caller uses this to detect "prior row already exists" and skip the
    # downstream materiality_events + unread_alerts writes.
    return db_writer(sql, params)


def _persist_materiality_event(
    ticker: str,
    event: Event,
    verdict: MaterialityVerdict,
    parameters_version: Optional[uuid.UUID],
    db_writer: Any,
) -> None:
    # Per Section 6 Q1: verbatim_quote required column. For M-1 verdicts
    # without a quote, we substitute the event's own verbatim_quote (if
    # present) or a placeholder annotated as informational.
    verbatim = verdict.verbatim_quote or event.verbatim_quote or "(M-1 informational; no quote)"
    # Idempotency: migration 022 adds a unique index on the natural-key
    # tuple (ticker, event_date, event_type, source_id, md5(verbatim_quote)).
    # The header-row guard in _persist_all_rows already short-circuits on
    # daily_refresh_log conflict — but we belt-and-suspenders this INSERT
    # too: a retry that somehow bypasses the header guard (e.g., split
    # transactions in the future) won't duplicate event rows.
    sql = (
        "INSERT INTO materiality_events "
        "(event_id, ticker, event_date, event_type, source_id, "
        " verbatim_quote, classification, cited_kill_criterion_id, "
        " llm_judge_confidence, parameters_version) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (ticker, event_date, event_type, source_id, "
        "             md5(verbatim_quote)) DO NOTHING"
    )
    params = (
        str(uuid.uuid4()),
        ticker,
        event.timestamp.isoformat(),
        event.type,
        event.source_id,
        verbatim,
        verdict.classification,
        verdict.cited_kill_criterion_id,
        verdict.confidence,
        str(parameters_version) if parameters_version else None,
    )
    db_writer(sql, params)


def _persist_unread_alert(
    outcome: DailyRefreshOutcome,
    db_writer: Any,
) -> Optional[uuid.UUID]:
    alert_id = uuid.uuid4()
    severity = outcome.materiality_rollup  # 2 or 3 (we only get here for M-2/M-3)
    if severity == MATERIALITY_M3:
        alert_type = "materiality_m3"
    else:
        # M-2: per Section 4.5 PB#4 every M-2 MUST fire an alert. Migration
        # 017 adds the dedicated 'materiality_m2' enum value to
        # unread_alerts.alert_type so we no longer have to suppress.
        # 'kill_criterion' is reserved for explicit kill-emission paths
        # (not the daily-monitor M-2 fall-through).
        alert_type = "materiality_m2"

    summary = (
        f"{outcome.ticker} {outcome.date} {outcome.materiality_label}: "
        f"{outcome.recommended_action} "
        f"(events={len(outcome.events)}, "
        f"cut={outcome.cut_decision.cut_recommended})"
    )
    payload = {
        "log_id": str(outcome.log_id),
        "mode": outcome.mode,
        "materiality_label": outcome.materiality_label,
        "cut_recommended": outcome.cut_decision.cut_recommended,
        "triggered_conditions": list(outcome.cut_decision.triggered_conditions),
        "agents_dispatched": _agents_dispatched(outcome.routings),
        "verbatim_quotes": [
            v.verbatim_quote for v in outcome.verdicts if v.verbatim_quote
        ],
    }
    sql = (
        "INSERT INTO unread_alerts "
        "(alert_id, severity, alert_type, ticker, summary, payload) "
        "VALUES (%s, %s, %s, %s, %s, %s::jsonb) RETURNING alert_id"
    )
    params = (
        str(alert_id),
        severity,
        alert_type,
        outcome.ticker,
        summary,
        json.dumps(payload, default=str),
    )
    db_writer(sql, params)
    return alert_id


def _agents_dispatched(routings: list[RoutingDecision]) -> list[str]:
    seen: list[str] = []
    for r in routings:
        for a in r.agents:
            if a not in seen:
                seen.append(a)
    return seen
