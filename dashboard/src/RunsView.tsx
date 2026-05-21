import { useEffect, useMemo, useState } from "react";
import {
  fetchRuns,
  fetchRunDetail,
  groupAttempts,
  type EnvelopeFile,
  type RunDetail,
  type RunListRow,
  type ValidationAttempt,
} from "./runs";

const ACTIVE_RUN_KEY = "dashboard-active-run";

const formatTs = (s: string | null | undefined): string => {
  if (!s) return "—";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
};

const formatCost = (n: number): string => `$${n.toFixed(2)}`;

const statusClass = (s: string | null | undefined): string => {
  if (!s) return "rs-unknown";
  if (s === "completed") return "rs-ok";
  if (s === "in_progress" || s === "in_flight") return "rs-flight";
  if (s.startsWith("failed_") || s === "rejected") return "rs-fail";
  return "rs-unknown";
};

const decisionClass = (d: string): string => {
  if (d === "PASS") return "rd-pass";
  if (d === "RETRY") return "rd-retry";
  if (d === "ESCALATE") return "rd-escalate";
  return "rd-other";
};

// Separate component so the truncation hook obeys Rules of Hooks regardless
// of how JsonView is recursively called with different value shapes.
const StringValue = ({ value }: { value: string }) => {
  const long = value.length > 240;
  const [open, setOpen] = useState(!long);
  if (long && !open) {
    return (
      <span>
        <span className="rv-str">"{value.slice(0, 200)}…"</span>{" "}
        <button className="rv-more" onClick={() => setOpen(true)}>show ({value.length} chars)</button>
      </span>
    );
  }
  return <span className="rv-str">"{value}"</span>;
};

// Compact JSON renderer for snapshot + envelope payloads. Truncates strings
// over the threshold and recursively pretty-prints objects/arrays.
const JsonView = ({ value, depth = 0 }: { value: unknown; depth?: number }) => {
  if (value === null || value === undefined) return <span className="rv-null">null</span>;
  if (typeof value === "boolean") return <span className="rv-bool">{String(value)}</span>;
  if (typeof value === "number") return <span className="rv-num">{value.toLocaleString()}</span>;
  if (typeof value === "string") return <StringValue value={value} />;
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="rv-muted">[]</span>;
    return (
      <ol className="rv-arr">
        {value.map((v, i) => (
          <li key={i}><JsonView value={v} depth={depth + 1} /></li>
        ))}
      </ol>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="rv-muted">{"{}"}</span>;
    return (
      <dl className="rv-obj">
        {entries.map(([k, v]) => (
          <div key={k} className="rv-row">
            <dt className="rv-key">{k}</dt>
            <dd className="rv-val"><JsonView value={v} depth={depth + 1} /></dd>
          </div>
        ))}
      </dl>
    );
  }
  return <span>{String(value)}</span>;
};

const Collapsible = ({ title, defaultOpen = false, children }: {
  title: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="rsec">
      <button className="rsec-h" onClick={() => setOpen((o) => !o)}>
        <span className="chev">{open ? "▾" : "▸"}</span>
        <span className="rsec-title">{title}</span>
      </button>
      {open && <div className="rsec-body">{children}</div>}
    </section>
  );
};

const AttemptPill = ({ a }: { a: ValidationAttempt }) => {
  const cls = decisionClass(a.decision);
  const gates = a.failed_gate_ids?.length ? ` · ${a.failed_gate_ids.join(",")}` : "";
  return (
    <span className={`rpill ${cls}`} title={`attempt ${a.attempt_n} · ${a.decision}${gates} · ${a.fingerprint}`}>
      <span className="rpill-n">#{a.attempt_n}</span>
      <span className="rpill-d">{a.decision}</span>
      {typeof a.attempt_cost_usd === "number" && (
        <span className="rpill-c">{formatCost(a.attempt_cost_usd)}</span>
      )}
    </span>
  );
};

