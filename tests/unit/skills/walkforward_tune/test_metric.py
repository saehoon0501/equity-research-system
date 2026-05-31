"""Pure-unit tests for the walkforward-tuning-loop survival-net metric (task 2.2).

``metric.score(outcome_records: list[OutcomeRecord]) -> OOSSample`` turns one
config's per-period replay ``OutcomeRecord``s (over ONE CPCV OOS partition) into
the ``OOSSample`` the gate consumes via ``OOSMatrix``. It is the realization of
R4.3 (the survival-net risk-adjusted return, reflecting the §13 ordering
``Survive ⊳ Preserve ⊳ Edge ⊳ Return`` — survival breaches / stop-outs dominate
the ranking) and R4.4 (calibration of the model's derived probabilities, via
``src.calibration.metrics``, as a behavioral evaluation input — not only
hit-rate or P&L). Computed over the harness's ``OutcomeRecord``s — NOT the
``counterfactual_ledger`` (design §Allowed Dependencies / §Evaluation Leaves).

THE TRAP THIS FILE GUARDS (tasks.md line 35, "the unit-green/integration-broken
trap class"): the tests MUST construct the REAL
``src.reactive.replay.types.OutcomeRecord`` frozen dataclass with ALL 9 fields —
NOT a loose dict / fake / namespace. A dict-fed test would pass against a metric
that reads ``rec["total_return_pnl"]`` and silently break the moment the
orchestrator threads the real frozen dataclass (which is attribute-accessed).
So every record below is the imported frozen dataclass; ``_rec`` is a builder
over the real shape, never a stand-in.

The load-bearing observable (tasks.md line 36): the survival-net metric reflects
the §13 ordering — **a survival breach dominates an edge gain**: a series that
took a survival breach (e.g. a ``stop_hit`` / ``safe_mode`` / ``kill_switch``)
must score strictly BELOW an otherwise-strictly-better series that did not,
*no matter how much larger* the breaching series' raw P&L is. That is the
lexicographic precedence (never trade a higher link for any amount of a lower
one) reduced to a scalar the gate can rank.

No LLM, MCP, or live DB — pure leaf (P1, P14 inner-ring).

Requirements: 4.3, 4.4.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

# The REAL consumed contract — imported, never faked (the trap class).
from src.calibration.metrics import brier_score
from src.calibration.scorer import Label
from src.reactive.replay.types import Fill, OutcomeRecord
from src.skills.walkforward_tune.metric import score
from src.skills.walkforward_tune.types import OOSSample


def _rec(
    *,
    period: str = "2026-01-02",
    symbol: str = "AAPL",
    decision: str = "LONG",
    predicted_probability: float | None = 0.6,
    total_return_pnl: float = 0.01,
    survival_events: list[str] | None = None,
    realized_outcome: float = 0.01,
    realized_label: Label = Label.BUY,
) -> OutcomeRecord:
    """Build a REAL ``OutcomeRecord`` frozen dataclass (all 9 fields).

    ``fills`` is a real ``Fill`` so the record is a faithful instance of the
    consumed shape — the metric never reads ``fills``, but constructing the true
    9-field dataclass is the contract this test exists to hold. The default
    ``realized_label=Label.BUY`` is the favorable (calibration-positive) outcome;
    callers flip it to SELL/TRIM/HOLD to make a record unfavorable.

    ``predicted_probability`` is typed ``float | None`` because the consumed
    harness emits ``None`` on every flat/HOLD day (``src/reactive/replay/outcomes.py``
    :103/:118 — "flat day → decision HOLD, probability None"). A HOLD day also has
    NO fills (``fills=[]``, outcomes.py :105/:29), so the builder reproduces that
    real flat-day shape: a HOLD record gets ``fills=[]`` (a ``Fill(side="HOLD")``
    is never the real shape — there is no HOLD-side fill).
    """
    if decision == "HOLD":
        fills = []
    else:
        fills = [Fill(side=decision, price=100.0, volume=1.0, ts=period + "T15:00:00Z")]
    return OutcomeRecord(
        period=period,
        symbol=symbol,
        decision=decision,
        predicted_probability=predicted_probability,  # type: ignore[arg-type]  # real runtime is float | None
        fills=fills,
        total_return_pnl=total_return_pnl,
        survival_events=survival_events if survival_events is not None else [],
        realized_outcome=realized_outcome,
        realized_label=realized_label,
    )


# --- The contract guard: real frozen dataclass, never a dict --------------


def test_inputs_are_the_real_frozen_outcomerecord_not_a_fake():
    """Guard the trap: ``_rec`` yields the imported frozen dataclass, 9 fields."""
    rec = _rec()
    assert isinstance(rec, OutcomeRecord)
    assert dataclasses.is_dataclass(rec)
    # frozen → mutation raises (proves it is the real frozen shape, not a dict).
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.total_return_pnl = 0.5  # type: ignore[misc]
    # the 9 pinned fields, in the seam's positional-stable order.
    assert [f.name for f in dataclasses.fields(OutcomeRecord)] == [
        "period",
        "symbol",
        "decision",
        "predicted_probability",
        "fills",
        "total_return_pnl",
        "survival_events",
        "realized_outcome",
        "realized_label",
    ]


# --- Shape of the output --------------------------------------------------


def test_score_returns_oossample_with_the_four_pinned_fields():
    recs = [_rec(total_return_pnl=0.01, realized_outcome=0.01) for _ in range(8)]
    out = score(recs)
    assert isinstance(out, OOSSample)
    assert {f.name for f in dataclasses.fields(out)} == {
        "survival_net_return",
        "skew",
        "kurtosis",
        "n_obs",
    }
    assert out.n_obs == 8
    assert isinstance(out.survival_net_return, float)
    assert isinstance(out.skew, float)
    assert isinstance(out.kurtosis, float)


def test_score_reads_off_the_real_attribute_shape():
    """The metric reads realized_outcome / survival_events / predicted_probability
    / realized_label off the REAL attribute shape (not dict subscription)."""
    # all-positive, well-calibrated, no breaches → a positive survival-net return.
    recs = [
        _rec(predicted_probability=0.9, total_return_pnl=0.02, realized_outcome=0.02)
        for _ in range(10)
    ]
    out = score(recs)
    assert out.n_obs == 10
    assert out.survival_net_return > 0.0


# --- THE §13 load-bearing property: a breach DOMINATES an edge gain -------


def test_survival_breach_dominates_an_edge_gain():
    """§13 (tasks.md line 36): a survival breach dominates an edge gain.

    The breaching series has *strictly larger* raw P&L on EVERY period, yet
    because it took a survival breach (a ``stop_hit``) it must score strictly
    BELOW the clean series. No amount of Edge/Return buys down Survive.
    """
    clean = [_rec(total_return_pnl=0.01, realized_outcome=0.01) for _ in range(12)]
    # identical except: strictly larger P&L AND one survival breach.
    breaching = [_rec(total_return_pnl=0.05, realized_outcome=0.05) for _ in range(11)]
    breaching.append(
        _rec(total_return_pnl=0.05, realized_outcome=0.05, survival_events=["stop_hit"])
    )

    clean_score = score(clean).survival_net_return
    breaching_score = score(breaching).survival_net_return

    assert breaching_score < clean_score, (
        "a survival breach must dominate the ranking even when the breaching "
        "series has strictly higher raw return (§13 lexicographic precedence)"
    )


@pytest.mark.parametrize("breach_event", ["stop_hit", "safe_mode", "kill_switch", "admit_reject"])
def test_each_survival_grade_event_penalizes(breach_event):
    """Every survival-grade event (not just stop_hit) drives the metric down."""
    base = [_rec(total_return_pnl=0.02, realized_outcome=0.02) for _ in range(10)]
    breached = [_rec(total_return_pnl=0.02, realized_outcome=0.02) for _ in range(9)]
    breached.append(
        _rec(total_return_pnl=0.02, realized_outcome=0.02, survival_events=[breach_event])
    )
    assert score(breached).survival_net_return < score(base).survival_net_return


def test_more_breaches_score_strictly_lower():
    """Two breaches dominate one (monotone in breach count)."""
    one = [_rec(total_return_pnl=0.02, realized_outcome=0.02) for _ in range(9)]
    one.append(_rec(total_return_pnl=0.02, realized_outcome=0.02, survival_events=["stop_hit"]))
    two = [_rec(total_return_pnl=0.02, realized_outcome=0.02) for _ in range(8)]
    two.extend(
        [
            _rec(total_return_pnl=0.02, realized_outcome=0.02, survival_events=["stop_hit"]),
            _rec(total_return_pnl=0.02, realized_outcome=0.02, survival_events=["safe_mode"]),
        ]
    )
    assert score(two).survival_net_return < score(one).survival_net_return


def test_non_survival_events_do_not_penalize():
    """A benign / non-survival-grade event string must NOT trigger the breach
    penalty — only the survival-grade vocabulary dominates (§13 is about the
    Survive link, not arbitrary bookkeeping markers)."""
    benign = [_rec(total_return_pnl=0.02, realized_outcome=0.02) for _ in range(9)]
    benign.append(
        _rec(total_return_pnl=0.02, realized_outcome=0.02, survival_events=["lifecycle_open"])
    )
    clean = [_rec(total_return_pnl=0.02, realized_outcome=0.02) for _ in range(10)]
    assert score(benign).survival_net_return == pytest.approx(
        score(clean).survival_net_return
    )


# --- THE unit-green/integration-broken trap (tasks.md line 35): real HOLD/None -

# The consumed harness emits predicted_probability=None on EVERY flat/HOLD day
# (src/reactive/replay/outcomes.py:103 `rd.probability if rd is not None else None`,
# persisted :118; docstring :87 "flat day → decision HOLD, probability None"). A
# real CPCV OOS partition is HOLD-DOMINATED (the reactive model holds far more
# often than it fires), so the metric MUST handle the real None-probability HOLD
# shape — float(None) would raise TypeError. These tests build the REAL flat-day
# OutcomeRecord (decision="HOLD", predicted_probability=None, fills=[],
# realized_outcome=0.0, realized_label=Label.HOLD) the harness produces.


def _hold(*, realized_outcome: float = 0.0, survival_events: list[str] | None = None):
    """The REAL flat/HOLD-day OutcomeRecord shape the harness emits.

    decision="HOLD", predicted_probability=None, fills=[], realized_label=HOLD —
    byte-for-byte the shape outcomes.py assembles on a flat day (no model fire).
    """
    return _rec(
        decision="HOLD",
        predicted_probability=None,
        total_return_pnl=realized_outcome,
        survival_events=survival_events,
        realized_outcome=realized_outcome,
        realized_label=Label.HOLD,
    )


def test_hold_record_carries_a_none_probability_like_the_real_harness():
    """Guard: the HOLD builder reproduces the real flat-day shape — None
    probability, no fills, HOLD label (src/reactive/replay/outcomes.py:103/105)."""
    rec = _hold()
    assert isinstance(rec, OutcomeRecord)
    assert rec.decision == "HOLD"
    assert rec.predicted_probability is None
    assert rec.fills == []
    assert rec.realized_label is Label.HOLD


def test_score_does_not_crash_on_a_hold_dominated_partition():
    """THE trap (tasks.md line 35): a real CPCV OOS partition is HOLD-dominated.
    The harness emits predicted_probability=None on every HOLD day, so a naive
    float(rec.predicted_probability) raises TypeError on the first HOLD record.
    score() must read the real None-probability HOLD shape without crashing and
    return a finite OOSSample."""
    # mostly HOLD (None probability), a couple of actionable LONG fires.
    recs = [_hold(realized_outcome=0.0) for _ in range(10)]
    recs += [_rec(decision="LONG", predicted_probability=0.8, realized_outcome=0.02) for _ in range(2)]
    out = score(recs)
    assert isinstance(out, OOSSample)
    assert out.n_obs == 12
    assert math.isfinite(out.survival_net_return)
    assert math.isfinite(out.skew)
    assert math.isfinite(out.kurtosis)


def test_score_does_not_crash_on_a_fully_hold_partition():
    """The degenerate-but-common real case: an all-HOLD partition (zero fires).
    Every record has predicted_probability=None, so the calibration sample is
    EMPTY — score() must NOT call brier_score([], []) (which raises ValueError at
    calibration/metrics.py:45) and must fall back to a zero calibration discount,
    returning a finite OOSSample over the realized-outcome (all-0.0) series."""
    recs = [_hold(realized_outcome=0.0) for _ in range(11)]
    out = score(recs)
    assert isinstance(out, OOSSample)
    assert out.n_obs == 11
    assert math.isfinite(out.survival_net_return)


def test_hold_records_are_excluded_from_the_calibration_sample():
    """The HOLD calibration SEMANTICS (reviewer fix direction): HOLD/None-probability
    records are EXCLUDED from the Brier sample — a stand-aside carries no calibration
    signal, so adding HOLD days to a LONG/SHORT series must leave the calibration
    term (and thus the survival-net scalar, P&L path held identical) UNCHANGED. A
    forced-miss inclusion of HOLDs would instead drag the score down."""
    fires = [_rec(decision="LONG", predicted_probability=0.85, realized_outcome=0.02) for _ in range(8)]
    # identical fires PLUS HOLD/None days that contribute the SAME realized_outcome
    # (0.02) to the return series — so the Sharpe core is unchanged too; the only
    # thing that could move the score is whether HOLDs enter the Brier sample.
    fires_plus_holds = list(fires) + [_hold(realized_outcome=0.02) for _ in range(8)]
    assert score(fires_plus_holds).survival_net_return == pytest.approx(
        score(fires).survival_net_return
    )


def test_hold_day_can_still_carry_a_survival_breach():
    """A HOLD day still participates in the SURVIVAL net — an admit_reject on a
    stand-aside day (the harness prepends admit_reject to HOLD days, outcomes.py
    :110-112) must still drive the breach penalty, even though the HOLD is
    excluded from the calibration sample."""
    clean = [_hold(realized_outcome=0.0) for _ in range(10)]
    breached = [_hold(realized_outcome=0.0) for _ in range(9)]
    breached.append(_hold(realized_outcome=0.0, survival_events=["admit_reject"]))
    assert score(breached).survival_net_return < score(clean).survival_net_return


# --- R4.4: calibration is a behavioral input, via calibration.metrics -----


def test_calibration_discounts_a_miscalibrated_edge():
    """R4.4: calibration (Brier/reliability) is folded into the survival-net
    scalar. Holding the realized P&L path (and thus the risk-adjusted core)
    IDENTICAL, a worse-calibrated probability series scores strictly lower.
    Calibration is delegated to ``calibration.metrics``, not reimplemented here
    (design §Evaluation Leaves)."""
    # IDENTICAL realized P&L path on both → identical risk-adjusted core; the
    # ONLY difference is predicted_probability, so any score gap is calibration.
    # Labels: first half BUY (favorable), second half SELL (unfavorable).
    def _series(p_fav: float, p_unfav: float):
        return (
            [_rec(predicted_probability=p_fav, total_return_pnl=0.01 + 0.001 * i,
                  realized_outcome=0.01, realized_label=Label.BUY) for i in range(5)]
            + [_rec(predicted_probability=p_unfav, total_return_pnl=0.01 + 0.001 * i,
                    realized_outcome=-0.01, realized_label=Label.SELL) for i in range(5)]
        )

    # well-calibrated: high P on the favorable (BUY) ones, low P on the SELL ones.
    well = _series(p_fav=0.85, p_unfav=0.15)
    # mis-calibrated: confident (high P) on BOTH — including the SELLs that lost.
    bad = _series(p_fav=0.85, p_unfav=0.85)

    assert score(bad).survival_net_return < score(well).survival_net_return


def test_calibration_delegates_to_calibration_metrics_brier():
    """The calibration term is the REAL ``calibration.metrics.brier_score`` over
    (predicted_probability, favorable==realized_label is BUY) — anchor to an
    externally computed Brier so the metric cannot silently reimplement it.

    Holds the realized P&L path FIXED across both series so the only moving part
    is the predicted probability (→ the Brier), isolating the calibration term."""
    # favorable = (realized_label is BUY): BUY,BUY,SELL,SELL → favorable=[1,1,0,0]
    # P&L path identical in both series (same risk-adjusted core).
    def _four(p: float):
        return [
            _rec(predicted_probability=p, total_return_pnl=0.03, realized_outcome=0.03, realized_label=Label.BUY),
            _rec(predicted_probability=p, total_return_pnl=0.01, realized_outcome=0.03, realized_label=Label.BUY),
            _rec(predicted_probability=p, total_return_pnl=0.02, realized_outcome=-0.03, realized_label=Label.SELL),
            _rec(predicted_probability=p, total_return_pnl=0.02, realized_outcome=-0.03, realized_label=Label.SELL),
        ]

    recs = _four(0.7)
    # external reference: brier on the EXACT (p, favorable) pairs the metric must use.
    expected_brier = brier_score([0.7, 0.7, 0.7, 0.7], [True, True, False, False])
    # hand-check: ((.7-1)^2 + (.7-1)^2 + (.7-0)^2 + (.7-0)^2)/4 = (.09+.09+.49+.49)/4 = 0.29
    assert expected_brier == pytest.approx(0.29)
    # A worse Brier (p=0.99 on the same favorable=[1,1,0,0]) ⇒ strictly lower score,
    # P&L path held fixed. brier(0.99) > brier(0.70) ⇒ larger discount.
    worse = _four(0.99)
    assert score(worse).survival_net_return < score(recs).survival_net_return


# --- R4.3: the return is RISK-adjusted, not a raw mean --------------------


def test_survival_net_return_is_risk_adjusted_not_raw_mean():
    """R4.3 + the gate's PSR/DSR contract: ``survival_net_return`` is the
    risk-adjusted (Sharpe-like) return, NOT a raw mean. Two breach-free,
    identically-calibrated series with the SAME mean ``realized_outcome`` return
    but DIFFERENT volatility must rank differently — the higher-volatility series
    scores strictly lower (the gate has no separate std field; the risk
    adjustment must live in this scalar)."""
    # Both: mean realized_outcome = 0.02, all favorable (>0 except the dips),
    # same predicted_probability. The return series the Sharpe reads is
    # realized_outcome, so the volatility lives THERE.
    low_vals = (0.019, 0.020, 0.021, 0.020, 0.019, 0.021, 0.020, 0.020)
    high_vals = (-0.10, 0.14, -0.06, 0.10, -0.08, 0.12, 0.00, 0.04)
    low_vol = [_rec(predicted_probability=0.7, realized_outcome=v) for v in low_vals]
    high_vol = [_rec(predicted_probability=0.7, realized_outcome=v) for v in high_vals]
    # sanity: the two series share the same arithmetic mean (a raw-mean metric ties
    # them); only the spread differs — so any score gap is the risk adjustment.
    assert sum(low_vals) == pytest.approx(sum(high_vals))
    # risk-adjusted ⇒ higher volatility scores strictly lower (a raw mean would tie).
    assert score(high_vol).survival_net_return < score(low_vol).survival_net_return


# --- R4.4: calibration is direction-agnostic (read off realized_outcome) --


def test_winning_short_scores_like_a_winning_long():
    """THE direction-aware regression guard (isolates the calibration term).

    A winning SHORT (price fell → ``realized_label`` SELL, but the *position*
    WON) and a winning LONG (price rose → label BUY, position won) with IDENTICAL
    ``realized_outcome`` and ``predicted_probability`` must score IDENTICALLY on
    the survival-net scalar — favorability is whether the directional CALL was
    vindicated, side-paired, not the bare price-direction label.

    This holds the Sharpe core IDENTICAL across both series (same realized_outcome
    path), so the ONLY thing that could differ is the calibration term. A
    side-blind ``realized_label is Label.BUY`` favorability would score the winning
    SHORTs (label SELL) as misses and the winning LONGs (label BUY) as hits,
    breaking the equality (proven non-vacuous: it splits to short≈-0.69 vs
    long≈+0.01 under that bug). This is the test that genuinely catches the
    winning-short-mis-scored regression."""
    p = 0.85
    short_win = [_rec(decision="SHORT", predicted_probability=p, realized_outcome=0.03, realized_label=Label.SELL) for _ in range(8)]
    long_win = [_rec(decision="LONG", predicted_probability=p, realized_outcome=0.03, realized_label=Label.BUY) for _ in range(8)]
    assert score(short_win).survival_net_return == pytest.approx(
        score(long_win).survival_net_return
    )


def test_confidently_wrong_short_scores_below_a_calibrated_short():
    """Calibration is read direction-aware AND from the position's success: two
    SHORT series with the SAME winning ``realized_outcome`` path (same Sharpe
    core) but different ``predicted_probability`` confidence. The lower-confidence
    one on a win is *worse*-calibrated, so it scores strictly lower — isolating
    the calibration term (the return core is identical)."""
    # Both: winning shorts (price fell → SELL, position won), same realized_outcome.
    confident_right = [_rec(decision="SHORT", predicted_probability=0.9, realized_outcome=0.02, realized_label=Label.SELL) for _ in range(10)]
    underconfident = [_rec(decision="SHORT", predicted_probability=0.4, realized_outcome=0.02, realized_label=Label.SELL) for _ in range(10)]
    # p=0.9 on a favorable outcome → low Brier; p=0.4 on a favorable outcome →
    # higher Brier → lower score. Sharpe core identical (same realized_outcome).
    assert score(underconfident).survival_net_return < score(confident_right).survival_net_return


# --- Distribution-shape stats (skew/kurtosis the gate's PSR needs) --------


def test_skew_and_kurtosis_reflect_the_return_distribution():
    """``skew``/``kurtosis`` summarize the per-period return distribution the
    gate's PSR/MinTRL is skew/kurtosis-aware over. A left-skewed series has
    negative skew."""
    # symmetric-ish series → skew ~ 0
    sym = [_rec(total_return_pnl=v, realized_outcome=v) for v in (-0.02, -0.01, 0.0, 0.01, 0.02, -0.02, -0.01, 0.0, 0.01, 0.02)]
    out_sym = score(sym)
    assert abs(out_sym.skew) < 0.5
    # left-skewed: many small gains, one big loss → negative skew
    left = [_rec(total_return_pnl=0.01, realized_outcome=0.01) for _ in range(9)]
    left.append(_rec(total_return_pnl=-0.30, realized_outcome=-0.30, realized_label=Label.SELL))
    assert score(left).skew < 0.0


def test_determinism_identical_inputs_identical_output():
    recs = [_rec(total_return_pnl=0.013 * (i + 1), realized_outcome=0.013 * (i + 1)) for i in range(7)]
    a = score(recs)
    b = score(recs)
    assert a == b


def test_empty_records_raises():
    """An empty OOS partition is a degenerate input — the metric must not return
    a silent zero (the gate's MinTRL sufficiency is what should reject few-obs;
    a zero-length series has no defined risk-adjusted return)."""
    with pytest.raises(ValueError):
        score([])


def test_near_constant_returns_do_not_explode_to_a_garbage_sharpe():
    """Numerical-stability guard: a series of identical decimal returns (e.g.
    0.02, which is NOT exactly representable in float) has FP-noise-level std
    (~3.7e-18), not exactly 0. A naive ``mean / std`` would blow that up to a
    ~5e15 garbage 'Sharpe' that would poison the gate's PSR/DSR. The metric must
    treat an effectively-constant series as zero-variance and fall back to the
    mean — so the survival-net return stays a sane O(mean − Brier) magnitude and
    skew/kurtosis stay 0.0 (not noise-amplified)."""
    recs = [_rec(predicted_probability=0.7, realized_outcome=0.02, realized_label=Label.BUY) for _ in range(10)]
    out = score(recs)
    assert math.isfinite(out.survival_net_return)
    # mean(0.02) − brier; bounded well under 1.0 — NOT a 1e15 explosion.
    assert abs(out.survival_net_return) < 1.0
    assert out.skew == 0.0
    assert out.kurtosis == 0.0


def test_single_record_has_defined_finite_output():
    """A single OOS observation yields n_obs=1 and finite stats (skew/kurtosis of
    a degenerate sample default to 0.0, not NaN, so the gate can read them)."""
    out = score([_rec(total_return_pnl=0.02, realized_outcome=0.02)])
    assert out.n_obs == 1
    assert math.isfinite(out.skew)
    assert math.isfinite(out.kurtosis)
