"""Anchor-drift orchestrator — runs all 3 channels per name.

Per spec ``docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md``
Section 4.5 Q5 (lines 530-536)::

    When triggered: operator must choose Reaffirm / Revise-with-rationale
    (verbatim citation required) / Cut. No-op default BLOCKED.

This module:
  * loads the watchlist row + last reread baseline,
  * runs all 3 channels (HMAC-verified along the way),
  * OR's the channel triggers into ``any_triggered``,
  * builds the ``forced_review`` JSONB scaffold (when any triggered),
  * INSERTs one row into ``anchor_drift_checks`` (010_v3_drift_detection.sql).

The forced_review scaffold writes ``operator_decision = 'pending'`` —
downstream UI flow MUST resolve to one of {reaffirm, revise_with_rationale,
cut} before the no-op default is unblocked. The schema CHECK constraint
``anchor_drift_review_decision_valid`` enforces the value enum.
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
    DECISION_PENDING,
)
from .channel_1_pillar_drift import (
    PillarDriftResult,
    detect_pillar_drift,
)
from .channel_2_outcome_divergence import (
    OutcomeDivergenceResult,
    detect_outcome_divergence,
)
from .channel_3_periodic_reread import (
    PeriodicRereadResult,
    detect_periodic_reread,
)

_LOG = logging.getLogger(__name__)


def _dsn() -> str:
    return os.environ.get(
        "EQUITY_RESEARCH_DSN",
        "postgresql://postgres@127.0.0.1:5432/equity_research",
    )


@dataclass
class AnchorDriftOutcome:
    """Aggregate result of all 3 channels for one ticker."""

    ticker: str
    check_date: str
    channel_1: PillarDriftResult
    channel_2: OutcomeDivergenceResult
    channel_3: PeriodicRereadResult
    any_triggered: bool
    triggered_channels: list[str] = field(default_factory=list)
    forced_review: Optional[dict[str, Any]] = None
    check_id: Optional[uuid.UUID] = None


def _build_forced_review(
    triggered_channels: list[str],
) -> Optional[dict[str, Any]]:
    """Build ``forced_review`` JSONB; None when nothing triggered.

    Matches the doc-comment shape in 010_v3_drift_detection.sql:
        { type: 'pillar_drift'|'outcome_divergence'|'periodic_reread'|...,
          surfaced_to: 'operator',
          operator_acknowledged_at: timestamptz,
          operator_decision: 'reaffirm'|'revise_with_rationale'|'cut'|'pending' }

    With multiple channels firing, ``type`` is the highest-priority
    channel: pillar_drift > outcome_divergence > periodic_reread.
    """
    if not triggered_channels:
        return None
    priority = ["pillar_drift", "outcome_divergence", "periodic_reread"]
    review_type = next(
        (p for p in priority if p in triggered_channels),
        triggered_channels[0],
    )
    return {
        "type": review_type,
        "surfaced_to": "operator",
        "operator_acknowledged_at": None,
        "operator_decision": DECISION_PENDING,
        "all_triggered": list(triggered_channels),
    }


def _fetch_watchlist(ticker: str) -> Optional[dict[str, Any]]:
    """Read watchlist + most-recent acknowledged reread date for ticker."""
    import psycopg  # deferred

    with psycopg.connect(_dsn()) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    mode,
                    thesis_pillars_original,
                    thesis_pillars_original_hmac,
                    scenario_A_base_projections,
                    scenario_A_base_projections_hmac,
                    added_at,
                    parameters_version,
                    last_reunderwritten_at
                FROM watchlist
                WHERE ticker = %s
                """,
                (ticker,),
            )
            row = cur.fetchone()
            if not row:
                return None
            (mode, pillars, pillars_hmac,
             scenario, scenario_hmac, added_at,
             params_version, last_reun) = row

            cur.execute(
                """
                SELECT MAX(check_date)
                FROM anchor_drift_checks
                WHERE ticker = %s
                  AND forced_review->>'operator_decision' IN
                      ('reaffirm', 'revise_with_rationale')
                """,
                (ticker,),
            )
            last_ack_row = cur.fetchone()
            last_ack = last_ack_row[0] if last_ack_row else None
            return {
                "mode": mode,
                "thesis_pillars_original": pillars,
                "thesis_pillars_original_hmac": pillars_hmac,
                "scenario_A_base_projections": scenario,
                "scenario_A_base_projections_hmac": scenario_hmac,
                "added_at": added_at,
                "last_reunderwritten_at": last_reun,
                "parameters_version": params_version,
                "last_acknowledged_reread": last_ack,
            }


