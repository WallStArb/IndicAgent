---
phase: 185-daily-data-foundation
plan: 43
subsystem: data layer cleanup (database and docs half)
tags: [deletion, apr-retirement, migration-459, D-06, D-07, D-26, docs, todos, census, gap_closure]
requires: [185-42, 185-44, 185-45]
provides:
  - "backfill_status has no reader or writer and is dropped (dump verified); onboarding seeds no bookkeeping"
  - "migration 459: 177 reader-less APR keys retired (history, state, schema), 3 tables dropped, 2 catalog-only tables closed; _PENDING_RETIREMENT empty"
  - "living docs (onboarding SOP, canonical truth registry, operations-database, gotchas, services and archive READMEs) state the final data layer; the design doc Status reads implemented"
  - "185-COMPLEXITY-EXIT.md: every census count against the 185-44 baseline, the two that rose explained item by item"
affects: [189-10, 185-47, 185-48, 189-09, 186-26, todo 499, todo 509, todo 510, todo 511]
tech-stack:
  added: []
  patterns:
    - "a retirement migration must be numbered after every migration that seeds a key it retires, or a fresh replay leaves the key standing"
key-files:
  created:
    - production/migrations/459_drop_backfill_status_retire_superseded_apr.sql
    - tests/unit/test_backfill_status_retirement_migration_contract.py
    - .planning/phases/185-daily-data-foundation/185-COMPLEXITY-EXIT.md
    - .planning/todos/pending/510-delete-185-38-185-43-185-45-backups-after-2026-11-06.md
    - .planning/todos/pending/511-island-head-rule-owner-decision.md
  modified:
    - src/config/instrument_onboarding.py
    - scripts/infrastructure/universe_expansion_onboard_manifest.py
    - scripts/infrastructure/universe_expansion_stratified_sourcing.py
    - services/bar_reconciliation_audit.py
    - src/intelligence/statistics/price_sanity.py
    - tests/unit/test_table_and_apr_key_readers.py
    - tests/unit/test_single_writer_registry.py
    - docs/foundation/instrument-onboarding-sop.md
    - docs/foundation/canonical-truth-registry.md
    - docs/operations/operations-database.md
    - docs/reference/gotchas.md
    - docs/plans/2026-10-06-data-layer-integrity-design.md
    - services/README.md
    - src/intelligence/archive/README.md
    - config/universe/README.md
    - .planning/todos/PRIORITIES.md
  deleted:
    - scripts/infrastructure/universe_expansion_pilot_draw.py
    - scripts/infrastructure/universe_expansion_onboard_gap_fill_etfs.py
    - scripts/ops/corpus/ops_known_corrupt_print_cleanup.py
    - tests/unit/test_known_corrupt_print_cleanup.py
decisions:
  - "Migration numbered 459, not 452: migration 454 seeds the two cutover keys, so a 452 retirement would leave them standing on a fresh replay"
  - "Root CLAUDE.md and src/intelligence/CLAUDE.md not edited: the plan assigns CLAUDE.md to 189-09 and instruction files are not an executor's to change on an orchestrator's word; their stale lines are listed below for 189-09"
  - "Whole reader-less families retired (alpha.frame.* 120 keys, threshold.signal_audit.* 6) with seven single keys whose code is gone; the remaining 51 frozen keys belong to live domains (regimes, construction, IC) and wait for phases 186 and 187"
  - "gate_evaluations, concept_annotation and factor_series_correlation kept although reader-less: the first two hold research records, the third has a live writer"
metrics:
  duration: about 3h45m (2026-10-07T23:55Z to 2026-10-08T03:40Z, including one coordinator restart message)
  completed: 2026-10-08
  tasks: 3
  files: 40
---

# Phase 185 plan 43: drop backfill_status, retire 177 unread APR keys, docs and todos describe the final data layer

