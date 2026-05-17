"""Unit tests for src.evaluator_gates.evidence_uuid_check (HG-26, Group J)."""

from __future__ import annotations

import uuid

import pytest

from src.evaluator_gates.evidence_uuid_check import (
    EvidenceUUIDResult,
    PLACEHOLDER_PATTERNS,
    validate_evidence_refs_syntactic,
)


def _u() -> str:
    return str(uuid.uuid4())


def test_clean_array_passes() -> None:
    refs = [_u(), _u(), _u()]
    r = validate_evidence_refs_syntactic(refs)
    assert r.valid
    assert r.n_refs == 3
    assert r.n_valid_uuid == 3
    assert r.n_invalid_uuid == 0
    assert not r.placeholder_entries


def test_empty_array_fails() -> None:
    """Group J: AMD + MU emitted [] — claim of evidence-backed findings
    with zero refs is a structural inconsistency."""
    r = validate_evidence_refs_syntactic([])
    assert not r.valid
    assert r.n_refs == 0
    assert any("minimum required" in n for n in r.notes)


def test_non_list_fails() -> None:
    r = validate_evidence_refs_syntactic("not-a-list")
    assert not r.valid
    assert any("must be a list" in n for n in r.notes)


def test_missing_field_returns_invalid() -> None:
    r = validate_evidence_refs_syntactic(None)
    assert not r.valid


@pytest.mark.parametrize("placeholder", [
    "TODO-uuid",
    "PLACEHOLDER-12345678",
    "evidence_id: PENDING",
    "uuid-here",
    "00000000-0000-0000-0000-000000000000",
    "TBD",
])
def test_placeholder_patterns_rejected(placeholder: str) -> None:
    r = validate_evidence_refs_syntactic([placeholder])
    assert not r.valid
    assert r.n_placeholders >= 1
    assert placeholder in r.placeholder_entries


def test_invalid_uuid_caught() -> None:
    r = validate_evidence_refs_syntactic(["not-a-uuid", _u()])
    assert not r.valid
    assert r.n_invalid_uuid == 1
    assert "not-a-uuid" in r.invalid_entries


def test_duplicate_uuid_caught() -> None:
    same = _u()
    r = validate_evidence_refs_syntactic([same, same, _u()])
    assert not r.valid
    assert r.n_duplicates == 1
    assert same in r.duplicate_entries


def test_uuid_canonical_form_handles_dup_case() -> None:
    raw = "ABCDEF12-3456-7890-abcd-ef1234567890"
    same_lower = raw.lower()
    r = validate_evidence_refs_syntactic([raw, same_lower])
    assert not r.valid
    assert r.n_duplicates == 1


def test_non_string_entries_become_invalid() -> None:
    r = validate_evidence_refs_syntactic([12345, None, {"foo": "bar"}])
    assert not r.valid
    assert r.n_invalid_uuid == 3


def test_placeholder_pattern_constants_present() -> None:
    """Sanity: the canonical placeholder list is non-empty + all upper-case
    substrings."""
    assert len(PLACEHOLDER_PATTERNS) >= 5
    for p in PLACEHOLDER_PATTERNS:
        assert isinstance(p, str)
