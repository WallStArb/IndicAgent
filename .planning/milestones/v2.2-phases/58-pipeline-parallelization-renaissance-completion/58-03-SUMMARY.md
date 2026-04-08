---
phase: 58-pipeline-parallelization-renaissance-completion
plan: 03
subsystem: infra
tags: [systemd, prometheus, thread-pool, benchmark, intelligence-pipeline]

# Dependency graph
requires:
  - phase: 58-01
    provides: LOG_FILE env var reading, pipeline_metrics_port via Settings, INTELLIGENCE_THREAD_POOL_WORKERS config
provides:
  - Thread pool throughput benchmark script at 5 pool sizes (28/48/64/96/128)
  - Systemd template unit indicagent-intelligence-pipeline@.service with %i parameterization
  - Old single-instance indicagent-intelligence-pipeline.service stopped and disabled
  - Instance @1 running, serving Prometheus metrics on port 9125, logging to logs/intelligence_pipeline_1.log
affects:
  - phase-58-04 (worker count tuning guided by benchmark CSV output)
  - ops-runbooks (systemctl commands now use @N syntax)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Systemd template unit (@.service) for horizontal scaling readiness without code changes"
    - "Instance-specific log files via LOG_FILE=logs/intelligence_pipeline_%i.log env var"
    - "asyncio.gather + run_in_executor benchmark pattern for GIL-bound thread pool sizing"

key-files:
  created:
    - production/scripts/benchmark_thread_pool.py
    - production/systemd/indicagent-intelligence-pipeline@.service
  modified:
    - production/scripts/README_PROFILING.md
    - /etc/systemd/system/indicagent-intelligence-pipeline@.service (installed)

key-decisions:
  - "METRICS_PORT=9125 hardcoded in template unit (not computed from %i) — locked decision from CONTEXT.md; single-port design avoids firewall/prometheus config proliferation"
  - "Consumer group stays intelligence_pipeline_consumer (shared) — Kafka partition distribution handles load automatically across instances"
  - "Old production/systemd/indicagent-intelligence-pipeline.service archived (renamed _archived_) to prevent confusion with template"
  - "INSTANCE_ID=%i passed as env var for future use — zero cost, enables downstream observability labeling"

patterns-established:
  - "Template unit pattern: Description includes (instance %i), SyslogIdentifier includes @%i, LOG_FILE uses %i — full instance-specific observability without port multiplication"

requirements-completed: [PIPE-03, PIPE-06]

# Metrics
duration: 45min
completed: 2026-04-01
---

# Phase 58 Plan 03: Thread Pool Benchmark + Systemd Template Unit Summary

**Thread pool throughput benchmark at 5 pool sizes and systemd template unit enabling horizontal intelligence pipeline scaling via `indicagent-intelligence-pipeline@1.service`**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-04-01T00:00:00Z
- **Completed:** 2026-04-01T00:45:00Z
- **Tasks:** 3 (2 auto + 1 human-verify checkpoint)
- **Files modified:** 4

## Accomplishments

- Created `production/scripts/benchmark_thread_pool.py` — synthetic asyncio+ThreadPoolExecutor throughput test across pool sizes [28, 48, 64, 96, 128] matching TIER_I1's 27-plugin count; produces CSV to stdout for easy analysis
- Converted single-instance systemd unit to template unit (`indicagent-intelligence-pipeline@.service`) with full %i parameterization for INSTANCE_ID, LOG_FILE, and SyslogIdentifier
- Transitioned live system: old `indicagent-intelligence-pipeline.service` stopped/disabled, `@1` instance active and serving Prometheus metrics on port 9125 with `logs/intelligence_pipeline_1.log` being written

## Task Commits

Each task was committed atomically:

1. **Task 1: Create thread pool benchmark script and update profiling docs** - `c360adf` (feat)
2. **Task 2: Create systemd template unit and update reference file** - `54c9791` (feat)
3. **Task 3: Install template unit and verify service starts as @1 instance** - human-verify checkpoint (approved)

## Files Created/Modified

- `production/scripts/benchmark_thread_pool.py` — asyncio benchmark: 5 pool sizes, 27 synthetic plugins, 200 bars, 1ms sleep per plugin; CSV output + summary table
- `production/scripts/README_PROFILING.md` — appended Thread Pool Benchmark section with run instructions and interpretation guide
- `production/systemd/indicagent-intelligence-pipeline@.service` — template unit with Environment=METRICS_PORT=9125, INSTANCE_ID=%i, LOG_FILE=logs/intelligence_pipeline_%i.log
- `production/systemd/_archived_indicagent-intelligence-pipeline.service` — old single-instance unit archived
- `/etc/systemd/system/indicagent-intelligence-pipeline@.service` — installed on live system

## Decisions Made

- METRICS_PORT=9125 hardcoded in template (not derived from %i) — per CONTEXT.md locked decision; avoids firewall/Prometheus config proliferation when scaling
- Shared consumer group `intelligence_pipeline_consumer` across instances — Kafka partition distribution handles load; no per-instance group needed
- `_archived_` prefix on old reference unit (not deleted) — preserves record of pre-template configuration

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. The @1 instance was installed and verified as part of the checkpoint.

## Next Phase Readiness

- Benchmark script ready to run: `.venv/bin/python production/scripts/benchmark_thread_pool.py > benchmark_results.csv`
- Optimal `INTELLIGENCE_THREAD_POOL_WORKERS` can be set in `.env` based on benchmark output
- Template unit ready for @2, @3 instances — just `sudo systemctl enable --now indicagent-intelligence-pipeline@2` (requires METRICS_PORT multiplexing design if multiple instances share port 9125)
- PIPE-03 and PIPE-06 requirements closed

## Self-Check: PASSED

- production/scripts/benchmark_thread_pool.py: FOUND
- production/systemd/indicagent-intelligence-pipeline@.service: FOUND
- .planning/phases/58-pipeline-parallelization-renaissance-completion/58-03-SUMMARY.md: FOUND
- Commit c360adf (Task 1): FOUND
- Commit 54c9791 (Task 2): FOUND

---
*Phase: 58-pipeline-parallelization-renaissance-completion*
*Completed: 2026-04-01*
