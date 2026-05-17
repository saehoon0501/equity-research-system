"""Bayesian Online Change-Point Detection — Adams-MacKay 2007 wrapper.

Per v3 spec §4.1 (method overlay #1) and §4.1 firing thresholds (Q3) +
operator-locked dual-signal architecture decision.

Dual-signal architecture (operator-locked)
------------------------------------------
BOCPD per Adams-MacKay 2007 produces a posterior over run-lengths. Two
distinct posterior summaries are first-class outputs of this module:

1. ``bocpd_change_probability`` — canonical Adams-MacKay change-point
   marginal `P(r_t = 0 | x_{1:t})`. Retained for academic rigor + audit
   traceability. Structurally pinned near the hazard rate in steady state
   when one run-length dominates the posterior — does NOT systematically
   cross the v3 §4.1 firing thresholds (>0.7 / >0.95) in steady state.
   This is a property of BOCPD with constant-hazard prior, not a bug.

2. ``bocpd_short_run_mass`` — cumulative posterior
   `P(r_t < short_run_threshold | x_{1:t})`. PRIMARY firing signal:
   what actually crosses the v3 §4.1 thresholds on regime shifts. Used
   by L4 daily-monitor cut_evaluator and refresh_emitter for M-2/M-3
   decisions.

Both signals are stored, both indexed, both auditable in the
`regime_classification_history` table. Operators tuning thresholds should
treat short_run_mass as the firing-decision signal and the canonical
marginal as the academic-provenance signal.

Reference
---------
Adams, R.P. and MacKay, D.J.C. (2007). "Bayesian online changepoint detection."
arXiv:0710.3742.

Implementation choice
---------------------
The PyPI package `bayesian_changepoint_detection` is the natural reference
but adds a heavy matplotlib dependency. Since BOCPD is a small algorithm
and the spec explicitly allows "roll your own per Adams-MacKay 2007", we
ship a compact in-house implementation with the standard constant-hazard
prior and Student-t predictive (Normal-Inverse-Gamma conjugate) — same as
the canonical reference.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np


logger = logging.getLogger(__name__)


# Constant-hazard rate. h = 1/250 → ~one change-point per trading year (a
# fairly diffuse prior; matches the v3 spec defaulting language). Tunable
# via `parameters` table at v0.5+.
DEFAULT_HAZARD: float = 1.0 / 250.0

# Conjugate Normal-Inverse-Gamma prior hyperparameters.
# Weakly informative — let the data speak from a few observations in.
DEFAULT_MU0: float = 0.0
DEFAULT_KAPPA0: float = 1.0
DEFAULT_ALPHA0: float = 1.0
DEFAULT_BETA0: float = 1.0

# Default short-run cutoff for `bocpd_short_run_mass`. The cumulative
# posterior over run-lengths r_t < SHORT_RUN_THRESHOLD captures
# "regime collapsed and hasn't recovered" patterns. 10 trading days
# (≈two weeks) is the operator-locked default per v3 §4.1 dual-signal
# architecture; tunable via `parameters` table at v0.5+.
DEFAULT_SHORT_RUN_THRESHOLD: int = 10


@dataclass(frozen=True)
class BocpdSignals:
    """Per-timestep BOCPD signal pair (canonical marginal + short-run mass).

    Attributes:
        change_probability: canonical Adams-MacKay marginal
            `P(r_t = 0 | x_{1:t})` over the input series. Shape: (n,).
            Retained for academic rigor + audit traceability per dual-signal
            architecture.
        short_run_mass: cumulative posterior
            `P(r_t < short_run_threshold | x_{1:t})` over the input series.
            Shape: (n,). PRIMARY firing signal — drives M-2/M-3 firing per
            v3 §4.1 thresholds.
    """

    change_probability: np.ndarray
    short_run_mass: np.ndarray


def _student_t_logpdf(x: float, mu: float, kappa: float, alpha: float, beta: float) -> float:
    """Predictive Student-t for the NIG conjugate (degrees-of-freedom = 2*alpha).

    Predictive variance scaling: beta * (kappa+1) / (alpha * kappa).
    """
    df = 2.0 * alpha
    scale = math.sqrt(beta * (kappa + 1.0) / (alpha * kappa))
    z = (x - mu) / scale
    # log Student-t density
    log_norm = (
        math.lgamma((df + 1.0) / 2.0)
        - math.lgamma(df / 2.0)
        - 0.5 * math.log(df * math.pi)
        - math.log(scale)
    )
    return log_norm - ((df + 1.0) / 2.0) * math.log1p(z * z / df)


def _clean_series(series: Sequence[float]) -> np.ndarray:
    """Forward-fill NaNs; drop leading NaNs."""
    arr = np.asarray(list(series), dtype=float)
    if not np.isnan(arr).any():
        return arr
    last = np.nan
    out = []
    for v in arr:
        if np.isnan(v):
            if not math.isnan(last):
                out.append(last)
        else:
            last = v
            out.append(v)
    return np.asarray(out, dtype=float)


def bocpd_signals(
    series: Sequence[float],
    hazard: float = DEFAULT_HAZARD,
    mu0: float = DEFAULT_MU0,
    kappa0: float = DEFAULT_KAPPA0,
    alpha0: float = DEFAULT_ALPHA0,
    beta0: float = DEFAULT_BETA0,
    short_run_threshold: int = DEFAULT_SHORT_RUN_THRESHOLD,
) -> BocpdSignals:
    """Run BOCPD over `series` and return both first-class signals.

    Per operator-locked dual-signal architecture (v3 §4.1):
      - canonical marginal `P(r_t = 0)` → academic / audit
      - short-run cumulative mass `P(r_t < short_run_threshold)` → firing

    Both are computed in a single pass over the data (one BOCPD forward
    sweep, two posterior summaries) so callers do not have to run the
    algorithm twice when they need both signals.

    Args:
        series: 1-D sequence of observations (e.g., daily EBP, daily
            S&P-bond rolling correlation, …). NaN-tolerant: NaNs are
            forward-filled then leading NaNs dropped.
        hazard: constant hazard rate H(r) = hazard. Default 1/250 ≈
            "one change per trading year."
        mu0, kappa0, alpha0, beta0: Normal-Inverse-Gamma prior. Defaults
            are weakly informative.
        short_run_threshold: cutoff for the cumulative short-run mass
            P(r_t < short_run_threshold). Default 10 ≈ two trading weeks.
            Operator-locked default per v3 §4.1 dual-signal architecture.

    Returns:
        :class:`BocpdSignals` with both signal arrays of shape (n_clean,).

    Numerical robustness: if a non-finite normalizer arises (NaN/inf in
    input → degenerate predictive), state is reset to prior and BOTH
    signals emit 0.0 (neutral) at that step. Pinning to 1.0 would falsely
    trip M-3 catastrophic alerts on a numerical artifact.
    """
    arr = _clean_series(series)
    n = arr.shape[0]
    if n == 0:
        return BocpdSignals(
            change_probability=np.zeros(0, dtype=float),
            short_run_mass=np.zeros(0, dtype=float),
        )

    mus = np.array([mu0], dtype=float)
    kappas = np.array([kappa0], dtype=float)
    alphas = np.array([alpha0], dtype=float)
    betas = np.array([beta0], dtype=float)
    log_R = np.array([0.0], dtype=float)  # log P(r_0=0) = 0 (degenerate)

    cp_prob = np.zeros(n, dtype=float)
    short_mass = np.zeros(n, dtype=float)
    log_1mh = math.log(1.0 - hazard)
    log_h = math.log(hazard) if hazard > 0 else float("-inf")

    for t in range(n):
        x = arr[t]

        log_pred = np.array(
            [_student_t_logpdf(x, mus[i], kappas[i], alphas[i], betas[i]) for i in range(len(log_R))]
        )

        log_growth = log_R + log_pred + log_1mh
        max_term = np.max(log_R + log_pred)
        log_change = max_term + math.log(np.sum(np.exp(log_R + log_pred - max_term))) + log_h
        log_R = np.concatenate(([log_change], log_growth))

        log_Z = np.max(log_R) + math.log(np.sum(np.exp(log_R - np.max(log_R))))
        if not np.isfinite(log_Z):
            # Numerical pathology — reset to prior, emit neutral 0.0 for
            # BOTH signals. v3 §4.1 firing thresholds must reflect data-
            # driven change-points, not solver artefacts.
            logger.warning(
                "bocpd: non-finite log_Z at t=%d (likely NaN/inf input or "
                "degenerate predictive); resetting state, emitting "
                "change_probability=0.0 and short_run_mass=0.0",
                t,
            )
            mus = np.array([mu0], dtype=float)
            kappas = np.array([kappa0], dtype=float)
            alphas = np.array([alpha0], dtype=float)
            betas = np.array([beta0], dtype=float)
            log_R = np.array([0.0], dtype=float)
            cp_prob[t] = 0.0
            short_mass[t] = 0.0
            continue

        # Signal 1 — canonical Adams-MacKay change-point marginal
        # P(r_t = 0 | x_{1:t}). After concatenate, log_R[0] is the
        # unnormalized log-joint log P(r_t=0, x_{1:t}); divide by log_Z.
        cp_prob[t] = float(np.exp(log_R[0] - log_Z))

        # Signal 2 — cumulative short-run mass P(r_t < threshold | x_{1:t}).
        upper = min(short_run_threshold, log_R.shape[0])
        log_short_mass = log_R[:upper]
        max_s = float(np.max(log_short_mass))
        log_short_total = max_s + math.log(float(np.sum(np.exp(log_short_mass - max_s))))
        short_mass[t] = float(np.exp(log_short_total - log_Z))

        # Update sufficient statistics (NIG conjugate update on each old run-length).
        new_mus = (kappas * mus + x) / (kappas + 1.0)
        new_kappas = kappas + 1.0
        new_alphas = alphas + 0.5
        new_betas = betas + (kappas * (x - mus) ** 2) / (2.0 * (kappas + 1.0))

        # Prepend the prior (for the new r=0 hypothesis).
        mus = np.concatenate(([mu0], new_mus))
        kappas = np.concatenate(([kappa0], new_kappas))
        alphas = np.concatenate(([alpha0], new_alphas))
        betas = np.concatenate(([beta0], new_betas))

    return BocpdSignals(change_probability=cp_prob, short_run_mass=short_mass)


def bocpd_change_probability(
    series: Sequence[float],
    hazard: float = DEFAULT_HAZARD,
    mu0: float = DEFAULT_MU0,
    kappa0: float = DEFAULT_KAPPA0,
    alpha0: float = DEFAULT_ALPHA0,
    beta0: float = DEFAULT_BETA0,
    short_run_threshold: int = DEFAULT_SHORT_RUN_THRESHOLD,
) -> np.ndarray:
    """Canonical Adams-MacKay change-point marginal `P(r_t = 0 | x_{1:t})`.

    Retained for academic rigor + audit traceability. NOTE: this signal is
    structurally pinned near the hazard rate in steady state; v3 §4.1
    firing thresholds (>0.7, >0.95) rarely trip on it. For firing decisions
    use ``bocpd_short_run_mass`` (or call ``bocpd_signals`` once and read
    both fields). See module docstring for dual-signal architecture.

    Args, return shape, NaN handling: same as ``bocpd_signals``.
    """
    return bocpd_signals(
        series,
        hazard=hazard,
        mu0=mu0,
        kappa0=kappa0,
        alpha0=alpha0,
        beta0=beta0,
        short_run_threshold=short_run_threshold,
    ).change_probability


def bocpd_short_run_mass(
    series: Sequence[float],
    hazard: float = DEFAULT_HAZARD,
    mu0: float = DEFAULT_MU0,
    kappa0: float = DEFAULT_KAPPA0,
    alpha0: float = DEFAULT_ALPHA0,
    beta0: float = DEFAULT_BETA0,
    short_run_threshold: int = DEFAULT_SHORT_RUN_THRESHOLD,
) -> np.ndarray:
    """Cumulative posterior `P(r_t < short_run_threshold | x_{1:t})`.

    PRIMARY firing signal per operator-locked dual-signal architecture.
    Drives M-2 / M-3 materiality firing per v3 §4.1 thresholds:
        > 0.7 sustained 2+ days → M-2
        > 0.95 single-day        → M-3 + alert

    Args, return shape, NaN handling: same as ``bocpd_signals``.
    """
    return bocpd_signals(
        series,
        hazard=hazard,
        mu0=mu0,
        kappa0=kappa0,
        alpha0=alpha0,
        beta0=beta0,
        short_run_threshold=short_run_threshold,
    ).short_run_mass


def latest_signals(series: Sequence[float], **kwargs) -> tuple[float, float]:
    """Convenience: run BOCPD over `series`, return the last timestep's
    pair `(change_probability, short_run_mass)`. Used by daily-cadence
    classifier — we only need today's signal pair for the daily row.

    Both elements are 0.0 if `series` is empty.
    """
    sigs = bocpd_signals(series, **kwargs)
    if sigs.change_probability.size == 0:
        return 0.0, 0.0
    return float(sigs.change_probability[-1]), float(sigs.short_run_mass[-1])


def latest_change_probability(series: Sequence[float], **kwargs) -> float:
    """Convenience: last-timestep canonical change probability.

    Retained for backwards-compat. Daily-cadence classifier should prefer
    ``latest_signals`` so both values come out of one BOCPD pass.
    """
    cp, _ = latest_signals(series, **kwargs)
    return cp


def latest_short_run_mass(series: Sequence[float], **kwargs) -> float:
    """Convenience: last-timestep short-run cumulative mass (firing signal)."""
    _, srm = latest_signals(series, **kwargs)
    return srm
