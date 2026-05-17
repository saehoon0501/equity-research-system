# Database substrate (Tier 1)

Local Postgres + TimescaleDB stack for the equity research system. Brought up via Docker Compose. Data persists in a named Docker volume (`equity-research-db-data`).

Per BUILD_LOG.md decision 6, this is a *tool* consumed by Claude Code — not an orchestrator. Schemas, migrations, and queries are issued by slash commands via `mcp__postgres`. This directory holds only the bring-up plumbing.

## Bring up the stack

```sh
# 1. Copy env template; edit POSTGRES_PASSWORD locally.
cp .env.example .env

# 2. Start the container.
docker compose up -d

# 3. Verify the container is healthy.
docker compose ps
# Expect: equity-research-db ... healthy

# 4. Verify first-boot init landed (extensions installed).
#    Connect with the credentials in your .env:
docker exec -it equity-research-db \
    psql -U "$(grep POSTGRES_USER .env | cut -d= -f2)" \
         -d equity_research \
         -c "SELECT extname, extversion FROM pg_extension ORDER BY extname;"
# Expect rows for: pgcrypto, plpgsql, timescaledb
```

## Stop the stack

```sh
# Stop the container, keep the data volume.
docker compose down

# Stop AND wipe data (resets to first-boot — init scripts run again).
docker compose down -v
```

## What's in `db/init/`

Postgres image runs every `*.sql` and `*.sh` here, in alphabetical order, **only on first initialization** (when `/var/lib/postgresql/data` is empty). After first boot, this directory is ignored.

- `01-extensions.sql` — installs `timescaledb` and `pgcrypto` extensions on the `equity_research` database. Both are required by later tier work; loaded once, at first boot.

Tier 2 (Conventions) DDL — `evidence_index`, append-only triggers, Predictions DB, Counterfactual Ledger — does **not** land here. Those are applied as a deliberate migration step against a running DB, so failure modes are visible to the operator (vs. silent partial init on container start). See BUILD_LOG.md Tier 2 step list.

## Migrations after first boot

There is no migration framework wired yet. When Tier 2 lands, the operator applies DDL by reading the SQL from `.claude/references/evidence-index-schema.md` (and equivalent files for other schemas) and executing it via `psql` or `mcp__postgres`. A lightweight migration tracker — e.g., a `schema_migrations` table the operator updates by hand — is sufficient for v0.1 scope; promoted to a real migration tool (alembic, sqitch, etc.) only if Tier 4 reveals it's needed.

## Connection string

For local tools (psql, MCP server config, ad-hoc clients):

```
postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-equity_research}
```

Where the variables come from your local `.env`.

## What this is not

- **Not production-tuned.** Default Postgres parameters; no `shared_buffers` overrides, no replication, no backup policy. Local v0.1 paper-only use.
- **Not the migration system.** First-boot init is for "extensions present, ready to apply schemas," not for declaring application tables.
- **Not the MCP wiring.** `mcp__postgres` is configured separately (next Tier 1 step in BUILD_LOG.md). This directory just makes the DB reachable.

## Reset and rebuild

If anything in `db/init/` changes, the new init scripts run only on a fresh data volume. To re-run them:

```sh
docker compose down -v   # destroys data
docker compose up -d
```

Reasonable to do during Tier 1 / Tier 2 since there's no production data yet.
