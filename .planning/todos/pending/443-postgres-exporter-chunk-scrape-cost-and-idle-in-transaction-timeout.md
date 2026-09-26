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
