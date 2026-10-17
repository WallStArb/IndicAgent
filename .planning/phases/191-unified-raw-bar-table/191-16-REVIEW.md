# Plan 191-16 Review: drop the old bar stores, verify the parity path

Status: PASS
Date: 2026-10-17
Reviewer: fresh-context code review (diff 56dcea490..HEAD, four commits)

Verdict: PASS. No P1 or P2 defects. The drop was correctly guarded, ordered, backed up and
verified; the deletions are complete with no dangling executable references; the documented
deviations are all sound. Six P3 findings below, all documentation or process polish.

## Findings

### P3-1: operations-database.md still documents the dropped tables as live, and no plan owns it

- File: `docs/operations/operations-database.md:68-76` (table inventory rows for
  `ohlcv_observation` and `ohlcv_intraday_raw_archive`, with a live-writer column naming
  `services/ohlcv_observation_writer.py`), `:85`, `:94` (the `ohlcv_observation_writer` role's
  INSERT/UPDATE/DELETE grant description "on the D1 tables").
- Summary: the DB operations doc CLAUDE.md points at still lists both dropped tables with
  writers and grants; plan 16 updated the glossary only, and plan 17's docs task (per
  191-17-PLAN.md task text) names only canonical-truth-registry.md and gotchas.md.
- Failure scenario: an operator or future session reading operations-database.md queries
  `ohlcv_observation` or assumes the D1 writer role still has table grants, and wastes a cycle
  on a relation-not-found error, or worse repeats a stale claim in new tooling.
- Fix: fold the D1 section rewrite into plan 17's docs task (the doc sweep already touches two
  other docs).

### P3-2: --verify cannot serve its stated retention-period role after the drop

