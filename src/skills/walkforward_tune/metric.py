"""Walkforward-tuning-loop survival-net metric + calibration leaf (task 2.2).

``score(outcome_records: list[OutcomeRecord]) -> OOSSample`` turns ONE config's
per-period replay ``OutcomeRecord``s over ONE CPCV out-of-sample partition into
the ``OOSSample`` the gate consumes via ``OOSMatrix``. It realizes:

  * R4.3 — the **survival-net risk-adjusted return** metric, reflecting the §13
    ordering ``Survive ⊳ Preserve ⊳ Edge ⊳ Return`` (docs/exploration §13):
    survival breaches / stop-outs **dominate** the ranking. The §13 structuring
    rule is *lexicographic, not weighted* — "never trade a higher link for any
    amount of a lower one; no return improvement ever buys down survival." This
    leaf reduces that ordering to a single scalar the (deterministic, pure)
    gate can rank: a series that took even one survival breach scores strictly
    below any clean series, regardless of how much larger its raw P&L is.
  * R4.4 — **calibration** of the model's derived probabilities (reliability
    over the OOS partition) as a behavioral evaluation input, *not only*
    hit-rate or P&L. Delegated to ``src.calibration.metrics.brier_score`` (the
    landed Brier/reliability home) — NOT reimplemented here (design §Evaluation
    Leaves; "calibration delegates to `calibration.metrics`").

Computed over the harness's ``OutcomeRecord``s — explicitly **NOT** the
``counterfactual_ledger`` (design §Allowed Dependencies / §Data Models "Reused":
the ledger is the slow-layer 4-bin sector-excess outer-ring substrate and cannot
express intraday-flat reactive P&L; reactive P&L comes from the replay records).

Pure leaf (P1 / design §Dependency direction `types -> {... metric ...}`):
stdlib + numpy + `calibration.metrics` only. NO other-leaf import, no MCP, no
DB, no consumer-spec import, no LLM. Determinism (R9.1): identical records ⇒
identical ``OOSSample``.

Requirements: 4.3, 4.4.
"""

from __future__ import annotations

import numpy as np

from src.calibration.metrics import brier_score
from src.calibration.scorer import Label
from src.reactive.replay.types import OutcomeRecord
from src.skills.walkforward_tune.types import OOSSample

# --- The §13 Survive vocabulary -------------------------------------------
# The survival-grade events whose presence in an ``OutcomeRecord.survival_events``
# list means the Survive link was threatened (a stop-out, a forced flatten, a
# safe-mode tightening, a kill-switch halt, or an admit-reject). These are the
# events that DOMINATE the ranking (§13). Sourced from the harness's pinned
# ``OutcomeRecord`` docstring example (`["admit_reject","stop_hit","flatten",
# "safe_mode"]`, src/reactive/replay/types.py) and the landed event-queue
# vocabulary (`safe_mode`/`kill_switch`, src/reactive/daemon/event_queue.py).
# A string NOT in this set (e.g. a benign "lifecycle_open" bookkeeping marker)
# does NOT trigger the survival penalty — §13 is about the Survive link, not
# arbitrary trace markers.
SURVIVAL_BREACH_EVENTS: frozenset[str] = frozenset(
    {
        "stop_hit",
        "flatten",
        "safe_mode",
        "kill_switch",
        "admit_reject",
    }
)

# --- Lexicographic dominance unit (§13 realization) -----------------------
# §13's rule is lexicographic — "never trade a higher link for ANY amount of a
# lower one; no return improvement ever buys down survival." A fixed constant
# penalty only dominates while the risk-adjusted core stays under that constant
# — but this is a *levered* CFD layer, so a per-partition Sharpe is not bounded
# a-priori. So the per-breach penalty is computed RELATIVE to the BREACHING
# series' own clean-core magnitude (see ``score``): a unit strictly larger than
# that series' |clean_core|, so one breach pulls it to ≤ -BREACH_PENALTY_MARGIN
# — strictly below any breach-free series with a non-negative clean core,
# regardless of how large the breaching series' raw return is. (This dominates
# the §13-relevant case — a breaching series with a large positive return; it
# does NOT order a breaching series below a pathologically negative breach-free
# comparator with clean core < -BREACH_PENALTY_MARGIN. The gate's §13
# lexicographic guard, task 2.3, is the authoritative backstop; this scalar is
# the ranking device feeding it.) Derived, not an asserted probability (P15).
BREACH_PENALTY_MARGIN: float = 1.0

