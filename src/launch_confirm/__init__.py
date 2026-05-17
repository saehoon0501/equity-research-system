"""launch_confirm — operator HMAC-attested sign-off on launch gates.

Per v3 spec Section 5.4 + Section 7.3.

Each invocation appends a sign-off entry to the append-only operator log
at:

    docs/superpowers/launch-readiness-log.md

Entry shape (one per gate, per operator, per attestation):
  - gate_name (e.g. 'hard_gates_green', 'walkthrough_PLTR_2022')
  - timestamp (UTC ISO)
  - operator
  - HMAC signature (canonical-payload contract from
    `src/audit_trail/hmac_verify.py`, keyed with `AUDIT_HMAC_KEY`)

The log file is human-readable Markdown so operator reviewers can scan
gates without running the verifier; the HMAC stamp anchors each row to
the signing key in force at the time.

Reference:
  docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
    Section 5.4 (slash commands)
    Section 7   (launch gates)
    Section 7.3 (operator sign-off block)
"""

from __future__ import annotations

__all__: list[str] = []
