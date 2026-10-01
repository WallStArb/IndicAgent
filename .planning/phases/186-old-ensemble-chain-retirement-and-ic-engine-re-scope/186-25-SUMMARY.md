---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 25
subsystem: services
tags: [feature-vectors, rebuild, bulk-load, provenance, timescaledb, preconditions]
requires:
  - phase: 186-06
    provides: bulk_load/BulkLoadSpec, completed_provenance_batch, bar_content_digests, provenance_batch guard triggers
  - phase: 186-15
    provides: kernel registry compute_kernels, CTF/externals builders, FeatureCache handoff
  - phase: 186-18
    provides: regime kernels (hmm_trend_*, hmm_volatility_*)
  - phase: 186-24
    provides: feature_vectors_v2 (migration 425), 312-column schema and evidence JSON
provides:
  - run_rebuild_stage: the single rebuild writer for feature_vectors_v2 (D-28), provenance-keyed (symbol chunk, tf, calendar-year) units, kill-and-resume (D-32a)
  - spool-file worker IPC closing todo 339 (paths and row counts across the pool boundary)
  - feature_vector_v2_row_values / feature_vectors_v2_columns, the v2 row contract pinned to the 186-24 migration
  - rebuild unit-design helpers (split_symbol_chunks, rebuild_unit_ranges, unit_fetch_start, unit_code_key)
  - APR keys infra.feature_factory.rebuild_symbols_per_chunk / max_unit_rows (migration 428) / rebuild_block_rows (migration 429)
  - services/rebuild_preconditions.py: seven pure D-32 checks plus run_all/RebuildPreconditionFailure and the two fetch helpers, for 186-26's first task
  - todos 339 and 476 closed
affects: [186-26, 186-27, 186-21]
key-files:
  created:
    - services/rebuild_preconditions.py
    - production/migrations/429_rebuild_block_rows.sql
    - tests/unit/test_rebuild_preconditions.py
    - tests/unit/intelligence/test_feature_vectors_v2_rows.py
  modified:
    - services/backfill_feature_factory.py
    - src/intelligence/features/feature_vector_persistence.py
    - production/migrations/428_rebuild_writer_apr.sql
    - tests/unit/services/test_backfill_feature_factory.py
    - tests/unit/intelligence/kernel_parity_reference.py
    - tests/unit/test_feature_factory_parallelism.py
    - tests/unit/intelligence/test_feature_factory_p7.py
    - tests/unit/intelligence/test_cross_tf_alignment.py
    - tests/unit/intelligence/test_legacy_featurevector_macro_fill.py
    - docs/foundation/glossary.md
    - .planning/todos/PRIORITIES.md
key-decisions:
  - "Compression deferred to the end of a clean full-scope run, not per (chunk, tf, year) group mid-run: a 1-year hypertable chunk spans every symbol chunk AND every tf of its year, so compressing when one group completes would make bulk_load refuse the later groups' units (186-06). End-of-run compression never leaves resume traffic facing a compressed chunk with pending units, which is the threat the group-keyed design guarded against (T-186-25-05)"
  - "The digest pass runs in the main process from bar statistics plus month content digests (two cheap grouped queries), not as a worker pass: no bar is fetched and no kernel runs, so a fully completed group costs two queries"
  - "The worker computes each (symbol, tf) series once from the series start: the contributing set of the full v2 column set includes path-dependent kernels (regime walk-forward, hurst, session VP), so unit_fetch_start resolves to the series start; pinned by test for the whole column set"
  - "The v2 row builder collapses None and NaN into one missing encoding (NULL): every v2 column is missing-or-value, unlike the legacy path where a mask-rebuilt None reached _guard. The 186-15 classes (nullable columns emit NaN plus an _<key>_is_none mask; never-None columns are plain floats) are preserved upstream in the kernels; the row layer writes NULL for both, never the text NaN and never a fabricated 0.0"
  - "The kernel parity reference (kernel_parity_reference.py) inlines the legacy compute_batch steps the deleted _compute_symbol_tf ran, so the golden digests are unchanged (D-25); the fixture is a historical pin, the v2 path is pinned by its own tests"
requirements-completed: [D-28, D-32a, R-10, D-24, D-01]
completed: 2026-10-01
---

# Phase 186 Plan 25: the rebuild writer and the D-32 precondition checker Summary

