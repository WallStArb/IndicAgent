---
phase: 185-daily-data-foundation
plan: 42
subsystem: data layer cleanup (code and scripts half)
tags: [deletion, D-06, D-09, D-15, synthetic_fill, d2-v1, ingress-contract, one-off-scripts, gap_closure]
requires: [185-35, 185-37, 185-39, 185-44, 189-08]
provides:
  - "no code path can build a synthetic_fill bar: normalize_bars deleted, builder allow-list empty"
  - "derivation.py holds only the types d2-v2 shares; d2-v1 and TRADIER_RULE_VERSION gone"
  - "the rebuild writer's --fetch-only stage writes through the ingress write contract (no first-write-wins insert, no backfill_status)"
  - "seven completed one-off scripts deleted; ten orphaned names parked for 185-43's migration"
affects: [185-43, 185-45, 186-26, 189-10, todo 499, todo 506]
tech-stack:
  added: []
  patterns: ["a deletion's orphaned APR keys and tables go to _PENDING_RETIREMENT (retire: 185-43) in the same commit"]
key-files:
  created: []
  modified:
    - src/core/bar_normalizer.py
    - src/intelligence/bars/derivation.py
    - src/intelligence/bars/sources.py
    - src/intelligence/bars/seams.py
    - services/bar_derivation.py
    - services/backfill_feature_factory.py
    - scripts/infrastructure/backfill/_empty_history.py
    - scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py
    - tests/unit/test_market_data_ohlcv_no_synthetic_fill.py
    - tests/unit/test_bar_write_no_first_write_wins.py
    - tests/unit/test_market_data_ohlcv_writer_boundary.py
    - tests/unit/test_market_data_ohlcv_boundary.py
    - tests/unit/test_market_data_ohlcv_scrub_input_boundary.py
    - tests/unit/test_single_writer_registry.py
    - tests/unit/test_table_and_apr_key_readers.py
    - tests/unit/test_cutover_admission_apr_migration_contract.py
    - docs/foundation/glossary.md
    - docs/foundation/canonical-truth-registry.md
    - docs/reference/gotchas.md
  deleted:
    - scripts/ops/bars/ops_d1_dedupe.py
    - scripts/ops/bars/ops_real_rows_swap.py
    - scripts/ops/bars/ops_measure_ohlcv_write_rates.py
    - scripts/ops/bars/ops_seam_audit.py
    - scripts/ops/bars/ops_cutover_review.py
    - scripts/infrastructure/backfill/infrastructure_fetch_htf_bars.py
    - scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh
    - tests/unit/scripts/test_ops_real_rows_swap.py
    - tests/integration/test_ops_real_rows_swap_scratch.py
    - tests/unit/scripts/test_seam_audit.py
    - tests/unit/scripts/test_ops_cutover_review.py
    - tests/unit/scripts/test_fetch_htf_bars.py
decisions:
  - "ops_d1_bootstrap.py is kept: its fresh-fetch is the only caller of IBKRProvider.fetch_adjusted_daily_closes, the only producer of the paired ADJUSTED_LAST observations that dividend_event_writer (D5) and D7's adjusted_vs_trades read"
  - "ops_scrub_historical_pass.py is kept: it is the only emitter of the bar_scrub historical_pass_complete fact the D-28 gate (ops_data_bar_check scrub_pass_complete) reads, and a pass cleared that condition's RSPM/RSPS regression today"
  - "The factory's fetch-only checkpoint (backfill_status read) is deleted with its writes: a checkpoint nothing writes is a silent wrong state; a rerun asks the full depth and the contract writes only the difference"
  - "derivation.py stays the home of Observation, SplitRecord and CanonicalBar (nine importers; moving them would change every one)"
metrics:
  duration: 45min
  completed: 2026-10-07
  tasks: 2
  files: 43
---

# Phase 185 plan 42: delete the fill path, d2-v1, the factory's first-write-wins insert and seven one-off scripts

`normalize_bars` and d2-v1 are gone, the rebuild writer's `--fetch-only` stage writes through the ingress write contract with no backfill_status bookkeeping, and seven completed one-off scripts are deleted; two candidates turned out to have live purposes and stay.

## Preconditions

