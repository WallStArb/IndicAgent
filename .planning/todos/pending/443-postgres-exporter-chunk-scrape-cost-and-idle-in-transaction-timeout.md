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

## Incident 2026-10-31 (the timeout change is now evidenced, with a caveat)

The 186-26 stage-2 rebuild's compute workers hold an idle-in-transaction read on
market_data_ohlcv_tradeable for their whole compute (the `rebuild_bars` server-side cursor
pattern: the txn opens at the cell's first read and stays open until the cell ends). At
12:29-12:31 EDT a wave of five-plus workers opened such txns; the 12:31 UTC-offset
`policy_compression` run on market_data_ohlcv queued behind them (relation lock), and behind
compression queued the rebuild's own DECLARE CURSOR readers, the audit's per-name reads and the
fetcher: the whole database stalled for about 20 minutes until the three oldest txns were
terminated by hand (12:38 EDT). Evidence in the session log; the compression jobs 1078
(market_data_ohlcv) and 1076 (ohlcv_raw) are PAUSED (`alter_job ... scheduled => false`) for the
rebuild's duration and MUST be re-enabled when 186-26 completes (`SELECT alter_job(1078,
scheduled => true); alter_job(1076, scheduled => true);`). Caveat for the timeout value: the
workers' idle txns legitimately last the whole compute (tens of minutes), so the 5-10 minute
timeout WOULD kill rebuild worker reads all day. The right fix is in the rebuild's read pattern
(close the read txn or fetch fully and close the cursor before compute), which cannot be edited
while the rebuild run is live (fingerprinted writer). Sequence: rebuild finishes -> re-enable
compression -> change the read pattern in the rebuild's modules -> then set the timeout. Add the
rebuild's worker-read pattern to the check list above.

## Done when

The exporter query is out of the top of `pg_stat_statements` by total time, the timeout is set in
the compose-managed Postgres config (not only via `ALTER SYSTEM` by hand), and both are verified.

## Progress 2026-10-07 (partial)

- Baseline over 13.9 days: the `pg_stat_all_tables` stats query is still first (85 min, 25,962 calls); `pg_database_size` is second (59 min, 480,744 calls). 313 chunks.
- Done: `--no-collector.statio_user_tables` in `production/docker-compose.yml` (nothing reads statio). `pg_stat_statements` reset at 2026-10-07 16:01 UTC for the after-measurement.
- Not done, and why: `stat_user_tables` stays on because `DeadTupleRatioHigh` (`alertmanager-rules.yml`) reads it; turning it off silences that alert. Fixing the main cost needs a custom exporter query over hypertable-level views plus a rewrite of that alert.
- Not done: the 10 minute `idle_in_transaction_session_timeout`. Before setting it, check the 189 fetcher, the 449 5m lane and the 186-26 rebuild for sessions that idle in a transaction while waiting on IBKR (they would be killed). Applying it needs a timescaledb restart.
- Note: the first `docker compose up -d postgres-exporter` also restarted `timescaledb` (compose drift); nothing was running against it.
- After-measurement at 23 min since the reset (2026-10-07): the `pg_stat_user_tables` query is still first, 14.2 s over 92 calls (about 0.15 s per call, about 1 h per day); `pg_database_size` is 558 calls in the same window (6 per scrape, worth a look). Re-check after a full day.
- Resolved: the 6 `pg_database_size` calls per scrape are one per database (indicagent, indicagent_test, langfuse, postgres, template0, template1) at about 3 ms each. Not a cost problem; the langfuse and test databases drop out when 185-45 removes langfuse.
