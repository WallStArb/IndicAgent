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

Pass 1 review fixes (determinism and identity) landed 2026-09-30 and supersede the unit, identity and code-key descriptions below; see the last section, "Pass 1 review fixes".

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

## kernel_code_key entries per job

Superseded by Pass 1 (P2): a hand-kept module list is gone. Entries: `src.intelligence.measure.{params,targets,ic}` plus `measure.proposer` and `measure.term_structure` (proposer), `measure.regime_disclosure` (regime_volatility), `measure.monitoring` (monitoring); `services.ic_measure` is hashed as its own file. `kernel_code_key` walks the first-party import closure of the entries with `ast` (22 to 23 modules per job, including `research.store`, `research.dividends` and `core.market_calendar`, which the old list missed). Keys are AST-normalized, so a comment or docstring edit does not move them.

## Design decisions made here

- Scopes `unstratified` (regime `_all`), `regime_volatility` (regime = label), `member_window` (regime `_all`, one row per window). `training_window_end` is the latest target exit bar of the stack (`max_target_end()`), or of the window for `member_window`.
- Term structure rows come from `term_structure` (IC, n, p per feature and horizon). The CI, BH-adjusted p and FDR columns come from `propose` at the tf's first configured horizon (the proposer horizon) and are NULL at the other horizons, so the bootstrap cost is not doubled. Disclosure runs at every configured horizon. Monitoring runs at the first horizon.
- Superseded by Pass 1: units are (job, tf), writer `ic_measure.<job>`, and own their whole scope (`replace_where` = tf, POOLED, regime_scope); there is no block index. The earlier per-block writer names and the block size in the identity are gone.
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

## Pass 1 review fixes (determinism and identity, 2026-09-30)

Commits on main (not pushed): b730cc7ae (P2 code key closure), 15a9372ef (P4 operational vs computational), 885e5c9b1 (P3b unit key, migration 416), 1a6ae6608 and da290877e (P1 family FDR and P3a panel digest).

FDR family and ic_engine. ic_engine corrects one family per training window: `_backfill_bh_fdr` (services/ic_engine.py 5570-5620) selects every row with `passes_fdr IS NULL` for that `training_window_end` and runs one `apply_bh_fdr` over all of them (all features, symbols, tfs, regimes and horizons), after `_mark_cluster_representatives` (3196-3240) keeps one representative per (regime, lookahead, cluster) and marks the rest `passes_fdr = False`. The fresh writer has no clusters and runs one tf per unit, so its family is every feature of the tf at the proposer horizon (the first configured horizon), corrected once after all blocks (`measure.proposer.family_fdr`). That is narrower than ic_engine's corpus-wide family on purpose: a corpus-wide family would make a `--tf` subset run change `bh_adjusted_p`, which is the same operational dependence this fix removes. The decision to widen it across tfs belongs to the owner and would need all tfs in one run.

Block dependence that was found beyond BH. `prepare_features` masked a row by the finiteness of the live features of the block only, so `n_independent`, IC, p and CI also moved with the block size (live check, 11 features, block 4 vs 11: n_independent 114 vs 97). ic_engine masks over all of a cell's features before its `feature_block_columns` chunks (`valid_mask`, 2152-2190 region). Fixed with `measure.ic.FamilyCompleteness` (AND of every block's live-feature finiteness, per row set: all rows for the proposer, one per regime label for the disclosure), passed as `complete=`. Blocks keep at least two columns (a trailing single column joins the previous block), as `ic._column_blocks` does, so the multi-column sums stay bit-identical.

Computational vs operational, as ic_engine splits its config (`_COMPUTATIONAL_CONFIG_FIELDS` and `_OPERATIONAL_CONFIG_FIELDS`, services/ic_engine.py 997-1070, where `feature_block_columns`, `symbol_fetch_chunk_rows` and `max_cell_rows` are operational). Every `MeasureParams` field carries a kind; `symbol_chunk_size` is operational, the rest computational; an unclassified field raises on construction. Operational keys (`alpha.ic.feature_block_columns`, `infra.ic_measure.symbol_chunk_size`, `infra.ic_measure.fetch_chunk_rows`, `alpha.ic.broadcast_max_bars_per_day.{tf}`, a guard that can only refuse) are read and logged, never in the identity or the snapshot. The snapshot holds the computational keys, `alpha.validation.oos_start` and this tf's own horizons (not the whole `alpha.ic_measure.horizons` mapping). Param typing comes from the dataclass annotations.

