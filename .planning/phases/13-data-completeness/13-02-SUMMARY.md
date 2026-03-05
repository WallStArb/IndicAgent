---
phase: 13-data-completeness
plan: "02"
subsystem: intelligence
tags: [signal-generator, redis-streams, i7, ml-training, aggregator]

# Dependency graph
requires:
  - phase: 13-01
    provides: intelligence_i7 stream key function in src/core/stream_keys.py

provides:
  - _build_i7_payload helper function in signal_generator_service.py
  - intelligence_i7 xadd call in _process_bar after every aggregation cycle
  - Compact signal list payload with is_winner flag for ML counterfactual learning

affects:
  - 13-03 (feature_writer i7 UPSERT subscriber)
  - 14-01 (feedback loop reads i7 data for ML training)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_build_i7_payload pure function pattern: separate payload construction from publish for testability"
    - "Publish even when all_ranked is empty — every bar gets a timestamped i7 data point"
    - "is_winner flag encodes aggregator selection decision alongside counterfactual signals"

key-files:
  created: []
  modified:
    - services/signal_generator_service.py
    - tests/unit/service_tests/test_signal_generator_service.py

key-decisions:
  - "_build_i7_payload is a module-level pure function (not method) to enable isolated unit testing without __new__ bypass"
  - "i7 payload includes only 10 compact fields per signal (not full signal dict) to reduce stream size"
  - "is_winner=True requires rank==1 AND selected_signal not None AND plugin match AND regime_eligible — suppressed signals never win"
  - "Empty bar publishes {data: '[]'} — ensures every bar has a timestamped i7 data point for temporal completeness"

patterns-established:
  - "Stream publish with routing fields: ts/symbol/tf in every enrichment stream message for feature_writer routing"

requirements-completed: [DATA-01, DATA-03]

# Metrics
duration: 15min
completed: 2026-03-05
---

# Phase 13 Plan 02: i7 Enrichment Stream Publisher Summary

**`_build_i7_payload` function + xadd to `intelligence_i7:SYMBOL:TF` after every aggregation cycle, publishing full signal ranked list with is_winner flag for ML counterfactual training**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-05T10:00:00Z
- **Completed:** 2026-03-05T10:15:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `_build_i7_payload` pure helper that builds compact 10-field signal list from `AggregatedResult.all_ranked`
- Wired xadd to `intelligence_i7:SYMBOL:TF` stream inside `_process_bar` — fires unconditionally after aggregation (including empty bar)
- `is_winner` flag correctly encodes aggregator selection: True only when rank==1, selected_signal not None, plugin match, and regime_eligible=True
- 5 new unit tests in `TestBuildI7Payload` all pass; full suite 1122 passing, 0 ruff errors

## Task Commits

Each task was committed atomically:

1. **Task 1: Publish all_ranked to intelligence_i7 stream in _process_bar** - `9d86d02` (feat)
2. **Task 2: Unit tests for i7 publish logic** - `6bc066a` (test)

**Plan metadata:** committed in final docs commit

## Files Created/Modified

- `services/signal_generator_service.py` — Added `sk_intelligence_i7` import, `_build_i7_payload` function, and xadd call in `_process_bar` (after signals_aggregated publish, before elapsed_ms)
- `tests/unit/service_tests/test_signal_generator_service.py` — Added `TestBuildI7Payload` class with 5 tests covering empty payload, signal shape, winner flag, suppression guard, and routing fields

## Decisions Made

- `_build_i7_payload` is a module-level pure function rather than a method — allows clean unit testing without the `__new__` bypass pattern
- Payload compacts signal fields to 10 keys (`setup_type`, `confidence`, `direction`, `regime_eligible`, `suppression_reason`, `entry`, `stop`, `target`, `composite_rank`, `is_winner`) rather than passing the full signal dict — reduces stream message size
- Empty `all_ranked` still publishes `{"data": "[]"}` — every bar must have a timestamped i7 entry for the ML training dataset to have complete temporal coverage

## Deviations from Plan

None — plan executed exactly as written. Minor: ruff auto-fixed import sort order from single-line to multi-line parenthesized form.

## Issues Encountered

Ruff I001 triggered on the stream_keys import alias. Applied `--fix` to resolve sort order. Zero functional impact.

## Next Phase Readiness

- `intelligence_i7:SYMBOL:TF` stream is now populated by `signal_generator_service` after each bar
- Plan 13-03 (feature_writer i7/i8 UPSERT subscriber) can now subscribe to this stream
- ML training dataset will have full signal-space per bar once feature_writer wires the UPSERT

---
*Phase: 13-data-completeness*
*Completed: 2026-03-05*

## Self-Check: PASSED

- services/signal_generator_service.py — FOUND
- tests/unit/service_tests/test_signal_generator_service.py — FOUND
- .planning/phases/13-data-completeness/13-02-SUMMARY.md — FOUND
- Commit 9d86d02 — FOUND
- Commit 6bc066a — FOUND