`run_rebuild_stage` is the single rebuild writer for feature_vectors_v2: units of (symbol chunk, tf, calendar-year range) keyed by provenance_batch records, workers that return spool paths and row counts instead of rows (todo 339), one compute_kernels pass per series with regime in the same pass, and every write through bulk_load; services/rebuild_preconditions.py turns every D-32 gate into a pure, tested check for 186-26 to run before launch. The rebuild itself was never launched.

## Commits (branch phase-186-25)

- 357221e85 feat(186-25): v2 row contract, rebuild unit design, APR keys (migration 428)
- 2770851da refactor(186-25): move FeatureCache and its pure helpers into the kernels package (todo 476)
- 2aee41215 feat(186-25): rebuild writer on provenance-keyed units and bulk_load (D-28, D-32a, todo 339)
- a924e5f6f chore(186-25): close todos 339 and 476
- 3648c4a13 chore(186-25): drop the pending todo paths closed by a924e5f6f
- cb1ee49fe feat(186-25): D-32 rebuild precondition checker (consumed by 186-26)

Plan Task 3's merge/push steps are deferred to the coordinator (no merge, no push, no worktree removal from this executor).

## D-01 gate

`ps aux | grep -E "ic_engine|backfill_feature_factory|regime_writer|feature_vector_rebuild|ic_measure" | grep -v grep` returns nothing (re-checked 2026-10-01 after the session restart), and STATE.md's lane table shows no live or resumable ic_engine corpus run or feature rebuild. The todo 449 backfill lane runs in another session against market_data_ohlcv; this plan wrote no bars and took no schema locks beyond migration applies.

## Unit design (the constants 186-26 needs)

- Chunk size: `infra.feature_factory.rebuild_symbols_per_chunk` = 25 (migration 428, fallback 25). Units are (25-symbol chunk, tf, calendar-year [Jan 1, Jan 1)); tf 1d runs one range per chunk (first bar to horizon). Changing the chunk size renames every unit, so a resumed run recomputes.
- Row bounds: `infra.feature_factory.max_unit_rows` = 1,000,000 (min 10,000) refuses an oversized unit before any write; `infra.feature_factory.rebuild_block_rows` = 10,000 (migration 429) bounds the worker's fetch/spool block (about 30 MB at 5m).
- Data horizon: default the first day of the current UTC month (whole months only; the bar content digest is month-granular). A resume must pass the same `--data-horizon`.
- Warmup: `unit_fetch_start` subtracts the max declared memory over the contributing kernels, converted with the registry's own tf conversion; `test_every_externally_fed_kernel_declares_memory_in_the_consuming_tf` pins the D-26 denomination contract (externally fed kernels declare memory in the consuming tf's bars, 0..3). No kernel in the registry is unconditionally series-start-expanding: the full v2 column set pins the fetch at the series start only through its path-dependent contributors (regime, hurst, session VP, AMD), which is the resolution the worker computes from.

## The old compute path is deleted (D-08 greps)

Deleted from services/backfill_feature_factory.py: `run_compute_stage`, `_run_compute_worker`, `_compute_symbol_tf`, `_batch_insert`, `_load_fv_row_counts`, `_theoretical_max`, `_pct`, `_vector_to_params`, `_mark_cell_failed`, `_log_coverage_report`, `_MARK_COMPUTE_*_SQL`, `_SELECT_FV_ROW_COUNTS_SQL`, `_INSERT/_UPSERT_FEATURE_VECTORS_SQL`, `--refresh`, `--pipeline-version`. Repo-wide grep of tests/ scripts/ src/ services/ for each name: the only referencing files were tests in this repo's own suite, all fixed or rewritten in commit 2aee41215 (test_feature_factory_p7 repointed to feature_vector_to_insert_params; test_feature_factory_parallelism rewritten for _rebuild_worker's contract; the stale CTF period-start-sharing test in test_cross_tf_alignment deleted with the mechanism; kernel_parity_reference inlines the legacy batch steps). Ops scripts referencing the compute stage (scripts/ops/corpus/ops_ctf_columns_recompute_15m.py, ops_known_corrupt_print_cleanup.py) are 186-21's scope, untouched: their imports (`_build_feature_factory_config`, `_connect_db`, `_fetch_bars_from_db`, `_load_config_service`) all still exist.

