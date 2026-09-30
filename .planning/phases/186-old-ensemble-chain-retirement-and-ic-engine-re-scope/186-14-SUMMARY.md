---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 14
subsystem: measure
tags: [ic, bulk_load, provenance, feature_ic_scores_v2, revision-detection, timescaledb]
requires: [186-06, 186-10, 186-11]
provides:
  - feature_ic_scores_v2 (migration 413): regime_scope in the PK from creation, frozen legacy table untouched
  - services/ic_measure.py: the fresh IC engine's one writer (proposer with term structure, regime_volatility disclosure, monitoring)
  - kernel_code_key, bar_content_digests and bulk_load(replace_where=) in services/_batch_utils.py
affects: [186-20, 186-23, 186-28]
tech-stack:
  added: []
  patterns: [unit identity = per-job code key + APR snapshot + bar digests + block digest, atomic replace with supersede flip, lazy compressed write session]
key-files:
  created:
    - production/migrations/413_feature_ic_scores_v2.sql
    - production/migrations/414_ic_measure_apr.sql
    - production/migrations/415_ic_measure_fetch_chunk_apr.sql
    - production/systemd/indicagent-ic-measure.service
    - services/ic_measure.py
    - tests/unit/test_ic_measure.py
    - tests/unit/test_provenance_identity.py
    - tests/integration/test_ic_measure.py
    - .planning/todos/pending/469-ic-measure-bootstrap-cost-needs-threads-before-the-fresh-ic-run.md
  modified:
    - services/_batch_utils.py
    - services/service_auditor.py
    - docs/foundation/glossary.md
    - tests/unit/test_bulk_load.py
    - tests/integration/test_bulk_load.py
    - .planning/todos/PRIORITIES.md
    - .planning/todos/completed/412-ic-engine-upstream-watermark-not-clamped-to-training-window-end.md
metrics:
  tasks: 3
  completed: 2026-09-30
---

# Phase 186 Plan 14: the fresh IC writer Summary

`services/ic_measure.py` runs the pure 186-10 jobs and writes the new hypertable `feature_ic_scores_v2` only through `bulk_load()`, one provenance batch per unit (job, tf, feature block). Reruns with an unchanged identity skip before computing; a revised bar replaces a unit atomically. Todo 412 is closed. The legacy `feature_ic_scores` table, `services/ic_engine.py` and `src/intelligence/research/` are untouched.

## Commits (branch phase-186-14, merged to main by fast-forward, not pushed)

| Commit | What |
|---|---|
| 5791722ea | migration 413, feature_ic_scores_v2 |
| c50288b5d | migration 414, APR keys |
| e48c7ced5 | service registration, unit file, glossary |
| e299c3ae5 | kernel_code_key, bar_content_digests, bulk_load replace_where |
| d8f5a8e31 | migration 415, fetch chunk APR key |
| 91a90d5c3 | the writer, unit and integration tests |
| 81f2d5902 | per-unit progress log, dry-run digest tolerance, todo 412 closed |
| 0db1aa213 | todo 469 filed |

## Gates (run for real)

D-01 gate (2026-09-30 about 12:12 UTC):

- `ps aux | grep -E "ic_engine|backfill_feature_factory|regime_writer|rebuild|ic_measure" | grep -v grep`: no output. The todo 449 backfill processes do not match and were not touched.
- `ls -t logs/ic_engine*.log`: only `logs/ic_engine.log`, 0 bytes, mtime 2026-09-27 00:24. No corpus run started and not completed in 7 days. STATE.md lists none.
- `pg_stat_activity` filtered on `feature_ic_scores`: no rows.
- 185-11 gate: `to_regclass('bar_content_digest_current')` = `bar_content_digest_current`, `to_regclass('bar_content_digest')` = `bar_content_digest`. `select count(*) from bar_content_digest` = 0 (see "Digest table is empty" below).

## Readers of the legacy table (for 186-28's drop gate, none edited here)

`scripts/debug/analysis/debug_analyze_feature_ic.py`, `scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh`, `scripts/ops/alpha/` (`ops_canary_integrity_assert`, `ops_dependence_length_diagnostic`, `ops_emission_threshold_sweep`, `ops_ensemble_ic_diagnosis`, `ops_ensemble_weight_compare`, `ops_ic_null_calibration`, `ops_ic_shrinkage`, `ops_interaction_primitives_pilot`, `ops_lookahead_horizon_response`, `ops_vol_normalized_target_ab`), `scripts/ops/corpus/` (`ops_corpus_pipeline_run.sh`, `ops_corpus_progress`, `ops_cost_hurdle_calibration`, `ops_ic_fingerprint_equivalence`, `ops_known_corrupt_print_cleanup`, `ops_oos_holdout_eval`), `scripts/research/cost_hurdle.py`, `services/cross_sectional_regime_model.py`, `services/ensemble_trainer.py`, `services/ic_engine.py`, `src/intelligence/ensemble/feature_selector.py`, `src/intelligence/regime_signals/{breadth_vol,commodity_momentum_ts,curve_credit,fx_dollar_carry}.py`, `src/observability/{corpus_manifest,corpus_manifest_verifier,metrics}.py`, `src/intelligence/statistics/ic_math.py` (comments and names), `services/service_auditor.py`, `tests/unit/` (conftest, ic_engine, ensemble_trainer, feature_lifecycle, summary_cards, batch_utils, bulk_load, scripts and observability tests).

