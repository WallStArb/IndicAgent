---
phase: 088-god-class-decomposition
plan: "03"
subsystem: intelligence-pipeline
tags: [god-class-decomposition, cache-manager, refresh-loops, eager-load, seed-api, unit-tests]
dependency_graph:
  requires: [088-01, 088-02]
  provides: [CacheManager class, eager-load contract, seed API]
  affects: [intelligence_pipeline_agent, pipeline_tests, pipeline_helpers]
tech_stack:
  added: []
  patterns: [eager-load-before-refresh-loops, merge-vs-atomic-replace, version-gated-mediation, ast-inspection-tests]
key_files:
  created:
    - src/intelligence/pipeline/cache_manager.py
    - tests/unit/pipeline_tests/test_cache_manager.py
  modified:
    - src/intelligence/pipeline/__init__.py
    - services/intelligence_pipeline_agent.py
    - tests/unit/pipeline_helpers.py
    - tests/unit/pipeline_tests/test_orchestrator_checkpoint_assembly.py
    - tests/unit/intelligence/test_metrics_compute.py
decisions:
  - CacheManager._load_cis_weights stores version but never calls cis_scorer.update_weights (Pitfall 4); orchestrator mediates via version-gate in _run_i7_inner
  - tod_priors uses merge semantics in both _load_tod_multipliers and seed_tod_priors (Pitfall 7)
  - load_initial() runs all 6 loaders sequentially in god-class order before start_refresh_loops ever sleeps (HIGH finding 3)
  - enroll_all_plugins called by orchestrator BEFORE load_initial so _load_shadow_cache sees populated registry (MEDIUM finding)
  - _pattern_reliability confirmed dead code via rg (written at 2 sites, zero readers) — deleted without rehoming
  - _load_cis_kalman_params moved to cache_manager.py; module-level and _CIS_KALMAN_DEFAULTS removed from orchestrator
  - test_seed_api_does_not_call_scorer and test_no_enroll_all_plugins use AST inspection rather than string search to avoid false positives from docstrings
metrics:
  duration_minutes: 11
  completed_date: "2026-05-18"
  tasks_completed: 3
  files_modified: 7
---

# Phase 088 Plan 03: CacheManager Extraction Summary

CacheManager extracted as the third DAG node from IntelligencePipelineComputeAgent. Owns all 6 DB-loaded caches and their refresh schedule, with a uniform public seed_* API for tests and checkpoint restore. Approximately 200 lines removed from orchestrator.

## What Was Built

`CacheManager` lives at `src/intelligence/pipeline/cache_manager.py`. It owns:

- 6 cache dicts: `_perf_weights`, `_cis_weights`, `_calibration_curves`, `_shadow_cache`, `_drift_penalties`, `_tod_priors`
- `_cis_kalman_params` loaded once from config file (no refresh loop per D-13)
- 7 properties: `perf_weights`, `cis_weights`, `cis_kalman_params`, `calibration_curves`, `drift_penalties`, `shadow_cache`, `tod_priors`, plus `cis_weights_version`
- `load_initial()` — eagerly runs all 6 loaders in god-class order (HIGH finding 3 regression guard)
- `start_refresh_loops()` — returns 6 background Tasks at intervals 3600/14400/1800/1800/14400/300
- `update_hmm_regime(hmm_val)` and `current_hmm_regime_label()` — regime label mapping (ported verbatim)
- 6 `seed_*` methods as the single public contract for outside writers (tests, checkpoint restore)
- 6 private `_load_*/_refresh_*` methods ported from god class

## Lines Removed from Orchestrator

| Removed | Location | Notes |
|---------|----------|-------|
| `self._shadow_cache = {}` | `__init__` | migrated |
| `self._cis_weights_cache = {}` | `__init__` | migrated |
| `self._cis_kalman_params = _load_cis_kalman_params()` | `__init__` | migrated |
| `self._calibration_curves = {}` | `__init__` | migrated |
| `self._perf_weights = {}` | `__init__` | migrated |
| `self._drift_penalties = {}` | `__init__` | migrated |
| `self._last_hmm_regime = None` | `__init__` | migrated |
| `self._tod_priors = {}` | `__init__` | migrated |
| `self._pattern_reliability = {}` | `__init__` | deleted (dead code) |
| `_load_cis_kalman_params()` | module func | moved to cache_manager.py |
| `_CIS_KALMAN_DEFAULTS` | module constant | moved to cache_manager.py |
| `_pattern_reliability_cache*` globals | module | deleted (dead code) |
| `_load_pattern_reliability_weights()` | module func | deleted (dead code) |
| `_run_refresh_loop()` | method | migrated to CacheManager |
| `_current_hmm_regime_label()` | method | migrated to CacheManager |
| `_load_perf_weights()` | method | migrated |
| `_load_shadow_cache()` | method | migrated |
| `_refresh_drift_penalties()` | method | migrated |
| `_load_cis_weights()` | method | migrated |
| `_load_calibration_curves()` | method | migrated |
| `_load_tod_multipliers()` | method | migrated |
| 6 refresh loop tasks from `_run()` | `asyncio.gather` | moved to `start_refresh_loops()` |
| `import json`, `from pathlib import Path`, `from src.monitoring.ks_drift_monitor import DRIFT_PENALTIES` | imports | no longer needed in orchestrator |
| **Total** | | ~200 lines |

