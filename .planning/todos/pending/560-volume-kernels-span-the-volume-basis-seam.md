---
status: pending
priority: P1
filed: 2026-10-28
source: scope guard of the todo 555 change
---

# Volume-reading kernels: basis seam and NULL volume (open checks before 186-26)

## Status (2026-10-31)

Guard design landed and independently reviewed (`d6a8da8de`, `96458db71`, review 2026-10-29:
mask arithmetic correct; two review fixes landed - none-mask column NaN at each segment's row 0,
and the invariant test for `rolling_poc` no longer vacuous). Remaining: the 186-26 launch has no
owner, and the research-panel provenance point below. The review also found and fixed the
seam-restart bug (next section).

## What holds

IBKR SMART volume is about 0.75 of consolidated (p5 0.61, p95 0.95), so a rolling window that
holds both bases carries a level shift; and a NULL-volume bar (the tradeable view NULLs volume
for ibkr `venue` and `fallback` kinds) is NaN since todo 555 - one NaN used to turn `volume_z`,
`ofi_z`, `cvd_slope_z`, `dollar_vol_z`, `vol_range_ratio`, `vol_std_z` and `obv_z` into 0.0 on
every later row. `compute_kernels` therefore runs every kernel that reads `volume` and is not
`nan_volume_safe` through `_compute_basis_guarded` (`features/contract/registry.py`): each
volume-basis segment runs alone; an output row is NaN when its trailing `memory + 1` bars hold a
dropped bar or span a segment boundary; the caller must supply `volume_basis`.

- Path-dependent kernels have no finite memory: they run through the whole series and only the
  affected rows are masked. Restarting one at a seam erred up to 4.2 sigma-units on
  `vwap_dev_sigma`; running through errs 0.07. These kernels weight by volume rather than read
  its level (per-kernel confirmed in review), so a 0.75 scaling errs at most 0.055 sigma and
  flips about 1% of `ctf_source` vwap-align signs. A dropped bar entered as 0.0 is a fill whose
  effect outlives its row: kernels with a reset anchor (`Kernel.volume_reset`:
  `calendar_above_wk_vwap` week, `session_vp` ET session) are masked from the dropped bar to the
  next reset; `vwap_dev_sigma` and `ctf_source` never reset and are masked while dropped bars
  exceed the APR share (5%, [initial_estimate], `feature.volume.dropped_max_fraction`,
  migration 541; leading NULLs before the first volume bar do not count, though their rows are
  NaN). A 4.8% drop moves `vwap_dev_sigma` 0.025 sigma; at or under 5% the error stays below
  about 0.1 sigma. Real 1d heavy names (SPGI, SCCO, HON: about 2,600 NULL bars each) are masked
  for most of the series, loudly; plan 191-20's Alpaca 1d re-derive (todo 545) may remove those
  NULLs. The weekly flag also masks the first row of the next week.
- Downstream readers are guarded transitively (`_guard_downstream`: `volume_z_velocity`,
  `ofi_z_velocity`, `cvd_slope_z_velocity`, `vwap_dev_sigma_velocity`, `vol_spike_events`,
  `bars_since_vol_spike_*`, `flow_products`); before this, a dropped bar zeroed the four
  velocity features to the end of the series and read as "no spike". `vol_spike_events` now
  emits float 1.0/0.0 with NaN where `rel_volume` is NaN.
- `bar_statistics_refresh` no longer declares `volume` (2026-10-29; it reads only high, low,
  close), so the guard leaves `hurst`, `shannon`, `garch_ratio`, `hma_slope_z` and `adx` alone;
  a perturbation scan confirmed every other guarded kernel but `session_levels` changes with
  volume. `session_levels` never reads volume and is now `nan_volume_safe`.

Tests: `tests/unit/intelligence/test_basis_guard_invariant.py` (every non-path-dependent
guarded kernel, random gaps and seams: clean-window row equals the kernel on its trailing
`memory + 1` bars, dirty-window row masked) and `test_basis_guard_end_to_end.py` (whole intraday
registry with one dropped bar fails on any unmasked difference). Without NULL volume or a basis
change the guard is a no-op, so parity goldens are unchanged. A missing session blanks
`memory + 1` rows of each affected kernel, where amihud's valid-fraction rule blanks fewer.

## Measured exposure (2026-10-29)

NULL volume exists only on 1d `ibkr/fallback` rows (125,174 of 7.08M, 1.8%; 23 of the 308 names
with NULL-volume bars, 12 heavy at 553 or more). A guarded output loses about the name's NULL
share plus memory: 36% of rows on heavy names, 6-13% on light ones, `support_strength` and the
`sr_*`/`ob_*` outputs highest at 37.5% heavy. `rolling_poc` outputs are NaN on 1d with clean
volume too (they need intraday sessions) and 5m has no NULL volume, so the 480-row blanking does
not bite on current data and the nan-aware rewrite is not needed. Path-dependent kernels with 8
random NULL bars: every row before the first NULL bit-identical to the clean run, each NULL
bar's own row masked, largest deviation after it `vwap_dev_sigma` at median 0.2%.

## Open

- `session_levels` declares `volume` without using it in any output (the shared `_replay_cache`
  feeds it to `advance_bar`, which only feeds the weekly VWAP the kernel does not read); the
  guard masks it on NULL-volume 1d bars. Left as is: it does not classify on 1d, and splitting
  the helper would touch a fingerprinted module for no output change.
- Research panel provenance (phase 184): until then the promoted `rk_vwap_dev` kernels refuse
  without a caller-supplied `volume_basis`.
- The 186-26 launch has no owner.
- `illiquidity_momentum_product` left `flow_products` for its own kernel, so its effective warmup
  fell from 300 to 35 bars (correct: it reads only `amihud_illiq_z` and `momentum_z_fast`); on
  the rebuild, rows between `first_row` and the old flow-products memory hold values instead of
  NULL. Live and legacy paths that still feed NaN volume to the cache (`feature_vector_pipeline`
  into `update_wk_vwap`, legacy `feature_factory` helpers, `ops_ctf_columns_recompute_15m`) are
  off the 186-26 rebuild path and stay as they are.