## Migrations and live effects

- 413 `feature_ic_scores_v2`: PK `(feature_name, symbol, tf, regime_scope, regime, lookahead_bars, training_window_end)`; CHECK `feature_ic_scores_v2_regime_scope_chk` allows only `unstratified`, `regime_volatility`, `member_window`; CHECK `feature_ic_scores_v2_fresh_scope_pooled_chk` (`is_pooled AND symbol = 'POOLED'`); shrinkage-weight unit-interval CHECK; hypertable on `training_window_end`, 30-day chunks; compression enabled with segmentby `symbol,tf`, orderby `training_window_end DESC`; no scheduled compression policy (`timescaledb_information.jobs` empty for the table); COMMENTs on the table, `training_window_end` and `regime_scope`. Live: 0 rows.
- Legacy untouched: `count(*), sum(hashtext(feature_name||symbol||tf||regime||lookahead_bars||coalesce(ic_value::text,''))::numeric)` = `10616092 | 822111492759` before migration 413, after it, and after the dry runs.
- 414 APR seeds (5 keys, each with a provenance tag and "Not an ML learning target", `config_history` rows `changed_by = 'migration_414'`): `alpha.ic_measure.degenerate_std` 1e-8, `alpha.ic_measure.monitor_degenerate_std` 1e-10, `alpha.ic_measure.horizons` (`{"5m":[6,12,39],"15m":[2,5,10],"1h":[1,2],"1d":[1,2,5,10]}`), `alpha.ic_measure.monitor_window_sessions` 63, `infra.ic_measure.symbol_chunk_size` 50.
- 415 APR seed (1 key): `infra.ic_measure.fetch_chunk_rows` 200000. Not in the plan: the writer's server-side cursor chunk size is an infrastructure constant, so the APR mandate requires a key (see deviations).
- Each migration number was re-checked against the highest file in `production/migrations` (412) immediately before it, applied live with `ON_ERROR_STOP=1`, and committed in the same breath.

## MeasureParams to APR map (source of truth: `MEASURE_PARAM_KEYS` in `services/ic_measure.py`)

All existing keys were verified against live `config_state` on 2026-09-30.

| Field | APR key |
|---|---|
| min_stride | alpha.ic.subsample_min_stride (5) |
| bootstrap_block_size | alpha.ic.bootstrap_block_size.{tf} |
| bootstrap_resamples | alpha.ic.bootstrap_resamples (2000) |
| rng_seed | alpha.ic.bootstrap_seed (42) |
| fdr_alpha | alpha.ic.fdr_alpha (0.05) |
| min_obs | alpha.ic.min_reliable_n (100) |
| symbol_chunk_size | infra.ic_measure.symbol_chunk_size (new) |
| monitor_window_sessions | alpha.ic_measure.monitor_window_sessions (new) |
| hac_max_lag | alpha.ic.hac_max_lag (3) |
| degenerate_std | alpha.ic_measure.degenerate_std (new) |
| monitor_degenerate_std | alpha.ic_measure.monitor_degenerate_std (new) |

Other existing `alpha.ic.*` keys the writer reads, so 186-21 and 186-23 must keep them: `alpha.ic.feature_block_columns` and `alpha.ic.broadcast_max_bars_per_day.{5m,15m,1h}` (the session length used to check a horizon before any fetch). `alpha.validation.oos_start` is required with no fallback. `alpha.ic.lookahead.*` is never read (a test enforces it).

## Registration decision

`_DAG_ORDER` (`indicagent-ic-measure: 8`) and `_ONESHOT_UNITS` only, plus a checked-in unit file (not installed, no timer). No `_AGENT_ID_TO_UNIT` entry and no `alert.lag.*` key: `PERSISTENCE_CONSUMER_LAG` (the `agent_id`-labelled metric those keys serve) is set only by `BaseWriter` (`src/core/agent/base_writer.py`) and `services/feature_vector_writer.py`; a batch oneshot never emits it, and ic-engine and feature-lifecycle have neither entry. `src/core/agent/base_batch.py` has no `agent_id` lag metric.

## kernel_code_key module lists per job

