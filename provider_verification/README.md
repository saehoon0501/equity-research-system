# Provider Verification

This directory holds verification artifacts proving that each LLM provider's training-data status was confirmed before [Date X] and at every phase boundary thereafter.

## Path A configuration (Day 1)

Per BUILD_LOG.md Day 1 architectural decisions, this project uses Path A: all agents run on Anthropic via Claude Code subagent infrastructure. v2-final §1.3 model-family diversity for BearCase is deliberately not enforced.

**Active providers requiring verification:**
- Anthropic (CompanyDeepDive, BearCase, MacroCycle, PMSupervisor, DailyMonitor, Evaluator — all agents)

**No second LLM provider** at v0.1. If Path A is reversed at any phase boundary (e.g., Checkpoint 3 results indicate contamination defense underperforms), a second provider verification artifact gets added at that point.

## Verification cadence

Per phasing-plan.md and implementation-sequencing.md §2.2:

- **Day 1 (2026-04-26):** initial verification before any agent code runs
- **v0.5 entry:** re-verify (status changes silently; verify at every phase boundary)
- **v1.0 entry:** re-verify

The mechanical re-verification at each phase boundary is the load-bearing protection against silent provider T&C changes.

## Files

- `anthropic.md` — Anthropic verification status and procedure
- `api_keys/` — sample API call responses documenting key works (no keys themselves; keys live in env vars)
- `artifacts/` — gitignored; holds screenshots, T&C PDF captures, account settings exports
