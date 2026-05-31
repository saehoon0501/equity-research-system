"""E2E leaf-wiring test for the walkforward-tuning-loop cycle (task 4.2) — the
conservative DECLINE path (P7), the most important to prove first.

WHAT THIS IS (and is NOT). The markdown orchestrator
(`.claude/commands/walkforward-tune.md`, task 4.1) is LLM-executed control flow —
REVIEWED, not unit-tested (its live path is LLM-in-the-loop, out of scope). This
file is the **leaf-wiring** proof: it composes the REAL leaves
(`read → fit → cpcv → metric → gate → audit`) directly, in the orchestrator's
cycle order (design §"Cycle (sequence)", line 157-170), with a **STUB**
`reactive-replay-harness` `replay_candidate` injected as the orchestrator↔harness
seam. The composition loop below plays the orchestrator's role; replay
correctness itself is the harness spec's test surface, NOT this loop's
(design §"What gets a test", line 300).

THE PATH PROVEN (design §"E2E (the conservative path)", line 312; R5.4 / R8.1):

    seeded firewalled read (conn=None dry-run)
      → fit.assemble_trial_set  (>=2 hashed Candidates)
      → cpcv.make_partitions    (CPCV purge/embargo; each Partition carries a ReplayWindow)
      → STUB replay_candidate    per config + incumbent per partition
      → metric.score             over the returned OutcomeRecords  → OOSSample
      → gate.evaluate_gate       → DECLINE: insufficient_oos (MinTRL not met)
      → publish NEVER called      (incumbent retained — P7)
      → audit.write_audit(conn=None)  → envelope: promoted=False, walk_forward_window=None

THE WIRING OBSERVABLES (task 4.2 "Observable"):
  * `replay_candidate` is called exactly once per (config-or-incumbent, partition)
    = ``(n_configs + 1) * n_partitions`` — "per config per partition";
  * the returned ``OutcomeRecord``s are THREADED into ``metric.score`` (the
    matrix the gate reads is built from the stub's records, nothing else);
  * the gate DECLINES specifically with reason ``insufficient_oos`` and
    ``min_trl_met is False`` (NOT the sibling ``below_benchmark`` /
    ``min_btl_breach`` / ``degenerate_trial_set`` paths — those would be a
    masquerading false pass);
  * the incumbent is RETAINED: ``publish`` is NOT called; the audit row carries
    ``promoted=False`` + a null advanced window.

REAL SHAPES ONLY (the unit-green/integration-broken trap class, tasks.md line 35):
the stub returns the REAL ``src.reactive.replay.types.{OutcomeRecord, Fill,
ReplayResult, FidelityResult}`` frozen dataclasses (9-field ``OutcomeRecord``),
the trial set carries the REAL imported ``Candidate`` + ``ParamSnapshot``, and
the partition windows are the REAL ``ReplayWindow`` — never a dict/fake.

No LLM, MCP, or live DB — pure leaf-wiring (P1, P14 inner ring). ``read`` and
``audit`` run on their ``conn=None`` dry-run paths (no DB).

Requirements: 1.1 (the after-market cycle), 4.1 (CPCV replay of the trial set
via the consumed harness), 5.4 (insufficient OOS ⇒ no-promote), 8.1 (audit
emitted on decline too), 9.1 (each phase persists its artifact).
"""

from __future__ import annotations

import dataclasses as d

import pytest

# --- The REAL consumed contract — IMPORTED, never re-declared (R10.3, P9). ---
from src.calibration.scorer import Label
from src.reactive.params import DEFAULTS as REACTIVE_DEFAULTS, ParamSnapshot
from src.reactive.replay import (
    Candidate,
    FidelityResult,
    Fill,
    OutcomeRecord,
    ReplayResult,
    ReplayWindow,
)

