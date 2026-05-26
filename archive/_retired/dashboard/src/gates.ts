// Client-side types for the gate scorecard. Mirrors the shapes emitted by
// vite.config.ts's /__api/gates endpoint. Keep field names in sync.

export type GateAggRow = {
  name: string;
  kind: "check" | "hg_code";
  agents: string[];
  attempts_total: number;
  attempts_pass: number;
  attempts_fail: number;
  attempts_escalate: number;
  pass_rate: number;
  cost_when_fail_usd: number;
  cost_avg_per_attempt_usd: number;
  recent_decisions: string[];
  last_failed_run_id: string | null;
  last_failed_at: number | null;
};

export type GateScorecard = {
  generated_at: number;
  total_attempts: number;
  total_runs: number;
  decision_breakdown: Record<string, number>;
  checks: GateAggRow[];
  hg_codes: GateAggRow[];
  insights: string[];
};

export const fetchGateScorecard = async (): Promise<GateScorecard> => {
  const res = await fetch("/__api/gates");
  if (!res.ok) throw new Error(`gates: ${res.status}`);
  return (await res.json()) as GateScorecard;
};
