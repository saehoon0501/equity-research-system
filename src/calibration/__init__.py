"""Calibration package (WS-4).

Resolver job + calibration metrics + the canonical Layer-1 verdict scorer.

  - ``horizon``  — signal_type -> primary_horizon -> recommendation_outcomes
                   column mapping (no t_plus_365).
  - ``resolver`` — PIT, total-return, idempotent UPSERT backfill of
                   label_binary + excess_return vs SPY.
  - ``metrics``  — Brier / log-loss / reliability diagram with seeded
                   block-bootstrap CI (block 5 / 1000 reps / 95%); ECE
                   off-headline.
  - ``scorer``   — Label / ScoreInput / Verdict / score (src/eval/scorer.py
                   shims to these).

Submodule imports are LAZY (PEP 562 ``__getattr__``) so that importing the pure
``src.calibration.scorer`` (no third-party deps) does NOT transitively pull in
``metrics`` -> numpy. This keeps the src/eval/scorer.py shim — and its sole
importer tests/unit/eval/test_scorer.py — dependency-light, exactly as before.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

# public name -> defining submodule (relative to this package).
_EXPORTS: dict[str, str] = {
    # horizon
    "LEGAL_HORIZONS": "horizon",
    "columns_for": "horizon",
    "horizons_for": "horizon",
    "primary_horizon_for": "horizon",
    "return_column_for": "horizon",
    "window_days_for": "horizon",
    # metrics
    "BLOCK_SIZE": "metrics",
    "N_REPS": "metrics",
    "CI_LEVEL": "metrics",
    "DEFAULT_BOOTSTRAP_SEED": "metrics",
    "CI": "metrics",
    "CalibrationReport": "metrics",
    "ReliabilityBin": "metrics",
    "brier_score": "metrics",
    "log_loss": "metrics",
    "reliability_diagram": "metrics",
    "expected_calibration_error": "metrics",
    "block_bootstrap_ci": "metrics",
    "calibration_report": "metrics",
    # resolver
    "BENCHMARK_TICKER": "resolver",
    "LABEL_METHOD_VERSION": "resolver",
    "PendingOutcome": "resolver",
    "PriceClient": "resolver",
    "OutcomeStore": "resolver",
    "ResolvedLabel": "resolver",
    "HorizonReturn": "resolver",
    "DeferredOutcome": "resolver",
    "ResolverRunResult": "resolver",
    "resolve_one": "resolver",
    "run_resolver": "resolver",
    # scorer
    "Label": "scorer",
    "ScoreInput": "scorer",
    "Verdict": "scorer",
    "score": "scorer",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{mod_name}", __name__)
    return getattr(module, name)


def __dir__():
    return sorted(__all__)


if TYPE_CHECKING:  # static-analysis convenience; not executed at runtime.
    from src.calibration.horizon import (  # noqa: F401
        LEGAL_HORIZONS,
        columns_for,
        horizons_for,
        primary_horizon_for,
        return_column_for,
        window_days_for,
    )
    from src.calibration.metrics import (  # noqa: F401
        BLOCK_SIZE,
        CI,
        CI_LEVEL,
        DEFAULT_BOOTSTRAP_SEED,
        N_REPS,
        CalibrationReport,
        ReliabilityBin,
        block_bootstrap_ci,
        brier_score,
        calibration_report,
        expected_calibration_error,
        log_loss,
        reliability_diagram,
    )
    from src.calibration.resolver import (  # noqa: F401
        BENCHMARK_TICKER,
        LABEL_METHOD_VERSION,
        DeferredOutcome,
        OutcomeStore,
        PendingOutcome,
        PriceClient,
        ResolvedLabel,
        ResolverRunResult,
        resolve_one,
        run_resolver,
    )
    from src.calibration.scorer import Label, ScoreInput, Verdict, score  # noqa: F401
