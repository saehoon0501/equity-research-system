-- 028_analyst_briefs.sql
-- Per spec §16.6 — per-ticker time-stamped brief history.
-- Cold-start: no prior brief for ticker → search-agent does full sweep,
-- brief built from scratch.
-- Warm-start: prior brief exists → search-agent does delta-sweep,
-- brief built as delta against prior, prior_brief_id linked, delta_summary populated.

CREATE TABLE IF NOT EXISTS analyst_briefs (
    brief_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker TEXT NOT NULL,
    run_id TEXT NOT NULL,
    brief_type TEXT NOT NULL CHECK (brief_type IN ('quantitative', 'strategic')),
    tier TEXT NOT NULL CHECK (tier IN ('core_fundamental','thematic_growth','speculative_optionality')),
    sector_identification TEXT NOT NULL,
    content TEXT NOT NULL,
    sources_used JSONB NOT NULL,
    essentials_referenced TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    prior_brief_id UUID REFERENCES analyst_briefs(brief_id),
    delta_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS analyst_briefs_ticker_type_recent
    ON analyst_briefs(ticker, brief_type, created_at DESC);

CREATE INDEX IF NOT EXISTS analyst_briefs_ticker_recent
    ON analyst_briefs(ticker, created_at DESC);

COMMENT ON TABLE analyst_briefs IS
    'Per-ticker time-stamped analytical briefs delivered to quantitative-analyst and strategic-analyst by cdd-lead. Linked-list via prior_brief_id enables longitudinal drift audit and warm-start delta generation.';
COMMENT ON COLUMN analyst_briefs.delta_summary IS
    'Human-readable diff between this brief and prior_brief. NULL on cold-start. High-signal artifact for slow-layer monitoring.';
