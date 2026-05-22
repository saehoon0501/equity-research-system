# Nested-Subagent MCP — Design Conversation History

**Date:** 2026-05-22
**Topic:** Iterative design of an MCP server enabling a Claude Code main session to spawn another main session as a tool call, with depth-cap enforcement and per-call visibility.
**Outcome:** v7 minimal — 2 files, ~60 lines of Python, after 6 review iterations and one full architectural collapse.

---

## Phase 0 — Starting point

**Operator** shared a package at `~/Downloads/nested-subagent-3layer/` containing 7 files (mcp_server.py, .mcp.json, .claude/agents/job-runner.md, .claude/hooks/{record_task_start,subagent_aggregate,inject_job_aggregate}.py, .claude/settings.json, README.md, INTEGRATION_PROMPT.md) implementing a 3-layer orchestration pattern — orchestrator → job-runner subagent → `nested_task` MCP tool → `claude -p` Layer-2.

**Background notes from operator:** Anthropic's official position is that subagents are flat; nested subagent hierarchy has no prior art. The package was being prototyped for an AX Incubation Camp demo. Two architectural directions identified — (A) full disler/cast-observe stack with our MCP wrapping it, or (B) minimal deterministic handoff via hooks. The package took direction B.

The package's claimed end-to-end smoke test produced:
```
[job aggregate] job_total_cost_usd=0.04655 nested_calls=2 max_depth_reached=1 nested_session_ids=...
```
gets injected into the orchestrator's context, with temp file cleanup.

---

## Phase 1 — /review-me convergence (v1 → v6)

Operator invoked `/review-me` with argument "cover all engineering side for this mcp" to pressure-test the v1 package across all engineering surfaces (correctness, concurrency, security, failure modes, observability, portability, lifecycle, API contracts, cost-model integrity, doc accuracy).

### Convergence table

| Iteration | Substantive issues caught | Direction |
|---|---|---|
| v1 → v2 | 16 (orchestrator-bypass, env-respawn-depth, argv-injection, parallel-collision, /tmp-symlink, footer-double-count, silent-OSError, ordering, JSON-noise, matcher-fragility, is_error-cost-loss, 60s-timeout, chmod-doc, sep, resume-incoherent, plus 1) | added (spec-level fixes) |
| v2 → v3 | 8 substantive (2 cuts: D3 stream-stdin, env-override) | mixed |
| v3 → v4 | 5 (3 cuts: PID-list→heartbeat, global-sweep→per-session-subdir, debug-ceremony→dev-script) | cutting |
| v4 → v5 | 2 (A1 window allows live-slow false-reset, B1 AND→OR asymmetry) | mixed |
| v5 → v6 | 1 substantive (B1 clause c always-true) + 1 polish | cut |
| v6 | 0 substantive | **converged** — "v6 looks solid, no substantive issues" |

Total: 6 iterations, ~32 substantive catches, 7 cuts, terminated on explicit reviewer signal.

### Key BLOCKER findings

**BLOCKER-1 — Orchestrator bypass.** `nested_task` is globally visible. Main session calls it directly → no SubagentStop → no `[job aggregate]` injection → cost incurred but invisible.

**BLOCKER-2 — Env depth doesn't survive nested respawn.** Nested `claude -p` spawns its own MCP server that may not inherit `CLAUDE_NESTING_DEPTH`. Whether the env var propagates through `.mcp.json`'s env-merge semantics determines whether depth gate can be bypassed at depth=2+.

### v6-final highlights

- **A1**: depth+heartbeat in `.nesting-state.json` with `fcntl.flock(LOCK_EX)`; clamped `timeout_seconds ∈ [60, 3600]`; staleness window 7200s.
- **B1**: new `gate_nested_task.py` PreToolUse hook denying main-session callers via `agent_id` empty OR `subagent_type` absent.
- **A2**: regex-validate `resume_session_id`, NUL/length check on `append_system_prompt`, `--append-system-prompt=<val>` equals form, `--` separator.
- **A4**: always emit footer with status ∈ {ok, error, timeout, parse_fail}.
- **A5**: balanced-brace last-`{...}` extraction.
- **C1**: structured walk for `tool_result` blocks paired with `tool_use name=="mcp__nested-subagent__nested_task"`; dedupe by `(session_id, tool_use_id)`.
- **D1**: three-tier correlation — floor=transcript-scrape, lift=parent_tool_use_id, last-resort=time-window. Honest "best-effort with documented precedence" claim.
- **E1**: per-user-per-session tempdir, mkdir 0700, post-stat ownership check, `O_NOFOLLOW|O_EXCL|0o600`.

