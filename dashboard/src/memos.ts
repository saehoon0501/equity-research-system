// @ts-expect-error virtual module supplied by vite plugin
import RAW from "virtual:memos";

export type Source = "file" | "db" | "agent";

export type Memo = {
  source: Source;
  file: string;
  ticker: string;
  kind: string;
  asOf: string | null;
  createdAt: number;
  modifiedAt: number;
  data: Record<string, unknown>;
};

type Raw = {
  source: Source;
  file: string;
  createdAt: number;
  modifiedAt: number;
  data: Record<string, unknown>;
};

export const AGENTS_BUCKET = "(agents)";

const FILE_KIND_HINTS: Array<[RegExp, string]> = [
  [/pm[_-]?report/i, "PM Report"],
  [/pm[_-]?decision/i, "PM Decision"],
  [/bearcase|bear[_-]?case|cdd_bear/i, "Bear Case"],
  [/backfill/i, "CDD Backfill"],
  [/cdd/i, "CDD Memo"],
];

const DB_KIND_LABELS: Record<string, string> = {
  analyst_briefs: "Analyst Brief",
  execution_recommendations: "PM Recommendation",
  watchlist: "Watchlist Entry",
  counterfactual_ledger: "Counterfactual Ledger",
  predictions: "Predictions Bundle",
  evidence_index: "Evidence Index Bundle",
  research_essentials: "Research Essential",
};

const inferKind = (entry: Raw): string => {
  if (entry.source === "agent") return "Agent Definition";
  if (entry.source === "db") {
    const table = entry.file.split("/")[2] ?? "";
    const base = DB_KIND_LABELS[table] ?? table;
    if (table === "analyst_briefs") {
      const bt = String(entry.data.brief_type ?? "");
      return bt ? `${base} · ${bt}` : base;
    }
    return base;
  }
  const agent = String(entry.data.agent_id ?? "");
  if (agent === "pm-supervisor") return "PM Decision";
  if (agent === "bear-case") return "Bear Case";
  if (agent === "company-deep-dive") return "CDD Memo";
  for (const [re, label] of FILE_KIND_HINTS) if (re.test(entry.file)) return label;
  if (entry.file.endsWith(".md")) return "Markdown Memo";
  return agent || "Memo";
};

const inferTicker = (entry: Raw): string => {
  if (entry.source === "agent") return AGENTS_BUCKET;
  const t = entry.data.ticker;
  if (typeof t === "string" && t.trim()) return t.toUpperCase();
  if (entry.source === "db") return "UNKNOWN";
  const base = entry.file.split("/").pop() ?? entry.file;
  const m = base.match(/^([a-zA-Z]{1,6})_/);
  return (m?.[1] ?? "UNKNOWN").toUpperCase();
};

const inferAsOf = (data: Record<string, unknown>): string | null => {
  for (const k of ["as_of_date", "report_date", "anchor_date_data_print", "date", "decision_date"]) {
    const v = data[k];
    if (typeof v === "string") return v;
  }
  return null;
};

export const loadMemos = (): Memo[] => {
  const raw = RAW as Raw[];
  return raw
    .map((r) => ({
      source: r.source,
      file: r.file,
      ticker: inferTicker(r),
      kind: inferKind(r),
      asOf: inferAsOf(r.data),
      createdAt: r.createdAt,
      modifiedAt: r.modifiedAt,
      data: r.data,
    }))
    .sort((a, b) => {
      const aAgents = a.ticker === AGENTS_BUCKET ? 0 : 1;
      const bAgents = b.ticker === AGENTS_BUCKET ? 0 : 1;
      if (aAgents !== bAgents) return aAgents - bAgents;
      return a.ticker.localeCompare(b.ticker) || b.createdAt - a.createdAt;
    });
};

export const groupByTicker = (memos: Memo[]): Map<string, Memo[]> => {
  const m = new Map<string, Memo[]>();
  for (const memo of memos) {
    const arr = m.get(memo.ticker) ?? [];
    arr.push(memo);
    m.set(memo.ticker, arr);
  }
  return m;
};

export const deleteMemo = async (file: string): Promise<void> => {
  const res = await fetch(`/__api/memos?file=${encodeURIComponent(file)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`delete failed: ${res.status}`);
};

export type CascadeResult = { files: number; rows: number; errors: string[] };

export const deleteTickerCascade = async (ticker: string): Promise<CascadeResult> => {
  const res = await fetch(`/__api/ticker?ticker=${encodeURIComponent(ticker)}`, { method: "DELETE" });
  const body = (await res.json()) as CascadeResult;
  if (!res.ok && res.status !== 207) {
    throw new Error(`delete failed: ${res.status} ${body.errors?.join("; ") ?? ""}`);
  }
  return body;
};

export type IndexStatus = { errors: string[]; builtAt: number };

export const fetchStatus = async (): Promise<IndexStatus> => {
  const res = await fetch("/__api/status");
  if (!res.ok) throw new Error(`status failed: ${res.status}`);
  return (await res.json()) as IndexStatus;
};

export const refreshIndex = async (): Promise<{ builtAt: number }> => {
  const res = await fetch("/__api/refresh", { method: "POST" });
  if (!res.ok) throw new Error(`refresh failed: ${res.status}`);
  return (await res.json()) as { builtAt: number };
};
