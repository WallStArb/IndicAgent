---
phase: 039-data-quality-db-health
plan: "04"
subsystem: infra
tags: [gap-fill, ibkr, market-data, asyncpg, prometheus, systemd, RTH]

requires:
  - phase: 039-01
    provides: signal_ledger schema hardening (signal integrity foundation)

provides:
  - Self-healing gap-fill service detecting missing 1m RTH bars per symbol
  - IBKR fetch for missing windows with ON CONFLICT DO NOTHING idempotency
  - Prometheus counters for gaps detected, bars fetched, fetch failures
  - systemd oneshot service + daily timer at 09:20 ET (13:20 UTC)

affects:
  - phase-040-machine-hardening (cleaner training data foundation)
  - phase-046-ml-model (gap-free market_data_ohlcv improves ML training quality)

tech-stack:
  added: []
  patterns:
    - "Gap detection: generate expected RTH timestamps, query actuals, diff for missing"
    - "systemd oneshot + timer pattern for daily maintenance jobs (not Restart=always)"
    - "asyncpg executemany with Python datetime objects for timestamptz columns"

key-files:
  created:
    - services/gap_fill_service.py
    - production/systemd/indicagent-gap-fill.service
    - production/systemd/indicagent-gap-fill.timer
    - tests/unit/service_tests/test_gap_fill_service.py
  modified: []

key-decisions:
  - "Type=oneshot (not simple) for systemd — gap-fill runs once and exits, timer handles scheduling"
  - "Pure function design for generate_rth_timestamps() and detect_gaps() — unit-testable without I/O"
  - "Group consecutive missing timestamps into contiguous windows to minimize IBKR API calls"
  - "CRITICAL_GAP_THRESHOLD=30 fires logger.critical() for systemic failure detection"
  - "Fixed UTC time (13:20) for timer — 09:20 EDT in summer, 08:20 EST in winter, both pre-market"

patterns-established:
  - "RTH window generation: iterate ET datetimes, convert to UTC — handles DST automatically via zoneinfo"
  - "Gap detection: pure set difference, no DB in hot path — testable with date fixtures"

requirements-completed:
  - DATA-05

duration: 4min
completed: 2026-03-19
---

# Phase 039 Plan 04: Gap-Fill Service Summary

**Self-healing gap-fill service detecting missing 1m RTH bars via asyncpg set-diff, fetching from IBKR, inserting with ON CONFLICT DO NOTHING; scheduled daily at 09:20 ET via systemd timer**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-19T23:03:05Z
- **Completed:** 2026-03-19T23:06:27Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- `generate_rth_timestamps()` produces exactly 390 UTC-aware 1m timestamps per RTH weekday session
- `detect_gaps()` diffs expected vs actual bar timestamps — pure function, no I/O
- `fill_gaps_for_symbol()` loops lookback days, groups missing timestamps into contiguous windows, fetches from IBKR, inserts with `ON CONFLICT DO NOTHING`
- Prometheus counters on port 9119 track gaps detected, bars fetched, and fetch failures per symbol
- `CRITICAL_GAP_THRESHOLD = 30` triggers `logger.critical()` for systemic failure alerting
- systemd `indicagent-gap-fill.service` (`Type=oneshot`) + `indicagent-gap-fill.timer` (daily 13:20 UTC, `Persistent=true`)
- 14 unit tests covering RTH window, DST handling, gap detection edge cases

## Task Commits

Each task was committed atomically:

1. **Task 1: Gap-fill service and unit tests** - `4fe0d35` (feat)
2. **Task 2: systemd unit and timer** - `90b3ccb` (feat)

## Files Created/Modified

- `services/gap_fill_service.py` - Gap-fill service: RTH detection, IBKR fetch, asyncpg insert, Prometheus metrics
- `tests/unit/service_tests/test_gap_fill_service.py` - 14 unit tests for pure functions
- `production/systemd/indicagent-gap-fill.service` - oneshot systemd service
- `production/systemd/indicagent-gap-fill.timer` - daily 09:20 ET timer with install instructions

## Decisions Made

- `Type=oneshot` for systemd service — gap-fill runs once and exits; `Restart=always` is wrong for batch jobs (timer handles re-scheduling)
- Pure-function design (`generate_rth_timestamps`, `detect_gaps`) enables fast, dependency-free unit testing
- Window grouping in `fetch_bars_from_ibkr()` collapses consecutive missing timestamps into contiguous ranges to minimize IBKR API round trips
- Timer uses fixed UTC time (13:20) since zoneinfo DST handling is in the service Python code, not the timer spec

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused imports caught by pre-commit hook**
- **Found during:** Task 1 commit
- **Issue:** Pre-commit hook detected unused `datetime`, `pytest`, and `timezone` imports in the test file
- **Fix:** Removed `datetime`, `pytest` from imports; removed unused `UTC = timezone.utc` constant and its import
- **Files modified:** `tests/unit/service_tests/test_gap_fill_service.py`
- **Verification:** Ruff passed, 14 tests still pass
- **Committed in:** `4fe0d35` (amended before final commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — import cleanup caught by pre-commit)
**Impact on plan:** No scope change. Pre-commit hook correctly caught dead code.

## Issues Encountered

- `git index.lock` transient error on Task 2 commit — resolved by retrying (lock had already been released)

## User Setup Required

To activate the timer:

```bash
sudo cp production/systemd/indicagent-gap-fill.service /etc/systemd/system/
sudo cp production/systemd/indicagent-gap-fill.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now indicagent-gap-fill.timer
```

Verify: `systemctl list-timers | grep gap-fill`

Manual dry-run: `.venv/bin/python services/gap_fill_service.py --dry-run --lookback-days 5`

## Next Phase Readiness

- Gap-fill service is production-ready but not yet enabled via systemd (requires sudo install)
- market_data_ohlcv completeness improved automatically each morning before RTH open
- Phase 040 (Machine Hardening) benefits from cleaner training data

---
*Phase: 039-data-quality-db-health*
*Completed: 2026-03-19*
