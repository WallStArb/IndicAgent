---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 21
subsystem: infrastructure
tags: [deletion, ops-scripts, apr, orchestrator, migration]
requires:
  - phase: 186-19
    provides: old-chain services deleted
provides:
  - seven old-chain ops scripts and four unit files deleted (D-10)
  - five-step corpus orchestrator ending at feature_lifecycle
  - migration 424 retiring 51 old-chain APR keys per key (D-08)
affects: [186-22, 186-23]
key-files:
  modified:
    - scripts/ops/corpus/ops_corpus_pipeline_run.sh
    - scripts/ops/corpus/ops_pipeline_monitor.sh
    - scripts/ops/corpus/ops_corpus_final_verification.py
    - src/observability/corpus_manifest_verifier.py
    - tools/vulture_whitelist.py
  created:
    - production/migrations/424_retire_old_chain_apr_keys.sql
key-decisions:
  - "51 of 53 candidate APR keys retired; mv_condition_max and cluster_regime_conditioned kept (live readers)"
requirements-completed: [D-10, D-09, D-08]
completed: 2026-10-01
---

# Phase 186 Plan 21: old-chain ops scripts and APR keys Summary

The old chain's operational surface is gone: seven ops scripts, their four unit files, orchestrator steps 6-8 with the WEIGHT_EPOCH block, the dead verifier branches and the ensemble_weights check, and 51 APR keys by literal per-key delete.

## Commits (branch phase-186-21-old-chain-ops-apr)

- refactor(186-21): delete old-chain ops scripts and cut the orchestrator steps after feature_lifecycle (D-10)
- chore(186-21): migration 424 retires the old-chain APR keys (D-08, per key)
- docs(186-21): state the deletion of the old-chain ops scripts and retired APR rows
- this SUMMARY commit

Pre-delete sha: `c250a09645a51c44b1a645314ff390a690e7af8a` (ancestor of main).

## Gate results (task 1)

1. D-01: `ps` for ic_engine, ic_measure, backfill_feature_factory, regime_writer, rebuild, orchestrator empty (a `pgrep -f` hit was the checking shell itself, confirmed by `ps -p`); `logs/ic_engine.log` empty, `.log.1` last written 2026-10-01 00:53 UTC with ic_measure bulk-load lines ending 2026-09-30 19:21; STATE.md lane table has no live or resumable ic_engine run. Pass.
2. Services gone, `scripts/analysis` has 2 tracked files, feature_lifecycle grep 0. Pass.
3. Timers: nightly-backfill, regime-coverage-auditor, dividend-event-writer@yahoo; none runs the orchestrator; no crontab. Pass.
4. `test_summary_cards.py` passes, no skip. Pass.

## D-08 inventory

Importers of the seven names: only the four deleted test files and the scripts themselves (ablation, ic_gate, weight_compare reference ic_diagnosis; all deleted). No `src/` or `services/` import. Comment and history mentions in `services/_batch_utils.py`, `services/ic_engine.py`, `tests/unit/test_batch_utils.py`, `tests/unit/test_fisher_z_ci.py`, `tests/unit/test_ic_engine_incremental_write.py`, `concept_registry_service.py`, `ops_ic_null_calibration.py`, `ops_interaction_primitives_pilot.py`, migrations, schema fixtures and dated docs stay as history. `tests/unit/test_ensemble_ablation.py` and `test_oos_gate1_signal_eval.py` were already gone (186-19).

Orchestrator edit sites: banner `/8` to `/5`; header; `check_canary_integrity` skip `FROM_STEP > 6` to `> 5` and message; WEIGHT_EPOCH block; feature_lifecycle comment; steps 6, 7, 8; two audit comments. Monitor: SERVICE_PATTERN, `Step [0-9]/5`, completion marker. Verifier: Check 6, two recovery branches, two ic_engine remediation lines. Verification script: REQUIRED_STEPS.

## APR disposition (53 candidates, 51 deleted)