Code key. `kernel_code_key(entries, own=...)` in services/_batch_utils.py walks the import closure (`src/core/code_identity.py`, stdlib only: AST-normalized source, docstrings blanked, imports inside functions followed, `src` and `services` only, a package `__init__` hashed but not followed). The normalizer moved to `src/core/code_identity.py`; ic_engine keeps its verbatim copy (`_normalized_source_for_hash`, 5329) until 186-23 deletes it, because editing ic_engine would move its own `code_content_key` (`_checkpoint_content_key`, 5360-5420, hashes every first-party module in `sys.modules`). A unit test asserts the two copies agree.

Unit identity (input digest, all hashed into the batch key with the code key and the computational APR snapshot): per-symbol bar content digests; the S0 panel content digest (`panels_digest`: union grid, traded mask and per-symbol open, close, volume, independent of `symbol_chunk_size`; it sees the tradeable filter and the calendar's session assembly that the month-granular bar digest cannot); a per-column digest of every feature of the family and the `present` mask (block-size invariant); `family_digest` (sorted names and computational params); the regime label digest or the member set. Dividends are deliberately not hashed: the targets are price-only executable open-to-open returns and `build_target_panels` never requests the dividend grid (a test asserts it), so a dividend revision cannot change an IC. A real run still refuses while any symbol has no `bar_content_digest` row (0 rows live as of this pass; phase 185 writes them), so 186-28 runs after 185 has written them.

Unit key (migration 416). `provenance_batch.unit_key` = sha256 of (writer, target, tf, replace_where), computed once by `BulkLoadSpec` (which now carries `replace_where`; `bulk_load` no longer takes it). The replace DELETE and the supersede flip both come from it, so a run over another symbol set, range, code, APR or input replaces the prior unit instead of loading beside it (before, the flip matched on symbols and range and the new rows hit a primary-key conflict). Replaces the docstring rule "give each unit its own writer name": units that must coexist in one target now differ in writer, tf or replace_where, stated in `BulkLoadSpec.unit_key`'s docstring. `prior_completed_unit` lives next to `completed_provenance_batch`. Migration 416 was applied live (provenance_batch empty: 0 rows; the migration refuses a non-empty table) and adds the column NOT NULL with a hex CHECK, an index on (unit_key, status), and the guard trigger's immutability of unit_key.

Units. (job, tf): `proposer` and `regime_volatility` per tf, `monitoring` per tf when members are given. Adding or removing a feature changes the family digest and replaces every unit of that tf, which is correct because the BH family and the completeness mask changed. The monitoring unit owns the tf's `member_window` scope, so a run with another member set replaces the earlier one.

Tests. `tests/unit/test_ic_measure.py` (identical rows for block sizes 2, 4, 5, 7 against 32 for all three jobs, with NaNs, ties, a constant and an all-missing column; code key closure against an independent bytecode walk), `tests/unit/measure/` (blocked cells with family completeness and one FDR equal the whole family), `tests/unit/test_bulk_load.py` (unit key), `tests/integration/test_ic_measure.py` cases 7 to 10 (another symbol set replaces, a moved window end replaces, operational knobs skip every unit with rows unchanged, a computational key replaces and moves the rows) and `tests/integration/test_bulk_load.py` (symbol-set replacement on a real hypertable).

RED lines (on the code before the fixes):
- unit key: `ic_measure.proposer.b000: duplicate key value violates unique constraint "1_1_feature_ic_scores_v2_pkey"` on a rerun with one symbol fewer.
- block dependence: old per-block API, block 4 vs block 11, `features whose stored n_independent/bh_adjusted_p/passes_fdr differ: 11 of 11`, f0: `(114, 0.9806540141687417, False)` vs `(97, 0.6582721738247401, False)`.
- code key and operational split: `AttributeError: module 'services.ic_measure' has no attribute 'job_code_modules'`, `... 'identity_snapshot'`, `ImportError: cannot import name 'COMPUTATIONAL'`.

Not fixed here (todo 470): the resume grain is now (job, tf), so a kill during a unit's compute loses that unit's cells; every run pays one fetch-and-digest pass over the family before the skip decision; a `--start` later than a prior real run leaves that run's earlier monitoring windows outside the new DELETE range. The bootstrap speed work (todo 469) and the simplification refactors are Pass 2.

## Pass 2 review fixes (bootstrap speed and writer simplification, 2026-09-30)

Commits on main (not pushed): f4382053e (S1 and S2 together: the two edit the same functions and were not separable without rewriting history), 135857e58 (S4d), 2a21512be (S4a), 1a0b62182 (S4b), e1dfcb1a9 (S4c), 8ba062815 (S3), d8860c346 (S5), 6f818fdbe and 04afe6a67 (two adjacent fixes below). No ic_engine, ic_measure or rebuild process was live at the start (checked with ps).

S1 kernel (applied). `measure.ic.block_bootstrap_ci` dense-ranks once per cell, draws `rng.integers(0, n_valid, size=(slice, K))` from a fresh `default_rng(seed)` in slices, and runs `ic_bootstrap_jit.blocked_bootstrap_ics`. Two operational MeasureParams fields, both outside the identity and snapshot: `infra.ic_measure.bootstrap_threads` (12) and `infra.ic_measure.bootstrap_chunk_resamples` (250), seeded by migration 417 (applied live, guarded with ON CONFLICT DO NOTHING, provenance tag and not-an-ML-target in the description; 416 was the highest before it). Timings on a synthetic 50,000 x 32 cell, 2000 resamples, BLAS at 1 thread: scipy 277 s, kernel 5.9 s (1 thread), 3.1 s (2), 1.8 s (6), 1.0 s (12). Real `--tf 1d --symbols SPY --jobs proposer --dry-run`: 21.7 s before, 4.8 s after. Equality: 14 captured cases (five raw cells with ties, a constant column and n up to 60,000, and the proposer, disclosure and monitoring rows of three synthetic tfs with NaNs) are exactly equal to the scipy-path rows captured before editing, and a unit test compares the kernel CI with `_circular_block_bootstrap_ic` on the same starts. The bound the brief gave (2^53, n below 4.7e5) is too high: squares and products of centered ranks are multiples of 0.25, so the sums are exact below 2^53 / 4 (n below about 3.0e5). Measured against scipy on identical resamples: n = 300,000 identical, n = 450,000 to 2,000,000 all differ, up to 2e-14 absolute. `feature_ic_scores_v2` stores these columns as double precision (live schema checked), so the differences are stored, not rounded away; nothing stored has to match (the table is empty). The kernel's own result is thread-count and slice-size invariant (tests). The kernel docstring in `ic_bootstrap_jit.py` carried the wrong bound and is corrected (docstring only; repro_frozen bit-identical before and after). RED lines: `AttributeError: module 'src.intelligence.measure.ic' has no attribute 'blocked_bootstrap_ics'`.

S2 discarded bootstraps (applied). `pooled_rank_ic(_prepared)` takes `bootstrap: bool`; `term_structure` bootstraps only horizon 0, whose cell is now `TermStructure.proposer_cell` (so the proposer no longer recomputes it and `propose_cell` leaves the writer), monitoring passes False. Columns checked by grep: `proposer_rows` reads CI only from `term.proposer_cell`, `member_rows` has no CI column, the other term-structure columns are ic, n_obs, p_value. Stored rows equal the captured BEFORE rows exactly (same 14 cases) and the new tests compare the proposer rows with rows built from cells bootstrapped at every horizon and the monitoring rows with bootstrap forced on. RED lines: `TypeError: pooled_rank_ic() got an unexpected keyword argument 'bootstrap'`; `assert [40, 40, 40] == [40]`; `assert ([20, 20, 10, 20, 20, 10, ...] == []`.

S3 simplification (applied; b was already gone). (a) `TfRun` frozen dataclass, `_family_units`, `_monitoring_unit`, `_identity`, `_spec`, `_run_unit`, `_labels` taking `TfRun`, `Counter` for the counts. (b) The `(kind, names, jobs)` tuples and the duplicate names no longer exist in the code (pass 1 removed them); only a local `family_jobs` list remains. (c) `make_tf_context` builds an immutable `TfContext` from the grid; `map_slots` and `scatter_features` read only timestamps and symbols and take a `StackGrid`; `slot_horizon` is gone. (d) `--allow-absent-digests` kept; the dry-run tolerance is one attribute (`IcMeasure.allow_absent_digests`) and the sentinel is `BAR_DIGEST_ABSENT_SYMBOL` exported from `_batch_utils`. (e) done under S4a. (f) `_LABEL_SOURCE` derives from `_LABEL_COLUMN`, `_to_utc` precedes its first use, one `_cell_row` builds every job's row. Rows exactly equal before and after. RED lines: `ImportError: cannot import name 'BAR_DIGEST_ABSENT_SYMBOL'`, `AttributeError: 'IcMeasure' object has no attribute 'allow_absent_digests'`, `Failed: DID NOT RAISE <class 'dataclasses.FrozenInstanceError'>`, `AttributeError: module 'services.ic_measure' has no attribute 'TfRun'`.

S4 reuse (applied). (a) `table_column_types` next to the bulk_load columns SQL is the one sync catalog read; `feature_names` and bulk_load use it, `validate_feature_table` and `_TABLE_EXISTS_SQL` are gone (a table with no columns raises; `run()` still checks before any work). RED: `AttributeError: module 'services._batch_utils' has no attribute 'table_column_types'`. The asyncpg `fetch_table_columns` stays: different driver, hardcoded public schema. (b) `canonical_json` moved to `src/core/canonical_json.py` (spec.py imports it, so spec hashes cannot move; `repro_frozen` printed bit-identical for phase 179 S3, 181 S2 and 181 S3 before and after); `_canonical` and BulkLoadSpec's two inline dumps use it. `provenance_batch` has 0 rows live, so no stored key exists to move; for JSON inputs with ASCII keys the texts are identical and a test pins the BulkLoadSpec keys against the old expressions. What changes is refusal: a NaN or a non-JSON value in an apr_snapshot now raises instead of hashing `str(value)`. (c) `_parse_oos` uses `parse_iso_ts` (handles Z, naive as UTC, offsets) and raises on its None, then converts to UTC. (d) `tests/unit/_responder_fakes.py` (FakeConn with `rows_responder` and `scripted`) replaces three fakes; `TEST_DB_URL` and `connect` live in `tests/integration/conftest.py`.

S5 (applied in part, no worker processes). The lambdas are replaced by the frozen `UnitCompute` dataclass. Measured runs are in todo 469 (closed): the real 8-symbol 1d proposer dry run went from 1:43.8 at the start of pass 2 to 0:10.1 (the executor's 10:55 was measured on the pre-pass-1 per-block units), and the full 925-symbol 1d run, both default jobs, takes 7:12 at 4.0 GB peak. A full 1d universe in minutes serially means processes buy nothing at 1d, so none are built. The class states that it is not picklable (its fetch is bound to the parent's connection); I did not claim worker readiness it does not have.

S6 (skipped). Nothing reads `symbol`, `is_pooled` or `vector_domain` of `feature_ic_scores_v2` today (only ic_measure writes it), but 186-28 repoints the legacy readers at v2 by table name and cites the PK and `feature_ic_scores_v2_fresh_scope_pooled_chk` as they are; 16 files under src, services and scripts mention `is_pooled` (`grep -rl is_pooled`: feature_selector, ensemble_trainer, ic_engine, ensemble_ic_engine, ops_canary_integrity_assert and others). Dropping the columns would turn each repoint into a predicate rewrite for no gain, since the table is empty and the extra constant columns cost nothing measurable. The compression segmentby `symbol,tf` is effectively `tf`; left as is for the same reason.

Adjacent, fixed: numpy's `Degrees of freedom <= 0` warning from an all-missing column (04afe6a67, test-first, RED `RuntimeWarning: Degrees of freedom <= 0 for slice.`); the kernel docstring bound (6f818fdbe).

Adjacent, filed: todo 471 (intraday full-universe memory and time: 15m on 40 symbols is 17:04 and 6.9 GB; the full universe extrapolates past the host's memory at block width 32). Todo 469 closed; todo 470 updated with the measured digest-pass cost.

Final checks: `pytest tests/unit/ -q --ignore=tests/unit/scripts/test_venue_study_script.py` printed `exit=0`; `tests/integration/test_ic_measure.py` (10) and `tests/integration/test_bulk_load.py` (11) pass; vulture lists the same 59 findings before and after (identical set); golden fixtures untouched.

## Final review fixes (F1 to F9, 2026-09-30)

Commits on main (not pushed): f61f1e6e8 (F1, F2, F6 and migration 418), 5a1d9a0a1 (F3, F4), a1611d17f (F5), c1c6045b2 (F7), 1b2670d9e (F8), 85e0f9f64 (F9).

F1 superseded identity returns. `provenance_batch` gained `generation` (migration 418, applied live; 417 was the highest before it): the primary key is `(batch_key, generation)`, the guard makes generation immutable, and `batch_key` stays the content identity and the skip key. A superseded latest row means the identity returns: `bulk_load` inserts generation + 1 and loads; the superseded row stays as history (no mutation, no trigger change beyond the immutable column). The takeover, completion, failure and supersede flip name the generation they act on, so a unit keeps one completed row. K1, K2, K1 on a real hypertable ends with K1's rows and the history `(K1,1,superseded) (K2,1,superseded) (K1,2,completed)`; the writer-level case 11 returns to the default identity after case 10 and replaces instead of failing, then skips. Nothing recomputes and then fails: a superseded identity legitimately recomputes because its rows were replaced. RED (old code): `BulkLoadRefused: ... superseded key is terminal and cannot be loaded again`.

F2 scope of the DELETE. The replace DELETE covers the `replace_where` scope over all time, the spec's range stays as the window rows may be written in and as provenance metadata, and a replacing spec's compressed-chunk refusal covers all time before `range_end` (the DELETE can reach any chunk). Todo 470's `--start` item is fixed and the todo says so. RED: `assert 4 == 8` (rows_replaced) for a later range_start.

F3 and F4 code key. `from pkg import Name` resolves through the package `__init__` to the module that defines Name (aliases, relative imports, chains of packages; only the names imported, never the whole hub); imports under `if TYPE_CHECKING:` are skipped (else kept). `src.core.code_identity.IO_BOUNDARY_MODULES` is an allow-list with a reason each, hashed by name only and not walked: `src.core.database_manager` (pool creation, pool gauges, jsonb codec registration; the snapshot reads bars as numeric and timestamp columns and `config_state.config_value` as text, so no jsonb decode reaches a value) and `src.observability.metrics` (OpenTelemetry instruments that record and never return or alter a value). `tier_aliases` is not on the list: it maps tier codes I1 to I8 to names, not timeframes, and was reachable only through metrics, so it leaves the closure by not being walked. Closure sizes (modules hashed per job), before then after: proposer 23 to 21, regime_volatility 22 to 20, monitoring 22 to 20; dropped: `src.observability.metrics`, `src.core.tier_aliases`; `src.core.database_manager` stays by name. No closure module had a TYPE_CHECKING-only import, so that rule removed nothing here. RED: `ImportError: cannot import name 'IO_BOUNDARY_MODULES'` for the new test module. The independent bytecode walk in test_ic_measure now resolves package names through `obj.__module__` and treats the allow-list as leaves.

F5 bootstrap stream. Ground truth: ic_engine seeds one generator per cross-sectional pass, `default_rng(seed=_derive_worker_rng_seed("cross_sectional", config.bootstrap_seed))` (services/ic_engine.py 6561-6563; derivation 1879-1897; "shared/advanced across every cell", 4719-4722, and 6555-6560), and draws one starts matrix per cell, reused by every feature block (2110-2117, 2158). The measure package draws the same shape with the same kernel but seeds a fresh `default_rng(alpha.ic.bootstrap_seed)` (raw constant) per cell. Decision: keep it. A constant per-cell seed is what makes a CI independent of the block size (P1), of cell order and of which units a rerun skips; an advancing stream would make a cell's CI depend on the cells before it. Every docstring that called the bootstrap ic_engine-equivalent now says: same draw shape and kernel, different stream, a CI is not bit-comparable with a stored ic_engine CI, IC and p-value are (measure.ic, services/ic_measure.py header, the 186-10 summary's `rng_seed` row). 186-20's parity scope is point IC only (its plan text says CIs are out of scope, D-21), so no plan claim is invalidated and no plan text changed. The 3.0e5 exactness bound (not 4.7e5) is stated where the kernel and scipy are compared. A characterization test asserts a cell's CI does not depend on which cells were measured before it.

F6 prior_completed_unit is False without a query for an append-only spec, so a dry run cannot report would_replace for it (test).

F7 naive timestamps. `_aware_utc` refuses a naive `alpha.validation.oos_start` and a naive `--start`, naming the key or flag (the rule `parse_training_window_end` applies); garbled values raise with the same name. RED: `DID NOT RAISE ValueError` for both.

F8 absent-digest scope. `check_bar_digests(before, after, used, ...)` checks the bracket and the absent refusal for the symbols the panels used, after the panels are built; a requested symbol with no bars and no digest row no longer blocks, and a used symbol with no row still does. RED: `TypeError: check_bar_digests() takes 2 positional arguments but 3 positional arguments (and 1 keyword-only argument) were given`.

F9 block digesting (applied in part). The skip decision already uses the scan's digests and only a computing unit re-fetches, so a run that skips every unit streams each column once and a computing unit adds one verifying fetch; tests count the fetches (the brief's 3 to 4 extra streams were the monitoring member scan on top of the family scan, now removed: monitoring takes its members' digests from the family scan, identity asserted equal). RED: `Counter({'f0': 2, 'f2': 2, ...})` (members fetched twice on a skip-everything run). Not done, on purpose: caching a verified digest across units. The proposer and regime_volatility units each fetch their own data, and a change between the two fetches would pass unchecked if the second reused the first's verification; the guard exists for exactly that. Sharing the fetch itself would need block-major execution across units (or holding every block in memory) and is not worth a third of one fetch pass at 1d.

Adjacent, not fixed: none that is real beyond what todo 471 already records.
