---
phase: 31-cis-learning-loop-signal-feature-snapshots
plan: 01
subsystem: database, intelligence
tags: [timescaledb, cis, signal-generator, weight-learning, hypertable, tdd]

# Dependency graph
requires:
  - phase: 30
    provides: signal_generator_service with perf_weights_refresh_loop pattern
  - phase: migration-012
    provides: cis_weights table with bootstrap seed row
provides:
  - Migration 034 with cis_weights asset_cluster extension, signal_features hypertable, signal_ledger is_shadow column
  - CISScorer.update_weights() method for runtime weight hot-swap
  - Signal generator _cis_weights_refresh_loop loading learned weights from DB every 30 min
affects:
  - Phase 32 (stop architecture — needs cis_weights schema stable)
  - Phase 33 (new I7 plugins — all fire into signal_features hypertable)
  - Phase 35 (Kalman/calibration — builds on CISScorer.update_weights() pattern)
  - weight_updater.py (now inserts into sample_size column)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Background refresh loop pattern: asyncio.wait_for(shutdown_event, timeout=N) for periodic DB reads"
    - "update_weights() on CISScorer: GIL protects dict/array assignment, no asyncio.Lock needed"
    - "TimescaleDB hypertable PK must include partitioning column (computed_at)"

key-files:
  created:
    - production/migrations/034_cis_learning_loop.sql
    - tests/unit/service_tests/test_signal_generator_weights.py
  modified:
    - src/intelligence/trading/cis_scorer.py
    - services/signal_generator_service.py
    - src/intelligence/weight_updater.py
    - tests/unit/intelligence/test_cis_scorer.py

key-decisions:
  - "TimescaleDB hypertable PK for signal_features uses (signal_id, feature_name, computed_at) not (signal_id, feature_name) — partitioning column must be part of any unique constraint"
  - "Renamed cis_weights.n_training_samples to sample_size to align with setup_performance convention and enable sample_size >= 100 filter"
  - "_load_cis_weights_from_db uses DISTINCT ON (asset_cluster, timeframe) ORDER BY version DESC to select latest version per cluster"
  - "_cis_scorer on service holds the runtime scorer; aggregator.aggregate() still creates its own CISScorer() per call — Phase 35 will pass the service scorer to aggregate()"

patterns-established:
  - "CIS weight hot-swap: update_weights() mutates _weights, _weights_version, _weights_array atomically"
  - "30-min DB refresh loop: mirrors _perf_weights_refresh_loop, added to tasks list in start()"

requirements-completed:
  - LEARN-01
  - LEARN-03

# Metrics
duration: 7min
completed: 2026-03-17
---

# Phase 31 Plan 01: CIS Learning Loop Schema Foundation + Runtime Weight Loader Summary

**Migration 034 applied (asset_cluster, signal_features hypertable, is_shadow) and CISScorer wired to load learned weights from DB every 30 minutes, closing the largest single alpha leak in the system.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-03-17T01:11:53Z
- **Completed:** 2026-03-17T01:25:35Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Migration 034 applied: cis_weights gains asset_cluster + new unique index; signal_features hypertable created with 7-day chunks; signal_ledger gains is_shadow column with partial index
- CISScorer.update_weights() added — atomically updates weights dict, version, and numpy array; 3 TDD unit tests pass
- Signal generator now loads learned CIS weights from DB at startup and every 30 minutes; bootstrap fallback preserved; 3 TDD unit tests pass

## Task Commits

1. **Task 1: Migration 034 schema foundation** - `c5ccb3f` (feat)
2. **Task 2: CISScorer.update_weights() + unit tests** - `2ce0a6e` (feat)
3. **Task 3: 30-min CIS weight refresh loop** - `bfbf98e` (feat)

## Files Created/Modified

- `production/migrations/034_cis_learning_loop.sql` — Three-section migration: cis_weights cluster extension, signal_features hypertable, signal_ledger is_shadow
- `src/intelligence/trading/cis_scorer.py` — Added update_weights() method after __init__
- `tests/unit/intelligence/test_cis_scorer.py` — Added TestUpdateWeights class with 3 tests
- `services/signal_generator_service.py` — Added _cis_scorer, _cis_weights_cache, _load_cis_weights_from_db(), _cis_weights_refresh_loop(); startup call + task registration
- `src/intelligence/weight_updater.py` — Updated INSERT to use renamed sample_size column
- `tests/unit/service_tests/test_signal_generator_weights.py` — 3 new unit tests for DB weight load

## Decisions Made

- **signal_features PK includes computed_at**: TimescaleDB requires the partitioning column in any unique constraint. Plan spec said `PRIMARY KEY (signal_id, feature_name)` which fails on hypertables. Fixed to `(signal_id, feature_name, computed_at)`.
- **Renamed n_training_samples to sample_size**: Aligns with setup_performance naming convention; required for Task 3 SQL to use `sample_size >= 100` as stated in acceptance criteria. Updated weight_updater.py INSERT accordingly.
- **_cis_scorer not yet passed to aggregate()**: The aggregator still creates `CISScorer()` per call. The service scorer is maintained and updated but the learned weights don't yet flow into the hot path. Phase 35 will pass the scorer to aggregate(). This is intentional scoping per the plan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed signal_features PRIMARY KEY to include computed_at**
- **Found during:** Task 1 (Migration 034)
- **Issue:** Plan specified `PRIMARY KEY (signal_id, feature_name)` but TimescaleDB hypertables require the partitioning column (`computed_at`) in any unique constraint. First migration run produced: `ERROR: cannot create a unique index without the column "computed_at"`
- **Fix:** Changed PK to `(signal_id, feature_name, computed_at)`; added explanatory comment
- **Files modified:** production/migrations/034_cis_learning_loop.sql
- **Verification:** Migration applied cleanly; hypertable appears in timescaledb_information.hypertables
- **Committed in:** c5ccb3f (Task 1 commit)

**2. [Rule 1 - Bug] Renamed n_training_samples to sample_size + updated weight_updater.py**
- **Found during:** Task 1 (reviewing Task 3 SQL requirements) + Task 3 implementation
- **Issue:** cis_weights table had `n_training_samples`; Task 3's acceptance criteria require `sample_size >= 100` in the SQL query. Column names must match.
- **Fix:** Added `RENAME COLUMN n_training_samples TO sample_size` to migration 034 (with idempotent DO block); updated weight_updater.py INSERT to reference `sample_size`
- **Files modified:** production/migrations/034_cis_learning_loop.sql, src/intelligence/weight_updater.py
- **Verification:** `\d cis_weights` shows `sample_size` column; weight_updater INSERT uses correct name
- **Committed in:** c5ccb3f (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — correctness bugs)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep.

## Issues Encountered

- None beyond the two auto-fixed deviations above.

## Next Phase Readiness

- Migration 034 applied — all Phase 31 downstream plans (031-02 signal_features writer, 031-03 weight learner upgrade) can proceed
- CISScorer.update_weights() is ready for Phase 35 to pass the service scorer into aggregate()
- signal_features hypertable is empty until 031-02 implements the writer
- is_shadow column ready for shadow-mode infrastructure in later plans

---
*Phase: 31-cis-learning-loop-signal-feature-snapshots*
*Completed: 2026-03-17*

## Self-Check: PASSED

- production/migrations/034_cis_learning_loop.sql: FOUND
- src/intelligence/trading/cis_scorer.py: FOUND
- services/signal_generator_service.py: FOUND
- tests/unit/service_tests/test_signal_generator_weights.py: FOUND
- Commit c5ccb3f: FOUND
- Commit 2ce0a6e: FOUND
- Commit bfbf98e: FOUND
