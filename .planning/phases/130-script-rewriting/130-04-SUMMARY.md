---
phase: 130-script-rewriting
plan: "04"
subsystem: services
tags: [signal-tracker, swarm-ledger-writer, signal-auditor, signal-probe-auditor, apr, bootstrap, 3-table-schema]
dependency_graph:
  requires: [130-01, 130-02]
  provides: [signal-tracker-bootstrap-rewrite, swarm-fk-on-signal-events, auditor-schema-cleanup]
  affects: [signal_tracker, swarm_ledger_writer, signal_auditor, signal_probe_auditor]
tech_stack:
  added: []
  patterns: [apr-migrate-as-you-go, repository-pattern, jsonb-frame-details-extraction]
key_files:
  created: []
  modified:
    - services/signal_tracker.py
    - services/swarm_ledger_writer.py
    - services/signal_auditor.py
    - services/signal_probe_auditor.py
    - tests/unit/services/test_signal_tracker_bootstrap.py
    - tests/unit/services/test_signal_tracker_immutability.py
    - tests/unit/services/test_signal_auditor.py
decisions:
  - "signal_tracker bootstrap now calls SignalEventsRepository.get_active_signals_for_bootstrap() — direct signal_events + trade_frames JOIN, not signal_ledger_full view which NULLs all lifecycle fields"
  - "signal_tracker direction text 'long'/'short' from signal_events converted to int 1/-1 before _load_signal to preserve existing canonical dict contract"
  - "swarm_ledger_writer FK check updated from signal_ledger to signal_events (D-06); no behavioral change"
  - "signal_auditor _check_pipeline_lag removed entirely — pipeline_lag_ms column dropped from schema; coverage query updated to signal_events (tf/ts columns)"
  - "signal_probe_auditor LEFT JOIN removed; stop_loss sourced from trade_frames.stop_price; entry zones from frame_details JSONB"
  - "APR keys loaded via get_config() in _setup() for signal_tracker bootstrap windows and auditor lookback"
metrics:
  duration: "~35 minutes"
  completed: "2026-06-16"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 7
---

# Phase 130 Plan 04: Tracker and Audit Service Rewrites

Bootstrap rewritten to query signal_events + trade_frames directly via SignalEventsRepository; swarm FK check moved to signal_events; signal_auditor and signal_probe_auditor purged of dropped-table/column dependencies.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Rewrite signal_tracker bootstrap + APR constants | c992dcdb | services/signal_tracker.py + 2 test files |
| 2 | Update swarm_ledger_writer FK, signal_auditor, signal_probe_auditor | 31475210 | 3 services + 1 test file |

## What Was Done

### Task 1: signal_tracker Bootstrap and APR Migration

**Bootstrap rewrite (RESEARCH Pitfall 1 fix):**

Replaced the inline `signal_ledger_full` query in `_bootstrap_active_signals()` with a call to `SignalEventsRepository.get_active_signals_for_bootstrap(pending_window_days, active_window_days)`. The old view returned NULL for all lifecycle fields (activated_at, trailing_stop_price, chandelier_vol_source, entry_zone_low/high, mae/mfe). The new query JOINs signal_events + trade_frames directly, extracting lifecycle metadata from trade_frames.frame_details JSONB.

**Direction text conversion:**

signal_events.direction is text ("long"/"short"). The existing `_load_signal()` method expects int (1/-1). Added conversion before calling `_load_signal`:
```python
dir_raw = raw.get("direction")
if isinstance(dir_raw, str):
    raw["direction"] = 1 if dir_raw == "long" else -1
```

**APR migration:**

Removed class constant `_BOOTSTRAP_MAX_ATTEMPTS = 3`. Added 5 APR-backed instance vars initialized in `__init__` with defaults, then loaded from BaseDaemon `get_config()` in `_setup()`:
- `feature.signal_tracker.bootstrap_max_attempts` (default 3)
- `feature.signal_tracker.bootstrap_pending_window_days` (default 7)
- `feature.signal_tracker.bootstrap_active_window_days` (default 30)
- `feature.signal_tracker.bootstrap_dedup_window_days` (default 3)
- `threshold.signal_tracker.staleness_score` (default STALENESS_SCORE_THRESHOLD)

The dedup count-check at retry time now queries `signal_events` with the APR window days param.

**MAE/MFE bootstrap:**

Old code said "Bootstrap MAE/MFE from signal_outcomes". New code defaults mae/mfe to 0.0 via `raw.setdefault("mae", 0.0)` — correct behavior, since live signals have no tracking history and the repository does not yet expose frame_details mae/mfe extraction (v2.11 responsibility).

**Test updates:**

Bootstrap tests were mocking `DatabaseManager.get_connection()` directly. Replaced with `_patch_bootstrap()` helper that patches `SignalEventsRepository` and `DatabaseManager.execute_query` for the dedup COUNT path. Immutability tests updated with `_staleness_score_threshold` in `_make_agent`.

### Task 2: swarm_ledger_writer, signal_auditor, signal_probe_auditor

**swarm_ledger_writer (D-06):**

One-line FK check updated from `SELECT 1 FROM signal_ledger WHERE signal_id = $1::uuid LIMIT 1` to `SELECT 1 FROM signal_events WHERE signal_id = $1::uuid LIMIT 1`. Comments updated to reference signal_events. Retry/backoff logic, UPSERT SQL, and all other behavior unchanged.

**signal_auditor:**

