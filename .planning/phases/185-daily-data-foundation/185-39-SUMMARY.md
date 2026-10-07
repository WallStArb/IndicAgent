---
phase: 185-daily-data-foundation
plan: 39
subsystem: data-integrity
tags: [write-contract, ingress, ibkr, ohlcv_revision, ohlcv_load, content-digest, d1-elision]
requires: [185-31, 185-32, 185-38]
provides:
  - "services/ohlcv_ingress_contract.py: apply_ingress_contract, RevisionRefused, record_refused_load (the IBKR ingress write contract)"
  - "ohlcv_request.content_digest (migration 448) stamped by persist_chunk_atomically"
  - "market_data_ohlcv, the archive and IBKR D1 observations written new-and-changed-only, with replaced values in ohlcv_revision"
  - "tests/unit/test_bar_write_no_first_write_wins.py (CI scan) and tests/integration/test_ingress_write_contract.py"
affects: [185-40, 185-42, 189-08, 189-10]
key-files:
  created:
    - production/migrations/448_ingress_write_contract.sql
    - services/ohlcv_ingress_contract.py
    - tests/unit/services/test_ohlcv_ingress_contract.py
    - tests/unit/test_bar_write_no_first_write_wins.py
    - tests/unit/test_ingress_write_contract_migration_contract.py
    - tests/integration/test_ingress_write_contract.py
  modified:
    - scripts/infrastructure/backfill/_intraday_persist.py
    - scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py
    - services/intraday_raw_archive.py
    - services/ohlcv_observation_writer.py
    - tests/unit/scripts/test_intraday_persist.py
    - tests/unit/scripts/test_run_historical_pipeline.py
    - tests/unit/services/test_intraday_raw_archive.py
    - tests/unit/services/test_ohlcv_observation_writer.py
    - tests/unit/test_ohlcv_load_revision_writer_boundary.py
  moved:
    - tests/unit/scripts/test_ohlcv_coverage_atomic_write.py -> tests/integration/test_ohlcv_coverage_atomic_write.py
decisions:
  - "The compare-and-write plumbing is one shared module (services/ohlcv_ingress_contract.py); each bar table keeps its own INSERT in its owner module (pipeline for market_data_ohlcv, intraday_raw_archive for the archive), passed in as callbacks, so no single-writer boundary moves"
  - "n_stored for the refusal ratio is the count of stored rows at the chunk's incoming keys (the rows the chunk could revise), not the series total"
  - "A refused chunk records its request rows with content_digest NULL: the column means what the chunk stored, and a refusal stores nothing"
  - "IBKR D1 elision lives in the observation sinks and applies to source ibkr, non-test callers only; the Tradier loader keeps its own elision and refusal logic"
metrics:
  completed: 2026-10-07
---

# Phase 185 Plan 39: Ingress write contract Summary

Every IBKR ingress write of market_data_ohlcv (5m, 1m), the raw archive (15m, 1h parity sample) and D1 (1d observations) now reads the stored rows for its keys, writes only new and changed rows, records the old values of changed rows in ohlcv_revision under one ohlcv_load row (source ibkr), and refuses a chunk that revises more than `threshold.bar_integrity.max_revision_ratio` of at least `revision_ratio_min_stored` stored rows. No phase 189 file was edited: `_history_fetch_item.py` still injects `_insert_market_data_rows` and `_insert_archive_rows`, which are now the contract writers.

## Commits

- 79d99c374: migration 448, the shared contract module, the pipeline's market_data_ohlcv path, request digests, CI scan, the live-DB atomic-write test moved to indicagent_test
- a8a1120d3: archive contract, ARCHIVE_FROM_TABLE_SQL without first-write-wins, IBKR D1 elision
- 0379a8cf8: integration test under the real roles on indicagent_test

## What changed

