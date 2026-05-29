"""Inner-ring unit tests for the decision core (`src.reactive.signal_model`).

Task 2.2 — the **directional aggregation** + the **signed projection** onto the
caller-supplied direction. (Tasks 2.3/2.4 and 3.3 will EXTEND this file with the
logistic, the thresholded `decide` contract, and the substrate.)

Covers (design §"Decision core — `signal_model`" Aggregation rule, §Testing
Strategy "Conflict aggregation", and requirements 1.5 + 3):

- aligned families → a decisive non-zero score;
- a cross-family conflict that SURVIVES damping (trend vs meanrev, flow≈0) → s≈0,
  contrasted with the SAME opposing votes under strong trend (|flow|=1) → meanrev
  damped away → decisive s (the pair proves the damping is what (de)permits it);
- strong-trend (|flow|→1) fully suppresses the mean-reversion term; range
  (|flow|→0) lets it contribute at full weight — incl. the byte-identical
  discriminator (flip meanrev under |flow|=1 ⇒ s unchanged);
- the projection sign follows the caller `Direction` (LONG vs SHORT mirror);
- `s ∈ [−1,+1]` across the vote domain (votes ∈ [−1,+1], damping ∈ [0,1], Σw=1);
- direction is a PURE INPUT — `aggregate_score` never reads it; the model never
  selects or flips the side (R3.2, R4.3).

No mocks, no LLM/MCP/DB (P14, R8). Hand-built `FeatureSet`s; the real reused cores
are exercised in `test_features.py` (task 2.1) — here we drive the aggregation
arithmetic directly with synthetic votes.
"""

from __future__ import annotations

import itertools
import math

import pytest

from src.reactive.features import FeatureSet
from src.reactive.params import DEFAULTS, ParamSnapshot, effective_threshold
from src.reactive.signal_model import (
    aggregate_score,
    decide,
    expose_calibration,
    probability,
    project,
)
from src.reactive.types import (
    CalibrationEvidence,
    DecisionSubstrate,
    FeatureFailure,
    ReactiveDecision,
    Weights,
)

# --- Helpers ----------------------------------------------------------------

# Exactly-equal weights (Σ=1) so a perfect trend/meanrev cancellation is a TRUE
# zero rather than the 0.01 residual the DEFAULTS 0.34/0.33/0.33 asymmetry leaves.
EQUAL_WEIGHTS = Weights(w_trend=1.0 / 3.0, w_flow=1.0 / 3.0, w_meanrev=1.0 / 3.0)


def _fs(
    trend_vote: float,
    flow_vote: float,
    meanrev_vote: float,
    trend_strength: float | None = None,
) -> FeatureSet:
    """A synthetic FeatureSet honoring the real `trend_strength == abs(flow_vote)`
    invariant (`features.py` owns that definition) unless overridden for a test."""
    ts = abs(flow_vote) if trend_strength is None else trend_strength
    return FeatureSet(
        trend_vote=trend_vote,
        flow_vote=flow_vote,
        meanrev_vote=meanrev_vote,
        trend_strength=ts,
        raw={},
    )


# --- Aggregation rule: aligned families decisive ----------------------------


def test_aligned_families_yield_decisive_nonzero_score():
    """All families agree LONG (+1) ⇒ the aggregate is decisively positive."""
    # trend_strength=1 here (flow=+1) damps meanrev to 0, but trend+flow alone
    # already carry it well above zero. Use EQUAL_WEIGHTS for clean arithmetic.
    fs = _fs(trend_vote=1.0, flow_vote=1.0, meanrev_vote=1.0)
    s = aggregate_score(fs, EQUAL_WEIGHTS)
    # s = 1/3·1 + 1/3·1 + 1/3·(1·(1−1)) = 2/3.
    assert s == pytest.approx(2.0 / 3.0)
    assert s > 0.5  # decisive


def test_aligned_short_families_yield_decisive_negative_score():
    """All families agree SHORT (−1) ⇒ decisively negative (sign mirror of above)."""
    fs = _fs(trend_vote=-1.0, flow_vote=-1.0, meanrev_vote=-1.0)
    s = aggregate_score(fs, EQUAL_WEIGHTS)
    assert s == pytest.approx(-2.0 / 3.0)
    assert s < -0.5


def test_range_regime_meanrev_contributes_at_full_weight():
    """Flat trend, flat flow (range, trend_strength=0): a lone oversold meanrev
    vote drives the score by exactly its full weight (undamped)."""
    fs = _fs(trend_vote=0.0, flow_vote=0.0, meanrev_vote=1.0)
    s = aggregate_score(fs, EQUAL_WEIGHTS)
    # s = 0 + 0 + 1/3·(1·(1−0)) = 1/3.
    assert s == pytest.approx(1.0 / 3.0)


# --- Conflict that SURVIVES damping → s≈0 (design line 241) -----------------


def test_conflict_surviving_damping_yields_near_zero_score():
    """Opposing trend(+1) vs meanrev(−1) with flow≈0 (trend_strength≈0): the
    meanrev term is UNDAMPED, so the two cancel → s≈0 (the conservative-Edge
    default → HOLD downstream). Exact zero under EQUAL_WEIGHTS."""
    fs = _fs(trend_vote=1.0, flow_vote=0.0, meanrev_vote=-1.0)
    s = aggregate_score(fs, EQUAL_WEIGHTS)
    # s = 1/3·1 + 1/3·0 + 1/3·(−1·(1−0)) = 0.
    assert s == pytest.approx(0.0, abs=1e-12)


def test_conflict_under_defaults_is_near_zero():
    """Same conflict under the real DEFAULTS weights (0.34/0.33/0.33): the
    weight asymmetry leaves only the residual 0.01 — still ≈0 (HOLD band),
    well inside a sane near-zero tolerance."""
    fs = _fs(trend_vote=1.0, flow_vote=0.0, meanrev_vote=-1.0)
    s = aggregate_score(fs, DEFAULTS.weights)
    # 0.34·1 − 0.33·1 = 0.01.
    assert s == pytest.approx(0.01, abs=1e-9)
    assert abs(s) < 0.05  # near-zero / HOLD band


def test_same_conflict_under_strong_trend_becomes_decisive():
    """CONTRAST to the surviving-conflict case: the SAME opposing trend(+1) vs
    meanrev(−1), but now flow=+1 (trend_strength=1) → meanrev term damped to 0
    → trend+flow win → decisive s. The pair proves the damping is what
    (de)permits the conflict, not an incidental zero."""
    surviving = aggregate_score(
        _fs(trend_vote=1.0, flow_vote=0.0, meanrev_vote=-1.0), EQUAL_WEIGHTS
    )
    damped = aggregate_score(
        _fs(trend_vote=1.0, flow_vote=1.0, meanrev_vote=-1.0), EQUAL_WEIGHTS
    )
    # surviving ≈ 0; damped = 1/3·1 + 1/3·1 + 1/3·(−1·(1−1)) = 2/3.
    assert surviving == pytest.approx(0.0, abs=1e-12)
    assert damped == pytest.approx(2.0 / 3.0)
    assert damped > 0.5
    assert abs(damped) > abs(surviving) + 0.5  # damping made it decisive


