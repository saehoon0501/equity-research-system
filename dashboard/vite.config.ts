import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync, unlinkSync } from "node:fs";
import { basename, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");
const memosDir = join(repoRoot, "memos");
const envelopesDir = join(memosDir, "envelopes");
const agentsDir = join(repoRoot, ".claude", "agents");
const validationLogPath = join(repoRoot, "logs", "validation_attempts.jsonl");

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const walk = (dir: string, exts: string[]): string[] => {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) out.push(...walk(full, exts));
    else if (exts.some((e) => name.endsWith(e))) out.push(full);
  }
  return out;
};

// Extract a ticker hint from markdown content — looks at the first ~20 lines
// for one of: a heading containing "— TICKER" / "- TICKER", or a "Ticker: X"
// label, or a parenthetical company name pattern like "TICKER (Company)".
const tickerFromMarkdown = (text: string): string | null => {
  const head = text.split("\n", 25).join("\n");
  const patterns: RegExp[] = [
    /^#+\s+.*?[—\-–]\s+([A-Z][A-Z.\-]{0,9})\b/m,
    /\bTicker\s*:\s*([A-Z][A-Z.\-]{0,9})\b/,
    /\b([A-Z][A-Z.\-]{0,9})\s*\([A-Z][a-zA-Z]/, // "MU (Micron …"
  ];
  for (const p of patterns) {
    const m = head.match(p);
    if (m) return m[1];
  }
  return null;
};

const fileEntries = () =>
  walk(memosDir, [".json", ".md"]).map((full) => {
    const st = statSync(full);
    const rel = relative(memosDir, full);
    const isJson = full.endsWith(".json");
    const text = readFileSync(full, "utf-8");
    const data: Record<string, unknown> = isJson
      ? JSON.parse(text)
      : { markdown: text };
    // For markdown files (esp. pm_reports/), seed data.ticker from content
    // so the downstream inferTicker resolves correctly even when the filename
    // doesn't start with the ticker.
    if (!isJson && !data.ticker) {
      const t = tickerFromMarkdown(text);
      if (t) data.ticker = t;
    }
    return {
      source: "file" as const,
      file: rel,
      createdAt: st.birthtimeMs || st.mtimeMs,
      modifiedAt: st.mtimeMs,
      data,
    };
  });

const agentEntries = () => {
  try {
    return walk(agentsDir, [".md"]).map((full) => {
      const st = statSync(full);
      const rel = relative(agentsDir, full);
      return {
        source: "agent" as const,
        file: `agents/${rel}`,
        createdAt: st.birthtimeMs || st.mtimeMs,
        modifiedAt: st.mtimeMs,
        data: { markdown: readFileSync(full, "utf-8") },
      };
    });
  } catch {
    return [];
  }
};

const psql = (sql: string, args: string[] = []): string => {
  return execFileSync(
    "docker",
    [
      "exec",
      "-i",
      "equity-research-db",
      "psql",
      "-U", "equity_research_admin",
      "-d", "equity_research",
      "-AtX",
      ...args,
    ],
    { encoding: "utf-8", input: sql, stdio: ["pipe", "pipe", "pipe"] },
  ).trim();
};

// Errors collected during the most-recent buildIndex() run. Surfaced via the
// virtual:memos-status module + /__api/status so the UI can show a banner
// instead of silently dropping DB entries.
const buildErrors: string[] = [];

const labelFromSql = (sql: string): string => {
  const m = sql.match(/FROM\s+([a-zA-Z_]+)/i);
  return m ? m[1] : sql.slice(0, 60);
};

const pg = (sql: string): unknown[] => {
  try {
    return JSON.parse(psql(`SELECT COALESCE(json_agg(t), '[]'::json)::text FROM (${sql}) t`));
  } catch (e) {
    const msg = (e as Error).message ?? String(e);
    const stderr = (e as { stderr?: Buffer | string }).stderr;
    const stderrStr = stderr instanceof Buffer ? stderr.toString() : stderr ?? "";
    const detail = stderrStr.split("\n").find((l) => l.trim()) ?? msg.split("\n")[0];
    const label = labelFromSql(sql);
    buildErrors.push(`${label}: ${detail}`);
    console.warn(`[memos] pg ${label} failed: ${detail}`);
    return [];
  }
};

const DB_PK_COLUMNS: Record<string, string> = {
  analyst_briefs: "brief_id",
  execution_recommendations: "recommendation_id",
  watchlist: "ticker",
  counterfactual_ledger: "ledger_entry_id",
  predictions: "agent_run_id",
  evidence_index: "agent_run_id",
  research_essentials: "key",
};

const deleteDbRow = (table: string, pk: string): { ok: boolean; msg: string } => {
  const pkCol = DB_PK_COLUMNS[table];
  if (!pkCol) return { ok: false, msg: `unknown table: ${table}` };
  if (!/^[A-Za-z0-9_-]+$/.test(pk)) return { ok: false, msg: "invalid pk" };
  try {
    psql(
      `DELETE FROM ${table} WHERE ${pkCol} = :'pk'`,
      ["-v", `pk=${pk}`],
    );
    return { ok: true, msg: "" };
  } catch (e) {
    return { ok: false, msg: (e as Error).message.split("\n")[0] };
  }
};

const dbEntries = (fileMemos: { data: Record<string, unknown> }[]) => {
  type Row = Record<string, unknown> & {
    ticker?: string;
    created_at?: string;
    agent_run_id?: string;
    run_id?: string;
  };

  const briefs = pg(
    `SELECT brief_id, ticker, brief_type, tier, sector_identification, content,
            sources_used, essentials_referenced, delta_summary, run_id, created_at
       FROM analyst_briefs`,
  ) as Row[];

  const recs = pg(
    `SELECT recommendation_id, ticker, date, recommendation, conviction,
            conviction_breakdown, mode, sizing_suggestion, execution_context,
            trigger_metadata, created_at
       FROM execution_recommendations`,
  ) as Row[];

  const watch = pg(
    `SELECT ticker, mode, company_quality_flag, conviction_threshold,
            disposition, parameters_version, added_at AS created_at,
            last_reunderwritten_at, thesis_pillars_original,
            scenario_a_base_projections, regime_sensitivity
       FROM watchlist`,
  ) as Row[];

  const ledger = pg(
    `SELECT ledger_entry_id, ticker, decision_made, decision_date, baseline,
            evaluation_window_start, evaluation_window_end, system_return,
            baseline_return, delta_vs_baseline, notes, created_at
       FROM counterfactual_ledger`,
  ) as Row[];

  // run_id → ticker map: from analyst_briefs + disk memos. Used to attribute
  // evidence_index / predictions / research_essentials (which are keyed by
  // agent_run_id, not ticker) to the right ticker bucket.
  const runIdToTicker = new Map<string, string>();
  for (const b of briefs) {
    if (b.run_id && b.ticker) runIdToTicker.set(String(b.run_id), String(b.ticker));
  }
  for (const m of fileMemos) {
    const rid = (m.data.agent_run_id ?? m.data.run_id) as string | undefined;
    const t = m.data.ticker as string | undefined;
    if (rid && t) runIdToTicker.set(rid, t.toUpperCase());
  }

  const predictionBundles = pg(
    `SELECT agent_run_id,
            COUNT(*)::int                 AS row_count,
            MIN(created_at)               AS created_at,
            json_agg(json_build_object(
              'prediction_id', prediction_id,
              'prediction_text', prediction_text,
              'prediction_type', prediction_type,
              'target_metric', target_metric,
              'target_date', target_date,
              'p10', p10, 'p50', p50, 'p90', p90,
              'predicted_outcome', predicted_outcome,
              'resolution_date', resolution_date,
              'resolved_value', resolved_value,
              'resolved_outcome', resolved_outcome,
              'resolved_correct', resolved_correct,
              'brier_component', brier_component
            ) ORDER BY created_at) AS predictions
       FROM predictions
      GROUP BY agent_run_id`,
  ) as Row[];

  const evidenceBundles = pg(
    `SELECT agent_run_id,
            COUNT(*)::int                 AS row_count,
            MIN(created_at)               AS created_at,
            json_agg(json_build_object(
              'evidence_id', evidence_id,
              'claim_text', claim_text,
              'claim_type', claim_type,
              'source_uri', source_uri,
              'source_date', source_date,
              'source_quality_tier', source_quality_tier
            ) ORDER BY created_at) AS evidence
       FROM evidence_index
      GROUP BY agent_run_id`,
  ) as Row[];

  const essentials = pg(
    `SELECT key, content, topic_tags, source_run_ids, confidence, last_updated AS created_at
       FROM research_essentials`,
  ) as Row[];

  const attachTicker = (row: Row, lookup?: string): string => {
    if (row.ticker) return String(row.ticker).toUpperCase();
    if (lookup) {
      const t = runIdToTicker.get(lookup);
      if (t) return t;
    }
    return "UNKNOWN";
  };

  const toEntry = (table: string, pkCol: string, opts: { runIdField?: keyof Row } = {}) =>
    (row: Row) => {
      const pk = String(row[pkCol] ?? row.ticker ?? "row");
      const ms = row.created_at ? new Date(String(row.created_at)).getTime() : Date.now();
      const ticker = attachTicker(row, opts.runIdField ? String(row[opts.runIdField] ?? "") : undefined);
      return {
        source: "db" as const,
        file: `db://${table}/${pk}`,
        createdAt: ms,
        modifiedAt: ms,
        data: { ticker, ...row },
      };
    };

  const essentialsToEntry = (row: Row) => {
    const runIds = (row.source_run_ids as string[] | undefined) ?? [];
    let ticker = "UNKNOWN";
    for (const rid of runIds) {
      const t = runIdToTicker.get(rid);
      if (t) { ticker = t; break; }
    }
    const ms = row.created_at ? new Date(String(row.created_at)).getTime() : Date.now();
    return {
      source: "db" as const,
      file: `db://research_essentials/${row.key}`,
      createdAt: ms,
      modifiedAt: ms,
      data: { ticker, ...row },
    };
  };

  return [
    ...briefs.map(toEntry("analyst_briefs", "brief_id")),
    ...recs.map(toEntry("execution_recommendations", "recommendation_id")),
    ...watch.map(toEntry("watchlist", "ticker")),
    ...ledger.map(toEntry("counterfactual_ledger", "ledger_entry_id")),
    ...predictionBundles.map(toEntry("predictions", "agent_run_id", { runIdField: "agent_run_id" })),
    ...evidenceBundles.map(toEntry("evidence_index", "agent_run_id", { runIdField: "agent_run_id" })),
    ...essentials.map(essentialsToEntry),
  ];
};

// Runs view helpers — sourced from run_parameters_snapshot joined with
// execution_recommendations (via trigger_metadata->>'run_id') plus a streaming
// scan of logs/validation_attempts.jsonl for per-attempt cost + decisions.

type ValidationAttempt = {
  run_id: string;
  agent_type: string;
  attempt_n: number;
  fingerprint: string;
  validation_passed: boolean;
  validation_summary?: Record<string, string>;
  failed_gate_ids?: string[];
  attempt_cost_usd?: number;
  cumulative_cost_usd?: number;
  envelope_path?: string;
  decision: "PASS" | "RETRY" | "ESCALATE" | string;
};

const readValidationAttempts = (filterRunId?: string): ValidationAttempt[] => {
  if (!existsSync(validationLogPath)) return [];
  let text: string;
  try {
    text = readFileSync(validationLogPath, "utf-8");
  } catch {
    return [];
  }
  const out: ValidationAttempt[] = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    try {
      const row = JSON.parse(line) as ValidationAttempt;
      if (filterRunId && row.run_id !== filterRunId) continue;
      out.push(row);
    } catch {/* skip malformed */}
  }
  return out;
};

