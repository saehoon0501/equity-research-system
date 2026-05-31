"""CPCV partition scheme (task 2.1) — the leakage-firewall realization.

``make_partitions(history, n_groups, k_test, embargo) -> list[Partition]``
produces **combinatorial purged cross-validation** splits (López de Prado,
*Advances in Financial Machine Learning*, ch. 7 — Combinatorial Purged
Cross-Validation; §7.4 purging, §7.4.1 embargo). Each split designates
``k_test`` of ``n_groups`` contiguous, time-ordered blocks as out-of-sample and
the rest as in-sample, then enforces the firewall on the in-sample set by
**purging** label-overlapping observations and **embargoing** the observations
immediately following each contiguous test block. There are
``C(n_groups, k_test)`` such splits.

This is the firewall realization for R2.2/2.3 and R4.1 (design §"Boundary
Commitments → This Spec Owns: the leakage firewall as CPCV purge/embargo";
§"Evaluation Leaves → cpcv"). It is the *only* leakage barrier for the loop —
no live-forward hold-out exists (the architecture is in-process CPCV replay, per
the design's 2026-05-30 operator decision).

**Firewall is enforced at the INDEX level, not the window level.** For
``k_test > 1`` the chosen test groups may be non-adjacent (e.g. {0, 2}). A
``Partition`` carries a *single* ``ReplayWindow`` (the shared harness window
type — design seam note, design.md line 205), which cannot express two disjoint
intervals, so ``oos_window`` is the **hull** ``[min OOS start, max OOS end]``.
The hull can span an interior training group; that is acceptable because the
firewall guarantee — *no OOS observation appears in the matching IS set* — is
asserted on ``is_indices`` / ``oos_indices`` (the index sets the metric/replay
actually consume per observation), never inferred from the window.

**Seam caution — ``oos_window`` is a data-fetch bound, NOT the scored set
(cpcv -> replay -> metric, R4.1/4.2/2.2).** The orchestrator hands ``oos_window``
to ``replay_candidate`` as the replay *span* (the harness imposes no CV scheme;
it replays the window it is given). But for ``k_test > 1`` with non-adjacent
test groups the hull covers interior training days the candidate was fit on; if
``metric.score`` scored *every* returned ``OutcomeRecord`` those interior days
would re-enter as spurious OOS performance (scoring-side leakage the index-level
firewall does not see). Therefore **``oos_indices`` (and the periods they map
to) are authoritative for scoring; the window is only the fetch bound** —
downstream MUST restrict metric scoring to the OOS observations' periods, not
trust the window. (For ``k_test == 1`` the OOS is one contiguous block, the hull
is exact, there is no interior gap — the validated path.)

History element shape (LOCAL to this leaf — deliberately NOT added to the
``types`` barrier, which is out of boundary for this task): each observation is
a mapping with three keys, matching the natural upstream ``ReadSet.trace_rows``
(``list[dict[str, Any]]``):

  - ``symbol``        — the traded name (→ the OOS ``ReplayWindow.tickers``).
  - ``event_ts``      — the feature/decision instant, ISO-sortable
                        (→ the OOS window ``start``; the purge/embargo span
                        anchor).
  - ``label_end_ts``  — the label-span end, ISO-sortable. A point-in-time label
                        sets it equal to ``event_ts`` (purge then a no-op); a
                        multi-period label sets it later, and an in-sample obs
                        whose ``[event_ts, label_end_ts]`` span overlaps a test
                        block's span is purged (the §7.4 label-overlap rule).

``embargo`` is an explicit **integer count of observations** to drop after each
contiguous test block's tail (LdP states it as a fraction of observations; a
passed integer count is clearer and directly testable, and keeps this leaf pure
of any global-history-length coupling). ``embargo=0`` disables it.

Pure leaf (P1, P14 inner-ring): stdlib only — ``itertools``, ``math``. No
``numpy``/``scipy``, no I/O, no LLM, no DB. Deterministic: identical inputs
yield an identical ``list[Partition]`` (the enumeration order of
``itertools.combinations`` over a sorted group index is stable). Strict
dependency direction (design §"Dependency direction"): imports ``types`` only;
no other-leaf import, no consumer-spec import.

Requirements: 2.2 (no OOS partition observation enters the IS fit — purge +
embargo of overlapping observations), 2.3 (timestamp attribution defines the
purge/embargo span), 4.1 (CPCV partitions of realized history, one OOS series
per partition).
"""

from __future__ import annotations

import itertools
from typing import Any, Mapping, Sequence

from src.reactive.replay import ReplayWindow
from src.skills.walkforward_tune.types import Partition


def _contiguous_blocks(n_obs: int, n_groups: int) -> list[list[int]]:
    """Split ``range(n_obs)`` into ``n_groups`` contiguous, time-ordered blocks.

    Sizes are balanced (the first ``n_obs % n_groups`` blocks get one extra
    observation), so every block is non-empty as long as
    ``n_groups <= n_obs`` (guarded by the caller). The blocks tile
    ``range(n_obs)`` with no gaps and no overlap — the index basis the
    combinations are taken over.
    """
    base, extra = divmod(n_obs, n_groups)
    blocks: list[list[int]] = []
    start = 0
    for g in range(n_groups):
        size = base + (1 if g < extra else 0)
        blocks.append(list(range(start, start + size)))
        start += size
    return blocks