# --- Trend-strength damping of the mean-reversion term ----------------------


def test_strong_trend_fully_suppresses_meanrev_byte_identical():
    """The strongest discriminator (design line 237/241): under |flow|=1
    (trend_strength=1) the meanrev term is `meanrev·(1−1)=0` REGARDLESS of the
    meanrev vote. Flipping meanrev +1→−1 must leave s BYTE-IDENTICAL. A formula
    that damps the wrong term or drops the `(1−trend_strength)` factor fails."""
    base = _fs(trend_vote=1.0, flow_vote=1.0, meanrev_vote=1.0)   # trend_strength=1
    flipped = _fs(trend_vote=1.0, flow_vote=1.0, meanrev_vote=-1.0)
    s_base = aggregate_score(base, EQUAL_WEIGHTS)
    s_flipped = aggregate_score(flipped, EQUAL_WEIGHTS)
    assert s_base == s_flipped  # exact equality — meanrev term is 0 either way


def test_range_meanrev_flip_swings_by_exactly_two_wm():
    """The complement: under flow=0 (trend_strength=0) the meanrev term is
    UNDAMPED, so flipping meanrev +1→−1 swings s by exactly `2·w_meanrev`."""
    pos = _fs(trend_vote=0.0, flow_vote=0.0, meanrev_vote=1.0)
    neg = _fs(trend_vote=0.0, flow_vote=0.0, meanrev_vote=-1.0)
    s_pos = aggregate_score(pos, EQUAL_WEIGHTS)
    s_neg = aggregate_score(neg, EQUAL_WEIGHTS)
    assert (s_pos - s_neg) == pytest.approx(2.0 * EQUAL_WEIGHTS.w_meanrev)


def test_partial_trend_strength_damps_proportionally():
    """At trend_strength=0.5 (|flow|=0.5) the meanrev term contributes at half
    weight — proves the damping factor is `(1−trend_strength)`, continuous."""
    fs = _fs(trend_vote=0.0, flow_vote=0.5, meanrev_vote=1.0)  # trend_strength=0.5
    s = aggregate_score(fs, EQUAL_WEIGHTS)
    # s = 0 + 1/3·0.5 + 1/3·(1·(1−0.5)) = 1/3·0.5 + 1/3·0.5 = 1/3.
    assert s == pytest.approx(1.0 / 3.0)


def test_aggregate_uses_features_trend_strength_not_recomputed():
    """`aggregate_score` reads `features.trend_strength` (the single owner of
    that definition is `features.py`); it does NOT recompute `abs(flow_vote)`
    internally. Drive trend_strength to a value DECOUPLED from flow_vote and the
    damping must follow the field, not the flow magnitude."""
    # flow_vote=1.0 (would imply strength 1 if recomputed) but strength forced to 0
    # ⇒ meanrev must be UNDAMPED (contributes at full weight).
    fs = _fs(trend_vote=0.0, flow_vote=1.0, meanrev_vote=1.0, trend_strength=0.0)
    s = aggregate_score(fs, EQUAL_WEIGHTS)
    # If it honored the field (strength 0): s = 1/3·1 (flow) + 1/3·(1·1) (meanrev) = 2/3.
    # If it wrongly recomputed abs(flow)=1: meanrev damped to 0 → s = 1/3.
    assert s == pytest.approx(2.0 / 3.0)


# --- Signed projection onto the caller direction (R3, R4.3) -----------------


def test_projection_long_is_identity():
    """LONG ⇒ signed = s (favorable LONG aggregate stays positive)."""
    assert project(0.42, "LONG") == pytest.approx(0.42)
    assert project(-0.42, "LONG") == pytest.approx(-0.42)


def test_projection_short_is_negation():
    """SHORT ⇒ signed = −s (a LONG-favoring aggregate is unfavorable for SHORT)."""
    assert project(0.42, "SHORT") == pytest.approx(-0.42)
    assert project(-0.42, "SHORT") == pytest.approx(0.42)


@pytest.mark.parametrize("s", [-1.0, -0.5, -0.01, 0.0, 0.01, 0.5, 1.0])
def test_projection_long_short_mirror(s):
    """The mirror invariant: `project(s, LONG) == −project(s, SHORT)` for every s.
    Direction is a PURE INPUT — it only flips the sign, it NEVER selects a side."""
    assert project(s, "LONG") == pytest.approx(-project(s, "SHORT"))


def test_projection_zero_is_direction_invariant():
    """s=0 projects to 0 for BOTH directions (no edge ⇒ no side)."""
    assert project(0.0, "LONG") == 0.0
    assert project(0.0, "SHORT") == 0.0


def test_aggregate_score_never_reads_direction():
    """`aggregate_score` takes (features, weights) ONLY — it has no `direction`
    parameter, so it structurally CANNOT select or flip the side (R3.2/R4.3)."""
    import inspect

    sig = inspect.signature(aggregate_score)
    assert "direction" not in sig.parameters


# --- s ∈ [−1,+1] across the vote domain (Σw=1) ------------------------------


def test_score_within_unit_interval_across_vote_domain():
    """Sweep the vote corners (and a few interiors) with NORMALIZED weights:
    the aggregate is provably bounded `|s| ≤ 1` (each vote ∈ [−1,+1], damping
    factor ∈ [0,1], Σw=1). The bound is NOT tight (damping caps the achievable
    max well below 1 for equal flow/meanrev weight) — assert ≤ 1, not = 1."""
    votes = (-1.0, -0.5, 0.0, 0.5, 1.0)
    for w in (EQUAL_WEIGHTS, DEFAULTS.weights):
        for tv, fv, mv in itertools.product(votes, votes, votes):
            fs = _fs(trend_vote=tv, flow_vote=fv, meanrev_vote=mv)
            s = aggregate_score(fs, w)
            assert -1.0 <= s <= 1.0


def test_projection_preserves_unit_bound():
    """Projection only flips a sign ⇒ a bounded s stays bounded under both sides."""
    for s in (-1.0, -0.3, 0.0, 0.7, 1.0):
        for d in ("LONG", "SHORT"):
            assert -1.0 <= project(s, d) <= 1.0


# --- Determinism (R8.1, partial — extended for full decide in 2.4) ----------


def test_aggregate_is_deterministic():
    """Identical (features, weights) → identical score (P14/R8.1)."""
    fs = _fs(trend_vote=0.6, flow_vote=-0.4, meanrev_vote=0.2)
    a = aggregate_score(fs, DEFAULTS.weights)
    b = aggregate_score(fs, DEFAULTS.weights)
    assert a == b


