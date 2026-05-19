#!/usr/bin/env bash
# research_company_as_of_tag_gate.sh — PreToolUse hook for /research-company.
#
# Purpose
# -------
# Enforce HMAC-attested governance for the `--as-of-tag` orchestrator arg
# (sweep test-row reads). Per /review-me v7-final C18 + C20:
#
#   - Skill invocations of /research-company WITHOUT `--as-of-tag` → allow.
#   - Invocations WITH `--as-of-tag` MUST present a valid HMAC signature over
#     the (tag, issued_at_unix) tuple, signed with AUDIT_HMAC_KEY, with
#     |now - issued_at| <= 600s.
#   - On missing/invalid signature → exit 2, stderr block-feedback, dispatch
#     aborted. DIVERGES from /spec-approve and /launch-confirm prior art
#     (which soft-fail on missing key) because here the affected artifact
#     (run_parameters_snapshot → recommendation row → portfolio sizing) is
#     consumed by downstream decisions and is NOT recoverable by re-running.
#     A sweep silently becoming production pollutes the recommendation ledger.
#
# Input  (stdin, JSON): PreToolUse-shaped payload from Claude Code.
#   { "tool_name": "Skill", "tool_input": { "skill": "research-company",
#                                            "args": "TICKER --as-of-tag=...
#                                                     --as-of-tag-sig=...
#                                                     --as-of-tag-issued-at=..." } }
#
# Output:
#   exit 0 + silent  → allow (no --as-of-tag, or sig validates)
#   exit 0 + stderr  → not our concern (different skill, or different tool)
#   exit 2 + stderr  → BLOCK with feedback message
#
# Idempotent / pure: reads only stdin + AUDIT_HMAC_KEY env (or, as a
# fallback, the file path in AUDIT_HMAC_KEY_FILE — see the validate block
# below). No state, no network, no DB.

set -euo pipefail

# Read full stdin payload.
PAYLOAD="$(cat || true)"
if [ -z "$PAYLOAD" ]; then
    # Empty payload — nothing to check. Allow.
    exit 0
fi

# Extract tool_name. If not Skill, ignore.
TOOL_NAME="$(printf '%s' "$PAYLOAD" | jq -r '.tool_name // ""' 2>/dev/null || echo "")"
if [ "$TOOL_NAME" != "Skill" ]; then
    exit 0
fi

# Extract skill name. If not research-company, ignore.
SKILL_NAME="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.skill // ""' 2>/dev/null || echo "")"
if [ "$SKILL_NAME" != "research-company" ]; then
    exit 0
fi

# Extract args string.
ARGS="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.args // ""' 2>/dev/null || echo "")"

# Extract --as-of-tag value.
TAG="$(printf '%s' "$ARGS" | grep -oE -- '--as-of-tag=[^ ]+' | head -1 | sed -E 's/^--as-of-tag=//' || true)"

# If no tag, this is a production run — allow.
if [ -z "$TAG" ]; then
    exit 0
fi

# Tag IS present — enforcement required.

TAG_SIG="$(printf '%s' "$ARGS" | grep -oE -- '--as-of-tag-sig=[^ ]+' | head -1 | sed -E 's/^--as-of-tag-sig=//' || true)"
TAG_ISSUED_AT="$(printf '%s' "$ARGS" | grep -oE -- '--as-of-tag-issued-at=[0-9]+' | head -1 | sed -E 's/^--as-of-tag-issued-at=//' || true)"

# Validate presence.
if [ -z "$TAG_SIG" ] || [ -z "$TAG_ISSUED_AT" ]; then
    cat >&2 <<EOF
[research_company_as_of_tag_gate] BLOCK: --as-of-tag=${TAG} requires both
  --as-of-tag-sig=<hex> and --as-of-tag-issued-at=<unix-ts> args. One or
  both were missing.

  No silent downgrade to production. Sweep runs are governance-attested.
  Sign the (tag, issued_at) tuple with AUDIT_HMAC_KEY and reinvoke.

  Example:
    NOW=\$(date +%s)
    SIG=\$(printf "%s|%s" "${TAG}" "\$NOW" | openssl dgst -sha256 -hmac "\$AUDIT_HMAC_KEY" -hex | awk '{print \$2}')
    /research-company TICKER --as-of-tag=${TAG} --as-of-tag-sig=\$SIG --as-of-tag-issued-at=\$NOW
EOF
    exit 2
fi

