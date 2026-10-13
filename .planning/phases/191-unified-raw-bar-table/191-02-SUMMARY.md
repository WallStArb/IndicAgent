---
phase: 191-unified-raw-bar-table
plan: 02
subsystem: bar data layer
tags: [ohlcv_raw, writer, selection, fetch-ledger, migration-473]
requires: [191-01]
provides:
  - services/ohlcv_raw_writer.py, the single INSERT/UPSERT owner of ohlcv_raw
  - src/intelligence/bars/selection.py, pure rank_vendors / select_slot / select_all
  - services/bar_selection.py, canonical vendor-row writer for 1m, 5m, 4h
  - services/ohlcv_request_writer.py, RequestSink / AsyncRequestSink without the observation buffer
  - APR key threshold.bar_integrity.future_bar_tolerance_s (migration 473)
affects: [191-03, 191-04, 191-05, 191-13, 191-16]
key-files:
  created:
    - production/migrations/473_future_bar_guard_apr.sql
    - services/ohlcv_raw_writer.py
    - services/bar_selection.py
    - services/ohlcv_request_writer.py
    - src/intelligence/bars/selection.py
    - tests/unit/services/test_ohlcv_raw_writer.py
    - tests/unit/services/test_ohlcv_request_writer.py
    - tests/unit/test_bar_selection.py
    - tests/unit/test_ohlcv_raw_writer_boundary.py
  modified:
    - tests/unit/test_single_writer_registry.py
    - tests/unit/test_table_and_apr_key_readers.py
    - tests/unit/test_ohlcv_load_revision_writer_boundary.py
    - tests/unit/test_market_data_ohlcv_writer_boundary.py
    - tests/unit/test_market_data_ohlcv_boundary.py
    - tests/unit/test_market_data_ohlcv_no_synthetic_fill.py
metrics:
  tasks: 3
  completed: 2026-10-12
---

# Phase 191 Plan 02: raw writer, selection and request writer Summary

Four additive modules: `write_raw` classifies each vendor row against the same (vendor, kind) key, inserts new rows, replaces changed rows last-wins and logs old values to `ohlcv_revision` (origin raw); selection is a pure, order-independent function of raw rows and policy; `bar_selection` writes the winners for 1m/5m/4h; `ohlcv_request_writer` is the fetch ledger sink with no observation buffer. No live module changed.

## Commits

- 9ec18116b feat(191-02): migration 473 future_bar_tolerance_s APR key (applied live with psql -f)
- 473c49c0a feat(191-02): ohlcv_raw_writer (Task 1)
- 41f77f868 feat(191-02): pure bar selection and the canonical selection writer (Task 2)
- 71dffb087 feat(191-02): ohlcv_request_writer (Task 3)

## Blocker and resolution

The plan said to run the changed-row replacement inside `compressed_hypertable_write_session(conn, "ohlcv_raw", decompress=False)` on the caller's transaction (and the same for `market_data_ohlcv`). Executing found that impossible: the session rejects any table outside `_WRITE_SESSION_HARDENED_TABLES` (the feature tables) with a ValueError, and it commits the caller's transaction on entry and rolls back on exit, which would break the atomic `ohlcv_load` + `ohlcv_revision` + raw write. Execution stopped and reported. The coordinator amended 191-02, 03 and 20 (commit bfad3819b): no write session in any phase 191 writer; a plain multi-row `INSERT ... ON CONFLICT DO UPDATE` on the caller's connection and transaction (the shape `_history_fetch.py` and `intraday_raw_archive` already use); batch size `min(copy_batch_rows, 65535 // columns_per_row)`; an async `read_write_params(config)` for both APR keys. The work below follows the amendment.

## Verification

- `pytest tests/unit/ -q`: full suite green (after the duplicate-test-name and synthetic_fill allow-list fixes below).
- Shuffle property test: 25 shuffles of a mixed candidate set return identical selections.
- `grep -rn "INSERT INTO ohlcv_raw" src services scripts` hits only `services/ohlcv_raw_writer.py`; `UPDATE market_data_ohlcv` absent from `services/bar_selection.py`; `selection.py` has no `services` import.
- `git diff --stat b861afa9a..HEAD` on `services/ohlcv_ingress_contract.py`, `services/ohlcv_observation_writer.py`, `scripts/infrastructure/backfill`: empty.
- `indicagent-ibkr-history-fetcher.timer` active at the end.
- Migration 473: config_schema, config_state and config_history rows present (int, 3600, min 0).
- Self-review found nothing further to fix.

## Deviations from plan

1. [Rule 3 - blocking] Write session removed per the coordinator's amendment (above). Tests assert a single upsert statement and no commit or rollback instead of session entry.
2. [Rule 3 - blocking] `write_raw` also takes `future_tolerance_s` and an optional `now` (the future guard is an APR value the caller reads through `read_write_params`); `RawWriteParams` carries both values.
3. [Rule 3] Two guard tests needed entries the plan did not list: `test_ohlcv_load_revision_writer_boundary.py` got an `ohlcv_revision` entry for the raw writer (segment `origin:raw`, since it owns no `ohlcv_load.source`), and `test_market_data_ohlcv_no_synthetic_fill.py` got an entry for its refusal. The duplicate-test-name hook required renaming 10 ported tests with a `request_sink_` prefix.
4. `ohlcv_raw` is registered `Covered` by `test_ohlcv_raw_writer_boundary.py`; the plan 01 placeholder and the `_PENDING_RETIREMENT` entry are gone (`FROM ohlcv_raw` reads in the writers are the readers).
5. `bar_selection` skips a winner with NULL volume and counts it (`skipped_null_volume`) rather than filling, because `market_data_ohlcv.volume` is NOT NULL. It never substitutes a lower-ranked vendor.

## Known limits

- `ohlcv_revision` keeps the old key `(load_id, symbol, timeframe, timestamp)` until plan 04, so two kinds restated at one slot in one load would collide before then.
- A canonical row replaced by `bar_selection` is not logged to `ohlcv_revision`; raw keeps both vendors' values and canonical is rebuildable.
- `canonical_columns(vendor, kind)` raises for pairs with no source label (for example `ibkr/smart_trades`), which is correct for direct timeframes only.

## For plan 03 and later

- Allow-list `scripts/ops/bars/ops_raw_backfill.py` in `tests/unit/test_ohlcv_raw_writer_boundary.py` when it exists (plan 03 owns that entry), unless the backfill routes through `write_raw`.
- `write_raw(conn, rows, *, load_id, request_id, vendor_codes, kind_codes, batch_rows, future_tolerance_s, now=None)` requires non-null lineage ids; the backfill legitimately writes NULLs, so it needs its own path (and its own allow-list entry), not `write_raw`.
- The caller inserts the `ohlcv_load` row first (`ohlcv_revision.load_id` is a foreign key) and applies `should_refuse` to the returned `RawDelta` (`n_stored`, `changed`) against the vendor's own overlap.
- `bar_selection.select_and_write` takes `policy_rows` (as `PolicyRow`) and `kind_order` as arguments; the caller reads `bar_source_policy` and CVR `bar_kind` sort_order. Plan 13 changes only `canonical_columns` and `_INSERT_HEAD`/`_UPSERT_TAIL`.
- `services/ohlcv_request_writer.py` and the old module both write `ohlcv_request`; the old registry entry is marked TEMPORARY (retire: 191-16).

## Self-Check: PASSED

All created files exist; commits 9ec18116b, 473c49c0a, 41f77f868, 71dffb087 are on main.
