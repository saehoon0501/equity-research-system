---
description: Operator HMAC-attested sign-off per launch gate per v3 §5.4 + §7.3. Appends a row to docs/superpowers/launch-readiness-log.md (append-only) with timestamp, operator, gate name, optional note, and AUDIT_HMAC_KEY-signed canonical payload.
argument-hint: <gate_name> [--operator <id>] [--note <text>] [--log-path <path>]
---

# /launch-confirm

Operator-locked HMAC-attested sign-off on a launch gate per v3 spec Section 5.4 + Section 7 + Section 7.3. Replaces the manual checkbox-in-spec + BUILD_LOG-note pattern (which was the v0.1 workaround per `docs/superpowers/operator-reference.md` §1.5).

## Arguments

`<gate_name>` — required. Free-form identifier (recommended: snake_case). Examples: `hard_gates_green`, `walkthrough_PLTR_2022`, `calibration_kappa`, `email_channel_test`.

Optional flags:
- `--operator <id>` — operator identifier. Defaults to `$OPERATOR_ID` env var or `saehoon0501`.
- `--note <text>` — optional one-line attestation note (e.g. evidence pointer, walkthrough summary).
- `--log-path <path>` — override the log file. Defaults to `docs/superpowers/launch-readiness-log.md`.

## Procedure

### 1. Pre-flight checks

- `AUDIT_HMAC_KEY` env var should be set. If unset, the CLI emits a stderr warning and signs with an empty key — downstream verification will flag the signature as unkeyed.
- Log file `docs/superpowers/launch-readiness-log.md` is created on first invocation if missing.

### 2. Invoke the CLI

```bash
python -m src.launch_confirm.cli <gate_name> [flags]
```

The CLI:
1. Computes canonical-payload HMAC over `(gate_name, timestamp, operator, note)` using `src/audit_trail/hmac_verify.py::compute_signature_dict`.
2. Appends a Markdown table row to the log.
3. Prints the log path + full HMAC signature for operator records.

Exit code mapping:
- `0` — success
- `1` — IO error (write failure)
- `2` — usage error

### 3. Log format

The log file `docs/superpowers/launch-readiness-log.md` is a Markdown table with:

| Timestamp (UTC) | Gate | Operator | Note | HMAC (truncated) |

Append-only by convention. The truncated HMAC is rendered for skim-readability; the full signature is printed to stdout when each row is written.

### 4. HMAC contract

Identical to the audit-chain HMAC contract per Section 5.2:
- Canonical JSON: `sort_keys=True, separators=(',',':'), ensure_ascii=False`.
- Algorithm: HMAC-SHA256 with `AUDIT_HMAC_KEY`.
- Verifier: `src/audit_trail/hmac_verify.py::compute_signature_dict`.

A future `/launch-confirm --verify <gate_name>` flag would replay the signature against the row's canonical payload — deferred to v0.5+.

### 5. Examples

Sign off the hard-gates green block:
```
/launch-confirm hard_gates_green --note "All 10 hard gates from §7.1 verified green."
```

Sign off a walkthrough:
```
/launch-confirm walkthrough_PLTR_2022 --note "Walkthrough Wave D.1; counterfactual veto blocks the cut."
```

## What `/launch-confirm` does NOT do

- **No DB write.** Sign-offs live in the Markdown log; v0.5+ may promote to a `launch_signoffs` table.
- **No revoke.** Append-only by convention. To overturn a sign-off, append a new row noting the reversal in `--note`.
- **No automatic gate evaluation.** This command attests only that the operator has reviewed and approved the gate; it does not run the gate's underlying validation logic. Run the corresponding evaluation (e.g. `python -m src.audit_trail.cli ... --verify --strict`, peak-pain catalog priority-run output, etc.) before invoking `/launch-confirm`.

## Failure modes

- **`AUDIT_HMAC_KEY` unset** — CLI emits stderr warning, signs with empty key, appends the row, exits 0. Future verifier will flag as unkeyed. Operator should re-attest once the key is in place.
- **Log file unwritable** — exit 1 with the OS error.

## Reference

- v3 spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Section 5.4 (slash commands), Section 7 (launch gates), Section 7.3 (operator sign-off block).
- Module: `src/launch_confirm/` (cli.py).
- Log file: `docs/superpowers/launch-readiness-log.md` (NEW; append-only).
- HMAC contract: `src/audit_trail/hmac_verify.py`.
