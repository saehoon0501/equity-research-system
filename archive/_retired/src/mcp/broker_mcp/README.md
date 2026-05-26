# `mcp__broker` server

Read-only broker MCP server for the equity research system. Per `docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md` Section 4.6 (L5/L6 — execution output) + Section 7 Q5 (broker MCP read-only positions endpoint).

**Scope discipline:** This server is READ-ONLY. There is no `place_order` tool and there will not be one at v0.1. Per Section 7 Q5 lock the system does not execute trades; positions are observed, not commanded.

| Tool | Purpose | Notes |
|---|---|---|
| `mcp__broker__get_positions(account_id_hash)` | Current portfolio snapshot | Cached at the daily-cadence floor (Section 7 Q3); restart MCP to clear |
| `mcp__broker__get_account_summary(account_id_hash)` | Cash + total-value snapshot | Same caching |
| `mcp__broker__poll_for_fills(account_id_hash, since_timestamp, previous_snapshot)` | Detected BUY/SELL/DIVIDEND/SPLIT/TRANSFER events since `since_timestamp` | Diff against caller-supplied previous snapshot + broker transactions feed; reconciled into canonical `FillEvent` |

`account_id_hash` is the broker-side opaque hash of the account (Schwab calls it `hashValue`). Raw account numbers must NEVER be passed in or out of this MCP.

## v0.1 = Schwab only

The first broker is Schwab — chosen because of post-TDA acquisition openness of its developer API and the absence of paid market-data licensing requirements for positions / transactions endpoints. v0.5+ may add IBKR / Fidelity by registering additional `BrokerAdapter` subclasses in `server.py:_ADAPTERS`; the MCP tool surface does not change.

## Bring-up — operator-driven OAuth (one time per machine)

This is the manual step gated by Section 7.1 ("Broker MCP OAuth flow tested; token refresh validated"). It must be done by the operator before the MCP can return any data.

### 1. Register an app on the Schwab developer portal

Go to <https://developer.schwab.com>, register an app, request the Trader API (Individual). Note:

- **Callback URL** must match what you'll provide in step 3 below. `https://127.0.0.1:8443/callback` is the standard local-loopback choice.
- **Scope:** `readonly`. The system does not need any write or trade-execution scope.
- After Schwab approves the app (this can take several days), you receive a `client_id` and `client_secret`.

### 2. Add credentials to `.env`

Add the following keys to the repo-root `.env` file (gitignored):

```
SCHWAB_CLIENT_ID=...your client id...
SCHWAB_CLIENT_SECRET=...your client secret...
BROKER_PROVIDER=schwab
```

### 3. Run the authorize flow

The operator-driven authorize flow exchanges your Schwab login for a long-lived `refresh_token` and a short-lived `access_token`:

```sh
# From repo root, with deps installed:
uv sync --project src/mcp/broker_mcp

# Run the authorize flow (this will open a browser):
uv run --project src/mcp/broker_mcp python -c "
from broker_mcp.schwab_adapter import SchwabAdapter
# (Schwab's OAuth requires interactive browser authorization on the first run.
# Follow the printed prompts; paste the redirect URL back into the terminal.)
print('See README §3 — authorize flow is operator-interactive at v0.1.')
"
```

At v0.1 the authorize flow is **operator-interactive on first run**. The Schwab Trader API requires a real browser session for the consent page (no headless flow exists). After the operator completes consent, the redirect URL contains a `code=...` query param; paste that back into the terminal prompt and the adapter will exchange it for tokens via `oauth.refresh_access_token`-equivalent. Tokens are written to `.env` via `oauth.save_tokens`.

After step 3, `.env` should additionally contain:

```
SCHWAB_ACCESS_TOKEN=...
SCHWAB_REFRESH_TOKEN=...
SCHWAB_TOKEN_EXPIRES_AT=1735689600   # epoch seconds
```

### 4. Smoke test

