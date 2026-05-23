---
phase: 092-signal-quality-completeness
plan: 02
subsystem: database
tags: [signal-metrics, entry-type, per-symbol, accumulator, asyncpg, pytest, otel]

requires:
  - phase: 092-01
    provides: "_build_metrics_result(entry_type=) signature, MetricsComputedEvent with entry_type and distribution fields, signal_metrics PK with entry_type, ON CONFLICT updated"

provides:
  - "compute_signal_metrics() emits three row families: global (*,*), per-symbol (sym,*), and per-entry_type (*,et)"
  - "by_entry_type defaultdict accumulator keyed by (plugin, tf, regime_label, entry_type_val)"
  - "NULL entry_type rows excluded from per-entry_type accumulation (fold to global only)"
  - "Unknown entry_type literals pass through to dedicated rows (no whitelist / no silent drop)"
  - "signal_metrics_compute_agent _QUERY selects entry_type; publish dict and Kafka key carry entry_type and all six distribution fields"
  - "TestEntryTypeGrouping: 7 unit tests covering n-gate, NULL fold, distribution fields, unknown entry_type pass-through"
  - "Integration tests: _ensure_schema idempotency, per-entry_type and per-symbol INSERT assertions, entry_type default"

affects:
  - "092-03 — tail gate in shadow_auditor_agent queries signal_metrics WHERE entry_type = '*'"
  - "cache_manager.py — already guarded with AND entry_type = '*' (Plan 01)"
  - "src/api/routes/signals.py — already guarded (Plan 01)"

tech-stack:
  added: []
  patterns:
    - "Three-accumulator pattern in compute_signal_metrics: regime_accs (symbol-keyed), all_accs (symbol rollup), by_entry_type (entry_type-keyed, symbol='*')"
    - "NULL guard for per-entry_type: entry_type_raw if entry_type_raw else None — empty string and NULL both fold to global"
    - "No whitelist for entry_type values — unknown literals accumulate to their own key; downstream queries filter entry_type='*'"

key-files:
  created:
    - "tests/integration/test_signal_metrics_per_entry_type.py"
  modified:
    - "src/intelligence/metrics/compute.py"
    - "services/signal_metrics_compute_agent.py"
    - "tests/unit/intelligence/test_metrics_compute.py"

key-decisions:
  - "by_entry_type accumulator gated at n >= 30 (not MIN_SAMPLE_SIZE) per CONTEXT.md D-07 — same threshold as per-symbol"
  - "NULL and empty string entry_type both fold to None via entry_type_raw if entry_type_raw — unified guard"
  - "No allowed-list check for entry_type values — unknown literals get their own row for diagnostic visibility; Plan 03 tail gate uses entry_type='*' only"
  - "Kafka key extended with :{mr.entry_type} suffix so per-entry_type messages have unique keys per PK tuple"
  - "per-entry_type n_total tracking: n_never_activated not accumulated in by_entry_type (pnl_r=None rows skip the guard)"

requirements-completed:
  - QUAL-02
  - QUAL-03

duration: 12min
completed: 2026-05-20
---

# Phase 092 Plan 02: Per-Symbol and Per-Entry-Type Grouping Summary

**compute_signal_metrics() extended with by_entry_type accumulator emitting (symbol='*', entry_type=actual) rows gated at n >= 30; Kafka publish dict carries entry_type and all six distribution fields**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-20T13:40:00Z
- **Completed:** 2026-05-20T13:52:00Z
- **Tasks:** 4
- **Files modified:** 3 (+ 1 created)

## Accomplishments

- Added `by_entry_type: dict[tuple, dict] = defaultdict(_empty_acc)` third accumulator to `compute_signal_metrics()`, keyed by `(plugin, tf_val, regime_label, entry_type_val)`. NULL/empty entry_type folds to global only; unknown literals pass through without whitelist check.
- Extended `signal_metrics_compute_agent._QUERY` with `entry_type` column; updated Kafka publish dict to include `entry_type` and all six distribution fields; extended Kafka key with `:{mr.entry_type}` suffix for unique-per-PK identification.
- Added `TestEntryTypeGrouping` class (7 tests) to unit test file covering n-gate, NULL fold, distribution field population, two-entry_type subset, global aggregate completeness, and unknown literal pass-through.
- Created `tests/integration/test_signal_metrics_per_entry_type.py` (7 tests) using AsyncMock: `_ensure_schema` idempotency, per-entry_type INSERT assertions, per-symbol INSERT assertions, entry_type default-to-star.

