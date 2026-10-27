# Phase 191 plan 20, Task 2 only: Tradier delete script and APR floor

Task 2 tooling was built ahead of the Task 1 owner checkpoint, which is still open because the plan 19 residue report does not exist yet. Nothing ran against the live database except read-only catalog and count queries used for design, and the non-destructive APR seed (migration 524). No `--dump`, `--trial`, `--delete` or `--verify` ran live, no DELETE was issued, and CLAUDE.md is untouched. Task 3 has not started.

## Commits (all on origin/main)

| Commit | What |
|--------|------|
| df7eeab18 | test(191-20): failing tests for the delete script (RED) |
| dd02a6f27 | feat(191-20): script, migration 524 (applied live), boundary allow-lists (GREEN) |
| 927edc8af | fix(191-20): scope the bar-table deletes to the 1d segments |

Commit 56fa09baf (another session's) swept the two `infra.tradier_delete.*` pending-retirement entries into `tests/unit/test_table_and_apr_key_readers.py`. Those entries are my content, already on main.

## Files

- `scripts/ops/bars/ops_tradier_delete.py` (new): `--dump`, `--verify [--require-complete]`, `--trial SYMBOL`, `--delete`. Every mode that writes needs `--apply`; without it, the mode reports and writes nothing.
- `tests/unit/scripts/test_ops_tradier_delete.py` (new, 41 test functions, 45 cases).
- `production/migrations/524_tradier_delete_apr.sql` (new, applied live): `infra.tradier_delete.min_free_disk_gb` = 200, `infra.tradier_delete.batch_symbols` = 20.
- Boundary tests, each entry marked TEMPORARY retire: 191-25:
  - `test_ohlcv_load_revision_writer_boundary.py`: one segment each for ohlcv_load and ohlcv_revision.
  - `test_ohlcv_coverage_writer_boundary.py`
  - `test_market_data_ohlcv_boundary.py`: raw read.
  - `test_market_data_ohlcv_writer_boundary.py`: writer row plus `_FENCE_EXEMPT`, because the 1d fence test requires it.
  - `test_table_and_apr_key_readers.py`: pending retirement for the two keys.
- `test_compressed_hypertable_write_boundary.py` and `test_ohlcv_raw_writer_boundary.py` needed no edit: the script has no UPDATE, and the raw guard does not cover DELETE.

## Tests

- Plan verify command plus the four named boundary and reader tests: 70 passed.
- `ruff check` and `black --check` are clean on all files I touched.
- `pytest tests/unit/ -n auto`: 6685 passed, 1 skipped.
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
8. **Count equality per batch.** Every DELETE's rowcount must equal the manifest's per-symbol count for the batch, or the whole batch rolls back.
9. **The first-bar TSV reuses plan 19's `ops_tradier_residue.run_measure`.** That is the same definition the owner approves at Task 1. The TSV is written once, before the first batch.

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
- **GSD bookkeeping.** This file's name ends in `-SUMMARY.md`, and the GSD tooling counts summaries by that suffix (`commands.cjs`), so plan 20 may be reported as having a summary before Tasks 1 and 3 run.

## Self-check: passed

Commits df7eeab18, dd02a6f27 and 927edc8af are on origin/main. The script, tests and migration exist, and both APR keys are live in config_state.
