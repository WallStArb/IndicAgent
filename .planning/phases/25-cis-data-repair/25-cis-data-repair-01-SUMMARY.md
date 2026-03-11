---
phase: 25-cis-data-repair
plan: 01
subsystem: Intelligence Pipeline (I7 Aggregation)
tags: [data-integrity, backfill, cis-aggregator]
dependency_graph:
  requires: []
  provides: [CIS fields in backfill-generated signal_ledger rows]
  affects: [historical_backfill.py, signal_ledger table]
tech_stack:
  added:
    - CIS field propagation in backfill path
  patterns:
    - TDD (RED-GREEN commit workflow)
    - Mock-based unit testing with patch
key_files:
  created:
    - tests/unit/scripts/test_historical_backfill.py (4 new CIS tests)
    - .planning/phases/25-cis-data-repair/deferred-items.md
  modified:
    - production/scripts/historical_backfill.py (3 changes: aggregate call, LedgerEntry construction, serialization)
decisions: []
metrics:
  duration_seconds: 1093
  duration_minutes: 18
  completed_date: "2026-03-11T08:48:00Z"
  tasks_completed: 1
  tests_added: 4
  tests_passing: 8 (4 pre-existing + 4 new)
---

# Phase 25 Plan 1: CIS Data Repair Summary

Fixed `historical_backfill.py` so that new replay runs populate CIS fields on every signal_ledger row that has matching intelligence data.

## One-liner

Pass `features=` kwarg to `aggregate()` in backfill script and propagate CIS fields through LedgerEntry → DB insertion, ensuring backfill signals carry the same cis_score/bucket_scores/weights_version as live signals.

## Objective Achieved

The backfill script was calling `aggregate()` without the `features=` kwarg, so the CIS scorer never ran and all new backfill signals landed with NULL cis_score, bucket_scores, and weights_version. This was a one-line call-site bug plus a propagation gap in `_insert_signals_sync`.

## Implementation

Three targeted changes to `production/scripts/historical_backfill.py`:

### Change 1 — `run_i7_and_persist` (line 513)

Pass `features=features` to `aggregate()`:

```python
# Before:
agg_result = aggregate(raw_signals, trend_regime=trend_regime)

# After:
agg_result = aggregate(raw_signals, trend_regime=trend_regime, features=features)
```

This enables the CIS scorer to compute cis_score, bucket_scores, and weights_version from the feature vector.

### Change 2 — `_build_ledger_entries` (lines 437-439)

Read CIS fields from `AggregatedResult` and pass them into each `LedgerEntry`:

```python
entries.append(LedgerEntry(
    # ... all existing fields ...
    cis_score=result.cis_score,
    bucket_scores=result.bucket_scores,
    weights_version=result.weights_version,
))
```

All signals in the same bar share the same CIS score (the score describes the bar's feature vector, not the individual signal) — this matches live aggregator behavior.

### Change 3 — `_insert_signals_sync` (lines 458-463)

Replace hardcoded `None` CIS values with reads from `LedgerEntry`:

```python
# Before:
None,   # cis_score — NULL for backfill rows
None,   # bucket_scores — NULL for backfill rows
None,   # weights_version — NULL for backfill rows
None,   # signal_quality — NULL for backfill rows

# After:
e.cis_score,
json.dumps(e.bucket_scores) if e.bucket_scores is not None else None,
e.weights_version,
None,  # signal_quality — populated by lifecycle on exit
```

The `signal_quality` field remains `None` because it is populated by the signal_lifecycle_service when signals exit (not at signal fire time).

## Tests Added (TDD RED-GREEN)

Four new unit tests in `tests/unit/scripts/test_historical_backfill.py`:

1. **`test_run_i7_and_persist_populates_cis_fields`**: Mock `aggregate()` to return `AggregatedResult` with cis_score=0.42, bucket_scores={"trend": 0.4}, weights_version=0. Mock `_insert_signals_sync` to capture `LedgerEntry` list. Assert entries[0].cis_score == 0.42, entries[0].bucket_scores == {"trend": 0.4}, entries[0].weights_version == 0.

2. **`test_run_i7_and_persist_passes_features_kwarg_to_aggregate`**: Use `unittest.mock.patch` on `aggregate`. Call `run_i7_and_persist` with non-empty features dict. Assert mock was called with `features=` that_dict.

3. **`test_insert_signals_sync_writes_cis_fields`**: Create `LedgerEntry` with cis_score=0.55, bucket_scores={"trend": 0.5}, weights_version=1. Call `_insert_signals_sync` with a mock psycopg2 connection. Assert the execute_batch call receives the tuple with those values at positions 24, 25, 26 (0-indexed) — not `None`.

4. **`test_run_i7_and_persist_cis_null_when_no_raw_signals`**: When no I7 plugins fire, `run_i7_and_persist` returns 0 and no DB insert — existing behaviour unaffected.

All 4 tests pass (GREEN).

## Deviations from Plan

None — plan executed exactly as written. All three changes were implemented in the exact locations specified, with the exact code patterns from the plan.

## Verification

- `.venv/bin/pytest tests/unit/scripts/test_historical_backfill.py -v` — 8/8 pass (4 pre-existing + 4 new)
- `.venv/bin/ruff check production/scripts/historical_backfill.py` — only pre-existing E501 line-too-long errors; no new errors introduced
- Diff confirms `aggregate(raw_signals, trend_regime=trend_regime, features=features)` is present
- Diff confirms `e.cis_score` appears in the `_insert_signals_sync` params (not `None`)
- Diff confirms `cis_score=result.cis_score` appears in the `_build_ledger_entries` LedgerEntry constructor

## Pre-existing Issues (Deferred)

Discovered but out of scope (not introduced by this task):

- **F821 Undefined name 'timezone' in `historical_backfill.py:941`**: Uses `timezone.utc` but only `UTC` is imported from datetime. This is in `main()` function's replay path (--days argument). Deferred to `.planning/phases/25-cis-data-repair/deferred-items.md`.

## Commits

- `c77b17a` — `test(25-01): add failing tests for CIS field propagation in backfill`
- `9b8dfa5` — `feat(25-01): fix CIS field propagation in historical_backfill.py`

## Impact

Future replay runs (via `historical_backfill.py --replay-only`) will produce signal_ledger rows with populated cis_score/bucket_scores/weights_version. This ensures:

1. Backfill data is consistent with live data for ML training dataset integrity
2. CIS weights adaptation (Phase 25-02 audit/repair) will work correctly on backfill rows
3. Signal outcomes from backfill can be used for statistical analysis of CIS performance

## Success Criteria Met

- [x] `historical_backfill.py` calls `aggregate(..., features=features)` on every I7 aggregation call
- [x] CIS fields from `AggregatedResult` flow through `_build_ledger_entries` into `LedgerEntry` objects
- [x] `_insert_signals_sync` serializes `LedgerEntry` CIS fields instead of hardcoding `None`
- [x] All 4 new tests pass; all pre-existing tests in `test_historical_backfill.py` still pass
- [x] Future replay runs will produce signal_ledger rows with populated cis_score/bucket_scores/weights_version
