---
phase: 085-persistence-writer-migration
plan: "03"
subsystem: database
tags: [asyncpg, writer-agents, positional-tuple, named-params, persistence]

# Dependency graph
requires:
  - phase: 085-02
    provides: FeatureSnapshotWriterAgent bounded retry (PERSIST-02)
provides:
  - lifecycle_writer_agent._exit_to_params named helper (12 positions, _EXIT_IDEMPOTENT_SQL)
  - ctx_writer_agent._to_event_row named helper (5 positions, _INSERT_CTX_EVENT_SQL)
  - ctx_writer_agent._to_snapshot_row named helper (4 positions, _UPSERT_CTX_SNAPSHOT_SQL)
  - bar_writer_agent._bar_to_row named helper (10 positions, _INSERT_OHLCV_SQL)
affects: [085-04, persistence-writer-fleet, code-review-audits]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Named _to_row() helper: private method extracts positional tuple from named args, each slot annotated with $N field::type comment"

key-files:
  created: []
  modified:
    - services/lifecycle_writer_agent.py
    - services/ctx_writer_agent.py
    - services/bar_writer_agent.py

key-decisions:
  - "Named _to_row() helpers are pure data-mapping methods with no side effects; callers spread or pass the tuple as needed"
  - "swarm_ledger_writer_agent confirmed clean by prior audit; no migration needed (PERSIST-05 scope explicitly excludes it)"

patterns-established:
  - "Fleet named-param pattern: private _to_row() / _to_params() helper on every writer class, one-comment-per-position, call sites pass named args"

requirements-completed:
  - PERSIST-05

# Metrics
duration: 10min
completed: 2026-05-17
---

# Phase 085 Plan 03: Positional-Tuple Writers Summary

**Named _to_row() helpers added to all three PERSIST-05 offenders: lifecycle_writer (12-pos exit params), ctx_writer (5-pos event + 4-pos snapshot rows), bar_writer (10-pos OHLCV row) — fleet-wide named-param pattern now consistent.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-17T09:08:00Z
- **Completed:** 2026-05-17T09:11:30Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- `LifecycleWriterAgent._exit_to_params(entry)` extracts 12 positional args for `_EXIT_IDEMPOTENT_SQL`; `_flush_exit_items` now calls `*self._exit_to_params(entry)` at the `execute_command` site
- `CtxWriterAgent._to_event_row(...)` and `_to_snapshot_row(...)` extract 5 and 4 positional args respectively; both `_process_message` buffer.append() sites use the helpers with named kwargs
- `BarWriterAgent._bar_to_row(bar, base, source)` extracts the 10-element OHLCV tuple; `_parse_payload` returns `[self._bar_to_row(bar, base, source)]`

## Task Commits

Each task was committed atomically:

1. **Task 1: Add _exit_to_params helper to lifecycle_writer_agent.py** - `908caf6f` (refactor)
2. **Task 2: Add _to_event_row and _to_snapshot_row helpers to ctx_writer_agent.py** - `ff59758f` (refactor)
3. **Task 3: Add _bar_to_row helper to bar_writer_agent.py** - `66b9a77a` (refactor)

## Files Created/Modified
- `services/lifecycle_writer_agent.py` - Added `_exit_to_params` helper; updated `_flush_exit_items` call site
- `services/ctx_writer_agent.py` - Added `_to_event_row` and `_to_snapshot_row` helpers; updated two `buffer.append()` sites in `_process_message`
- `services/bar_writer_agent.py` - Added `_bar_to_row` helper; updated `_parse_payload` return

## Decisions Made
- Named helpers are placed immediately before the method that calls them (locality), matching the `feature_writer_agent._record_to_insert_params` reference pattern
- Each helper uses named keyword arguments at the call sites for maximum readability, not positional pass-through
- `swarm_ledger_writer_agent` was confirmed clean by prior audit and required no changes — PERSIST-05 scope is satisfied by the three files addressed

## Deviations from Plan

None - plan executed exactly as written.

One minor inline fix: initial draft of `_bar_to_row` signature used a quoted `"BarMessage"` forward reference which ruff flagged as UP037 (unnecessary quotes since `BarMessage` is already imported). Fixed before commit; no behavior change.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- PERSIST-05 satisfied; all persistence writers now follow the named _to_row() helper pattern
- Phase 085-04 can proceed with the remaining PERSIST requirements
- Fleet review: any future writer agent should add a named _to_row() / _to_params() helper as the established pattern

---
*Phase: 085-persistence-writer-migration*
*Completed: 2026-05-17*
