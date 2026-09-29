---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 09
subsystem: feature-lifecycle
tags: [feature_lifecycle, data-quality, concept_registry, apr, migration-387]
requires: []
provides:
  - src/intelligence/statistics/feature_coverage.py (shared coverage statistic, one definition)
  - data-quality feature_lifecycle (no reader of ensemble_weights, feature_ic_scores, alpha.ensemble.*, alpha.decay.*)
  - migration 387 (four feature.* APR keys, two trigger reasons)
affects: [186-19, 186-21, 186-22, todo-421, todo-435]
tech-stack:
  added: []
  patterns: [one aggregate query per tf over the lookback span, dtype from information_schema, pure verdict over counts]
key-files:
  created:
    - src/intelligence/statistics/feature_coverage.py
    - tests/unit/test_feature_coverage.py
    - production/migrations/387_feature_lifecycle_data_quality.sql
  modified:
    - services/feature_lifecycle.py
    - src/intelligence/concept_registry_service.py
    - src/observability/metrics.py
    - tests/unit/test_feature_lifecycle.py
    - tests/unit/test_concept_registry_service.py
    - src/intelligence/schemas.py
    - scripts/ops/alpha/ops_concept_registry_override.py
    - docs and planning files listed in the plan
  deleted:
    - scripts/ops/alpha/ops_concept_feature_migration_verify.py
    - tests/unit/test_feature_edge_by_regime_filter_parity.py
decisions:
  - "LifecycleGate holds only demotion_min_consecutive and recovery_min_passes from APR; concept_gate.min_demotion_consecutive and recovery_min_observations are no longer read."
  - "Derivation reads only concept_evaluation rows whose detail carries per_tf (this rule's rows), so IC-era rows in the shared ledger are never evidence."
  - "data_quality_restored is exempt from the L-6 FDR guard; data_quality_fail and data_quality_restored are automated reasons and cannot target deprecated."
metrics:
  tasks: 3
  completed: 2026-09-29
---

# Phase 186 Plan 09: feature_lifecycle shrunk to data-quality checks

feature_lifecycle now decides a governed feature's status from three checks (computed, finite, symbol coverage at or above the APR floor `feature.coverage.min_symbol_fraction`), using a pure statistic in `src/intelligence/statistics/feature_coverage.py` that todo 421 and todo 435 can import.

## Commits

- e43ecef64 test(186-09): failing tests for the shared coverage statistic (RED)
- e7bcda72e feat(186-09): shared feature coverage statistic and verdict (GREEN)
- 02590dbcc feat(186-09): feature_lifecycle decides status from data quality (migration 387 with the code that reads its keys)
- bfed851f9 chore(186-09): feature_registry residue removal and doc corrections
- 9bc705a89 refactor(186-09): simplify failure counting, drop a dead NaN check

## D-01 gate

`ps aux | grep -E "ic_engine|backfill_feature_factory|regime_writer|rebuild|ic_measure" | grep -v grep` returned nothing before any edit. STATE.md lists no live or resumable ic_engine or rebuild run.

## D-08 consumer grep

