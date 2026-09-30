---
status: pending
priority: P2
filed: 2026-09-30
source: plan 186-15 review (altitude, reuse); tie to streaming revival and 186-25
---

# The live CTF path differs from the batch path, and the live kernel run recomputes the window per bar

## What

`services/feature_vector_pipeline.py` (`_update_ctf_cache_from_htf_bar`, about lines 1697-1735) sets
only `cache.ctf_momentum` on each LTF cache. `ctf_vwap_align` and `ctf_regime_align` stay at the
`FeatureCache` default 0.0 and `ext_htf_last_log_ret` is NaN on the live path, so `ret_div_5m_1h`
and `ret_div_1h_1d` are never produced live. The value the live path reads is the newest buffered
HTF bar, and which bar that is depends on the order `PerKeyWorkerManager` runs the (symbol, tf)
tasks, so two runs over the same ticks can store different `ctf_momentum`. The batch path reads the
HTF bar closed by the row start (`CtfSeries.asof`), so live and batch disagree on three columns and
on the rule.

A second cost on the same path: `_precompute_series` runs all 92 series kernels over the whole
buffered window on every live bar (about 73 ms at a 600-bar window, measured 2026-09-30; not a
regression from 186-15, the loop did the same work before). It is the live-path latency lever.

## Options

1. Leave it: the streaming path is dormant (IBKR live feed down, todo 395), nothing is written.
2. Patch the live path: set all three CTF fields from a per-HTF-bar update and add the HTF return.
   Keeps the FeatureCache replay (`_get_cache`, `update_*` mutators) and its task-order dependence.
3. Run `compute_kernels` over the buffered tail with the same alignment builders the batch path
   uses (`ctf_series_by_close`, `ctf_row_inputs`, `daily_asof_indices`), and delete the FeatureCache
   replay. One rule, one code path; the window length is the declared memory of the requested
   kernels, which also bounds the per-bar cost.

## Recommendation

Option 3, done with the streaming revival and 186-25 (which already moves the cache-backed kernels
off `FeatureCache`). Until then the path stays dormant and must not be revived as is. For the
latency: request only the kernels whose outputs the consumer reads, slice the window to the
maximum declared memory plus the path-dependent series start, and measure against the 73 ms
baseline; vectorizing the rolling std in `_build_ctf_series` is not bit-identical (measured), so it
is not part of this.

## Steps

1. Write a live-versus-batch parity test on a synthetic tick stream (same rows, same CTF columns).
2. Build the live tail call on `compute_kernels` with the batch alignment builders.
3. Delete `_get_cache`, the `update_*` replay and `_update_ctf_cache_from_htf_bar`.
4. Record the per-bar latency before and after.
