---
status: pending
priority: P2
filed: 2026-09-19
source: user statement 2026-09-19 that a 1000-2000 symbol universe is not reachable at the current
  compute cost; measured from the live ic_engine corpus run's log plus Fable 5.1's research pass
  (docs/research/2026-09-19-ic-engine-bootstrap-ci-optimization-research.md)
---

# ic_engine full recompute costs about 2.4 worker-hours per symbol -- a 1000-2000 symbol universe means 10-20 day recomputes; measure per-symbol threading before anything else

## What

The current corpus run (`services/ic_engine.py --workers 10`, PID 359172, started 2026-09-17) had
processed about 207 of the 233 `compute_eligible` symbols after 2 days 2 hours. Derived from
`logs/ic_engine.log*` `ic_engine.clustering` events (symbol count seen, not a benchmark; some
symbols counted are still in progress; box was also shared with other work, load average ~20):

- about 2.4 worker-hours per symbol, or 4-5 CPU-hours at the ~190% CPU each worker shows
- per-symbol work is linear in symbol count: 1000 symbols is about 10 days per full recompute on
  this box, 2000 is about 20 days
- the first run's per-symbol and pooled passes finished (233 symbols x 4 tfs, 2026-09-20 07:00 UTC),
  then the run died at 09:19 UTC on the first 15m cross-sectional cell because of a guard artifact,
  not a real size problem. Commit 100f0602b (2026-09-15, Phase 174-05, todo 371) added a pre-flight
  cell-size check that estimates rows as `regime_timestamps x symbols` (assumes every symbol has a
  row at every timestamp): 21.5M for 15m high_bear vs the 15M `alpha.ic.max_cell_rows` cap. Measured
  2026-09-20 with a join of `market_regimes` to `feature_vectors`: 15m high_bear actually has 4.1M rows
  (all 233 symbols, an upper bound for the 182-symbol group), and the largest 5m cell is 12.5M
  (mid_neutral). Every remaining cell is under 15M by its real count; the estimate overstates by
  2-6x because most symbols have far less feature history than the 2006 regime timestamps. The
  count query takes about 7 s for all 15m and 5m cells, so an exact pre-flight count is cheap.
  An earlier version of this todo wrongly scaled the cross-sectional stage from the estimate (98M
  rows, 250 GB scratch); those figures were the guard's upper bound, not real sizes.
  `max_cell_rows` is excluded from the cell fingerprint and cross-sectional cells resume via
  per-cell fingerprints, so a rerun keeps the completed 1d/1h cells.

Adding symbols is not the expensive part (existing symbols' results do not change when new ones
join, apart from pooled/cross-sectional stages). The cost that blocks iteration is every
recompute after a feature, config, or methodology change.

## Levers, in the order to pull them

1. **Per-symbol threading (measure first).** `per_symbol_bootstrap_threads` has been 2 on every
   TF since 2026-07-30 (`config_state`), so the ~2.7 worker-hr/symbol re-derived above ALREADY
   includes threading at 2 -- the "defaults to 1" framing was stale, and the remaining experiment
   is raising it above 2. The `cross_sectional_bootstrap_threads` comment at
   `services/ic_engine.py:583-598` records a 2-6x wall-time reduction from threading because
   scipy `rankdata` releases the GIL. Not measured on the per-symbol path above 2; measure memory
   before raising 5m (largest real cell 12.5M rows, deliberately set lower than 15m). Run only
   when the box is idle (no corpus run or phase execution live).
