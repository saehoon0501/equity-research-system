"""Acceptance criterion 2 — ALCE citation P/R is DETERMINISTIC, no network.

This module must import and run with NO anthropic / network / DB. It only
touches ``src.scoring.articulation.citation`` (pure stdlib + the
frameworks_cited dual-read shim) and hand-computes P/R/F1 on >=5 fixtures,
asserting agreement within +-0.05.

If importing this test pulled in any LLM/network dependency, that would
itself be a criterion-2 failure — so the imports below are deliberately
narrow.
"""

from __future__ import annotations

import math

import pytest

from src.scoring.articulation.citation import (
    CITATION_METHOD,
    compute_citation_pr,
    score_citation,
)

TOL = 0.05


def _legacy_env(keys):
    """Envelope with legacy list-form frameworks_cited."""
    return {"frameworks_cited": [{"framework_key": k, "output": {}} for k in keys]}


def _keyed_env(keys):
    """Envelope with v3.1 keyed-object-form frameworks_cited."""
    return {"frameworks_cited": {k: {"framework_key": k, "output": {}} for k in keys}}


# (id, cited, supported, expected_precision, expected_recall, expected_f1)
# All hand-computed.
FIXTURES = [
    # 3 cited, all 3 supported, supported has 4 => P=1.0, R=3/4=0.75
    (
        "perfect-precision-partial-recall",
        {"a", "b", "c"},
        {"a", "b", "c", "d"},
        1.0,
        0.75,
        2 * 1.0 * 0.75 / (1.0 + 0.75),  # 0.857142...
    ),
    # 4 cited, 2 supported-overlap, supported has 2 => P=0.5, R=1.0
    (
        "half-precision-full-recall",
        {"a", "b", "x", "y"},
        {"a", "b"},
        0.5,
        1.0,
        2 * 0.5 * 1.0 / (0.5 + 1.0),  # 0.6666...
    ),
    # cited 2, supported 2, identical => P=1, R=1, F1=1
    (
        "exact-match",
        {"m", "n"},
        {"m", "n"},
        1.0,
        1.0,
        1.0,
    ),
    # cited 3, zero overlap => P=0, R=0, F1=0
    (
        "no-overlap",
        {"p", "q", "r"},
        {"s", "t"},
        0.0,
        0.0,
        0.0,
    ),
    # nothing cited (empty) => P=0 (zero denom), R=0 (no overlap), F1=0
    (
        "empty-cited",
        set(),
        {"a", "b"},
        0.0,
        0.0,
        0.0,
    ),
    # nothing supported => P=0 (no overlap), R=0 (zero denom), F1=0
    (
        "empty-supported",
        {"a", "b"},
        set(),
        0.0,
        0.0,
        0.0,
    ),
    # 5 cited, 4 overlap, supported 6 => P=4/5=0.8, R=4/6=0.6667
    (
        "five-cited-mixed",
        {"a", "b", "c", "d", "z"},
        {"a", "b", "c", "d", "e", "f"},
        0.8,
        4 / 6,
        2 * 0.8 * (4 / 6) / (0.8 + 4 / 6),  # 0.7272...
    ),
]


@pytest.mark.parametrize(
    "name,cited,supported,exp_p,exp_r,exp_f1", FIXTURES, ids=[f[0] for f in FIXTURES]
)
def test_citation_pr_matches_hand_computed(name, cited, supported, exp_p, exp_r, exp_f1):
    res = compute_citation_pr(cited, supported)
    assert abs(res.precision - exp_p) <= TOL, f"{name} precision"
    assert abs(res.recall - exp_r) <= TOL, f"{name} recall"
    assert abs(res.f1 - exp_f1) <= TOL, f"{name} f1"


def test_citation_pr_is_deterministic_repeat():
    """Same inputs -> identical output across repeated calls (no randomness)."""
    a = compute_citation_pr({"a", "b", "c"}, {"a", "b", "c", "d"})
    b = compute_citation_pr({"a", "b", "c"}, {"a", "b", "c", "d"})
    assert a == b
    assert a.method == CITATION_METHOD


def test_score_citation_reads_legacy_list_form():
    env = _legacy_env(["a", "b", "c"])
    res = score_citation(env, {"a", "b", "c", "d"})
    assert math.isclose(res.precision, 1.0)
    assert math.isclose(res.recall, 0.75)
    assert res.n_cited == 3 and res.n_supported == 4 and res.n_overlap == 3


def test_score_citation_reads_keyed_object_form():
    """Dual-read: keyed-object form yields the same result as list form."""
    env = _keyed_env(["a", "b", "x", "y"])
    res = score_citation(env, {"a", "b"})
    assert math.isclose(res.precision, 0.5)
    assert math.isclose(res.recall, 1.0)


def test_no_anthropic_imported_by_citation_path():
    """Criterion 2: the deterministic path imports no LLM SDK.

    We assert ``anthropic`` is not in sys.modules after importing the
    citation module + running scores. (anthropic may be entirely absent in
    this env; either way it must not have been imported by our path.)
    """
    import sys

    assert "anthropic" not in sys.modules


def test_citation_block_serialization_shape():
    res = compute_citation_pr({"a", "b"}, {"a"})
    block = res.to_block()
    assert set(block) >= {
        "precision",
        "recall",
        "f1",
        "n_cited",
        "n_supported",
        "n_overlap",
        "method",
        "mode",
    }
    assert block["mode"] == "advisory"
