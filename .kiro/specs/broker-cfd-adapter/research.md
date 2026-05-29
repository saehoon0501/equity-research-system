# Research & Design Decisions

## Summary
- **Feature**: `broker-cfd-adapter`
- **Discovery Scope**: New Feature / Complex Integration (new leaf-level MCP server wrapping an external venue API — Gate TradFi CFD)
- **Key Findings**:
  - The venue API is fully specified (`gate-tradfi-api-reference.md`); the design rests on verified endpoints/fields, not assumptions. Residuals (`gate-api-gaps.md`) are build-time confirmations, none blocking.
  - The house MCP pattern (`src/mcp/<name>/server.py`, FastMCP, `@mcp.tool()`, dict returns) has **no precedent for separating importable leaf functions from MCP tool registration** — the daemon-callable leaf functions this spec requires are a new intra-server split (`core.py` ↔ `server.py`).
  - A working reference implementation of the `/tradfi/*` surface exists (`gate/gate-local-mcp`) — adopted as the P12/P14 validation reference only, **not** a runtime dependency (operator decision 2026-05-29).

## Research Log

### Gate TradFi CFD venue API
- **Context**: The adapter must place/manage orders and read positions/account against Gate TradFi (forex + CFD on MT5).
- **Sources Consulted**: `gate-tradfi-api-reference.md` (operator-supplied official spec), `gate-api-gaps.md` (residual tracker), `gate-research-findings-2026-05-29.md` (deep-research, 104 agents / 18 confirmed claims), exploration `docs/exploration-systematic-flow-architecture-2026-05-28.md` §11–§14.
- **Findings**:
  - Signed REST APIv4 (key+secret HMAC-SHA512 SIGN); base `https://api.gateio.ws/api/v4/`. No MT5 bridge; REST proxies only. TradFi service must be **activated** (account `status` 3=active).
  - Orders are **asynchronous**: `POST /tradfi/orders` returns a Queue Task ID, not an order/position id → must poll `/tradfi/orders` + `/tradfi/positions` to confirm.
  - TRIM/SELL = **close-by-`position_id`** via `POST /tradfi/positions/{id}/close` (`close_volume` null=full, partial=TRIM). No symbol-level netting close.
  - **Leverage is not a per-order parameter** — fixed per-instrument (US-stock CFDs 5x; no setter endpoint). Exposure is controlled via order `volume`, bounded by per-symbol `min/max_order_volume`.
  - Critical enums: `side` 1=SELL / 2=BUY (counterintuitive — guard off-by-one); `trade_mode` 0=disabled/1=long-only/2=short-only/3=close-only/4=full; `position_status` history 2=forced liquidation; `order_opt_type` 5/6 = force-close long/short.
  - Enforcement-critical fields (`leverage`, `min/max_order_volume`, swap rates, `price_sl_level`) live on **authenticated** `GET /tradfi/symbols/detail` (≤10 symbols/call → ~45 calls to cache all 441 names). Public `GET /tradfi/symbols` gives only `status`/`trade_mode`/`next_open_time`/`price_precision`/`settlement_currency`.
  - No native paper/dry-run mode → must simulate in-adapter (price from `tickers` bid/ask). No client-order-id/idempotency key → double-send protection is adapter-side.
  - Rate limits: no published `/tradfi` row; global `api/v4` rule + `X-Gate-RateLimit-*` headers + HTTP 429 govern → discover at runtime.
- **Implications**: drives the async submit→poll→reconcile core, the close-by-position-id mapping, the volume-only exposure model, the authenticated symbol-detail cache, the in-adapter paper simulator, the double-send guard, and runtime rate-limit discovery.

### Existing Gate MCP servers (build-vs-adopt input)
- **Context**: Could an existing implementation be adopted as transport instead of building signed-REST in-house?
- **Sources Consulted**: `gate/gate-mcp` (hosted, OAuth2, 400+ tools incl. TradFi) and `gate/gate-local-mcp` (npm `gate-mcp` ≥0.19.0, TypeScript stdio, `GATE_API_KEY/SECRET`, `--modules=tradfi`, `GATE_READONLY`) — both verified existent 2026-05-29 (gh api + npm registry).
- **Findings**: both are general-purpose exchange MCPs (MCP-only, no in-process leaf funcs, no enforcement/paper-sim/gating layer). The local variant uses the same APIv4 key+secret model and covers the `/tradfi/*` surface.
- **Implications**: **Reference + validation only** (operator decision 2026-05-29). Used read-only as the P12/P14 authenticated round-trip to ground-truth field names, the async lifecycle, `close_type` 1/2, and the rate-limit headers; not vendored (Node/MCP-only, out of posture, gives no in-process functions). Recorded in `gate-api-gaps.md`.