Common: `services.ic_measure`, `src.intelligence.measure.{params,targets,ic}`, `src.intelligence.research.{panel,snapshot}`, `src.intelligence.statistics.ic_math`. Plus `measure.proposer` and `measure.term_structure` (proposer), `measure.regime_disclosure` (regime_volatility), `measure.monitoring` (monitoring). Keys are AST-normalized, so a comment or docstring edit does not move them.

## Design decisions made here

- Scopes `unstratified` (regime `_all`), `regime_volatility` (regime = label), `member_window` (regime `_all`, one row per window). `training_window_end` is the latest target exit bar of the stack (`max_target_end()`), or of the window for `member_window`.
- Term structure rows come from `term_structure` (IC, n, p per feature and horizon). The CI, BH-adjusted p and FDR columns come from `propose` at the tf's first configured horizon (the proposer horizon) and are NULL at the other horizons, so the bootstrap cost is not doubled. Disclosure runs at every configured horizon. Monitoring runs at the first horizon.
- Writer names carry the block index: `ic_measure.<job>.b<NNN>`. `bulk_load`'s supersede flip matches on writer, target, tf, range and symbols, so units of one tf that share a range need distinct writers or they would supersede each other. A change of `alpha.ic.feature_block_columns` reshuffles blocks; that changes the APR snapshot, so every key is new and the `replace_where` DELETE (by tf, scope, feature list) replaces the old rows, but an old block's provenance row stays `completed` for a writer index whose features moved. Not reachable in practice without changing that key; noted rather than engineered around.
- A unit with no finite target at a horizon raises (a silent empty unit would hide a data problem). A failed unit is logged, counted, the run continues, and the exit status is failure.
- NaN IC, p, CI are written as NULL with `reliable` false; no COPY value is NaN.
- The write session is opened lazily on the first actual write, so a rerun that skips every unit never decompresses or VACUUMs anything.

## Deviations from the plan

1. **[Rule 3] `compress_before` is not passed to `bulk_load`.** Units of different jobs and feature blocks share the same 30-day chunks; compressing a chunk after one unit makes the next unit refuse (`BulkLoadRefused`, compressed chunk in range). The compressed write session recompresses every chunk and VACUUMs on exit, which gives the "compressed after the run" state (integration case 6 proves it). Intent preserved.
2. **[Rule 3] `feature_ic_scores_v2` added to `_WRITE_SESSION_HARDENED_TABLES`** in `services/_batch_utils.py`. The session validates against that hand-curated allow-list and would raise for v2 otherwise; the plan calls the session on v2 but did not mention the allow-list. Commit 91a90d5c3.
3. **[Rule 2] Migration 415** for `infra.ic_measure.fetch_chunk_rows` (APR mandate, infrastructure constants).
4. **[Rule 2] Absent digests refuse a real run.** `bar_content_digests` returns `"absent"` for a symbol with no digest rows (per the plan); the writer raises for a real run if any symbol is absent (revision detection would be blind, and the before and after bracket would compare two identical sentinels). `--allow-absent-digests` accepts it explicitly; a dry run tolerates it and logs a warning per tf. Not in the plan.
5. **A superseded batch key is terminal and cannot be loaded again** (`BulkLoadRefused`, loud). The provenance guard forbids superseded to started, so a revert of inputs to an old identity would otherwise fail with an opaque trigger error.
6. **Live dry run narrowed.** The plan asks for `--tf 1d` on the live universe and `--tf 15m` on 40 symbols. Both were started and neither finished its first unit: 1d on 931 names ran 73 min and 15m on 40 names ran 37 min before I killed them (see measurements). The recorded dry runs are smaller (next section). Cause and follow-up: todo 469.
7. The `slot_horizon=1` argument of `make_tf_context` exists only to give `map_slots` a `TargetStack` (it reads timestamps and symbols, never targets).
8. TDD ordering: RED runs recorded per task (below). `test_load_params_maps_every_measure_param_field_to_its_apr_key` and the other unit tests were written in one file before the module existed and all went green together on the first implementation run.

## RED lines

- `tests/unit/test_provenance_identity.py`: `ImportError: cannot import name 'bar_content_digests' from 'services._batch_utils'` at collection.
- `tests/unit/test_bulk_load.py::TestBulkLoadReplaceWhere`: 7 failures before `replace_where` and `rows_replaced` existed.
- `tests/unit/test_ic_measure.py` (includes the load_params mapping, NaN-to-NULL and slot-present-mask proofs): `ModuleNotFoundError: No module named 'services.ic_measure'` at collection; all 30 passed after the writer landed.

## Live dry-run measurements (no writes)

Unbounded runs (killed by PID, single process, no workers to orphan):