## Task Commits

1. **Task 1: Add by_entry_type accumulation and result emission** - `9de932b6` (feat)
2. **Task 2: Update _QUERY, publish dict, and Kafka key** - `682aff34` (feat)
3. **Task 3: Add TestEntryTypeGrouping unit tests** - `9d3c41e6` (test)
4. **Task 4: Add integration tests** - `bf479e7d` (test)

## Files Created/Modified

- `src/intelligence/metrics/compute.py` - Added `by_entry_type` accumulator dict, `entry_type_val` extraction with NULL guard, per-entry_type result emission loop; explicit `entry_type="*"` on existing calls
- `services/signal_metrics_compute_agent.py` - Added `entry_type` to `_QUERY` SELECT; added `entry_type` and 6 distribution fields to publish dict; extended Kafka key
- `tests/unit/intelligence/test_metrics_compute.py` - Added `entry_type="at_close"` to `_make_row()`; updated `test_returns_row_when_n_meets_minimum` to `>= 2`; added `TestEntryTypeGrouping` with 7 tests
- `tests/integration/test_signal_metrics_per_entry_type.py` - New file: 7 integration tests via AsyncMock

## Decisions Made

- Gate for per-entry_type rows is `n >= 30` (not `MIN_SAMPLE_SIZE`) to match per-symbol gate per CONTEXT.md D-07.
- No whitelist for entry_type values - unknown literals (e.g. `"experimental_zone"`) accumulate to their own row key. Downstream tail gate (Plan 03) queries `AND entry_type = '*'` so orphan rows do not corrupt governance but remain visible for diagnostics.
- `n_never_activated` is NOT tracked in `by_entry_type` accumulator because `pnl_r=None` rows never reach the `if entry_type_val is not None:` guard (they `continue` before it). This is correct - never-activated signals have no classifiable entry pattern.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_returns_row_when_n_meets_minimum assertion**
- **Found during:** Task 3 (unit tests)
- **Issue:** Existing test expected exactly 2 results; after Task 1, MIN_SAMPLE_SIZE=30 rows with `entry_type="at_close"` now also emit a per-entry_type row, producing 3 results
- **Fix:** Changed assertion to `>= 2` with explanatory comment
- **Files modified:** `tests/unit/intelligence/test_metrics_compute.py`
- **Committed in:** `9d3c41e6`

**2. [Rule 1 - Bug] Fixed test_per_entry_type_distribution_fields_populated data construction**
- **Found during:** Task 3 (unit tests)
- **Issue:** Used uniform loss values (-1.0) which made p5_r equal to min value; tail `[r < p5]` empty -> `cvar_5=None`. CVaR requires at least one value strictly below the 5th-percentile cut.
- **Fix:** Replaced with 10 losses of progressively worse values `[-(i+1)*0.3 for i in range(10)]` so p5 lands in the interior of the loss range
- **Files modified:** `tests/unit/intelligence/test_metrics_compute.py`
- **Committed in:** `9d3c41e6`

---

**Total deviations:** 2 auto-fixed (both Rule 1 - test data/assertion corrections)
**Impact on plan:** Both fixes were test correctness issues; no production logic changes needed.

## Issues Encountered

None - plan executed cleanly. The two test fixes were expected edge cases from combining non-trivial distribution behavior with deterministic test data.

## User Setup Required

None - no external service configuration required. Schema migration runs automatically at `signal_metrics_writer_agent` startup via `_ensure_schema()`.

## Next Phase Readiness

Plan 03 (shadow governance tail gate) can proceed:
- `signal_metrics` table has `entry_type` and six distribution columns (from Plan 01)
- Per-entry_type rows now written by compute agent (this plan)
- All three consumer queries already carry `AND entry_type = '*'` guards (Plan 01) - no duplication risk
- `_build_metrics_result(entry_type='*')` signature ready for Plan 03's `signal_metrics` query which must filter `AND entry_type = '*' AND symbol = '*'`

---
*Phase: 092-signal-quality-completeness*
*Completed: 2026-05-20*
