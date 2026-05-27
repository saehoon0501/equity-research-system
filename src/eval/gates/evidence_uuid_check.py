"""Evidence-index UUID validator (HG-26, Group J fix — 2026-05-16).

The pm-supervisor §8 envelope carries an ``evidence_index_refs`` array of
UUIDs that point into the ``evidence_index`` table. The aggregated audit
across 11 historical PM reports found 6/11 reports hard-fail this gate:

- AMD + MU: empty arrays despite the report claiming evidence-backed claims
- multiple: placeholder strings (e.g. ``"evidence_id: TODO"``) rather than
  valid UUIDs
- multiple: UUIDs that don't resolve in the ``evidence_index`` table
  (silent INSERT failure upstream)

This module validates the array in two passes:

1. **Syntactic** (no DB): every element parses as a valid UUID; the array
   is non-empty; no duplicates.
2. **Resolution** (DB-required): every UUID resolves to a row in
   ``evidence_index``. Optional — controlled by ``--resolve-db`` CLI
   flag. When the DB is unavailable, the gate degrades to syntactic-only
   and emits ``db_resolved=False`` in the result.

DETERMINISM: syntactic pass is pure stdlib. DB pass uses psycopg if
available; otherwise reports the resolution check as skipped.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass, field

# Empty arrays MUST be rejected — every report claims evidence-backed
# findings, so an empty refs array is a structural inconsistency.
MIN_REFS_REQUIRED = 1

# Common placeholder patterns we've seen in the historical corpus. These
# look UUID-ish but are not. Caught by the UUID parser already, but
# detecting them explicitly produces a better delta-prompt error message.
PLACEHOLDER_PATTERNS: tuple[str, ...] = (
    "TODO",
    "PLACEHOLDER",
    "PENDING",
    "FIXME",
    "TBD",
    "<uuid>",
    "uuid-here",
    "00000000-0000-0000-0000-000000000000",  # all-zero UUID
)


@dataclass
class EvidenceUUIDResult:
    """Result envelope for evidence_index_refs validation."""

    valid: bool
    n_refs: int
    n_valid_uuid: int
    n_invalid_uuid: int
    n_placeholders: int
    n_duplicates: int
    invalid_entries: list[str] = field(default_factory=list)
    placeholder_entries: list[str] = field(default_factory=list)
    duplicate_entries: list[str] = field(default_factory=list)
    # DB-resolution results (only populated when --resolve-db succeeds).
    db_resolved: bool = False
    n_resolved_in_db: int = 0
    unresolved_uuids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _is_placeholder(value: str) -> bool:
    """True iff ``value`` matches a known placeholder pattern."""
    upper = value.upper()
    return any(p.upper() in upper for p in PLACEHOLDER_PATTERNS)


def _parse_uuid(value: str) -> uuid.UUID | None:
    """Return a UUID instance for ``value`` or None on parse failure."""
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


def validate_evidence_refs_syntactic(
    refs: object,
) -> EvidenceUUIDResult:
    """Syntactic validation of an ``evidence_index_refs`` array.

    Args:
        refs: the array value from the envelope. Expected list[str] of
            UUIDs.

    Returns:
        EvidenceUUIDResult with valid=True iff (a) refs is a non-empty
        list, (b) every element parses as a valid UUID, (c) no element
        matches a placeholder pattern, (d) no duplicates.
    """
    if not isinstance(refs, list):
        return EvidenceUUIDResult(
            valid=False,
            n_refs=0,
            n_valid_uuid=0,
            n_invalid_uuid=0,
            n_placeholders=0,
            n_duplicates=0,
            notes=[
                f"evidence_index_refs must be a list; got "
                f"{type(refs).__name__}"
            ],
        )

    n_refs = len(refs)
    valid_uuids: list[str] = []
    invalid: list[str] = []
    placeholders: list[str] = []
    seen: dict[str, int] = {}
    duplicates: list[str] = []

    for entry in refs:
        # Coerce to string for diagnostic reporting; non-strings are
        # invalid UUIDs by definition.
        s = entry if isinstance(entry, str) else str(entry)

        if _is_placeholder(s):
            placeholders.append(s)
            continue

        parsed = _parse_uuid(s)
        if parsed is None:
            invalid.append(s)
            continue

        canonical = str(parsed)
        seen[canonical] = seen.get(canonical, 0) + 1
        if seen[canonical] == 2:  # first time we hit duplicate threshold
            duplicates.append(canonical)
        valid_uuids.append(canonical)

    notes: list[str] = []
    if n_refs < MIN_REFS_REQUIRED:
        notes.append(
            f"evidence_index_refs has {n_refs} entries; minimum required "
            f"is {MIN_REFS_REQUIRED} (every report claims evidence-backed "
            "findings)"
        )

    is_valid = (
        n_refs >= MIN_REFS_REQUIRED
        and not invalid
        and not placeholders
        and not duplicates
    )

    return EvidenceUUIDResult(
        valid=is_valid,
        n_refs=n_refs,
        n_valid_uuid=len(valid_uuids),
        n_invalid_uuid=len(invalid),
        n_placeholders=len(placeholders),
        n_duplicates=len(duplicates),
        invalid_entries=invalid,
        placeholder_entries=placeholders,
        duplicate_entries=duplicates,
        notes=notes,
    )


def validate_evidence_refs_with_db(
    refs: object,
    db_dsn: str | None = None,
) -> EvidenceUUIDResult:
    """Full validation: syntactic + DB resolution.

    Args:
        refs: the array value from the envelope.
        db_dsn: Postgres DSN. Defaults to env var EVIDENCE_DB_DSN, then
            DATABASE_URL. If neither set and no DSN passed, falls back
            to syntactic-only.

    Returns:
        EvidenceUUIDResult with db_resolved=True iff the DB pass ran
        successfully. valid=True iff (a) syntactic pass clean AND (b)
        every UUID resolves to a row in evidence_index.
    """
    result = validate_evidence_refs_syntactic(refs)
    # Bail early if syntactic failed — no point hitting DB with garbage.
    if not result.valid:
        return result

    dsn = db_dsn or os.environ.get("EVIDENCE_DB_DSN") or os.environ.get(
        "DATABASE_URL"
    )
    if dsn is None:
        result.notes.append(
            "no DB DSN provided (set EVIDENCE_DB_DSN or DATABASE_URL or "
            "pass --db-dsn); resolution check skipped"
        )
        return result

    try:
        import psycopg  # type: ignore
    except ImportError:
        result.notes.append(
            "psycopg not installed; DB resolution check skipped"
        )
        return result

    canonical_uuids = [
        str(u)
        for u in (_parse_uuid(r) for r in refs if isinstance(r, str))
        if u is not None
    ]

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT evidence_id::text FROM evidence_index "
                    "WHERE evidence_id = ANY(%s::uuid[])",
                    (canonical_uuids,),
                )
                resolved = {row[0] for row in cur.fetchall()}
    except Exception as exc:  # noqa: BLE001 — surface DB errors as note
        result.notes.append(f"DB resolution failed: {exc}")
        return result

    unresolved = [u for u in canonical_uuids if u not in resolved]
    result.db_resolved = True
    result.n_resolved_in_db = len(resolved)
    result.unresolved_uuids = unresolved
    if unresolved:
        result.valid = False
        result.notes.append(
            f"{len(unresolved)} UUID(s) do not resolve in evidence_index"
        )

    return result


def _result_to_dict(r: EvidenceUUIDResult) -> dict:
    return {
        "valid": r.valid,
        "n_refs": r.n_refs,
        "n_valid_uuid": r.n_valid_uuid,
        "n_invalid_uuid": r.n_invalid_uuid,
        "n_placeholders": r.n_placeholders,
        "n_duplicates": r.n_duplicates,
        "invalid_entries": r.invalid_entries,
        "placeholder_entries": r.placeholder_entries,
        "duplicate_entries": r.duplicate_entries,
        "db_resolved": r.db_resolved,
        "n_resolved_in_db": r.n_resolved_in_db,
        "unresolved_uuids": r.unresolved_uuids,
        "notes": r.notes,
    }


def _cli(argv: list[str] | None = None) -> int:
    """CLI wrapper. Reads envelope JSON and validates evidence_index_refs.

    Exit codes:
      0  valid
      1  invalid
      2  unparseable input or arguments
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="evidence_uuid_check",
        description=(
            "Validate the evidence_index_refs array of a pm-supervisor "
            "envelope. Syntactic checks always; DB resolution check "
            "when --resolve-db. Exit 0 valid, 1 invalid, 2 unparseable."
        ),
    )
    parser.add_argument(
        "--envelope",
        required=True,
        help='path to envelope JSON file, or "-" to read from stdin',
    )
    parser.add_argument(
        "--resolve-db",
        action="store_true",
        help=(
            "also verify each UUID resolves in the evidence_index table "
            "(requires psycopg + EVIDENCE_DB_DSN or DATABASE_URL or --db-dsn)"
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

    refs = envelope.get("evidence_index_refs") if isinstance(
        envelope, dict
    ) else None

    if args.resolve_db:
        result = validate_evidence_refs_with_db(refs, db_dsn=args.db_dsn)
    else:
        result = validate_evidence_refs_syntactic(refs)

    sys.stdout.write(json.dumps(_result_to_dict(result), indent=2) + "\n")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "EvidenceUUIDResult",
    "validate_evidence_refs_syntactic",
    "validate_evidence_refs_with_db",
    "MIN_REFS_REQUIRED",
    "PLACEHOLDER_PATTERNS",
]