def _coalesce_adjacent(group_ids: tuple[int, ...]) -> list[list[int]]:
    """Coalesce a sorted set of test-group ids into maximal contiguous runs.

    Embargo follows each *contiguous test block* (design §"Evaluation Leaves";
    LdP §7.4.1), so adjacent chosen groups (e.g. {0, 1}) form ONE block and get
    ONE embargo after the coalesced tail, while non-adjacent groups (e.g.
    {0, 2}) form two blocks each with its own embargo. Returns a list of
    group-id runs, e.g. ``(0, 1, 3)`` -> ``[[0, 1], [3]]``.
    """
    runs: list[list[int]] = []
    for gid in sorted(group_ids):
        if runs and gid == runs[-1][-1] + 1:
            runs[-1].append(gid)
        else:
            runs.append([gid])
    return runs


def _overlaps(
    a_start: str, a_end: str, b_start: str, b_end: str
) -> bool:
    """Closed-interval overlap test on ISO-sortable strings.

    ``[a_start, a_end]`` overlaps ``[b_start, b_end]`` iff ``a_start <= b_end``
    and ``b_start <= a_end``. ISO timestamps compare correctly as strings.
    """
    return a_start <= b_end and b_start <= a_end


def make_partitions(
    history: Sequence[Mapping[str, Any]],
    n_groups: int,
    k_test: int,
    embargo: int,
) -> list[Partition]:
    """Build the combinatorial purged CV partitions over ``history``.

    See the module docstring for the ``history`` element shape, the hull-window
    rule, the index-level firewall guarantee, and the ``embargo`` unit.

    Args:
      history: time-ordered observations (each a mapping with ``symbol`` /
        ``event_ts`` / ``label_end_ts``). Order is the index basis; not mutated.
      n_groups: number of contiguous CPCV blocks (``2 <= n_groups <= len``).
      k_test: blocks designated out-of-sample per split (``1 <= k_test <
        n_groups`` — ``k_test == n_groups`` would leave no training data).
      embargo: integer count of observations to drop after each contiguous test
        block's tail (``>= 0``; ``0`` disables embargo).

    Returns:
      One ``Partition`` per ``C(n_groups, k_test)`` combination, ``partition_id``
      = enumeration index. Each carries its post-purge/embargo ``is_indices``,
      its ``oos_indices``, and the hull ``oos_window`` (a consumed
      ``ReplayWindow``).

    Raises:
      ValueError: on a degenerate request (``n_groups`` out of range,
        ``k_test`` not in ``[1, n_groups)``, ``embargo`` negative, or empty
        history) — fail toward not producing a leaky/degenerate split (P7).
    """
    n_obs = len(history)
    if n_obs == 0:
        raise ValueError("history is empty")
    if n_groups < 2:
        raise ValueError(f"n_groups must be >= 2, got {n_groups}")
    if n_groups > n_obs:
        raise ValueError(
            f"n_groups ({n_groups}) must not exceed history length ({n_obs})"
        )
    if k_test < 1 or k_test >= n_groups:
        raise ValueError(
            f"k_test must satisfy 1 <= k_test < n_groups; "
            f"got k_test={k_test}, n_groups={n_groups}"
        )
    if embargo < 0:
        raise ValueError(f"embargo must be >= 0, got {embargo}")

    blocks = _contiguous_blocks(n_obs, n_groups)

    partitions: list[Partition] = []
    for partition_id, test_group_ids in enumerate(
        itertools.combinations(range(n_groups), k_test)
    ):
        oos_indices = sorted(
            idx for gid in test_group_ids for idx in blocks[gid]
        )
        oos_set = set(oos_indices)

        # The contiguous test blocks (coalesce adjacent chosen groups) — both
        # the purge label-overlap spans AND the embargo tails derive from these.
        test_runs = _coalesce_adjacent(test_group_ids)
        test_index_blocks: list[list[int]] = [
            [idx for gid in run for idx in blocks[gid]] for run in test_runs
        ]

        # Each test block's time span [min event_ts, max label_end_ts] — the
        # purge reference (an IS obs overlapping any of these is dropped).
        test_spans: list[tuple[str, str]] = []
        embargoed: set[int] = set()
        for block in test_index_blocks:
            span_start = min(history[i]["event_ts"] for i in block)
            span_end = max(history[i]["label_end_ts"] for i in block)
            test_spans.append((span_start, span_end))
            # Embargo: the `embargo` observations immediately after the block's
            # tail (by index — the time-ordered next observations).
            tail = block[-1]
            for off in range(1, embargo + 1):
                nxt = tail + off
                if nxt < n_obs:
                    embargoed.add(nxt)

        is_indices: list[int] = []
        for i in range(n_obs):
            if i in oos_set:
                continue
            if i in embargoed:
                continue
            # Purge: drop an IS obs whose label span overlaps any test span.
            obs_start = history[i]["event_ts"]
            obs_end = history[i]["label_end_ts"]
            if any(
                _overlaps(obs_start, obs_end, ts_start, ts_end)
                for ts_start, ts_end in test_spans
            ):
                continue
            is_indices.append(i)

        # The OOS hull window: [min start, max end] over the OOS observations,
        # tickers = the OOS symbols (sorted for determinism). end uses
        # label_end_ts so the realized label horizon is not truncated.
        oos_start = min(history[i]["event_ts"] for i in oos_indices)
        oos_end = max(
            max(history[i]["event_ts"], history[i]["label_end_ts"])
            for i in oos_indices
        )
        tickers = sorted({history[i]["symbol"] for i in oos_indices})

        partitions.append(
            Partition(
                partition_id=partition_id,
                is_indices=is_indices,
                oos_indices=oos_indices,
                oos_window=ReplayWindow(
                    start=oos_start, end=oos_end, tickers=tickers
                ),
            )
        )

    return partitions
