---
phase: 106-foundation-hardening
plan: "04"
subsystem: intelligence-pipeline
tags:
  - backpressure
  - output-queue
  - observability
  - state-manager
  - secondary-index
  - tracing
  - histogram
dependency_graph:
  requires:
    - 105-03  # histogram infrastructure in intelligence_pipeline_agent.py
  provides:
    - lossless-intel-journal-output  # back-pressure via enqueue_blocking
    - o1-state-lookup                # _states_by_key secondary index
    - pipeline-hotpath-span          # observed_span on _process_bar_inner
    - tier-latency-histogram         # intelligence_pipeline_tier_latency_ms
  affects:
    - services/intelligence_pipeline_agent.py
    - src/intelligence/pipeline/output_queue.py
    - src/intelligence/pipeline/state_manager.py
    - src/intelligence/pipeline/feature_pipeline_executor.py
tech_stack:
  added:
    - "opentelemetry.metrics._meter.create_histogram (tier-level)"
  patterns:
    - "enqueue_blocking with timeout_sec for bounded teardown safety"
    - "secondary index (_states_by_key) kept consistent across all write paths"
    - "async with observed_span() wrapping hot-path compute"
key_files:
  modified:
    - services/intelligence_pipeline_agent.py
    - src/intelligence/pipeline/output_queue.py
    - src/intelligence/pipeline/state_manager.py
    - src/intelligence/pipeline/feature_pipeline_executor.py
decisions:
  - "Used _process_bar_compute() helper to avoid re-indenting 60-line body under observed_span; semantically identical to inline wrap"
  - "timeout_sec=5.0 on both new enqueue_blocking call sites; None default preserves backward-compat for existing signal enqueue sites"
  - "INTELLIGENCE_PIPELINE_TIER_LATENCY_MS defined at module level in feature_pipeline_executor.py using _meter directly (matches metrics.py pattern)"
  - "No delete/clear/expiry paths found in _plugin_states; only update and update_batch mutate it — both now mirror to _states_by_key"
metrics:
  duration: "~10 minutes"
  completed_date: "2026-05-25"
  tasks: 4
  files: 4
---

# Phase 106 Plan 04: Hot-Path Reliability Hardening Summary

Back-pressure enqueue for intel+journal, O(1) state lookup via secondary index, observed_span on the per-bar hot path, and per-tier latency histogram at I1/I2-I6 boundaries.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Replace non-blocking enqueue with enqueue_blocking | 7743adab | services/intelligence_pipeline_agent.py, src/intelligence/pipeline/output_queue.py |
| 2 | Add _states_by_key secondary index to PluginStateManager | f295bcf7 | src/intelligence/pipeline/state_manager.py |
| 3 | Wrap _process_bar_inner in observed_span | 04801fe4 | services/intelligence_pipeline_agent.py |
| 4 | Add per-tier latency histogram at tier boundaries | af187759 | src/intelligence/pipeline/feature_pipeline_executor.py |

## What Was Built

### Task 1 — Lossless intel + journal output

`OutputQueue.enqueue_blocking` gained a `timeout_sec: float | None = None` parameter backed by `asyncio.wait_for`. When the pipeline's intel or journal enqueue call times out (5s default), it raises `asyncio.TimeoutError` rather than hanging — making teardown bounded. Two call sites changed from non-blocking `enqueue` (silent drop on full) to `await enqueue_blocking(..., timeout_sec=5.0)`:

- intel topic enqueue (~line 513)
- `_enqueue_intel_journal` method (converted from sync to async; journal enqueue at ~line 607)

The signal enqueue at ~line 536 was already `enqueue_blocking` and was left unchanged.

### Task 2 — O(1) state lookup via secondary index

`PluginStateManager` now maintains a `_states_by_key: dict[tuple[str, str], dict[str, dict]]` secondary index keyed by `(symbol, tf)`. Every write to `_plugin_states` (in `update()` and `update_batch()`) mirrors the change into `_states_by_key`. `get_all_states_for()` now returns `dict(self._states_by_key.get((symbol, tf), {}))` — O(1) instead of O(N). The index is never serialized; `read_checkpoint()` rebuilds it from `_plugin_states` after restore. Audited all `_plugin_states` references: only `update` and `update_batch` mutate it (no delete, clear, or expiry paths exist).

### Task 3 — observed_span on hot path

`_process_bar_inner` now wraps its compute body in `async with observed_span("pipeline.process_bar_inner", **{ATTR_SYMBOL: bar.symbol, ATTR_TF: bar.tf})`. The compute body was extracted to `_process_bar_compute()` to avoid re-indenting ~60 lines. The span starts after the warmup check (no spans emitted for unwarmed bars). `observed_span` auto-records ERROR status and exception on raise — no manual try/except needed.

### Task 4 — Per-tier latency histogram

`feature_pipeline_executor.py` defines `INTELLIGENCE_PIPELINE_TIER_LATENCY_MS = _meter.create_histogram("intelligence_pipeline_tier_latency_ms", ...)` at module level. Two `.record()` calls added at the coarse tier boundaries:

- After `run_i1(...)`: records `{"tier": "i1"}`
- After `run_tiers(...)`: records `{"tier": "i2_i6"}`

One measurement per tier group per bar. No per-plugin timing added (that already exists via `intelligence_pipeline_plugin_duration_ms`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] `enqueue_blocking` had no timeout/cancellation support**

- **Found during:** Task 1
- **Issue:** The threat model flagged that `enqueue_blocking` blocks indefinitely with no timeout, which causes teardown hangs.
- **Fix:** Added `timeout_sec: float | None = None` parameter to `OutputQueue.enqueue_blocking`; uses `asyncio.wait_for` when timeout is set.
- **Files modified:** src/intelligence/pipeline/output_queue.py
- **Commit:** 7743adab

**2. [Rule 1 - Bug] `_enqueue_intel_journal` was a sync method called from async context**

- **Found during:** Task 1 (when converting journal enqueue to async)
- **Issue:** Switching the journal enqueue to `await enqueue_blocking` required `_enqueue_intel_journal` to be async. The method was sync, so the `await` needed the whole method to become `async def`.
- **Fix:** Converted `_enqueue_intel_journal` to `async def` and updated the call site to `await`.
- **Files modified:** services/intelligence_pipeline_agent.py
- **Commit:** 7743adab

**3. [Rule 3 - Blocking] Pre-commit hook could not find ruff/black in worktree**

- **Found during:** First commit attempt
- **Issue:** Worktree has no `.venv`; pre-commit hook looks for `${REPO_ROOT}/.venv/bin/ruff`.
- **Fix:** Created `.venv` symlink from worktree root to project `.venv`.
- **Files modified:** (symlink, not tracked)
- **Commit:** N/A

## Verification Results

- `grep -n "self._out_queue.enqueue(" services/intelligence_pipeline_agent.py` — no matches (all converted)
- `grep -c "enqueue_blocking" services/intelligence_pipeline_agent.py` — 5 (intel + 2×signal + journal + 1 in dlq path)
- `grep -c "_states_by_key" src/intelligence/pipeline/state_manager.py` — 9 references
- `observed_span("pipeline.process_bar_inner", ...)` present in `_process_bar_inner`
- `intelligence_pipeline_tier_latency_ms` histogram defined; 2 `.record()` calls with tier labels
- All 4 modules import cleanly
- Unit tests: 3,996 passed (57 pre-existing failures unrelated to this plan, confirmed present on base)

## Self-Check: PASSED

All 4 modified files confirmed present on disk. All 4 task commits found in git log.