const StageRow = ({ agent, attempts }: { agent: string; attempts: ValidationAttempt[] }) => {
  const final = attempts[attempts.length - 1];
  const total = attempts.reduce((sum, a) => sum + (a.attempt_cost_usd ?? 0), 0);
  return (
    <div className="rstage">
      <div className="rstage-agent">{agent}</div>
      <div className="rstage-attempts">
        {attempts.map((a) => <AttemptPill key={a.attempt_n} a={a} />)}
      </div>
      <div className="rstage-final">
        <span className={`rfinal ${decisionClass(final?.decision ?? "")}`}>
          {final?.decision ?? "—"}
        </span>
        <span className="rstage-cost">{formatCost(total)}</span>
      </div>
      {attempts.some((a) => !a.validation_passed) && (
        <details className="rstage-detail">
          <summary>fingerprints + gates</summary>
          <table className="rftable">
            <thead>
              <tr><th>#</th><th>decision</th><th>fingerprint</th><th>failed gates</th></tr>
            </thead>
            <tbody>
              {attempts.map((a) => (
                <tr key={a.attempt_n}>
                  <td>{a.attempt_n}</td>
                  <td>{a.decision}</td>
                  <td className="rfp">{a.fingerprint}</td>
                  <td>{(a.failed_gate_ids ?? []).join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
};

const EnvelopeCard = ({ env }: { env: EnvelopeFile }) => {
  const kindBadge = env.kind === "envelope" ? null : (
    <span className={`env-kind env-kind-${env.kind}`}>{env.kind}</span>
  );
  return (
    <article className="renv">
      <header className="renv-h">
        <div className="renv-agent">
          <span>{env.agent}</span>
          {kindBadge}
        </div>
        <div className="renv-meta">
          <span className="rv-muted">{env.filename}</span>
          <span className="rv-muted">{(env.size_bytes / 1024).toFixed(1)} kB</span>
        </div>
      </header>
      {env.kind === "degraded" ? (
        <div className="renv-body rv-muted">
          (degraded marker — agent halted; no envelope written)
        </div>
      ) : env.data ? (
        <Collapsible title="payload" defaultOpen={false}>
          <JsonView value={env.data} />
        </Collapsible>
      ) : (
        <div className="renv-body rv-muted">(empty or unparseable)</div>
      )}
    </article>
  );
};

const RunListItem = ({ row, active, onClick }: {
  row: RunListRow;
  active: boolean;
  onClick: () => void;
}) => (
  <button className={`rrow ${active ? "rrow-active" : ""}`} onClick={onClick}>
    <div className="rrow-top">
      <span className="rrow-ticker">{row.ticker}</span>
      {row.summary_code && (
        <span className={`code-badge code-badge-sm code-${row.summary_code}`}>{row.summary_code}</span>
      )}
      <span className={`rstatus ${statusClass(row.run_status)}`}>{row.run_status ?? "—"}</span>
    </div>
    <div className="rrow-mid">
      <span className="rv-muted">{formatTs(row.run_started_at)}</span>
      {row.tag && <span className="rv-muted rrow-tag" title={`tag: ${row.tag}`}>{row.tag.slice(0, 8)}…</span>}
    </div>
    <div className="rrow-bot">
      <span title="validation attempts">{row.attempt_count} att</span>
      <span title="aggregate cost from validation_attempts.jsonl">{formatCost(row.total_cost_usd)}</span>
      <span title="agents that emitted a PASS envelope">{row.agents_completed.length}/{4} ag</span>
    </div>
  </button>
);

const RunDetailPane = ({ detail, row }: { detail: RunDetail; row: RunListRow }) => {
  const stages = useMemo(() => groupAttempts(detail.attempts), [detail.attempts]);
  const stageOrder = useMemo(() => {
    const canonical = ["quantitative-analyst", "strategic-analyst", "cdd-integration-stage2", "catalyst-scout", "pm-supervisor", "evaluator"];
    const seen = new Set(stages.keys());
    const ordered = canonical.filter((s) => seen.has(s));
    for (const s of seen) if (!ordered.includes(s)) ordered.push(s);
    return ordered;
  }, [stages]);

  const snapshot = detail.snapshot as Record<string, unknown> | null;
  const rec = detail.recommendation as Record<string, unknown> | null;
  const params = snapshot?.effective_parameters_jsonb as Record<string, unknown> | undefined;

  return (
    <div className="rdetail">
      <header className="rdetail-h">
        <h2>
          {row.ticker}
          <span className={`code-badge ${row.summary_code ? `code-${row.summary_code}` : ""}`} style={{marginLeft: 12}}>
            {row.summary_code ?? "no recommendation"}
          </span>
        </h2>
        <div className="rdetail-meta">
          <span className={`rstatus ${statusClass(row.run_status)}`}>{row.run_status ?? "—"}</span>
          <span className="rv-muted">started {formatTs(row.run_started_at)}</span>
          {row.run_ended_at && <span className="rv-muted">ended {formatTs(row.run_ended_at)}</span>}
          <span className="rv-muted">{formatCost(row.total_cost_usd)} total</span>
        </div>
        <div className="rdetail-id">run_id: <code>{row.run_id}</code></div>
      </header>

      <Collapsible title={<>Stage timeline · <span className="rv-muted">{detail.attempts.length} attempts across {stages.size} agents</span></>} defaultOpen={true}>
        {stageOrder.length === 0 ? (
          <div className="rv-muted">No validation attempts logged for this run.</div>
        ) : (
          <div className="rstages">
            {stageOrder.map((agent) => (
              <StageRow key={agent} agent={agent} attempts={stages.get(agent) ?? []} />
            ))}
          </div>
        )}
      </Collapsible>

      <Collapsible title={<>Envelopes · <span className="rv-muted">{detail.envelopes.length} files</span></>} defaultOpen={false}>
        {detail.envelopes.length === 0 ? (
          <div className="rv-muted">No envelope files found for this run_id.</div>
        ) : (
          <div className="renvs">
            {detail.envelopes.map((e) => <EnvelopeCard key={e.filename} env={e} />)}
          </div>
        )}
      </Collapsible>

      <Collapsible title="Final recommendation" defaultOpen={!!rec}>
        {rec ? <JsonView value={rec} /> : <div className="rv-muted">No execution_recommendations row keyed to this run_id (run did not reach pm-supervisor emission, or was rejected at evaluator).</div>}
      </Collapsible>

      <Collapsible title={<>Parameters snapshot · <span className="rv-muted">hash {row.parameters_hash_prefix}…</span></>} defaultOpen={false}>
        {snapshot ? (
          <>
            <table className="rkv">
              <tbody>
                <tr><td>parameters_version_max</td><td><code>{String(snapshot.parameters_version_max ?? "")}</code></td></tr>
                <tr><td>effective_parameters_hash</td><td><code>{String(snapshot.effective_parameters_hash ?? "")}</code></td></tr>
                <tr><td>tag</td><td>{snapshot.tag ? <code>{String(snapshot.tag)}</code> : <span className="rv-muted">production run</span>}</td></tr>
                <tr><td>tag_issued_at_unix</td><td>{snapshot.tag_issued_at_unix ? String(snapshot.tag_issued_at_unix) : <span className="rv-muted">—</span>}</td></tr>
              </tbody>
            </table>
            {params && (
              <Collapsible title={<>effective_parameters_jsonb · <span className="rv-muted">{Object.keys(params).length} keys</span></>}>
                <JsonView value={params} />
              </Collapsible>
            )}
          </>
        ) : <div className="rv-muted">No snapshot row.</div>}
      </Collapsible>

      {detail.system_errors.length > 0 && (
        <Collapsible title={<>System errors · <span className="rserr-count">{detail.system_errors.length}</span></>} defaultOpen={true}>
          <table className="rerrs">
            <thead><tr><th>time</th><th>source</th><th>type</th><th>detail</th></tr></thead>
            <tbody>
              {detail.system_errors.map((e, i) => (
                <tr key={i}>
                  <td className="rv-muted">{formatTs(String(e.timestamp_at ?? ""))}</td>
                  <td>{String(e.source ?? "")}</td>
                  <td>{String(e.error_type ?? "")}</td>
                  <td><code className="rerr-detail">{String(e.error_detail ?? "").slice(0, 240)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Collapsible>
      )}
    </div>
  );
};

export const RunsView = () => {
  const [runs, setRuns] = useState<RunListRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(() => localStorage.getItem(ACTIVE_RUN_KEY));
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    fetchRuns().then(setRuns).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    localStorage.setItem(ACTIVE_RUN_KEY, selectedId);
    setLoadingDetail(true);
    setDetailErr(null);
    fetchRunDetail(selectedId)
      .then((d) => { setDetail(d); setLoadingDetail(false); })
      .catch((e) => { setDetailErr(String(e)); setLoadingDetail(false); });
  }, [selectedId]);

  const filtered = useMemo(() => {
    if (!runs) return [];
    const q = filter.trim().toUpperCase();
    if (!q) return runs;
    return runs.filter((r) =>
      r.ticker.toUpperCase().includes(q)
      || r.run_id.startsWith(q.toLowerCase())
      || (r.summary_code ?? "").toUpperCase().includes(q)
      || (r.run_status ?? "").toUpperCase().includes(q),
    );
  }, [runs, filter]);

  const selectedRow = useMemo(
    () => filtered.find((r) => r.run_id === selectedId) ?? runs?.find((r) => r.run_id === selectedId) ?? null,
    [filtered, runs, selectedId],
  );

  if (error) return <div className="rerr">Failed to load runs: {error}</div>;
  if (!runs) return <div className="rv-muted">Loading runs…</div>;

  return (
    <div className="rgrid">
      <aside className="rlist">
        <input
          className="search"
          placeholder="Filter runs…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <div className="rlist-count">{filtered.length} run{filtered.length === 1 ? "" : "s"}</div>
        <div className="rlist-rows">
          {filtered.map((r) => (
            <RunListItem key={r.run_id} row={r} active={selectedId === r.run_id} onClick={() => setSelectedId(r.run_id)} />
          ))}
          {filtered.length === 0 && <div className="rv-muted" style={{padding: "12px 4px"}}>No runs match filter.</div>}
        </div>
      </aside>
      <main className="rmain">
        {!selectedRow && <div className="rv-muted">Pick a run from the list.</div>}
        {selectedRow && loadingDetail && <div className="rv-muted">Loading run detail…</div>}
        {selectedRow && detailErr && <div className="rerr">Failed: {detailErr}</div>}
        {selectedRow && detail && !loadingDetail && !detailErr && (
          <RunDetailPane detail={detail} row={selectedRow} />
        )}
      </main>
    </div>
  );
};