### Seven cuts applied during v1 → v6

1. D3 stream-stdin (premature optimization)
2. Env-override on depth (footgun: stale env wedges depth permanently)
3. PID-list crash recovery → heartbeat (PID reuse unsound across containers)
4. Global 1h temp-file sweep → per-session subdir (redundant given immediate-delete)
5. debug_dump.py operator ceremony → dev-only sanity script
6. Background heartbeat-refresher thread → clamped-timeout invariant
7. B1 clause c (`session_id == main_session_id`) — always-true under Claude Code session model

---

## Phase 2 — /simplify pass (v6 → v6-simplified)

Operator invoked `/simplify` to review the v6 spec for reuse, quality, and efficiency. Three parallel review agents.

### 8 simplifications applied

| # | Change | Effect |
|---|---|---|
| S1 | `json.JSONDecoder().raw_decode()` replaces brace counter | -20 lines, stdlib |
| S2 | `tempfile.mkdtemp()` replaces mkdir + stat check | -10 lines, atomic semantics |
| S3 | Footer is single-line JSON, not `k=v` | Immune to space-in-value bugs |
| S4 | New `_constants.py` | Kills 7 magic numbers/strings in 2 files |
| S5 | `parse_fail_count` separated in injection | Correctness fix — no silent under-reporting |
| S6 | D1 docstring says "guard-clause cascade" | Prevents nested if/else impl |
| S7 | 4 hook scripts → 1 `nested_hook.py` with subcommand dispatch + lazy imports | 30-50% cold-start saved per hook |
| S8 | D2 polling gated on substring precheck | 500ms saved on no-nested-work Tasks |

### Conflict resolution

- REUSE agent said NO to `_hook_lib.py` (sys.path fragility).
- QUALITY agent said YES (15 lines × 4 saved).
- EFFICIENCY agent's H1 (consolidate to one script) resolved it — single `nested_hook.py` with subcommand dispatch, boilerplate dedup happens inside one file.

### File count: 5 Python files → 3

`mcp_server.py` + `_constants.py` + consolidated `nested_hook.py`. Net code ~150 lines, but cleaner.

---

## Phase 3 — TIMEOUT_BOUNDS bump

**Operator:** "TIMEOUT_BOUNDS -> 3600 too short, research-company usually takes more than 1hr"

**Decision:** raise upper bound to 14400 (4hr), STALENESS_SEC to 28800 (8hr — preserves 2× invariant), WARN_AGE_SEC to 1800 (30min stale warning).

Rationale: `/research-company` runs 6+ stages (cdd-lead + quantitative + strategic + tactical + catalyst-scout + pm-supervisor + evaluator) and routinely exceeds 1hr end-to-end. A single nested call wrapping a whole stage can breach 3600s.

**Override path:** documented one-line edit in `_constants.py`; STALENESS_SEC must move with the 2× rule.

---

## Phase 4 — Live-lock hybrid (v6.2)

**Operator:** "instead of timeout, hybrid approach -> live ping (by checking the subprocess session is working or not)"

Replaced heartbeat-staleness window with kernel-managed liveness via per-call `fcntl.flock` on individual lockfiles.

### Design

```python
def _count_live_and_sweep(state_dir):
    live = 0
    for path in state_dir.glob("call-*.lock"):
        fd = os.open(path, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            # Succeeded → no exclusive holder → stale → unlink
            fcntl.flock(fd, fcntl.LOCK_UN)
            try: path.unlink()
            except OSError: pass
        except BlockingIOError:
            # Someone holds exclusive → live
            live += 1
        finally:
            os.close(fd)
    return live
```

Each `nested_task` call opens its own `call-{uuid}.lock` with `LOCK_EX`, held during `subprocess.run`, released in `finally`. Kernel auto-releases on process death (including SIGKILL).

### Benefits

| | Heartbeat (v6-simplified) | Live-lock (v6.2) |
|---|---|---|
| Crash recovery latency | up to STALENESS_SEC (8hr) | instant (next call) |
| Magic numbers | 3 | 0 (sanity TIMEOUT cap only) |
| PID reuse vulnerability | n/a (used ts) | n/a (lock ownership) |
| Code complexity | RMW + heartbeat math | flock + count + sweep |

`TIMEOUT_BOUNDS` raised to (60, 86400) as pure sanity cap, no longer invariant-linked. `STALENESS_SEC` and `WARN_AGE_SEC` cut.

