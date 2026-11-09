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

## Applied 2026-11-01 (the exporter half; the timeout stays deferred)

Before (pg_stat_statements, reset 2026-10-10): the `pg_stat_all_tables` scrape query was
first at 263.7 minutes over 18,608 calls (850 ms mean) of 1,513.5 total; `pg_database_size`
50.4 minutes over 611,599 calls.

Change (config only, no restart of anything the rebuild touches): the 15 s
`indicagent-postgres-exporter` now runs `--no-collector.stat_user_tables` (statio was already
off), and a second container `indicagent-postgres-exporter-tables` carries the per-table
collector at a 5-minute scrape (prometheus job `postgres-tables`). The DeadTupleRatioHigh
alert reads the same metric names from the slow job; `for` loosened 10m to 5m so one scrape
interval keeps it meaningful. Applied with `docker compose up -d --no-deps` on the two
exporters only (timescaledb untouched, still up 3 weeks), prometheus and alertmanager
restarted, statement stats reset 2026-10-31 22:47 UTC just before the switch.

After (75 minutes of window): the scrape query ran 8 times (the 5-minute cadence), 0.06
minutes total, 469 ms mean; `pg_database_size` 0.01 minutes; total statement time in the
window 0.2 minutes. Extrapolated the table walk drops from about 287 to about 8 minutes per
day, and DeadTupleRatioHigh still evaluates (health ok, 1,269 dead-tup series in prometheus,
all five targets up).

Still deferred, unchanged from the incident note: the `idle_in_transaction_session_timeout`
cut. The rebuild's workers legitimately idle in transaction for their whole compute, so the
5-10 minute value would kill them; the sequence is rebuild finishes, compression re-enabled,
the rebuild's read pattern fixed, then the timeout. Note the timeout is reloadable
(PGC_USERSET), so no restart is needed when that sequence completes; the done-when's
compose-managed requirement still applies at that point.

## After-window confirmed 2026-11-01 13:35 UTC (~15 h since the 22:47 UTC reset; research lane, read-only)

Verified live, not re-derived from the apply note: both exporters up 12 h with the intended flags
(fast job `--no-collector.statio_user_tables --no-collector.stat_user_tables`, tables job carries
the per-table collector); prometheus has all five targets up, `postgres-tables` last scrape
2.3 ms, and 1,269 `pg_stat_user_tables_n_live_tup` series on the slow job, so DeadTupleRatioHigh
still evaluates. pg_stat_statements over the ~15 h window: total 57.5 minutes, dominated by the
rebuild's own reads (top statement 8.4 min is the tradeable-view read) and coverage writes; the
exporter's per-table query is 0.98 minutes over 150 calls (the 5-minute cadence, ~390 ms mean),
out of the top 5 entirely. Extrapolated exporter cost holds at roughly 1.6 minutes per day
against 305 minutes in the three days before the switch. The exporter half of the done-when is
met; leave pg_stat_statements un-reset so the rebuild window keeps its record.

The timeout half stays deferred, unchanged: `idle_in_transaction_session_timeout` is 1h and
there are 8 sessions idle in transaction RIGHT NOW, all the rebuild's compute-spanning reads; a
5-10 minute value would terminate them mid-compute. The incident note's sequence stands (rebuild
finishes, compression re-enabled, the rebuild's read pattern fixed, then the timeout; it is
PGC_USERSET, reloadable, no restart needed at that point). The compose-managed requirement
applies when that lands.

## Status 2026-11-05 (lead indicagent-4d)

Compression jobs 1078 (market_data_ohlcv) and 1076 (ohlcv_raw) re-enabled: the 186-26 rebuild
whose idle-in-transaction reads caused the stall is discarded (migration 569), and no
idle-in-transaction holder was present. First runs deferred 3 h past the manual D7 audit (next_start
2026-11-05 15:33Z and 15:48Z). Five chunks (about 5.7 GB) were uncompressed. Job 1065 left with the
dropped v1 feature_vectors. Still open here: the exporter scrape cost and the idle-in-transaction
timeout; the rerun plan (186-31) owns the rebuild read pattern.

2026-11-09 vehicle note (lead indicagent-d8): the 186-26 rebuild is superseded by the 186-30/31 corpus rerun at the new pin (rows discarded, migration 569). Sequence the timeout cut after the rerun ends (its compute workers legitimately idle in transaction).