backfill_status is gone with its last writer (onboarding's seed) and reader (a report-only one-off), migration 459 retired 177 reader-less APR keys and dropped three tables, the living docs and the todo ledger describe the system that exists, and the census proves the debt fell against the 185-44 baseline.

## Task 1: readers, dumps, migration 459 (78d4e90d7)

Reader grep at start (`grep -rn "backfill_status\|fetch_complete" services src scripts`): real code in `src/config/instrument_onboarding.py` (the seed INSERT) and `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py` (its candidate list); everything else was comments. Moves:

| Reader or writer | Action |
|---|---|
| `onboard_instrument()` seed | Deleted with the `timeframes` parameter and `OnboardResult.backfill_rows_seeded`; the queue and `ohlcv_coverage` pick a new name up from `instruments`. Tests first: the write set is exactly instruments, classification, tags, metadata (RED, then GREEN) |
| manifest and stratified onboarders | `--timeframes` removed |
| `universe_expansion_pilot_draw.py` | Deleted: completed phase 174 pilot, and its `_run_commit(sample, settings, ("1d",))` call no longer matched the 4-argument signature (it could not run). Its only APR key `alpha.universe.pilot_sample_size` retired |
| `universe_expansion_onboard_gap_fill_etfs.py` | Deleted: a one-time onboarding of EMLC and VIXY, both onboarded; a rerun is refused as existing |
| `ops_known_corrupt_print_cleanup.py` and its test | Deleted under the grep guard: report-only since 185-18, no caller in scripts, units or docs procedures; `bar_scrub` owns detection. Its removal orphaned `price_sanity.count_corroborating_symbols_batch` (vulture), deleted with three tests and a whitelist line |
| comments in five fetch-path files | Reworded; the fetcher's status file renamed `logs/ibkr_history_fetcher_status.json` (the old name contained the table name; the log file was moved so D7's `nightly_skipped` reads the same content) |

After: `grep -rln backfill_status services src scripts --include=*.py` is empty.

