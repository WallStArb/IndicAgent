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