---

## Phase 5 — Slow-model question

**Operator:** "what happens when the model takes time to response but our process is running?"

Confirmed this is exactly the live-lock design's sweet spot. The Python MCP server process holds the flock for the entire duration of `subprocess.run` regardless of what the child is doing internally (network wait, streaming, tool-use). Siblings probe via `LOCK_SH | LOCK_NB` → BlockingIOError → correctly counted as live → respect depth.

```
t=0       MCP server enters nested_task, takes LOCK_EX on call-abc.lock
          subprocess.run([claude, -p, ...]) starts
          [Python blocked in waitpid; flock still held]
t=5min    claude subprocess waiting on API stream
t=15min   Sibling MCP server tries to nest
          → _count_live_and_sweep sees call-abc.lock locked
          → counts as LIVE → depth=1 → max=1 → REFUSED
t=20min   claude finishes, subprocess.run returns
          → finally: unlock, close, unlink
```

The legitimately slow call is indistinguishable from a fast one from the gate's POV — both hold the flock. No timer to tune.

---

## Phase 6 — Topology verification (v6.3)

**Operator:** "If I open 2 main session -> each uses the mcp tool to spawn 3 other process for running main session(these should be blocked using the mcp tool). all covered?"

Surfaced a real bug in v6.2: `_count_live_and_sweep` conflated **concurrent count** (cross-tree) with **nesting depth** (per-call-chain). Under v6.2 as written, the orchestrator's 2nd parallel call would see the 1st call still holding its flock → live=1 → depth=1 → REFUSED. Parallel fan-out from a single orchestrator broken.

### v6.3 fix — separate the two concepts

**Depth (per call-chain):** restored env-var path. Standard MCP `.mcp.json` `env` block merges on top of inherited env, so `CLAUDE_NESTING_DEPTH=1` survives the nested `claude -p` MCP server launch.

```python
current_depth = int(os.environ.get("CLAUDE_NESTING_DEPTH", "0"))
if current_depth >= max_depth:
    return "ERROR: max nesting depth reached"
env_for_child = os.environ.copy()
env_for_child["CLAUDE_NESTING_DEPTH"] = str(current_depth + 1)
```

**Liveness (diagnostic only):** per-call flock kept, but used only for gate-hook refusal-reason diagnostic, NOT for depth gating.

### Topology walkthrough

| Step | Action | Result |
|---|---|---|
| Main A spawns 3 parallel | Each child's env: CLAUDE_NESTING_DEPTH=1 | OK, 3 children at depth=1 |
| Main B independently same | Independent env chain | OK, 3 more children at depth=1 |
| Any Layer-1 child tries to nest | MCP server reads env=1, max=1 | REFUSED ✓ |
| Main A bypass attempt (calls nested_task from main) | gate hook B1: agent_id empty | DENIED ✓ |
| Crash of A2 | Kernel releases flock | Doesn't affect siblings |

All 7 requirements covered.

---

## Phase 7 — Hard vs soft rules classification

**Operator:** "distinguish the part that we need absolute guarantee -> implement code to block and prompt to behave correctly. depth cap is an example of hard rule"

### Classification matrix

| Rule | Class | Enforcement |
|---|---|---|
| Depth cap | **HARD** | env var check in nested_task |
| Orchestrator-bypass prevention | **HARD** | gate hook B1 |
| Argv-injection resistance | **HARD** | A2 regex + equals-form + `--` separator |
| Resume + nesting refused | **HARD** | A6 explicit refusal |
| Cost accounting completeness | **HARD** | A4 always-emit-footer + C1 count-all-statuses |
| Footer double-count prevention | **HARD** | C1 structured walk + dedupe |
| /tmp hijack resistance | **HARD** | E1 mkdtemp + O_NOFOLLOW |
| Resource cleanup on crash | **HARD** (kernel) | per-call flock |
| timeout_seconds bounds | **HARD** | clamp |
| Don't manually echo footers | SOFT (but hardened by C1) | job-runner.md |
| Don't retry after max-depth ERROR | SOFT | job-runner.md |
| Decompose only when beneficial | SOFT | job-runner.md |
| Slow-call timeout guidance | SOFT | job-runner.md |

### Two soft items proposed for promotion to HARD

- **H14 — Per-tree concurrency cap** (max 5 in-flight per tree) — defense against runaway fan-out token explosion.
- **H15 — Prompt size cap** (64KB) — defense against argv blowup / cost explosion.

