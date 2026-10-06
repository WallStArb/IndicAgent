---
phase: 185-daily-data-foundation
plan: 44
subsystem: repo hygiene / complexity debt census and CI guards
tags: [D-06, D-26, census, single_writer, allow-list expiry, APR, gap_closure]
requires: [185-27]
provides: [committed complexity baseline (185-COMPLEXITY-BASELINE.md), read-only census script 185-43 reruns, TEMPORARY and pending-retirement expiry guard, reader guard for migration tables and APR keys, single_writer registry for every canonical data layer table]
affects: [every later data layer plan that orphans a key or table (adds a _PENDING_RETIREMENT entry), adds a canonical table or writer (edits the registry), or completes a plan a retire clause names]
tech-stack:
  added: []
  patterns: ["frozen pre-existing violation lists that may only shrink: stale entries fail and a migration-number ceiling stops new names entering", "retire: <plan id> / retire: todo <n> clauses expire when the plan's SUMMARY or the completed todo exists", "migration catalog parsed from production/migrations in order instead of read from the live DB, so the guards stay CI-clean"]
key-files:
  created:
    - scripts/ops/ops_complexity_census.py
    - tests/unit/scripts/test_ops_complexity_census.py
    - .planning/phases/185-daily-data-foundation/185-COMPLEXITY-BASELINE.md
    - tests/unit/_migration_catalog.py
    - tests/unit/test_temporary_allow_list_expiry.py
    - tests/unit/test_table_and_apr_key_readers.py
    - tests/unit/test_single_writer_registry.py
  modified:
    - tests/unit/test_market_data_ohlcv_writer_boundary.py
    - tests/unit/test_canonical_lineage_digest_writer_boundary.py
    - .planning/phases/185-daily-data-foundation/deferred-items.md
decisions:
  - "Canonical tables are defined by rule, not by a hand list: migration-created tables whose name starts ohlcv_, bar_, market_data_, canonical_bar_, corporate_action, listing_venue, dividend_ or integrity_monitor. A new one (bar_source_policy in 185-36) fails CI until registered, which is the forcing function the plan asks for. This widened the plan's list by the dividend tables, market_data_gaps, ohlcv_provider_head and the two transient market_data_ohlcv_new/_old tables."
  - "Segments are declared on one named dimension per table (rule, inferred_by, monitor_type, timeframe) and checked pairwise disjoint; at most one writer may own the complement. integrity_monitor uses this: the shared helper owns every monitor_type except the two raw-INSERT scripts' own values."
  - "Covered tables stay single-sourced in their dedicated boundary test. The Tradier loader's second-writer entries there (market_data_ohlcv, canonical_bar_lineage) were re-marked TEMPORARY with retire: 185-38, the plan that deletes them, so the expiry guard enforces their removal."
  - "The APR reader rule lives once, in the census script (has_apr_reader), and the reader guard imports it, so the census and CI cannot disagree on what a reader is."
  - "The two clause-less TEMPORARY lease entries (phase 189 test file, paused session) are frozen rather than edited."
metrics:
  duration: 40min
  completed: 2026-10-06
  tasks: 3
  files: 10
---

# Phase 185 plan 44: complexity baseline and CI guards

The baseline is committed before any data layer integrity change, and three guards now fail CI when a TEMPORARY exception outlives its plan, when a migration table or APR key has no reader, or when a canonical data layer table gains a writer outside its registered single writer.

## Task 1: census and baseline (e1e8c08d0)

`scripts/ops/ops_complexity_census.py` prints JSON (or `--markdown`). Every count is a pure function over an injected listing. The script gathers listings from the filesystem, `git`, `systemctl show` and one psycopg session with `read_only = True` that is rolled back. A test asserts that the source contains no write or DDL statement and no commit.

Baseline at 74fb3fd4b, 2026-10-06T22:29Z:

| Measure | Count |
|---|---|
| scripts_total (scripts_ops) | 103 (36) |
| temporary_entries | 2 |
| tables_public / views_public | 100 / 14 |
| apr_keys_without_reader (of config_state) | 177 (of 845) |
| services_without_live_consumer | 38 |
| todos_pending | 88 |
| docs_stale_status | 10 |

The census script is included in its own scripts count. 185-43 reruns the same command.

## Task 2: expiry and reader guards (b75922a9c)

- `tests/unit/_migration_catalog.py` parses production/migrations in order: CREATE minus DROP TABLE with renames followed, and config_schema inserts minus deletes, including LIKE deletes and key renames. Against the live DB, the only differences are 4 tables that application code creates, 5 tables dropped outside migrations, 2 keys deleted outside migrations, and 110 keys seeded by SQL concatenation (108 `alpha.frame.*` per-regime keys and 2 zone-engine asset keys), which the parse cannot see.
- `test_table_and_apr_key_readers.py` fails on any reader-less name unless it is:
  - in the frozen 2026-10-06 lists (5 tables, 71 keys). These may only shrink: an entry that gains a reader or leaves the migrations fails, and a frozen name must come from a migration numbered 441 or lower.
  - in `_KEEP_TABLES` with a reason (empty today).
  - in `_PENDING_RETIREMENT` with `retire: <plan id>` (empty today).
