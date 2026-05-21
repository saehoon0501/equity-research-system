import { useEffect, useMemo, useState } from "react";
import { marked } from "marked";
import {
  loadMemos,
  groupByTicker,
  deleteMemo,
  deleteTickerCascade,
  fetchStatus,
  refreshIndex,
  AGENTS_BUCKET,
  type IndexStatus,
  type Memo,
} from "./memos";
import { LivePanel } from "./LivePanel";
import { RunsView } from "./RunsView";

marked.setOptions({ gfm: true, breaks: true });

const ALL_INITIAL = loadMemos();

const humanize = (k: string) =>
  k.replace(/^section_\d+(_\d+)?_/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const isPlain = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

const formatDate = (ms: number) => {
  const d = new Date(ms);
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
};

const Markdown = ({ text }: { text: string }) => (
  <div className="md" dangerouslySetInnerHTML={{ __html: marked.parse(text) as string }} />
);

const Value = ({ value }: { value: unknown }) => {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  if (typeof value === "boolean") return <span className="pill">{String(value)}</span>;
  if (typeof value === "number") return <span className="num">{value.toLocaleString()}</span>;
  if (typeof value === "string") {
    if (/^https?:\/\//.test(value))
      return <a href={value} target="_blank" rel="noreferrer">{value}</a>;
    return <span>{value}</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="muted">(empty)</span>;
    const allScalar = value.every((v) => typeof v !== "object" || v === null);
    if (allScalar) {
      return (
        <ul className="bullets">
          {value.map((v, i) => <li key={i}><Value value={v} /></li>)}
        </ul>
      );
    }
    return (
      <div className="list">
        {value.map((v, i) => (
          <div key={i} className="list-item">
            <div className="list-idx">#{i + 1}</div>
            <Value value={v} />
          </div>
        ))}
      </div>
    );
  }
  if (isPlain(value)) {
    return (
      <table className="kv">
        <tbody>
          {Object.entries(value).map(([k, v]) => (
            <tr key={k}>
              <td className="kv-key">{humanize(k)}</td>
              <td className="kv-val"><Value value={v} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  return <span>{String(value)}</span>;
};

const META_KEYS = new Set([
  "memo_id", "agent_id", "agent_run_id", "ticker", "as_of_date",
  "report_date", "mode",
]);

const Section = ({ k, v }: { k: string; v: unknown }) => {
  const [open, setOpen] = useState(true);
  return (
    <section className="section">
      <button className="section-h" onClick={() => setOpen((o) => !o)}>
        <span className="chev">{open ? "▾" : "▸"}</span>
        <span>{humanize(k)}</span>
      </button>
      {open && <div className="section-body"><Value value={v} /></div>}
    </section>
  );
};

const IconCopy = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="9" y="9" width="13" height="13" rx="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </svg>
);

const IconCheck = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12" />
  </svg>
);

const IconTrash = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
    <path d="M10 11v6M14 11v6" />
    <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
  </svg>
);

type Action = "BUY" | "HOLD" | "TRIM" | "SELL";
type Conviction = "LOW" | "MEDIUM" | "HIGH";

type MatrixCell = { tag: "ok" | "block" | "off"; body: string };

const DECISION_MATRIX: Record<Action, Record<Conviction, MatrixCell>> = {
  BUY: {
    LOW:    { tag: "block", body: "Not reachable. LOW forces size {0,0,0}; derivation rule requires bullish Structural Theory + sleeve PASS, neither survives LOW dominators." },
    MEDIUM: { tag: "ok",    body: "Bullish Structural Theory + sleeve PASS + no overlay block. Size 1.5–3.0% × mode multiplier. \"Good but not max\" add." },
    HIGH:   { tag: "ok",    body: "Bullish Structural Theory + sleeve PASS + HIGH gate (debate ≥ 4 AND kills = 0 AND ≥ 2 SURVIVOR AND anchor-drift ≤ 1). Size 3.0–6.0% × mode multiplier. Highest-conviction add." },
  },
  HOLD: {
    LOW:    { tag: "off",   body: "LOW with no directional signal — mixed read across quant/strategic/catalyst-scout; nothing actionable." },
    MEDIUM: { tag: "off",   body: "Cap-blocked would-be BUY (§3 sleeve VIOLATION) OR neutral/mixed Structural Theory. Reasoning row must disambiguate." },
    HIGH:   { tag: "off",   body: "Cap-blocked would-be BUY at HIGH OR §2.7 R1–R4 brief-quality / dual-DCF floor failure downgraded BUY → HOLD. Would have been strongest add." },
  },
  TRIM: {
    LOW:    { tag: "block", body: "Non-canonical — LOW + overpriced usually routes SELL or HOLD." },
    MEDIUM: { tag: "off",   body: "\"Intrinsic ≪ spot\" — overpriced but not a terminal failure. Holders reduce; new buyers stay out. Replaces 4-bin REJECT." },
    HIGH:   { tag: "off",   body: "Same overpriced read as MEDIUM-TRIM with stronger evidence (implied-growth ≫ CAGR, austere DCF ≫ spot)." },
  },
  SELL: {
    LOW:    { tag: "ok",    body: "Canonical SELL — LOW + ≥ 2 NON-SURVIVOR analog veto OR LOW + \"terminal thesis break.\" Strongest exit signal." },
    MEDIUM: { tag: "block", body: "Not standard — SELL is reserved for LOW per rollup precedence." },
    HIGH:   { tag: "block", body: "Not standard — catastrophic stress-test failures down-shift conviction to LOW first via kills_fired, then SELL fires." },
  },
};

const CELL_GLYPH: Record<MatrixCell["tag"], string> = {
  ok: "✓",
  block: "⛔",
  off: "·",
};

const IconHelp = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.8.4-1 1-1 1.7" />
    <line x1="12" y1="17" x2="12" y2="17.01" />
  </svg>
);

const DecisionMatrixModal = ({ onClose }: { onClose: () => void }) => {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const actions: Action[] = ["BUY", "HOLD", "TRIM", "SELL"];
  const convictions: Conviction[] = ["LOW", "MEDIUM", "HIGH"];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header className="modal-h">
          <h3>Action × Conviction matrix</h3>
          <button className="status-close" onClick={onClose} aria-label="close">×</button>
        </header>
        <div className="modal-body">
          <table className="matrix">
            <thead>
              <tr>
                <th></th>
                {convictions.map((c) => <th key={c} className="matrix-conv">{c}</th>)}
              </tr>
            </thead>
            <tbody>
              {actions.map((a) => (
                <tr key={a}>
                  <th scope="row">
                    <span className={`code-badge code-${a}`}>{a}</span>
                  </th>
                  {convictions.map((c) => {
                    const cell = DECISION_MATRIX[a][c];
                    return (
                      <td key={c} className={`matrix-cell matrix-${cell.tag}`}>
                        <span className="matrix-glyph">{CELL_GLYPH[cell.tag]}</span>
                        <span className="matrix-body">{cell.body}</span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <footer className="matrix-foot">
            <div>
              <span className="matrix-foot-label">Size bands (% of book):</span>
              {" "}HIGH 3.0–6.0 / MEDIUM 1.5–3.0 / LOW 0.
            </div>
            <div>
              <span className="matrix-foot-label">Mode multiplier:</span>
              {" "}B 1.0 / B′ 0.5 / C 0.333. Applied only when action == BUY.
            </div>
            <div className="matrix-legend">
              <span><span className="matrix-glyph">✓</span> canonical</span>
              <span><span className="matrix-glyph">⛔</span> blocked / non-canonical</span>
              <span><span className="matrix-glyph">·</span> reachable, non-action</span>
            </div>
          </footer>
        </div>
      </div>
    </div>
  );
};

type CardProps = {
  memo: Memo;
  onDelete: (file: string) => void;
};

const SUMMARY_CODE_RE = /^(BUY|HOLD|TRIM|SELL|ADD|WATCH|PASS|REJECT)$/i;

const pickSummaryCode = (data: Record<string, unknown>): string | null => {
  for (const k of ["summary_code", "recommendation", "decision", "disposition_recommendation"]) {
    const v = data[k];
    if (typeof v === "string" && SUMMARY_CODE_RE.test(v)) return v.toUpperCase();
  }
  return null;
};

const pickConviction = (data: Record<string, unknown>): string | null => {
  const v = data.conviction;
  if (typeof v === "string" && /^(HIGH|MEDIUM|LOW)$/i.test(v)) return v.toUpperCase();
  if (typeof v === "number") return v.toFixed(2);
  return null;
};

const MemoCard = ({ memo, onDelete }: CardProps) => {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const md = typeof memo.data.markdown === "string" ? (memo.data.markdown as string) : null;
  const summaryCode = pickSummaryCode(memo.data);
  const conviction = pickConviction(memo.data);
  const entries = Object.entries(memo.data).filter(([k]) => !META_KEYS.has(k) && k !== "markdown");

  const copy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const payload = md ?? JSON.stringify(memo.data, null, 2);
    await navigator.clipboard.writeText(payload);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  const remove = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(`Delete ${memo.file}?`)) return;
    try {
      await deleteMemo(memo.file);
      onDelete(memo.file);
    } catch (err) {
      alert(String(err));
    }
  };

  return (
    <article className="memo">
      <header className="memo-h" onClick={() => setOpen((o) => !o)}>
        <div className="memo-id">
          <div className="memo-kind">{memo.kind}</div>
          <div className="memo-file">{memo.file}</div>
        </div>
        <div className="memo-meta">
          {summaryCode && (
            <span className={`code-badge code-${summaryCode}`} title="summary code">
              {summaryCode}
            </span>
          )}
          {conviction && <span className="badge" title="conviction">{conviction}</span>}
          <span className={`src-badge src-${memo.source}`}>{memo.source}</span>
          <span className="created" title="created">{formatDate(memo.createdAt)}</span>
          {memo.asOf && <span className="badge">as-of {memo.asOf}</span>}
          <button
            className="icon-btn"
            onClick={copy}
            title={copied ? "copied" : "copy JSON"}
            aria-label="copy"
          >
            {copied ? <IconCheck /> : <IconCopy />}
          </button>
          {memo.source !== "agent" && (
            <button
              className="icon-btn icon-btn-danger"
              onClick={remove}
              title={memo.source === "db" ? "delete DB row" : "delete memo"}
              aria-label="delete"
            >
              <IconTrash />
            </button>
          )}
          <span className="chev">{open ? "▾" : "▸"}</span>
        </div>
      </header>
      {open && (
        <div className="memo-body">
          {md && <Markdown text={md} />}
          {entries.map(([k, v]) => <Section key={k} k={k} v={v} />)}
        </div>
      )}
    </article>
  );
};

const THEME_KEY = "dashboard-theme";
const SORT_KEY = "dashboard-sort";
const TABS_KEY = "dashboard-tabs";
const ACTIVE_KEY = "dashboard-active";
const VIEW_KEY = "dashboard-view";

type View = "tickers" | "runs";

type TabPaneProps = {
  ticker: string;
  memos: Memo[];
  hidden: boolean;
  onDelete: (file: string) => void;
};

// Each TabPane has its own React tree, so MemoCard `open` state is preserved
// across tab switches (we toggle visibility, not mount/unmount).
const TabPane = ({ ticker, memos, hidden, onDelete }: TabPaneProps) => (
  <div className="tab-pane" hidden={hidden}>
    {ticker !== AGENTS_BUCKET && ticker !== "UNKNOWN" && (
      <LivePanel ticker={ticker} />
    )}
    <div className="memos">
      {memos.map((m) => (
        <MemoCard key={m.file} memo={m} onDelete={onDelete} />
      ))}
    </div>
  </div>
);
type Theme = "light" | "dark";
type SortKey = "newest" | "oldest" | "kind" | "name" | "source";

const SORTS: Record<SortKey, { label: string; cmp: (a: Memo, b: Memo) => number }> = {
  newest: { label: "Newest first",  cmp: (a, b) => b.createdAt - a.createdAt },
  oldest: { label: "Oldest first",  cmp: (a, b) => a.createdAt - b.createdAt },
  kind:   { label: "Kind",          cmp: (a, b) => a.kind.localeCompare(b.kind) || b.createdAt - a.createdAt },
  source: { label: "Source",        cmp: (a, b) => a.source.localeCompare(b.source) || b.createdAt - a.createdAt },
  name:   { label: "Name",          cmp: (a, b) => a.file.localeCompare(b.file) },
};

export const App = () => {
  const [memos, setMemos] = useState<Memo[]>(ALL_INITIAL);
  const [query, setQuery] = useState("");
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem(THEME_KEY) as Theme | null;
    if (saved) return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  const [sortKey, setSortKey] = useState<SortKey>(() => {
    const saved = localStorage.getItem(SORT_KEY) as SortKey | null;
    return saved && saved in SORTS ? saved : "newest";
  });
  const [view, setView] = useState<View>(() => {
    const saved = localStorage.getItem(VIEW_KEY);
    return saved === "runs" ? "runs" : "tickers";
  });

  useEffect(() => {
    localStorage.setItem(VIEW_KEY, view);
  }, [view]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem(SORT_KEY, sortKey);
  }, [sortKey]);

  const groups = useMemo(() => groupByTicker(memos), [memos]);
  const tickers = useMemo(() => Array.from(groups.keys()), [groups]);

  // Per-ticker latest decision (newest memo with a summary_code-like field).
  const latestDecisions = useMemo(() => {
    const out = new Map<string, string>();
    for (const [t, rows] of groups) {
      let best: { ts: number; code: string } | null = null;
      for (const m of rows) {
        const code = pickSummaryCode(m.data);
        if (code && (best === null || m.createdAt > best.ts)) {
          best = { ts: m.createdAt, code };
        }
      }
      if (best) out.set(t, best.code);
    }
    return out;
  }, [groups]);
  const [status, setStatus] = useState<IndexStatus>({ errors: [], builtAt: 0 });
  const [refreshing, setRefreshing] = useState(false);
  const [statusDismissed, setStatusDismissed] = useState(false);
  const [matrixOpen, setMatrixOpen] = useState(false);

  useEffect(() => {
    fetchStatus().then(setStatus).catch(() => {/* ignore */});
  }, []);

  const handleRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await refreshIndex();
      // Server broadcasts a full-reload over Vite HMR which will re-fetch the
      // virtual module + remount the app. Give it a beat then force-reload
      // defensively if HMR didn't fire.
      setTimeout(() => window.location.reload(), 250);
    } catch (e) {
      alert(`refresh failed: ${e}`);
      setRefreshing(false);
    }
  };

  const [tabs, setTabs] = useState<string[]>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(TABS_KEY) ?? "[]") as string[];
      return Array.isArray(saved) ? saved : [];
    } catch {
      return [];
    }
  });
  const [selected, setSelected] = useState<string | null>(() => {
    return localStorage.getItem(ACTIVE_KEY) || tickers[0] || null;
  });

  // Prune tabs that no longer exist (after cascade delete or memo removal).
  useEffect(() => {
    setTabs((prev) => prev.filter((t) => groups.has(t)));
  }, [groups]);

  useEffect(() => {
    if (selected && !groups.has(selected)) setSelected(tabs[0] ?? tickers[0] ?? null);
  }, [selected, groups, tabs, tickers]);

  useEffect(() => {
    localStorage.setItem(TABS_KEY, JSON.stringify(tabs));
  }, [tabs]);

  useEffect(() => {
    if (selected) localStorage.setItem(ACTIVE_KEY, selected);
    else localStorage.removeItem(ACTIVE_KEY);
  }, [selected]);

  const openTicker = (t: string) => {
    setTabs((prev) => (prev.includes(t) ? prev : [...prev, t]));
    setSelected(t);
  };

  const closeTab = (e: React.MouseEvent, t: string) => {
    e.stopPropagation();
    setTabs((prev) => {
      const next = prev.filter((x) => x !== t);
      if (selected === t) {
        const idx = prev.indexOf(t);
        const fallback = next[idx - 1] ?? next[0] ?? null;
        setSelected(fallback);
      }
      return next;
    });
  };

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase();
    return q ? tickers.filter((t) => t.includes(q)) : tickers;
  }, [query, tickers]);

  const visible = useMemo(() => {
    const rows = selected ? groups.get(selected) ?? [] : [];
    return [...rows].sort(SORTS[sortKey].cmp);
  }, [selected, groups, sortKey]);

  const sortedByTab = useMemo(() => {
    const out = new Map<string, Memo[]>();
    for (const t of tabs) {
      const rows = groups.get(t) ?? [];
      out.set(t, [...rows].sort(SORTS[sortKey].cmp));
    }
    return out;
  }, [tabs, groups, sortKey]);

  const handleDelete = (file: string) => {
    setMemos((prev) => prev.filter((m) => m.file !== file));
  };

  const handleTickerDelete = async (e: React.MouseEvent, t: string) => {
    e.stopPropagation();
    const count = groups.get(t)?.length ?? 0;
    if (!confirm(`Cascade delete ALL ${count} outputs for ${t}?\n\nThis removes:\n  • disk memos (.json/.md) under memos/\n  • DB rows in analyst_briefs, execution_recommendations, watchlist, counterfactual_ledger\n  • run_id-keyed bundles in predictions, evidence_index\n\nThis cannot be undone.`)) return;
    try {
      const r = await deleteTickerCascade(t);
      setMemos((prev) => prev.filter((m) => m.ticker !== t));
      const errs = r.errors.length ? `\nErrors: ${r.errors.join("; ")}` : "";
      alert(`${t}: removed ${r.files} files + ${r.rows} DB rows.${errs}`);
    } catch (err) {
      alert(String(err));
    }
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-top">
          <div className="view-toggle" role="tablist" aria-label="view mode">
            <button
              role="tab"
              aria-selected={view === "tickers"}
              className={`view-toggle-btn ${view === "tickers" ? "view-active" : ""}`}
              onClick={() => setView("tickers")}
              title="ticker-grouped view"
            >Tickers</button>
            <button
              role="tab"
              aria-selected={view === "runs"}
              className={`view-toggle-btn ${view === "runs" ? "view-active" : ""}`}
              onClick={() => setView("runs")}
              title="per-run observability view"
            >Runs</button>
          </div>
          <div className="sidebar-actions">
            <button
              className="theme-toggle"
              onClick={() => setMatrixOpen(true)}
              title="action × conviction matrix"
              aria-label="open decision matrix help"
            >
              <IconHelp />
            </button>
            <button
              className="theme-toggle"
              onClick={handleRefresh}
              title="refresh data (re-scan disk + DB)"
              disabled={refreshing}
            >
              <span className={refreshing ? "spin" : ""}>↻</span>
            </button>
            <button
              className="theme-toggle"
              onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
              title="toggle theme"
            >
              {theme === "dark" ? "☀" : "☾"}
            </button>
          </div>
        </div>
        {view === "tickers" && (
          <>
        <input
          className="search"
          placeholder="Filter tickers…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <nav>
          {filtered.map((t) => {
            const count = groups.get(t)?.length ?? 0;
            const deletable = t !== AGENTS_BUCKET;
            return (
              <div key={t} className={`tick-row ${selected === t ? "active" : ""}`}>
                <button
                  className="tick"
                  onClick={() => openTicker(t)}
                >
                  <span className="tick-name">{t}</span>
                  {latestDecisions.get(t) && (
                    <span
                      className={`code-badge code-badge-sm code-${latestDecisions.get(t)}`}
                      title={`latest decision: ${latestDecisions.get(t)}`}
                    >
                      {latestDecisions.get(t)}
                    </span>
                  )}
                  <span className="count">{count}</span>
                </button>
                {deletable && (
                  <button
                    className="tick-del icon-btn icon-btn-danger"
                    onClick={(e) => handleTickerDelete(e, t)}
                    title={`cascade delete ${t}`}
                    aria-label={`delete ${t}`}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                      <path d="M10 11v6M14 11v6" />
                    </svg>
                  </button>
                )}
              </div>
            );
          })}
        </nav>
        <footer className="sidebar-foot">
          {memos.length} memos · {tickers.length} tickers
        </footer>
          </>
        )}
        {view === "runs" && (
          <div className="sidebar-runs-hint rv-muted">
            Run-centric observability — pick a run on the right to inspect its parameters snapshot, stage timeline, envelopes, recommendation, and any system errors.
          </div>
        )}
      </aside>

      <main className={`content ${view === "runs" ? "content-runs" : ""}`}>
        {view === "runs" ? (
          <RunsView />
        ) : (<>
        {status.errors.length > 0 && !statusDismissed && (
          <div className="status-banner">
            <div className="status-icon">⚠</div>
            <div className="status-body">
              <div className="status-title">
                {status.errors.length} index query{status.errors.length === 1 ? "" : "s"} failed
              </div>
              <ul className="status-list">
                {status.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
              <div className="status-hint">
                Likely a transient DB outage — check Postgres, then click ↻ Refresh in the sidebar.
              </div>
            </div>
            <button
              className="status-close"
              onClick={() => setStatusDismissed(true)}
              title="dismiss"
              aria-label="dismiss"
            >×</button>
          </div>
        )}
        {tabs.length > 0 && (
          <div className="tabs">
            {tabs.map((t) => (
              <div
                key={t}
                className={`tab ${selected === t ? "tab-active" : ""}`}
                onClick={() => setSelected(t)}
              >
                <span className="tab-name">{t}</span>
                {latestDecisions.get(t) && (
                  <span
                    className={`code-badge code-badge-sm code-${latestDecisions.get(t)}`}
                    title={`latest: ${latestDecisions.get(t)}`}
                  >
                    {latestDecisions.get(t)}
                  </span>
                )}
                <button
                  className="tab-close"
                  onClick={(e) => closeTab(e, t)}
                  title={`close ${t}`}
                  aria-label={`close ${t}`}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
        {selected ? (
          <>
            <header className="content-h">
              <h2>{selected}</h2>
              <span className="muted">{visible.length} output{visible.length === 1 ? "" : "s"}</span>
              <label className="sort">
                <span className="sort-label">Sort</span>
                <select
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value as SortKey)}
                >
                  {(Object.keys(SORTS) as SortKey[]).map((k) => (
                    <option key={k} value={k}>{SORTS[k].label}</option>
                  ))}
                </select>
              </label>
            </header>
            {tabs.map((t) => (
              <TabPane
                key={t}
                ticker={t}
                memos={sortedByTab.get(t) ?? []}
                hidden={t !== selected}
                onDelete={handleDelete}
              />
            ))}
          </>
        ) : (
          <p className="muted">No memos found in ../memos.</p>
        )}
        </>)}
      </main>
      {matrixOpen && <DecisionMatrixModal onClose={() => setMatrixOpen(false)} />}
    </div>
  );
};
