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

## Fix attempt 1: batching -- FALSIFIED by measurement, do not retry

Original hypothesis: vectorize `_resample_ic`'s loop over a bounded batch of resamples
at once (NOT all 2000, to respect the RAM ceiling), eliminating per-call Python/
rankdata dispatch overhead. Implemented (`_vectorized_ic_batch` + a batched
`_blocked_bootstrap_ci`, `resample_batch_size` param), verified byte-identical output
across batch sizes 1/7/25/50/100/250/2000 -- but **directly benchmarked on a realistic
array (n_valid=4000, block_p=32, n_boot=2000) it produced ZERO speedup and got
progressively SLOWER as batch size grew** (21.7s at batch=1 -> 32.5s at batch=2000).
Root cause of the falsified hypothesis: each individual resample's rankdata call
(n_valid=4000 x block_p=32) is not actually "small" -- there was no meaningful per-call
dispatch overhead to eliminate; the O(n log n) sort cost is the real, inherent cost,
paid once per resample regardless of batching. Reverted entirely -- do not resurrect
this approach without new evidence.

## Fix attempt 2: threading -- REAL, MEASURED WIN, PARTIALLY LANDED 2026-07-30

While benchmarking attempt 1, tested whether `_blocked_bootstrap_ci`'s pre-existing
(but per-symbol-path-disabled) `pool: ThreadPoolExecutor` parameter actually helps --
it does, substantially: scipy's `rankdata`/`argsort` releases the GIL, so on the SAME
realistic array, 2/4/8 threads gave ~2.4x/4x/5.9x wall-time reduction (26.8s serial ->
4.6s at 8 threads), with output verified byte-identical (resample indices are fully
determined before any resampling begins; `np.percentile` is order-invariant --
`test_subsample_and_rank_threaded_matches_serial`).

This mechanism already existed in the codebase (`cross_sectional_bootstrap_threads`
uses it) -- todo 131 just hardcoded `max_workers=1` for the per-symbol path on the
theory that threading on top of the already-running `n_workers`-way
`ProcessPoolExecutor` pool would oversubscribe cores rather than help. That theory was
asserted, never measured, and the isolated-single-worker benchmark above contradicts
it. **Landed**: `max_workers=1` -> `config.per_symbol_bootstrap_threads[tf]` (new
per-tf dict field, mirroring `cross_sectional_bootstrap_threads`'s exact shape via the
shared `_load_per_tf_apr_dict` helper -- code review caught an initial flat-`int`
version that should have reused this, fixed before commit), backed by 4 new APR keys
`infra.ic_engine.per_symbol_bootstrap_threads.{5m,15m,1h,1d}` (migration 273), **all
seeded at 1 (serial, byte-identical to pre-215 behavior)** -- deliberately NOT raised
to the benchmarked value, because the isolated-worker test doesn't establish whether a
given thread count nets positive once all `infra.ic_engine.workers` (currently 8)
processes are threading simultaneously and genuinely contending for the box's 24
cores. That's a materially different concurrency regime from one worker running alone.

Also corrected the same now-disproven oversubscription claim everywhere it was
persisted or documented, not just the code path this todo actually changed: migration
250's live `config_schema.description` for `alpha.ic.cross_sectional_bootstrap_threads.5m`
(migration 274 -- description-only correction, no value change), and
`ic_math.py`'s `_circular_block_bootstrap_ic`/`circular_block_bootstrap_ic_serial`
docstrings. That second function (a separate implementation, used by one other
per-symbol call site -- daily/context-feature bootstrap CI, `ic_engine.py` ~line 2481)
was deliberately left structurally serial-only (no `max_workers` param at all, by
design, to prevent exactly this kind of accidental oversubscription copy-paste) --
its docstring now says the old claim is unmeasured/disproven-elsewhere rather than
settled fact, but extending threading to it is separate, unstarted scope: a different
function, needing its own benchmark, not covered by this todo's evidence.

## Remaining: multi-worker contention benchmark

The mechanism is in place and config-only to raise (no code change needed once a safe
value is known). What's left: measure real speedup/regression under actual 8-process
concurrent load -- deliberately NOT done live against today's in-flight corpus pipeline
run (would either contaminate the benchmark with contention noise or slow down the
live measurement pass, or both). Do this once it's safe to run a dedicated benchmark
without interfering with a live corpus pipeline pass -- try `per_symbol_bootstrap_threads`
values that keep `n_workers x threads` in the neighborhood of the host's 24 cores (e.g.
2, matching `infra.ic_engine.workers=8 x 2 = 16`, leaving headroom) rather than
naively deploying the isolated-worker-optimal value of 8.

## Sizing

Threading mechanism: small, already landed (config wiring only, the actual thread pool
code pre-existed). Remaining work is a benchmark, not new code.
