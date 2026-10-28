---
phase: 184-multi-timeframe-research-inputs
plan: 04
subsystem: research S0
tags: [feature-read, provenance, warmup, coverage, read-boundary, todo-435]
requires: [184-02 (ordering only, PRIORITIES.md rows)]
provides:
  - src/intelligence/research/feature_inputs.py (S0 pure feature-read decisions, B1d-B1j)
  - tests/unit/test_feature_vectors_read_boundary.py (B1k CI read boundary)
affects: [184-07 (check_intraday_vendors), 184-08 (S0 wiring), 184-09, 184-10, 184-12]
tech-stack:
  added: []
  patterns: [pure decide-and-refuse over fetched rows, hash-only config pin, per-file grep allow-list]
key-files:
  created:
    - src/intelligence/research/feature_inputs.py
    - tests/unit/research/test_feature_inputs.py
    - tests/unit/test_feature_vectors_read_boundary.py
    - .planning/todos/pending/554-remove-legacy-feature-vectors-research-readers.md
  modified:
    - .planning/todos/PRIORITIES.md
decisions:
  - "Row presence, not finite value, drives warmup and coverage: scatter_rows keeps its 2-tuple and a separate present_mask(rows, timestamps, symbols) feeds warmup_mask(..., present=) and coverage_check(..., present=), so the mask is idempotent with the rebuild's own NULL warmup rows"
  - "B1j rebuild identity is (writer 'backfill-feature-factory', target_table 'feature_vectors_v2'), the 186-26 writer's _JOB and _V2_TABLE"
  - "feature_config re-checks the block's projection hash and coerces only containers (lists to tuples, dicts to nested dataclasses through their constructors); scalars stay as stored so the projection hash round-trips"
  - "Boundary grep matches multi-segment suffixes (feature_vectors(?:_[a-z0-9]+)*) and keeps FROM/JOIN case-sensitive, so prose 'from feature_vectors' in docstrings does not count"
metrics:
  duration: about 9 h wall, mostly waiting on shared repro_frozen and compare-all runs
  completed: 2026-10-28
---

# Phase 184 Plan 04: Feature-read decisions and read boundary summary

S0's feature read now has a pure module that decides and refuses, naming the rule id each time. It allow-lists columns against the registry before any SQL (B1e), scatters by exact (bar_ts, symbol) to float32 [t, i] (B1e), pins provenance over completed batches only (one code_key, whole-projection agreement, hash-only pin; B1f), and rebuilds the one FeatureFactoryConfig, nested HmmConfig included, from the verified projection. It masks warmup by row presence and refuses path-dependent columns (B1g), applies the coverage floor through `feature_tf_quality` (B1h), allows HMM regime columns only from the 186-26 rebuild (B1j), and accepts only derived 5m-grid bars at 15m and 1h (B1d). A CI grep boundary fails any new `feature_vectors` reader that is not on the allow-list (B1k).

## Commits

| Task | Commit | Files |
|---|---|---|
| 1 feature_inputs pure helpers | b80a0277c | src/intelligence/research/feature_inputs.py, tests/unit/research/test_feature_inputs.py |
| 2 read boundary and todo 554 | 57d37953a | tests/unit/test_feature_vectors_read_boundary.py, .planning/todos/pending/554-remove-legacy-feature-vectors-research-readers.md, .planning/todos/PRIORITIES.md |

## Interface for 184-07/08/09/10

`FeatureInputRefused(ValueError)`, `FEATURE_TABLE`, `PROVENANCE_TARGET_TABLES`, `REBUILD_WRITER`, `REBUILD_TARGET_TABLE`, `PROVENANCE_SQL` ($1 target tables, $2 tf, $3 start, $4 end; also selects `status`), `check_columns(names, registry)`, `feature_select_sql(names, registry=None)`, `scatter_rows(rows, timestamps, symbols, names) -> (arrays, unmatched)` with rows shaped `(symbol, bar_ts, *values)`, `present_mask(rows, timestamps, symbols)`, `config_projection`, `config_projection_hash`, `provenance_pin(...)` (block keys: span, batch_keys, code_key, apr_hashes, input_digests, writers, target_tables, projection, projection_hash), `feature_config(block)`, `column_memory_bars(column, config, registry)`, `refuse_path_dependent`, `warmup_mask(values, memory_bars, *, present)`, `coverage_check(values, symbols, *, present, feature, tf, floor)`, `refuse_regime_columns(columns, registry, batches)`, `check_intraday_vendors(tf, vendor_kinds)`, `feature_array_name(tf, column)`.

## Verification