`grep -vn '^\s*#' services/backfill_feature_factory.py | grep -cE "(INSERT INTO|UPDATE|COPY) feature_vectors([^_]|$)"` = 0; `grep -c "regime_writer"` = 0; `validate_feature_vector|build_feature_vector_row` = 0 on non-comment lines; `--refresh` gone. Non-flag "refresh" matches kept and listed: `regime_cache_refresh_bars` (a FeatureFactoryConfig field the kernels require) and one docstring mention of the statistics-refresh kernel family. The fetch stage (market_data_ohlcv writes, backfill_status fetch checkpoint) is untouched, phase 185's disposition.

## None/NaN policy on the v2 path

The kernels keep 186-15's classes: a nullable helper emits NaN plus an `_<key>_is_none` mask; never-None columns are plain floats. `_compute_series_columns` applies the mask and the declared-memory warmup, then `_clamp_real_array` applies the real-column clamp bulk_load applies; `feature_vector_v2_row_values` writes NaN as None, so the spool carries an empty field and Postgres stores NULL. Early-history macro NaN (vix_z through rate_beta_z before the first daily record, tip_tlt_ret_z and hyg_lqd_ret_z on the first record date) is expected data: NULL, never the text NaN, never 0.0. The legacy `_guard(..., 0.0)` re-fabrication stays quarantined inside FeatureFactory for the live pipeline until the 186-27 swap (todo 463); test_legacy_featurevector_macro_fill.py now pins that quarantine instead of the rebuild's behavior, and the rebuild source-greps prove the legacy row builders are never imported.

## Kill-and-resume procedure (D-32a, mirrored from the module docstring)

    kill <main_pid>
    ps -eo pid,cmd | awk '/backfill_feature_factory/ && !/awk/ {print $1}' | xargs kill
    # confirm zero remain, then terminate a leftover COPY backend:
    #   select pid from pg_stat_activity where state='active' and wait_event='ClientWrite'
    #     and query like 'COPY feature_vectors_v2%';
    #   select pg_terminate_backend(<pid>);

Relaunch the same command: completed units are skipped via provenance_batch, a killed unit left a started record and zero rows (the COPY and the completed record commit together) and is retaken. Never edit this module, the kernels, or anything they import while a run is live or resumable: the unit code key hashes them.

## Todos closed

- 339: spool-file option (b); per-unit worker dispatch rejected because one compute pass per (symbol, tf) shared across the group's units amortizes the externals construction and kernel compute under memory-bounded warmup (note in completed/339-*.md, commit 2aee41215).
- 476: kernels-package helper move, landed in 2770851da; no kernel imports the legacy cache (grep clean, golden digests bit-identical).

PRIORITIES.md rows removed, build-lane note updated; test_todo_priorities_link_integrity green.

## TDD gate compliance

