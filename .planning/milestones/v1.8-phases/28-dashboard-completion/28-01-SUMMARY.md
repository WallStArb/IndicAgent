---
phase: 28-dashboard-completion
plan: "01"
subsystem: api/sse
tags: [sse, streaming, intelligence_i7, signal_scorecard, dashboard]
dependency_graph:
  requires: [src/core/stream_keys.py intelligence_i7]
  provides: [SSE signal_scorecard event type, intelligence_i7 stream in SSE endpoint]
  affects: [dashboard SSE consumers, frontend signal scorecard component]
tech_stack:
  added: []
  patterns: [TDD red-green, lru_cache domain routing]
key_files:
  created: []
  modified:
    - src/api/routes/sse.py
    - tests/unit/test_sse_snapshot_filter.py
decisions:
  - intelligence_i7 check placed before intelligence: check to prevent startswith shadowing
  - intelligence_i7 added to known_domains for correct env-prefix stripping
metrics:
  duration: "~2 min"
  completed: "2026-03-12"
  tasks_completed: 2
  files_modified: 2
---

# Phase 28 Plan 01: Wire intelligence_i7 into SSE — Summary

**One-liner:** Added `intelligence_i7` Redis stream domain to SSE endpoint, emitting `signal_scorecard` events for all symbol×timeframe combinations.

## What Was Built

The signal generator already publishes `all_ranked` data to `intelligence_i7:SYMBOL:TF` on every bar. This plan made that stream visible to the frontend by wiring it into the SSE endpoint.

Changes to `src/api/routes/sse.py`:
1. Added `from ...core.stream_keys import intelligence_i7 as sk_intelligence_i7`
2. In `_build_stream_list()`: appended `sk_intelligence_i7(env_prefix, contract, tf)` right after the `sk_intelligence` call in the `for tf in timeframes:` loop
3. In `_event_name_for_stream()`: added `"intelligence_i7"` to `known_domains` set for correct env-prefix stripping
4. Added `if candidate.startswith("intelligence_i7:"): return "signal_scorecard"` BEFORE the existing `intelligence:` check to prevent shadowing

## Tests Added

`TestIntelligenceI7Routing` class in `tests/unit/test_sse_snapshot_filter.py` — 6 tests:
- `test_event_name_for_intelligence_i7_es_1m` — ESH6 1m stream → `signal_scorecard`
- `test_event_name_for_intelligence_i7_nq_5m` — NQH6 5m stream → `signal_scorecard`
- `test_intelligence_data_not_regressed` — intelligence: still → `intelligence_data`
- `test_build_stream_list_includes_intelligence_i7` — single TF includes i7 stream
- `test_build_stream_list_includes_two_intelligence_i7_for_two_tfs` — 2 TFs → 2 i7 streams
- `test_build_stream_list_i7_stream_contains_correct_tf` — TF suffix correct in stream key

All 12 tests pass (6 existing + 6 new).

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

### Files exist:
- src/api/routes/sse.py: FOUND
- tests/unit/test_sse_snapshot_filter.py: FOUND

### Commits exist:
- 520f457: test(28-01): add failing tests for intelligence_i7 SSE routing
- d049896: feat(28-01): wire intelligence_i7 stream into SSE endpoint

## Self-Check: PASSED
