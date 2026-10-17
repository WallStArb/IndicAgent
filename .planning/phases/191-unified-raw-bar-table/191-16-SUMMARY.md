# Plan 191-16 Summary: drop the old bar stores, verify the parity path

Status: complete
Date: 2026-10-17
Author: gsd executor session (plan 191-16)

## Task 1: old-store COPY backup and verify

- Script: `scripts/ops/bars/ops_old_store_backup.py` (dump and verify), tests `tests/unit/scripts/test_ops_old_store_backup.py` (16 tests), APR seed migration 498 (`infra.old_store_backup.disk_margin`, int, default 2, `[initial_estimate]`, not an ML target).
- Dump: run 2026-10-17 04:09:38Z to 04:17:43Z, one serial connection, one REPEATABLE READ transaction, per-table gzip CSV per year slice of the date column. Log: `logs/old_store_backup_dump_191_16.log`.
- Manifest: `data/backups/191/old_store_backup_manifest.json`, `retention_until: 2026-11-12`, disk margin 2, estimated output 3,795,279,872 bytes.
- Exact counts (manifest = live = files, per year slice and per table):
  - `ohlcv_observation`: 16,269,722 rows, 28 files (1999-2026), 284,583,870 bytes gz.
  - `ohlcv_intraday_raw_archive`: 201,982,404 rows, 22 files (2005-2026), 2,808,233,349 bytes gz.
  - Total 218,252,126 rows, 2.9 GB on disk under `data/backups/191/`.
- Verify: exit 0 in-session 2026-10-17 (`logs/old_store_backup_verify_191_16.log`): manifest totals, live recount per year slice and file row counts agree, zero problems. Re-confirmed immediately before the drop (no writer to either table has existed since plans 191-05/08).

## Task 2: inventory, deletions, drop migration, glossary