- `ps -eo pid,args | grep -E '[b]ackfill_feature_factory|[i]ntraday_chain|[i]bkr_history_fetcher'`: no process, checked before the first edit and again immediately before the factory commit.
- No completed rebuild cells: `select writer, status, count(*) from provenance_batch group by 1,2` returned 0 rows.
- `canonical_bar_lineage` relkind is `v` (a view) in the live DB, so the daily stage's table guard had nothing left to guard.

## Task 1: fill path, d2-v1, the factory's fetch stage

### Rebuild writer (0ff1c6b6c, cross-phase edit of a phase 186 file)

- `services/backfill_feature_factory.py`: `_STORE_OHLCV_SQL` (`ON CONFLICT DO NOTHING`), `_UPSERT_STATUS_SQL` (already unused), `_MARK_FETCH_COMPLETE_SQL`, `_SELECT_STATUS_SQL` and `_load_status_map` deleted. `run_fetch_stage` stores each fetched series with `_history_fetch.store_bars`, which writes through `_insert_market_data_rows` (the 185-39 ingress contract: new rows inserted, changed rows rewritten with old values in ohlcv_revision, one ohlcv_load row per series). No checkpoint remains (see deviations).
- `test_bar_write_no_first_write_wins.py`: the factory's TEMPORARY entry (`retire: 185-42`) removed. `test_market_data_ohlcv_writer_boundary.py`: the factory's entry removed (it no longer contains a raw write; the stale-entry check required it).
- Tests: the skip-on-fetch_complete test became a source test (no backfill_status, no raw insert, `store_bars(` in the stage); the fence test and the real-bars test drive the stage with `store_bars` patched.

### Fill path and d2-v1 (0b9c48dda)

| Item | Guard grep (services src scripts tests production docs/foundation docs/operations docs/reference tools CLAUDE.md) | Action |
|---|---|---|
| `normalize_bars` | definition, its tests, the guard test, two prose mentions (`_empty_history.py` docstring, glossary, canonical-truth-registry) | deleted with 8 tests; prose updated |
| `SOURCE_SYNTHETIC_FILL` | read by `intraday_raw_archive.py` (refusal) and `bar_reconciliation_audit.py` (D7 reads) | kept as the refused label, comment says so |
| `derive_daily`, `_choose_venue_route`, `_class_rank`, `_pick`, `split_staleness_threshold`, `RULE_VERSION = "d2-v1"` | only `derivation.py` and `tests/unit/bars/test_derivation.py` | deleted; `test_derivation.py` now covers the shared types (3 tests) |
| `sources.TRADIER_RULE_VERSION` | only `test_bar_derivation_daily.py` | deleted; the digest test uses d2-v2's `RULE_VERSION` |
| `bar_derivation._SELECT_LINEAGE_RELKIND_SQL` and the apply guard | only the module and the daily test fake | deleted with `test_apply_refuses_while_canonical_bar_lineage_is_a_table` and the fake's relkind |
| `--exclude-symbols-file`, `_read_exclude_file`, the `excluded_lane` outcome | no caller in scripts, systemd (`ExecStart ... --stage grid --changed-only --apply`), production or docs | deleted with `test_excluded_lane_symbol_is_skipped` |

- `test_market_data_ohlcv_no_synthetic_fill.py`: `_SYNTHETIC_BUILDERS` is empty (the `retire: todo 499` entry is gone); `bar_normalizer.py` moved to the reference list as "definition only"; the normalize_bars call fence and its counter retired with the function. Literal `"d2-v1"` strings stay in three tests as stored-history data (digests and lineage rows recorded under d2-v1).
- Todo 499: progress section added (step 2 done, only the gap-reader step 3 remains, closing it no longer trips a guard); PRIORITIES row updated.
- Plan verify: the listed suites pass; `grep -rn 'def normalize_bars\|def derive_daily(' src services scripts` is empty.

## Task 2: one-off scripts (15a076635)

