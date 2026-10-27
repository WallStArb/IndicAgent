# Phase 191 plan 20, Task 2 only: Tradier delete script and APR floor

Task 2 tooling was built ahead of the Task 1 owner checkpoint, which is still open because the plan 19 residue report does not exist yet. Nothing ran against the live database except read-only catalog and count queries used for design, and the non-destructive APR seed (migration 524). No `--dump`, `--trial`, `--delete` or `--verify` ran live, no DELETE was issued, and CLAUDE.md is untouched. Task 3 has not started.

## Commits (all on origin/main)

| Commit | What |
|--------|------|
| df7eeab18 | test(191-20): failing tests for the delete script (RED) |
| dd02a6f27 | feat(191-20): script, migration 524 (applied live), boundary allow-lists (GREEN) |
| 927edc8af | fix(191-20): scope the bar-table deletes to the 1d segments |
| 39e64670a | test(191-20): failing tests for the review fixes, plus the scratch-schema integration test (RED: 35 of 60 unit cases fail against dd02a6f27/927edc8af) |
| 90ea7f984 | fix(191-20): review fixes: content digests, in-flight settlement, TSV in the trial, dump safety (GREEN) |

Commit 56fa09baf (another session's) swept the two `infra.tradier_delete.*` pending-retirement entries into `tests/unit/test_table_and_apr_key_readers.py`. Those entries are my content, already on main.

## Files

- `scripts/ops/bars/ops_tradier_delete.py` (new): `--dump`, `--verify [--require-complete]`, `--trial SYMBOL`, `--delete`. Every mode that writes needs `--apply`; without it, the mode reports and writes nothing.
- `tests/unit/scripts/test_ops_tradier_delete.py` (new, 60 cases).
- `tests/integration/test_ops_tradier_delete_scratch.py` (new): the real modes against copies of the seven tables in a throwaway schema on indicagent_test (see "Review fixes").
- `production/migrations/524_tradier_delete_apr.sql` (new, applied live): `infra.tradier_delete.min_free_disk_gb` = 200, `infra.tradier_delete.batch_symbols` = 20.
- Boundary tests, each entry marked TEMPORARY retire: 191-25:
  - `test_ohlcv_load_revision_writer_boundary.py`: one segment each for ohlcv_load and ohlcv_revision.
  - `test_ohlcv_coverage_writer_boundary.py`
  - `test_market_data_ohlcv_boundary.py`: raw read.
  - `test_market_data_ohlcv_writer_boundary.py`: writer row plus `_FENCE_EXEMPT`, because the 1d fence test requires it.
  - `test_table_and_apr_key_readers.py`: pending retirement for the two keys.
- `test_compressed_hypertable_write_boundary.py` and `test_ohlcv_raw_writer_boundary.py` needed no edit: the script has no UPDATE, and the raw guard does not cover DELETE.

## Tests

- Plan verify command plus the four named boundary and reader tests and the expiry guard: 91 passed (after the review fixes).
- Integration test on the scratch schema: 1 passed.
- `ruff check` and `black --check` are clean on all files I touched.
- `pytest tests/unit/ -n auto`: 6700 passed, 1 skipped (after the review fixes; 6685 before).
  - One earlier run failed `tests/unit/api/test_research_route.py::test_runs_count_their_groups_and_date_from_the_latest_finish`. That test and `src/api/routes/research.py` carry another session's uncommitted dashboard edits, and the test passed on the next run once their edit settled. It is not mine.
  - A transient xdist "different tests collected" error came from the same concurrent editing.

## Deviations from the plan text

1. **ohlcv_revision gets its own predicate, and some Tradier loads are kept** (Rule 2, data preservation).
   - Live counts: the Tradier loads own 3,179,829 ohlcv_revision rows of vendor ibkr, kind named (the old IBKR canonical 1d values the Tradier loader displaced on 2026-10-03). They also own 1,139 rows of vendor tradier.
   - Derived loads own a further 154,211 rows of vendor tradier.
   - The plan's "ohlcv_revision rows go by ON DELETE CASCADE" would delete 3.18M IBKR rows and leave the 154k Tradier rows behind.
   - What the script does instead:
     - It deletes `ohlcv_revision WHERE vendor = 'tradier'` explicitly, and backs those rows up.
     - Its ohlcv_load predicate keeps any Tradier load that owns a revision row of another vendor. The manifest records these as `retained_loads`, and `--verify` checks the count.
     - Each batch checks that the load delete cascades into nothing.
   - **Owner decision needed at Task 1:** keep those IBKR revision rows (the default) or accept losing them.
2. **Five tables, not four.** ohlcv_revision is added, as above. So `ls data/backups/191/ | grep -c tradier_` will be 5.
3. **Raw and canonical predicates carry `timeframe = '1d'`** (commit 927edc8af). See the risks section. Every Tradier bar is 1d (live: 7,140,397 raw, 6,661,722 canonical), and `--dump` refuses if any Tradier bar of another timeframe exists, so the predicate stays exact.
4. **`--apply` is required for every write**, including `--trial` and `--dump`. Task 3's commands become `--dump --apply`, `--trial SYMBOL --apply` and `--delete --apply`.
5. **The ohlcv_request check is stricter on the Tradier rows and looser on the total.** The Tradier-source count must be unchanged, and the total must not shrink (the plan said the total must be equal). This lets the fetcher resume without failing verify.
6. **`--verify` handles both phases.** One mode compares live counts against the manifest, per table and symbol, expecting zero for symbols the state file records as done. Add `--require-complete` after the full delete.
7. **No `compressed_hypertable_write_session`**, per the 2026-10-13 amendment.
   - Each batch is one plain transaction across the five tables, and lifts `timescaledb.max_tuples_decompressed_per_dml_transaction` with SET LOCAL.
   - "decompress=False" appears only in the docstring that explains why, so the done criterion's grep matches the explanation, not a call.
8. **Content and count equality per batch.** Each batch runs in one REPEATABLE READ transaction. Before any delete it recomputes, per (table, symbol), the row count and an md5 over the ordered whole-row text, and both must equal the manifest; then every DELETE's rowcount must equal the batch's manifest total. Any difference rolls the whole batch back. Per-symbol counts come from the digest read in the same snapshot, not from `DELETE ... RETURNING`, so a compressed-batch delete keeps its fast path.
9. **The first-bar TSV reuses plan 19's `ops_tradier_residue.run_measure`.** That is the same definition the owner approves at Task 1. The TSV is written once, before the first delete of any kind: the trial writes it if the trial runs first, and `--delete` skips it then.

## Risks for the live run (Task 3)

- **Segment decompression (fixed).** vendor is a segmentby column on ohlcv_raw but not on market_data_ohlcv, whose segmentby is (symbol, timeframe). A vendor-only batch delete there would decompress every timeframe of each name: AAPL holds 611k canonical rows, of which 6.7k are 1d. Across the corpus that means the whole canonical table decompressed, which would stay uncompressed until the policy reruns. The 1d scope fixes this, and EXPLAIN shows the symbol and timeframe filter pushed into the compressed chunk scan. Even so, the 1d segments the delete touches stay partly uncompressed until the compression policy runs. The trial measures that growth. Free disk today is 605 GB against the 200 GB floor.
- **Slow full scans.**
  - The dump's off-1d guard (`vendor = 'tradier' AND timeframe <> '1d'` on market_data_ohlcv) decompresses every non-1d segment once, read-only. That is slow, probably minutes to tens of minutes.
  - `ohlcv_revision WHERE vendor = 'tradier'` has no vendor index, so every dump or verify count seq-scans the 7.2 GB table. Each `--verify` and each `--delete` start pays this.
- **The VACUUM list grows.** After the delete, also run bare `VACUUM ohlcv_revision;` (the plan lists only raw, canonical and ohlcv_load). ohlcv_load and ohlcv_revision are plain tables, not hypertables.
- **ohlcv_restatement_flag** references ohlcv_load with ON DELETE RESTRICT. There are 0 rows on Tradier loads today, and `--delete` refuses if any appear.
- **ohlcv_coverage has 0 Tradier rows today.** Its backup file will be empty, and no symbol has Tradier rows in all four of the plan's tables. Task 3's "a symbol with rows in all four tables" cannot be met, so pick a trial symbol with raw, canonical and load rows.
- **bar_derivation must stay stopped between `--dump` and the last batch.** If the daily stage rewrites canonical Tradier 1d rows in that window, the per-batch count check rolls back and aborts the batch, which is loud but stops the run.
- **Free disk is read on `/` by default.** The database volume (/var/lib/docker/volumes/production_timescale-data) and data/backups/ both sit on that filesystem. Use `--disk-path` to override.
- **Digest cost.** The dump computes an md5 per (table, symbol) over every Tradier row (about 14M rows across the tables), and each batch recomputes its symbols' digests before deleting, so each batch reads its rows twice.

## Review fixes (2026-10-27)

A fresh-context review found no HIGH issues. Fixed, all under the same rules (no live dump, trial, delete or verify; no DELETE on live tables):

1. **Crash between commit and state save.** A batch's symbols are saved as in flight before its transaction starts. A rerun of `--trial` or `--delete` settles them from the live counts: zero in every table means committed (marked done), the manifest's counts mean rolled back (pending again), anything else refuses. `--verify` applies the same reading without saving. A committed trial settled this way gets a report marked `recovered` (its disk delta is measured from the saved free-disk reading to now, so it includes anything else that happened in between).
2. **TSV missed the trial symbol.** The trial now writes the TSV before its delete, sharing the `tsv_written` flag.
3. **Count-only guard.** Per-symbol content digests, as in deviation 8.
4. **Fakes could pass wrong SQL.** `tests/integration/test_ops_tradier_delete_scratch.py` copies the seven tables into a scratch schema on indicagent_test and runs `run_dump`, `run_verify`, `run_trial` and `run_delete` through a `Runtime` whose connections set `search_path` to that schema alone. The script's SQL names its tables unqualified, so production behavior is unchanged (`PRODUCTION` is the default Runtime). The fixture asserts the database is indicagent_test and the session's schema list is the scratch schema only, so a missing table errors instead of falling back to public. The case has mixed vendors, a held-back name, a Tradier load owning an ibkr revision (kept), a derived load owning a tradier revision (row deleted, load kept), a restatement flag on a Tradier load (refuses until removed), non-1d rows of another vendor, a load detail with an embedded newline, a value change after the dump (refused by the digest), and a simulated crash with a batch in flight. It asserts exactly the right rows remain, then restores from the backup files and gets every table back byte for byte.
5. **Dump overwrite.** The dump refuses while any `tradier_*.csv.gz` or the manifest exists, opens each file with `xb`, fsyncs each file and the directory, and writes the manifest exclusively with an fsync.
6. **Statement timeout.** `_connect` sets `statement_timeout=0` (and `timezone=UTC`) for every mode.
7. **Per-symbol counts.** As in deviation 8.
8. **Other-vendor revision count.** The manifest records the count of non-Tradier revision rows under Tradier loads (3,179,829 ibkr rows on 2026-10-27), and `--verify` requires it unchanged (T-191-45).

## Task 3 notes

- **Stop list.** From the first trial or batch until the 1d re-derive is done, stop every writer of the five tables and every consumer of canonical 1d (`market_data_ohlcv` and `market_data_ohlcv_tradeable`), not only the fetcher and bar_derivation. Scheduled on 2026-10-27 (`systemctl list-timers --all | grep indicagent`): `indicagent-ibkr-history-fetcher`, `indicagent-bar-derivation-grid`, `indicagent-bar-reconciliation-audit` (D7), `indicagent-alpaca-nightly`, `indicagent-dividend-event-writer-yahoo`, `indicagent-regime-coverage-auditor`, `indicagent-gateway-auth-probe` (harmless, no bar reads). Running services: `indicagent-feature-vector-writer`. Cron: the hourly `ops_tradier_residue_gate.sh`. No regime-writer, ic-measure or feature batch timer is installed today; recheck both commands and crontab at Task 3 and stop any feature, regime-writer, ic-measure or other 1d consumer found then, plus any manual 186-26 or feature backfill run.
- **ohlcv_load criterion.** With 743 retained Tradier loads today (the loads owning the IBKR revision rows), Task 3's done criterion "`select count(*) from ohlcv_load where source='tradier'` prints 0" becomes "prints the manifest's `retained_loads`" (plus any held-back names' loads). The owner rules on keeping them at Task 1.
- **TSV n_tradier.** The TSV's `n_tradier_sessions` comes from plan 19's measure, which leaves out raw rows whose request has a `test-%` caller; the delete itself takes every Tradier row. The owner should know the TSV count can be lower than the deleted raw count for a name.
- **Check the trial's raw row count.** ohlcv_raw is segmented by vendor, so its Tradier delete may take TimescaleDB's compressed-batch path. Check in the trial report that `tables.ohlcv_raw.rows` equals the manifest's count for the symbol; the batch already refuses a mismatch, but if the compressed path reports a wrong rowcount, every batch would refuse and the run stops at the trial.
- **Commands.** `--dump --apply [--hold A,B]`, `--verify`, `--trial SYMBOL --apply`, `--delete --apply`, then `--verify --require-complete`, then the four bare VACUUMs (raw, canonical, ohlcv_load, ohlcv_revision).

## Self-check: passed

Commits df7eeab18, dd02a6f27, 927edc8af, 39e64670a and 90ea7f984 are on origin/main. The script, tests and migration exist, and both APR keys are live in config_state.
