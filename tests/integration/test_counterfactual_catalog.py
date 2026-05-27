"""Unit tests for src.eval.gates.counterfactual_catalog (Group E)."""

from __future__ import annotations

import pytest

from src.eval.gates.counterfactual_catalog import (
    ALLOWED_BUCKETS,
    EXPECTED_TOP_K,
    REQUIRED_BUCKETS,
    validate_top3_block_schema,
    validate_counterfactual_top3,
)


def test_canonical_block_passes() -> None:
    block = {
        "survivor": 3,
        "diluted_survivor": 0,
        "non_survivor": 0,
        "lens_disciplined_note": "3 mega-cap consumer/internet platform SURVIVOR analogs",
    }
    r = validate_top3_block_schema(block)
    assert r.valid, r.notes


def test_empty_retrieval_passes_schema() -> None:
    """Sum=0 means retrieval failed; schema-valid but caller may still
    treat retrieval-fail separately."""
    block = {"survivor": 0, "diluted_survivor": 0, "non_survivor": 0}
    r = validate_top3_block_schema(block)
    assert r.valid


def test_mu_invented_tbd_bucket_caught() -> None:
    """MU: invented `tbd: 1` bucket."""
    block = {
        "survivor": 1,
        "diluted_survivor": 1,
        "non_survivor": 0,
        "tbd": 1,
    }
    r = validate_top3_block_schema(block)
    assert not r.valid
    assert "tbd" in r.invented_buckets
    assert any("invented bucket" in n for n in r.notes)


def test_missing_bucket_caught() -> None:
    """ANET/CRCL: missing one or more required count buckets."""
    block = {"survivor": 3}
    r = validate_top3_block_schema(block)
    assert not r.valid
    assert "diluted_survivor" in r.missing_buckets
    assert "non_survivor" in r.missing_buckets


def test_invented_sibling_field_caught() -> None:
    """RKLB-style: extra free-form sibling field outside the canonical schema."""
    block = {
        "survivor": 0,
        "diluted_survivor": 0,
        "non_survivor": 3,
        "veto_recommended": True,  # not in schema
    }
    r = validate_top3_block_schema(block)
    assert not r.valid
    assert "veto_recommended" in r.invented_fields


def test_negative_count_rejected() -> None:
    block = {"survivor": -1, "diluted_survivor": 0, "non_survivor": 0}
    r = validate_top3_block_schema(block)
    assert not r.valid
    assert any("negative" in n for n in r.notes)


def test_non_int_count_rejected() -> None:
    block = {"survivor": "three", "diluted_survivor": 0, "non_survivor": 0}
    r = validate_top3_block_schema(block)
    assert not r.valid
    assert any("non-negative int" in n for n in r.notes)


def test_count_not_top_k_flagged() -> None:
    """Sum should be 0 or EXPECTED_TOP_K (3). Anything else is suspicious."""
    block = {"survivor": 1, "diluted_survivor": 1, "non_survivor": 0}  # sum=2
    r = validate_top3_block_schema(block)
    assert not r.valid
    assert r.total_count == 2
    assert not r.count_matches_top_k


def test_envelope_wrapper_handles_missing_block() -> None:
    """If counterfactual_top3_summary is entirely absent from the envelope."""
    r = validate_counterfactual_top3({})
    assert not r.valid


def test_envelope_wrapper_invalid_type() -> None:
    r = validate_counterfactual_top3({
        "counterfactual_top3_summary": "should-be-dict",
    })
    assert not r.valid
    assert any("must be a dict" in n for n in r.notes)


def test_allowed_constants_match_spec() -> None:
    """Pin the canonical bucket enum."""
    assert ALLOWED_BUCKETS == frozenset({
        "survivor", "diluted_survivor", "non_survivor"
    })
    assert REQUIRED_BUCKETS == ("survivor", "diluted_survivor", "non_survivor")
    assert EXPECTED_TOP_K == 3