# --- Probability derivation: the 2-class logistic (R2, P15) -----------------
#
# Task 2.3. `P = 1/(1+exp(−signed/temperature))` where `signed` is the 2.2
# `project(...)` output. The probability is MODEL-DERIVED (a logistic over the
# aggregated/projected score), monotonic increasing in `signed`, in the OPEN
# interval (0,1), with `signed=0 → 0.5`. The reference intraday hold-logit is
# DELIBERATELY DROPPED (design §"Probability derivation" / Boundary line 28) —
# HOLD comes ONLY from the threshold in 2.4, NEVER from a probability term.
# No threshold/decision/sizing/substrate here (that crosses the 2.4 boundary).


def test_probability_signed_zero_is_one_half():
    """`signed = 0 → P = 0.5` exactly — the logistic's symmetry point (no edge ⇒
    even odds). A linear/clamped placeholder centered elsewhere fails this."""
    assert probability(0.0, DEFAULTS.temperature) == pytest.approx(0.5)


def test_probability_positive_projection_above_half():
    """A positive projection (caller direction favored) → P > 0.5."""
    assert probability(0.5, DEFAULTS.temperature) > 0.5


def test_probability_negative_projection_below_half():
    """A negative projection (caller direction disfavored) → P < 0.5."""
    assert probability(-0.5, DEFAULTS.temperature) < 0.5


def test_probability_strictly_monotonic_in_signed():
    """STRICTLY increasing in `signed` across the projection domain — the
    discriminating property of a real logistic. A constant/clamped/saturating
    stub (or a flat placeholder) fails because distinct `signed` → distinct P.
    Uses strict `<` (not `<=`): with `signed ∈ [−1,1]` and T≈1 there is no
    float saturation, so the curve is strictly rising everywhere."""
    xs = [-1.0, -0.7, -0.3, -0.05, 0.0, 0.05, 0.3, 0.7, 1.0]
    ps = [probability(x, DEFAULTS.temperature) for x in xs]
    for lo, hi in zip(ps, ps[1:]):
        assert lo < hi


def test_probability_in_open_unit_interval():
    """`P ∈ (0,1)` — strictly inside the open interval across the projection
    domain (`|signed| ≤ 1`, where upstream votes live) and modestly beyond. A
    logistic never reaches 0 or 1; this guards against a clamped/linear stub that
    would hit an endpoint at e.g. `signed = ±1`. (Not asserted at extreme
    saturating inputs like ±100, where `1/(1+exp(∓100))` rounds to exactly 1.0/
    0.0 in IEEE754 — a float-representation artifact, not a model property, and
    outside the bounded operating domain anyway.)"""
    for x in (-3.0, -1.0, -0.01, 0.0, 0.01, 1.0, 3.0):
        p = probability(x, DEFAULTS.temperature)
        assert 0.0 < p < 1.0


def test_probability_matches_closed_form_logistic():
    """Pin the exact closed form `1/(1+exp(−signed/T))` — a wrong sign, a missing
    `/T`, or a different curve (e.g. linear/tanh-scaled) diverges from this."""
    signed, temp = 0.4, 1.3
    expected = 1.0 / (1.0 + math.exp(-signed / temp))
    assert probability(signed, temp) == pytest.approx(expected)


def test_lower_temperature_sharpens_probability():
    """Lower temperature SHARPENS the probability: for the SAME nonzero `signed`,
    a smaller T pushes P further from 0.5 (more extreme/decisive). Framed as
    `abs(P − 0.5)` so it holds for both signs of `signed` (lower T pushes P→1
    when signed>0 but P→0 when signed<0). A stub that ignores T fails."""
    signed = 0.5
    sharp = probability(signed, 0.25)   # low temperature
    soft = probability(signed, 4.0)     # high temperature
    assert abs(sharp - 0.5) > abs(soft - 0.5)
    # Mirror check for a negative projection (sign-robust).
    sharp_neg = probability(-signed, 0.25)
    soft_neg = probability(-signed, 4.0)
    assert abs(sharp_neg - 0.5) > abs(soft_neg - 0.5)


def test_probability_long_short_symmetric_on_mirrored_signed():
    """The logistic is symmetric about 0.5: `P(signed) + P(−signed) == 1`.
    Combined with 2.2's `project(s, LONG) == −project(s, SHORT)`, this is the
    LONG/SHORT mirror of the derived probability (design §Testing Strategy 2.x)."""
    for x in (0.0, 0.1, 0.5, 1.0):
        assert probability(x, DEFAULTS.temperature) + probability(
            -x, DEFAULTS.temperature
        ) == pytest.approx(1.0)


def test_probability_is_deterministic():
    """Identical (signed, temperature) → identical P (P14/R8.1)."""
    assert probability(0.37, 0.9) == probability(0.37, 0.9)


# --- Calibration exposure: carried through, never computed (R2.4, R7) -------
#
# Task 2.3. The snapshot's `CalibrationEvidence` is EXPOSED alongside the
# probability — passed through UNCHANGED, never computed/mutated here. Computing
# Brier/reliability over realized outcomes is the tuning loop's job (R7.4); this
# module does no metric math.


def test_expose_calibration_passes_snapshot_evidence_through_by_identity():
    """`expose_calibration` returns the SNAPSHOT's exact `CalibrationEvidence`
    object — identity (`is`), not just equality. Identity is the discriminating
    check: `CalibrationEvidence` is a frozen dataclass, so `==` would still pass
    if the value were RECONSTRUCTED; `is` proves it is carried through, not
    recomputed/rebuilt (R7.4 — calibration is exposed, never computed)."""
    evidence = CalibrationEvidence(brier=0.21, reliability=0.88)
    snap = ParamSnapshot(
        weights=DEFAULTS.weights,
        temperature=DEFAULTS.temperature,
        threshold=DEFAULTS.threshold,
        calibration=evidence,
        code_version="t",
        param_version="t",
    )
    assert expose_calibration(snap) is evidence


def test_expose_calibration_under_defaults_is_unestablished_none():
    """Under the inner-ring `DEFAULTS`, the exposed calibration is the
    UNESTABLISHED `CalibrationEvidence(None, None)` — exposed (not computed)
    exactly as carried (design §params Invariants: DEFAULTS.calibration == None).
    Both the value (`==`) and the identity (`is`) hold."""
    exposed = expose_calibration(DEFAULTS)
    assert exposed == CalibrationEvidence(brier=None, reliability=None)
    assert exposed is DEFAULTS.calibration  # carried through, not rebuilt


def test_expose_calibration_does_not_mutate_or_compute():
    """The pass-through neither mutates the snapshot's evidence nor fills in any
    metric: a snapshot whose calibration is None stays None after exposure (no
    Brier/reliability is fabricated here — that is the tuning loop's job)."""
    exposed = expose_calibration(DEFAULTS)
    assert exposed.brier is None and exposed.reliability is None