- **Contract module.** `apply_ingress_contract(cur, rows, destination, caller, write_new, write_changed)` groups the chunk by series, reads stored rows at the incoming keys, classifies with `write_contract.classify` (removal scope None), raises `RevisionRefused` before any write on a breach, and otherwise writes the load row, the revision rows and then the new and changed rows. It returns the rows offered, which the persist helper's coverage arithmetic needs.
- **Pipeline.** `_STORE_VALUES_SQL` is a plain multi-row INSERT of new rows; changed rows use `INSERT ... ON CONFLICT (timestamp, symbol, timeframe) DO UPDATE` restricted to the changed set (no raw UPDATE, so the market_data_ohlcv boundary allow-list stays empty). The three comments that described ON CONFLICT DO NOTHING are corrected.
- **Persist helper.** Computes the chunk digest (`bar_content_digest` arithmetic, one row per timestamp, last wins) and stamps each request row that answered with bars. On `RevisionRefused` the transaction rolls back, then a second transaction records the request rows and an ohlcv_load row with outcome refused (detail: changed / stored = ratio > max, new and unchanged counts) and re-raises, so the item fails through phase 189's existing retry and `max_consecutive_failures` path.
- **Archive.** `insert_fetched_archive_rows` writes through the contract (destination archive). `ARCHIVE_FROM_TABLE_SQL` is `INSERT ... SELECT ... WHERE NOT EXISTS` an archived row under the key, with the dead synthetic_fill filter dropped.
- **Migration 448 (applied live, lock_timeout 10s).** `ohlcv_request.content_digest text NULL` with a sha256-hex check; the archive's UPDATE-or-DELETE trigger replaced by a DELETE-only one (the TRUNCATE trigger is untouched; 88 trigger instances confirmed live on the parent and 87 chunks); UPDATE on the archive granted to bar_derivation_writer. No compressed column type change, so no VACUUM is owed.
- **D1 elision.** Sinks with source ibkr and a non-test caller drop observations equal to the latest stored non-test observation of the same (symbol, bar_date, route, what_to_show); within a flush a repeated answer lands once; the request row keeps the full `n_bars`.
- **CI scan.** `test_bar_write_no_first_write_wins.py` fails on `ON CONFLICT ... DO NOTHING` into market_data_ohlcv, the archive or ohlcv_observation outside two reasoned entries: `services/bar_writer.py` (dormant streaming path, a design non-goal) and `services/backfill_feature_factory.py` (retire: 185-42).

## Tests

- Unit (fakes, no live DB): contract module, archive, observation writer, persist helper, pipeline store tests, CI scan, migration contract and boundary tests. All green.
- `tests/unit/ -q`: green (5 pre-existing skips). black clean. ruff clean on every file touched; `ruff check .` reports one pre-existing import-order finding in `tests/unit/research_tools/test_repro_frozen.py` (not touched here).
- Integration on indicagent_test (`-m integration`): 8 contract tests plus the 6 moved atomic-write tests, all pass, no skips. They cover: same chunk twice writes zero bar rows (row xmin unchanged) and zero revisions; one changed bar rewrites exactly one row with one revision and one load row (market_data_ohlcv 5m and archive 15m); request rows carry the chunk digest; a 78-row tail with 2 restated bars is written; 600 stored with 20 changed is refused with bars unchanged and the refused load and request rows recorded; archive DELETE and TRUNCATE raise while UPDATE works; restated bars in compressed chunks of both tables are rewritten under the real role (ON CONFLICT DO UPDATE on a compressed hypertable works on TimescaleDB 2.27.1); IBKR D1 elision stores an identical answer once and a restated one again.
- The live database was not written by any test (checked: zero ZZ1* instruments or loads afterward).

## Deviations from plan

- **Migration number.** The plan names 448. `ls production/migrations` shows 449 taken, 448 free, and 450 to 452 claimed by plans 185-40, 189-10 and 185-43 (no file yet). 448 was kept; no plan filename amendment was needed.
- **[Rule 3] Shared contract module.** The plan allow-lists the pipeline and `intraday_raw_archive.py` as ohlcv_load / ohlcv_revision writers. Both needed identical plumbing, so it lives in `services/ohlcv_ingress_contract.py`, which is the one allow-listed ibkr writer of both tables; the pipeline and the archive module only call it and keep their own bar INSERTs. `files_modified` gained the new module and its test file.
- **Elision scope.** The plan says "excluding test callers". Implemented as both: the stored comparison excludes `test-%` callers' observations, and a sink whose own caller is `test-%` never elides (otherwise test fixtures equal to real rows would vanish). Elision applies to source ibkr only, so the Tradier loader's own elision is not doubled.
- **Revision (spec section 4 / 185-39 revision note).** As recorded in the plan: 5m month digests are written by the grid stage after the fetch run, not inside each chunk's transaction. This plan delivers the per-request content digest in the chunk transaction; 185-40's digest_fresh verdict catches a month the grid stage missed.
- **Tests rewritten.** Two unit tests asserted the old `ON CONFLICT DO NOTHING` SQL shape and were rewritten for the contract; a duplicate test name from the new CI scan was renamed for the pre-commit duplicate-name check.

## Not done, by instruction

- STATE.md, ROADMAP.md and REQUIREMENTS.md were not edited (shared checkout; the plan does not require it). Requirements D-05, D-07, D-09 are for the orchestrator to mark.
- The IBKR fetcher service and timer were not started; no fetch ran against IBKR.

## Known stubs

None.

## Threat flags

None. The new DELETE-only archive trigger and UPDATE grant are the plan's stated surface change.

## Self-Check

Files exist: migration 448, ohlcv_ingress_contract.py, the four new test files, the SUMMARY. Commits 79d99c374, a8a1120d3, 0379a8cf8 are in `git log`. Migration 448 is applied live (content_digest column present, no_delete trigger on parent and chunks, UPDATE granted).

Self-Check: PASSED
