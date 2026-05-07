-- 027_research_essentials.sql
-- Per spec §16.6 — atemporal cross-company methodology learnings.
-- Lifecycle: written by cdd-lead Stage 2 (UPSERT 0-3 per run, increment confidence
-- on reaffirmation); read by cdd-lead Stage 1 (filter by topic_tags overlap).

CREATE TABLE IF NOT EXISTS research_essentials (
    key TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    topic_tags TEXT[] NOT NULL,
    source_run_ids TEXT[] NOT NULL,
    confidence INT NOT NULL DEFAULT 1,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS research_essentials_tags_idx
    ON research_essentials USING GIN (topic_tags);

COMMENT ON TABLE research_essentials IS
    'Durable cross-company methodology learnings extracted from /research-company runs. Read in cdd-lead Stage 1 brief generation.';
COMMENT ON COLUMN research_essentials.confidence IS
    'Count of distinct runs that reaffirmed this learning. <3 = preliminary; brief-generator must re-verify via search-agent.';