# --- The REAL leaves — composed directly (this file is the orchestrator). ---
from src.skills.walkforward_tune import audit as audit_mod
from src.skills.walkforward_tune.audit import (
    gate_metrics_from_verdict,
    mint_audit_id,
    write_audit,
)
from src.skills.walkforward_tune.cpcv import make_partitions
from src.skills.walkforward_tune.fit import assemble_trial_set
from src.skills.walkforward_tune.gate import evaluate_gate
from src.skills.walkforward_tune.metric import score
from src.skills.walkforward_tune.read import read_firewalled
from src.skills.walkforward_tune.types import (
    GateParams,
    GateVerdict,
    OOSMatrix,
    Partition,
    ReadSet,
    TrialSet,
    TunerActionAudit,
)

RUN_ID = "e2e00000-0000-4000-8000-000000000001"
CODE_VERSION = "wf-code@v0.1"
IS_BOUNDARY = "2024-07-01"


# --------------------------------------------------------------------------- #
# Seeded inputs — real shapes only.                                            #
# --------------------------------------------------------------------------- #


def _outcome(realized_outcome: float, period: str, symbol: str) -> OutcomeRecord:
    """A REAL 9-field ``OutcomeRecord`` — a clean, breach-free HOLD day.

    A flat/HOLD day carries NO fill and NO derived probability (the consumed
    harness's real flat-day shape: ``fills=[]``, ``predicted_probability=None`` —
    src/reactive/replay/outcomes.py). No ``survival_events`` ⇒ no survival
    breach ⇒ ``metric.score`` folds in NO survival penalty, so the per-partition
    survival-net return is the plain risk-adjusted return — a clean positive
    edge whose only failing is too-few observations (the ``insufficient_oos``
    path, NOT ``below_benchmark``).
    """
    return OutcomeRecord(
        period=period,
        symbol=symbol,
        decision="HOLD",
        predicted_probability=None,  # type: ignore[arg-type]  # real flat-day runtime
        fills=[],
        total_return_pnl=realized_outcome,
        survival_events=[],
        realized_outcome=realized_outcome,
        realized_label=Label.HOLD,
    )


# Per-(config-or-incumbent, partition) seeded return panels. Each inner list is
# one OOS partition's day returns: VARIED + POSITIVE so that across partitions
# the survival-net series has mean>0 and std>0 ⇒ sr_hat > benchmark(0) ⇒ a
# FINITE MinTRL ⇒ the gate fails on the floor (insufficient_oos), not on
# below_benchmark. Three panels per series = the three CPCV partitions.
_SEED_RETURNS: dict[str, list[list[float]]] = {
    # config A — a strong, varied positive edge.
    "A": [[0.010, 0.020, 0.015], [0.025, 0.018, 0.030], [0.012, 0.022, 0.017]],
    # config B — also positive, slightly different shape (so the trial set is
    # non-degenerate and the gate's cross-config SR variance is non-zero).
    "B": [[0.008, 0.014, 0.011], [0.019, 0.013, 0.024], [0.009, 0.016, 0.013]],
    # the incumbent champion — a modest positive baseline.
    "__incumbent__": [
        [0.005, 0.007, 0.006],
        [0.006, 0.008, 0.005],
        [0.004, 0.009, 0.006],
    ],
}


def _history() -> list[dict]:
    """A small realized-history index for CPCV (6 obs ⇒ C(3,1)=3 partitions)."""
    return [
        {
            "symbol": "AAPL",
            "event_ts": f"2024-0{1 + i}-01",
            "label_end_ts": f"2024-0{1 + i}-15",
        }
        for i in range(6)
    ]


def _proposed_configs() -> list[dict]:
    """Two valid param-track LLM-proposed configs (the orchestrator's judgment,
    already structured) — a non-trivial trial set the gate can deflate."""
    return [
        {"track": "param", "param_snapshot": d.replace(REACTIVE_DEFAULTS, threshold=0.58)},
        {"track": "param", "param_snapshot": d.replace(REACTIVE_DEFAULTS, threshold=0.62)},
    ]


def _memory() -> dict:
    return {
        "rolling": {"start": "2024-04-01", "end": "2024-06-30"},
        "anchored": {"start": "2003-09-10", "end": "2024-06-30"},
    }


