---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 19
subsystem: infrastructure
tags: [deletion, ensemble, old-chain, vulture, service-auditor]
requires:
  - phase: 186-03
    provides: determinism tool promoted to scripts/research/determinism
  - phase: 186-09
    provides: feature_lifecycle no longer reads the old chain's tables
  - phase: 186-11
    provides: ctx-writer retired, deny-list precedent
  - phase: 186-14
    provides: ic_measure registered in service_auditor
  - phase: 186-16
    provides: scripts/analysis deleted (last importers)
provides:
  - old ensemble chain code, tests and unit files deleted (D-09); git history is the archive (D-13)
  - src/intelligence/ensemble/ reduced to covariance, shrinkage, weights with an import-free __init__ (R-04)
  - five old-chain units deny-listed in the service_auditor registry test
affects: [186-21, 186-22, 186-23]
tech-stack:
  added: []
  patterns:
    - "package __init__ with no eager imports so one submodule loads no other"
key-files:
  created: []
  modified:
    - src/intelligence/ensemble/__init__.py
    - src/intelligence/ensemble/weights.py
    - src/intelligence/ensemble/covariance.py
    - services/service_auditor.py
    - services/_batch_utils.py
    - src/observability/metrics.py
    - src/core/stream_keys.py
    - src/core/agent/base_batch.py
    - tools/vulture_whitelist.py
    - .mypy-baseline.txt
key-decisions:
  - "Spread tracker deleted because R1 (rank_vol_neutral_weights/returns in research/portfolio.py) covers the long-short construction role and the card legacy-ctf-momentum-decile-ls preserves the decile spec (D-07)"
requirements-completed: [D-09, R-04, D-07, D-08, D-13, D-01]
duration: about 70 min
completed: 2026-10-01
---

# Phase 186 Plan 19: old-chain deletion Summary

Eight old-chain services, `gate_math.py`, three ensemble modules, two unit files and 34 test files are gone; the research package still loads only `covariance`, `shrinkage` and `weights`, and the frozen books reproduce bit-identically on merged main.

## Commits (on main, ff-only merge)

- `d70700e55` refactor(186-19): delete the old ensemble chain services, modules and tests (D-09, R-04)
- `a9cc258f9` refactor(186-19): remove metrics, topic and helpers used only by the deleted chain
- `9b2e37b59` docs(186-19): drop current-fact references to the deleted old chain
- the SUMMARY commit (includes a stale-comment cleanup in `tests/unit/test_ensemble_math.py`)

Pre-delete sha (last commit holding the old-chain services): `2d4c2e4e13980202ad2e06e0cb44dfd049aa41c4`. `git diff --shortstat` to HEAD: 76 files, 72 insertions, 18,381 deletions.

## Task 1 gate results

1. D-01: no ic_engine, ic_measure, backfill_feature_factory, regime_writer or rebuild process; `logs/ic_engine.log` empty, `.log.1` ends 2026-09-30 19:21 UTC with ic_measure bulk-load writes only (no corpus run); STATE.md lane table names no live or resumable ic_engine or rebuild run. Pass.
2. No process runs a deleted module or the orchestrator scripts. Pass.
3. No old-chain unit installed (`systemctl list-unit-files`, `/etc/systemd/system`). Pass.
4. Timers: regime-coverage-auditor, dividend-event-writer@yahoo, nightly-backfill; none invokes the orchestrator; no crontab. Pass.
5. SUMMARYs 03, 09, 11, 14, 16 present; `scripts/analysis` has 2 tracked files (limit 3); feature_lifecycle grep 0; ctx-writer 0; ic-measure 2. Pass.
6. Determinism tool loads only `ensemble.alpha_score` and `feature_selector` of the deleted names (through the package init, removed here). Pass.
7. `test_summary_cards.py` passes with no skip; `decile_fraction` count 1; both `rank_vol_neutral_*` defs present. Pass.

## D-08 inventory

Real importers (grep of `(from|import)` lines) of the deleted modules outside themselves and the deleted tests: `ensemble/__init__.py:18,20`, `scripts/ops/corpus/ops_oos_gate1_signal_eval.py:63`, `scripts/ops/alpha/ops_ensemble_ablation.py:85`. After this plan only the two 186-21 scripts remain (plus one comment in `test_ensemble_math.py`, removed in the SUMMARY commit). Comment-only mentions in surviving modules and about 100 dated docs stay as records. No timer, cron or unit runs the two ops scripts or the orchestrator. Metric, topic and `alert.lag.*` consumers: none found. Tests that mention deleted names only as strings or comments were kept (`test_migration_number_uniqueness.py`, `test_emission_threshold_sweep.py`, `test_ensemble_ic_bh_fdr.py`, `research_tools/test_determinism_modules.py`, `research_tools/test_repro_frozen.py`, plus the kept list in the plan).

Todo dispositions: 009, 223, 228 got a dated note (subject or fix is a deleted module); 317 and 191 already state the deletion or the module as provenance only; 099 mentions `ensemble_trainer.py` as provenance only.

## Test delete list (34 files, each imports or source-reads only deleted code; list matched the plan with no differences)

