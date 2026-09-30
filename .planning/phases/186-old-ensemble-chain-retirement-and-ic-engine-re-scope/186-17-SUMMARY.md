---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: "17"
status: PARTIAL
subsystem: database
tags: [postgres, timescaledb, tuning, compose-drift]
requirements-completed: []
completed: 2026-09-30 (Task 1 only)
---

# Phase 186 Plan 17: Postgres tuning Summary (PARTIAL)

Task 1 complete (gate, target values, before measurement, compose edit prepared). Task 2 refused by its own gate: a todo 449 IBKR backfill is live. Nothing was restarted or applied; the timescaledb container StartedAt is still 2026-09-24T10:42:17.882531394Z. The ROADMAP checkbox for 186-17 is not ticked.

## Task commits

1. Task 1: `ce1c9686a` chore(186-17): D-38 before measurement (186-17-pg-before.json), fast-forwarded onto local main. Not pushed.

The compose edit is NOT committed. It sits uncommitted in the worktree `/home/bg/dev/indicagent-wt/186-17` (branch `gsd/186-17-pg-tuning`), because the plan commits it in the same step as its apply.

## Task 2 gate output (verbatim, 2026-09-30 02:33:08 UTC, 22:33 EDT)

Refused: "186-17 Task 2 refused: todo 449 backfill (pids 3688015 intraday_chain.sh, 3688017 and 3868826 intraday_htf_lane.sh, 3863894 and 3868825 infrastructure_run_historical_pipeline.py) is live; rerun after it finishes".

```
bg 3688015 bash logs/backfill_ops/intraday_chain.sh
bg 3688017 /bin/bash logs/backfill_ops/intraday_htf_lane.sh htf_all 46 logs/backfill_ops/intraday_htf/all.symbols
bg 3863894 .venv/bin/python .../infrastructure_run_historical_pipeline.py --symbols AMPH...
bg 3868825 .venv/bin/python -u .../infrastructure_run_historical_pipeline.py --dimension backfill --timeframes 1h,15m --real-bars-only ...
bg 3868826 /bin/bash logs/backfill_ops/intraday_htf_lane.sh htf_all 46 ...

pg_stat_activity (non-idle):
 686415 | lease:ibkr_history_stream:bulk:historical-pipeline:46 | active | 00:10:16 | SELECT pg_advisory_lock($1)
 688445 | lease:ibkr_history_stream:bulk:historical-pipeline:46 | active | 00:08:37 | SELECT pg_advisory_lock($1)

max(backfill_status.completed_at) = 2026-09-25 05:15:15+00 (4 d 21 h ago; the 449 lane writes elsewhere or is waiting on the lease)
timers: nightly-backfill 01:00 EDT (in ~2h27m, inside the 30 min rule only near that time), regime-coverage-auditor 02:00 EDT, dividend-event-writer-yahoo 02:30 EDT
```

The process test alone refuses. Idle-in-transaction sessions: none listed. The gate was not retried in a loop and no process or backend was touched.

## Task 1 evidence

Gate (Task 1 pass, recorded only): same processes as above; units active before (the before set): api, compression-auditor, dashboard, feature-vector-writer, lineage-writer, redpanda-ready, timescaledb-ready, wave1-4 targets, infrastructure target, dividend-event-writer slice; failed before the plan: feature-vector-pipeline, intelligence-pipeline, regime-coverage-auditor (pre-existing). Timers as listed above.

Drift cause confirmed as 186-05 stated (container never recreated); no extra ALTER SYSTEM or role reset is needed.