2. **Numba `nogil=True` kernel plus threads.** Fable measured a byte-identical 1.26-1.54x for a
   fused Numba kernel without `nogil` (`scripts/analysis/ic_engine_bootstrap_ci_numba_benchmark.py`,
   same contention caveat). `nogil=True` plus `ThreadPoolExecutor`, and `prange`, were not tested.
   Extend that script to test them before deciding.
   **Measured 2026-09-23 (idle box, 24 cores, script extended with scipy-threads/nogil/prange
   arms, all outputs byte-identical to scipy serial at 0.0e+00 diff -- exact, not float-noise):**
   numba serial 1.00-1.15x; scipy threads=2 1.75-1.88x (today's production setting, already
   captured in the 2.7 worker-hr/symbol figure); scipy threads=8 2.19-4.68x; nogil threads=8
   4.78-5.97x; **prange 10.77-13.12x** (uses all cores via numba's internal scheduler). The win
   over the best scipy-threads arm is ~2.3-2.8x at equal core budget. Production adoption needs a
   LAYOUT decision first: 10 worker processes x prange(at default) = 240-thread oversubscription;
   either cap numba threads per worker (~2, only ~10-20% over scipy-threads-2) or cut worker
   processes and give prange 4-6 threads each (the real ~1.5-2x end-to-end option). Editing
   ic_engine.py for adoption moves code_content_key -- belongs in the bundled todo 389/386
   landing, not standalone.
   **Built 2026-09-23 (branch perf/ic-engine-speedups), and the benchmark's prange kernel was
   the wrong target.** End to end on a real cell it gave only 1.23x at equal threads (SPY 1h,
   2 threads: 279s vs 342s), because every resample still argsorted every column. Replaced
   with a counting-rank kernel (`src/intelligence/statistics/ic_bootstrap_jit.py`): a bootstrap
   resample only repeats original rows, so each column is dense-ranked once and each
   resample's average ranks come from counts plus a prefix sum, with no sort in the hot loop.
   Measured end to end through `_compute_symbol_tf`, unprofiled, same box:

   | cell | path | threads | wall |
   |---|---|---|---|
   | SPY 1h | scipy (production) | 2 | 338.7s |
   | SPY 1h | counting kernel | 1 | 26.9s |
   | SPY 1h | counting kernel | 2 | 16.7s (20x) |
   | SPY 1h | counting kernel | 6 | 11.7s |
   | SPY 5m | counting kernel | 2 | 121.5s, peak RSS 3.8 GB |

   Correctness: bit-identical to scipy fed float64 (unit tests: ties, NaN rows drawn by some
   resamples, NaN returns, constant columns, early-stop chunking). Against production's float32
   path, CI bounds differ by at most 2.3e-8 over all 5706 SPY 1h rows with zero gate flips
   (scipy >= 1.15 keeps float32 ranks, so production accumulates in float32; the kernel is the
   more accurate path). Behind `alpha.ic.bootstrap_numba_kernel`, a COMPUTATIONAL fingerprint
   field. The profile after the kernel: 15.7s total on SPY 1h, kernel 9.8s, DB fetch ~1.7s,
   percentiles ~0.85s, remaining scipy rankdata (point IC, folds) ~1.5s.
   **Found on the way, a real determinism bug:** `_compute_symbol_tf` built its regime-label
   lists from `set(...)`, so string hash randomization reordered which cells draw from the
   shared per-symbol bootstrap RNG in every process. Same inputs, different CI bounds and
   `passes_ci_gate` run to run (9/4506 rows flipped on SPY 1h). Fixed with `sorted()` on the
   same branch; verified bit-identical across `PYTHONHASHSEED` values.
   **Layout:** 24 cores, 29 GB RAM, ~3.8 GB peak per 5m worker, so fewer processes with more
   threads each (e.g. 6 workers x 4 threads) instead of today's 8 x 2. Both knobs are
   operational (not in the fingerprint), so tune after landing without invalidating cells.
3. **Staged bootstrap.** Cheap point IC for every cell; 2000-resample bootstrap only where it can
   change a decision. Selecting cells on the same statistic later tested distorts BH-FDR, so the
   selection rule must be pre-registered and the FDR family defined over all cells. Todo 227's
   early stopping already does a within-cell version of this.
4. **Incremental recompute.** Key each cell's result to a feature-definition and config hash so a
   change to one feature invalidates only that feature's cells. Largest structural win, most
   engineering.
5. **Cluster.** The standing long-term direction (`project_long_term_securities_universe_scaling`).
   Optimize first; a cluster running an unoptimized job only costs more.

## Not in scope

HAC-for-rank-IC replacement of the bootstrap. Fable's verdict stands: the only candidate
(Pohle/Wermuth/Weiss, arXiv:2512.14609) is R-only, unvalidated on this corpus, and its own
simulations show no coverage advantage over block bootstrap. Revisit only as a dedicated
statistical validation against `ops_ic_null_calibration.py` on the 5m cells behind todo 099.

## Gate

**Lever 1 unblocked 2026-09-22 -- the run finished. Re-derived 2026-09-23 from the completed
run's own logs** (`logs/ic_engine.log.1`, `.log.2.gz`, `.log.3.gz`, manifest
`elapsed_s: 41391`): the run reached success through three process legs, and the earlier
"~11.5 hours total wall-clock" read counted only the last leg:

- **Leg A** (per-symbol + pooled, 10 workers): 2026-09-17 -> 2026-09-20 07:00 UTC, about 2.6-3.0
  days; all 233 per-symbol cells. Killed 09:19 UTC by the todo 386 pre-flight guard artifact.
- **Leg B** (cross-sectional restart after migration 347, `cs_chunk_ts=5000`): 2026-09-20 13:12 ->
  2026-09-21 ~21:00 UTC, about 31 h; log shows `n_to_compute: 0` (every per-symbol cell retained,
  straight into `starting_cross_sectional_pass`). Superseded by migration 348's `cs_chunk_ts`
  5000->2000; zero committed cells.
- **Leg C** (cross-sectional at `cs_chunk_ts=2000` + FDR/compression): 2026-09-21 21:03:27 ->
  2026-09-22 08:33:18 UTC, 11.5 h; `elapsed_s: 41391` is this process's lifetime only; 97128
  committed / 10738 skipped.

Corrected numbers (cite these):

- **Per-symbol pass: about 2.7 worker-hours per symbol** (about 650 worker-h / 233 symbols).
  The 2.4 mid-flight estimate was confirmed, not refuted.
- **Cross-sectional stage: about 9-11.5 h wall post-migration-348** (leg C), down from about 31 h
  at `cs_chunk_ts=5000` (leg B, discarded).
- **Clean full recompute today: about 3.1-3.5 days wall** (233 symbols, 10 workers), per-symbol
  dominated.
- At 1000 symbols: about 2700 worker-h / 10 workers = about 11-12 days per full recompute (plus
  cross-sectional growth). The original 10-20 day projection stands.

Scope any universe expansion by that cost, not a target symbol count. Phase 174's D-10 result
already made single-name equity expansion the weaker lever (cross-asset ETFs first), so this cost
bound mostly caps how far a later single-name expansion can go, not the near-term plan. What
remains open in this todo is the lever work, starting with the lever 1 threading measurement
(needs idle CPU; do not run while another corpus job or phase execution is live).

## Sequencing constraint

Any edit to a first-party module that `ic_engine.py` imports moves `code_content_key` (AST hash,
`_checkpoint_content_key`) and invalidates every completed cell. Levers 2-4 above are code changes, so
land them together, with todo 386 (exact pre-flight cell count replacing the Phase 174-05 estimate, and
restoring `alpha.ic.max_cell_rows` to 15,000,000 after migration 347 raised it to 100,000,000 for the
2026-09-20 rerun), immediately before the next recompute that is already required, never mid-run.
Lever 1 (thread counts) is APR-only and does not invalidate. Also hold `TagCalibrator` runs while a
rerun is resumable: the upstream watermark hashes `instrument_tags` (symbol, tag, source, weight).
