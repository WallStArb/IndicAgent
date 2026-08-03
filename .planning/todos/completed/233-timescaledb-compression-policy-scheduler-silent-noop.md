# 233 — TimescaleDB compression policy jobs silently no-op via scheduler

**Filed:** 2026-08-02, during a general file/DB cleanup pass.

## What happened

`alpha_events` (job 1068) and `ensemble_alpha` (job 1067) both had `compression_enabled = true`
and an `add_compression_policy` job scheduled every 12h (`compress_after` 30 days), with
`timescaledb_information.job_stats` showing 57/57 successful runs over ~29 days — but **0 of 81
chunks compressed on either table**, despite the vast majority of chunks being years old
(`alpha_events` chunk range: 2006-09 to 2026-09).

A direct `CALL run_job(1068)` / `CALL run_job(1067)` compressed 79/81 and 80/81 chunks
respectively, instantly, with zero errors — same as a manual `compress_chunk()` on one chunk
tested first. So the compression mechanism itself is fine; only the *background-scheduler-
triggered* execution path was a no-op that still reported `last_run_status = 'Success'`.

**Reclaimed by the manual run:** `alpha_events` 5617 MB → 642 MB, `ensemble_alpha` 8709 MB →
864 MB. DB total: 76 GB → 63 GB.

All other hypertables' scheduled compression jobs are working normally (partial compression
counts reflect real recent in-window chunks, e.g. `market_data_ohlcv` 248/250, `feature_vectors`
80/83) — this looks specific to these two (newest job IDs in the table, both from recent
ensemble/alpha work).

## Why this matters

A job reporting `Success` while doing nothing is exactly the "silent wrong answer" CLAUDE.md
warns against — this could recur for any new hypertable's compression policy and nobody would
notice without manually diffing chunk counts, since disk isn't under pressure (15% used) and
nothing errors.

## Root-cause investigation, 2026-08-02 (session 2)

Ruled out, with evidence:

- **Duplicate/conflicting jobs**: `SELECT hypertable_name, count(*) FROM timescaledb_information.jobs
  WHERE proc_name='policy_compression' GROUP BY 1 HAVING count(*)>1` — zero rows. One job per table.
- **Continuous aggregates blocking compression**: none defined on either table.
- **Retention policy interaction**: neither table has a `policy_retention` job.
- **Bad/stale job config** (e.g. `hypertable_id` pointing at a recreated table): the manual
  `CALL run_job(1067/1068)` used the exact same `config` JSON the scheduler would have used and
  it worked — config is valid, ruling out a catalog-id mismatch.
- **`max_background_workers` exhaustion**: 16 workers configured, 41 total scheduled jobs
  spread across staggered `next_start` times — plausible contention in principle, but wouldn't
  explain 57/57 *reported-success* runs; a worker-starved job would be delayed, not falsely
  marked successful.
- **Current lock contention**: `pg_locks`/`pg_stat_activity` show zero locks and zero
  idle-in-transaction backends on either table right now. No live writer process either —
  `alpha_publisher`/`ensemble_trainer` are one-shot ops scripts, not persistent systemd units,
  and none were running at investigation time.
- **Config/pattern difference from a working sibling**: `ensemble_alpha` and `alpha_events`
  were given their compression policy in the *same* migration (193) as `forward_returns`
  (`add_compression_policy('forward_returns', ...)` immediately preceding the other two, same
  `ALTER TABLE ... SET (timescaledb.compress...)` pattern, same segmentby/orderby shape) —
  and `forward_returns`'s job (1066) has been compressing correctly. Identical mechanism,
  identical migration, one works and two don't — rules out "the migration did something wrong,"
  since it did the same thing three times.

**Evidence trail is exhausted, not just inconclusive**: `timescaledb_information.job_history`
returned **zero rows for every job checked, including the known-good ones** (e.g. job 1022,
`market_data_ohlcv`) — this view isn't retaining/recording routine run history in this
environment (default retention or config gap, not investigated further). `docker logs
timescaledb --since 24h | grep -i compress` is also empty. There is no forensic record of what
the 57 failed background-triggered runs actually did internally — job_stats' aggregate
success/failure counters are the only surviving signal, and they don't distinguish "ran and
compressed nothing eligible" from "silently skipped its real work."

**The bug is no longer reproducible against its original targets**: manually compressing the
79-81 backlogged chunks on both tables (done this session) removed the only condition that
exposed the failure — there's no large eligible-but-uncompressed backlog left on either table
to re-test the scheduler against. Any future scheduler test on these two tables would only have
1 chunk (the current window) to work with, and that chunk won't be `compress_after`-eligible for
~30 days.