def _incumbent() -> Candidate:
    """The incumbent champion the trial set is assembled against + replayed."""
    return Candidate(
        param_snapshot=REACTIVE_DEFAULTS, survival_parameters=None, code_version=None
    )


def _decline_gate_params() -> GateParams:
    """Gate knobs that force the conservative DECLINE on the insufficient_oos
    path: a MinTRL floor far above what this seeded history supplies (mirrors
    test_gate's ``min_trl=10_000``); ``benchmark_sharpe=0`` so the candidate's
    positive sr_hat clears the benchmark (a FINITE MinTRL, not below_benchmark);
    ``min_btl=1`` so the breadth/history check does not fire first."""
    return GateParams(
        dsr_threshold=0.90,
        psr_threshold=0.90,
        min_trl=10_000,
        pbo_threshold=0.20,
        min_btl=1,
        benchmark_sharpe=0.0,
        oos_margin=0.0,
        consecutive_required=1,
        hysteresis=0.0,
    )


# --------------------------------------------------------------------------- #
# The stub reactive-replay-harness — the orchestrator↔harness seam.            #
# --------------------------------------------------------------------------- #


class StubHarness:
    """A recording stub of the consumed ``replay_candidate(candidate, window)``.

    INJECTED into the composition loop (not monkeypatched onto the harness
    module — no leaf imports ``replay_candidate``; the orchestrator is the only
    caller, so the seam is a direct injection). Records every call as
    ``(series_key, window)`` and returns the seeded ``ReplayResult`` for that
    series×partition with a ``fidelity="pass"`` precondition (so the decline is
    the gate's MinTRL verdict, NOT a fidelity withhold — a different path,
    design line 285)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ReplayWindow]] = []
        # param_version → series key, populated by the loop AFTER fit stamps the
        # content-hash param_versions (an instance attr, never a module global —
        # so two cycles in one test never share routing state).
        self.pv_to_key: dict[str | None, str] = {}

    def bind_series(self, candidates: list[Candidate]) -> None:
        """Map each trial-set candidate's stamped param_version to its seeded
        series key (call once after ``assemble_trial_set``)."""
        for key, cand in zip(("A", "B"), candidates):
            self.pv_to_key[cand.param_snapshot.param_version] = key

    def replay_candidate(
        self, candidate: Candidate, window: ReplayWindow
    ) -> ReplayResult:
        assert isinstance(candidate, Candidate), "stub got a non-Candidate"
        assert isinstance(window, ReplayWindow), "stub got a non-ReplayWindow"
        key = self._series_key(candidate, window)
        # partition index is the order this window appears for this series.
        part_idx = sum(1 for k, _ in self.calls if k == key)
        self.calls.append((key, window))
        returns = _SEED_RETURNS[key][part_idx]
        records = [
            _outcome(r, period=f"{window.start}+{i}", symbol=window.tickers[0])
            for i, r in enumerate(returns)
        ]
        return ReplayResult(
            records=records,
            fidelity=FidelityResult(status="pass", detail="stub: champion reproduced"),
        )

    def _series_key(self, candidate: Candidate, window: ReplayWindow) -> str:
        # The incumbent carries the landed DEFAULTS param_version; the trial-set
        # candidates carry the fit-stamped content hash. Map both to a series key.
        pv = candidate.param_snapshot.param_version if candidate.param_snapshot else None
        if pv == REACTIVE_DEFAULTS.param_version:
            return "__incumbent__"
        return self.pv_to_key[pv]


# --------------------------------------------------------------------------- #
# The composition loop — this file plays the orchestrator (4.1 is markdown).   #
# --------------------------------------------------------------------------- #


class CycleResult:
    """What one composed cycle produced — the artifacts the assertions read."""

    def __init__(self) -> None:
        self.read_set: ReadSet | None = None
        self.trial_set: TrialSet | None = None
        self.partitions: list[Partition] = []
        self.matrix: OOSMatrix | None = None
        self.verdict: GateVerdict | None = None
        self.audit_envelope: dict | None = None
        self.publish_calls: int = 0
        self.score_call_count: int = 0


def _run_cycle(harness: StubHarness, *, gate_params: GateParams) -> CycleResult:
    """Compose the leaves in the orchestrator's cycle order (design line 157-170).

    The ONLY non-leaf piece is the stub ``harness.replay_candidate`` (the
    consumed seam) and the ``publish`` spy (a counter — publish must NOT be
    called on the decline branch; incumbent retained)."""
    out = CycleResult()

    # --- Phase 1: firewall-bounded read (conn=None dry-run — no DB). ---------
    out.read_set = read_firewalled(
        keys={"run_id": RUN_ID, "code_version": CODE_VERSION},
        is_boundary=IS_BOUNDARY,
        conn=None,
    )

    # --- Phase 2: fit the trial set from the LLM-proposed configs. -----------
    incumbent = _incumbent()
    out.trial_set = assemble_trial_set(
        _proposed_configs(), base=incumbent, memory=_memory()
    )
    # Map each stamped param_version → its seeded series key (for the stub) — the
    # content-hash versions are known only after fit runs.
    harness.bind_series(out.trial_set.candidates)

    # --- Phase 3: CPCV partition the realized history. -----------------------
    out.partitions = make_partitions(_history(), n_groups=3, k_test=1, embargo=0)

    # --- Phase 4: call the harness per config + incumbent per partition; -----
    #              thread the returned OutcomeRecords into metric.score.
    series: list[tuple[str, Candidate]] = [
        (c.param_snapshot.param_version, c) for c in out.trial_set.candidates
    ]
    per_config: dict[str, list] = {}
    for pv, cand in series:
        samples = []
        for part in out.partitions:
            result = harness.replay_candidate(cand, part.oos_window)
            samples.append(score(result.records))  # OutcomeRecords → OOSSample
            out.score_call_count += 1
        per_config[pv] = samples

    incumbent_samples = []
    for part in out.partitions:
        result = harness.replay_candidate(incumbent, part.oos_window)
        incumbent_samples.append(score(result.records))
        out.score_call_count += 1

    out.matrix = OOSMatrix(
        per_config=per_config,
        incumbent=incumbent_samples,
        trial_metadata={"effective_n": 2},
    )

    # --- Phase 5: the deterministic gate over the matrix. --------------------
    out.verdict = evaluate_gate(out.matrix, gate_params)

    # --- Phase 6: branch on the verdict (P7: decline ⇒ retain incumbent). ----
    if out.verdict.promote:
        # Promote branch (NOT exercised here) — would call publish + advance the
        # boundary. The spy increments so a mis-wired promote would be caught.
        out.publish_calls += 1
        advanced_window = IS_BOUNDARY  # would be the advanced boundary
    else:
        # Decline branch: publish is NOT called; the incumbent is retained.
        advanced_window = None

    # --- Phase 7: emit the audit on BOTH promote and decline (R8.1; dry-run).
    selected_pv = out.verdict.selected_config or "none"
    audit = TunerActionAudit(
        audit_id=mint_audit_id(run_id=RUN_ID),
        run_id=RUN_ID,
        code_version=CODE_VERSION,
        param_version=selected_pv,
        walk_forward_window=advanced_window,  # None on decline (mig-053: null until promoted)
        promoted=out.verdict.promote,
        track="param",
        gate_metrics=gate_metrics_from_verdict(out.verdict),
        hypothesis={
            "statement": (
                "No candidate cleared the gate this cycle; the incumbent is "
                "retained because the OOS evidence was statistically insufficient "
                "(MinTRL not met)."
            ),
            "falsifiers": [
                "next cycle's OOS observation count clears MinTRL for a candidate",
                "a candidate's deflated Sharpe clears the threshold next cycle",
            ],
        },
    )
    out.audit_envelope = write_audit(audit, conn=None)  # dry-run: envelope, no DB row
    return out


# --------------------------------------------------------------------------- #
# Fixtures.                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _redirect_envelope_dir(tmp_path, monkeypatch):
    """The audit envelope write is UNCONDITIONAL (even dry-run), so redirect the
    audit module's repo-root seam to a tmp dir — the E2E never touches the shared
    repo ``memos/envelopes/`` (the test_audit fixture pattern)."""
    monkeypatch.setattr(audit_mod, "_REPO_ROOT", tmp_path)
    return tmp_path


@pytest.fixture()
def cycle(_redirect_envelope_dir) -> CycleResult:
    """Run one composed decline cycle and hand the artifacts to the assertions."""
    return _run_cycle(StubHarness(), gate_params=_decline_gate_params())


# --------------------------------------------------------------------------- #
# Assertions — the decline → insufficient_oos → incumbent-retained path.       #
# --------------------------------------------------------------------------- #


def test_phases_produce_the_real_owned_shapes(cycle: CycleResult) -> None:
    """Each leaf produced its owned shape — the wiring threads real types end to
    end (not dicts/fakes)."""
    assert isinstance(cycle.read_set, ReadSet)
    assert isinstance(cycle.trial_set, TrialSet)
    assert len(cycle.trial_set.candidates) >= 2  # non-trivial trial set (R3.4)
    assert all(isinstance(c, Candidate) for c in cycle.trial_set.candidates)
    assert all(isinstance(p, Partition) for p in cycle.partitions)
    assert all(isinstance(p.oos_window, ReplayWindow) for p in cycle.partitions)
    assert isinstance(cycle.matrix, OOSMatrix)
    assert isinstance(cycle.verdict, GateVerdict)


def test_replay_called_per_config_and_incumbent_per_partition() -> None:
    """The orchestrator↔harness wiring: ``replay_candidate`` is called exactly
    once per (config-or-incumbent, partition) = ``(n_configs + 1) * n_part``
    (design line 162: "per config + incumbent per partition")."""
    harness = StubHarness()
    out = _run_cycle(harness, gate_params=_decline_gate_params())

    n_configs = len(out.trial_set.candidates)
    n_part = len(out.partitions)
    expected = (n_configs + 1) * n_part  # +1 for the incumbent series
    assert len(harness.calls) == expected
    assert expected == 9  # 2 configs + 1 incumbent, 3 CPCV partitions

    # Each call's window is one of the CPCV partition windows (the loop hands the
    # harness the OOS span of each Partition, not an arbitrary window).
    # ReplayWindow carries a list field (``tickers``) so it is unhashable —
    # compare by a hashable identity tuple.
    def _wkey(w: ReplayWindow) -> tuple:
        return (w.start, w.end, tuple(w.tickers))

    partition_windows = {_wkey(p.oos_window) for p in out.partitions}
    assert {_wkey(w) for _, w in harness.calls} == partition_windows

    # Every series (both configs + the incumbent) was replayed over every
    # partition exactly once.
    from collections import Counter

    per_series = Counter(k for k, _ in harness.calls)
    assert set(per_series) == {"A", "B", "__incumbent__"}
    assert all(c == n_part for c in per_series.values())


def test_outcome_records_are_threaded_into_metric(cycle: CycleResult) -> None:
    """The returned ``OutcomeRecord``s are threaded into ``metric.score`` — the
    matrix the gate reads is built from the stub's records (one ``score`` call,
    hence one ``OOSSample``, per replay call)."""
    n_configs = len(cycle.trial_set.candidates)
    n_part = len(cycle.partitions)
    # one score() per (config-or-incumbent, partition).
    assert cycle.score_call_count == (n_configs + 1) * n_part
    # the matrix carries one OOSSample series per trial-set config + the incumbent.
    assert len(cycle.matrix.per_config) == n_configs
    assert all(len(s) == n_part for s in cycle.matrix.per_config.values())
    assert len(cycle.matrix.incumbent) == n_part
    # the samples are the metric's owned OOSSample (the metric→gate seam), and
    # the seeded positive edge produced positive survival-net returns (no breach
    # penalty folded in — a clean edge that only fails on too-few observations).
    for series in cycle.matrix.per_config.values():
        for sample in series:
            assert sample.n_obs == 3  # the seeded per-partition day count
            assert sample.survival_net_return > 0.0


def test_gate_declines_specifically_on_insufficient_oos(cycle: CycleResult) -> None:
    """THE crux: the gate declines on the ``insufficient_oos`` (MinTRL-not-met)
    path — NOT the sibling ``below_benchmark`` / ``min_btl_breach`` /
    ``degenerate_trial_set`` paths, which would be a masquerading false pass."""
    v = cycle.verdict
    assert v.promote is False  # conservative: no promotion (P7)
    assert v.min_trl_met is False  # MinTRL sufficiency NOT met (R5.4)
    assert v.selected_config is not None  # a best WAS selected; it just didn't clear

    reasons = " ".join(v.reasons).lower()
    assert "insufficient_oos" in reasons, f"expected insufficient_oos, got: {v.reasons}"
    # Discriminate from the neighboring decline paths the seeding must avoid.
    assert "below_benchmark" not in reasons, v.reasons
    assert "min_btl" not in reasons, v.reasons
    assert "degenerate" not in reasons, v.reasons


def test_incumbent_retained_publish_not_called(cycle: CycleResult) -> None:
    """Incumbent retained (P7): on the decline branch ``publish`` is NOT called
    and no IS boundary is advanced."""
    assert cycle.verdict.promote is False
    assert cycle.publish_calls == 0  # publish spy never fired


def test_audit_emitted_on_decline_with_null_advanced_window(
    cycle: CycleResult,
) -> None:
    """The audit is emitted on the DECLINE too (R8.1), carrying ``promoted=False``,
    a NULL advanced window (mig-053: null until promoted), the four correlation
    keys, derived gate metrics (P15), and the falsifiable hypothesis."""
    env = cycle.audit_envelope
    assert env is not None
    assert env["promoted"] is False
    assert env["walk_forward_window"] is None  # decline advances no boundary

    # The four correlation keys (R8.3) — joinable to decision_process_trace.
    assert env["run_id"] == RUN_ID
    assert env["code_version"] == CODE_VERSION
    assert env["param_version"] == cycle.verdict.selected_config  # the selected best
    # (walk_forward_window is the 4th key, asserted null above.)

    # Derived gate metrics (P15) — projected from the verdict, not asserted.
    gm = env["gate_metrics"]
    for k in ("dsr", "psr", "min_trl_met", "pbo", "effective_n", "lexicographic_ok"):
        assert k in gm, f"gate_metrics missing derived key {k}"
    assert gm["min_trl_met"] is False  # the derived metrics mirror the decline

    # The falsifiable hypothesis (P15) — a structured statement + observable
    # falsifiers, not a bare string.
    hyp = env["hypothesis"]
    assert isinstance(hyp["statement"], str) and hyp["statement"]
    assert isinstance(hyp["falsifiers"], list) and len(hyp["falsifiers"]) >= 1

    # Dry-run: the envelope was written but NO DB row (conn=None).
    assert env["written"] == 0


def test_audit_envelope_persisted_to_disk(
    cycle: CycleResult, tmp_path
) -> None:
    """The cross-stage artifact (P4) lands on disk under the run_id — each phase
    persists its artifact for resume (R9.1). The redirect fixture points the
    audit repo-root at ``tmp_path``."""
    envelope_file = tmp_path / "memos" / "envelopes" / f"walkforward-tune__{RUN_ID}.json"
    assert envelope_file.exists()

    import json

    on_disk = json.loads(envelope_file.read_text())
    assert on_disk["promoted"] is False
    assert on_disk["walk_forward_window"] is None
    assert on_disk["run_id"] == RUN_ID
    # the on-disk envelope does NOT carry the operational "written" flag (that is
    # only on the in-memory return, per the audit leaf's contract).
    assert "written" not in on_disk


def test_cycle_is_deterministic() -> None:
    """Identical seeded inputs ⇒ identical verdict (R9.1 determinism) — two runs
    of the composed cycle produce the same gate verdict."""
    v1 = _run_cycle(StubHarness(), gate_params=_decline_gate_params()).verdict
    v2 = _run_cycle(StubHarness(), gate_params=_decline_gate_params()).verdict
    assert v1 == v2  # frozen dataclass equality