# Validate AUDIT_HMAC_KEY env var is set.
# Fallback chain (highest priority first):
#   1. AUDIT_HMAC_KEY env var directly
#   2. AUDIT_HMAC_KEY_FILE env var → read AUDIT_HMAC_KEY= line from that file
#   3. DEFAULT: <script_dir>/../.env → same pattern (self-resolving path)
#
# Path (3) makes the gate work without ANY env-block propagation from
# Claude Code's settings.json — useful when settings.json env changes have
# not yet been picked up by a session restart, or when running the gate
# directly from CLI for testing. The default resolves to the project root's
# .env (gitignored), which is the operator's canonical credential store.
#
# Why self-resolve vs hardcode an absolute path: script lives in scripts/
# next to .env at the project root; relative resolution works for any
# checkout location (main repo, worktrees, ad-hoc clones).
if [ -z "${AUDIT_HMAC_KEY:-}" ]; then
    # Resolve a candidate .env path via the first match of:
    #   1. AUDIT_HMAC_KEY_FILE env var (explicit operator config)
    #   2. Walk up from script dir looking for .env (handles main repo AND
    #      worktrees; in a worktree at .claude/worktrees/<name>/scripts/, the
    #      walk-up reaches the main repo root where the canonical .env lives)
    KEY_FILE=""
    if [ -n "${AUDIT_HMAC_KEY_FILE:-}" ] && [ -r "$AUDIT_HMAC_KEY_FILE" ]; then
        KEY_FILE="$AUDIT_HMAC_KEY_FILE"
    else
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        CANDIDATE="$SCRIPT_DIR"
        # Walk up at most 8 levels; stop at filesystem root.
        for _ in 1 2 3 4 5 6 7 8; do
            if [ -r "$CANDIDATE/.env" ]; then
                KEY_FILE="$CANDIDATE/.env"
                break
            fi
            PARENT="$(dirname "$CANDIDATE")"
            [ "$PARENT" = "$CANDIDATE" ] && break
            CANDIDATE="$PARENT"
        done
    fi
    if [ -n "$KEY_FILE" ]; then
        # Robust extraction: match line starting with literal var name,
        # take everything after the first '=' (handles base64 with '=='),
        # strip optional surrounding single or double quotes.
        EXTRACTED="$(grep -E '^AUDIT_HMAC_KEY=' "$KEY_FILE" 2>/dev/null \
            | head -1 \
            | sed -E 's/^AUDIT_HMAC_KEY=//' \
            | sed -E 's/^"(.*)"$/\1/' \
            | sed -E "s/^'(.*)'\$/\\1/" || true)"
        if [ -n "$EXTRACTED" ]; then
            AUDIT_HMAC_KEY="$EXTRACTED"
            export AUDIT_HMAC_KEY
        fi
    fi
fi

if [ -z "${AUDIT_HMAC_KEY:-}" ]; then
    cat >&2 <<EOF
[research_company_as_of_tag_gate] BLOCK: --as-of-tag=${TAG} present but
  AUDIT_HMAC_KEY env var is unset (and AUDIT_HMAC_KEY_FILE fallback either
  unset or did not yield a value). Cannot verify the signature.

  Either export AUDIT_HMAC_KEY in your shell before launching Claude Code,
  or set "env": { "AUDIT_HMAC_KEY_FILE": "/path/to/.env" } in
  .claude/settings.json so the gate can read the secret from a gitignored
  file at hook-invocation time.

  No silent downgrade to production.
EOF
    exit 2
fi

# Validate the timestamp window (|now - issued_at| <= 600s).
NOW="$(date +%s)"
if ! [[ "$TAG_ISSUED_AT" =~ ^[0-9]+$ ]]; then
    cat >&2 <<EOF
[research_company_as_of_tag_gate] BLOCK: --as-of-tag-issued-at=${TAG_ISSUED_AT}
  is not a valid unix timestamp.
EOF
    exit 2
fi

DELTA="$(( NOW - TAG_ISSUED_AT ))"
if [ "$DELTA" -lt 0 ]; then DELTA="$(( -DELTA ))"; fi
if [ "$DELTA" -gt 600 ]; then
    cat >&2 <<EOF
[research_company_as_of_tag_gate] BLOCK: --as-of-tag-issued-at=${TAG_ISSUED_AT}
  is ${DELTA}s away from now=${NOW} (limit: 600s).

  Re-sign with a fresh timestamp and reinvoke. Replay-protection window
  is tight by design: sweep attestations are single-use within 10 minutes.
EOF
    exit 2
fi

# Compute expected sig and constant-time compare.
EXPECTED_SIG="$(printf '%s|%s' "$TAG" "$TAG_ISSUED_AT" \
                | openssl dgst -sha256 -hmac "$AUDIT_HMAC_KEY" -hex 2>/dev/null \
                | awk '{print $2}')"

if [ -z "$EXPECTED_SIG" ]; then
    cat >&2 <<EOF
[research_company_as_of_tag_gate] BLOCK: openssl HMAC-SHA256 computation
  failed. Check that openssl is installed and AUDIT_HMAC_KEY env is readable.
EOF
    exit 2
fi

# Constant-time compare using openssl's hash equality (avoid early-exit info leak).
# Lower-case both sides and compare via length + cmp.
EXPECTED_LC="$(printf '%s' "$EXPECTED_SIG" | tr '[:upper:]' '[:lower:]')"
PROVIDED_LC="$(printf '%s' "$TAG_SIG" | tr '[:upper:]' '[:lower:]')"

if [ "${#EXPECTED_LC}" != "${#PROVIDED_LC}" ]; then
    cat >&2 <<EOF
[research_company_as_of_tag_gate] BLOCK: --as-of-tag-sig length mismatch
  (expected ${#EXPECTED_LC} hex chars, got ${#PROVIDED_LC}).
EOF
    exit 2
fi

# Bytewise constant-time compare via cmp on temp files.
TMP_E="$(mktemp -t astg.XXXXXX)"
TMP_P="$(mktemp -t astg.XXXXXX)"
trap 'rm -f "$TMP_E" "$TMP_P"' EXIT
printf '%s' "$EXPECTED_LC" > "$TMP_E"
printf '%s' "$PROVIDED_LC" > "$TMP_P"

if ! cmp -s "$TMP_E" "$TMP_P"; then
    cat >&2 <<EOF
[research_company_as_of_tag_gate] BLOCK: --as-of-tag-sig does not match
  HMAC-SHA256(AUDIT_HMAC_KEY, "${TAG}|${TAG_ISSUED_AT}").

  No silent downgrade to production. Re-sign with the canonical payload
  format and reinvoke.
EOF
    exit 2
fi

# Sig validates. Allow the dispatch.
exit 0
