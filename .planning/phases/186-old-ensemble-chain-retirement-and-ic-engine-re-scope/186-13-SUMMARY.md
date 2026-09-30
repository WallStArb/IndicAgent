---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 13
subsystem: features
tags: [hmm, regime, kernel-registry, walk-forward, causality, golden-parity]
requires:
  - phase: 186-12
    provides: kernel registry with external inputs, path-dependent kernels, causality probe
provides:
  - walk-forward HMM as four registry kernels (trend and volatility heavy kernels plus label kernels), math in kernels/_hmm.py
  - regime golden fixture with a capture, verify and regenerate script
  - thin regime_writer (one fetch, one compute, one write) over the kernels
  - causal segment gate (training slice) and length-independent first boundary
  - migration 410 (dead HMM APR keys deleted, infra.hmm.rolling_block_rows seeded)
affects: [186-16, 186-18, 186-25, 186-26]
tech-stack:
  added: []
  patterns:
    - "capture golden from the unchanged code first, move code in commits that leave the fixture untouched, behavior change as a fix commit plus a regeneration commit"
    - "golden defined at one BLAS thread; more threads are not run to run reproducible"
key-files:
  created:
    - src/intelligence/features/kernels/_hmm.py
    - src/intelligence/features/kernels/regime.py
    - scripts/infrastructure/features_capture_regime_kernel_golden.py
    - tests/fixtures/regime_kernel/ (manifest, real_inputs, real_golden, synthetic_golden)
    - tests/unit/intelligence/regime_kernel_fixtures.py
    - tests/unit/intelligence/test_regime_kernel.py
    - production/migrations/410_regime_kernel_apr.sql
    - .planning/todos/pending/466-regime-columns-lookahead-dependents-303-304-benchmark.md
    - .planning/todos/pending/467-regime-kernel-raises-on-a-constant-training-slice.md
  modified:
    - services/regime_writer.py
    - services/_batch_utils.py
    - services/backfill_feature_factory.py
    - src/intelligence/feature_factory.py
    - src/config/vocabulary_drift.py
    - scripts/ops/corpus/ops_regime_null_out_and_verify.py
key-decisions:
  - "Todo 248 was already deployed (flag true since 2026-08-12); the plan's premise 'built, not deployed' was stale and is corrected in the todo, PRIORITIES.md and memory (STATE.md left to the coordinator)"
  - "The segment gate is taken on the fitted model's smoothed decode of its own training slice; the first boundary is max(warmup, K x min_obs_factor)"
  - "The writer and its tests pass the kernels a SimpleNamespace of hmm_* fields, because FeatureFactoryConfig has about 150 required fields"
patterns-established:
  - "moving pure code from services/ into src/ puts it under 'mypy src/': check it before merging"
requirements-completed: [D-29, R-10, D-01]
duration: 100min
completed: 2026-09-30
---

# Phase 186 Plan 13: Walk-forward HMM regime kernels, causal segment gate, thin regime_writer

The per-symbol walk-forward HMM is now four pure registry kernels (`hmm_trend_walk_forward`,
`hmm_volatility_walk_forward` and their label kernels) that reproduced the unchanged writer's
output byte for byte on a golden captured first. The full-history path and its flags are deleted.
The segment occupation gate did read future bars (proved by two RED tests) and is fixed and
re-goldened in separate commits. `regime_writer` is a fetch, kernel, write wrapper that was never
run against `feature_vectors`.

## Commits (branch phase-186-13, fast-forwarded into main locally; not pushed)