Live hits handled here: `services/feature_lifecycle.py`, `tests/unit/test_feature_lifecycle.py`, `tests/unit/test_feature_edge_by_regime_filter_parity.py` (deleted), `scripts/ops/alpha/ops_concept_feature_migration_verify.py` (deleted), `src/intelligence/schemas.py` comment. Old-chain hits left for 186-19/186-21: `services/ensemble_trainer.py`, `services/alpha_publisher.py`, `scripts/ops/alpha/ops_ic_shrinkage.py`, `ops_ensemble_ablation.py`, `ops_ensemble_weight_compare.py`, `ops_emission_threshold_sweep.py`, `services/generate_ic_discovery_report.py`, `scripts/ops/corpus/ops_corpus_pipeline_run.sh` (step 5 still passes `--training-window-end`, which is kept), `ops_corpus_progress.py`, `services/service_auditor.py`, `services/ic_engine.py` (a comment naming `feature_lifecycle.guard_cells`, left untouched to avoid moving ic_engine's code key), the truncate script, and several old-chain tests.

## Migration

387 (`production/migrations/387_feature_lifecycle_data_quality.sql`), applied live and committed with the code that reads it. Live tail was 386 when checked immediately before writing and applying. Effects: four APR keys seeded (`feature.coverage.min_symbol_fraction` 0.95, `feature.lifecycle.lookback_days` 90, `feature.lifecycle.demotion_min_consecutive` 2, `feature.lifecycle.recovery_min_passes` 1); `concept_transition_log_trigger_reason_check` re-added with `data_quality_fail` and `data_quality_restored` (table is an uncompressed hypertable, no VACUUM step).

## Dry run on the last corpus window

`python services/feature_lifecycle.py --training-window-end 2025-12-24T05:15:00+00:00 --dry-run`, wall clock about 12 s total. Per-tf query time: 1d 1.19 s, 1h 1.19 s, 5m 5.4 s, 15m similar to 1h (4 tfs). 295 features evaluated, 18 failing:

- not_computed (6): `asian_session_high_dist_atr`, `asian_session_low_dist_atr`, `momentum_rank_z`, `ret_div_1m_5m`, `volatility_rank_z`, `volume_rank_z`
- coverage, intraday only (8 velocity and overnight): `cvd_slope_z_velocity`, `ofi_z_velocity`, `rsi_velocity_fast`, `rsi_velocity_mid`, `rsi_velocity_slow`, `volume_z_velocity` (min coverage 0.041); `overnight_high_dist_atr`, `overnight_low_dist_atr`, `overnight_range_pct` (0.53)
- coverage at all tfs (3): `hmm_duration`, `hmm_entropy`, `hmm_regime_prob` (0.22)

By check and tf: coverage 5m 12, 15m 12, 1h 12, 1d 3; not_computed 6. Planned transitions: none (a single window cannot reach demotion_min_consecutive of 2). The dry run wrote nothing: `concept_evaluation` rows with `run_ref like 'feature_lifecycle:%'` in the last day = 0. The three hmm_* features and the asian_session pair are additions to what todo 421 predicted; the rebuild (186-25/186-26) is expected to fix source coverage, and no real run should apply demotions before it.

## Verification

- New and rewritten tests: 45 in `test_feature_lifecycle.py`, `test_feature_coverage.py`, `test_concept_registry_service.py` slice pass; 11 in test_feature_coverage.
- `pytest tests/unit -q` on the branch: green (3 skips, all pre-existing).
- No old-chain name in `services/feature_lifecycle.py` (source test plus grep 0); removed metric names have zero hits in src, services, scripts, tests.
- `git diff --stat main -- src/intelligence/research/` empty; `feature_coverage.py` imports nothing from asyncpg or ConfigService (0 hits), so repro_frozen.py was not required.
- `to_regclass('feature_registry')` and `to_regclass('feature_transition_log')` both empty. Migration 311 landed in commit 95e19e528.

## Deviations from Plan

1. [Rule 2] Added the `detail ? 'per_tf'` filter to the ledger load. The ledger holds IC-era rows for the same windows; without the filter they would count as data-quality evidence toward the demotion streak.
2. [Rule 3] Acceptance grep for `feature_registry` outside `ensemble_trainer.py` and `ops_ic_shrinkage.py` is not empty: remaining hits are historical prose (docs/foundation/unified-concept-registry.md, glossary, apr-calibration-backlog), code comments saying the table no longer exists (`scripts/analysis/_nonlinear_interaction_combiner_shared.py`), test docstrings (`test_ic_engine.py`, `test_ensemble_trainer_alignment_gate.py`, `test_concept_parent_lineage.py`, `test_migration_schema_sync.py`) and schema baseline fixtures. None reads the dropped table. Rewriting history text was judged out of scope.
3. Design 14.3 correction: only one line (730) exists in the design doc; the "line near 197" reference in the plan did not match anything.
4. `docs/research/concept-unified-registry.md` line 23 rewritten in place (a dated history entry naming the deleted script); the line already carried em dashes, which were not swept.
5. `/simplify` and `/review` were done as a manual pass in this dispatch (one simplification commit, 9bc705a89); the slash-command skills were not invoked.
6. `STATE.md` not edited (coordinator owns it); it was not checked for phase 170 07-08 wording.

## APR keys that lost their reader in feature_lifecycle (for 186-21)

`alpha.decay.materiality_threshold`, `guard_band_z`, `guard_min_cells`, `guard_min_history`, `guard_history_window`, `recovery_min_observations`, `recovery_min_passes`, `demotion_min_consecutive`; `alpha.ensemble.meta_fdr_min_fraction`, `alpha.ensemble.weight_version`, `alpha.ensemble.sign_symmetric`; `alpha.ic.staleness_alert_days`. Other readers may remain (ensemble_trainer and old-chain tools); 186-21 re-greps before deleting. `concept_gate.min_demotion_consecutive` is also no longer read. All left in place.

## Known Stubs

None.

## Self-Check: PASSED