# --- The public `decide` entry point (task 2.4) -----------------------------
#
# `decide(features, direction, snapshot, runtime_threshold=None) -> ReactiveDecision`
# assembles the pipeline from 2.1–2.3: aggregate_score → project → probability →
# effective_threshold → thresholded decision + advisory sizing hint + substrate.
# Covers design §"Decision core — `signal_model`" Postconditions/Invariants and
# requirements 1 (FeatureFailure→HOLD+reason), 3 (P>θ→LONG/SHORT==direction;
# P≤θ→HOLD; vocab; invalid→HOLD+invalid_direction; non-final flag), 4 (non_final
# always; never flips/escalates), 5 (advisory sizing hint, None on HOLD), 6
# (tighten-only effective threshold applied), 7 (substrate). No LLM/MCP/DB (R8).


def _snap(threshold: float = 0.55, temperature: float = 1.0) -> ParamSnapshot:
    """A ParamSnapshot with a tunable threshold/temperature for decide() tests
    (otherwise DEFAULTS: equal-ish weights, calibration None, fixed versions)."""
    return ParamSnapshot(
        weights=DEFAULTS.weights,
        temperature=temperature,
        threshold=threshold,
        calibration=DEFAULTS.calibration,
        code_version="reactive-signal-model@vT",
        param_version="defaults@vT",
    )


# A strongly LONG-favoring feature set: all families +1 ⇒ s≈0.67 ⇒ signed (LONG)
# ⇒ P well above the 0.55 default threshold. (meanrev damped to 0 by flow=1.)
_STRONG_LONG = _fs(trend_vote=1.0, flow_vote=1.0, meanrev_vote=1.0)
# A flat feature set: all votes 0 ⇒ s=0 ⇒ signed=0 ⇒ P=0.5 ≤ θ ⇒ HOLD.
_FLAT = _fs(trend_vote=0.0, flow_vote=0.0, meanrev_vote=0.0)


# --- R3.3 / Postcondition: P>θ → LONG/SHORT matching the caller direction ----


def test_decide_above_threshold_emits_caller_long():
    """P > effective threshold ⇒ decision == the caller LONG direction, non_final,
    with an actionable (non-None) sizing hint and a populated substrate."""
    snap = _snap(threshold=0.55)
    d = decide(_STRONG_LONG, "LONG", snap)
    assert isinstance(d, ReactiveDecision)
    assert d.decision == "LONG"
    assert d.direction_in == "LONG"
    assert d.non_final is True
    assert d.reason is None
    assert d.sizing_hint is not None
    assert d.probability > snap.threshold


def test_decide_above_threshold_emits_caller_short():
    """The SHORT mirror: a strongly SHORT-favoring set (all votes −1) projected
    onto a SHORT caller clears θ ⇒ decision == SHORT (never flipped to LONG)."""
    strong_short = _fs(trend_vote=-1.0, flow_vote=-1.0, meanrev_vote=-1.0)
    snap = _snap(threshold=0.55)
    d = decide(strong_short, "SHORT", snap)
    assert d.decision == "SHORT"
    assert d.direction_in == "SHORT"
    assert d.probability > snap.threshold
    assert d.sizing_hint is not None


def test_decide_emits_only_canonical_vocabulary():
    """Across actionable and HOLD paths the decision is drawn ONLY from
    {LONG, SHORT, HOLD} (P9, R3.5)."""
    snap = _snap()
    for feats, direction in (
        (_STRONG_LONG, "LONG"),
        (_fs(-1.0, -1.0, -1.0), "SHORT"),
        (_FLAT, "LONG"),
    ):
        assert decide(feats, direction, snap).decision in {"LONG", "SHORT", "HOLD"}


# --- R3.4 / Postcondition: P ≤ θ → HOLD with no actionable hint --------------


def test_decide_at_or_below_threshold_holds():
    """P ≤ effective threshold ⇒ HOLD with sizing_hint None (no actionable hint).
    A flat feature set gives P=0.5 ≤ 0.55, and the threshold comparison is strict
    (`>`), so even P == θ is HOLD."""
    d = decide(_FLAT, "LONG", _snap(threshold=0.55))
    assert d.decision == "HOLD"
    assert d.sizing_hint is None
    assert d.non_final is True
    assert d.reason is None  # sub-threshold HOLD is a real derivation, not an abstain
    assert d.probability <= 0.55


def test_decide_strict_threshold_p_equal_theta_is_hold():
    """The threshold is STRICT (`P > θ`, R3.3/R3.4): set θ exactly to the derived
    P=0.5 (flat features, signed=0) ⇒ P == θ ⇒ HOLD, not LONG."""
    d = decide(_FLAT, "LONG", _snap(threshold=0.5))
    assert d.probability == pytest.approx(0.5)
    assert d.decision == "HOLD"
    assert d.sizing_hint is None


# --- R6.3/6.4 / Invariant: tighten-only effective threshold APPLIED ----------


def test_decide_higher_runtime_threshold_flips_long_to_hold():
    """Tighten-only, load-bearing: a would-be LONG (P>snapshot θ) becomes HOLD
    when a HIGHER runtime_threshold is supplied that P does not clear. Proves the
    runtime override is actually applied to the decision (R6.3)."""
    snap = _snap(threshold=0.55)
    base = decide(_STRONG_LONG, "LONG", snap)
    assert base.decision == "LONG"  # clears the snapshot threshold
    p = base.probability
    # Choose a runtime threshold strictly between the snapshot θ and P, but ABOVE
    # P so the decision flips to HOLD. p is comfortably above 0.55 here.
    tightened = decide(_STRONG_LONG, "LONG", snap, runtime_threshold=p + 0.01)
    assert tightened.decision == "HOLD"
    assert tightened.sizing_hint is None
    assert tightened.substrate.effective_threshold == pytest.approx(p + 0.01)


def test_decide_lower_runtime_threshold_is_ignored():
    """A LOWER runtime_threshold is rejected; the snapshot threshold is retained
    (loosening forbidden, R6.4). A flat-features HOLD at θ=0.55 stays HOLD even
    when a lower runtime threshold (0.10) is passed — the snapshot θ governs."""
    snap = _snap(threshold=0.55)
    d = decide(_FLAT, "LONG", snap, runtime_threshold=0.10)
    # effective threshold is max(0.55, 0.10) = 0.55, NOT the lower 0.10.
    assert d.substrate.effective_threshold == pytest.approx(0.55)
    assert d.decision == "HOLD"


def test_decide_lower_runtime_threshold_does_not_enable_a_long():
    """Stronger lower-override case: P clears the snapshot θ would-be LONG; a
    runtime threshold BELOW the snapshot must NOT change the effective threshold
    (so the LONG stands at the snapshot θ, never at the looser runtime value)."""
    snap = _snap(threshold=0.55)
    d = decide(_STRONG_LONG, "LONG", snap, runtime_threshold=0.10)
    assert d.substrate.effective_threshold == pytest.approx(0.55)
    assert d.decision == "LONG"


def test_decide_effective_threshold_matches_params_resolver():
    """`decide` reuses `params.effective_threshold` (not a reimplementation): the
    substrate's effective_threshold equals the resolver for None / higher / lower
    runtime overrides."""
    snap = _snap(threshold=0.55)
    for runtime in (None, 0.70, 0.30):
        d = decide(_FLAT, "LONG", snap, runtime_threshold=runtime)
        assert d.substrate.effective_threshold == pytest.approx(
            effective_threshold(snap, runtime)
        )