### Codebase pattern map
- **Context**: The adapter must conform to house style (P1, T2).
- **Sources Consulted**: `src/mcp/massive/`, `src/mcp/polygon/`, `src/eval/gates/`, `src/calibration/scorer.py`, `tests/`, `.mcp.json`, `.env.example` (codebase-analysis subagent, 2026-05-29).
- **Findings**:
  - Server pattern: `src/mcp/<name>/{server.py,pyproject.toml,README.md}`; `mcp = FastMCP("<name>")`; `@mcp.tool()` (sync/async) returning `dict` and never raising; `if __name__ == "__main__": mcp.run()`. `pyproject.toml` minimal: `requires-python = ">=3.11"`, `mcp>=1.0.0`, `httpx`, `python-dotenv`; `tool.uv.package = false`.
  - `.mcp.json`: `"<name>": {"command":"uv","args":["run","--directory","src/mcp/<name>","python","server.py"],"cwd":"."}`. No `env` block — keys read from repo-root `.env` at import time via `load_dotenv`.
  - Secrets read fresh per call (key rotation without restart): `os.environ.get("X_API_KEY","").strip()`.
  - P9 vocabulary canonical: `class Label(str, Enum)` at `src/calibration/scorer.py:28` (BUY/HOLD/TRIM/SELL). **Import, never redefine.**
  - Sleeve-cap/tier vocabulary at `src/eval/gates/sizing_math.py` (`VALID_TIERS`) — **not** used by the broker (survival-gate owns sleeve enforcement).
  - Tests: `tests/{unit,integration,contract,fixtures,regression}/`; `tests/conftest.py` loads `.env`; markers `integration` + `integration_live`; MCP servers loaded in tests via `importlib.util` + `skipif` on key presence.
  - Stale `src/mcp/broker_mcp/` exists in the main repo only (empty `__pycache__`/`adapters/`); absent from this worktree. Canonical host dir = `src/mcp/broker/`.
- **Implications**: clone the FastMCP server shape; add the `core.py`/`server.py` split for daemon-callable leaf funcs; import `Label`; add `GATE_*` to `.env.example`; register `broker` in `.mcp.json`; unit-test leaf funcs with a mocked transport.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Layered ports-and-adapters (chosen) | Types → Config → Transport → Cache/Mappers → Validation → Paper → Core(leaf funcs) → MCP server | Pure testable core; daemon imports leaf funcs directly; transport swappable; matches the spec's "leaf MCP tool + importable funcs" | Introduces a new intra-server split not seen in other `src/mcp` servers | Aligns P1 (leaf tool), P7 (validation as a one-way gate), P14 (pure-unit inner ring) |
| Single-module server (status quo) | Everything inline in `server.py`, helpers prefixed `_` (massive/polygon style) | Matches existing servers exactly | No importable in-process functions for the daemon; validation + transport + sim entangled → hard to unit-test | Rejected — fails the daemon-leaf-function requirement |
| Vendor `gate-local-mcp` as transport | Wrap the third-party MCP/SDK | No signing code to write | Node/MCP-only; no in-process funcs; external dependency out of paper posture | Rejected as runtime dep; kept as validation reference |

## Design Decisions

### Decision: Split `core.py` (leaf functions) from `server.py` (MCP tools)
- **Context**: 1.* / 2.* / 3.* / 10.* must be callable by the execution-daemon **in-process, not via MCP** (requirements intro; brief), while also exposed as MCP tools.
- **Alternatives Considered**: 1) single-module server (house default); 2) two packages.
- **Selected Approach**: one server package; `core.py` holds pure importable operation functions returning typed results; `server.py` holds thin `@mcp.tool()` wrappers that call `core` and coerce to `dict`, never raising.
- **Rationale**: gives the daemon a stable Python interface and keeps the MCP seam thin; both surfaces share one validated code path (no drift).
- **Trade-offs**: a new pattern vs the other servers; justified by the explicit dual-surface requirement.
- **Follow-up**: confirm `uv run` import path works for both the MCP launch and a daemon `import`.

