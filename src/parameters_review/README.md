# parameters_review — quarterly recalibration (v0.1 STUB)

v0.1 STUB module backing the `/parameters-review` slash command. Full
proposal-generation workflow deferred to v0.5+ per v3 spec §5.4 + §6.3.

## Module status

| Subcommand | Status | Notes |
|---|---|---|
| `summary`  | implemented | Groups `parameters` rows by `parameter_key`; surfaces current + prior `value`. |
| `suggest`  | implemented | Ranks `parameter_key` by `operator_overrides` frequency over last 90 days. |
| `propose`  | STUB        | Refuses to generate proposals; points to v0.5+ scope. |

## Why a stub at v0.1

Proposal generation requires:
- 90-day counterfactual ledger with sufficient outcome diversity.
- Parameter-vs-outcome attribution model.
- Operator approve/modify/reject UI for proposed changes.

None of these is in the v0.1 hard-gate set. The CLI provides read-only
visibility (`summary` + `suggest`) so operator can manually triage; full
workflow lands once §6.3 calibration cadence has accumulated enough signal.

## Usage

```bash
python -m src.parameters_review.cli summary
python -m src.parameters_review.cli summary --namespace mode_classifier
python -m src.parameters_review.cli suggest --since-days 90
python -m src.parameters_review.cli propose       # stub message
```

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
  Section 1.5 (parameter governance), Section 5.4 (slash commands),
  Section 6.3 (calibration cadence).
- Slash command: `.claude/commands/parameters-review.md`.
- Schema: `db/migrations/004_v3_parameters.sql` (`parameters` table),
  `db/migrations/013_v3_calibration.sql` (`operator_overrides`).
- Operator-reference deferred-status: `docs/superpowers/operator-reference.md` §1.5.