Three considered-and-rejected: cumulative session cost cap (policy, not correctness), refused-call rate limit (refusal is cheap), self-call detection (depth cap already prevents).

---

## Phase 8 — Prompt surfaces clarified

**Operator:** "job-runner.md -> meaning tool description"

Distinguished three prompt surfaces:

| Surface | File location | Seen by | Governs |
|---|---|---|---|
| **S1** | `mcp_server.py` `@mcp.tool()` docstring | Any agent with the tool | When/why to call; parameter semantics |
| **S2** | `.claude/agents/job-runner.md` frontmatter `description:` | Orchestrator (dispatch decision) | When to dispatch a job-runner |
| **S3** | `.claude/agents/job-runner.md` body | The job-runner itself | How to behave once invoked |

Re-mapped each soft rule to its correct surface. Confirmed every soft rule has a hard counterpart so non-compliance is cost-inefficient at worst, never unsafe.

---

## Phase 9 — Concise descriptions

**Operator:** "no subagent should concise tool description"

S1 and S2 tightened to scannable forms. Tool docstrings get re-injected every turn — token bloat matters.

**S1 final (concise):**
```python
"""Spawn a fresh Claude Code main session to handle one self-contained
sub-task. The spawned session has its own Task tool and can fan out
to its own subagents.

Subagent-only. Depth-capped at 1. ~20k token overhead per call.

Args: ...
"""
```

**S2 final (one line):**
```yaml
description: Handle one orchestrator-assigned job that itself requires further subagent delegation. Dispatch one per logically independent job.
```

Length budgets locked in:

| Surface | Token budget | Why |
|---|---|---|
| Tool docstrings | ≤120 tokens | Re-injected every turn |
| Subagent frontmatter description | ≤30 tokens | One scannable line in orchestrator's picker |
| Subagent body | as needed | One-shot system prompt |

---

## Phase 10 — Architectural collapse (v6.4)

**Operator:** "anything under agents should be moved (no subagents for claude code only mcp tool)"

Cut the entire Claude Code subagent layer. Architecture goes from 3-layer (orchestrator → job-runner → claude -p) to 2-layer (orchestrator → claude -p).

### What disappeared

- `.claude/agents/job-runner.md` (S2 + S3 surfaces both gone)
- `.claude/hooks/nested_hook.py` (all 4 subcommands)
- `.claude/settings.json` (was only registering hooks)
- `tools/dump_hook_stdin.py` (was for verifying hook payload shapes)

### Why this works

The hook chain's entire value proposition was bridging the subagent↔orchestrator context gap. Remove the subagent, the gap disappears, the hooks disappear with it.

Three hard rules also dissolved because their failure mode no longer exists:
- Orchestrator-bypass gate → main IS the legitimate caller
- Footer double-count prevention → no transcript parsing happens
- Filesystem isolation → no shared disk state to symlink-attack

### File count: 9 → 5, Python LOC: ~400 → ~120

Lost capability: automatic cross-call cost-aggregation injection. Orchestrator must sum footers itself from individual tool results.

---

## Phase 11 — v7 minimal

**Operator:** "Do not over-engineer. All I want -> allow claude code to launch another main session as a subagent. (MAX DEPTH LIMIT). The first session should know whether the tool is working or stale. (just like claude code knows how many mcp tool called, token usage, is it running from subagents)"

Pulled back to the actual core. Three asks:

1. Spawn another main Claude Code session as a tool call.
2. Max-depth cap so it can't recurse forever.
3. First session sees a summary of what the spawned session did.

### v7 final — 2 files, ~60 lines

**`mcp_server.py`** (~55 lines):