| Candidate | Plan that used it | Last commit | Guard result | Outcome |
|---|---|---|---|---|
| `ops_d1_bootstrap.py` | 185-15 | bc7383391 | `_fetcher_lock.py` docstring, scrub-input allow-list, its test; deleting it orphans `IBKRProvider.fetch_adjusted_daily_closes` (vulture) | KEPT (see decisions) |
| `ops_d1_dedupe.py` | 185-27 era | 1fe60b8ef | only its single_writer TEMPORARY entry | deleted (126 lines) |
| `ops_real_rows_swap.py` | 185-25 | 3597da3a1 | its unit and integration tests, three allow-lists, migration 439's header | deleted (1,933 lines, 963 test lines) |
| `ops_tradier_fetch_complete_repair.py` | 2026-10-06 repair | - | already deleted by 189-08 | nothing to do |
| `ops_measure_ohlcv_write_rates.py` | 185-01 | 757e4f04b | no reference | deleted (554 lines); `scratch_185` schema absent live |
| `ops_scrub_historical_pass.py` | 185-10 | 6d3e9868e | `bar_scrub.py` docstring; only emitter of `historical_pass_complete`, read by `ops_data_bar_check` | KEPT (see decisions) |
| `ops_seam_audit.py` | 185-15 | 939fa13da | its test, scrub-input allow-list, registry segment, two foundation docs, migration 400 | deleted (546 + 183 lines); docs updated |
| `ops_cutover_review.py` | 185-38 | 4e93b0dd6 | its test, one assertion in the migration 454 contract test | deleted (159 + 91 lines) |
| `infrastructure_fetch_htf_bars.py` | pre-189 (v2.x) | ff8a477b1 | its test, gotchas.md (a stale chunking claim) | deleted (172 + 74 lines); gotcha line trimmed |
| `infrastructure_truncate_derived_tables.sh` | corpus re-backfill | aa843503c | the raw-table reader allow-list | deleted (80 lines), see deviations |

Totals: 7 scripts (3,570 lines) and 5 test files (1,311 lines) deleted; 0 rows of any table touched.

Rollback per item: `git checkout 15a076635^ -- <path>` (and its test path).

Allow-lists and registry shrank: `test_market_data_ohlcv_boundary.py` (-2), `test_market_data_ohlcv_scrub_input_boundary.py` (-1), `test_market_data_ohlcv_no_synthetic_fill.py` (-1), `test_single_writer_registry.py` (the ops_d1_dedupe TEMPORARY writer, the seam_audit corporate_action segment, the swap writer of market_data_ohlcv_new). The ops_d1_dedupe entry was the last `retire: 185-42` clause; none remain.

### Pending retirement for 185-43 (all `retire: 185-43` in `_PENDING_RETIREMENT`)

| Name | Reason | Live |
|---|---|---|
| `infra.real_rows_swap.copy_statement_timeout_s`, `.disk_margin`, `.lock_timeout_s`, `.masked_audit_max_age_hours`, `.statement_timeout_s`, `.stats_flush_wait_s` | read only by ops_real_rows_swap.py | present in config_state |
| `threshold.bar_integrity.cutover_max_removed_share`, `threshold.bar_integrity.cutover_max_refused_share` | read only by ops_cutover_review.py | present |
| table `market_data_ohlcv_new` | migration 439's swap target; reader was the swap script | absent live; still in the migration catalog, so 185-43 needs `DROP TABLE IF EXISTS` |
| table `market_data_ohlcv_old` | migration 045 leftover; reader was the swap script | absent live; same |

Not orphaned: `infra.ohlcv_observation.copy_batch_rows` (read by `ohlcv_observation_writer.py`, `_history_fetch.py`, `ops_venue_study.py`), `infra.bar_campaign.bootstrap_years` (ops_d1_bootstrap.py kept), `threshold.seam.*` (seams.py, split_detect, Tradier loader).

## Verification

- vulture against the pre-plan tree (`git archive 0ff1c6b6c^`): no new finding; six findings gone (`normalize_bars`, `derive_daily`, `TRADIER_RULE_VERSION`, three in ops_real_rows_swap.py). The whitelist held no entry for any deleted name, so nothing to prune. Two new findings appeared mid-task and were resolved: `fetch_adjusted_daily_closes` and `HIST_RATE_LIMIT_KEYS` (by keeping ops_d1_bootstrap.py) and `Seam.max_rel_dev` (field removed, see deviations).
- Boundary family, expiry, reader and registry guards: 70 passed.
- Full `.venv/bin/pytest tests/unit/`: 8360 passed, 5 skipped (the same five pre-existing skips) before the Task 2 commit.
- ruff and black clean on every touched file; pre-commit 9/9 on all three commits.
- No edit under `src/intelligence/research/` or `statistics/`, so repro_frozen does not apply.
- Acceptance grep `git grep <name> -- services src scripts tests production`: 0 hits for every deleted name except immutable migrations (400, 439, 454, 205, 236) and the `_PENDING_RETIREMENT` reasons that name the deleted reader (they leave with 185-43).

