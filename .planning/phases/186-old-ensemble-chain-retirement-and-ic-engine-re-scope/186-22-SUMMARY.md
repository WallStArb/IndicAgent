---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 22
subsystem: database
tags: [deletion, migration, timescaledb, old-chain, drop-table]
requires:
  - phase: 186-02
    provides: summary cards covering every dropped table (D-06)
  - phase: 186-09
    provides: feature_lifecycle free of ensemble_weights and alpha_ensemble_ic
  - phase: 186-19
    provides: old-chain services and tests deleted
  - phase: 186-21
    provides: ops scripts, orchestrator steps and old-chain APR keys retired
provides:
  - nine old-chain tables dropped by migration 426 (D-14)
  - orphaned ops readers, the context_features writer and six truncate blocks removed
  - todo 355 closed (R-01)
affects: [186-23, 186-27, 186-28]
key-files:
  created:
    - production/migrations/426_drop_old_chain_tables.sql
  modified:
    - scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh
    - docs/intelligence/intelligence-alpha-frames-and-feature-lifecycle.md
    - docs/foundation/canonical-truth-registry.md
    - docs/foundation/unified-concept-registry.md
    - docs/operations/operations-database.md
    - docs/operations/operations-disaster-recovery.md
    - .planning/todos/PRIORITIES.md
key-decisions:
  - "Row-count guard refuses only growth past the card baseline, so the integration database (smaller tables) replays the migration"
requirements-completed: [D-14, D-06, R-03, R-01, D-07, D-16, D-08]
completed: 2026-10-01
---

# Phase 186 Plan 22: old-chain table drops Summary

Migration 426 dropped `ensemble_weights`, `ensemble_alpha`, `alpha_ensemble_ic`, `alpha_events`, `alpha_frames`, `alpha_strategy_scores`, `context_features`, `feature_ic_scores_history` and `construction_spreads`, freeing about 50.7 GB; the readers they left behind are deleted and todo 355 is closed.

## Commits (branch phase-186-22-chain-drops)

- refactor(186-22): cut the readers orphaned by the old-chain table drops (D-08, R-01)
- feat(186-22): drop the nine old-chain tables (migration 426, D-14)
- docs(186-22): close todo 355 and trim docs naming the dropped old-chain tables
- this SUMMARY commit

Pre-drop sha: `5574497dd0ffc0625cfb8239270470a8c0f4ae0b` (main HEAD at the start, ancestor of main).

## Gate results (task 1)

1. D-06: `tests/unit/test_summary_cards.py` green with git checks active; all seven covering cards present (`cache-context-features`, `cache-feature-ic-scores-history`, `legacy-ensemble-champion`, `legacy-phase142a-ensemble-ic`, `legacy-phase142b-frames-frame04`, `legacy-phase148-score-01-03`, `legacy-ctf-momentum-decile-ls`).
2. D-01: `ps` for ic_engine, ic_measure, backfill_feature_factory, regime_writer, rebuild, ops_corpus_pipeline_run empty; `logs/ic_engine.log` empty, `.log.1` last written 2026-10-01 00:53 UTC; no corpus run.
3. Dependencies: the four services absent; `scripts/analysis` 2 tracked files; feature_lifecycle grep 0; `ops_ic_shrinkage.py` absent; `REQUIRED_STEPS = ["ic_engine"]` count 1; four APR keeps count 4.
4. `pg_stat_activity` readers of the nine names: 0 rows.

## D-08 inventory

Live hits over src, services, scripts, tests, tools, dashboard/src, production/systemd (migrations, `.planning` and dated docs excluded):