type RunListRow = {
  run_id: string;
  ticker: string;
  run_started_at: string;
  run_ended_at: string | null;
  run_status: string | null;
  parameters_hash_prefix: string;
  tag: string | null;
  recommendation_id: string | null;
  summary_code: string | null;
  conviction: string | null;
  attempt_count: number;
  total_cost_usd: number;
  agents_completed: string[];
};

const listRuns = (): RunListRow[] => {
  const rows = pg(
    `SELECT s.run_id::text             AS run_id,
            s.ticker                   AS ticker,
            s.run_started_at           AS run_started_at,
            s.run_ended_at             AS run_ended_at,
            s.run_status               AS run_status,
            SUBSTRING(s.effective_parameters_hash, 1, 12) AS parameters_hash_prefix,
            s.tag                      AS tag,
            r.recommendation_id::text  AS recommendation_id,
            r.recommendation           AS summary_code,
            r.conviction               AS conviction
       FROM run_parameters_snapshot s
       LEFT JOIN execution_recommendations r
         ON r.trigger_metadata->>'run_id' = s.run_id::text
       ORDER BY s.run_started_at DESC NULLS LAST, s.created_at DESC`,
  ) as Array<Record<string, string | null>>;

  // Roll up validation_attempts.jsonl per run for cost + attempt count.
  // O(N*M) in the worst case but N (runs) is tiny — fine for v0.1.
  const attempts = readValidationAttempts();
  const byRun = new Map<string, { count: number; cost: number; agents: Set<string> }>();
  for (const a of attempts) {
    const slot = byRun.get(a.run_id) ?? { count: 0, cost: 0, agents: new Set<string>() };
    slot.count += 1;
    slot.cost += typeof a.attempt_cost_usd === "number" ? a.attempt_cost_usd : 0;
    if (a.decision === "PASS") slot.agents.add(a.agent_type);
    byRun.set(a.run_id, slot);
  }

  return rows.map((r) => {
    const rid = String(r.run_id);
    const roll = byRun.get(rid);
    return {
      run_id: rid,
      ticker: String(r.ticker ?? "UNKNOWN"),
      run_started_at: String(r.run_started_at ?? ""),
      run_ended_at: r.run_ended_at,
      run_status: r.run_status,
      parameters_hash_prefix: String(r.parameters_hash_prefix ?? ""),
      tag: r.tag,
      recommendation_id: r.recommendation_id,
      summary_code: r.summary_code,
      conviction: r.conviction,
      attempt_count: roll?.count ?? 0,
      total_cost_usd: roll ? Number(roll.cost.toFixed(2)) : 0,
      agents_completed: roll ? Array.from(roll.agents).sort() : [],
    };
  });
};

