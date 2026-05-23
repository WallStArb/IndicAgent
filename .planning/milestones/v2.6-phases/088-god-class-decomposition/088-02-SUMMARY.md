---
phase: 088-god-class-decomposition
plan: "02"
subsystem: intelligence-pipeline
tags: [god-class-decomposition, plugin-state-manager, checkpoint, background-loop, unit-tests]
dependency_graph:
  requires: [088-01]
  provides: [PluginStateManager class, interim checkpoint wiring]
  affects: [intelligence_pipeline_agent, pipeline_tests, pipeline_helpers]
tech_stack:
  added: []
  patterns: [single-writer-checkpoint, background-loop-resilience, extra-state-injection]
key_files:
  created:
    - src/intelligence/pipeline/state_manager.py
    - tests/unit/pipeline_tests/test_state_manager.py
    - tests/unit/pipeline_tests/test_orchestrator_checkpoint_assembly.py
  modified:
    - src/intelligence/pipeline/__init__.py
    - services/intelligence_pipeline_agent.py
    - tests/unit/pipeline_helpers.py
decisions:
  - Lock keying changed from per-(plugin_name,symbol,tf) to per-(symbol,tf) matching plan specification
  - _restore_tuple_key moved into state_manager.py to keep all checkpoint helpers co-located
  - Unused ast/state_serializer imports removed from orchestrator after migration
  - Constants (_AGENT_VERSION, _CHECKPOINT_FIELDS, _CHECKPOINT_PATH) migrated to state_manager; orchestrator imports only _CHECKPOINT_PATH
  - Interim acceptance test created in separate file (test_orchestrator_checkpoint_assembly.py) so plan 03/05 owners know exactly what to update
metrics:
  duration_minutes: 12
  completed_date: "2026-05-18"
  tasks_completed: 3
  files_modified: 6
---

# Phase 088 Plan 02: PluginStateManager Extraction Summary

PluginStateManager extracted as the second DAG node from IntelligencePipelineComputeAgent. Owns the `_plugin_states` dict keyed by `(plugin_name, symbol, tf)`, per-`(symbol, tf)` threading locks, and the checkpoint file. Background checkpoint loop is now class-owned — orchestrator calls `start_checkpoint_loop` once.

## What Was Built

`PluginStateManager` lives at `src/intelligence/pipeline/state_manager.py`. It owns:

- `_plugin_states: dict[tuple, dict]` keyed by `(plugin_name, symbol, tf)` — single owner
- `_locks: dict[tuple, threading.Lock]` keyed by `(symbol, tf)` — per-bar-slot, not per-plugin
- `get_state(key)` — single-plugin read by full 3-tuple
- `get_all_states_for(symbol, tf) -> dict[str, dict]` — per-bar read API keyed by plugin_name (HIGH finding 1)
- `get_lock(key: (symbol, tf))` — lazy-init lock
- `update(key, state)` / `update_batch(state_updates)` — write API
- `get_all_states()` — full snapshot for checkpoint and tests
- `write_checkpoint(extra_state)` — SINGLE WRITER; raises ValueError if `plugin_states` in extra_state (HIGH finding 5); raises on I/O failure (D-15)
- `read_checkpoint()` — async; restores `_plugin_states` internally, returns cross-owned fields dict
- `start_checkpoint_loop(interval_sec, get_extra_fn)` — returns asyncio.Task; loop catches per-iteration exceptions (MEDIUM finding); CancelledError propagates

## Module Constants Migrated

| Constant | From | To |
|----------|------|----|
| `_AGENT_VERSION` | `services/intelligence_pipeline_agent.py` | `src/intelligence/pipeline/state_manager.py` |
| `_CHECKPOINT_PATH` | `services/intelligence_pipeline_agent.py` | `src/intelligence/pipeline/state_manager.py` |
| `_CHECKPOINT_FIELDS` | `services/intelligence_pipeline_agent.py` | `src/intelligence/pipeline/state_manager.py` |
| `_restore_tuple_key` | `services/intelligence_pipeline_agent.py` | `src/intelligence/pipeline/state_manager.py` |

Orchestrator imports only `_CHECKPOINT_PATH` (for `parent.mkdir()`).

## Methods Removed from Orchestrator

| Removed | Location | Lines |
|---------|----------|-------|
| `self._plugin_states = {}` | `__init__` | 1 |
| `self._plugin_states_locks = {}` | `__init__` | 1 |
| `def _get_state_lock(self, key)` | method | 4 |
| `def _write_local_checkpoint(self)` | method | 7 |
| `async def _read_local_checkpoint(self)` | method | 24 |
| `_AGENT_VERSION`, `_CHECKPOINT_FIELDS`, `_restore_tuple_key` | module scope | 12 |
| **Total removed** | | ~49 lines |

## Checkpoint Single-Writer Contract (HIGH Finding 5)

