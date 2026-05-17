"""Mechanical contamination check MCP server for the equity research system.

Per BUILD_LOG.md decision 6, this is a tool consumed by Claude Code (specifically
the Evaluator subagent), not an orchestrator. Implements the design memo at
`src/mcp/contamination_check/DESIGN.md`.

Three tools:

- verify(agent_run_id, evidence_index_refs, claims): hard-gate verification
                                                     against evidence_index rows.
- verify_memo(memo_path): convenience wrapper that reads a memo JSON file and
                          calls verify() against it.
- diagnostic(agent_run_id): read-only re-examination of stored rows + reverify.

The check is mechanical: any failure mode in any claim produces verdict=FAIL.
No partial credit, no severity weighting, no semantic override. The check is a
consumer of the Evidence Index — it never writes.

Connection info is loaded from the repo root `.env` file via python-dotenv,
sharing the single source of truth with mcp__postgres.
"""

from __future__ import annotations

import datetime
import decimal
import json
import os
import uuid
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Walk: server.py → contamination_check/ → mcp/ → src/ → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


def _dsn() -> str:
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ.get('POSTGRES_HOST', '127.0.0.1')}:{os.environ.get('POSTGRES_PORT', '5432')}"
        f"/{os.environ['POSTGRES_DB']}"
    )


def _jsonify(value: Any) -> Any:
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return value


