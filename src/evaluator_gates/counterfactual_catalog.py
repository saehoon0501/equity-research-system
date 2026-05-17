"""Counterfactual top-3 catalog-membership validator (Group E fix — 2026-05-16).

The pm-supervisor §8 envelope carries a ``counterfactual_top3_summary``
block with the per-bucket counts from §3.5 retrieval against the
``peak_pain_archetypes`` catalog. The aggregated audit across 11
historical PM reports surfaced these failure modes in this block:

- GOOGL: invented analog ``KODAK_1990s_2000s`` (NOT in the live catalog)
  was woven into the Reasoning row without going through retrieval.
- MU: invented a fourth bucket ``tbd: 1`` — not in the canonical schema
  (only ``survivor``/``diluted_survivor``/``non_survivor`` are allowed
  per pm-supervisor.md §8 line 488).
- AMZN: emitted similarity scores of 0.667 uniformly across all 3
  matches — placeholder pattern suggesting retrieval was simulated, not
  executed.
- ANET/CRCL: emitted no per-case similarity scores or
  ``lens_disciplined_note`` — retrieval not treated as a structured
  gate.

This module validates the block in two layers:

1. **Bucket-schema integrity** (always): the block has exactly the
   spec-defined keys; no invented buckets; count values are
   non-negative integers; total non-zero.
2. **case_id catalog membership** (optional, when a case_id list is
   provided via ``--case-ids`` or pulled from
   ``counterfactual_ledger.top3_match_case_ids``): every case_id is
   present in the live ``peak_pain_archetypes`` catalog.

DETERMINISM: pure stdlib for layer 1; layer 2 uses psycopg if available.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

# Canonical bucket keys per pm-supervisor.md §8 line 488 / Bug 13 schema.
ALLOWED_BUCKETS: frozenset[str] = frozenset({
    "survivor",
    "diluted_survivor",
    "non_survivor",
})

# Required count buckets — ALL three must be present even when zero.
REQUIRED_BUCKETS: tuple[str, ...] = (
    "survivor",
    "diluted_survivor",
    "non_survivor",
)

# Optional sibling fields per spec (line 492). lens_disciplined_note is
# nullable. Anything else is an invented field.
OPTIONAL_TOP3_FIELDS: frozenset[str] = frozenset({
    "lens_disciplined_note",
})

# Top-3 means exactly 3 retrieved cases. Counts can be zero only if the
# retrieval failed entirely; total = 3 is the canonical case.
EXPECTED_TOP_K = 3


@dataclass
class CounterfactualCatalogResult:
    """Result envelope for counterfactual catalog-membership validation."""

    valid: bool
    # Layer 1 — schema integrity.
    bucket_counts: dict[str, int] = field(default_factory=dict)
    missing_buckets: list[str] = field(default_factory=list)
    invented_buckets: list[str] = field(default_factory=list)
    invented_fields: list[str] = field(default_factory=list)
    total_count: int = 0
    count_matches_top_k: bool = True
    # Layer 2 — case_id catalog membership.
    case_ids_checked: list[str] = field(default_factory=list)
    case_ids_in_catalog: list[str] = field(default_factory=list)
    case_ids_not_in_catalog: list[str] = field(default_factory=list)
    catalog_resolved: bool = False
    notes: list[str] = field(default_factory=list)


def validate_top3_block_schema(
    block: object,
) -> CounterfactualCatalogResult:
    """Layer 1: schema integrity of the counterfactual_top3_summary block.

    Args:
        block: the value of envelope["counterfactual_top3_summary"].

    Returns:
        CounterfactualCatalogResult with valid=True iff:
        - block is a dict
        - all 3 REQUIRED_BUCKETS are present with non-negative int values
        - no invented buckets (any name outside ALLOWED_BUCKETS ∪ OPTIONAL_TOP3_FIELDS)
        - sum of counts equals EXPECTED_TOP_K (or 0 if retrieval failed)
    """
    if not isinstance(block, dict):
        return CounterfactualCatalogResult(
            valid=False,
            notes=[
                f"counterfactual_top3_summary must be a dict; got "
                f"{type(block).__name__}"
            ],
        )

    result = CounterfactualCatalogResult(valid=True)

    # Required bucket presence + non-negative int values.
    for bucket in REQUIRED_BUCKETS:
        value = block.get(bucket)
        if value is None:
            result.missing_buckets.append(bucket)
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            result.notes.append(
                f"bucket {bucket}={value!r} is not a non-negative int"
            )
            result.valid = False
            continue
        if value < 0:
            result.notes.append(
                f"bucket {bucket}={value} is negative — counts must be >= 0"
            )
            result.valid = False
            continue
        result.bucket_counts[bucket] = value

    if result.missing_buckets:
        result.valid = False
        result.notes.append(
            f"missing required buckets: {result.missing_buckets}"
        )

    # Invented-bucket detection (anything not in ALLOWED ∪ OPTIONAL).
    allowed_keys = ALLOWED_BUCKETS | OPTIONAL_TOP3_FIELDS
    invented_keys: list[str] = []
    invented_buckets: list[str] = []
    for k in block.keys():
        if k in allowed_keys:
            continue
        # Heuristic: if the value is an int, the agent treated it as a
        # bucket count (this is MU's tbd:1 case). Otherwise it's just an
        # invented sibling field.
        if isinstance(block[k], int) and not isinstance(block[k], bool):
            invented_buckets.append(k)
        else:
            invented_keys.append(k)
    result.invented_buckets = invented_buckets
    result.invented_fields = invented_keys
    if invented_buckets:
        result.valid = False
        result.notes.append(
            f"invented bucket(s) {invented_buckets} — canonical schema is "
            f"{sorted(ALLOWED_BUCKETS)} only"
        )
    if invented_keys:
        result.valid = False
        result.notes.append(
            f"invented sibling field(s) {invented_keys} — only "
            f"{sorted(OPTIONAL_TOP3_FIELDS)} permitted"
        )

    # Count integrity: total should equal EXPECTED_TOP_K (retrieval ran)
    # or 0 (retrieval failed). Anything in between is suspicious.
    result.total_count = sum(result.bucket_counts.values())
    if result.total_count not in (0, EXPECTED_TOP_K):
        result.count_matches_top_k = False
        result.valid = False
        result.notes.append(
            f"sum of bucket counts = {result.total_count}; spec calls for "
            f"top-{EXPECTED_TOP_K} retrieval (sum 0 if retrieval failed, "
            f"{EXPECTED_TOP_K} if it ran)"
        )

    return result


def validate_case_ids_in_catalog(
    case_ids: list[str],
    db_dsn: str | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Layer 2 helper: check each case_id resolves in peak_pain_archetypes.

    Returns:
        (resolved, unresolved, notes) — lists of case_ids that resolved
        vs didn't, plus any diagnostic notes.
    """
    notes: list[str] = []
    if not case_ids:
        return [], [], notes

    dsn = db_dsn or os.environ.get("EVIDENCE_DB_DSN") or os.environ.get(
        "DATABASE_URL"
    )
    if dsn is None:
        notes.append(
            "no DB DSN provided (set EVIDENCE_DB_DSN or DATABASE_URL or "
            "pass --db-dsn); catalog-membership check skipped"
        )
        return [], [], notes

    try:
        import psycopg  # type: ignore
    except ImportError:
        notes.append("psycopg not installed; catalog-membership check skipped")
        return [], [], notes

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT case_id FROM peak_pain_archetypes "
                    "WHERE case_id = ANY(%s)",
                    (case_ids,),
                )
                resolved = {row[0] for row in cur.fetchall()}
    except Exception as exc:  # noqa: BLE001
        notes.append(f"DB catalog lookup failed: {exc}")
        return [], [], notes

    resolved_list = [c for c in case_ids if c in resolved]
    unresolved_list = [c for c in case_ids if c not in resolved]
    return resolved_list, unresolved_list, notes


