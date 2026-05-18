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
# ENV CONTRACT:
#   AUDIT_HMAC_KEY  required. Same key the PreToolUse gate uses to verify.
#                   Mismatch → gate rejects with exit 2.
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

: "${AUDIT_HMAC_KEY:?AUDIT_HMAC_KEY env var required (same key the PreToolUse gate uses to verify)}"

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
