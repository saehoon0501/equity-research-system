// Client-side types + fetchers for the run-centric view. Mirrors the shapes
// emitted by vite.config.ts's /__api/runs endpoints. Keep field names in sync.

export type RunListRow = {
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

export type ValidationAttempt = {
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

export type EnvelopeFile = {
  agent: string;
  filename: string;
  kind: "envelope" | "context" | "degraded" | "backup";
  size_bytes: number;
  modified_at: number;
  data: Record<string, unknown> | null;
};

export type RunDetail = {
  snapshot: Record<string, unknown> | null;
  recommendation: Record<string, unknown> | null;
  attempts: ValidationAttempt[];
  envelopes: EnvelopeFile[];
  system_errors: Array<Record<string, unknown>>;
};

export const fetchRuns = async (): Promise<RunListRow[]> => {
  const res = await fetch("/__api/runs");
  if (!res.ok) throw new Error(`runs list: ${res.status}`);
  return (await res.json()) as RunListRow[];
};

export const fetchRunDetail = async (runId: string): Promise<RunDetail> => {
  const res = await fetch(`/__api/runs/${encodeURIComponent(runId)}`);
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? `run detail: ${res.status}`);
  }
  return (await res.json()) as RunDetail;
};

// Group attempts by agent for the per-stage timeline. Within each agent,
// attempts come back already sorted by attempt_n from the server.
export const groupAttempts = (attempts: ValidationAttempt[]): Map<string, ValidationAttempt[]> => {
  const out = new Map<string, ValidationAttempt[]>();
  for (const a of attempts) {
    const arr = out.get(a.agent_type) ?? [];
    arr.push(a);
    out.set(a.agent_type, arr);
  }
  return out;
};