type EnvelopeFile = {
  agent: string;
  filename: string;
  kind: "envelope" | "context" | "degraded" | "backup";
  size_bytes: number;
  modified_at: number;
  data: Record<string, unknown> | null;
};

const ENVELOPE_NAME_RE = /^([a-z][a-z0-9-]+)__([0-9a-f-]+?)(?:\.(json|degraded|context\.json))(\.bak(?:-[a-z0-9-]+)?)?$/i;

const listEnvelopesForRun = (runId: string): EnvelopeFile[] => {
  if (!existsSync(envelopesDir)) return [];
  const out: EnvelopeFile[] = [];
  for (const name of readdirSync(envelopesDir)) {
    if (!name.includes(runId)) continue;
    const m = name.match(ENVELOPE_NAME_RE);
    if (!m) continue;
    const [, agent, , ext, bakSuffix] = m;
    const full = join(envelopesDir, name);
    const st = statSync(full);
    let kind: EnvelopeFile["kind"];
    if (bakSuffix) kind = "backup";
    else if (ext === "degraded") kind = "degraded";
    else if (ext === "context.json") kind = "context";
    else kind = "envelope";
    let data: Record<string, unknown> | null = null;
    if (kind !== "degraded") {
      try {
        const raw = readFileSync(full, "utf-8");
        data = raw.trim() ? (JSON.parse(raw) as Record<string, unknown>) : null;
      } catch {/* leave null */}
    }
    out.push({
      agent,
      filename: name,
      kind,
      size_bytes: st.size,
      modified_at: st.mtimeMs,
      data,
    });
  }
  // Sort: envelope first per agent, then context, then degraded, then backups; agents alpha.
  const kindRank: Record<EnvelopeFile["kind"], number> = { envelope: 0, context: 1, degraded: 2, backup: 3 };
  out.sort((a, b) => a.agent.localeCompare(b.agent) || kindRank[a.kind] - kindRank[b.kind] || a.filename.localeCompare(b.filename));
  return out;
};

