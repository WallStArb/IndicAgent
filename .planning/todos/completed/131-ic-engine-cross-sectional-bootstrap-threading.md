---
status: completed
priority: P1
filed: 2026-07-17
closed: 2026-07-17
source: user asked whether the corpus rebuild's compute time (post todo-128 fix, still
  multi-day) could be reduced — a 3-day compute isn't sustainable for a recurring rebuild
---

# `_circular_block_bootstrap_ic`'s serial bootstrap loop was the actual multi-hour bottleneck — threaded the compute step

## Finding

After todo 128 fixed the corpus re-run's connection-drop crash, the underlying compute cost was
still the real problem: one (regime_group, tf, regime_label) cross-sectional cell at production
scale (n~361674 rows, p=154 features) took ~8h53m end to end, almost entirely inside
`_circular_block_bootstrap_ic`'s 2000-iteration bootstrap loop
(`src/intelligence/statistics/ic_math.py`). Direct benchmarking on the production host isolated
the cost: `scipy.stats.rankdata` on a (361674, 154) array is ~8s/call, called twice per
iteration (X matrix + Y vector), 2000 times, fully serial.

Each iteration's compute (re-rank the resampled block, then `_vectorized_ic`) is independent of
every other iteration once its block indices are drawn — only the RNG draw itself has to stay
strictly serial and in-order for determinism/reproducibility. That's a clean seam for thread
parallelism: `numpy`/`scipy`'s sort releases the GIL enough for real wall-clock speedup via
`ThreadPoolExecutor` (no `ProcessPoolExecutor` needed, so no per-worker array-copy cost — threads
share the read-only `X_raw`/`Y_raw` arrays directly).

An initial pass considered swapping `scipy.stats.rankdata` for a hand-rolled argsort-based rank
function, hypothesizing scipy's dispatch/tie-handling overhead was the cost. Benchmarked and
disproved: argsort itself is the dominant O(n log n) cost regardless of implementation (~12%
faster only). Threading was the real lever.

A second miss, caught by code review before this shipped: the first pass seeded
`infra.ic_engine.cross_sectional_bootstrap_threads = 12` without measuring memory, only wall
time. Direct `resource.getrusage(RUSAGE_SELF).ru_maxrss` measurement at the real cell shape
showed 12 threads peaks at ~23GB RSS — on a host with ~22GB free with nothing else running, i.e.
~0 safety margin against the other live daemons (`feature_vector_pipeline`, `ctx-writer`,
`lineage-writer`, TimescaleDB, Redpanda) that actually run concurrently with this pass. Each
concurrent thread holds its own full re-ranked `(n, p)` working set — a real per-thread memory
cost the wall-clock-only benchmark never surfaced.

## Fix

`_circular_block_bootstrap_ic` gained a `max_workers: int = 1` parameter (default preserves the
exact pre-threading serial code path, bit-for-bit). When `max_workers > 1`: draws block indices
serially in `max_workers`-sized batches (the only order-dependent step), then dispatches the
independent re-rank+IC compute for that batch to a `ThreadPoolExecutor`, writing results back via
`boot_ics[b:batch_end] = list(pool.map(...))` (`Executor.map` is submission-order-preserving per
stdlib guarantee — verified, not assumed). Batching (not one `executor.map` over all 2000
indices) bounds peak memory to `max_workers` index arrays at a time, not 2000 of them.

Wired via `ICEngineConfig.cross_sectional_bootstrap_threads` (new field, APR key
`infra.ic_engine.cross_sectional_bootstrap_threads`, migration 239) into the **cross-sectional
call site only** (`_compute_cross_sectional_tf`) — the two per-symbol call sites
(`_compute_symbol_tf`) now pass `max_workers=1` *explicitly* (not just via the parameter default)
with a comment explaining why: they already run inside `main()`'s
`ProcessPoolExecutor(max_workers=n_workers)` pool, so threading on top would oversubscribe cores,
not speed anything up. Cross-sectional is safe because it runs single-process, strictly after
that pool has already shut down — confirmed via trace, no concurrent invocation exists.

Seeded value corrected during code review from an unmeasured 12 to a directly-measured 6
(`config_schema.max_value` also tightened from 24 to 8 — a deliberate, measurement-backed
ceiling, not a placeholder). Real production-scale measurements:

| max_workers | wall time (n_boot=2000, extrapolated) | peak RSS |
|---|---|---|
| 1 (serial baseline) | ~3.72h | 3.3 GB |
| 4 | ~1.22h | 11.5 GB |
| **6 (seeded)** | **~0.99h** | **13.6 GB** |
| 12 (original guess, rejected) | ~0.68h | ~23 GB — unsafe |

6 threads gets the worst-case cell from ~8h53m to under an hour with a real ~8GB memory margin,
instead of shipping a config with ~0 margin that would likely OOM in production the first time
it ran alongside the other live daemons.

TDD: `tests/unit/test_bootstrap_ic.py` — `test_threaded_matches_serial_bit_for_bit` (max_workers=8
vs max_workers=1, same seed, bit-identical output) and `test_threaded_determinism_same_seed_identical_bounds`
(two threaded calls, same seed, identical bounds) both watched RED (missing `max_workers` kwarg)
before implementing. `test_circular_wrap_handles_boundary_without_raising_threaded` extends the
existing heavy-wraparound boundary test through the threaded path too. Full `tests/unit/` suite
green.

Full multi-agent `/simplify` + `/code-review` (8 finder angles: line-by-line, removed-behavior,
cross-file, reuse, simplification, efficiency, altitude, conventions) run before commit — the
memory-safety finding above came from the removed-behavior angle, then independently confirmed
by direct measurement rather than taken on the finder's estimate alone.

## Not yet done

- A 4th call site (`scripts/ops/alpha/ops_ic_null_calibration.py`) also calls
  `_circular_block_bootstrap_ic` and stays serial (no CLI flag to set `max_workers`) — low
  priority, it's a manually-invoked diagnostic script, not corpus-critical.
- The corpus re-run needs relaunching from step 5 with this fix in place (killed the in-flight
  run from todo 128 ~12 minutes in, negligible loss, to land this fix first rather than let a
  ~3-day run finish on code already known to be far slower than necessary).