## Deviations from plan

1. [Rule 1 - Bug] Factory checkpoint read deleted with the writes. The plan named only the backfill_status writes; once nothing writes `fetch_complete`, the read would skip pairs on stale rows forever. The fetch stage now has no checkpoint. Commit 0ff1c6b6c.
2. [Plan conflict, kept] `ops_d1_bootstrap.py` stays. The plan lists it as one-off, but vulture showed it is the only caller of `fetch_adjusted_daily_closes`, the only route to fresh ADJUSTED_LAST observations that D5 and D7 pair with TRADES. 189-10's one-time fetch for never-asked names, or any dividend refresh, needs it or a fetcher replacement. Its key `infra.bar_campaign.bootstrap_years` is therefore not parked.
3. [Plan conflict, kept] `ops_scrub_historical_pass.py` stays. The plan's reason ("the daily stage scrubs every write now") holds for new writes, but the D-28 gate's scrub_pass_complete condition reads only this script's `historical_pass_complete` fact, and 185-35 needed a pass today to clear RSPM/RSPS.
4. [Scope] `infrastructure_truncate_derived_tables.sh` deleted although it truncates no bar or archive table (the plan's condition). Its re-seed half wrote the factory checkpoint deleted in deviation 1, and its truncate half targets the old `feature_vectors` and IC tables the 186 rebuild does not write; a one-prompt truncate of them is a hazard with no remaining purpose.
5. [Rule 3] `Seam.max_rel_dev` removed (`seams.py`, the Tradier loader's constructor, two tests). Its only reader was ops_seam_audit.py; leaving it would be a new vulture finding. `test_seams.py` now checks the same bound from the ratios.
6. [Rule 3] Doc edits outside the file list (the docs half is 185-43's): glossary, canonical-truth-registry and gotchas named deleted code; three lines updated so the guard grep is clean. `_empty_history.py` (a 189 file) had a docstring naming `normalize_bars`; one sentence changed.
7. `test_cutover_admission_apr_migration_contract.py` lost its assertion that migration 454's header names `ops_cutover_review.py`; the header text itself is immutable.
8. The factory's loads are labeled with `store_bars`' caller `ibkr-history-fetch` in ohlcv_load (the contract writer takes no caller argument). The stage is unscheduled; todo 506 (FetcherLock for the factory after 186-26) is the natural place to give it its own caller label if it is ever run.

## For the next plans

- 185-43: migration retires the eight APR keys and drops `market_data_ohlcv_new` and `market_data_ohlcv_old` IF EXISTS (both absent live; the catalog still creates them), then removes the ten `_PENDING_RETIREMENT` entries. Remove the factory and `infrastructure_truncate_derived_tables.sh` from the backfill_status writer and reader lists (neither touches it now). The census counts 7 fewer scripts. Docs still naming deleted scripts in dated history are fine; `docs/foundation` and `docs/reference` are clean for these names. `ops_data_bar_check` condition 2 now reads frozen evidence (seam_audit rows and fact); if the gate reruns, condition 1 still needs a fresh `ops_scrub_historical_pass.py --tf 1d --apply` after any 1d revision.
- 185-45: nothing here touches the dormant v2.x or AI stack; `infrastructure_fetch_htf_bars.py` (a v2.x topic replay) is already gone.
- 186-26: `services/backfill_feature_factory.py` changed (0ff1c6b6c) before any rebuild cell exists, so the rebuild's code key is taken on this version. The factory now imports `scripts.infrastructure.backfill._history_fetch`; the writer's own module is hashed as a file without its imports, so `_history_fetch` does not enter the unit code key.
- 189-10: ADJUSTED_LAST for new names still comes only from `ops_d1_bootstrap.py fresh-fetch`; decide there whether the fetcher takes it over.
- Todo 499: open for step 3 only.

## Known stubs

None.

## Threat flags

None. T-185-42-01 mitigated by the per-item grep, vulture and the suite (two candidates kept on live callers); T-185-42-02 by the process and provenance_batch checks; T-185-42-03: no table row was written or deleted.

## Self-Check: PASSED

- GONE: the seven deleted scripts and five deleted test files.
- FOUND: ops_d1_bootstrap.py, ops_scrub_historical_pass.py, tests/unit/bars/test_derivation.py.
- FOUND commits on main (pushed): 0ff1c6b6c, 0b9c48dda, 15a076635.
