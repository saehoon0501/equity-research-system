#!/usr/bin/env bash
# snapshot_for_standalone.sh — produce a PARAMETERS_USED block + audit_mode=snapshot
# dispatch context for ad-hoc mean-reversion-overlay invocation.
#
# Usage: scripts/snapshot_for_standalone.sh <ticker> <as_of_date>
#
# Output (to stdout): a complete PARAMETERS_USED header block + the 4 dispatch
# context lines (audit_mode, run_id, ticker, as_of_date) ready to paste into an
# Agent(mean-reversion-overlay, ...) prompt body.
#
# Side effects: INSERTs a row into run_parameters_snapshot (the audit chain).
# Operator skips this script entirely if they're OK with audit_mode=standalone
# (no row inserted; envelope is the only artifact).
#
# Dependencies: docker (running equity-research-db), python3, uuidgen, jq.
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <ticker> <as_of_date>" >&2
    echo "Example: $0 CRWD 2026-05-23" >&2
    exit 2
fi

TICKER="$1"
AS_OF_DATE="$2"

# Locate the .env file by walking up to repo root.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
if [ ! -f "$REPO_ROOT/.env" ]; then
    echo "[snapshot_for_standalone] cannot find .env at $REPO_ROOT/.env" >&2
    exit 2
fi
# Robust env-load: only extract POSTGRES_* lines (tolerates broken non-POSTGRES lines).
while IFS='=' read -r key val; do
    case "$key" in
        POSTGRES_USER|POSTGRES_PASSWORD|POSTGRES_DB|POSTGRES_PORT)
            export "$key=$val"
            ;;
    esac
done < <(grep -E '^POSTGRES_' "$REPO_ROOT/.env" 2>/dev/null || true)

if [ -z "${POSTGRES_USER:-}" ] || [ -z "${POSTGRES_PASSWORD:-}" ] || [ -z "${POSTGRES_DB:-}" ]; then
    echo "[snapshot_for_standalone] POSTGRES_* vars missing from .env" >&2
    exit 2
fi

RUN_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"

# Pull reversion.* rows from parameters_active in a single REPEATABLE-READ
# transaction (mirrors /research-company §1.5 Step 3).
ROWS_JSON="$(docker exec -i -e PGPASSWORD="$POSTGRES_PASSWORD" equity-research-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -F$'\t' --single-transaction <<SQL
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SELECT parameter_key, value, version_id::text
FROM parameters_active
WHERE parameter_namespace = 'reversion'
ORDER BY parameter_key;
SQL
)"

if [ -z "$ROWS_JSON" ]; then
    echo "[snapshot_for_standalone] no reversion.* rows in parameters_active" >&2
    exit 1
fi

# Compose canonical JSON map of {parameter_key: value} and sha256 hash.
PARAMS_COMPOSED="$(python3 - <<PY
import sys, json, hashlib
rows = """$ROWS_JSON""".strip().split("\n")
eff_map = {}
version_ids = []
for line in rows:
    parts = line.split("\t")
    if len(parts) < 3:
        continue
    key, value, vid = parts[0], parts[1], parts[2]
    # Try to parse value as JSON (numbers, strings, etc.)
    try:
        eff_map[key] = json.loads(value)
    except json.JSONDecodeError:
        eff_map[key] = value
    version_ids.append(vid)

eff_json = json.dumps(eff_map, sort_keys=True, separators=(",", ":"))
eff_hash = hashlib.sha256(eff_json.encode()).hexdigest()
# Sort UUIDs lexicographically as deterministic max
parameters_version_max = max(version_ids)

# Output: hash<TAB>version_max<TAB>compact_json
print(f"{eff_hash}\t{parameters_version_max}\t{eff_json}")
PY
)"

EFFECTIVE_HASH="$(printf '%s' "$PARAMS_COMPOSED" | cut -f1)"
PARAMETERS_VERSION_MAX="$(printf '%s' "$PARAMS_COMPOSED" | cut -f2)"
EFFECTIVE_JSON="$(printf '%s' "$PARAMS_COMPOSED" | cut -f3)"

# INSERT snapshot row.
docker exec -i -e PGPASSWORD="$POSTGRES_PASSWORD" equity-research-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<SQL >/dev/null
INSERT INTO run_parameters_snapshot (
    run_id, ticker, parameters_version_max,
    effective_parameters_jsonb, effective_parameters_hash,
    tag, tag_signature, tag_issued_at_unix, run_status
) VALUES (
    '$RUN_ID'::uuid, '$TICKER', '$PARAMETERS_VERSION_MAX'::uuid,
    '$EFFECTIVE_JSON'::jsonb, '$EFFECTIVE_HASH',
    NULL, NULL, NULL, 'standalone_snapshot'
);
SQL

# Emit the dispatch context block to stdout.
echo "=== PARAMETERS_USED (parameters_version_max: $PARAMETERS_VERSION_MAX, effective_parameters_hash: $EFFECTIVE_HASH, tag: NULL) ==="
echo "$ROWS_JSON" | while IFS=$'\t' read -r key value vid; do
    [ -z "$key" ] && continue
    # Filter only reversion.* keys (psql tag-lines like "SET" may leak through -t -A output)
    case "$key" in
        reversion.*) echo "$key: $value" ;;
    esac
done
echo "=== END PARAMETERS_USED ==="
echo ""
echo "audit_mode: snapshot"
echo "run_id: $RUN_ID"
echo "ticker: $TICKER"
echo "as_of_date: $AS_OF_DATE"
