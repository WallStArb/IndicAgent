---
**Created:** 2026-07-05
**Area:** tests
**Type:** tech_debt
**Priority:** P3
**Effort:** 1-2 hours
**Benefit:** Restores real coverage for 15 Stage-2 (Intelligence Replay) unit tests that currently fail on main
**Risk:** low
---

**Resolved 2026-07-08 — differently than proposed:** rather than sweeping the stale
`production.scripts.run_historical_pipeline` patch paths for all 15 tests, the underlying
Stage 2 (I1-I7 intelligence-replay) code they cover was deleted outright. It was confirmed
dead independent of this todo: `signal_events`/`trade_frames`/`trade_executions` all had 0
rows, every writer service (`indicagent-signal-writer`, `indicagent-signal-tracker-compute`,
`indicagent-lifecycle-writer`) was `inactive dead`, and the file already carried its own
2026-07-05 RCA comment (`F7`) independently concluding "this entire archived v2.x
plugin/replay stack has no live consumer." The full I1-I7 plugin corpus remains preserved in
`src/intelligence/archive/` for any future reimplementation. `infrastructure_run_historical_pipeline.py`
went from 3055 to 1329 lines (Stage 1 IBKR-fetch logic, still live, untouched); the file's own
docstring and git history now record the removal. `test_run_historical_pipeline.py` was
rewritten to keep only the 12 tests covering surviving Stage 1 functions
(`aggregate_bars_from_1m`, `fetch_bars`/`store_bars`, `detect_gaps` — the latter's patch
paths fixed to the correct module) — all pass. The `TestDetectGaps` tests specifically
(3 of the 15) were live-code coverage that a naive whole-file delete would have destroyed;
worth remembering for next time this kind of cleanup comes up.

# 062 — Fix stale `production.scripts.run_historical_pipeline` mock patch paths

**Relationship to todo 045:** this is the fully-diagnosed subset of the broader 33-test-failure
set todo 045 originally tracked — 045 has been narrowed to exclude this file now that it has
its own concrete fix here. The `test_regime_writer.py`/`test_causal_hmm_decoding.py` failures
045 still tracks are a different, unexplained root cause (possible HMM numeric drift), not
stale mock paths — don't conflate the two when picking either up.

Discovered 2026-07-05 while verifying an unrelated fix (F1-F7 IBKR backfill robustness
pass) didn't regress `tests/unit/scripts/test_run_historical_pipeline.py`. Confirmed via
`git stash` that 15 tests in that file **already fail on main, independent of any change
made this session**:

```
test_build_ledger_entries_sets_market_entry_price_to_bar_close
test_build_ledger_entries_ecl_fields_non_null_when_annotated
test_run_i7_and_persist_populates_cis_fields
test_run_i7_and_persist_passes_features_kwarg_to_aggregate
test_insert_signals_sync_writes_cis_fields
test_run_i7_and_persist_cis_null_when_no_raw_signals
test_run_i1_plugins_isolates_state_between_symbols
test_run_i1_plugins_state_written_back_after_compute
test_run_analysis_pipeline_includes_i2_tier
test_replay_worker_calls_replay_symbol_and_returns_tuple
test_replay_worker_closes_connection_on_failure
TestCISColumnsInSQL::test_insert_signals_sync_params_include_cis_nulls
TestDetectGaps::test_nyse_over_weekend_no_gaps
TestDetectGaps::test_nyse_on_holiday_no_gaps
TestDetectGaps::test_genuine_intraday_gap_detected
test_run_i7_and_persist_passes_calibration_to_aggregate
test_replay_symbol_threads_calibration_to_run_i7
```

**Root cause:** these tests use `unittest.mock.patch("production.scripts.run_historical_pipeline.<name>", ...)`
— a module path from before commit `0e2023cd` (`refactor(scripts): reorganize
production/scripts/ into scripts/{debug,infrastructure,ops}`). The correct current path
is `scripts.infrastructure.backfill.infrastructure_run_historical_pipeline`. `patch()`
fails at `__enter__` with `ModuleNotFoundError`/`AttributeError` trying to resolve the
stale path, so these tests fail before ever exercising the code under test — meaning the
functions they're meant to cover (`run_i1_plugins`, `run_analysis_pipeline`,
`_build_ledger_entries`, `run_i7_and_persist`, `_insert_signals_sync`, `_replay_worker`,
`detect_gaps`) currently have **no real unit test coverage** despite `pytest` reporting
these as regular (not skipped/xfail) test functions.

**Fix:** sweep `tests/unit/scripts/test_run_historical_pipeline.py` for all
`patch("production.scripts.run_historical_pipeline...")` occurrences and update to
`patch("scripts.infrastructure.backfill.infrastructure_run_historical_pipeline...")`.
Re-run the file after each batch to confirm the patches actually take effect (a stale
path can silently no-op a patch in some mock configurations rather than erroring —
verify each fixed test's assertions actually exercise the mocked behavior, not just that
it stops raising).

**Gate:** none — standalone, no dependency on other in-flight work.