# Calibration weight: the Brier score lives in [0, 1] (0 = perfect, 1 = worst).
# It is folded into the risk-adjusted core as a bounded discount so a
# confidently-wrong model's edge is discounted (R4.4). It is an Edge-link
# concern; the structural breach penalty dominates it by construction, so
# calibration NEVER outranks survival (§13: Edge/Return never buys down Survive).
CALIBRATION_WEIGHT: float = 1.0


def _favorable(rec: OutcomeRecord) -> bool:
    """The binary calibration outcome for one record (R4.4).

    ``predicted_probability`` is the softmax P at fire = P(the directional call
    is right); the binary outcome is whether that directional call was VINDICATED
    — read DIRECTION-AWARE off the position side (``decision``) and the realized
    price-direction verdict (``realized_label``):

      - a ``LONG`` call is favorable iff price went up   (``realized_label`` BUY),
      - a ``SHORT`` call is favorable iff price went down (``realized_label`` SELL).

    This reads all of the mandated fields LITERALLY (``decision`` +
    ``realized_label``) AND is the direction-correct definition. ``realized_label``
    alone is a *price-direction* verdict (BUY=up, SELL=down per ``scorer._is_hit``)
    — it does NOT encode position success without the side, so keying favorability
    off ``realized_label is Label.BUY`` would mis-score a winning SHORT (price
    fell, label SELL, but the short WON) as a calibration miss. Pairing the side
    with the label fixes that.

    This is mathematically equivalent to the harness's continuous calibration
    target ``realized_outcome > 0`` (design line 236: "the day's realized
    round-trip return") — a vindicated directional call has a positive round-trip
    return — so the two agree in all four win/lose × LONG/SHORT cases.

    Called ONLY on records that already passed ``_is_calibration_fire`` (an
    actionable LONG/SHORT with a non-None probability) — ``score`` excludes HOLD /
    None-probability records from the calibration sample BEFORE this is reached
    (the consumed harness emits a probability only on an actual fire; a flat/HOLD
    day carries ``predicted_probability=None`` and no derived probability to
    calibrate, src/reactive/replay/outcomes.py:103). The ``return False`` HOLD
    fall-through below is therefore DEFENSIVE (it is never the live path) — a HOLD
    that somehow reached here would be a not-favorable stand-aside, but it cannot,
    because it is filtered out of the Brier sample upstream.
    """
    if rec.decision == "LONG":
        return rec.realized_label is Label.BUY
    if rec.decision == "SHORT":
        return rec.realized_label is Label.SELL
    return False


def _is_calibration_fire(rec: OutcomeRecord) -> bool:
    """True iff this record contributes a calibration (Brier) sample point (R4.4).

    A record carries a calibration signal ONLY when the model actually FIRED a
    directional call with a derived probability: an actionable ``LONG``/``SHORT``
    AND a non-None ``predicted_probability``. The consumed harness emits
    ``predicted_probability=None`` on every flat/HOLD day (no model fire —
    src/reactive/replay/outcomes.py:103 ``rd.probability if rd is not None else
    None``, docstring :87 "flat day → decision HOLD, probability None"), and a
    real CPCV OOS partition is HOLD-dominated. Such records have NO derived
    probability to score, so they are excluded from the Brier sample (R4.4 is the
    calibration of the model's *derived* probabilities — not a forced miss for a
    correct stand-aside). The ``predicted_probability is not None`` guard is also
    the crash-fix: it prevents ``float(None)`` over a HOLD record.
    """
    return rec.decision in ("LONG", "SHORT") and rec.predicted_probability is not None


# Absolute + relative tolerance for "effectively constant" (zero-variance)
# detection. A literal ``std == 0`` test is FRAGILE: a constant decimal like
# 0.02 is not exactly representable, so ``np.std`` of ten identical 0.02s is
# ~3.7e-18 (floating-point noise), not 0 — which a naive ``mean / std`` would
# blow up to a ~5e15 garbage "Sharpe". A series is treated as constant iff its
# std is below ``_VAR_ATOL + _VAR_RTOL * max|x|`` (scale-relative so it holds at
# any return magnitude). Origin: numerical-stability fix, near-constant OOS
# partition.
_VAR_ATOL: float = 1e-12
_VAR_RTOL: float = 1e-9


