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
- a path-dependent kernel has no finite memory: it runs through the whole series and only the
  dropped bar's row is masked (a restart at a seam erred up to 4.2 sigma-units, a run-through 0.07);
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

## Fixed 2026-10-29

`bar_statistics_refresh` no longer declares `volume` (it reads only high, low and close), so the guard
leaves `hurst`, `shannon`, `garch_ratio`, `hma_slope_z` and `adx` alone. A perturbation scan of the other
guarded kernels found every one but `session_levels` changes with volume.

## Open

- `session_levels` also declares `volume` without using it in any output (the shared `_replay_cache`
  feeds it to `advance_bar`, which only feeds the weekly VWAP the kernel does not read). The guard
  masks it on NULL-volume 1d bars; left as is, since `session_levels` does not classify on 1d.
  Splitting the helper would touch a fingerprinted module for no change in output.
- Independent review of the guard commits (`d6a8da8de`, `96458db71`), 2026-10-29. Arithmetic of the
  masks is correct. Fixed: a none-mask column was NaN at each segment's row 0 (now 1); the invariant
  test passed vacuously for `rolling_poc` (now asserts a finite comparison, `rolling_poc` listed as
  too long for the fixture). Fixed after measuring: a path-dependent kernel
  (`vwap_dev_sigma`, `ctf_source`, `calendar_above_wk_vwap`, `session_vp`, `session_levels`) used to
  restart at a seam, which erred by up to 4.2 sigma-units on `vwap_dev_sigma` (one flip bar at row 251
  of the test series). These kernels weight by volume rather than read its level, so running through
  with the later volume scaled to 0.75 errs by at most 0.066. The guard now runs them through the
  seam and masks only the dropped bar's row. Needs a second independent review before 186-26.
- Research panel provenance (phase 184): until then the promoted `rk_vwap_dev` kernels refuse
  without a caller-supplied `volume_basis`.
- The 186-26 launch has no owner.