Per-key grep (literal key plus prefix and f-string forms) over `services src scripts tools tests`, ignoring comments and the deleted scripts. Runtime readers found:

| Key | Reader | Disposition |
|---|---|---|
| alpha.ensemble.mv_condition_max | services/tag_calibrator.py:1254; scripts/research/determinism/config.py:53 | KEEP |
| alpha.ensemble.cluster_regime_conditioned | services/ic_engine.py:840 | KEEP, 186-23 hand-off |
| alpha.ic.shrinkage_k, alpha.ic.canary_rng_seed, alpha.ic.lookahead.* | outside candidate families | untouched |

Other hits were test dict literals (`test_batch_utils.py`: max_feature_weight, min_passing_features, weight_version, sign_symmetric), a docstring (`ic_engine.py:1918`, sign_symmetric) and migration-text reads (`test_alpha_frames_schema.py`, `test_alpha_frames_target_r_multiple_migration.py`, 186-22 scope); none read the DB. Deleted: 10 `alpha.decay.*`, 20 `alpha.ensemble.*`, 9 `alpha.ensemble_ic.*`, 7 `alpha.scoring.*`, 4 `infra.*` (1 alpha_frame_writer, 3 counterfactual_tracker), `alpha.ic.staleness_alert_days`; the exact list is the literal list in migration 424. The live DB held 53 candidates (plan measured 52).

## Migration 424 effects

Applied live from the worktree (psql exit 0): DELETE 76 config_history, 51 config_state, 51 config_schema. Post-apply: retire-prefix count in config_state 0; four keeps present (4); `alpha.ic.lookahead.%` 20 before and after; config_schema retire-prefix count 0; `alpha.regime.groups` present (1, per the 186-20 relay); `alpha.ensemble.%` left: 2. Numbered 424 from the live tail (423 landed from another session during the plan; re-checked before write and before apply).

## Verification

- Full `pytest tests/unit` exit 0 in the worktree after task 2; collection clean for unit and integration.
- ruff: only the two pre-existing I001 findings (`test_repro_frozen.py`, `test_bar_campaign_preflight.py`, both outside this plan); black clean; duplicate-test check, glossary check and todo link integrity pass.
- Vulture: output identical to before. Four items whose only callers were the deleted scripts (`feature_to_group`, `fisher_z_difference_p`, `ensure_success_for`, `record_comparison_outcome`) sit in files this plan may not edit (research lane D-02, ic_engine import closure D-01, registry service), so each is whitelisted with a reason; the stale `weight_mass_fraction` line was removed.
- Smoke: `bash -n` passes on both shell scripts; `--bogus` prints the usage line and exits 1 (the script's existing behavior; the plan text said 2).
- No edit under `src/intelligence/research/`, `scripts/research/` or `src/intelligence/statistics/`; determinism repro not required.

## Deviations

1. Plan said the usage smoke exits 2; the script exits 1 (non-zero with usage text). Left unchanged.
2. Candidate and delete counts are 53 and 51 (plan expected 52 and about 48), from the live DB at run time.
3. Four vulture whitelist additions (above), per the plan's whitelist-with-owner rule.
4. Verifier check keys: the surviving checks are unnumbered in log keys apart from the "Check 7" comment, left as is.

## Hand-off

- 186-22: `ensemble_weights` and the other old-chain tables; `test_alpha_frames_schema.py` and `test_alpha_frames_target_r_multiple_migration.py` still name retired keys as migration text.
- 186-23: `alpha.ensemble.cluster_regime_conditioned` (ic_engine.py:840); `REQUIRED_STEPS = ["ic_engine"]` and the orchestrator's ic_engine step; vulture entries for `ensure_success_for` and `fisher_z_difference_p` follow ic_engine and ic_math; `record_comparison_outcome` has no caller (UCR service fate).
- Research lane: `feature_to_group` in `scripts/research/determinism/results.py` has no reader left outside snapshot_io and tests.

## Known Stubs

None.

## Self-Check: PASSED

Deleted files absent, migration present and applied, three task commits on the branch.
