# Provider verification — `broker_schwab`

Verification record for the Schwab broker MCP integration. Per Section 7.1 launch gate ("Broker MCP OAuth flow tested; token refresh validated") this checklist must pass before v0.1 launch.

## verify_credentials

Operator confirms the following are present in `.env`:

- [ ] `SCHWAB_CLIENT_ID` — issued by <https://developer.schwab.com> after app approval
- [ ] `SCHWAB_CLIENT_SECRET` — paired secret from same developer portal
- [ ] `SCHWAB_ACCESS_TOKEN` — populated by the operator-interactive authorize flow (`src/mcp/broker_mcp/README.md` step 3)
- [ ] `SCHWAB_REFRESH_TOKEN` — populated by the same flow
- [ ] `SCHWAB_TOKEN_EXPIRES_AT` — epoch seconds; access-token expiry; populated by the same flow
- [ ] `BROKER_PROVIDER=schwab` (or absent — `schwab` is the default)

`.env` is gitignored. Tokens MUST NEVER be committed.

## Smoke test

Run from repo root:

```sh
uv sync --project src/mcp/broker_mcp

# 1. Smoke positions endpoint:
uv run --project src/mcp/broker_mcp python -c "
from broker_mcp.server import get_positions
result = get_positions('YOUR_ACCOUNT_HASH')
print('broker:', result['broker'])
print('positions:', len(result['positions']))
for p in result['positions'][:3]:
    print(' ', p['ticker'], p['shares_held'], '@', p['cost_basis'])
"

# 2. Smoke account summary:
uv run --project src/mcp/broker_mcp python -c "
from broker_mcp.server import get_account_summary
print(get_account_summary('YOUR_ACCOUNT_HASH'))
"

# 3. Smoke poll_for_fills (cold start — empty previous snapshot):
uv run --project src/mcp/broker_mcp python -c "
from broker_mcp.server import poll_for_fills
result = poll_for_fills(
    account_id_hash='YOUR_ACCOUNT_HASH',
    since_timestamp='2026-04-01T00:00:00Z',
    previous_snapshot=[],
)
print('fill_events:', len(result['fill_events']))
"
```

## Acceptance gates

- [ ] `get_positions` returns at least one row that matches what the operator sees in the Schwab UI (Section 7.3: "Operator confirmed broker MCP positions match brokerage UI")
- [ ] `get_account_summary` cash + total values match Schwab UI within ±$1 (rounding)
- [ ] `poll_for_fills` returns recent transactions when `since_timestamp` is set to a known date with activity
- [ ] Token refresh: artificially set `SCHWAB_TOKEN_EXPIRES_AT` to a past timestamp; next tool call must succeed (refresh transparent)

## Error modes (expected)

| Scenario | Expected behavior | Verified |
|---|---|---|
| `.env` missing client credentials | `BrokerConfigError` raised on adapter init | [ ] |
| `.env` missing tokens (no authorize flow) | `BrokerAuthError: No Schwab OAuth tokens in .env` | [ ] |
| Refresh token expired (>7 days idle) | `BrokerAuthError: Schwab token refresh failed (HTTP 400)` | [ ] |
| Schwab returns HTTP 429 (rate limit) | Backoff schedule (0.5s/1s/2s/4s); after exhaustion → `BrokerRateLimitError` | [ ] |
| Bad `account_id_hash` | Schwab returns 404; surfaces as `httpx.HTTPStatusError` (caller sees through MCP) | [ ] |

## Caveats

- **Refresh-token longevity:** Schwab refresh tokens last only 7 days. If the operator does not run the MCP for a week, they must re-run the interactive authorize flow. At v0.5+ this is a candidate for an automated nightly refresh job.
- **Tax-lot accounting:** Schwab's positions endpoint does not expose per-lot acquisition dates. The MCP returns `first_acquired=""` and `cost_basis_method="FIFO"` by default; the application-layer position_history reconciler handles per-lot FIFO from observed BUY events. Per Section 8.1, advanced tax-lot methods (specific-lot, average-cost) are deferred past v0.1.
- **Account-id-hash mapping:** Schwab issues an opaque `hashValue` per account on `GET /trader/v1/accounts/accountNumbers`. The operator must obtain this once (via Schwab UI or a one-off API call) and pass it on every tool invocation. Plain account numbers must never enter the MCP — this is a deliberate PII boundary.
- **Cache TTL:** positions + summary are cached for 24 hours (the daily-cadence floor for mode C per Section 7 Q3). Restart the MCP to bust the cache; v0.5+ may add a per-call `force_refresh` parameter.
- **Read-only enforcement:** the OAuth scope requested is `readonly`; even if a future operator added `place_order` to the adapter, Schwab would reject the call. Belt-and-suspenders against accidental execution.

## References

- Schwab Trader API (Individual): <https://developer.schwab.com/products/trader-api--individual>
- Spec: `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` §4.6, §7 Q5
- Schema contract: `db/migrations/007_v3_watchlist_positions.sql`
- README: `src/mcp/broker_mcp/README.md`
