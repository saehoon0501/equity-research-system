"""Pure-unit tests for the CPCV partition scheme (task 2.1, ``cpcv.py``).

``make_partitions(history, n_groups, k_test, embargo) -> list[Partition]``
realizes the leakage firewall as **combinatorial purged cross-validation**
(López de Prado, *Advances in Financial Machine Learning* ch. 7 — CPCV /
purging / embargo). There is no numeric formula to anchor here (that discipline
belongs to the gate, 2.3); the **invariants ARE the spec**, so these tests
assert the firewall properties directly (tasks.md 2.1 Observable, design
§"Testing Strategy → Unit Tests → cpcv.py", R2.2/2.3/4.1):

  * purge removes label-overlapping observations (a training obs whose label
    span reaches into a test block is dropped);
  * embargo follows each *contiguous* test block (a training obs within
    ``embargo`` observations after a test block's tail is dropped);
  * **NO out-of-sample observation appears in the matching IS set** — the
    load-bearing firewall property, asserted per partition;
  * the combinatorial count is ``C(n_groups, k_test)``;
  * deterministic (identical inputs → identical ``list[Partition]``).

Each ``Partition``'s OOS span maps to the consumed harness ``ReplayWindow``
(design seam note, design.md line 205 — the two specs share ONE window type).
For ``k_test > 1`` the chosen test groups can be non-adjacent ({0, 2}); since
``Partition.oos_window`` is a *single* ``ReplayWindow``, the window is the
**hull** ``[min OOS start, max OOS end]`` (documented in cpcv.py) and the
firewall is enforced at the **index level**, not the window level.

History element shape (local to cpcv.py, NOT added to the types barrier — it is
out of boundary): each observation is a ``dict`` with ``symbol`` (→ window
``tickers``), ``event_ts`` (the feature/decision instant → window ``start``),
and ``label_end_ts`` (the label-span end → drives purge). This matches the
natural upstream ``ReadSet.trace_rows`` being ``list[dict[str, Any]]``.

Pure leaf (P1, P14 inner-ring): stdlib only, no LLM / MCP / DB / numpy.
"""

from __future__ import annotations

import itertools
from math import comb

from src.reactive.replay import ReplayWindow
from src.skills.walkforward_tune.cpcv import make_partitions
from src.skills.walkforward_tune.types import Partition


# --- History builders ------------------------------------------------------


def _point_in_time_history(n: int) -> list[dict]:
    """``n`` observations, each labeled within its own day (no overlap).

    ``event_ts`` and ``label_end_ts`` are the same ISO day — a degenerate
    point-in-time label so purge is a no-op. This is the trivially-disjoint
    baseline; the planted-overlap histories below exercise purge/embargo.
    """
    return [
        {
            "symbol": "AAA",
            "event_ts": f"2026-01-{day:02d}",
            "label_end_ts": f"2026-01-{day:02d}",
        }
        for day in range(1, n + 1)
    ]


# --- Combinatorial count ---------------------------------------------------


def test_partition_count_is_n_groups_choose_k_test() -> None:
    history = _point_in_time_history(12)
    parts = make_partitions(history, n_groups=4, k_test=2, embargo=0)
    assert len(parts) == comb(4, 2) == 6


def test_k_test_one_yields_n_groups_partitions() -> None:
    history = _point_in_time_history(12)
    parts = make_partitions(history, n_groups=4, k_test=1, embargo=0)
    assert len(parts) == 4


def test_every_partition_is_a_partition_dataclass() -> None:
    history = _point_in_time_history(12)
    for p in make_partitions(history, n_groups=3, k_test=1, embargo=0):
        assert isinstance(p, Partition)
        assert isinstance(p.oos_window, ReplayWindow)


def test_partition_ids_are_the_enumeration_index() -> None:
    history = _point_in_time_history(12)
    parts = make_partitions(history, n_groups=4, k_test=2, embargo=0)
    assert [p.partition_id for p in parts] == list(range(len(parts)))


def test_oos_index_sets_match_the_combinations_of_groups() -> None:
    # 12 obs / 4 groups → contiguous blocks [0..2],[3..5],[6..8],[9..11].
    history = _point_in_time_history(12)
    blocks = [list(range(0, 3)), list(range(3, 6)), list(range(6, 9)), list(range(9, 12))]
    parts = make_partitions(history, n_groups=4, k_test=2, embargo=0)
    got = {tuple(sorted(p.oos_indices)) for p in parts}
    expected = {
        tuple(sorted(blocks[a] + blocks[b]))
        for a, b in itertools.combinations(range(4), 2)
    }
    assert got == expected


