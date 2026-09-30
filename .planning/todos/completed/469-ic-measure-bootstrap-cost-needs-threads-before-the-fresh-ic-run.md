---
status: completed
priority: P2
filed: 2026-09-30
closed: 2026-09-30
source: plan 186-14 live dry run of services/ic_measure.py
---

Closed by plan 186-14 pass 2: the counting-rank kernel, sliced draws and 12 threads make the full 1d
universe a 7-minute serial run, so unit-level worker processes are not built. Decision and numbers
below ("Pass 2 measurements"). The intraday full-universe memory question this run raised is todo 471.

# The fresh IC writer's bootstrap is serial and too slow for the 186-28 run

## What

`services/ic_measure.py` calls the 186-10 measure jobs, whose `pooled_rank_ic` calls
`_circular_block_bootstrap_ic` with its default `max_workers=1`: 2000 resamples, each re-ranking the
resampled (n, 32) block. Measured 2026-09-30 on one idle core (single cell, 32 features,
2000 resamples): 22 s at 5,000 strided rows, 102 s at 20,000, linear, so about 5 ms per strided
row per cell.

A full 1d cell (931 names x about 2,700 sessions, stride 5, about 500,000 strided rows) is about
42 minutes, and a unit costs five cells (term structure at four horizons, plus the proposer cell
at the first horizon), so the 1d proposer alone is on the order of 35 hours serial before
`regime_volatility` disclosure (per label, per horizon). The unbounded dry run confirmed it: 1d on
931 names ran 73 minutes without finishing its first unit; 15m on 40 names ran 37 minutes
without finishing its first unit (both killed).

ic_engine avoided this with bootstrap threads (`alpha.ic.cross_sectional_bootstrap_threads.*`,
about 5x at 16 workers) and early stopping (`alpha.ic.bootstrap_early_stop.*`); `MeasureParams`
carries neither.

## Why it matters

186-28 runs the fresh IC once on the rebuilt features. At serial speed that is days of wall clock,
and a kill loses the current unit (units are the resume grain).

## What to do

Measure first (the 186-14 numbers above are the baseline), then pick: a thread count on
`MeasureParams` passed to the bootstrap (determinism holds: only the order-free resample step is
threaded), unit-level worker processes in the writer (compute-only workers, writes stay serial in
main, the CLAUDE.md pool rule), or both. Keep the stored values bit-identical to the serial path
for one small cell as the acceptance test. Decide before 186-28 starts, not during it.

## Pass 2 measurements (2026-09-30): kernel step done

The measure package now bootstraps with `ic_bootstrap_jit` (counting ranks, no sort) through
`measure.ic.block_bootstrap_ci`, drawing block starts from one `default_rng(seed)` stream in slices of
`infra.ic_measure.bootstrap_chunk_resamples` (250) and running them on `infra.ic_measure.bootstrap_threads`
(12) numba threads. Both keys are operational (migration 417), never in a unit identity. Jobs that discard
the CI no longer compute it: the term structure bootstraps only its first (proposer) horizon and monitoring
none.

Synthetic cell, 50,000 rows x 32 features, 2000 resamples, block 10, BLAS at 1 thread, 24-core host with a
backfill running:

| Path | Wall clock |
|---|---|
| scipy per resample (the 186-14 path) | 277 s (138 ms per resample, measured on 100 and scaled) |
| kernel, 1 thread | 5.9 s |
| kernel, 2 threads | 3.1 s |
| kernel, 6 threads | 1.8 s |
| kernel, 12 threads | 1.0 s |

Real cell, `--tf 1d --symbols SPY --jobs proposer --dry-run` (one symbol, four horizons, 300 features): 21.7 s
before, 4.8 s after (both include the panel build and feature fetch).

Bit-identity against the scipy path: stored rows of 14 captured cases (five raw cells with ties and a constant
column, n up to 60,000; proposer, disclosure and monitoring rows of three synthetic tfs) are exactly equal
before and after, and a unit test compares the kernel CI with `_circular_block_bootstrap_ic` on the same
starts. The exactness bound is lower than the kernel's docstring says: centered ranks are multiples of 0.5 so
their squares are multiples of 0.25, and the sums are exact below n**3 / 12 < 2**53 / 4, n below about 3.0e5,
not 4.7e5. Measured against scipy on the same resample rows (3 columns, 12 resamples): n = 300,000 identical
(0 of 36 differ); n = 450,000 to 2,000,000 all 36 differ by up to 2e-14 absolute (about 1e4 to 6e4 ulps of a
0.001 IC). `feature_ic_scores_v2` stores these columns as double precision, so the differences are kept, not
rounded away. The fresh table is empty and the legacy table came from another engine, so nothing stored has to
match; within the new engine the result is the same for any thread count and slice size, and the code key
moved with the kernel.

## Decision (2026-09-30): closed without unit-level worker processes

Real dry runs on the live database after the kernel, the skipped bootstraps and the thread count
(`services/ic_measure.py --dry-run`, BLAS at 1 thread, kernel at 12 threads, a backfill running on the
host; none writes):

| Run | Before (HEAD at the start of pass 2) | After |
|---|---|---|
| 8 symbols, `--tf 1d --jobs proposer` (`AA AAPL ADM AEP AGG AMD AMLP AMT`) | 1:43.8 (the executor's 10:55 was the pre-pass-1 per-block units) | 0:10.1, 488 MB |
| 100 symbols, `--tf 1d`, both default jobs | not run | 0:31.5, 830 MB; scan pass 12.6 s of it, bootstraps about 7 s per job |
| all 925 compute_eligible_1d symbols, `--tf 1d`, both default jobs | first unit unfinished after 73:01 (186-14 summary) | 7:12 (proposer unit done at 5:12, disclosure at 7:10), 4.0 GB peak |
| 40 symbols, `--tf 15m`, both default jobs (4,170,077 feature rows, 2006 to 2026) | first unit unfinished after 37:29 | 17:04 (proposer 11:37, disclosure +5:25), 6.9 GB peak |

What dominates at 1d is now the serial feature fetch (three passes over 300 columns: the identity scan and
one verified fetch per job, about three quarters of the wall clock at 100 symbols), not the bootstrap. Processes would
parallelize fetch and compute across units, but a full 1d run is minutes, a kill loses at most one unit
(about 2 to 5 minutes), and a worker needs its own connection and the shared grid. The CLAUDE.md pool rule
(compute-only workers, one serial writer) would be followed, but there is nothing to buy at 1d, so nothing
is built. `UnitCompute` (a frozen dataclass, not a closure) names exactly what a unit's compute holds; it is
not picklable because `source.fetch` is bound to the parent's connection, and that is stated on the class.

Remaining cost, not a bootstrap cost: the 15m run scales with rows (about 23x the 40 names for the whole
universe, hours of kernel time at 12 threads) and its memory scales with bars x symbols x the block width
(`alpha.ic.feature_block_columns`, 32). That is todo 471.