# --- R3.6 / decide-OWNED reason: invalid/missing direction → HOLD ------------


@pytest.mark.parametrize("bad", [None, "long", "BUY", "", "SELL", 0])
def test_decide_invalid_direction_holds_with_owned_reason(bad):
    """Missing/invalid direction (decide's OWNED reason) ⇒ HOLD + reason
    'invalid_direction', non_final, no sizing hint, with a substrate still
    attached. `direction_in` echoes the raw bad input (Literal not enforced at
    runtime)."""
    d = decide(_STRONG_LONG, bad, _snap())  # type: ignore[arg-type]
    assert d.decision == "HOLD"
    assert d.reason == "invalid_direction"
    assert d.non_final is True
    assert d.sizing_hint is None
    assert isinstance(d.substrate, DecisionSubstrate)


def test_decide_invalid_direction_does_not_compute_features():
    """The invalid-direction abstain is decided BEFORE any feature derivation:
    even a degenerate FeatureSet-less sentinel as `features` must not be touched.
    Passing an object that would explode on attribute access proves features are
    not read on this path."""

    class _Explode:
        def __getattr__(self, name):  # any attribute access blows up
            raise AssertionError(f"features touched on invalid-direction path: {name}")

    # Direction invalid ⇒ decide returns before ever reading `features`.
    d = decide(_Explode(), None, _snap())  # type: ignore[arg-type]
    assert d.decision == "HOLD"
    assert d.reason == "invalid_direction"


# --- R1.6/1.7 / failure-ownership: FeatureFailure → HOLD + its reason --------


@pytest.mark.parametrize("reason", ["insufficient_history", "degenerate_features"])
def test_decide_feature_failure_holds_with_that_reason(reason):
    """A FeatureFailure input ⇒ HOLD carrying that exact reason (decide trusts the
    discriminator), non_final, no sizing hint, substrate attached."""
    d = decide(FeatureFailure(reason=reason), "LONG", _snap())
    assert d.decision == "HOLD"
    assert d.reason == reason
    assert d.non_final is True
    assert d.sizing_hint is None
    assert isinstance(d.substrate, DecisionSubstrate)
    assert d.direction_in == "LONG"  # a valid direction is still echoed


def test_decide_feature_failure_does_not_recompute_features():
    """decide trusts the FeatureFailure discriminator and does NOT re-validate
    history/ATR (design §Feature adapter failure-ownership): a FeatureFailure has
    no `.raw`/vote fields, so any attempt to run aggregate_score/project on it
    would AttributeError. Reaching a clean HOLD proves no recomputation."""
    d = decide(FeatureFailure(reason="insufficient_history"), "SHORT", _snap())
    assert d.decision == "HOLD"
    assert d.reason == "insufficient_history"
    assert d.substrate.feature_values == {}  # nothing was computed


def test_decide_invalid_direction_wins_over_feature_failure():
    """Ordering pin (task step 1 before step 2): when BOTH the direction is
    invalid AND features is a FeatureFailure, the decide-owned 'invalid_direction'
    is reported (direction validity is checked first)."""
    d = decide(FeatureFailure(reason="insufficient_history"), None, _snap())  # type: ignore[arg-type]
    assert d.decision == "HOLD"
    assert d.reason == "invalid_direction"


# --- R4 / Postcondition+Invariant: non_final always; never flips direction ---


def test_decide_non_final_always_true_across_all_paths():
    """Every decision is flagged non_final (R4.1) — actionable, HOLD, invalid
    direction, and FeatureFailure paths alike."""
    cases = [
        decide(_STRONG_LONG, "LONG", _snap()),                      # actionable
        decide(_FLAT, "LONG", _snap()),                             # sub-threshold HOLD
        decide(_STRONG_LONG, None, _snap()),                        # invalid direction
        decide(FeatureFailure(reason="degenerate_features"), "LONG", _snap()),
    ]
    for d in cases:
        assert d.non_final is True


def test_decide_never_flips_direction():
    """R4.3: a SHORT-favoring aggregate projected onto a LONG caller yields a low
    P (≤θ) ⇒ HOLD — decide NEVER flips the unfavorable LONG into a SHORT. The
    decision is the caller direction or HOLD, never the opposite side."""
    # All votes -1 favors SHORT; caller asks LONG ⇒ signed<0 ⇒ P<0.5 ⇒ HOLD.
    short_favoring = _fs(trend_vote=-1.0, flow_vote=-1.0, meanrev_vote=-1.0)
    d = decide(short_favoring, "LONG", _snap(threshold=0.55))
    assert d.probability < 0.5
    assert d.decision == "HOLD"        # NOT "SHORT"
    assert d.decision != "SHORT"
    assert d.direction_in == "LONG"    # echoes the caller side, unflipped


# --- R5 / sizing hint: advisory, increasing above θ, None on HOLD ------------


def test_decide_sizing_hint_increases_with_probability_above_threshold():
    """R5.1: among actionable decisions, a HIGHER probability (further above θ)
    yields a LARGER sizing hint. Two LONG-favoring sets with different strengths,
    both clearing θ, ordered by their P."""
    snap = _snap(threshold=0.55)
    # Weaker but still-clearing LONG: trend+flow only, smaller |signed|.
    weak = _fs(trend_vote=0.6, flow_vote=0.6, meanrev_vote=0.0)
    strong = _STRONG_LONG
    dw = decide(weak, "LONG", snap)
    ds = decide(strong, "LONG", snap)
    assert dw.decision == "LONG" and ds.decision == "LONG"
    assert ds.probability > dw.probability
    assert ds.sizing_hint > dw.sizing_hint  # increases with P above θ


def test_decide_sizing_hint_tracks_distance_above_threshold():
    """R5.1, sharper: a tighter (higher) effective threshold shrinks the hint for
    the SAME features (less distance above θ). Proves the hint scales with
    `P − effective_threshold`, not just with P."""
    snap = _snap(threshold=0.55)
    loose = decide(_STRONG_LONG, "LONG", snap)                       # θ=0.55
    p = loose.probability
    # A higher runtime threshold still below P keeps it LONG but shrinks the gap.
    tighter = decide(_STRONG_LONG, "LONG", snap, runtime_threshold=p - 0.01)
    assert tighter.decision == "LONG"
    assert tighter.sizing_hint < loose.sizing_hint


def test_decide_hold_has_no_actionable_sizing_hint():
    """R5.2: HOLD ⇒ no actionable sizing hint (None) on every HOLD path."""
    for d in (
        decide(_FLAT, "LONG", _snap()),                                  # sub-threshold
        decide(_STRONG_LONG, None, _snap()),                             # invalid direction
        decide(FeatureFailure(reason="insufficient_history"), "LONG", _snap()),
    ):
        assert d.decision == "HOLD"
        assert d.sizing_hint is None


