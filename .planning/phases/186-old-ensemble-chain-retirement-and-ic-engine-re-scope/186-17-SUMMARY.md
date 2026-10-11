---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: "17"
status: COMPLETE
subsystem: database
tags: [postgres, timescaledb, tuning, compose-drift]
requirements-completed: [D-38, R-12]
completed: 2026-10-11 (Tasks 1 and 2)
---

# Phase 186 Plan 17: Postgres tuning Summary

D-38 applied: shared_buffers 3GB -> 7GB, work_mem -> 128MB, shm_size 512m -> 13g, landed by a gated container recreate; zero drift between compose and the running server, versions unchanged, the spill measured gone on the top read-only query.

## Task commits

1. Task 1: `ce1c9686a` chore(186-17): D-38 before measurement (186-17-pg-before.json)
2. Task 2: `29f507735` perf(186-17): tune shared_buffers and work_mem, recreate to fix compose drift (D-38, R-12) (compose edit committed with its apply, per plan rule)
3. Task 2: `a939eb8bf` docs(186-17): D-38 after measurement, settings section and SOP case study (186-17-pg-after.json, operations-database.md settings section, SOP case study)

All three are on local `main` by fast-forward; pushed to origin (see below).

## Task 2 gate output (verbatim, 2026-10-11 01:51 UTC, 21:51 EDT)

PASS. The gate re-ran Task 1's checks plus the extra ones:

