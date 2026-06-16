---
phase: 130-script-rewriting
plan: "05"
subsystem: api
tags: [api, signal-ledger-full, apr-migration, schema-migration, 3-table-schema]
dependency_graph:
  requires: [130-01, 130-02]
  provides: [api-read-path-3-table, ui-signals-apr-loading]
  affects: [dashboard, narrative-endpoint, signal-detail-endpoint]
tech_stack:
  added: []
  patterns: [apr-request-time-loading, parameterized-sql-intervals, graceful-config-fallback]
key_files:
  created: []
  modified:
    - src/api/routes/signals.py
    - src/api/routes/narrative.py
    - tests/unit/api/test_signals_route.py
    - tests/unit/api/test_signals_api_detail.py
    - tests/unit/api/test_signals_api_stats.py
    - tests/unit/api/test_signals_api_tier.py
    - tests/unit/api/test_narrative_route.py
decisions:
  - "_get_ui_config() fetches ui.signals.* APR keys per-request with graceful fallback to _APR_DEFAULTS dict; no caching to ensure operator edits take effect immediately"
  - "Parameterized SQL for all APR-driven windows (NOW() - ($N::int * INTERVAL '1 day')) to avoid f-string SQL injection surface; test guard enforces this"
  - "stop_basis extracted from frame_details->>'stop_basis' JSONB inline in SELECT; no extra JOIN needed"
  - "actual_pnl_r used in view queries (from trade_executions); aliased to pnl_r in response for dashboard compatibility"
  - "_signal_query in narrative.py simplified: lateral jsonb join on trading_signals removed; entry_price/stop_loss/targets/entry_type now direct columns from signal_ledger_full"
metrics:
  duration: "~15 minutes"
  completed: "2026-06-16"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 7
---

# Phase 130 Plan 05: API Read-Path Rewrite onto 3-Table Schema

API read-path rewrite: `signals.py` migrated to `signal_ledger_full` view with 7 dropped columns removed and all 10 UX constants migrated to `ui.signals.*` APR keys. `narrative.py` updated to use `tf` instead of dropped `feature_tf`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Rewrite signals.py queries and migrate UX constants to ui.signals.* APR | 1cfdaf36 | src/api/routes/signals.py + 4 test files |
| 2 | Update narrative.py to use tf instead of feature_tf | 82b05624 | src/api/routes/narrative.py + test_narrative_route.py |

## What Was Done

### Task 1: signals.py Rewrite

**Dropped columns removed** (all 7):
- `signal_type` - no equivalent in 3-table schema
- `feature_tf` - replaced by `tf` (canonical column name)
- `bucket_scores` - dropped
- `staleness_score` - dropped
- `staleness_trigger_reason` - dropped
- `feature_schema_version` - dropped
- `pipeline_lag_ms` - dropped (derived: `signal_computed_at - ts`)

**View target corrected**:
- `get_active_signals()` was querying `signal_ledger` (the old monolith); updated to `signal_ledger_full`
- All other endpoints already used `signal_ledger_full`; verified clean

**stop_basis extracted**:
- `frame_details->>'stop_basis'` inline in SELECT; available as `stop_basis` response field in active signals and detail endpoint

**APR migration** - 10 constants migrated to `ui.signals.*` APR keys:

| APR Key | Seed Value | Was |
|---------|-----------|-----|
| `ui.signals.recent_window_days` | 90 | `_RECENT_SIGNAL_WINDOW_DAYS = 90` (line 33) |
| `ui.signals.min_confidence` | 0.40 | inline literal (lines 72/334/454) |
| `ui.signals.min_cis_score` | 0.35 | inline literal (line 334) |
| `ui.signals.today_window_hours` | 24 | inline literal (multiple) |
| `ui.signals.yesterday_window_hours` | 48 | inline literal (line 448) |
| `ui.signals.short_window_days` | 7 | inline literal (multiple) |
| `ui.signals.medium_window_days` | 30 | inline literal (multiple) |
| `ui.signals.latency_threshold_minutes` | 5 | inline literal (line 487) |
| `ui.signals.max_results` | 500 | inline literal (line 203) |
| `ui.signals.top_n_results` | 10 | inline literal (line 527) |

**APR loading pattern**: `_get_ui_config(db_manager)` fetches from `config_state` per request with graceful fallback to `_APR_DEFAULTS`. Exception-safe: test mocks (which return signal rows instead of config rows) are handled by `"config_key" not in row` guard.

**Parameterized SQL**: `get_recent_signals()` uses `$6::int * INTERVAL '1 day'` and `$7::float` / `$8::float` parameters instead of f-string interpolation. A pre-existing unit test guard (`test_no_fstring_query_in_get_recent_signals`) enforces this invariant.

