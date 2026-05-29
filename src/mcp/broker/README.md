# `broker` MCP — Gate TradFi CFD execution adapter

A vetted, leaf-level execution adapter for the **Gate TradFi CFD venue**
(`https://api.gateio.ws/api/v4/tradfi/*`). It turns a thresholded Edge signal —
expressed in the canonical BUY/HOLD/TRIM/SELL vocabulary plus a long/short
direction — into a position, and reads back positions, account assets, tradable
symbols, and history with venue-authoritative values.

This is the **most conservative node** in the reactive execution chain (P7): it
validates and rejects, never sizes, scores, upsizes, or computes survival math.

## v0.1 posture — paper-only

**v0.1 ships with no enabled live real-money path** (Requirement 8.1). The
adapter operates in paper/dry-run mode only: it runs the full validation chain
and returns a structured *simulated* confirmation priced from the venue
bid/ask, without invoking the venue order-create operation. A live transmit is
gated behind a four-condition AND — paper mode explicitly disabled, account
active, a `survival-gate` clearance signal present, and the kill switch clear —
and no enabled path reaches it in v0.1.

## Dual surface

Unlike the other house MCP servers, this one exposes two surfaces over a single
validated path:

- **MCP tools** — the Claude → tool seam, thin `@mcp.tool()` wrappers in
  `server.py` that coerce typed results to `dict` and never raise.
- **Importable leaf functions** — the `execution-daemon` calls the same
  operations in-process by importing `core`, outside the MCP transport.

## Configuration

In the repo-root `.env` (gitignored; read fresh per call so credential rotation
needs no restart, never logged, never returned in results):

```
GATE_API_KEY=...      # Gate TradFi CFD execution venue
GATE_API_SECRET=...   # APIv4 SIGN (HMAC-SHA512) secret
```

The Gate CFD execution venue is **distinct** from the pre-existing
`BROKER_PROVIDER=schwab` block (read-only positions, slow layer). The two are
separate venues with separate credentials.
