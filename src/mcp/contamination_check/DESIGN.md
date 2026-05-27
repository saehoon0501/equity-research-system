# Mechanical Contamination Check — Design Memo

**Status:** Design only. No implementation. Targets BUILD_LOG.md Tier 2 step: "Mechanical contamination check implemented as enforced hook within slash-command wrapper logic."

---

## 1. Recommendation: MCP tool, not a skill helper

**Build this as an MCP server at `src/mcp/contamination_check/`, parallel to `src/mcp/postgres/`.** Per decision 6, Claude Code is the brain and code is a tool *consumed by* it. A skill helper Python module would be invoked by slash-command wrapper logic as a subprocess — but that subprocess pattern means the brain would be reasoning about a `subprocess.run` return code rather than calling a typed capability through the MCP surface where every other capability lives.

The check is load-bearing: per `contamination-check.md` it is *the* defense under Path A (decision 1) once model-family diversity is gone. Load-bearing capabilities deserve the same surface as `mcp__postgres` — discoverable by name, invokable from any subagent (`evaluator` already declares `mcp__postgres` as a tool; it will declare `mcp__contamination_check` the same way), and surfaced to the slash-command body as `mcp__contamination_check.verify(...)`. Skill helpers are appropriate when the capability is private to one slash command. This one is consumed by `evaluator` (subagent), `/research-company` (slash command release gate), `/evaluate` (manual re-eval), and Checkpoint 3 audit. Promote it to MCP.

The `src/mcp/postgres/` server is the precedent: ~150 lines of Python, FastMCP, `.env` for config, decision-6 canonical shape. Mirror it.

---

## 2. Tool surface

Server name: `mcp__contamination_check`. Three tools:

```python
@mcp.tool()
def verify(agent_run_id: str, evidence_index_refs: list[str], claims: list[dict]) -> dict:
    """Hard-gate verification of an agent output against the Evidence Index.

    Args:
        agent_run_id: UUID grouping all claims from this agent invocation.
        evidence_index_refs: list of evidence_id UUIDs the output cites.
        claims: list of {claim_text, claim_type, evidence_id, resolution_date}
                where claim_type ∈ {numerical, qualitative, prediction, dated_fact}
                and resolution_date is ISO-8601 (YYYY-MM-DD).

    Returns:
        {
          "verdict": "PASS" | "FAIL",
          "agent_run_id": "<uuid>",
          "checked_at": "<iso-8601>",
          "summary": {"n_claims": N, "n_refs": M, "n_failures": K},
          "failures": [
              {
                "claim_text": "...",
                "evidence_id": "<uuid|null>",
                "failure_mode": "MISSING_REF" | "FABRICATED_UUID" |
                                "POSTDATED_SOURCE" | "INCOHERENT_PREDICTION" |
                                "EMPTY_REFS",
                "diagnostic": "human-readable explanation",
                "source_date": "<iso-8601|null>",
                "resolution_date": "<iso-8601|null>",
              },
              ...
          ]
        }

    On any failure_mode appearing in `failures`: verdict = "FAIL". Hard gate.
    """
```

```python
@mcp.tool()
def verify_memo(memo_path: str) -> dict:
    """Convenience wrapper. Reads a memo JSON file from disk, extracts the
    `evidence_index_refs` and `reviewable_predictions` fields plus heuristic
    claims (sentences with numbers/dates/named-facts), then calls verify().

    For ad-hoc audit at /evaluate. Production path is verify() called from the
    Evaluator subagent, which has structured access to the output.
    """
```

```python
@mcp.tool()
def diagnostic(agent_run_id: str) -> dict:
    """Read-only — returns Evidence Index rows for an agent_run_id alongside
    a re-run of verify() against the row set. Used by Checkpoint 3 manual
    audit and by /evaluate when the operator wants to re-examine a stored memo.
    """
```