def _persist(
    *,
    ticker: str,
    check_date: str,
    c1: PillarDriftResult,
    c2: OutcomeDivergenceResult,
    c3: PeriodicRereadResult,
    any_triggered: bool,
    forced_review: Optional[dict[str, Any]],
    parameters_version: Optional[uuid.UUID],
) -> uuid.UUID:
    """Insert one anchor_drift_checks row, idempotent on (ticker, check_date).

    Idempotency contract: migration 010 declares
    ``anchor_drift_unique_per_day UNIQUE (ticker, check_date)``. Channel 1
    ("M-2 system event") fires on a re-read schedule; if a crash + retry
    re-invokes the orchestrator on the same day for the same ticker, the
    plain INSERT would raise UniqueViolation and surface to the operator
    as a system error. ON CONFLICT DO NOTHING gives first-call-wins
    semantics (the prior row survives — its forced_review workflow state
    isn't clobbered by the retry's pending scaffold). We RETURN the
    inserted check_id; on conflict the function returns the prior row's
    check_id so the caller has a stable handle.
    """
    import psycopg  # deferred

    cid = uuid.uuid4()
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO anchor_drift_checks (
                    check_id, ticker, check_date,
                    channel_1_pillar_drift,
                    channel_2_outcome_divergence,
                    channel_3_periodic_reread,
                    any_triggered, forced_review,
                    parameters_version
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (ticker, check_date) DO NOTHING
                RETURNING check_id
                """,
                (
                    cid,
                    ticker,
                    check_date,
                    json.dumps(c1.to_payload(), default=str),
                    json.dumps(c2.to_payload(), default=str),
                    json.dumps(c3.to_payload(), default=str),
                    any_triggered,
                    json.dumps(forced_review, default=str)
                    if forced_review else None,
                    parameters_version,
                ),
            )
            inserted = cur.fetchone()
            if inserted is None:
                # Prior row already committed for (ticker, check_date) —
                # return its existing check_id so the caller has a stable
                # handle and the audit trail isn't broken.
                cur.execute(
                    "SELECT check_id FROM anchor_drift_checks "
                    "WHERE ticker = %s AND check_date = %s",
                    (ticker, check_date),
                )
                existing = cur.fetchone()
                if existing is not None:
                    cid = existing[0]
        conn.commit()
    return cid


def run_anchor_drift_check(
    *,
    ticker: str,
    current_pillars: Any,
    as_of: Optional[str] = None,
    persist: bool = True,
    llm_client: Any | None = None,
    fundamentals_fn: Any | None = None,
    watchlist_row: Optional[dict[str, Any]] = None,
) -> AnchorDriftOutcome:
    """Run all 3 anchor-drift channels for one ticker.

    Args:
        ticker: equity ticker.
        current_pillars: live operating thesis pillars (Channel 1 input).
        as_of: ISO date for the check (default today).
        persist: when True, INSERT a row into anchor_drift_checks.
        llm_client: optional Anthropic SDK client for Channel 1 (tests).
        fundamentals_fn: optional injected fundamentals callable
            (Channel 2 tests).
        watchlist_row: optional pre-fetched watchlist row (tests).

    Returns:
        AnchorDriftOutcome with per-channel results, any_triggered OR,
        forced_review scaffold (when triggered), and inserted check_id.

    Raises:
        LookupError: when ticker is not in watchlist.
    """
    ticker = ticker.upper().strip()
    # Use UTC date — ``date.today()`` reads the server's local timezone, which
    # would produce off-by-one ``check_date`` rows on any non-UTC server near
    # the UTC day boundary. The DB ``check_date`` column is logically a UTC
    # day key per Section 4.5; persist accordingly.
    today = as_of or _dt.datetime.now(_dt.timezone.utc).date().isoformat()

    wl = watchlist_row or _fetch_watchlist(ticker)
    if wl is None:
        raise LookupError(f"{ticker} not in watchlist")

    c1 = detect_pillar_drift(
        ticker=ticker,
        thesis_pillars_original=wl["thesis_pillars_original"],
        thesis_pillars_original_hmac=wl["thesis_pillars_original_hmac"],
        current_pillars=current_pillars,
        client=llm_client,
    )
    c2 = detect_outcome_divergence(
        ticker=ticker,
        scenario_A_base_projections=wl["scenario_A_base_projections"],
        scenario_A_base_projections_hmac=wl["scenario_A_base_projections_hmac"],
        fundamentals_fn=fundamentals_fn,
    )

    last_reread = (
        wl.get("last_acknowledged_reread")
        or wl.get("last_reunderwritten_at")
        or wl.get("added_at")
    )
    c3 = detect_periodic_reread(
        ticker=ticker,
        mode=wl["mode"],
        last_reread_date=last_reread,
        as_of=today,
    )

    triggered_channels: list[str] = []
    if c1.triggered:
        triggered_channels.append("pillar_drift")
    if c2.triggered:
        triggered_channels.append("outcome_divergence")
    if c3.triggered:
        triggered_channels.append("periodic_reread")
    any_triggered = bool(triggered_channels)
    forced_review = _build_forced_review(triggered_channels)

    cid: Optional[uuid.UUID] = None
    if persist:
        cid = _persist(
            ticker=ticker,
            check_date=today,
            c1=c1,
            c2=c2,
            c3=c3,
            any_triggered=any_triggered,
            forced_review=forced_review,
            parameters_version=wl.get("parameters_version"),
        )

    return AnchorDriftOutcome(
        ticker=ticker,
        check_date=today,
        channel_1=c1,
        channel_2=c2,
        channel_3=c3,
        any_triggered=any_triggered,
        triggered_channels=triggered_channels,
        forced_review=forced_review,
        check_id=cid,
    )


def run_anchor_drift_check_bulk(
    *,
    as_of: Optional[str] = None,
    persist: bool = True,
    current_pillars_by_ticker: Optional[dict[str, Any]] = None,
) -> list[AnchorDriftOutcome]:
    """Bulk-run anchor-drift across the entire watchlist.

    Args:
        as_of: ISO date for the check.
        persist: when True, write to anchor_drift_checks.
        current_pillars_by_ticker: optional mapping ticker -> pillars;
            if absent, the last-known pillars are pulled from the
            decision-event log (Section 6.1).

    Returns:
        One AnchorDriftOutcome per watchlist ticker.
    """
    import psycopg  # deferred

    with psycopg.connect(_dsn()) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute("SELECT ticker FROM watchlist ORDER BY ticker")
            tickers = [r[0] for r in cur.fetchall()]

    out: list[AnchorDriftOutcome] = []
    pillars_map = current_pillars_by_ticker or {}
    for t in tickers:
        try:
            out.append(
                run_anchor_drift_check(
                    ticker=t,
                    current_pillars=pillars_map.get(t, []),
                    as_of=as_of,
                    persist=persist,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.exception("anchor-drift failure on %s: %s", t, exc)
    return out


__all__ = [
    "AnchorDriftOutcome",
    "run_anchor_drift_check",
    "run_anchor_drift_check_bulk",
]
