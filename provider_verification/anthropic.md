# Anthropic API Verification

**Initial capture target:** Week 1 (2026-04-26 to 2026-05-02)
**Build clock:** 2026-04-26
**Re-verification at v0.5 entry:** TBD per phasing-plan.md §3.2
**Re-verification at v1.0 entry:** TBD per phasing-plan.md §4.2

---

## Path A acknowledgment

This project uses Path A per BUILD_LOG.md Day 1 architectural decisions: all agents run on Anthropic via Claude Code subagent infrastructure. v2-final §1.3 model-family diversity for BearCase is deliberately not enforced. The primary contamination defense (mechanical Evidence Index check, v2-final §4.2.5) remains the load-bearing protection.

The startup configuration check that v2-final §4.3 specifies (refuse to run if CompanyDeepDive and BearCase resolve to the same family) is replaced for this deployment with this documented acknowledgment of the override. Reversal path: route BearCase through OpenAI or Google API directly, bypassing Claude Code for that one agent. Reversal trigger: Checkpoint 3 post-cutoff degradation >20%.

---

## Verification procedure

To capture the Day-1 verification artifact, complete each step and check off:

- [ ] **Console screenshot — data privacy settings**
  - Visit https://console.anthropic.com → Settings → Data Privacy
  - Confirm: "Anthropic does not train on data submitted to Claude API by default"
  - Save screenshot to `artifacts/anthropic_console_2026-04-26.png` (gitignored)

- [ ] **T&C link captured with date stamp**
  - Visit https://www.anthropic.com/legal/commercial-terms
  - Capture full PDF or HTML to `artifacts/anthropic_tc_2026-04-26.pdf` (gitignored)
  - Note the T&C version date in this file under "Verification record" below

- [ ] **Sample API call**
  - Run a minimal `POST /v1/messages` call with placeholder content
  - Save response headers (not body) to `api_keys/anthropic_sample_response_2026-04-26.json`
  - Document SDK version (anthropic-sdk-python ≥ 0.30 required for prompt caching per v2-final §4.7)

- [ ] **Account org ID**
  - Note last 4 chars of org ID under "Verification record" — establishes which account was verified, without exposing the full ID

- [ ] **Org-level data-handling settings**
  - Confirm no admin has enabled training opt-in or data sharing
  - Capture admin-panel screenshot to `artifacts/anthropic_admin_2026-04-26.png` (gitignored)

---

## Re-verification protocol (v0.5 entry, v1.0 entry)

Mechanically re-run each step above with the date updated. Compare current state against initial capture. Any divergence flagged.

If org-level settings have changed (e.g., admin enabled training opt-in inadvertently), this triggers phasing-plan.md §3.6.5 / §4.6.5 kill criterion: "Provider training-data status changes mid-phase." System halts; rotate to compliant configuration before resuming.

---

## Verification record (fill in at capture time)

**Day 1 capture (target 2026-04-26 to 2026-05-02):**

- Capture date: [TBD]
- Anthropic SDK version: [TBD]
- Account org ID (last 4 chars only): [TBD]
- T&C version date: [TBD]
- Sample API response status: [TBD]
- Console screenshot path: [TBD]
- Admin panel screenshot path: [TBD]

**v0.5 entry re-verification:**

- [ ] Pending — execute at v0.5 entry per phasing-plan.md §3.2

**v1.0 entry re-verification:**

- [ ] Pending — execute at v1.0 entry per phasing-plan.md §4.2

---

## Status

**Verification artifact capture status:** PENDING (Day 1 task — week 1)

This file becomes the audit trail. Verification is not "I checked once and moved on." It's a record that gets re-executed at each phase boundary so future-tired-you can prove training-data status was sound at every transition point.