```sh
uv run --project src/mcp/broker_mcp python -c "
from broker_mcp.server import get_positions
print(get_positions('your-account-hash-here'))
"
```

If you see a `BrokerAuthError`, the refresh token expired (Schwab refresh tokens are 7 days) — re-run step 3.

If you see a `BrokerRateLimitError`, the daily cache has been disabled or you've hit Schwab's rate limit; the app layer should set a degraded-broker flag on the positions row (per Phase 4 Q9) and try again later.

## Token refresh

Refresh is automatic on every tool call: the adapter checks `SCHWAB_TOKEN_EXPIRES_AT` and exchanges the refresh token for a new access token if expiration is within 60 seconds. The new tokens are written back to `.env`.

**Schwab refresh tokens last 7 days.** If the operator does not run the MCP for >7 days, they will need to re-run the operator-interactive authorize flow (step 3 above). At v0.5+ this is a candidate for automation via a scheduled refresh routine.

## Debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| `BrokerConfigError: SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET must be set` | `.env` missing keys | Add per step 2 |
| `BrokerAuthError: No Schwab OAuth tokens in .env` | Authorize flow not run | Run step 3 |
| `BrokerAuthError: Schwab token refresh failed (HTTP 400)` | Refresh token expired (>7d idle) | Re-run step 3 |
| `BrokerRateLimitError: Schwab GET ... exhausted retries` | Schwab rate-limited; backoff schedule (0.5s/1s/2s/4s) exhausted | Wait + retry; app layer should set degraded-broker flag |
| Empty positions list when account has positions | `account_id_hash` mismatch | Schwab returns the hash on `GET /trader/v1/accounts/accountNumbers`; confirm you are using the right one |

## How connection info is loaded

`server.py` walks up to repo root and loads `.env` via `python-dotenv` — same single source of truth as `mcp__edgar` and `mcp__postgres`.

### Required env

| Var | Required | Purpose |
|---|---|---|
| `BROKER_PROVIDER` | no (default `schwab`) | Selects adapter class from `_ADAPTERS` registry |
| `SCHWAB_CLIENT_ID` | yes (Schwab) | OAuth client id from developer portal |
| `SCHWAB_CLIENT_SECRET` | yes (Schwab) | OAuth client secret from developer portal |
| `SCHWAB_ACCESS_TOKEN` | populated by authorize flow | Bearer token on API calls |
| `SCHWAB_REFRESH_TOKEN` | populated by authorize flow | Used to mint new access tokens |
| `SCHWAB_TOKEN_EXPIRES_AT` | populated by authorize flow | Epoch seconds; access-token expiry |

## What this is not

- **Not a trading interface.** No `place_order`. Per Section 7 Q5 lock the system observes positions; it does not execute.
- **Not multi-broker simultaneously at v0.1.** One adapter active per process per Phase 4 deferral. v0.5+ may load multiple.
- **Not the source of truth for HMAC-signed thesis pillars.** That is `watchlist.thesis_pillars_original_hmac` per `db/migrations/007_v3_watchlist_positions.sql`. The broker MCP only returns positions data; HMAC verification stays at the application layer.
- **Not tax-lot-aware beyond FIFO.** Per Section 8.1 deferral. Schwab's positions endpoint exposes only an `averagePrice`, not per-lot acquisition dates; the position_history reconciler in the app layer is responsible for per-lot FIFO accounting from observed BUY events.
- **Not a connection pool.** New `httpx.Client` per tool call. v0.1 single-operator usage.

## Why a thin wrapper

Same rationale as `mcp__edgar`: the underlying truth is the broker's HTTP API. A thin httpx wrapper is auditable end-to-end (every request to Schwab is visible in `schwab_adapter.py`). The schema discipline (canonical `PositionRecord` / `AccountSummary` / `FillEvent` TypedDicts in `adapters/base.py`) means swapping in IBKR / Fidelity at v0.5+ does not require changes anywhere outside that adapter file.
