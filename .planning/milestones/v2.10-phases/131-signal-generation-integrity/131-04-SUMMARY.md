---
phase: 131-signal-generation-integrity
plan: "04"
subsystem: intelligence-pipeline
tags: [ctf, i6-confluence, replay, feature-pipeline-executor, cold-start, a7-fix]

requires:
  - phase: 131-01
    provides: A7 root cause diagnosis — ctf_score=0.0 because _last_events empty on bar 1
  - phase: 131-03
    provides: Wave 2 A4 fix already applied — executor and signal processor hardened

provides:
  - "_seed_last_events_from_db() async method on FeaturePipelineExecutor for live executor path"
  - "intelligence_cache DB seed in replay_symbol() for replay path"
  - "--no-seed CLI flag for regression testing the unseeded path"
  - "Unit tests: happy path + cold-start + multi-pair parallel gather"

affects:
  - "133-clean-corpus-rebuild: ctf_score will be non-zero after this fix on full rebuild"
  - "132-stop-zone-geometry-apr-migration: any replay invocations benefit from seed"

tech-stack:
  added: []
  patterns:
    - "Live path: FeaturePipelineExecutor._seed_last_events_from_db() uses asyncio.gather() for parallel (symbol, tf) seed queries"
    - "Replay path: replay_symbol() seeds intelligence_cache from psycopg2 cursor with cur.description column mapping"
    - "Cold-start safe: both seed paths handle empty intelligence_features without raising"

key-files:
  created:
    - "tests/unit/pipeline/test_feature_pipeline_executor_seed.py"
  modified:
    - "src/intelligence/pipeline/feature_pipeline_executor.py"
    - "production/scripts/run_historical_pipeline.py"
    - "tests/unit/scripts/test_run_historical_pipeline.py"

key-decisions:
  - "Live executor and replay use separate seed mechanisms: async _seed_last_events_from_db() for live (asyncpg pool), synchronous cursor loop for replay (psycopg2)"
  - "Seed only I3 trend fields (trend_direction, trend_strength, trend_duration_bars) — the only fields extract_trend_sign() reads; all other tier fields default to None"
  - "Seed builds a valid minimal IntelligenceEvent (all required tier fields present as empty instances) rather than storing a raw dict — preserves model_dump() contract used by cross-tf frame assembly"
  - "seed_from_db=True is the default; --no-seed flag enables before/after ctf_score distribution comparison"

patterns-established:
  - "Intelligence cache cold-start seed: always populate before bar event loop, never assume cache is warm"

requirements-completed:
  - "D-03"

duration: 25min
completed: 2026-06-17
---

# Phase 131 Plan 04: A7 Cold-Start CTF Seed Summary

**DB seed of I3 trend fields into intelligence_cache/\_last_events before bar 1, fixing ctf_score=0.0 across 537K signals by giving I6 non-None trend context on the first bar of every symbol/timeframe.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-06-17T13:38:00Z
- **Completed:** 2026-06-17T14:05:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Added `_seed_last_events_from_db()` async method to `FeaturePipelineExecutor` using `asyncio.gather()` for parallel (symbol, tf) queries against `intelligence_features`
- Added synchronous DB seed of `intelligence_cache` in `replay_symbol()` before the bar event loop, with `cur.description` column mapping for robustness
- Added `--no-seed` CLI flag to `run_historical_pipeline.py` and threaded `seed_from_db` through `_WorkerArgs`, `_replay_worker`, and all `replay_symbol()` call sites
- 3 unit tests cover happy path (trend_direction seeded), cold-start (no exception on empty table), and parallel gather (4 queries for 2 symbols x 2 tfs)

## Task Commits

1. **T-01: Add _seed_last_events_from_db() to FeaturePipelineExecutor** - `e77adf81` (feat)
2. **T-02: Seed intelligence_cache in replay_symbol() from DB before bar event loop** - `1b16c182` (feat)
3. **T-03: Unit tests for _seed_last_events_from_db()** - `c08d44f4` (test)

## Files Created/Modified

- `src/intelligence/pipeline/feature_pipeline_executor.py` - Added `_seed_last_events_from_db()` async method + `asyncio` import + TYPE_CHECKING `DatabaseManager` import
- `production/scripts/run_historical_pipeline.py` - Added `seed_from_db` param to `replay_symbol()`, seed block for `intelligence_cache`, `--no-seed` CLI flag, `seed_from_db` field to `_WorkerArgs`, propagation through `_replay_worker` and all call sites
- `tests/unit/pipeline/test_feature_pipeline_executor_seed.py` - Created: 3 async tests for seed method
- `tests/unit/scripts/test_run_historical_pipeline.py` - Updated `_replay_worker` tests to include 8th `seed_from_db` element in `_WorkerArgs` tuple

## Decisions Made

- Live executor and replay use separate seed mechanisms: the live `FeaturePipelineExecutor._seed_last_events_from_db()` uses asyncpg async pool; `replay_symbol()` uses the existing psycopg2 connection with synchronous cursor. This avoids introducing async complexity into the script.
- Seed builds a valid minimal `IntelligenceEvent` (all required tier fields present as empty `I4Context()`, `I5Patterns()`, etc.) so that `model_dump()` works correctly when cross-tf frame assembly calls it. Storing a raw dict would bypass schema validation.
- Only I3 trend fields are seeded (`trend_direction`, `trend_strength`, `trend_duration_bars`) since those are the only fields `extract_trend_sign()` reads for ctf_score computation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Existing _replay_worker tests broke due to new _WorkerArgs field**
- **Found during:** T-02 (after adding `seed_from_db` field to `_WorkerArgs`)
- **Issue:** Two existing tests passed 7-element tuples to `_replay_worker`; `_WorkerArgs` now requires 8 fields
- **Fix:** Updated both test tuple literals to include `True` (seed_from_db) as 8th element; updated `mock_replay.assert_called_once_with` to include `seed_from_db=True`
- **Files modified:** `tests/unit/scripts/test_run_historical_pipeline.py`
- **Verification:** Full unit suite green (4759 passed)
- **Committed in:** `1b16c182` (Task 2 commit)

**2. [Rule 3 - Blocking] Pre-commit hook couldn't find ruff/black in worktree**
- **Found during:** First commit attempt
- **Issue:** Pre-commit hook resolves `REPO_ROOT` to worktree dir; `.venv` symlink not present there
- **Fix:** Created `.venv` symlink in worktree pointing to main repo `.venv`
- **Files modified:** `.venv` symlink (worktree local, not committed)
- **Verification:** Pre-commit hooks pass cleanly

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both necessary for test integrity and toolchain function. No scope creep.

## Issues Encountered

- `IntelligenceEvent` requires `i1`, `i3`, `i4`, `i5`, `smc`, `i6` tier fields — all mandatory, no defaults. The seed method must construct a full valid event with empty tier instances (`I4Context()`, `I5Patterns()`, etc.) rather than only passing i3. Resolved by providing all required tiers with their empty constructors (all fields within each tier are individually optional).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 133 clean corpus rebuild will now produce non-zero ctf_scores from bar 1 of each symbol
- The `--no-seed` flag enables a before/after comparison to quantify the A7 ctf_score improvement
- Live executor path has `_seed_last_events_from_db()` ready for integration at startup (caller must invoke it with active symbols and timeframes + DatabaseManager reference)

---
*Phase: 131-signal-generation-integrity*
*Completed: 2026-06-17*
