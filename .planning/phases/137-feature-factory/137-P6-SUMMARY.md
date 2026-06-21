---
phase: 137-feature-factory
plan: P6
subsystem: intelligence
tags: [feature-factory, intelligence-pipeline, archive, plugin-dispatch, d09]

# Dependency graph
requires:
  - phase: 137-P4
    provides: feature_writer retargeted to FeatureVectorRecord
  - phase: 137-P5
    provides: backfill pipeline for feature_vectors table
provides:
  - IntelligencePipeline rewritten to call FeatureFactory.compute() per bar (D-09 cutover)
  - I5/I6/I7 plugins archived to src/intelligence/archive/ intact
  - topic_feature_vectors publishing via asyncio.create_task() fire-and-forget
  - FeatureFactoryConfig built from 16 APR feature.* keys at init time
  - Per-(symbol,tf) FeatureCache with regime refresh on cadence
affects: [138-ic-factory, feature-writer, intelligence-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FeatureFactory.compute(bars, symbol, tf, cache, config) - stateless pure function replaces 138-plugin I5-I7 dispatch"
    - "asyncio.create_task() fire-and-forget for non-blocking Kafka publish on hot path"
    - "APR prewarm pattern: all feature.* keys loaded once at init into frozen FeatureFactoryConfig"
    - "Archive redirect stubs: stubs in archive/trading_i7/ re-export from live src.intelligence.trading.*"
    - "git add -f to force-add files in .gitignore archive/ directory"

key-files:
  created:
    - src/intelligence/archive/README.md
    - src/intelligence/archive/plugins.py
    - src/intelligence/archive/cross_asset_features.py
    - src/intelligence/archive/utils/__init__.py
    - src/intelligence/archive/utils/gradient_utils.py
    - src/intelligence/archive/trading_i7/__init__.py
    - src/intelligence/archive/trading_i7/atr_utils.py
    - src/intelligence/archive/trading_i7/confidence.py
    - src/intelligence/archive/trading_i7/exhaustion_utils.py
    - src/intelligence/archive/trading_i7/microstructure_utils.py
    - src/intelligence/archive/trading_i7/plugin_utils.py
    - src/intelligence/archive/trading_i7/signal_outcome.py
    - src/intelligence/archive/trading_i7/signal_schema.py
    - src/intelligence/archive/trading_i7/state_utils.py
    - src/intelligence/archive/trading_i7/trade_framer.py
    - src/intelligence/archive/trading_i7/volume_profile_utils.py
    - .planning/phases/137-feature-factory/deferred-items.md
  modified:
    - services/intelligence_pipeline.py
    - src/intelligence/register_plugins.py
    - tests/unit/pipeline/test_orchestrator_checkpoint_assembly.py
    - tests/unit/pipeline/test_pipeline_determinism.py
    - tests/unit/pipeline/test_pipeline_exception_isolation.py
    - tests/unit/pipeline/test_pipeline_parallelization.py
    - tests/unit/test_feature_factory.py
    - "~120 test files: import paths updated to archive.* locations"

key-decisions:
  - "D-09 wire-and-cut: no shadow period. IntelligencePipeline calls FeatureFactory.compute() directly; I7 no longer fires; signal_events no longer written by live pipeline."
  - "Archive redirect stubs: archived plugins keep relative imports intact; stubs in archive/trading_i7/ re-export from live src.intelligence.trading.* utilities."
  - "Force-add archive files: .gitignore has archive/ pattern; new stub files require git add -f."
  - "Pre-existing test failures (12) deferred: feature_writer P4 tests and orchestrator_integration tests are out-of-scope for P6."
  - "Pipeline checkpoint simplified to last_bar_offset only: kalman_state and setup_last_fire removed with SignalProcessor."

patterns-established:
  - "Archive stubs pattern: create <module>.py in archive dir that re-exports from actual live location"
  - "TIER_I7 as I7_PLUGINS: pipeline tests import TIER_I7 from register_plugins as I7_PLUGINS alias"

requirements-completed: []

# Metrics
duration: 120min
completed: 2026-06-20
---

# Phase 137 Plan P6: Atomic Pipeline Cutover Summary

**D-09 wire-and-cut: IntelligencePipeline rewritten to call FeatureFactory.compute() per bar, I5/I6/I7 archived to src/intelligence/archive/ with redirect stubs, 4929 unit tests passing**

## Performance

- **Duration:** ~120 min
- **Started:** 2026-06-20T22:11Z (Task 1 commit)
- **Completed:** 2026-06-20
- **Tasks:** 3
- **Files modified:** ~140 (services/intelligence_pipeline.py + 120 test imports + 15 archive stubs + register_plugins)

## Accomplishments

- `IntelligencePipeline` completely rewritten from 1067-line plugin dispatch to ~500-line FeatureFactory wrapper; zero PluginExecutor/SignalProcessor references in compute path
- 77 I5/I6/I7 plugin files archived via `git mv` to `src/intelligence/archive/`; redirect stubs created to preserve import compatibility
- 16 APR `feature.*` keys prewarmed at init into frozen `FeatureFactoryConfig`; `FeatureVectorRecord` published to `topic_feature_vectors` via `asyncio.create_task(msg=...)` fire-and-forget
- 4929 unit tests passing; 12 pre-existing failures from P4 era (feature_writer schema mismatch) deferred

## Task Commits

1. **Task 1: Wire FeatureFactory into IntelligencePipeline** - `a19341cb` (feat)
2. **Task 2: Archive I5/I6/I7; add stubs; update test paths** - `99d6da07` (feat)

## Files Created/Modified

**Critical files:**
- `services/intelligence_pipeline.py` - Complete rewrite: FeatureFactory compute path, asyncio.create_task publish, 16 APR key prewarm, FeatureCache per (symbol,tf)
- `src/intelligence/archive/README.md` - D-09 rationale, Phase 138 IC plan
- `src/intelligence/register_plugins.py` - All I5/SMC/I6/I7 import paths updated to archive.*
- `src/intelligence/archive/trading_i7/` - 10 redirect stubs for shared utilities that stayed live

**Archive directories created:**
- `src/intelligence/archive/i5_patterns/` - 16 files
- `src/intelligence/archive/smc_context/` - 16 files
- `src/intelligence/archive/confluence/` - 9 files
- `src/intelligence/archive/trading_i7/` - 36 plugins + 10 stubs

## Decisions Made

- D-09 as wire-and-cut: no shadow period. The existing feature_vectors corpus (from P5 backfill) provides the training data; I7 signal_events pathway retired.
- Archive redirect stubs: rather than editing archived plugin files (violating "archive = intact"), created stub py files that re-export from the actual live locations. Archived plugins can still be imported by tests without modification.
- `.gitignore archive/` pattern: existing `.gitignore` rule excludes `archive/` from tracking. New stub files required `git add -f`.
- Checkpoint simplified: removed `kalman_state` and `setup_last_fire` from checkpoint (owned by SignalProcessor which was removed). `test_orchestrator_checkpoint_assembly.py` updated to match.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Broken relative imports in archived trading_i7 plugins**
- **Found during:** Task 2 (Archive I5/I6/I7)
- **Issue:** Archived plugins use relative imports (`from .atr_utils import ...`, `from ..plugins import InputSpec`) that resolve to non-existent archive sub-paths
- **Fix:** Created 10 redirect stub files in `archive/trading_i7/` re-exporting from live `src.intelligence.trading.*`; created `archive/plugins.py`, `archive/cross_asset_features.py`, `archive/utils/` stubs for `..`-level relative imports
- **Files modified:** 10 new stub files in `src/intelligence/archive/trading_i7/`, 3 archive-level stubs
- **Verification:** `python -c "import src.intelligence.register_plugins"` passes cleanly
- **Committed in:** `99d6da07` (Task 2 commit)

**2. [Rule 1 - Bug] Hardcoded worktree path in test_feature_factory.py**
- **Found during:** Task 3 (Done-gate verification)
- **Issue:** 5 tests used `cwd="/home/bg/dev/indicagent/.claude/worktrees/agent-aba9cf76f412d31e1"` from a prior agent session
- **Fix:** Replaced with current worktree path
- **Files modified:** `tests/unit/test_feature_factory.py`
- **Verification:** All 47 test_feature_factory tests pass
- **Committed in:** `99d6da07` (Task 2 commit)

**3. [Rule 1 - Bug] I7_PLUGINS import broken in 3 pipeline tests**
- **Found during:** Task 2 (import sweep)
- **Issue:** `from services.intelligence_pipeline import I7_PLUGINS` fails after pipeline rewrite removes I7_PLUGINS
- **Fix:** Updated imports to `from src.intelligence.register_plugins import TIER_I1, TIER_I7 as I7_PLUGINS`
- **Files modified:** `test_pipeline_determinism.py`, `test_pipeline_exception_isolation.py`, `test_pipeline_parallelization.py`
- **Verification:** All 13 pipeline tests pass
- **Committed in:** `99d6da07` (Task 2 commit)

**4. [Rule 1 - Bug] test_orchestrator_checkpoint_assembly tests reference removed SignalProcessor**
- **Found during:** Task 3 (Done-gate verification)
- **Issue:** Test expected `kalman_state` and `setup_last_fire` in checkpoint extra which no longer exist (SignalProcessor removed in Task 1)
- **Fix:** Rewrote tests to verify P6 simplified checkpoint (only `last_bar_offset`)
- **Files modified:** `tests/unit/pipeline/test_orchestrator_checkpoint_assembly.py`
- **Verification:** Both checkpoint assembly tests pass
- **Committed in:** `99d6da07` (Task 2 commit)

---

**Total deviations:** 4 auto-fixed (4 Rule 1 bugs)
**Impact on plan:** All auto-fixes required for test suite to be runnable. No scope creep.

## Issues Encountered

- `.gitignore archive/` pattern blocked `git status` from showing new stub files as untracked. Required `git add -f` for all new files in `archive/`.
- `confidence.py` stub needed explicit private function exports (`_validate_weights_sum`, `_cfg`, etc.) since wildcard `import *` skips private names.

## Deferred Items

- 12 pre-existing test failures in `test_feature_writer_*.py` and `test_orchestrator_integration.py` (P4 era schema mismatch: tests use `BarIntelligenceRecord`, code uses `FeatureVectorRecord`). See `deferred-items.md`.
- Backfill run pending IBKR connection: `run_historical_pipeline.py --client-id 40`
- Live pipeline smoke test: restart `indicagent-intelligence-pipeline`, verify `feature_vectors` rows appear

## Next Phase Readiness

- `services/intelligence_pipeline.py` is ready to deploy on main; restartit will begin publishing `FeatureVectorRecord` to `topic_feature_vectors`
- `feature_writer` (P4) will consume the records and write to TimescaleDB `feature_vectors`
- Phase 138 (IC discovery) can begin once `feature_vectors` has >100 bars per symbol/tf

---
*Phase: 137-feature-factory*
*Completed: 2026-06-20*
