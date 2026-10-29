---
status: pending
priority: P1
filed: 2026-10-29
source: Opus review of the todo 560 volume guard
---

# Regime walk-forward kernels fail a whole 1d series on a mid-series NULL-volume bar

`hmm_trend_walk_forward` is `nan_volume_safe` and reads `volume` (`needs_volume`). Its
`_finite_prefix_rows` (`kernels/regime.py`) raises `ValueError` when a non-finite value is followed
by finite rows, deliberately (a NaN volume is never silent). `compute_kernels` runs the regime
kernels in the same call as every other kernel, so one mid-series NULL-volume bar fails the whole
series in `backfill_feature_factory` (logged as a failed series, no rows written).

145 names have mid-series NULL volume on 1d (IBKR `ibkr/fallback` and `venue` rows, all followed by
non-NULL bars). The raise predates todo 560 and is correct for a silent-wrong-answer standard, but
those 145 names then get no regime and no features from the 186-26 rebuild.

## Options

- Plan 191-20's Alpaca 1d re-derive (todo 545, D-191-Q) may remove the NULLs; recount after it lands
  before building anything.
- Else treat a NaN-volume row as a missing observation in the trend family: the walk-forward state
  carries over and that row's outputs are unlabeled, which needs the HMM's own review (todo 248).

Decide before 186-26 launches, since the regime kernels are in its fingerprinted closure.