# --- THE firewall property: no OOS obs in the matching IS set --------------


def test_no_oos_observation_appears_in_the_matching_is_set() -> None:
    history = _point_in_time_history(20)
    for p in make_partitions(history, n_groups=5, k_test=2, embargo=1):
        assert set(p.is_indices).isdisjoint(set(p.oos_indices)), (
            f"firewall breach in partition {p.partition_id}: "
            f"OOS index leaked into IS"
        )


def test_is_and_oos_indices_are_within_history_range() -> None:
    history = _point_in_time_history(15)
    for p in make_partitions(history, n_groups=5, k_test=1, embargo=2):
        for i in p.is_indices + p.oos_indices:
            assert 0 <= i < len(history)


# --- PURGE: a training obs whose label span reaches into a test block ------


def test_purge_drops_a_training_observation_overlapping_a_test_block() -> None:
    # 9 obs / 3 groups → blocks [0,1,2],[3,4,5],[6,7,8].
    # Plant obs index 2 (last of train group 0) with a label that ends inside
    # test group 1 (its label_end_ts reaches 2026-01-04, which is in block 1's
    # span). With group 1 as the single test block, index 2 must be PURGED from
    # the IS set even though it lives in a training group.
    history = _point_in_time_history(9)
    history[2] = {
        "symbol": "AAA",
        "event_ts": "2026-01-03",
        "label_end_ts": "2026-01-04",  # reaches into block 1 (days 04-06)
    }
    # Find the partition whose OOS is exactly the middle block (indices 3,4,5).
    parts = make_partitions(history, n_groups=3, k_test=1, embargo=0)
    mid = next(p for p in parts if set(p.oos_indices) == {3, 4, 5})
    assert 2 not in mid.is_indices, (
        "obs 2 overlaps the test block's label span and must be purged"
    )
    # A non-overlapping training obs in the same group (index 0) stays.
    assert 0 in mid.is_indices


def test_purge_is_a_noop_for_point_in_time_labels() -> None:
    # With same-day labels, nothing overlaps → IS = all non-OOS, non-embargo.
    history = _point_in_time_history(9)
    parts = make_partitions(history, n_groups=3, k_test=1, embargo=0)
    mid = next(p for p in parts if set(p.oos_indices) == {3, 4, 5})
    assert set(mid.is_indices) == {0, 1, 2, 6, 7, 8}


# --- EMBARGO: a training obs within `embargo` after a test block's tail -----


def test_embargo_drops_training_observations_after_a_test_block() -> None:
    # 9 obs / 3 groups, point-in-time labels (purge is a no-op). Test the
    # FIRST block (indices 0,1,2); embargo=2 must drop the 2 training obs
    # immediately after the block's tail (indices 3 and 4).
    history = _point_in_time_history(9)
    parts = make_partitions(history, n_groups=3, k_test=1, embargo=2)
    first = next(p for p in parts if set(p.oos_indices) == {0, 1, 2})
    assert 3 not in first.is_indices, "index 3 is in the embargo zone"
    assert 4 not in first.is_indices, "index 4 is in the embargo zone"
    assert 5 in first.is_indices, "index 5 is past the embargo zone"


def test_embargo_zero_keeps_all_non_overlapping_training_obs() -> None:
    history = _point_in_time_history(9)
    parts = make_partitions(history, n_groups=3, k_test=1, embargo=0)
    first = next(p for p in parts if set(p.oos_indices) == {0, 1, 2})
    assert set(first.is_indices) == {3, 4, 5, 6, 7, 8}


def test_embargo_applies_after_each_contiguous_test_block() -> None:
    # k_test=2 with NON-adjacent groups {0, 2} (blocks [0,1,2] and [6,7,8]).
    # 9 obs / 3 groups, embargo=1: each contiguous block gets its own embargo.
    # Block [0,1,2] tail → embargo drops index 3; block [6,7,8] tail is the end
    # of history → no obs to embargo. Index 3 dropped; index 4,5 kept.
    history = _point_in_time_history(9)
    parts = make_partitions(history, n_groups=3, k_test=2, embargo=1)
    split = next(p for p in parts if set(p.oos_indices) == {0, 1, 2, 6, 7, 8})
    assert 3 not in split.is_indices, "embargo after the first test block drops index 3"
    assert {4, 5}.issubset(set(split.is_indices)), "indices 4,5 are past the embargo"