```python
import os, json, subprocess
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nested-subagent")
MAX_DEPTH = int(os.environ.get("CLAUDE_MAX_NESTING_DEPTH", "1"))


@mcp.tool()
def nested_task(prompt: str, timeout_seconds: int = 3600) -> str:
    """Spawn a fresh Claude Code main session to handle one sub-task.

    Depth-capped. The nested session has no memory of this conversation
    — include all needed context in the prompt.

    Args:
        prompt: Standalone task description for the nested agent.
        timeout_seconds: Max execution time (default 3600).

    Returns the nested agent's final answer plus a one-line summary
    (depth, turns, duration_ms, cost_usd, session_id, status).
    """
    depth = int(os.environ.get("CLAUDE_NESTING_DEPTH", "0"))
    if depth >= MAX_DEPTH:
        return f"ERROR: max nesting depth ({MAX_DEPTH}) reached. Do not retry."

    env = os.environ.copy()
    env["CLAUDE_NESTING_DEPTH"] = str(depth + 1)

    cmd = ["claude", "-p", "--output-format", "json", "--", prompt]

    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        return f"[nested-task] depth={depth+1} status=stale (timed out after {timeout_seconds}s)"
    except FileNotFoundError:
        return "ERROR: 'claude' CLI not on PATH."

    if proc.returncode != 0:
        return (f"[nested-task] depth={depth+1} status=error exit={proc.returncode}\n"
                f"stderr: {proc.stderr.strip()[:500]}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return f"[nested-task] depth={depth+1} status=parse_fail\nraw: {proc.stdout[:500]}"

    cost = payload.get("total_cost_usd")
    if cost is None:
        cost = payload.get("cost_usd", 0)

    summary = (f"[nested-task] depth={depth+1} "
               f"turns={payload.get('num_turns','?')} "
               f"duration_ms={payload.get('duration_ms','?')} "
               f"cost_usd={cost:.4f} "
               f"session_id={payload.get('session_id','')} "
               f"status={'error' if payload.get('is_error') else 'ok'}")

    result_text = (payload.get("result") or "").strip()
    return f"{result_text}\n\n---\n{summary}"


if __name__ == "__main__":
    mcp.run()
```

**`.mcp.json`**:

```json
{
  "mcpServers": {
    "nested-subagent": {
      "command": "python3",
      "args": ["./mcp_server.py"]
    }
  }
}
```

### How v7 answers the asks

| Ask | Mechanism |
|---|---|
| Launch main session as tool | `nested_task` MCP tool calls `claude -p` |
| Max depth limit | env-based `CLAUDE_NESTING_DEPTH` check |
| Is it working or stale? | Status field in summary: `ok` / `stale` (timeout) / `error` / `parse_fail` |
| How many MCP tools, tokens? | `turns`, `duration_ms`, `cost_usd` in summary from claude CLI's JSON output |
| Running from subagent? | `depth=N` field; nested session reads env var to self-identify |

### What v7 deliberately does NOT include

| Cut | Why |
|---|---|
| Hooks (all 4) | No subagent layer → no aggregation gap |
| Concurrency cap | Operator manages parallel fan-out |
| Argv validation regex / size caps | `shell=False` + `--` separator prevents flag injection |
| Filesystem isolation / lockfiles | Nothing written to disk |
| Resume support | Add later if needed |
| `_constants.py` | One constant, inlined |
| `.claude/agents/` | No subagent |
| `tools/dump_hook_stdin.py` | No hooks to debug |

---

## Convergence summary

The journey: **9 files / ~400 LOC** (v1 package as shipped) → **3 files / ~150 LOC** (v6-simplified after 6 review iterations + simplify) → **5 files / ~120 LOC** (v6.4 after dropping subagent layer) → **2 files / ~60 LOC** (v7 after dropping over-engineered features).

Every cut was driven by an operator instruction or a reviewer finding that the additional complexity wasn't load-bearing for the actual goal.

### Lessons captured

1. **Hard vs soft rules.** Distinguishing kernel/process-enforced invariants from prompt-guided behavior is load-bearing for both correctness and simplicity. Putting a hard rule in a prompt is a vulnerability; putting a soft rule in code is over-engineering.

2. **Prompt surface placement.** Tool docstrings, subagent frontmatter descriptions, and subagent system prompts have different audiences and re-injection patterns. Placing guidance on the wrong surface either bloats context or misses the audience.

3. **Live-lock > heartbeat for liveness.** Kernel-managed `fcntl.flock` makes "alive" a continuous invariant the kernel maintains, removing the need for staleness windows and timer tuning. (Cut entirely in v7 because no liveness tracking needed without hooks.)

4. **Architecture before optimization.** Six review iterations refined a 3-layer architecture; one operator instruction collapsed it to 2-layer and erased most of the refinements. Question the architecture before polishing it.

5. **Operator constraint "MINIMAL + SIMPLE" is enforceable.** The /review-me protocol's anti-creep guards caught 7 over-engineered items across iterations, including 2 in the final two review rounds. Convergence trajectory monotonically decreased issue counts AND cumulative line count.

---

## Files in this design history

```
docs/nested-subagent-mcp/
└── CONVERSATION.md     ← this file
```

The v7 reference implementation lives at `~/Downloads/nested-subagent-3layer/` (operator's local working copy of the v1 package) and would need to be reduced to the v7 minimal form per the spec above.