type RunDetail = {
  snapshot: Record<string, unknown> | null;
  recommendation: Record<string, unknown> | null;
  attempts: ValidationAttempt[];
  envelopes: EnvelopeFile[];
  system_errors: Array<Record<string, unknown>>;
};

const getRunDetail = (runId: string): RunDetail => {
  // Caller MUST have validated runId as a UUID before calling — SQL inlines
  // the value because there is no parameterized helper, and the UUID gate
  // makes injection impossible.
  if (!UUID_RE.test(runId)) throw new Error("getRunDetail: runId must be a UUID");

  const snapshotRows = pg(
    `SELECT run_id::text                  AS run_id,
            ticker, run_started_at, run_ended_at, run_status,
            parameters_version_max::text  AS parameters_version_max,
            effective_parameters_hash,
            effective_parameters_jsonb,
            tag, tag_signature, tag_issued_at_unix,
            created_at
       FROM run_parameters_snapshot
      WHERE run_id = '${runId}'`,
  ) as Array<Record<string, unknown>>;

  const recRows = pg(
    `SELECT recommendation_id::text  AS recommendation_id,
            ticker, date, recommendation, conviction,
            conviction_breakdown, mode, company_quality_flag, mode_certainty,
            sizing_suggestion, execution_context, trigger_metadata,
            rule_engine_version, debate_prompt_version,
            model_id, model_version,
            parameters_version::text  AS parameters_version,
            created_at
       FROM execution_recommendations
      WHERE trigger_metadata->>'run_id' = '${runId}'
      ORDER BY created_at DESC
      LIMIT 1`,
  ) as Array<Record<string, unknown>>;

  // system_errors: blocked_decision is "research_company_TICKER_TIMESTAMP" —
  // no direct run_id column, so we widen via substring match on error_detail
  // (the orchestrator's terminal-update failure path JSON-embeds run_id).
  const errRows = pg(
    `SELECT error_id::text AS error_id, timestamp_at, source, error_type, error_detail,
            retry_count, escalated_to_alert, blocked_decision, resolution, resolved_at
       FROM system_errors
      WHERE error_detail LIKE '%${runId}%'
      ORDER BY timestamp_at DESC`,
  ) as Array<Record<string, unknown>>;

  return {
    snapshot: snapshotRows[0] ?? null,
    recommendation: recRows[0] ?? null,
    attempts: readValidationAttempts(runId).sort(
      (a, b) => a.agent_type.localeCompare(b.agent_type) || a.attempt_n - b.attempt_n,
    ),
    envelopes: listEnvelopesForRun(runId),
    system_errors: errRows,
  };
};

// Gate scorecard — aggregates validation_attempts.jsonl by check name +
// HG-code. Designed to answer "which gate fails most, is its retry rate
// trending up, and how much does it cost per attempt?"  Pure aggregation
// over the JSONL log; no DB, no caching — file is small (≤thousands of rows).

