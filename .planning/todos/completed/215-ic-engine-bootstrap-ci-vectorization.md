---
status: completed
priority: P1
filed: 2026-07-30
completed: 2026-07-30
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

## Multi-worker contention benchmark -- DONE 2026-07-30 evening, against the live pass (not a dedicated one)

This section originally recommended NOT benchmarking against the in-flight corpus pass.
That's what happened anyway, for a practical reason: `per_symbol_bootstrap_threads` was
bumped to 2 live via `ConfigService.set()`, which required killing/restarting `ic_engine`
to pick up the new value -- and the restart independently forced a full 80-symbol
recompute for an unrelated reason (the restart also reloaded this todo's own just-landed
code change from disk, invalidating every fingerprint via `code_content_key` regardless
of the APR field's OPERATIONAL classification -- see
`feedback_restart_batch_job_check_code_diff_first`). Given a full recompute was already
happening, measuring the real threads=2 throughput on it was free additional signal
rather than a separate cost, so it was taken.

**Real measured speedup, two symbols, apples-to-apples (identical `n_rows`/`n_skipped`
confirms output stayed bit-identical across the thread-count change):**
- BTAL: 2974s (49m34s) -> 2319s (38m39s) = **1.28x**
- CWB (heavier cell): 8507s (2h21m47s) -> 6326s (1h45m26s) = **1.35x**

Consistent ~1.3x across a light and a heavy symbol -- real, not noise, but well below
the 2.4x isolated-single-worker benchmark. Confirms the contention risk this section
originally flagged: 12 physical cores, 8 `ProcessPoolExecutor` workers already claiming
8 of them, only 4 idle physical cores to absorb the doubling. threads=2 sits close to
the safe ceiling given that headroom -- threads=4/8 would need 32/64 logical threads
against a 24-thread box and would almost certainly regress further via oversubscription,
not improve. **Decision: keep threads=2 as the standing value for all 4 tfs** (~1.3x on
the pipeline's single longest step is a real, safe win; not worth the restart risk of
testing higher values without a dedicated idle-box benchmark first).

## Sizing

Threading mechanism: small, already landed (config wiring only, the actual thread pool
code pre-existed). Contention benchmark: done, real data in hand, decision made.
