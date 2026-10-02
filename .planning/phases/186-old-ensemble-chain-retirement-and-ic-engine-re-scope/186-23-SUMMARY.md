---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 23
subsystem: measure
tags: [ic-measurement, apr, timescaledb, deletion, corpus-pipeline]
requires:
  - 186-16 (analysis scripts deleted)
  - 186-20 (committed parity report, PASS writer-path cell)
  - 186-21 (ops surface and REQUIRED_STEPS hand-off)
  - 186-22 (nine old-chain tables dropped)
  - 185 D-14 (bar flags landed in src/intelligence/bars/scrub_rules.py)
provides:
  - forward_returns table dropped (migration 430, ~14 GB freed)
  - 39 orphaned APR keys retired (430 + 431)
  - orchestrator/monitor/verifier repointed at ic_measure, 1-4 pipeline
  - CLAUDE.md Invariant 1 rewritten to the kernel
affects: [186-26 (rebuild gates include this drop), 186-27/186-28 (own feature drops)]
tech-stack:
  added: []
  patterns: ["guarded DROP TABLE with pg_stat_activity reader guard", "literal per-key APR retirement IN-lists (migrations 360/361 pattern)"]
key-files:
  created:
    - production/migrations/430_drop_forward_returns_retire_lookahead_keys.sql
    - production/migrations/431_retire_cluster_max_corr.sql
  modified:
    - scripts/ops/corpus/ops_corpus_pipeline_run.sh
    - scripts/ops/corpus/ops_pipeline_monitor.sh
    - scripts/ops/corpus/ops_corpus_final_verification.py
    - scripts/ops/corpus/ops_known_corrupt_print_cleanup.py
    - scripts/ops/corpus/ops_oos_holdout_eval.py
    - scripts/ops/alpha/ops_broadcast_feature_audit.py
    - scripts/ops/alpha/ops_dependence_length_diagnostic.py
    - services/service_auditor.py
    - services/_batch_utils.py
    - src/observability/metrics.py
    - src/observability/corpus_manifest_verifier.py
    - src/core/code_identity.py
    - CLAUDE.md
    - tools/vulture_whitelist.py
    - docs/foundation/glossary.md
    - docs/foundation/canonical-truth-registry.md
    - docs/foundation/apr-calibration-backlog.md
    - docs/foundation/instrument-tag-registry.md
    - docs/reference/services/overview.md
    - docs/reference/db-maintenance.md
    - docs/reference/naming-conventions.md
  deleted:
    - services/ic_engine.py (6,755 lines)
    - services/forward_return_writer.py
    - scripts/ops/alpha/ops_ic_null_calibration.py
    - scripts/ops/alpha/ops_interaction_primitives_pilot.py
    - scripts/ops/alpha/ops_vol_normalized_target_ab.py
    - scripts/ops/alpha/ops_lookahead_horizon_response.py
    - scripts/ops/corpus/ops_ic_fingerprint_equivalence.py
    - 21 test files (20 ic_engine/writer tests + tests of deleted ops scripts)
decisions:
  - "alpha.forward_returns.gap_* and corroboration keys KEEP: 185's bar-flag code reads them (plan anticipated this branch)"
  - "infra.ensemble_ic_engine.* retired here: 186-19 deleted their only reader but left the keys; grep-justified orphan"
  - "alpha.ic.cluster_max_corr retired by follow-up migration 431: Task 1's namespace-prefix enumeration missed it; docs-pass grep found zero surviving readers"
  - "the old engine's P6 metrics block deleted with the service (no surviving emitter), beyond the plan's named P5 block"
  - "TRAINING_WINDOW_END hand-off dropped: ic_measure derives its own window and enforces alpha.validation.oos_start itself (D-19)"
metrics:
  duration: "one session (resumed once after a 429 usage-limit stop mid-Task 3)"
  completed: 2026-10-02
---

# Phase 186 Plan 23: Old IC stack deletion (ic_engine, forward_return_writer, forward_returns, lookahead keys) Summary

