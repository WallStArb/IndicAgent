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

## Open

- Full-pipeline check through `compute_batch` on a real name with injected NULL volume for the
  path-dependent guarded kernels the property test skips: `vwap_dev_sigma`, `session_vp`,
  `session_levels`, `calendar_above_wk_vwap`, `ctf_source`, `bar_statistics_refresh`.
- Independent review of the guard commits (`d6a8da8de`, `96458db71`).
- Research panel provenance (phase 184): until then the promoted `rk_vwap_dev` kernels refuse
  without a caller-supplied `volume_basis`.
- The 186-26 launch has no owner.