**Error cases:** (a) `mcp__postgres` unavailable → tool raises; Evaluator's "REJECT all outputs by default" rule fires upstream. (b) Malformed claim record (missing `resolution_date` for `dated_fact`/`prediction`) → fail-closed: that claim is FAIL with `failure_mode="MALFORMED_CLAIM"`. (c) `evidence_index_refs` is `[]` → see edge cases §4.

---

## 3. Algorithm

**Claim parsing.** Two paths:

1. **Structured path (preferred).** The CompanyDeepDive memo's section 13 already lists `evidence_index_refs` (UUIDs) and section 12 lists `reviewable_predictions` with explicit `resolution_date`. The Evaluator subagent passes a `claims` list it has already extracted from the structured output. The check does *not* re-tokenize prose.
2. **Heuristic fallback (`verify_memo` only).** Sentences containing (a) digit-with-unit (%, $, x, bps, M/B), (b) ISO/US date patterns, or (c) all-caps tickers/named-facts. Every such sentence must map to an `evidence_id` in `evidence_index_refs` or it's a claim-without-source — counts as `MISSING_REF`. Heuristic is fail-closed (false positives become operator-visible flags, not silent passes).

**Per-claim verification.** For each `claim`:

```
1. If claim.evidence_id is None and claim.claim_type ∈ {numerical, dated_fact, prediction}:
       → MISSING_REF (hard fail)
   If claim.evidence_id is None and claim.claim_type == qualitative:
       → skip (qualitative claims exempt from Evidence Index per schema §"What counts")

2. SELECT evidence_id, source_date, source_uri, claim_type
   FROM evidence_index WHERE evidence_id = claim.evidence_id

3. If row not found → FABRICATED_UUID (hard fail)

4. resolution_date = compute_resolution_date(claim):
     - claim_type='dated_fact':       date the fact occurred (claim.resolution_date supplied by caller)
     - claim_type='numerical' (current state, e.g., "net debt is $2.4B"):
                                      surfaced_date = today
     - claim_type='numerical' (historical, e.g., "Q3 2024 revenue grew 23%"):
                                      end of the referenced period
     - claim_type='prediction':       prediction.target_date (must be > today)

5. If row.source_date > resolution_date → POSTDATED_SOURCE (hard fail; this is
   the contamination signature the check exists to catch)

6. If claim_type='prediction' and resolution_date <= today
                                  → INCOHERENT_PREDICTION (self-resolving, hard fail)
```

**Failure mode.** ANY claim with any `failure_mode` → `verdict="FAIL"`. This is the hard gate. No partial credit, no severity weighting, no semantic override. Mechanical means mechanical.

---

## 4. Edge cases

| Case | Handling |
|---|---|
| Claim with no `evidence_id` reference, `claim_type='qualitative'` | PASS (qualitative exempt per schema). |
| Claim with no `evidence_id` reference, any other `claim_type` | `MISSING_REF` → FAIL. |
| `evidence_id` referenced but row absent | `FABRICATED_UUID` → FAIL. The contamination signature when the agent invents a UUID. |
| `source_date > resolution_date` | `POSTDATED_SOURCE` → FAIL. The post-dating contamination this check exists to catch. |
| `source_date == resolution_date` (boundary) | PASS. The schema query uses `<=`. Same-day allowed because filings/transcripts published the same day a claim resolves are valid sources. |
| Multiple claims in one sentence | One row per distinct fact per schema §"Edge cases". The structured path receives N claim records; the heuristic path tokenizes by sentence then re-splits on connectives ("and", "while", ";"). Heuristic is best-effort; structured path is canonical. |
| Forward-looking statement (`prediction`) | `source_date` (when guidance was issued) ≤ `surfaced_date` (today) AND `target_date` > today. Both checked. Self-resolving prediction (target_date already past) → `INCOHERENT_PREDICTION`. |
| Empty `evidence_index_refs` | `EMPTY_REFS` → FAIL by default. Override only with explicit `claims=[]` and a `qualitative_only=true` flag (operator opt-in; logged). Per `contamination-check.md` test case 4. |

---