**"Live natural-experiment" note above was itself wrong — correction, 2026-08-02 (session 3):**
the "2 chunks overdue" claim used a flat 35-day assumption. `feature_vectors`' real policy is
`compress_after = '6 months'` (not 30 days like the other tables) — those 2 chunks aren't
actually due until **2026-09-09** and **2026-12-07**. Checking on 2026-08-03 would have proven
nothing. This mistake is exactly why per-table `compress_after` must be read from each job's own
config, never assumed uniform — which is precisely how the permanent fix below avoids the same
error.

## Permanent fix shipped, 2026-08-02 (session 3) — root cause left open, class of bug closed

Rather than keep chasing an unreproducible scheduler-internals bug with an exhausted evidence
trail (see above), built the structural fix CLAUDE.md's own principles call for: stop trusting
`job_stats.last_run_status` as ground truth at all, and independently verify + self-heal.

**`services/compression_auditor.py` (new `CompressionAuditor(BaseDaemon)`, modeled exactly on
`BarAuditor`'s self-healing-auditor shape):**
- Every 6h (`infra.compression_auditor.check_interval_seconds`), runs one query joining
  `timescaledb_information.jobs` (for each table's own `compress_after`, no hardcoded per-table
  values — this is what would have prevented the `feature_vectors` mistake above) against
  `timescaledb_information.chunks.is_compressed` — ground truth against ground truth, never
  `job_stats`. Generic over every hypertable with a `policy_compression` job, present or future.
- Any hypertable found overdue beyond `compress_after` + `infra.compression_auditor.grace_period_hours`
  (default 24h, comfortably past the 12h policy schedule) gets remediated inline via
  `CALL run_job(job_id)` — the exact call proven safe this session on the real backlog. Pure
  in-DB SQL, no external dependency, so remediation is inline (no Kafka round-trip needed,
  unlike BarAuditor's IBKR-fetch case).
- Each hypertable is its own failure domain in the audit loop (one row's anomaly can't block
  remediation of the others in the same cycle) and the whole cycle never raises (transient
  DB errors retry next cycle, same contract as every other auditor in this codebase).
- Full Golden Signals (D-14) via OTel: `compression_auditor_{audits_run,audit_errors,
  overdue_chunks_found,remediation_runs,remediation_errors}_total`, `..._audit_duration_seconds`.
- Registered in `service_auditor.py`'s `_DAG_ORDER`/`_AGENT_ID_TO_UNIT` (Layer 7, audit tier —
  DB-only, no pipeline dependency beyond TimescaleDB). Systemd unit
  `production/systemd/indicagent-compression-auditor.service`, `alert.lag.compression-auditor`
  + the two `infra.compression_auditor.*` keys seeded via migration 282.
- Tests: `tests/unit/services/test_compression_auditor.py` (7 cases, mocked pool) +
  `tests/integration/test_compression_auditor_drift_query.py` (real DB). The integration test
  exists because the unit suite's mock initially missed a real bug: the grace-period parameter
  was first passed as a Python `str` to an asyncpg `$1::interval`-cast parameter, which a mock
  accepts silently but real asyncpg rejects (`'str' object has no attribute 'days'` — asyncpg's
  interval codec requires `datetime.timedelta`). Caught only by watching the deployed daemon's
  live log, not by the mocked tests — fixed, and the integration test now pins it so this exact
  regression fails CI instead of shipping silently next time.
- **Deployed and confirmed live**: `systemctl status indicagent-compression-auditor` active,
  first audit cycle logged `hypertables_with_drift: 0` with zero errors against the real DB.

**What this does and doesn't resolve:** the underlying scheduler-internals question (why the
TimescaleDB background-worker path specifically no-op'd for these two jobs) is still
undiagnosed — see the ruled-out list and exhausted-evidence-trail section above, unchanged. What
changes is that it no longer matters whether that root cause is ever found: this class of bug
(a policy job silently doing nothing while claiming success) is now caught within 6h and
self-healed automatically for every hypertable in the database, present or future, without
depending on the exact mechanism ever being understood. If the underlying scheduler bug
recurs, `CompressionAuditor`'s own logs/metrics are the evidence trail that was missing this
time — `compression_auditor.overdue_chunks_detected` fires before every remediation attempt.

## Remaining, lower-priority

Root-causing the actual TimescaleDB scheduler behavior (why `CALL run_job()` succeeds where the
background-triggered path didn't) is still open but no longer urgent — the auditor makes it a
research curiosity rather than a live risk. If it resurfaces (via
`compression_auditor.overdue_chunks_detected` firing for some new hypertable), that's the moment
to catch it live with `py-spy`/`pg_stat_activity` monitoring at the exact scheduled `next_start`,
since retroactive analysis has no evidence trail to work with (job_history/postgres logs don't
retain long enough, confirmed above).
