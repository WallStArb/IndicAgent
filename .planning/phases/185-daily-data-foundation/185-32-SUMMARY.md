---
phase: 185-daily-data-foundation
plan: 32
subsystem: bars
tags: [synthetic-fill, migration-444, ci-guard, provider-matrix, gap-closure]
requires: [185-27, 185-31]
provides:
  - "market_data_ohlcv CHECK constraint market_data_ohlcv_no_synthetic_fill (migration 444, live)"
  - "tests/unit/test_market_data_ohlcv_no_synthetic_fill.py: AST guard on normalize_bars calls and synthetic_fill builds and references"
  - "provider matrix in docs/foundation/canonical-truth-registry.md"
  - "todo 499 (phase 189 handoff)"
affects: [185-39, 185-43, 186-26, 189-08]
tech-stack:
  added: []
  patterns: ["AST allow-list guard: calls and row builds, not text mentions; stale entries fail"]
key-files:
  created:
    - production/migrations/444_market_data_ohlcv_no_synthetic_fill.sql
    - tests/unit/test_market_data_ohlcv_no_synthetic_fill.py
    - .planning/todos/pending/499-drop-normalize-bars-and-move-gap-readers-to-coverage-ledger.md
  modified:
    - scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py
    - scripts/infrastructure/backfill/ibkr_history_fetcher.py
    - services/backfill_feature_factory.py
    - src/core/bar_normalizer.py
    - docs/foundation/canonical-truth-registry.md
    - .planning/todos/PRIORITIES.md
    - tests/unit/scripts/test_run_historical_pipeline.py
    - tests/unit/scripts/test_historical_pipeline_d1_capture.py
    - tests/unit/scripts/test_history_fetch_item.py
    - tests/unit/services/test_backfill_feature_factory.py
    - tests/unit/test_market_data_ohlcv_boundary.py
    - tests/integration/test_market_data_ohlcv_tradeable_view.py
decisions:
  - "CHECK constraint, not a trigger: TimescaleDB 2.27.1 accepts ADD CONSTRAINT on the compressed hypertable; it is NOT VALID in the catalog because VALIDATE is refused on columnstore hypertables, but the ADD checks existing chunk rows (scratch rehearsal)"
  - "A NULL source stays allowed (IS DISTINCT FROM), matching the 185-25 swap's definition of a real row"
  - "ibkr_history_fetcher.py's --normalize removed (Rule 3) rather than leaving a call to the deleted run_normalize"
metrics:
  duration: "about 1 h 15 min"
  completed: 2026-10-07
---

# Phase 185 Plan 32: synthetic-fill fences and the provider matrix Summary

`market_data_ohlcv` now refuses a synthetic_fill row at the database (migration 444, applied live). An AST CI guard fails any new `normalize_bars` call or synthetic_fill row build. The historical pipeline's `--normalize` mode and its last fill branch are deleted. `backfill_feature_factory`'s fetch stage stores raw 5m and 1m bars only. The canonical truth registry gains a provider matrix.

## Commits

| Task | Commit | What |
|---|---|---|
| 1 RED | c733e7d01 | failing CI guard, pipeline tests (4h real bars only, `--normalize` no longer parses), fetch-stage tests, migration 444 contract |
| 1 GREEN | 1d8cd69be | migration 444 (applied live), pipeline edits, fetch-stage edit, fetcher `--normalize` removal, normalize_bars docstring, test restatements |
| 2 | c1ba75c5f | provider matrix, canonical 1d lineage sentence, todo 499 and its PRIORITIES row |

## Task 1: removed and fenced

**Historical pipeline (`infrastructure_run_historical_pipeline.py`), the three named edits and nothing else:**
1. `run_normalize`, the `--normalize` argument and its dispatch are deleted.
2. `"4h"` joins `_REAL_BARS_ONLY_TFS`. The comment above it and `real_bars_only_for`'s docstring are updated.
3. The dead `normalize_bars` branch is removed. `store_bars` now takes `bar_dicts` directly (the `canonical` variable is gone). The `SOURCE_SYNTHETIC_FILL` and `normalize_bars` imports are removed; `SOURCE_DERIVED_1M` stays.

`grep -n "run_normalize\|--normalize"` on the pipeline returns nothing. `grep -n "normalize_bars\|SOURCE_SYNTHETIC"` returns only the three comments at lines 803, 1915 and 1922. The CI guard is AST-based, so these comments do not count.

**`services/backfill_feature_factory.py` (phase 186 file, cross-phase edit named in the commit):**
- `run_fetch_stage` stays, because `--fetch-only` still dispatches it.
- Its `normalize_bars` import and call are gone. It stores the provider's bars as they arrived.
- New `_FETCH_STAGE_TIMEFRAMES = {"5m", "1m"}`. After the existing derivation-owned fence (which drops or refuses 1d, 15m and 1h), any timeframe outside that set raises `ValueError`.
- The no-live-rebuild check ran before each covered edit and was clean both times:
  - before this file: no `backfill_feature_factory` process, zero `provenance_batch` rows targeting `feature_vectors%`, `feature_vectors_v2` empty;
  - again before `bar_normalizer.py`: same result.