```python
def write_checkpoint(self, extra_state: dict) -> None:
    if "plugin_states" in extra_state:
        raise ValueError("extra_state must not contain 'plugin_states' — ...")
    payload = {"version": ..., "ts": ..., "plugin_states": _tag_value(self._plugin_states)}
    for k, v in extra_state.items():
        payload[k] = _tag_value(v)
    ...
```

The orchestrator's `_assemble_checkpoint_extra()` returns ONLY cross-owned fields:
```python
{"kalman_state": ..., "tod_priors": ..., "last_bar_offset": ..., "setup_last_fire": ...}
```

## Background Loop Resilience (MEDIUM Finding)

```python
async def _loop():
    while True:
        try:
            await asyncio.sleep(interval_sec)
            extra = get_extra_fn()
            self.write_checkpoint(extra)
        except asyncio.CancelledError:
            raise  # propagate — do not swallow
        except Exception as exc:
            self._checkpoint_failures.add(1)
            self._logger.exception("checkpoint_loop.iteration_failed", ...)
            # continue — transient failure does not kill the loop
```

`write_checkpoint` itself still raises on failure (D-15 preserved for teardown callers). The loop wrapper catches that raise so the background task stays alive.

## Interim-State Hazard Documentation

Between plans 02 and 03/05, `_assemble_checkpoint_extra` reads orchestrator-owned attributes:

| Field | Interim owner | Plan that migrates |
|-------|---------------|-------------------|
| `tod_priors` | `self._tod_priors` | Plan 03 (CacheManager) |
| `kalman_state` | `self._kalman_state` | Plan 05 (SignalProcessor) |
| `setup_last_fire` | `self._setup_last_fire` | Plan 05 (SignalProcessor) |
| `last_bar_offset` | `self._last_bar_offset` | Plan 05 (SignalProcessor) |

The file `tests/unit/pipeline_tests/test_orchestrator_checkpoint_assembly.py` documents this hazard explicitly. Plans 03/05 must update this test in lockstep when they migrate the source attributes.

## Unit Tests Added

14 isolated tests in `tests/unit/pipeline_tests/test_state_manager.py`:
- `test_get_lock_returns_same_lock_per_key`
- `test_get_lock_different_keys_return_different_locks`
- `test_update_and_get_state_roundtrip`
- `test_get_all_states_for_filters_by_symbol_tf` (HIGH finding 1)
- `test_get_all_states_for_returns_empty_dict_when_no_match`
- `test_update_batch_merges_full_tuple_keys`
- `test_write_then_read_checkpoint_roundtrip`
- `test_write_checkpoint_raises_if_extra_contains_plugin_states` (HIGH finding 5)
- `test_write_checkpoint_persists_internal_plugin_states`
- `test_write_checkpoint_raises_on_io_error` (D-15)
- `test_read_checkpoint_returns_none_on_missing_file`
- `test_start_checkpoint_loop_writes_periodically`
- `test_start_checkpoint_loop_survives_transient_failure` (MEDIUM finding)
- `test_start_checkpoint_loop_propagates_cancellation`

2 interim acceptance tests in `tests/unit/pipeline_tests/test_orchestrator_checkpoint_assembly.py`:
- `test_assemble_checkpoint_extra_keys_are_exactly_cross_owned`
- `test_assemble_checkpoint_extra_plugin_states_not_present_when_state_mgr_has_data`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] No .venv symlink in worktree for pre-commit hooks**
- **Found during:** Task 1 commit
- **Issue:** Pre-commit hook uses `${REPO_ROOT}/.venv/bin/ruff` but this worktree had no .venv.
- **Fix:** Created symlink `/home/bg/dev/indicagent/.claude/worktrees/agent-a2cfd8db2de70baf6/.venv -> /home/bg/dev/indicagent/.venv` (same fix as plan 01)
- **Files modified:** worktree .venv symlink (not tracked)

**2. [Rule 2 - Missing functionality] Lock key granularity changed**
- **Found during:** Task 2 implementation
- **Issue:** Original code used `(plugin_name, symbol, tf)` as lock key (per-plugin locks). The plan specifies `(symbol, tf)` (per-bar-slot locks). This is the correct design — the plan is authoritative.
- **Fix:** `get_lock` keyed by `(symbol, tf)` and all call sites updated accordingly.

## Self-Check

```bash
[ -f "src/intelligence/pipeline/state_manager.py" ] && echo "FOUND: state_manager.py" || echo "MISSING: state_manager.py"
[ -f "tests/unit/pipeline_tests/test_state_manager.py" ] && echo "FOUND: test_state_manager.py" || echo "MISSING: test_state_manager.py"
[ -f "tests/unit/pipeline_tests/test_orchestrator_checkpoint_assembly.py" ] && echo "FOUND: test_orchestrator_checkpoint_assembly.py" || echo "MISSING: test_orchestrator_checkpoint_assembly.py"
```

## Self-Check: PASSED

All created files exist. All 3302 unit tests pass. All 16 new tests pass. Ruff clean.