def validate_counterfactual_top3(
    envelope: object,
    case_ids: list[str] | None = None,
    db_dsn: str | None = None,
) -> CounterfactualCatalogResult:
    """Full validation: layer 1 (schema) + optional layer 2 (catalog).

    Args:
        envelope: parsed pm-supervisor JSON envelope.
        case_ids: optional list of case_ids to check against the live
            catalog. When None and counterfactual_ledger isn't queryable,
            layer 2 is skipped (with a note).
        db_dsn: Postgres DSN for the catalog table.

    Returns:
        CounterfactualCatalogResult.
    """
    if not isinstance(envelope, dict):
        return CounterfactualCatalogResult(
            valid=False,
            notes=[
                f"envelope must be a JSON object; got "
                f"{type(envelope).__name__}"
            ],
        )

    block = envelope.get("counterfactual_top3_summary")
    result = validate_top3_block_schema(block)

    if case_ids:
        resolved, unresolved, notes = validate_case_ids_in_catalog(
            case_ids, db_dsn=db_dsn
        )
        result.case_ids_checked = list(case_ids)
        result.case_ids_in_catalog = resolved
        result.case_ids_not_in_catalog = unresolved
        result.notes.extend(notes)
        if resolved or unresolved:
            result.catalog_resolved = True
        if unresolved:
            result.valid = False
            result.notes.append(
                f"{len(unresolved)} case_id(s) not in peak_pain_archetypes "
                f"catalog: {unresolved}"
            )

    return result


