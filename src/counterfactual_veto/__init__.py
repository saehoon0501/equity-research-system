"""Counterfactual VETO pipeline (v3 spec Section 4.5 Q6 d').

Three-layer capitulation defense for cut decisions on watchlist names that
have hit 2× cut threshold:

    Layer 1 — Cooling-off floor (universal, mode-tuned 24h/48h/72h)
    Layer 2 — Multi-source confirmation (≥2 independent kills, verbatim
              primary source, pre-mortem within 30 days)
    Layer 3 — Counterfactual VETO authority (top-3 peak-pain archetype
              retrieval; SURVIVOR-dominant top-3 → cut blocked, requires
              operator override)

The veto operates ON TOP of mode polarity — i.e., even Mode-C cut-fast names
get blocked when their structural features match historical SURVIVOR cases
(the PLTR-2022 problem, motivating Walkthrough #1 in Section 7.3a).

Re-fire policy (Section 6 Q6 PB#5): single-fire per peak-pain event. Re-fires
only on M-3 materiality refresh that shifts archetype mix (e.g., founder
departure flipping founder_in_place → SURVIVOR archetypes drop out of top-3).

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 4.5 Q6 (capitulation triggers; Layer 1/2/3),
           Section 4.4 (peak-pain catalog two-layer schema, retrieval scoring),
           Section 6 Q6 PB#5 (veto lifecycle re-fire policy),
           Section 7.2 (calibration archetype-coverage agreement gate),
           Section 7.3a Walkthrough #1 (PLTR-2022 motivating case).

Public surface:
    - `feature_extractor.extract_candidate_features` — extract candidate's
      structural features at peak-pain trigger (reuses peak_pain_catalog
      3-LLM consensus pipeline).
    - `retrieval.retrieve_top_3` — mechanical similarity scoring against
      catalog (0.7 universal-core Hamming + 0.3 sector extensions).
    - `layer1_cooling_off.evaluate_cooling_off` — mode-tuned cooling-off floor.
    - `layer2_multi_source.evaluate_multi_source` — multi-source confirmation.
    - `layer3_veto.evaluate_veto` — archetype-distribution VETO authority.
    - `lifecycle.refresh_on_m3` — M-3-driven re-evaluation per PB#5.
    - `orchestrator.run_pipeline` — end-to-end pipeline.
"""

from __future__ import annotations

# Public re-exports — keep the surface compact; deep types live in submodules.
__all__ = [
    "MODE_COOLING_OFF_HOURS",
    "MODE_2X_THRESHOLDS",
    "CUT_STATUS_NOT_ACTIVATED_BELOW_2X",
]


# Composite cut-status label for the activation gate (Section 4.5 Q6 — 2× cut
# threshold MUST be met before the 3-layer pipeline runs at all).
CUT_STATUS_NOT_ACTIVATED_BELOW_2X: str = "not_activated_below_2x_threshold"

# Mode-tuned cooling-off floors (Section 4.5 Q6 Layer 1).
MODE_COOLING_OFF_HOURS: dict[str, int] = {
    "B": 72,
    "B_prime": 48,
    "C": 24,
}

# 2× cut thresholds in percentage points (Section 4.5 Q6 activation gate).
MODE_2X_THRESHOLDS: dict[str, float] = {
    "B": 20.0,
    "B_prime": 24.0,
    "C": 30.0,
}
