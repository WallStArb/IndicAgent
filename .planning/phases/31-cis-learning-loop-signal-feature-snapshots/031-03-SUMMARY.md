---
phase: 31-cis-learning-loop-signal-feature-snapshots
plan: 03
subsystem: database
tags: [signal_ledger, signal_features, shadow, ab_testing, statistical_inference, statsmodels, asyncpg, timescaledb]

# Dependency graph
requires:
  - phase: 31-cis-learning-loop-signal-feature-snapshots/031-01
    provides: signal_features hypertable, signal_ledger.is_shadow column (migration 034)

provides:
  - LedgerEntry.is_shadow field with 39-param INSERT SQL
  - FEATURE_BUCKET_MAP and _build_feature_rows() for feature snapshot extraction
  - _INSERT_FEATURES_SQL with ON CONFLICT (signal_id, feature_name) DO NOTHING
  - _write_signal_with_features() atomic method in signal_generator_service
  - promote_shadow.py CLI gate: proportions_ztest with p < 0.05 AND N >= 200

affects:
  - Phase 32 (stop architecture — any code calling to_insert_params() needs 39 params)
  - Phase 33 (new I7 plugins — all signals automatically get feature snapshots)
  - Phase 35 (CIS calibration — signal_features is the training dataset)
  - ML scoring phases (signal_features as labeled training data)

# Tech tracking
tech-stack:
  added:
    - statsmodels.stats.proportion.proportions_ztest (scipy.stats has no proportions_ztest in 1.17+)
  patterns:
    - TDD: RED (write failing tests) -> GREEN (implement) -> verify all pass
    - Atomic DB writes via asyncpg conn.transaction() context manager
    - Shadow A/B flag on domain model (is_shadow: bool = False) for safe live experimentation
    - Statistical gate for promotion (p < 0.05 AND N >= 200 — Renaissance discipline)

key-files:
  created:
    - production/scripts/promote_shadow.py
    - tests/unit/service_tests/test_signal_generator_features.py
    - tests/unit/scripts/test_promote_shadow.py
  modified:
    - src/intelligence/trading/signal_ledger.py
    - services/signal_generator_service.py
    - tests/unit/intelligence/test_signal_ledger.py

key-decisions:
  - "Use statsmodels.stats.proportion.proportions_ztest not scipy.stats — scipy 1.17+ removed it"
  - "Pass features dict replicated per entry (all signals on same bar share same mid-bar snapshot); cis_result=None means bucket_contribution is NULL (acceptable — contributions can be back-filled)"
  - "asyncpg conn.transaction() is a synchronous context manager (not awaitable) — use MagicMock not AsyncMock for transaction() in tests"
  - "is_shadow default False — existing signals are production by default, opt-in for shadow"
  - "One-sided z-test (alternative='larger') — only promote when shadow is BETTER, not just different"

patterns-established:
  - "Signal feature snapshots: _build_feature_rows() extracts numeric-only values, maps to FEATURE_BUCKET_MAP buckets"
  - "Atomic signal writes: _write_signal_with_features() wraps both signal_ledger + signal_features in conn.transaction()"
  - "Shadow A/B: is_shadow=True on LedgerEntry enables matched-pair comparison via promote_shadow.py"

requirements-completed: [FEAT-01, FEAT-02, SHAD-01, SHAD-02]

# Metrics
duration: 35min
completed: 2026-03-17
---

# Phase 31 Plan 03: Signal Feature Snapshots + Shadow Promotion Gate Summary

**Atomic signal_features writes via asyncpg transaction, LedgerEntry.is_shadow for A/B comparison, and promote_shadow.py CLI enforcing p < 0.05 AND N >= 200 before any shadow path goes live**

## Performance

- **Duration:** 35 min
- **Started:** 2026-03-17T02:00:00Z
- **Completed:** 2026-03-17T02:35:00Z
- **Tasks:** 3
- **Files modified:** 5 (3 source, 2 new test files)

## Accomplishments
- Extended LedgerEntry with is_shadow flag and updated to_insert_params() to return 39-element tuple
- Added FEATURE_BUCKET_MAP (34 feature-to-bucket mappings) and _build_feature_rows() with ON CONFLICT safety
- Replaced insert_signals() in signal_generator_service with _write_signal_with_features() — atomically writes signal_ledger + signal_features in one asyncpg transaction
- Created promote_shadow.py CLI with statsmodels proportions_ztest (one-sided, p < 0.05 AND N >= 200 gates)

## Task Commits

Each task was committed atomically:

1. **Task 1: LedgerEntry is_shadow + _build_feature_rows** - `419448a` (feat)
2. **Task 2: Atomic signal_features write** - `36694e6` (feat)
3. **Task 3: Shadow promotion CLI** - `72ebc1c` (feat)

_Note: TDD tasks — RED verified before GREEN implementation._

## Files Created/Modified
- `src/intelligence/trading/signal_ledger.py` — is_shadow field, 39-param INSERT, FEATURE_BUCKET_MAP, _build_feature_rows, _INSERT_FEATURES_SQL
- `services/signal_generator_service.py` — _write_signal_with_features() method, replaced insert_signals() call
- `production/scripts/promote_shadow.py` — CLI gate with proportions_ztest
- `tests/unit/intelligence/test_signal_ledger.py` — 12 new tests (TestIsShadowField, TestBuildFeatureRows), updated 4 existing param count assertions
- `tests/unit/service_tests/test_signal_generator_features.py` — 7 new tests for atomic write
- `tests/unit/scripts/test_promote_shadow.py` — 6 new tests for promotion gate

## Decisions Made
- Use `statsmodels.stats.proportion.proportions_ztest` — scipy 1.17+ removed it from `scipy.stats`
- Pass `features` dict replicated per entry (all signals on same bar share mid-bar snapshot); `cis_result=None` means `bucket_contribution` is NULL — acceptable for V1
- asyncpg `conn.transaction()` returns a synchronous context manager, not a coroutine — tests must use `MagicMock` for `transaction()`, not `AsyncMock`
- `is_shadow` defaults to `False` — existing production signals are unaffected; shadow path is opt-in
- One-sided z-test (`alternative="larger"`) — only promote when shadow is statistically BETTER than production

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] scipy.stats has no proportions_ztest in scipy 1.17+**
- **Found during:** Task 3 (promote_shadow.py test run)
- **Issue:** `from scipy.stats import proportions_ztest` raises ImportError — function moved/removed in scipy 1.17.1
- **Fix:** Changed import to `from statsmodels.stats.proportion import proportions_ztest` — already installed in venv
- **Files modified:** production/scripts/promote_shadow.py
- **Verification:** All 6 promote_shadow tests pass
- **Committed in:** 72ebc1c (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking import fix)
**Impact on plan:** Minimal — identical API, same statistical behavior. statsmodels is the canonical location for this function.

## Issues Encountered
- Existing test `test_to_insert_params` asserted `len(params) == 38` — updated to 39 to match new is_shadow field. Also updated 3 other tests with the same assertion. All pre-existing tests pass after update.

## Next Phase Readiness
- signal_features is now written atomically on every signal fire — ML training dataset accumulation begins immediately
- is_shadow infrastructure ready for Phase 31 Plan 04 (shadow signal path in signal_generator_service)
- promote_shadow.py CLI available for statistical validation once shadow signals accumulate N >= 200

---
*Phase: 31-cis-learning-loop-signal-feature-snapshots*
*Completed: 2026-03-17*