| Run | Wall clock | Peak RSS | Result |
|---|---|---|---|
| `--tf 1d --jobs proposer,regime_volatility --dry-run` (931 names) | 1:13:01 | 3.7 GB | first unit not finished |
| `--tf 15m --dry-run --symbols <first 40 compute_eligible>` | 37:29 | 6.3 GB | first unit not finished |

Bounded runs, complete, first 8 compute_eligible symbols (`AA AAPL ADM AEP AGG AMD AMLP AMT`):

| Run | Wall clock | Peak RSS | Units | Rows |
|---|---|---|---|---|
| `--tf 1d --jobs proposer --dry-run` | 10:55 | 392 MB | 10 x `would_load` | 1,200 |
| `--tf 15m --jobs proposer,regime_volatility --start 2025-09-01 --dry-run` | 4:21 | 335 MB | 20 x `would_load` | 3,600 |

All 300 FeatureVector fields are numeric columns of live `feature_vectors`, so 10 blocks of 32 (the last of 12). A proposer unit is 32 x 3 horizons = 96 rows on 15m; a disclosure unit is 288 rows (3 labels).

Why the unbounded runs do not finish: the block bootstrap (`_circular_block_bootstrap_ic`, `max_workers=1`) re-ranks 2000 resamples per cell. Measured on an idle core, one cell of 32 features: 22 s at 5,000 strided rows, 102 s at 20,000 (about 5 ms per strided row). A full 1d cell has about 500,000 strided rows, about 42 min, and a unit is five cells, so the 1d proposer is on the order of 35 hours serial. Filed as todo 469 (P2), to be decided before 186-28.

Live counts after every dry run: `feature_ic_scores` 10,616,092 rows, checksum 822111492759 (unchanged); `feature_ic_scores_v2` 0 rows; `provenance_batch` rows with `writer like 'ic_measure.%'` 0 (unchanged).

## Digest table is empty (for the coordinator)

`bar_content_digest` has 0 rows (185 plan 12 runs the grid rewrite; 1d digests arrive with 185-17/18). Every symbol therefore reads `"absent"` and a real `ic_measure` run refuses until digests exist or `--allow-absent-digests` is passed. The dry runs above used the dry-run tolerance and logged `ic_measure.bar_digests_absent` (931 symbols on 1d, 40 on 15m). 186-28 must run after 185 has written 1d digests for the universe.

## Tests

- `pytest tests/unit/test_provenance_identity.py tests/unit/test_bulk_load.py tests/unit/test_batch_utils.py tests/unit/test_market_data_ohlcv_boundary.py tests/unit/test_provenance_batch_sole_writer.py -q`: exit 0.
- `pytest tests/unit/test_ic_measure.py -q`: 30 passed.
- `pytest tests/integration/test_bulk_load.py -q` (indicagent_test): 10 passed (7 existing, a replace case and a superseded-identity case, a digest composition case).
- `pytest tests/integration/test_ic_measure.py -q` (indicagent_test): 6 passed, the six plan cases (write with both fresh scopes and the predictive feature's IC above 0.3; rerun skips every unit; a revised bar plus its new month digest replaces every unit and supersedes the previous keys; legacy table unchanged; monitoring writes one row per window; every chunk compressed after the runs).
- Full suite on merged main: `.venv/bin/pytest tests/unit/ -q --ignore=tests/unit/scripts/test_venue_study_script.py; echo exit=$?` printed `exit=0`.
- ruff: clean on every touched Python file. black: clean. mypy on `services/ic_measure.py` and `services/_batch_utils.py`: no new errors (the remaining ones are pre-existing: missing pandas stubs, memmap and threadpoolctl lines in `_batch_utils.py`). vulture: 59 findings repo-wide, none in `services/ic_measure.py` or `services/_batch_utils.py`.
- `git diff 5824c2b0c..HEAD --stat -- services/ic_engine.py src/intelligence/research src/intelligence/statistics`: empty, so `repro_frozen` was not required.
- /simplify and /review cannot be invoked from an executor. I did a careful manual read of `services/ic_measure.py` and the `bulk_load` changes instead; the coordinator runs the real gates.

## Adjacent findings

- Todo 469 filed (bootstrap cost), with a PRIORITIES row.
- `numpy` emits `RuntimeWarning: Degrees of freedom <= 0` from `prepare_features`' `nanstd` on all-NaN columns (186-10 suppresses only `invalid`). Harmless; not fixed (out of scope, measure package).
- `grep -rn feature_ic_scores` shows the legacy table still read by ~35 files (list above); 186-28 dispositions them.

## Known stubs

None.

## Threat flags

None beyond the plan's register. T-186-14-01 (legacy untouched, checksum equal) and T-186-14-04 (D-19 refusal before bulk_load, integration-asserted) verified.

## Self-Check

PASSED. All 10 created files verified present, all 8 commits verified on main, todo 412 absent from pending/ and present in completed/.