type GateAggRow = {
  // Stable name from validation_summary keys (envelope_shape, quant_memo_shape, …)
  // OR HG-code from failed_gate_ids (HG-29, HG-31, …) — recordKind disambiguates.
  name: string;
  kind: "check" | "hg_code";
  agents: string[];            // distinct agent_types that exercise this gate
  attempts_total: number;
  attempts_pass: number;
  attempts_fail: number;
  attempts_escalate: number;
  pass_rate: number;           // attempts_pass / attempts_total, [0..1]
  cost_when_fail_usd: number;  // sum of attempt_cost_usd for failing attempts
  cost_avg_per_attempt_usd: number;
  recent_decisions: string[];  // up to last N decisions chronologically (oldest→newest)
  last_failed_run_id: string | null;
  last_failed_at: number | null; // unix ms (file order proxy — JSONL is append-only)
};

type GateScorecard = {
  generated_at: number;
  total_attempts: number;
  total_runs: number;
  decision_breakdown: Record<string, number>;
  checks: GateAggRow[];        // sorted by attempts_total DESC
  hg_codes: GateAggRow[];      // sorted by attempts_fail DESC (HG codes only matter when failing)
  insights: string[];          // human-readable trend flags
};

const SPARK_WINDOW = 14;

const buildGateScorecard = (): GateScorecard => {
  const attempts = readValidationAttempts();
  // The JSONL is append-only — its file order is the chronological order.
  // No timestamps live on individual rows yet (a known gap from the obs review),
  // so order-index is the best proxy for "recent."
  const checkAcc = new Map<string, GateAggRow>();
  const hgAcc = new Map<string, GateAggRow>();
  const decisionBreakdown: Record<string, number> = {};
  const runIds = new Set<string>();

  const newRow = (name: string, kind: GateAggRow["kind"]): GateAggRow => ({
    name, kind,
    agents: [],
    attempts_total: 0, attempts_pass: 0, attempts_fail: 0, attempts_escalate: 0,
    pass_rate: 0,
    cost_when_fail_usd: 0, cost_avg_per_attempt_usd: 0,
    recent_decisions: [],
    last_failed_run_id: null,
    last_failed_at: null,
  });

  for (let i = 0; i < attempts.length; i++) {
    const a = attempts[i];
    decisionBreakdown[a.decision] = (decisionBreakdown[a.decision] ?? 0) + 1;
    runIds.add(a.run_id);

    // validation_summary: keys are the named checks; values "pass" | "fail" (occasionally other)
    for (const [check, verdict] of Object.entries(a.validation_summary ?? {})) {
      const row = checkAcc.get(check) ?? newRow(check, "check");
      row.attempts_total += 1;
      const v = String(verdict).toLowerCase();
      if (v === "pass") row.attempts_pass += 1;
      else if (v === "fail") row.attempts_fail += 1;
      // any other verdict left uncategorized; counted in total but not pass/fail
      if (!row.agents.includes(a.agent_type)) row.agents.push(a.agent_type);
      const cost = typeof a.attempt_cost_usd === "number" ? a.attempt_cost_usd : 0;
      if (v === "fail") {
        row.cost_when_fail_usd += cost;
        row.last_failed_run_id = a.run_id;
        row.last_failed_at = i; // ordinal proxy
      }
      row.recent_decisions.push(v === "pass" ? "P" : v === "fail" ? "F" : "?");
      if (row.recent_decisions.length > SPARK_WINDOW) row.recent_decisions.shift();
      checkAcc.set(check, row);
    }

    // failed_gate_ids: HG-codes that fired during this attempt
    for (const hg of a.failed_gate_ids ?? []) {
      const row = hgAcc.get(hg) ?? newRow(hg, "hg_code");
      row.attempts_total += 1;
      row.attempts_fail += 1; // HG codes only appear in failed_gate_ids
      if (!row.agents.includes(a.agent_type)) row.agents.push(a.agent_type);
      row.cost_when_fail_usd += typeof a.attempt_cost_usd === "number" ? a.attempt_cost_usd : 0;
      row.last_failed_run_id = a.run_id;
      row.last_failed_at = i;
      row.recent_decisions.push("F");
      if (row.recent_decisions.length > SPARK_WINDOW) row.recent_decisions.shift();
      // Also count ESCALATE separately on the HG row that triggered the escalate.
      if (a.decision === "ESCALATE") row.attempts_escalate += 1;
      hgAcc.set(hg, row);
    }
  }

  const finalize = (rows: GateAggRow[]): GateAggRow[] => {
    for (const r of rows) {
      r.pass_rate = r.attempts_total > 0 ? r.attempts_pass / r.attempts_total : 0;
      r.cost_avg_per_attempt_usd = r.attempts_total > 0
        ? Number((r.cost_when_fail_usd / r.attempts_total).toFixed(2))
        : 0;
      r.cost_when_fail_usd = Number(r.cost_when_fail_usd.toFixed(2));
      r.agents.sort();
    }
    return rows;
  };

  // Insights: trend flags from the trailing-half vs leading-half failure rate.
  // Crude but cheap — operator can drill if a flag fires.
  const insights: string[] = [];
  for (const row of checkAcc.values()) {
    const recent = row.recent_decisions;
    if (recent.length < 6) continue;
    const half = Math.floor(recent.length / 2);
    const leading = recent.slice(0, half);
    const trailing = recent.slice(half);
    const leadFail = leading.filter((d) => d === "F").length / leading.length;
    const trailFail = trailing.filter((d) => d === "F").length / trailing.length;
    if (trailFail > leadFail + 0.2) {
      insights.push(`${row.name} fail rate rose ${(leadFail * 100).toFixed(0)}% → ${(trailFail * 100).toFixed(0)}% across last ${recent.length} attempts (agents: ${row.agents.join(", ")})`);
    }
  }
  // Cost hotspot: any check with avg failure cost > $5 and attempts_fail > 2
  for (const row of checkAcc.values()) {
    if (row.attempts_fail >= 3 && row.cost_avg_per_attempt_usd > 5) {
      insights.push(`${row.name} is a cost hotspot — ${row.attempts_fail} fails contributed $${row.cost_when_fail_usd} (${row.cost_avg_per_attempt_usd}/attempt avg)`);
    }
  }
  // Any escalation at all is noteworthy
  for (const row of hgAcc.values()) {
    if (row.attempts_escalate > 0) {
      insights.push(`${row.name} reached ESCALATE ${row.attempts_escalate}× — stuck-loop fingerprint or 3-attempt cap exhaustion`);
    }
  }

  const checks = finalize(Array.from(checkAcc.values())).sort((a, b) => b.attempts_total - a.attempts_total);
  const hg_codes = finalize(Array.from(hgAcc.values())).sort((a, b) => b.attempts_fail - a.attempts_fail);

  return {
    generated_at: Date.now(),
    total_attempts: attempts.length,
    total_runs: runIds.size,
    decision_breakdown: decisionBreakdown,
    checks,
    hg_codes,
    insights,
  };
};