def test_decide_sizing_hint_is_positive_when_actionable():
    """R5.1: an actionable hint is a positive scalar (P strictly above θ ⇒ a
    positive gap). It is advisory (a hint, never enforced) and carries no cap —
    decide enforces no size and no cap (R5.4/R5.5)."""
    d = decide(_STRONG_LONG, "LONG", _snap(threshold=0.55))
    assert d.sizing_hint > 0.0


# --- R7 / substrate: feature_values + probability + θ + versions + calib ------


def test_decide_substrate_carries_feature_values_and_probability():
    """R7.2: on an actionable decision the substrate exposes the feature `raw`
    values and the derived probability used for the decision."""
    raw = {"rsi_14": 25.0, "atr": 1.5, "flow_composite": 1.0}
    feats = FeatureSet(
        trend_vote=1.0, flow_vote=1.0, meanrev_vote=1.0, trend_strength=1.0, raw=raw
    )
    d = decide(feats, "LONG", _snap(threshold=0.55))
    assert d.substrate.feature_values == raw
    assert d.substrate.feature_values is raw  # carried through, not rebuilt
    assert d.substrate.probability == d.probability


def test_decide_substrate_carries_effective_threshold_and_versions():
    """R7.3: substrate exposes the EFFECTIVE threshold actually applied and the
    consumed snapshot versions (code_version / param_version)."""
    snap = _snap(threshold=0.55)
    d = decide(_STRONG_LONG, "LONG", snap, runtime_threshold=0.60)
    assert d.substrate.effective_threshold == pytest.approx(0.60)  # tightened
    assert d.substrate.code_version == snap.code_version
    assert d.substrate.param_version == snap.param_version


def test_decide_substrate_exposes_snapshot_calibration_by_identity():
    """R7.1/R7.4: the substrate exposes the snapshot's CalibrationEvidence
    UNCHANGED (identity), never computed. Uses a snapshot carrying real evidence."""
    evidence = CalibrationEvidence(brier=0.19, reliability=0.91)
    snap = ParamSnapshot(
        weights=DEFAULTS.weights,
        temperature=1.0,
        threshold=0.55,
        calibration=evidence,
        code_version="c",
        param_version="p",
    )
    d = decide(_STRONG_LONG, "LONG", snap)
    assert d.substrate.calibration is evidence  # carried through, not recomputed


def test_decide_substrate_present_on_abstain_paths():
    """R7: even the abstain paths (invalid direction, FeatureFailure) attach a
    substrate carrying the effective threshold + versions + calibration, with no
    feature values (nothing was computed)."""
    snap = _snap(threshold=0.55)
    invalid = decide(_STRONG_LONG, None, snap)                       # invalid direction
    failure = decide(FeatureFailure(reason="degenerate_features"), "LONG", snap)
    for d in (invalid, failure):
        assert isinstance(d.substrate, DecisionSubstrate)
        assert d.substrate.feature_values == {}
        assert d.substrate.effective_threshold == pytest.approx(0.55)
        assert d.substrate.code_version == snap.code_version
        assert d.substrate.param_version == snap.param_version
        assert d.substrate.calibration is snap.calibration


# --- R8.1 / determinism: identical inputs → identical ReactiveDecision -------


def test_decide_is_deterministic_full_decision_equality():
    """Identical (features, direction, snapshot, runtime_threshold) → byte-identical
    ReactiveDecision (frozen dataclass `==`), across actionable / HOLD / abstain."""
    snap = _snap(threshold=0.55)
    cases = [
        (_STRONG_LONG, "LONG", None),
        (_FLAT, "LONG", None),
        (_STRONG_LONG, "LONG", 0.99),                 # tightened to HOLD
        (_STRONG_LONG, None, None),                   # invalid direction
        (FeatureFailure(reason="insufficient_history"), "LONG", None),
    ]
    for feats, direction, runtime in cases:
        a = decide(feats, direction, snap, runtime_threshold=runtime)  # type: ignore[arg-type]
        b = decide(feats, direction, snap, runtime_threshold=runtime)  # type: ignore[arg-type]
        assert a == b


# ===========================================================================
# Task 3.3 — coverage-completion additions (the FINAL inner-ring gate).
#
# The bulk of the decision-core contract is already covered above (tasks
# 2.2/2.3/2.4). 3.3 adds only what was genuinely MISSING:
#
#   1. **Isolation (R8.2/R8.3) — the new item.** Assert `signal_model.py`'s OWN
#      direct import surface is confined to stdlib + the EXACT allowed
#      `src.reactive.{types,params,features}` deps (design §Allowed Dependencies:
#      `types → params → features → signal_model`). NO overlays/indicators (those
#      are `features.py`'s deps, not this module's), NO intraday
#      `src.micro.signal_model`, NO LLM/MCP/network/DB. AST-over-source (the
#      harness loads numpy/scipy/httpx/pandas, so a `sys.modules` probe is
#      polluted — mirrors the established `test_features.py` predicate). Includes
#      a self-proving negative so the green real-surface result is meaningful.
#   2. **End-to-end conflict→HOLD through `decide`** (design §Testing Strategy
#      line 241). 2.2 asserted `s≈0` at the AGGREGATION level only; here we assert
#      the surviving-conflict feature set actually EMITS HOLD through the full
#      public `decide` pipeline (s≈0 → P≈0.5 ≤ θ → HOLD, reason=None — a real
#      sub-threshold derivation, not an abstain).
#   3. **End-to-end determinism spanning the conflict→HOLD path** — the 2.4
#      full-decision `==` test spans actionable / sub-threshold-HOLD / tightened /
#      invalid / insufficient_history, but NOT the surviving-conflict→HOLD nor the
#      `degenerate_features` abstain. Close those two gaps so determinism is
#      byte-identical-asserted across ALL `decide` outcome classes.
# ===========================================================================

import ast  # noqa: E402  (3.3 isolation test — kept local to this section)
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import src.reactive.signal_model as signal_model_mod  # noqa: E402

# LLM/MCP/network/DB + heavy-numeric families that would break the "pure leaf,
# no LLM/MCP/live-DB" contract if imported DIRECTLY by signal_model.py (R8.2).
# numpy/scipy/pandas are listed because the design says this module needs NO
# numeric lib at all (pure arithmetic via `math`) — a direct numpy import would
# be a regression even though it is not strictly an I/O family. The stdlib
# allowlist below is the load-bearing general check; this list is the
# reviewer-legible guard against the named offenders (mirrors test_features.py).
_FORBIDDEN_SM_IMPORT_SUBSTRINGS = (
    "psycopg",
    "sqlalchemy",
    "httpx",
    "requests",
    "urllib3",
    "aiohttp",
    "mcp",
    "llm",
    "anthropic",
    "openai",
    "boto3",
    "numpy",
    "scipy",
    "pandas",
)