- `tests/unit/research/test_feature_inputs.py`: 39 passed; each of `-k round_trip, unpinned, config, columns, scatter, provenance, warmup_mask, coverage, hmm, vendor, hash` selects passing tests.
- `tests/unit/test_feature_vectors_read_boundary.py`: 3 passed. Fail-closed probe: with `scripts/research/_tmp_fv_probe.py` containing `SELECT x FROM feature_vectors`, the first test failed with `AssertionError: New `feature_vectors` reader(s) found, not on the allow-list: {'scripts/research/_tmp_fv_probe.py'}. ...`; the scratch file was deleted.
- `.venv/bin/pytest tests/unit -k priorities -q`: passed.
- Acceptance greps on feature_inputs.py: `FeatureFactoryConfig()` 0, `ConfigService` 0, `SELECT *` 0, asyncpg/measure/services imports 0, `status = 'completed'` 1. ruff, black, mypy clean for the file.
- Full unit suite in the main checkout: `6 failed, 7095 passed, 1 skipped`. The failures are in `tests/unit/intelligence/test_liquidity_kernels.py` and, on an earlier run, 8 registry/schema tests (`test_kernel_registry`, `test_feature_kernels`, `test_feature_vectors_v2_rows`, `test_feature_vectors_v2_schema`) asserting on `roll_spread`/`high_low_spread`. All of them come from another agent's uncommitted todo 553/390 kernel work (`kernels/liquidity.py`, registry, schema and volume.py edits), not this plan. In a detached-HEAD scratch worktree at HEAD, the registry, schema and both 184-04 test files all passed; that worktree was then removed.

### B7 trio (verbatim)

repro_frozen, run in the shared detached worktree `wt_cmp` at d47174891 (contains b80a0277c and 57d37953a), exit 0:

```
phase 179 S3: bit-identical [ 0.21612308 -0.14601638 -0.10558864]
phase 181 S2 (signal from Panel): bit-identical
phase 181 S3: bit-identical [0.19424572]
```

`tests/unit/research/test_spec_hashes_pinned.py`: 8 passed.

compare-all: per the coordinator, the shared run by the 184-03 executor covers this plan; it is cited verbatim from its result file:

```
Shared 184 compare-all (covers 184-01..04 code)
start 2026-10-28T06:53:40Z at d4717489105df8b511f76b24710d0b8537345103
     16 "outcome": "equal"
      4 "outcome": "pre_e17"
log: logs/research/series_backfill_2026-10-28T11:26:10.035417Z.json
exit=0
```

## Deviations from plan

1. [Rule 1 - Bug] Presence mask added. As written, `warmup_mask(values, memory_bars)` with presence taken from finite values masks more rows each time it is applied, so it cannot be idempotent with the rebuild's own NULL warmup rows. The fix adds `present_mask` plus a required `present=` keyword on `warmup_mask` and `coverage_check`, and coverage's denominator ("symbols with any row") also needs that mask. `scatter_rows` keeps the planned 2-tuple. 184-08 must pass `present_mask(...)` (184-08's interface text lists the old signatures).
2. [Rule 3] Duplicate test name. Pre-commit's duplicate-test check rejected `test_allow_list_has_no_stale_entries` (the ohlcv boundary test uses the same name). It is renamed `test_feature_vectors_allow_list_has_no_stale_entries`.
3. Boundary pattern broadened to multi-segment suffixes (`(?:_[a-z0-9]+)*`), so names like `feature_vectors_v2_old` also count. `test_legacy_entries_name_removal_todo` requires a pending removal todo only while a `scripts/research/` entry exists, so closing todo 554 does not break it.
4. Commits. The plan's single end-of-plan commit became one commit per task, as the executor protocol requires. TDD RED was not committed separately: tests and implementation landed in the Task 1 commit.
5. `ops_oos_holdout_eval.py` (scripts/ops) evaluates features against forward opens outside the runner. Its allow-list reason names todo 554, which covers it alongside the two `scripts/research/` readers.

## Threat model

T-184-13 to T-184-17 are mitigated as planned (allow-list before quoting plus a quote-injection test; completed-only, whole-projection, hash-only pin with a round-trip test; config from the verified projection only; presence-based warmup and path-dependent refusal; regime refusal; CI grep). No new surface.

## Known stubs

None. Wiring into `snapshot.build_panel` is 184-08 by design.

## Self-Check: PASSED

Files exist: feature_inputs.py, test_feature_inputs.py, test_feature_vectors_read_boundary.py, todo 554. Commits b80a0277c and 57d37953a are on main and origin/main.