def _is_constant(x: np.ndarray) -> bool:
    """True iff the series has negligible (FP-noise-level) dispersion (see tols)."""
    if x.size < 2:
        return True
    sd = float(x.std(ddof=0))
    scale = float(np.max(np.abs(x))) if x.size else 0.0
    return sd <= _VAR_ATOL + _VAR_RTOL * scale


def _sample_skewness(x: np.ndarray) -> float:
    """Fisher–Pearson sample skewness (population convention, g1).

    Degenerate samples (n < 2 or effectively-constant) return 0.0 so the gate
    reads a finite stat rather than NaN or a noise-amplified value. g1 =
    m3 / m2**1.5 over central moments.
    """
    if x.size < 2 or _is_constant(x):
        return 0.0
    d = x - x.mean()
    m2 = float(np.mean(d**2))
    if m2 <= 0.0:
        return 0.0
    m3 = float(np.mean(d**3))
    return m3 / (m2**1.5)


def _excess_kurtosis(x: np.ndarray) -> float:
    """Fisher (excess) kurtosis (population convention, g2 = m4/m2**2 - 3).

    Degenerate samples (n < 2 or effectively-constant) return 0.0 (finite).
    """
    if x.size < 2 or _is_constant(x):
        return 0.0
    d = x - x.mean()
    m2 = float(np.mean(d**2))
    if m2 <= 0.0:
        return 0.0
    m4 = float(np.mean(d**4))
    return m4 / (m2**2) - 3.0


def _risk_adjusted_return(x: np.ndarray) -> float:
    """The per-partition RISK-ADJUSTED return (a Sharpe-like ratio): mean / std.

    The field is the survival-net **risk-adjusted** return (types.py / design
    §Evaluation Leaves), and the gate consumes it as the Sharpe input to its
    PSR/DSR (Bailey–López de Prado) — ``OOSSample`` carries ``skew`` /
    ``kurtosis`` / ``n_obs`` (the PSR's other arguments) and NO separate std
    field, so the risk adjustment must live IN this scalar. A raw mean would not
    be risk-adjusted: two series with the same mean but different volatility must
    rank differently (higher volatility ⇒ lower risk-adjusted return).

    Conventions:
      - sample standard deviation (ddof=1) so a single observation has no defined
        spread; n < 2 falls back to the mean itself (finite, not NaN).
      - an EFFECTIVELY-constant series (every return identical, up to
        floating-point representation noise — see ``_is_constant``) has an
        undefined Sharpe (mean / ~0); it falls back to the mean — a constant
        non-zero return is finite and its ranking vs other constants is preserved
        by the mean. This guard is what prevents a near-constant 0.02 series from
        producing a ~5e15 garbage Sharpe from FP noise.
    """
    if x.size < 2 or _is_constant(x):
        return float(x.mean())
    sd = float(x.std(ddof=1))
    return float(x.mean()) / sd