## 5. Dependencies

- `mcp__postgres` for read-only `SELECT` against `evidence_index`. The contamination check **never writes** — writes are the agent's job per `evidence-index-schema.md` §"Write procedure". The check is consumer of the index, not producer.
- `psycopg`, `python-dotenv`, `mcp>=1.0.0` (mirror `src/mcp/postgres/pyproject.toml`).
- Postgres connection: same `.env` as `mcp__postgres` — single source of truth.

---

## 6. Where it attaches in slash-command flow

Trace through `/research-company`:

1. **Step 2 (CompanyDeepDive subagent).** CompanyDeepDive writes Evidence Index rows, produces memo with `evidence_index_refs`. Submits to Evaluator (subagent post-processing).
2. **Inside Evaluator subagent.** `evaluator.md` HG-1 explicitly says: *"Per `contamination-check.md` ... do it as a Postgres query, not as a vibes check."* The Evaluator calls `mcp__contamination_check.verify(...)` as the FIRST hard gate (cheapest and most definitive, per evaluator.md §"Process" step 2). If FAIL → return REJECT to CompanyDeepDive; subagent revises (≤3 rounds).
3. **Slash command release gate.** `/research-company` step 2 reads Evaluator's verdict. If REJECT after 3 rounds → halt. If ACCEPT → proceed to BearCase.
4. **Same pattern for BearCase (step 3).**
5. **`/evaluate` (secondary call site).** The manual re-evaluation command invokes the `evaluator` subagent which runs the same `mcp__contamination_check.verify` call. The slash command itself does not invoke the check directly — it goes through the Evaluator.

**Attachment point: inside the `evaluator` subagent**, called as `mcp__contamination_check.verify(...)`, BEFORE any soft scoring. The slash command's release-gate logic checks the Evaluator's overall verdict, not the contamination check directly. This keeps the brain (Claude Code, via Evaluator) in charge of orchestration; the MCP tool is a typed capability — decision 6 satisfied.

---

## 7. Implementation note for next step

**Files to create:**

- `src/mcp/contamination_check/server.py` — FastMCP server, three tools above. Mirror `src/mcp/postgres/server.py` shape.
- `src/mcp/contamination_check/pyproject.toml` — same deps as postgres MCP plus nothing new.
- `src/mcp/contamination_check/README.md` — bring-up doc.
- Update repo-root `.mcp.json` to launch `mcp__contamination_check` alongside `mcp__postgres`.
- Update `.claude/agents/eval/evaluator.md` `tools:` line to add `mcp__contamination_check`.

**Smoke test (matches `contamination-check.md` §"Test cases for week 6 implementation"):**

```python
# tests/test_contamination_check.py
# Synthetic data: insert 3 evidence_index rows with known dates.
# Case 1: claims all reference existing rows, source_date < resolution_date → PASS
# Case 2: one claim references a non-existent UUID → FAIL (FABRICATED_UUID)
# Case 3: claim resolution_date = 2024-09-30, source_date = 2024-12-15 → FAIL (POSTDATED_SOURCE)
# Case 4: evidence_index_refs=[] without qualitative_only override → FAIL (EMPTY_REFS)
# Case 5: prediction with target_date in the past → FAIL (INCOHERENT_PREDICTION)
# Boundary: source_date == resolution_date → PASS
```

**Synthetic data needed:** 3-5 hand-rolled `evidence_index` rows with deterministic UUIDs (use `uuid.uuid5` from a fixed namespace so tests are reproducible) and deterministic `source_date`. Run against the local Postgres from `docker-compose.yml`. Tear down via the append-only-respecting path: `TRUNCATE evidence_index RESTART IDENTITY` is permitted in test setup only via a separate test schema, not the production `evidence_index` table — append-only is real.

**Order of work:** server.py → smoke tests → `.mcp.json` update → `evaluator.md` update → end-to-end test where Evaluator subagent calls the check via MCP. Do not skip the end-to-end test; that's the actual decision-6 validation.