- The recent `logs/backfill_feature_factory.log` lines come from unit-test runs: 3 synthetic symbols, `code_key a70a4864d51e`.

**`src/core/bar_normalizer.py`:** docstring only. It says `normalize_bars` is retired for `market_data_ohlcv`, names its last caller and todo 499, and points to the CI guard.

**CI guard (`tests/unit/test_market_data_ohlcv_no_synthetic_fill.py`)** scans `services/`, `scripts/` and `src/` with `ast`:
- `normalize_bars` calls (name or attribute). Allow-list: `_history_fetch_item.py`, TEMPORARY, `retire: todo 499`.
- synthetic_fill row builds: a `"source":` dict entry, a `source=` keyword, or a `["source"] =` assignment. Allow-list: `bar_normalizer.py`, TEMPORARY, `retire: todo 499`.
- every other reference to `SOURCE_SYNTHETIC_FILL` or the `'synthetic_fill'` literal, docstrings excluded. Each needs a listed read or refusal reason. Listed: `intraday_raw_archive.py` (refusal and the copy filter 185-39 removes), `bar_reconciliation_audit.py`, `ops_real_rows_swap.py`, `ops_masked_slot_baseline.py`.
- Each allow-list also fails on stale entries.
- A self-test proves the detectors count calls but not comments or docstrings, and catch all three build forms.

Grep evidence (non-test `normalize_bars` calls after the plan): `services/backfill_feature_factory.py` 0, the pipeline 0. `_history_fetch_item.py:605` remains; it is the allow-listed call, unreachable now. `_empty_history.py:106` is a docstring mention, not a call; the guard ignores it, and the file was not edited.

**Database guard (migration 444).** `ls production/migrations` right before applying showed 443 and 445 and no 444.

Rehearsal on `indicagent_test`, using a scratch compressed hypertable shaped like the live one (segmentby symbol, timeframe; orderby timestamp; 5 compressed chunks), dropped afterwards:
- With a synthetic_fill row inside a compressed chunk, `ADD CONSTRAINT ... NOT VALID` was refused: `check constraint "scratch_no_synthetic" of relation "_hyper_49_113_chunk" is violated by some row`. So TimescaleDB checks existing chunk rows even under NOT VALID.
- Without the offender, the ADD succeeded in 5 ms. After that:
  - a synthetic_fill INSERT into a compressed chunk's range failed;
  - the same INSERT into a new chunk failed;
  - an UPDATE to synthetic_fill failed;
  - a real row and a NULL source inserted;
  - `compress_chunk` and `decompress_chunk` still worked.
- `VALIDATE CONSTRAINT` is refused: `operation not supported on hypertables that have columnstore enabled`.

Live apply:
- Before: zero synthetic_fill rows and no non-idle backends.
- The apply took 3.3 s under `lock_timeout 10s`.
- The constraint now sits on the parent and all 110 chunks (111 rows). All are `convalidated = f`, because VALIDATE is not possible. The rehearsal shows the ADD checks existing rows anyway, and the live count was 0.
- The migration is idempotent (applied twice on `indicagent_test`).

Live proof: inside `BEGIN ... ROLLBACK`, two synthetic_fill inserts failed (`new row for relation "_hyper_130_78769_chunk" violates check constraint "market_data_ohlcv_no_synthetic_fill"`, and the same on compressed-range chunk `_hyper_130_78675_chunk`, 2015). An `ibkr_named` insert at the same key succeeded and was rolled back. No trigger fallback was needed.

## Task 2: provider matrix

The new "Provider matrix" section comes after the Ownership Table. It has one row per provider and timeframe: IBKR 1d, Tradier 1d, IBKR 5m, 1m, 15m/1h and 4h, and Yahoo. Each row gives the route and source values, the D1, `ohlcv_load`/`ohlcv_revision`, `market_data_ohlcv` and archive writes, and the writer. Facts were checked against the live database on 2026-10-07:
- 1d observation routes: SMART (TRADES and ADJUSTED_LAST), AMEX, ARCA, BATS, ISLAND, NYSE, LEGACY_IMPORT, and TRADIER.
- `ohlcv_request` holds ibkr requests at 1m, 5m, 15m, 1h and 1d.
- Default scopes are `{"compute_1d": ["1d", "5m"]}`.
- Rows by timeframe and source: 4h has 2,184 `ibkr_named` rows. 15m and 1h still hold `ibkr_named` vendor rows next to `derived_5m` for names the grid stage has not replaced yet; the matrix says so.

