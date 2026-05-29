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

import pytest

from src.reactive.features import FeatureSet
from src.reactive.params import DEFAULTS
from src.reactive.signal_model import aggregate_score, project
from src.reactive.types import Weights

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
