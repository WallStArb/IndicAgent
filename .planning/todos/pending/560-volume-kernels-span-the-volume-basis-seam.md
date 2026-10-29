---
status: pending
priority: P1
filed: 2026-10-28
source: scope guard of the todo 555 change
---

# Volume-reading kernels: basis seam and NULL volume (open checks before 186-26)

IBKR SMART volume is about 0.75 of consolidated (p5 0.61, p95 0.95), so a rolling window that
holds both bases carries a level shift. A NULL-volume bar (the tradeable view NULLs volume for the
ibkr `venue` and `fallback` kinds) is NaN since todo 555, and one NaN turned `volume_z`, `ofi_z`,
`cvd_slope_z`, `dollar_vol_z`, `vol_range_ratio`, `vol_std_z` and `obv_z` into 0.0 on every later
row. Both affect the 25 volume-reading kernels other than `amihud_illiq_z` and the HMM kernels
(which handle them themselves). `kernels/` is in the 186-26 fingerprinted import closure, so this
closes before the launch.

## What holds

`compute_kernels` runs every kernel that reads `volume` and is not `nan_volume_safe` through
`_compute_basis_guarded` (`features/contract/registry.py`):

- each volume-basis segment runs alone;
- NaN volume enters as 0.0;
- an output row is NaN (a none-mask row is 1) when its trailing `memory + 1` bars hold a dropped
  bar or span a segment boundary, so the declared memory holds and the gap is loud;
- a path-dependent kernel has no finite memory: only the dropped bar's row is masked and its
  accumulation restarts at a segment;
- the caller must supply `volume_basis`.

`tests/unit/intelligence/test_basis_guard_invariant.py` proves, for every non-path-dependent
guarded kernel over random gaps and seams, that a clean-window row equals the kernel run on its
trailing `memory + 1` bars and a dirty-window row is masked. Without NULL volume or a basis change
the guard is a no-op, so the parity goldens are unchanged. A missing session blanks `memory + 1`
rows of each affected kernel, where amihud's valid-fraction rule blanks fewer.

## Checked

Path-dependent guarded kernels, 37 outputs, synthetic series with 8 random NULL-volume bars
(2026-10-29): every row before the first NULL is bit-identical to the clean run, every NULL bar's
own row is masked, and the largest deviation after it is `vwap_dev_sigma` at a median 0.2%.

Masked share on real names (2026-10-29, 1d, 23 of the 308 names with NULL-volume bars, 12 heavy
at 553 or more, 11 light; synthetic 5m config for the memories): NULL volume exists only on 1d
`ibkr/fallback` rows (125,174 of 7.08M, 1.8%). A guarded output loses about its name's NULL share
plus a little for memory: 36% of rows on heavy names, 6 to 13% on light ones, `support_strength`
and the `sr_*` and `ob_*` outputs highest at 37.5% heavy. The `rolling_poc` outputs are NaN on 1d
with clean volume too (they need intraday sessions) and 5m has no NULL volume, so the 480-row
blanking does not bite on current data and the nan-aware rewrite is not needed.

## Open

- Fix `bar_statistics_refresh` (`kernels/price.py`): it declares `volume` as an input but reads only
  high, low and close, so the guard masks `hurst`, `shannon`, `garch_ratio`, `hma_slope_z` and `adx`
  on every NULL-volume bar for nothing. Drop `volume` from its inputs (and check what else lists
  `volume` without reading it) before 186-26; it changes a kernel in the fingerprinted closure.
- Independent review of the guard commits (`d6a8da8de`, `96458db71`).
- Research panel provenance (phase 184): until then the promoted `rk_vwap_dev` kernels refuse
  without a caller-supplied `volume_basis`.
- The 186-26 launch has no owner.
