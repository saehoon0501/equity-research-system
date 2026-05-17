# spec_approve — operator HMAC-attested spec sign-off

Backs the `/spec-approve <version>` slash command. Writes an attestation
file matching the `v3.0-signoff-attestation.md` template, with an
`AUDIT_HMAC_KEY`-signed canonical payload.

## Module status

**v0.1 minimal implementation.** The CLI:
1. Resolves the spec file matching the version string (or accepts
   `--spec-path`).
2. Computes a canonical-payload HMAC signature over
   `(version, spec_path, timestamp, operator)` using
   `src/audit_trail/hmac_verify.py::compute_signature_dict`.
3. Writes
   `docs/superpowers/specs/v<version>-signoff-attestation.md`.

## Usage

```bash
python -m src.spec_approve.cli 3.1
python -m src.spec_approve.cli 3.1 --operator alice@example.com
python -m src.spec_approve.cli 3.1 --scope-summary "Approves the v3.1 patch cycle..."
```

## HMAC contract

Identical to the audit-chain contract:
- Canonical JSON: `sort_keys=True, separators=(',',':'), ensure_ascii=False`.
- Algorithm: HMAC-SHA256 keyed with `AUDIT_HMAC_KEY`.
- Verifier: `src/audit_trail/hmac_verify.py::compute_signature_dict`.

If `AUDIT_HMAC_KEY` is unset, the CLI emits a stderr warning and signs
with an empty key — downstream verification will flag the signature
as unkeyed (matching the `--verify` unkeyed-mode semantics in
`/audit-trail`).

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md`
  Section 5.4 (slash commands), Section 8 PB#1 (sign-off chain).
- Template: `docs/superpowers/specs/v3.0-signoff-attestation.md`.
- Slash command: `.claude/commands/spec-approve.md`.
- HMAC contract: `src/audit_trail/hmac_verify.py`.
