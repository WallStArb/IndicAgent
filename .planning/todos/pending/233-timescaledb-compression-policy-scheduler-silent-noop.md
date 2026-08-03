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

## Next steps (not done in this pass)

1. Root-cause why the TimescaleDB background worker path skips these two jobs specifically —
   check `timescaledb.max_background_workers`, and whether `_timescaledb_internal.bgw_job`
   catalog state differs for job_id 1067/1068 vs the working ones (1015-1066).
2. Decide whether to keep relying on the scheduler after understanding the cause, or add an
   explicit periodic `CALL run_job(...)` (systemd timer or ops script) as a belt-and-suspenders
   check — note systemd timers are otherwise confirmed disabled project-wide as of 2026-07-02,
   so this would be a new exception if chosen.
3. Sweep the rest of the hypertable list periodically (`timescaledb_information.chunks` grouped
   by `hypertable_name, is_compressed`) rather than assuming "Success" job stats mean the job
   actually did anything.