| Step | Commit | Message |
|---|---|---|
| T1 | `ec3d8a814` | docs: verify todo 248 deployment state; correct PRIORITIES.md |
| T1 | `01296f4ed` | test: regime walk-forward golden captured from the unchanged writer |
| T1 | `02b5beb31` | refactor: walk-forward HMM as registry kernels |
| T1 | `a75048500` | refactor: delete the full-history HMM path; walk-forward is the only mode (D-29) |
| T2 | `e24427178` | fix: gate walk-forward HMM segments on their training data, not the decoded future (causal) |
| T2 | `bef01e2d7` | test: regenerate regime golden after the causal segment gate fix |
| T2 | `e58fc52f0` | docs: close todo 451, file todo 466 |
| T3 | `a3599078b` | perf: bound rolling-window memory in the HMM obs builders (todo 290) |
| T3 | `efe3613c2` | refactor: thin regime_writer over the regime kernels (todos 290, 291) |
| T3 | `4f2ca1e6d` | chore: migration 410 deletes dead HMM APR keys, seeds infra.hmm.rolling_block_rows |
| T3 | `bf6388efd` | perf: single regime scan in the vocabulary drift audit; precomputed null-out SQL |
| T3 | `eee38a608` | docs: close todos 248, 290 and 291; note on todo 108 |
| Review | `3c69cbb49` | chore: review pass (mypy-clean moved code, drop dead helpers) |
| Review | `d754a1c98` | fix: kernel modules must not carry the word "backward" (scan test) |
| Docs | see git log | todo 467, this summary, ROADMAP tick |

## D-01 gate

`ps aux | grep -E "ic_engine|backfill_feature_factory|regime_writer|rebuild|ic_measure" | grep -v grep`
at 2026-09-30 00:2x EDT: no output; `ps -eo pid,cmd | grep '[i]c_engine'`: none. STATE.md's lane table
lists no live or resumable ic_engine corpus run or feature rebuild. `regime_writer`, `_batch_utils`,
`feature_factory` and `metrics` are in ic_engine's import closure and were edited with no run live
or resumable. The todo 449 backfill lane and its files were not touched.

## Todo 248 state (task 1 step 2)