- Inventory: `grep -rnE "(FROM|JOIN|INTO|COPY)\s+(ohlcv_observation|ohlcv_intraday_raw_archive)" src services scripts` is empty (the plan's hard done check). The broad inventory grep's remaining hits all classify as non-executable: the live APR key name `infra.ohlcv_observation.copy_batch_rows` (six readers including `services/ohlcv_raw_writer.py`; the name embeds the old table's name, renaming it is its own APR lifecycle change), the kept role `ohlcv_observation_writer` (`SET LOCAL ROLE` in `services/ohlcv_request_writer.py` and `scripts/infrastructure/backfill/_intraday_persist.py`), historical prose and provenance lines, and the migration-contract tests that assert historical migration text.
- Deleted: `services/ohlcv_observation_writer.py`, `scripts/ops/bars/ops_raw_backfill.py`, `tests/unit/services/test_ohlcv_observation_writer.py`, `tests/unit/scripts/test_ops_raw_backfill.py`, `tests/unit/test_ohlcv_intraday_raw_archive_writer_boundary.py`, `tests/integration/test_ohlcv_observation_store.py`. `services/intraday_raw_archive.py` was already gone (plan 191-08).
- Guard edits: single-writer registry entries removed (both tables plus the TEMPORARY observation-writer row under `ohlcv_request`); `infra.backfill.ohlcv_insert_batch_size` pending-retirement entry removed; ops_raw_backfill rows removed from the ohlcv_raw, market_data_ohlcv boundary, no-synthetic-fill and load/revision boundary allow lists; `ops_selection_gate.py` lost `--locate-unsourced` (its subject was the old stores' balance check); `vendor_kind.observation_kind` docstring reworded; one `test_daily_rule.py` comment updated.
- Migration 499 `production/migrations/499_drop_observation_and_raw_archive.sql`: one transaction, `SET LOCAL lock_timeout`, pg_depend guard (allows only the table family: tables, chunks, own constraints, own non-internal triggers; raises on anything else; dry-run validated against the live catalog before the apply), both archive triggers, `DROP TABLE ohlcv_intraday_raw_archive`, `DROP TABLE ohlcv_observation`, `DROP FUNCTION IF EXISTS ohlcv_archive_no_delete()` (after both tables; the ~89 chunk trigger clones pin it until the table goes), then the APR retirement block (history, state, schema) for `infra.backfill.ohlcv_insert_batch_size` and `infra.raw_backfill.statement_timeout_s`. No CASCADE, no chunk round trip, `ohlcv_request` and `bar_derivation_append_only` untouched.
- Migration 500 `production/migrations/500_selection_gate_timeout_apr.sql`: seeds `infra.selection_gate.statement_timeout_s` = 7200; `ops_selection_gate.py` reads it (it had been squatting on the raw-backfill key retired by 499).
- Apply: 2026-10-17 ~05:55Z under the cutover window (`psql -v ON_ERROR_STOP=1 -f`), all statements clean (DELETE 1 / 2 / 2 across config_history / state / schema). The in-flight 871-name 1d catch-up finished on its own at 05:47:06Z (partial: 620 items, 605 ok, 15 error, gateway flakiness) before the apply; nothing was killed. Last balance evidence before the drop: `scripts.ops.bars.ops_capture_completeness --gate` OK (unexplained 0 in every source/timeframe group).
- VACUUM: `VACUUM ohlcv_raw;` then `VACUUM market_data_ohlcv;` as separate bare statements.
- Disk: 269G used / 607G free before the drop; 258G used / 618G free after the VACUUMs (about 11 GB returned, matching the design doc estimate).
- Done checks: `pg_class` count for both names is 0; the executable grep is empty; glossary entries `observation`, `raw archive`, `derived grid`, `source` and the fetcher entry's parity-lane line updated with retired statuses and pointers to `ohlcv_raw`.
- Window: opened 04:43:29Z (timers stopped, batch left to finish), evidence `.planning/phases/191-unified-raw-bar-table/191-16-WINDOW-EVIDENCE.json`, all ten units cleared with `--plan 191-16`, `resume --all` clean, all three timers active again. Window record archived to `logs/raw_cutover_window.closed_191_16.json`.

## Task 3: parity path sample and the APR key

- t0 06:13:39Z; run `ohlcv_history_fetcher.py --timeframes 15m,1h --symbols URA --no-derive` (fetch_run_id c21e338a-8991-4347-bbd9-0e6f32a30656): 2 items ok, 561 bars, exit 0.
- Checks, all pass:
  1. `ohlcv_raw` 15m/1h ibkr rows with `served_at >= t0`: 429 (URA 15m x 338, URA 1h x 91, served 06:14:01Z).
  2. Canonical 15m/1h count unchanged: 135,090,402 before and after (exact count equality, stronger than a stats delta; the derivation units were idle).
  3. The run's `ohlcv_load` rows: 2, both destination `raw`, outcome `applied`.
  4. `pg_stat_user_tables` n_tup_ins deltas among bar tables: only `ohlcv_load` (+2) and `ohlcv_request` (+2) moved; `ohlcv_revision`, `ohlcv_coverage`, `bar_derivation_batch`, `bar_content_digest`, `ohlcv_empty_history`, `market_data_ohlcv_old` unchanged. Hypertable parents (`ohlcv_raw`, `market_data_ohlcv`) show 0 at parent level because inserts land in chunks; the raw writes are proven by check 1 and the canonical no-writes by check 2.
  5. No canonical writes anywhere (see 2 and 4).
- APR: `infra.backfill.grid_parity_sample_names_per_week` set to 10 (config_state version 4) with changed_by `phase-191-15`, reason "parity path verified writing ohlcv_raw only; resumes the lane paused by 0f066c302"; confirmed as the latest config_history row. Intermediate value 1 for the sample draw was set and superseded by the same change chain (versions 3 and 4).
- Fetcher timer restarted and active (first post-restart run launched 06:15Z).

## Deviations

1. Window close: `ops_raw_cutover_window.py` has no close verb; after `resume --all` the record was archived with `mv logs/raw_cutover_window.json logs/raw_cutover_window.closed_191_16.json` (precedents 191-12, 191-14 Deviation 2). The window-open also needed `SUDO_PASS` exported (the script's documented sudo mechanism); the first attempt without it failed stopping a timer and was rerun.
2. `ops_raw_backfill.py` was deleted in full here, not just the 1d twin query: every mode of it read the old stores, and the plan's own done criterion (the executable grep) forces zero references. Plan 17 therefore finds less to do than its text assumes (same pattern as plan 15's ops_d1_bootstrap note). Its last-balance duty moved to `ops_capture_completeness --gate` (run and passed before the drop).
3. `infra.raw_backfill.statement_timeout_s` was retired by migration 499 in this plan (the readers-test comment had slated plan 17) because its subject died here, and `ops_selection_gate.py` still read it; migration 500 seeds the gate its own key at the same live value (7200). The pending-retirement comment in `tests/unit/test_table_and_apr_key_readers.py` was updated accordingly.
4. The `infra.old_store_backup.disk_margin` pending entry says `retire: 191-18`, not 191-17 as the plan text said: plan 17 keeps the backup script to the retention date 2026-11-12 and plan 18 deletes it, so a 191-17 clause would have expired while the script still lives.
5. Drop order inside migration 499: the function drop follows both table drops (the plan text said function first). The archive's chunk-level trigger clones reference `ohlcv_archive_no_delete` and only disappear with the table, so function-first aborts. The contract test asserts the enforced order.
6. Task 3 route: the fetcher CLI cannot target the parity lane (an explicit `--symbols` run is not a "default run", so parity items are never queued), and a one-tick default run was unreachable in practice: with key=1 the dry run placed URA's parity 15m/1h items at queue positions 1032-1033 behind roughly a thousand due-1d items, hours of grinding. The verification is therefore composed of two halves: (a) lane engagement, proven by the dry run with key=1 (queue summary `lane=parity tf=15m: 1, tf=1h: 1`, items `URA ibkr 15m/1h lane=parity`, the deterministic week-42 draw over 1,137 eligible names); (b) the write path, proven by the explicit URA 15m/1h run above, which exercises the same fetch, planner and ingress-contract machinery the parity branch uses (the branch's only difference is the 0-day overlap). The key went to 10 on that combined evidence.
7. Observed out of scope, worth a todo: two fetcher runs with small default-scoped queues hung after "Disconnected" (main thread idle in `select` under `run_until_complete`, an unfinished future; py-spy dumps taken) and were killed; loads already applied stayed applied, the advisory lock frees on death. The explicit `--timeframes` run and the full 05:47Z run exit cleanly.
8. `indicagent-dividend-event-writer@yahoo.service` was already in state `failed` before the window opened (active_at_open false); untouched by this plan.
9. The live APR key `infra.ohlcv_observation.copy_batch_rows` embeds the dropped table's name; kept as-is (six live readers, rename is its own APR lifecycle action, flagged here for a later todo if wanted).

## Commits

- 3a37fa3c6 feat(191-16): old-store COPY backup script, migration 498, gitignore exception, readers pending entry.
- 091592150 test(191-16): failing contract for the drop migration (RED).
- 165ab7f58 feat(191-16): drop the old bar stores (migration 499) and their readers (GREEN; includes migration 500, guard edits, glossary).
- docs commit: this SUMMARY plus STATE.md and ROADMAP updates.

## Test results

- `tests/unit/scripts/test_ops_old_store_backup.py`: 16 passed.
- `tests/unit/test_drop_observation_and_archive_migration_contract.py`: 11 passed (RED before migration 499, GREEN after).
- Full suite `.venv/bin/pytest tests/unit/ -q` after the Task 2 edits and again on the committed tree: all passed, 2 known skips (pipeline annotation confidence.py, HMM degenerate Viterbi). No failures.