Ensemble trainer (4 under tests/unit/services plus test_ensemble_trainer, _ic_input, _meta_cols, _weight_method, test_ensemble_weight_epoch, test_ensemble_meta_fdr), alpha frame writer (3), alpha publisher (2), alpha scorer, counterfactual tracker (2), cross-sectional spread tracker (unit and integration), ensemble IC engine (config, decay, executable_returns, idempotency, measurement_population, pooled_dispatch, stop_target_calibration, wf_stability, worker_fetch), test_ensemble_ablation and test_oos_gate1_signal_eval (they test 186-21's scripts, which import the deleted service), test_frame_gate, test_gate_math, test_stratum_fit.
Edited: `test_ensemble_math.py` (EffectiveN and ComputeShrinkageCovariance only), `test_batch_utils.py` (resolve_per_tf tests removed), `test_compute_universe_readers.py`, `test_span_coverage_compliance.py`, `_source_grep_helpers.py`, `test_service_auditor_registry_integrity.py` (five units on `_ARCHIVED_UNIT_DENYLIST`, three stale allow-list rows removed).

Collected unit tests: 8,388 before, 7,940 after.

## Dead code removed or whitelisted

Deleted: seven `ENSEMBLE_*`/`ALPHA_PUBLISHER_*`/`COUNTERFACTUAL_TRACKER_*` metric constants plus `ALPHA_PUBLISHER_REJECTIONS_TOTAL` (and their whitelist line), `topic_alpha_events`, `BaseBatch._run_with_manifest_capture` (and its two unused imports), `resolve_per_tf`, `covariance_to_correlation`, `derive_weights`, `cluster_deflate_weights`. In `weights.py` and `covariance.py` only deletions plus docstring rewording; `effective_n`, `mean_variance_weights` and `compute_shrinkage_covariance` are byte-unchanged.
Whitelist additions (reasons in the file): `_.itersize` (ic_engine named-cursor fetch size, deleted whole by 186-23) and `set_config_service` (APR hook in `src/intelligence/trading/`, only caller was alpha_frame_writer, fate is todo 223). Removed whitelist line: `evaluate_stratum_expectancy_gate` (gate_math).
mypy-baseline: one line removed (`gate_math.py`). Vulture output after equals before (59 lines, both pre-existing).

## Verification on merged main

- Full `pytest tests/unit` exit 0; `tests/unit/research` and `tests/unit/research_tools` pass.
- Determinism repro (log in the session scratchpad, `repro_186_19.log`): three lines, `phase 179 S3`, `phase 181 S2`, `phase 181 S3`, all bit-identical, no error text.
- `import src.intelligence.research.portfolio` loads exactly `ensemble`, `covariance`, `shrinkage`, `weights`.
- `git diff 2d4c2e4e1 HEAD` over research, scripts/research, tests/unit/research, ic_engine, forward_return_writer, scripts/ops, migrations and corpus_manifest_verifier is empty.
- No research run was live at merge.

## Deviations from Plan

1. [Rule 3 - ordering] SUMMARY was written on main after the merge and post-merge proof, not on the branch, so it records real repro results. Main was ff-merged locally, proven, then pushed; nothing was pushed before the proof.
2. [Pre-existing] `mypy src | mypy-baseline filter` exits 100 on main before this plan (947 error lines not in the baseline, from other sessions' code); the criterion was applied as "no new error": the sorted error sets before and after differ only by the removed gate_math line.
3. [Pre-existing] `ruff check .` reports two I001 import-order findings in `tests/unit/research_tools/test_repro_frozen.py` and `tests/unit/scripts/test_bar_campaign_preflight.py`; both files are outside this plan (D-02 research lane and another session) and untouched.
4. Vulture baseline on main is 59 lines, not 2 as the plan text said; the rule "no new finding" holds.
5. CLAUDE.md line 159 no longer cited `ensemble_trainer.py` (186-04 repointed it); only line 51 changed.

## Hand-off

- 186-21: `scripts/ops/alpha/ops_ensemble_ablation.py` and `scripts/ops/corpus/ops_oos_gate1_signal_eval.py` fail at import until deleted; `ops_corpus_pipeline_run.sh` steps 7-8 call deleted services; `corpus_manifest_verifier` step names; `infra.alpha_frame_writer.*`, `infra.counterfactual_tracker.*` and other old-chain APR keys; `ops_pipeline_monitor.sh`. Window between this plan and 186-21: nothing runs them automatically.
- 186-22: `tests/unit/test_alpha_frames_schema.py`, `tests/integration/test_construction_spreads_schema.py`, the tables (`alpha_ensemble_ic`, `ensemble_alpha`, `ensemble_weights`, `alpha_events`, `alpha_frames`, `construction_spreads`); canonical-truth-registry carries a comment that they have no writer.
- 186-23: `_.itersize` whitelist entry leaves with ic_engine.

## Self-Check: PASSED

Files deleted confirmed absent, ensemble package holds `__init__`, `covariance`, `shrinkage`, `weights`; commits d70700e55, a9cc258f9, 9b2e37b59 present on main; worktree and branch removed.
