---
status: pending
priority: P1
filed: 2026-09-26
source: Postgres best-practices audit of the live database, 2026-09-26 (read-only)
---

# postgres-exporter's per-table scrape is the top database consumer; idle-in-transaction timeout is 1 hour

## What

1. **Monitoring costs more than the work it monitors.** `pg_stat_statements` (reset 2026-09-23)
   ranks first by total time a `postgres-exporter` stats query over `pg_stat_all_tables`: about
   1 s per call, 17,932 calls, 305 minutes in 3 days, more than every `alpha_events` insert
   combined. The exporter (`indicagent-postgres-exporter`, Prometheus `scrape_interval: 15s`)
   walks every TimescaleDB chunk table in `_timescaledb_internal`. A sibling statio query adds
   another 14 minutes. Fix: exclude `_timescaledb_internal` from the table collectors (or use the
   hypertable-level views), or move those collectors to a 5-minute scrape. Keep the
   database-level and activity collectors at 15 s.
2. **`idle_in_transaction_session_timeout` is 3,600,000 ms (1 hour).** An orphaned worker that
   holds chunk locks (the Phase 178 resume incident, CLAUDE.md) can block writers for an hour.
   Set it to 5-10 minutes; long batch jobs that legitimately idle in a transaction set their own
   session value.

Re-measure with `pg_stat_statements` after both changes (reset first) and record the before and
after in this todo's closure note.

## Done when

The exporter query is out of the top of `pg_stat_statements` by total time, the timeout is set in
the compose-managed Postgres config (not only via `ALTER SYSTEM` by hand), and both are verified.

## Progress 2026-10-07 (partial)

- Baseline over 13.9 days: the `pg_stat_all_tables` stats query is still first (85 min, 25,962 calls); `pg_database_size` is second (59 min, 480,744 calls). 313 chunks.
- Done: `--no-collector.statio_user_tables` in `production/docker-compose.yml` (nothing reads statio). `pg_stat_statements` reset at 2026-10-07 16:01 UTC for the after-measurement.
- Not done, and why: `stat_user_tables` stays on because `DeadTupleRatioHigh` (`alertmanager-rules.yml`) reads it; turning it off silences that alert. Fixing the main cost needs a custom exporter query over hypertable-level views plus a rewrite of that alert.
- Not done: the 10 minute `idle_in_transaction_session_timeout`. Before setting it, check the 189 fetcher, the 449 5m lane and the 186-26 rebuild for sessions that idle in a transaction while waiting on IBKR (they would be killed). Applying it needs a timescaledb restart.
- Note: the first `docker compose up -d postgres-exporter` also restarted `timescaledb` (compose drift); nothing was running against it.