- Removed `_PIPELINE_LAG_P50` and `_PIPELINE_LAG_P95` OTel metrics (pipeline_lag_ms column dropped from schema)
- Removed `_LAG_P95_WARN_MS` constant
- Removed `_check_pipeline_lag()` method entirely
- Removed `_check_pipeline_lag()` call from `_run_audit()`
- Coverage query updated: `FROM signal_ledger_full WHERE timeframe = ... AND feature_ts >= ...` becomes `FROM signal_events WHERE tf = ... AND ts >= ...`
- CIS distribution query updated: `FROM signal_ledger_full sl JOIN intelligence_features f ON f.ts = sl.feature_ts AND f.tf = sl.feature_tf` becomes `FROM signal_events se JOIN intelligence_features f ON f.ts = se.ts AND f.tf = se.tf`
- Added APR-backed `_audit_lookback_hours` instance var, loaded in `_setup()` via `get_config("feature.signal_auditor.audit_lookback_hours", default=1)`

**signal_probe_auditor:**

- `_select_unselected_sample`: replaced `FROM signal_ledger_full slf LEFT JOIN signal_outcomes so USING (signal_id)` with `FROM signal_events se LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts`. stop_loss sourced from `tf.stop_price`. entry_zone_low/high sourced from `tf.frame_details JSONB`. direction converted from text to int inline. activated_at check moved to frame_details JSONB.
- `_count_competing_signals`: replaced `FROM signal_ledger_full WHERE was_selected = true AND timeframe = ...` with `FROM signal_events se JOIN trade_frames tf ON ... WHERE tf.was_selected = true AND se.tf = ...`

**Test updates:**

`test_signal_auditor.py`: removed `_LAG_P95_WARN_MS` import, removed two pipeline lag test methods, removed `_pipeline_lag_p50/_p95` from agent fixture, added `_audit_lookback_hours` to fixture.

## Verification

All acceptance criteria met:
- `get_active_signals_for_bootstrap` in signal_tracker.py: present
- `signal_events_repository` import in signal_tracker.py: present
- `FROM signal_ledger_full` in signal_tracker.py: absent
- `feature.signal_tracker.bootstrap_pending_window_days` in signal_tracker.py: present
- `FROM signal_events WHERE signal_id` in swarm_ledger_writer.py: 1 match
- `FROM signal_ledger WHERE signal_id` in swarm_ledger_writer.py: 0 matches
- `signal_outcomes` in signal_probe_auditor.py: 0 matches
- `pipeline_lag_ms` in signal_auditor.py: 0 matches
- `feature.signal_auditor.audit_lookback_hours` in signal_auditor.py: 2 matches (load + log)
- All three modules import without error
- pytest tests/unit/: 4746 passed, 37 skipped

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] direction text "long"/"short" from signal_events incompatible with _load_signal**

- **Found during:** Task 1 implementation
- **Issue:** signal_events.direction column is text "long"/"short". `_load_signal()` does `int(raw.get("direction", 1))` which raises ValueError on text direction. The old signal_ledger_full view provided integer direction; the new bootstrap returns text.
- **Fix:** Added direction text-to-int conversion before passing to _load_signal: `raw["direction"] = 1 if dir_raw == "long" else -1`
- **Files modified:** services/signal_tracker.py
- **Commit:** c992dcdb

**2. [Rule 1 - Bug] Bootstrap tests mocked DatabaseManager.get_connection() but new code uses SignalEventsRepository**

- **Found during:** Task 1 - pytest run after implementation
- **Issue:** All 6 bootstrap tests used `_make_db_mock()` which mocked `db.get_connection()`. New code creates `SignalEventsRepository(db)` and calls `.get_active_signals_for_bootstrap()` - no longer calls `conn.fetch()` directly.
- **Fix:** Replaced `_make_db_mock` with `_patch_bootstrap()` helper that patches `SignalEventsRepository` class and its `get_active_signals_for_bootstrap` method. DatabaseManager mock retained only for `execute_query` (dedup COUNT path).
- **Files modified:** tests/unit/services/test_signal_tracker_bootstrap.py
- **Commit:** c992dcdb

**3. [Rule 1 - Bug] test_signal_auditor.py imports _LAG_P95_WARN_MS which was removed**

- **Found during:** Task 2 - pytest collection failure
- **Issue:** `from services.signal_auditor import _LAG_P95_WARN_MS` fails after constant removal. Also had `_check_pipeline_lag` test methods that reference the removed method.
- **Fix:** Removed `_LAG_P95_WARN_MS` from import, removed two pipeline lag test methods, cleaned up fixture of pipeline lag metric mocks.
- **Files modified:** tests/unit/services/test_signal_auditor.py
- **Commit:** 31475210

**4. [Rule 2 - Missing] APR instance var defaults missing for test agents bypassing __init__**

- **Found during:** Task 1 - immutability test failure
- **Issue:** `_make_agent()` in two test files uses `SignalTracker.__new__(SignalTracker)` bypassing `__init__`. New instance vars `_staleness_score_threshold` and `_bootstrap_max_attempts` were not in `_make_agent`. BaseDaemon raises AttributeError for missing attrs.
- **Fix:** Added APR default attrs to both `_make_agent` helpers.
- **Files modified:** tests/unit/services/test_signal_tracker_bootstrap.py, tests/unit/services/test_signal_tracker_immutability.py
- **Commit:** c992dcdb

## Self-Check

- [x] `services/signal_tracker.py` modified — imports SignalEventsRepository, calls get_active_signals_for_bootstrap
- [x] `services/swarm_ledger_writer.py` modified — FK check on signal_events
- [x] `services/signal_auditor.py` modified — no pipeline_lag_ms, APR lookback loaded
- [x] `services/signal_probe_auditor.py` modified — no signal_outcomes, no signal_ledger_full
- [x] Commit c992dcdb exists (Task 1)
- [x] Commit 31475210 exists (Task 2)
- [x] pytest tests/unit/: 4746 passed
- [x] All acceptance criteria verified

## Self-Check: PASSED
