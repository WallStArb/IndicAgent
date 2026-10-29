---
status: pending
priority: P1
filed: 2026-10-28
source: scope guard of the todo 555 change (amihud volume_basis); sequencing call belongs to indicagent-3a
---

# Volume-reading kernels other than amihud_illiq_z span the volume basis seam

## What

Todo 555 added the `volume_basis` bar field (one integer per bar, derived from the canonical
(vendor, kind) through `bars/vendor_kind.py`) and made `amihud_illiq_z` restart its window at a
basis change. Every other kernel that reads `volume` still runs its rolling window straight
across the seam: IBKR SMART volume (basis `smart`) is about 0.41 to 0.91 of consolidated on 1d
and 0.38 to 0.95 on 5m, so a window that holds both bases carries a level shift as signal. The
seam is per name and per timeframe, wherever the selected rows' basis changes (53 names have IBKR
rows inside the Alpaca era), never a date. Bars with no volume (basis `none`, NULL volume) are
NaN and never start or end a segment.

## Kernels that read `volume` (from the registry, 2026-10-28)

Rolling statistics of volume or volume-weighted price, the same defect as amihud:
`volume_z`, `rel_volume`, `dollar_vol_z`, `vol_acceleration`, `vol_range_ratio`,
`vol_trend_ratio`, `vol_percentile`, `vol_persistence`, `vol_std_z`, `ofi_z`, `cvd_slope_z`,
`up_vol_ratio` (fast, slow), `mfi` (fast, slow), `price_vol_corr` (fast, slow), `cmf`.

Cumulative or path-dependent, where the seam cannot be handled by a window restart and needs a
design call (restart the accumulator at a basis change and record it, or rescale):
`obv_z`, `vwap_dev_sigma`, `rolling_poc`, `session_vp`, `calendar_above_wk_vwap`,
`ctf_source` (the VWAP-align source).

Volume enters as a confirmation or weight, so the effect is second order but still present:
`order_blocks`, `support_resistance`, `swing_momentum`, `bar_statistics_refresh`,
`hmm_trend_walk_forward`.

## Fix

Each adopts the 555 pattern: take `volume_basis` as an input, restart the window at a change
(`_volume_basis_segment_starts` in `kernels/volume.py`), NaN until warm, NaN volume handled by a
nan-aware statistic with a minimum valid fraction (APR key per kernel or a shared one).
Definition changes, so each moves its parity goldens with the reason recorded.

## Sequencing

`kernels/` is in the 186-26 fingerprinted import closure, so the same window applies as 553 and
555: land before the launch or pay a follow-up rebuild of these columns. indicagent-3a makes the
sequencing call. The rebuild loaders already carry `volume_basis` and NULL volume as NaN (555),
so these kernels need no loader change.

## Resolution (indicagent-24, 2026-10-28; in review)

One guard in `compute_kernels` (`_compute_basis_guarded`, `features/contract/registry.py`) covers
every kernel that reads `volume` and is not marked `nan_volume_safe` (25 kernels: the 17 listed
above plus the VP/SR, swing, session-level, CTF and statistics kernels). `amihud_illiq_z` and the
HMM kernels handle it themselves. The guard:

- runs the kernel on each volume-basis segment alone, so no window spans a basis change;
- feeds NaN volume (a NULL-volume bar) as 0.0, finite, so a cumulative sum or rolling std is not
  poisoned (one NaN used to turn `volume_z`, `ofi_z`, `cvd_slope_z`, `dollar_vol_z`,
  `vol_range_ratio`, `vol_std_z` and `obv_z` into 0.0 on every later row);
- masks the output NaN (a none-mask row 1) for any row whose trailing `memory + 1` bars hold a
  dropped bar or a segment start, so the declared memory still holds and the gap is loud; a
  path-dependent kernel has no finite memory, so only the dropped bar's own row is masked and
  its accumulation restarts at a segment;
- requires the `volume_basis` bar field from the caller.

Measured on the synthetic fixture with one NaN bar: every output is NaN only inside its declared
memory and equals the clean run after it (cumulative-sum kernels to 1e-11 relative). No change
where there is no NULL volume and no basis change, so the parity goldens are unchanged.
A window counts calendar bars; a missing session blanks `memory + 1` rows of each affected
kernel, unlike amihud's minimum-valid-fraction rule. Per-kernel nan-aware rewrites are a possible
refinement, not a blocker.

Research: `kernel_source` still needs the caller to supply `volume_basis`, so the promoted
`rk_vwap_dev` kernels refuse without it until the panel carries vendor provenance (a 184
follow-up).

## Still open (2026-10-29)

- Full-pipeline check through `compute_batch` on a real name with injected NULL volume, for the
  path-dependent guarded kernels the property test skips (`vwap_dev_sigma`, `session_vp`,
  `session_levels`, `calendar_above_wk_vwap`, `ctf_source`, `bar_statistics_refresh`).
- Independent review of the guard commits (`d6a8da8de`, `96458db71`); 555 had one, 560 did not.
- Research panel provenance (phase 184) so `rk_vwap_dev` accepts a real basis.
