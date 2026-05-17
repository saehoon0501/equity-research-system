# launch_confirm — operator HMAC-attested launch-gate sign-off

Backs the `/launch-confirm <gate_name>` slash command. Appends a row
to `docs/superpowers/launch-readiness-log.md` (append-only) with an
`AUDIT_HMAC_KEY`-signed canonical payload.

## Module status

**v0.1 minimal implementation.** The CLI:
1. Computes a canonical-payload HMAC over
   `(gate_name, timestamp, operator, note)` using
   `src/audit_trail/hmac_verify.py::compute_signature_dict`.
2. Appends a Markdown table row to the launch-readiness log.

The log file is created on first invocation if missing.

## Usage

```bash
python -m src.launch_confirm.cli hard_gates_green
python -m src.launch_confirm.cli walkthrough_PLTR_2022 \
    --operator alice@example.com \
    --note "Reviewed counterfactual veto behaviour against PLTR-2022 trace."
```

## HMAC contract

Identical to the audit-chain HMAC contract:
- Canonical JSON: `sort_keys=True, separators=(',',':'), ensure_ascii=False`.
- Algorithm: HMAC-SHA256 with `AUDIT_HMAC_KEY`.
- Verifier: `src/audit_trail/hmac_verify.py::compute_signature_dict`.

The truncated signature is rendered in the log table; the full hex
signature is printed to stdout when the row is appended (operator may
wish to capture it externally).

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
  Section 5.4 (slash commands), Section 7 (launch gates),
  Section 7.3 (operator sign-off block).
- Slash command: `.claude/commands/launch-confirm.md`.
- Log file: `docs/superpowers/launch-readiness-log.md` (append-only).
- HMAC contract: `src/audit_trail/hmac_verify.py`.
