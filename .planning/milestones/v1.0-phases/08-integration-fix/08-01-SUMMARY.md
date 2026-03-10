---
phase: 08-integration-fix
plan: 01
subsystem: infra
tags: [systemd, timer, weight-updater, cis, logistic-regression]

# Dependency graph
requires:
  - phase: 07-composite-intelligence-score
    provides: weight_updater.py with run_weight_update() entrypoint, cis_weights table (migration 012), signal_ledger CIS columns (migration 011)
provides:
  - systemd timer (daily 02:00, Persistent=true) automating CIS weight learning loop
  - indicagent-weight-updater.service one-shot unit (python -m src.intelligence.weight_updater)
  - indicagent-weight-updater.timer installed and enabled in /etc/systemd/system/
affects: [09-milestone-verification, weight_updater, cis_weights]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Systemd one-shot + timer pair pattern for scheduled Python tasks (mirrors other indicagent services)"
    - "Persistent=true on timer catches missed runs after system downtime"

key-files:
  created:
    - production/systemd/indicagent-weight-updater.service
    - production/systemd/indicagent-weight-updater.timer
  modified:
    - src/intelligence/weight_updater.py  # bug fix: connect→initialize, disconnect→close

key-decisions:
  - "Used Persistent=true on timer so missed 02:00 runs fire on next boot (correct for daily weight learning)"
  - "Service runs as one-shot Type=oneshot — weight_updater is not a daemon, it runs and exits"
  - "DatabaseManager API uses initialize()/close() not connect()/disconnect() — __main__ block corrected"

patterns-established:
  - "Scheduled Python tasks: systemd one-shot service + timer pair, not cron"
  - "Unit files live in production/systemd/ in-repo, copied to /etc/systemd/system/ via sudo"

requirements-completed: []

# Metrics
duration: ~30min (including human-action checkpoint for sudo install)
completed: 2026-02-28
---

# Phase 8 Plan 01: Systemd Timer for CIS Weight Updater Summary

**Wire CIS weight learning loop via systemd timer (daily 02:00, Persistent=true) — closes integration gap where run_weight_update() had no automated trigger**

## Performance

- **Duration:** ~30 min (human-action checkpoint for sudo installation)
- **Started:** 2026-02-28
- **Completed:** 2026-02-28
- **Tasks:** 3
- **Files modified:** 3 (2 created, 1 bug-fixed)

## Accomplishments

- Created `indicagent-weight-updater.service` (Type=oneshot, runs `python -m src.intelligence.weight_updater`)
- Created `indicagent-weight-updater.timer` (OnCalendar=*-*-* 02:00:00, Persistent=true) — CIS adaptive learning now automated daily
- Fixed bug in `weight_updater.py` `__main__` block: `db.connect()`/`db.disconnect()` → `db.initialize()`/`db.close()` (DatabaseManager API)
- Timer installed, enabled, and verified running; service smoke-tested exits 0 with expected "No update needed (insufficient resolved signals)" output
- Migrations 011 and 012 confirmed applied (signal_ledger CIS columns, cis_weights table with bootstrap row)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create service and timer unit files** - `0acde6d` (chore)
2. **Task 2: Install timer into systemd** - (human-action checkpoint — sudo performed by user)
3. **Task 3: Smoke-test service runs without error** - (verified by user; exit 0 confirmed)

**Bug fix commit:** `56346ba` (fix: weight_updater connect→initialize, disconnect→close)

## Files Created/Modified

- `production/systemd/indicagent-weight-updater.service` - Systemd one-shot service unit for CIS weight update job
- `production/systemd/indicagent-weight-updater.timer` - Systemd timer triggering weight updater daily at 02:00
- `src/intelligence/weight_updater.py` - Bug fix: DatabaseManager API correction in `__main__` block

## Decisions Made

- `Persistent=true` on the timer: if system is off at 02:00 (e.g., weekend maintenance), the weight update fires on next boot. This is the correct behavior for a daily learning job — ensures no run is permanently skipped.
- `Type=oneshot` for the service: weight_updater runs to completion and exits; it is not a persistent daemon. This matches the actual semantics of the script.
- Fixed `connect()`/`disconnect()` → `initialize()`/`close()`: DatabaseManager has always used `initialize()`/`close()` (async context manager pattern). The `__main__` block used the wrong method names, which would have caused `AttributeError` at runtime.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed DatabaseManager API calls in weight_updater __main__ block**
- **Found during:** Task 3 (smoke-test)
- **Issue:** `weight_updater.py` `__main__` block called `db.connect()` and `db.disconnect()`, but `DatabaseManager` exposes `initialize()` and `close()`. Would have raised `AttributeError` on every scheduled run.
- **Fix:** Replaced `db.connect()` → `db.initialize()`, `db.disconnect()` → `db.close()` in the `__main__` async block
- **Files modified:** `src/intelligence/weight_updater.py`
- **Verification:** Service ran successfully, exit 0, journal showed "No update needed (insufficient resolved signals)"
- **Committed in:** `56346ba`

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Fix essential for correctness — without it every scheduled run would crash with AttributeError. No scope creep.

## Issues Encountered

- Task 2 required `sudo` for systemd installation — returned as `human-action` checkpoint. User performed sudo steps (copy units to /etc/systemd/system/, daemon-reload, enable + start timer). Timer confirmed enabled with next trigger at 02:00.

## User Setup Required

None beyond what was completed — timer is already installed and enabled in systemd.

## Next Phase Readiness

- CIS weight learning loop is now automated: once 50+ resolved signals accumulate, the daily 02:00 timer will trigger `run_weight_update()` and transition weights from `designed` → `blended` → `learned`
- Phase 8 Plan 02 (backfill SQL CIS columns) already complete (`401c5c7`)
- Phase 8 Plan 03 (remove dead `_persist_intelligence()` from market_analysis_service) is next

---
*Phase: 08-integration-fix*
*Completed: 2026-02-28*
