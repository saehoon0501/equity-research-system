"""Portfolio-fit risk → correlation sizing multiplier (WS-7.2, Phase 3).

See package docstring (``src/risk_overlay/__init__.py``) for the why.

This module is the compute layer. It exposes:

    beta_from_returns(candidate, benchmark)      -> float   (offline math)
    correlation_to_book(candidate, book)         -> float   (offline math)
    portfolio_fit_multiplier(beta, corr_to_book) -> float in (0, 1.0]
    resolve_portfolio_fit(...)                    -> PortfolioFitResult
                                                    (the orchestration seam)

Mapping / reasoning for ``portfolio_fit_multiplier``
----------------------------------------------------
Two independent penalty factors, each in (0, 1], combined multiplicatively:

    beta penalty:  no haircut while |beta| <= beta_floor (default 1.0 — a name
                   no more market-sensitive than the benchmark itself adds no
                   *excess* systematic risk). Above the floor the penalty ramps
                   down linearly in the excess beta, bottoming at beta_min_mult
                   once |beta| reaches beta_cap.

    corr penalty:  no haircut while corr_to_book <= corr_floor (default 0.3 — a
                   weak/uncorrelated name is a genuine diversifier). Above the
                   floor the penalty ramps down linearly in the excess
                   correlation, bottoming at corr_min_mult once corr_to_book
                   reaches corr_cap (default 1.0 — perfect co-movement).

    multiplier = clamp( beta_penalty * corr_penalty,  hard_floor,  1.0 )

Why multiplicative (not additive / min):
    - Multiplicative keeps each dimension independently monotone: raising
      either beta or corr (holding the other fixed) can only lower the
      multiplier, never raise it — required by the acceptance contract.
    - It also encodes the *interaction*: a name that is high on BOTH axes
      (high-beta AND high-corr-to-book) is the worst diversifier and gets the
      compounded haircut, which is the concentration story we want to penalise
      hardest. A name high on only one axis gets a milder, single-factor cut.

Why never > 1.0:
    Portfolio-fit risk is a *haircut* dimension. A great diversifier is
    rewarded by the ABSENCE of a haircut (multiplier 1.0), not by inflation —
    size inflation is conviction/regime's job. Capping at 1.0 also keeps the
    composable geometric product's "any overlay can tighten to ~0, none can
    blow up" invariant intact.

Offline / injectable:
    Every market input is a seam. You may pass precomputed ``beta`` /
    ``corr_to_book``, OR aligned return arrays (beta/corr computed here with
    numpy), OR a ``fetcher`` callable. ``fetcher`` defaults to ``None`` and is
    the ONLY place a live price-history fetch would ever be wired in — this
    module itself performs no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence, Tuple

import numpy as np

# --------------------------------------------------------------------------- #
# Tunables (defaults). All overridable per-call so the mapping is testable.   #
# --------------------------------------------------------------------------- #

# Beta at/below which there is no systematic-risk haircut. A name as market-
# sensitive as the benchmark (beta 1.0) adds no *excess* systematic risk.
DEFAULT_BETA_FLOOR = 1.0
# Beta at which the beta penalty bottoms out (fully applied).
DEFAULT_BETA_CAP = 2.0
# Floor for the beta penalty factor (a very high-beta name still keeps this
# fraction of its target). Keeps the multiplier strictly > 0.
DEFAULT_BETA_MIN_MULT = 0.6

# Correlation-to-book at/below which the name is treated as a diversifier
# (no haircut).
DEFAULT_CORR_FLOOR = 0.3
# Correlation at which the corr penalty bottoms out (perfect co-movement).
DEFAULT_CORR_CAP = 1.0
# Floor for the corr penalty factor.
DEFAULT_CORR_MIN_MULT = 0.6

# Absolute hard floor on the final multiplier — guarantees (0, 1.0].
DEFAULT_HARD_FLOOR = 1e-6


@dataclass(frozen=True)
class PortfolioFitInputs:
    """Resolved numeric inputs to the portfolio-fit multiplier.

    Either ``beta`` / ``corr_to_book`` are supplied directly, or they are
    derived from the aligned return series. All optional so the dataclass can
    also serve as a record of what was provided.
    """

    beta: Optional[float] = None
    corr_to_book: Optional[float] = None
    candidate_returns: Optional[Sequence[float]] = None
    benchmark_returns: Optional[Sequence[float]] = None
    book_returns: Optional[Sequence[float]] = None


@dataclass(frozen=True)
class PortfolioFitResult:
    """Output of ``resolve_portfolio_fit``.

    ``multiplier`` is the value to pass to
    ``composable_size(correlation_multiplier=...)``.
    """

    beta: float
    corr_to_book: float
    beta_penalty: float
    corr_penalty: float
    multiplier: float
    # Axes whose scalar input was non-finite (NaN / inf) and therefore could not
    # be trusted. Such an axis is treated as a DATA ERROR: it fails *closed*
    # (its penalty is forced to the conservative ramp floor, never 1.0) and is
    # surfaced here so a caller / monitor can see the data gap rather than the
    # haircut being silently indistinguishable from a genuine diversifier.
    axes_unavailable: Tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict:
        return {
            "beta": round(self.beta, 4),
            "corr_to_book": round(self.corr_to_book, 4),
            "beta_penalty": round(self.beta_penalty, 4),
            "corr_penalty": round(self.corr_penalty, 4),
            "multiplier": round(self.multiplier, 4),
            "dimension": "correlation",
            "axes_unavailable": list(self.axes_unavailable),
        }


# --------------------------------------------------------------------------- #
# Offline market math                                                         #
# --------------------------------------------------------------------------- #


def _as_array(name: str, x: Sequence[float]) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    if a.ndim != 1:
        raise ValueError(f"{name} must be a 1-D return series")
    if a.size < 2:
        raise ValueError(f"{name} needs >= 2 observations, got {a.size}")
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} contains non-finite values")
    return a


def beta_from_returns(
    candidate_returns: Sequence[float], benchmark_returns: Sequence[float]
) -> float:
    """Ordinary-least-squares beta of candidate vs benchmark.

        beta = Cov(candidate, benchmark) / Var(benchmark)

    Inputs must be aligned (same length, same dates). Deterministic, offline.
    """
    c = _as_array("candidate_returns", candidate_returns)
    b = _as_array("benchmark_returns", benchmark_returns)
    if c.size != b.size:
        raise ValueError(
            f"candidate ({c.size}) and benchmark ({b.size}) must be aligned"
        )
    var_b = float(np.var(b))  # population variance; cancels with cov's 1/N
    if var_b == 0.0:
        raise ValueError("benchmark has zero variance; beta undefined")
    cov = float(np.cov(c, b, bias=True)[0, 1])
    return cov / var_b


def correlation_to_book(
    candidate_returns: Sequence[float], book_returns: Sequence[float]
) -> float:
    """Pearson correlation between candidate and the existing book's returns.

    ``book_returns`` is the (weighted) return series of the current
    portfolio/holdings. Aligned with candidate. Deterministic, offline.
    """
    c = _as_array("candidate_returns", candidate_returns)
    bk = _as_array("book_returns", book_returns)
    if c.size != bk.size:
        raise ValueError(
            f"candidate ({c.size}) and book ({bk.size}) must be aligned"
        )
    if np.var(c) == 0.0 or np.var(bk) == 0.0:
        raise ValueError("zero-variance series; correlation undefined")
    return float(np.corrcoef(c, bk)[0, 1])


# --------------------------------------------------------------------------- #
# The mapping                                                                 #
# --------------------------------------------------------------------------- #


def _ramp_penalty(
    value: float, floor: float, cap: float, min_mult: float
) -> float:
    """Linear ramp from 1.0 (at/below ``floor``) down to ``min_mult`` (at/above
    ``cap``). Monotone non-increasing in ``value``.
    """
    if cap <= floor:
        raise ValueError("cap must be > floor")
    if value <= floor:
        return 1.0
    if value >= cap:
        return min_mult
    frac = (value - floor) / (cap - floor)  # in (0, 1)
    return 1.0 - frac * (1.0 - min_mult)


def portfolio_fit_multiplier(
    beta: float,
    corr_to_book: float,
    *,
    beta_floor: float = DEFAULT_BETA_FLOOR,
    beta_cap: float = DEFAULT_BETA_CAP,
    beta_min_mult: float = DEFAULT_BETA_MIN_MULT,
    corr_floor: float = DEFAULT_CORR_FLOOR,
    corr_cap: float = DEFAULT_CORR_CAP,
    corr_min_mult: float = DEFAULT_CORR_MIN_MULT,
    hard_floor: float = DEFAULT_HARD_FLOOR,
) -> float:
    """Map portfolio-fit risk (beta + corr-to-book) to a sizing haircut.

    Returns a float in (0, 1.0]. See module docstring for the full mapping and
    diversification/concentration rationale.

    Properties (verified by tests):
        * Low-beta, low-corr diversifier  => 1.0 (no haircut).
        * High-beta + high-corr           => < 1.0.
        * Monotone non-increasing in beta (corr fixed) and in corr (beta fixed).
        * Always in (0, 1.0].

    Beta uses |beta|: a strongly *negative* beta is also a large systematic
    exposure (an inverse market bet), so its magnitude — not sign — drives the
    excess-systematic-risk haircut. Correlation-to-book is NOT abs'd: a name
    *negatively* correlated to the book is a hedge / diversifier and should keep
    its full size (penalty 1.0 below the floor), so only positive co-movement
    above ``corr_floor`` is penalised.

    Non-finite inputs FAIL CLOSED, not open. A NaN or inf ``beta`` /
    ``corr_to_book`` is a data error (a garbage/missing market input), not a
    diversifier. Letting it through would make NaN comparisons silently False
    and the function would return 1.0 — a risk overlay failing OPEN, handing a
    name with unknown risk its full target size. Instead a non-finite axis is
    treated as UNAVAILABLE and contributes that axis's conservative ramp floor
    (``beta_min_mult`` / ``corr_min_mult``) rather than 1.0. The result is thus
    a finite value strictly below 1.0 (distinguishable from a clean diversifier)
    and never NaN/inf. ``resolve_portfolio_fit`` additionally records which axis
    was unavailable in its returned payload for monitoring.
    """
    beta_penalty = (
        _ramp_penalty(abs(beta), beta_floor, beta_cap, beta_min_mult)
        if math.isfinite(beta)
        else beta_min_mult
    )
    corr_penalty = (
        _ramp_penalty(corr_to_book, corr_floor, corr_cap, corr_min_mult)
        if math.isfinite(corr_to_book)
        else corr_min_mult
    )
    mult = beta_penalty * corr_penalty
    # Clamp into (0, 1.0]. The ramp can never exceed 1.0, but clamp defensively
    # in case of pathological tunable overrides.
    mult = min(1.0, mult)
    return max(hard_floor, mult)


# --------------------------------------------------------------------------- #
# Orchestration seam                                                          #
# --------------------------------------------------------------------------- #


def resolve_portfolio_fit(
    inputs: Optional[PortfolioFitInputs] = None,
    *,
    beta: Optional[float] = None,
    corr_to_book: Optional[float] = None,
    candidate_returns: Optional[Sequence[float]] = None,
    benchmark_returns: Optional[Sequence[float]] = None,
    book_returns: Optional[Sequence[float]] = None,
    fetcher: Optional[Callable[[], PortfolioFitInputs]] = None,
    **mapping_kwargs,
) -> PortfolioFitResult:
    """Resolve beta + corr-to-book from whatever seam is provided, then map.

    Resolution precedence (first satisfied wins for each quantity):
        1. Explicit ``beta`` / ``corr_to_book`` kwargs (or on ``inputs``).
        2. Computed from aligned return arrays (kwargs or on ``inputs``).
        3. ``fetcher()`` — the INTEGRATION SEAM. Defaults to ``None``; when
           provided it must return a ``PortfolioFitInputs`` carrying either the
           scalars or the return arrays. The live price-history fetch wires in
           HERE and nowhere else; this module performs no network I/O itself.

    Returns a ``PortfolioFitResult`` whose ``.multiplier`` is ready for
    ``composable_size(correlation_multiplier=...)``.
    """
    # Collapse the three input channels (inputs dataclass, kwargs, fetcher) into
    # a single resolved set of fields, kwargs taking precedence over `inputs`,
    # and `fetcher` used only to fill gaps.
    src = inputs or PortfolioFitInputs()

    r_beta = beta if beta is not None else src.beta
    r_corr = corr_to_book if corr_to_book is not None else src.corr_to_book
    r_cand = candidate_returns if candidate_returns is not None else src.candidate_returns
    r_bench = benchmark_returns if benchmark_returns is not None else src.benchmark_returns
    r_book = book_returns if book_returns is not None else src.book_returns

    need_fetch = (r_beta is None and (r_cand is None or r_bench is None)) or (
        r_corr is None and (r_cand is None or r_book is None)
    )
    if need_fetch and fetcher is not None:
        fetched = fetcher()
        if not isinstance(fetched, PortfolioFitInputs):
            raise TypeError("fetcher must return a PortfolioFitInputs")
        r_beta = r_beta if r_beta is not None else fetched.beta
        r_corr = r_corr if r_corr is not None else fetched.corr_to_book
        r_cand = r_cand if r_cand is not None else fetched.candidate_returns
        r_bench = r_bench if r_bench is not None else fetched.benchmark_returns
        r_book = r_book if r_book is not None else fetched.book_returns

    if r_beta is None:
        if r_cand is None or r_bench is None:
            raise ValueError(
                "beta unavailable: supply `beta`, or aligned "
                "candidate_returns + benchmark_returns, or a fetcher providing them"
            )
        r_beta = beta_from_returns(r_cand, r_bench)

    if r_corr is None:
        if r_cand is None or r_book is None:
            raise ValueError(
                "corr_to_book unavailable: supply `corr_to_book`, or aligned "
                "candidate_returns + book_returns, or a fetcher providing them"
            )
        r_corr = correlation_to_book(r_cand, r_book)

    r_beta = float(r_beta)
    r_corr = float(r_corr)

    # A non-finite (NaN / inf) resolved scalar is a DATA ERROR for that axis —
    # it must NOT fail open to a clean 1.0. Mark the axis unavailable and force
    # its reported penalty to the conservative ramp floor (mirrors what
    # portfolio_fit_multiplier does internally), so the gap is visible in the
    # payload and never propagates a NaN into the multiplier arithmetic.
    beta_min_mult = mapping_kwargs.get("beta_min_mult", DEFAULT_BETA_MIN_MULT)
    corr_min_mult = mapping_kwargs.get("corr_min_mult", DEFAULT_CORR_MIN_MULT)
    axes_unavailable = []

    if math.isfinite(r_beta):
        beta_penalty = _ramp_penalty(
            abs(r_beta),
            mapping_kwargs.get("beta_floor", DEFAULT_BETA_FLOOR),
            mapping_kwargs.get("beta_cap", DEFAULT_BETA_CAP),
            beta_min_mult,
        )
    else:
        beta_penalty = beta_min_mult
        axes_unavailable.append("beta")

    if math.isfinite(r_corr):
        corr_penalty = _ramp_penalty(
            r_corr,
            mapping_kwargs.get("corr_floor", DEFAULT_CORR_FLOOR),
            mapping_kwargs.get("corr_cap", DEFAULT_CORR_CAP),
            corr_min_mult,
        )
    else:
        corr_penalty = corr_min_mult
        axes_unavailable.append("corr_to_book")

    multiplier = portfolio_fit_multiplier(r_beta, r_corr, **mapping_kwargs)

    return PortfolioFitResult(
        beta=r_beta,
        corr_to_book=r_corr,
        beta_penalty=beta_penalty,
        corr_penalty=corr_penalty,
        multiplier=multiplier,
        axes_unavailable=tuple(axes_unavailable),
    )