let lastBuiltAt = 0;

const buildIndex = () => {
  buildErrors.length = 0;
  const files = fileEntries();
  const db = dbEntries(files);
  const agents = agentEntries();
  lastBuiltAt = Date.now();
  return [...files, ...db, ...agents];
};

type Status = { errors: string[]; builtAt: number };

const buildStatus = (): Status => ({
  errors: [...buildErrors],
  builtAt: lastBuiltAt,
});

const loadDotenv = (): Record<string, string> => {
  try {
    const text = readFileSync(join(repoRoot, ".env"), "utf-8");
    const out: Record<string, string> = {};
    for (const line of text.split("\n")) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
      if (!m) continue;
      let v = m[2].trim();
      if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
        v = v.slice(1, -1);
      }
      out[m[1]] = v;
    }
    return out;
  } catch {
    return {};
  }
};

const POLYGON_BASE = "https://api.polygon.io";
const polygonKey = loadDotenv().POLYGON_API_KEY ?? "";

const polygonFetch = async (path: string): Promise<{ status: number; body: string }> => {
  if (!polygonKey) return { status: 500, body: JSON.stringify({ error: "POLYGON_API_KEY missing" }) };
  const url = `${POLYGON_BASE}${path}${path.includes("?") ? "&" : "?"}apiKey=${polygonKey}`;
  try {
    const res = await fetch(url);
    const body = await res.text();
    return { status: res.status, body };
  } catch (e) {
    return { status: 502, body: JSON.stringify({ error: String(e) }) };
  }
};

const isTicker = (t: string) => /^[A-Z][A-Z.\-]{0,9}$/.test(t);