def score(outcome_records: list[OutcomeRecord]) -> OOSSample:
    """Score one config's per-partition ``OutcomeRecord``s into an ``OOSSample``.

    Pure (R9.1 determinism). Folds three things into the single
    ``survival_net_return`` scalar — in §13 precedence order:

      3. **Edge/Return core (risk-adjusted):** the per-partition Sharpe-like
         risk-adjusted return (mean / std of per-period ``realized_outcome``) —
         the gate's PSR/DSR Sharpe input (there is no separate std field on
         ``OOSSample``).
      2. **Calibration discount (R4.4):** the Brier score of the derived
         probabilities vs the direction-aware favorable outcome (LONG vindicated
         by an up-label, SHORT by a down-label — see ``_favorable``; equivalent
         to ``realized_outcome > 0``), via ``calibration.metrics.brier_score`` —
         a worse Brier discounts the edge. The Brier sample is ONLY the actionable
         fires (``_is_calibration_fire``: LONG/SHORT with a non-None probability);
         HOLD / None-probability stand-aside days are EXCLUDED (the harness emits
         no derived probability on a flat day — src/reactive/replay/outcomes.py:103
         — and a real OOS partition is HOLD-dominated). A no-fire partition gets a
         neutral zero discount (no calibration signal), never a ``brier_score([])``
         ValueError.
      1. **Survive (dominant):** a per-breach penalty sized strictly larger than
         the breaching series' own (core − calibration) magnitude, so even one
         survival-grade event drives the scalar to ≤ -BREACH_PENALTY_MARGIN —
         strictly below any breach-free series with a non-negative clean core,
         regardless of how large the breaching series' raw return is
         (lexicographic dominance for the §13-relevant case, R4.3 / §13). The
         gate's §13 lexicographic guard (task 2.3) is the authoritative backstop.

    Skew / kurtosis of the per-period return distribution are reported alongside
    (the gate's PSR/MinTRL is skew/kurtosis-aware).

    Raises ``ValueError`` on an empty record list — a zero-length OOS partition
    has no defined risk-adjusted return; the gate's MinTRL sufficiency is what
    rejects *few*-but-nonzero observations, not this leaf.
    """
    if not outcome_records:
        raise ValueError("cannot score an empty OutcomeRecord list (degenerate OOS partition)")

    # The return series is ``realized_outcome`` — the harness's "day's realized
    # round-trip return" (design line 236) and one of the four MANDATED read
    # fields (the read-list is realized_outcome / survival_events /
    # predicted_probability / realized_label — it excludes ``total_return_pnl``,
    # which is the harness-side fidelity check's field, not the scorer's).
    returns = np.asarray([rec.realized_outcome for rec in outcome_records], dtype=float)
    n_obs = int(returns.size)

    # 3. Edge/Return core: the per-partition RISK-ADJUSTED return (Sharpe-like).
    risk_adjusted = _risk_adjusted_return(returns)

    # 2. Calibration discount (R4.4) — delegate to calibration.metrics.brier_score,
    #    over (predicted_probability, direction-aware favorability of the call).
    #    ONLY actionable LONG/SHORT fires with a non-None probability enter the
    #    calibration sample (see ``_is_calibration_fire``): the consumed harness
    #    emits ``predicted_probability=None`` on every flat/HOLD day
    #    (src/reactive/replay/outcomes.py:103/:118 — "flat day → decision HOLD,
    #    probability None"), and a real CPCV OOS partition is HOLD-dominated. A
    #    stand-aside carries NO calibration signal (R4.4: calibration of the
    #    model's DERIVED probabilities — there is no derived probability on a
    #    no-fire day), so HOLD/None records are excluded rather than scored as a
    #    forced MISS (which would both crash on float(None) and distort R4.4).
    fires = [rec for rec in outcome_records if _is_calibration_fire(rec)]
    if fires:
        scores = [float(rec.predicted_probability) for rec in fires]
        favorable = [_favorable(rec) for rec in fires]
        brier = brier_score(scores, favorable)  # [0, 1]; lower is better
        calibration_discount = CALIBRATION_WEIGHT * brier
    else:
        # No fires in this OOS partition (e.g. a fully-HOLD partition — the common
        # real case). The calibration sample is empty; ``brier_score([], [])``
        # would raise ValueError (calibration/metrics.py:45). A no-fire partition
        # has no calibration signal → a neutral zero discount (the gate's MinTRL
        # sufficiency, task 2.3, is what rejects thin partitions, not this leaf).
        calibration_discount = 0.0

    # The clean (breach-free) core the survival penalty must dominate.
    clean_core = risk_adjusted - calibration_discount

    # 1. Survive (dominant) — total survival-grade breach count across all records.
    breach_count = sum(
        1
        for rec in outcome_records
        for ev in rec.survival_events
        if ev in SURVIVAL_BREACH_EVENTS
    )
    # §13 dominance: one breach's penalty exceeds this series' own |clean_core| +
    # margin, so the breaching series lands at ≤ -BREACH_PENALTY_MARGIN — below any
    # breach-free series with a non-negative clean core, however large THIS series'
    # raw return is. The unit is derived from the score's own terms (not a
    # magnitude-assumed constant). The gate's §13 lexicographic guard (task 2.3)
    # is the authoritative backstop for the full ordering.
    penalty_unit = abs(clean_core) + BREACH_PENALTY_MARGIN
    survival_penalty = penalty_unit * breach_count

    survival_net_return = clean_core - survival_penalty

    return OOSSample(
        survival_net_return=survival_net_return,
        skew=_sample_skewness(returns),
        kurtosis=_excess_kurtosis(returns),
        n_obs=n_obs,
    )