- Removed here: `ops_corpus_progress.py`, `ops_cost_hurdle_calibration.py` (and `tests/unit/test_cost_hurdle_calibration.py`, which imported it), `watch_todo335_recompute.sh`, the writer `infrastructure_context_features_writer.py`, 24 truncate-script lines (six count rows twice, six TRUNCATEs, two comment blocks), `tests/unit/test_alpha_frames_schema.py`, `tests/unit/test_alpha_frames_target_r_multiple_migration.py`, `tests/integration/test_construction_spreads_schema.py`.
- Comment or history, kept: `breadth_vol.py`, `curve_credit.py`, `compression_auditor.py` and its test, `ops_corpus_final_verification.py` docstring, `test_corpus_manifest_verifier.py`, `test_feature_vector_pipeline_regime_none.py`, `_source_grep_helpers.py`, `tools/pre-commit.hook` and `tools/check_counterfactual_ledger.sh` (allow-list and remediation text about new tables), `test_feature_lifecycle.py:632` (asserts the source no longer names the old keys), `test_summary_cards.py` (DROP_TABLES), the two schema baseline fixtures (frozen snapshots of past schemas).
- Deliberate live reader: `services/ic_engine.py` lines 1423 and 1460 INSERT into `feature_ic_scores_history`. Old ic_engine is non-runnable from this drop until 186-23 deletes it (strangler order); never run it in between.
- v2.x payload key `context_features` (signal_events, signal_processor, signal_writer, trading/*, debug scripts, tests): different concept, untouched.
- `topic_alpha_events`: already deleted by 186-19, no callers.
- Writer-script APR keys: `feature.vix.zscore_window` (read by `services/backfill_feature_factory.py:339`, `services/feature_vector_pipeline.py:1073`), `feature.yield_curve.zscore_window` (same files, 340, 1074), `feature.cross_asset.rv_window` (357, 1091): all KEEP, no APR deletes in the migration.
- The `scripts/ops/corpus/ops_corpus_final_verification.py` verifier surface and `corpus_manifest_verifier.py` name none of the nine tables as readers; the ic_engine entry is untouched for 186-23.
- Kafka topic for alpha events is transport; left alone.

## Baselines and migration effects

Row counts equalled the card baseline exactly: ensemble_weights 358, ensemble_alpha 106,690,090, alpha_ensemble_ic 0, alpha_events 65,622,721, alpha_frames 0, alpha_strategy_scores 120, context_features 8,985, feature_ic_scores_history 49,568,124, construction_spreads 130,625.

Hypertable sizes before: feature_ic_scores_history 38 GB, alpha_events 5,617 MB, ensemble_alpha 3,367 MB, construction_spreads 133 MB, alpha_frames 56 kB, alpha_ensemble_ic 32 kB.

Jobs before: 1067 (ensemble_alpha), 1068 (alpha_events), 1069 (alpha_frames), 1070 (construction_spreads), 1071 (feature_ic_scores, survivor), 1072 and 1073 (feature_ic_scores_history compression and retention).

Applied live with `psql -v ON_ERROR_STOP=1 -f`, exit 0 (3.8 s), then committed:

- `to_regclass` NULL for all nine names; non-NULL for `forward_returns`, `feature_vectors`, `feature_ic_scores`.
- Jobs 1067-1070, 1072, 1073: 0 left; `feature_ic_scores` still has job 1071.
- Four 186-21 APR keeps still count 4.
- `pg_database_size('indicagent')`: 191,954,589,375 bytes (179 GB) before, 141,228,947,135 bytes (132 GB) after; 50.7 GB freed. `df -h /` used 372G to 325G. With 186-23's `forward_returns` drop the phase target of about 61 GB is still ahead.
- Migration number 426 from the live tail (425 landed from 186-24; re-checked in the main tree immediately before the apply, no 426 elsewhere). The vacuum-check and migration-uniqueness tests pass; a plain drop needs no VACUUM.

## Verification

- ruff: only the two pre-existing I001 findings (`test_repro_frozen.py`, `test_bar_campaign_preflight.py`, outside this plan); black clean; vulture output identical to the baseline (59 lines); unit and integration collection clean; full `pytest tests/unit` exit 0 on the branch.
- No edit under `src/intelligence/research/`, `scripts/research/` or `src/intelligence/statistics/`; the determinism repro was not required.
- `bash -n` passes on the truncate script; it keeps feature_ic_scores, forward_returns, market_regimes, feature_vectors and backfill_status.

## Deviations from Plan

1. [Rule 1] The row-count guard raises only when a table grew past its baseline, not on any difference. `tests/integration/conftest.py` replays migrations above its baseline on the integration database, where the tables hold different (smaller) counts; an equality guard would fail there. Growth is the case that means unrecorded data.
2. [Rule 3] Two test files beyond the plan's list were deleted because they exercised deleted code or dropped tables: `tests/unit/test_cost_hurdle_calibration.py` (imports the deleted script) and `tests/unit/test_alpha_frames_target_r_multiple_migration.py` (migration-text assertions for `alpha_frames`; 186-21 relay). `tests/integration/test_cross_sectional_spread_tracker.py` was already gone (186-19).
3. The first commit initially missed the edited truncate script (unstaged); amended before anything was pushed.
4. `tools/vulture_whitelist.py`, `src/core/stream_keys.py` needed no edit (vulture unchanged; `topic_alpha_events` already deleted).
5. Docs trimmed: the feature lifecycle doc was rewritten to the data-quality role (the alpha_frames, CounterfactualTracker and ensemble sections described deleted code); `docs/reference/gotchas.md` and `docs/reference/services/overview.md` left as measured history.

## Hand-off

- 186-23: old `services/ic_engine.py` cannot run (its history INSERT targets a dropped table); delete it with `forward_returns`; repoint `REQUIRED_STEPS` and the orchestrator ic_engine step.
- 186-28: job 1071 and `feature_ic_scores` remain.

## Known Stubs

None.

## Self-Check: PASSED

Deleted files absent, migration 426 present and applied, three task commits on the branch.