const memosPlugin = (): Plugin => ({
  name: "memos-virtual",
  resolveId(id) {
    if (id === "virtual:memos") return "\0virtual:memos";
    if (id === "virtual:memos-status") return "\0virtual:memos-status";
  },
  load(id) {
    if (id === "\0virtual:memos") {
      const entries = buildIndex();
      return `export default ${JSON.stringify(entries)};`;
    }
    if (id === "\0virtual:memos-status") {
      // Re-emit current status. virtual:memos must load first for fresh errors;
      // Vite's load ordering doesn't guarantee that, so the /__api/status
      // endpoint is the authoritative live source — this module is just an
      // initial snapshot to seed the UI before its first fetch.
      return `export default ${JSON.stringify(buildStatus())};`;
    }
  },
  configureServer(server) {
    const invalidate = () => {
      const mod = server.moduleGraph.getModuleById("\0virtual:memos");
      if (mod) {
        server.moduleGraph.invalidateModule(mod);
        server.ws.send({ type: "full-reload" });
      }
    };
    server.watcher.add([memosDir, agentsDir]);
    server.watcher.on("add", invalidate);
    server.watcher.on("unlink", invalidate);
    server.watcher.on("change", invalidate);

    const safeJson = (s: string): unknown => {
      try { return JSON.parse(s); } catch { return { raw: s }; }
    };

    const polygonHandler = (kind: "quote" | "options") => async (req: any, res: any) => {
      const url = new URL(req.url ?? "", "http://x");
      const ticker = (url.searchParams.get("ticker") ?? "").toUpperCase();
      if (!isTicker(ticker)) {
        res.statusCode = 400;
        res.end(JSON.stringify({ error: "bad ticker" }));
        return;
      }
      res.setHeader("content-type", "application/json");

      if (kind === "quote") {
        // Snapshot (live last trade + day OHLC + prev close + computed change,
        // covers pre/post-market via lastTrade) + 1-day intraday minutes.
        const to = new Date();
        const from = new Date(to.getTime() - 4 * 24 * 60 * 60 * 1000); // 4d window to cover weekends
        const f = (d: Date) => d.toISOString().slice(0, 10);
        const [snap, mins] = await Promise.all([
          polygonFetch(`/v2/snapshot/locale/us/markets/stocks/tickers/${ticker}`),
          polygonFetch(`/v2/aggs/ticker/${ticker}/range/1/minute/${f(from)}/${f(to)}?adjusted=true&sort=asc&limit=5000`),
        ]);
        res.statusCode = 200;
        res.end(JSON.stringify({
          ticker,
          snapshot: safeJson(snap.body),
          minutes: safeJson(mins.body),
          fetched_at: new Date().toISOString(),
        }));
        return;
      }

      // options snapshot
      const r = await polygonFetch(`/v3/snapshot/options/${ticker}?limit=250`);
      res.statusCode = 200;
      res.end(JSON.stringify({
        ticker,
        snapshot: safeJson(r.body),
        fetched_at: new Date().toISOString(),
      }));
    };

    server.middlewares.use("/__api/polygon/quote", polygonHandler("quote"));
    server.middlewares.use("/__api/polygon/options", polygonHandler("options"));

    server.middlewares.use("/__api/status", (_req, res) => {
      res.setHeader("content-type", "application/json");
      res.statusCode = 200;
      res.end(JSON.stringify(buildStatus()));
    });

    server.middlewares.use("/__api/runs", (req, res) => {
      res.setHeader("content-type", "application/json");
      const url = new URL(req.url ?? "", "http://x");
      // /__api/runs/<uuid>   → detail
      // /__api/runs          → list
      const trailing = url.pathname.replace(/^\/+|\/+$/g, "");
      if (trailing && trailing !== "") {
        if (!UUID_RE.test(trailing)) {
          res.statusCode = 400;
          res.end(JSON.stringify({ error: "invalid run_id" }));
          return;
        }
        try {
          const detail = getRunDetail(trailing);
          if (!detail.snapshot && !detail.recommendation && detail.attempts.length === 0 && detail.envelopes.length === 0) {
            res.statusCode = 404;
            res.end(JSON.stringify({ error: "no such run" }));
            return;
          }
          res.statusCode = 200;
          res.end(JSON.stringify(detail));
        } catch (e) {
          res.statusCode = 500;
          res.end(JSON.stringify({ error: String(e).split("\n")[0] }));
        }
        return;
      }
      try {
        const rows = listRuns();
        res.statusCode = 200;
        res.end(JSON.stringify(rows));
      } catch (e) {
        res.statusCode = 500;
        res.end(JSON.stringify({ error: String(e).split("\n")[0] }));
      }
    });

    server.middlewares.use("/__api/gates", (_req, res) => {
      res.setHeader("content-type", "application/json");
      try {
        res.statusCode = 200;
        res.end(JSON.stringify(buildGateScorecard()));
      } catch (e) {
        res.statusCode = 500;
        res.end(JSON.stringify({ error: String(e).split("\n")[0] }));
      }
    });

    server.middlewares.use("/__api/refresh", (req, res) => {
      if (req.method !== "POST") {
        res.statusCode = 405;
        res.end("method not allowed");
        return;
      }
      invalidate();
      // The full-reload broadcast above is async; reply immediately with what
      // we know — the client polls /__api/status after reload for fresh state.
      res.setHeader("content-type", "application/json");
      res.statusCode = 200;
      res.end(JSON.stringify({ invalidated: true, builtAt: lastBuiltAt }));
    });

    server.middlewares.use("/__api/ticker", (req, res) => {
      if (req.method !== "DELETE") {
        res.statusCode = 405;
        res.end("method not allowed");
        return;
      }
      const url = new URL(req.url ?? "", "http://x");
      const ticker = (url.searchParams.get("ticker") ?? "").toUpperCase();
      if (!isTicker(ticker)) {
        res.statusCode = 400;
        res.end("invalid ticker");
        return;
      }
      const result = { files: 0, rows: 0, errors: [] as string[] };

      // 1. Collect run_ids for this ticker (analyst_briefs + disk memos).
      const runIds = new Set<string>();
      try {
        const rows = JSON.parse(
          psql(`SELECT json_agg(run_id) FROM analyst_briefs WHERE ticker = :'pk' AND run_id IS NOT NULL`,
            ["-v", `pk=${ticker}`]) || "null",
        ) as string[] | null;
        for (const r of rows ?? []) runIds.add(String(r));
      } catch (e) {
        result.errors.push(`run_ids: ${(e as Error).message.split("\n")[0]}`);
      }
      for (const full of walk(memosDir, [".json", ".md"])) {
        try {
          if (!full.endsWith(".json")) continue;
          const data = JSON.parse(readFileSync(full, "utf-8")) as Record<string, unknown>;
          if (typeof data.ticker === "string" && data.ticker.toUpperCase() === ticker) {
            const rid = (data.agent_run_id ?? data.run_id) as string | undefined;
            if (rid) runIds.add(String(rid));
          }
        } catch {/* skip parse errors */}
      }

      // 2. Delete disk memos.
      for (const full of walk(memosDir, [".json", ".md"])) {
        const base = full.split("/").pop() ?? "";
        const prefixMatch = base.toLowerCase().startsWith(ticker.toLowerCase() + "_");
        let dataMatch = false;
        if (full.endsWith(".json")) {
          try {
            const d = JSON.parse(readFileSync(full, "utf-8")) as Record<string, unknown>;
            dataMatch = typeof d.ticker === "string" && d.ticker.toUpperCase() === ticker;
          } catch {/* */}
        }
        if (prefixMatch || dataMatch) {
          try { unlinkSync(full); result.files++; } catch (e) {
            result.errors.push(`unlink ${base}: ${(e as Error).message.split("\n")[0]}`);
          }
        }
      }

      // 3. Delete DB rows in ticker-keyed tables.
      const tickerTables = ["analyst_briefs", "execution_recommendations", "watchlist", "counterfactual_ledger"];
      for (const tbl of tickerTables) {
        try {
          const out = psql(
            `WITH d AS (DELETE FROM ${tbl} WHERE ticker = :'pk' RETURNING 1) SELECT count(*) FROM d`,
            ["-v", `pk=${ticker}`],
          );
          result.rows += parseInt(out, 10) || 0;
        } catch (e) {
          result.errors.push(`${tbl}: ${(e as Error).message.split("\n")[0]}`);
        }
      }

      // 4. Delete run_id-keyed bundles (predictions + evidence_index).
      if (runIds.size > 0) {
        const idList = Array.from(runIds).filter((r) => /^[A-Za-z0-9_-]+$/.test(r));
        if (idList.length > 0) {
          const inClause = idList.map((id) => `'${id}'`).join(",");
          for (const tbl of ["predictions", "evidence_index"]) {
            try {
              const out = psql(
                `WITH d AS (DELETE FROM ${tbl} WHERE agent_run_id IN (${inClause}) RETURNING 1) SELECT count(*) FROM d`,
              );
              result.rows += parseInt(out, 10) || 0;
            } catch (e) {
              result.errors.push(`${tbl}: ${(e as Error).message.split("\n")[0]}`);
            }
          }
        }
      }

      res.setHeader("content-type", "application/json");
      res.statusCode = result.errors.length ? 207 : 200;
      res.end(JSON.stringify(result));
    });

    server.middlewares.use("/__api/memos", (req, res) => {
      if (req.method !== "DELETE") {
        res.statusCode = 405;
        res.end("method not allowed");
        return;
      }
      const url = new URL(req.url ?? "", "http://x");
      const file = url.searchParams.get("file");
      if (!file) {
        res.statusCode = 400;
        res.end("missing file");
        return;
      }
      if (file.startsWith("db://")) {
        const parts = file.slice("db://".length).split("/");
        const [table, pk] = parts;
        if (!table || !pk) {
          res.statusCode = 400;
          res.end("malformed db uri");
          return;
        }
        const { ok, msg } = deleteDbRow(table, pk);
        if (!ok) {
          res.statusCode = 500;
          res.end(msg);
          return;
        }
        res.statusCode = 204;
        res.end();
        return;
      }
      const target = resolve(memosDir, file);
      if (!target.startsWith(memosDir + "/") && target !== memosDir) {
        res.statusCode = 400;
        res.end("invalid path");
        return;
      }
      try {
        unlinkSync(target);
        res.statusCode = 204;
        res.end();
      } catch (e) {
        res.statusCode = 500;
        res.end(String(e));
      }
    });
  },
});

export default defineConfig({
  plugins: [react(), memosPlugin()],
  server: { port: 5173, fs: { allow: [fileURLToPath(new URL("..", import.meta.url))] } },
});