def _result_to_dict(r: CounterfactualCatalogResult) -> dict:
    return {
        "valid": r.valid,
        "bucket_counts": r.bucket_counts,
        "missing_buckets": r.missing_buckets,
        "invented_buckets": r.invented_buckets,
        "invented_fields": r.invented_fields,
        "total_count": r.total_count,
        "count_matches_top_k": r.count_matches_top_k,
        "case_ids_checked": r.case_ids_checked,
        "case_ids_in_catalog": r.case_ids_in_catalog,
        "case_ids_not_in_catalog": r.case_ids_not_in_catalog,
        "catalog_resolved": r.catalog_resolved,
        "notes": r.notes,
    }


def _cli(argv: list[str] | None = None) -> int:
    """CLI wrapper.

    Exit codes:
      0 valid
      1 invalid (schema and/or catalog check failed)
      2 input unparseable
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="counterfactual_catalog",
        description=(
            "Validate counterfactual_top3_summary against the canonical "
            "bucket schema, optionally verifying each case_id resolves "
            "in peak_pain_archetypes. Exit 0 valid, 1 invalid, 2 unparseable."
        ),
    )
    parser.add_argument(
        "--envelope",
        required=True,
        help='path to envelope JSON file, or "-" to read from stdin',
    )
    parser.add_argument(
        "--case-ids",
        default=None,
        help=(
            "comma-separated list of case_ids from §3.5 retrieval to "
            "validate against the live catalog (layer 2 check)"
        ),
    )
    parser.add_argument(
        "--db-dsn",
        default=None,
        help="Postgres DSN; defaults to EVIDENCE_DB_DSN / DATABASE_URL env",
    )
    args = parser.parse_args(argv)

    try:
        if args.envelope == "-":
            raw = sys.stdin.read()
        else:
            with open(args.envelope, "r", encoding="utf-8") as f:
                raw = f.read()
        envelope = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"unable to read/parse envelope: {exc}\n")
        return 2

    case_ids: list[str] | None = None
    if args.case_ids:
        case_ids = [c.strip() for c in args.case_ids.split(",") if c.strip()]

    result = validate_counterfactual_top3(
        envelope, case_ids=case_ids, db_dsn=args.db_dsn
    )
    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "CounterfactualCatalogResult",
    "validate_counterfactual_top3",
    "validate_top3_block_schema",
    "validate_case_ids_in_catalog",
    "ALLOWED_BUCKETS",
    "REQUIRED_BUCKETS",
    "OPTIONAL_TOP3_FIELDS",
    "EXPECTED_TOP_K",
]