def _parse_date(value: Any) -> datetime.date | None:
    """Parse an ISO-8601 date string or date/datetime instance to a date.

    Returns None for None/empty input. Raises ValueError on malformed strings.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        # date.fromisoformat handles both YYYY-MM-DD and full ISO-8601 datetimes
        # (3.11+) but be defensive: strip a trailing time portion if present.
        try:
            return datetime.date.fromisoformat(value[:10])
        except ValueError as e:
            raise ValueError(f"Cannot parse date: {value!r}") from e
    raise ValueError(f"Cannot parse date from type {type(value).__name__}: {value!r}")


def _build_failure(
    claim_text: str | None,
    evidence_id: str | None,
    failure_mode: str,
    diagnostic: str,
    source_date: datetime.date | None = None,
    resolution_date: datetime.date | None = None,
) -> dict[str, Any]:
    return {
        "claim_text": claim_text,
        "evidence_id": str(evidence_id) if evidence_id is not None else None,
        "failure_mode": failure_mode,
        "diagnostic": diagnostic,
        "source_date": source_date.isoformat() if source_date is not None else None,
        "resolution_date": (
            resolution_date.isoformat() if resolution_date is not None else None
        ),
    }


mcp = FastMCP("contamination_check")


@mcp.tool()
def verify(
    agent_run_id: str,
    evidence_index_refs: list[str],
    claims: list[dict],
) -> dict[str, Any]:
    """Hard-gate verification of an agent output against the Evidence Index.

    Mechanical check per DESIGN.md §3. Any failure in any claim → verdict=FAIL.
    Single Postgres connection per call, read-only transaction.

    Args:
        agent_run_id: UUID grouping all claims from this agent invocation.
        evidence_index_refs: list of evidence_id UUIDs the output cites.
        claims: list of {claim_text, claim_type, evidence_id, resolution_date}
                where claim_type ∈ {numerical, qualitative, prediction, dated_fact}
                and resolution_date is ISO-8601 (YYYY-MM-DD).
                Optional per-claim flag `qualitative_only` participates only in
                the EMPTY_REFS opt-out semantics at the call level.

    Returns:
        {
          "verdict": "PASS" | "FAIL",
          "agent_run_id": "<uuid>",
          "checked_at": "<iso-8601>",
          "summary": {"n_claims": N, "n_refs": M, "n_failures": K},
          "failures": [...]
        }
    """
    # UTC date — ``date.today()`` would read the server's local timezone,
    # which causes the INCOHERENT_PREDICTION boundary check below to flip
    # on either side of midnight UTC depending on the host. ``resolution_date``
    # arrives as a UTC ISO date, so ``today`` must also be a UTC day.
    today = datetime.datetime.now(datetime.timezone.utc).date()
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    failures: list[dict[str, Any]] = []

    # EMPTY_REFS: empty evidence_index_refs with at least one non-qualitative
    # claim is a hard fail. Operator opt-out is via a `qualitative_only=True`
    # flag at the claim level (per DESIGN.md §4 edge case).
    has_non_qualitative = any(
        (c.get("claim_type") != "qualitative") for c in claims
    )
    qualitative_only_override = any(
        bool(c.get("qualitative_only")) for c in claims
    )
    if (
        evidence_index_refs == []
        and len(claims) > 0
        and has_non_qualitative
        and not qualitative_only_override
    ):
        failures.append(
            _build_failure(
                claim_text=None,
                evidence_id=None,
                failure_mode="EMPTY_REFS",
                diagnostic=(
                    "evidence_index_refs is empty but claims contain non-qualitative "
                    "items. Operator opt-out requires explicit qualitative_only=true."
                ),
            )
        )

    # Per-claim verification with a single read-only connection.
    with psycopg.connect(_dsn()) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            for claim in claims:
                claim_text = claim.get("claim_text")
                claim_type = claim.get("claim_type")
                evidence_id = claim.get("evidence_id")

                # Parse caller-supplied resolution_date defensively.
                try:
                    resolution_date = _parse_date(claim.get("resolution_date"))
                except ValueError as e:
                    failures.append(
                        _build_failure(
                            claim_text=claim_text,
                            evidence_id=evidence_id,
                            failure_mode="MALFORMED_CLAIM",
                            diagnostic=(
                                f"resolution_date is not parseable as ISO-8601: {e}"
                            ),
                        )
                    )
                    continue

                # Step 1: missing evidence_id reference handling.
                if evidence_id is None:
                    if claim_type == "qualitative":
                        # Qualitative claims exempt from Evidence Index per schema.
                        continue
                    failures.append(
                        _build_failure(
                            claim_text=claim_text,
                            evidence_id=None,
                            failure_mode="MISSING_REF",
                            diagnostic=(
                                f"claim_type={claim_type!r} requires an evidence_id "
                                "but none was provided."
                            ),
                            resolution_date=resolution_date,
                        )
                    )
                    continue

                # Step 2: look up the evidence row.
                cur.execute(
                    """
                    SELECT evidence_id, source_date, source_uri, claim_type
                    FROM evidence_index
                    WHERE evidence_id = %s
                    """,
                    (str(evidence_id),),
                )
                row = cur.fetchone()

                # Step 3: row missing → FABRICATED_UUID.
                if row is None:
                    failures.append(
                        _build_failure(
                            claim_text=claim_text,
                            evidence_id=evidence_id,
                            failure_mode="FABRICATED_UUID",
                            diagnostic=(
                                "evidence_id not found in evidence_index — the agent "
                                "appears to have invented a UUID."
                            ),
                            resolution_date=resolution_date,
                        )
                    )
                    continue

                row_source_date = row[1]
                if isinstance(row_source_date, datetime.datetime):
                    row_source_date = row_source_date.date()

                # Step 5: postdating check. Boundary same-day is PASS (use <=).
                if (
                    resolution_date is not None
                    and row_source_date is not None
                    and row_source_date > resolution_date
                ):
                    failures.append(
                        _build_failure(
                            claim_text=claim_text,
                            evidence_id=evidence_id,
                            failure_mode="POSTDATED_SOURCE",
                            diagnostic=(
                                f"source_date {row_source_date.isoformat()} is after "
                                f"resolution_date {resolution_date.isoformat()} — "
                                "contamination signature."
                            ),
                            source_date=row_source_date,
                            resolution_date=resolution_date,
                        )
                    )
                    continue

                # Step 6: incoherent prediction (target_date already past).
                if (
                    claim_type == "prediction"
                    and resolution_date is not None
                    and resolution_date <= today
                ):
                    failures.append(
                        _build_failure(
                            claim_text=claim_text,
                            evidence_id=evidence_id,
                            failure_mode="INCOHERENT_PREDICTION",
                            diagnostic=(
                                f"prediction.resolution_date {resolution_date.isoformat()} "
                                f"is not after today ({today.isoformat()}) — "
                                "self-resolving prediction."
                            ),
                            source_date=row_source_date,
                            resolution_date=resolution_date,
                        )
                    )
                    continue

    verdict = "FAIL" if failures else "PASS"
    return {
        "verdict": verdict,
        "agent_run_id": agent_run_id,
        "checked_at": checked_at,
        "summary": {
            "n_claims": len(claims),
            "n_refs": len(evidence_index_refs),
            "n_failures": len(failures),
        },
        "failures": failures,
    }


@mcp.tool()
def verify_memo(memo_path: str) -> dict[str, Any]:
    """Read a memo JSON file from disk and run verify() against it.

    For ad-hoc audit at /evaluate. Production path is verify() called from the
    Evaluator subagent, which has structured access to the output.

    Heuristic limitation: this wrapper does NOT re-tokenize prose. It expects
    the memo's structured output to either:
      (a) already contain a `claims` list (preferred — Tier 2 minimum), OR
      (b) contain `reviewable_predictions` (list of {prediction_text, target_date,
          evidence_id?}) which is mapped to prediction-typed claim records.
    If neither is present, returns a synthetic FAIL with diagnostic — fail-closed
    per DESIGN.md §3 ("Heuristic is fail-closed").

    Args:
        memo_path: path to a JSON file (absolute or relative to CWD).

    Returns:
        Same shape as verify().
    """
    path = Path(memo_path)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    with path.open("r", encoding="utf-8") as f:
        memo = json.load(f)

    agent_run_id = memo.get("agent_run_id") or str(uuid.uuid4())
    evidence_index_refs = list(memo.get("evidence_index_refs") or [])

    # Prefer structured claims list directly off the memo.
    claims_raw = memo.get("claims")
    if isinstance(claims_raw, list) and len(claims_raw) > 0:
        claims: list[dict] = list(claims_raw)
    else:
        # Fall back to reviewable_predictions only.
        claims = []
        predictions = memo.get("reviewable_predictions") or []
        for p in predictions:
            claims.append(
                {
                    "claim_text": p.get("prediction_text"),
                    "claim_type": "prediction",
                    "evidence_id": p.get("evidence_id"),
                    "resolution_date": p.get("target_date"),
                }
            )

        # If we still have nothing, fail-closed.
        if not claims and not evidence_index_refs:
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return {
                "verdict": "FAIL",
                "agent_run_id": agent_run_id,
                "checked_at": now,
                "summary": {"n_claims": 0, "n_refs": 0, "n_failures": 1},
                "failures": [
                    _build_failure(
                        claim_text=None,
                        evidence_id=None,
                        failure_mode="MALFORMED_CLAIM",
                        diagnostic=(
                            "Memo lacks both structured `claims` and "
                            "`reviewable_predictions`; cannot mechanically verify."
                        ),
                    )
                ],
            }

    return verify(agent_run_id, evidence_index_refs, claims)


@mcp.tool()
def diagnostic(agent_run_id: str) -> dict[str, Any]:
    """Read-only diagnostic for Checkpoint 3 audits and /evaluate re-examination.

    Returns the Evidence Index rows tagged with the given agent_run_id alongside
    a re-run of verify() against that row set. The re-verify treats every row's
    own `source_date` as the resolution_date (i.e. self-consistency check) — it
    surfaces FABRICATED_UUID-style anomalies but cannot detect POSTDATED_SOURCE
    against the *original* claim resolution_dates (those live in the agent's
    structured output, not in the index). For full reverification, call
    verify() directly with the original claims payload.

    Args:
        agent_run_id: UUID identifying the agent invocation to inspect.

    Returns:
        {"rows": [...evidence_index_rows...], "reverify": {...verify result...}}
    """
    rows: list[dict[str, Any]] = []
    refs: list[str] = []
    synthetic_claims: list[dict] = []

    with psycopg.connect(_dsn()) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT evidence_id, source_date, source_uri, claim_type, claim_text
                FROM evidence_index
                WHERE agent_run_id = %s
                ORDER BY source_date NULLS LAST, evidence_id
                """,
                (agent_run_id,),
            )
            columns = [d.name for d in cur.description] if cur.description else []
            for raw in cur.fetchall():
                row_dict = {col: _jsonify(val) for col, val in zip(columns, raw)}
                rows.append(row_dict)

                evidence_id = row_dict.get("evidence_id")
                if evidence_id is not None:
                    refs.append(str(evidence_id))
                synthetic_claims.append(
                    {
                        "claim_text": row_dict.get("claim_text"),
                        "claim_type": row_dict.get("claim_type"),
                        "evidence_id": evidence_id,
                        "resolution_date": row_dict.get("source_date"),
                    }
                )

    reverify = verify(agent_run_id, refs, synthetic_claims)
    return {"rows": rows, "reverify": reverify}


if __name__ == "__main__":
    mcp.run()