- `ps aux` pattern (ic_engine|backfill_feature_factory|regime_writer|cross_sectional_regime|feature_lifecycle|infrastructure_run_historical_pipeline|backfill|scripts/research|src.intelligence.research|rebuild): **zero matches** (the bar_derivation grid run reported by the orchestrator had finished at 01:46 UTC; nothing else live).
- `pg_stat_activity` non-idle indicagent sessions: **0 rows** (no idle-in-transaction either).
- `systemctl list-timers --all | grep indicagent`: next fires in 4h08m (bar-reconciliation-audit and regime-coverage-auditor at 06:00 UTC / 02:00 EDT; dividend 06:30 UTC). No timer within 30 minutes. The old nightly-backfill timer is gone from the list (unscheduled under the pull freeze / 190 cutover).
- Backfill write check: **`backfill_status` no longer exists** (relation dropped since the plan was written). The gate fell back to the process list, which is clean; this is the one gate clause that could not be evaluated as written (deviation below).
- Peak active-backend sample, 1 Hz x 60 s: **max 1**. The Task 1 work_mem bound used peak 3, so 128MB stands with margin (the coordinator's option to lower to 64MB was not needed).
- Host: `free -g` 21 GB available, swap 2 GB used.

Task 1's full gate and formula record is preserved below unchanged.

## Apply and verification (Task 2)

- Compose edit committed in the worktree, rebased onto main (main had moved: ce1c9686a was already an ancestor), ff-merged: main got `29f507735`, and `git show HEAD:production/docker-compose.yml` shows shared_buffers=7GB, work_mem=128MB, shm_size '13g'.
- Pre-apply facts (immediately before the apply, 01:52 UTC): container Created/StartedAt 2026-10-07T16:01:31Z with label `e9609d38...` (the pre-edit compose hash). Running settings: shared_buffers 393216x8kB (3GB), work_mem 65536 kB (64MB) - **an unrelated recreation on 2026-10-07 had already healed the original R-12 work_mem drift (8MB -> 64MB)**; shared_buffers and /dev/shm were still at the old values. Versions PostgreSQL 18.4 / timescaledb 2.27.1 / vector 0.8.2; 15 scheduled jobs.
- Apply: `cd /home/bg/dev/indicagent/production && docker compose up -d --no-deps --no-build timescaledb` at 01:53 UTC. Healthy on the first poll (~10 s). No error/fatal/panic in startup logs. No rollback needed.
- Post-apply verification:
  - `SHOW shared_buffers` = 917504x8kB (7GB); `SHOW work_mem` = 131072 kB (128MB); both `source='command line'`, `pending_restart=f`.
  - `docker exec timescaledb df -h /dev/shm`: 13.0G (was 512M). ShmSize 13958643712.
  - Versions unchanged: PostgreSQL 18.4 (musl), timescaledb 2.27.1, vector 0.8.2. Scheduled jobs 15 = 15.
  - `docker inspect` `.Config.Cmd` = [..., shared_buffers=7GB, work_mem=128MB]; config-hash label `94dab31e...` equals `docker compose -f /home/bg/dev/indicagent/production/docker-compose.yml config --hash timescaledb`.
  - Units: every unit from Task 1's before set still active (api, compression-auditor, dashboard, feature-vector-writer running; redpanda-ready, timescaledb-ready active (exited); wave1-4 + infrastructure targets active; dividend slice active). The only failed unit, `indicagent-dividend-event-writer@yahoo.service`, was already failed before the restart. Nothing restarted.
  - Health reads: SELECT 1 = 1; 1,529 active instruments; max 1d timestamp on market_data_ohlcv_tradeable = 2026-10-09.
  - After baseline (`186-17-pg-after.json`): **zero drift entries**.
- Host after one minute: 21 GB still available, swap 2 GB; timescaledb container 3.621 GiB (the 7GB pool fills lazily), redpanda 138 MiB.

## Before/after EXPLAIN (ANALYZE, BUFFERS)

Same statement, same literals (ic_engine DISTINCT ts on market_regimes, equity/5m/low_bull, ts <= 2025-12-24 05:15Z), warm (second) runs:

| Metric | Before (Task 1, 2026-09-30) | After (2026-10-11) |
|---|---|---|
| HashAggregate batches | 5, Disk 7,392 kB | **1, no disk** |
| Aggregate memory | 16,441 kB | 32,793 kB |
| Temp buffers | read 724, written 1,461 | 0 |
| Shared buffers | hit 8,246, read 122,133 | hit 130,379 |
| Execution time | 315.5 ms | 229.4 ms |

Cumulative `pg_stat_database` temp counters did NOT carry across the restart as the plan expected (68,243 files / 1,151.6 GB before -> 3,281 files / 160.0 GB after, `stats_reset` null in both JSONs): the recreate reset them. Both JSONs are committed, so a later reader can take a delta from the after snapshot; the EXPLAIN pairs above are the actual before/after comparison.

## Task 1 evidence (unchanged from the PARTIAL summary)

Gate (Task 1 pass, recorded only, 2026-09-30): units active before (the before set): api, compression-auditor, dashboard, feature-vector-writer, redpanda-ready, timescaledb-ready, wave1-4 targets, infrastructure target, dividend-event-writer slice; failed before the plan: feature-vector-pipeline, intelligence-pipeline, regime-coverage-auditor (pre-existing).

Drift cause confirmed as 186-05 stated (container never recreated); no extra ALTER SYSTEM or role reset was needed, and the 2026-10-07 recreation confirmed it by healing work_mem without any manual reset.

Formulas and inputs:
- shared_buffers: MemTotal 30,900,336 kB = 29.47 GiB, 25% = 7.37 GiB, rounded down = 7GB. Headroom: MemAvailable 20.4 GiB + current 3 GiB = 23.4 GiB > 7 + 4 = 11. Passes.
- work_mem: bound work_mem x hash_mem_multiplier (2) x (max_parallel_workers_per_gather 12 + 1) x peak active backends (3, max of 60 one-second samples taken during the 449 backfill; re-sampled at 1 in the Task 2 window) < 29.47 - 7 - 8.2 (other containers by `docker stats`, redpanda at its 6 GiB limit) - 4 (reserve) = 10.3 GiB. 78 x work_mem < 10.3 GiB gives work_mem < 135 MB; the largest power of two is 128MB (78 x 128MB = 9.75 GiB). Evidence side: 1,151 GB in 68,243 temp files since reset, mean ~17 MB per file, sampled spiller a 16 MB hash in 5 batches at 8 MB.
- shm_size: A2 held (dynamic_shared_memory_type posix, /dev/shm 512 MB). 128 MB x 2 x 13 x 4 = 13,312 MB, rounded up = 13g (a tmpfs cap, not a reservation).
- effective_cache_size 2,219,520 x 8kB (17 GiB), maintenance_work_mem 2 GB, max_parallel_workers 24, max_parallel_workers_per_gather 12, hash_mem_multiplier 2, other command args unchanged.

Config hash at Task 1: container label `358de008f221e024...`, committed compose `e9609d38b1b2a682...` (differed: the R-12 drift; the baseline compare then reported exactly one drift, work_mem compose 64MB vs running 8MB).

iostat -x 1 30 (nvme0n1, sampled during the backfill): idle, %iowait ~0.55, %util ~1.3, w_await under 1 ms in the excerpted second.

Versions before: PostgreSQL 18.4 (musl), timescaledb 2.27.1, vector 0.8.2; scheduled timescaledb jobs 39 at Task 1 time (15 at Task 2, both before and after the restart - the difference predates this plan and is not a restart effect).

## What was NOT done (out of scope, per plan)

No code change, no per-session SET work_mem wiring, no APR keys, no ALTER SYSTEM, no other container, no migration, no rebuild launch. 186-26/27/28 untouched.

## Deviations from Plan

1. **[Gate clause unevaluable] `backfill_status` no longer exists.** The Task 2 gate's backfill-write check (`SELECT max(completed_at) FROM backfill_status`) errored with "relation does not exist" (the table was dropped since the plan was written). The gate fell back to its primary check, the `ps aux` process list, which was clean; the plan's own R-13 concern (todo 449 backfill) is also moot since the pull freeze holds and no backfill process exists. Not a refusal condition; recorded here.
2. **[Environment change, not plan] The R-12 work_mem drift had already healed before this task ran.** An unrelated container recreation on 2026-10-07 (between Task 1 and Task 2) put the then-committed compose values (work_mem 64MB) on the server. The plan's gate/verify steps all still hold: the apply landed the new values with zero drift and matching hashes, and the docs record the full timeline.
3. **[Plan assumption wrong] Cumulative pg_stat temp counters do not carry across a container recreate** (the plan said a clean restart preserves them). They reset. Both JSONs are committed; the EXPLAIN pairs are the comparison. No action needed.
4. **[Process] Commit `ce1c9686a` (before JSON) had been ff-merged to local main in Task 1 as an interim step**; at Task 2 the branch was rebased onto the moved main and both new commits ff-merged on top, so main's history stays linear. The before JSON commit therefore predates this task's push.

## Push

Local main (2b93422ef + the three commits above) pushed to origin main after the final commit, per the session instruction. CI is the backstop.

## Self-Check: PASSED

- 186-17-pg-before.json and 186-17-pg-after.json exist and parse; after has zero drift entries.
- Commits ce1c9686a, 29f507735, a939eb8bf on main; `git log -1 -- production/docker-compose.yml` = the perf commit; `git diff HEAD -- production/docker-compose.yml` empty.
- `SHOW shared_buffers`/`SHOW work_mem` = compose values from command line, pending_restart f; /dev/shm 13.0G; versions unchanged; config-hash label equals `docker compose config --hash`.
- `grep -c "Postgres settings (D-38" docs/operations/operations-database.md` = 1.
- Every unit active before the restart is active after; nothing restarted.
- Worktree removed and branch deleted after the merge (plan's final step).
