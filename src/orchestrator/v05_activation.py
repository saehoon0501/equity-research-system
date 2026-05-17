"""v0.5 activation gate — single source of truth for "should v0.5 features
be live yet?".

Per v3 spec §6.4 + §8.1, v0.5 features (Brier haircut, believability
weighting, BB-pseudo-BMA+ regime weights, composable sizing formula)
operate in shadow mode at v0.1 and flip to live at v0.5-active. Consumers
should call `is_feature_live(conn, feature)` rather than re-deriving the
phase predicate themselves so a single change here cascades correctly.

Per-feature gating allows a graduated rollout — for instance the Brier
haircut may go live as soon as N≥50 outcomes accrue, while BB-pseudo-BMA+
remains shadow until N≥30 *with stable shrinkage outputs across 4 weeks*.

The default predicate is "phase is V05_ACTIVE OR V10_ACTIVE". Callers may
pass a parameters_dict to override per-feature (read from `parameters_active`
table in production; tests pass an explicit dict).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from src.orchestrator.phase_detector import Phase, detect_phase


class V05Feature(str, Enum):
    """Per-feature toggle keys. Add new ones here as the surface grows."""

    BRIER_HAIRCUT = "brier_haircut"
    BELIEVABILITY_WEIGHTING = "believability_weighting"
    BB_REGIME_WEIGHTS = "bb_regime_weights"
    COMPOSABLE_SIZING = "composable_sizing"
    CONTINUOUS_CONVICTION = "continuous_conviction"


@dataclass(frozen=True)
class ActivationStatus:
    """Snapshot of phase + per-feature live/shadow status."""

    phase: Phase
    features_live: dict[V05Feature, bool]

    def is_live(self, feature: V05Feature) -> bool:
        return self.features_live.get(feature, False)


def _default_features_for_phase(phase: Phase) -> dict[V05Feature, bool]:
    """Default gating: every v0.5 feature is live in V05_ACTIVE+ phases.

    Per-feature override comes from `parameters_active` rows; this helper
    only returns the default behavior so consumers don't have to special-
    case missing parameters rows.
    """
    is_v05_or_later = phase in (Phase.V05_ACTIVE, Phase.V10_ACTIVE)
    return {feat: is_v05_or_later for feat in V05Feature}


def get_activation_status(
    conn: Any,
    *,
    parameter_overrides: Optional[dict[V05Feature, bool]] = None,
) -> ActivationStatus:
    """Return current phase + per-feature live/shadow flags.

    Args:
        conn: psycopg connection (read-only).
        parameter_overrides: per-feature override (typically read from
            `parameters_active` table by the caller). Wins over the
            phase-default mapping.
    """
    snapshot = detect_phase(conn)
    features = _default_features_for_phase(snapshot.phase)
    if parameter_overrides:
        features.update(parameter_overrides)
    return ActivationStatus(phase=snapshot.phase, features_live=features)


def is_feature_live(
    conn: Any,
    feature: V05Feature,
    *,
    parameter_overrides: Optional[dict[V05Feature, bool]] = None,
) -> bool:
    """Convenience predicate. See `get_activation_status`."""
    status = get_activation_status(
        conn, parameter_overrides=parameter_overrides
    )
    return status.is_live(feature)