- File: `scripts/ops/bars/ops_old_store_backup.py:352-367` (`run_verify` recounts every table
  live before touching files); `191-17-PLAN.md:85` ("ops_old_store_backup.py stays until the
  backup retention date, 2026-11-12, because `--verify` is how the backup is checked").
- Summary: with both tables dropped, `--verify` fails at the live recount (UndefinedTable)
  before it ever re-reads a file, so the backup has no script-backed integrity check for the
  26 days it must survive on disk.
- Failure scenario: silent bit rot or accidental deletion of a backup slice between now and
  2026-11-12 is discovered only at restore time; the manifest and files permit a check
  (sha256 + newline recount against manifest constants) but nothing runs it.
- Fix: a `--verify-files` mode (manifest sha256 and file row recount only, no DB), or a
  documented one-liner in plan 17's notes. Cheap; the script dies in plan 18 either way.

### P3-3: the fetcher teardown-hang observation was not captured as a pending todo

- File: `.planning/phases/191-unified-raw-bar-table/191-16-SUMMARY.md:51` (deviation 7,
  "worth a todo"); `.planning/todos/pending/` (highest number 537, no fetcher-hang todo;
  todo 534 is throughput, not the shutdown deadlock).
- Summary: two fetcher runs hung after "Disconnected" (main thread idle in select under
  run_until_complete, py-spy dumps taken) and were killed; the SUMMARY flags it but no todo
  file exists, against the owner's capture-todos-immediately rule.
- Failure scenario: the hang recurs on a default-scoped run while the owner is away, blocks
  the 15-minute timer cadence until a human kills it, and the observation only survives in a
  phase SUMMARY nobody greps for fetcher symptoms.
- Fix: one pending todo (hang after Disconnected, py-spy dumps referenced, candidate cause the
  unfinished future in run_until_complete). Same sweep can carry deviation 9's optional
  `infra.ohlcv_observation.copy_batch_rows` rename note.

### P3-4: migration 499's idempotency comment overstates what the file does

- File: `production/migrations/499_drop_observation_and_raw_archive.sql:36` ("every DROP is
  IF EXISTS") versus `:84-85` (both `DROP TABLE` statements are plain, no IF EXISTS).
- Summary: comment rot inside a permanent migration file; the two table drops are deliberately
  loud on rerun, which is fine, but the header claims otherwise.
- Failure scenario: a future migration author copies 499 as an idempotency template, trusts
  the comment over the statements, and ships a "rerunnable" migration that aborts midway.
- Fix: correct the comment to "the trigger and function drops are IF EXISTS; the table drops
  are deliberately plain so a rerun fails loudly" (a docs-only follow-up commit; do not amend
  the applied file's semantics).

### P3-5: two dangling doc references to deleted code in live scripts

- Files: `scripts/ops/bars/ops_head_rerun.py:7` ("every answer lands in ohlcv_request /
  ohlcv_observation (D-16)" - false since the drop, though the next sentence self-corrects to
  ohlcv_raw); `scripts/ops/bars/ops_data_bar_check.py:104` (docstring credits "the guard
  ops_raw_backfill renders its constants-in-SQL through" - the script is gone).
- Summary: prose-only staleness in executable files' docstrings; behavior is correct (the
  executable grep over src/services/scripts is empty).
- Failure scenario: a reader traces the described data flow and looks for a table or script
  that no longer exists; minor confusion, no wrong action likely.
- Fix: one-line rewording in plan 17's sweep.

### P3-6: the parity lane's end-to-end execution is still unobserved (note, not a defect)

- File: `ohlcv_raw` (no vendor 15m/1h rows served for any name other than the explicit URA
  run; the week-42 parity items sit queued behind the 1d catch-up backlog, as the dry run
  showed at positions 1032-1033).
- Summary: task 3's evidence is a composition - lane engagement proven by the key=1 dry run,
  write path proven by the explicit URA 15m/1h run - and the composition is sound (verified in
  code: the parity lane exists only in `_fetch_queue.py` as a hold point plus queue admission;
  `_history_fetch_item.py`/`_intraday_persist.py`/`_derivation_stage.py` carry no parity or
  lane-specific persist branch, and the plan's own primary route was exactly this explicit
  CLI run). The first true parity-lane fetch happens under live operation.
- Failure scenario: a defect that only manifests when a parity item executes (for example the
  week-start hold computing a bad window) surfaces in the first live parity run rather than in
  task 3. Plan 17's time-gated close (one 06:00 UTC D7 run plus R6 green) is the backstop and
  would catch it.
- Fix: none required now; plan 17 should confirm the week-42 draw actually executed and wrote
  raw before closing (a one-line addition to its R6/D7 check).

## Checklist verification

1. Backup script (`scripts/ops/bars/ops_old_store_backup.py`)
   - Read-only enforced: `grep -nE "DELETE|DROP|UPDATE|INSERT|TRUNCATE|ALTER|MERGE"` over the
     file is empty; the plan's own done-criterion grep variant is empty; and
     `test_source_carries_no_write_or_ddl_tokens` pins it permanently. The only statements
     issued are SELECT, COPY ... TO STDOUT and catalog reads, with a rollback after the size
     estimation.
   - Manifest arithmetic: on-disk manifest re-summed independently; per-table file sums equal
     the recorded `total_rows` (16,269,722 + 201,982,404 = 218,252,126), 28 + 22 = 50 files
     present on disk, 2.9G total, years 1999-2026 and 2005-2026, margin 2, retention
     2026-11-12, created/completed timestamps match the SUMMARY's 04:09:38-04:17:43Z.
   - `--verify`: recounts every year slice live inside ONE REPEATABLE READ transaction
     (`run_verify`), re-counts file rows by decompressed newline count with a final-newline
     refusal, re-hashes every file, and compares all four sources per slice (manifest, live,
     files, digests) in both directions - a live year the manifest lacks is also flagged.
     Every mismatch message names table and year; nonzero exit with a count. Tests cover the
     mismatch matrix.
   - Disk-margin refusal: `disk_refusal` refuses below estimate times margin, raises on
     margin < 1, reads `infra.old_store_backup.disk_margin` via ConfigService (default 2);
     seeded by migration 498; estimated output uses pg_total_relation_size (conservative
     against gzip).
2. Migrations
   - 499: one transaction; SET LOCAL lock_timeout; order is guard, both parent triggers,
     tables (archive then observation), function, then the APR retirement block. No CASCADE,
     no chunk round trip (contract-test enforced). The pg_depend guard allowlists exactly the
     table family (tables, chunks via pg_inherits, own constraints, own non-internal triggers)
     and raises on anything else, so a later view or foreign FK aborts by name; the two live
     FKs to ohlcv_request and bar_derivation_batch pass correctly and go with their tables.
     Function-last is required (the archive's chunk trigger clones pin it until the table
     drops) and the contract test pins that order. Applied live cleanly (guard passed,
     survivors verified: `bar_derivation_append_only` present, `ohlcv_archive_no_delete` gone,
     both tables gone from pg_class, role `ohlcv_observation_writer` retained for its SET
     LOCAL ROLE users).
   - 500: APR-compliant re-seed of `infra.selection_gate.statement_timeout_s` = 7200
     (config_schema with `[initial_estimate]` and "Not an ML learning target", config_state,
     config_history with changed_by migration_500); `ops_selection_gate._TIMEOUT_KEY` updated;
     DB confirms 7200 at version 1 and both retired keys absent from config_state and
     config_schema. 498 follows the same pattern for disk_margin.
3. ops_raw_backfill.py wholesale deletion
   - Repo-wide sweep: zero remaining executable references. What remains is historical
     planning docs (191-02/03/04/11/15/17 files, todo 535), two intentional explanatory
     comments in tests (`test_table_and_apr_key_readers.py:147`, `test_daily_rule.py:668`),
     STATE.md prose, the window-evidence note, and the two stale docstrings in P3-5. No
     import, test, allow-list, crontab (user crontab checked), systemd unit or shell script
     invokes it.
   - Value-loss inventory (from the pre-deletion source): modes were `--bulk`, `--delta`,
     `--check`, `--revisions`, `--prune-forming-revisions`, all of which read the dropped
     stores, so every mode was dead the moment migration 499 committed; the plan's executable
     grep done criterion forces exactly this. The standing balance duty is genuinely covered:
     `scripts/ops/bars/ops_capture_completeness.py --gate` exists (unexplained invariant,
     exit 1 on any nonzero row) and was run green immediately before the drop (recorded in
     the window evidence). The revision-history reconstruction had already run in plan 04 and
     its load/revision rows are permanent; the boundary test now explicitly forbids any live
     writer from claiming the `raw-backfill-191` caller. Nothing of value was lost.
   - Plan 17 impact: its text still lists deleting the script and its allow-list rows; all
     already done, so plan 17 finds less to do (documented as deviation 2; same pattern plan
     15 set). No CI check breaks.
4. Task 3 evidence chain
   - Verified against the live DB: ohlcv_load rows for URA at 06:14:01Z, 15m and 1h, both
     destination raw, outcome applied, caller ibkr-history-fetch; ohlcv_raw URA 15m ibkr named
     = 338 and 1h = 91 (the claimed 429 total); loads n_bars 442 + 119 = 561 matches the run
     report. The canonical 15m/1h count recorded equal at t0 has since grown by 165 rows via
     the 06:19:00Z grid derivation (ohlcv_load rows destination market_data_ohlcv, caller
     bar_derivation-grid) after the window closed - legitimate post-window derivation, not a
     contradiction of the t0 evidence.
   - Sufficiency: the composition (dry-run lane engagement at key=1 with the deterministic
     week-42 draw, plus the explicit run exercising the identical fetch/planner/ingress
     machinery) matches the plan's own primary route ("through its normal CLI ... explicit-
     symbol and timeframe flags"), and code inspection confirms the parity lane differs only
     in queue admission and hold point. Sufficient, with the P3-6 residual noted.
5. SOP
   - Naming/ring/APR: no new hard-coded tunables (disk margin is an APR key; the gzip
     compresslevel 6 equals the library default in a temporary script; retention date is a
     recorded deadline, not a tunable). statement_timeout_s retirement handled correctly
     (499 retires with the house history/state/schema order; 500 re-seeds with provenance).
     No src/core or observability changes; vendor_kind change is a docstring only.
   - Tests assert behavior: the backup tests exercise the pure functions including the
     mismatch matrix and the read-only source token check; the migration contract strips SQL
     comments before matching, locates the file by glob (so at commit 091592150, which
     contains only the test, all 11 tests fail at the exactly-one-match assert - a genuine
     RED), and pins order, no-CASCADE, non-targets and the APR retirement. Its limits are the
     house limits of a source-level contract (it text-asserts the guard's presence rather
     than simulating pg_depend); the live apply with the guard passing is the behavioral
     evidence. 16 + 11 tests pass as claimed (27 ran green in this review), plus the six
     guard suites re-run here (58 tests green).
6. Deletion safety
   - Glossary: `observation`, `raw archive`, `derived grid`, `source` and the fetcher entry's
     parity-lane line all carry retired statuses with date, plan, migration and pointers to
     ohlcv_raw and the backup; `raw archive` now reads "Code surface: none live"; the kept
     role is documented as kept.
   - Registries: single-writer rows for both tables, the TEMPORARY observation-writer row,
     and the ops_raw_backfill rows in the ohlcv_raw, market_data_ohlcv boundary,
     no-synthetic-fill and load/revision allow-lists are all gone; `--locate-unsourced` and
     its test removed with their subject; services/README.md carries an explicit deleted-note
     row; no importer of the deleted service module remains.

## Deviation confirmations (all nine from the SUMMARY)

1. Window close via archive mv - CONFIRMED sound. ops_raw_cutover_window.py has no close verb
   (open/status/clear/resume only); logs/raw_cutover_window.json absent,
   raw_cutover_window.closed_191_16.json present; all three timers active again (fetcher last
   triggered 46 minutes before this review).
2. ops_raw_backfill deleted in full, not just the twin query - CONFIRMED sound. Plan 16's own
   text never mentions the script; the mandate is phase-level (191-11 SUMMARY and todo 535
   item 41: plan 16 runs the last balance, then deletes) and the executable grep forces zero
   references. Loss inventory in checklist 3: nothing uncovered.
3. statement_timeout_s retired here with migration 500 re-seed - CONFIRMED (see checklist 2).
4. disk_margin retire clause moved to 191-18 - CONFIRMED correct. The 191-16 plan text said
   plan 17 retires the key, but 191-17's own text keeps the script to the 2026-11-12
   retention date and plan 18 deletes it; a 191-17 clause would have expired while the
   script still lived. The readers-test entry records 191-18.
5. DROP FUNCTION after the tables - CONFIRMED correct (see checklist 2); the contract test
   asserts the enforced order.
6. Task 3 dry-run + explicit URA run - CONFIRMED sufficient with the P3-6 residual (the
   plan's primary route was exactly this CLI run; the key=1 fallback was the unreachable
   variant, and its lane-engagement purpose was still captured by the dry run).
7. Fetcher teardown-hang todo candidate - observed and documented, but NOT captured as a
   pending todo (P3-3).
8. dividend-event-writer failed state pre-existing - CONFIRMED recorded in the window
   evidence as active_at_open false and untouched.
9. copy_batch_rows key name kept - CONFIRMED disclosed; six live readers, rename is its own
   APR lifecycle action; optionally fold into the P3-3 todo sweep.

## Evidence

- Diffs read in full: 56dcea490..HEAD (all 28 files).
- `grep -nE "DELETE|DROP|UPDATE|INSERT|TRUNCATE|ALTER|MERGE" scripts/ops/bars/ops_old_store_backup.py`
  -> empty; stricter than the plan's done-criterion grep, also empty.
- `grep -rnE "(FROM|JOIN|INTO|COPY)\s+(ohlcv_observation|ohlcv_intraday_raw_archive)" src services scripts`
  -> empty (hits only in tests/fixtures/docs, each classified: the new backup test's expected
  SQL, a pinned historical query string in test_bar_write_no_first_write_wins.py, the
  d2v2_known_cases.json provenance fixture consumed only as known answers, migration-contract
  tests asserting historical text, integration schema baseline snapshot, prose docs).
- Repo-wide `ops_raw_backfill` sweep (py/md/json/sh/service/timer + user crontab + the 537
  gate script) -> no executable reference remains.
- Live DB (read-only): pg_class count 0 for both tables; `bar_derivation_append_only` present,
  `ohlcv_archive_no_delete` gone; role `ohlcv_observation_writer` present; APR state
  (disk_margin 2 v1, selection_gate timeout 7200 v1, grid_parity 10 v4; retired keys absent);
  grid_parity config_history rows v2-v4; URA ohlcv_load and ohlcv_raw rows as in checklist 4;
  canonical 15m/1h count 135,090,567 now with the 06:19 grid derivation explaining the +165
  drift from the recorded t0 equality.
- Manifest re-summed from disk: totals exact, 50 slice files, 2.9G.
- Tests run in this review: the two new files (27 passed) and the six guard suites (58
  passed). Coordinator had already verified the full suite green on the committed tree.
- `git show 091592150 --stat`: the RED commit contains only the contract test (126 lines), so
  the migration glob finds nothing and every test fails before 165ab7f58 - genuine RED.
- Migration numbering sequential: 497, 498, 499, 500.
- Working tree clean at review time.
