"""Risk overlay package — WS-7.2 (Phase 3, OPTIONAL) portfolio-fit risk.

Computes a *portfolio-fit* (a.k.a. correlation/diversification) risk haircut
that feeds ``src.sizing.composable.composable_size(correlation_multiplier=...)``.

The portfolio-fit dimension answers: "Given what the book already owns, does
adding this candidate *concentrate* risk (poor diversifier) or *spread* it
(good diversifier)?" Two ingredients drive the answer:

    beta          — candidate sensitivity to the benchmark (systematic risk).
                    High beta means the name amplifies market moves; on a book
                    already exposed to the market it adds little independent
                    information and a lot of directional risk.
    corr_to_book  — candidate's return correlation to the EXISTING book/
                    portfolio. High correlation means the name moves with what
                    you already hold — it stacks the same bet rather than
                    diversifying it.

A name that is BOTH high-beta and highly correlated to the book is the worst
diversifier: it concentrates the book's existing exposure. It therefore earns
a haircut (< 1.0). A low-beta, low-correlation name is a genuine diversifier
and earns no haircut (== 1.0). The multiplier is NEVER > 1.0 — portfolio-fit
risk can only *reduce* a target size, never inflate it (sizing inflation is
the job of conviction/regime, not a risk overlay).

Injectable seams (fully offline-testable):
    - Pass ``beta`` / ``corr_to_book`` precomputed, OR
    - Pass aligned candidate/benchmark/book return arrays and let this module
      compute beta and correlation deterministically (numpy), OR
    - Pass a ``fetcher`` callable (defaults to ``None``) that returns the
      return series. The LIVE price-history fetch is the integration boundary —
      this module never makes a network call; ``fetcher=None`` simply means the
      caller must supply the numeric inputs directly.

Spec reference: WS-7 risk dimensions extension to v0.5 composable sizing
(``src/sizing/composable.py`` ``CalibratedWeights.correlation``).
"""

from __future__ import annotations

from src.risk_overlay.portfolio_fit import (
    DEFAULT_BETA_FLOOR,
    DEFAULT_CORR_FLOOR,
    PortfolioFitInputs,
    PortfolioFitResult,
    beta_from_returns,
    correlation_to_book,
    portfolio_fit_multiplier,
    resolve_portfolio_fit,
)

__all__ = [
    "DEFAULT_BETA_FLOOR",
    "DEFAULT_CORR_FLOOR",
    "PortfolioFitInputs",
    "PortfolioFitResult",
    "beta_from_returns",
    "correlation_to_book",
    "portfolio_fit_multiplier",
    "resolve_portfolio_fit",
]