- `test_temporary_allow_list_expiry.py` reads every TEMPORARY reason in `test_*boundary*.py` and `test_*_registry.py`:
  - A reason with `retire: <plan>` fails once that plan's SUMMARY exists (current or archived phases).
  - A reason with `retire: todo <n>` fails once the todo is in `completed/`.
  - A reason with no clause fails unless it is frozen. Two lease entries are frozen; a frozen entry that is gone or has gained a clause fails as stale.
  - `_PENDING_RETIREMENT` entries fail once their plan completes while the name is still created or seeded, and fail as stale once the name is gone.

## Task 3: single_writer registry (5f97e84bd)

There are 22 canonical tables:

- 5 are Covered by a dedicated boundary test: market_data_ohlcv, ohlcv_intraday_raw_archive, ohlcv_coverage, canonical_bar_lineage and bar_content_digest. For each, the guard asserts that the file exists and names the table.
- 17 are scanned for INSERT, UPDATE, DELETE, COPY, TRUNCATE, MERGE and asyncpg `copy_records_to_table` writes. A writer that is not registered fails, and a registered writer that has stopped writing fails as stale.

Tables with more than one writer declare disjoint segments:

| Table | Segmented by | Writers |
|---|---|---|
| bar_quality_flag | `rule` | scrub (9 rules + split_seam), derivation (constituent_flag, partial_constituents), 185-30 repair (legacy_price_sanity_status) |
| corporate_action | `inferred_by` | tradier_refetch, nightly_overlap, seam_audit |
| integrity_monitor | `monitor_type` | shared helper as complement, ic_bootstrap, stale_k3_hmm_field_cleanup |

The only TEMPORARY entry in the registry is the delete of ohlcv_observation by `ops_d1_dedupe.py` (`retire: 185-42`). ohlcv_load and ohlcv_revision become Covered when 185-31 adds their boundary test.

TEMPORARY entries after this plan: 5. That is the baseline's 2 clause-less lease entries plus 3 with retire clauses:
- 185-38 ×2: the Tradier loader's second-writer entries for market_data_ohlcv and canonical_bar_lineage.
- 185-42 ×1: the ops_d1_dedupe.py delete in the registry.

185-43 explains this delta against the baseline.

## Verification

- Touched-area tests and the boundary family: 51 passed. This covers every `test_*boundary*.py`, the three new guards and the census test.
- Full `.venv/bin/pytest tests/unit/`: 8137 passed, 5 skipped, 1 failed. The failure is `test_ops_real_rows_swap.py::test_every_allow_listed_reader_has_a_verdict`. It also fails at 74fb3fd4b, before this plan (checked in a detached scratch worktree), because 185-30 allow-listed `ops_tradier_lineage_backfill.py` without a `CONSUMER_VERDICTS` row. It is logged in deferred-items.md.
- ruff and black are clean on every touched file. `ruff check .` reports one pre-existing unsorted import in `tests/unit/research_tools/test_repro_frozen.py`, also logged as deferred.

## Deviations from Plan

1. [Rule 3 - Blocking] Added `tests/unit/_migration_catalog.py`, a shared migration parser. Both the reader guard and the single_writer guard need the migration table set, and the expiry guard needs the names present. One parser avoids three copies. Commit b75922a9c.
2. [Rule 2 - Missing critical] Edited two files outside the plan's list, `test_market_data_ohlcv_writer_boundary.py` and `test_canonical_lineage_digest_writer_boundary.py`. The Tradier loader's second-writer entries in them changed from PERMANENT to TEMPORARY with `retire: 185-38`. The plan's Task 3 action names this case. 185-38 already plans to delete both entries. Commit 5f97e84bd.
3. [Scope] The canonical table set is defined by a name rule, not the plan's list, so it adds 7 tables (see decisions). Every one has a single writer or a declared segment today.
4. [Fact correction] The plan says there were 14 boundary test files on 2026-10-06. There are 8.
5. Task 1's test, script and baseline went into one commit, because the plan says to commit them together. There is no separate RED commit; the RED run (collection error, module missing) was observed before the script was written.

## Known limits

- Writes through a table name held in a variable (`f"INSERT INTO {table}"`) are invisible to the single_writer scan, as in every boundary test.
- APR keys seeded by SQL concatenation inside a migration are invisible to the reader guard. Only the census, which reads the live config_state, counts them: 108 of the census's 177 reader-less keys are outside the guard's frozen list for this reason (the other 69 are frozen; 2 frozen keys are already gone from the live DB).
- The table reader rule counts any whole-word reference that is not a write or DDL target as a read, so a table named only in a log event string would pass. The rule errs toward passing.

## Self-Check: PASSED

- Files exist: scripts/ops/ops_complexity_census.py, tests/unit/scripts/test_ops_complexity_census.py, 185-COMPLEXITY-BASELINE.md, tests/unit/_migration_catalog.py, test_temporary_allow_list_expiry.py, test_table_and_apr_key_readers.py, test_single_writer_registry.py.
- Commits exist on main: e1e8c08d0, b75922a9c, 5f97e84bd.
