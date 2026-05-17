"""Counterfactual-catalog evaluator gate.

DEPRECATED 2026-05-17 — no-op stub. Original behavior validated
counterfactual_top_3 presence and case_id references against the
peak_pain_archetypes catalog. That validation is no longer load-bearing.

The module retains the public symbols (`CounterfactualCatalogResult`,
`validate_counterfactual_top3`) so existing imports in
`src/evaluator_gates/__init__.py` continue to function. Both always
report `valid=True` with empty defect-fields.

See docs/superpowers/plans/2026-05-17-remove-peak-pain-archetypes-and-counterfactual-veto.md.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CounterfactualCatalogResult:
    """No-op result. All fields default to empty / valid."""

    valid: bool = True
    missing_buckets: list[str] = field(default_factory=list)
    invented_buckets: list[str] = field(default_factory=list)
    invented_fields: list[str] = field(default_factory=list)
    case_ids_not_in_catalog: list[str] = field(default_factory=list)
    notes: str = "deprecated-no-op (2026-05-17 peak_pain_archetypes removal)"


def validate_counterfactual_top3(
    envelope: dict[str, Any],
    case_ids: list[str] | None = None,
    db_dsn: str | None = None,
) -> CounterfactualCatalogResult:
    """No-op stub. Always returns a valid result."""
    warnings.warn(
        "evaluator_gates.counterfactual_catalog.validate_counterfactual_top3 "
        "deprecated 2026-05-17; no-op stub.",
        DeprecationWarning,
        stacklevel=2,
    )
    return CounterfactualCatalogResult()
