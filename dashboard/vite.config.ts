import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync, statSync, unlinkSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");
const memosDir = join(repoRoot, "memos");
const agentsDir = join(repoRoot, ".claude", "agents");

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
