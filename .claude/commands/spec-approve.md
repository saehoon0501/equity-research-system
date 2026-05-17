---
description: Operator HMAC-attested sign-off on spec revisions per v3 §5.4 + §8 PB#1. Writes a sign-off attestation file to docs/superpowers/specs/v<version>-signoff-attestation.md matching the v3.0 template, with an AUDIT_HMAC_KEY-signed canonical payload.
argument-hint: <version> [--operator <id>] [--spec-path <path>] [--scope-summary <text>] [--out <path>] [--force]
---

# /spec-approve

Operator-locked HMAC-attested sign-off on a spec revision per v3 spec Section 5.4 + Section 8 PB#1. Replaces the manual attestation pattern (which was canonical at v0.1 — see `docs/superpowers/specs/v3.0-signoff-attestation.md`).

## Arguments

`<version>` — required. Version string (e.g. `3.1`, `3.0`). Leading `v` is tolerated.

Optional flags:
- `--operator <id>` — operator identifier. Defaults to `$OPERATOR_ID` env var or `saehoon0501`.
- `--spec-path <path>` — path to the spec file being signed. Auto-resolves from `docs/superpowers/specs/` by default.
- `--scope-summary <text>` — free-form scope-of-approval body. `{version}` placeholder is substituted.
- `--out <path>` — output path. Defaults to `docs/superpowers/specs/v<version>-signoff-attestation.md`.
- `--force` — overwrite existing attestation file (rare; sign-offs are append-only by convention).

## Procedure

### 1. Pre-flight checks

- `AUDIT_HMAC_KEY` env var should be set. If unset, the CLI emits a stderr warning and signs with an empty key — downstream verification will flag the signature as unkeyed.
- Spec file matching the version exists in `docs/superpowers/specs/` (or operator passes `--spec-path` explicitly).

### 2. Invoke the CLI

```bash
python -m src.spec_approve.cli <version> [flags]
```

The CLI:
1. Resolves the spec file path.
2. Computes a canonical-payload HMAC over `(version, spec_path, timestamp, operator)` using `src/audit_trail/hmac_verify.py::compute_signature_dict`.
3. Writes `docs/superpowers/specs/v<version>-signoff-attestation.md`.
4. Prints the path + HMAC signature for operator records.

Exit code mapping:
- `0` — success
- `1` — IO error (write failure)
- `2` — usage error
- `3` — file already exists (use `--force` to overwrite)

### 3. HMAC contract

Identical to the audit-chain HMAC contract per Section 5.2:
- Canonical JSON: `sort_keys=True, separators=(',',':'), ensure_ascii=False`.
- Algorithm: HMAC-SHA256 with `AUDIT_HMAC_KEY`.
- Verifier: `src/audit_trail/hmac_verify.py::compute_signature_dict`.

A future `/spec-approve --verify` flag would replay the signature against the attestation file's canonical payload — deferred to v0.5+.

### 4. Examples

Sign off v3.1:
```
/spec-approve 3.1
```

With explicit operator + custom scope:
```
/spec-approve 3.1 --operator alice@example.com --scope-summary "Approves the v3.1 patch cycle resolving 4 cleanup findings from Wave D.4 audit."
```

Re-sign (rare):
```
/spec-approve 3.1 --force
```

## What `/spec-approve` does NOT do

- **No DB write.** Sign-offs live in the spec directory as Markdown attestations; this matches the v3.0 manual-attestation pattern. A future `signoff_attestations` table is v0.5+ scope.
- **No retroactive countersignature.** The CLI signs with the current `AUDIT_HMAC_KEY`. Key rotation invalidates older signatures by design — that is the rotation-scope contract.
- **No revoke.** Sign-offs are append-only by convention; `--force` exists for accidental file-write recovery only.

## Failure modes

- **`AUDIT_HMAC_KEY` unset** — CLI emits stderr warning, signs with empty key, exits 0. Verifier will flag the signature as unkeyed at the next `/audit-trail --verify --strict` invocation. Operator should re-sign once the key is in place.
- **Attestation file already exists** — exit 3 unless `--force`. Sign-offs are append-only; the existing attestation should be the canonical record.

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Section 5.4 (slash commands), Section 8 PB#1 (sign-off chain).
- Template: `docs/superpowers/specs/v3.0-signoff-attestation.md`.
- Module: `src/spec_approve/` (cli.py).
- HMAC contract: `src/audit_trail/hmac_verify.py`.