Census query for leftover swap or backup tables (`swap|_old|_bak|backup|_pre_|_tmp|_new$|scratch`, all schemas): none live. Reader-less tables from the census: `batch_job_checkpoints` (0 rows, no reference) and `ic_cell_fingerprints` (2,916 rows, the deleted old ic_engine's cache) dropped; three kept (see decisions).

Dumps (`data/backups/185-43/`), each checked with `pg_restore -l` and restored into a scratch database with matching counts: `backfill_status.dump` 3,069 rows, `batch_job_checkpoints.dump` 0, `ic_cell_fingerprints.dump` 2,916. Retired APR rows exported to `config_{schema,state,history}_retired_keys.csv` (177, 177, 356 rows).

Migration 459: dry run with ROLLBACK first (DELETE 356, 177, 177; five drops), applied live 2026-10-08 00:03:25 UTC under `lock_timeout 10s`. Rerun dry: DELETE 0 three times; the 177 keys have 0 rows in all three config tables. config_state 858 -> 681 keys. `_PENDING_RETIREMENT` is empty; the frozen lists lost 18 keys and two tables; the single-writer registry lost the two catalog-only tables. The bar_derivation APR snapshot prefix (`threshold.bar_integrity.`) counted the cutover keys as read by the census rule; the snapshot is a provenance record, not a digest input, so dropping them changes no derivation.

Rollback: `pg_restore` each dump; `\copy` the three CSVs back (schema, state, history).

Lineage dump: `data/backups/185-38/canonical_bar_lineage_2026-10-07.dump` is 0 days old, under the 30-day rule, so it stays; todo 510 (P3 row) carries its delete date 2026-11-06 together with the 185-43 and 185-45 backups.

## Task 2: docs, todos, housekeeping (fa48d2cce)

- Onboarding SOP: rules 3 and 5, stages 5-7 and 9, the failure table and gap 3 rewritten: the verdict gate, `ohlcv_coverage` progress, the fetcher as the 1d fetch step (Tradier unfunded), no `--timeframes`. 189-09 later updates the fetcher step once the timer runs.
- Canonical truth registry 3.3: rows for d2-v2 canonical 1d (one rule, one writer, sources tradier, ibkr_fallback and ibkr_named by policy, lineage a view), `bar_source_policy`, the write contract (`ohlcv_load`, `ohlcv_revision` for every writer), the verdict report as the gate, ingress modes on the D1 and 5m rows; provider matrix rewritten.
- operations-database: write contract columns, policy, coverage, verdict rows in `integrity_monitor`, the bookkeeping table's removal, the fetcher status file, the Tradier unit disabled.
- gotchas: the backfill_status column gotcha and the placeholder "stored N bars" gotcha deleted; "no split history yet" corrected (`corporate_action` holds one row, ETHA 2026-10-02; pre-2026-10 splits are not recorded); the pipeline CLI and lease line replaced by the fetcher and FetcherLock (189-08 deferred item 9); the timers line updated. The D1 test-isolation rule kept.
- `services/README.md` (was a v2.x unit table) and `src/intelligence/archive/README.md` state current facts; `config/universe/README.md`'s "now sets it" line corrected.
- Design doc Status: implemented (plans 185-31, 185-33, 185-35 to 185-45, 189-07, 189-08; 189-09 to 189-11 pull the new data).
- Todos closed with Resolution sections and SHAs: 056 and 223 (superseded by 185-45 and 509), 317 (table dropped), 462 (fill path gone, coverage ledger), 484 (lanes deleted), 488 (fetcher timeout and watchdog), 500 (the view no longer reads price_sanity_status; all ten bars visible, checked live). Filed: 510 (backup deletion dates), 511 (ISLAND rule owner decision, carried from 500). PRIORITIES rows updated, the Data critical-path row and the v2.x header sentence rewritten; link integrity passes.
- Plan verify: link integrity green, `grep -rln 'backfill_status\|tradier-v1' docs/foundation docs/operations docs/reference` empty, Status implemented. No em dash in any added line.

Housekeeping, each with its rollback:

| Item | Done | Rollback |
|---|---|---|
| Leftover swap or backup tables | None found live | none needed |
| Completed phase directories | Nothing to archive: the GSD cleanup workflow archives phases of completed milestones only, and the one candidate (183) belongs to the open milestone v3.5; 185, 186 and 189 are excluded by the plan | none |
| Rotated logs older than 14 days | 9 found; `regime_writer.log.2` kept (cited by 186-13-SUMMARY and todo 248); 8 deleted, about 0.6 MB: `manual_catchup_run1.log.1`, `tag_calibrator.log.2.gz`, `alpha_publisher.log.3.gz`, `universe_expansion_correlation_structure_check.log.1`, `regime_writer.log.3`, `regime_writer.log.3.gz`, `forward_return_writer.log.1`, `vocabulary_drift_audit.log.1` | none (untracked, uncited) |
| Memory directory | Copied to `data/backups/185-43/memory/` (103 files) first. Deleted `feedback_backfill_status_seed.md` (table gone); resolved history cut from `project_corpus_pipeline_state.md` (synthetic_fill and old ic_engine chain), `project_post_reboot_expected_state.md` (lane relaunch), `project_ibkr_live_ingestion_stalled_2fa.md` (nightly and lease), `project_tradier_primary_daily_source.md` (rebase steps; measured vendor facts kept); MEMORY.md index lines updated | copy files back from the backup directory |

## Task 3: exit criteria (185-COMPLEXITY-EXIT.md)

| Measure | Baseline | Start | End |
|---|---|---|---|
| scripts_total | 103 | 83 | 80 |
| scripts_ops | 36 | 28 | 27 |
| temporary_entries | 2 | 1 | 1 |
| tables_public | 100 | 80 | 77 |
| views_public | 14 | 15 | 15 |
| apr_keys_without_reader | 177 | 211 | 51 |
| services_without_live_consumer | 38 | 21 | 21 |
| todos_pending | 88 | 97 | 92 |
| docs_stale_status | 10 | 10 | 1 |

Two counts rose against the baseline and are explained by name in the exit file: views +1 (`canonical_bar_lineage` became a view in 185-38, replacing a table) and todos +4 (eleven filed by 185-29 to 185-46, 189-08 and this plan, each with an owner, against seven closed). docs_stale_status fell to 1 after the nine archived designs got an Archived Status; the last, `docs/architecture/architecture-overview.md`, is a quarantined draft whose rewrite is its own project.

Gates, in order:

- vulture against the pre-plan tree (`git archive b286a2910`): 102 findings before, 102 after, no new finding (one appeared mid-task, `count_corroborating_symbols_batch`, and was deleted).
- `pytest tests/unit -k "boundary or registry or expiry or readers"`: 253 passed.
- Full `pytest tests/unit`: 7,270 passed, 5 skipped (the same five pre-existing skips) before the Task 1 commit and again with this SUMMARY present (the expiry guard sees no `retire: 185-43` entry left).
- `repro_frozen` (the `src/intelligence/statistics/price_sanity.py` edit): bit-identical (phase 181 S2 and S3).
- ruff and black clean; pre-commit 9/9 on every commit.

## Deviations from plan

1. [Rule 1] Migration number 459, not 452 (see decisions). 185-48's text "unless 452 already did" means 459; `infra.tradier.max_changed_bar_ratio` is retired.
2. [Scope, deletion over edit] Two onboarding scripts the plan listed for editing were deleted instead (pilot draw: completed and unable to run; gap-fill ETFs: completed one-time onboarding). The corrupt-print report script was deleted, an option the plan named.
3. [Rule 3] The fetcher status file was renamed (`ibkr_history_fetcher_status.json`) because the plan's verify grep matched the old file name; the live file was moved with it.
4. [Rule 3] `price_sanity.count_corroborating_symbols_batch` deleted (a statistics edit) to keep vulture at no new finding; repro_frozen run and bit-identical.
5. [Scope] Retired beyond the named keys: the `alpha.frame.*` and `threshold.signal_audit.*` families and seven keys whose code was deleted by 186-23 or never existed (each proven unread by grep; listed in the migration header). Two reader-less tables dropped (`batch_job_checkpoints`, `ic_cell_fingerprints`).
6. [Scope] Docs outside the plan's file list edited because they named removed code: `services/README.md`, `src/intelligence/archive/README.md`, `config/universe/README.md`, nine archived design Status lines.
7. [Not done, by rule] Root `CLAUDE.md` and `src/intelligence/CLAUDE.md` not edited (plan: CLAUDE.md belongs to 189-09). Stale lines for 189-09: root "IBKR: ... Every history fetch takes the `ibkr_history_stream` lease" (now FetcherLock, fail-fast); root "Archived and dormant" (the I8 stack and most of v2.x are removed, not dormant; todo 509 lists what remains); `src/intelligence/CLAUDE.md` AI stack, plugin authoring, LLM chain and Signal Ledger sections.
8. [Not done, by rule] STATE.md, ROADMAP.md and REQUIREMENTS.md not touched (the plan forbids the first two; requirement checkboxes D-06, D-07, D-26 are left to the orchestrator with them).
9. Other stale docs left: the v2.x body of `docs/operations/operations-database.md` under its stale banner (gap-fill and replay commands name the deleted pipeline CLI), `docs/reference/db-maintenance.md` and `docs/reference/services/overview.md` (each one line naming the deleted pipeline CLI), `docs/foundation/naming-system.md`'s example file name. 189-09 owns the fetcher docs pass.

## For the next plans

- 189-10 Task 1: no fetch path writes or reads `backfill_status`; the table is gone, so any plan text that seeds or reads it is void. New names enter the queue from `instruments` and `ohlcv_coverage`. The fetcher writes its status to `logs/ibkr_history_fetcher_status.json` (D7 `nightly_skipped` reads it; the constant is still named `NIGHTLY_STATUS_FILE`). Migration 451 is still free. The onboarding SOP's stage 7 names the fetcher command; 189-09 should update it once the timer runs.
- 185-47: the default 1d policy row is still Tradier primary, IBKR fallback; 74 open IBKR symbol rows and 31 closed ones (unchanged). Migration 456 free. No APR key it reads was retired.
- 185-48: `infra.tradier.max_changed_bar_ratio` is already retired by 459; the other `infra.tradier.*` keys remain for its retirement. Migration 457 free. The operations-database and registry rows already say the loader is disabled and deleted by 185-48; update them to past tense when it lands.
- 186-26: `services/rebuild_preconditions.py` treats this SUMMARY's existence as 185-43 landed. todo 506 (the one TEMPORARY entry) waits on the rebuild.
- Residue recorded, not fixed: late-name dispositions FUBO, LION, RCAT (zero-volume rule, 185-33); `freshness_1d` and `session_coverage` fail until 189-10's update lane runs; todos 505, 507, 508, 509 open (509 is an owner decision); 510 and 511 new.

## Known stubs

None.

## Threat flags

None. T-185-43-01 mitigated by the per-name grep (recorded in the migration header and repeated by the contract test), verified dumps and a dry run; T-185-43-02: the migration names no raw table (the contract test fails on any of them), `market_data_ohlcv`, D1, `ohlcv_revision`, `ohlcv_load`, `corporate_action` and `bar_source_policy` untouched; T-185-43-03: every closed todo cites resolvable SHAs, unresolved items carried to 510 and 511.

## Self-Check: PASSED

- FOUND: migration 459, its contract test, 185-COMPLEXITY-EXIT.md, todos 510 and 511, `data/backups/185-43/backfill_status.dump`.
- FOUND commits: 78d4e90d7, fa48d2cce (pushed); this SUMMARY's commit follows.
- GONE live: `backfill_status`, `batch_job_checkpoints`, `ic_cell_fingerprints`; 0 rows for the 177 keys in config_schema, config_state and config_history.