Formulas and inputs:
- shared_buffers: MemTotal 30,900,336 kB = 29.47 GiB, 25% = 7.37 GiB, rounded down = 7GB. Headroom: MemAvailable 20.4 GiB + current 3 GiB = 23.4 GiB > 7 + 4 = 11. Passes.
- work_mem: bound work_mem x hash_mem_multiplier (2) x (max_parallel_workers_per_gather 12 + 1) x peak active backends (3, max of 60 one-second samples, taken during the 449 backfill) < 29.47 - 7 (shared_buffers) - 8.2 (other containers by `docker stats`: ib-gateway 1.0, prometheus 0.53, grafana 0.16, exporter 0.13, loki 0.09, ssfi 0.08, otel 0.07, tempo 0.05, alertmanager 0.04, node-exporter 0.02, plus redpanda at its 6 GiB limit) - 4 (reserve) = 10.3 GiB. 78 x work_mem < 10.3 GiB gives work_mem < 135 MB; the largest power of two is 128MB (78 x 128 MB = 9.75 GiB). Evidence side: 1,151 GB in 68,243 temp files since reset, mean about 17 MB per file, and the sampled spiller shows a 16 MB hash needing 5 batches at 8 MB. The peak-backend sample of 3 is thin (taken with only the backfill running); the 128MB bound would tighten to 64MB if the sampled peak were 6 or more, so the coordinator can lower it at apply time if a busier window is seen.
- shm_size: A2 held (dynamic_shared_memory_type posix, /dev/shm 512 MB). 128 MB x 2 x 13 x 4 = 13,312 MB, rounded up = 13g (a tmpfs cap, not a reservation).
- effective_cache_size 2,219,520 x 8kB (17 GiB), maintenance_work_mem 2 GB, max_parallel_workers 24, max_parallel_workers_per_gather 12, hash_mem_multiplier 2, other command args unchanged.

Versions before: PostgreSQL 18.4 (musl), timescaledb 2.27.1, vector 0.8.2; scheduled timescaledb jobs 39; image sha256:2d9d08557f6e.

Config hash: container label `358de008f221e024...`, `docker compose config --hash timescaledb` (committed compose, before the edit) `e9609d38b1b2a682...`. They differ: the R-12 drift, as stated in 186-05. The baseline compare reports exactly one drift, `work_mem` (compose 64MB, running 8MB); shared_buffers 3GB matches before the edit.

iostat -x 1 30 (nvme0n1, sampled during the backfill): idle, %iowait about 0.55, %util about 1.3, w_await under 1 ms in the excerpted second (full file not committed).

Cumulative counters: hit ratio 98.59%, 68,243 temp files, 1,151.6 GB temp bytes.

EXPLAIN (ANALYZE, BUFFERS) of the one usable SELECT (the ic_engine DISTINCT ts query on market_regimes, equity/5m/low_bull, ts <= 2025-12-24 05:15Z, the 186-05 literals). Only one spiller exists in pg_stat_statements that is a SELECT-shaped read; the other top entry is the Timescale compression policy CALL (not read-only, skipped). Warm run (second): HashAggregate, Batches 5, Memory 16,441 kB, Disk 7,392 kB, temp read 724 written 1,461 blocks, shared hit 8,246 read 122,133, execution 315.5 ms (cold run 932 ms). The after run must be compared with this.

Compose edit (uncommitted, worktree only): `shared_buffers=3GB` -> `7GB`, `work_mem=64MB` -> `128MB`, `shm_size '512m'` -> `'13g'`, plus a D-38 comment block above `command:` with the formulas and the recreate rule. `docker compose config --quiet` exits 0.

## What remains (Task 2)

Everything in Task 2: re-run the gate, commit the compose edit, ff-merge, `cd /home/bg/dev/indicagent/production && docker compose up -d --no-deps --no-build timescaledb`, verify settings, config-hash label, versions, units, run the baseline script to `186-17-pg-after.json` (zero drift), re-run the warm EXPLAIN, write the "Postgres settings (D-38, phase 186)" section in `docs/operations/operations-database.md` and the SOP case study, remove the worktree and branch.

Unblock condition: no todo 449 backfill process or lease-holding session (lanes between runs or 449 finished), no research or rebuild run, no non-idle or open-transaction session, and no indicagent timer within 30 minutes (timers 05:00, 06:00, 06:30 UTC). Recheck the peak-active-backend sample in that window before fixing work_mem at 128MB.

## Deviations from Plan

- The plan's fallback for "fewer than one pure SELECT among the top 20" found only the compression policy CALL; the 186-05 ic_engine DISTINCT ts query (a SELECT) was used instead. Only one statement instead of up to three.
- Commit `ce1c9686a` landed on local main by fast-forward as an interim step (only the before JSON); the plan otherwise merges at Task 2.

## Self-Check: PASSED

before.json exists and parses, commit ce1c9686a on main, StartedAt unchanged, worktree holds the uncommitted compose edit.