# The EXACT intra-`src` modules signal_model.py is permitted to depend on. Per
# design §Allowed Dependencies the strict left→right chain is
# `types → params → features → signal_model`, so the decision core imports ONLY
# its three sibling reactive contracts. Deliberately TIGHTER than features.py's
# allowlist: signal_model must NOT import the overlay cores / indicators
# directly (those are `features.py`'s deps — it consumes the already-computed
# `FeatureSet`), and must NEVER touch the intraday `src.micro.signal_model`.
# Exact-match (not a `src.reactive.*` prefix) so a future `src.reactive.db` or
# `src.reactive.telemetry.*` import would be flagged, not silently admitted.
_ALLOWED_SM_SRC_MODULES = frozenset(
    {
        "src.reactive.types",
        "src.reactive.params",
        "src.reactive.features",
    }
)


def _check_sm_import_surface(source: str) -> list[str]:
    """Return a list of isolation violations for `source` (empty = clean).

    AST over the *source text* — NOT `sys.modules` — because the test harness
    itself loads numpy/scipy/httpx/pandas (see the validation command), so a
    `sys.modules` probe would be polluted and report false positives. This
    inspects what signal_model.py actually DECLARES as direct imports.

    A violation is any import whose top-level root is neither stdlib nor `src`,
    OR any `src.`-prefixed import not in the exact `_ALLOWED_SM_SRC_MODULES` set.
    """
    allowed_roots = set(sys.stdlib_module_names) | {"__future__", "src"}
    violations: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in allowed_roots:
                    violations.append(f"import {alias.name}")
                elif root == "src" and alias.name not in _ALLOWED_SM_SRC_MODULES:
                    # Plain `import src.micro.signal_model` must be caught too —
                    # not only the `from ... import` form (else the intraday
                    # model could slip in via the plain-import style).
                    violations.append(f"import {alias.name} (src not in allowlist)")
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or node.module is None:
                violations.append("relative import (level>0 or no module)")
                continue
            root = node.module.split(".")[0]
            if root not in allowed_roots:
                violations.append(f"from {node.module}")
            elif root == "src" and node.module not in _ALLOWED_SM_SRC_MODULES:
                violations.append(f"from {node.module} (src not in allowlist)")
    return violations


# --- Isolation (R8.2 / R8.3): signal_model.py's OWN import surface ----------


def test_signal_model_import_surface_is_stdlib_plus_allowed_reactive_only():
    """R8.2/R8.3 (the 3.3 new item): signal_model.py is a pure leaf. Its DIRECT
    import surface must be confined to stdlib + the EXACT allowed reactive deps
    (`src.reactive.{types,params,features}`) — no LLM/MCP/network/DB, no numeric
    lib, and crucially NO overlay cores / indicators (features.py's deps) and NO
    intraday `src.micro.signal_model`. `sys.stdlib_module_names` is the robust
    general allowlist (catches ANY third-party import, incl. numpy/scipy/pandas,
    not only the enumerated offenders)."""
    source = Path(signal_model_mod.__file__).read_text()
    violations = _check_sm_import_surface(source)
    assert violations == [], (
        f"signal_model.py has forbidden direct imports {violations} — breaks the "
        "pure-leaf isolation contract (R8.2/R8.3; design §Allowed Dependencies)"
    )


def test_signal_model_import_surface_check_actually_catches_violations():
    """Self-proving: the isolation predicate is not vacuous — it FLAGS each
    forbidden form. Run it over a crafted bad source (without touching src/): a
    third-party import, the EXCLUDED intraday model, the overlay cores (allowed
    for features.py but NOT for the decision core), and a non-allowlisted `src`
    module must all be reported; the clean stdlib + allowed-reactive imports must
    NOT be. If this passes, the green real-surface result above is meaningful."""
    bad_source = (
        "import numpy\n"
        "from src.micro.signal_model import softmax3\n"  # excluded intraday (from-form)
        "import src.micro.signal_model\n"  # excluded intraday (plain-import form)
        "from src.overlays.flow.bin_classifier import classify_flow\n"  # features' dep, not core's
        "from src.reactive.db import write_row\n"
        "import math\n"  # stdlib — must NOT be flagged
        "from src.reactive.features import FeatureSet\n"  # allowed — must NOT be flagged
        "from src.reactive.params import ParamSnapshot\n"  # allowed — must NOT be flagged
    )
    violations = _check_sm_import_surface(bad_source)
    assert "import numpy" in violations
    assert "from src.micro.signal_model (src not in allowlist)" in violations
    # The plain `import src.micro.signal_model` form must ALSO be caught — the
    # exact-allowlist is enforced in both AST branches, not just `ImportFrom`.
    assert "import src.micro.signal_model (src not in allowlist)" in violations
    # The overlay cores are features.py's deps, NOT the decision core's — the
    # tighter allowlist correctly flags them here.
    assert "from src.overlays.flow.bin_classifier (src not in allowlist)" in violations
    assert "from src.reactive.db (src not in allowlist)" in violations
    # The clean stdlib + allowed-reactive imports must NOT be reported.
    assert not any("math" in v for v in violations)
    assert not any("features" in v for v in violations)
    assert not any("params" in v for v in violations)


def test_signal_model_has_no_forbidden_io_or_numeric_imports():
    """R8.2: explicit, reviewer-legible guard against the named LLM/MCP/network/
    DB + heavy-numeric families as DIRECT signal_model.py imports. Redundant with
    the stdlib allowlist above by design — documents that R8.2's specific
    offenders (incl. numpy/scipy/pandas, which the design says this pure-arithmetic
    module never needs) are absent from the direct surface."""
    source = Path(signal_model_mod.__file__).read_text()
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    for root in roots:
        for forbidden in _FORBIDDEN_SM_IMPORT_SUBSTRINGS:
            assert forbidden not in root, (
                f"signal_model imports forbidden I/O/LLM/heavy-numeric family "
                f"{root!r} (matched {forbidden!r}) — violates R8.2 (no LLM/MCP/"
                "live-DB; the decision core is pure `math` arithmetic)"
            )