**Column renames**:
- `signal_quality` -> `raw_confidence` (canonical column in signal_events)
- `pnl_r` -> `actual_pnl_r` (from trade_executions via view)
- `outcome` -> `exit_reason` (from trade_executions via view)
- `feature_tf` -> `tf` in all JOIN conditions and feature lookups

**Module docstring** updated per D-14: "Provides access to signal_ledger with optional JOIN..." -> "Queries signal_events/trade_frames via signal_ledger (join view)"

### Task 2: narrative.py Update

- `_SIGNAL_QUERY`: `sl.feature_tf` -> `sl.tf`; JOIN condition `sl.feature_tf = f.tf` -> `sl.tf = f.tf`
- `_SIGNAL_QUERY`: simplified from `LATERAL jsonb_array_elements(f.trading_signals)` lateral join to direct columns `sl.entry_price, sl.stop_loss, sl.targets, sl.entry_type` (all available in `signal_ledger_full`)
- `_build_context_from_row`: `row["feature_tf"]` -> `row["tf"]`
- `_NARRATIVE_UPSERT` execute call: `row["feature_tf"]` -> `row["tf"]`
- Docstring updated: "signal_ledger + intelligence_features row" -> "signal_ledger_full + intelligence_features row"

## Verification

- `signals.py`: `python -c "import src.api.routes.signals; print('import ok')"` -> `import ok`
- `narrative.py`: `assert 'feature_tf' not in src` -> `ok`
- `pytest tests/unit/ -q` -> 4748 passed, 37 skipped

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test mock rows used old schema column names**

- **Found during:** Task 1 verification (pytest run)
- **Issue:** 5 test files had mock rows with `signal_type`, `confidence`, `feature_tf`, `bucket_scores`, `staleness_score`, `outcome`, `pnl_r`, `mfe`, `bars_in_trade`, `bars_to_activation` - all old schema names. Tests failed with `KeyError` on new column names.
- **Fix:** Updated all test mock rows to use 3-table schema column names (`raw_confidence`, `actual_pnl_r`, `exit_reason`, `entry_type`, `tf`). Updated test assertions that checked for now-dropped fields (`bucket_scores`, `staleness_score`, `mfe`, `bars_in_trade`).
- **Files modified:** `test_signals_route.py`, `test_signals_api_detail.py`, `test_signals_api_stats.py`, `test_signals_api_tier.py`, `test_narrative_route.py`
- **Commit:** 1cfdaf36 (Task 1), 82b05624 (Task 2)

**2. [Rule 1 - Bug] get_recent_signals used f-string SQL - blocked by pre-existing test guard**

- **Found during:** Task 1 verification
- **Issue:** Initial implementation used `f"""...{recent_window_days}..."""` in `get_recent_signals()`. A pre-existing test `test_no_fstring_query_in_get_recent_signals` enforces parameterized SQL.
- **Fix:** Rewrote to use `$6::int * INTERVAL '1 day'`, `$7::float`, `$8::float` as parameterized args; appended `recent_window_days, min_confidence, min_cis_score` to the `fetch()` call.
- **Commit:** 1cfdaf36

**3. [Rule 1 - Bug] narrative.py _SIGNAL_QUERY used LATERAL jsonb join on trading_signals**

- **Found during:** Task 2 (reviewing the full query)
- **Issue:** The old query used `LEFT JOIN LATERAL jsonb_array_elements(f.trading_signals) AS tf_sig(value)` to get entry_price/stop_loss/targets/entry_type from a JSONB array column in `intelligence_features`. This column no longer exists in the same form; the data is now directly in `signal_ledger_full` as `tf.entry_price`, `tf.stop_price`, `tf.target_price`, `tf.entry_type` (from trade_frames).
- **Fix:** Replaced lateral join with direct column selection from `signal_ledger_full`.
- **Commit:** 82b05624

## Self-Check

- [x] `src/api/routes/signals.py` exists
- [x] Contains `"Queries signal_events/trade_frames via signal_ledger"` in module docstring
- [x] No reference to `signal_type`, `feature_tf`, `bucket_scores`, `staleness_score`, `staleness_trigger_reason`, `feature_schema_version`, `pipeline_lag_ms` (all grep 0)
- [x] Contains `"ui.signals."` references (33 occurrences)
- [x] `src/api/routes/narrative.py` contains no `feature_tf` (grep 0)
- [x] `narrative.py` uses `row["tf"]` (lines 121, 245)
- [x] Commit 1cfdaf36 exists (Task 1)
- [x] Commit 82b05624 exists (Task 2)
- [x] pytest tests/unit/: 4748 passed, 37 skipped

## Self-Check: PASSED