## Critical Constraints Preserved

### Eager-Load Contract (HIGH finding 3)

```python
# Orchestrator _setup():
self._cache_mgr = CacheManager(db=self._db, settings=self.settings)
async with self._db.pool.acquire() as conn:
    await enroll_all_plugins(conn)       # enrollment BEFORE load_initial
await self._cache_mgr.load_initial()    # eager load all 6 caches
for task in self._cache_mgr.start_refresh_loops():   # loops start AFTER
    self._background_tasks.add(task)
    task.add_done_callback(self._background_tasks.discard)
```

Without `load_initial()`, the service would start cold for up to 4 hours (one refresh interval per cache).

### Enrollment Ordering (MEDIUM finding)

`enroll_all_plugins(conn)` runs before `load_initial()` because `_load_shadow_cache` (the last step inside `load_initial`) reads the `shadow_registry` table that enrollment populates.

### tod_priors Merge Semantics (Pitfall 7)

Both `_load_tod_multipliers` and `seed_tod_priors` use `{**self._tod_priors, **priors}`. After `load_initial` loads from DB, checkpoint restore applies `seed_tod_priors(extra.get("tod_priors", {}))` to merge checkpoint values on top.

### CIS Scorer Mediation (Pitfall 4 / D-07)

`CacheManager._load_cis_weights` stores `_cis_weights` and `_cis_weights_version` but never calls `cis_scorer.update_weights`. The orchestrator mediates in `_run_i7_inner`:

```python
if self._cache_mgr.cis_weights_version != self._last_synced_cis_version:
    self._cis_scorer.update_weights(
        self._cache_mgr.cis_weights, self._cache_mgr.cis_weights_version
    )
    self._last_synced_cis_version = self._cache_mgr.cis_weights_version
```

After plan 05, this moves into `SignalProcessor.sync_cis_weights()`.

## Dead Code Confirmed and Deleted

`rg "_pattern_reliability|load_pattern_reliability"` confirmed:
- `self._pattern_reliability` written at lines 426 and 603 in the god class
- Zero readers anywhere in the codebase
- Deleted without rehoming: the instance attr, module-level cache globals (`_pattern_reliability_cache`, `_pattern_reliability_cache_ts`, `_pattern_reliability_cache_ttl_sec`), and the `_load_pattern_reliability_weights` module function

## Unit Tests Added

17 isolated tests in `tests/unit/pipeline_tests/test_cache_manager.py`:

- `test_initial_caches_are_empty_dicts`
- `test_update_hmm_regime_drives_label` (0/1/2/None/5 cases)
- `test_seed_tod_priors_merge_preserves_existing`
- `test_seed_perf_weights_atomic_replace`
- `test_seed_cis_weights_sets_version`
- `test_seed_cis_weights_version_zero_not_stored`
- `test_seed_api_does_not_call_scorer` (AST check — no update_weights call)
- `test_seed_calibration_curves_atomic_replace`
- `test_seed_shadow_cache_atomic_replace`
- `test_seed_drift_penalties_atomic_replace`
- `test_load_tod_multipliers_merge_not_replace` (Pitfall 7 regression)
- `test_load_perf_weights_atomic_replacement`
- `test_load_cis_weights_does_not_call_scorer`
- `test_start_refresh_loops_returns_six_tasks`
- `test_load_initial_invokes_all_six_loaders` (HIGH finding 3 regression guard)
- `test_load_initial_runs_shadow_cache_last` (MEDIUM enrollment ordering guard)
- `test_no_enroll_all_plugins_in_cache_manager` (AST check — orchestrator-owned)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_seed_api_does_not_call_scorer and test_no_enroll_all_plugins_in_cache_manager used string search which matched docstrings**
- **Found during:** Task 3 test run
- **Issue:** `inspect.getsource(CacheManager)` includes docstrings which legitimately mention "cis_scorer" and "enroll_all_plugins" for documentation. Plain string assertions failed.
- **Fix:** Replaced with AST inspection (`ast.parse` + `ast.walk`) checking for actual function calls and attribute accesses. String matches in comments/docstrings no longer trigger false positives.
- **Commits:** a5fb0703

**2. [Rule 1 - Bug] test_metrics_compute referenced _load_perf_weights on IntelligencePipelineComputeAgent**
- **Found during:** Task 2 test run
- **Issue:** `TestPipelinePerfWeightsSymbol.test_load_perf_weights_builds_three_tuple_keys` inspected `IntelligencePipelineComputeAgent._load_perf_weights` which no longer exists after migration.
- **Fix:** Updated test to inspect `CacheManager._load_perf_weights` instead.
- **Commit:** d7cb2c38

## Self-Check

All verification commands from plan:

```
rg "_pattern_reliability|load_pattern_reliability" -> confirmed zero readers (instance attr, module globals, module func all deleted)
.venv/bin/ruff check src/intelligence/pipeline/ services/intelligence_pipeline_agent.py tests/unit/pipeline_tests/ -> All checks passed
grep -n "self._perf_weights=..." services/intelligence_pipeline_agent.py -> no results
grep -n "def _load_perf_weights|def _run_refresh_loop|..." services/intelligence_pipeline_agent.py -> no results
.venv/bin/pytest tests/unit/ -q -> 3319 passed, 1 skipped
```

## Self-Check: PASSED