def test_signal_model_does_not_import_intraday_model_by_root_module():
    """R1 adjacent / R8.3: belt-and-braces — `src.micro` must not appear AT ALL in
    signal_model.py's direct imports. The intraday `/micro` model is a sibling
    that this design explicitly leaves untouched (it reuses only the *pattern*,
    not the module); a direct `src.micro.*` dependency would couple the days-to-
    weeks Edge core to the intraday module and is forbidden here (overlays/
    indicators reuse lives behind the `features` adapter, not in the core)."""
    source = Path(signal_model_mod.__file__).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("src.micro"), (
                    f"signal_model.py directly imports {alias.name} — the decision "
                    "core must not depend on the intraday `src.micro` module"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                assert not node.module.startswith("src.micro"), (
                    f"signal_model.py directly imports from {node.module} — the "
                    "decision core must not depend on the intraday `src.micro` module"
                )


# --- End-to-end conflict→HOLD through the public `decide` (design line 241) --
#
# 2.2 proved a surviving cross-family conflict aggregates to `s≈0` at the
# AGGREGATION level. 3.3 closes the loop: assert that same feature set actually
# EMITS HOLD through the full public `decide` pipeline (s≈0 → P≈0.5 ≤ θ → HOLD)
# — the conservative-Edge default surfaced end-to-end, not just in the score.


# A surviving-conflict feature set: trend(+1) vs meanrev(−1), flow=0
# (trend_strength=0 ⇒ meanrev UNDAMPED) ⇒ s≈0 under near-equal weights.
_CONFLICT = _fs(trend_vote=1.0, flow_vote=0.0, meanrev_vote=-1.0)


def test_decide_surviving_conflict_holds_via_full_pipeline_long():
    """The conflict→HOLD design default (line 241) END-TO-END through `decide`:
    a surviving trend/meanrev conflict (s≈0) yields P≈0.5, which is ≤ the 0.55
    default threshold ⇒ HOLD. Crucially `reason is None` — this is a REAL
    sub-threshold derivation (the conservative-Edge prudence), NOT an abstain;
    and no actionable sizing hint. Uses EQUAL_WEIGHTS so s is an exact zero."""
    snap = ParamSnapshot(
        weights=EQUAL_WEIGHTS,
        temperature=DEFAULTS.temperature,
        threshold=0.55,
        calibration=DEFAULTS.calibration,
        code_version="reactive-signal-model@vT",
        param_version="equalw@vT",
    )
    d = decide(_CONFLICT, "LONG", snap)
    assert d.probability == pytest.approx(0.5)  # s≈0 → signed 0 → P 0.5
    assert d.decision == "HOLD"
    assert d.reason is None  # a derived sub-threshold HOLD, not an abstain
    assert d.sizing_hint is None
    assert d.non_final is True


def test_decide_surviving_conflict_holds_for_both_directions():
    """The conflict→HOLD default is direction-symmetric: the SAME surviving
    conflict (s≈0) HOLDs whether the caller asks LONG or SHORT (project only
    flips the sign of ~0, leaving P≈0.5 ≤ θ either way). Reinforces that the
    HOLD is the no-edge default, not a side-specific artifact."""
    snap = ParamSnapshot(
        weights=EQUAL_WEIGHTS,
        temperature=DEFAULTS.temperature,
        threshold=0.55,
        calibration=DEFAULTS.calibration,
        code_version="c",
        param_version="p",
    )
    for direction in ("LONG", "SHORT"):
        d = decide(_CONFLICT, direction, snap)
        assert d.decision == "HOLD"
        assert d.reason is None
        assert d.probability == pytest.approx(0.5)


def test_decide_damped_conflict_becomes_actionable_contrast():
    """CONTRAST pair (mirrors the 2.2 aggregation-level contrast, now end-to-end):
    the SAME opposing trend(+1)/meanrev(−1) but with flow=+1 (trend_strength=1)
    damps the meanrev term to 0 ⇒ trend+flow win ⇒ s decisive ⇒ P > θ ⇒ the
    decision becomes the actionable LONG. Proves the damping is what (de)permits
    the conflict-HOLD through the full `decide`, not an incidental zero."""
    snap = ParamSnapshot(
        weights=EQUAL_WEIGHTS,
        temperature=DEFAULTS.temperature,
        threshold=0.55,
        calibration=DEFAULTS.calibration,
        code_version="c",
        param_version="p",
    )
    surviving = decide(_CONFLICT, "LONG", snap)  # flow=0 → s≈0 → HOLD
    damped = decide(
        _fs(trend_vote=1.0, flow_vote=1.0, meanrev_vote=-1.0), "LONG", snap
    )
    assert surviving.decision == "HOLD"
    assert damped.decision == "LONG"
    assert damped.probability > surviving.probability


# --- End-to-end determinism spanning ALL decide outcome classes (R8.1) ------
#
# The 2.4 `test_decide_is_deterministic_full_decision_equality` spans actionable
# / sub-threshold-HOLD / tightened-HOLD / invalid-direction / insufficient_history.
# It does NOT span the surviving-conflict→HOLD path nor the `degenerate_features`
# abstain — close both so byte-identical determinism is asserted across EVERY
# `decide` outcome class (the final inner-ring determinism gate).


def test_decide_deterministic_across_conflict_and_degenerate_paths():
    """Byte-identical `ReactiveDecision` (frozen dataclass `==`) on the two
    outcome classes the 2.4 determinism test omitted: the surviving-conflict→HOLD
    derivation and the `degenerate_features` abstain. Completes R8.1 coverage so
    determinism holds across actionable / sub-threshold-HOLD / conflict-HOLD /
    tightened-HOLD / invalid-direction / insufficient_history / degenerate."""
    snap = ParamSnapshot(
        weights=EQUAL_WEIGHTS,
        temperature=DEFAULTS.temperature,
        threshold=0.55,
        calibration=DEFAULTS.calibration,
        code_version="reactive-signal-model@vT",
        param_version="equalw@vT",
    )
    cases = [
        (_CONFLICT, "LONG", None),                                 # surviving conflict → HOLD
        (_CONFLICT, "SHORT", None),                                # conflict, other side
        (FeatureFailure(reason="degenerate_features"), "LONG", None),  # degenerate abstain
    ]
    for feats, direction, runtime in cases:
        a = decide(feats, direction, snap, runtime_threshold=runtime)  # type: ignore[arg-type]
        b = decide(feats, direction, snap, runtime_threshold=runtime)  # type: ignore[arg-type]
        assert a == b


def test_decide_full_decision_equality_spans_every_outcome_class():
    """The consolidated determinism gate: one parametrize-free sweep asserting
    byte-identical `decide` output across ALL SEVEN outcome classes in a single
    test, so a future refactor that introduces nondeterminism on any path is
    caught here regardless of which earlier per-class test it slips past."""
    snap = ParamSnapshot(
        weights=EQUAL_WEIGHTS,
        temperature=DEFAULTS.temperature,
        threshold=0.55,
        calibration=DEFAULTS.calibration,
        code_version="reactive-signal-model@vT",
        param_version="equalw@vT",
    )
    cases = [
        (_STRONG_LONG, "LONG", None),                              # actionable LONG
        (_fs(-1.0, -1.0, -1.0), "SHORT", None),                    # actionable SHORT
        (_FLAT, "LONG", None),                                     # sub-threshold HOLD
        (_CONFLICT, "LONG", None),                                 # conflict HOLD
        (_STRONG_LONG, "LONG", 0.99),                              # tightened to HOLD
        (_STRONG_LONG, None, None),                                # invalid direction
        (FeatureFailure(reason="insufficient_history"), "LONG", None),
        (FeatureFailure(reason="degenerate_features"), "SHORT", None),
    ]
    for feats, direction, runtime in cases:
        a = decide(feats, direction, snap, runtime_threshold=runtime)  # type: ignore[arg-type]
        b = decide(feats, direction, snap, runtime_threshold=runtime)  # type: ignore[arg-type]
        assert a == b