def test_adjacent_test_groups_coalesce_into_one_block_for_embargo() -> None:
    # 12 obs / 4 groups → blocks [0..2],[3..5],[6..8],[9..11]. Choose adjacent
    # groups {0,1} (one contiguous block [0..5]); embargo=1 drops only ONE obs
    # after the coalesced tail (index 6), not after each group.
    history = _point_in_time_history(12)
    parts = make_partitions(history, n_groups=4, k_test=2, embargo=1)
    coalesced = next(p for p in parts if set(p.oos_indices) == {0, 1, 2, 3, 4, 5})
    assert 6 not in coalesced.is_indices, "embargo after the coalesced block drops index 6"
    assert 7 in coalesced.is_indices, "only ONE obs is embargoed after a coalesced block"


# --- oos_window: the hull mapped to the consumed ReplayWindow --------------


def test_oos_window_is_the_hull_of_the_oos_span() -> None:
    # 9 obs / 3 groups, single middle block {3,4,5} → days 04,05,06.
    history = _point_in_time_history(9)
    parts = make_partitions(history, n_groups=3, k_test=1, embargo=0)
    mid = next(p for p in parts if set(p.oos_indices) == {3, 4, 5})
    assert mid.oos_window.start == "2026-01-04"
    assert mid.oos_window.end == "2026-01-06"


def test_oos_window_hull_spans_non_adjacent_blocks() -> None:
    # NON-adjacent OOS {0,1,2} ∪ {6,7,8} → hull [day 01, day 09], which spans
    # the interior training group. This is the documented hull behavior: the
    # window is a hull; the firewall is enforced at the INDEX level.
    history = _point_in_time_history(9)
    parts = make_partitions(history, n_groups=3, k_test=2, embargo=0)
    split = next(p for p in parts if set(p.oos_indices) == {0, 1, 2, 6, 7, 8})
    assert split.oos_window.start == "2026-01-01"
    assert split.oos_window.end == "2026-01-09"


def test_oos_window_tickers_are_the_symbols_in_the_oos_span() -> None:
    history = _point_in_time_history(9)
    history[3] = {"symbol": "BBB", "event_ts": "2026-01-04", "label_end_ts": "2026-01-04"}
    parts = make_partitions(history, n_groups=3, k_test=1, embargo=0)
    mid = next(p for p in parts if set(p.oos_indices) == {3, 4, 5})
    assert set(mid.oos_window.tickers) == {"AAA", "BBB"}


def test_oos_window_end_uses_label_end_not_event_ts() -> None:
    # The OOS window must cover the full label horizon of its observations:
    # an OOS obs whose label_end_ts extends past the last event_ts pushes the
    # window end out (no truncation of the realized label span).
    history = _point_in_time_history(9)
    history[5] = {"symbol": "AAA", "event_ts": "2026-01-06", "label_end_ts": "2026-01-20"}
    parts = make_partitions(history, n_groups=3, k_test=1, embargo=0)
    mid = next(p for p in parts if set(p.oos_indices) == {3, 4, 5})
    assert mid.oos_window.end == "2026-01-20"


# --- Determinism -----------------------------------------------------------


def test_identical_inputs_yield_identical_partitions() -> None:
    history = _point_in_time_history(15)
    a = make_partitions(history, n_groups=5, k_test=2, embargo=1)
    b = make_partitions(history, n_groups=5, k_test=2, embargo=1)
    assert a == b


def test_does_not_mutate_the_input_history() -> None:
    history = _point_in_time_history(9)
    snapshot = [dict(row) for row in history]
    make_partitions(history, n_groups=3, k_test=1, embargo=2)
    assert history == snapshot


# --- Degeneracy / guards ---------------------------------------------------


def test_k_test_must_be_less_than_n_groups() -> None:
    # k_test == n_groups leaves no training data — a degenerate request.
    history = _point_in_time_history(9)
    import pytest

    with pytest.raises(ValueError):
        make_partitions(history, n_groups=3, k_test=3, embargo=0)


def test_n_groups_must_not_exceed_history_length() -> None:
    history = _point_in_time_history(4)
    import pytest

    with pytest.raises(ValueError):
        make_partitions(history, n_groups=5, k_test=1, embargo=0)
