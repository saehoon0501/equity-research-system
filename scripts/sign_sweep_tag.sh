#!/usr/bin/env bash
# =============================================================================
# sign_sweep_tag.sh
#
# Generate (or sign a supplied) sweep tag for /research-company --as-of-tag.
# Outputs the 3 args the orchestrator + PreToolUse gate expect:
#   --as-of-tag=<TAG>
#   --as-of-tag-sig=<SIG>
#   --as-of-tag-issued-at=<UNIX_TIMESTAMP>
#
# Replay-protection: the gate hook enforces |now - issued_at| <= 600s.
# Re-run this script before each multi-ticker sweep batch or pass --keep-tag
# to re-sign the same tag with a fresh timestamp.
#
# USAGE:
#   ./scripts/sign_sweep_tag.sh                          # new uuid, args-style output
#   ./scripts/sign_sweep_tag.sh --tag <existing-uuid>    # re-sign existing tag
#   ./scripts/sign_sweep_tag.sh --format cmd TICKER      # ready-to-paste full command
#   ./scripts/sign_sweep_tag.sh --format json            # machine-readable
#   ./scripts/sign_sweep_tag.sh --format env             # eval-able env exports
#
# ENV CONTRACT (resolved in priority order — first match wins):
#   AUDIT_HMAC_KEY       env var holding the key directly. Fastest path.
#   AUDIT_HMAC_KEY_FILE  env var holding a path to a file with
#                        `AUDIT_HMAC_KEY=<value>` on a line.
#   <walk-up>            walks up from script dir looking for `.env`;
#                        reads the AUDIT_HMAC_KEY= line if found. This is
#                        the no-config fallback that just works when run
#                        from inside the repo (main or any worktree).
#   Mismatch → PreToolUse gate rejects with exit 2.
#   None found → this script errors with a clear message.
# =============================================================================

set -euo pipefail

FORMAT="args"      # args | cmd | json | env
TAG=""
TICKER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)       TAG="$2"; shift 2 ;;
        --format)    FORMAT="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,25p' "$0" | sed 's/^# *//'
            exit 0
            ;;
        *)
            if [[ -z "$TICKER" ]]; then
                TICKER="$1"
            else
                echo "ERROR: unexpected arg: $1" >&2
                exit 1
            fi
            shift
            ;;
    esac
done

# Resolve AUDIT_HMAC_KEY (symmetric with research_company_as_of_tag_gate.sh).
# Fallback chain:
#   1. AUDIT_HMAC_KEY env var (existing behavior — fastest path)
#   2. AUDIT_HMAC_KEY_FILE env var → read AUDIT_HMAC_KEY= line from that file
#   3. DEFAULT: walk up from script dir, find first .env (handles main repo
#      AND worktrees; preserves the .env file-permission security model since
#      only the file owner can read -rw------- .env)
if [ -z "${AUDIT_HMAC_KEY:-}" ]; then
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

: "${AUDIT_HMAC_KEY:?AUDIT_HMAC_KEY env var required (same key the PreToolUse gate uses to verify). Tried env var, AUDIT_HMAC_KEY_FILE, and walk-up .env discovery; none found. Set the env var explicitly OR place a .env file containing AUDIT_HMAC_KEY=<value> at the project root.}"

if [[ -z "$TAG" ]]; then
    TAG="$(uuidgen | tr '[:upper:]' '[:lower:]')"
fi

ISSUED_AT="$(date +%s)"

# Canonical HMAC payload — MUST match gate hook exactly:
#   printf '%s|%s' "$TAG" "$ISSUED_AT" | openssl dgst -sha256 -hmac "$AUDIT_HMAC_KEY" -hex
SIG="$(printf '%s|%s' "$TAG" "$ISSUED_AT" \
       | openssl dgst -sha256 -hmac "$AUDIT_HMAC_KEY" -hex 2>/dev/null \
       | awk '{print $2}')"

if [[ -z "$SIG" ]]; then
    echo "ERROR: openssl HMAC computation failed. Check that openssl is installed." >&2
    exit 1
fi

case "$FORMAT" in
    args)
        echo "--as-of-tag=${TAG} --as-of-tag-sig=${SIG} --as-of-tag-issued-at=${ISSUED_AT}"
        ;;
    cmd)
        if [[ -z "$TICKER" ]]; then
            echo "ERROR: --format cmd requires a TICKER positional arg." >&2
            exit 1
        fi
        echo "/research-company ${TICKER} --as-of-tag=${TAG} --as-of-tag-sig=${SIG} --as-of-tag-issued-at=${ISSUED_AT}"
        ;;
    json)
        printf '{"tag":"%s","sig":"%s","issued_at":%s,"expires_at":%s}\n' \
            "$TAG" "$SIG" "$ISSUED_AT" "$(( ISSUED_AT + 600 ))"
        ;;
    env)
        cat <<EOF
export SWEEP_TAG="${TAG}"
export SWEEP_SIG="${SIG}"
export SWEEP_ISSUED_AT="${ISSUED_AT}"
# Then: /research-company TICKER --as-of-tag=\$SWEEP_TAG --as-of-tag-sig=\$SWEEP_SIG --as-of-tag-issued-at=\$SWEEP_ISSUED_AT
EOF
        ;;
    *)
        echo "ERROR: --format must be one of: args, cmd, json, env (got: ${FORMAT})" >&2
        exit 1
        ;;
esac
