"""parameters_review — quarterly parameter recalibration (STUB).

Per v3 spec Section 1.5 + Section 5.4:
  Cadence-driven parameter recalibration. System proposes; operator approves.
  Quarterly default; runs against rolling 90-day counterfactual ledger.

This is a v0.1 STUB module. The structured workflow lands at v0.5+ once the
counterfactual ledger has accumulated enough rolling-90-day signal to make
recalibration suggestions defensible.

At v0.1 the CLI provides:
  - `summary`     — group `parameters` rows by namespace; show latest + prior.
  - `suggest`     — read `operator_overrides` rows from last 90 days; surface
                    parameter keys most frequently overridden.
  - `propose`     — placeholder; emits a stub message pointing to v0.5+ scope.

Reference:
  docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 1.5 (parameter governance)
    Section 5.4 (slash commands)
    Section 6.3 (calibration cadence)
  docs/superpowers/operator-reference.md §1.5 (deferred slash-command status)
"""

from __future__ import annotations

__all__: list[str] = []
