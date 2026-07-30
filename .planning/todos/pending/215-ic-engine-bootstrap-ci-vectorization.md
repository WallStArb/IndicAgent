---
status: pending
priority: P1
filed: 2026-07-30
source: user mandate mid-session ("compute needs to improve") -- live py-spy profiling of
  the running corpus pipeline's ic_engine step (started 2026-07-30 13:19 EDT) found this
---

# `_blocked_bootstrap_ci`'s 2000-resample loop is a serial Python for-loop calling
# `scipy.stats.rankdata` twice per resample -- the confirmed hot path for the corpus
# pipeline's single longest-running step

## Evidence

Live `py-spy dump` against 5/5 samples of a running `ic_engine.py` ProcessPoolExecutor
worker (PIDs 1404438/1404442, corpus pipeline step 5/8, 2026-07-30) landed in the same
stack every time:

```
_wrapfunc (numpy/_core/fromnumeric.py:54)
argsort (numpy/_core/fromnumeric.py:1213)
_rankdata (scipy/stats/_stats_py.py:10045)
rankdata (scipy/stats/_stats_py.py:10011)
_resample_ic (services/ic_engine.py:1583)
_blocked_bootstrap_ci (services/ic_engine.py:1590)
_subsample_and_rank (services/ic_engine.py:1722)
_compute_one_regime_cell (services/ic_engine.py:1938)
_compute_symbol_tf (services/ic_engine.py:2304)
```

`_blocked_bootstrap_ci` (ic_engine.py:1526-1576) resamples `alpha.ic.bootstrap_resamples`
(currently 2000) times per feature block, per scale, per regime, per tf, per symbol.
`alpha.ic.feature_block_columns` = 32, and there are ~244 features, so each cell does
~8 blocks x 2000 resamples x 2 `rankdata` calls (X block + Y) = ~32,000 individual
`rankdata` calls, run in a bare Python `for b in range(n_boot)` loop (`pool is None`
branch, lines 1567-1570) -- threading is deliberately disabled on this path per todo
131's docstring: "never passed for the per-symbol ProcessPoolExecutor worker path."
Per-call overhead (function dispatch, small-array argsort setup) dominates at this
call count.

Step 5 (`ic_engine`) is one of the two largest steps in the 8-step corpus pipeline (the
other is `regime_writer`, see todo 216) -- it took 2h40m+ and was still running (~15% of
58 symbols done) when this was filed.

## Constraint: this function has documented bit-identical reproducibility guarantees

`_subsample_and_rank`'s docstring (ic_engine.py:1602 area) is explicit: the bootstrap
resample index matrix is drawn from `rng` exactly ONCE before the feature-block loop,
reused identically across every block, and this was "verified: a single batched
`rng.integers(..., size=(B, K))` call consumes the RNG stream identically to B
sequential calls" -- i.e. bit-identical, not "close," is the existing bar. The blocked
design itself exists to bound peak memory (`O(n_sub x block)` not `O(n_sub x
n_features)`) after a 2026-07-18 OOM caused by `rankdata` always returning float64
regardless of input dtype.

## Fix sketch (not yet designed in detail)

Vectorize `_resample_ic`'s loop over some bounded batch of resamples at once (NOT all
2000 -- that multiplies the block's transient memory by 2000x and would very likely
reproduce the 2026-07-18 OOM class of bug, especially given the host is already RAM-
constrained: `infra.ic_engine.workers` was RCA-capped at 8 on 2026-07-12 specifically
because 12 workers caused swap thrashing on this 29GB box, per todo 102 -- and `free -h`
during this run already shows 1.7GB in swap with only 8 workers running). A batched
approach (e.g. `resample_batch_size` resamples ranked together via one vectorized
argsort-based rank call per batch, looped `n_boot / resample_batch_size` times instead
of `n_boot` times) trades a bounded amount of extra transient memory for eliminating
most of the ~32,000-calls-per-cell Python/rankdata dispatch overhead. Needs its own
`resample_batch_size` sizing pass (mirrors `feature_block_columns`) and a test verifying
byte-identical CI output against the current unbatched implementation across a range of
n_valid/block_p values -- same bar the existing feature-blocking passed.

## Why not fixed now

`ic_engine.py` is the same file with a live corpus-pipeline run in flight as of filing
(do not touch/restart that process -- see STATE.md). Design, implement, and verify
bit-identical output entirely offline; land on `main` only once tested, ready for the
NEXT corpus run, never touching the current one.

## Sizing

Real algorithmic change to a measurement-integrity-critical function -- needs its own
plan with a bit-identical verification test, not a quick patch.