### Decision: Generalize enforcement into an ordered validation chain
- **Context**: 1.5/1.6/1.8/1.9/1.10/1.11, 4.2/4.3, 5.1/5.2, 6.1, 7.1/7.2/7.3, 8.3/8.4/8.5 are all pre-transmit rejections.
- **Selected Approach**: `validation.py` exposes pure predicates composed into a single ordered chain run before any transmit; first failure short-circuits to a structured `RejectionReason`; the chain never modifies the request (the "reject, never upsize" contract, P7).
- **Rationale**: one cohesive, exhaustively unit-testable gate instead of scattered checks; the order is the audit-able policy.
- **Trade-offs**: callers must read a structured rejection, not an exception.
- **Follow-up**: lock the chain order in tests so reordering is a visible change.

### Decision: Build a thin signed-REST client; do not vendor a third party
- **Context**: APIv4 HMAC-SHA512 SIGN over `/tradfi` paths; the official SDK does not cover TradFi.
- **Selected Approach**: `gate_client.py` over `httpx` (already in the stack); implements SIGN, rate-limit header parsing + 429 backoff; returns raw venue JSON only (no business rules).
- **Rationale**: smallest dependency surface; matches the paper-only self-hosted posture; `gate-local-mcp` validates our field names/lifecycle without being imported.
- **Trade-offs**: we own the signing code (covered by the P12/P14 live round-trip).

### Decision: In-adapter paper simulation as a mode flag, not a parallel implementation
- **Context**: 8.1/8.2 — no native venue dry-run; v0.1 is paper-only.
- **Selected Approach**: a single validated path; at the transmit seam, paper mode routes to `paper.py` (price from `tickers` bid/ask, structured simulated confirmation, no POST) instead of `gate_client`. Live transmit additionally requires all four clearances (8.3).
- **Rationale**: paper and live share the identical validation + mapping path → paper coverage is meaningful for live behavior.

### Decision: No HG envelope validator; no multi-provider abstraction
- **Context**: P11 HG validators are for envelope-emitting agents; `BROKER_PROVIDER=schwab` exists in `.env.example`.
- **Selected Approach**: the broker is deterministic Python returning structured dicts → inner-ring = pure unit tests + contract/golden tests (P14), not an HG validator. One Gate implementation only; the `core.py` leaf-function signatures are the de-facto interface a future provider could match — **generalize the interface, not the implementation** (no provider-abstraction layer built now).
- **Rationale**: avoids speculative abstraction; keeps the design the smallest one that satisfies the requirements.

## Risks & Mitigations
- **Venue API drift** (TradFi is a Jan–Mar 2026 moving product, ~v4.106) — Mitigation: the P12/P14 authenticated round-trip + `gate-local-mcp` read-only cross-check before trust; revalidation trigger documented.
- **Async/no-idempotency double-send → duplicate independent position** — Mitigation: double-send guard (7.4) polls active orders/positions before any resend.
- **Gap-through-stop / no-NBP tail risk** — out of this spec's boundary (survival-gate owns it); the adapter only surfaces the account/stop-out fields it needs (3.2). Documented so it is not silently absorbed here.
- **Authenticated symbol-detail cache staleness** (trade_mode could change) — Mitigation: cache freshness policy + refresh on validation miss; documented as a performance/consistency note.
- **`close_type` 1/2 semantics unconfirmed** — Mitigation: confirm on first authenticated close (build-time); mapping isolates it in `mappers.py`.

## References
- `.kiro/specs/broker-cfd-adapter/gate-tradfi-api-reference.md` — primary venue API spec (endpoints, enums, gotchas).
- `.kiro/specs/broker-cfd-adapter/gate-api-gaps.md` — residual tracker + P12/P14 validation-vehicle decision.
- `.kiro/specs/broker-cfd-adapter/gate-research-findings-2026-05-29.md` — deep-research (leverage, NBP, rate limits).
- `docs/exploration-systematic-flow-architecture-2026-05-28.md` §11–§14 — strategic record.
- `src/mcp/massive/`, `src/mcp/polygon/` — house MCP server pattern. `src/calibration/scorer.py` — `Label` enum (P9).
- [gate/gate-local-mcp](https://github.com/gate/gate-local-mcp) / npm `gate-mcp` — validation reference (read-only).
