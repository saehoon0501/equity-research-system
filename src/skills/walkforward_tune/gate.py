"""Deterministic promotion gate (task 2.3) — THE statistical crux of the loop.

``evaluate_gate(matrix, params) -> GateVerdict`` turns the CPCV out-of-sample
matrix into a reproducible promote/decline verdict. It is the *entire*
quantitative defense between an LLM-authored config and the (paper) book
(requirements §Introduction), so every figure is a DERIVED metric (P15) and any
insufficiency / degeneracy / uncertainty fails toward ``promote=false`` (P7 —
decisions only get more conservative downstream).

THE ORDER (design §gate "Responsibilities & Constraints"; R5.1):
  1. select the highest survival-net config from the trial set (R4.5);
  2. PSR / MinTRL sufficiency (skew/kurtosis-aware, vs a non-trivial benchmark
     Sharpe) — insufficient ⇒ decline (R5.4);
  3. DSR + PBO/CSCV — overfitting-corrected; DSR is deflated by ``effective_n``,
     and MinBTL DECLINES when the trial-set breadth exceeds the available
     history (a sufficiency gate, never a downward deflation cap; R5.1/5.2/5.3);
  4. decision-rule — OOS margin vs the incumbent / consecutive cycles /
     anti-churn hysteresis (R5.5);
  5. §13 lexicographic guard — no Edge/Return gain at the cost of a worse
     Survive/Preserve (R6.3).
Pure + deterministic (P14): no I/O, no LLM, no clock, no DB. **Never** consults
an in-sample Sharpe (R4.5/R5.5) — the verdict carries no IS-Sharpe field and the
gate ignores any ``is_sharpe`` key in ``trial_metadata``.

====================================================================
FORMULA SOURCES — cited per-statistic below. There is NO repo precedent for
these (Bailey & López de Prado), so the inner-ring tests anchor to values
EXTERNAL to this implementation (the standard-normal table + the MinTRL→PSR=α
roundtrip + a hand-traced CSCV matrix), and the reviewer verifies
formula-vs-source, not just self-consistency.

  [BLdP-2012] Bailey & López de Prado (2012), "The Sharpe Ratio Efficient
              Frontier", Journal of Risk — PSR, MinTRL, and the Mertens/Lo
              SR-estimator variance D².
  [BLdP-2014] Bailey & López de Prado (2014), "The Deflated Sharpe Ratio:
              Correcting for Selection Bias, Backtest Overfitting and
              Non-Normality", Journal of Portfolio Management — DSR + the
              expected-maximum-Sharpe SR₀.
  [BBLZ-2014] Bailey, Borwein, López de Prado & Zhu (2014), "The Probability of
              Backtest Overfitting" — CSCV / PBO via the logit of the IS-best
              config's OOS rank.

⚠️ SPEC-vs-SOURCE: two prose invariants in this loop's spec are INVERTED
relative to the published formulas, and the source wins:
  • spec "DSR rises with trial count" → WRONG. DSR *falls* with N: SR₀ rises
    with N (more trials ⇒ a higher bar), and that downward adjustment IS the
    deflation.  (See ``expected_max_sharpe`` / ``deflated_sharpe_ratio``.)
  • spec "PSR/MinTRL grows with negative skew" → only the MinTRL half is right.
    PSR *falls* with negative skew (it is designed to penalise it); MinTRL
    *rises* (you need a longer track record). Both follow from D² rising when
    γ₃ < 0 and SR̂ > 0.  (See ``probabilistic_sharpe_ratio`` / ``min_track_record_length``.)
====================================================================

CONVENTIONS THIS LEAF DEFINES (metric.py — task 2.2 — does not exist yet, so the
gate is *defining*, not reading, the ``trial_metadata`` layout; this is the
integration seam flagged in the task notes — keep it in sync when metric lands):
  • Per-config Sharpe SR̂ is computed over the config's per-partition
    ``survival_net_return`` SERIES (one scalar per CPCV partition); the
    skew/kurtosis fed to the statistics are the n_obs-weighted means of the
    per-partition ``skew`` / ``kurtosis``; the effective track-record length
    ``n`` for PSR/DSR/MinTRL is ``Σ n_obs`` across the config's partitions (the
    statistically meaningful observation count, R5.4).
  • ``trial_metadata`` keys the gate reads (all optional; absent ⇒ conservative
    default):
      - ``"effective_n"`` (int): the effective independent-trial count to
        deflate against (R5.2). Absent ⇒ the raw config count. NOT clamped
        downward by ``min_btl`` — a lower effective_n would UNDER-deflate (lower
        SR₀ ⇒ higher DSR ⇒ easier promotion), the opposite of P7. MinBTL is a
        separate history-sufficiency DECLINE gate (R5.3), see below.
      - ``"sr_variance"`` (float): V for SR₀ (the cross-sectional variance of
        the trial set's SR̂s, R5.1/BLdP-2014). Absent ⇒ derived from the
        per-config SR̂ estimates.
      - ``"lexicographic"`` (dict): ``{config_id: {"survive","preserve","edge",
        "return"}}`` + a ``"__incumbent__"`` entry — the SEPARABLE §13 scores
        the guard needs (``survival_net_return`` alone cannot drive the guard).
        ABSENT for the selected config ⇒ ``lexicographic_ok`` UNCONFIRMABLE ⇒
        ``promote=false`` (P7).
      - ``"is_sharpe"`` / ``"in_sample_sharpe"``: IGNORED by design (R4.5/R5.5).

Requirements: 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.2, 6.3.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Sequence

from src.skills.walkforward_tune.types import (
    GateParams,
    GateVerdict,
    OOSMatrix,
    OOSSample,
)

# Euler–Mascheroni constant — the SR₀ expected-maximum-Sharpe weight [BLdP-2014].
_EULER_GAMMA = 0.5772156649015329
# Default confidence for the MinTRL sufficiency test (PSR reaches this α at
# n = MinTRL). 0.95 is the conventional B&LdP track-record significance level.
_MIN_TRL_ALPHA = 0.95
# Excess→full kurtosis offset: a normal distribution has full kurtosis 3.
_NORMAL_KURTOSIS = 3.0


# ===========================================================================
# Math primitives — a small in-module normal CDF + inverse (no scipy, to keep
# the inner ring lean per the task constraints). Anchored in the tests to the
# published standard-normal table (Φ(1.959964)=0.975, Φ⁻¹(0.975)=1.959964).
# ===========================================================================


def norm_cdf(x: float) -> float:
    """Standard-normal CDF Φ(x) via the stdlib error function.

    Φ(x) = ½·(1 + erf(x/√2)). Exact to machine precision — no approximation.
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _acklam_ppf(p: float) -> float:
    """Acklam's rational approximation to the inverse normal CDF (raw).

    Peter Acklam's piecewise rational approximation; the public ``norm_ppf``
    polishes it with one Halley step to reach ~1e-12 (matching the exact erf CDF
    by bisection), so the SR₀/MinTRL anchors land on their true values, not on a
    1e-3-biased tail approximation.
    """
    a = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
    b = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00)
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF Φ⁻¹(p) for p in (0, 1).

    Acklam approximation + one Halley refinement (Acklam's recommended polish),
    accurate to ~1e-12. ``p`` at the open-interval boundary is degenerate
    (Φ⁻¹(0) = -∞, Φ⁻¹(1) = +∞) and raises — callers (e.g. the N=1 SR₀ case)
    treat that as the degeneracy that forces no-promote.
    """
    if not (0.0 < p < 1.0):
        raise ValueError(f"norm_ppf domain is the open interval (0,1); got {p}")
    x = _acklam_ppf(p)
    # One Halley step against the exact erf CDF: e = Φ(x) - p.
    e = norm_cdf(x) - p
    u = e * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    x = x - u / (1.0 + x * u / 2.0)
    return x


def full_kurtosis(excess_kurtosis: float) -> float:
    """Convert EXCESS kurtosis to FULL kurtosis (γ₄ = excess + 3).

    ``OOSSample.kurtosis`` is pinned as EXCESS kurtosis (types.py); the B&LdP
    variance term D² wants FULL kurtosis (γ₄ = 3 for a normal). This single
    conversion lives here so it cannot be silently forgotten — omitting the +3
    corrupts every PSR/DSR/MinTRL.
    """
    return excess_kurtosis + _NORMAL_KURTOSIS


# ===========================================================================
# The four Bailey & López de Prado statistics.
# ===========================================================================


def _sr_estimator_variance_term(sr_hat: float, skew: float, excess_kurt: float) -> float:
    """The Mertens/Lo SR-estimator variance term D² [BLdP-2012].

    D² = 1 - γ₃·SR̂ + ((γ₄ - 1)/4)·SR̂²,  γ₄ = FULL kurtosis.

    σ̂(SR̂)² = D²/(n-1) is the *sampling* variance of the Sharpe estimator — a
    function of the OBSERVED Sharpe and OBSERVED moments, never of the threshold
    tested against (so DSR keeps SR̂ here and only swaps the numerator threshold
    to SR₀; see ``deflated_sharpe_ratio``). With SR̂ > 0, γ₃ < 0 makes -γ₃·SR̂
    POSITIVE ⇒ D² rises (this is why PSR falls / MinTRL rises with negative skew).
    """
    g4 = full_kurtosis(excess_kurt)
    return 1.0 - skew * sr_hat + ((g4 - 1.0) / 4.0) * sr_hat * sr_hat


def probabilistic_sharpe_ratio(
    sr_hat: float,
    sr_benchmark: float,
    n: float,
    skew: float,
    excess_kurt: float,
) -> float:
    """Probabilistic Sharpe Ratio PSR(SR*) [BLdP-2012].

    PSR(SR*) = Φ[ (SR̂ - SR*)·√(n-1) / D ],  D² = the estimator-variance term.

    The probability the true Sharpe exceeds the benchmark SR*, given the sample
    length ``n`` and the first four moments. Source-correct directions: PSR
    FALLS with negative skew and with fatter tails (both raise D²).
    """
    if n <= 1:
        return 0.0  # no (n-1) track record ⇒ no significance.
    d2 = _sr_estimator_variance_term(sr_hat, skew, excess_kurt)
    if d2 <= 0.0:
        return 0.0  # degenerate variance term ⇒ no significance (fail-safe).
    z = (sr_hat - sr_benchmark) * math.sqrt(n - 1.0) / math.sqrt(d2)
    return norm_cdf(z)


def min_track_record_length(
    sr_hat: float,
    sr_benchmark: float,
    skew: float,
    excess_kurt: float,
    alpha: float = _MIN_TRL_ALPHA,
) -> float:
    """Minimum Track Record Length MinTRL [BLdP-2012].

    MinTRL = 1 + D²·( Φ⁻¹(α) / (SR̂ - SR*) )².

    The smallest ``n`` at which PSR(SR*) reaches confidence α — i.e. the
    track-record length needed to call the Sharpe significant. RISES with
    negative skew / fat tails (D² rises). If SR̂ ≤ SR* the candidate never beats
    the benchmark ⇒ an infinitely long record can never confirm it ⇒ +∞ (the
    gate maps that to no-promote).
    """
    excess_sr = sr_hat - sr_benchmark
    if excess_sr <= 0.0:
        return math.inf
    d2 = _sr_estimator_variance_term(sr_hat, skew, excess_kurt)
    z_alpha = norm_ppf(alpha)
    return 1.0 + d2 * (z_alpha / excess_sr) ** 2


def expected_max_sharpe(sr_variance: float, n_trials: int) -> float:
    """Expected maximum Sharpe SR₀ across ``n_trials`` independent trials [BLdP-2014].

    SR₀ = √V · ( (1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e)) ),  γ = Euler–Mascheroni.

    The benchmark a strategy must clear to be significant AFTER multiple-testing
    selection: Φ⁻¹(1 - 1/N) RISES with N, so SR₀ rises with the trial count —
    the deflation. N < 2 is degenerate (Φ⁻¹(1 - 1/1) = Φ⁻¹(0) = -∞); callers
    treat that as the reason a single-config trial set cannot earn a pass.
    """
    if n_trials < 2:
        raise ValueError("expected_max_sharpe is degenerate for N < 2 (Φ⁻¹(0) = -∞)")
    if sr_variance < 0.0:
        raise ValueError("sr_variance must be non-negative")
    q1 = norm_ppf(1.0 - 1.0 / n_trials)
    q2 = norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(sr_variance) * ((1.0 - _EULER_GAMMA) * q1 + _EULER_GAMMA * q2)


def deflated_sharpe_ratio(
    sr_hat: float,
    n: float,
    skew: float,
    excess_kurt: float,
    sr_variance: float,
    n_trials: int,
) -> float:
    """Deflated Sharpe Ratio DSR = PSR(SR₀) [BLdP-2014].

    DSR substitutes the expected-maximum-Sharpe SR₀ (the multiple-testing bar)
    in as the PSR benchmark; the variance term keeps the OBSERVED SR̂ (the 2012
    PSR convention). DSR FALLS as ``n_trials`` rises (SR₀ rises) — that is the
    deflation, and it is why the spec's "DSR rises with trial count" prose is
    inverted (the source wins).
    """
    sr0 = expected_max_sharpe(sr_variance, n_trials)
    return probabilistic_sharpe_ratio(
        sr_hat=sr_hat, sr_benchmark=sr0, n=n, skew=skew, excess_kurt=excess_kurt
    )


def probability_of_backtest_overfitting(matrix: OOSMatrix, n_subsets: int) -> float:
    """Probability of Backtest Overfitting via CSCV [BBLZ-2014].

    Combinatorially-Symmetric Cross-Validation. The performance matrix has rows
    = CPCV partitions and columns = trial-set configs (values =
    ``survival_net_return``). Partition the S partition-subsets into all
    C(S, S/2) train(IS)/test(OOS) combinations; for each: pick the IS-best
    config, find its OOS relative rank ω = rank/(N+1) ∈ (0,1), take the logit
    λ = ln(ω/(1-ω)). PBO = fraction of combinations with λ ≤ 0 (the IS-best lands
    at or below the OOS median — the signature of overfitting).

    A degenerate matrix (too few partitions to form ``n_subsets`` subsets, <2
    configs) returns 1.0 (maximally overfit) so the gate fails toward no-promote.

    DELIBERATE CHOICE: within each subset the per-config performance is the MEAN
    ``survival_net_return`` (not a re-derived Sharpe). ``survival_net_return`` is
    already a risk-adjusted, §13-aware metric (design §metric), so ranking by its
    mean is the meaningful CSCV ranking here; this is a documented deviation from
    textbook CSCV (which ranks by in-/out-of-sample Sharpe of a raw return path).
    """
    config_ids = list(matrix.per_config.keys())
    n_configs = len(config_ids)
    if n_configs < 2:
        return 1.0
    # Build the row-per-partition return matrix; require equal, consistent length.
    series_lengths = {len(matrix.per_config[c]) for c in config_ids}
    if len(series_lengths) != 1:
        return 1.0
    n_partitions = series_lengths.pop()
    if n_partitions == 0 or n_subsets < 2 or n_partitions < n_subsets:
        return 1.0
    if n_partitions % n_subsets != 0:
        # Trim to the largest multiple of n_subsets (B&LdP use equal subsets).
        n_partitions = (n_partitions // n_subsets) * n_subsets
        if n_partitions < n_subsets:
            return 1.0
    rows: list[list[float]] = [
        [matrix.per_config[c][p].survival_net_return for c in config_ids]
        for p in range(n_partitions)
    ]
    block = n_partitions // n_subsets
    subsets = [list(range(i * block, (i + 1) * block)) for i in range(n_subsets)]

    def subset_perf(part_rows: Sequence[int], col: int) -> float:
        vals = [rows[r][col] for r in part_rows]
        return sum(vals) / len(vals)  # mean survival-net return over the subset.

    lambdas: list[float] = []
    for is_combo in combinations(range(n_subsets), n_subsets // 2):
        is_rows = [r for s in is_combo for r in subsets[s]]
        oos_rows = [r for s in range(n_subsets) if s not in is_combo for r in subsets[s]]
        is_perf = [subset_perf(is_rows, c) for c in range(n_configs)]
        best = max(range(n_configs), key=lambda c: is_perf[c])
        oos_perf = [subset_perf(oos_rows, c) for c in range(n_configs)]
        # Ascending order: rank 1 = worst OOS, rank N = best OOS.
        ascending = sorted(range(n_configs), key=lambda c: oos_perf[c])
        rank = ascending.index(best) + 1
        omega = rank / (n_configs + 1.0)  # ω ∈ (0,1), excludes the 0/1 endpoints.
        lambdas.append(math.log(omega / (1.0 - omega)))
    if not lambdas:
        return 1.0
    return sum(1 for lam in lambdas if lam <= 0.0) / len(lambdas)


# ===========================================================================
# Per-config aggregation over the CPCV partition series (the conventions this
# leaf defines — see the module docstring).
# ===========================================================================


def _sample_mean_std(values: Sequence[float]) -> tuple[float, float]:
    """Sample mean and ddof=1 standard deviation. (0, 0) for a single value."""
    n = len(values)
    m = sum(values) / n
    if n < 2:
        return m, 0.0
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    return m, math.sqrt(var)


def _config_stats(samples: list[OOSSample]) -> dict[str, float]:
    """Aggregate one config's per-partition series into the gate's inputs.

    SR̂ = mean / std of the per-partition ``survival_net_return`` series;
    skew / excess-kurtosis = n_obs-weighted means of the per-partition stats;
    ``n`` = Σ n_obs (the track-record length for PSR/DSR/MinTRL).
    """
    returns = [s.survival_net_return for s in samples]
    mean_r, std_r = _sample_mean_std(returns)
    total_obs = sum(s.n_obs for s in samples)
    if total_obs > 0:
        w_skew = sum(s.skew * s.n_obs for s in samples) / total_obs
        w_kurt = sum(s.kurtosis * s.n_obs for s in samples) / total_obs
    else:
        w_skew = w_kurt = 0.0
    sr_hat = mean_r / std_r if std_r > 0.0 else 0.0
    return {
        "mean_return": mean_r,
        "sr_hat": sr_hat,
        "skew": w_skew,
        "excess_kurt": w_kurt,
        "n": float(total_obs),
    }


def _decline(
    selected: str | None,
    reasons: list[str],
    *,
    dsr: float = 0.0,
    psr: float = 0.0,
    min_trl_met: bool = False,
    pbo: float = 1.0,
    effective_n: int = 0,
    lexicographic_ok: bool = False,
) -> GateVerdict:
    """Construct a conservative decline verdict (P7 fail-safe)."""
    return GateVerdict(
        promote=False,
        selected_config=selected,
        reasons=reasons,
        dsr=dsr,
        psr=psr,
        min_trl_met=min_trl_met,
        pbo=pbo,
        effective_n=effective_n,
        lexicographic_ok=lexicographic_ok,
    )


# ===========================================================================
# The gate.
# ===========================================================================


def evaluate_gate(matrix: OOSMatrix, params: GateParams) -> GateVerdict:
    """Deterministic promotion verdict over the CPCV OOS matrix.

    Runs the ordered sub-checks (select → PSR/MinTRL → DSR/PBO → decision-rule →
    §13 guard). ``promote=True`` only if EVERY sub-check passes for the selected
    config; ``reasons`` cite the binding sub-check. Any insufficiency /
    degeneracy / malformed input ⇒ ``promote=False`` (P7). Never consults an
    in-sample Sharpe (R4.5/R5.5). Identical inputs ⇒ identical verdict.
    """
    try:
        return _evaluate_gate_inner(matrix, params)
    except Exception as exc:  # noqa: BLE001 — fail toward no-promote (design §Error Handling).
        return _decline(None, [f"gate_exception: {type(exc).__name__}: {exc}"])


def _evaluate_gate_inner(matrix: OOSMatrix, params: GateParams) -> GateVerdict:
    per_config = matrix.per_config
    meta = matrix.trial_metadata or {}

    # ---- 0. Degenerate trial set ----------------------------------------
    if not per_config:
        return _decline(None, ["no_candidates: empty trial set"])
    # Any config with an empty partition series is malformed ⇒ no-promote.
    if any(len(s) == 0 for s in per_config.values()):
        return _decline(None, ["malformed_matrix: a config has an empty partition series"])

    # ---- 1. Select the highest survival-net config (R4.5) ---------------
    # Mean survival-net return across the config's CPCV partitions. Ties broken
    # by config id for determinism.
    stats = {cid: _config_stats(samples) for cid, samples in per_config.items()}
    selected = max(
        per_config.keys(), key=lambda cid: (stats[cid]["mean_return"], cid)
    )
    s = stats[selected]

    # ---- effective_N: the count the gate DEFLATES against (R5.2) --------
    # The orchestrator supplies a CONSERVATIVE effective independent-trial count
    # in trial_metadata (correlated LLM-proposed sweeps reduced to an effective
    # count — design line 322; absent ⇒ the raw config count). We do NOT clamp
    # it downward: effective_n enters only via SR₀, and a LOWER effective_n
    # gives a LOWER SR₀ ⇒ a HIGHER DSR ⇒ an EASIER promotion. Capping it down
    # would deflate a broad (overfit-prone) trial set as if it were narrow —
    # the opposite of P7. So MinBTL is enforced as a sufficiency DECLINE below,
    # never as a downward cap on the deflation count.
    effective_n = max(1, int(meta.get("effective_n", len(per_config))))

    # A single (effective) trial is degenerate: SR₀ = √V·Φ⁻¹(1 - 1/1) =
    # √V·Φ⁻¹(0) = -∞ blows up the deflation — the math degeneracy IS why a
    # single-config trial set cannot earn a deflated pass (R5.2/5.3, P7).
    if effective_n < 2 or len(per_config) < 2:
        return _decline(
            selected,
            ["degenerate_trial_set: effective_n < 2 (DSR deflation undefined)"],
            effective_n=effective_n,
        )

    # ---- MinBTL: a history-sufficiency DECLINE, not a deflation cap (R5.3)
    # MinBTL ("minimum backtest length") bounds the trial-set BREADTH to the
    # available history: each effective trial must be backed by at least
    # ``min_btl`` observations. If the search is broader than the history can
    # support (history / effective_n < min_btl), DECLINE — do NOT silently
    # pretend fewer trials ran and proceed (that would under-deflate; P7).
    available_history = s["n"]  # the selected config's total OOS observations.
    if params.min_btl > 0 and available_history / effective_n < params.min_btl:
        return _decline(
            selected,
            [
                "min_btl_breach: trial-set breadth exceeds available history "
                f"(history={available_history:.0f}/effective_n={effective_n} "
                f"= {available_history / effective_n:.1f} per trial < min_btl={params.min_btl})"
            ],
            effective_n=effective_n,
        )

    # ---- 2. PSR / MinTRL sufficiency (R5.1, R5.4) -----------------------
    # MinTRL sufficiency: the candidate must have enough OOS observations for
    # its own distribution AND clear the operator's MinTRL floor.
    min_trl_needed = min_track_record_length(
        sr_hat=s["sr_hat"],
        sr_benchmark=params.benchmark_sharpe,
        skew=s["skew"],
        excess_kurt=s["excess_kurt"],
    )
    min_trl_met = (
        math.isfinite(min_trl_needed)
        and s["n"] >= min_trl_needed
        and s["n"] >= params.min_trl
    )
    psr = probabilistic_sharpe_ratio(
        sr_hat=s["sr_hat"],
        sr_benchmark=params.benchmark_sharpe,
        n=s["n"],
        skew=s["skew"],
        excess_kurt=s["excess_kurt"],
    )
    if not min_trl_met:
        if not math.isfinite(min_trl_needed):
            # SR̂ ≤ benchmark_sharpe ⇒ MinTRL = +∞: the candidate never beats
            # the benchmark (a distinct decline category from too-few-obs).
            reason = (
                "below_benchmark: candidate Sharpe does not exceed the benchmark "
                f"(sr_hat={s['sr_hat']:.4f} <= benchmark={params.benchmark_sharpe})"
            )
        else:
            reason = (
                "insufficient_oos: MinTRL not met "
                f"(n={s['n']:.0f}, need>={min_trl_needed:.1f}, floor={params.min_trl})"
            )
        return _decline(
            selected,
            [reason],
            psr=psr,
            min_trl_met=False,
            effective_n=effective_n,
        )

    # ---- 3. DSR + PBO/CSCV (overfitting-corrected; R5.1) ----------------
    # V for SR₀: the cross-sectional variance of the trial set's SR̂s, unless the
    # orchestrator supplied a (conservatively-estimated) one in trial_metadata.
    sr_hats = [stats[c]["sr_hat"] for c in per_config]
    derived_v = _sample_mean_std(sr_hats)[1] ** 2 if len(sr_hats) > 1 else 0.0
    sr_variance = float(meta.get("sr_variance", derived_v))

    dsr = deflated_sharpe_ratio(
        sr_hat=s["sr_hat"],
        n=s["n"],
        skew=s["skew"],
        excess_kurt=s["excess_kurt"],
        sr_variance=sr_variance,
        n_trials=effective_n,
    )
    n_subsets = _choose_n_subsets(len(per_config[selected]))
    pbo = probability_of_backtest_overfitting(matrix, n_subsets=n_subsets)

    reasons: list[str] = []
    if psr < params.psr_threshold:
        reasons.append(f"psr_below_threshold (psr={psr:.4f} < {params.psr_threshold})")
    if dsr < params.dsr_threshold:
        reasons.append(f"dsr_below_threshold (dsr={dsr:.4f} < {params.dsr_threshold})")
    if pbo > params.pbo_threshold:
        reasons.append(f"pbo_above_threshold (pbo={pbo:.4f} > {params.pbo_threshold})")

    # ---- 4. Decision-rule: OOS margin vs incumbent (R5.5) ---------------
    incumbent_mean = (
        sum(x.survival_net_return for x in matrix.incumbent) / len(matrix.incumbent)
        if matrix.incumbent
        else 0.0
    )
    margin = s["mean_return"] - incumbent_mean
    # Anti-churn hysteresis raises the effective bar the candidate must clear.
    required_margin = params.oos_margin + params.hysteresis
    if margin < required_margin:
        reasons.append(
            f"oos_margin_not_beaten (margin={margin:.4f} < required={required_margin:.4f})"
        )
    # Consecutive-cycle sustain (R5.5 anti-churn): the orchestrator threads the
    # observed consecutive-beat count via trial_metadata; absent ⇒ treat this
    # cycle as the first beat (count=1).
    consecutive = int(meta.get("consecutive_beats", 1))
    if consecutive < params.consecutive_required:
        reasons.append(
            f"consecutive_not_sustained (beats={consecutive} < {params.consecutive_required})"
        )

    # ---- 5. §13 lexicographic guard (R6.3) ------------------------------
    lexicographic_ok = _lexicographic_guard_ok(meta, selected)
    if not lexicographic_ok:
        reasons.append(
            "section13_guard: Edge/Return gain at the cost of a worse Survive/Preserve "
            "(or decomposition absent ⇒ unconfirmable)"
        )

    if reasons:
        return _decline(
            selected,
            reasons,
            dsr=dsr,
            psr=psr,
            min_trl_met=True,
            pbo=pbo,
            effective_n=effective_n,
            lexicographic_ok=lexicographic_ok,
        )

    # Every sub-check passed for the selected config.
    return GateVerdict(
        promote=True,
        selected_config=selected,
        reasons=[
            "promote: PSR/MinTRL sufficient, DSR/PBO clear, margin+hysteresis beaten, §13 ok"
        ],
        dsr=dsr,
        psr=psr,
        min_trl_met=True,
        pbo=pbo,
        effective_n=effective_n,
        lexicographic_ok=True,
    )


def _choose_n_subsets(n_partitions: int) -> int:
    """Largest even subset count ≤ partitions (CSCV needs an even S, S/2 per half).

    Falls back to the conventional S=4 when the partition count is too small for
    a larger even split; ``probability_of_backtest_overfitting`` handles the
    too-few-partitions degeneracy (returns 1.0 ⇒ no-promote).
    """
    if n_partitions < 4:
        return 2
    s = n_partitions if n_partitions % 2 == 0 else n_partitions - 1
    # Cap at a modest even S so C(S, S/2) stays small/deterministic.
    return min(s, 8) if (min(s, 8) % 2 == 0) else min(s, 8) - 1


def _lexicographic_guard_ok(meta: dict, selected: str) -> bool:
    """§13 guard: the selected config must not trade Survive/Preserve for Edge/Return.

    Survive ⊳ Preserve ⊳ Edge ⊳ Return (the lexicographic ordering, R6.3). The
    selected config must have Survive ≥ incumbent's Survive AND Preserve ≥
    incumbent's Preserve. The separable scores live in
    ``trial_metadata["lexicographic"]`` (the gate defines this convention; see
    the module docstring). If the decomposition for the selected config or the
    incumbent is ABSENT, the guard cannot be CONFIRMED ⇒ return False (P7
    fail-safe — an unconfirmable §13 invariant blocks promotion).
    """
    lex = meta.get("lexicographic")
    if not isinstance(lex, dict):
        return False
    cand = lex.get(selected)
    incumbent = lex.get("__incumbent__")
    if not isinstance(cand, dict) or not isinstance(incumbent, dict):
        return False
    for key in ("survive", "preserve"):
        if key not in cand or key not in incumbent:
            return False
        # A lower Survive/Preserve than the incumbent is the forbidden trade.
        if cand[key] < incumbent[key]:
            return False
    return True


__all__ = [
    "norm_cdf",
    "norm_ppf",
    "full_kurtosis",
    "probabilistic_sharpe_ratio",
    "min_track_record_length",
    "expected_max_sharpe",
    "deflated_sharpe_ratio",
    "probability_of_backtest_overfitting",
    "evaluate_gate",
]
