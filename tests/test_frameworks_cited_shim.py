"""Tests for the frameworks_cited dual-read shim (CAF-2 migration)."""

from __future__ import annotations

import pytest

from src.evaluator_gates._frameworks_cited_shim import (
    find_framework,
    get_framework_keys,
    is_keyed_object_form,
    iter_frameworks,
)


# ---------- legacy list-form fixtures ----------

LIST_FORM_MEMO = {
    "frameworks_cited": [
        {"framework_key": "damodaran_narrative_dcf", "output": {"base": 218.60}},
        {"framework_key": "mauboussin_reverse_dcf", "output": {"implied_growth_pct": 17.92}},
        {"framework_key": "buffett_2007_inevitables", "output": {"reinvestment_moat": {"quality_label": "A"}}},
    ]
}

# ---------- v3.1+ keyed-object-form fixtures ----------

KEYED_FORM_MEMO = {
    "frameworks_cited": {
        "damodaran_narrative_dcf": {"framework_key": "damodaran_narrative_dcf", "output": {"base": 218.60}},
        "mauboussin_reverse_dcf": {"framework_key": "mauboussin_reverse_dcf", "output": {"implied_growth_pct": 17.92}},
        "buffett_2007_inevitables": {"framework_key": "buffett_2007_inevitables", "output": {"reinvestment_moat": {"quality_label": "A"}}},
    }
}


# ---------- find_framework — equivalence across forms ----------


@pytest.mark.parametrize("memo", [LIST_FORM_MEMO, KEYED_FORM_MEMO])
def test_find_framework_returns_dcf_entry(memo: dict) -> None:
    entry = find_framework(memo, "damodaran_narrative_dcf")
    assert entry is not None
    assert entry["output"]["base"] == 218.60


@pytest.mark.parametrize("memo", [LIST_FORM_MEMO, KEYED_FORM_MEMO])
def test_find_framework_returns_reverse_dcf_entry(memo: dict) -> None:
    entry = find_framework(memo, "mauboussin_reverse_dcf")
    assert entry is not None
    assert entry["output"]["implied_growth_pct"] == 17.92


@pytest.mark.parametrize("memo", [LIST_FORM_MEMO, KEYED_FORM_MEMO])
def test_find_framework_returns_buffett_entry(memo: dict) -> None:
    entry = find_framework(memo, "buffett_2007_inevitables")
    assert entry is not None
    assert entry["output"]["reinvestment_moat"]["quality_label"] == "A"


@pytest.mark.parametrize("memo", [LIST_FORM_MEMO, KEYED_FORM_MEMO])
def test_find_framework_returns_none_for_missing_key(memo: dict) -> None:
    assert find_framework(memo, "nonexistent_framework") is None


def test_find_framework_handles_missing_field() -> None:
    assert find_framework({}, "damodaran_narrative_dcf") is None


def test_find_framework_handles_none_field() -> None:
    assert find_framework({"frameworks_cited": None}, "damodaran_narrative_dcf") is None


def test_find_framework_handles_malformed_list_entries() -> None:
    """A legacy list with non-dict entries should be skipped, not crash."""
    memo = {"frameworks_cited": ["not_a_dict", None, 42]}
    assert find_framework(memo, "damodaran_narrative_dcf") is None


def test_find_framework_handles_malformed_keyed_entries() -> None:
    """A keyed-object form with non-dict values should be skipped."""
    memo = {"frameworks_cited": {"damodaran_narrative_dcf": "not_a_dict"}}
    assert find_framework(memo, "damodaran_narrative_dcf") is None


def test_find_framework_handles_wrong_type() -> None:
    """frameworks_cited must be list or dict; other types return None."""
    assert find_framework({"frameworks_cited": "string"}, "x") is None
    assert find_framework({"frameworks_cited": 42}, "x") is None


# ---------- iter_frameworks ----------


@pytest.mark.parametrize("memo", [LIST_FORM_MEMO, KEYED_FORM_MEMO])
def test_iter_frameworks_yields_three_entries(memo: dict) -> None:
    entries = list(iter_frameworks(memo))
    assert len(entries) == 3
    keys = {e["framework_key"] for e in entries}
    assert keys == {"damodaran_narrative_dcf", "mauboussin_reverse_dcf", "buffett_2007_inevitables"}


def test_iter_frameworks_handles_missing_field() -> None:
    assert list(iter_frameworks({})) == []


def test_iter_frameworks_handles_none() -> None:
    assert list(iter_frameworks({"frameworks_cited": None})) == []


# ---------- get_framework_keys ----------


@pytest.mark.parametrize("memo", [LIST_FORM_MEMO, KEYED_FORM_MEMO])
def test_get_framework_keys_returns_set(memo: dict) -> None:
    keys = get_framework_keys(memo)
    assert keys == {"damodaran_narrative_dcf", "mauboussin_reverse_dcf", "buffett_2007_inevitables"}


def test_get_framework_keys_handles_missing() -> None:
    assert get_framework_keys({}) == set()


# ---------- is_keyed_object_form (migration telemetry) ----------


def test_is_keyed_object_form_detects_keyed() -> None:
    assert is_keyed_object_form(KEYED_FORM_MEMO) is True


def test_is_keyed_object_form_detects_list() -> None:
    assert is_keyed_object_form(LIST_FORM_MEMO) is False


def test_is_keyed_object_form_missing_field() -> None:
    assert is_keyed_object_form({}) is False


def test_is_keyed_object_form_none() -> None:
    assert is_keyed_object_form({"frameworks_cited": None}) is False