Verdict: walk-forward deployed for every sampled cell; the STATE.md bullet ("walk-forward fix built,
not deployed") is stale.

- `config_history`: `alpha.hmm.walk_forward.enabled` version 2 = true, 2026-08-12 18:20:40 UTC, by
  brandon, "flipped alongside the post-231-symbol-expansion full corpus recompute"; `config_state`
  true today.
- `logs/regime_writer.log.2` and `.3` (2026-08-16): 1,986 `walk_forward_hmm_convergence_iters`,
  1,512 `walk_forward_segment_skipped`, 21 `walk_forward_all_segments_degenerate` events. The
  older `.log` and `.log.1` hold no `regime_writer.starting` record.
- First non-NULL label, 0-based among `market_data_ohlcv_tradeable` bars: regime SPY 1d 1280, SPY 1h
  8270, TLT 1d 776, TLT 1h 4970, QQQ 1d 776, QQQ 1h 4970; regime_volatility SPY 1d 1003, SPY 1h
  18649, QQQ 1d 2515, QQQ 1h 13699, TLT (both) none. Walk-forward warmup is 504 (1d) and 3300 (1h).
  The full-history path would put the first label near bar 20.
- Corrected: the todo (State verified section), PRIORITIES.md, the memory entry and its MEMORY.md
  index line. STATE.md was not edited (see "Relay to the coordinator").

## Golden and parity

- Sample (fixed before capture): SPY, TLT, LQD 1d full history and SPY 1h full history (31,254
  bars), both families, plus `make_synthetic_regime_bars(3000, 42)` under `SMALL_HMM_APR` at the 1d
  schedule. Captured at commit `ec3d8a814` from the unchanged writer functions through a fake
  connection serving only the two bar SELECT shapes, each case run twice, refusing on difference.
- The first two capture attempts refused: the same fit differs run to run at 24 BLAS threads
  (SPY 1d trend probabilities differ in low bits; measured, 3 runs). At one thread it is
  reproducible, and production's pool runs one thread per worker (`limit_blas_threads`). The
  golden is defined at one thread; the capture script sets the thread environment variables before
  numpy loads and the test module holds `threadpool_limits(1)`. The kernel's determinism guarantee
  (186-25) therefore holds at one BLAS thread.
- Kernel vs writer on the unchanged-behavior commits: `--verify` printed `VERIFY OK: 10 case/family
  digests match the stored golden` (57 s, all ten including SPY 1h). `test_regime_kernel.py` runs
  the synthetic case and the three 1d cases (about 16 s); SPY 1h is left to `--verify` (about 40 s
  per run).
- Fixture directory history: `git log main..phase-186-13 -- tests/fixtures/regime_kernel/` shows the
  capture commit and, after task 2, the regeneration commit; neither refactor commit touched it.

## RED tests (task 2, todo 451), against task 1's code

- Segment gate (`test_segment_gate_verdict_does_not_depend_on_bars_after_t`): 920-bar series
  (`make_collapsing_segment_bars`, first segment = bars 620..919). Full run:
  `_hmm_trend_segment_status[620:649]` = all 2 (degenerate_occupation); run cut at bar 649: all 1
  (written). Output: `AssertionError: the segment gate read bars after the cut ... array([2., 2., ...
  2.]), array([1., 1., ... 1.])`.
- Length gate (`test_first_boundary_does_not_depend_on_total_series_length`): 700-bar series, the
  full run labels bar 620 and 621 (code 0.0); cut at 622 bars (602 observations, below
  warmup + K = 603) every row was NaN. Output: `assert np.array_equal(full[...][:622],
  truncated[...], equal_nan=True)` false, tail `... nan, 0., 0.` against `... nan, nan`.
- Both pass after `e24427178`; the causality probe passes both heavy kernels at ulp 0 under
  `SMALL_HMM_APR` at the 1d and 1h schedules at rows just after a refit boundary, mid-segment and
  the last row.

## Flip list (golden regeneration, from `--dump` before and after)

Every difference lies in a refit segment whose gate verdict flipped, except `hmm_duration` in the
first written run after a flipped segment (a run starts exactly at a flipped segment's end, labels
equal): SPY 1d 21 rows, SPY 1h 3, synthetic 27. No churn difference outside flipped segments.

| Case / family | Segments flipped | Rows gained a label | Rows lost a label |
|---|---|---|---|
| SPY 1d trend | 13 skipped to written | 3,052 | 0 |
| SPY 1d volatility | 1 written to skipped | 0 | 252 |
| SPY 1h trend | 11 skipped to written | 18,034 | 0 |
| SPY 1h volatility | 3 skipped to written, 1 written to skipped | 4,355 | 1,650 |
| LQD 1d trend | 1 written to skipped | 0 | 252 |
| LQD 1d volatility | 1 skipped to written | 252 | 0 |
| TLT 1d trend | 1 each way | 252 | 252 |
| TLT 1d volatility | none | 0 | 0 |
| synthetic trend | 7 skipped to written | 2,080 | 0 |
| synthetic volatility | 1 skipped to written | 300 | 0 |

The training-slice gate accepts far more segments than the whole-segment gate (which rejected a
segment for its own future collapse). Stored `feature_vectors` coverage will rise when the rebuild
runs; that bears on todos 289 and 341 (re-measure in 186-18). The flip report is in
`manifest.json` (`changed_cases`).

## Caveat trace (todo 466)

Read-only grep of the ledger, summary cards, `scripts/research/` and `src/intelligence/research/families/`:
no family or positive verdict reads the stored regime columns. Dependents: the DEAD 303 and 304
verdicts benchmarked against stored `regime_volatility` (orthogonality on 5 sample symbols, 3 with
non-empty labels; regime_volatility-stratified terciles), a benchmark whose mask can only make
candidates look worse; `scripts/research/feature_matrix.py` excludes `regime` but not the numeric
`hmm_*` columns. `feature_ic_scores` rows with `regime_scope = 'symbol_hmm'` are deleted by 186-20.
Filed as todo 466 (P2) with a PRIORITIES row; the defect is on the `cache-feature-vectors-v1` card
(`test_summary_cards.py` green). Todo 451 closed with the RED outputs and flip counts.

## Todos 290 and 291

- Rolling memory: `_rolling(arr, window, fn, block_rows)` is bitwise equal to the unblocked result
  at windows 20, 60, 250 and block sizes 1, 7, 4096, 5000 for `np.std`, `np.sum`, `np.mean`
  (test passes; no prefix sums needed), and both obs builders are equal blocked at 257. tracemalloc
  peak at n = 395,609, window 250 (volatility builder): 809.7 MB unblocked, 48.7 MB blocked
  (16384 rows). Regime golden unchanged.
- `bulk_update_by_key` returns the JOIN-UPDATE rowcount (`-> int`), tested.
- Writer: `_fetch_bars`, `_compute_family_rows`, `_write_family_results` (no count query),
  `RegimeWriteSpec` constants (`TREND_SPEC`, `VOLATILITY_SPEC`), `_WorkerArgs` NamedTuple with a
  field-name test, one end-of-run grouped NULL-remaining query setting the gauge per
  (symbol, tf, regime_column); both families record `REGIME_WRITER_ROWS_UPDATED_TOTAL` with
  `regime_column`. `grep -rn "regime_writer_null_regime_remaining\|regime_writer_rows_updated"
  production docs` finds no dashboard or doc query; only the metric descriptions in
  `src/observability/metrics.py` (updated).
- The writer was not run against the database. Its UPDATE path goes through
  `compressed_hypertable_write_session`, which the todo 426 guard refuses; the guard is untouched.
  Every writer test uses mock connections.
- Vocabulary drift audit: one `array_agg(DISTINCT ...) FILTER` scan feeds both regime namespaces;
  three new `run_drift_audit` tests on fakes cover per-namespace results, all-NULL idle and the
  empty-string placeholder. `_ColumnFamily` computes its four SQL strings once (test counts calls).

## D-08 greps (2026-09-30)

- `_compute_symbol_tf\b` (regime_writer's): live code outside the writer imports it only in three
  analysis pilots (`scripts/analysis/hmm_regime_parameter_lookahead_pilot_spy_1h.py`, `..._tlt_1h.py`,
  `..._spy_15m.py`), which 186-16 deletes; the other `_compute_symbol_tf` hits are ic_engine's and
  backfill_feature_factory's own functions. `_compute_symbol_tf_walk_forward`,
  `_compute_symbol_tf_volatility_walk_forward`, `_fetch_obs_matrix*`, `_write_regime_results`,
  `_write_regime_volatility_results`: no importer outside the writer and its tests, only prose in
  scripts and docs.
- `walk_forward_enabled`, `--no-walk-forward`: nothing outside the writer. `alpha.hmm.walk_forward.enabled`:
  a comment in `services/ic_engine.py` and migrations. `heldout_fraction`: the three pilots (a
  kwarg to the deleted function) and migration 176. `alpha.hmm.n_restarts`: analysis pilots and
  migration 277. Nothing else reads any of the three keys.

## Deleted tests

`test_compute_symbol_tf_returns_tuple_structure`, `_logs_convergence_iterations`, `_regime_values`,
`_probabilities_sum_to_one`, `_returns_none_on_insufficient_data`, `_no_db_write`,
`test_compute_symbol_tf_n_restarts_default_fits_once_on_convergence`,
`..._default_preserves_same_seed_retry`, `..._selects_highest_log_likelihood`,
`test_run_symbol_worker_dispatches_on_walk_forward_flag`,
`test_main_regime_volatility_no_walk_forward_exits_nonzero`, the four
`test_fetch_obs_matrix_volatility_*` tests (replaced by two `_fetch_bars` tests), the two
`test_write_regime_volatility_results_*` tests (replaced by parametrized `_write_family_results`
and `_record_null_remaining` tests), the arity-pin test (replaced by the NamedTuple field-name pin).
The walk-forward wrapper tests stay, calling a test-local adapter with the old argument list over
`_fetch_bars` and `_compute_family_rows`.

## Migration 410

`production/migrations/410_regime_kernel_apr.sql`, numbered above the highest file in the shared
checkout and the other worktrees (409); applied live in the same step as its commit (`4f2ca1e6d`).
Effects verified: the three keys (`alpha.hmm.walk_forward.enabled`, `alpha.hmm.n_restarts`,
`feature.hmm.heldout_fraction`) are gone from `config_state` and `config_schema` (count 0), 3
`config_history` rows remain, `infra.hmm.rolling_block_rows` = 16384 with its history row. A
consequence for anyone running the pre-merge writer from another checkout: the walk-forward flag
key no longer exists, so its fallback (False) would select the single-fit path there; that path's
UPDATE is refused by the 426 guard anyway.

## Deviations from Plan

1. **[Rule 3] Config object.** The plan says `FeatureFactoryConfig(**load_hmm_config_fields(cfg))`;
   `FeatureFactoryConfig` has about 150 required fields, so the writer and tests build a
   `SimpleNamespace` of the hmm_* fields (the kernels read only those). The rebuild passes the real
   config, which carries the same fields (backfill's `_build_feature_factory_config` merges
   `load_hmm_config_fields`).
2. **[Rule 1] Nondeterministic capture.** Fixed by defining the golden at one BLAS thread (above).
3. **Logging.** Segment-skipped, convergence and insufficient-obs events are emitted by
   `walk_forward_family_arrays` (with gate diagnostics) rather than the writer; the kernel has no
   `symbol` input, so the convergence events carry `tf` and `symbol=None`. Nothing consumes those
   events beyond the phase 171/172 planning docs.
4. **Plan ordering.** The intermediate 17-element worker tuple (task 1) then the NamedTuple (task 3)
   as planned; the writer-function mode of the capture script was removed in task 3 when the
   functions it called were deleted. The manifest's `source` field still says `writer` (the first
   capture); `regenerated_from` and `changed_cases` document the regeneration.
5. **Extras the merge required (Rule 3):** the moved HMM math is now under `mypy src/`, so three
   `Any` returns and one `min(key=)` were typed (bitwise output unchanged); the scan test
   `test_no_smooth_or_backward_in_factory` rejected the word "backward" in a moved comment;
   `test_kernel_registry` origin allow-list gained `regime`; `test_regime_writer.py`'s obs-builder
   signature pin gained `block_rows`; the eight per-tf `hmm_*` schedule fields are in
   `tools/vulture_whitelist.py` (read by `getattr`); the capture script gained `--dump` and
   `--regenerate --changed-from` so the flip report is reproducible.
6. **STATE.md not edited** (dispatch: coordinator owns it).
7. `/simplify` and `/review` cannot be invoked from an executor. I did a manual pass instead
   (diff read for dead code, stale docstrings, mypy, vulture, ruff, black, all touched tests); the
   coordinator runs the two gates after this lands.

## Verification

- Branch worktree, `pytest tests/unit/ -q --ignore=tests/unit/scripts/test_venue_study_script.py`:
  exit 0, 2 skips (the same two as before).
- Merged main checkout (`/home/bg/dev/indicagent`, tip `d754a1c98`, same command): exit 0, the
  same 2 skips.
- `repro_frozen.py`: not required; nothing under `src/intelligence/research/` or `statistics/`
  changed (`git diff --stat 53905e1ca HEAD -- src/intelligence/research services/cross_sectional_regime_model.py
  tests/fixtures/kernel_parity` is empty).
- `ruff` clean on touched files, `black --check` clean, `vulture` adds no finding over main's
  existing exit-3 run, `mypy` clean on the two new kernel modules.
- `default_registry()` has origin `regime`; its 16 feature columns equal the two owned-column
  constants; `feature_memory_bars` raises for each (tested).

## Handoffs

- 186-16: after `scripts/analysis/` is deleted, `_walk_forward_hmm_labels`, `_hmm_seed_stability_check`,
  `_state_groups` and the `_causal_decode` alias in `kernels/_hmm.py` (and their re-exports in
  `regime_writer.py`) are used only by tests; delete them with the pilots. Vulture flags them at 60%.
- 186-18: the training-slice gate changes which segments are skipped (table above); re-measure todo
  289 (1d `regime_volatility` coverage) and 341 (BIL, ETHA, IBIT all-NULL).
- 186-25: `compute_batch` still emits None for the hmm columns; the rebuild pass reads the regime
  kernels (`compute_kernels(default_registry(), inputs, config, outputs=...)` with `tf` per row).
  Run the kernels at one BLAS thread. A constant training slice raises (todo 467).

## Relay to the coordinator

- STATE.md still says "walk-forward fix built, not deployed" (line ~121); replace it with: walk-forward
  deployed 2026-08-12 (flag true, corpus recomputed); stored regime columns carry the todo 451 gate
  mask until the 186-26 rebuild; 186-13 makes the HMM a registry kernel. The PRIORITIES "Build" row
  (line 51) still lists "290, 291, 248 bundle"; those are closed.
- 186-13 unblocks: 186-18 and 186-25 handoffs above.

## Known Stubs

None.

## Threat Flags

None: no new endpoint, auth path or trust-boundary file access. The migration deletes three APR
keys with no remaining reader.

## Self-Check: PASSED
