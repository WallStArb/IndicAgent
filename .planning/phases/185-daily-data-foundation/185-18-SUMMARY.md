---
phase: 185-daily-data-foundation
plan: 18
subsystem: bars
tags: [d2, single-writer, d1-only, gap-planner, historical-apply]
requires: [185-09, 185-12, 185-17]
provides:
  - shared gap planner (gap_plan.py, _d1_gaps.py) with answered-window coverage, real 5m/1m bars by default
  - D1-only 1d backfill path, writer fences, CI guards (D2 is the sole 1d writer)
  - nightly daily derivation stage behind the lane guard
  - historical D2 apply: 931 names, canonical_bar_lineage 3,877,335 rows at d2-v1
  - integration baseline regenerated at cutoff 433 (todo 486)
affects: [185-19, 186-26, 189-04]
key-files:
  created:
    - production/migrations/435_bar_derivation_writer_update_1d.sql
    - tests/integration/test_d2_single_writer_live.py
    - tests/integration/test_d2_excludes_test_caller_observations.py
    - tests/integration/test_d2_writer_can_upsert_1d.py
    - tests/integration/fixtures/seed_config_2026-10-02.sql
    - .planning/todos/pending/490-grid-stage-archive-verify-fails-on-revised-bars.md
  modified:
    - services/bar_derivation.py
    - scripts/infrastructure/backfill/infrastructure_nightly_backfill.py
    - scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py
    - tests/integration/conftest.py
decisions:
  - Migration 435, not a reserved number: 434 belongs to 189-08 and 404-408 to other 185 plans.
  - The writer grant is table level because a column grant cannot propagate to the compressed hypertable.
  - D2 provenance-excludes observations whose request caller starts with test-; D1 is append-only, so rows a test already appended cannot be removed.
  - One stored bar with no D1 observation (TLT 2026-10-01, written by the pre-fence nightly) is a registered, self-checking exception in the live test; the next sanctioned 1d fetch of TLT heals it.
metrics:
  tasks: 4
  completed: 2026-10-03
---

# Phase 185 Plan 18: D2 sole 1d writer and historical apply Summary

D2 now writes every 1d bar and has derived the whole history. The pilot (SPY, AAPL, MRNA,
ALMS, IWO: 59 changed bars, equal to the dry-run total for those names) and then all 931
1d-eligible names ran with 0 failures; the full apply took 200 s and changed 5,674 bars, which
is the report's 5,733 less the pilot's 59.

## Results

- Gap planning (task 1a) and the D1-only 1d path with writer fences and CI guards (task 1b)
  landed 2026-10-02; the /simplify gate followed (shared derivation-owned timeframe set, one
  empty-history rule, one stage runner).
- Task 0 (todo 486): the integration baseline is regenerated at cutoff 433. The schema-only
  dump needed more than a regeneration: `config_schema` and `config_state` are a fourth seed,
  and the hypertables file drops the `_compressed_hypertable_N` stubs the dump restores before
  it re-registers compression. Closed todo 486.
- Task 2: live acceptance. Stored 1d bars with volume and a canonical source and no lineage:
  1 (TLT 2026-10-01, see decisions), 0 otherwise; `bar_derivation_batch` has completed daily
  batches; sources on 1d are `ibkr_named` and `synthetic_fill` only. The live test
  `test_d2_single_writer_live.py` checks lineage coverage, canonical sources, stored values
  against a D1 recompute for 10 seeded symbols, digest coverage and the split seam (vacuous:
  `corporate_action_current` is empty).

## Deviations

- Fixture rows would have become canonical bars. `test_ohlcv_observation_store` appended
  permanent synthetic SPY observations to the live D1 ledger on every run, and D2 takes the
  latest observation per bar; the pilot dry run showed SPY at 33 changed bars against the
  report's 30, and `derive_daily` would have stored SPY 2024-01-02 at close 100.5 (real
  472.65). Fixed three ways before any apply: the test runs against `indicagent_test`, D2's
  observation select and changed-since probe exclude `test-` callers, and a test proves it.
  The rows already in production stay (D1 is append-only).
- The daily stage could not write. Migration 383 granted the writer SELECT, INSERT, DELETE on
  `market_data_ohlcv` and the daily upsert needs UPDATE; the first pilot apply failed every
  symbol with permission denied and wrote nothing. Migration 435 grants it, with an
  integration test that runs the real upsert under the real role.
- `test_nightly_lease` patched only the daily stage, so full unit runs spawned a real
  `bar_derivation.py --stage grid --apply` against the live database (nine runs on
  2026-10-03, the first derived 74 symbols through the normal idempotent changed-only path).
  It now patches the stage trio. The same runs exposed todo 490: the grid stage fails every
  night for 7 symbols whose 2026-09-28 to 10-01 bars were observed twice inside IBKR's revision
  window, which the first-write-wins archive cannot hold.

## Open

- Todo 490 (P1): decide archive-as-observation-history or a settle window before 189-04.
- `test_ic_parity_replay` and `test_bar_quality_flag_quarantine` read the live database and
  are red for unrelated reasons (dropped `forward_returns`; a migration 381 snapshot that 185-12
  moved). `tests/unit/scripts/test_ohlcv_coverage_atomic_write.py` is a unit test that writes
  to the live database with a self-cleaning sentinel; it leaves no rows today.
- 186-26 can launch on 185's side; todo 489 still owns adding `check_d2_landed` to its
  preconditions.