Task 2 (tdd=true): the RED line was observed indirectly. The writer code arrived as the dead session's WIP, so the tests were written against that WIP and first ran as a red batch: the pruned test file failed on the still-wired old CLI (run_compute_stage references) and the new tests failed stage-by-stage (9 failures) while the harness seams were completed; each fix flipped its test to green within the same working session, so there are no separate test()/feat() RED/GREEN commits for task 2. Task 3 followed the cycle cleanly: tests/unit/test_rebuild_preconditions.py was written first and failed at collection (module absent), then the implementation turned all 22 tests green in one feat commit, per the task's own commit spec.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Group-keyed mid-run compression replaced with end-of-run compression**
- **Found during:** Task 2 reconciliation of the WIP against the plan's behavior block
- **Issue:** The plan's behavior pinned compression when a unit's (chunk, tf, calendar-year) group completes; a 1-year hypertable chunk spans every symbol chunk and every tf of its year, so compressing on one group's completion would make bulk_load refuse every other group's pending units in that chunk (186-06's refusal is by design)
- **Fix:** compression runs once at the end, only for a full-scope run with zero failed units; partial scope or any failed unit defers it; the stage summary records chunks_compressed and the per (tf, year) checklist
- **Files modified:** services/backfill_feature_factory.py, tests
- **Commit:** 2aee41215

**2. [Rule 3 - Blocking] Migration 429 added for rebuild_block_rows**
- **Found during:** Task 2 reconciliation
- **Issue:** the WIP reads infra.feature_factory.rebuild_block_rows with "(migration 429)" in its comment, but no migration 429 existed; an unseeded APR key would silently run on the fallback forever
- **Fix:** production/migrations/429_rebuild_block_rows.sql on the 375/428 shape, applied live (config_state value 10000 verified), committed with its apply
- **Commit:** 2aee41215

**3. [Rule 2 - Missing critical] main() and _parse_args still targeted the deleted compute stage**
- **Found during:** Task 2 reconciliation
- **Issue:** the WIP deleted run_compute_stage/_log_coverage_report but left main() calling them (NameError at runtime) and the --refresh/--pipeline-version flags in place
- **Fix:** main() calls run_rebuild_stage with --data-horizon (default the current month's first day); old flags removed
- **Commit:** 2aee41215

**4. [Rule 1 - Bug] Parity reference depended on the deleted _compute_symbol_tf**
- **Found during:** Task 2's D-08 grep
- **Issue:** kernel_parity_reference._compute_real imported the deleted function, breaking the golden-fixture tests and the capture script
- **Fix:** the legacy compute_batch steps inlined in _compute_real; golden digests verified unchanged (test_kernel_registry_parity green)
- **Commit:** 2aee41215

## Handoff to 186-26

- **Checker entry point:** `services.rebuild_preconditions.run_all(...)`; on `RebuildPreconditionFailure` the launch refuses and the message names every unmet gate. Checks are pure; supply measured inputs:
  - coverage: `fetch_coverage_inputs(conn, tfs, symbols)` (reads market_data_ohlcv_tradeable only, 10 min statement timeout) plus `expected_spans` built from the todo 449 fetch-depth contract; `ohlcv_empty_history` spans are inputs, not errors
  - markers: `fetch_landed_markers(conn)` returns the dependency markers plus `grid_marker` (the STATE.md "D2b landed" bullet 185-12 writes)
  - todo 445 record: `{"decision": "keep_5m", "rebuild_timeframes": ["15m","1h","1d","5m"]}` from completed/445-*.md (186-07's result JSON); must equal the writer's configured tf set
  - disk (R-09): pilot-measured projected compressed bytes, largest uncompressed chunk working set, free bytes, reserve bytes, and the margin 186-26 states (the checker takes it as a parameter; no APR key)
  - no-live-run: `ps aux` lines plus any resumable-run evidence from logs
- **Launch command shape:** `python services/backfill_feature_factory.py --compute-only [--data-horizon YYYY-MM-DD]` (workers from APR infra.feature_factory.workers; `--symbols`/`--tf` for a pilot chunk; a partial scope defers compression, so the full-scope run is what compresses).
- **Order:** the rebuild must not launch until run_all passes AND the 186-22/186-23 drops have landed (check_drops_landed fails otherwise). After a clean full-scope run, 186-27 verifies "all chunks compressed" from the stage summary's chunk checklist.
- **The rebuild was never run by this plan:** feature_vectors_v2 still has zero rows and provenance_batch has no completed backfill-feature-factory rows.

## Verification

- `pytest tests/unit/services/test_backfill_feature_factory.py tests/unit/test_bulk_load.py tests/unit/test_todo_priorities_link_integrity.py tests/unit/intelligence/test_feature_vectors_v2_rows.py tests/unit/intelligence/test_feature_vectors_v2_schema.py tests/unit/intelligence/test_kernel_registry_parity.py tests/unit/intelligence/test_cross_tf_alignment.py tests/unit/intelligence/test_legacy_featurevector_macro_fill.py tests/unit/test_feature_factory_parallelism.py tests/unit/intelligence/test_feature_factory_p7.py tests/unit/intelligence/test_feature_factory_batch.py tests/unit/intelligence/test_compute_batch_window_slicing.py tests/unit/test_feature_vector_persistence_completeness.py tests/unit/test_market_data_ohlcv_writer_boundary.py tests/unit/test_ibkr_history_lease_boundary.py -q`: green (154 tests).
- Full `pytest tests/unit/ -q`: exit 0, 7907 collected, 0 collection errors.
- Live DB: three infra.feature_factory.rebuild_* keys present (428 + 429 applied); no rebuild rows anywhere.
- ruff and black clean on every touched file; pre-commit's 9 checks passed on all six commits.
- No edit under src/intelligence/research/ (D-02): branch diff contains none.

## Threat surface scan

Nothing beyond the plan's threat register. The writer adds no endpoint, no auth path, and no new schema; its only new surface (the spool directory under logs/rebuild_spool, main-process-owned, purged at stage start and per-group cleanup) is local derived data, rebuildable.

## Self-Check: PASSED

All six branch commits found in git log; every created file exists on disk; the working tree is clean except this SUMMARY file, committed below.