One change deleted the old measurement stack end to end: 6,755-line `services/ic_engine.py`, `services/forward_return_writer.py`, their 21 test files, the five table-reading/orphaned ops scripts, the 14 GB `forward_returns` hypertable (migration 430, applied and committed together), and 39 orphaned APR keys; the corpus orchestrator, monitor, verifier and CLAUDE.md now describe exactly the ic_measure + kernel-target path.

## Gates (Task 1, all recorded before any edit)

1. **Parity evidence: PASS.** `186-20-PARITY-REPORT.md` is tracked on main; verdict PASS (1078/1080 exact, 2 float32-noise cells, all 136 fresh-vs-stored deltas attributed); the writer-path parity cell section is present and records delta 0.000e+00 against the 1e-9 tolerance. `pytest tests/unit/test_summary_cards.py -q` green on main before the drop.
2. **185 D-14 landed: PASS.** Recorded in `185-05-SUMMARY.md` (requirements-completed includes D-14; D-14 ports live as pure APR-parameterized functions in `src/intelligence/bars/scrub_rules.py`), `185-10-SUMMARY.md` (5m pass ran D-14 ports), `185-12-SUMMARY.md` ("D-14 scrub ports" section: 15m/1h applied, zero quarantines). Code agrees: `scrub_rules.py` computes `gap_before_next`/`return_magnitude` and reads `alpha.forward_returns.gap_*` APR keys; the writer's own flag path dies with the writer.
3. **D-01: PASS.** `ps aux` for ic_engine/ic_measure/backfill_feature_factory/regime_writer/rebuild/ops_corpus_pipeline_run: empty (an initial `pgrep -f` hit was the invoking shell's own command line; bracketed pattern confirmed empty). `logs/ic_engine.log` empty (rotated 2026-10-01), `.log.1` ends 2026-09-30T19:21:20Z with `compressed_hypertable_write_session.exited` (run completed, nothing resumable). STATE.md lane table names no live or resumable ic_engine/rebuild run. `pgrep -f ops_corpus_pipeline_run[.]sh`: empty. `pg_stat_activity` non-idle foreign queries on forward_returns/feature_ic_scores: 0 rows (re-checked immediately before both applies).
4. **Dependencies: PASS.** 186-16/20/21/22 summaries all present; `git ls-files scripts/analysis | wc -l` = 0; `ops_ic_shrinkage.py` absent; `REQUIRED_STEPS = ["ic_engine"]` count = 1 pre-change; ensemble_weights/ensemble_alpha/alpha_events/feature_ic_scores_history/construction_spreads all absent (count 0); `feature_ic_scores` = 10,616,092 rows at gate time and unchanged after every run; the four named keeps counted 4.

**Pre-delete sha:** `b8432d52c89b7803f9779083120c5d147ce4f3c4` (main HEAD; `git merge-base --is-ancestor` held).

## D-08 inventory (the four master greps, grouped)

**Grep 1, `\bic_engine\b`** (repo-wide, excludes .git/.venv/logs/__pycache__/.planning): ~1,900 hits pre-change across 300+ files. Grouped: live importers (all disposed, see below); comment/docstring history (ic_math, measure package, cross_sectional_regime_model, tag_calibrator, integrity_monitor, gotchas, parity harness line references: kept); test files (deleted with the service or repointed); tooling (vulture whitelist pruned/reworded); migrations and docs (history, kept; current-fact doc hits fixed in Task 3). Post-change: zero live imports, zero current-fact code statements; remaining hits are comments, fixtures, the verifier's history comments, and whitelist entries.

**Grep 2, `forward_return_writer`**: pre-change live hits in service_auditor (_DAG_ORDER + _ONESHOT_UNITS, removed), metrics.py P5 block (deleted), ops_oos_holdout_eval import (cut), infrastructure_truncate_derived_tables.sh (TRUNCATE + count lines, removed), plus docs/comments (history, kept where dated). Post-change: comments and whitelist entries only.

**Grep 3, importer grep `(from|import) services.(ic_engine|forward_return_writer)`**: 34 pre-change hits in 25 files. Classification: delete-with (19 ic_engine test files, test_forward_return_writer, tests of the deleted ops scripts, test_interaction_primitives_parent_order which imported the deleted pilot's helper, test_regime_scope which tested ic_engine's regime_scope resolver); cut-import (ops_broadcast_feature_audit, ops_dependence_length_diagnostic: `_FEATURE_NAMES` now derived from `dataclasses.fields(FeatureVector)`; ops_oos_holdout_eval: same plus `forward_log_return` now a thin wrapper over `src.intelligence.research.panel.forward_returns`, the kernel); repoint-or-delete test cases (test_hac_ic_sharpe: SimpleNamespace container, lookaheads_for case deleted; test_ic_bootstrap_jit: ic_engine kernel case deleted, ic_math cases kept; test_vol_normalized_target: ic_engine wiring case deleted, ic_math cases kept; test_e_values: pilot-gate class deleted; test_cross_sectional_regime_model: `_build_symbol_regime_class` routing case deleted; test_provenance_identity: ic_engine-copy comparison deleted with the copy; test_compute_universe_readers: ic_engine param entry removed; test_measure_purity: strangler-direction guard deleted with the module). `src/intelligence/statistics/ic_math.py`: comment/docstring mentions only, file untouched (D-02). Post-change grep: **empty**.

**Grep 4, `forward_returns` table readers**: real SQL readers (deleted): ops_ic_null_calibration (2 INNER JOIN), ops_vol_normalized_target_ab (INNER JOIN), ops_interaction_primitives_pilot (INNER JOIN), infrastructure_truncate_derived_tables.sh (TRUNCATE + 2 count queries). Mention-only (kept, reworded where the text was operator-facing): ops_known_corrupt_print_cleanup (its printed `--apply` playbook named a `DELETE FROM forward_returns` step and a forward_return_writer re-run; rewritten to the feature_vectors-only purge plus ic_measure re-run), ops_lookahead_horizon_response (deleted as importer orphan). Research-package check: `grep forward_returns src/intelligence/research/` minus `panel.forward_returns`/`forward_returns(`: empty; no table read from the lane. Schema baseline fixtures (integration, frozen snapshots): kept.

**Parity-harness fix:** none needed. `grep services.ic_engine tests/unit/measure/ tests/integration/` found no import; 186-20 already shipped the inlined legacy-arithmetic replica. `pytest tests/unit/measure/test_parity_harness.py -q` green after the change.

**Known mention-only non-reader honored:** ops_known_corrupt_print_cleanup's line-145 comment ("the prior version of this query drew candidates from forward_returns") is history; stays.

## Per-key APR disposition (grep evidence per key; literal IN deletes only)

| Key(s) | Count | Reader evidence | Decision |
|---|---|---|---|
| `alpha.ic.lookahead.{5m,15m,1h,1d}.{fast,mid,slow,extended}` + 4 base | 20 | Only readers: ic_engine, forward_return_writer, scripts deleted here, corpus_manifest_verifier (mirror made the documented source, bytewise-equal at retirement) | DELETE (430) |
| `alpha.ensemble.cluster_regime_conditioned` | 1 | Only runtime reader `cfg.get_sync` at ic_engine ~840 | DELETE (430) |
| `alpha.ic.insert_batch_size` | 1 | Only reader forward_return_writer | DELETE (430) |
| `infra.ic_engine.*` | 16 | Only reader ic_engine | DELETE (430) |
| `infra.ensemble_ic_engine.{workers,pooled_fetch_itersize}` | 2 | Reader deleted by 186-19; zero surviving readers (grep; only a test fixture mention, updated) | DELETE (430) |
| `alpha.ic.cluster_max_corr` | 1 | Only reader ic_engine; missed by Task 1's prefix enumeration, caught by the docs-pass grep | DELETE (431) |
| `alpha.forward_returns.gap_{max_seconds,multiplier}` | 2 | **Live readers**: `src/intelligence/bars/scrub_rules.py:130-131` (185's bar-flag code), fixture values in tests/unit/bars/_builders.py, snapshot prefix in ops_scrub_historical_pass.py | KEEP |
| `alpha.quant.cross_symbol_corroboration.{min_symbols,window_minutes}` | 2 | Live readers: scrub_rules.py, bar_auditor.py:531, ops_known_corrupt_print_cleanup.py:448 | KEEP |
| `alpha.ensemble.mv_condition_max`, `alpha.ic.shrinkage_k`, `alpha.ic.canary_rng_seed` | 3 | tag_calibrator import check passed post-apply; research lane and feature_factory per plan | KEEP (verified: count 3 post-apply) |
| `alpha.ic.{subsample_min_stride,bootstrap_block_size.*,bootstrap_resamples,bootstrap_seed,fdr_alpha,min_observations,hac_max_lag,feature_block_columns}`, `alpha.validation.oos_start` | 12 | ic_measure reads them (`ic_measure.py` key map, `measure/params.py`) | KEEP (verified: count 12 post-apply) |

Post-apply counts: `alpha.ic.lookahead.%` = 0; orphan groups = 0; keeps intact.

## Migration

**430** (`production/migrations/430_drop_forward_returns_retire_lookahead_keys.sql`): DO $$ guard raising on any non-idle foreign `forward_returns` reader; plain `DROP TABLE forward_returns` (no IF EXISTS, no CASCADE; compression job removed automatically, nothing decompressed, no VACUUM; D-16 proven by the passing `test_compressed_hypertable_migration_vacuum_check.py`); then literal per-key DELETEs from config_history/config_state/config_schema (22 + 17 keys). Applied live with `ON_ERROR_STOP=1`: `BEGIN/DO/DROP TABLE/DELETE 19/22/22/32/17/17/COMMIT`, exit 0, in the same commit as the file (2fea95291 includes it).

**431** (follow-up, same docs commit): retires `alpha.ic.cluster_max_corr` (enumeration miss, zero readers). Applied live, exit 0.

**Post-apply probes (all pass):** `to_regclass('forward_returns')` NULL while `feature_vectors` and `feature_ic_scores` resolve; `feature_ic_scores` row count 10,616,092 before and after (untouched); `timescaledb_information.jobs WHERE hypertable_name='forward_returns'` = 0 (job 1066 gone); `alpha.ic.lookahead.%` = 0; keeps counted; `import services.tag_calibrator` and `import services.ic_measure` exit 0.

## Orchestrator step renumbering map

| Old (186-21 shape) | New |
|---|---|
| 1 feature_factory | 1 feature_factory |
| 2 regime_writer; 2 regime_writer_volatility | 2 regime_writer; 2 regime_writer_volatility |
| (regime consistency gate, skip if FROM_STEP > 5) | (skip if FROM_STEP > 4) |
| 3 forward_return_writer | **deleted** |
| 4 cross_sectional_regime_model | 3 cross_sectional_regime_model |
| 5 ic_engine (--training-window-end $TRAINING_WINDOW_END) | **4 ic_measure** (`services/ic_measure.py`, space-separated `--symbols`; no window hand-off: ic_measure derives its window and enforces `alpha.validation.oos_start` itself, D-19; default --jobs proposer,regime_volatility; default --tf = every tf in `alpha.ic_measure.horizons`) |
| (canary gate, skip if FROM_STEP > 5) | (skip if FROM_STEP > 4) |
| 5 feature_lifecycle | 4 feature_lifecycle |

Banner `Step %d/5` → `Step %d/4`; header sequence and the freeze-point comment updated (TRAINING_WINDOW_END is still computed, displayed, and passed to feature_lifecycle). `ops_pipeline_monitor.sh`: `SERVICE_PATTERN='services[./](backfill_feature_factory|regime_writer|ic_measure)'`, step detection `/5` → `/4`. `ops_corpus_final_verification.py`: `REQUIRED_STEPS = ["ic_measure"]`. `corpus_manifest_verifier.py`: `print_recovery` ic_engine branch renamed to ic_measure with remediation lines pointing at `services/ic_measure.py` and the `indicagent-ic-measure` oneshot; the lookahead mirror's fallback comment rewritten so the mirror is the stated source (keys retired; mirror equaled the APR values bytewise at retirement), and the APR lookup no longer queries the retired keys. `bash -n` passes on both shell scripts; usage smoke (`--bogus-flag`) exits non-zero with usage (exit 1, the script's long-standing value, not the plan's stated 2).

## Metrics, service registry, tooling

- `metrics.py`: deleted the P5 forward_return_writer block (rows_written_total, run_latency_seconds, forward_returns_coverage gauge) **and** the P6 ic_engine block (cells_completed/skipped, run latency, symbols counters, FDR/walk-forward gauges, IC health gauges): no surviving emitter or reader for any of them (grep; ic_measure uses generic helpers only).
- `service_auditor.py`: `indicagent-ic-engine` and `indicagent-forward-return-writer` removed from `_DAG_ORDER` and `_ONESHOT_UNITS`; `indicagent-ic-measure` and its checked-in unit stay. `systemctl list-unit-files | grep -E "ic-engine|forward-return"`: no units existed, nothing to disable. The registry-integrity test's `_MISSING_UNIT_ALLOWLIST` stale entries removed.
- `_batch_utils.py`: `lookahead_by_scale_from_apr` and `lookaheads_for_tf` deleted (caller grep: zero survivors; recorded); `LOOKAHEAD_FALLBACKS_BY_TF` kept (ops_oos_holdout_eval falls back to it) and is now the grid's documented source; `bars_to_scale_map` deleted too (zero surviving callers after the ops deletions; its two test cases removed).
- `vulture_whitelist.py`: 7 entries naming deleted code removed; the three ic_math "186-10/186-23 decide" entries and `ensure_success_for` resolved to final wording; 7 new whitelist entries added with reasons (content_key, canonicalize_active_scales, ACTIVE_SCALES_FALLBACKS_BY_TF, Float32ChunkAccumulator methods, price_sanity window_minutes) for orphans whose only caller died here but whose owner module survives or is frozen. Canonical `vulture` output is byte-identical to the untouched main tree's (84 pre-existing findings, exit 3 on both: pre-existing, out of scope).

## Docs current-fact fixes (Task 3)

glossary.md (`forward_returns` entry retired with kernel pointer; forward-return/IC-discovery/status lines updated; MeasurementEngine discussion updated); canonical-truth-registry.md (pipeline line, forward_returns row repointed at the kernel with a deletion comment, feature_ic_scores writer annotated frozen); services/overview.md (chain and step table now ic_measure/feature_ic_scores_v2); db-maintenance.md (forward_returns rows removed from the three maintenance tables with a migration pointer); apr-calibration-backlog.md (cluster_max_corr row removed with change note; hac_max_lag reader now ic_measure); instrument-tag-registry.md (ic_engine reader annotated deleted, reader count corrected); naming-conventions.md (ICEngine example row replaced with ICMeasure); CLAUDE.md (Invariant 1 rewritten to the kernel in Task 2's commit; pipeline line and lifecycle-chain line name ic_measure; the import-closure and per-row-logging rules reworded to writer-agnostic form; ProcessPoolExecutor/orphan-worker rules untouched). History kept as written: gotchas.md incident records, v3-north-star frozen src-anchor records, operations-promotion-protocol's dated staleness note, methodology-change-ledger, archived plans. `tools/check_glossary.py --all --baseline` exit 0; todo link integrity test green. Timers and crontab name nothing invoking the deleted services (checked: nightly backfill, regime coverage auditor, dividend writer only).

## Deletions are unreferenced (end-state)

`grep -rnE "(from|import) services.(ic_engine|forward_return_writer)" --include=*.py src services scripts tests tools`: empty. `grep "FROM forward_returns|INTO forward_returns|TRUNCATE forward_returns"` over src/services/scripts (excluding tests and migrations): empty. `rebuild_preconditions.py`'s `DROPS_DUE_BEFORE_REBUILD` includes forward_returns, so 186-26's gate now sees this drop as landed. `repro_frozen` not run: nothing under `src/intelligence/research/` or `src/intelligence/statistics/` was edited (verified: `git diff <pre-delete sha> --stat -- src/intelligence/research scripts/research services/ic_measure.py services/feature_lifecycle.py` is empty).

## Verification

- `pytest tests/unit/ -q`: exit 0, 0 failures (7,538 collected after the deletion, 5 pre-existing skips). `pytest tests/integration -q --co`: 0 errors. ruff clean on all touched paths; black clean; pre-commit's 9 checks passed on both commits.
- Post-change probes recorded above; DB size 134 GB → **120 GB** (14 GB freed, matching forward_returns); data mount 557G → 571G free. Phase-186+185 disk target (~61 GB combined): this plan contributes its full 14 GB share.

## Deviations from Plan

1. **[Rule 3 - Blocking] Orchestrator-provided worktree used instead of the plan's `git worktree add /home/bg/dev/indicagent-186-23`.** The executor was spawned inside Claude Code's worktree (`agent-aeee1b524f5221232`, branch `worktree-agent-aeee1b524f5221232`); creating a second worktree would defeat the isolation. The spawn base was one commit behind main (missing 185-16's implementation commit, which made pytest collection red at base); the branch was fast-forwarded to main HEAD `b8432d52c` (sanctioned by the plan's "worktree sits on main's HEAD" done-criterion) before any edit.
2. **[Scope] Task 3's merge/push/worktree-removal steps not executed.** The orchestrator prompt assigns merge, push, and worktree cleanup to the orchestrator after the wave; the executor committed `SUMMARY.md` on the worktree branch instead of merging to main itself.
3. **[Rule 1 - Bug] `alpha.forward_returns.gap_*` classified KEEP, not DELETE.** The plan's orphan list guessed the gap keys might be orphans; the run-time per-key grep (which the plan makes authoritative) found 185's `scrub_rules.py` reading both at runtime. Kept; recorded in the migration header.
4. **[Rule 2] `infra.ensemble_ic_engine.*` retired here** (186-19 deleted the reader but left the keys) and **migration 431 added** for `alpha.ic.cluster_max_corr` (Task 1's prefix-grouped enumeration query missed the key; the docs-pass literal grep found zero readers). Both are grep-justified orphans under D-22's per-key rule.
5. **[Rule 2] The old engine's P6 metrics block deleted** alongside the plan's named P5 block: every emitter and reader died with the service.
6. **[Rule 1] `ops_ic_fingerprint_equivalence.py` deleted** though the plan listed it nowhere: it is a pure ic_engine subprocess dispatcher (imports nothing, so the importer grep missed it); its only purpose died with the engine, same classification as ops_lookahead_horizon_response. No test referenced it.
7. **[Rule 2] `ops_known_corrupt_print_cleanup.py`'s printed recovery playbook rewritten**: the plan kept this script as mention-only, but its `--apply` output instructs operators to `DELETE FROM forward_returns` and re-run `forward_return_writer` (T-186-23-06, operator reaches for a deleted path); now purges feature_vectors only and re-runs ic_measure. Its tests updated to match.
8. Usage smoke exits 1, not the plan's stated 2 (the script's pre-existing behavior; acceptance is non-zero).

## Auth gates

None.

## Known Stubs

None. Every survivor's data path is wired (ops_oos_holdout_eval computes targets with the kernel; feature lists derive from the FeatureVector schema).

## Hand-off

186-26 (rebuild) now sees every `DROPS_DUE_BEFORE_REBUILD` relation dropped. 186-27/186-28 own the `feature_vectors` rebuild and the `feature_ic_scores` drop; the fresh IC run reads rebuilt features through ic_measure with kernel targets. The APR grid for horizons lives at `alpha.ic_measure.horizons` (414); the per-tf bar-count grid that used to be `alpha.ic.lookahead.*` is documented in `LOOKAHEAD_FALLBACKS_BY_TF` and the verifier's by-value mirror.

## Self-Check: PASSED

- Commit 2fea95291 on branch `worktree-agent-aeee1b524f5221232` contains the migration file (`git log -1 --name-only` verified at commit time), applied-before-committed (psql exit 0 recorded above, applied at 06:4x before the 06:55 commit).
- All deleted paths absent (`test ! -e` on services/ic_engine.py, services/forward_return_writer.py, every deleted script and test).
- Docs commit (this one) contains glossary/registry/overview/db-maintenance/backlog/ITR/naming fixes and migration 431.
- SUMMARY.md committed before any narration, per the parallel-executor order.
