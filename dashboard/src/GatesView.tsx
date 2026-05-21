import { useEffect, useMemo, useState } from "react";
import { fetchGateScorecard, type GateAggRow, type GateScorecard } from "./gates";

const pct = (r: number): string => `${Math.round(r * 100)}%`;
const cost = (n: number): string => `$${n.toFixed(2)}`;

// Sparkline rendered with Unicode block characters — keeps the row compact
// and copies cleanly to clipboard / monitoring chat. Each decision becomes
// one block: P=full (green), F=full (red), ?=light (muted).
const SparkBlocks = ({ decisions }: { decisions: string[] }) => {
  if (decisions.length === 0) return <span className="gs-empty">—</span>;
  return (
    <span className="gs-spark" title={`oldest → newest: ${decisions.join(" ")}`}>
      {decisions.map((d, i) => {
        const cls = d === "P" ? "gs-spark-pass" : d === "F" ? "gs-spark-fail" : "gs-spark-na";
        return <span key={i} className={`gs-spark-cell ${cls}`}>█</span>;
      })}
    </span>
  );
};

const trendArrow = (decisions: string[]): { arrow: string; cls: string; tip: string } | null => {
  if (decisions.length < 6) return null;
  const half = Math.floor(decisions.length / 2);
  const leadFail = decisions.slice(0, half).filter((d) => d === "F").length / half;
  const trailFail = decisions.slice(half).filter((d) => d === "F").length / (decisions.length - half);
  const delta = trailFail - leadFail;
  if (delta > 0.2) return { arrow: "↑", cls: "gs-trend-up", tip: `fail rate rose ${pct(leadFail)} → ${pct(trailFail)}` };
  if (delta < -0.2) return { arrow: "↓", cls: "gs-trend-down", tip: `fail rate fell ${pct(leadFail)} → ${pct(trailFail)}` };
  return null;
};

const passRateClass = (rate: number): string => {
  if (rate >= 0.9) return "gs-rate-good";
  if (rate >= 0.6) return "gs-rate-mid";
  return "gs-rate-bad";
};

const GateRow = ({ row, hg = false }: { row: GateAggRow; hg?: boolean }) => {
  const trend = trendArrow(row.recent_decisions);
  return (
    <tr className="gs-row">
      <td className="gs-name">
        <code>{row.name}</code>
        {trend && <span className={`gs-trend ${trend.cls}`} title={trend.tip}>{trend.arrow}</span>}
      </td>
      <td className="gs-num">{row.attempts_total}</td>
      {!hg && (
        <td className={`gs-num gs-rate ${passRateClass(row.pass_rate)}`}>{pct(row.pass_rate)}</td>
      )}
      <td className="gs-num">{row.attempts_fail}</td>
      {hg && (
        <td className="gs-num gs-esc">{row.attempts_escalate > 0 ? row.attempts_escalate : ""}</td>
      )}
      <td className="gs-num gs-cost">{cost(row.cost_when_fail_usd)}</td>
      <td className="gs-num gs-cost">{cost(row.cost_avg_per_attempt_usd)}</td>
      <td className="gs-spark-cell-wrap"><SparkBlocks decisions={row.recent_decisions} /></td>
      <td className="gs-agents">
        {row.agents.map((a) => <span key={a} className="gs-agent-chip">{a}</span>)}
      </td>
    </tr>
  );
};

export const GatesView = () => {
  const [data, setData] = useState<GateScorecard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [hideClean, setHideClean] = useState(false);

  useEffect(() => {
    fetchGateScorecard().then(setData).catch((e) => setErr(String(e)));
  }, []);

  const visibleChecks = useMemo(() => {
    if (!data) return [];
    if (!hideClean) return data.checks;
    // "Hide all-pass" — operators usually only care about gates with at least one fail.
    return data.checks.filter((c) => c.attempts_fail > 0);
  }, [data, hideClean]);

  if (err) return <div className="rerr">Failed to load scorecard: {err}</div>;
  if (!data) return <div className="rv-muted">Loading gate scorecard…</div>;

  const totalCost = data.checks.reduce((s, r) => s + r.cost_when_fail_usd, 0)
    + data.hg_codes.reduce((s, r) => s + r.cost_when_fail_usd, 0);

  return (
    <div className="gview">
      <header className="gview-h">
        <h2>Gate scorecard</h2>
        <div className="gview-meta">
          <span><strong>{data.total_attempts}</strong> attempts</span>
          <span><strong>{data.total_runs}</strong> runs</span>
          <span><strong>{data.decision_breakdown.PASS ?? 0}</strong> pass</span>
          <span><strong>{data.decision_breakdown.RETRY ?? 0}</strong> retry</span>
          <span className={(data.decision_breakdown.ESCALATE ?? 0) > 0 ? "gs-warn" : ""}>
            <strong>{data.decision_breakdown.ESCALATE ?? 0}</strong> escalate
          </span>
          <span><strong>{cost(totalCost)}</strong> retry-cost burned</span>
        </div>
      </header>

      {data.insights.length > 0 && (
        <section className="gs-insights">
          <h3>Insights</h3>
          <ul>
            {data.insights.map((i, idx) => <li key={idx}>{i}</li>)}
          </ul>
        </section>
      )}

      <section className="gs-section">
        <div className="gs-section-h">
          <h3>Named checks <span className="rv-muted">({visibleChecks.length}{hideClean ? ` of ${data.checks.length}` : ""})</span></h3>
          <label className="gs-toggle">
            <input type="checkbox" checked={hideClean} onChange={(e) => setHideClean(e.target.checked)} />
            Hide all-pass
          </label>
        </div>
        <table className="gs-table">
          <thead>
            <tr>
              <th>Gate</th>
              <th>Attempts</th>
              <th>Pass %</th>
              <th>Fails</th>
              <th>Retry $</th>
              <th>Avg $/att</th>
              <th>Last 14</th>
              <th>Agents</th>
            </tr>
          </thead>
          <tbody>
            {visibleChecks.map((r) => <GateRow key={r.name} row={r} />)}
            {visibleChecks.length === 0 && (
              <tr><td colSpan={8} className="rv-muted">No gates match filter.</td></tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="gs-section">
        <div className="gs-section-h">
          <h3>HG-codes (failure-coded) <span className="rv-muted">({data.hg_codes.length})</span></h3>
        </div>
        {data.hg_codes.length === 0 ? (
          <div className="rv-muted">No HG-code failures recorded.</div>
        ) : (
          <table className="gs-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Attempts</th>
                <th>Fails</th>
                <th>Escalates</th>
                <th>Retry $</th>
                <th>Avg $/att</th>
                <th>Last 14</th>
                <th>Agents</th>
              </tr>
            </thead>
            <tbody>
              {data.hg_codes.map((r) => <GateRow key={r.name} row={r} hg />)}
            </tbody>
          </table>
        )}
      </section>

      <footer className="gs-foot">
        <span className="rv-muted">
          Aggregated from <code>logs/validation_attempts.jsonl</code>. Sparkline cells = last {Math.min(14, data.total_attempts)} attempts per gate, oldest left → newest right. Trend arrows fire when fail-rate delta ≥ 20pp between leading and trailing halves of the spark window.
        </span>
      </footer>
    </div>
  );
};