The section also states that no synthetic_fill exists and names both fences, and gives the state of the three gap readers. The canonical 1d row now names both lineage rules, `d2-v1` and `tradier-v1`. Todo 499 is filed with its PRIORITIES row (Data and ingestion group, next to the other phase 189 items). The link-integrity test passes, and no em dash was added (`git diff -U0 docs/ | grep -cP "\x{2014}"` = 0).

## Verification

- Plan verify set, plus `tests/unit/scripts/`, the fetch-stage tests, and the three 185-44 guards (`test_temporary_allow_list_expiry.py`, `test_table_and_apr_key_readers.py`, `test_single_writer_registry.py`): all pass. The plan verify set is the guard, the pipeline test, the writer boundary, the read boundary, bar_normalizer, migration number uniqueness, the compressed-hypertable write boundary and the ibkr history lease boundary.
- Integration: `tests/integration/test_market_data_ohlcv_tradeable_view.py` passes with 444 in place.
- ruff and black are clean on every touched file. Pre-commit (9 checks) passed on all three commits.
- Full `.venv/bin/pytest tests/unit/ -q`: exit 0, about 8,137 passed, 5 skipped (pre-existing skips), 0 failures.

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 3 - Blocking] `ibkr_history_fetcher.py` called the deleted `run_normalize`.**
- Found during: Task 1.
- Issue: phase 189's fetcher had its own `--normalize` flag, whose `_normalize` method called `_pipeline.run_normalize`. Deleting `run_normalize` would have left a call that raises AttributeError.
- Fix: removed the flag, the dispatch and the method, nothing else (16 lines). The fetcher is stopped and disabled, and it stays so.
- The plan said not to edit 189 files; this is the one exception. It is recorded in todo 499. `Candidates.scope_contracts` now has no reader and is left for the 189 session.
- Commit: 1d8cd69be.

**2. [Rule 1 - Consequence of the named edit] Tests that encoded 4h's placeholder path.**
- `_history_fetch_item.py` reads `real_bars_only_for` from the pipeline, so adding 4h changes the fetcher item too. Its 4h fill branch is now unreachable, which the plan intends.
- Restated to match:
  - `test_each_timeframe_plans_through_its_shared_planner`: 4h now reads answered windows.
  - `test_placeholder_fill_is_stored_without_coverage` became `test_4h_stores_real_bars_only`.
  - `test_historical_pipeline_d1_capture.py`: dropped the monkeypatch of the pipeline's removed `normalize_bars` and its `normalized` assertions, and updated `test_real_bars_only_now_covers_1d` to assert 4h is True.
- Commit: 1d8cd69be.

**3. [Rule 1] Stale allow-list reason in `test_market_data_ohlcv_boundary.py`.** The pipeline's read-boundary reason described `run_normalize` and "creates and consumes its own synthetic fills". It was rewritten to the current truth. Commit: 1d8cd69be.

**4. [Rule 3] The integration fixture inserted a synthetic_fill row** (`test_market_data_ohlcv_tradeable_view.py`). Migration 444 replays above the integration baseline cutoff (433), so the row would be refused. It now has a NULL source with volume 0, and the test still passes. Commit: 1d8cd69be.

**5. Plan text vs. code: "refuses 1d, 15m and 1h" in the fetch stage** was already true through `_restrict_timeframes(refuse_derivation_owned=True)` (185-18). The new check adds a positive list (5m, 1m), so 4h and anything else are refused too. 1m stays unreachable in practice, because `_DEPTH_YEARS` has no 1m entry and the APR timeframe list is validated against it.

## Handoff to phase 189

- This plan deletes the pipeline's `--normalize` mode and adds 4h to `_REAL_BARS_ONLY_TFS`. 189-08's rename or retirement of `infrastructure_run_historical_pipeline.py` inherits both. `ops_head_rerun.py` (185-28) invokes the pipeline by path, and so did the nightly (deleted in 189-07).
- Edited in 189 files: `ibkr_history_fetcher.py` lost `--normalize` and `_normalize` (deviation 1). Two `test_history_fetch_item.py` tests were restated (deviation 2).
- Todo 499 holds the follow-ups:
  - drop `normalize_bars` from `_history_fetch_item.py`;
  - delete the fill path and both TEMPORARY allow-list entries;
  - drop `scope_contracts` if it is unused;
  - move the 5m/1m placeholder-coverage gap readers onto `ohlcv_coverage`.

## Known Stubs

None.

## Threat Flags

None. The plan's threat register is covered: T-185-32-01 by 444 plus the CI guard; T-185-32-02 because the lane is deleted (189-07), the pipeline tests pass, and the 1h/15m path was untouched; T-185-32-03 by the clean no-live-rebuild checks.

## Self-Check: PASSED

- Files exist: migration 444, the CI guard test, todo 499.
- Commits exist: c733e7d01, 1d8cd69be, c1ba75c5f.
- Live constraint present on the parent and 110 chunks; a synthetic_fill insert inside BEGIN/ROLLBACK fails.
